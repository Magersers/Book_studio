"""Drama 3 speech through RouterAI; no SSH, CUDA or speech weights on the PC.

RouterAI's OpenAI-compatible envelope carries native Fish Audio options in
provider.options['fish-audio']. Selected avatar recordings are sent inline;
they are never published as voice-library models. A paid POST is attempted
once. A lost connection must be resumed explicitly, since the provider may
already have charged or completed the request.
"""
import atexit
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
import uuid

import imageio_ffmpeg
import numpy as np
import requests
import soundfile as sf

import avatar_store as store
import tts_settings

MODEL = 'fish-audio/drama-3'
VERSION = 'routerai-drama3-inline-reference-v1'
MAX_AUDIO_BYTES = 128 * 1024 * 1024
RESERVED_OPTIONS = frozenset((
    'text', 'input', 'model', 'voice', 'references', 'reference_id', 'format',
    'sample_rate', 'mp3_bitrate', 'seed', 'authorization', 'api_key', 'headers',
    'base_url', 'url', 'provider',
))


class Cancelled(RuntimeError):
    pass


def hidden():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def _cancel_path():
    return store.DATA / 'runtime' / 'cancel-audio'


def reset_cancel():
    _cancel_path().unlink(missing_ok=True)


def request_cancel():
    path = _cancel_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def check_cancel():
    if _cancel_path().exists():
        raise Cancelled('Озвучка отменена. Готовые записи сохранены.')


class FileCancellation:
    def is_set(self):
        return _cancel_path().exists()


def _check_callback(callback=None):
    if callback is None:
        return
    if callable(callback):
        callback()
    elif callback.is_set():
        raise Cancelled('Операция отменена.')


def _check(callback=None):
    check_cancel()
    _check_callback(callback)


def status_error(status):
    messages = {
        400: 'RouterAI отклонил запрос. Проверьте параметры Fish Audio.',
        401: 'RouterAI не принял API-ключ. Проверьте настройки озвучки.',
        402: 'На балансе RouterAI недостаточно средств.',
        403: 'RouterAI запретил доступ к выбранной модели.',
        404: 'Адрес API или модель Drama 3 не найдены.',
        413: 'Запрос слишком большой. Сократите текст или образец голоса.',
        422: 'RouterAI не принял параметры Fish Audio или образец голоса.',
        429: 'RouterAI ограничил частоту запросов. Продолжите позже.',
    }
    return messages.get(status, f'RouterAI вернул HTTP {status}.') + ' Автоматического повтора нет.'


def probe(base_url, key, model=MODEL, cancel=None):
    """Read-only authentication/model discovery; never synthesizes paid audio."""
    base_url = tts_settings.normalize_url(base_url)
    key = tts_settings.validate_key(key)
    model = tts_settings.validate_model(model)
    _check_callback(cancel)
    try:
        with requests.Session() as session:
            with session.get(base_url + '/models', headers={'Authorization': 'Bearer ' + key},
                             timeout=(10, 20), allow_redirects=False) as response:
                if response.status_code != 200:
                    raise RuntimeError(status_error(response.status_code))
                data = response.json()
    except requests.RequestException:
        raise RuntimeError('Не удалось подключиться к RouterAI. Проверьте адрес и интернет.') from None
    except ValueError:
        raise RuntimeError('RouterAI не вернул список моделей в формате JSON.') from None
    _check_callback(cancel)
    if not isinstance(data, dict) or not isinstance(data.get('data'), list):
        raise RuntimeError('RouterAI не вернул список моделей.')
    if model not in [item.get('id') for item in data['data'] if isinstance(item, dict)]:
        raise RuntimeError('Ключ принят, но выбранной модели нет в доступном списке.')
    return 'Подключение проверено. Drama 3 доступна; платная генерация не запускалась.'


