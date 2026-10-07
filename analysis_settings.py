"""Provider preferences and a Windows DPAPI-protected API key. No model imports."""
import base64,ctypes,json,os,re
from urllib.parse import urlsplit,urlunsplit
import avatar_store as store

DEFAULT_URL='https://api.deepseek.com'
DEFAULT_MODEL='deepseek-flash'
PROVIDERS={
    'deepseek':dict(label='DeepSeek',url=DEFAULT_URL,models=['deepseek-flash','deepseek-v4-pro'],keys='https://platform.deepseek.com/api_keys'),
    'openrouter':dict(label='OpenRouter',url='https://openrouter.ai/api/v1',models=[],keys='https://openrouter.ai/settings/keys'),
    'compatible':dict(label='Custom API (OpenAI-compatible)',url='',models=[],keys=''),
}
def is_remote(provider):return provider in PROVIDERS


def path():return store.DATA/'analysis-api.json'

def settings():
    raw=store.load_json(path(),{})
    return dict(provider=raw.get('provider','local'),base_url=raw.get('base_url',DEFAULT_URL),
                model=raw.get('model',DEFAULT_MODEL),has_key=bool(raw.get('protected_key')))

def normalize_url(value):
    value=value.strip().rstrip('/')
    parsed=urlsplit(value)
    try:port=parsed.port
    except ValueError:raise ValueError('Некорректный порт API.') from None
    if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise ValueError('Укажите HTTPS-адрес API без ключа, параметров и пароля, например https://api.deepseek.com.')
    suffix=parsed.path.rstrip('/')
    if suffix.endswith('/chat/completions'):suffix=suffix[:-len('/chat/completions')]
    if suffix.endswith('/models'):suffix=suffix[:-len('/models')]
    return urlunsplit((parsed.scheme,parsed.netloc.lower(),suffix,'',''))

def validate_model(value):
    value=value.strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}',value):
        raise ValueError('Укажите идентификатор модели, например deepseek-flash.')
    return value

class Blob(ctypes.Structure):
    _fields_=[('size',ctypes.c_ulong),('data',ctypes.POINTER(ctypes.c_ubyte))]

def _crypt(data,protect):
    if os.name!='nt':raise RuntimeError('Защищённое хранение ключа доступно в Windows.')
    source=ctypes.create_string_buffer(data)
    incoming=Blob(len(data),ctypes.cast(source,ctypes.POINTER(ctypes.c_ubyte)));outgoing=Blob()
    dll=ctypes.WinDLL('crypt32',use_last_error=True)
    if protect:
        function=dll.CryptProtectData
        function.argtypes=[ctypes.POINTER(Blob),ctypes.c_wchar_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(Blob)]
        args=(ctypes.byref(incoming),'Vox Studio API key',None,None,None,1,ctypes.byref(outgoing))
    else:
        function=dll.CryptUnprotectData
        function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(Blob)]
        args=(ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(outgoing))
    function.restype=ctypes.c_int
    if not function(*args):raise RuntimeError('Windows не смогла обработать сохранённый ключ. Введите ключ заново.')
    try:return ctypes.string_at(outgoing.data,outgoing.size)
    finally:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
        kernel.LocalFree(ctypes.cast(outgoing.data,ctypes.c_void_p))

def api_key(base_url=None):
    raw=store.load_json(path(),{})
    if base_url is not None and normalize_url(base_url)!=raw.get('base_url',DEFAULT_URL):
        raise ValueError('Для нового адреса сервера введите API-ключ заново.')
    if not raw.get('protected_key'):raise ValueError('Введите API-ключ в настройках разметки.')
    try:return _crypt(base64.b64decode(raw['protected_key'],validate=True),False).decode('utf-8')
    except (ValueError,UnicodeError):raise ValueError('Не удалось прочитать ключ. Введите его заново.') from None

def validate_key(value):
    value=value.strip()
    if not value or len(value)>2048 or any(c.isspace() for c in value) or not value.isascii():
        raise ValueError('Вставьте API-ключ без пробелов, а не ссылку на личный кабинет.')
    if value.startswith(('http:','https:')):raise ValueError('В поле ключа нужен API-ключ, а не ссылка.')
    return value

def save(provider,base_url=DEFAULT_URL,model=DEFAULT_MODEL,key=''):
    if provider!='local' and not is_remote(provider):raise ValueError('Неизвестный способ разметки.')
    old=store.load_json(path(),{})
    if provider=='local':
        old['provider']='local';store.atomic_json(path(),old);return
    base_url=normalize_url(base_url);model=validate_model(model)
    if key.strip():protected=base64.b64encode(_crypt(validate_key(key).encode('utf-8'),True)).decode('ascii')
    else:
        api_key(base_url)  # Also verify DPAPI access before enabling the provider.
        protected=old['protected_key']
    store.atomic_json(path(),dict(provider=provider,base_url=base_url,model=model,protected_key=protected))

def label():
    config=settings()
    if is_remote(config['provider']):return PROVIDERS[config['provider']]['label']+' API · '+config['model']
    from runtime_config import config as runtime
    model=runtime().get('roles','qwen4')
    from ui_language import tr
    return tr('Локально · ')+{'qwen9':'Qwen 9B','qwen4':'Qwen 4B','gemma12':'Gemma 12B'}.get(model,model)

def ready():
    config=settings()
    if is_remote(config['provider']):
        normalize_url(config['base_url']);validate_model(config['model']);api_key(config['base_url'])

