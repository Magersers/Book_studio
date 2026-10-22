"""Cloud avatars must work for book narration without a local reference WAV."""
import copy
import gc
import tempfile
import unittest
from pathlib import Path
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

    def test_force_stop_and_startup_recovery_keep_paid_render_checkpoints(self):
        import avatar_store as store
        import book_state as state
        for recovery in (False,True):
            with self.subTest(recovery=recovery), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)
                with patch.object(store,'DATA',root),patch.object(books,'BOOKS',root/'books'),patch('runtime_config.tts_id',return_value='routerai:test'):
                    source=root/'source.txt';source.write_text('Первая реплика.\n\nВторая реплика.',encoding='utf-8')
                    books.import_book(source,'test',lambda *args:None)
                    state.migrate('test')
                    wav=root/'paid.wav';wav.write_bytes(b'retained audio')
                    with books.connect('test') as db:
                        first=db.execute('SELECT min(id) FROM segments').fetchone()[0]
                        db.execute('UPDATE segments SET analyzed=1')
                        db.execute('UPDATE segments SET wav=?,signature=? WHERE id=?',(str(wav),'paid-checkpoint',first))
                    state.update('test',stage='render',job_status='running',active_chapter=1)
                    if recovery:state.recover()
                    else:state.force_reset('test')
                    with books.connect('test') as db:
                        saved=db.execute('SELECT wav,signature FROM segments WHERE id=?',(first,)).fetchone()
                    self.assertEqual(tuple(saved),(str(wav),'paid-checkpoint'))
                    self.assertTrue(wav.is_file())
                    self.assertEqual(books.metadata('test')['render_done'],1)
                    self.assertEqual(books.metadata('test')['job_status'],'stopped')
                    db.close()
                    gc.collect()


if __name__ == '__main__':
    unittest.main()
