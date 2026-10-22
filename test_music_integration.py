"""CPU-only music publication, real speech timing and cancellation GUI checks."""
import gc
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

import avatar_store as store
import book_engine as books
import book_state as state


class MusicBookIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.changes=[patch.object(store,'DATA',self.root),patch.object(books,'BOOKS',self.root/'books'),
                      patch('tts_settings.settings',return_value=dict(mode='api',music_enabled=False))]
        for change in self.changes:change.start()
    def tearDown(self):
        for change in reversed(self.changes):change.stop()
        gc.collect();self.tmp.cleanup()

    def test_api_setup_seeds_client_preferences_once_without_overwriting(self):
        script=(Path(books.__file__).parent/'setup.ps1').read_text(encoding='utf-8')
        seed=next(line for line in script.splitlines() if 'atomic_json(target,dict(mode=' in line)
        code=seed.split(' -c "',1)[1].rsplit('"',1)[0]
        exec(compile(code,'setup.ps1 client preferences','exec'),{})
        import tts_settings
        self.assertEqual(store.load_json(tts_settings.path(),{}),dict(mode='api',base_url=tts_settings.DEFAULT_URL,model=tts_settings.DEFAULT_MODEL,music_enabled=False,sound_generation_enabled=False,local_audio_device='auto',local_audio_offload=True))
        old=dict(mode='api',base_url=tts_settings.DEFAULT_URL,model=tts_settings.DEFAULT_MODEL,music_enabled=True,fish_options={'temperature':.7})
        store.atomic_json(tts_settings.path(),old)
        exec(compile(code,'setup.ps1 client preferences','exec'),{})
        self.assertEqual(store.load_json(tts_settings.path(),{}),old)

    def test_timeline_matches_written_frames_after_trim_and_heading(self):
        source=self.root/'speech.wav'
        sf.write(source,np.ones(24000,dtype='float32')*.1,24000)
        target=self.root/'joined.wav'
        def trimmed(audio,*args):
            audio.seek(2400);yield audio.read(16800,dtype='float32')
        with patch('book_audio.edge_blocks',trimmed):
            timing=books.stitch([source,source,source],target,'book',[350,180],segment_ids=[None,10,11])
        self.assertEqual([r['segment_id'] for r in timing],[10,11])
        self.assertAlmostEqual(timing[0]['start_seconds'],1.05)
        self.assertAlmostEqual(timing[0]['end_seconds'],1.75)
        self.assertAlmostEqual(timing[1]['start_seconds'],1.93)
        self.assertAlmostEqual(timing[-1]['end_seconds'],sf.info(target).duration)

    def test_whole_book_join_handles_mixed_wav_channels_and_bit_depth(self):
        mono=self.root/'dry.wav';stereo=self.root/'music.wav'
        sf.write(mono,np.ones(24000)*.1,24000,subtype='PCM_16')
        sf.write(stereo,np.column_stack((np.ones(24000)*.2,np.ones(24000)*.3)),24000,subtype='PCM_24')
        for index,paths in enumerate(([mono,stereo],[stereo,mono])):
            joined=self.root/f'whole-{index}.wav'
            books.join_chapters(paths,joined,'book')
            data,sr=sf.read(joined,always_2d=True)
            self.assertEqual(data.shape,(48000,2));self.assertEqual(sr,24000)
            first=0 if index==0 else 24000
            self.assertAlmostEqual(data[first+100,0],.1,places=4)
            self.assertAlmostEqual(data[first+100,1],.1,places=4)
            mp3=joined.with_suffix('.mp3')
            books.run_ffmpeg(['-i',str(joined),'-codec:a','libmp3lame','-b:a','192k',str(mp3)],'book')
            self.assertAlmostEqual(sf.info(mp3).duration,2.,delta=.05)

    def test_book_exports_use_mix_and_disabling_music_reuses_voice_cache(self):
        reference=self.root/'reference.wav';sf.write(reference,np.zeros(24000,dtype='float32'),24000)
        voice=store.save_profile('Автор',reference,'Точный образец.',1)
        source=self.root/'chapter.txt';source.write_text('Глава 1\n\nОн открыл дверь.\n\nОна рассмеялась.',encoding='utf-8')
        books.import_book(source,'book',lambda *a:None);state.migrate('book')
        with books.connect('book') as db:
            db.execute('UPDATE segments SET analyzed=1')
        db.close()
        state.update('book',default_avatar=voice['id'],analysis_complete=True,music_enabled=True,
                     music_plan=dict(version=1,source='manual',cues=[],voice_assignments={}))
        calls=[]
        class Pipeline:
            supports_narrator_styles=True
            def synthesize_book_clip(self,reference,text,transcript,seed,target,**options):
                calls.append(text)
                tone=np.sin(np.arange(12000)*.08).astype('float32')*.12
                sf.write(target,np.concatenate((np.zeros(1200),tone,np.zeros(1200))),24000)
                return str(target)
        mixed=[]
        def render_music(book_id,chapter_id,dry,timing,plan,progress,cancel):
            audio,sr=sf.read(dry,dtype='float32');target=Path(dry).with_name('generated-music.wav')
            sf.write(target,np.column_stack((audio,audio*.7)),sr)
            mixed.append((Path(dry),timing,target))
            return str(target)
        events=[]
        with patch('music_planner.ensure_book_plan',return_value={'cues':[]}) as planner,patch('music_engine.render_book',side_effect=render_music),patch('book_engine.chapter_heading_plan',return_value=[dict(text='Название главы',avatar=voice['id'],narrator_style='heading')]):
            result=books.render('book',Pipeline(),lambda *a:None,emit=lambda kind,**event:events.append(kind))
        self.assertEqual(Path(result).name,'audiobook.mp3')
        self.assertTrue(Path(result).is_file())
        self.assertEqual(planner.call_count,1)
        dry,timing,_=mixed[0]
        self.assertTrue(dry.is_file())
        self.assertGreater(timing[0]['start_seconds'],0)
        self.assertAlmostEqual(timing[-1]['end_seconds'],sf.info(dry).duration)
        chapter=books.folder('book')/'chapter-0001.wav'
        self.assertEqual(sf.info(chapter).channels,2)
        self.assertEqual(sf.info(books.folder('book')/'audio'/'00000001.wav').channels,1)
        before=list(calls)
        state.update('book',music_enabled=False)
        with patch('music_planner.ensure_book_plan') as planner,patch('music_engine.render_book') as renderer:
            books.render('book',Pipeline(),lambda *a:None)
            planner.assert_not_called();renderer.assert_not_called()
        self.assertEqual(calls,before)
        self.assertEqual(sf.info(chapter).channels,1)
        self.assertTrue(dry.is_file())

    def test_studio_mix_keeps_dry_files_and_history_uses_mixed_audio(self):
        from music_integration import finish_studio
        dry=self.root/'speech.wav';sf.write(dry,np.zeros(12000),24000)
        original_mp3=self.root/'speech.mp3';original_mp3.write_bytes(b'original')
        report=self.root/'speech.json';store.atomic_json(report,{'needs_review':True,'duration_seconds':.5})
        mixed=self.root/'speech-music.wav';sf.write(mixed,np.zeros((12000,2)),24000)
        with patch('music_engine.render_studio',return_value=str(mixed)):
            mp3,wav,metadata=finish_studio('Текст',str(original_mp3),str(dry),str(report),lambda *a:None,lambda:None)
        entry=store.add_history(dict(id='voice',name='Автор'),'Текст',mp3,wav,metadata)
        self.assertEqual(entry['wav'],str(mixed))
        self.assertTrue(entry['needs_review'])
        saved=store.load_json(metadata,{})
        self.assertEqual(saved['dry_wav'],str(dry))
        self.assertEqual(original_mp3.read_bytes(),b'original')
        self.assertEqual(store.load_json(report,{})['duration_seconds'],.5)

    def test_checkbox_book_flow_plans_real_voices_and_music_then_assembles_automatically(self):
        reference=self.root/'reference.wav';sf.write(reference,np.zeros(24000,dtype='float32'),24000)
        narrator=store.save_profile('Рассказчик',reference,'Образец.',1)
        girl=store.save_profile('Девушка',reference,'Образец девушки.',1)
        source=self.root/'automatic.txt';source.write_text('Глава 1\n\nОн открыл дверь.\n\n— Ты пришёл!',encoding='utf-8')
        books.import_book(source,'book',lambda *a:None);state.migrate('book')
        with books.connect('book') as db:
            db.execute("INSERT INTO characters(name,avatar,mentions) VALUES('Мира','',1)")
            db.execute('UPDATE segments SET analyzed=1')
            db.execute("UPDATE segments SET speaker='Мира' WHERE id=3")
        db.close();state.update('book',analysis_complete=True,music_enabled=True)
        sequence=[]
        class API:
            def __init__(self,*args):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def complete(self,prompt,schema,budget,callback):
                sequence.append('plan')
                return dict(cues=[dict(start_segment=2,end_segment=3,prompt='Sparse quiet warm harmonic air')],
                            voice_assignments={'$narrator':narrator['id'],'Мира':girl['id']})
        class Pipeline:
            def synthesize_book_clip(self,reference,text,transcript,seed,target,**options):
                sequence.append('speech')
                sf.write(target,np.sin(np.arange(12000)*.08).astype('float32')*.1,24000)
                return str(target)
        observed=[]
        def music(book_id,chapter_id,dry,timing,plan,progress,cancel):
            sequence.append('music');observed.append((timing,plan))
            progress(.5,'Музыка: 4 / 8')
            data,sr=sf.read(dry,dtype='float32');target=Path(dry).with_name('automatic-music.wav')
            sf.write(target,np.column_stack((data,data)),sr);return str(target)
        events=[]
        with patch('analysis_settings.settings',return_value=dict(provider='deepseek')),patch('deepseek_model.DeepSeekModel',API),patch('music_engine.render_book',side_effect=music):
            result=books.render('book',Pipeline(),lambda *a:None,emit=lambda kind,**event:events.append((kind,event)))
        self.assertTrue(Path(result).is_file())
        self.assertEqual(sequence[0],'plan');self.assertEqual(sequence[-1],'music')
        self.assertEqual(books.metadata('book')['default_avatar'],narrator['id'])
        with books.connect('book') as db:
            self.assertEqual(db.execute("SELECT avatar FROM characters WHERE name='Мира'").fetchone()[0],girl['id'])
        db.close()
        timing,plan=observed[0]
        self.assertTrue(timing);self.assertEqual(plan['source'],'deepseek')
        self.assertEqual(plan['cues'][0]['level_db'],-41.)
        self.assertTrue(any(kind=='music_progress' and event['value']==.5 for kind,event in events))
        self.assertTrue((books.folder('book')/'chapter-0001-dry.wav').is_file())


