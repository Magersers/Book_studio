"""Install the shipped reference voices without replacing a user's library."""
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit
import wave

import avatar_store as store

ROOT = Path(__file__).resolve().parent
MANIFEST = 'assets/voices/manifest.json'
DEFAULT_FOLDER = 'Студийные · RU'


def _text(value, field, maximum, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError(f'Некорректное поле {field} в комплекте голосов.')
    return value.strip()


def _hash(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def read_manifest(root=None):
    """Validate the whole pack before writing anything to the user data folder."""
    root = Path(root or ROOT).resolve()
    manifest = root/MANIFEST
    if not manifest.exists():
        return None
    asset_root = (root/'assets/voices').resolve()
    if not asset_root.is_relative_to(root) or not manifest.resolve().is_relative_to(asset_root):
        raise ValueError('Комплект голосов должен находиться внутри папки приложения.')
    data = json.loads(manifest.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError('Неизвестный формат встроенного комплекта голосов.')
    pack_id = _text(data.get('pack_id'), 'pack_id', 64)
    if not re.fullmatch(r'[a-zA-Z0-9]+', pack_id):
        raise ValueError('Некорректный идентификатор комплекта голосов.')
    voices = data.get('voices')
    if not isinstance(voices, list) or len(voices) > 64:
        raise ValueError('Некорректный список встроенных голосов.')
    validated = []
    identifiers = set()
    for voice in voices:
        if not isinstance(voice, dict):
            raise ValueError('Некорректная запись встроенного голоса.')
        ident = voice.get('id', '')
        if not isinstance(ident, str) or not re.fullmatch(r'[a-zA-Z0-9]{4,64}', ident) or ident in identifiers:
            raise ValueError('Повторяющийся или некорректный идентификатор встроенного голоса.')
        identifiers.add(ident)
        # Only the matching packaged WAV is allowed, including after resolving
        # symlinks. Manifest entries cannot read arbitrary files on the PC.
        expected = f'assets/voices/{ident}.wav'
        if voice.get('file') != expected:
            raise ValueError('Образец должен находиться внутри assets/voices и совпадать с id.')
        path = (root/expected).resolve()
        if not path.is_relative_to(asset_root.resolve()) or not path.is_file():
            raise ValueError('Не найден встроенный образец голоса: '+ident)
        checksum = voice.get('sha256', '')
        if not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum) or _hash(path) != checksum:
            raise ValueError('Нарушена целостность встроенного образца голоса: '+ident)
        try:
            with wave.open(str(path), 'rb') as audio:
                duration = audio.getnframes()/audio.getframerate()
                valid = (audio.getnchannels() == 1 and audio.getframerate() == 24000
                         and audio.getsampwidth() in (2,3) and audio.getcomptype() == 'NONE'
                         and 3 <= duration <= 30)
        except (OSError, EOFError, ZeroDivisionError, wave.Error) as exc:
            raise ValueError('Не удалось прочитать встроенный WAV: '+ident) from exc
        declared = voice.get('duration')
        if not valid or isinstance(declared, bool) or not isinstance(declared, (int,float)) or not math.isfinite(declared) or abs(declared-duration) > .05:
            raise ValueError('Встроенный образец должен быть PCM WAV, 24 кГц mono, от 3 до 30 секунд.')
        source = voice.get('source')
        if not isinstance(source, dict):
            raise ValueError('Нужен источник встроенного образца голоса.')
        source = dict(source)
        url = _text(source.get('url'), 'source.url', 2000)
        parsed = urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('Нужна публичная HTTP-ссылка на источник образца голоса.')
        source['url'] = url
        source['title'] = _text(source.get('title'), 'source.title', 300)
        source['license'] = _text(source.get('license'), 'source.license', 1000)
        gender = voice.get('gender', '')
        if gender not in ('male','female',''):
            raise ValueError('Некорректный gender встроенного голоса.')
        validated.append(dict(id=ident, name=_text(voice.get('name'), 'name', 60),
            transcript=_text(voice.get('transcript'), 'transcript', 4000), duration=duration,
            description=_text(voice.get('description'), 'description', 1000), gender=gender,
            source=source, sha256=checksum, path=path))
    return dict(pack_id=pack_id, voices=validated)


def install(root=None):
    """Seed absent stable IDs on first launch or upgrade; archived IDs stay hidden."""
    pack = read_manifest(root)
    result = dict(installed=[], skipped=[])
    if not pack:
        return result
    avatars = store.DATA/'avatars'
    avatars.mkdir(parents=True, exist_ok=True)
    created = datetime.now().isoformat(timespec='seconds')
    for voice in pack['voices']:
        destination = avatars/voice['id']
        # Never re-enable an archived bundled voice or replace an edited voice,
        # even if its packaged reference or metadata changes in a later release.
        if destination.exists():
            result['skipped'].append(voice['id'])
            continue
        with tempfile.TemporaryDirectory(prefix='.bundled-', dir=avatars) as temporary:
            stage = Path(temporary)
            shutil.copyfile(voice['path'], stage/'reference.wav')
            if _hash(stage/'reference.wav') != voice['sha256']:
                raise ValueError('Изменился встроенный образец при копировании: '+voice['id'])
            item = {key: voice[key] for key in ('id','name','transcript','duration','description','gender','source')}
            item.update(created=created, updated=created, archived=False,
                        bundled_pack=pack['pack_id'], bundled_reference_sha256=voice['sha256'])
            store.atomic_json(stage/'avatar.json', item)
            try:
                # The desktop data lock serializes normal app startup. A second
                # setup process may have installed this stable ID meanwhile.
                if destination.exists():
                    result['skipped'].append(voice['id'])
                    continue
                stage.rename(destination)
            except FileExistsError:
                result['skipped'].append(voice['id'])
                continue
        result['installed'].append(voice['id'])
    if result['installed']:
        import avatar_folders as folders
        data = folders.load()
        group = next((f for f in data['folders'] if not f.get('parent')
                      and f['name'].casefold() == DEFAULT_FOLDER.casefold()), None)
        group_id = group['id'] if group else folders.create(DEFAULT_FOLDER)
        # Only brand-new bundled profiles are moved. Previously installed voices
        # keep any folder or unassigned placement chosen by the user.
        folders.move(result['installed'], group_id)
    return result
