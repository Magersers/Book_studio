"""Export finished chapters without TTS or another lossy encode."""
import re,shutil,subprocess,tempfile,zipfile
from pathlib import Path
import book_engine as books

def chapters(book_id,chapter_id=None):
    result=[];missing=[]
    with books.connect(book_id) as db:
        from book_cast import voices
        cast=voices(db);meta=books.metadata(book_id)
        for chapter in db.execute('SELECT * FROM chapters '+('WHERE id=? ' if chapter_id is not None else '')+'ORDER BY id',(chapter_id,) if chapter_id is not None else ()):
            rows=db.execute('SELECT * FROM segments WHERE chapter=? ORDER BY id',(chapter['id'],)).fetchall()
            if not any(books.segment_plan(row,chapter,cast,meta) for row in rows):continue
            path=Path(chapter['output']) if chapter['output'] else None
            if path is None or not path.is_file():missing.append(str(chapter['id']))
            else:result.append((chapter['id'],chapter['title'],path))
    if missing:raise ValueError('Сначала завершите озвучку глав: '+', '.join(missing)+'.')
    if not result:raise ValueError('В книге пока нет готовых глав для экспорта.')
    return result

def export(book_id,target,mode,chapter_id=None):
    if mode not in ('full','chapters','chapter'):raise ValueError('Неизвестный формат экспорта.')
    if mode=='chapter' and chapter_id is None:raise ValueError('Выберите главу для скачивания.')
    rows=chapters(book_id,chapter_id) if mode=='chapter' else chapters(book_id);target=Path(target)
    if mode=='chapter':
        with books.connect(book_id) as db:
            if any(row['output'] and target.resolve()==Path(row['output']).resolve() for row in db.execute('SELECT output FROM chapters')):
                raise ValueError('Выберите отдельный файл для экспорта, чтобы сохранить исходные главы.')
    if any(target.resolve()==p.resolve() for _,_,p in rows):raise ValueError('Выберите отдельный файл для экспорта, чтобы сохранить исходные главы.')
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='vox-export-',dir=target.parent) as tmp:
        tmp=Path(tmp);output=tmp/('book.zip' if mode=='chapters' else 'book.mp3')
        if mode=='chapter':shutil.copyfile(rows[0][2],output)
        elif mode=='chapters':
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
                for index,(_,title,path) in enumerate(rows,1):
                    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]',' ',title).strip(' .')[:120] or 'Глава'
                    archive.write(path,f'{index:03d} — {name}.mp3')
        else:
            # Local ASCII names avoid concat quoting problems in user paths.
            for i,(_,_,path) in enumerate(rows):shutil.copyfile(path,tmp/f'{i:04d}.mp3')
            listing=tmp/'chapters.txt';listing.write_text('\n'.join(f"file '{i:04d}.mp3'" for i in range(len(rows))),encoding='utf-8')
            import imageio_ffmpeg
            command=[imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-y','-f','concat','-safe','1','-i',str(listing),'-c:a','copy',str(output)]
            result=subprocess.run(command,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess,'CREATE_NO_WINDOW') else 0)
            if result.returncode:raise ValueError('Не удалось объединить готовые главы: '+result.stderr.decode('utf-8',errors='replace')[-800:])
        output.replace(target)
    return target
