"""Standalone, pinned Linux bootstrap, streamed to python3 over SSH stdin.

Only this file runs on the server. stdout is a JSON-lines protocol; package
manager output goes to the dedicated runtime's setup.log. No SSH key is sent.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
import uuid

ROOT = Path('/workspace/book-studio-drama3')
COMFY_SHA = '355cd6b14c92c19ac3188fe528e47a3f21ef5178'
NODES_SHA = '67a733a96890637dc27b1914974ad00c569405fb'
REVISION = '681e2fae64af1f12e64b9c19c82930a5f3bba1a4'
ASR_REVISION = '6ad8c9be026925839479a8d97749068a4202fbe9'
MODEL = 'drama3_fp8experts_bf16.safetensors'
CODEC = 'drama3_codec.safetensors'
ASR = 'qwen3_asr_0.6b_bf16.safetensors'
WEIGHTS = [
    ('diffusion_models', MODEL, 'PedroMarinhoDev/Drama-3-ComfyUI', REVISION, 38578417928,
     '5d053a200cf0f77faa13c087c78ef200c3b53f288451a6b9e7a8fa421c03a67b'),
    ('vae', CODEC, 'PedroMarinhoDev/Drama-3-ComfyUI', REVISION, 1565647484,
     '4fecf102907a48414230da9a74d72d07c3a92368eab53fab655797837bddf5ae'),
    ('asr', ASR, 'PedroMarinhoDev/Qwen3-ASR-ComfyUI', ASR_REVISION, 1564928184,
     'eb350ce7510a538eb136d8320db470a0761713c47de6e12b0fca090d4fc15ecf'),
]
MUSIC_REVISION = '75aad8836271cb5a5123fb58304fae5d3bb4b0f9'
MUSIC_MODEL = 'stable_audio_3_medium.safetensors'
MUSIC_ENCODER = 't5gemma_b_b_ul2.safetensors'
MUSIC_WEIGHTS = [
    ('checkpoints', MUSIC_MODEL, 'Comfy-Org/stable-audio-3', MUSIC_REVISION, 9222116660,
     '48d9c65e290e7bcd5194e0633bfc2424a59ee9683f5c2d58762d997b7d8ce0b5'),
    ('text_encoders', MUSIC_ENCODER, 'Comfy-Org/stable-audio-3', MUSIC_REVISION, 1187264003,
     '1e1eba25be8872edb0d3c6335c6658fd6388e7b14b60da6e454e404cfcd8150e'),
]
REQUIRED = ('Drama3Loader', 'Drama3CodecLoader', 'Drama3EncodeVoice', 'Drama3Generate',
            'Drama3Decode', 'Qwen3ASRLoader', 'Qwen3ASRTranscribe', 'SaveAudio', 'LoadAudio')
MUSIC_REQUIRED = ('CheckpointLoaderSimple', 'CLIPLoader', 'CLIPTextEncode',
                  'EmptyLatentAudio', 'KSampler', 'VAEDecodeAudio', 'SaveAudio')
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def emit(kind='progress', **fields):
    print(json.dumps(dict(book_studio=1, type=kind, **fields), ensure_ascii=False), flush=True)


def report(message, value=None, **fields):
    emit(message=message, value=value, indeterminate=value is None, **fields)


def api(port, route):
    with HTTP.open(f'http://127.0.0.1:{port}{route}', timeout=15) as response:
        return json.load(response)


def port_listening(port):
    """Only a refused connection proves absence; timeouts/permission errors do not."""
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except ConnectionRefusedError:
        return False
    except OSError:
        return None


def choices(info, node, key):
    definition = info[node]['input']['required'][key]
    return definition[1].get('options', []) if definition[0] == 'COMBO' else definition[0]


def comfy_processes():
    """Include processes still importing nodes, before their HTTP listener opens."""
    try:
        processes = list(Path('/proc').iterdir())
    except OSError:
        return
    for process in processes:
        if not process.name.isdigit():
            continue
        with contextlib.suppress(OSError):
            arguments = (process/'cmdline').read_bytes().decode(errors='replace').split('\0')
            if not any(Path(argument).name == 'main.py' for argument in arguments):
                continue
            comfy = (process/'cwd').resolve(strict=True)
            if (comfy/'main.py').is_file() and (comfy/'folder_paths.py').is_file():
                yield process, comfy, arguments


def starting_comfy(port):
    for _, _, arguments in comfy_processes():
        process_port = 8188  # ComfyUI's default without --port.
        for index, argument in enumerate(arguments):
            if argument == '--port' and index + 1 < len(arguments):
                process_port = arguments[index + 1]
            elif argument.startswith('--port='):
                process_port = argument.partition('=')[2]
        if str(process_port) == str(port):
            return True
    return False


def inspect_port(port, music=False):
    """A listening but slow service must never trigger a second installation."""
    if port_listening(port) is False:
        if starting_comfy(port):
            return dict(ready=False, status='busy', port=port, message=f'ComfyUI на порту {port} '
                        'ещё запускается. Дождитесь запуска и повторите подключение.')
        return dict(ready=False, status='absent', port=port)
    result = dict(ready=False, port=port, reused=True)
    try:
        version = api(port, '/system_stats')['system']['comfyui_version']
        info = api(port, '/object_info')
    except OSError:
        return dict(result, status='busy', message=f'ComfyUI на порту {port} не отвечает. '
                    'Возможно, сервер занят генерацией. Дождитесь её завершения и повторите подключение.')
    except (ValueError, KeyError, TypeError):
        return dict(result, status='incompatible', message=f'Сервис на порту {port} не является совместимым ComfyUI.')
    try:
        if tuple(int(x) for x in version.split('.')[:3]) < (0, 42, 0):
            raise ValueError('Нужен ComfyUI 0.42.0 или новее.')
        if any(name not in info for name in REQUIRED):
            raise ValueError('В запущенном ComfyUI отсутствуют узлы Drama 3 / Qwen3 ASR.')
        for node, key, filename in [('Drama3Loader', 'model_name', MODEL),
                                    ('Drama3CodecLoader', 'codec_name', CODEC),
                                    ('Qwen3ASRLoader', 'model_name', ASR)]:
            if filename not in choices(info, node, key):
                raise ValueError('В запущенном ComfyUI отсутствует модель ' + filename + '.')
        if music:
            if any(name not in info for name in MUSIC_REQUIRED):
                raise ValueError('В запущенном ComfyUI отсутствуют встроенные узлы Stable Audio 3.')
            if 'stable_audio' not in choices(info, 'CLIPLoader', 'type'):
                raise ValueError('В запущенном ComfyUI нет текстового кодировщика Stable Audio.')
            if (MUSIC_MODEL not in choices(info, 'CheckpointLoaderSimple', 'ckpt_name') or
                    MUSIC_ENCODER not in choices(info, 'CLIPLoader', 'clip_name')):
                return dict(result, status='music_missing', drama_ready=True, music_ready=False,
                            message='Stable Audio 3 Medium ещё не установлена. '
                            'Нажмите «Установить / обновить окружение» с включённой музыкой.')
        return dict(result, ready=True, status='ready', music_ready=bool(music))
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        return dict(result, status='incompatible', message=f'ComfyUI на порту {port}: {exc} '
                    'Используется уже запущенный сервер; автоматическая установка второго окружения отключена.')


def compatible(port, music=False):
    """Require scoped cancellation and the precise graph/model input contract."""
    return inspect_port(port, music)['ready']


def probe(music=False):
    results = []
    for port in (8187, 8188):
        result = inspect_port(port, music)
        if result['ready']:
            return result
        results.append(result)
    # Prefer augmenting a known Drama runtime over considering a second port.
    for status in ('music_missing', 'busy', 'incompatible'):
        for result in results:
            if result['status'] == status:
                return result
    return dict(ready=False, status='absent')


def running_comfy_directory(port):
    """Resolve the actual listening Comfy process, never guess another model folder."""
    inodes = set()
    for table in ('/proc/net/tcp', '/proc/net/tcp6'):
        with contextlib.suppress(OSError, ValueError, IndexError):
            for line in Path(table).read_text().splitlines()[1:]:
                fields = line.split()
                if fields[3] == '0A' and int(fields[1].rsplit(':', 1)[1], 16) == port:
                    inodes.add('socket:[' + fields[9] + ']')
    paths = set()
    for process, comfy, _ in comfy_processes():
        with contextlib.suppress(OSError):
            for fd in (process/'fd').iterdir():
                # An unrelated fd may close between readdir and readlink.
                with contextlib.suppress(OSError):
                    if os.readlink(fd) in inodes:
                        paths.add(comfy)
                        break
    if len(paths) != 1:
        raise RuntimeError('Не удалось определить каталог запущенного ComfyUI. '
                           'Музыкальная модель не скачана: второй каталог окружения не создавался.')
    return paths.pop()


def missing_bytes(comfy, weights):
    total = 0
    for kind, name, _, _, size, _ in weights:
        target = comfy/'models'/kind/name
        if target.is_file() and target.stat().st_size == size:
            continue
        partial = target.with_suffix(target.suffix + '.part')
        offset = partial.stat().st_size if partial.is_file() else 0
        total += size - offset if 0 <= offset <= size else size
    return total


class Installer:
    def __init__(self, job):
        if not re.fullmatch('[a-f0-9]{32}', job):
            raise ValueError('Некорректный идентификатор установки.')
        self.job = job
        ROOT.mkdir(parents=True, exist_ok=True)
        self.cancel_path = ROOT / ('cancel-' + job)

    def check(self):
        if self.cancel_path.exists():
            raise InterruptedError('Установка отменена. Скачивание можно продолжить.')

    def command(self, args, message, timeout=2400):
        self.check()
        report(message)
        with (ROOT / 'setup.log').open('ab', buffering=0) as log:
            process = subprocess.Popen(list(map(str, args)), stdout=log, stderr=log,
                                       stdin=subprocess.DEVNULL, start_new_session=True)
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    self.check()
                    if time.monotonic() > deadline:
                        raise TimeoutError(message + ': превышено время ожидания.')
                    time.sleep(.2)
                if process.returncode:
                    with (ROOT / 'setup.log').open('rb') as source:
                        source.seek(max(0, source.seek(0, 2) - 3000))
                        detail = source.read().decode('utf-8', errors='replace')
                    raise RuntimeError(message + '\n' + detail)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()

    def download(self, url, target, size, digest):
        """Resume verified-size partials; never append a full 200 response."""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        stamp = target.with_suffix(target.suffix + '.verified.json')
        if target.is_file() and stamp.is_file():
            try:
                cached = json.loads(stamp.read_text())
                stat = target.stat()
                if cached == dict(sha256=digest, size=size, mtime_ns=stat.st_mtime_ns) and stat.st_size == size:
                    report('Уже скачано: ' + target.name, 1)
                    return
            except (ValueError, OSError):
                pass
        partial = target.with_suffix(target.suffix + '.part')
        if not target.is_file() or target.stat().st_size != size:
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > size:
                partial.unlink()
                offset = 0
            if offset < size:
                self.check()
                request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
                with urllib.request.urlopen(request, timeout=30) as response:
                    if response.status == 206:
                        if not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                            raise RuntimeError('Сервер вернул некорректное продолжение файла.')
                    else:
                        offset = 0
                    with partial.open('ab' if offset else 'wb') as dest:
                        last = 0
                        while True:
                            self.check()
                            block = response.read(4 * 1024 * 1024)
                            if not block:
                                break
                            dest.write(block)
                            offset += len(block)
                            if offset > size:
                                raise RuntimeError('Размер модели превышает ожидаемый.')
                            if time.monotonic() - last > .3:
                                report(f'{target.name}: {offset/1e9:.2f} / {size/1e9:.2f} ГБ', offset/size,
                                       current=offset, total=size)
                                last = time.monotonic()
            if partial.stat().st_size != size:
                raise RuntimeError('Скачивание прервано: размер модели не совпадает. Повторите установку.')
            source = partial
        else:
            source = target
        hasher = hashlib.sha256()
        report('Проверяем SHA-256: ' + target.name, 0)
        with source.open('rb') as src:
            read, last = 0, 0
            while True:
                self.check()
                block = src.read(8 * 1024 * 1024)
                if not block:
                    break
                hasher.update(block)
                read += len(block)
                if time.monotonic() - last > .3:
                    report('Проверяем SHA-256: ' + target.name, read / size)
                    last = time.monotonic()
        if hasher.hexdigest() != digest:
            # Neither a complete partial nor a corrupt final file should poison
            # every later attempt. These paths contain this pinned download.
            partial.unlink(missing_ok=True)
            if source == target:
                target.unlink(missing_ok=True)
            stamp.unlink(missing_ok=True)
            raise RuntimeError('SHA-256 модели не совпадает. Повторите скачивание: ' + target.name)
        if source == partial:
            partial.replace(target)
        stamp.write_text(json.dumps(dict(sha256=digest, size=size, mtime_ns=target.stat().st_mtime_ns)))
        report('Проверено: ' + target.name, 1)

    def source(self, repo, sha, target):
        if (target / '.book-studio-revision').is_file():
            if (target / '.book-studio-revision').read_text() == sha:
                return
            raise RuntimeError('Версия исходников отличается: ' + str(target))
        if target.exists():
            raise RuntimeError('Незавершённый каталог исходников: ' + str(target))
        archive = ROOT / (sha + '.tar.gz')
        report('Скачиваем исходники: ' + repo)
        with urllib.request.urlopen(f'https://codeload.github.com/{repo}/tar.gz/{sha}', timeout=30) as response:
            with archive.open('wb') as dest:
                while True:
                    self.check()
                    data = response.read(1024 * 1024)
                    if not data:
                        break
                    dest.write(data)
        unpack = ROOT / ('unpack-' + uuid.uuid4().hex)
        try:
            unpack.mkdir()
            with tarfile.open(archive) as source:
                # Python >=3.12 is checked before installing dependencies.
                source.extractall(unpack, filter='data')
            children = list(unpack.iterdir())
            if len(children) != 1 or not children[0].is_dir():
                raise RuntimeError('Некорректный архив исходников.')
            target.parent.mkdir(parents=True, exist_ok=True)
            children[0].rename(target)
            (target / '.book-studio-revision').write_text(sha)
        finally:
            shutil.rmtree(unpack, ignore_errors=True)
            archive.unlink(missing_ok=True)

    def install(self, music=False):
        import fcntl
        with (ROOT / 'install.lock').open('w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('На сервере уже идёт установка Book Studio. Дождитесь её завершения.')
            return self._install(music=music)

    def wait_for_probe(self, music=False, timeout=180):
        """Decoding can block Comfy's event loop; wait without treating it as absent."""
        deadline = time.monotonic() + timeout
        reported = False
        while True:
            self.check()
            ready = probe(music=music)
            if ready.get('status') != 'busy':
                return ready
            if not reported:
                report('ComfyUI уже запущен, но пока не отвечает. Ждём завершения текущей операции…')
                reported = True
            if time.monotonic() >= deadline:
                raise TimeoutError(ready['message'])
            time.sleep(1)

    def download_weights(self, comfy, weights):
        for kind, name, repo, revision, size, digest in weights:
            remote_name = f'{kind}/{name}' if repo == 'Comfy-Org/stable-audio-3' else name
            self.download(f'https://huggingface.co/{repo}/resolve/{revision}/{remote_name}',
                          comfy/'models'/kind/name, size, digest)

    def install_music(self, ready):
        """Only add native music weights to the runtime that already serves Drama."""
        self.check()
        comfy = running_comfy_directory(ready['port'])
        needed = missing_bytes(comfy, MUSIC_WEIGHTS) + 512 * 1024**2
        if shutil.disk_usage(comfy).free < needed:
            raise RuntimeError('Для Stable Audio 3 Medium нужно ещё примерно ' +
                               str(round(needed/1e9, 1)) + ' ГБ свободного места.')
        report('Добавляем Stable Audio 3 Medium в запущенный ComfyUI…')
        self.download_weights(comfy, MUSIC_WEIGHTS)
        result = self.wait_for_probe(music=True)
        if not result['ready']:
            raise RuntimeError(result.get('message') or 'ComfyUI не обнаружил скачанную музыкальную модель.')
        report('Drama 3 и Stable Audio 3 Medium готовы.', 1)
        return result

    def _install(self, music=False):
        ready = self.wait_for_probe(music=music)
        if ready['ready']:
            report('Совместимая Drama 3' + (' и Stable Audio 3 Medium' if music else '') +
                   ' уже запущена. Повторное скачивание не нужно.', 1)
            return ready
        if ready.get('status') == 'music_missing':
            return self.install_music(ready)
        if ready.get('status') == 'incompatible':
            raise RuntimeError(ready['message'])
        report('Проверяем GPU, память и место на диске…')
        if sys.version_info < (3, 12):
            raise RuntimeError('Нужен Linux-образ с Python 3.12 или новее и NVIDIA CUDA.')
        gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.total,driver_version',
                                       '--format=csv,noheader,nounits'], text=True).splitlines()[0].split(',')
        if int(gpu[0]) < 22000 or int(gpu[1].strip().split('.')[0]) < 580:
            raise RuntimeError('Нужно минимум 22 ГБ VRAM и NVIDIA driver 580+ (CUDA 13).')
        ram = int(re.search(r'MemTotal:\s+(\d+)', Path('/proc/meminfo').read_text())[1]) * 1024
        with contextlib.suppress(OSError, ValueError):
            cgroup = (Path('/sys/fs/cgroup/memory.max')).read_text().strip()
            if cgroup != 'max':
                ram = min(ram, int(cgroup))
        if ram < 48 * 1024**3:
            raise RuntimeError('Для FP8 Drama 3 с выгрузкой экспертов нужно минимум 48 ГБ RAM.')
        comfy = ROOT / 'ComfyUI'
        python = ROOT/'venv/bin/python'
        weights = WEIGHTS + (MUSIC_WEIGHTS if music else [])
        missing = missing_bytes(comfy, weights)
        dependencies_needed = not (ROOT/'dependencies-ready').is_file() or not python.is_file()
        headroom = 10 * 1024**3 if dependencies_needed else 512 * 1024**2
        if shutil.disk_usage(ROOT).free < missing + headroom:
            raise RuntimeError('Недостаточно места: нужно ещё примерно ' + str(round((missing+headroom)/1e9, 1)) + ' ГБ.')
        self.source('Comfy-Org/ComfyUI', COMFY_SHA, comfy)
        self.source('PedroMarinhoDev/ComfyUI-Drama3', NODES_SHA, comfy/'custom_nodes/ComfyUI-Drama3')
        uv = shutil.which('uv')
        if not uv:
            self.command([sys.executable, '-m', 'pip', 'install', '--target', ROOT/'bootstrap',
                          '--no-cache-dir', 'uv==0.9.5'], 'Подготавливаем менеджер пакетов…')
            uv = ROOT/'bootstrap/bin/uv'
        if not python.exists():
            self.command([uv, 'venv', '--python', sys.executable, ROOT/'venv'], 'Создаём изолированное окружение…')
        constraints = ROOT/'constraints.txt'
        constraints.write_text('torch==2.11.0\ntorchaudio==2.11.0\ntorchvision==0.26.0\n')
        if not (ROOT/'dependencies-ready').exists():
            self.command([uv, 'pip', 'install', '--python', python, '--no-cache', '--index-url',
                          'https://download.pytorch.org/whl/cu130', 'torch==2.11.0',
                          'torchaudio==2.11.0', 'torchvision==0.26.0'], 'Устанавливаем PyTorch CUDA 13…')
            self.command([uv, 'pip', 'install', '--python', python, '--no-cache', '-c', constraints,
                          '-r', comfy/'requirements.txt', 'soundfile', 'einops', 'transformers',
                          'sentencepiece', 'safetensors', 'numpy'], 'Устанавливаем ComfyUI и зависимости Drama 3…')
            (ROOT/'dependencies-ready').write_text(COMFY_SHA + '\n' + NODES_SHA)
        self.download_weights(comfy, weights)
        self.check()
        # Never replace a service occupying our dedicated port.
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', 8187))
            except OSError:
                raise RuntimeError('Порт 8187 занят несовместимым сервисом. Освободите его и повторите подключение.')
        report('Запускаем Drama 3. Модели загрузятся при первой озвучке…')
        env = dict(os.environ, OMP_NUM_THREADS='4', MKL_NUM_THREADS='4', HF_HUB_DISABLE_TELEMETRY='1')
        with (ROOT/'server.log').open('ab', buffering=0) as log:
            proc = subprocess.Popen([str(python), 'main.py', '--listen', '127.0.0.1', '--port', '8187',
                                     '--preview-method', 'none', '--reserve-vram', '1', '--use-pytorch-cross-attention'],
                                    cwd=comfy, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                    start_new_session=True)
        (ROOT/'server.pid').write_text(str(proc.pid))
        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                self.check()
                if compatible(8187, music=music):
                    report('Drama 3' + (' и Stable Audio 3 Medium' if music else '') +
                           ' готова к подключению.', 1)
                    return dict(ready=True, port=8187, reused=False, music_ready=bool(music))
                if proc.poll() is not None:
                    raise RuntimeError('Сервис не запустился. Проверьте ' + str(ROOT/'server.log'))
                time.sleep(1)
            raise TimeoutError('Сервис не стал доступен за 180 секунд. Проверьте ' + str(ROOT/'server.log'))
        except BaseException:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
            raise


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--probe', action='store_true')
    group.add_argument('--install')
    group.add_argument('--cancel')
    parser.add_argument('--music', action='store_true', help='Проверить / установить Stable Audio 3 Medium')
    args = parser.parse_args()
    try:
        if args.cancel:
            if not re.fullmatch('[a-f0-9]{32}', args.cancel):
                raise ValueError('Некорректный идентификатор установки.')
            # Cancellation can arrive before the original SSH bootstrap starts.
            # Retain its marker so that a late installer sees it immediately.
            ROOT.mkdir(parents=True, exist_ok=True)
            (ROOT/('cancel-' + args.cancel)).touch()
            result = dict(cancel_requested=True)
        elif args.install:
            result = Installer(args.install).install(music=args.music)
        else:
            result = probe(music=args.music)
        emit('result', **result)
    except Exception as exc:
        emit('error', message=str(exc))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
