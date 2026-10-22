"""RouterAI speech preferences and a Windows-protected API key."""
import base64
import json
import os
import re
from urllib.parse import urlsplit, urlunsplit

import avatar_store as store

DEFAULT_URL = 'https://routerai.ru/api/v1'
DEFAULT_MODEL = 'fish-audio/drama-3'
MODEL_ID = 'routerai:fish-audio/drama-3:voice-id-v2'


def path():
    return store.DATA / 'tts-settings.json'


def settings():
    value = store.load_json(path(), {})
    # Older local/SSH preferences are deliberately not returned or reused.
    return dict(mode='api', base_url=value.get('base_url', DEFAULT_URL),
                model=DEFAULT_MODEL, has_key=bool(value.get('protected_key') or os.environ.get('ROUTERAI_API_KEY')),
                music_enabled=value.get('music_enabled') is True,
                sound_generation_enabled=value.get('sound_generation_enabled') is True,
                local_audio_device=value.get('local_audio_device', 'auto') if value.get('local_audio_device', 'auto') in ('auto', 'cuda', 'cpu') else 'auto',
                local_audio_offload=True,
                fish_options=value.get('fish_options', {}),
                api_workers=validate_api_workers(value.get('api_workers', 3)))


def normalize_url(value):
    value = str(value).strip().rstrip('/')
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError:
        raise ValueError('Некорректный порт API.') from None
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise ValueError('Укажите HTTPS-адрес API без ключа и параметров.')
    suffix = parsed.path.rstrip('/')
    for ending in ('/audio/speech', '/models'):
        if suffix.endswith(ending):
            suffix = suffix[:-len(ending)]
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), suffix, '', ''))


def validate_model(value):
    if str(value).strip() != DEFAULT_MODEL:
        raise ValueError('Для озвучки используется fish-audio/drama-3.')
    return DEFAULT_MODEL


def validate_key(value):
    value = str(value).strip()
    if (not value or len(value) > 2048 or any(not 33 <= ord(c) <= 126 for c in value)
            or value.startswith(('http:', 'https:'))):
        raise ValueError('Вставьте API-ключ RouterAI без пробелов, а не ссылку.')
    return value


def validate_voice_id(value):
    value = str(value).strip()
    if not re.fullmatch(r'[a-fA-F0-9]{32}', value):
        raise ValueError('Fish Audio ID должен состоять из 32 символов: цифры и латинские буквы a–f. '
                         'Скопируйте его из ссылки fish.audio/m/<ID>.')
    return value.lower()


def validate_api_workers(value):
    if type(value) is not int or not 1 <= value <= 8:
        raise ValueError('Число параллельных запросов должно быть целым от 1 до 8.')
    return value


def validate_fish_options(value):
    if isinstance(value, str):
        if len(value) > 32768:
            raise ValueError('Параметры Fish Audio должны быть короче 32 КБ.')
        try:
            value = json.loads(value.strip() or '{}')
        except (ValueError, RecursionError):
            raise ValueError('Параметры Fish Audio должны быть корректным JSON-объектом.') from None
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError('Параметры Fish Audio должны быть JSON-объектом.')
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError('Параметры Fish Audio содержат неподдерживаемое значение.') from None
    if len(encoded.encode('utf-8')) > 32768:
        raise ValueError('Параметры Fish Audio должны быть короче 32 КБ.')
    reserved = {'api_key', 'authorization', 'headers', 'text', 'input', 'model', 'voice',
                'format', 'sample_rate', 'references', 'reference_id', 'mp3_bitrate',
                'base_url', 'url', 'provider', 'seed'}
    if any(str(key).lower() in reserved for key in value):
        raise ValueError('Голос, образец и формат задаёт программа; API-ключ вводится в отдельное поле.')
    return json.loads(encoded)


def api_key(base_url=None):
    value = store.load_json(path(), {})
    selected = normalize_url(base_url or value.get('base_url', DEFAULT_URL))
    saved_url = normalize_url(value.get('base_url', DEFAULT_URL))
    if value.get('protected_key'):
        if selected != saved_url:
            raise ValueError('Для нового адреса API введите ключ заново.')
        from analysis_settings import _crypt
        try:
            return validate_key(_crypt(base64.b64decode(value['protected_key'], validate=True), False).decode('utf-8'))
        except (ValueError, UnicodeError):
            raise ValueError('Не удалось прочитать ключ RouterAI. Введите его заново.') from None
    # Environment keys are only sent to RouterAI's standard endpoint.
    if selected == DEFAULT_URL and os.environ.get('ROUTERAI_API_KEY'):
        return validate_key(os.environ['ROUTERAI_API_KEY'])
    raise ValueError('Введите API-ключ RouterAI в настройках озвучки.')


def save(mode='api', *, base_url=None, model=DEFAULT_MODEL, key='', music_enabled=None,
         sound_generation_enabled=None, fish_options=None, local_audio_device=None, api_workers=None):
    if mode != 'api':
        raise ValueError('Озвучка работает через RouterAI API.')
    old = store.load_json(path(), {})
    base_url = normalize_url(base_url or old.get('base_url', DEFAULT_URL))
    model = validate_model(model)
    options = validate_fish_options(old.get('fish_options', {}) if fish_options is None else fish_options)
    workers = validate_api_workers(old.get('api_workers', 3) if api_workers is None else api_workers)
    device = local_audio_device or old.get('local_audio_device', 'auto')
    if device not in ('auto', 'cuda', 'cpu'):
        raise ValueError('Выберите GPU или CPU для локальной модели звука.')
    protected = old.get('protected_key', '')
    if key.strip():
        from analysis_settings import _crypt
        protected = base64.b64encode(_crypt(validate_key(key).encode('utf-8'), True)).decode('ascii')
    elif protected:
        if normalize_url(old.get('base_url', DEFAULT_URL)) != base_url:
            raise ValueError('Для нового адреса API введите ключ заново.')
    value = dict(mode='api', base_url=base_url, model=model, fish_options=options,
                 music_enabled=old.get('music_enabled') is True if music_enabled is None else bool(music_enabled),
                 sound_generation_enabled=old.get('sound_generation_enabled') is True if sound_generation_enabled is None else bool(sound_generation_enabled),
                 local_audio_device=device, local_audio_offload=True, api_workers=workers)
    if protected:
        value['protected_key'] = protected
    store.atomic_json(path(), value)


def ready():
    value = settings()
    normalize_url(value['base_url'])
    validate_model(value['model'])
    validate_fish_options(value['fish_options'])
    api_key(value['base_url'])


def label():
    from ui_language import tr
    return tr('Озвучка: Drama 3 · RouterAI API')
