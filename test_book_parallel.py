"""Concurrent paid-call boundaries, ordered output and durable recovery offline."""
from concurrent.futures import ThreadPoolExecutor
import io
import gc
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

import avatar_store as store
import book_engine as books
import book_parallel
import book_state as state
import routerai_engine as router


VOICE = '7312c38557eb4fb384e3874e8e9cea67'


class FakePipeline:
    uses_voice_ids = True
    supports_parallel_book = True
    supports_progress = True

    def __init__(self, workers=3, owner=None):
        self.config = dict(api_workers=workers)
        self.owner = owner or self
        self.closed = False
        self.busy = False
        if owner is None:
            self.lock = threading.Lock()
            self.active = self.peak = 0
            self.started = [];self.finished = [];self.children = []
            self.hook = lambda index, cancel: None
            self.after_write = lambda index: None
            self.cancelled = threading.Event()

    def check_book_cancel(self):
        if self.owner.cancelled.is_set():
            raise router.Cancelled('cancel test')

    def fork_book_pipeline(self):
        child = FakePipeline(self.config['api_workers'], self)
        self.children.append(child)
        return child

    def close(self):
        self.closed = True

    def synthesize_book_clip(self, reference, text, transcript, seed, target, **options):
        owner = self.owner
        index = int(re.search(r'\d+', text)[0])
        with owner.lock:
            if self.busy:
                raise AssertionError('Shared Pipeline used concurrently')
            self.busy = True
            owner.active += 1;owner.peak = max(owner.peak, owner.active)
            owner.started.append(index)
        try:
            owner.hook(index, options.get('cancel', lambda: None))
            if 'progress' in options:
                options['progress'](.5, f'Реплика {index}')
            sf.write(target, np.sin(np.arange(3600) * (.03 + index / 1000)) * .15, 24000)
            store.atomic_json(Path(target).with_suffix('.cleanup.json'), dict(needs_review=index == 2))
            with owner.lock:
                owner.finished.append(index)
            owner.after_write(index)
            return str(target)
        finally:
            with owner.lock:
                owner.active -= 1;self.busy = False


class BookParallelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for change in (patch.object(store, 'DATA', self.root),
                       patch.object(books, 'BOOKS', self.root / 'books'),
                       patch('tts_settings.settings', return_value=dict(mode='api', music_enabled=False))):
            change.start();self.addCleanup(change.stop)
        self.voice = store.save_fish_profile('Автор', VOICE)
        source = self.root / 'chapter.txt';source.write_text('Глава 1\n\nТекст.', encoding='utf-8')
        books.import_book(source, 'book', lambda *a: None);state.migrate('book')
        with books.connect('book') as db:
            db.execute('DELETE FROM segments')
            for index in range(1, 7):
                db.execute('INSERT INTO segments(id,chapter,text,analyzed) VALUES(?,1,?,1)',
                           (index, f'Реплика номер {index}.'))
        state.update('book', default_avatar=self.voice['id'], analysis_complete=True)
        self.addCleanup(gc.collect)

    def saved_ids(self):
        with books.connect('book') as db:
            return [r['id'] for r in db.execute("SELECT id FROM segments WHERE signature!='' AND wav!='' ORDER BY id")]

    def test_bounded_overlap_ordered_assembly_main_thread_publication_and_cache_reuse(self):
        pipeline = FakePipeline(3)
        rendezvous = threading.Barrier(3)
        finished_third = threading.Event()
        def hook(index, cancel):
            if index <= 3:
                rendezvous.wait(timeout=3)
                if index != 3:
                    self.assertTrue(finished_third.wait(3))
        pipeline.hook = hook
        pipeline.after_write = lambda index: finished_third.set() if index == 3 else None
        coordinator = threading.get_ident()
        progress_threads = [];assembly_threads = [];assemblies = [];stages = []
        original = books.assemble_chapter_segments
        def assemble(*args, **kwargs):
            assembly_threads.append(threading.get_ident())
            assemblies.append([row['id'] for row in args[1]])
            return original(*args, **kwargs)
        def prepare(*args, **kwargs):
            self.assertEqual(pipeline.active, 0);self.assertFalse(pipeline.started)
            stages.append(('effects', threading.get_ident()));return books.metadata('book')
        def music(book_id, chapter_id, dry, timing, *args):
            self.assertEqual(pipeline.active, 0)
            self.assertEqual([r['segment_id'] for r in timing], list(range(1, 7)))
            stages.append(('music', threading.get_ident()));return str(dry)
        state.update('book', music_enabled=True, sound_generation_enabled=True)
        with patch('book_engine.assemble_chapter_segments', side_effect=assemble), \
                patch('book_sounds.prepare', side_effect=prepare), \
                patch('music_planner.ensure_book_plan', return_value=dict(cues=[])), \
                patch('music_engine.render_book', side_effect=music):
            output = books.render('book', pipeline, lambda *a: progress_threads.append(threading.get_ident()))
        self.assertTrue(Path(output).is_file())
        self.assertEqual(pipeline.peak, 3)
        self.assertEqual(pipeline.finished[0], 3)
        self.assertEqual(sorted(pipeline.started), list(range(1, 7)))
        self.assertEqual(self.saved_ids(), list(range(1, 7)))
        self.assertEqual(assemblies[-1], list(range(1, 7)))
        self.assertEqual(set(progress_threads + assembly_threads), {coordinator})
        self.assertEqual(stages, [('effects', coordinator), ('music', coordinator)])
        self.assertTrue(all(child.closed for child in pipeline.children))
        with books.connect('book') as db:
            self.assertEqual(db.execute('SELECT audio_review FROM segments WHERE id=2').fetchone()[0], 1)
        # A different number of HTTP workers is not an audio/cache identity change.
        state.update('book', music_enabled=False, sound_generation_enabled=False)
        resumed = FakePipeline(4)
        books.render('book', resumed, lambda *a: None)
        self.assertFalse(resumed.started);self.assertFalse(resumed.children)

    def test_first_failure_stops_new_submissions_and_saves_successful_inflight_for_resume(self):
        pipeline = FakePipeline(3)
        rendezvous = threading.Barrier(3)
        def hook(index, cancel):
            rendezvous.wait(timeout=3)
            if index == 1:
                raise RuntimeError('paid request failed; do not retry')
        pipeline.hook = hook
        with self.assertRaisesRegex(RuntimeError, 'do not retry'):
            books.render('book', pipeline, lambda *a: None)
        self.assertEqual(sorted(pipeline.started), [1, 2, 3])
        self.assertEqual(self.saved_ids(), [2, 3])
        self.assertEqual(books.metadata('book')['render_done'], 2)
        self.assertTrue(all(child.closed for child in pipeline.children))
        resumed = FakePipeline(3)
        books.render('book', resumed, lambda *a: None)
        self.assertEqual(sorted(resumed.started), [1, 4, 5, 6])

    def test_pause_drains_inflight_and_checkpoints_before_resume_without_new_requests(self):
        pipeline = FakePipeline(2)
        rendezvous = threading.Barrier(2)
        pause_written = threading.Event();pauses = []
        def hook(index, cancel):
            if index <= 2:
                rendezvous.wait(timeout=3)
                if index == 1:
                    state.control('book', 'pause');pause_written.set()
                else:
                    self.assertTrue(pause_written.wait(3))
        pipeline.hook = hook
        original = state.Control.boundary
        def boundary(control, *args, **kwargs):
            if state.requested('book') == 'pause':
                self.assertEqual(sorted(pipeline.started), [1, 2])
                self.assertEqual(self.saved_ids(), [1, 2])
                pauses.append(threading.get_ident());state.control('book', 'run')
            return original(control, *args, **kwargs)
        with patch('book_state.Control.boundary', boundary):
            books.render('book', pipeline, lambda *a: None)
        self.assertEqual(pauses, [threading.get_ident()])
        self.assertEqual(self.saved_ids(), list(range(1, 7)))

    def test_cancel_stops_scheduling_but_keeps_success_already_returned(self):
        pipeline = FakePipeline(2)
        rendezvous = threading.Barrier(2)
        def hook(index, cancel):
            rendezvous.wait(timeout=3)
            if index == 2:
                self.assertTrue(pipeline.cancelled.wait(3));cancel()
        pipeline.hook = hook
        pipeline.after_write = lambda index: pipeline.cancelled.set() if index == 1 else None
        with self.assertRaises(router.Cancelled):
            books.render('book', pipeline, lambda *a: None)
        self.assertEqual(sorted(pipeline.started), [1, 2])
        self.assertEqual(self.saved_ids(), [1])
        self.assertTrue(all(child.closed for child in pipeline.children))

    def test_only_opted_in_api_pipelines_parallelize_and_worker_bounds_are_finite(self):
        class Local:
            config = dict(api_workers=8)
        self.assertEqual(book_parallel.worker_count(Local(), {}), 1)
        pipeline = FakePipeline(3)
        self.assertEqual(book_parallel.worker_count(pipeline, {}), 3)
        for configured, expected in ((0, 1), (50, 8), ('many', 3), (True, 3)):
            self.assertEqual(book_parallel.worker_count(pipeline, dict(api_workers=configured)), expected)

    def test_single_effect_and_skipped_segment_checkpoint_without_speech_or_raw_placeholder(self):
        import book_sounds
        sound = self.root / 'effect.wav'
        sf.write(sound, np.sin(np.arange(4800) * .1) * .1, 24000)
        cue = dict(kind='sound', text='Скрип.', speaker='', sound_description='Колёса телеги')
        with books.connect('book') as db:
            db.execute('UPDATE segments SET text=?,parts=? WHERE id=1',
                       (cue['text'], json.dumps([cue])))
            db.execute('UPDATE segments SET parts=? WHERE id=2',
                       (json.dumps([dict(kind='toc', text='Оглавление', speaker='')]),))
        state.update('book', sounds={book_sounds.identity(cue): dict(file=str(sound))})
        pipeline = FakePipeline(3)
        books.render('book', pipeline, lambda *a: None)
        self.assertEqual(sorted(pipeline.started), [3, 4, 5, 6])
        self.assertEqual(self.saved_ids(), list(range(1, 7)))
        self.assertFalse((books.folder('book') / 'audio' / '00000001.wav').exists())
        with books.connect('book') as db:
            effect = db.execute('SELECT wav FROM segments WHERE id=1').fetchone()[0]
        self.assertEqual(sf.info(effect).frames, 4800)
        self.assertTrue(sound.is_file())

    def test_explicit_resume_of_failed_multipart_reuses_completed_raw_paid_part(self):
        with books.connect('book') as db:
            db.execute('DELETE FROM segments WHERE id!=1')
            parts=[dict(kind='content',speaker='',text='Первая часть.'),
                   dict(kind='content',speaker='',text='Вторая часть.')]
            db.execute('UPDATE segments SET text=?,parts=? WHERE id=1',
                       ('Первая часть. Вторая часть.',json.dumps(parts)))
        calls={}
        def post(*args,**kwargs):
            text=kwargs['json']['input'];calls[text]=calls.get(text,0)+1
            if text=='Вторая часть.' and calls[text]==1:
                raise router.requests.ConnectionError('offline simulated lost response')
            return RouterAIParallelSessionTests.response()
        def session():
            client=MagicMock();client.post.side_effect=post;return client
        with patch('routerai_engine.requests.Session',side_effect=session), \
                patch('tts_settings.api_key',return_value='offline-test-key'):
            client=router.Pipeline(dict(base_url='https://routerai.ru/api/v1',model=router.MODEL,api_workers=3))
            self.addCleanup(client.close)
            with self.assertRaisesRegex(RuntimeError,'автоматического повтора нет'):
                books.render('book',client,lambda *a:None)
            self.assertEqual((calls['Первая часть.'],calls['Вторая часть.']),(1,1))
            self.assertEqual(sum(calls.values()),3)  # One cached chapter heading, too.
            self.assertEqual(self.saved_ids(),[])
            self.assertTrue((books.folder('book')/'audio'/'00000001-part-000.cleanup.json').is_file())
            books.render('book',client,lambda *a:None)
            self.assertEqual((calls['Первая часть.'],calls['Вторая часть.']),(1,2))
            self.assertEqual(sum(calls.values()),4)
            self.assertEqual(self.saved_ids(),[1])


