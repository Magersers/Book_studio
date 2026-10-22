"""Durable receipts for this application's Comfy jobs, never the global queue.

The submit lock spans POST /prompt. A parent cancelling a killed worker waits
for that POST before cancelling its preassigned ID, closing the submit race.
OS advisory locks are released automatically if the worker crashes.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
import uuid

import requests
import avatar_store as store


def directory():
    path = store.DATA / 'ssh' / 'owned-jobs'
    path.mkdir(parents=True, exist_ok=True)
    return path


def ticket_path(ticket):
    if not isinstance(ticket, str) or not ticket.isalnum():
        raise ValueError('Некорректный идентификатор локального задания.')
    return directory() / (ticket + '.json')


@contextmanager
def locked(ticket, timeout=40):
    path = ticket_path(ticket).with_suffix('.lock')
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b'0'); stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise TimeoutError('Не завершилась отправка задания на сервер; отмена не подтверждена.')
                time.sleep(.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def register(url, connection, remote_port=None):
    ticket = uuid.uuid4().hex
    value = dict(version=1, ticket=ticket, prompt_id=str(uuid.uuid4()), url=url,
                 connection=dict(connection), remote_port=remote_port,
                 owner_pid=os.getpid(), created=time.time(), phase='submitting', type='generation')
    store.atomic_json(ticket_path(ticket), value)
    return value


def register_install(connection, job_id):
    if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        raise ValueError('Некорректный идентификатор установки.')
    ticket = uuid.uuid4().hex
    value = dict(version=1, type='install', ticket=ticket, job_id=job_id, prompt_id=job_id,
                 connection=dict(connection), owner_pid=os.getpid(), created=time.time(), phase='installing')
    store.atomic_json(ticket_path(ticket), value)
    return value


def update(ticket, **fields):
    value = store.load_json(ticket_path(ticket), None)
    if value is not None:
        value.update(fields)
        store.atomic_json(ticket_path(ticket), value)


def finish(ticket):
    ticket_path(ticket).unlink(missing_ok=True)


def cancel_at(session, url, prompt_id):
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.path:
        raise ValueError('Недопустимый адрес локального SSH-туннеля.')
    # UUIDs are normal; older compatible servers can return simple job IDs.
    if not prompt_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in prompt_id):
        raise ValueError('Некорректный идентификатор серверного задания.')
    response = session.post(url + '/api/jobs/' + prompt_id + '/cancel', json={}, timeout=10)
    response.raise_for_status()


def cancel_owned(owner_pid=None):
    """Bounded blocking helper: run in a GUI background thread before killing.

    Returns [{prompt_id, confirmed, error?}]. Unconfirmed receipts are retained
    for another attempt. A receipt survives lost POST responses and tunnel loss.
    Installer receipts use only the scoped bootstrap --cancel operation.
    No install/probe or global interrupt is invoked here.
    """
    (store.DATA / 'ssh').mkdir(parents=True, exist_ok=True)
    (store.DATA / 'ssh' / 'cancel-speech').touch()
    results = []
    with requests.Session() as session:
        session.trust_env = False
        for path in sorted(directory().glob('*.json')):
            receipt = store.load_json(path, None)
            if not receipt or (owner_pid is not None and receipt.get('owner_pid') != owner_pid):
                continue
            ticket = receipt['ticket']
            try:
                with locked(ticket):
                    receipt = store.load_json(path, None)
                    if receipt is None:
                        continue  # The worker already confirmed completion/cancellation.
                    if receipt.get('type') == 'install':
                        from remote_ssh import SSHConnection
                        config = receipt['connection']
                        host = config['host']
                        target = f"{config['user']}@" + (f'[{host}]' if ':' in host else host)
                        ssh = SSHConnection(dict(connection=f"ssh {target} -p {config['port']}",
                                                 identity_file=config.get('identity_file', '')))
                        try:
                            ssh._cancel_install(receipt['job_id'])
                        finally:
                            ssh.close()
                        finish(ticket)
                        results.append(dict(prompt_id=receipt['job_id'], confirmed=True))
                        continue
                    try:
                        cancel_at(session, receipt['url'], receipt['prompt_id'])
                    except requests.RequestException:
                        # The worker may have lost or closed its original tunnel.
                        from remote_ssh import SSHConnection
                        config = receipt['connection']
                        host = config['host']
                        target = f"{config['user']}@" + (f'[{host}]' if ':' in host else host)
                        if not isinstance(receipt.get('remote_port'), int):
                            raise RuntimeError('Исходный SSH-туннель закрыт; порт сервиса неизвестен.')
                        ssh = SSHConnection(dict(connection=f"ssh {target} -p {config['port']}",
                                                 identity_file=config.get('identity_file', '')))
                        try:
                            ssh.forward(receipt['remote_port'])
                            cancel_at(session, ssh.url, receipt['prompt_id'])
                        finally:
                            ssh.close()
                    finish(ticket)
                    results.append(dict(prompt_id=receipt['prompt_id'], confirmed=True))
            except Exception as exc:
                results.append(dict(prompt_id=receipt.get('prompt_id', ''), confirmed=False, error=str(exc)))
    return results
