"""Persistent cast groups; individual voices always override group defaults."""
import json

CATEGORIES={'main':'Главные персонажи','supporting':'Второстепенные персонажи','episodic':'Эпизодические персонажи'}
INSTRUCTION='''Для каждого characters укажи category: main (центральные герои и важные для сюжета близкие, например семья главного героя), supporting (второстепенные устойчивые роли, слуги, спутники), episodic (разовые участники). category_reason — краткое обоснование по сюжету. Используй known_characters с dialogue_count и category: число реплик помогает, но само по себе не определяет важность. Именованный слуга может быть главным героем по сюжету. Не объединяй разных персонажей одной категории в одну роль. Возвращай также существующих персонажей, если уточняешь их категорию. Ручная категория category_manual имеет приоритет.'''

def migrate(db):
    columns={r[1] for r in db.execute('PRAGMA table_info(characters)')}
    for name,definition in [('category',"TEXT DEFAULT 'supporting'"),('category_reason',"TEXT DEFAULT ''"),('category_manual','INTEGER DEFAULT 0'),('portrait',"TEXT DEFAULT '{}'"),('user_notes',"TEXT DEFAULT ''")]:
        if name not in columns:db.execute(f'ALTER TABLE characters ADD COLUMN {name} {definition}')
    db.execute("CREATE TABLE IF NOT EXISTS cast_categories(id TEXT PRIMARY KEY,avatar TEXT DEFAULT '')")
    existing={r[0] for r in db.execute('SELECT id FROM cast_categories')}
    missing=[(k,) for k in CATEGORIES if k not in existing]
    if missing:db.executemany('INSERT INTO cast_categories(id) VALUES(?)',missing)
    db.execute("CREATE TABLE IF NOT EXISTS chapter_context(chapter INTEGER PRIMARY KEY,summary TEXT DEFAULT '')")

def voices(db):
    migrate(db)
    groups={r['id']:r['avatar'] for r in db.execute('SELECT * FROM cast_categories')}
    return {r['name']:r['avatar'] or groups.get(r['category'],'') for r in db.execute('SELECT * FROM characters')}

def counts(db):
    result={r[0]:0 for r in db.execute('SELECT name FROM characters')}
    for row in db.execute('SELECT text,speaker,parts FROM segments'):
        parts=json.loads(row['parts'] or '[]') or [dict(text=row['text'],speaker=row['speaker'])]
        # Count speaking turns, merging adjacent parts of the same speaker.
        previous=None
        for part in parts:
            speaker=part.get('speaker','')
            if speaker and speaker!=previous and part.get('kind','content')=='content':result[speaker]=result.get(speaker,0)+1
            previous=speaker
    db.executemany('UPDATE characters SET mentions=? WHERE name=?',[(n,name) for name,n in result.items()])
    return result

def extend_schema(character):
    character['properties'].update(category={'type':'string','enum':list(CATEGORIES)},category_reason={'type':'string'})
    character['required']+=['category','category_reason']
    from character_portrait import schema
    character['properties']['portrait']=schema();character['required'].append('portrait')

def apply_category(db,character,name):
    category=character.get('category')
    if category in CATEGORIES:
        db.execute('UPDATE characters SET category=?,category_reason=? WHERE name=? AND category_manual=0',
                   (category,str(character.get('category_reason',''))[:400],name))
