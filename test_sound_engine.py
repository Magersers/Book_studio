import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

import avatar_store as store
import sound_engine as engine
from routerai_engine import Cancelled, reset_cancel


class SoundEngineTests(unittest.TestCase):
    def setUp(self):
        reset_cancel()
        self.addCleanup(reset_cancel)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        change=patch.object(store,'DATA',self.root/'data');change.start();self.addCleanup(change.stop)
        self.part=dict(kind='sound',text='Скрип-скрип.',sound_description='Скрип колёс телеги',
                       sound_prompt='Close-up foley of a wooden cart axle creaking twice outdoors. Quiet dry dirt road.',
                       sound_duration=1.5,sound_seed=17)

    def pipeline(self):
        pipeline=MagicMock()
        noise=np.random.default_rng(9).normal(0,.1,(44100*2,2)).astype('float32')
        pipeline.generate.return_value=noise,44100
        return pipeline

    def test_specification_uses_shared_local_medium_sfx_without_music_style(self):
        spec=engine.specification(self.part)
        self.assertTrue(spec['prompt'].startswith('TrackType: SFX.'))
        self.assertNotIn('underscore',spec['prompt'])
        self.assertNotIn('sustained',spec['prompt'])
        self.assertEqual(spec['steps'],8)
        self.assertEqual(spec['sampler'],'lcm')
        self.assertEqual(spec['model'],engine.MUSIC_MODEL)
        self.assertEqual(spec['encoder'],engine.MUSIC_ENCODER)

    def test_prompt_replaces_competing_track_type_and_keeps_context(self):
        part=dict(self.part,sound_prompt='TrackType: Music. Wooden cart wheels creak close to microphone, outdoors.')
        spec=engine.specification(part)
        self.assertEqual(spec['prompt'].count('TrackType:'),1)
        self.assertIn('Wooden cart wheels',spec['prompt'])
        self.assertEqual(spec['target_lufs'],-29.)
        self.assertEqual(spec['true_peak'],-7.)

    def test_bounded_duration_seed_and_prompt_fail_before_connect(self):
        for field,value in (('sound_duration',0),('sound_duration',12.1),('sound_duration',float('nan')),
                            ('sound_duration',True),('sound_seed',1.2),('sound_prompt','x')):
            with self.subTest(field=field,value=value),patch.object(engine,'Pipeline') as pipeline:
                with self.assertRaises(ValueError):engine.generate(dict(self.part,**{field:value}),self.root)
                pipeline.assert_not_called()
        self.assertEqual(engine.specification(dict(self.part,sound_duration=.5))['generation_seconds'],1.)

    def test_local_cache_check_does_not_connect_or_allocate_files(self):
        cache=self.root/'missing'
        with patch.object(engine,'Pipeline') as pipeline:
            self.assertIsNone(engine.cached_path(self.part,cache))
        pipeline.assert_not_called();self.assertFalse(cache.exists())

    def test_generate_retains_native_and_outputs_quiet_exact_mono_cache(self):
        pipeline=self.pipeline();progress=[]
        with patch.object(engine,'Pipeline',return_value=pipeline) as make:
            result=engine.generate(self.part,self.root/'cache',lambda value,message:progress.append((value,message)))
            second=engine.generate(self.part,self.root/'cache')
        self.assertEqual(result,second);self.assertEqual(make.call_count,1)
        make.assert_called_once_with()
        args=pipeline.generate.call_args.args
        self.assertTrue(args[0].startswith('TrackType: SFX.'))
        self.assertEqual(args[1:3],(1.5,17))
        info=sf.info(result)
        self.assertEqual((info.samplerate,info.channels,info.frames),(24000,1,36000))
        report=store.load_json(Path(result).with_suffix('.json'),{})
        native=sf.info(report['native_file'])
        self.assertEqual((native.samplerate,native.channels),(44100,2))
        audio,_=sf.read(result)
        self.assertLess(float(np.max(np.abs(audio))),10**(-7/20)+.001)
        self.assertLess(float(np.sqrt(np.mean(audio**2))),.06)
        self.assertGreater(float(np.sqrt(np.mean(audio**2))),.001)
        self.assertEqual(report['target_lufs'],-29.)
        self.assertEqual(report['specification']['revision'],engine.MUSIC_REVISION)
        self.assertEqual(progress[-1][0],1)

    def test_seed_and_duration_invalidate_effect_cache(self):
        pipeline=self.pipeline()
        with patch.object(engine,'Pipeline',return_value=pipeline):
            first=engine.generate(self.part,self.root/'cache')
            self.assertIsNone(engine.cached_path(dict(self.part,sound_seed=18),self.root/'cache'))
            self.assertIsNone(engine.cached_path(dict(self.part,sound_duration=2.),self.root/'cache'))
            self.assertIsNone(engine.cached_path(dict(self.part,sound_prompt='A wooden door hinge squeals indoors.'),self.root/'cache'))
        self.assertTrue(Path(first).is_file())

    def test_shared_local_runtime_has_sound_labels_and_real_generation_steps(self):
        pipeline=self.pipeline();outputs=pipeline.generate.return_value;events=[]
        def generate(prompt,seconds,seed,progress,cancel):
            progress(1.,'Локальная модель готова')
            progress(None,'Stable Audio 3: загружаем музыкальную модель')
            progress(None,'Stable Audio 3: создаём фоновую музыку')
            progress(.5,'Stable Audio 3: шаг 4/8')
            return outputs
        pipeline.generate.side_effect=generate
        with patch.object(engine,'Pipeline',return_value=pipeline):
            engine.generate(self.part,self.root/'cache',lambda value,message:events.append((value,message)))
        self.assertFalse(any('музык' in message.casefold() for value,message in events))
        self.assertTrue(any(abs(value-.4)<.001 and '4/8' in message for value,message in events if value is not None))

    def test_cancel_during_local_processing_keeps_native_for_resume_without_gpu(self):
        pipeline=self.pipeline()
        with patch.object(engine,'Pipeline',return_value=pipeline),patch.object(engine,'_run',side_effect=Cancelled('stop')):
            with self.assertRaises(Cancelled):engine.generate(self.part,self.root/'cache')
        pipeline.close.assert_called_once()
        self.assertTrue(list((self.root/'cache').glob('*.native.wav')))
        self.assertFalse(list((self.root/'cache').glob('*.partial.wav')))
        with patch.object(engine,'Pipeline',side_effect=AssertionError('Remote generation repeated')):
            result=engine.generate(self.part,self.root/'cache')
        self.assertIsNotNone(engine.cached_path(self.part,self.root/'cache'))
        self.assertTrue(Path(result).is_file())

    def test_failed_local_job_closes_owned_pipeline_without_cache_success(self):
        pipeline=self.pipeline();pipeline.generate.side_effect=Cancelled('Local generation cancelled')
        with patch.object(engine,'Pipeline',return_value=pipeline):
            with self.assertRaises(Cancelled):engine.generate(self.part,self.root/'cache')
        pipeline.close.assert_called_once()
        self.assertIsNone(engine.cached_path(self.part,self.root/'cache'))

    def test_corrupt_processed_cache_reuses_retained_native(self):
        pipeline=self.pipeline()
        with patch.object(engine,'Pipeline',return_value=pipeline):
            result=engine.generate(self.part,self.root/'cache')
        Path(result).write_bytes(b'incomplete')
        self.assertIsNone(engine.cached_path(self.part,self.root/'cache'))
        with patch.object(engine,'Pipeline',side_effect=AssertionError('Remote generation repeated')):
            self.assertEqual(engine.generate(self.part,self.root/'cache'),result)


if __name__=='__main__':unittest.main()
