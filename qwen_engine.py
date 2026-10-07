"""Qwen3-TTS voice cloning with local reference transcription."""
import os
os.environ.setdefault('OMP_NUM_THREADS', '6')
os.environ.setdefault('MKL_NUM_THREADS', '6')
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
import gc
import json
import re
import subprocess
import threading
import uuid
from collections import OrderedDict
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
torch.set_num_threads(int(os.environ['OMP_NUM_THREADS']))


def split_text(text):
    segments = []
    for sentence in re.split(r'(?<=[.!?…])\s+|\n+', text.strip()):
        while len(sentence) > 240:
            cut = max(sentence.rfind(p, 60, 240) for p in [',', ';', ':', ' '])
            cut = cut + 1 if cut >= 0 else 240
            segments.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            segments.append(sentence)
    return segments


from voice_reference import prepare_reference, transcribe


class Pipeline:
    def __init__(self):
        self.model = None
        self.book_prompts = OrderedDict()

    def generate_checked(self,text,prompt,seed,report_path,progress=lambda *a:None):
        from audio_cleanup import clean_onset
        torch.manual_seed(int(seed));torch.cuda.manual_seed_all(int(seed))
        waves,sr=self.model.generate_voice_clone(text=text,language='Russian',voice_clone_prompt=prompt,
            non_streaming_mode=True,max_new_tokens=2048)
        wave=np.asarray(waves[0],dtype=np.float32).reshape(-1)
        if not len(wave) or not np.isfinite(wave).all() or np.max(np.abs(wave))<1e-5:
            raise RuntimeError('Модель вернула некорректное аудио.')
        wave,noise=clean_onset(wave,sr)
        report=dict(mode='single_pass',seed=int(seed),noise=noise,trimmed_ms=noise['trimmed_ms'],
            speech_status='not_checked',needs_review=False)
        Path(report_path).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return wave,sr,report

    def synthesize_book_clip(self, reference, text, transcript, seed, target):
        """One bounded book fragment, no duplicate references or intermediate MP3s."""
        if not text.strip() or len(text) > 500:
            raise ValueError('Фрагмент книги должен содержать от 1 до 500 символов.')
        with LOCK, torch.inference_mode():
            self.load()
            source = Path(reference)
            key = (str(source), source.stat().st_mtime_ns, transcript)
            if key not in self.book_prompts:
                self.book_prompts[key] = self.model.create_voice_clone_prompt(
                    ref_audio=str(source), ref_text=transcript, x_vector_only_mode=False)
                if len(self.book_prompts) > 8:
                    self.book_prompts.popitem(last=False)
            self.book_prompts.move_to_end(key)
            target = Path(target)
            audio,sr,cleanup=self.generate_checked(text,self.book_prompts[key],seed,target.with_suffix('.cleanup.json'))
            audio *= min(1., .98 / max(float(np.max(np.abs(audio))), 1e-6))
            temporary = target.with_suffix('.partial.wav')
            sf.write(temporary, audio, sr)
            temporary.replace(target)
            target.with_suffix('.cleanup.json').write_text(json.dumps(cleanup,ensure_ascii=False),encoding='utf-8')
            return str(target)

    def load(self, progress=lambda *args: None):
        with LOCK:
            if self.model is None:
                if not torch.cuda.is_available():
                    raise RuntimeError('Видеокарта NVIDIA недоступна. Проверьте драйвер и перезапустите приложение.')
                progress(.35, 'Загружаем голосовую модель…')
                from qwen_tts import Qwen3TTSModel
                self.model = Qwen3TTSModel.from_pretrained(
                    str(ROOT / 'models/Qwen3-TTS-1.7B'), device_map='cuda:0',
                    dtype=torch.bfloat16, attn_implementation='sdpa', local_files_only=True)
            return self

    def synthesize(self, reference, text, reference_text='', start=0, duration=15, seed=42,
                   progress=lambda *args: None):
        if not text or not text.strip() or len(text) > 3000:
            raise ValueError('Введите от 1 до 3000 символов текста.')
        with LOCK:
            folder = ROOT / 'outputs' / ('qwen_' + uuid.uuid4().hex[:12])
            folder.mkdir(parents=True)
            sample = prepare_reference(reference, folder, start, duration)
            transcript = reference_text.strip() if reference_text else ''
            if not transcript:
                progress(.03, 'Whisper: распознавание образца на CPU…')
                transcript = transcribe(sample)
            (folder / 'reference.txt').write_text(transcript, encoding='utf-8')
            self.load(progress)
            # Preserve natural prosody for short texts; split only long passages.
            segments = [text.strip()] if len(text) <= 500 else split_text(text)
            torch.manual_seed(int(seed))
            torch.cuda.manual_seed_all(int(seed))
            parts = []; cleanups=[]
            with torch.inference_mode():
                prompt = self.model.create_voice_clone_prompt(ref_audio=str(sample), ref_text=transcript,
                                                              x_vector_only_mode=False)
                for i, segment in enumerate(segments):
                    progress(.25 + .65 * i / len(segments), f'Qwen-TTS: фрагмент {i+1}/{len(segments)}…')
                    wave,sr,cleanup=self.generate_checked(segment,prompt,int(seed)+i,folder/f'segment-{i:04d}.cleanup.json',progress)
                    cleanups.append(cleanup)
                    parts.append(wave)
                    if i < len(segments)-1:
                        parts.append(np.zeros(round(.25*sr), dtype=np.float32))
            audio = np.concatenate(parts)
            audio *= min(1., .98 / max(float(np.max(np.abs(audio))), 1e-6))
            wav, mp3 = folder / 'speech.wav', folder / 'speech.mp3'
            sf.write(wav, audio, sr)
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-i', str(wav),
                            '-codec:a', 'libmp3lame', '-b:a', '192k', str(mp3)], check=True, capture_output=True)
            report = dict(model='Qwen3-TTS-12Hz-1.7B-Base', text=text, reference_text=transcript,
                          reference_start=float(start), reference_duration=float(duration), seed=int(seed),
                          duration_seconds=len(audio)/sr, sample_rate=sr,onset_cleanup=cleanups,needs_review=any(c.get('needs_review') for c in cleanups))
            metadata = folder / 'generation.json'
            metadata.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            progress(1, 'Готово')
            return str(mp3), str(wav), str(metadata), transcript
