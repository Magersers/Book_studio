"""Atomic deployment switch, separate from user profiles and books."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def config():
    path=ROOT/'models/runtime.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(tts='qwen',roles='qwen4')
def tts_id():
    from tts_settings import MODEL_ID, settings
    import hashlib
    preferences=settings()
    identity={key:preferences.get(key) for key in ('base_url','model','fish_options')}
    suffix=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
    return MODEL_ID+':'+suffix
