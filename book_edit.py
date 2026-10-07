"""Durable library edits. Deleted books are retained in the local trash state."""
import json
import book_engine as b
import book_state as state

def editable(bid):
    if b.metadata(bid).get('job_status') in ('running','paused','waiting_chapter'):
        raise ValueError('Сначала нажмите «Стоп» и дождитесь сохранения книги.')
    state.migrate(bid)

def recount(bid):
    with b.connect(bid) as db:
        chapters=db.execute('SELECT count(*) FROM chapters').fetchone()[0]
        segments=db.execute('SELECT count(*) FROM segments').fetchone()[0]
        db.execute('UPDATE characters SET mentions=(SELECT count(*) FROM segments WHERE speaker=characters.name)')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='role_batches'").fetchone():db.execute('DELETE FROM role_batches')
    state.update(bid,chapters=chapters,segments=segments,output='',render_complete=False,job_status='stopped',active_chapter=None)
    state.export_all(bid)

def rename_book(bid,title):
    editable(bid)
    if not title.strip():raise ValueError('Введите название книги.')
    state.update(bid,title=title.strip()[:200]);state.snapshot(bid)

def delete_book(bid):
    editable(bid);state.update(bid,status='deleted',job_status='stopped')

def restore_book(bid):
    state.update(bid,status='ready');state.export_all(bid)

def delete_chapter(bid,cid):
    editable(bid)
    with b.connect(bid) as db:
        db.execute('DELETE FROM segments WHERE chapter=?',(cid,));db.execute('DELETE FROM chapters WHERE id=?',(cid,))
    # Obsolete chapter JSON must not remain in the active markup directory.
    path=b.folder(bid)/'markup'/f'chapter-{cid:04d}.json'
    if path.exists():path.unlink()
    recount(bid)

def rename_chapter(bid,cid,title):
    editable(bid)
    if not title.strip():raise ValueError('Введите название главы.')
    title=title.strip()[:160]
    with b.connect(bid) as db:
        old=db.execute('SELECT title FROM chapters WHERE id=?',(cid,)).fetchone()
        if not old:raise ValueError('Глава не найдена.')
        first=db.execute('SELECT id,text FROM segments WHERE chapter=? ORDER BY id LIMIT 1',(cid,)).fetchone()
        db.execute('UPDATE chapters SET title=? WHERE id=?',(title,cid))
        if first and first['text']==old['title']:
            db.execute("UPDATE segments SET text=?,speaker='',parts=?,wav='',signature='' WHERE id=?",(title,json.dumps([dict(text=title,speaker='')],ensure_ascii=False),first['id']))
            db.execute("UPDATE chapters SET output='' WHERE id=?",(cid,))
    recount(bid)

def character(bid,old,new=None):
    editable(bid);new=new.strip() if new else ''
    if len(new)>120:raise ValueError('Имя персонажа — не более 120 символов.')
    if new.casefold() in ('автор','рассказчик','narrator'):raise ValueError('Автор — постоянная роль. Для передачи реплик автору удалите персонажа.')
    with b.connect(bid) as db:
        if new and any(r[0].casefold()==new.casefold() and r[0]!=old for r in db.execute('SELECT name FROM characters')):raise ValueError('Персонаж с таким именем уже существует.')
        for row in db.execute('SELECT id,speaker,parts FROM segments').fetchall():
            parts=json.loads(row['parts']);changed=row['speaker']==old
            for part in parts:
                if part['speaker']==old:part['speaker']=new;changed=True
            if changed:
                db.execute("UPDATE segments SET speaker=?,parts=?,manual=1,wav='',signature='' WHERE id=?",(new if row['speaker']==old else row['speaker'],json.dumps(parts,ensure_ascii=False),row['id']))
        if new:db.execute('UPDATE characters SET name=? WHERE name=?',(new,old))
        else:db.execute('DELETE FROM characters WHERE name=?',(old,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='character_aliases'").fetchone():
            if new:
                from roles_analysis import key
                db.execute('UPDATE character_aliases SET name=? WHERE name=?',(new,old))
                db.execute('INSERT OR REPLACE INTO character_aliases VALUES(?,?)',(key(old),new))
            else:db.execute('DELETE FROM character_aliases WHERE name=?',(old,))
        db.execute("UPDATE chapters SET output='' WHERE id IN (SELECT DISTINCT chapter FROM segments WHERE signature='')")
    recount(bid)

def delete_segment(bid,sid):
    editable(bid)
    removed_chapter=None
    with b.connect(bid) as db:
        row=db.execute('SELECT chapter FROM segments WHERE id=?',(sid,)).fetchone()
        if not row:return
        db.execute('DELETE FROM segments WHERE id=?',(sid,));db.execute("UPDATE chapters SET output='' WHERE id=?",(row['chapter'],))
        if not db.execute('SELECT 1 FROM segments WHERE chapter=?',(row['chapter'],)).fetchone():
            db.execute('DELETE FROM chapters WHERE id=?',(row['chapter'],))
            removed_chapter=row['chapter']
    if removed_chapter:
        path=b.folder(bid)/'markup'/f'chapter-{removed_chapter:04d}.json'
        if path.exists():path.unlink()
    recount(bid)
