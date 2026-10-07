"""Conservative removal of isolated leading clicks/noise, never a fixed crop."""
import numpy as np

VERSION='onset-cleanup-v3-decay'


def pre_speech_artifact(audio,sr):
    """Detect an isolated, already-decaying start, without voice templates.

    A normal rising speech onset is kept. All conditions must hold: a peak
    in the first 25 ms, a smooth decay, >=60 ms of relative quiet and later
    sustained speech. Return a mute boundary inside that quiet interval.
    """
    if sr<=0:raise ValueError('Sample rate must be positive')
    head=np.asarray(audio,dtype=np.float32).reshape(-1)[:round(sr*1.6)]
    frame=max(1,round(sr*.005));n=len(head)//frame
    if n<60:return 0
    rms=np.sqrt(np.mean(head[:n*frame].reshape(n,frame)**2,axis=1))
    peak=float(np.max(rms[:24]));peak_index=int(np.argmax(rms[:24]))
    if peak<.008 or peak_index>5:return 0
    # At least most of the first 80 ms must be a decay, not a developing
    # syllable. A plateau, breath or steady vowel must not qualify.
    if np.mean(np.diff(rms[peak_index:16])<=peak*.08)<.85:return 0
    if float(np.mean(rms[14:20]))>peak*.23:return 0
    quiet=max(.0008,peak*.25)
    gap=next((i for i in range(max(4,peak_index+3),29)
              if np.max(rms[i:i+12])<quiet),None)
    if gap is None:return 0
    active=rms>max(.002,float(np.percentile(rms,85))*.09)
    later=np.flatnonzero(active[gap+12:])
    speech=next((gap+12+int(i) for i in later
                 if gap+12+i<=240 and np.count_nonzero(active[gap+12+i:gap+82+i])>=20),None)
    if speech is None:return 0
    return min(gap+12,speech-5)*frame

def _trim_isolated(audio,sr):
    wave=np.asarray(audio,dtype=np.float32).reshape(-1)
    report=dict(version=VERSION,trimmed_ms=0,reason='kept')
    frame=max(1,round(sr*.005)); n=len(wave)//frame
    if n<30:return wave,report
    rms=np.sqrt(np.mean(wave[:n*frame].reshape(n,frame)**2,axis=1))
    threshold=max(.002,float(np.percentile(rms,85))*.09)
    active=rms>threshold
    indices=np.flatnonzero(active)
    if not len(indices):return wave,report
    first=int(indices[0])
    if first*.005>.12:return wave,report
    # A genuine gap separates an onset artifact from the subsequent speech.
    gap=None
    for i in range(first+1,min(n-12,61)):
        if not active[i:i+12].any():gap=i;break
    if gap is None:return wave,report
    duration=(gap-first)*.005
    if duration>.3:return wave,report
    later=np.flatnonzero(active[gap+12:])
    if not len(later):return wave,report
    speech=gap+12+int(later[0])
    if speech*.005>1.2 or np.count_nonzero(active[speech:speech+70])<28:return wave,report
    burst=wave[first*frame:gap*frame]
    if not len(burst):return wave,report
    zcr=float(np.mean(np.signbit(burst[1:])!=np.signbit(burst[:-1])))
    # Longer voiced sounds may be a legitimate first word; preserve them.
    periodic=0.
    centered=burst-burst.mean()
    if duration>.02:
        for lag in range(max(1,sr//400),min(len(centered)//2,sr//65),max(1,sr//4000)):
            a,b=centered[:-lag],centered[lag:]
            periodic=max(periodic,float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)+1e-10)))
        if zcr<.18 or periodic>.45:return wave,report
    cut=max(0,(speech-5)*frame)
    result=wave[cut:].copy(); fade=min(len(result),max(1,round(sr*.003)))
    result[:fade]*=np.linspace(0,1,fade,dtype=np.float32)
    report.update(trimmed_ms=round(1000*cut/sr,1),artifact_ms=round(duration*1000,1),reason='isolated_leading_noise')
    return result,report

