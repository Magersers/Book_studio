"""Persistent book states, JSON markup snapshots and cooperative controls."""
import json,os,time
from pathlib import Path
import avatar_store as store
import book_engine as books
class Stopped(Exception):pass

def migrate(book_id):
    with books.connect(book_id) as db:
        from book_cast import migrate as migrate_cast
        migrate_cast(db)
        columns={r[1] for r in db.execute('PRAGMA table_info(segments)')}
        if 'parts' not in columns:db.execute("ALTER TABLE segments ADD COLUMN parts TEXT DEFAULT '[]'")
        if 'review_reason' not in columns:db.execute("ALTER TABLE segments ADD COLUMN review_reason TEXT DEFAULT ''")
        if 'audio_review' not in columns:db.execute('ALTER TABLE segments ADD COLUMN audio_review INTEGER DEFAULT 0')
        if 'analyzed' not in columns:
            db.execute('ALTER TABLE segments ADD COLUMN analyzed INTEGER DEFAULT 0')
            if books.metadata(book_id).get('analysis_complete'):db.execute('UPDATE segments SET analyzed=1')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='role_batches'").fetchone():
            if 'chapter' not in {r[1] for r in db.execute('PRAGMA table_info(role_batches)')}:
                db.execute('ALTER TABLE role_batches ADD COLUMN chapter INTEGER DEFAULT 0')

def update(book_id,**fields):
    meta=books.metadata(book_id);meta.update(fields);books.save_meta(book_id,meta);return meta

def snapshot(book_id,chapter=None,**fields):
    migrate(book_id)
    with books.connect(book_id) as db:
        total=db.execute('SELECT count(*) FROM segments').fetchone()[0]
        analyzed=db.execute('SELECT count(*) FROM segments WHERE analyzed=1').fetchone()[0]
        role_review_count=db.execute('SELECT count(*) FROM segments WHERE review=1').fetchone()[0]
        rendered=db.execute("SELECT count(*) FROM segments WHERE wav!='' AND signature!=''").fetchone()[0]
        audio_review_count=db.execute("SELECT count(*) FROM segments WHERE audio_review=1 AND wav!='' AND signature!=''").fetchone()[0]
        chapters=[dict(r) for r in db.execute('SELECT * FROM chapters ORDER BY id')]
        characters=[dict(r) for r in db.execute('SELECT * FROM characters ORDER BY name')]
        categories=[dict(r) for r in db.execute('SELECT * FROM cast_categories')]
        aliases=[]
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='character_aliases'").fetchone():aliases=[dict(r) for r in db.execute('SELECT * FROM character_aliases')]
        if chapter is not None:
            rows=[dict(r) for r in db.execute('SELECT id,text,speaker,review,review_reason,manual,analyzed,parts,audio_review FROM segments WHERE chapter=? ORDER BY id',(chapter,))]
            for row in rows:row['parts']=json.loads(row['parts'])
            store.atomic_json(books.folder(book_id)/'markup'/f'chapter-{chapter:04d}.json',dict(chapter=chapter,complete=all(r['analyzed'] for r in rows),segments=rows))
    meta=update(book_id,analysis_done=analyzed,render_done=rendered,total_segments=total,role_review_count=role_review_count,audio_review_count=audio_review_count,analysis_percent=round(100*analyzed/max(1,total),1),render_percent=round(100*rendered/max(1,total),1),analysis_complete=bool(total and analyzed==total),**fields)
    store.atomic_json(books.folder(book_id)/'markup.json',dict(version=1,book_id=book_id,title=meta.get('title'),analysis_complete=meta['analysis_complete'],analysis_percent=meta['analysis_percent'],characters=characters,categories=categories,aliases=aliases,sounds=meta.get('sounds',{}),chapters=[dict(id=c['id'],title=c['title'],avatar=c['avatar'],mode=c['mode'],file=f'markup/chapter-{c["id"]:04d}.json') for c in chapters]))
    return meta

def export_all(book_id):
    migrate(book_id)
    with books.connect(book_id) as db:
        chapters=[r[0] for r in db.execute('SELECT id FROM chapters')]
        for chapter in chapters:
            rows=[dict(r) for r in db.execute('SELECT id,text,speaker,review,review_reason,manual,analyzed,parts,audio_review FROM segments WHERE chapter=? ORDER BY id',(chapter,))]
            for row in rows:row['parts']=json.loads(row['parts'])
            store.atomic_json(books.folder(book_id)/'markup'/f'chapter-{chapter:04d}.json',dict(chapter=chapter,complete=all(r['analyzed'] for r in rows),segments=rows))
    snapshot(book_id)

def refresh_audio(book_id):
    meta=books.metadata(book_id);voices={a['id']:a for a in store.avatars()};changed=False
    with books.connect(book_id) as db:
        chapters={r['id']:r for r in db.execute('SELECT * FROM chapters')}
        from book_cast import voices as cast_voices
        characters=cast_voices(db)
        rows=db.execute("SELECT * FROM segments WHERE wav!='' OR signature!=''").fetchall()
        for row in rows:
            try:
                plan=books.segment_plan(row,chapters[row['chapter']],characters,meta)
                valid=Path(row['wav']).is_file() and row['signature']==books.plan_signature(plan,voices,meta.get('seed',42))
            except (KeyError,OSError):valid=bool(row['signature'] and row['wav'] and Path(row['wav']).is_file())
            if not valid:
                db.execute("UPDATE segments SET wav='',signature='' WHERE id=?",(row['id'],));changed=True
                db.execute("UPDATE chapters SET output='' WHERE id=?",(row['chapter'],))
    if changed:snapshot(book_id,output='',render_complete=False)

