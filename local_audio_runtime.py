"""Optional local Stable Audio 3 runtime. No sockets, SSH or speech weights.

The isolated worker uses Comfy's inference libraries directly, without starting
its UI or HTTP service. This gives Windows users PyTorch attention and CPU
offloading without the native Stable Audio package's Flash Attention build.
"""
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid
import zipfile

import requests

import avatar_store as store
from routerai_engine import check_cancel

SOURCE_REVISION = '355cd6b14c92c19ac3188fe528e47a3f21ef5178'
MODEL_REVISION = '75aad8836271cb5a5123fb58304fae5d3bb4b0f9'
MODEL = 'stable_audio_3_medium.safetensors'
ENCODER = 't5gemma_b_b_ul2.safetensors'
VERSION = 'stable-audio3-local-lcm8-v1'
MAX_CHUNK_SECONDS = 15.
LOCK_WAIT_TIMEOUT = 2 * 60 * 60
LOCK_POLL_SECONDS = .1
LOCK_PROGRESS_SECONDS = 2.
WEIGHTS = (
    ('checkpoints', MODEL, 9222116660,
     '48d9c65e290e7bcd5194e0633bfc2424a59ee9683f5c2d58762d997b7d8ce0b5'),
    ('text_encoders', ENCODER, 1187264003,
     '1e1eba25be8872edb0d3c6335c6658fd6388e7b14b60da6e454e404cfcd8150e'),
)


def hidden():
    return dict(creationflags=subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else {}


def root():
    return store.ROOT / 'models' / 'local-audio'


def python_path():
    return root() / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def _cancel(callback):
    callback()


@contextmanager
def _lock(name, progress=lambda *args: None, cancel=lambda: None,
          timeout=LOCK_WAIT_TIMEOUT):
    """Wait cancellably for the OS lock; an abandoned file is not a lock.

    Preparation takes generation.lock before prepare.lock. Keep that order for
    all callers, and never nest prepare() inside an acquired generation lock.
    The OS releases byte/flock locks even if their owning process crashes.
    """
    _cancel(cancel)
    directory = root()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / name).open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        started = time.monotonic()
        last_report = None
        while True:
            _cancel(cancel)
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if (exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK)
                        and getattr(exc, 'winerror', None) not in (32, 33, 36)):
                    raise
                now = time.monotonic()
                waited = now - started
                if waited >= timeout:
                    raise RuntimeError(
                        'Истекло время ожидания локальной модели звука. '
                        'Другая подготовка или генерация всё ещё выполняется. '
                        'Повторите задачу после её завершения; готовые записи сохранены.') from exc
                if last_report is None or now - last_report >= LOCK_PROGRESS_SECONDS:
                    task = ('подготовки локальной модели' if name == 'prepare.lock'
                            else 'подготовки или генерации музыки и звуков')
                    progress(None, f'Ожидаем завершения {task}: {int(waited)} с. '
                             'Ожидание можно отменить.')
                    last_report = now
                time.sleep(min(LOCK_POLL_SECONDS, timeout - waited))
        try:
            _cancel(cancel)
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)


def _hash(path, progress, cancel):
    digest = hashlib.sha256()
    size = path.stat().st_size
    done = 0
    with path.open('rb') as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
            _cancel(cancel); digest.update(block); done += len(block)
            progress(done / max(1, size), 'Проверяем скачанную модель: ' + path.name)
    return digest.hexdigest()


def _verified(path, size, digest):
    marker = path.with_suffix(path.suffix + '.verified.json')
    saved = store.load_json(marker, {})
    return (path.is_file() and path.stat().st_size == size
            and saved.get('sha256') == digest
            and saved.get('mtime_ns') == path.stat().st_mtime_ns)


