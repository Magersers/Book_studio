"""Deterministic spoken chapter numbering, independent of AI role labels."""
import re
from num2words import num2words

def spoken(title):
    def number(m):
        label,value=m.group(1),m.group(2)
        gender='masculine' if label.casefold() in ('том','раздел') else 'feminine'
        if '.' in value:
            words=' точка '.join(num2words(int(n),lang='ru') for n in value.split('.'))
        else:words=num2words(int(value),lang='ru',to='ordinal',gender=gender)
        return label.capitalize()+' '+words+'. '
    text=re.sub(r'\b(том|глава|часть|раздел|книга)\s+(\d+(?:\.\d+)*)\b',number,title,flags=re.I)
    text=re.sub(r'\((\d+)\)\s*$',lambda m:'. Часть '+num2words(int(m[1]),lang='ru',to='ordinal',gender='feminine')+'.',text)
    text=re.sub(r'\s+[—–-]\s+','. ',text)
    text=re.sub(r'\s+([.!?,])',r'\1',text)
    text=re.sub(r'\.(?:\s*\.)+','.',text)
    return re.sub(r'\s+',' ',text).strip()

def same(text,title):
    def key(value):return ' '.join(re.findall(r'\w+',spoken(value).casefold().replace('ё','е')))
    return bool(title.strip()) and key(text)==key(title)
