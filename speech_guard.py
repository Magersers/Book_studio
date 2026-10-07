"""Text-aware onset verification. ASR stays on CPU; cuts require a real gap."""
import re
from pathlib import Path
import numpy as np

VERSION='speech-onset-v2-general'
LEAD_IN='Начинаем запись.'

def tokens(text):return re.findall(r'[а-яёa-z0-9]+',text.casefold().replace('ё','е'))
def filler(word):return bool(re.fullmatch(r'(?:а+|э+|ы+|м+|о+|у+|э+м+)',word))

def decide(words,text):
    expected=tokens(text)
    observed=[]
    for word in words:
        for token in tokens(word['word']):observed.append(dict(word,token=token))
    base=dict(version=VERSION,status='uncertain',reason='prefix_not_aligned',trimmed_ms=0)
    if not expected or not observed:return base
    # Do not remove a real opening interjection supplied by the user.
    if filler(expected[0]):return dict(base,status='keep',reason='intentional_interjection')
    anchor=expected[:min(3,len(expected))]
    for index in range(min(4,len(observed))):
        match=observed[index:index+len(anchor)]
        if [w['token'] for w in match]!=anchor:continue
        if index==0:return dict(base,status='keep',reason='matches_text',first_word=match[0]['start'])
        extra=observed[:index]
        if len(anchor)<2 or any(w.get('probability',0)<.45 for w in match):return base
        duration=extra[-1]['end']-extra[0]['start']
        if 0<=duration<=.6 and match[0]['start']<=1.2 and extra[-1]['end']<=1.2:
            return dict(base,status='retry',reason='extra_spoken_prefix',extra=' '.join(w['token'] for w in extra),speech_start=match[0]['start'],extra_end=extra[-1]['end'])
        return base
    return base

def cut_at_gap(wave,sr,decision):
    if decision['status']!='retry':return wave,decision
    start=float(decision['speech_start']);end=float(decision['extra_end'])
    frame=max(1,round(sr*.005));n=len(wave)//frame
    if not n:return wave,decision
    rms=np.sqrt(np.mean(wave[:n*frame].reshape(n,frame)**2,axis=1))
    threshold=max(.001,float(np.percentile(rms,85))*.035)
    # Search only before the ASR-aligned first intended word. Never cut by a
    # fixed 300 ms duration or inside an uninterrupted vowel/consonant.
    low=max(.03,end-.04,start-.22);high=start-.015
    candidates=[]
    for i in range(max(0,int(low/.005)),min(n-3,int(high/.005))):
        if np.all(rms[i:i+3]<threshold):candidates.append(i)
    if not candidates:return wave,decision
    cut=(candidates[-1]+1)*frame
    cleaned=wave[cut:].copy();fade=min(len(cleaned),max(1,int(.003*sr)))
    cleaned[:fade]*=np.linspace(0,1,fade,dtype=np.float32)
    return cleaned,dict(decision,status='trimmed',reason='extra_prefix_with_gap',trimmed_ms=round(1000*cut/sr,1))

def isolated_prefix(wave,sr):
    """Candidate only: the caller must verify the remaining spoken text."""
    frame=max(1,round(sr*.005));n=len(wave)//frame
    if n<90:return None
    rms=np.sqrt(np.mean(wave[:n*frame].reshape(n,frame)**2,axis=1))
    active=rms>max(.002,float(np.percentile(rms,85))*.08)
    indices=np.flatnonzero(active)
    if not len(indices) or indices[0]>24:return None
    first=int(indices[0]);gap=None
    for i in range(first+3,min(first+71,n-16)):
        if not active[i:i+16].any():gap=i;break
    if gap is None:return None
    later=np.flatnonzero(active[gap+16:])
    if not len(later):return None
    speech=gap+16+int(later[0])
    if speech*.005>1.2 or np.count_nonzero(active[speech:speech+60])<20:return None
    cut=max(0,(speech-5)*frame)
    return cut

