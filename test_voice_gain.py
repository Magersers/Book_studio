"""Per-book gain is an assembly-only change, preserving paid speech and timing."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import imageio_ffmpeg
import numpy as np
import soundfile as sf

import book_engine as books
import voice_gain


class VoiceGainTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        for change in (patch.object(voice_gain,'ROOT',self.root),patch.object(books,'BOOKS',self.root/'books')):
            change.start();self.addCleanup(change.stop)
        self.source=self.root/'normalized.wav'
        sf.write(self.source,np.sin(np.arange(12000)*2*np.pi*440/24000)*.15,24000,subtype='PCM_24')

    @staticmethod
    def checksum(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def test_two_db_is_measurable_after_normalization_and_frames_and_original_are_unchanged(self):
        original=self.checksum(self.source)
        output=voice_gain.gained_file(self.source,2)
        before,rate=sf.read(self.source);after,after_rate=sf.read(output)
        measured=20*np.log10(np.sqrt(np.mean(after**2))/np.sqrt(np.mean(before**2)))
        self.assertAlmostEqual(measured,2.,delta=.01)
        self.assertEqual((len(after),after_rate),(len(before),rate))
        self.assertEqual(self.checksum(self.source),original)
        with patch('audio_level.run',side_effect=AssertionError('Cache should avoid another gain pass')):
            self.assertEqual(voice_gain.gained_file(self.source,2),output)
        self.assertEqual(voice_gain.gained_file(self.source,0),self.source.resolve())

    def test_limiter_preserves_frames_and_limits_oversampled_true_peak(self):
        sf.write(self.source,np.sin(np.arange(12001)*2*np.pi*6800/24000)*.85,24000,subtype='PCM_24')
        output=voice_gain.gained_file(self.source,2)
        args=[imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-i',str(output),
              '-af','aresample=96000','-f','f32le','-acodec','pcm_f32le','-']
        result=subprocess.run(args,capture_output=True,**({'creationflags':subprocess.CREATE_NO_WINDOW} if hasattr(subprocess,'CREATE_NO_WINDOW') else {}))
        self.assertEqual(result.returncode,0,result.stderr)
        samples=np.frombuffer(result.stdout,dtype='<f4')
        self.assertTrue(np.isfinite(samples).all())
        self.assertLessEqual(float(np.max(np.abs(samples))),10**(-1/20))
        self.assertEqual(sf.info(output).frames,sf.info(self.source).frames)

    def test_invalid_gains_are_noops_and_corrupt_gain_cache_is_rebuilt(self):
        for value in (None,'2',float('nan'),float('inf'),True):
            self.assertEqual(voice_gain.gain_for({'voice':value},'voice'),0)
        self.assertEqual(voice_gain.gain_for({'voice':99},'voice'),12)
        output=voice_gain.gained_file(self.source,2);good=self.checksum(output)
        output.write_bytes(b'corrupted cached gain')
        self.assertEqual(voice_gain.gained_file(self.source,2),output)
        self.assertEqual(self.checksum(output),good)

    def test_only_selected_voice_gets_gain_after_normalization_and_default_revision_is_reused(self):
        book=books.folder('book');cache=book/'audio';cache.mkdir(parents=True)
        narrator=cache/'00000001-part-000.wav';actor=cache/'00000001-part-001.wav';effect=self.root/'effect.wav'
        for path,amplitude in ((narrator,.15),(actor,.1),(effect,.08)):
            sf.write(path,np.sin(np.arange(12000)*.08)*amplitude,24000,subtype='PCM_24')
        narrator.with_suffix('.cleanup.json').write_text('{"api_request_attempts":1}',encoding='utf-8')
        originals={path:self.checksum(path) for path in (narrator,actor,effect,narrator.with_suffix('.cleanup.json'))}
        plan=[dict(text='Слова автора.',avatar='mita'),dict(text='Реплика героя.',avatar='actor'),
              dict(text='Скрип.',sound_file=str(effect))]
        voices={'mita':dict(fish_voice_id='6dc11f3f67a543f6ad4537a4a347e224'),
                'actor':dict(fish_voice_id='7312c38557eb4fb384e3874e8e9cea67')}
        signature=books.plan_signature(plan,voices,42)
        segment=dict(id=1,wav=str(cache/'00000001.wav'))
        books.save_meta('book',{})
        observed=[];stitch=books.stitch
        def capture(paths,*args,**kwargs):
            observed.append(list(map(str,paths)));return stitch(paths,*args,**kwargs)
        with patch('audio_level.normalized_file',side_effect=lambda path:Path(path)) as normalized, \
                patch('book_engine.stitch',side_effect=capture):
            baseline=books.assemble_chapter_segments('book',[segment],[plan])[0]
            books.save_meta('book',dict(voice_gain_db={'mita':2,'actor':0}))
            boosted=books.assemble_chapter_segments('book',[segment],[plan])[0]
            self.assertNotEqual(boosted,baseline)
            self.assertNotEqual(observed[1][0],observed[0][0])
            self.assertEqual(observed[1][1:],observed[0][1:])
            self.assertEqual(normalized.call_count,4)  # Two speech clips per assembly; never SFX.
            normalized.reset_mock()
            self.assertEqual(books.assemble_chapter_segments('book',[segment],[plan])[0],boosted)
            normalized.assert_not_called()
            books.save_meta('book',dict(voice_gain_db={'mita':0}))
            self.assertEqual(books.assemble_chapter_segments('book',[segment],[plan])[0],baseline)
        self.assertEqual(books.plan_signature(plan,voices,42),signature)
        for path,digest in originals.items():self.assertEqual(self.checksum(path),digest)


if __name__=='__main__':unittest.main()
