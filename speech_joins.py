"""Conservative boundary silence removal; never cut inside audible speech."""
import numpy as np

def quiet_edge(samples,sr):
    frame=max(1,round(sr*.005))
    n=len(samples)//frame
    if not n:return 0
    blocks=samples[:n*frame].reshape(n,frame)
    # Only near-digital silence; retain quiet consonants and breaths.
    active=np.flatnonzero(np.max(np.abs(blocks),axis=1)>.0005)
    if not len(active):return 0
    return max(0,int(active[0])*frame-round(sr*.035))

def trim(audio,sr):
    window=min(len(audio),sr*2)
    left=quiet_edge(audio[:window],sr)
    right=quiet_edge(audio[-window:][::-1],sr)
    return audio[left:len(audio)-right] if left+right<len(audio) else audio

def gap(previous,current,default=180):
    if previous.get('sound_file') or current.get('sound_file'):return 40
    if previous.get('narrator_style')=='heading':return max(350,default)
    if previous.get('avatar')!=current.get('avatar'):return default
    text=previous.get('text','').rstrip(' \"»”')
    return 140 if text.endswith(('.', '!', '?', '…')) else 55
