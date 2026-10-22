"""Source-safe SFX metadata, durable preparation and retained speech takes."""
from contextlib import closing
import gc
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

import avatar_store as store
import book_engine as books
import book_sounds as sounds
import book_state as state
import compact_roles
import roles_analysis as roles
from remote_ssh import Cancelled


class SoundGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.changes=[patch.object(store,'DATA',self.root),patch.object(books,'BOOKS',self.root/'books'),
                      patch('tts_settings.settings',return_value=dict(mode='remote',music_enabled=False))]
        for change in self.changes:change.start()
    def tearDown(self):
        for change in reversed(self.changes):change.stop()
        gc.collect();self.temp.cleanup()

    def book(self,parts):
        source=self.root/'book.txt';source.write_text('\n\n'.join(p['text'] for p in parts),encoding='utf-8')
        books.import_book(source,'book',lambda *args:None);state.migrate('book')
        with closing(books.connect('book')) as db,db:
            db.execute("UPDATE chapters SET title=''")
            rows=list(db.execute('SELECT id FROM segments ORDER BY id'))
            self.assertEqual(len(rows),len(parts))
            for row,part in zip(rows,parts):
                db.execute('UPDATE segments SET parts=?,analyzed=1 WHERE id=?',
                           (json.dumps([part],ensure_ascii=False),row['id']))
        state.update('book',analysis_complete=True,sound_generation_enabled=True)

    @staticmethod
    def cue(text='Скрип-скрип.',prompt='Two dry wooden cart axle creaks outdoors.'):
        return dict(text=text,speaker='',kind='sound',sound_description='Скрип колёс деревянной телеги',
                    sound_prompt=prompt,sound_duration=2.)

    def effect(self,name='effect.wav'):
        path=self.root/name;wave=np.zeros(48000,dtype='float32')
        wave[6000:36000]=.02*np.sin(np.arange(30000)*.08)
        sf.write(path,wave,24000,subtype='PCM_24')
        return path

    def test_optional_fields_are_bounded_and_preserved_by_compact_source_decode(self):
        cue=self.cue();self.book([cue])
        with closing(books.connect('book')) as db,db:
            roles.ensure_schema(db)
            row=dict(db.execute('SELECT id,text FROM segments').fetchone())
            raw=dict(characters=[],summary='Колёса скрипнули.',assignments=[dict(id=row['id'],speaker='',
                uncertain=False,parts=[dict(unit_id=0,**{k:v for k,v in cue.items() if k!='text'})])])
            result=compact_roles.reconcile(raw,[row],db,compact=True)
            roles.apply_result(db,result)
            saved=db.execute('SELECT text,parts FROM segments').fetchone()
        decoded=json.loads(saved['parts'])[0]
        self.assertEqual(saved['text'],cue['text']);self.assertEqual(decoded['text'],cue['text'])
        self.assertEqual(decoded['sound_prompt'],cue['sound_prompt']);self.assertEqual(decoded['sound_duration'],2.)
        for schema in (roles.schema([1]),compact_roles.schema([1])):
            item=schema['properties']['assignments']['items']['properties']['parts']['items']
            self.assertNotIn('sound_prompt',item['required']);self.assertNotIn('sound_duration',item['required'])
            self.assertEqual(item['properties']['sound_duration']['maximum'],12)
        for fields in (dict(sound_prompt='Скрип колёс'),dict(sound_prompt={}),dict(sound_prompt='x'),
                       dict(sound_duration=True),dict(sound_duration=float('nan')),dict(sound_duration=12.1),
                       dict(kind='content',sound_prompt='A wooden cart creak.')):
            with self.subTest(fields=fields),self.assertRaises(ValueError):sounds.validate_part(dict(cue,**fields))

    def test_legacy_russian_description_and_missing_description_remain_usable(self):
        from sound_engine import specification
        for part in (dict(text='*Скрип*',kind='sound',speaker='',sound_description='Скрип отодвигаемого стула'),
                     dict(text='Тук.',kind='sound',speaker='')):
            saved=dict(part)
            request=sounds.generation_input(part,dict(seed=7))
            self.assertTrue(specification(request)['prompt'].startswith('TrackType: SFX.'))
            self.assertEqual(part,saved);self.assertEqual(request['sound_seed'],7)

    def test_between_cue_cancel_keeps_completed_effect_and_resume_reuses_it(self):
        first=self.cue();second=self.cue('Стук.','One quiet knock on a wooden door indoors.')
        self.book([first,second])
        originals=[]
        with closing(books.connect('book')) as db:
            originals=[tuple(r) for r in db.execute('SELECT text,parts FROM segments ORDER BY id')]
        cache={};generated=[]
        def cached(part,directory):return cache.get(part['sound_prompt'])
        def generate(part,directory,progress,cancel):
            path=str(self.effect(f'effect-{len(generated)}.wav'));cache[part['sound_prompt']]=path
            generated.append(part['sound_prompt']);return path
        boundaries=[0]
        def stop():
            boundaries[0]+=1
            if boundaries[0]==2:raise Cancelled('stopped after completed cue')
        with patch('sound_engine.cached_path',side_effect=cached),patch('sound_engine.generate',side_effect=generate):
            with self.assertRaises(Cancelled):sounds.prepare('book',boundary=stop)
            self.assertEqual(len(books.metadata('book')['generated_sounds']),1)
            sounds.prepare('book')
            sounds.prepare('book')
        self.assertEqual(len(generated),2)
        meta=books.metadata('book')
        self.assertEqual(meta.get('sounds',{}),{})
        self.assertEqual(len(meta['generated_sounds']),2)
        with closing(books.connect('book')) as db:
            self.assertEqual([tuple(r) for r in db.execute('SELECT text,parts FROM segments ORDER BY id')],originals)
        items=sounds.entries('book')
        self.assertTrue(all(item['generated_file'] for item in items))
        self.assertTrue(all(not item['choice'].get('file') for item in items))

    def test_prepare_generates_only_analyzed_sound_parts_in_selected_chapter(self):
        first=self.cue();second=self.cue('Динь.','One small metallic bell rings gently indoors.')
        narrative=dict(text='Слышался скрип колёс деревянной телеги.',speaker='',kind='content')
        self.book([first,second,narrative])
        with closing(books.connect('book')) as db,db:
            db.execute('UPDATE segments SET chapter=2 WHERE id=2')
        effect=self.effect()
        with patch('sound_engine.cached_path',return_value=None),patch('sound_engine.generate',return_value=str(effect)) as generate:
            sounds.prepare('book',chapter_id=1)
            self.assertEqual(generate.call_count,1)
            self.assertEqual(generate.call_args.args[0]['text'],first['text'])
        with closing(books.connect('book')) as db,db:db.execute('UPDATE segments SET analyzed=0 WHERE id=2')
        with patch('sound_engine.cached_path',return_value=str(effect)),patch('sound_engine.generate') as generate:
            sounds.prepare('book')
            generate.assert_not_called()

    def test_generated_effect_never_overwrites_retained_raw_voice_take(self):
        cue=self.cue();self.book([cue])
        raw=books.folder('book')/'audio/00000001.wav';raw.parent.mkdir(parents=True)
        sf.write(raw,.1*np.sin(np.arange(24000)*.06),24000,subtype='PCM_24')
        before=hashlib.sha256(raw.read_bytes()).hexdigest()
        with closing(books.connect('book')) as db,db:
            db.execute('UPDATE segments SET wav=?,signature=?',(str(raw),'previous-voice-signature'))
        class NoTTS:
            def synthesize_book_clip(self,*args,**kwargs):raise AssertionError('Pure SFX reached speech model')
        effect=self.effect()
        events=[]
        with patch('sound_engine.cached_path',return_value=None),patch('sound_engine.generate',return_value=str(effect)) as generate:
            result=books.render('book',NoTTS(),lambda *a:None,chapter_id=1,
                                emit=lambda kind,**fields:events.append(kind))
        self.assertTrue(Path(result).is_file());self.assertEqual(generate.call_count,1)
        self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(),before)
        self.assertEqual(sf.info(Path(result).with_suffix('.wav')).frames,48000)
        self.assertIn('sound_progress',events)


if __name__=='__main__':unittest.main()
