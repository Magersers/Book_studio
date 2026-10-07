"""Speech-only punctuation and bounded frame budgets for Higgs."""
import re

def speech_chunks(text,limit=180):
    """Split before inference, preserving words and sentence punctuation."""
    text=re.sub(r'(?:…|\.{3,})\s+(?=[А-ЯЁA-Z])', '. ', text)
    text=re.sub(r'(?m)^\s*[-•]\s+','',text)
    text=re.sub(r'(?<=[.!?])(?=[А-ЯЁA-Z])',' ',text)
    for paragraph in text.splitlines():
        paragraph=re.sub(r'\s+',' ',paragraph).strip()
        for sentence in re.split(r'(?<=[.!?])\s+(?=[А-ЯЁA-Z—–])',paragraph):
            # Leading dialogue ellipses may split off before a proper name.
            # Layout punctuation alone is not an independent utterance.
            if not any(c.isalnum() for c in sentence):continue
            while len(sentence)>limit:
                boundaries=[m.end() for m in re.finditer(r'[,;:]\s+|\s+[—–]\s+',sentence[:limit+1]) if m.end()>limit//3]
                cut=boundaries[-1] if boundaries else sentence.rfind(' ',0,limit+1)
                if cut<=0:cut=limit
                piece=sentence[:cut].strip()
                if any(c.isalnum() for c in piece):yield piece
                sentence=sentence[cut:].strip()
            if any(c.isalnum() for c in sentence):yield sentence

def prepare(text):
    # Dialogue dashes are book layout. Unicode/triple-dot ellipses can trap
    # Higgs in a non-terminating continuation on very short utterances.
    text=re.sub(r'(?m)^\s*(?:[—–]\s*|-\s+)','',text)
    def pause(match):
        following=match.string[match.end():].lstrip()
        if following and following[0] in '?!,;:.':return ''
        if following and following[0].isupper():return '. ' if any(c.isalnum() for c in match.string[:match.start()]) else ''
        return ', ' if re.match(r'\w',following) else '.'
    text=re.sub(r'(?:…|\.{3,})+',pause,text)
    text=re.sub(r'\s+',' ',text).strip()
    text=re.sub(r'([,;:])\s*([,;:.!?])',r'\2',text)
    text=text.lstrip(' ,;:').strip()
    # Extracted author insertions start mid-sentence in the book. Each TTS
    # request is independent, so give it a sentence start, not a continuation.
    first=re.search(r'(?<!\w)[а-яёa-z]',text,re.I)
    if first and any(c.isalnum() for c in text[:first.start()]):first=None
    if first:text=text[:first.start()]+text[first.start()].upper()+text[first.end():]
    # A title or imported fragment without terminal punctuation can leave
    # the autoregressive decoder waiting for continuation instead of EOC.
    if text and text[-1].isalnum():text+='.'
    return text

def frame_budget(text):
    # 25 generated frames/s. Leave a generous allowance for slow speech;
    # short utterances must not be allowed to loop for a full minute.
    syllables=len(re.findall(r'[аеёиоуыэюяaeiouy]',text,re.I))
    words=len(re.findall(r'\w+',text))
    return max(384,min(2400,256+16*syllables+4*words))
