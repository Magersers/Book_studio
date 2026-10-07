"""Repair automatic narration assignments in an idle, already analyzed book."""
import json
from datetime import datetime
import sqlite3
import book_engine as books
import book_state as state
from book_edit import editable
from roles_text import normalize_narration


def repair(book_id):
    editable(book_id)
    with books.connect(book_id) as db:
        names={r[0] for r in db.execute('SELECT name FROM characters')}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='character_aliases'").fetchone():
            names.update(r[0] for r in db.execute('SELECT alias_key FROM character_aliases'))
        changes=[]
        for row in db.execute('SELECT * FROM segments WHERE manual=0 AND analyzed=1'):
            parts=json.loads(row['parts']) or [dict(text=row['text'],speaker=row['speaker'])]
            corrected=normalize_narration(parts,row['text'],names)
            if corrected!=parts or (row['speaker'] and not any(p.get('speaker') for p in corrected)):
                changes.append((row['id'],row['chapter'],corrected))
        if not changes:return []
        backup=books.folder(book_id)/'backups'/datetime.now().strftime('narration-%Y%m%d-%H%M%S-%f')
        backup.mkdir(parents=True)
        from contextlib import closing
        with closing(sqlite3.connect(backup/'book.sqlite')) as dest:db.backup(dest)
        books.store.atomic_json(backup/'book.json',books.metadata(book_id))
        # Acquire the write lock and re-check idle state before mutations.
        db.execute('BEGIN IMMEDIATE')
        if books.metadata(book_id).get('job_status') in ('running','paused','waiting_chapter'):
            raise ValueError('Книга начала обработку; исправление отложено.')
        for sid,cid,parts in changes:
            db.execute("UPDATE segments SET speaker='',parts=?,review=0,wav='',signature='',audio_review=0 WHERE id=? AND manual=0",
                       (json.dumps(parts,ensure_ascii=False),sid))
            db.execute("UPDATE chapters SET output='' WHERE id=?",(cid,))
    state.update(book_id,output='',render_complete=False)
    state.export_all(book_id)
    return [sid for sid,_,_ in changes]
