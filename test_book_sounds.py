import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import soundfile as sf
import book_engine as b
import book_sounds as sounds
from compact_roles import units,reconcile
from roles_analysis import ensure_schema

class SoundTests(unittest.TestCase):
    def test_formatting_variants_share_group_but_different_sources_do_not(self):
        variants=[dict(text=t,sound_description='Оглушительный взрыв') for t in ('*Бум!','Бум!','Бум!*',' бум… ')]
        self.assertEqual(len({sounds.identity(p) for p in variants}),1)
        self.assertNotEqual(sounds.identity(dict(text='Скрип',sound_description='Стул')),sounds.identity(dict(text='Скрип',sound_description='Дверь')))
        meta={'sounds':{sounds.identity(variants[0]):{'fallback':'skip'}}}
        self.assertTrue(all(sounds.plan(p,meta) is None for p in variants))
        legacy={'sounds':{sounds.legacy_identity(variants[0]):{'fallback':'skip'}}}
        self.assertIsNone(sounds.plan(variants[0],legacy))

    def test_groups_merge_existing_settings_and_count_occurrences(self):
        import sqlite3
        from contextlib import contextmanager
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE segments(id INTEGER,chapter INTEGER,parts TEXT)')
        variants=[dict(text=t,kind='sound',speaker='',sound_description='Взрыв') for t in ('*Бум!','Бум!','Бум!*')]
        for i,p in enumerate(variants):db.execute('INSERT INTO segments VALUES(?,?,?)',(i,i+1,json.dumps([p])))
        @contextmanager
        def connect(_):yield db
        meta={'sounds':{sounds.legacy_identity(variants[1]):{'file':'saved.wav','fallback':'skip'}}}
        with patch.object(b,'connect',connect),patch.object(b,'metadata',return_value=meta),patch.object(b,'save_meta'),patch('book_state.refresh_audio'),patch('book_state.snapshot'):
            items=sounds.entries('book')
        self.assertEqual(len(items),1);self.assertEqual(items[0]['count'],3)
        self.assertEqual(items[0]['chapters'],{1,2,3})
        self.assertEqual(meta['sounds'][sounds.identity(variants[0])]['file'],'saved.wav')
        self.assertFalse(items[0]['conflict']);db.close()

    def test_render_inserts_file_without_tts_and_persists_choice(self):
        import avatar_store as store
        import book_state as state
        import roles_analysis as roles
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with patch.object(b,'BOOKS',root/'books'),patch.object(store,'DATA',root):
                src=root/'book.txt';src.write_text('*Стук*',encoding='utf-8')
                b.import_book(src,'test',lambda *a:None);state.migrate('test')
                cue=dict(text='*Стук*',kind='sound',speaker='',sound_description='Стук двери')
                with b.connect('test') as db:
                    roles.ensure_schema(db)
                    roles.apply_result(db,dict(characters=[],assignments=[dict(id=1,speaker='',uncertain=False,parts=[cue])]))
                    db.execute('UPDATE segments SET analyzed=1')
                    db.execute("UPDATE chapters SET title=''")
                db.close();state.snapshot('test')
                wav=root/'effect.wav';sf.write(wav,np.sin(np.arange(24000)*.1)*.1,24000)
                imported=sounds.import_audio('test',wav)
                sounds.save('test',sounds.identity(cue),dict(file=imported,fallback='skip'))
                self.assertEqual(sounds.entries('test')[0]['description'],'Стук двери')
                class NoTTS:
                    def synthesize_book_clip(self,*args,**kwargs):raise AssertionError('Effect was sent to TTS')
                result=b.render('test',NoTTS(),lambda *a:None,chapter_id=1)
                self.assertTrue(Path(result).is_file())
                self.assertEqual(sf.info(str(Path(result).with_suffix('.wav'))).frames,24000)
                data=json.loads((b.folder('test')/'markup.json').read_text(encoding='utf-8'))
                self.assertEqual(data['sounds'][sounds.identity(cue)]['file'],imported)
                db.close()
                import gc
                gc.collect()

    def test_ai_sound_survives_validation_and_merge(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        db.execute("CREATE TABLE characters(name TEXT PRIMARY KEY,avatar TEXT DEFAULT '',mentions INTEGER DEFAULT 0)");ensure_schema(db)
        text='Он встал. *Скрип* Стул отодвинулся.'
        parts=[dict(unit_id=u['unit_id'],speaker='',kind='sound' if u['text']=='*Скрип*' else 'content',sound_description='Скрип стула' if u['text']=='*Скрип*' else '') for u in units(text)]
        raw=dict(characters=[],summary='',assignments=[dict(id=1,speaker='',uncertain=False,parts=parts,number_readings=[])])
        result=reconcile(raw,[dict(id=1,text=text)],db,compact=True)['assignments'][0]['parts']
        self.assertEqual(''.join(p['text'] for p in result),text)
        effects=[p for p in result if p.get('kind')=='sound'];self.assertEqual(len(effects),1)
        self.assertEqual(effects[0]['sound_description'],'Скрип стула');db.close()

    def test_plan_order_fallback_and_signature(self):
        cue=dict(text='*Скрип*',kind='sound',speaker='',sound_description='Стул')
        seg=dict(text='',speaker='',parts=json.dumps([dict(text='До.',speaker=''),cue,dict(text='После.',speaker='')]))
        chapter=dict(title='',mode='single',avatar='author');meta=dict(default_avatar='author')
        p=b.segment_plan(seg,chapter,{},meta)
        self.assertTrue(any('Скрип' in x['text'] for x in p));self.assertTrue(all(x['avatar']=='author' for x in p))
        meta['sounds']={sounds.identity(cue):dict(fallback='skip')}
        self.assertFalse(any('Скрип' in x['text'] for x in b.segment_plan(seg,chapter,{},meta)))
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'sound.wav';sf.write(f,np.ones(2400)*.1,24000)
            meta['sounds'][sounds.identity(cue)]['file']=str(f)
            p=b.segment_plan(seg,chapter,{},meta);self.assertEqual(p[1]['sound_file'],str(f));self.assertEqual(p[2]['text'],'После.')
            a=b.plan_signature([p[1]],{},42);sf.write(f,np.zeros(4800),24000)
            self.assertNotEqual(a,b.plan_signature([p[1]],{},42))

    def test_effect_onset_is_not_cleaned(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'audio').mkdir();source=root/'audio'/'00000001.wav'
            signal=np.zeros(24000,dtype='float32');signal[:120]=.2;signal[12000:15000]=.1;sf.write(source,signal,24000)
            plan=[dict(text='*Стук*',avatar='',sound_file=str(source))]
            with patch.object(b,'folder',lambda _:root),patch.object(b,'cancelled',lambda _:None):
                result=b.assemble_chapter_segments('test',[dict(id=1,wav=str(source))],[plan])
            audio,sr=sf.read(result[0]);self.assertEqual(len(audio),len(signal));self.assertGreater(audio[0],.19)

if __name__=='__main__':unittest.main()
