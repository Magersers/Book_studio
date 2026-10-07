"""Incremental, source-grounded character memory; user notes stay separate."""
import json

INSTRUCTION='''Для characters добавляй portrait и возвращай существующего персонажа, когда появились новые сведения о нём. portrait.role — роль, возраст/пол только если известны, положение в семье/сюжете; traits — устойчивые черты; voice — подтверждённые особенности речи, полезные для выбора аватара; relationships — объекты character (каноническое имя другого героя), relationship (например младший брат, отец, слуга, противник), attitude (доброжелательное, враждебное, нейтральное, скрытое или неизвестное, с кратким уточнением). Связи направленные: отец Кейла — отношение Дерита к Кейлу, не наоборот. state — ТЕКУЩЕЕ состояние в этом блоке, отдельно от постоянных черт. Не превращай разовую злость в постоянную вражду; не считай притворную доброту истинным отношением. Не выдумывай факты, возраст, тембр или родство по одному имени. Пустое значение означает, что новых сведений нет. Дополняй known_characters.portrait, не теряй подтверждённые факты; меняй связь только при явном развитии сюжета. Используй portrait и user_notes для распознавания персонажей и понимания интонации в текущей сцене. Старое state не переносится автоматически на новую сцену: текущий текст имеет приоритет. Не добавляй сведения портрета в озвучиваемый текст.'''

INSTRUCTION+=' relationship записывай ПОЛНЫМ предложением с обоими именами, чтобы направление связи не перепуталось: «Басен — младший брат Кейла», «Дерит — отец Кейла», «Кейл — сын Дерита». Не оставляй только «отец» или «брат». Не выдавай планы и желания за уже произошедшие события.'

def schema():
    relationship=dict(type='object',properties={k:dict(type='string') for k in ('character','relationship','attitude')},required=['character','relationship','attitude'],additionalProperties=False)
    return dict(type='object',properties=dict(role=dict(type='string'),traits=dict(type='array',items=dict(type='string')),voice=dict(type='string'),relationships=dict(type='array',items=relationship),state=dict(type='string')),required=['role','traits','voice','relationships','state'],additionalProperties=False)

def read(value):
    try:result=json.loads(value or '{}')
    except (TypeError,ValueError):return {}
    return result if isinstance(result,dict) else {}

def clean(value,limit=600):return value.strip()[:limit] if isinstance(value,str) else ''

def merge(old,update):
    result=dict(old)
    if not isinstance(update,dict):return result
    for field in ('role','voice'):
        value=clean(update.get(field))
        if value:result[field]=value
    traits=list(result.get('traits',[]))
    incoming=update.get('traits',[])
    if isinstance(incoming,list):
        for item in incoming:
            item=clean(item,180)
            if item and item.casefold() not in {v.casefold() for v in traits}:traits.append(item)
    result['traits']=traits[-24:]
    relations={r['character'].casefold().replace('ё','е'):r for r in result.get('relationships',[]) if isinstance(r,dict) and isinstance(r.get('character'),str)}
    incoming=update.get('relationships',[])
    if isinstance(incoming,list):
        for row in incoming:
            if not isinstance(row,dict):continue
            name=clean(row.get('character'),120)
            if not name:continue
            key=name.casefold().replace('ё','е');item=dict(relations.get(key,{}),character=name)
            for field in ('relationship','attitude'):
                value=clean(row.get(field),240)
                if value:item[field]=value
            relations[key]=item
    result['relationships']=list(relations.values())[-30:]
    # This field is explicitly a recent observation, not a permanent trait.
    result['state']=clean(update.get('state'),400)
    return result

def apply(db,character,name,chapter=None):
    if not isinstance(character.get('portrait'),dict):return
    row=db.execute('SELECT portrait FROM characters WHERE name=?',(name,)).fetchone()
    portrait=merge(read(row[0]),character['portrait'])
    if chapter is not None:portrait['updated_chapter']=chapter
    db.execute('UPDATE characters SET portrait=? WHERE name=?',(json.dumps(portrait,ensure_ascii=False),name))

def describe(portrait):
    lines=[]
    for label,key in [('Кто это','role'),('Речь и голос','voice')]:
        if portrait.get(key):lines.append(f'{label}: {portrait[key]}')
    if portrait.get('traits'):lines.append('Черты: '+', '.join(portrait['traits']))
    for row in portrait.get('relationships',[]):
        lines.append(row['character']+': '+'; '.join(row.get(k,'') for k in ('relationship','attitude') if row.get(k)))
    if portrait.get('state'):lines.append('Последнее состояние (не постоянная эмоция): '+portrait['state'])
    if portrait.get('updated_chapter'):lines.append('Последнее обновление: глава '+str(portrait['updated_chapter']))
    return '\n\n'.join(lines) or 'Портрет появится после разметки новых глав или повторной разметки книги.'
