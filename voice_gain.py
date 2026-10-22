"""Optional book voice gain after normalization; original speech is immutable."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import uuid

import imageio_ffmpeg
import numpy as np
import soundfile as sf

import avatar_store as store

ROOT = Path(__file__).resolve().parent
VERSION = 'book-voice-gain-v1'
# A little resampling headroom below the requested -1 dB true-peak ceiling.
LIMIT = 10 ** (-1.1 / 20)
TRUE_PEAK_LIMIT = 10 ** (-1 / 20)


def _true_peak(path):
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error', '-i', str(path),
               '-af', 'aresample=96000', '-f', 'f32le', '-acodec', 'pcm_f32le', '-']
    result = subprocess.run(command, capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError('Не удалось проверить пиковую громкость голоса.')
    samples = np.frombuffer(result.stdout, dtype='<f4')
    if not np.isfinite(samples).all():
        raise RuntimeError('Некорректные значения в усиленной записи.')
    return float(np.max(np.abs(samples), initial=0))


def gain_for(mapping, avatar):
    if not isinstance(mapping, dict):
        return 0.
    value = mapping.get(avatar, 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0.
    return max(-12., min(12., float(value)))


def gained_file(source, gain_db):
    source = Path(source).resolve()
    gain_db = gain_for({'voice': gain_db}, 'voice')
    if gain_db == 0:
        return source
    info = sf.info(source)
    if info.samplerate != 24000 or info.channels != 1:
        raise ValueError('Усиление голоса требует моно WAV 24 кГц после выравнивания громкости.')
    stat = source.stat()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    spec = dict(version=VERSION, source=str(source), source_sha256=digest,
                source_size=stat.st_size, source_mtime_ns=stat.st_mtime_ns,
                gain_db=gain_db, limiter_ceiling_db=-1.1, frames=info.frames)
    key = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    folder = ROOT / '.cache' / 'voice-gain'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (key + '.wav')
    report = target.with_suffix('.json')
    saved = store.load_json(report, {})
    if (target.is_file() and saved.get('spec') == spec
            and saved.get('audio_sha256') == hashlib.sha256(target.read_bytes()).hexdigest()):
        return target
    temporary = folder / (key + '.' + uuid.uuid4().hex + '.wav')
    try:
        from audio_level import run
        # Lookahead limiting at 4x the native rate also constrains intersample
        # peaks. Latency compensation and exact trimming retain every cue time.
        filters = (f'volume={gain_db}dB,aresample=96000,'
                   f'alimiter=limit={LIMIT}:level=false:attack=5:release=50:latency=true,'
                   f'aresample=24000,apad=whole_len={info.frames},atrim=end_sample={info.frames}')
        run(source, filters, temporary)
        peak = _true_peak(temporary)
        if peak > TRUE_PEAK_LIMIT:
            # Resampling after lookahead limiting can add a tiny overshoot.
            # A final constant attenuation retains the smooth envelope and
            # constrains the reconstructed 4x true peak with quantization room.
            audio, rate = sf.read(temporary, dtype='float32')
            audio *= TRUE_PEAK_LIMIT / peak * 10 ** (-.02 / 20)
            sf.write(temporary, audio, rate, subtype='PCM_24')
        output = sf.info(temporary)
        if (output.frames, output.samplerate, output.channels) != (info.frames, 24000, 1):
            raise RuntimeError('После усиления голоса изменилась длительность записи.')
        temporary.replace(target)
        store.atomic_json(report, dict(spec=spec, audio_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    finally:
        temporary.unlink(missing_ok=True)
    return target