class RouterAIParallelSessionTests(unittest.TestCase):
    @staticmethod
    def response():
        body = io.BytesIO()
        sf.write(body, np.sin(np.arange(4410) * .07) * .1, 44100, format='WAV')
        response = MagicMock();response.__enter__.return_value = response
        response.status_code = 200
        response.headers = {'Content-Type': 'audio/mpeg', 'Content-Length': str(len(body.getvalue()))}
        response.iter_content.return_value = iter([body.getvalue()])
        return response

    def test_forks_use_exclusive_sessions_and_raw_clip_cache_survives_worker_count_change(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(store, 'DATA', Path(temporary)), \
                patch('tts_settings.api_key', return_value='offline-test-key'):
            parent = router.Pipeline(dict(base_url='https://routerai.ru/api/v1', model=router.MODEL, api_workers=2))
            self.addCleanup(parent.close)
            children = [parent.fork_book_pipeline() for _ in range(2)]
            for child in children:self.addCleanup(child.close)
            self.assertIsNot(children[0].http, children[1].http)
            self.assertIsNot(children[0].http, parent.http)
            self.assertEqual(children[0].http.adapters['https://'].max_retries.total, 0)
            rendezvous = threading.Barrier(2)
            def post(*args, **kwargs):
                rendezvous.wait(timeout=3);return self.response()
            targets = [Path(temporary) / f'clip-{index}.wav' for index in range(2)]
            with patch.object(children[0].http, 'post', side_effect=post) as post0, \
                    patch.object(children[1].http, 'post', side_effect=post) as post1:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(child.clip, VOICE, f'Реплика {index}.', '', 42, target,
                                               sample_rate=24000)
                               for index, (child, target) in enumerate(zip(children, targets))]
                    for future in futures:self.assertTrue(Path(future.result(timeout=8)).is_file())
                self.assertEqual([post0.call_count, post1.call_count], [1, 1])
            parent.config['api_workers'] = 4
            recovered = parent.fork_book_pipeline();self.addCleanup(recovered.close)
            with patch.object(recovered.http, 'post') as post:
                recovered.clip(VOICE, 'Реплика 0.', '', 42, targets[0], sample_rate=24000)
            post.assert_not_called()
            self.assertEqual(store.load_json(targets[0].with_suffix('.cleanup.json'), {})['api_request_attempts'], 1)


if __name__ == '__main__':unittest.main()
