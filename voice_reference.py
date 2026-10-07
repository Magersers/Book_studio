"""Shared voice preparation; speech recognition loads only when requested."""
from pathlib import Path
import subprocess
import gc
import numpy as np
import soundfile as sf
import imageio_ffmpeg
ROOT=Path(__file__).resolve().parent

def prepare_reference(source, folder, start=0, duration=15):
    if not source:
        raise ValueError('Загрузите образец голоса.')
    if not (0 <= float(start) <= 36000 and 3 <= float(duration) <= 30):
        raise ValueError('Укажите начало от 0 и длительность образца от 3 до 30 секунд.')
    target = folder / 'reference.wav'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-ss', str(start),
                    '-i', str(source), '-t', str(duration), '-ar', '24000', '-ac', '1', str(target)],
                   check=True, capture_output=True)
    audio, sr = sf.read(target, dtype='float32')
    if len(audio) < sr * 3 or not np.isfinite(audio).all() or np.max(np.abs(audio)) < .005:
        raise ValueError('Выбранный фрагмент короче 3 секунд, пустой или слишком тихий.')
    from audio_level import normalized_file
    return normalized_file(target,'reference')


def transcribe(reference):
    import librosa
    import whisper
    audio, sr = sf.read(reference, dtype='float32')
    audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
    asr = whisper.load_model('base', device='cpu', download_root=str(ROOT / 'models/whisper'))
    result = asr.transcribe(audio, language='ru', fp16=False, temperature=0, condition_on_previous_text=False)
    transcript = result['text'].strip()
    del asr
    gc.collect()
    if not transcript:
        raise ValueError('Не удалось распознать образец. Введите его расшифровку вручную.')
    return transcript


