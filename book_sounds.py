"""Book-local sound cues and imported audio, independent of voice avatars."""
import hashlib,json,math,re,uuid
from pathlib import Path

RULES='''Выделяй звуковые вставки (*скрип*, *динь*, *стук*, звукоподражания вне реплики) отдельной частью kind="sound", speaker="". sound_description — кратко источник звука по контексту, например «Скрип отодвигаемого стула». Для остальных частей sound_description="". Не превращай описание «он услышал звон» целиком в звук, не помечай обычный курсив или кашель/междометие внутри речи персонажа. Не добавляй отсутствующие звуки. Сохраняй исходные символы и положение вставки.'''
RULES+=''' Для kind="sound" дополнительно можно указать sound_prompt — короткое описание самого слышимого звука на английском (от 4 до 1000 символов), и sound_duration — длительность от 0.5 до 12 секунд. Укажи источник, действие и акустическую среду по реальному контексту: например "Two dry creaks of a wooden cart axle rolling slowly outdoors". Это звуковой эффект, без музыки, речи или голоса. Не добавляй действий, которых нет в сцене. Пример «Скрип-скрип.» может стать kind="sound", а соседнее «Слышался скрип колёс» остаётся дословным content рассказчика. У остальных частей эти два необязательных поля не указывай. sound_description сохраняй для человека и старой разметки; text и unit_id всегда исходные, не заменяй их английским промптом.'''

def extend(part):
    part['properties']['kind']['enum'].append('sound')
    part['properties']['sound_description']={'type':'string'}
    part['required'].append('sound_description')
    part['properties']['sound_prompt']={'type':'string','maxLength':1000}
    part['properties']['sound_duration']={'type':'number','minimum':.5,'maximum':12}

def validate_part(part):
    if not isinstance(part,dict):raise ValueError('Звуковая часть должна быть объектом.')
    if 'sound_prompt' in part:
        prompt=part['sound_prompt']
        if not isinstance(prompt,str) or len(prompt)>1000:raise ValueError('sound_prompt должен быть строкой до 1000 символов.')
        if prompt and (len(prompt.strip())<4 or not re.search('[A-Za-z]',prompt) or re.search('[А-Яа-яЁё]',prompt)):
            raise ValueError('sound_prompt должен кратко описывать звук на английском.')
        if prompt and part.get('kind','content')!='sound':raise ValueError('sound_prompt допустим только у kind=sound.')
    if 'sound_duration' in part:
        seconds=part['sound_duration']
        if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or not .5<=seconds<=12:
            raise ValueError('sound_duration должен быть числом от 0.5 до 12 секунд.')
        if part.get('kind','content')!='sound':raise ValueError('sound_duration допустим только у kind=sound.')

def generation_input(part,meta):
    """Build model input separately; never replace source text or old descriptions."""
    validate_part(part)
    result=dict(part,sound_seed=int(meta.get('seed',42)))
    description=part.get('sound_description','')
    if not result.get('sound_prompt') and (not isinstance(description,str) or len(description.strip())<4):
        result['sound_description']='Short isolated sound corresponding to the written cue: '+part['text']
    return result

def generation_key(part,meta):
    from sound_engine import specification
    spec=specification(generation_input(part,meta))
    return hashlib.sha256(json.dumps(spec,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def generated_record(part,meta):
    if not meta.get('sound_generation_enabled',False):return None
    record=meta.get('generated_sounds',{}).get(generation_key(part,meta))
    if record and Path(record.get('file','')).is_file():return dict(record)
    return None

def automatic(part,meta):
    choices=meta.get('sounds',{});choice=choices.get(identity(part),choices.get(legacy_identity(part),{}))
    return bool(meta.get('sound_generation_enabled',False) and not choice.get('file')
                and choice.get('fallback','auto')=='auto')

def prepare(book_id,progress=lambda *args:None,cancel=lambda:None,chapter_id=None,boundary=lambda:None):
    """Generate only analyzed sound inserts, before any speech cache is checked."""
    import book_engine as b
    from sound_engine import generate,cached_path,VERSION
    from routerai_engine import check_cancel
    meta=b.metadata(book_id)
    if not meta.get('sound_generation_enabled',False):return meta
    parts={}
    with b.connect(book_id) as db:
        query='SELECT parts FROM segments WHERE analyzed=1 '+('AND chapter=? ' if chapter_id is not None else '')+'ORDER BY id'
        for row in db.execute(query,(chapter_id,) if chapter_id is not None else ()):
            for part in json.loads(row['parts'] or '[]'):
                if part.get('kind')=='sound' and automatic(part,meta):
                    parts.setdefault(generation_key(part,meta),part)
    cache=b.folder(book_id)/'sounds/generated'
    for index,(key,part) in enumerate(parts.items()):
        boundary()
        check_cancel();cancel();b.cancelled(book_id)
        def update(value,message):
            progress(None if value is None else (index+max(0.,min(1.,value)))/max(1,len(parts)),
                     f'Звук {index+1}/{len(parts)} · '+message)
        request=generation_input(part,meta)
        path=cached_path(request,cache) or generate(request,cache,update,cancel)
        check_cancel();cancel()
        # A completed cue is durable even if a later cue is cancelled.
        meta=b.metadata(book_id)
        meta.setdefault('generated_sounds',{})[key]=dict(file=str(path),group_id=identity(part),model=VERSION,
            sound_prompt=part.get('sound_prompt',''),sound_description=part.get('sound_description',''),
            sound_duration=part.get('sound_duration',3.),sound_seed=request['sound_seed'])
        b.save_meta(book_id,meta)
        progress((index+1)/max(1,len(parts)),f'Звук {index+1}/{len(parts)} готов')
        boundary()
    if not parts:progress(1,'Нет звуковых вставок для автоматической генерации')
    return meta

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
                item=found.setdefault(ident,dict(id=ident,text=p['text'].strip(),description=p.get('sound_description',''),chapters=set(),count=0,legacy_ids=set(),variants=set(),_parts=[]))
                item['chapters'].add(row['chapter']);item['count']+=1
                item['_parts'].append(p)
                item['legacy_ids'].add(legacy_identity(p));item['variants'].add(p['text'].strip())
    meta=b.metadata(book_id);choices=meta.get('sounds',{});changed=False
    for item in found.values():
        old=[choices[k] for k in sorted(item['legacy_ids']) if k in choices]
        unique={json.dumps(c,sort_keys=True):c for c in old}
        item['conflict']=item['id'] not in choices and len(unique)>1
        if item['id'] not in choices and len(unique)==1:
            choices[item['id']]=dict(next(iter(unique.values())));changed=True
        item['choice']=dict(choices.get(item['id'],{}))
        records=[generated_record(p,meta) for p in item.pop('_parts')]
        item['generated']=next((record for record in records if record),None)
        item['generated_file']=item['generated']['file'] if item['generated'] else ''
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
    if automatic(part,meta):
        record=generated_record(part,meta)
        if record:return dict(text=part['text'],avatar='',sound_file=record['file'],generated_sound=True)
    return dict(part,text=part['text'].strip().strip('*').strip(),speaker='',kind='content')

def save(book_id,ident,choice):
    import book_engine as b
    import book_state as state
    meta=b.metadata(book_id);meta.setdefault('sounds',{})[ident]=choice;b.save_meta(book_id,meta)
    state.refresh_audio(book_id);state.export_all(book_id)
