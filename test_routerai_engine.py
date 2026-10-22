"""Voice IDs reach RouterAI, cached audio never crosses voices, failures do not retry."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import requests
import soundfile as sf

import avatar_store as store
import routerai_engine as engine
import tts_settings


VOICE = '7312c38557eb4fb384e3874e8e9cea67'
OTHER_VOICE = '563736b1eb904cb29572f5eb5d9c46d2'


class RouterAISpeechTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        data = patch.object(store, 'DATA', self.root)
        data.start()
        self.addCleanup(data.stop)
        key = patch('tts_settings.api_key', return_value='test-secret-key')
        key.start()
        self.addCleanup(key.stop)
        self.config = dict(base_url=tts_settings.DEFAULT_URL, model=engine.MODEL,
                           fish_options={'temperature': .8})
        self.pipeline = engine.Pipeline(self.config)
        self.addCleanup(self.pipeline.close)

    @staticmethod
    def response(status=200, content_type='audio/mpeg'):
        # An actual audio stream exercises download, ffmpeg and PCM validation.
        audio = io.BytesIO()
        samples = .1 * np.sin(np.arange(4410, dtype='float32') * .06)
        sf.write(audio, samples, 44100, format='WAV', subtype='PCM_16')
        body = audio.getvalue()
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = status
        response.headers = {'Content-Type': content_type, 'Content-Length': str(len(body)),
                            'X-Generation-Id': 'test-generation'}
        response.iter_content.return_value = iter([body[:100], body[100:]])
        return response

    def test_catalog_voice_with_no_reference_has_exact_id_provider_and_no_upload(self):
        target = self.root / 'clip.wav'
        avatar = dict(id='fish' + VOICE, fish_voice_id=VOICE, transcript='', duration=0)
        with patch.object(self.pipeline.http, 'post', return_value=self.response()) as post:
            self.pipeline.clip(avatar, '[warm] Добрый вечер.', '', 42, target,
                               sample_rate=24000)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args, (tts_settings.DEFAULT_URL + '/audio/speech',))
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['voice'], VOICE)
        self.assertEqual(payload['provider']['only'], ['fish-audio'])
        self.assertEqual(payload['input'], '[warm] Добрый вечер.')
        self.assertEqual(payload['response_format'], 'mp3')
        self.assertEqual(payload['provider']['options']['fish-audio']['temperature'], .8)
        self.assertNotIn('references', json.dumps(payload))
        self.assertNotIn('reference_id', json.dumps(payload))
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        audio = sf.info(target)
        self.assertEqual((audio.samplerate, audio.channels), (24000, 1))
        self.assertGreater(audio.frames, 0)
        report = store.load_json(target.with_suffix('.cleanup.json'), {})
        self.assertEqual(report['fish_voice_id'], VOICE)
        self.assertEqual(report['api_request_attempts'], 1)
        self.assertNotIn('test-secret-key', json.dumps(report))

    def test_valid_cached_audio_reused_but_changing_voice_posts_again(self):
        target = self.root / 'cached.wav'
        with patch.object(self.pipeline.http, 'post', side_effect=lambda *a, **k: self.response()) as post:
            self.pipeline.clip(VOICE, 'Привет.', '', 7, target)
            self.pipeline.clip(VOICE, 'Привет.', '', 7, target)
            self.assertEqual(post.call_count, 1)
            self.pipeline.clip(OTHER_VOICE, 'Привет.', '', 7, target)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs['json']['voice'], OTHER_VOICE)

    def test_studio_synthesizes_catalog_voice_without_transcript_or_local_sample(self):
        with patch.object(self.pipeline.http, 'post', return_value=self.response()) as post:
            mp3, wav, report_path, transcript = self.pipeline.synthesize(
                dict(fish_voice_id=VOICE), 'Готовая студийная запись.')
        self.assertEqual(post.call_count, 1)
        self.assertTrue(Path(mp3).is_file())
        self.assertGreater(sf.info(wav).duration, 0)
        self.assertEqual(transcript, '')
        self.assertEqual(store.load_json(report_path, {})['fish_voice_id'], VOICE)
        self.assertFalse((Path(mp3).parent / 'reference.wav').exists())

    def test_voice_resolution_supports_legacy_avatar_path_without_wav(self):
        folder = self.root / 'avatars' / ('fish' + VOICE)
        store.atomic_json(folder / 'avatar.json', dict(fish_voice_id=VOICE))
        self.assertFalse((folder / 'reference.wav').exists())
        self.assertEqual(engine.resolve_voice_id(folder / 'reference.wav'), VOICE)
        self.assertEqual(engine.resolve_voice_id({'fish_audio_voice_id': VOICE}), VOICE)
        self.assertEqual(engine.resolve_voice_id('fish:' + VOICE.upper()), VOICE)

    def test_local_only_and_invalid_voices_fail_before_api_or_key_lookup(self):
        with patch('tts_settings.api_key') as key, patch.object(self.pipeline.http, 'post') as post:
            for voice in (dict(id='local'), dict(fish_voice_id='alloy'), 'fish:not-a-voice'):
                with self.subTest(voice=voice), self.assertRaisesRegex(ValueError, 'Fish Audio'):
                    self.pipeline.clip(voice, 'Привет.', '', 42, self.root / 'bad.wav')
        key.assert_not_called()
        post.assert_not_called()

    def test_payment_error_and_connection_loss_are_not_retried_or_cached(self):
        for problem in (self.response(status=402), requests.ConnectionError('test-secret-key')):
            with self.subTest(problem=type(problem).__name__):
                options = {'side_effect': problem} if isinstance(problem, Exception) else {'return_value': problem}
                with patch.object(self.pipeline.http, 'post', **options) as post:
                    with self.assertRaises(RuntimeError) as error:
                        self.pipeline.clip(VOICE, 'Привет.', '', 42, self.root / 'error.wav')
                self.assertEqual(post.call_count, 1)
                self.assertNotIn('test-secret-key', str(error.exception))
                self.assertFalse((self.root / 'error.wav').exists())
                self.assertFalse((self.root / 'error.cleanup.json').exists())
                self.assertFalse(list(self.root.glob('*.download')))

    def test_text_response_is_rejected_without_replacing_existing_audio(self):
        target = self.root / 'existing.wav'
        target.write_bytes(b'previous-recording')
        with patch.object(self.pipeline.http, 'post', return_value=self.response(content_type='application/json')) as post:
            with self.assertRaisesRegex(RuntimeError, 'текст вместо аудио'):
                self.pipeline.clip(VOICE, 'Привет.', '', 42, target)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(target.read_bytes(), b'previous-recording')

    def test_invalid_custom_options_cannot_override_voice_or_include_credentials(self):
        for options in ({'voice': OTHER_VOICE}, {'references': []}, {'api_key': 'secret'},
                        {'sample_rate': 44100}, {'temperature': float('nan')}, {1: .8}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                engine.cache_identity(dict(self.config, fish_options=options))
        before = dict(self.config['fish_options'])
        engine._fish_options(self.config)['temperature'] = 9
        self.assertEqual(self.config['fish_options'], before)


if __name__ == '__main__':
    unittest.main()
