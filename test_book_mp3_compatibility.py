"""Chapter/full exports decode as standard 44.1 kHz MPEG-1 without paid speech."""
from contextlib import closing
import gc
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

import avatar_store as store
import book_engine as books
import book_state as state


class MP3CompatibilityTests(unittest.TestCase):
    def test_real_chapter_and_whole_book_mp3_are_mpeg1_192k_and_preserve_lossless_speech(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with patch.object(store,'DATA',root),patch.object(books,'BOOKS',root/'books'), \
                    patch('tts_settings.settings',return_value=dict(music_enabled=False,sound_generation_enabled=False)):
                voice=store.save_fish_profile('Автор','7312c38557eb4fb384e3874e8e9cea67')
                source=root/'book.txt';source.write_text('Глава 1\n\nПервый текст.\n\nГлава 2\n\nВторой текст.',encoding='utf-8')
                books.import_book(source,'book',lambda *a:None);state.migrate('book')
                with closing(books.connect('book')) as db,db:
                    db.execute('UPDATE segments SET analyzed=1')
                state.update('book',default_avatar=voice['id'],analysis_complete=True)
                calls=[]
                class Pipeline:
                    uses_voice_ids=True
                    def synthesize_book_clip(self,reference,text,transcript,seed,target,**options):
                        calls.append(text)
                        sf.write(target,np.sin(np.arange(12000)*.08)*.15,24000)
                        return str(target)
                full=Path(books.render('book',Pipeline(),lambda *a:None))
                with closing(books.connect('book')) as db:
                    chapters=[Path(row['output']) for row in db.execute('SELECT output FROM chapters ORDER BY id')]
                self.assertEqual(len(chapters),2)
                self.assertTrue(calls)
                for mp3 in [*chapters,full]:
                    raw=mp3.read_bytes()
                    offset=(10+sum((raw[6+i]&127)<<(21-7*i) for i in range(4))) if raw[:3]==b'ID3' else 0
                    header=int.from_bytes(raw[offset:offset+4],'big')
                    self.assertEqual((header>>21)&0x7ff,0x7ff)
                    self.assertEqual((header>>19)&3,3)  # MPEG-1; MPEG-2 clamps 192k to 160k.
                    self.assertEqual((header>>17)&3,1)  # Layer III.
                    self.assertEqual((header>>12)&15,11)  # 192 kb/s.
                    self.assertEqual((header>>10)&3,0)  # 44.1 kHz.
                    info=sf.info(mp3)
                    self.assertEqual((info.samplerate,info.channels),(44100,2))
                    code='''import json,sys,numpy as np,soundfile as sf
with sf.SoundFile(sys.argv[1]) as f:
    frames=0
    for block in f.blocks(blocksize=65536,dtype="float32"):
        assert np.isfinite(block).all()
        frames+=len(block)
    print(json.dumps(dict(frames=frames)))
'''
                    decoded=subprocess.run([sys.executable,'-c',code,str(mp3)],capture_output=True,
                        text=True,encoding='utf-8',errors='replace',**({'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}))
                    self.assertEqual(decoded.returncode,0,decoded.stderr)
                    self.assertEqual(decoded.stderr,'')
                    self.assertEqual(json.loads(decoded.stdout)['frames'],info.frames)
                for index,mp3 in enumerate(chapters,1):
                    wav=books.folder('book')/f'chapter-{index:04d}.wav'
                    self.assertEqual(sf.info(wav).samplerate,24000)
                    self.assertAlmostEqual(sf.info(wav).duration,sf.info(mp3).duration,delta=.03)
                before=list(calls)
                books.render('book',Pipeline(),lambda *a:None)
                self.assertEqual(calls,before)
            gc.collect()


if __name__=='__main__':unittest.main()
