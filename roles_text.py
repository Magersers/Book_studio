"""Anchor model-assigned speakers to the original book, never rewritten prose."""
import re

# Third-person actions in unquoted prose are narration, not utterances by
# the person doing the action. Keep explicit dialogue, labels and thoughts.
ACTION=r'(?:взял[аи]?|достал[аи]?|посмотрел[аи]?|развернул[аи]?|осмотрел[аи]?|прот[её]р(?:ла|ли)?|показал[аи]?|указал[аи]?|заметил[аи]?|скрестил[аи]?|приподнял[аи]?|поднял[аи]?|опустил[аи]?|подош[её]л|подошл[аи]|приш[её]л|пришл[аи]|пош[её]л|пошл[аи]|вош[её]л|вошл[аи]|заглянул[аи]?|улыбнул(?:ся|ась|ись)|рассмеял(?:ся|ась|ись)|замял(?:ся|ась|ись)|наклонил(?:ся|ась|ись)|выпрямил(?:ся|ась|ись)|сверил(?:ся|ась|ись)|замер(?:ла|ли)?|вздохнул[аи]?|покачал[аи]?|сел[аи]?|встал[аи]?|остановил(?:ся|ась|ись)|позвал[аи]?|отпрыгнул[аи]?|замолчал[аи]?|прин[её]с(?:ла|ли)?)'


def is_action_narration(text,names):
    # An explicit voice cue takes priority over the words inside the quote.
    if re.match(r'^\s*[—–\-«„"“]',text):return False
    if re.search(r'(?:[.!?:]\s*)[—–]\s*\S',text):return False
    if re.search(r'\b(?:подум\w*|мысленно|про\s+себя)\b',text,re.I):return False
    if any(q in text for q in ('«','»','"','“','”','„')) and not re.search(r'\bнаписан[оаы]?\b\s*:',text,re.I):return False
    subjects={n.strip() for n in names if n and n.strip()}|{'он','она','они','ребята','все','дедушка'}
    subject='(?:'+'|'.join(re.escape(n) for n in sorted(subjects,key=len,reverse=True))+')'
    if re.match(rf'^\s*{subject}\s*:',text,re.I):return False
    adverb=r'(?:медленно|быстро|осторожно|внимательно|немного|снова|тоже|первым|первой|сразу|вдруг|широко)'
    action=re.compile(rf'\b{subject}\s+(?:{adverb}\s+){{0,3}}{ACTION}\b',re.I)
    # A named subject plus an action must occur before any written quotation.
    plain=text.split('«',1)[0].split('"',1)[0]
    if '?' in plain or '!' in plain or re.search(r'\b(?:я|мы|ты|вы|мне|тебе|вам|нам|меня|нас|вас)\b',plain,re.I):return False
    if action.search(plain):return True
    return bool(re.fullmatch(r'\s*(?:шорох|шум|стук|звук|ветер|дождь)\s+(?:повторился|послышался|раздался|начался|усилился|стих)[.]?\s*',text,re.I))


def normalize_narration(parts,source,names):
    if is_action_narration(source,names):
        return [dict(p,speaker='') if p.get('kind')!='label' else p for p in parts]
    return parts

AUTHOR=re.compile(r'\s[—–]\s+(?:(?:вдруг|тихо|громко|внезапно|спокойно|задумчиво|разочарованно)\s+)?(?:[А-ЯЁ][а-яё]+\s+)?(?:сказ|подум|ответ|восклик|удив|заяв|рассме|засме|спрос|прошеп|прокрич|замет|добав|улыб|вздох|пробормот|позвал|закрич|поддразн|предполож|предлож|задум|поинтерес|согласил|бурк|отозва)\w*')

def explicit_dialogue(source,parts,names):
    """A named reporting clause is stronger evidence than a model's narrator guess."""
    if not re.match(r'^\s*[—–]\s*\S',source):return parts
    speakers=set()
    for match in AUTHOR.finditer(source):
        end=re.search(r'[.!?]|\s[—–]\s',source[match.end():])
        clause=source[match.start():match.end()+(end.start() if end else len(source))]
        for name in names:
            if re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',clause,re.I):speakers.add(name)
    if len(speakers)!=1:return parts
    name=next(iter(speakers))
    return split_author_insertions([dict(text=source,speaker=name)])


def split_author_insertions(parts):
    """Split explicit lower-case reporting clauses without changing any text."""
    output=[]
    for part in parts:
        if not part.get('speaker'):
            output.append(part);continue
        text=part['text']
        while True:
            match=AUTHOR.search(text)
            if not match:
                if text:output.append(dict(part,text=text))
                break
            if text[:match.start()]:output.append(dict(part,text=text[:match.start()]))
            continuation=re.search(r'\s[—–]\s+(?=[А-ЯЁ«„"])',text[match.end():])
            end=match.end()+continuation.start() if continuation else len(text)
            output.append(dict(text=text[match.start():end],speaker=''))
            text=text[end:]
    return output


def reassign_parts(parts,source,speaker):
    """Apply a human role correction, retaining narrator clauses and number readings."""
    if not parts:parts=[dict(text=source,speaker='')]
    if speaker and not any(p.get('speaker') for p in parts):
        rebuilt=[]
        for part in parts:
            if part.get('kind') in ('label','sound'):rebuilt.append(dict(part));continue
            pieces=split_author_insertions([dict(text=part['text'],speaker=speaker)])
            if part.get('spoken_text'):
                spoken=split_author_insertions([dict(text=part['spoken_text'],speaker=speaker)])
                if len(pieces)==len(spoken) and [p['speaker'] for p in pieces]==[p['speaker'] for p in spoken]:
                    for original,expanded in zip(pieces,spoken):original['spoken_text']=expanded['text']
            rebuilt.extend(pieces)
        return rebuilt
    return [dict(p,speaker=speaker) if p.get('speaker') else dict(p) for p in parts]


def restore_source_parts(parts,source):
    if ''.join(p['text'] for p in parts)==source:return parts
    tokens=list(re.finditer(r'\w+',source))
    proposed=[list(re.finditer(r'\w+',p['text'])) for p in parts]
    normalize=lambda word:word.casefold().replace('ё','е')
    expected=[normalize(m[0]) for m in tokens]
    actual=[normalize(m[0]) for words in proposed for m in words]
    if actual!=expected:
        raise ValueError('Модель пропустила, добавила или заменила слова исходного текста')
    if any(not words for words in proposed):
        # Punctuation-only boundaries cannot be located by word order safely.
        raise ValueError('Неоднозначная граница части без слов')
    result=[];start=0;used=0
    for i,(part,words) in enumerate(zip(parts,proposed)):
        used+=len(words)
        if i==len(parts)-1:end=len(source)
        else:
            end=tokens[used-1].end();next_word=tokens[used].start()
            # Keep closing punctuation with the preceding clause; opening
            # quotes and a dialogue dash belong to the next clause.
            while end<next_word and source[end] in ',.!?…;:»”)]':end+=1
        result.append(dict(part,text=source[start:end]));start=end
    assert ''.join(p['text'] for p in result)==source
    return result
