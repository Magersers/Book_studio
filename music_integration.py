"""Publish studio music mixes while retaining original speech and its report."""
import subprocess
import time
from pathlib import Path

import avatar_store as store


def finish_studio(text, mp3, wav, metadata, progress, cancel):
    import imageio_ffmpeg
    import soundfile as sf
    from music_engine import render_studio

    mixed = Path(render_studio(text, wav, progress, cancel))
    if mixed.resolve()==Path(wav).resolve():
        return str(mp3),str(wav),str(metadata)
    target = mixed.with_suffix('.mp3')
    temporary = target.with_suffix('.partial.mp3')
    progress(None, 'Сохраняем озвучку с фоновой музыкой…')
    process = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-i', str(mixed),
                                '-codec:a', 'libmp3lame', '-b:a', '192k', str(temporary)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        while process.poll() is None:
            cancel()
            time.sleep(.1)
        _, error = process.communicate()
        if process.returncode:
            raise RuntimeError(error.decode('utf-8', errors='replace')[-2000:])
        cancel()
        temporary.replace(target)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        temporary.unlink(missing_ok=True)
    report = dict(store.load_json(metadata, {}))
    report.update(music_enabled=True, dry_mp3=str(mp3), dry_wav=str(wav), dry_metadata=str(metadata),
                  duration_seconds=sf.info(mixed).duration,
                  music_report=str(mixed.with_suffix('.music.json')))
    destination = mixed.with_suffix('.json')
    store.atomic_json(destination, report)
    return str(target), str(mixed), str(destination)
