"""Local UI language; book text and model prompts are never translated."""
import json,os
from pathlib import Path
import avatar_store as store
ROOT=Path(__file__).resolve().parent
_language=None
_english=None
def language():
    global _language
    if _language is None:_language=os.environ.get('VOX_UI_LANGUAGE') or store.load_json(store.DATA/'ui-preferences.json',{}).get('language','ru')
    return _language
def save_language(value):
    if value not in ('ru','en'):raise ValueError('Unknown language')
    store.atomic_json(store.DATA/'ui-preferences.json',dict(language=value))
def tr(text):
    global _english
    if language()!='en':return text
    if _english is None:_english=json.loads((ROOT/'locales/en.json').read_text(encoding='utf-8'))
    return _english.get(text,text)
