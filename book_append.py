"""Append new chapters transactionally without replacing existing book data."""
from pathlib import Path
import book_engine as books
import book_state as state

def append(book_id,path,progress=lambda *a:None):
    state.migrate(book_id)
    meta=books.metadata(book_id)
    warnings=list(meta.get('warnings',[]))
    with books.connect(book_id) as db:
        first=db.execute('SELECT coalesce(max(id),0)+1 FROM chapters').fetchone()[0]
        chapter=first-1;size=0;added=0
        for text,heading in books.blocks(path,warnings,progress,lambda:books.cancelled(book_id)):
            books.cancelled(book_id);text=text.strip()
            if not text:continue
            if heading or chapter<first or size>=30000:
                chapter+=1;size=0
                db.execute('INSERT INTO chapters(id,title) VALUES(?,?)',(chapter,text[:160] if heading else f'Раздел {chapter}'))
            for part in books.chunks(text):
                if size and size+len(part)>30000:
                    chapter+=1;size=0
                    db.execute('INSERT INTO chapters(id,title) VALUES(?,?)',(chapter,f'Раздел {chapter}'))
                db.execute('INSERT INTO segments(chapter,text) VALUES(?,?)',(chapter,part));size+=len(part);added+=1
        if not added:raise ValueError('В дополнении не найден текст. Книга не изменена.')
        # Keep the append boundary in the same transaction as imported text.
        db.execute('CREATE TABLE IF NOT EXISTS append_state(id INTEGER PRIMARY KEY CHECK(id=1),first_chapter INTEGER)')
        db.execute('INSERT INTO append_state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET first_chapter=min(first_chapter,excluded.first_chapter)',(first,))
        chapters=db.execute('SELECT count(*) FROM chapters').fetchone()[0]
        total=db.execute('SELECT count(*) FROM segments').fetchone()[0]
    state.update(book_id,chapters=chapters,segments=total,warnings=warnings,analyzed=False,ai_chapters_complete=False,output='',render_complete=False)
    state.export_all(book_id)
    return dict(added=added,first_chapter=first)

def boundary(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='append_state'").fetchone():return None
    row=db.execute('SELECT first_chapter FROM append_state WHERE id=1').fetchone()
    return row[0] if row else None
