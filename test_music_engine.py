import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

import avatar_store as store
import book_engine as books
import music_engine as music
import music_planner as planner
import music_timeline as timeline
import local_audio_runtime as local_audio
from routerai_engine import Cancelled, reset_cancel, request_cancel


class MusicTests(unittest.TestCase):
    def setUp(self):
        reset_cancel()
        self.addCleanup(reset_cancel)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for change in (patch.object(store, 'DATA', self.root), patch.object(books, 'BOOKS', self.root/'books')):
            change.start(); self.addCleanup(change.stop)

    def book(self, plan=None, narrator='', character=''):
        books.folder('test').mkdir(parents=True)
        books.save_meta('test', dict(default_avatar=narrator, **({'music_plan': plan} if plan is not None else {})))
        with books.connect('test') as db:
            db.executescript("CREATE TABLE segments(id INTEGER,chapter INTEGER,text TEXT,speaker TEXT);"
                             "CREATE TABLE characters(name TEXT PRIMARY KEY,avatar TEXT DEFAULT '',mentions INTEGER DEFAULT 0);")
            db.executemany('INSERT INTO segments VALUES(?,?,?,?)', [(1,1,'Тихая комната.',''), (2,1,'Привет.','Анна'), (3,1,'Пойдём.','Анна')])
            db.execute('INSERT INTO characters(name,avatar) VALUES(?,?)', ('Анна', character))
        db.close()

    @staticmethod
    def plan():
        return dict(version=1, source='manual', cues=[dict(start_segment=1,end_segment=2,prompt='Sparse electronic air')],
                    voice_assignments={'$narrator':'v2', 'Анна':'v2'})

    def test_manual_plan_never_initializes_api_and_preserves_voices(self):
        self.book(self.plan(), narrator='v1', character='v1')
        with patch.object(store, 'avatars', return_value=[dict(id='v1'),dict(id='v2')]), patch('deepseek_model.DeepSeekModel', side_effect=AssertionError('API called')):
            plan = planner.ensure_book_plan('test')
        self.assertEqual(plan['source'], 'manual')
        self.assertEqual(books.metadata('test')['default_avatar'], 'v1')
        with books.connect('test') as db:
            self.assertEqual(db.execute('SELECT avatar FROM characters').fetchone()[0], 'v1')
        db.close()

    def test_manual_plan_fills_only_missing_real_voices(self):
        self.book(self.plan())
        with patch.object(store, 'avatars', return_value=[dict(id='v2')]):
            planner.ensure_book_plan('test')
        self.assertEqual(books.metadata('test')['default_avatar'], 'v2')
        with books.connect('test') as db:
            self.assertEqual(db.execute('SELECT avatar FROM characters').fetchone()[0], 'v2')
        db.close()

    def test_invalid_boundaries_overlap_and_invented_voice_rejected(self):
        rows=[dict(id=i,chapter=1) for i in (1,2,3)]
        plan=self.plan();plan['cues'][0]['end_segment']=9
        with self.assertRaises(ValueError):planner.validate_plan(plan,rows,[dict(id='v2')])
        plan=self.plan();plan['cues']*=2
        with self.assertRaises(ValueError):planner.validate_plan(plan,rows,[dict(id='v2')])
        with self.assertRaises(ValueError):planner.validate_plan(self.plan(),rows,[dict(id='v1')])
        plan=self.plan();plan['cues'][0]['level_db']=-20
        self.assertEqual(planner.validate_plan(plan,rows,[dict(id='v2')])['cues'][0]['level_db'],-38.)

    def test_automatic_plan_uses_selected_api_and_saved_response(self):
        self.book()
        model=MagicMock();model.__enter__.return_value=model
        model.complete.return_value=self.plan()
        with patch.object(store,'avatars',return_value=[dict(id='v2',name='Студийный')]), patch('analysis_settings.settings',return_value=dict(provider='deepseek')), patch('deepseek_model.DeepSeekModel',return_value=model) as constructor:
            first=planner.ensure_book_plan('test')
            second=planner.ensure_book_plan('test')
        self.assertEqual(first['source'],'deepseek');self.assertEqual(first['cues'],second['cues'])
        self.assertEqual(model.complete.call_count,1);self.assertEqual(constructor.call_count,1)
        self.assertIn('<|im_start|>system\n',model.complete.call_args.args[0])

    def test_incomplete_api_cast_does_not_silently_use_narrator_for_everyone(self):
        self.book()
        model=MagicMock();model.__enter__.return_value=model
        model.complete.return_value=dict(cues=[],voice_assignments={'$narrator':'v2'})
        with patch.object(store,'avatars',return_value=[dict(id='v2')]),patch('analysis_settings.settings',return_value=dict(provider='deepseek')),patch('deepseek_model.DeepSeekModel',return_value=model):
            with self.assertRaisesRegex(ValueError,'персонажей'):planner.ensure_book_plan('test')
        self.assertNotIn('music_plan',books.metadata('test'))

    def test_timeline_uses_measured_files_and_real_pauses(self):
        paths=[]
        for i,length in enumerate((1000,1500)):
            path=self.root/f'{i}.wav';sf.write(path,np.zeros(length),1000);paths.append(path)
        measured=timeline.segment_timing(paths,[1,2],[350],initial_offset=2.)
        self.assertEqual(measured[1]['start_seconds'],3.35)
        cues=timeline.cue_times(self.plan(),measured,5.)
        self.assertEqual((cues[0]['start_seconds'],cues[0]['end_seconds']),(2.,4.85))
        pieces=list(timeline.chunks(3.,96.))
        self.assertTrue(all(b-a<=45.001 for a,b in pieces))
        self.assertEqual(pieces[0][0],3.);self.assertAlmostEqual(pieces[-1][1],96.)
        self.assertTrue(all(abs(a[1]-b[0]-2)<.001 for a,b in zip(pieces,pieces[1:])))

    def test_local_runtime_bounds_audio_before_loading_or_installing_weights(self):
        pipeline=local_audio.Pipeline()
        with patch.object(pipeline,'_start') as start:
            for seconds in (0,.5,16,float('nan')):
                with self.subTest(seconds=seconds),self.assertRaises(ValueError):
                    pipeline.generate('quiet atmosphere',seconds,42)
            start.assert_not_called()
        self.assertEqual(local_audio.MAX_CHUNK_SECONDS,15.)

    def test_real_ffmpeg_mix_is_quiet_sample_exact_and_cached(self):
        dry=self.root/'speech.wav';sr=24000
        speech=np.sin(np.arange(sr*5,dtype='float32')*.045)*.16
        sf.write(dry,speech,sr,subtype='PCM_24')
        pipeline=MagicMock()
        generator=np.random.default_rng(4)
        noise=generator.normal(0,.07,(44100*5,2)).astype('float32')
        pipeline.generate.return_value=(noise,44100)
        cues=[dict(start_seconds=.5,end_seconds=4.5,prompt='soft harmonic air',level_db=-41.)]
        with patch.object(music,'Pipeline',return_value=pipeline) as make:
            output=music._render(dry,cues,self.root/'cache',lambda *args:None,lambda:None)
            again=music._render(dry,cues,self.root/'cache',lambda *args:None,lambda:None)
        result,actual=sf.read(output,always_2d=True,dtype='float32')
        original,_=sf.read(dry,dtype='float32')
        self.assertEqual((len(result),actual),(len(original),sr));self.assertEqual(output,again)
        delta=result-original[:,None]
        self.assertLess(float(np.sqrt(np.mean(delta**2))),float(np.sqrt(np.mean(original**2)))/15)
        self.assertLess(float(np.max(np.abs(delta[:sr//3]))),.0001)
        self.assertEqual(make.call_count,1);self.assertEqual(pipeline.generate.call_count,1)
        self.assertTrue(Path(output).with_suffix('.music.json').is_file())
        self.assertNotEqual(Path(output),dry)


class LocalAudioLifecycleTests(unittest.TestCase):
    def setUp(self):
        reset_cancel();self.addCleanup(reset_cancel)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for change in (patch.object(store,'DATA',self.root/'data'),
                       patch.object(local_audio,'root',return_value=self.root)):
            change.start();self.addCleanup(change.stop)

    def test_cancel_before_submit_does_not_install_or_start_worker(self):
        pipeline=local_audio.Pipeline()
        request_cancel()
        with patch.object(pipeline,'_start') as start:
            with self.assertRaises(Cancelled):pipeline.generate('quiet atmosphere',2,42)
        start.assert_not_called()
        self.assertFalse(list(self.root.glob('audio-*.wav')))

    def test_close_terminates_only_owned_worker_and_releases_generation_lock(self):
        pipeline=local_audio.Pipeline();process=MagicMock();process.poll.return_value=None
        lock=MagicMock();log=MagicMock()
        pipeline.process=process;pipeline.lock=lock;pipeline.log=log
        pipeline.close()
        process.terminate.assert_called_once_with();process.wait.assert_called_once_with(timeout=5)
        process.kill.assert_not_called()
        process.stdin.close.assert_called_once();process.stdout.close.assert_called_once()
        lock.__exit__.assert_called_once_with(None,None,None);log.close.assert_called_once()
        self.assertIsNone(pipeline.process);self.assertIsNone(pipeline.lock)
        pipeline.close()
        process.terminate.assert_called_once()

    def test_close_kills_owned_worker_only_after_terminate_times_out(self):
        pipeline=local_audio.Pipeline();process=MagicMock();process.poll.return_value=None
        process.wait.side_effect=[subprocess.TimeoutExpired('local-audio',5),0]
        pipeline.process=process
        pipeline.close()
        process.terminate.assert_called_once();process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count,2)
        self.assertIsNone(pipeline.process)

    def test_worker_error_closes_process_without_resubmitting_or_leaving_audio(self):
        pipeline=local_audio.Pipeline();process=MagicMock();process.poll.return_value=None
        def start(progress,cancel):
            pipeline.process=process
            pipeline.messages.put(dict(type='error',message='local worker failed'))
        with patch.object(pipeline,'_start',side_effect=start):
            with self.assertRaisesRegex(RuntimeError,'local worker failed'):
                pipeline.generate('quiet atmosphere',2,42)
        process.stdin.write.assert_called_once();process.terminate.assert_called_once()
        self.assertFalse(list(self.root.glob('audio-*.wav')))


if __name__=='__main__':unittest.main()
