"""Actor metadata survives source validation; only Drama receives sound cues."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import avatar_store as store
import book_engine as books
import compact_roles
import drama3_performance as performance
import roles_analysis as roles
from roles_text import split_author_insertions
import tts_settings


class PerformanceIntegrationTests(unittest.TestCase):
    def db(self, text):
        db = sqlite3.connect(':memory:')
        db.row_factory = sqlite3.Row
        db.executescript("CREATE TABLE characters(name TEXT PRIMARY KEY,avatar TEXT DEFAULT '',mentions INTEGER DEFAULT 0);"
            "CREATE TABLE segments(id INTEGER PRIMARY KEY,chapter INTEGER,text TEXT,speaker TEXT DEFAULT '',"
            "manual INTEGER DEFAULT 0,review INTEGER DEFAULT 0,parts TEXT DEFAULT '[]');")
        db.execute('INSERT INTO characters(name) VALUES(?)', ('Рик',))
        db.execute('INSERT INTO segments(id,chapter,text) VALUES(1,1,?)', (text,))
        roles.ensure_schema(db)
        self.addCleanup(db.close)
        return db

    @staticmethod
    def result(parts):
        return dict(characters=[], summary='Рик рассмеялся.', assignments=[
            dict(id=1, speaker='Рик', uncertain=False, parts=parts)])

    def test_optional_bounded_field_in_both_analysis_schemas_and_prompts(self):
        full = roles.schema([1])['properties']['assignments']['items']['properties']['parts']['items']
        compact = compact_roles.schema([1])['properties']['assignments']['items']['properties']['parts']['items']
        for schema in (full, compact):
            self.assertEqual(schema['properties']['performance']['enum'], list(performance.SUPPORTED))
            self.assertNotIn('performance', schema['required'])
        for compact in (False, True):
            prompt = roles.prompt([dict(id=1, text='— Ха!')], [], '', '', compact=compact)
            self.assertIn(performance.INSTRUCTION, prompt)

    def test_validation_and_storage_keep_source_and_actor_boundary_exact(self):
        source = '— Ха! Ты угадал, — рассмеялся Рик. — Идём.'
        parts = [dict(text='— Ха! Ты угадал,', speaker='Рик', performance='laughs'),
                 dict(text=' — рассмеялся Рик.', speaker=''), dict(text=' — Идём.', speaker='Рик')]
        db = self.db(source)
        result = self.result(parts)
        roles.validate(result, [dict(id=1, text=source)], db)
        roles.apply_result(db, result)
        saved = db.execute('SELECT * FROM segments').fetchone()
        stored = json.loads(saved['parts'])
        self.assertEqual(saved['text'], source)
        self.assertEqual(''.join(p['text'] for p in stored), source)
        self.assertEqual(stored[0]['performance'], 'laughs')
        self.assertEqual(stored[1]['speaker'], '')
        self.assertNotIn('performance', stored[1])
        self.assertNotIn('performance', stored[2])
        self.assertEqual(stored[0]['speaker'], 'Рик')

    def test_author_split_never_copies_actor_sound_to_narrator_or_continuation(self):
        source = '— Ха! — рассмеялся Рик. — Продолжим.'
        original = dict(text=source, speaker='Рик', performance='chuckles')
        before = copy.deepcopy(original)
        parts = split_author_insertions([original])
        self.assertEqual(''.join(p['text'] for p in parts), source)
        self.assertEqual(original, before)
        self.assertEqual(parts[0]['performance'], 'chuckles')
        self.assertEqual(parts[1]['speaker'], '')
        self.assertNotIn('performance', parts[1])
        self.assertNotIn('performance', parts[2])

    def test_invalid_metadata_and_changed_source_are_rejected(self):
        source = '— Ха!'
        db = self.db(source)
        for bad in (None, True, {}, [], '[laughs]', 'laughing', 'laughs,chuckles'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                roles.validate(self.result([dict(text=source, speaker='Рик', performance=bad)]),
                               [dict(id=1, text=source)], db)
        with self.assertRaises(ValueError):
            roles.validate(self.result([dict(text='— Хо!', speaker='Рик', performance='laughs')]),
                           [dict(id=1, text=source)], db)
        with self.assertRaises(ValueError):
            roles.validate(self.result([dict(text=source, speaker='', performance='laughs')]),
                           [dict(id=1, text=source)], db)
        with self.assertRaises(ValueError):
            roles.validate(self.result(['not an object']), [dict(id=1, text=source)], db)

    def test_compact_decode_retains_performance_without_merging_adjacent_speech(self):
        source = '— Ха! Ты угадал.'
        db = self.db(source)
        units = compact_roles.units(source)
        self.assertGreaterEqual(len(units), 2)
        encoded = [dict(unit_id=u['unit_id'], speaker='Рик', kind='content',
                        **({'performance': 'laughs'} if index == 0 else {}))
                   for index, u in enumerate(units)]
        raw = self.result(encoded)
        result = compact_roles.reconcile(raw, [dict(id=1, text=source)], db, compact=True)
        parts = result['assignments'][0]['parts']
        self.assertEqual(''.join(p['text'] for p in parts), source)
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0]['performance'], 'laughs')
        self.assertNotIn('performance', parts[1])
        segment=dict(text=source,speaker='Рик',parts=json.dumps(parts,ensure_ascii=False))
        before=copy.deepcopy(segment)
        with patch('runtime_config.tts_id',return_value=tts_settings.MODEL_ID):
            plan=books.segment_plan(segment,dict(title='Глава',mode='roles',avatar=''),{'Рик':'actor'},{})
        self.assertEqual(plan,[dict(text='[laughs heartily] Ты угадал.',avatar='actor',performance='laughs')])
        self.assertEqual(segment,before)

    def test_drama_plan_transforms_only_actor_stream_and_cache_signature(self):
        source = '— Ха! Ты угадал. Рик рассмеялся.'
        parts = [dict(text='— Ха! Ты угадал.', speaker='Рик', performance='laughs'),
                 dict(text=' Рик рассмеялся.', speaker='')]
        segment = dict(text=source, speaker='Рик', parts=json.dumps(parts, ensure_ascii=False))
        before = copy.deepcopy(segment)
        chapter = dict(title='Другая глава', mode='roles', avatar='')
        meta = dict(default_avatar='narrator')
        with patch('runtime_config.tts_id', return_value=tts_settings.MODEL_ID):
            plan = books.segment_plan(segment, chapter, {'Рик': 'actor'}, meta)
            self.assertEqual(plan, [dict(text='[laughs heartily] Ты угадал.', avatar='actor', performance='laughs'),
                                    dict(text='Рик рассмеялся.', avatar='narrator')])
            plain = dict(segment, parts=json.dumps([dict(p, performance='none') for p in parts]))
            unperformed = books.segment_plan(plain, chapter, {'Рик': 'actor'}, meta)
            with tempfile.TemporaryDirectory() as temp:
                reference = Path(temp)/'reference.wav'; reference.touch()
                voices = {name: dict(id=name) for name in ('actor', 'narrator')}
                with patch.object(store, 'avatar_path', return_value=reference):
                    self.assertNotEqual(books.plan_signature(plan, voices, 42),
                                        books.plan_signature(unperformed, voices, 42))
        self.assertEqual(segment, before)
        with patch('runtime_config.tts_id', return_value='qwen-book-v1'):
            local = books.segment_plan(segment, chapter, {'Рик': 'actor'}, meta)
        self.assertIn('Ха!', local[0]['text'])
        self.assertNotIn('[laughs', ' '.join(p['text'] for p in local))

    def test_single_voice_still_keeps_actor_sound_out_of_author_request(self):
        parts = [dict(text='— Ха! Ты угадал.', speaker='Рик', performance='laughs'),
                 dict(text=' Рик рассмеялся.', speaker=''), dict(text=' — Пойдём.', speaker='Рик')]
        segment = dict(text=''.join(p['text'] for p in parts), speaker='Рик',
                       parts=json.dumps(parts, ensure_ascii=False))
        from narrator_profiles import VERSION
        with patch('runtime_config.tts_id', return_value=tts_settings.MODEL_ID):
            plan = books.segment_plan(segment, dict(title='Глава', mode='single', avatar=''),
                                      {'Рик': 'actor'}, dict(default_avatar='narrator', narrator_profiles=VERSION))
        self.assertEqual(len(plan), 3)
        self.assertEqual(plan[0]['text'], '[laughs heartily] Ты угадал.')
        self.assertEqual(plan[1]['text'], 'Рик рассмеялся.')
        self.assertEqual(plan[2]['text'], '— Пойдём.')
        self.assertTrue(all(p['avatar'] == 'narrator' for p in plan))

    def test_confirmed_actor_onset_survives_artifact_muting_and_join_cache(self):
        import numpy as np
        import soundfile as sf
        from audio_cleanup import pre_speech_artifact
        sr = 24000
        wave = np.zeros(sr, dtype='float32')
        time = np.arange(round(sr*.12))/sr
        wave[:len(time)] = .2*np.cos(2*np.pi*180*time)*np.exp(-time/.012)
        wave[round(sr*.3):round(sr*.9)] = .03*np.sin(np.arange(round(sr*.6))*.06)
        self.assertGreater(pre_speech_artifact(wave, sr), 0)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'audio').mkdir()
            source = root/'audio/00000001.wav'; sf.write(source, wave, sr)
            plain = [dict(text='[chuckles] Верно.', avatar='actor')]
            directed = [dict(plain[0], performance='chuckles')]
            segment = [dict(id=1, wav=str(source))]
            with patch.object(books, 'folder', return_value=root), patch.object(books, 'cancelled'), \
                 patch('audio_level.normalized_file', side_effect=lambda path: path) as normalize:
                old = books.assemble_chapter_segments('book', segment, [plain])[0]
                protected = books.assemble_chapter_segments('book', segment, [directed])[0]
            old_audio, _ = sf.read(old)
            kept_audio, _ = sf.read(protected)
            # A distinct cache revision prevents reusing an earlier muted join.
            self.assertNotEqual(old, protected)
            self.assertLess(float(np.max(np.abs(old_audio[:1440]))), .04)
            self.assertGreater(float(np.max(np.abs(kept_audio[:1440]))), .08)
            self.assertEqual(normalize.call_count, 2)

    def test_only_first_directed_chunk_is_protected_and_questions_stay_ordinary(self):
        text = '— Ха! ' + 'Это длинная реплика. '*55
        part = dict(text=text, speaker='Рик', performance='laughs')
        segment = dict(text=text, speaker='Рик', parts=json.dumps([part], ensure_ascii=False))
        chapter = dict(title='Глава', mode='roles', avatar='')
        with patch('runtime_config.tts_id', return_value=tts_settings.MODEL_ID):
            plan = books.segment_plan(segment, chapter, {'Рик': 'actor'}, {})
            self.assertGreater(len(plan), 1)
            self.assertEqual([p.get('performance') for p in plan].count('laughs'), 1)
            question = dict(text='— Ха? Ты о чём?', speaker='Рик', performance='laughs')
            segment = dict(text=question['text'], speaker='Рик', parts=json.dumps([question]))
            plan = books.segment_plan(segment, chapter, {'Рик': 'actor'}, {})
        self.assertNotIn('performance', plan[0])
        self.assertEqual(plan[0]['text'], question['text'])

    def test_production_plan_never_submits_a_tag_only_vocal_generation(self):
        for source, action in (('— Ха!', 'laughs'), ('Хехе.', 'chuckles')):
            part = dict(text=source, speaker='Рик', performance=action)
            segment = dict(text=source, speaker='Рик', parts=json.dumps([part], ensure_ascii=False))
            with self.subTest(source=source), patch('runtime_config.tts_id', return_value=tts_settings.MODEL_ID):
                plan = books.segment_plan(segment, dict(title='Глава', mode='roles', avatar=''),
                                          {'Рик': 'actor'}, {})
            self.assertEqual(plan, [dict(text=source.lstrip('— '), avatar='actor')])

    def test_inline_scaffold_never_crosses_an_author_or_service_boundary(self):
        for boundary in (dict(text=' Рик рассмеялся.',speaker=''),
                         dict(text=' Издательство.',speaker='',kind='credits')):
            parts=[dict(text='— Ха!',speaker='Рик',performance='laughs'),
                   boundary,dict(text=' — Продолжим.',speaker='Рик')]
            segment=dict(text=''.join(p['text'] for p in parts),speaker='Рик',parts=json.dumps(parts,ensure_ascii=False))
            with self.subTest(boundary=boundary),patch('runtime_config.tts_id',return_value=tts_settings.MODEL_ID):
                plan=books.segment_plan(segment,dict(title='Глава',mode='roles',avatar=''),
                                        {'Рик':'actor'},dict(default_avatar='narrator'))
            self.assertEqual(plan[0]['text'],'Ха!')
            self.assertTrue(all('performance' not in p for p in plan))


if __name__ == '__main__':
    unittest.main()
