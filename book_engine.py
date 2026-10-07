"""Durable audiobook queue in SQLite, bounded chunks and resumable synthesis."""
import hashlib
import json
import re
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
import avatar_store as store
from book_import import blocks

BOOKS=store.DATA/'books'
class Paused(Exception): pass

def folder(book_id):
    if not str(book_id).isalnum(): raise ValueError('Некорректная книга')
    return BOOKS/book_id

def connect(book_id):
    db=sqlite3.connect(folder(book_id)/'book.sqlite')
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    return db

def cancelled(book_id):
    if (folder(book_id)/'pause').exists(): raise Paused('Остановлено. Готовые фрагменты сохранены.')

def save_meta(book_id,meta): store.atomic_json(folder(book_id)/'book.json',meta)
def metadata(book_id): return store.load_json(folder(book_id)/'book.json',{})
def library():
    BOOKS.mkdir(parents=True,exist_ok=True)
    return sorted([store.load_json(p,{}) for p in BOOKS.glob('*/book.json')],key=lambda x:x.get('created',''),reverse=True)

def chunks(text,limit=420):
    text=re.sub(r'\s+',' ',text).strip()
    while len(text)>limit:
        candidates=[m.end() for m in re.finditer(r'[.!?…;:]\s+|,\s+',text[:limit+1]) if m.end()>limit//3]
        cut=candidates[-1] if candidates else text.rfind(' ',0,limit+1)
        if cut<=0: cut=limit
        yield text[:cut].strip(); text=text[cut:].strip()
    if text: yield text

def import_book(path, book_id, progress):
    from datetime import datetime
    dest=folder(book_id); dest.mkdir(parents=True,exist_ok=True)
    meta=dict(id=book_id,title=Path(path).stem,created=datetime.now().isoformat(timespec='seconds'),status='importing',warnings=[],default_avatar='',seed=42,pause_ms=180)
    save_meta(book_id,meta)
    with connect(book_id) as db:
        db.executescript('''CREATE TABLE chapters(id INTEGER PRIMARY KEY,title TEXT,avatar TEXT DEFAULT '',mode TEXT DEFAULT 'roles',output TEXT DEFAULT '');
        CREATE TABLE segments(id INTEGER PRIMARY KEY,chapter INTEGER,text TEXT,speaker TEXT DEFAULT '',review INTEGER DEFAULT 0,manual INTEGER DEFAULT 0,wav TEXT DEFAULT '',signature TEXT DEFAULT '');
        CREATE INDEX chapter_segments ON segments(chapter,id);
        CREATE TABLE characters(name TEXT PRIMARY KEY,avatar TEXT DEFAULT '',mentions INTEGER DEFAULT 0);
        ''')
        chapter=0; count=0; chapter_size=0
        for text,heading in blocks(path,meta['warnings'],progress,lambda:cancelled(book_id)):
            cancelled(book_id)
            text=text.strip()
            if not text: continue
            if heading or chapter==0 or chapter_size>=30000:
                chapter+=1; chapter_size=0
                db.execute('INSERT INTO chapters(id,title) VALUES(?,?)',(chapter,text[:160] if heading else f'Раздел {chapter}'))
            for part in chunks(text):
                # A DOCX/FB2 paragraph can itself contain hundreds of pages.
                # Bound storage sections even when the reader yields one huge block.
                if chapter_size and chapter_size+len(part)>30000:
                    chapter+=1;chapter_size=0
                    db.execute('INSERT INTO chapters(id,title) VALUES(?,?)',(chapter,f'Раздел {chapter}'))
                db.execute('INSERT INTO segments(chapter,text) VALUES(?,?)',(chapter,part)); count+=1
                chapter_size+=len(part)
            if count%100<5:
                db.commit(); progress(0,f'Импорт: {chapter} глав, {count} фрагментов…')
        if not count:
            raise ValueError('Текст не найден. Для PDF-скана сначала выполните OCR и импортируйте копию с текстовым слоем.')
    meta.update(status='ready',segments=count,chapters=chapter); save_meta(book_id,meta)
    return meta

def analyze(book_id,progress):
    from roles_analysis import analyze as llm_analyze
    return llm_analyze(book_id,progress)


def voice_for(segment,chapter,characters,meta):
    if meta.get('voice_mode')=='single':return meta.get('default_avatar','')
    narrator=chapter['avatar'] or meta.get('default_avatar','')
    return narrator if chapter['mode']=='single' else characters.get(segment['speaker'],'') or narrator

def audio_signature(text,voice,seed):
    from runtime_config import tts_id
    return hashlib.sha256(json.dumps([tts_id(),text,voice,store.avatar_path(voice).stat().st_mtime_ns,seed],ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def segment_plan(segment,chapter,characters,meta):
    parts=json.loads(segment['parts']) if 'parts' in segment.keys() else []
    if not parts:
        parts=[dict(text=segment['text'],speaker=segment['speaker'])]
    from book_heading import same,spoken
    if same(segment['text'],chapter['title']):
        return [dict(text=spoken(chapter['title']),avatar=voice_for({'speaker':''},chapter,characters,meta),narrator_style='heading')]
    from roles_analysis import mark_labels,key
    parts=mark_labels(parts,{key(name) for name in characters}|{key(segment['speaker'])})
    parts=[p for p in parts if p.get('kind') not in ('label','toc','bibliography','credits','book_title') and p['text'].strip()]
    parts=[dict(p,text=p.get('spoken_text',p['text'])) for p in parts]
    if parts and not any(p.get('kind')=='sound' for p in parts) and (meta.get('voice_mode')=='single' or chapter['mode']=='single'):
        parts=[dict(text=' '.join(p['text'].strip() for p in parts),speaker=segment['speaker'])]
    from narrator_profiles import VERSION,split as narrator_parts
    active=meta.get('narrator_profiles')==VERSION
    from higgs_text import speech_chunks
    split_speech=speech_chunks if active else chunks
    single=meta.get('voice_mode')=='single' or chapter['mode']=='single'
    plan=[]
    for part in parts:
        if part.get('kind')=='sound':
            from book_sounds import plan as sound_plan
            part=sound_plan(part,meta)
            if part is None:continue
            if part.get('sound_file'):
                plan.append(part);continue
        if active and (not part.get('speaker') or single):
            for content,style in narrator_parts(part['text'],chapter['title']):
                for text in split_speech(content):plan.append(dict(text=text,avatar=voice_for(part,chapter,characters,meta),narrator_style=style))
        else:
            plan.extend(dict(text=text,avatar=voice_for(part,chapter,characters,meta)) for text in split_speech(part['text']))
    return plan

def plan_signature(plan,voices,seed):
    if any(p.get('sound_file') for p in plan):
        items=[['sound',p['sound_file'],Path(p['sound_file']).stat().st_mtime_ns,Path(p['sound_file']).stat().st_size] if p.get('sound_file') else plan_signature([p],voices,seed) for p in plan]
        return hashlib.sha256(json.dumps(items).encode()).hexdigest()
    signatures=[audio_signature(p['text'],voices[p['avatar']],seed) for p in plan]
    if any(p.get('narrator_style') for p in plan):
        from narrator_profiles import VERSION
        from narrator_reference import select
        anchors=[select(store.avatar_path(voices[p['avatar']]),voices[p['avatar']].get('transcript',''))[2] if p.get('narrator_style') else None for p in plan]
        identity=[VERSION,signatures,[p.get('narrator_style') for p in plan]]
        if any(anchors):identity.append(anchors)
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return signatures[0] if len(signatures)==1 else hashlib.sha256(json.dumps(['narrator-parts-v1',signatures]).encode()).hexdigest()

def chapter_heading_plan(first_segment,chapter,characters,meta):
    from narrator_profiles import VERSION
    if meta.get('narrator_profiles')!=VERSION or not chapter['title'].strip():return []
    first=segment_plan(first_segment,chapter,characters,meta) if first_segment else []
    if any(p.get('narrator_style')=='heading' for p in first):return []
    from book_heading import spoken
    return [dict(text=spoken(chapter['title']),avatar=voice_for({'speaker':''},chapter,characters,meta),narrator_style='heading')]

def run_ffmpeg(args,book_id):
    import imageio_ffmpeg
    p=subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-y',*args],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        while p.poll() is None:
            cancelled(book_id); time.sleep(.15)
        _,errors=p.communicate()
        if p.returncode: raise RuntimeError(errors.decode('utf-8',errors='replace')[-2000:])
    finally:
        if p.poll() is None: p.kill(); p.wait()

def stitch(paths,target,book_id,pause_ms=180,prefix_mutes=None,preserve=None):
    import soundfile as sf
    import numpy as np
    temporary=target.with_suffix('.partial.wav')
    with sf.SoundFile(temporary,'w',samplerate=24000,channels=1,format='RF64',subtype='PCM_16') as out:
        for index,path in enumerate(paths):
            cancelled(book_id)
            pause=pause_ms[index-1] if isinstance(pause_ms,list) and index else pause_ms
            if index and pause: out.write(np.zeros(int(24*pause),dtype='float32'))
            with sf.SoundFile(path) as source:
                if source.samplerate!=24000 or source.channels!=1: raise ValueError('Некорректный формат фрагмента')
                from book_audio import edge_blocks
                blocks=source.blocks(blocksize=65536,dtype='float32') if str(path) in (preserve or set()) else edge_blocks(source,(prefix_mutes or {}).get(str(Path(path)),0),lambda:cancelled(book_id))
                for block in blocks:
                    out.write(block)
    temporary.replace(target)


def assemble_chapter_segments(book_id,segments,plans,destination=None):
    """Rebuild voice joins from saved clips, including cache hits; no TTS calls."""
    from book_audio import chapter_sources,VERSION
    sources,mutes=chapter_sources(folder(book_id),segments,plans)
    destination=Path(destination) if destination else folder(book_id)/'audio'/'joined'
    destination.mkdir(parents=True,exist_ok=True)
    paths=[]
    from speech_joins import gap
    for segment,clips,plan in zip(segments,sources,plans):
        # The desktop player may still hold the previous preview open on
        # Windows. Publish a new content version instead of overwriting it.
        identity=[VERSION,[(str(p),p.stat().st_size,p.stat().st_mtime_ns,mutes.get(str(p),0)) for p in clips],plan]
        revision=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:12]
        target=destination/f'{segment["id"]:08d}-{revision}.wav'
        # Legacy fallback can already be the processed file. Do not apply
        # cumulative fades on each resume when its raw clips are unavailable.
        if not target.is_file():
            from audio_level import normalized_file
            leveled=[];level_mutes={};preserve=set()
            sound_paths={str(p) for p,part in zip(clips,plan) if part.get('sound_file')} 
            for clip in clips:
                cancelled(book_id)
                prepared=clip if str(clip) in sound_paths else normalized_file(clip);leveled.append(prepared)
                if str(clip) in sound_paths:preserve.add(str(prepared))
                level_mutes[str(prepared)]=mutes.get(str(clip),0)
            pauses=[gap(a,b) for a,b in zip(plan,plan[1:])] if len(plan)==len(clips) else 60
            stitch(leveled,target,book_id,pause_ms=pauses,prefix_mutes=level_mutes,preserve=preserve)
        paths.append(str(target))
    store.atomic_json(destination/'joins.json',dict(version=VERSION,prefix_mutes_ms={p:round(n/24,2) for p,n in mutes.items()}))
    return paths

def render(book_id,pipeline,progress,chapter_id=None,emit=lambda *a,**k:None):
    import book_state as state
    state.migrate(book_id)
    meta=metadata(book_id)
    if not meta.get('analysis_complete'):
        raise ValueError('Сначала завершите разметку всей книги. Озвучка доступна после 100%.')
    if getattr(pipeline,'supports_narrator_styles',False):
        from narrator_profiles import VERSION
        if meta.get('narrator_profiles')!=VERSION:
            meta['narrator_profiles']=VERSION;save_meta(book_id,meta)
    state.refresh_audio(book_id)
    ctl=state.Control(book_id,'render',emit)
    with connect(book_id) as db:
        chapters=db.execute('SELECT * FROM chapters '+('WHERE id=? ' if chapter_id else '')+'ORDER BY id', (chapter_id,) if chapter_id else ()).fetchall()
        if not chapters: raise ValueError('В книге нет глав.')
        from book_cast import voices as cast_voices
        characters=cast_voices(db)
        book_title=''
        for row in db.execute('SELECT parts FROM segments ORDER BY id'):
            titles=[p['text'].strip() for p in json.loads(row['parts'] or '[]') if p.get('kind')=='book_title']
            if titles:
                book_title=' '.join(titles);break
        meta['spoken_book_title']=book_title
        state.update(book_id,spoken_book_title=book_title)
        first_chapter=db.execute('SELECT min(chapter) FROM segments').fetchone()[0]
        voices={a['id']:a for a in store.avatars()}
        total=0
        for chapter in chapters:
            for segment in db.execute('SELECT * FROM segments WHERE chapter=? ORDER BY id',(chapter['id'],)):
                for part in segment_plan(segment,chapter,characters,meta):
                    if not part.get('sound_file') and part['avatar'] not in voices: raise ValueError(f'Выберите доступный голос автора и персонажей для главы «{chapter["title"]}».')
                total+=1
        done=0; rendered=[]
        for chapter in chapters:
            ctl.begin(chapter['id'])
            paths=[]
            intro=None
            first=db.execute('SELECT * FROM segments WHERE chapter=? ORDER BY id LIMIT 1',(chapter['id'],)).fetchone()
            heading=chapter_heading_plan(first,chapter,characters,meta)
            all_rows=db.execute('SELECT * FROM segments WHERE chapter=? ORDER BY id',(chapter['id'],)).fetchall()
            has_content=any(segment_plan(s,chapter,characters,meta) for s in all_rows)
            if not has_content:heading=[]
            if book_title and chapter['id']==first_chapter and getattr(pipeline,'supports_narrator_styles',False):
                heading=[dict(text=book_title,avatar=voice_for({'speaker':''},chapter,characters,meta),narrator_style='heading')]+[p for p in heading if p['text'].casefold()!=book_title.casefold()]
            if heading and getattr(pipeline,'supports_narrator_styles',False):
                item=heading[0] if len(heading)==1 else dict(heading[0],text='. '.join(p['text'].rstrip('. ') for p in heading)+'.');voice=voices[item['avatar']]
                signature=plan_signature(heading,voices,meta['seed'])
                target=folder(book_id)/'audio'/f'chapter-{chapter["id"]:04d}-heading.wav'
                target.parent.mkdir(parents=True,exist_ok=True)
                saved=target.with_suffix('.heading.json')
                if not target.is_file() or store.load_json(saved,{}).get('signature')!=signature:
                    progress(done/max(1,total),'Читаем название главы: '+chapter['title'])
                    pipeline.synthesize_book_clip(str(store.avatar_path(voice)),item['text'],voice['transcript'],meta['seed'],target,narrator_style='heading')
                    store.atomic_json(saved,dict(signature=signature,title=chapter['title'],avatar=item['avatar']))
                from audio_level import normalized_file
                intro=str(normalized_file(target))
            for segment in db.execute('SELECT * FROM segments WHERE chapter=? ORDER BY id',(chapter['id'],)).fetchall():
                cancelled(book_id)
                plan=segment_plan(segment,chapter,characters,meta)
                signature=plan_signature(plan,voices,meta['seed'])
                progress(done/total,f'Глава {chapter["id"]}: фрагмент {done+1} / {total}')
                if segment['signature']==signature and Path(segment['wav']).is_file():
                    wav=segment['wav']
                else:
                    cache=folder(book_id)/'audio'; cache.mkdir(exist_ok=True)
                    clips=[];audio_review=False
                    for part_index,part in enumerate(plan):
                        target=cache/(f'{segment["id"]:08d}.wav' if len(plan)==1 else f'{segment["id"]:08d}-part-{part_index:03d}.wav')
                        if part.get('sound_file'):
                            import shutil
                            shutil.copyfile(part['sound_file'],target);clips.append(str(target));continue
                        voice=voices[part['avatar']]
                        options={'narrator_style':part['narrator_style']} if part.get('narrator_style') and getattr(pipeline,'supports_narrator_styles',False) else {}
                        clips.append(pipeline.synthesize_book_clip(str(store.avatar_path(voice)),part['text'],voice['transcript'],meta['seed'],target,**options))
                        audio_review=audio_review or bool(store.load_json(target.with_suffix('.cleanup.json'),{}).get('needs_review'))
                    wav=str(cache/f'{segment["id"]:08d}.wav')
                    if len(plan)>1:stitch(clips,Path(wav),book_id,pause_ms=60)
                    if not plan:
                        import soundfile as sf
                        import numpy as np
                        sf.write(wav,np.zeros(240,dtype='float32'),24000)
                    # Pause previews must use the same level as the final book.
                    if plan:
                        wav=assemble_chapter_segments(book_id,[dict(id=segment['id'],wav=wav)],[plan])[0]
                    db.execute('UPDATE segments SET wav=?,signature=?,audio_review=? WHERE id=?',(wav,signature,int(audio_review),segment['id'])); db.commit()
                if plan:paths.append(wav)
                done+=1
                progress(done/total,f'Озвучено {done}/{total} фрагментов · {done*100/total:.1f}%')
                ctl.boundary(chapter['id'])
            cancelled(book_id)
            # Cached segment WAVs can contain several speaker changes. Always
            # revisit their retained individual clips before chapter assembly.
            saved=db.execute('SELECT * FROM segments WHERE chapter=? ORDER BY id',(chapter['id'],)).fetchall()
            saved=[s for s in saved if segment_plan(s,chapter,characters,meta)]
            plans=[segment_plan(s,chapter,characters,meta) for s in saved]
            progress(done/total,'Выравниваем громкость голосов и собираем главу…')
            paths=assemble_chapter_segments(book_id,saved,plans)
            for segment,path in zip(saved,paths):
                db.execute('UPDATE segments SET wav=? WHERE id=?',(path,segment['id']))
            db.commit()
            target=folder(book_id)/f'chapter-{chapter["id"]:04d}.wav'
            from speech_joins import gap
            pauses=[gap(a[-1],b[0],meta['pause_ms']) if a and b else meta['pause_ms'] for a,b in zip(plans,plans[1:])]
            if intro:paths=[intro,*paths];pauses=[max(350,meta['pause_ms']),*pauses]
            if not paths:
                db.execute('UPDATE chapters SET output=? WHERE id=?',('',chapter['id']));db.commit()
                ctl.boundary(chapter['id'],chapter_done=True)
                continue
            stitch(paths,target,book_id,pauses)
            mp3=target.with_suffix('.mp3'); temp=mp3.with_suffix('.partial.mp3')
            run_ffmpeg(['-i',str(target),'-codec:a','libmp3lame','-b:a','192k',str(temp)],book_id); temp.replace(mp3)
            db.execute('UPDATE chapters SET output=? WHERE id=?',(str(mp3),chapter['id'])); db.commit()
            rendered.append(target)
            ctl.boundary(chapter['id'],chapter_done=True)
        if chapter_id:
            result=str(rendered[0].with_suffix('.mp3')) if rendered else ''
        else:
            if not rendered:raise ValueError('После исключения служебных сведений в книге не осталось текста для озвучки.')
            progress(.99,'Собираем книгу в один MP3…')
            listing=folder(book_id)/'concat.txt'
            listing.write_text('\n'.join("file '"+p.name+"'" for p in rendered),encoding='utf-8')
            target=folder(book_id)/'audiobook.mp3'; temp=folder(book_id)/'audiobook.partial.mp3'
            run_ffmpeg(['-f','concat','-safe','1','-i',str(listing),'-codec:a','libmp3lame','-b:a','192k',str(temp)],book_id); temp.replace(target)
            result=str(target)
    with connect(book_id) as db:review_count=db.execute("SELECT count(*) FROM segments WHERE audio_review=1 AND wav!='' AND signature!=''").fetchone()[0]
    state.update(book_id,output=result,render_complete=not bool(chapter_id),audio_review_count=review_count)
    ctl.finish()
    return result
