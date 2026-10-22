"""Drama 3 over an owned SSH tunnel; no CUDA or model weights on the client."""
import atexit
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

import imageio_ffmpeg
import numpy as np
import requests
import soundfile as sf
import websocket

import avatar_store as store
from drama3_server_setup import MODEL, CODEC, ASR
from drama3_text import chunks, frame_budget
from remote_ssh import SSHConnection, Cancelled, hidden
import tts_settings
import remote_jobs


def reset_cancel():
    (store.DATA/'ssh/cancel-speech').unlink(missing_ok=True)


def request_cancel():
    (store.DATA/'ssh').mkdir(parents=True, exist_ok=True)
    (store.DATA/'ssh/cancel-speech').touch()


def check_cancel():
    if (store.DATA/'ssh/cancel-speech').exists():
        raise Cancelled('Озвучка отменена. Готовые записи сохранены.')


class FileCancellation:
    def is_set(self):
        return (store.DATA/'ssh/cancel-speech').exists()


def graph(reference, text, transcript, seed, prefix):
    return {
        '2': dict(class_type='Drama3Loader', inputs=dict(model_name=MODEL, experts='in RAM',
                  expert_cache_gb=14.0, second_gpu='none', split_layer=0)),
        '3': dict(class_type='Drama3CodecLoader', inputs=dict(codec_name=CODEC)),
        '4': dict(class_type='LoadAudio', inputs=dict(audio=reference)),
        '5': dict(class_type='Drama3EncodeVoice', inputs=dict(codec=['3', 0], audio=['4', 0], transcript=transcript)),
        '6': dict(class_type='Drama3Generate', inputs=dict(model=['2', 0], text=text,
                  **{'voices.voice0': ['5', 0]}, seed=int(seed) % (2**64), temperature=1.0,
                  top_p=.9, top_k=0, max_frames=frame_budget(text), split_long_text=False, speakers='together')),
        '7': dict(class_type='Drama3Decode', inputs=dict(codec=['3', 0], codes=['6', 0], shorten_long_pauses=False)),
        '8': dict(class_type='SaveAudio', inputs=dict(audio=['7', 0], filename_prefix=prefix)),
    }


