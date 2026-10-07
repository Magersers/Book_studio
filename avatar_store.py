"""Portable, atomic local storage; no model imports in the GUI process."""
import json
import os
import shutil
import uuid
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('VOX_DATA_DIR', str(ROOT / 'data')))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('w', encoding='utf-8') as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    # Windows readers / antivirus can briefly prevent atomic replacement.
    for attempt in range(10):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(.02 * (attempt + 1))


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def avatars():
    entries = []
    for path in (DATA / 'avatars').glob('*/avatar.json'):
        item = load_json(path, {})
        if item and not item.get('archived'):
            entries.append(item)
    return sorted(entries, key=lambda x: x.get('created', ''))


def get_avatar(avatar_id):
    if not isinstance(avatar_id, str) or not avatar_id.isalnum():
        raise ValueError('Некорректный аватар.')
    item = load_json(DATA / 'avatars' / avatar_id / 'avatar.json', None)
    if not item or item.get('archived'):
        raise ValueError('Аватар не найден.')
    return item


def avatar_path(item, filename='reference.wav'):
    return DATA / 'avatars' / item['id'] / filename


def save_profile(name, reference, transcript, duration, picture='', avatar_id=None):
    name = name.strip()
    if not 1 <= len(name) <= 60:
        raise ValueError('Имя аватара должно содержать от 1 до 60 символов.')
    old = get_avatar(avatar_id) if avatar_id else {}
    avatar_id = old.get('id', uuid.uuid4().hex)
    folder = DATA / 'avatars' / avatar_id
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / 'reference.wav'
    if Path(reference).resolve() != destination.resolve():
        temp_audio = folder / 'reference.new.wav'
        shutil.copyfile(reference, temp_audio)
        temp_audio.replace(destination)
    if picture:
        from PIL import Image, ImageOps
        with Image.open(picture) as image:
            image = ImageOps.exif_transpose(image).convert('RGB')
            image = ImageOps.fit(image, (512, 512))
            image.save(folder / 'portrait.new.png')
        (folder / 'portrait.new.png').replace(folder / 'portrait.png')
    item = dict(id=avatar_id, name=name, transcript=transcript.strip(), duration=float(duration),
                created=old.get('created', datetime.now().isoformat(timespec='seconds')),
                updated=datetime.now().isoformat(timespec='seconds'), archived=False)
    atomic_json(folder / 'avatar.json', item)
    return item


def archive_profile(avatar_id):
    item = get_avatar(avatar_id)
    item['archived'] = True
    atomic_json(DATA / 'avatars' / avatar_id / 'avatar.json', item)


def history():
    return load_json(DATA / 'history.json', [])


def add_history(avatar, text, mp3, wav, metadata):
    report = load_json(metadata, {})
    entry = dict(id=uuid.uuid4().hex, avatar_id=avatar['id'], avatar_name=avatar['name'], text=text,
                 needs_review=bool(report.get('needs_review')),missing_text=report.get('missing_text',[]),
                 mp3=mp3, wav=wav, metadata=metadata, duration=report.get('duration_seconds', 0),
                 created=datetime.now().isoformat(timespec='seconds'))
    atomic_json(DATA / 'history.json', [entry] + history())
    return entry


def bootstrap_previous_voices():
    marker = DATA / '.imported_previous_voices'
    if marker.exists():
        return
    prior = ROOT / 'outputs/user_20260930_150554'
    if (prior / 'reference_15s.wav').exists() and (prior / 'reference_transcript.txt').exists():
        save_profile('Энергичный', prior / 'reference_15s.wav',
                     (prior / 'reference_transcript.txt').read_text(encoding='utf-8'), 15)
    desired = load_json(ROOT / 'outputs/night_monologue.json', {})
    if desired:
        for report in (ROOT / 'outputs').glob('qwen_*/generation.json'):
            if load_json(report, {}).get('text') == desired.get('text') and (report.parent / 'reference.wav').exists():
                save_profile('Рассказчик', report.parent / 'reference.wav', desired['reference_text'], 15)
                break
    DATA.mkdir(parents=True, exist_ok=True)
    marker.write_text('Imported voice samples only; originals preserved.', encoding='utf-8')
