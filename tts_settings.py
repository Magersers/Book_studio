"""User-selected speech backend. SSH identities stay on the local computer."""
import re
import shlex
from pathlib import Path
from urllib.parse import urlsplit, unquote

import avatar_store as store

MODEL_ID = 'drama3-fp8-20261017-v1'


def path():
    return store.DATA / 'tts-settings.json'


def settings():
    value = store.load_json(path(), {})
    return dict(mode=value.get('mode', 'local'), connection=value.get('connection', ''),
                identity_file=value.get('identity_file', ''),
                music_enabled=value.get('music_enabled') is True)


def parse_connection(value, identity_file=''):
    """Accept an SSH command or URI, never a shell expression or arbitrary -o options."""
    value = value.strip()
    if not value or any(c in value for c in '\r\n\x00'):
        raise ValueError('Введите SSH-подключение к серверу.')
    user, host, port = 'root', '', 22
    if value.startswith('ssh://'):
        parsed = urlsplit(value)
        if parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('SSH-ссылка не должна содержать пароль, путь или параметры.')
        try:
            host = parsed.hostname or ''
            port = 22 if parsed.port is None else parsed.port
        except ValueError as exc:
            raise ValueError('Некорректный SSH-порт.') from exc
        user = unquote(parsed.username or 'root')
    else:
        lexer = shlex.shlex(value, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ''
        lexer.escape = ''  # Preserve Windows paths inside -i "...".
        try:
            tokens = list(lexer)
        except ValueError as exc:
            raise ValueError('Проверьте кавычки в SSH-подключении.') from exc
        if tokens and tokens[0] in ('ssh', 'ssh.exe'):
            tokens.pop(0)
        target = None
        while tokens:
            token = tokens.pop(0)
            if token in ('-p', '-i', '-l'):
                if not tokens:
                    raise ValueError('После SSH-параметра нужно значение.')
                option, argument = token, tokens.pop(0)
            elif token.startswith(('-p', '-i', '-l')) and len(token) > 2:
                option, argument = token[:2], token[2:]
            elif token.startswith('-'):
                raise ValueError('Поддерживаются только SSH-параметры -p, -i и -l.')
            else:
                if target is not None:
                    raise ValueError('Введите только SSH-адрес, без удалённой команды.')
                target = token
                continue
            if option == '-p':
                try:
                    port = int(argument)
                except ValueError as exc:
                    raise ValueError('SSH-порт должен быть числом.') from exc
            elif option == '-i':
                identity_file = identity_file or argument
            else:
                user = argument
        if not target:
            raise ValueError('В SSH-подключении не указан сервер.')
        if '@' in target:
            user, host = target.rsplit('@', 1)
        else:
            host = target
        if host.startswith('[') and host.endswith(']'):
            host = host[1:-1]
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', user):
        raise ValueError('Некорректное SSH-имя пользователя.')
    if not host or not re.fullmatch(r'[A-Za-z0-9:][A-Za-z0-9.:-]*', host) or host.startswith('-'):
        raise ValueError('Некорректное имя SSH-сервера.')
    if not 1 <= port <= 65535:
        raise ValueError('SSH-порт должен быть от 1 до 65535.')
    identity_file = str(identity_file).strip()
    if any(c in identity_file for c in '\r\n\x00'):
        raise ValueError('Некорректный путь к SSH-ключу.')
    return dict(user=user, host=host.lower(), port=port, identity_file=identity_file)


def save(mode, connection='', identity_file='', music_enabled=None):
    if mode not in ('local', 'remote'):
        raise ValueError('Неизвестный режим озвучки.')
    old = settings()
    if mode == 'remote':
        parsed = parse_connection(connection, identity_file)
        identity_file = parsed['identity_file']
        if identity_file and not Path(identity_file).expanduser().is_file():
            raise ValueError('Файл SSH-ключа не найден.')
        old.update(connection=connection.strip(), identity_file=identity_file)
    old['mode'] = mode
    if music_enabled is not None:
        old['music_enabled'] = bool(music_enabled)
    store.atomic_json(path(), old)


def label():
    from ui_language import tr
    if settings()['mode'] == 'remote':
        return tr('Озвучка: Drama 3 · SSH-сервер')
    return tr('Озвучка: на компьютере')