class Pipeline:
    supports_narrator_styles = True
    supports_progress = True

    def __init__(self, config=None, music=False):
        self.ssh = SSHConnection(config or tts_settings.settings())
        self.http = requests.Session()
        self.http.trust_env = False
        self.uploaded = {}
        self.pending = None
        self.url = None
        self.music = bool(music)
        self.remote_port = None
        self.ticket = None
        atexit.register(self.close)

    def load(self, progress=lambda *args: None):
        if self.url and self.ssh.tunnel and self.ssh.tunnel.poll() is None:
            return self
        progress(None, 'Подключаемся к Drama 3 по SSH…')
        # Installation was explicitly authorized by choosing this backend. The
        # idempotent bootstrap also restarts its own runtime after a server reboot.
        options = dict(cancel=FileCancellation(), install=True)
        if self.music:
            options['music'] = True
        ready = self.ssh.prepare(lambda event: progress(event.get('value'), event.get('message', '')), **options)
        self.remote_port = ready.get('port')
        self.url = self.ssh.url
        self.http.get(self.url + '/system_stats', timeout=15).raise_for_status()
        progress(1, 'Drama 3 · SSH-сервер готов')
        return self

    def cancel_job(self, prompt_id):
        if not prompt_id or not self.url:
            return
        # Atomic server-side targeting. NEVER use global /interrupt or clear /queue.
        remote_jobs.cancel_at(self.http, self.url, prompt_id)
        if self.ticket:
            remote_jobs.finish(self.ticket)
            self.ticket = None

    def close(self):
        try:
            if self.pending:
                self.cancel_job(self.pending)
        finally:
            self.pending = None
            self.ssh.close()
            self.url = None
            self.http.close()

    def upload(self, reference):
        reference = Path(reference)
        digest = hashlib.sha256(reference.read_bytes()).hexdigest()
        if digest in self.uploaded:
            return self.uploaded[digest]
        with reference.open('rb') as src:
            response = self.http.post(self.url + '/upload/image', files={'image':
                ('bookstudio_' + digest[:24] + reference.suffix.lower(), src, 'application/octet-stream')},
                data={'type': 'input', 'overwrite': 'false'}, timeout=60)
        response.raise_for_status()
        uploaded = response.json()
        name = '/'.join(part for part in (uploaded.get('subfolder', ''), uploaded['name']) if part)
        self.uploaded[digest] = name
        return name

    def execute(self, prompt, progress=lambda *args: None, cancel=lambda: None, timeout=1800):
        """WS provides live events; history remains authoritative after reconnect."""
        self.load(progress)
        client = uuid.uuid4().hex
        ws = None
        prompt_id = None
        try:
            check_cancel()
            cancel()
            try:
                ws = websocket.create_connection(self.url.replace('http:', 'ws:') + '/ws?clientId=' + client,
                                                 timeout=10, http_no_proxy=['127.0.0.1', 'localhost'])
                # The SSH handshake can take seconds; only subsequent receives
                # need a short timeout so cancellation remains responsive.
                ws.settimeout(.4)
            except (OSError, websocket.WebSocketException):
                pass  # History polling still reports queue/execution/completion.
            receipt = remote_jobs.register(self.url, self.ssh.config, self.remote_port)
            self.ticket = receipt['ticket']
            prompt_id = receipt['prompt_id']
            with remote_jobs.locked(self.ticket):
                check_cancel()
                cancel()
                # Persist the ID BEFORE sending. A lost HTTP response must not
                # leave a GPU job whose owner no longer knows its ID.
                response = self.http.post(self.url + '/prompt',
                    json=dict(prompt=prompt, client_id=client, prompt_id=prompt_id), timeout=30)
                if not response.ok:
                    remote_jobs.finish(self.ticket)
                    self.ticket = None
                    raise RuntimeError('Сервер отклонил запрос: ' + response.text[:1800])
                prompt_id = response.json()['prompt_id']
                remote_jobs.update(self.ticket, prompt_id=prompt_id, phase='submitted')
            self.pending = prompt_id
            deadline, next_history, next_status = time.monotonic() + timeout, 0, 0
            progress(None, 'Drama 3: ожидаем сервер; первая загрузка модели может занять несколько минут…')
            while time.monotonic() < deadline:
                check_cancel()
                cancel()
                now = time.monotonic()
                if now >= next_history:
                    response = self.http.get(self.url + '/history/' + prompt_id, timeout=10)
                    response.raise_for_status()
                    item = response.json().get(prompt_id)
                    if item:
                        status = item.get('status', {})
                        for kind, data in status.get('messages', []):
                            if kind in ('execution_error', 'execution_interrupted'):
                                raise RuntimeError('Drama 3: ' + data.get('exception_message', 'генерация прервана'))
                        if status.get('status_str') == 'error':
                            raise RuntimeError('Drama 3 завершила запрос с ошибкой.')
                        if status.get('completed'):
                            remote_jobs.finish(self.ticket)
                            self.ticket = None
                            self.pending = None
                            return item.get('outputs', {})
                    next_history = now + 1
                if ws:
                    try:
                        raw = ws.recv()
                        if isinstance(raw, str):
                            event = json.loads(raw)
                            data = event.get('data', {})
                            if data.get('prompt_id') == prompt_id:
                                if event.get('type') == 'progress':
                                    value, maximum = data.get('value', 0), data.get('max', 0)
                                    if self.music:
                                        progress(value / maximum if maximum else None,
                                                 f'Stable Audio 3: шаг {value}/{maximum}')
                                    else:
                                        progress(None, f"Drama 3: сгенерировано {value} кадров · лимит {maximum}")
                                elif event.get('type') == 'executing' and data.get('node'):
                                    node = prompt.get(str(data['node']), {}).get('class_type', '')
                                    label = {'Drama3Loader': 'загружаем модель',
                                        'Drama3EncodeVoice': 'подготавливаем голос', 'Drama3Generate': 'озвучиваем',
                                        'Drama3Decode': 'декодируем звук', 'SaveAudio': 'сохраняем звук',
                                        'CheckpointLoaderSimple': 'загружаем музыкальную модель',
                                        'CLIPLoader': 'подготавливаем описание музыки',
                                        'CLIPTextEncode': 'готовим музыкальную сцену',
                                        'EmptyLatentAudio': 'готовим длительность фона',
                                        'KSampler': 'создаём фоновую музыку',
                                        'VAEDecodeAudio': 'восстанавливаем звук'}.get(node, 'подготавливаем звук')
                                    progress(None, ('Stable Audio 3: ' if self.music else 'Drama 3: ') + label)
                    except websocket.WebSocketTimeoutException:
                        pass
                    except (ValueError, OSError, websocket.WebSocketException):
                        ws.close()
                        ws = None
                else:
                    time.sleep(.2)
                    if now >= next_status:
                        progress(None, 'Drama 3: сервер обрабатывает запрос…')
                        next_status = now + 10
            raise TimeoutError('Drama 3: превышено время ожидания генерации.')
        except BaseException as exc:
            if prompt_id and self.ticket:
                try:
                    self.cancel_job(prompt_id)
                except Exception as cancel_error:
                    raise RuntimeError('Связь с сервером потеряна: отмену задания ' + prompt_id +
                                       ' подтвердить не удалось. ' + str(cancel_error)) from exc
            raise
        finally:
            self.pending = None
            if ws:
                ws.close()

    def transcribe_reference(self, reference):
        self.load()
        uploaded = self.upload(reference)
        outputs = self.execute({
            '1': dict(class_type='LoadAudio', inputs=dict(audio=uploaded)),
            '2': dict(class_type='Qwen3ASRLoader', inputs=dict(model_name=ASR)),
            '3': dict(class_type='Qwen3ASRTranscribe', inputs=dict(model=['2', 0], audio=['1', 0],
                       language='auto', context='', max_new_tokens=1024)),
            '4': dict(class_type='PreviewAny', inputs=dict(source=['3', 0])),
        })
        text = ''.join(outputs.get('4', {}).get('text', [])).strip()
        if not text:
            raise RuntimeError('Не удалось распознать образец. Введите его расшифровку вручную.')
        return text

    def download_audio(self, descriptor, target, progress, cancel, stereo=False):
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix('.download')
        try:
            with self.http.get(self.url + '/view', params={key: descriptor[key] for key in
                               ('filename', 'subfolder', 'type')}, stream=True, timeout=(10, 30)) as response:
                response.raise_for_status()
                size, received = int(response.headers.get('Content-Length', 0)), 0
                with partial.open('wb') as dest:
                    for block in response.iter_content(256 * 1024):
                        check_cancel()
                        cancel()
                        dest.write(block)
                        received += len(block)
                        progress(received / size if size else None, 'Скачиваем готовую озвучку…')
                if size and received != size:
                    raise RuntimeError('Аудиофайл скачан не полностью.')
            audio, sr = sf.read(partial, dtype='float32')
            if audio.ndim == 2 and not stereo:
                audio = audio.mean(axis=1)
            if sr < 16000 or sr > 192000 or not len(audio) or not np.isfinite(audio).all() or np.max(np.abs(audio)) < 1e-5:
                raise RuntimeError('Сервер вернул пустое или некорректное аудио.')
            return audio, sr
        finally:
            partial.unlink(missing_ok=True)

    def clip(self, reference, text, transcript, seed, target, progress, cancel, sample_rate=None):
        self.load(progress)
        check_cancel()
        cancel()
        uploaded = self.upload(reference)
        outputs = self.execute(graph(uploaded, text, transcript, seed, 'bookstudio/' + uuid.uuid4().hex), progress, cancel)
        descriptors = outputs.get('8', {}).get('audio', [])
        if not descriptors:
            raise RuntimeError('Drama 3 не вернула аудиофайл.')
        audio, sr = self.download_audio(descriptors[0], target, progress, cancel)
        native_rate = sr
        if sample_rate and sr != sample_rate:
            # FFmpeg is already bundled with Book Studio; keep book joins at 24 kHz.
            with tempfile.TemporaryDirectory(prefix='drama3-resample-') as temp:
                source, converted = Path(temp)/'source.wav', Path(temp)/'converted.wav'
                sf.write(source, audio, sr, subtype='PCM_24')
                subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-i', str(source),
                                '-ar', str(sample_rate), '-ac', '1', str(converted)],
                               check=True, capture_output=True, **hidden())
                audio, sr = sf.read(converted, dtype='float32')
        target = Path(target)
        temp = target.with_suffix('.partial.wav')
        sf.write(temp, audio, sr, subtype='PCM_24')
        temp.replace(target)
        report = dict(model=tts_settings.MODEL_ID, text=text, seed=int(seed), sample_rate=sr,
                      native_sample_rate=native_rate, temperature=1.0, top_p=.9, top_k=0,
                      max_frames=frame_budget(text), trimmed_ms=0, needs_review=False)
        # Frame budget is a hard cap; reaching it warrants listening, not silent success.
        report['needs_review'] = len(audio) / sr >= frame_budget(text) / 21.5 - .5
        store.atomic_json(target.with_suffix('.cleanup.json'), report)
        return str(target)

    def synthesize_book_clip(self, reference, text, transcript, seed, target, narrator_style=None,
                             progress=lambda *args: None, cancel=lambda: None):
        return self.clip(reference, text, transcript, seed, target, progress, cancel, sample_rate=24000)

    def synthesize(self, reference, text, reference_text='', start=0, duration=15, seed=42, progress=lambda *args: None):
        if not text.strip() or len(text) > 6000:
            raise ValueError('Введите текст до 6000 символов.')
        from voice_reference import prepare_reference
        folder = store.DATA/'generations'/('drama3_' + uuid.uuid4().hex)
        folder.mkdir(parents=True)
        sample = prepare_reference(reference, folder, start, duration)
        transcript = reference_text.strip() or self.transcribe_reference(sample)
        pieces = list(chunks(text))
        waves, reports, sr = [], [], 44100
        for index, piece in enumerate(pieces):
            def clip_progress(value, message):
                progress(None if value is None else (index + value*.9) / len(pieces), f'Фрагмент {index+1}/{len(pieces)} · ' + message)
            target = Path(self.clip(sample, piece, transcript, int(seed)+index,
                                   folder/f'{index:04d}.wav', clip_progress, lambda: None))
            audio, current_rate = sf.read(target, dtype='float32')
            if waves and current_rate != sr:
                raise RuntimeError('Сервер изменил частоту дискретизации между фрагментами.')
            sr = current_rate
            if waves:
                waves.append(np.zeros(int(.14*sr), dtype='float32'))
            waves.append(audio)
            reports.append(store.load_json(target.with_suffix('.cleanup.json'), {}))
        audio = np.concatenate(waves)
        wav, mp3, metadata = folder/'speech.wav', folder/'speech.mp3', folder/'generation.json'
        sf.write(wav, audio, sr, subtype='PCM_24')
        progress(.98, 'Сохраняем WAV и MP3…')
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-i', str(wav),
                        '-codec:a', 'libmp3lame', '-b:a', '192k', str(mp3)], check=True, capture_output=True, **hidden())
        store.atomic_json(metadata, dict(model=tts_settings.MODEL_ID, text=text, reference_text=transcript,
            duration_seconds=len(audio)/sr, sample_rate=sr, seed=seed, fragments=reports,
            needs_review=any(report.get('needs_review') for report in reports)))
        progress(1, 'Готово')
        return str(mp3), str(wav), str(metadata), transcript
