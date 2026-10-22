import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import requests
import soundfile as sf

import avatar_store as store
import book_engine as books
import music_engine as music
import music_planner as planner
import music_timeline as timeline
import remote_jobs
from remote_ssh import Cancelled


class MusicTests(unittest.TestCase):
    def setUp(self):
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

    def test_native_graph_uses_medium_lcm8_and_stereo_decoder(self):
        graph=music.graph('quiet atmosphere',12,42,'music/test')
        self.assertEqual(graph['1']['inputs']['ckpt_name'],music.MODEL)
        self.assertEqual(graph['6']['inputs']['steps'],8)
        self.assertEqual(graph['6']['inputs']['sampler_name'],'lcm')
        self.assertEqual(graph['7']['inputs']['vae'],['1',2])
        self.assertIn('No vocals',graph['3']['inputs']['text'])

    def test_real_ffmpeg_mix_is_quiet_sample_exact_and_cached(self):
        dry=self.root/'speech.wav';sr=24000
        speech=np.sin(np.arange(sr*5,dtype='float32')*.045)*.16
        sf.write(dry,speech,sr,subtype='PCM_24')
        pipeline=MagicMock();pipeline.execute.return_value={'8':{'audio':[dict(filename='music.flac',subfolder='',type='output')]}}
        generator=np.random.default_rng(4)
        noise=generator.normal(0,.07,(44100*5,2)).astype('float32')
        pipeline.download_audio.return_value=(noise,44100)
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
        self.assertEqual(make.call_count,1);self.assertEqual(pipeline.execute.call_count,1)
        self.assertTrue(Path(output).with_suffix('.music.json').is_file())
        self.assertNotEqual(Path(output),dry)


class OwnedJobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        change=patch.object(store,'DATA',Path(self.temp.name));change.start();self.addCleanup(change.stop)

    def receipt(self):
        return remote_jobs.register('http://127.0.0.1:12345',dict(user='root',host='gpu.example',port=22,identity_file=''),8188)

    def test_parent_cancel_targets_receipt_and_preserves_failed_ack(self):
        receipt=self.receipt();session=MagicMock();session.__enter__.return_value=session
        session.post.side_effect=RuntimeError('no ACK')
        with patch.object(remote_jobs.requests,'Session',return_value=session):
            result=remote_jobs.cancel_owned()
        self.assertFalse(result[0]['confirmed']);self.assertTrue(remote_jobs.ticket_path(receipt['ticket']).is_file())
        session.post.side_effect=None
        with patch.object(remote_jobs.requests,'Session',return_value=session):
            result=remote_jobs.cancel_owned()
        self.assertTrue(result[0]['confirmed']);self.assertFalse(remote_jobs.ticket_path(receipt['ticket']).exists())
        self.assertEqual(session.post.call_args.args[0],'http://127.0.0.1:12345/api/jobs/'+receipt['prompt_id']+'/cancel')

    def test_submit_lock_blocks_cancellation_until_post_finishes(self):
        receipt=self.receipt();entered=threading.Event();release=threading.Event();done=threading.Event()
        def submit():
            with remote_jobs.locked(receipt['ticket']):
                entered.set();release.wait(2)
        def cancel():
            with remote_jobs.locked(receipt['ticket']):done.set()
        thread=threading.Thread(target=submit);thread.start();self.assertTrue(entered.wait(2))
        second=threading.Thread(target=cancel);second.start()
        self.assertFalse(done.wait(.1));release.set();thread.join(2);second.join(2)
        self.assertTrue(done.is_set())

    def test_parent_cancels_installer_by_id_without_installing_or_global_interrupt(self):
        receipt=remote_jobs.register_install(dict(user='root',host='gpu.example',port=22,identity_file=''),'a'*32)
        ssh=MagicMock()
        with patch('remote_ssh.SSHConnection',return_value=ssh):
            result=remote_jobs.cancel_owned()
        self.assertTrue(result[0]['confirmed'])
        ssh._cancel_install.assert_called_once_with('a'*32)
        ssh.prepare.assert_not_called();ssh.forward.assert_not_called()
        self.assertFalse(remote_jobs.ticket_path(receipt['ticket']).exists())

    def test_lost_post_response_still_cancels_preassigned_id(self):
        import drama3_engine as engine
        pipeline=engine.Pipeline(dict(connection='ssh gpu.example'))
        pipeline.url='http://127.0.0.1:12345';pipeline.http=MagicMock()
        pipeline.http.post.side_effect=[requests.Timeout('response lost'),MagicMock()]
        try:
            with patch.object(pipeline,'load'),patch.object(engine.websocket,'create_connection',side_effect=OSError):
                with self.assertRaises(requests.Timeout):pipeline.execute({})
            calls=pipeline.http.post.call_args_list
            assigned=calls[0].kwargs['json']['prompt_id']
            self.assertEqual(calls[1].args[0],pipeline.url+'/api/jobs/'+assigned+'/cancel')
            self.assertFalse(list(remote_jobs.directory().glob('*.json')))
        finally:pipeline.close()


if __name__=='__main__':unittest.main()