def _download(url, target, progress, cancel, expected_size=None, sha256=None):
    """Resume only HTTP byte ranges which the origin actually confirms."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if expected_size and sha256 and _verified(target, expected_size, sha256):
        progress(1, 'Модель уже скачана: ' + target.name)
        return
    if target.is_file() and expected_size and target.stat().st_size == expected_size:
        if _hash(target, progress, cancel) == sha256:
            store.atomic_json(target.with_suffix(target.suffix + '.verified.json'),
                              dict(sha256=sha256, mtime_ns=target.stat().st_mtime_ns))
            return
    partial = target.with_suffix(target.suffix + '.partial')
    for attempt in range(5):
        _cancel(cancel)
        offset = partial.stat().st_size if partial.is_file() else 0
        if expected_size and offset == expected_size:
            break
        if expected_size and offset > expected_size:
            partial.unlink(); offset = 0
        try:
            headers = {'Range': f'bytes={offset}-'} if offset else {}
            with requests.get(url, headers=headers, stream=True, timeout=(20, 30)) as response:
                response.raise_for_status()
                confirmed = response.status_code == 206
                if confirmed:
                    match = response.headers.get('Content-Range', '').split(' ', 1)[-1].split('-', 1)[0]
                    if match != str(offset):
                        raise RuntimeError('Источник вернул неверный диапазон скачивания.')
                else:
                    offset = 0
                total = expected_size or offset + int(response.headers.get('Content-Length') or 0)
                with partial.open('ab' if confirmed else 'wb') as output:
                    for block in response.iter_content(1024 * 1024):
                        _cancel(cancel)
                        if not block: continue
                        output.write(block); offset += len(block)
                        if expected_size and offset > expected_size:
                            raise RuntimeError('Размер модели превышает ожидаемый.')
                        progress(offset / total if total else None,
                                 f'{target.name}: {offset / 1024**2:.0f}' +
                                 (f' / {total / 1024**2:.0f} МБ' if total else ' МБ'))
                if expected_size and offset != expected_size:
                    raise requests.ConnectionError('Incomplete model download')
            break
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 4: raise RuntimeError('Не удалось докачать модель. Повторите подготовку — скачивание продолжится.') from None
            progress(None, 'Соединение прервано; продолжаем скачивание…')
            for _ in range(10): _cancel(cancel); time.sleep(.1)
    if sha256 and _hash(partial, progress, cancel) != sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeError('Проверка SHA-256 модели не прошла. Повторите скачивание.')
    _cancel(cancel)
    partial.replace(target)
    if sha256:
        store.atomic_json(target.with_suffix(target.suffix + '.verified.json'),
                          dict(sha256=sha256, mtime_ns=target.stat().st_mtime_ns))


def _command(arguments, progress, cancel, message):
    progress(None, message)
    with (root() / 'install.log').open('ab') as log:
        process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, **hidden())
        try:
            while process.poll() is None:
                _cancel(cancel); time.sleep(.1)
            if process.returncode:
                raise RuntimeError('Не удалось установить локальную модель звука. Подробности: ' + str(root() / 'install.log'))
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


def prepare(progress=lambda *args: None, cancel=lambda: None):
    """Explicit/on-demand install; importing this module never downloads anything."""
    _cancel(cancel)
    with _lock('generation.lock', progress, cancel), _lock('prepare.lock', progress, cancel):
        source = root() / 'inference'
        marker = root() / 'runtime.json'
        constraints = store.ROOT / 'requirements-audio.txt'
        signature = hashlib.sha256(constraints.read_bytes()).hexdigest()
        saved = store.load_json(marker, {})
        if not (python_path().is_file() and (source / 'comfy/sd.py').is_file()
                and saved.get('source') == SOURCE_REVISION and saved.get('constraints') == signature):
            archive = root() / ('inference-' + SOURCE_REVISION + '.zip')
            if not archive.is_file():
                _download('https://codeload.github.com/Comfy-Org/ComfyUI/zip/' + SOURCE_REVISION,
                          archive, progress, cancel)
            progress(None, 'Распаковываем локальный модуль генерации звука…')
            source.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as package:
                for item in package.infolist():
                    _cancel(cancel)
                    name = Path(*Path(item.filename).parts[1:])
                    if not name.parts or '..' in name.parts or name.is_absolute() or name.drive: continue
                    target = source / name
                    if item.is_dir(): target.mkdir(parents=True, exist_ok=True); continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(item) as src, target.open('wb') as dst:
                        import shutil
                        shutil.copyfileobj(src, dst)
            if not python_path().is_file():
                executable = Path(sys.executable)
                if executable.name.lower() == 'pythonw.exe': executable = executable.with_name('python.exe')
                _command([str(executable), '-m', 'venv', str(root() / 'venv')], progress, cancel,
                         'Создаём отдельное окружение для музыки и звуков…')
            base = [str(python_path()), '-m', 'pip', 'install', '--disable-pip-version-check', '--only-binary=:all:']
            _command(base + ['torch==2.11.0', 'torchvision==0.26.0', 'torchaudio==2.11.0',
                            '--index-url', 'https://download.pytorch.org/whl/cu128'], progress, cancel,
                     'Скачиваем PyTorch для локального GPU; ход установки — в install.log…')
            _command(base + ['-r', str(source / 'requirements.txt'), '-c', str(constraints), 'soundfile==0.13.1'],
                     progress, cancel, 'Устанавливаем зависимости локального звука…')
            store.atomic_json(marker, dict(source=SOURCE_REVISION, constraints=signature))
        total = len(WEIGHTS)
        for index, (folder, filename, size, digest) in enumerate(WEIGHTS):
            def update(value, message):
                progress(None if value is None else (index + value) / total, message)
            _download('https://huggingface.co/Comfy-Org/stable-audio-3/resolve/' + MODEL_REVISION +
                      '/' + folder + '/' + filename, root() / 'models' / folder / filename,
                      update, cancel, size, digest)
        progress(1, 'Stable Audio 3 Medium готова: одна модель для музыки и звуков')
    return dict(ready=True, model=MODEL, path=str(root()), memory_mode='cpu-offload')


class Pipeline:
    """One persistent local process; music and SFX share the same lazy weights."""
    def __init__(self):
        self.process = None
        self.messages = queue.Queue()
        self.log = None
        self.lock = None

    def _start(self, progress, cancel):
        if self.process is not None:
            if self.process.poll() is None: return
            raise RuntimeError('Процесс локальной модели завершился. Повторите генерацию.')
        prepare(progress, cancel)
        lock = _lock('generation.lock', progress, cancel); lock.__enter__(); self.lock = lock
        try:
            from tts_settings import settings
            config = settings()
            self.log = (root() / 'generation.log').open('ab')
            arguments = [str(python_path()), '-X', 'utf8', '-u', str(store.ROOT / 'local_audio_worker.py'),
                         '--runtime', str(root()), '--device', config.get('local_audio_device', 'auto')]
            if config.get('local_audio_offload', True): arguments.append('--offload')
            self.process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=self.log, text=True, encoding='utf-8', **hidden())
        except BaseException:
            self.close(); raise
        stream = self.process.stdout
        messages = self.messages
        def reader():
            try:
                for line in stream:
                    try: messages.put(json.loads(line))
                    except ValueError: pass
            except (OSError, ValueError):
                pass
            finally: messages.put(dict(type='closed'))
        threading.Thread(target=reader, daemon=True).start()

    def generate(self, prompt, seconds, seed, progress=lambda *args: None, cancel=lambda: None):
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
            raise ValueError('Нужно описание музыки или звукового эффекта.')
        if not 1 <= float(seconds) <= MAX_CHUNK_SECONDS + .01:
            raise ValueError('Локальная генерация: от 1 до 15 секунд за фрагмент.')
        caller_cancel = cancel
        def cancel():
            check_cancel()
            caller_cancel()
        _cancel(cancel)
        output = root() / ('audio-' + uuid.uuid4().hex + '.wav')
        try:
            self._start(progress, cancel)
            self.process.stdin.write(json.dumps(dict(prompt=prompt, seconds=float(seconds),
                seed=int(seed) % (2**64), output=str(output)), ensure_ascii=True) + '\n')
            self.process.stdin.flush()
            while True:
                _cancel(cancel)
                try: event = self.messages.get(timeout=.1)
                except queue.Empty: continue
                if event.get('type') == 'progress': progress(event.get('value'), event.get('message', ''))
                elif event.get('type') == 'error': raise RuntimeError(event.get('message', 'Ошибка локального звука'))
                elif event.get('type') == 'complete':
                    import soundfile as sf
                    audio, rate = sf.read(str(output), dtype='float32', always_2d=True)
                    return audio, rate
                elif event.get('type') == 'closed':
                    raise RuntimeError('Локальная модель завершилась. Подробности: ' + str(root() / 'generation.log'))
        except BaseException:
            self.close(); raise
        finally:
            output.unlink(missing_ok=True)
            output.with_suffix('.partial.wav').unlink(missing_ok=True)

    def close(self):
        try:
            if self.process is not None:
                if self.process.poll() is None:
                    self.process.terminate()
                    try: self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(timeout=5)
                if self.process.stdin: self.process.stdin.close()
                if self.process.stdout: self.process.stdout.close()
        finally:
            self.process = None
            self.messages = queue.Queue()
            if self.log: self.log.close(); self.log = None
            if self.lock: self.lock.__exit__(None, None, None); self.lock = None
