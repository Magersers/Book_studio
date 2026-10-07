"""One-shot analysis process: no torch, TTS, Whisper or Natasha imports."""
import json,os,sys,traceback
from desktop_job import join_job
OUTPUT=sys.stdout;sys.stdout=sys.stderr
def emit(kind,**fields):OUTPUT.write(json.dumps(dict(type=kind,**fields),ensure_ascii=False)+'\n');OUTPUT.flush()
def progress(value,message):emit('progress',value=value,message=message)
def main():
    join_job(os.environ.get('VOX_JOB_NAME'));emit('hello',pid=os.getpid())
    command=json.loads(sys.stdin.readline());book_id=command['book_id']
    import book_engine as books
    from roles_analysis import analyze
    import book_state as state
    try:
        if command['action']=='book_import':
            books.import_book(command['path'],book_id,progress)
            state.export_all(book_id)
        if command['action']=='book_append':
            from book_append import append
            append(book_id,command['path'],progress)
        emit('model_state',active='roles',pid=os.getpid())
        analyze(book_id,progress,emit=emit)
        from roles_model import LABEL
        count=books.metadata(book_id).get('role_review_count',0)
        message=f'Разметка {LABEL} готова. Ручные назначения сохранены.'
        if count:message+=f' Проверьте {count} фрагментов: причины указаны во вкладке «Текст и разметка».'
        emit('book_done',book_id=book_id,message=message)
    except books.Paused:emit('book_paused',book_id=book_id,message='Разметка остановлена. Проверенные блоки сохранены; «Разметить роли» продолжит анализ.')
    except state.Stopped as exc:emit('book_stopped',book_id=book_id,message=str(exc))
    except Exception as exc:
        traceback.print_exc(file=sys.stderr);state.failed(book_id,str(exc))
        emit('error',book_id=book_id,action=command['action'],message=str(exc))
if __name__=='__main__':
    try:main()
    except Exception as exc:traceback.print_exc(file=sys.stderr);emit('error',message=str(exc))