def _fish_options(config):
    options = config.get('fish_options', {})
    if not isinstance(options, dict) or any(not isinstance(key, str) for key in options):
        raise ValueError('Параметры Fish Audio должны быть JSON-объектом.')
    if any(key.lower() in RESERVED_OPTIONS for key in options):
        raise ValueError('Голос, текст, адрес и формат задаёт программа; удалите их из параметров Fish Audio.')
    try:
        encoded = json.dumps(options, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError('Параметры Fish Audio содержат некорректные JSON-значения.') from None
    if len(encoded.encode('utf-8')) > 65536:
        raise ValueError('Параметры Fish Audio слишком большие.')
    result = dict(temperature=1.0, top_p=.9, latency='normal')
    result.update(copy.deepcopy(options))
    return result


def cache_identity(config=None):
    """Speech-cache identity excludes credentials and local music settings."""
    config = config or tts_settings.settings()
    return dict(version=VERSION,
                base_url=tts_settings.normalize_url(config['base_url']),
                model=tts_settings.validate_model(config.get('model', MODEL)),
                fish_options=_fish_options(config))


def _reference(reference, transcript):
    if not isinstance(transcript, str) or not transcript.strip():
        raise ValueError('Введите точную расшифровку выбранного образца голоса. Для API она нужна при клонировании.')
    path = Path(reference)
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Образец голоса не найден или превышает 16 МБ.')
    audio, rate = sf.read(path, dtype='float32', always_2d=True)
    if (not 8000 <= rate <= 192000 or not 3 <= len(audio) / rate <= 30.1
            or not np.isfinite(audio).all() or np.max(np.abs(audio)) < .00001):
        raise ValueError('Нужен непустой образец голоса длительностью от 3 до 30 секунд.')
    encoded = io.BytesIO()
    sf.write(encoded, audio.mean(axis=1), rate, format='WAV', subtype='PCM_16')
    return dict(audio=base64.b64encode(encoded.getvalue()).decode('ascii'), text=transcript.strip())


class Pipeline:
    supports_narrator_styles = True
    supports_progress = True

    def __init__(self, config=None):
        self.config = dict(config) if config is not None else tts_settings.settings()
        self.http = requests.Session()
        # The default adapter does not retry POST. Make the billing rule explicit.
        adapter = requests.adapters.HTTPAdapter(max_retries=0)
        self.http.mount('https://', adapter)
        self.url = None
        self.key = ''
        self.active_response = None
        self.active_stop = None
        self.reference_cache = {}
        self.closed = False
        atexit.register(self.close)

    def load(self, progress=lambda *args: None):
        check_cancel()
        if self.closed:
            raise RuntimeError('Клиент RouterAI уже закрыт.')
        if not self.url:
            identity = cache_identity(self.config)
            key = tts_settings.api_key(identity['base_url'])
            self.identity = identity
            self.url = identity['base_url']
            self.model = identity['model']
            self.key = key
        progress(1, 'Озвучка через RouterAI · Drama 3')
        return self

    def close(self):
        self.closed = True
        if self.active_stop:
            self.active_stop.set()
        if self.active_response is not None:
            threading.Thread(target=self._close_response, args=(self.active_response,),
                             name='RouterAI-close', daemon=True).start()
        self.active_response = None
        self.http.close()
        self.key = ''
        self.reference_cache.clear()

    def transcribe_reference(self, reference):
        raise ValueError('Для нового голоса впишите слова из образца в поле «Расшифровка». '
                         'Распознавание и загрузка локальной речевой модели не запускаются.')

    def _voice(self, reference, transcript):
        path = Path(reference)
        if not path.is_file():
            raise ValueError('Образец выбранного голоса не найден.')
        stat = path.stat()
        identity = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, transcript)
        if identity not in self.reference_cache:
            self.reference_cache[identity] = _reference(reference, transcript)
        return self.reference_cache[identity]

    def _download(self, payload, destination, progress, cancel):
        """One request; a worker keeps UI cancellation responsive during headers/read."""
        events = queue.Queue(maxsize=8)
        stopped = threading.Event()
        self.active_stop = stopped
        deadline = time.monotonic() + 900
        key = self.key

        def send(event):
            while not stopped.is_set():
                try:
                    events.put(event, timeout=.1)
                    return
                except queue.Full:
                    pass

        def reader():
            try:
                if stopped.is_set():
                    return
                check_cancel()
                with self.http.post(self.url + '/audio/speech',
                        headers={'Authorization': 'Bearer ' + key, 'Accept': 'audio/mpeg'},
                        json=payload, stream=True, timeout=(10, 90), allow_redirects=False) as response:
                    if stopped.is_set() or self.active_stop is not stopped or self.closed:
                        return
                    self.active_response = response
                    if response.status_code != 200:
                        send(('error', status_error(response.status_code)))
                        return
                    content_type = response.headers.get('Content-Type', '').lower()
                    if 'json' in content_type or 'text/' in content_type:
                        send(('error', 'RouterAI вернул текст вместо аудио. Проверьте модель и параметры Fish Audio.'))
                        return
                    try:
                        length = int(response.headers.get('Content-Length', 0))
                    except ValueError:
                        length = 0
                    if response.headers.get('Content-Encoding', 'identity') != 'identity':
                        length = 0
                    if length > MAX_AUDIO_BYTES:
                        send(('error', 'Ответ RouterAI превышает допустимый размер аудио.'))
                        return
                    generation = response.headers.get('X-Generation-Id', '')
                    if not re.fullmatch(r'[A-Za-z0-9:_-]{1,160}', generation) or key in generation:
                        generation = ''
                    send(('start', (length, generation)))
                    for block in response.iter_content(64 * 1024):
                        if stopped.is_set():
                            return
                        if block:
                            send(('data', block))
                    send(('done', None))
            except requests.RequestException:
                send(('error', 'Связь с RouterAI прервалась. Запрос мог выполниться у провайдера; '
                               'автоматического повтора нет. Готовые фрагменты сохранены.'))
            except Exception:
                # Do not surface a requests/payload repr containing credentials
                # or a base64 recording through a background-thread traceback.
                send(('error', 'Не удалось получить аудио RouterAI. Автоматического повтора нет.'))
            finally:
                if self.active_stop is stopped:
                    self.active_response = None

        thread = threading.Thread(target=reader, name='RouterAI-audio', daemon=True)
        thread.start()
        received, expected, generation, last_status = 0, 0, '', 0.
        try:
            with Path(destination).open('wb') as output:
                while True:
                    _check(cancel)
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Превышено время ожидания RouterAI. Запрос мог выполниться; автоматического повтора нет.')
                    try:
                        kind, value = events.get(timeout=.1)
                    except queue.Empty:
                        if time.monotonic() - last_status >= 2:
                            progress(None, 'Drama 3: RouterAI создаёт озвучку…')
                            last_status = time.monotonic()
                        continue
                    if kind == 'error':
                        raise RuntimeError(value)
                    if kind == 'start':
                        expected, generation = value
                    elif kind == 'data':
                        received += len(value)
                        if received > MAX_AUDIO_BYTES:
                            raise RuntimeError('Ответ RouterAI превышает допустимый размер аудио.')
                        output.write(value)
                        progress(.1 + .65 * min(1., received / expected) if expected else None,
                                 'Получаем готовую озвучку…')
                    elif kind == 'done':
                        break
            if not received or (expected and received != expected):
                raise RuntimeError('Аудио RouterAI получено не полностью. Автоматического повтора нет.')
            return generation
        finally:
            stopped.set()
            response = self.active_response
            if response is not None:
                # urllib3 may be holding its read lock in the reader thread.
                # Closing there must not block the UI until the socket timeout.
                threading.Thread(target=self._close_response, args=(response,),
                                 name='RouterAI-close', daemon=True).start()
            self.active_stop = None

    @staticmethod
    def _close_response(response):
        try:
            response.close()
        except (OSError, requests.RequestException):
            pass

    def _ffmpeg(self, arguments, cancel):
        process = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error', '-y',
                                    *arguments], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden())
        deadline = time.monotonic() + 120
        try:
            while process.poll() is None:
                _check(cancel)
                if time.monotonic() > deadline:
                    raise TimeoutError('Превышено время обработки аудио.')
                time.sleep(.08)
            if process.returncode:
                raise RuntimeError('Не удалось прочитать или сохранить аудио RouterAI. Автоматического повтора нет.')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)

    def clip(self, reference, text, transcript, seed, target,
             progress=lambda *args: None, cancel=lambda: None, sample_rate=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 6000:
            raise ValueError('Введите текст от 1 до 6000 символов.')
        self.load(progress)
        _check(cancel)
        fish = _fish_options(self.config)
        # Clear the envelope's generic voice alias at the native-provider layer;
        # the selected avatar is defined by its inline recording, not 'alloy'.
        fish.update(reference_id=None, references=[self._voice(reference, transcript)], seed=int(seed) % (2 ** 64),
                    format='mp3', sample_rate=44100, mp3_bitrate=192)
        # Keep directed speech and paired tags intact. Fish performs its own
        # native chunking instead of splitting a <whisper> scope in the client.
        payload = dict(model=self.model, input=text, voice='alloy', response_format='mp3',
                       provider={'options': {'fish-audio': fish}})
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        downloaded = target.with_name(target.stem + '.' + token + '.download')
        temporary = target.with_name(target.stem + '.' + token + '.partial.wav')
        rate = int(sample_rate or 44100)
        if rate not in (24000, 44100, 48000):
            raise ValueError('Неподдерживаемая частота выходного аудио.')
        signature = hashlib.sha256(json.dumps(dict(
            backend=self.identity, payload=payload, sample_rate=rate),
            ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')).hexdigest()
        report_path = target.with_suffix('.cleanup.json')
        cached = store.load_json(report_path, {})
        if target.is_file() and cached.get('request_signature') == signature:
            if cached.get('audio_sha256') == hashlib.sha256(target.read_bytes()).hexdigest():
                info = sf.info(target)
                if info.frames > 0 and info.samplerate == rate and info.channels == 1:
                    _check(cancel)
                    progress(1, 'Готовая реплика восстановлена из кэша')
                    return str(target)
        try:
            generation = self._download(payload, downloaded, progress, cancel)
            progress(.82, 'Проверяем аудио и подготавливаем частоту дискретизации…')
            self._ffmpeg(['-i', str(downloaded), '-map', '0:a:0', '-vn', '-ar', str(rate), '-ac', '1',
                          '-c:a', 'pcm_s24le', str(temporary)], cancel)
            audio, actual_rate = sf.read(temporary, dtype='float32')
            if (actual_rate != rate or audio.ndim != 1 or not len(audio)
                    or not np.isfinite(audio).all() or np.max(np.abs(audio)) < .00001):
                raise RuntimeError('RouterAI вернул пустую или некорректную запись.')
            _check(cancel)
            temporary.replace(target)
            store.atomic_json(report_path, dict(
                model=tts_settings.MODEL_ID, api_model=self.model, provider='RouterAI',
                generation_id=generation, text=text, seed=int(seed), sample_rate=rate,
                native_sample_rate=44100, trimmed_ms=0, needs_review=False,
                duration_seconds=len(audio) / rate, api_request_attempts=1,
                speech_backend=self.identity, request_signature=signature,
                audio_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
            progress(1, 'Реплика готова')
            return str(target)
        finally:
            downloaded.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)

    def synthesize_book_clip(self, reference, text, transcript, seed, target, narrator_style=None,
                             progress=lambda *args: None, cancel=lambda: None, performance=None):
        # Preserve the selected narrator timbre; no generic style prompt is added.
        return self.clip(reference, text, transcript, seed, target, progress, cancel, sample_rate=24000)

    def synthesize(self, reference, text, reference_text='', start=0, duration=15,
                   seed=42, progress=lambda *args: None):
        if not isinstance(text, str) or not text.strip() or len(text) > 6000:
            raise ValueError('Введите текст от 1 до 6000 символов.')
        if not reference_text.strip():
            self.transcribe_reference(reference)
        from voice_reference import prepare_reference
        folder = store.DATA / 'generations' / ('routerai_' + uuid.uuid4().hex)
        folder.mkdir(parents=True)
        sample = prepare_reference(reference, folder, start, duration)
        wav, mp3, metadata = folder / 'speech.wav', folder / 'speech.mp3', folder / 'generation.json'
        self.clip(sample, text, reference_text, seed, wav, progress, lambda: None, sample_rate=44100)
        progress(.98, 'Сохраняем MP3…')
        temporary = folder / 'speech.partial.mp3'
        try:
            self._ffmpeg(['-i', str(wav), '-codec:a', 'libmp3lame', '-b:a', '192k', str(temporary)], None)
            _check()
            temporary.replace(mp3)
        finally:
            temporary.unlink(missing_ok=True)
        report = store.load_json(wav.with_suffix('.cleanup.json'), {})
        store.atomic_json(metadata, dict(model=tts_settings.MODEL_ID, provider='RouterAI',
            api_model=self.model, text=text, reference_text=reference_text.strip(),
            duration_seconds=sf.info(wav).duration, sample_rate=44100, seed=seed,
            fragments=[report], needs_review=report.get('needs_review', False)))
        progress(1, 'Готово')
        return str(mp3), str(wav), str(metadata), reference_text.strip()
