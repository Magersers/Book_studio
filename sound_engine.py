"""Short contextual foley using the existing Stable Audio 3 SSH runtime.

No music prompt/style is used. Native audio is retained separately from the
quiet 24 kHz mono export consumed by book sound_file plans.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

import imageio_ffmpeg
import numpy as np
import soundfile as sf

import avatar_store as store
from drama3_engine import Pipeline, check_cancel
from drama3_server_setup import MUSIC_MODEL, MUSIC_ENCODER, MUSIC_REVISION
from remote_ssh import hidden

VERSION = 'stable-audio3-medium-sfx-lcm8-v1'
SAMPLE_RATE = 24000
TARGET_LUFS = -29.
TRUE_PEAK = -7.


def specification(part):
    if not isinstance(part, dict):
        raise ValueError('Нужна разметка звукового эффекта.')
    prompt = part.get('sound_prompt') or part.get('sound_description', '')
    if not isinstance(prompt, str) or not 4 <= len(prompt.strip()) <= 1000:
        raise ValueError('Опишите источник и действие звука: от 4 до 1000 символов.')
    seconds = part.get('sound_duration', 3.)
    if isinstance(seconds, bool) or not isinstance(seconds, (int,float)) or not math.isfinite(seconds) or not .5 <= seconds <= 12:
        raise ValueError('Звуковой эффект должен длиться от 0,5 до 12 секунд.')
    seed = part.get('sound_seed', 42)
    if type(seed) is not int:
        raise ValueError('Seed звукового эффекта должен быть целым числом.')
    # There must be only one track type even when a saved prompt supplied one.
    prompt = re.sub(r'^TrackType\s*:\s*\w+[\s.,;:]*', '', prompt.strip(), flags=re.I)
    prompt = ('TrackType: SFX. ' + prompt.rstrip(' .') + '. '
              'Natural isolated sound effect, no music, no rhythm, no speech, no voices.')
    frames = round(float(seconds)*SAMPLE_RATE)
    return dict(version=VERSION, model=MUSIC_MODEL, revision=MUSIC_REVISION, encoder=MUSIC_ENCODER,
                prompt=prompt, duration_seconds=frames/SAMPLE_RATE, frames=frames, sample_rate=SAMPLE_RATE,
                generation_seconds=max(1., frames/SAMPLE_RATE), seed=seed % (2**64),
                steps=8, cfg=1., sampler='lcm', scheduler='simple', target_lufs=TARGET_LUFS, true_peak=TRUE_PEAK)


def _paths(part, cache_dir):
    spec = specification(part)
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    root = Path(cache_dir)
    return spec, digest, root/(digest+'.wav'), root/(digest+'.native.wav'), root/(digest+'.json')


def _hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def cached_path(part, cache_dir):
    """Local-only probe; safe during plan validation before any SSH connection."""
    spec, digest, target, native, report = _paths(part, cache_dir)
    try:
        saved = store.load_json(report, {})
        if saved.get('signature') != digest or not target.is_file():
            return None
        info = sf.info(str(target))
        if info.samplerate != SAMPLE_RATE or info.channels != 1 or info.frames != spec['frames']:
            return None
        if saved.get('processed_sha256') != _hash(target):
            return None
        return str(target)
    except (ValueError, OSError, RuntimeError):
        return None


def graph(prompt, seconds, seed, prefix):
    """Same installed weights and native eight-step graph, without music STYLE."""
    if not isinstance(prompt, str) or not prompt.startswith('TrackType: SFX.'):
        raise ValueError('Для звукового эффекта нужен TrackType: SFX.')
    if not 1 <= float(seconds) <= 12:
        raise ValueError('Некорректная длительность генерации эффекта.')
    return {
        '1': dict(class_type='CheckpointLoaderSimple', inputs=dict(ckpt_name=MUSIC_MODEL)),
        '2': dict(class_type='CLIPLoader', inputs=dict(clip_name=MUSIC_ENCODER, type='stable_audio', device='default')),
        '3': dict(class_type='CLIPTextEncode', inputs=dict(clip=['2', 0], text=prompt)),
        '4': dict(class_type='CLIPTextEncode', inputs=dict(clip=['2', 0], text='')),
        '5': dict(class_type='EmptyLatentAudio', inputs=dict(seconds=float(seconds), batch_size=1)),
        '6': dict(class_type='KSampler', inputs=dict(model=['1', 0], positive=['3', 0], negative=['4', 0],
            latent_image=['5', 0], seed=int(seed) % (2**64), steps=8, cfg=1., sampler_name='lcm', scheduler='simple', denoise=1.)),
        '7': dict(class_type='VAEDecodeAudio', inputs=dict(samples=['6', 0], vae=['1', 2])),
        '8': dict(class_type='SaveAudio', inputs=dict(audio=['7', 0], filename_prefix=prefix)),
    }


def _run(arguments, cancel):
    check_cancel(); cancel()
    # A file avoids a full stderr pipe stalling cancellation on decoder errors.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error', '-y', *arguments],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors, **hidden())
        try:
            while process.poll() is None:
                check_cancel(); cancel(); time.sleep(.08)
            if process.returncode:
                errors.seek(0)
                raise RuntimeError('Не удалось подготовить звуковой эффект: '+errors.read().decode('utf-8',errors='replace')[-1400:])
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)


def generate(part, cache_dir, progress=lambda *args: None, cancel=lambda: None):
    check_cancel(); cancel()
    spec, digest, target, native, report = _paths(part, cache_dir)
    hit = cached_path(part, cache_dir)
    if hit:
        progress(1, 'Звуковой эффект уже готов')
        return hit
    target.parent.mkdir(parents=True, exist_ok=True)
    native_report = native.with_suffix('.json')
    native_partial = native.with_suffix('.partial.wav')
    partial = target.with_suffix('.partial.wav')
    pipeline = None
    try:
        receipt = store.load_json(native_report, {})
        have_native = native.is_file() and receipt.get('signature') == digest and receipt.get('sha256') == _hash(native)
        if not have_native:
            progress(None, 'Подключаем модель звуковых эффектов…')
            pipeline = Pipeline(music=True)
            def update(value, message):
                friendly = re.sub(r'^(?:Drama 3|Stable Audio 3)\s*:\s*', '', message)
                friendly = friendly.replace('создаём фоновую музыку','создаём звуковой эффект').replace('музыкальную модель','модель звуков').replace('музыкальную сцену','описание эффекта').replace('длительность фона','длительность эффекта').replace('описание музыки','описание эффекта').replace('готовую озвучку','звуковой эффект')
                fraction = None
                if value is not None:
                    value = max(0., min(1.,value))
                    if 'шаг' in message.casefold():fraction = .05+.7*value
                    elif 'скачиваем' in message.casefold():fraction = .75+.07*value
                    else:fraction = .05*value  # Connection/model setup is not a finished effect.
                progress(fraction, 'Звуковой эффект · '+friendly)
            outputs = pipeline.execute(graph(spec['prompt'], spec['generation_seconds'], spec['seed'],
                'bookstudio_sfx/'+uuid.uuid4().hex), update, cancel)
            descriptors = outputs.get('8', {}).get('audio', [])
            if not descriptors:
                raise RuntimeError('Сервер не вернул звуковой эффект.')
            audio, rate = pipeline.download_audio(descriptors[0], native, update, cancel, stereo=True)
            sf.write(str(native_partial), audio, rate, subtype='FLOAT')
            native_partial.replace(native)
            store.atomic_json(native_report, dict(signature=digest, sha256=_hash(native), sample_rate=rate,
                                                   frames=len(audio), output=descriptors[0]))
        check_cancel(); cancel()
        progress(.85, 'Настраиваем тихий уровень звукового эффекта…')
        seconds, frames = spec['duration_seconds'], spec['frames']
        # Keep the attack and natural decay. No speech cleanup or voice -20 LUFS.
        filters = (f'aformat=channel_layouts=mono,atrim=duration={seconds},loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA=7,'
                   f'aresample={SAMPLE_RATE},apad=whole_len={frames},atrim=end_sample={frames},'
                   f'afade=t=in:d=0.003,afade=t=out:st={max(0.,seconds-.02)}:d=0.02')
        _run(['-i',str(native),'-af',filters,'-ar',str(SAMPLE_RATE),'-ac','1','-c:a','pcm_s24le',str(partial)],cancel)
        audio, rate = sf.read(str(partial), dtype='float32')
        if rate != SAMPLE_RATE or audio.ndim != 1 or len(audio) != frames or not np.isfinite(audio).all() or float(np.max(np.abs(audio))) < .000001:
            raise RuntimeError('Получен пустой или некорректный звуковой эффект. Уточните описание или seed.')
        check_cancel(); cancel()
        partial.replace(target)
        store.atomic_json(report, dict(signature=digest, specification=spec, native_file=str(native),
                                      processed_sha256=_hash(target), target_lufs=TARGET_LUFS, true_peak=TRUE_PEAK,
                                      sample_rate=SAMPLE_RATE, channels=1, frames=frames))
        progress(1, 'Звуковой эффект готов')
        return str(target)
    finally:
        try:
            if pipeline:pipeline.close()
        finally:
            native_partial.unlink(missing_ok=True)
            partial.unlink(missing_ok=True)
