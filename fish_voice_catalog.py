"""Install a searchable snapshot of public Russian Fish Audio voices.

Only public metadata is bundled. Synthesis uses the provider's real voice ID;
no remote sample is downloaded or passed off as a local cloning reference.
"""
from datetime import datetime
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

import avatar_store as store

ROOT = Path(__file__).resolve().parent
MANIFEST = 'assets/voices/fish-audio-ru.json'
FOLDER = 'Fish Audio · RU'


def _string(value, maximum=8000):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError('Некорректная строка в каталоге Fish Audio.')
    return value.strip()


def _strings(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError('Некорректный список тегов или языков Fish Audio.')
    return [_string(item, 300) for item in value]


def _url(value, hosts=None):
    value = _string(value, 4000)
    if not value:
        return ''
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or (hosts and parsed.hostname not in hosts)):
        raise ValueError('Некорректная публичная ссылка Fish Audio.')
    return value


def read_manifest(root=None):
    path = Path(root or ROOT) / MANIFEST
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('voices'), list):
        raise ValueError('Неизвестный формат каталога Fish Audio.')
    voices = []
    seen = set()
    for raw in data['voices']:
        if not isinstance(raw, dict):
            raise ValueError('Некорректный голос в каталоге Fish Audio.')
        ident = raw.get('id')
        if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident) or ident in seen:
            raise ValueError('Повторяющийся или некорректный ID Fish Audio.')
        seen.add(ident)
        name = _string(raw.get('name'), 1000)
        if not name:
            raise ValueError('В каталоге Fish Audio отсутствует имя голоса.')
        voice = dict(id=ident, name=name,
                     description=_string(raw.get('description', '')),
                     gender=_string(raw.get('gender', ''), 100),
                     age=_string(raw.get('age', ''), 100),
                     author=_string(raw.get('author', ''), 300),
                     languages=_strings(raw.get('languages', [])),
                     tags=_strings(raw.get('tags', [])),
                     source_url=_url(raw.get('source_url', 'https://fish.audio/m/' + ident), {'fish.audio', 'www.fish.audio'}),
                     sample_url=_url(raw.get('sample_url', '')))
        for field in ('rank', 'task_count'):
            value = raw.get(field, 0)
            if type(value) is not int or value < 0:
                raise ValueError('Некорректная популярность голоса Fish Audio.')
            voice[field] = value
        voice['licensed'] = raw.get('licensed') is True
        # The scraper must explicitly identify the catalog as Russian. Empty
        # metadata is allowed when Fish's Russian filter returned the record.
        if voice['languages'] and not any(code.casefold() in ('ru', 'rus', 'russian', 'русский') for code in voice['languages']):
            raise ValueError('В русский каталог попал голос с другим языком: ' + ident)
        voices.append(voice)
    return dict(voices=voices, fetched_at=_string(data.get('fetched_at', ''), 100))


def category(voice):
    """Use declared metadata only; never guess gender from the speaker's name."""
    gender = voice.get('gender', '').casefold()
    gender_folder = {'male': 'Мужские', 'female': 'Женские', 'мужской': 'Мужские',
                     'женский': 'Женские'}.get(gender, 'Пол не указан')
    text = ' '.join([voice.get('name', ''), voice.get('description', ''), *voice.get('tags', [])]).casefold()
    age = voice.get('age', '').casefold()
    if age in ('child', 'kid', 'children', 'детский'):
        use = 'Детские'
    elif any(word in text for word in ('narrat', 'voiceover', 'voice-over', 'audiobook', 'рассказчик', 'диктор', 'закадров', 'аудиокниг')):
        use = 'Рассказчики и дикторы'
    elif any(word in text for word in ('character', 'anime', 'cartoon', 'персонаж', 'аниме', 'мульт', 'game', 'игров')):
        use = 'Персонажи'
    elif age in ('old', 'elder', 'elderly', 'пожилой', 'пожилая'):
        use = 'Пожилые'
    elif age in ('young', 'teen', 'teenager', 'молодой', 'молодая'):
        use = 'Молодые'
    else:
        use = 'Другие'
    return (FOLDER, gender_folder, use)


def install(root=None):
    """Add absent catalog IDs; retain edits, archives and folder moves on upgrade."""
    pack = read_manifest(root)
    result = dict(installed=[], skipped=[])
    if pack is None:
        return result
    import avatar_folders as folders
    folder_data = folders.load()
    original_folders = json.dumps(folder_data, ensure_ascii=False, sort_keys=True)

    def folder_path(names):
        parent = ''
        for name in names:
            existing = next((f for f in folder_data['folders'] if f.get('parent', '') == parent
                             and f['name'].casefold() == name.casefold()), None)
            if not existing:
                import uuid
                existing = dict(id=uuid.uuid4().hex, name=name, parent=parent)
                folder_data['folders'].append(existing)
            parent = existing['id']
        return parent

    avatars = store.DATA / 'avatars'
    created = datetime.now().isoformat(timespec='seconds')
    for voice in pack['voices']:
        ident = 'fish' + voice['id']
        destination = avatars / ident
        if destination.exists():
            result['skipped'].append(ident)
            continue
        avatars.mkdir(parents=True, exist_ok=True)
        item = {key: value for key, value in voice.items() if key != 'id'}
        item.update(id=ident, fish_voice_id=voice['id'], voice_provider='fish-audio',
                    duration=0, transcript='', created=created, updated=created, archived=False,
                    catalog='fish-audio-ru', catalog_fetched_at=pack['fetched_at'])
        with tempfile.TemporaryDirectory(prefix='.fish-catalog-', dir=avatars) as temporary:
            stage = Path(temporary)
            store.atomic_json(stage / 'avatar.json', item)
            try:
                stage.rename(destination)
            except FileExistsError:
                result['skipped'].append(ident)
                continue
        result['installed'].append(ident)
        # Assign only freshly imported voices. An existing user assignment,
        # including a move to the root, must never be reset by an upgrade.
        folder_data['assignments'][ident] = folder_path(category(voice))
    if json.dumps(folder_data, ensure_ascii=False, sort_keys=True) != original_folders:
        folders.save(folder_data)
    return result
