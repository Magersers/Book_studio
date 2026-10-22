"""Cloud avatars must work for book narration without a local reference WAV."""
import copy
import unittest
from unittest.mock import patch

import book_engine as books


class CloudBookVoicesTest(unittest.TestCase):
    def setUp(self):
        self.voice=dict(id='fish'+'a'*32, name='Рассказчик', fish_voice_id='a'*32,
                        transcript='', duration=0, voice_provider='fish-audio')

    def test_cloud_signature_never_reads_local_reference(self):
        with patch('runtime_config.tts_id', return_value='routerai-voice-id-v2'), \
             patch('avatar_store.avatar_path', side_effect=AssertionError('No local WAV for Fish voice')):
            signature=books.audio_signature('Привет.', self.voice, 42)
            renamed=dict(self.voice,name='Новое имя',task_count=9999)
            self.assertEqual(signature, books.audio_signature('Привет.',renamed,42))
            self.assertNotEqual(signature, books.audio_signature('Пока.',self.voice,42))
            self.assertNotEqual(signature, books.audio_signature('Привет.',dict(self.voice,fish_voice_id='b'*32),42))

    def test_cloud_narrator_plan_skips_local_anchor(self):
        voices={self.voice['id']:self.voice}
        plan=[dict(text='Глава первая.',avatar=self.voice['id'],narrator_style='heading')]
        with patch('runtime_config.tts_id',return_value='routerai-voice-id-v2'), \
             patch('narrator_reference.select',side_effect=AssertionError('No local narrator anchor')):
            self.assertTrue(books.plan_signature(plan,voices,42))

    def test_pipeline_adapter_preserves_local_pipeline_contract(self):
        remote=type('Remote',(),{'uses_voice_ids':True})()
        local=object()
        self.assertIs(books.pipeline_voice(self.voice,remote),self.voice)
        self.assertTrue(books.pipeline_voice(self.voice,local).endswith('reference.wav'))


if __name__ == '__main__':
    unittest.main()
