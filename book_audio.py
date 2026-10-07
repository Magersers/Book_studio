"""CPU-only checks of individual utterances before joining a chapter."""
import re
from pathlib import Path
import numpy as np
import soundfile as sf

VERSION='book-joins-v4-silence'


def repeated_prefixes(items):
    """Find near-identical, isolated decaying prefixes across different texts.

    Never infer a crop from a speaker change alone. Require three different
    opening words from the same avatar, a matching waveform and a speech gap.
    Read only the first 1.6 seconds; keep at most 16 templates per avatar.
    Returned lengths are muted, not removed, so timing remains unchanged.
    """
    groups={};candidates=[]
    for item in items:
        with sf.SoundFile(item['path']) as source:
            if source.samplerate!=24000 or source.channels!=1:continue
            head=source.read(38400,dtype='float32')
        frame=120;n=len(head)//frame
        if n<50:continue
        rms=np.sqrt(np.mean(head[:n*frame].reshape(n,frame)**2,axis=1))
        threshold=max(.002,float(np.percentile(rms,85))*.09)
        active=rms>threshold
        # An artifact is already present at the file boundary and decays
        # within 120 ms, separated from the actual utterance by >=60 ms.
        if not active[:3].any():continue
        gap=next((i for i in range(4,min(25,n-12)) if not active[i:i+12].any()),None)
        if gap is None:continue
        later=np.flatnonzero(active[gap+12:])
        if not len(later):continue
        speech=next((gap+12+int(i) for i in later
                     if gap+12+i<=240 and np.count_nonzero(active[gap+12+i:gap+82+i])>=20),None)
        if speech is None:continue
        peak=float(np.max(rms[:gap]))
        if float(np.mean(rms[gap:gap+12]))>peak*.25:continue
        words=re.findall(r'[\wё]+',item['text'].casefold())
        if not words:continue
        fingerprint=head[240:1680].copy();fingerprint-=fingerprint.mean()
        norm=float(np.linalg.norm(fingerprint))
        if norm<.02:continue
        fingerprint/=norm
        member=(str(Path(item['path'])),min(gap+12,speech-5)*frame)
        candidates.append((item['avatar'],fingerprint,member))
        clusters=groups.setdefault(item['avatar'],[])
        cluster=next((c for c in clusters if float(np.dot(c['template'],fingerprint))>.985),None)
        if cluster is None:
            if len(clusters)>=16:continue
            cluster=dict(template=fingerprint,members=[],words=set());clusters.append(cluster)
        cluster['words'].add(words[0])
        cluster['members'].append(member)
    confirmed={avatar:[c for c in clusters if len(c['words'])>=3] for avatar,clusters in groups.items()}
    # After three near-exact witnesses, allow small variations of that known
    # artifact. A loose match alone can never establish an artifact template.
    return {member[0]:member[1] for avatar,fingerprint,member in candidates
            if any(float(np.dot(c['template'],fingerprint))>.90 for c in confirmed[avatar])}


def chapter_sources(book_folder,segments,plans):
    """Use separate voice clips even when a cached segment is already joined."""
    items=[];sources=[]
    for segment,plan in zip(segments,plans):
        raw=Path(book_folder)/'audio'
        paths=[raw/(f'{segment["id"]:08d}.wav' if len(plan)==1 else
                    f'{segment["id"]:08d}-part-{i:03d}.wav') for i in range(len(plan))]
        if paths and all(p.is_file() for p in paths):
            sources.append(paths)
            items.extend(dict(path=str(p),avatar=part['avatar'],text=part['text']) for p,part in zip(paths,plan) if not part.get('sound_file'))
        else:
            # Older projects may not have retained the individual voice clips.
            sources.append([Path(segment['wav'])])
    mutes=repeated_prefixes(items)
    from audio_cleanup import pre_speech_artifact
    for item in items:
        with sf.SoundFile(item['path']) as source:
            if source.samplerate!=24000 or source.channels!=1:continue
            count=pre_speech_artifact(source.read(38400,dtype='float32'),source.samplerate)
        if count:mutes[item['path']]=max(count,mutes.get(item['path'],0))
    return sources,mutes


def edge_blocks(source,mute_samples=0,check=lambda:None):
    """Stream with short fades at both ends and an optional proven prefix mute."""
    sr=source.samplerate;fade=max(2,round(sr*.005));offset=0;length=len(source)
    from speech_joins import quiet_edge
    source.seek(0);head=source.read(min(length,sr*2),dtype='float32')
    head[:min(mute_samples,len(head))]=0
    left=quiet_edge(head,sr)
    source.seek(max(0,length-sr*2));tail=source.read(dtype='float32')
    right=quiet_edge(tail[::-1],sr)
    if left+right>=length:left=right=0
    source.seek(left);length-=left+right;mute_samples=max(0,mute_samples-left)
    for block in source.blocks(blocksize=65536,frames=length,dtype='float32'):
        check()
        positions=np.arange(offset,offset+len(block))
        gain=np.ones(len(block),dtype='float32')
        if mute_samples:
            gain[positions<mute_samples]=0
        start=(positions>=mute_samples)&(positions<mute_samples+fade)
        gain[start]*=.5-.5*np.cos(np.pi*(positions[start]-mute_samples)/(fade-1))
        end=positions>=max(0,length-fade)
        gain[end]*=.5-.5*np.cos(np.pi*(length-1-positions[end])/(fade-1))
        yield block*gain
        offset+=len(block)
