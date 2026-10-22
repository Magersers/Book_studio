"""OpenSSH transport: argument lists, local-only forwarding and pinned host keys."""
import atexit
import json
import os
import queue
import shutil
import socket
import subprocess
import threading
import time
import uuid
import tempfile
from pathlib import Path

import avatar_store as store
from tts_settings import parse_connection


class Cancelled(RuntimeError):
    pass


def hidden():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


class SSHConnection:
    def __init__(self, config):
        self.config = parse_connection(config['connection'], config.get('identity_file', ''))
        self.tunnel = None
        self.tunnel_log = None
        self.url = None
        atexit.register(self.close)

    def arguments(self):
        executable = shutil.which('ssh')
        if not executable and os.name == 'nt':
            candidate = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'System32/OpenSSH/ssh.exe'
            if candidate.is_file():
                executable = str(candidate)
        if not executable:
            raise RuntimeError('Не найден OpenSSH Client. Установите его в дополнительных компонентах Windows.')
        (store.DATA / 'ssh').mkdir(parents=True, exist_ok=True)
        known = (store.DATA / 'ssh/known_hosts').resolve().as_posix()
        system_known = (Path.home() / '.ssh/known_hosts').as_posix()
        args = [executable, '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
                '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
                '-o', 'StrictHostKeyChecking=accept-new',
                '-o', f'UserKnownHostsFile="{known}" "{system_known}"',
                '-p', str(self.config['port'])]
        identity = self.config['identity_file']
        if identity:
            args += ['-i', str(Path(identity).expanduser())]
        return args

    def destination(self):
        host = self.config['host']
        return self.config['user'] + '@' + (f'[{host}]' if ':' in host else host)

    def _cancel_install(self, job_id):
        try:
            result = self.run_program(['--cancel', job_id], timeout=20)
            if result.get('cancel_requested') is not True:
                raise RuntimeError('Сервер не подтвердил запрос отмены.')
        except Exception as exc:
            raise RuntimeError('Не удалось подтвердить запрос отмены установки на сервере. '
                               'Установка могла продолжиться. Идентификатор: ' + job_id + '\n' + str(exc)) from exc

    def run_program(self, options, progress=lambda event: None, cancel=None, timeout=7200):
        script = Path(__file__).with_name('drama3_server_setup.py').read_bytes()
        install_ticket = None
        if '--install' in options:
            from remote_jobs import register_install, finish
            job_id = options[options.index('--install') + 1]
            install_ticket = register_install(self.config, job_id)['ticket']
            # The GUI marks cancellation before enumerating receipts. If its
            # snapshot preceded this receipt, do not launch a late installer.
            if cancel and cancel.is_set():
                finish(install_ticket)
                raise Cancelled('Установка отменена до запуска SSH.')
        process = subprocess.Popen(self.arguments() + [self.destination(), 'python3', '-u', '-', *options],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **hidden())
        messages = queue.Queue()

        def read(stream, channel):
            try:
                for line in iter(stream.readline, b''):
                    messages.put((channel, line.decode('utf-8', errors='replace').rstrip()))
            finally:
                stream.close()
                messages.put((channel, None))

        for stream, channel in ((process.stdout, 'out'), (process.stderr, 'err')):
            threading.Thread(target=read, args=(stream, channel), daemon=True).start()
        # A writer thread also lets cancellation work while an SSH handshake is pending.
        def write():
            try:
                process.stdin.write(script)
                process.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass
        threading.Thread(target=write, daemon=True).start()
        errors, result, streams_done = [], None, 0
        deadline = time.monotonic() + timeout
        try:
            while streams_done < 2 or process.poll() is None:
                if cancel and cancel.is_set():
                    if '--install' in options:
                        self._cancel_install(options[options.index('--install') + 1])
                        finish(install_ticket)
                    raise Cancelled('Операция отменена. Частично скачанные модели сохранены для продолжения.')
                if time.monotonic() > deadline:
                    if '--install' in options:
                        self._cancel_install(options[options.index('--install') + 1])
                        finish(install_ticket)
                    raise TimeoutError('Истекло время ожидания SSH-сервера.')
                try:
                    channel, line = messages.get(timeout=.15)
                except queue.Empty:
                    continue
                if line is None:
                    streams_done += 1
                    continue
                try:
                    event = json.loads(line) if channel == 'out' else None
                except ValueError:
                    event = None
                if isinstance(event, dict) and event.get('book_studio') == 1:
                    if event.get('type') == 'result':
                        result = event
                    elif event.get('type') == 'error':
                        errors.append(event.get('message', 'Ошибка сервера'))
                    else:
                        progress(event)
                elif line:
                    errors.append(line)
                    errors = errors[-20:]
            process.wait(timeout=5)
            if process.returncode or not result:
                detail = '\n'.join(errors[-8:])[-2000:]
                raise RuntimeError('SSH-сервер не готов. Проверьте адрес, ключ и ssh-agent.\n' + detail)
            if install_ticket:
                finish(install_ticket)
            return result
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)

    def prepare(self, progress=lambda event: None, cancel=None, install=False, music=False):
        job = uuid.uuid4().hex
        options = ['--install', job] if install else ['--probe']
        if music:
            options.append('--music')
        result = self.run_program(options, progress, cancel)
        if not result.get('ready'):
            raise RuntimeError(result.get('message') or
                'Drama 3 ещё не установлена. Нажмите «Установить / обновить окружение».')
        self.forward(result['port'], cancel)
        return result

    def forward(self, remote_port, cancel=None):
        if not isinstance(remote_port, int) or not 1 <= remote_port <= 65535:
            raise RuntimeError('Сервер сообщил некорректный порт.')
        self.close()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.tunnel_log = tempfile.TemporaryFile(mode='w+', encoding='utf-8')
        self.tunnel = subprocess.Popen(self.arguments() + ['-N', '-o', 'ExitOnForwardFailure=yes',
            '-L', f'127.0.0.1:{port}:127.0.0.1:{remote_port}', self.destination()],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self.tunnel_log, **hidden())
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if cancel and cancel.is_set():
                self.close()
                raise Cancelled('Подключение отменено.')
            if self.tunnel.poll() is not None:
                self.tunnel_log.seek(0)
                detail = self.tunnel_log.read()[-1600:]
                self.close()
                raise RuntimeError('Не удалось открыть SSH-туннель.\n' + detail)
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.3):
                    self.url = f'http://127.0.0.1:{port}'
                    return
            except OSError:
                time.sleep(.1)
        self.close()
        raise TimeoutError('SSH-туннель не открылся за 25 секунд.')

    def close(self):
        if self.tunnel:
            process, self.tunnel = self.tunnel, None
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        if self.tunnel_log:
            self.tunnel_log.close()
            self.tunnel_log = None
        self.url = None
