import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import avatar_store as store
import avatar_folders as folders
import fish_voice_catalog as catalog


class FishVoiceCatalogTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'app'
        self.data = Path(self.temporary.name) / 'user'
        self.path = self.root / catalog.MANIFEST
        self.path.parent.mkdir(parents=True)
        self.voice = dict(id='a'*32, name='Русский рассказчик',
                          description='Спокойный голос для аудиокниг.',
                          languages=['ru'], gender='male', age='middle-aged',
                          tags=['narration', 'calm'], author='Автор каталога',
                          rank=1, task_count=1234, licensed=False,
                          source_url='https://fish.audio/m/'+'a'*32,
                          sample_url='https://platform.r2.fish.audio/sample.mp3')
        self.manifest = dict(version=1, fetched_at='2026-10-22T15:00:00Z', voices=[self.voice])
        self.write()
        self.patch = patch.object(store, 'DATA', self.data)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temporary.cleanup()

    def write(self):
        self.path.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8')

    def test_metadata_only_install_has_real_voice_id_and_categorized_folder(self):
        result = catalog.install(self.root)
        self.assertEqual(result['installed'], ['fish'+'a'*32])
        item = store.get_avatar(result['installed'][0])
        self.assertEqual(item['fish_voice_id'], self.voice['id'])
        self.assertEqual(item['duration'], 0)
        self.assertFalse(store.avatar_path(item).exists())
        self.assertEqual(item['author'], 'Автор каталога')
        self.assertEqual(item['task_count'], 1234)
        self.assertEqual(folders.labels()[item['id']], 'Fish Audio · RU / Мужские / Рассказчики и дикторы')
        self.assertFalse((self.data/'tts-settings.json').exists())

    def test_upgrade_keeps_user_names_archives_folder_moves_and_assignments(self):
        catalog.install(self.root)
        ident = 'fish'+'a'*32
        item = store.get_avatar(ident)
        item.update(name='Мой голос', archived=True)
        profile = self.data/'avatars'/ident/'avatar.json'
        store.atomic_json(profile, item)
        custom = folders.create('Избранное')
        data = folders.load(); data['assignments'][ident] = custom; folders.save(data)
        before = profile.read_bytes()
        self.voice.update(name='Обновлённый рассказчик')
        second = copy.deepcopy(self.voice); second.update(id='b'*32, gender='female', rank=1)
        self.manifest['voices'].append(second); self.write()
        result = catalog.install(self.root)
        self.assertEqual(result['skipped'], [ident])
        self.assertEqual(result['installed'], ['fish'+'b'*32])
        self.assertEqual(profile.read_bytes(), before)
        self.assertEqual(folders.labels()[ident], 'Избранное')
        self.assertIn('Женские', folders.labels()['fish'+'b'*32])
        # Catalog install never reactivates archived records.
        self.assertNotIn(ident, [v['id'] for v in store.avatars()])

    def test_validation_rejects_entire_bad_catalog_before_writing_user_data(self):
        second = copy.deepcopy(self.voice); second['id'] = '../invalid'
        self.manifest['voices'].append(second); self.write()
        with self.assertRaisesRegex(ValueError, 'ID'):
            catalog.install(self.root)
        self.assertFalse(self.data.exists())
        second['id'] = 'b'*32; second['sample_url'] = 'file:///C:/secret.mp3'; self.write()
        with self.assertRaisesRegex(ValueError, 'ссылка'):
            catalog.install(self.root)
        self.assertFalse(self.data.exists())

    def test_manual_fish_voice_saved_without_reference_preserves_existing_metadata(self):
        item = store.save_fish_profile('Николай', 'c'*32)
        self.assertEqual(item['fish_voice_id'], 'c'*32)
        self.assertFalse(store.avatar_path(item).exists())
        group = folders.create('Мои голоса'); folders.move([item['id']], group)
        edited = store.save_fish_profile('Николай — закадровый', 'c'*32, avatar_id=item['id'])
        self.assertEqual(edited['id'], item['id'])
        self.assertEqual(folders.labels()[edited['id']], 'Мои голоса')
        with self.assertRaisesRegex(ValueError, 'Voice ID'):
            store.save_fish_profile('Николай', 'not-an-id')

    def test_actual_shipped_catalog_is_twenty_most_popular_russian_voices(self):
        pack = catalog.read_manifest()
        self.assertEqual(len(pack['voices']), 20)
        self.assertEqual(len({v['id'] for v in pack['voices']}), 20)
        for gender in ('male', 'female'):
            voices = [v for v in pack['voices'] if v['gender'] == gender]
            self.assertEqual(len(voices), 10)
            self.assertEqual([v['rank'] for v in voices], list(range(1, 11)))
            self.assertEqual([v['task_count'] for v in voices], sorted((v['task_count'] for v in voices), reverse=True))
            self.assertTrue(all('ru' in v['languages'] for v in voices))

    def test_metadata_search_and_editor_support_catalog_without_fake_audio(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QPixmap
        from types import SimpleNamespace
        from avatar_tree import AvatarTree, ROLE
        from desktop_app import AvatarDialog
        from book_design import VoicePicker
        app = QApplication.instance() or QApplication([])
        catalog.install(self.root)
        item = store.avatars()[0]
        tree = AvatarTree(SimpleNamespace(busy=False))
        tree.reload(item['id'], lambda _: QPixmap())
        self.assertIn('#1', tree.currentItem().text(0))
        self.assertIn('Автор каталога', tree.currentItem().toolTip(0))
        self.assertNotIn('0 сек', tree.currentItem().text(0))
        for query in ('calm', 'аудиокниг', 'a'*32, 'Автор каталога'):
            tree.set_filter(query)
            self.assertFalse(tree.currentItem().isHidden())
        tree.set_filter('нет такого голоса')
        self.assertTrue(tree.currentItem().isHidden())
        picker = VoicePicker()
        self.assertIn('calm', picker.itemData(1, ROLE+1))
        dialog = AvatarDialog(None, item)
        dialog.validate()
        self.assertEqual(dialog.result(), 1)
        self.assertEqual(dialog.payload()['fish_voice_id'], 'a'*32)
        for widget in (tree, picker, dialog):
            widget.close(); widget.deleteLater()
        app.processEvents()


if __name__ == '__main__':
    unittest.main()
