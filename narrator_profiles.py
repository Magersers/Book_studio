"""Expressive narrator delivery without a fixed emotion or rushed attribution."""
import re

VERSION='narrator-natural-v3'
PROFILES={
    'narrative':dict(label='Естественное повествование',tags='',temperature=.6),
    'attribution':dict(label='Естественная вставка',tags='',temperature=.6),
    'heading':dict(label='Название главы',tags='',temperature=.6),
}
REPORTING=re.compile(r'\b(?:сказ\w*|спрос\w*|ответ\w*|восклик\w*|добав\w*|прошеп\w*|позвал\w*|бурк\w*|предлож\w*|предполож\w*|прокрич\w*|закрич\w*|поддразн\w*|пробормот\w*|произн[её]с\w*|поинтерес\w*|отозва\w*|заяв\w*)\b',re.I)
THOUGHT=re.compile(r'\b(?:подум\w*|думал\w*|мысленно|про\s+себя|задум\w*)\b',re.I)

def split(text,chapter_title=''):
    """Used only on narrator parts. Never infer a speaker from an actor's name."""
    plain=text.strip()
    title=chapter_title.strip()
    if title and plain.casefold()==title.casefold():return [(plain,'heading')]
    # An imported heading may share a fragment with the first prose paragraph.
    if title and plain.casefold().startswith(title.casefold()) and len(plain)>len(title):
        tail=plain[len(title):]
        if tail[0].isspace() or tail[0] in '.:—–':
            rest=tail.lstrip(' \t\r\n.:—–')
            if rest and rest[0].isupper():return [(plain[:len(title)],'heading'),(rest,'narrative')]
    if len(plain)<100 and re.fullmatch(r'(?:Глава|Часть|Раздел)\s+(?:\d+|[IVXLCDM]+|первая|вторая|третья|четв[её]ртая|пятая|шестая|седьмая|восьмая|девятая|десятая)[.:]?',plain,re.I):
        return [(plain,'heading')]
    words=re.findall(r'\w+',plain)
    short=len(plain)<=110 and len(words)<=12 and not re.search(r'[.!?…]\s+\w',plain)
    from roles_text import ACTION
    reports=list(REPORTING.finditer(plain))
    other_action=any(not any(r.start()<=a.start()<r.end() for r in reports) for a in re.finditer(r'\b'+ACTION+r'\b',plain,re.I))
    mode='attribution' if short and reports and not THOUGHT.search(plain) and not other_action else 'narrative'
    return [(plain,mode)]

def controlled_input(text,profile):
    if profile not in PROFILES:raise ValueError('Неизвестный режим автора.')
    # Strip embedded controls; delivery is owned by the application.
    plain=re.sub(r'<\|[^<>]*\|>','',text).strip()
    return PROFILES[profile]['tags']+plain
