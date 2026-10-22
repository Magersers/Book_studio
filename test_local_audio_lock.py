"""Real OS-lock contention without downloading models or starting inference."""
import errno
import hashlib
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import avatar_store as store
import local_audio_runtime as runtime
from routerai_engine import Cancelled


HOLDER = r'''
import os, sys
from pathlib import Path
with Path(sys.argv[1]).open('a+b') as stream:
    stream.seek(0, 2)
    if not stream.tell():
        stream.write(b'0'); stream.flush()
    stream.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print('locked', flush=True)
    sys.stdin.readline()
'''


class LocalAudioLockTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for change in (patch.object(runtime, 'root', return_value=self.root),
                       patch.object(store, 'ROOT', self.root)):
            change.start()
            self.addCleanup(change.stop)

    def holder(self, name='generation.lock'):
        process = subprocess.Popen([sys.executable, '-u', '-c', HOLDER, str(self.root / name)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, **runtime.hidden())
        def cleanup():
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        self.addCleanup(cleanup)
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
        self.assertEqual(ready.get(timeout=5).strip(), 'locked')
        return process

    @staticmethod
    def release(process):
        process.stdin.write('\n')
        process.stdin.flush()
        process.wait(timeout=5)

    def ready_runtime(self):
        constraints = self.root / 'requirements-audio.txt'
        constraints.write_text('test constraints', encoding='utf-8')
        source = self.root / 'inference' / 'comfy' / 'sd.py'
        source.parent.mkdir(parents=True)
        source.touch()
        executable = runtime.python_path()
        executable.parent.mkdir(parents=True)
        executable.touch()
        store.atomic_json(self.root / 'runtime.json',
                          dict(source=runtime.SOURCE_REVISION,
                               constraints=hashlib.sha256(constraints.read_bytes()).hexdigest()))

    def test_waits_for_other_process_and_reports_waiting_before_entry(self):
        holder = self.holder()
        progress = []
        def report(value, message):
            progress.append((value, message))
            self.release(holder)
        with runtime._lock('generation.lock', report, timeout=3):
            self.assertEqual(holder.poll(), 0)
        self.assertTrue(progress)
        self.assertIsNone(progress[0][0])
        self.assertIn('Ожидаем завершения подготовки или генерации', progress[0][1])
        self.assertIn('отменить', progress[0][1])

    def test_wait_cancels_promptly_without_terminating_other_owner(self):
        holder = self.holder()
        waiting = []
        def cancel():
            if waiting:
                raise Cancelled('cancel wait')
        started = time.monotonic()
        with self.assertRaises(Cancelled):
            with runtime._lock('generation.lock', lambda *event: waiting.append(event), cancel, timeout=3):
                self.fail('Entered a lock held by another process')
        self.assertLess(time.monotonic() - started, 1.)
        self.assertIsNone(holder.poll())
        self.release(holder)
        with runtime._lock('generation.lock', timeout=.1):
            pass

    def test_wait_has_finite_timeout_without_touching_other_owner(self):
        holder = self.holder()
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, 'Истекло время ожидания'):
            with runtime._lock('generation.lock', timeout=.15):
                self.fail('Entered a lock held by another process')
        self.assertLess(time.monotonic() - started, 1.)
        self.assertIsNone(holder.poll())

    def test_crashed_owner_leaves_file_but_no_stale_lock(self):
        holder = self.holder()
        holder.terminate()
        holder.wait(timeout=5)
        self.assertTrue((self.root / 'generation.lock').is_file())
        with runtime._lock('generation.lock', timeout=.1):
            pass

    def test_cancel_just_after_acquiring_releases_os_lock(self):
        calls = []
        def cancel():
            calls.append(None)
            if len(calls) == 3:
                raise Cancelled('cancel after acquisition')
        with self.assertRaises(Cancelled):
            with runtime._lock('generation.lock', cancel=cancel, timeout=.1):
                self.fail('Cancellation should happen before entering the body')
        with runtime._lock('generation.lock', timeout=.1):
            pass

    def test_non_contention_os_error_is_not_retried_as_busy(self):
        target = 'msvcrt.locking' if os.name == 'nt' else 'fcntl.flock'
        with patch(target, side_effect=OSError(errno.EIO, 'test I/O failure')) as lock:
            with self.assertRaises(OSError) as error:
                with runtime._lock('generation.lock', timeout=.1):
                    self.fail('I/O error should propagate')
        self.assertEqual(error.exception.errno, errno.EIO)
        self.assertEqual(lock.call_count, 1)

    def test_prepare_waits_for_generation_then_completes_without_reinstall(self):
        self.ready_runtime()
        holder = self.holder()
        events = []
        def progress(value, message):
            events.append(message)
            if holder.poll() is None:
                self.release(holder)
        with patch.object(runtime, '_download') as download, patch.object(runtime, '_command') as command:
            result = runtime.prepare(progress)
        self.assertTrue(result['ready'])
        self.assertIn('Ожидаем', events[0])
        self.assertEqual(download.call_count, len(runtime.WEIGHTS))
        command.assert_not_called()

    def test_prepare_cancel_on_second_lock_releases_first_lock(self):
        holder = self.holder('prepare.lock')
        waiting = []
        def cancel():
            if waiting:
                raise Cancelled('cancel preparation wait')
        with self.assertRaises(Cancelled), patch.object(runtime, '_download') as download:
            runtime.prepare(lambda *event: waiting.append(event), cancel)
        self.assertIn('подготовки локальной модели', waiting[0][1])
        download.assert_not_called()
        self.assertIsNone(holder.poll())
        with runtime._lock('generation.lock', timeout=.1):
            pass

    def test_pipeline_start_waits_after_prepare_and_close_releases_lock(self):
        holder = self.holder()
        pipeline = runtime.Pipeline()
        self.addCleanup(pipeline.close)
        process = MagicMock()
        process.poll.return_value = None
        process.stdout.__iter__.return_value = iter(())
        events = []
        def progress(value, message):
            events.append(message)
            self.release(holder)
        with patch.object(runtime, 'prepare') as prepare, \
                patch.object(runtime.subprocess, 'Popen', return_value=process), \
                patch('tts_settings.settings', return_value={}):
            pipeline._start(progress, lambda: None)
        prepare.assert_called_once()
        self.assertIn('Ожидаем', events[0])
        self.assertIsNotNone(pipeline.lock)
        pipeline.close()
        with runtime._lock('generation.lock', timeout=.1):
            pass


if __name__ == '__main__':
    unittest.main()
