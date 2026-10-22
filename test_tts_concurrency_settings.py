import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import avatar_store as store
import tts_settings as settings


class ConcurrencyPreferences(unittest.TestCase):
    def test_old_preferences_get_safe_default_and_other_saves_preserve_choice(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(store, 'DATA', Path(temporary)):
            self.assertEqual(settings.settings()['api_workers'], 3)
            settings.save(api_workers=5)
            settings.save(music_enabled=True)
            self.assertEqual(settings.settings()['api_workers'], 5)
            self.assertTrue(settings.settings()['music_enabled'])

    def test_rejects_out_of_range_and_noninteger_without_mutating(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(store, 'DATA', Path(temporary)):
            settings.save(api_workers=2)
            before=settings.path().read_bytes()
            for value in (0, 9, -1, True, 2.5, '3'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    settings.save(api_workers=value)
                self.assertEqual(settings.path().read_bytes(), before)

    def test_dialog_restores_and_serializes_user_choice(self):
        from PySide6.QtWidgets import QApplication
        from tts_settings_ui import TTSSettingsDialog
        application=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary, patch.object(store, 'DATA', Path(temporary)):
            settings.save(api_workers=4)
            dialog=TTSSettingsDialog()
            try:
                self.assertEqual(dialog.api_workers.value(),4)
                self.assertEqual((dialog.api_workers.minimum(),dialog.api_workers.maximum()),(1,8))
                dialog.api_workers.setValue(6)
                self.assertEqual(dialog.values()['api_workers'],6)
            finally:
                dialog.close()


if __name__=='__main__':unittest.main()
