"""Optional SFX controls and saved manual playback choices, without a server."""
import gc
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QMainWindow,QPushButton
import avatar_store as store
import book_engine as books
import book_state as state
from book_ui import BookDialog


class SoundGenerationUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.changes=[patch.object(store,'DATA',self.root),patch.object(books,'BOOKS',self.root/'books'),
            patch('tts_settings.settings',return_value=dict(mode='api',music_enabled=False))]
        for change in self.changes:change.start()
        source=self.root/'book.txt';source.write_text('Глава 1\n\nСкрип-скрип.\n\nТелега проехала мимо.',encoding='utf-8')
        books.import_book(source,'book',lambda *args:None);state.migrate('book')
        self.host=QMainWindow();self.host.ready=True;self.host.backend=MagicMock();self.host.set_busy=MagicMock()
        self.dialog=BookDialog(self.host)
    def tearDown(self):
        self.dialog.running=False;self.dialog.allow_close=True;self.dialog.close();self.dialog.deleteLater()
        self.host.close();self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);self.app.processEvents()
        for change in reversed(self.changes):change.stop()
        gc.collect();self.tmp.cleanup()

    def test_checkbox_defaults_off_and_toggles_without_invalidating_voice_cache(self):
        checkbox=self.dialog.sounds.generation_checkbox
        self.assertFalse(checkbox.isChecked());self.assertTrue(checkbox.isEnabled())
        with patch('book_state.invalidate') as invalidate:
            checkbox.setChecked(True)
        invalidate.assert_not_called()
        meta=books.metadata('book');self.assertTrue(meta['sound_generation_enabled'])
        self.assertFalse(meta.get('music_enabled',False))
        self.dialog.select_book();self.assertTrue(checkbox.isChecked())
        with patch('tts_settings.settings',return_value=dict(mode='api',music_enabled=False)):
            self.dialog.sounds.update_generation_controls()
            self.assertTrue(checkbox.isEnabled())
            checkbox.setChecked(False)
            self.assertTrue(checkbox.isEnabled())
        self.assertFalse(books.metadata('book')['sound_generation_enabled'])

    def test_primary_and_detail_controls_sync_independently_and_keep_speech_checkpoints(self):
        # The controls above the tabs must be usable without discovering the
        # detailed sound panel, and changing the mix must not re-synthesize speech.
        with books.connect('book') as db:
            segment=db.execute('SELECT id FROM segments LIMIT 1').fetchone()['id']
            db.execute("UPDATE segments SET wav='cached-speech.wav',signature='speech-signature' WHERE id=?",(segment,))
            db.execute("UPDATE chapters SET output='old-mix.wav'")
        state.update('book',output='old-mix.wav',render_complete=True)
        with patch('book_state.invalidate') as invalidate:
            self.dialog.sound_checkbox.setChecked(True)
            self.assertTrue(self.dialog.sounds.generation_checkbox.isChecked())
            self.assertFalse(self.dialog.music_checkbox.isChecked())
            self.dialog.music_checkbox.setChecked(True)
            self.dialog.sounds.generation_checkbox.setChecked(False)
        invalidate.assert_not_called()
        self.assertFalse(self.dialog.sound_checkbox.isChecked())
        self.assertTrue(self.dialog.music_checkbox.isChecked())
        meta=books.metadata('book')
        self.assertFalse(meta['sound_generation_enabled']);self.assertTrue(meta['music_enabled'])
        self.assertFalse(meta['render_complete']);self.assertEqual(meta['output'],'')
        with books.connect('book') as db:
            row=db.execute('SELECT wav,signature FROM segments WHERE id=?',(segment,)).fetchone()
            self.assertEqual((row['wav'],row['signature']),('cached-speech.wav','speech-signature'))
            self.assertTrue(all(row['output']=='' for row in db.execute('SELECT output FROM chapters')))
        # Refresh only loads flags: it must not save a partly initialized state.
        with patch('book_engine.save_meta') as save:
            self.dialog.sounds.refresh()
        save.assert_not_called()
        self.dialog.select_book()
        self.assertTrue(self.dialog.music_checkbox.isChecked())
        self.assertFalse(self.dialog.sound_checkbox.isChecked())
        self.assertFalse(self.dialog.sounds.generation_checkbox.isChecked())

    def test_primary_controls_are_adjacent_visible_and_disabled_when_unavailable(self):
        self.dialog.resize(1110,790);self.dialog.show();self.app.processEvents()
        self.assertLessEqual(self.dialog.width(),1110)
        self.assertLessEqual(self.dialog.height(),790)
        music=self.dialog.music_checkbox;sound=self.dialog.sound_checkbox
        self.assertIs(music.parent(),sound.parent())
        self.assertTrue(music.isVisible());self.assertTrue(sound.isVisible())
        self.assertEqual(music.geometry().top(),sound.geometry().top())
        self.assertTrue(self.dialog.rect().contains(music.mapTo(self.dialog,music.rect().topLeft())))
        self.assertTrue(self.dialog.rect().contains(sound.mapTo(self.dialog,sound.rect().bottomRight())))
        self.dialog.set_running(True)
        self.assertFalse(music.isEnabled());self.assertFalse(sound.isEnabled())
        self.assertFalse(self.dialog.sounds.generation_checkbox.isEnabled())
        self.dialog.set_running(False)
        self.assertTrue(music.isEnabled());self.assertTrue(sound.isEnabled())
        self.dialog.book_id=None;self.dialog.sounds.refresh();self.dialog.set_running(False)
        self.assertFalse(music.isEnabled());self.assertFalse(sound.isEnabled())
        self.assertFalse(self.dialog.sounds.generation_checkbox.isEnabled())

    def test_studio_audio_action_opens_the_real_book_sound_panel(self):
        from PySide6.QtGui import QIcon
        from desktop_app import MainWindow
        with patch('desktop_app.ensure_assets',return_value=QIcon()):window=MainWindow(start_backend=False)
        window.backend=MagicMock();window.ready=True
        try:
            with patch('book_ui.BookDialog') as dialog:
                window.book_sounds_button.click()
                dialog.assert_called_once_with(window)
                dialog.return_value.tabs.setCurrentWidget.assert_called_once_with(dialog.return_value.sounds)
                dialog.return_value.exec.assert_called_once_with()
            window.set_busy(True)
            self.assertFalse(window.book_sounds_button.isEnabled())
            window.set_busy(False)
            self.assertTrue(window.book_sounds_button.isEnabled())
        finally:
            window.book_dialog=None;window.close();window.deleteLater()

    def test_progress_is_independent_and_no_longer_visible_after_terminal_event(self):
        self.dialog.music_progress.setValue(170)
        self.dialog.handle(dict(type='sound_progress',value=.625,message='Эффект: 5/8'))
        self.assertEqual(self.dialog.sound_progress.value(),625)
        self.assertEqual(self.dialog.music_progress.value(),170)
        self.dialog.handle(dict(type='sound_progress',value=0,message='Загрузка эффектов',indeterminate=True))
        self.assertEqual(self.dialog.sound_progress.maximum(),0)
        self.dialog.handle(dict(type='book_done',message='Готово'))
        self.assertTrue(self.dialog.sound_progress.isHidden())

    def test_automatic_narrator_and_skip_choices_remain_explicit(self):
        item=dict(id='effect',text='Скрип-скрип.',description='Скрип колёс телеги',count=1,chapters={1},
                  variants={'Скрип-скрип.'},choice={},generated_file='')
        with patch('book_sounds.entries',return_value=[item]):self.dialog.sounds.refresh()
        fallback=self.dialog.sounds.table.cellWidget(0,3)
        self.assertEqual(fallback.currentData(),'auto')
        with patch('book_sounds.save') as save,patch.object(self.dialog.sounds,'refresh'):
            fallback.setCurrentIndex(fallback.findData('narrator'))
            self.assertEqual(save.call_args.args[2]['fallback'],'narrator')
            fallback.setCurrentIndex(fallback.findData('skip'))
            self.assertEqual(save.call_args.args[2]['fallback'],'skip')

    def test_manual_file_preview_has_priority_over_cached_ai_effect(self):
        manual=self.root/'manual.wav';generated=self.root/'generated.wav'
        item=dict(id='effect',text='Скрип.',description='Колёса телеги',count=1,chapters={1},variants={'Скрип.'},
                  choice=dict(file=str(manual),fallback='auto'),generated_file=str(generated))
        with patch('book_sounds.entries',return_value=[item]):self.dialog.sounds.refresh()
        buttons=self.dialog.sounds.table.cellWidget(0,2).findChildren(QPushButton)
        with patch('sound_ui.QDesktopServices.openUrl') as play:
            buttons[1].click()
        self.assertEqual(Path(play.call_args.args[0].toLocalFile()).resolve(),manual.resolve())


if __name__=='__main__':unittest.main()
