"""Shared voice preparation for inline API references."""
from pathlib import Path
import subprocess
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




