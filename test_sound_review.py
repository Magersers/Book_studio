"""Independent CPU-only review of sound timing and selective book cache reuse."""
from contextlib import closing
import gc
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
from narrator_profiles import VERSION


class SoundReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.changes=[patch.object(store,'DATA',self.root),patch.object(books,'BOOKS',self.root/'books'),
                      patch('tts_settings.settings',return_value=dict(mode='remote',music_enabled=False))]
        for change in self.changes:change.start()
    def tearDown(self):
        for change in reversed(self.changes):change.stop()
        gc.collect();self.temp.cleanup()

    def test_real_render_retains_effect_duration_level_and_unrelated_speech_cache(self):
        source=self.root/'book.txt';source.write_text('Он поднял телегу.\n\nСкрип-скрип.',encoding='utf-8')
        reference=self.root/'reference.wav';sf.write(reference,np.sin(np.arange(24000)*.07)*.1,24000)
        avatar=store.save_profile('Автор',reference,'Точный образец голоса.',1.)
        books.import_book(source,'book',lambda *args:None);state.migrate('book')
        cue=dict(text='Скрип-скрип.',speaker='',kind='sound',sound_description='Скрип колёс деревянной телеги',
                 sound_prompt='Two isolated wooden cart axle creaks, close microphone outdoors.',sound_duration=2.)
        with closing(books.connect('book')) as db,db:
            db.execute("UPDATE chapters SET title='' WHERE id=1")
            db.execute('UPDATE segments SET parts=?,manual=1,analyzed=1 WHERE id=1',
                       (json.dumps([dict(text='Он поднял телегу.',speaker='',kind='content')]),))
            db.execute('UPDATE segments SET parts=?,manual=1,analyzed=1 WHERE id=2',(json.dumps([cue],ensure_ascii=False),))
        state.update('book',default_avatar=avatar['id'],narrator_profiles=VERSION,
                     analysis_complete=True,sound_generation_enabled=True,music_enabled=False)
        raw=books.folder('book')/'audio'/'00000001.wav';raw.parent.mkdir(parents=True)
        sf.write(raw,np.sin(np.arange(24000)*.055)*.12,24000,subtype='PCM_24')
        with closing(books.connect('book')) as db,db:
            row=db.execute('SELECT * FROM segments WHERE id=1').fetchone()
            chapter=db.execute('SELECT * FROM chapters').fetchone()
            plan=books.segment_plan(row,chapter,{},books.metadata('book'))
            speech_signature=books.plan_signature(plan,{avatar['id']:avatar},42)
            db.execute('UPDATE segments SET wav=?,signature=? WHERE id=1',(str(raw),speech_signature))
        raw_mtime=raw.stat().st_mtime_ns
        signal=np.zeros(48000,dtype='float32')
        signal[7200:36000]=np.random.default_rng(4).normal(0,.012,28800)
        first=self.root/'first-effect.wav';second=self.root/'second-effect.wav'
        sf.write(first,signal,24000,subtype='PCM_24');sf.write(second,signal*.8,24000,subtype='PCM_24')
        class NoTTS:
            supports_narrator_styles=True
            supports_progress=True
            def synthesize_book_clip(self,*args,**kwargs):raise AssertionError('Speech cache was invalidated by SFX')
        with patch('sound_engine.cached_path',return_value=None),patch('sound_engine.generate',return_value=str(first)) as generate:
            books.render('book',NoTTS(),lambda *args:None,chapter_id=1)
        generate.assert_called_once()
        dry=books.folder('book')/'chapter-0001.wav'
        written,sr=sf.read(dry,dtype='float32')
        # Speech1s +40ms boundary +effect2s; quiet effect edges are intentional.
        self.assertEqual((len(written),sr),(72960,24000))
        np.testing.assert_allclose(written[24960:],signal,atol=4e-5,rtol=0)
        with closing(books.connect('book')) as db:
            first_signature=db.execute('SELECT signature FROM segments WHERE id=2').fetchone()[0]
        changed=dict(cue,sound_prompt='Two softer isolated cart axle creaks, close microphone outdoors.')
        with closing(books.connect('book')) as db,db:
            db.execute('UPDATE segments SET parts=? WHERE id=2',(json.dumps([changed],ensure_ascii=False),))
        with patch('sound_engine.cached_path',return_value=None),patch('sound_engine.generate',return_value=str(second)):
            books.render('book',NoTTS(),lambda *args:None,chapter_id=1)
        with closing(books.connect('book')) as db:
            rows=list(db.execute('SELECT id,text,parts,signature FROM segments ORDER BY id'))
        self.assertEqual(rows[0]['signature'],speech_signature)
        self.assertNotEqual(rows[1]['signature'],first_signature)
        self.assertEqual(raw.stat().st_mtime_ns,raw_mtime)
        self.assertEqual(rows[1]['text'],'Скрип-скрип.')
        self.assertEqual(json.loads(rows[1]['parts'])[0]['text'],'Скрип-скрип.')

    def test_explicit_manual_file_narrator_and_skip_never_generate(self):
        source=self.root/'book.txt';source.write_text('Скрип-скрип.',encoding='utf-8')
        books.import_book(source,'book',lambda *args:None);state.migrate('book')
        cue=dict(text='Скрип-скрип.',speaker='',kind='sound',sound_description='Колёса телеги',
                 sound_prompt='Wooden cart wheels creak outdoors.',sound_duration=1.)
        with closing(books.connect('book')) as db,db:
            db.execute('UPDATE segments SET parts=?,analyzed=1',(json.dumps([cue]),))
        manual=self.root/'manual.wav';sf.write(manual,np.ones(2400)*.01,24000)
        for choice in (dict(file=str(manual)),dict(fallback='narrator'),dict(fallback='skip')):
            meta=state.update('book',sound_generation_enabled=True,sounds={sounds.identity(cue):choice})
            with patch('sound_engine.cached_path',side_effect=AssertionError('Manual choice probed generated cache')),patch('sound_engine.generate',side_effect=AssertionError('Manual choice generated')):
                sounds.prepare('book')
            plan=sounds.plan(cue,meta)
            if choice.get('file'):self.assertEqual(plan['sound_file'],str(manual))
            elif choice.get('fallback')=='skip':self.assertIsNone(plan)
            else:self.assertEqual(plan['kind'],'content')


if __name__=='__main__':unittest.main()
