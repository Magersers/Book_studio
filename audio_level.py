"""Cached two-pass perceived loudness matching. Originals remain untouched."""
import hashlib,json,math,os,re,subprocess,uuid
from pathlib import Path
import imageio_ffmpeg
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parent
VERSION='speech-level-v2'
TARGET=-20.0
PREFILTER='highpass=f=65,treble=g=-1.5:f=4500'

def run(source,filters,target=None):
    args=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-nostats','-y','-i',str(source),'-af',filters]
    args+=['-ar','24000','-ac','1',str(target)] if target else ['-f','null','-']
    p=subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if p.returncode:raise RuntimeError('Ошибка выравнивания громкости: '+p.stderr.decode(errors='replace')[-1000:])
    return p.stderr.decode(errors='replace')

def measure(path):
    log=run(path,'loudnorm=I=-20:TP=-2:LRA=11:print_format=json')
    match=re.search(r'\{\s*"input_i".*?\}',log,re.S)
    if not match:raise RuntimeError('Не удалось измерить громкость')
    return json.loads(match[0])

def normalized_file(source,kind='speech'):
    source=Path(source).resolve();stat=source.stat()
    own=ROOT/'.cache/voice-level'/kind
    if source.parent==own.resolve() and source.with_suffix('.json').is_file():
        saved=json.loads(source.with_suffix('.json').read_text(encoding='utf-8'))
        if saved.get('version')==VERSION:return source
        return normalized_file(saved['source'],kind)
    key=hashlib.sha256(json.dumps([VERSION,str(source),stat.st_size,stat.st_mtime_ns,kind]).encode()).hexdigest()
    folder=ROOT/'.cache/voice-level'/kind;folder.mkdir(parents=True,exist_ok=True)
    target=folder/(key+'.wav');report=target.with_suffix('.json')
    if target.is_file() and report.is_file():return target
    log=run(source,PREFILTER+',loudnorm=I=-20:TP=-2:LRA=11:print_format=json')
    stats=json.loads(re.search(r'\{\s*"input_i".*?\}',log,re.S)[0])
    level=float(stats['input_i']);peak=float(stats['input_tp'])
    if math.isfinite(level) and math.isfinite(peak):
        # Avoid amplifying near-silence/background hiss without bound.
        goal=min(TARGET,level+24)
        norm=f'volume={goal-level}dB'
    else:
        audio,sr=sf.read(source,dtype='float32',always_2d=True);audio=audio.mean(axis=1)
        active=audio[np.abs(audio)>max(.0001,float(np.max(np.abs(audio),initial=0))*.03)]
        rms=float(np.sqrt(np.mean(active**2))) if len(active) else 0
        gain=min(24, -23-20*math.log10(rms)) if rms>1e-5 else 0
        norm=f'volume={gain}dB'
    temp=folder/(key+'.'+uuid.uuid4().hex+'.wav')
    try:
        run(source,PREFILTER+','+norm+',aresample=96000,alimiter=limit=0.794328:level=false:latency=true,aresample=24000',temp)
        after=measure(temp)
        temp.replace(target)
        from avatar_store import atomic_json
        atomic_json(report,dict(version=VERSION,source=str(source),input=stats,output=after,target_lufs=TARGET))
    finally:
        if temp.exists():temp.unlink()
    return target