class SpeechGuard:
    def __init__(self):self.model=None
    def recognize(self,wave,sr):
        import whisper
        from scipy.signal import resample_poly
        from math import gcd
        root=Path(__file__).resolve().parent/'models/whisper'
        if self.model is None:
            # Use the already installed local checkpoint; no implicit download.
            self.model=whisper.load_model(str(root/'base.pt'),device='cpu')
        samples=np.asarray(wave[:int(7*sr)],dtype=np.float32)
        factor=gcd(int(sr),16000)
        samples=resample_poly(samples,16000//factor,int(sr)//factor).astype('float32')
        result=self.model.transcribe(samples,language='ru',fp16=False,temperature=0,
            condition_on_previous_text=False,word_timestamps=True,verbose=None)
        return [w for segment in result.get('segments',[]) for w in segment.get('words',[])]
    def strip_lead_in(self,wave,sr,text):
        """Discard a sacrificial spoken lead-in, only at a verified speech gap."""
        report=dict(version='spoken-lead-in-v1',status='retry',reason='lead_in_not_aligned',trimmed_ms=0)
        try:
            words=self.recognize(wave,sr)
            observed=[dict(w,token=t) for w in words for t in tokens(w['word'])]
            expected=tokens(text)[:3];marker=tokens(LEAD_IN)
            if not expected:return wave,report
            names=[w['token'] for w in observed]
            marker_end=next((i+len(marker) for i in range(min(5,len(names))) if names[i:i+len(marker)]==marker),None)
            if marker_end is None:return wave,report
            first=next((i for i in range(marker_end,min(marker_end+4,len(names))) if names[i:i+len(expected)]==expected),None)
            if first is None:return wave,report
            speech_start=float(observed[first]['start']);marker_time=float(observed[marker_end-1]['end'])
            if not .2<speech_start<5:return wave,report
            frame=max(1,round(sr*.005));n=len(wave)//frame
            rms=np.sqrt(np.mean(wave[:n*frame].reshape(n,frame)**2,axis=1))
            low=max(.15,marker_time-.08,speech_start-.6);high=speech_start-.02
            threshold=max(.001,float(np.percentile(rms,85))*.045)
            runs=[];start=None
            for i in range(max(0,int(low/.005)),min(n,int(high/.005))):
                if rms[i]<threshold:
                    if start is None:start=i
                elif start is not None:
                    if i-start>=4:runs.append((start,i))
                    start=None
            if start is not None and int(high/.005)-start>=4:runs.append((start,min(n,int(high/.005))))
            if not runs:return wave,dict(report,reason='no_safe_lead_in_boundary')
            left,right=runs[-1];cut=((left+right)//2)*frame
            candidate=wave[cut:].copy();verified=self.recognize(candidate,sr)
            verified_tokens=[t for w in verified for t in tokens(w['word'])]
            if verified_tokens[:len(expected)]!=expected:return wave,dict(report,reason='lead_in_cut_not_verified')
            if any(w.get('probability',0)<.35 for w in verified[:min(len(expected),len(verified))]):return wave,dict(report,reason='lead_in_cut_low_confidence')
            fade=min(len(candidate),max(1,int(.003*sr)));candidate[:fade]*=np.linspace(0,1,fade,dtype=np.float32)
            return candidate,dict(report,status='trimmed',reason='lead_in_removed',trimmed_ms=round(1000*cut/sr,1),verified=' '.join(w['word'].strip() for w in verified))
        except Exception as exc:
            return wave,dict(report,reason='lead_in_asr_failed',error=str(exc)[:300])
    def check(self,wave,sr,text):
        try:
            words=self.recognize(wave,sr)
            decision=decide(words,text);decision['recognized']=' '.join(w['word'].strip() for w in words)
            output,decision=cut_at_gap(wave,sr,decision)
            expected=tokens(text)
            # ASR can omit any isolated sound entirely. Check a candidate crop
            # against the full intended prefix; a genuine first word must stay.
            if decision['status'] in ('keep','uncertain') and len(expected)>=2 and not filler(expected[0]):
                cut=isolated_prefix(wave,sr)
                if cut:
                    candidate=wave[cut:].copy();following=self.recognize(candidate,sr)
                    check=decide(following,text)
                    confidence=all(w.get('probability',0)>=.7 for w in following[:min(3,len(expected))])
                    if check['status']=='keep' and check['reason']=='matches_text' and confidence:
                        fade=min(len(candidate),max(1,int(.003*sr)));candidate[:fade]*=np.linspace(0,1,fade,dtype=np.float32)
                        return candidate,dict(decision,status='trimmed',reason='untranscribed_prefix_verified',trimmed_ms=round(1000*cut/sr,1),verified=' '.join(w['word'].strip() for w in following))
            if decision['status']=='trimmed':
                verified=decide(self.recognize(output,sr),text)
                if verified['status']!='keep' or verified['reason']!='matches_text':
                    return wave,dict(decision,status='retry',reason='trim_not_verified',trimmed_ms=0)
            return output,decision
        except Exception as exc:
            return wave,dict(version=VERSION,status='unchecked',reason='asr_unavailable',error=str(exc)[:300],trimmed_ms=0)
