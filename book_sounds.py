"""Book-local sound cues and imported audio, independent of voice avatars."""
import hashlib,json,re,uuid
from pathlib import Path

RULES='''Выделяй звуковые вставки (*скрип*, *динь*, *стук*, звукоподражания вне реплики) отдельной частью kind="sound", speaker="". sound_description — кратко источник звука по контексту, например «Скрип отодвигаемого стула». Для остальных частей sound_description="". Не превращай описание «он услышал звон» целиком в звук, не помечай обычный курсив или кашель/междометие внутри речи персонажа. Не добавляй отсутствующие звуки. Сохраняй исходные символы и положение вставки.'''

def extend(part):
    part['properties']['kind']['enum'].append('sound')
    part['properties']['sound_description']={'type':'string'}
    part['required'].append('sound_description')

def legacy_identity(part):
    return hashlib.sha256((part['text'].strip().casefold()+'|'+part.get('sound_description','').strip().casefold()).encode()).hexdigest()[:24]

def normalized(value):
    return ' '.join(re.findall(r'[\w]+',value.casefold().replace('ё','е')))

def identity(part):
    # Formatting and punctuation do not define a different sound. Keep the
    # source description: a door squeak must not become a violin squeak.
    return hashlib.sha256((normalized(part['text'])+'|'+normalized(part.get('sound_description',''))).encode()).hexdigest()[:24]

def entries(book_id):
    import book_engine as b
    found={}
    with b.connect(book_id) as db:
        for row in db.execute('SELECT chapter,parts FROM segments ORDER BY id'):
            for p in json.loads(row['parts'] or '[]'):
                if p.get('kind')!='sound':continue
                ident=identity(p)
                item=found.setdefault(ident,dict(id=ident,text=p['text'].strip(),description=p.get('sound_description',''),chapters=set(),count=0,legacy_ids=set(),variants=set()))
                item['chapters'].add(row['chapter']);item['count']+=1
                item['legacy_ids'].add(legacy_identity(p));item['variants'].add(p['text'].strip())
    meta=b.metadata(book_id);choices=meta.get('sounds',{});changed=False
    for item in found.values():
        old=[choices[k] for k in sorted(item['legacy_ids']) if k in choices]
        unique={json.dumps(c,sort_keys=True):c for c in old}
        item['conflict']=item['id'] not in choices and len(unique)>1
        if item['id'] not in choices and len(unique)==1:
            choices[item['id']]=dict(next(iter(unique.values())));changed=True
        item['choice']=dict(choices.get(item['id'],{}))
        item['text']=re.sub(r'[*_`]+','',item['text']).strip()
    if changed:
        import book_state as state
        meta['sounds']=choices;b.save_meta(book_id,meta)
        state.refresh_audio(book_id);state.snapshot(book_id)
    return list(found.values())

def import_audio(book_id,path):
    import book_engine as b
    import soundfile as sf
    target=b.folder(book_id)/'sounds'/f'{uuid.uuid4().hex}.wav'
    target.parent.mkdir(exist_ok=True)
    try:
        b.run_ffmpeg(['-i',str(path),'-ac','1','-ar','24000',str(target)],book_id)
        info=sf.info(str(target))
        if info.frames==0:raise ValueError('Аудиофайл пуст.')
    except BaseException:
        target.unlink(missing_ok=True);raise
    return str(target)

def plan(part,meta):
    choices=meta.get('sounds',{});choice=choices.get(identity(part),choices.get(legacy_identity(part),{}))
    path=choice.get('file','')
    if path:
        if not Path(path).is_file():raise ValueError('Не найден выбранный звук: '+path)
        return dict(text=part['text'],avatar='',sound_file=path)
    if choice.get('fallback','narrator')=='skip':return None
    return dict(part,text=part['text'].strip().strip('*').strip(),speaker='',kind='content')

def save(book_id,ident,choice):
    import book_engine as b
    import book_state as state
    meta=b.metadata(book_id);meta.setdefault('sounds',{})[ident]=choice;b.save_meta(book_id,meta)
    state.refresh_audio(book_id);state.export_all(book_id)