os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QMainWindow
from PySide6.QtGui import QCloseEvent,QIcon


class MusicUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.changes=[patch.object(store,'DATA',self.root),patch.object(books,'BOOKS',self.root/'books')]
        for change in self.changes:change.start()
        self.widgets=[]
    def tearDown(self):
        for widget in self.widgets:
            widget.force_close=True
            widget.close();widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);self.app.processEvents()
        for change in reversed(self.changes):change.stop()
        gc.collect()
        self.tmp.cleanup()

    def test_book_checkbox_does_not_invalidate_cached_voice(self):
        from book_ui import BookDialog
        source=self.root/'chapter.txt';source.write_text('Глава 1\n\nОн открыл дверь.',encoding='utf-8')
        books.import_book(source,'book',lambda *a:None);state.migrate('book')
        parent=QMainWindow();parent.ready=True;parent.backend=MagicMock();self.widgets.append(parent)
        with patch('tts_settings.settings',return_value=dict(mode='api',music_enabled=False)):
            dialog=BookDialog(parent);self.widgets.insert(0,dialog)
            self.assertTrue(dialog.music_checkbox.isEnabled())
            with patch('book_state.invalidate') as invalidate:
                dialog.music_checkbox.setChecked(True)
            invalidate.assert_not_called()
            self.assertTrue(books.metadata('book')['music_enabled'])
            dialog.handle(dict(type='music_progress',message='Музыка: 4/8',value=.5))
            self.assertEqual(dialog.music_progress.value(),500)
            dialog.select_book()
            self.assertTrue(dialog.music_checkbox.isChecked())
        with patch('tts_settings.settings',return_value=dict(mode='api',music_enabled=True)):
            dialog.set_running(False)
            self.assertTrue(dialog.music_checkbox.isEnabled())
            with patch('book_state.invalidate') as invalidate:
                dialog.music_checkbox.setChecked(False)
            invalidate.assert_not_called()
            self.assertFalse(books.metadata('book')['music_enabled'])
            self.assertTrue(dialog.music_checkbox.isEnabled())

    def test_parent_cancel_signals_api_and_local_audio_without_terminating_worker(self):
        from desktop_app import MainWindow
        with patch('desktop_app.ensure_assets',return_value=QIcon()):
            window=MainWindow(start_backend=False)
        self.widgets.append(window);window.backend=MagicMock();window.busy=True
        with patch('routerai_engine.request_cancel') as cancel:
            window.cancel_speech()
        cancel.assert_called_once_with();window.backend.stop.assert_not_called()
        self.assertFalse(window.cancel_speech_button.isEnabled())
        self.assertIn('локальную',window.status_text.text())

    def test_studio_checkbox_is_persisted_and_forwarded_before_busy_disables_it(self):
        import tts_settings
        from desktop_app import MainWindow
        tts_settings.save(music_enabled=False)
        with patch('desktop_app.ensure_assets',return_value=QIcon()):
            window=MainWindow(start_backend=False)
        self.widgets.append(window);window.backend=MagicMock();window.ready=True
        window.current_avatar=dict(id='voice');window.editor.setPlainText('Получилось!')
        window.music_checkbox.setChecked(True)
        self.assertTrue(tts_settings.settings()['music_enabled'])
        window.generate()
        self.assertFalse(window.music_checkbox.isEnabled())
        self.assertTrue(window.backend.send.call_args.args[0]['music_enabled'])

    def test_close_cancels_audio_stops_owned_worker_and_preserves_draft(self):
        from desktop_app import MainWindow
        with patch('desktop_app.ensure_assets',return_value=QIcon()):
            window=MainWindow(start_backend=False)
        self.widgets.append(window);window.backend=MagicMock();window.busy=True
        window.current_avatar=dict(id='voice');window.editor.setPlainText('Сохранённый черновик')
        with patch('routerai_engine.request_cancel') as cancel:
            event=QCloseEvent();window.closeEvent(event)
        self.assertTrue(event.isAccepted());cancel.assert_called_once_with()
        window.backend.stop.assert_called_once_with()
        saved=store.load_json(store.DATA/'settings.json',{})
        self.assertEqual(saved['draft'],'Сохранённый черновик');self.assertEqual(saved['avatar_id'],'voice')

    def test_running_book_close_waits_for_checkpoint_before_stopping_worker(self):
        from desktop_app import MainWindow
        with patch('desktop_app.ensure_assets',return_value=QIcon()):
            window=MainWindow(start_backend=False)
        self.widgets.append(window);window.backend=MagicMock();window.book_dialog=MagicMock()
        window.book_dialog.running=True
        event=QCloseEvent();window.closeEvent(event)
        self.assertFalse(event.isAccepted());window.backend.stop.assert_not_called()
        window.book_dialog.request_stop.assert_called_once_with(close_app=True,confirm=False)
        window.book_dialog=None

    def test_api_error_reenables_settings_and_keeps_existing_voice(self):
        from desktop_app import MainWindow
        with patch('desktop_app.ensure_assets',return_value=QIcon()):
            window=MainWindow(start_backend=False)
        self.widgets.append(window);window.backend=MagicMock();window.ready=True
        window.current_avatar=dict(id='voice');window.editor.setPlainText('Текст')
        window.set_busy(True)
        with patch('desktop_app.QMessageBox.warning') as warning:
            window.on_event(dict(type='error',message='RouterAI connection lost'))
        self.assertFalse(window.busy);self.assertTrue(window.tts_settings_button.isEnabled())
        self.assertEqual(window.current_avatar['id'],'voice');warning.assert_called_once()
        with patch('tts_settings_ui.TTSSettingsDialog') as settings_dialog:
            settings_dialog.return_value.exec.return_value=0
            window.configure_tts()
        settings_dialog.assert_called_once_with(window)

    def test_clean_api_client_starts_supervisor_and_restarts_after_settings(self):
        import tts_settings
        from desktop_app import MainWindow
        tts_settings.save(music_enabled=False)
        with patch('desktop_app.ensure_assets',return_value=QIcon()):
            window=MainWindow(start_backend=False)
        self.widgets.append(window)
        with patch('desktop_app.Backend') as backend:
            window.start_backend()
            backend.assert_called_once_with(window);backend.return_value.start.assert_called_once()
            window.on_event(dict(type='ready'))
            self.assertTrue(window.ready);self.assertTrue(window.tts_settings_button.isEnabled())
            self.assertFalse(window.generate_button.isEnabled())
            def configure():
                tts_settings.save(music_enabled=True)
                return 1
            with patch('tts_settings_ui.TTSSettingsDialog') as dialog:
                dialog.return_value.exec.side_effect=configure
                window.configure_tts()
            self.assertEqual(backend.call_count,2)
            self.assertEqual(backend.return_value.start.call_count,2)
            self.assertTrue(window.music_checkbox.isChecked())


if __name__=='__main__':unittest.main()
