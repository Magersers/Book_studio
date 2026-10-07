"""Atomic deployment switch, separate from user profiles and books."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def config():
    path=ROOT/'models/runtime.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(tts='qwen',roles='qwen4')
def tts_id():return 'higgs-tts-3-4b-q8-v1' if config().get('tts')=='higgs' else 'qwen-book-v1'
