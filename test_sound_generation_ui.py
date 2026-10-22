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
            patch('tts_settings.settings',return_value=dict(mode='remote',connection='ssh user@gpu.example',music_enabled=False))]
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
        with patch('tts_settings.settings',return_value=dict(mode='local',music_enabled=False)):
            self.dialog.sounds.update_generation_controls()
            self.assertTrue(checkbox.isEnabled())
            checkbox.setChecked(False)
            self.assertFalse(checkbox.isEnabled())
        self.assertFalse(books.metadata('book')['sound_generation_enabled'])

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
