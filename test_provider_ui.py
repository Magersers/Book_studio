import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import avatar_store as store
import analysis_settings as settings
import ui_language
from deepseek_model import list_models,DeepSeekModel
from PySide6.QtWidgets import QApplication
from analysis_settings_ui import AnalysisSettingsDialog

class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(store,'DATA',Path(self.temp.name));p.start();self.addCleanup(p.stop)
    def test_provider_switch_and_manual_model(self):
        dialog=AnalysisSettingsDialog()
        dialog.provider.setCurrentIndex(dialog.provider.findData('openrouter'))
        self.assertEqual(dialog.url.text(),'https://openrouter.ai/api/v1')
        dialog.checked(True,['vendor/one','vendor/two'])
        dialog.model.setCurrentText('vendor/manual-model')
        self.assertEqual(dialog.values()[1],'vendor/manual-model')
        dialog.provider.setCurrentIndex(dialog.provider.findData('compatible'))
        self.assertEqual(dialog.url.text(),'')
        dialog.close()
    @unittest.skipUnless(os.name=='nt','DPAPI')
    def test_custom_profile_persists_and_is_endpoint_bound(self):
        settings.save('compatible','https://example.org/v1','vendor/model','test-key')
        self.assertEqual(settings.settings()['provider'],'compatible')
        settings.save('local');settings.save('compatible','https://example.org/v1','vendor/other')
        self.assertEqual(settings.api_key(),'test-key')
        with self.assertRaises(ValueError):settings.api_key('https://different.example/v1')
    def test_models_list_filters_and_sorts_without_generation(self):
        response=MagicMock();response.__enter__.return_value=response;response.status_code=200
        response.json.return_value={'data':[{'id':'z/model'},{'id':'a/model'},{'id':'a/model'},None,{}]}
        with patch('deepseek_model.requests.get',return_value=response) as get:
            self.assertEqual(list_models('https://example.org/v1','test-key'),['a/model','z/model'])
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
    def test_english_controls_and_persistence_do_not_translate_user_text(self):
        with patch.object(ui_language,'_language','en'):
            dialog=AnalysisSettingsDialog()
            self.assertEqual(dialog.save_button.text(),'Save')
            self.assertEqual(ui_language.tr('Моя книга'), 'Моя книга')
            dialog.close()
        ui_language.save_language('en')
        self.assertEqual(json.loads((store.DATA/'ui-preferences.json').read_text())['language'],'en')

if __name__=='__main__':unittest.main()