def _repair_impulses(wave,sr):
    """Repair isolated paired discontinuities within the first 600 ms.

    Thresholds follow local derivative activity: dense consonants/noise are
    left alone. Interpolation is limited to isolated excursions under 2 ms.
    """
    size=min(len(wave),round(.6*sr))
    if size<8:return wave,[]
    head=wave[:size];difference=np.diff(head)
    block=max(8,round(.02*sr));threshold=np.empty(len(difference),dtype='float32')
    for start in range(0,len(difference),block):
        local=difference[max(0,start-block):min(len(difference),start+2*block)]
        threshold[start:start+block]=max(.025,14*float(np.median(np.abs(local))))
    edges=np.flatnonzero(np.abs(difference)>threshold)
    if len(edges)<2:return wave,[]
    maximum=max(2,round(.002*sr));neighborhood=max(maximum*2,round(.008*sr))
    output=None;repaired=[];used=-1
    for k,left in enumerate(edges[:-1]):
        if left<=used:continue
        right=int(edges[k+1]);left=int(left)
        if right-left>maximum or difference[left]*difference[right]>=0:continue
        # Lots of nearby jumps indicate a fricative or other noisy speech.
        count=np.searchsorted(edges,right+neighborhood,side='right')-np.searchsorted(edges,left-neighborhood)
        if count>2:continue
        a=float(head[left]);b=float(head[right+1]);jump=min(abs(float(difference[left])),abs(float(difference[right])))
        # Endpoints may differ naturally over a voiced pitch cycle. Allow
        # the local speech slope, while still rejecting unmatched steps.
        slope=float(max(threshold[left],threshold[right]))/14
        if abs(a-b)>max(.015,jump*.4,2*slope*(right-left)):continue
        ratio=max(abs(float(difference[left])),abs(float(difference[right])))/max(jump,1e-8)
        if ratio>3:continue
        if output is None:output=wave.copy()
        output[left:right+2]=np.linspace(a,b,right-left+2,dtype=np.float32)
        repaired.append(dict(start_ms=round(left*1000/sr,2),duration_ms=round((right-left+1)*1000/sr,2)))
        used=right
    return wave if output is None else output,repaired

def clean_onset(audio,sr):
    """Bounded, one-pass DSP. No ASR, inference, retries or fixed-time crop."""
    original=np.asarray(audio,dtype=np.float32).reshape(-1)
    if sr<=0:raise ValueError('Sample rate must be positive')
    wave=original;trims=[]
    # Multiple isolated leading noises can occur before real speech.
    for _ in range(3):
        candidate,report=_trim_isolated(wave,sr)
        if not report['trimmed_ms']:break
        already=len(original)-len(wave)
        if already+len(wave)-len(candidate)>round(.8*sr):break
        wave=candidate;trims.append(report)
    mute=pre_speech_artifact(wave,sr)
    if mute:
        wave=wave.copy();wave[:mute]=0
        fade=min(len(wave)-mute,max(2,round(.005*sr)))
        wave[mute:mute+fade]*=(.5-.5*np.cos(np.linspace(0,np.pi,fade))).astype('float32')
    wave,repairs=_repair_impulses(wave,sr)
    fade_ms=0.
    # A nonzero boundary produces a click even if there is no isolated spike.
    # Smooth only the first 5 ms; no syllable or fixed prefix is removed.
    if len(wave) and abs(float(wave[0]))>.002:
        wave=wave.copy();count=min(len(wave),max(2,round(.005*sr)))
        wave[:count]*=(.5-.5*np.cos(np.linspace(0,np.pi,count))).astype('float32')
        fade_ms=round(count*1000/sr,2)
    trimmed_ms=round((len(original)-len(wave))*1000/sr,2)
    reasons=[]
    if mute:reasons.append('isolated_decaying_prefix')
    if trims:reasons.append('isolated_leading_noise')
    if repairs:reasons.append('impulse_repair')
    if fade_ms:reasons.append('boundary_fade')
    return wave,dict(version=VERSION,trimmed_ms=trimmed_ms,reason='+'.join(reasons) or 'kept',
        repaired_clicks=len(repairs),repairs=repairs,fade_ms=fade_ms,isolated_trims=trims,
        muted_prefix_ms=round(mute*1000/sr,2))
