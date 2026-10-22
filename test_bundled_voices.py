import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

import avatar_store as store
import bundled_voices as bundled


class BundledVoicesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base/'application'
        self.data = self.base/'user-data'
        self.assets = self.root/'assets/voices'
        self.assets.mkdir(parents=True)
        self.voice = dict(id='studionarrator', name='Новый рассказчик',
            file='assets/voices/studionarrator.wav', transcript='Точный текст чистого образца.',
            duration=3., description='Спокойный взрослый баритон.', gender='male',
            source=dict(url='https://example.org/voice/narrator', title='Reference voice',
                        license='Test fixture, generated silent PCM.'))
        self.write_audio(self.voice)
        self.manifest = dict(version=1, pack_id='studiotest', voices=[self.voice])
        self.save_manifest()
        self.data_patch = patch.object(store, 'DATA', self.data)
        self.data_patch.start()

    def tearDown(self):
        self.data_patch.stop()
        self.temporary.cleanup()

    def write_audio(self, voice):
        path = self.root/voice['file']
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(3); audio.setframerate(24000)
            audio.writeframes(b'\0'*3*24000*3)
        voice['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

    def save_manifest(self):
        (self.assets/'manifest.json').write_text(json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8')

    def test_first_launch_contains_ready_reference_and_provenance_without_models(self):
        result = bundled.install(self.root)
        self.assertEqual(result, dict(installed=['studionarrator'], skipped=[]))
        avatar = store.get_avatar('studionarrator')
        self.assertEqual(avatar['name'], self.voice['name'])
        self.assertEqual(avatar['transcript'], self.voice['transcript'])
        self.assertEqual(avatar['description'], self.voice['description'])
        self.assertEqual(avatar['source'], self.voice['source'])
        self.assertEqual(avatar['bundled_pack'], 'studiotest')
        self.assertEqual(store.avatar_path(avatar).read_bytes(), (self.root/self.voice['file']).read_bytes())
        self.assertEqual([a['id'] for a in store.avatars()], ['studionarrator'])
        import avatar_folders as folders
        self.assertEqual(folders.labels()['studionarrator'], 'Студийные · RU')
        self.assertFalse((self.data/'tts-settings.json').exists())

    def test_upgrade_keeps_edited_and_archived_voices_and_book_assignments(self):
        bundled.install(self.root)
        avatar = store.get_avatar('studionarrator')
        avatar.update(name='Мой рассказчик', archived=True, transcript='Моя расшифровка')
        profile = self.data/'avatars/studionarrator/avatar.json'
        store.atomic_json(profile, avatar)
        reference = profile.parent/'reference.wav'
        reference.write_bytes(b'User reference stays unchanged')
        assignments = self.data/'books/existing/book.json'
        store.atomic_json(assignments, dict(default_avatar='myexistingvoice'))
        before = {p: p.read_bytes() for p in (profile, reference, assignments)}
        import avatar_folders as folders
        custom_folder = folders.create('Мои любимые')
        folder_data = folders.load()
        folder_data['assignments']['studionarrator'] = custom_folder
        folders.save(folder_data)
        self.voice['name'] = 'Имя из обновлённого пакета'
        self.save_manifest()
        self.assertEqual(bundled.install(self.root), dict(installed=[], skipped=['studionarrator']))
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(store.avatars(), [])
        second = copy.deepcopy(self.voice)
        second.update(id='studioelder', name='Старый торговец', file='assets/voices/studioelder.wav')
        self.write_audio(second)
        self.manifest['voices'].append(second); self.save_manifest()
        self.assertEqual(bundled.install(self.root)['installed'], ['studioelder'])
        self.assertEqual(folders.labels()['studionarrator'], 'Мои любимые')
        self.assertEqual(folders.labels()['studioelder'], 'Студийные · RU')
        self.assertEqual(sum(f['name']=='Студийные · RU' for f in folders.load()['folders']), 1)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_validation_is_atomic_for_whole_pack_and_rejects_hash_mismatch(self):
        second = copy.deepcopy(self.voice)
        second.update(id='studiobroken', file='assets/voices/studiobroken.wav')
        self.write_audio(second)
        second['sha256'] = '0'*64
        self.manifest['voices'].append(second); self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'целостность'):
            bundled.install(self.root)
        self.assertFalse(self.data.exists())

    def test_voice_rename_keeps_description_and_original_pack_attribution(self):
        bundled.install(self.root)
        original = store.get_avatar('studionarrator')
        edited = store.save_profile('Моё имя', store.avatar_path(original), original['transcript'],
                                    original['duration'], avatar_id=original['id'])
        for key in ('description','gender','source','bundled_pack','bundled_reference_sha256'):
            self.assertEqual(edited[key], original[key])
        self.assertEqual(edited['name'], 'Моё имя')

    def test_interrupted_copy_leaves_no_half_installed_profile_and_can_retry(self):
        with patch.object(bundled.shutil, 'copyfile', side_effect=OSError('Disk full')):
            with self.assertRaisesRegex(OSError, 'Disk full'):
                bundled.install(self.root)
        self.assertFalse((self.data/'avatars/studionarrator').exists())
        self.assertEqual(list((self.data/'avatars').iterdir()), [])
        self.assertEqual(bundled.install(self.root)['installed'], ['studionarrator'])

    def test_changed_sample_during_copy_is_not_installed(self):
        def changed_copy(source, destination):
            Path(destination).write_bytes(b'Changed after validation')
        with patch.object(bundled.shutil, 'copyfile', side_effect=changed_copy):
            with self.assertRaisesRegex(ValueError, 'при копировании'):
                bundled.install(self.root)
        self.assertFalse((self.data/'avatars/studionarrator').exists())

    def test_manifest_cannot_import_external_files_or_duplicate_ids(self):
        for filename in ('../secret.wav', 'assets/voices/../secret.wav', 'C:/outside.wav',
                         'assets/voices/other.wav'):
            with self.subTest(filename=filename):
                self.voice['file'] = filename; self.save_manifest()
                with self.assertRaises(ValueError): bundled.install(self.root)
                self.assertFalse(self.data.exists())
        self.voice['file'] = 'assets/voices/studionarrator.wav'
        self.manifest['voices'].append(dict(self.voice)); self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'идентификатор'):
            bundled.install(self.root)
        self.assertFalse(self.data.exists())

    def test_invalid_pcm_duration_and_private_source_do_not_seed_library(self):
        for field, value in [('duration', True), ('duration', 30.), ('gender', 'invalid')]:
            with self.subTest(field=field, value=value):
                old = self.voice[field]; self.voice[field] = value; self.save_manifest()
                with self.assertRaises(ValueError): bundled.install(self.root)
                self.assertFalse(self.data.exists()); self.voice[field] = old
        self.voice['source']['url'] = 'https://name:password@example.org/reference'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'публичная'):
            bundled.install(self.root)
        self.assertFalse(self.data.exists())

    def test_source_checkout_without_pack_is_a_noop(self):
        (self.assets/'manifest.json').unlink()
        self.assertEqual(bundled.install(self.root), dict(installed=[], skipped=[]))
        self.assertFalse(self.data.exists())


if __name__ == '__main__':
    unittest.main()
