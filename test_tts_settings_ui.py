import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent
import avatar_store as store
from tts_settings_ui import TTSSettingsDialog, ServerTask


class ServerUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        change = patch.object(store, 'DATA', Path(self.temp.name))
        change.start()
        self.addCleanup(change.stop)
        self.dialog = TTSSettingsDialog()
        self.addCleanup(self.dispose_dialog)

    def dispose_dialog(self):
        # Destroy C++ widgets while QApplication and Python slot objects still
        # exist. Leaving a QDialog with overridden reject() for interpreter
        # teardown can call a half-destroyed Python object on Windows/PySide6.
        self.dialog.close()
        self.dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.dialog = None

    def test_remote_mode_requires_successful_check_for_current_address(self):
        d = self.dialog
        self.assertTrue(d.save_button.isEnabled())
        d.mode.setCurrentIndex(d.mode.findData('remote'))
        d.connection.setText('ssh user@gpu.example -p 1234')
        self.assertFalse(d.save_button.isEnabled())
        d.on_result(True, 'ready')
        d.refresh()
        self.assertTrue(d.save_button.isEnabled())
        d.connection.setText('ssh other@gpu.example -p 1234')
        self.assertFalse(d.save_button.isEnabled())

    def test_byte_progress_and_indeterminate_stages(self):
        d = self.dialog
        d.on_progress(dict(message='PyTorch', value=None))
        self.assertEqual(d.bar.maximum(), 0)
        d.on_progress(dict(message='5 / 10 GB', value=.5))
        self.assertEqual((d.bar.maximum(), d.bar.value()), (1000, 500))
        self.assertEqual(d.status.text(), '5 / 10 GB')

    def test_closing_running_install_requests_cancel_without_blocking(self):
        d = self.dialog
        d.task = MagicMock()
        d.reject()
        d.task.cancel.set.assert_called_once()
        self.assertTrue(d.closing)
        d.on_finished()
        self.assertIsNone(d.task)

    def test_music_is_explicit_optional_and_part_of_verified_configuration(self):
        d=self.dialog
        self.assertFalse(d.music.isChecked())
        self.assertFalse(d.music.isEnabled())
        d.mode.setCurrentIndex(d.mode.findData('remote'))
        d.connection.setText('ssh user@gpu.example -p 1234')
        d.on_result(True,'ready');d.refresh()
        self.assertTrue(d.save_button.isEnabled())
        d.music.setChecked(True)
        self.assertTrue(d.values()['music_enabled'])
        self.assertFalse(d.save_button.isEnabled())
        self.assertIn('музыку',d.install_button.text())
        d.on_result(True,'ready');d.refresh();d.save()
        import tts_settings
        self.assertTrue(tts_settings.settings()['music_enabled'])

    def test_music_setup_requests_optional_weights_and_reports_progress(self):
        task=ServerTask(dict(connection='ssh user@gpu.example',music_enabled=True),True)
        connection=MagicMock();connection.url='http://127.0.0.1:12345'
        result=[];task.result.connect(lambda success,message:result.append(success))
        with patch('remote_ssh.SSHConnection',return_value=connection),patch('requests.Session'):
            task.run()
        self.assertTrue(connection.prepare.call_args.kwargs['music'])
        self.assertTrue(connection.prepare.call_args.kwargs['install'])
        self.assertEqual(result,[True])
        task.deleteLater()


if __name__ == '__main__':
    unittest.main()
