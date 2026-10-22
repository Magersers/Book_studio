"""Bound utterances without splitting or deleting Drama 3 inline controls."""
import re


def chunks(text, limit=420):
    tokens = re.findall(r'\[[^\]\n]*\]|\S+', text.strip())
    result = []
    length = 0
    for token in tokens:
        if result and length + len(token) + 1 > limit:
            yield ' '.join(result)
            result, length = [], 0
        result.append(token)
        length += len(token) + 1
    if result:
        yield ' '.join(result)


def frame_budget(text):
    words = re.findall(r'\w+', re.sub(r'\[[^\]]*\]', '', text))
    # 21.5 codec frames/sec; allow slow, emotional delivery plus end-of-speech.
    return min(2600, max(215, int((len(words) / 1.4 + 4) * 21.5)))
