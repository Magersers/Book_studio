"""Optional Stable Audio 3 underscore over the same owned SSH runtime.

Speech stays in the dry export. Music is synthesized in bounded cached chunks,
normalized on its actual used crop, faded, gently ducked and mixed separately.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

import imageio_ffmpeg
import numpy as np
import soundfile as sf

import avatar_store as store
from drama3_engine import Pipeline, check_cancel
from remote_ssh import hidden
from music_planner import DEFAULT_PROMPT, STYLE
from music_timeline import cue_times, chunks
from drama3_server_setup import MUSIC_MODEL as MODEL, MUSIC_ENCODER as ENCODER

VERSION = 'stable-audio3-medium-lcm8-background-v1'


def graph(prompt, seconds, seed, prefix):
    if not 1 <= seconds <= 45.01:
        raise ValueError('Музыка генерируется блоками от 1 до 45 секунд.')
    return {
        '1': dict(class_type='CheckpointLoaderSimple', inputs=dict(ckpt_name=MODEL)),
        '2': dict(class_type='CLIPLoader', inputs=dict(clip_name=ENCODER, type='stable_audio', device='default')),
        '3': dict(class_type='CLIPTextEncode', inputs=dict(clip=['2', 0], text=prompt + '. ' + STYLE)),
        '4': dict(class_type='CLIPTextEncode', inputs=dict(clip=['2', 0], text='')),
        '5': dict(class_type='EmptyLatentAudio', inputs=dict(seconds=float(seconds), batch_size=1)),
        '6': dict(class_type='KSampler', inputs=dict(model=['1', 0], positive=['3', 0], negative=['4', 0],
                  latent_image=['5', 0], seed=int(seed) % (2**64), steps=8, cfg=1.,
                  sampler_name='lcm', scheduler='simple', denoise=1.)),
        '7': dict(class_type='VAEDecodeAudio', inputs=dict(samples=['6', 0], vae=['1', 2])),
        '8': dict(class_type='SaveAudio', inputs=dict(audio=['7', 0], filename_prefix=prefix)),
    }


def _run(arguments, cancel):
    """Local FFmpeg stays cancellable and never leaves a child after an error."""
    check_cancel(); cancel()
    process = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error', '-y', *arguments],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **hidden())
    try:
        while process.poll() is None:
            check_cancel(); cancel()
            time.sleep(.08)
        errors = process.stderr.read().decode('utf-8', errors='replace')
        if process.returncode:
            raise RuntimeError('Не удалось собрать фоновую музыку: ' + errors[-1400:])
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=3)
        process.stderr.close()


def _fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as src:
        while True:
            block = src.read(1024 * 1024)
            if not block:
                break
            check_cancel()
            digest.update(block)
    return digest.hexdigest()


def _render(dry_wav, cues, cache, progress, cancel):
    dry_wav, cache = Path(dry_wav), Path(cache)
    check_cancel(); cancel()
    info = sf.info(str(dry_wav))
    if info.frames <= 0 or info.samplerate < 16000:
        raise ValueError('Сначала нужна готовая озвучка.')
    if not cues:
        progress(1, 'В этой сцене музыка не предусмотрена')
        return str(dry_wav)
    duration = info.frames / info.samplerate
    # Output follows actual speech rate and stereo music; never change duration.
    sr, frames = info.samplerate, info.frames
    cache.mkdir(parents=True, exist_ok=True)
    spec = dict(version=VERSION, speech=_fingerprint(dry_wav), cues=cues, rate=sr, frames=frames)
    signature = hashlib.sha256(json.dumps(spec, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    target = dry_wav.with_name(dry_wav.stem + '-music.wav')
    report = target.with_suffix('.music.json')
    if store.load_json(report, {}).get('signature') == signature and target.is_file():
        cached = sf.info(str(target))
        if cached.frames == frames and cached.samplerate == sr:
            progress(1, 'Озвучка с музыкой уже готова')
            return str(target)
    tasks = []
    for cue in cues:
        start, end = max(0., cue['start_seconds']), min(duration, cue['end_seconds'])
        if end <= start:
            continue
        level = max(-50., min(-38., float(cue.get('level_db', -41.))))
        pieces = list(chunks(start, end))
        for index, (a, b) in enumerate(pieces):
            tasks.append(dict(cue=cue, start=a, end=b, level=level,
                              fade_in=min(2., (b-a)/3), fade_out=min(2., (b-a)/3),
                              first=index == 0, last=index == len(pieces)-1))
    if not tasks:
        return str(dry_wav)
    bed = cache / ('bed-' + uuid.uuid4().hex + '.wav')
    partial = target.with_name(target.stem + '.' + uuid.uuid4().hex + '.partial.wav')
    pipeline = None
    try:
        # Allocate the bed on disk. RAM use is bounded by one 45-second chunk.
        with sf.SoundFile(str(bed), 'w', samplerate=sr, channels=2, subtype='FLOAT') as output:
            zero = np.zeros((sr, 2), dtype='float32')
            for position in range(0, frames, sr):
                check_cancel(); cancel()
                output.write(zero[:min(sr, frames-position)])
        for index, task in enumerate(tasks):
            check_cancel(); cancel()
            seconds = task['end'] - task['start']
            # Model has a one-second minimum. Only the actual speech crop is used.
            generation_seconds = max(1., seconds)
            clip_spec = dict(version=VERSION, prompt=task['cue']['prompt'], seconds=round(generation_seconds, 6),
                             crop_seconds=round(seconds, 6),
                             index=index, level=task['level'], sr=sr)
            digest = hashlib.sha256(json.dumps(clip_spec, sort_keys=True).encode()).hexdigest()
            raw = cache / (digest + '-raw.wav')
            normalized = cache / (digest + '.wav')
            expected = max(1, round(seconds * sr))
            def update(value, message):
                progress(None if value is None else .02 + .84*(index + min(1., max(0., value)))/len(tasks),
                         f'Фон {index+1}/{len(tasks)} · ' + message)
            if not normalized.is_file() or sf.info(str(normalized)).frames != expected:
                if not raw.is_file():
                    if pipeline is None:
                        pipeline = Pipeline(music=True)
                    outputs = pipeline.execute(graph(task['cue']['prompt'], generation_seconds,
                        int(digest[:15], 16), 'bookstudio_music/' + uuid.uuid4().hex), update, cancel)
                    descriptors = outputs.get('8', {}).get('audio', [])
                    if not descriptors:
                        raise RuntimeError('Stable Audio 3 не вернула музыку.')
                    audio, native_rate = pipeline.download_audio(descriptors[0], raw, update, cancel, stereo=True)
                    raw_partial = raw.with_suffix('.partial.wav')
                    sf.write(raw_partial, audio, native_rate, subtype='PCM_24')
                    raw_partial.replace(raw)
                update(.9, 'Выравниваем тихий фон на используемом фрагменте…')
                normalized_partial = normalized.with_suffix('.partial.wav')
                try:
                    _run(['-i', str(raw), '-t', str(seconds), '-af',
                          f'atrim=duration={seconds},loudnorm=I={task["level"]}:TP=-7:LRA=7,'
                          f'aresample={sr},apad=whole_len={expected},atrim=end_sample={expected}',
                          '-ar', str(sr), '-ac', '2', '-c:a', 'pcm_s24le', str(normalized_partial)], cancel)
                    normalized_partial.replace(normalized)
                finally:
                    normalized_partial.unlink(missing_ok=True)
            audio, _ = sf.read(str(normalized), dtype='float32', always_2d=True)
            # Two-second linear adjacent fades sum to unity. Outer edges fade too.
            onset = min(len(audio), max(1, round(task['fade_in'] * sr)))
            offset = min(len(audio), max(1, round(task['fade_out'] * sr)))
            audio[:onset] *= np.linspace(0., 1., onset, dtype='float32')[:, None]
            audio[-offset:] *= np.linspace(1., 0., offset, dtype='float32')[:, None]
            position = round(task['start'] * sr)
            length = min(len(audio), frames-position)
            with sf.SoundFile(str(bed), 'r+') as output:
                output.seek(position); previous = output.read(length, dtype='float32', always_2d=True)
                output.seek(position); output.write(previous + audio[:length])
            progress(.02 + .84*(index+1)/len(tasks), f'Тихий фон: {index+1}/{len(tasks)} фрагментов готово')
        progress(.9, 'Микшируем тихий фон под голосами…')
        speech_channels = 'pan=stereo|c0=c0|c1=c0,' if info.channels == 1 else ''
        filters = ('[0:a]' + speech_channels + 'asplit=2[speech][key];'
                   '[1:a][key]sidechaincompress=threshold=0.06:ratio=1.5:attack=30:release=850[bg];'
                   '[speech][bg]amix=inputs=2:normalize=0:duration=first,'
                   f'alimiter=limit=0.98:level=0:latency=1,apad=whole_len={frames},atrim=end_sample={frames}[out]')
        _run(['-i', str(dry_wav), '-i', str(bed), '-filter_complex', filters, '-map', '[out]',
              '-ar', str(sr), '-ac', '2', '-c:a', 'pcm_s24le', str(partial)], cancel)
        check = sf.info(str(partial))
        if check.frames != frames or check.samplerate != sr:
            raise RuntimeError('Длина музыки и исходной озвучки не совпала.')
        partial.replace(target)
        store.atomic_json(report, dict(signature=signature, model=MODEL, cues=cues,
                                      dry_wav=str(dry_wav), sample_rate=sr, frames=frames,
                                      cue_target_lufs=[task['level'] for task in tasks], dry_preserved=True))
        progress(1, 'Озвучка с тихой фоновой музыкой готова')
        return str(target)
    finally:
        if pipeline:
            pipeline.close()
        bed.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)


def render_book(book_id, chapter_id, dry_wav, segment_timing, plan,
                progress=lambda *args: None, cancel=lambda: None):
    import book_engine as books
    info = sf.info(str(dry_wav))
    cues = cue_times(plan, segment_timing, info.frames / info.samplerate)
    return _render(dry_wav, cues, books.folder(book_id) / 'music' / f'chapter-{int(chapter_id):04d}', progress, cancel)


def render_studio(text, dry_wav, progress=lambda *args: None, cancel=lambda: None):
    # Studio is a short single text preview. No analysis API is needed here;
    # detailed character/scene planning belongs to imported books.
    info = sf.info(str(dry_wav))
    duration = info.frames / info.samplerate
    # Leave the opening and ending quiet; never extend the speech export.
    start, end = min(1., duration*.08), max(0., duration-min(1.5, duration*.1))
    cues = [dict(start_seconds=start, end_seconds=end, prompt=DEFAULT_PROMPT, level_db=-41.)] if end > start else []
    return _render(dry_wav, cues, Path(dry_wav).parent / 'music-cache', progress, cancel)