def control(book_id,command):store.atomic_json(books.folder(book_id)/'control.json',dict(command=command))

def failed(book_id,message):
    """Persist failure before notifying the GUI, retaining completed fragments."""
    meta=books.metadata(book_id)
    if meta.get('status')=='ready':
        snapshot(book_id,meta.get('active_chapter'),job_status='error',active_chapter=None,last_error=str(message))

def requested(book_id):return store.load_json(books.folder(book_id)/'control.json',{}).get('command','run')

def invalidate(book_id,chapter=None,analysis=False):
    migrate(book_id)
    with books.connect(book_id) as db:
        if analysis:
            db.execute('UPDATE segments SET analyzed=0 WHERE chapter>=?',(chapter or 0,))
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='role_batches'").fetchone():db.execute('DELETE FROM role_batches WHERE chapter>=? OR chapter=0',(chapter or 0,))
        where=' WHERE chapter>=?' if analysis else (' WHERE chapter=?' if chapter else '')
        args=(chapter or 0,) if analysis else ((chapter,) if chapter else ())
        db.execute("UPDATE segments SET wav='',signature=''"+where,args)
        db.execute("UPDATE chapters SET output=''"+(' WHERE id>=?' if analysis else (' WHERE id=?' if chapter else '')),args)
    snapshot(book_id,chapter,output='',render_complete=False)

def restart_audio(book_id,chapter=None):
    """Forget synthesis checkpoints only; keep markup, voices and old exports."""
    with books.connect(book_id) as db:
        ids=[r[0] for r in db.execute('SELECT id FROM chapters'+(' WHERE id=?' if chapter is not None else ''),(chapter,) if chapter is not None else ())]
    if not ids:raise ValueError('Глава не найдена.')
    for cid in ids:
        (books.folder(book_id)/'audio'/f'chapter-{cid:04d}-heading.heading.json').unlink(missing_ok=True)
    invalidate(book_id,chapter)

def force_reset(book_id):
    meta=books.metadata(book_id);chapter=meta.get('active_chapter');stage=meta.get('stage')
    if meta.get('status')!='ready':
        update(book_id,job_status='stopped',active_chapter=None)
        control(book_id,'run')
        return
    # Paid API responses are committed atomically per block. Keep those checkpoints
    # even after a forced close; only the unfinished request needs resubmission.
    api_analysis=stage=='analysis' and meta.get('roles_model','').startswith('deepseek-')
    if chapter and not api_analysis:invalidate(book_id,chapter,analysis=stage=='analysis')
    snapshot(book_id,chapter,job_status='stopped',active_chapter=None,interrupted_chapter=chapter)
    control(book_id,'run')

def recover():
    for meta in books.library():
        if meta.get('status')!='ready':continue
        migrate(meta['id'])
        if meta.get('job_status') in ('running','paused','waiting_chapter'):
            # Atomic checkpoints survive crashes; a chapter interrupted without a graceful exit is restarted.
            force_reset(meta['id'])
        elif not (books.folder(meta['id'])/'markup.json').exists():export_all(meta['id'])

def ready_audio(book_id,chapter=None):
    with books.connect(book_id) as db:
        rows=db.execute('SELECT wav,signature FROM segments '+('WHERE chapter=? ' if chapter else '')+'ORDER BY id',(chapter,) if chapter else ()).fetchall()
    paths=[]
    for row in rows:
        if not row['signature'] or not row['wav'] or not Path(row['wav']).is_file():break
        paths.append(row['wav'])
    return paths

class Control:
    def __init__(self,book_id,stage,emit=lambda *a,**k:None):
        self.book_id=book_id;self.stage=stage;self.emit=emit
        migrate(book_id);update(book_id,stage=stage,job_status='running',active_chapter=None)
    def begin(self,chapter):
        update(self.book_id,active_chapter=chapter,stage=self.stage)
    def boundary(self,chapter,chapter_done=False):
        meta=snapshot(self.book_id,chapter,active_chapter=None if chapter_done else chapter)
        self.emit('book_state',book_id=self.book_id,**{k:meta[k] for k in ('stage','job_status','analysis_percent','render_percent')})
        command=requested(self.book_id)
        if command=='pause':
            update(self.book_id,job_status='paused');self.emit('book_state',book_id=self.book_id,job_status='paused',stage=self.stage)
            while requested(self.book_id)=='pause':time.sleep(.12)
            command=requested(self.book_id)
            update(self.book_id,job_status='running');self.emit('book_state',book_id=self.book_id,job_status='running',stage=self.stage)
        if command=='stop':
            if chapter_done:
                snapshot(self.book_id,chapter,job_status='stopped',active_chapter=None)
                raise Stopped('Остановлено после сохранения главы. Модель выгружена.')
            update(self.book_id,job_status='waiting_chapter')
            self.emit('book_state',book_id=self.book_id,job_status='waiting_chapter',stage=self.stage)
    def finish(self):
        snapshot(self.book_id,job_status='done',active_chapter=None)
