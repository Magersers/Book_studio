import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

import avatar_store as store
import drama3_server_setup as setup
from drama3_text import chunks, frame_budget
from remote_ssh import SSHConnection, Cancelled
import tts_settings as settings


class SettingsTests(unittest.TestCase):
    def test_command_uri_and_windows_key(self):
        key = str(Path('key folder')/'id_ed25519')
        result = settings.parse_connection(f'ssh root@gpu.example -p 1234 -i "{key}"')
        self.assertEqual(result, dict(user='root', host='gpu.example', port=1234, identity_file=key))
        self.assertEqual(settings.parse_connection('ssh://alice@[::1]:2222')['host'], '::1')
        self.assertEqual(settings.parse_connection('ssh -p1234 -l alice gpu.example')['user'], 'alice')

    def test_reject_shell_commands_options_and_passwords(self):
        for value in ('ssh host whoami', 'ssh host;whoami', 'ssh -o ProxyCommand=bad host',
                      'ssh://root:secret@host', 'ssh host -p 0', 'ssh host -p 70000',
                      'ssh host\nwhoami', 'ssh host && whoami', 'ssh://host/path', 'ssh://user@host:0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings.parse_connection(value)

    def test_settings_switch_changes_audio_cache_identity(self):
        import runtime_config
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            local = runtime_config.tts_id()
            settings.save('remote', 'ssh user@gpu.example -p 2222')
            self.assertEqual(runtime_config.tts_id(), settings.MODEL_ID)
            self.assertNotEqual(local, runtime_config.tts_id())
            settings.save('local')
            self.assertEqual(settings.settings()['connection'], 'ssh user@gpu.example -p 2222')

    def test_music_preference_defaults_off_and_survives_mode_switch(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            self.assertFalse(settings.settings()['music_enabled'])
            settings.save('remote', 'ssh gpu.example', music_enabled=True)
            settings.save('local')
            self.assertTrue(settings.settings()['music_enabled'])
            settings.save('remote', 'ssh gpu.example', music_enabled=False)
            self.assertFalse(settings.settings()['music_enabled'])

    def test_prepare_music_is_explicit_and_unready_server_is_not_forwarded(self):
        connection = SSHConnection(dict(connection='ssh gpu.example'))
        self.addCleanup(connection.close)
        with patch.object(connection, 'run_program', return_value=dict(ready=True, port=8188)) as run, \
             patch.object(connection, 'forward') as forward:
            connection.prepare(music=True)
            self.assertEqual(run.call_args.args[0], ['--probe', '--music'])
            connection.prepare(install=True, music=True)
            options = run.call_args.args[0]
            self.assertEqual((options[0], options[-1]), ('--install', '--music'))
            self.assertEqual(len(options[1]), 32)
            connection.prepare()
            self.assertEqual(run.call_args.args[0], ['--probe'])
            forward.assert_called_with(8188, None)
        with patch.object(connection, 'run_program', return_value=dict(ready=False, message='Сервер занят')), \
             patch.object(connection, 'forward') as forward:
            with self.assertRaisesRegex(RuntimeError, 'Сервер занят'):
                connection.prepare(install=True)
            forward.assert_not_called()

    def test_host_keys_are_pinned_and_ssh_is_an_argument_list(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            connection = SSHConnection(dict(connection='ssh user@gpu.example -p 2222'))
            args = connection.arguments()
            self.assertIn('StrictHostKeyChecking=accept-new', args)
            self.assertIn('BatchMode=yes', args)
            self.assertNotIn('StrictHostKeyChecking=no', args)
            self.assertEqual(connection.destination(), 'user@gpu.example')
            connection.close()

    def test_fast_exit_does_not_lose_final_json_line(self):
        original = subprocess.Popen
        def launch(*args, **kwargs):
            return original([sys.executable, '-c', 'import sys; sys.stdin.buffer.read(); '
                'print(\'{"book_studio":1,"type":"result","ready":true}\')'], **kwargs)
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            connection = SSHConnection(dict(connection='ssh gpu.example'))
            with patch('remote_ssh.subprocess.Popen', side_effect=launch):
                for _ in range(3):
                    self.assertTrue(connection.run_program(['--probe'], timeout=10)['ready'])
            connection.close()

    def test_install_receipt_exists_before_ssh_and_survives_unknown_failure(self):
        import remote_jobs
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            connection = SSHConnection(dict(connection='ssh gpu.example -p 2222'))
            self.addCleanup(connection.close)
            def fail(*args, **kwargs):
                receipts = list(remote_jobs.directory().glob('*.json'))
                self.assertEqual(len(receipts), 1)
                receipt = store.load_json(receipts[0], {})
                self.assertEqual(receipt['job_id'], 'a'*32)
                self.assertEqual(receipt['connection']['port'], 2222)
                raise OSError('SSH start failed')
            with patch('remote_ssh.subprocess.Popen', side_effect=fail):
                with self.assertRaisesRegex(OSError, 'SSH start failed'):
                    connection.run_program(['--install', 'a'*32])
            self.assertEqual(len(list(remote_jobs.directory().glob('*.json'))), 1)

    def test_install_cancelled_before_launch_never_starts_ssh_or_leaves_receipt(self):
        import remote_jobs
        cancel = threading.Event(); cancel.set()
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            connection = SSHConnection(dict(connection='ssh gpu.example'))
            self.addCleanup(connection.close)
            with patch('remote_ssh.subprocess.Popen') as launch:
                with self.assertRaises(Cancelled):
                    connection.run_program(['--install', 'a'*32], cancel=cancel)
                launch.assert_not_called()
            self.assertFalse(list(remote_jobs.directory().glob('*.json')))

    def test_completed_install_removes_its_durable_receipt(self):
        import remote_jobs
        original = subprocess.Popen
        def launch(*args, **kwargs):
            return original([sys.executable, '-c', 'import sys; sys.stdin.buffer.read(); '
                'print(\'{"book_studio":1,"type":"result","ready":true}\')'], **kwargs)
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            connection = SSHConnection(dict(connection='ssh gpu.example'))
            self.addCleanup(connection.close)
            with patch('remote_ssh.subprocess.Popen', side_effect=launch):
                self.assertTrue(connection.run_program(['--install', 'a'*32], timeout=10)['ready'])
            self.assertFalse(list(remote_jobs.directory().glob('*.json')))

    def test_cancel_install_failure_is_not_reported_as_success(self):
        connection = SSHConnection(dict(connection='ssh gpu.example'))
        self.addCleanup(connection.close)
        with patch.object(connection, 'run_program', side_effect=OSError('offline')):
            with self.assertRaisesRegex(RuntimeError, 'Установка могла продолжиться'):
                connection._cancel_install('a'*32)
        with patch.object(connection, 'run_program', return_value=dict(cancel_requested=False)):
            with self.assertRaisesRegex(RuntimeError, 'Сервер не подтвердил'):
                connection._cancel_install('a'*32)
        with patch.object(connection, 'run_program', return_value=dict(cancel_requested=True)) as run:
            connection._cancel_install('a'*32)
            run.assert_called_once_with(['--cancel', 'a'*32], timeout=20)

    def test_cues_are_atomic_and_budget_is_bounded(self):
        text = '[laughing, delighted] ' + 'Серьёзно? ' * 150
        pieces = list(chunks(text, 90))
        self.assertEqual(' '.join(pieces), text.strip())
        self.assertTrue(pieces[0].startswith('[laughing, delighted]'))
        self.assertTrue(all(len(piece) <= 90 for piece in pieces))
        self.assertLessEqual(frame_budget(text*100), 2600)


class ProbeTests(unittest.TestCase):
    @staticmethod
    def info(music=True):
        info = {name: {} for name in setup.REQUIRED}
        for node, key, filename in [('Drama3Loader', 'model_name', setup.MODEL),
                                    ('Drama3CodecLoader', 'codec_name', setup.CODEC),
                                    ('Qwen3ASRLoader', 'model_name', setup.ASR)]:
            info[node] = dict(input=dict(required={key: [[filename]]}))
        if music:
            info.update({name: {} for name in setup.MUSIC_REQUIRED})
            info['CLIPLoader'] = dict(input=dict(required={
                'clip_name': ['COMBO', dict(options=[setup.MUSIC_ENCODER])],
                'type': [['stable_audio']]}))
            info['CheckpointLoaderSimple'] = dict(input=dict(required={
                'ckpt_name': [[setup.MUSIC_MODEL]]}))
        return info

    @staticmethod
    def api(info):
        return lambda port, route: info if route == '/object_info' else dict(system=dict(comfyui_version='0.42.0'))

    def test_missing_listener_is_the_only_absence(self):
        with patch.object(setup, 'port_listening', return_value=False), patch.object(setup, 'api') as api:
            self.assertEqual(setup.probe()['status'], 'absent')
            api.assert_not_called()
        with patch.object(setup.socket, 'create_connection', side_effect=TimeoutError):
            self.assertIsNone(setup.port_listening(8188))
        with patch.object(setup.socket, 'create_connection', side_effect=ConnectionRefusedError):
            self.assertIs(setup.port_listening(8188), False)

    def test_slow_comfy_is_busy_instead_of_absent(self):
        with patch.object(setup, 'port_listening', return_value=True), \
             patch.object(setup, 'api', side_effect=TimeoutError('busy decoding')):
            result = setup.probe(music=True)
            self.assertFalse(result['ready'])
            self.assertEqual(result['status'], 'busy')
            self.assertIn('занят генерацией', result['message'])

    def test_starting_comfy_before_listener_opens_is_not_absent(self):
        for arguments, port in ((['python', 'main.py'], 8188),
                                (['python', 'main.py', '--port', '8187'], 8187),
                                (['python', 'main.py', '--port=8187'], 8187)):
            with self.subTest(arguments=arguments), \
                 patch.object(setup, 'comfy_processes', return_value=[(None, None, arguments)]), \
                 patch.object(setup, 'port_listening', return_value=False), patch.object(setup, 'api') as api:
                self.assertEqual(setup.inspect_port(port)['status'], 'busy')
                other = 8187 if port == 8188 else 8188
                self.assertEqual(setup.inspect_port(other)['status'], 'absent')
                api.assert_not_called()

    def test_existing_native_music_models_are_ready_without_custom_nodes(self):
        with patch.object(setup, 'port_listening', return_value=True), \
             patch.object(setup, 'api', side_effect=self.api(self.info())):
            result = setup.probe(music=True)
            self.assertTrue(result['ready'])
            self.assertTrue(result['music_ready'])

    def test_music_missing_is_distinct_from_absent_and_disabled_music_needs_no_nodes(self):
        info = self.info()
        info['CLIPLoader']['input']['required']['clip_name'] = [[]]
        with patch.object(setup, 'port_listening', return_value=True), \
             patch.object(setup, 'api', side_effect=self.api(info)):
            self.assertEqual(setup.probe(music=True)['status'], 'music_missing')
            self.assertTrue(setup.probe()['ready'])
        with patch.object(setup, 'port_listening', return_value=True), \
             patch.object(setup, 'api', side_effect=self.api(self.info(music=False))):
            self.assertTrue(setup.probe()['ready'])
            self.assertEqual(setup.probe(music=True)['status'], 'incompatible')

    def test_busy_install_waits_then_reuses_without_touching_software(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(setup, 'ROOT', Path(temp)), \
             patch.object(setup, 'report'), patch.object(setup.time, 'sleep'):
            installer = setup.Installer('a'*32)
            busy = dict(ready=False, status='busy', message='busy')
            ready = dict(ready=True, port=8188)
            with patch.object(setup, 'probe', side_effect=[busy, ready]), \
                 patch.object(installer, 'source', side_effect=AssertionError('second runtime')), \
                 patch.object(installer, 'download', side_effect=AssertionError('duplicate weights')):
                self.assertEqual(installer._install(), ready)

    def test_busy_timeout_and_incompatible_server_never_start_another_runtime(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(setup, 'ROOT', Path(temp)), \
             patch.object(setup, 'report'):
            installer = setup.Installer('a'*32)
            with patch.object(setup, 'probe', return_value=dict(ready=False, status='busy', message='busy')), \
                 patch.object(setup.time, 'monotonic', side_effect=[0, 181]), \
                 patch.object(installer, 'source') as source:
                with self.assertRaisesRegex(TimeoutError, 'busy'):
                    installer._install(music=True)
                source.assert_not_called()
            with patch.object(setup, 'probe', return_value=dict(ready=False, status='incompatible', message='old version')), \
                 patch.object(installer, 'source') as source:
                with self.assertRaisesRegex(RuntimeError, 'old version'):
                    installer._install()
                source.assert_not_called()

    def test_busy_wait_is_cancellable(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(setup, 'ROOT', Path(temp)), \
             patch.object(setup, 'report'), patch.object(setup.time, 'sleep'):
            installer = setup.Installer('a'*32)
            def busy(**kwargs):
                installer.cancel_path.touch()
                return dict(ready=False, status='busy', message='busy')
            with patch.object(setup, 'probe', side_effect=busy):
                with self.assertRaises(InterruptedError):
                    installer._install()

    def test_music_is_added_only_to_the_existing_runtime_with_pinned_urls(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(setup, 'ROOT', Path(temp)/'managed'), \
             patch.object(setup, 'report'):
            installer = setup.Installer('a'*32)
            comfy = Path(temp)/'existing-comfy'
            comfy.mkdir()
            missing = dict(ready=False, port=8188, status='music_missing')
            ready = dict(ready=True, port=8188, music_ready=True)
            with patch.object(setup, 'probe', side_effect=[missing, ready]), \
                 patch.object(setup, 'running_comfy_directory', return_value=comfy), \
                 patch.object(setup.shutil, 'disk_usage', return_value=MagicMock(free=20*1024**3)), \
                 patch.object(installer, 'download') as download, \
                 patch.object(installer, 'source', side_effect=AssertionError('duplicate source')), \
                 patch.object(installer, 'command', side_effect=AssertionError('extra package install')):
                self.assertEqual(installer._install(music=True), ready)
                self.assertEqual(download.call_count, 2)
                for call, weight in zip(download.call_args_list, setup.MUSIC_WEIGHTS):
                    kind, name, repo, revision, size, digest = weight
                    self.assertEqual(call.args, (f'https://huggingface.co/{repo}/resolve/{revision}/{kind}/{name}',
                        comfy/'models'/kind/name, size, digest))

    def test_music_ready_reuses_models_without_reading_or_downloading_them(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(setup, 'ROOT', Path(temp)), \
             patch.object(setup, 'report'):
            installer = setup.Installer('a'*32)
            with patch.object(setup, 'probe', return_value=dict(ready=True, port=8188, music_ready=True)), \
                 patch.object(installer, 'download') as download, \
                 patch.object(setup, 'running_comfy_directory') as directory:
                self.assertTrue(installer._install(music=True)['music_ready'])
                download.assert_not_called()
                directory.assert_not_called()

    def test_music_cli_flag_reaches_probe(self):
        with patch.object(sys, 'argv', ['setup', '--probe', '--music']), \
             patch.object(setup, 'probe', return_value=dict(ready=True)) as probe, \
             patch.object(setup, 'emit'):
            self.assertEqual(setup.main(), 0)
            probe.assert_called_once_with(music=True)

    def test_music_space_counts_partial_downloads_without_negative_sizes(self):
        with tempfile.TemporaryDirectory() as temp:
            comfy = Path(temp)
            weight = ('checkpoints', 'small', 'repo', 'revision', 100, '0'*64)
            partial = comfy/'models/checkpoints/small.part'
            partial.parent.mkdir(parents=True)
            partial.write_bytes(b'x'*40)
            self.assertEqual(setup.missing_bytes(comfy, [weight]), 60)
            partial.write_bytes(b'x'*140)
            self.assertEqual(setup.missing_bytes(comfy, [weight]), 100)


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = b'original FP8 bytes' * 1000
        cls.ranges = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                requested = self.headers.get('Range')
                cls.ranges.append(requested)
                start = int(requested.split('=')[1].split('-')[0]) if requested else 0
                resume = self.path == '/range' and requested
                self.send_response(206 if resume else 200)
                if resume:
                    self.send_header('Content-Range', f'bytes {start}-{len(cls.payload)-1}/{len(cls.payload)}')
                self.end_headers()
                self.wfile.write(cls.payload[start:] if resume else cls.payload)
            def log_message(self, *args):
                pass
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_range_resume_full_response_restart_and_verified_cache(self):
        for route in ('range', 'full'):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as temp, patch.object(setup, 'ROOT', Path(temp)):
                installer = setup.Installer('a'*32)
                target = Path(temp)/'model.safetensors'
                target.with_suffix('.safetensors.part').write_bytes(self.payload[:123])
                url = f'http://127.0.0.1:{self.server.server_port}/{route}'
                digest = hashlib.sha256(self.payload).hexdigest()
                with patch.object(setup, 'report'):
                    installer.download(url, target, len(self.payload), digest)
                    self.assertEqual(target.read_bytes(), self.payload)
                    with patch.object(setup.urllib.request, 'urlopen', side_effect=AssertionError('redownload')):
                        installer.download(url, target, len(self.payload), digest)

    def test_hash_failure_is_not_committed_and_cancel_keeps_partial(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(setup, 'ROOT', Path(temp)), patch.object(setup, 'report'):
            installer = setup.Installer('a'*32)
            target = Path(temp)/'model'
            url = f'http://127.0.0.1:{self.server.server_port}/full'
            with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
                installer.download(url, target, len(self.payload), '0'*64)
            self.assertFalse(target.exists())
            partial = target.with_suffix('.part')
            partial.write_bytes(self.payload[:123])
            installer.cancel_path.touch()
            with self.assertRaises(InterruptedError):
                installer.download(url, target, len(self.payload), hashlib.sha256(self.payload).hexdigest())
            self.assertEqual(partial.stat().st_size, 123)

    def test_existing_runtime_reused_without_installing(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(setup, 'ROOT', Path(temp)), patch.object(setup, 'report'):
            installer = setup.Installer('a'*32)
            with patch.object(setup, 'probe', return_value=dict(ready=True, port=8188)), \
                 patch.object(installer, 'command', side_effect=AssertionError('modified server')):
                self.assertEqual(installer._install()['port'], 8188)

    def test_cancel_marker_survives_before_runtime_directory_exists(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(setup, 'ROOT', Path(temp)/'new-runtime'), \
             patch.object(sys, 'argv', ['setup', '--cancel', 'a'*32]), patch.object(setup, 'emit') as emit:
            self.assertEqual(setup.main(), 0)
            self.assertTrue((setup.ROOT/('cancel-'+'a'*32)).is_file())
            emit.assert_called_once_with('result', cancel_requested=True)
            installer = setup.Installer('a'*32)
            with self.assertRaises(InterruptedError):
                installer.check()

    def test_corrupt_final_file_is_removed_so_next_attempt_can_download(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(setup, 'ROOT', Path(temp)), patch.object(setup, 'report'):
            installer = setup.Installer('a'*32)
            target = Path(temp)/'model'
            target.write_bytes(b'x'*len(self.payload))
            digest = hashlib.sha256(self.payload).hexdigest()
            url = f'http://127.0.0.1:{self.server.server_port}/full'
            with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
                installer.download(url, target, len(self.payload), digest)
            self.assertFalse(target.exists())
            installer.download(url, target, len(self.payload), digest)
            self.assertEqual(target.read_bytes(), self.payload)

    def test_installed_runtime_restart_does_not_require_fresh_dependency_space(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(setup, 'ROOT', Path(temp)), patch.object(setup, 'report'):
            installer = setup.Installer('a'*32)
            python = Path(temp)/'venv/bin/python'
            python.parent.mkdir(parents=True)
            python.touch()
            (Path(temp)/'dependencies-ready').touch()
            original = Path.read_text
            def read_text(path, *args, **kwargs):
                if str(path).replace('\\', '/') == '/proc/meminfo':
                    return 'MemTotal: 67108864 kB'
                if str(path).replace('\\', '/') == '/sys/fs/cgroup/memory.max':
                    return 'max'
                return original(path, *args, **kwargs)
            class ReachedSource(Exception):
                pass
            disk = MagicMock(free=1024**3)
            with patch.object(setup, 'probe', return_value=dict(ready=False)), \
                 patch.object(setup, 'WEIGHTS', []), patch.object(Path, 'read_text', read_text), \
                 patch.object(setup.subprocess, 'check_output', return_value='24576,595.99\n'), \
                 patch.object(setup.shutil, 'disk_usage', return_value=disk), \
                 patch.object(installer, 'source', side_effect=ReachedSource):
                with self.assertRaises(ReachedSource):
                    installer._install()

    def test_drama_book_chunks_keep_emotion_controls_atomic(self):
        import book_engine as books
        from narrator_profiles import VERSION
        text = 'Он молча шёл по тёмному коридору '*5 + '[whispering, frightened] Здесь кто-то есть. Он замер.'
        with patch('runtime_config.tts_id', return_value=settings.MODEL_ID):
            plan = books.segment_plan(dict(text=text, speaker='', parts='[]'),
                dict(title='Другая глава', avatar='voice', mode='roles'), {},
                dict(default_avatar='voice', narrator_profiles=VERSION))
        self.assertTrue(all(part['text'].count('[')==part['text'].count(']') for part in plan))
        self.assertIn('[whispering, frightened]', ' '.join(part['text'] for part in plan))


class EngineTests(unittest.TestCase):
    def setUp(self):
        import drama3_engine as engine
        self.engine = engine
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        change = patch.object(store, 'DATA', Path(self.temp.name))
        change.start()
        self.addCleanup(change.stop)
        self.pipeline = engine.Pipeline(dict(connection='ssh gpu.example'))
        self.pipeline.url = 'http://127.0.0.1:12345'
        self.addCleanup(self.pipeline.close)

    def test_original_sampler_and_inline_emotions(self):
        prompt = self.engine.graph('reference.wav', '[angry] Нет! [laughing] Шучу.', 'Пример.', 42, 'job')
        request = prompt['6']['inputs']
        self.assertEqual(request['text'], '[angry] Нет! [laughing] Шучу.')
        self.assertEqual((request['temperature'], request['top_p'], request['top_k']), (1., .9, 0))
        self.assertEqual(request['voices.voice0'], ['5', 0])

    def test_cancellation_is_scoped_to_owned_prompt(self):
        pipeline = self.pipeline
        pipeline.http = MagicMock()
        pipeline.http.post.return_value.json.return_value = {'prompt_id': 'my-job'}
        pipeline.http.post.return_value.ok = True
        def cancel_after_submission():
            if pipeline.pending:
                raise Cancelled('test cancelled')
        with patch.object(pipeline, 'load'), patch.object(self.engine.websocket, 'create_connection', side_effect=OSError):
            with self.assertRaises(Cancelled):
                pipeline.execute({}, cancel=cancel_after_submission)
        urls = [call.args[0] for call in pipeline.http.post.call_args_list]
        self.assertEqual(urls, [pipeline.url+'/prompt', pipeline.url+'/api/jobs/my-job/cancel'])
        self.assertIsNone(pipeline.pending)

    def test_websocket_failure_falls_back_to_history(self):
        pipeline = self.pipeline
        pipeline.http = MagicMock()
        pipeline.http.post.return_value.ok = True
        pipeline.http.post.return_value.json.return_value = {'prompt_id': 'job'}
        pipeline.http.get.return_value.json.return_value = {'job': dict(status=dict(completed=True), outputs={'8': {'audio': []}})}
        with patch.object(pipeline, 'load'), patch.object(self.engine.websocket, 'create_connection', side_effect=OSError):
            self.assertIn('8', pipeline.execute({}))

    def test_websocket_handshake_allows_ssh_latency_but_receives_are_cancellable(self):
        pipeline = self.pipeline
        pipeline.http = MagicMock()
        pipeline.http.post.return_value.ok = True
        pipeline.http.post.return_value.json.return_value = {'prompt_id': 'job'}
        pipeline.http.get.return_value.json.return_value = {'job': dict(status=dict(completed=True), outputs={})}
        socket = MagicMock()
        with patch.object(pipeline, 'load'), patch.object(self.engine.websocket, 'create_connection', return_value=socket) as connect:
            pipeline.execute({})
        self.assertEqual(connect.call_args.kwargs['timeout'], 10)
        socket.settimeout.assert_called_once_with(.4)
        socket.close.assert_called_once()

    def test_download_validates_audio_and_does_not_trust_output_path(self):
        import numpy as np
        import soundfile as sf
        output = io.BytesIO()
        sf.write(output, .1*np.sin(np.arange(44100)*.1), 44100, format='WAV')
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {'Content-Length': str(len(output.getvalue()))}
        response.iter_content.return_value = [output.getvalue()]
        self.pipeline.http = MagicMock()
        self.pipeline.http.get.return_value = response
        target = Path(self.temp.name)/'expected.wav'
        audio, sr = self.pipeline.download_audio(dict(filename='../../outside.wav', subfolder='', type='output'), target,
                                                 lambda *args: None, lambda: None)
        self.assertEqual((len(audio), sr), (44100, 44100))
        self.assertFalse(target.with_suffix('.download').exists())


if __name__ == '__main__':
    unittest.main()
