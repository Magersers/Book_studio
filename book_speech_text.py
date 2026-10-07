"""Omit redundant spoken-dialogue attributions from the synthesis plan only.

The original book and lossless role markup are never edited. Ambiguous prose,
actions, negation and thought/silent-speech markers remain with the narrator.
"""
import re

VERBS=(r'сказал[аи]?|спросил[аи]?|ответил[аи]?|воскликнул[аи]?|'
       r'произн[её]с(?:ла|ли)?|проговорил[аи]?|промолвил[аи]?|'
       r'прошептал[аи]?|шепнул[аи]?|прокричал[аи]?|крикнул[аи]?|'
       r'пробормотал[аи]?|добавил[аи]?|заявил[аи]?|заметил[аи]?|'
       r'продолжил[аи]?|переспросил[аи]?|повторил[аи]?|отозвал[аи]сь|отозвался')
ADVERBS=r'(?:вдруг|тихо|громко|спокойно|внезапно|уверенно|неуверенно|шёпотом|шепотом|весело|грустно|задумчиво|резко|быстро|медленно|снова|затем|тут|наконец)'


def without_spoken_attributions(parts,names):
    names={n.strip() for n in names if n and n.strip()}
    names.update(p['speaker'] for p in parts if p.get('speaker'))
    actors=[re.escape(n) for n in sorted(names,key=len,reverse=True)]
    actors+=['он','она','они','я','мы']
    actor='(?:'+'|'.join(actors)+')'
    adv=rf'(?:{ADVERBS}\s+){{0,3}}'
    # Require the entire clause: do not drop actions or reported content
    # after a comma, e.g. "сказала Аня, указывая на дверь".
    attribution=re.compile(rf'^\s*[—–-]?\s*{adv}(?:{actor}\s+{adv}(?:{VERBS})|(?:{VERBS})\s+{adv}{actor})(?:\s+{ADVERBS}){{0,2}}\s*[,.:;!?…]*\s*[—–-]?\s*$',re.I)
    result=[]
    for i,part in enumerate(parts):
        if part.get('speaker') or part.get('kind')=='label':
            result.append(part);continue
        previous=parts[i-1] if i else {}
        following=parts[i+1] if i+1<len(parts) else {}
        follows_dialogue=bool(previous.get('speaker'))
        introduces_dialogue=bool(following.get('speaker')) and part['text'].rstrip().endswith(':')
        if not (follows_dialogue or introduces_dialogue):
            result.append(part);continue
        text=part['text']
        # Examine just the clause adjoining dialogue; narrative sentences
        # elsewhere in the same author part must stay verbatim.
        if follows_dialogue:
            match=re.match(r'^.*?[.!?…](?:\s*[—–-](?=\s|$))?|^.*$',text,re.S)
            boundary=match.end()
            if attribution.fullmatch(text[:boundary]):text=text[boundary:]
        elif introduces_dialogue and attribution.fullmatch(text):
            text=''
        if text.strip(' \t\r\n—–-,:;.'):result.append(dict(part,text=text))
    return result
