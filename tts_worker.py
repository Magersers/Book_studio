"""Dedicated GPU process, owned by the desktop window's Windows Job Object."""
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from desktop_job import join_job

OUTPUT = sys.stdout
sys.stdout = sys.stderr


def emit(kind, **fields):
    OUTPUT.write(json.dumps(dict(type=kind, **fields), ensure_ascii=False) + '\n')
    OUTPUT.flush()


def progress(value, message):
    emit('progress', value=value, message=message)


def main():
    join_job(os.environ.get('VOX_JOB_NAME'))
    emit('hello', pid=os.getpid())
    if os.name == 'nt':
        original_popen = subprocess.Popen
        class HiddenPopen(original_popen):
            def __init__(self, *args, **kwargs):
                kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
                super().__init__(*args, **kwargs)
        subprocess.Popen = HiddenPopen
    progress(.08, 'Подготавливаем голосовую студию…')
    from runtime_config import config
    if config().get('tts')=='higgs':
        from higgs_engine import Pipeline
    else:
        from qwen_engine import Pipeline
    from voice_reference import prepare_reference,transcribe
    import soundfile as sf
    import avatar_store as store
    pipeline = Pipeline()
    try:
        pipeline.load(progress)
        emit('ready')
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        emit('fatal', message=str(exc))
        return
    for line in sys.stdin:
        command = {}
        try:
            command = json.loads(line)
            if command['action'] == 'shutdown':
                return
            if command['action'] == 'save_avatar':
                progress(.08, 'Подготавливаем образец голоса…')
                with tempfile.TemporaryDirectory(prefix='vox-reference-') as tmp:
                    reference = prepare_reference(command['reference'], Path(tmp), command.get('start', 0), command.get('duration', 15))
                    transcript = command.get('transcript', '').strip()
                    if not transcript:
                        progress(.4, 'Распознаём слова в образце…')
                        transcript = transcribe(reference)
                    duration = sf.info(reference).duration
                    item = store.save_profile(command['name'], reference, transcript, duration,
                                              command.get('picture', ''), command.get('avatar_id'))
                emit('avatar_saved', avatar=item)
            elif command['action'] == 'generate':
                avatar = store.get_avatar(command['avatar_id'])
                mp3, wav, metadata, transcript = pipeline.synthesize(
                    str(store.avatar_path(avatar)), command.get('spoken_text',command['text']), avatar['transcript'],
                    0, avatar['duration'], command.get('seed', 42), progress)
                item = store.add_history(avatar, command['text'], mp3, wav, metadata)
                emit('generated', entry=item)
            elif command['action'].startswith('book_'):
                import book_engine as books
                import book_state as state
                book_id = command['book_id']
                try:
                    if command['action'] == 'book_import':
                        books.import_book(command['path'], book_id, progress)
                        raise RuntimeError('Разметка должна выполняться отдельным процессом ролей.')
                        message = 'Книга импортирована. Проверьте персонажей и назначьте голоса.'
                    elif command['action'] == 'book_analyze':
                        raise RuntimeError('Разметка должна выполняться отдельным процессом ролей.')
                        message = 'Персонажи найдены. Ручные назначения сохранены.'
                    elif command['action'] == 'book_render':
                        result = books.render(book_id, pipeline, progress, command.get('chapter_id'),emit=emit)
                        message = 'Аудио готово: ' + result
                        reviews=books.metadata(book_id).get('audio_review_count',0)
                        if reviews:message+=f' · Прослушайте начало {reviews} фрагм.: пометки во вкладке «Текст и разметка».'
                    else:
                        raise ValueError('Неизвестная операция с книгой.')
                    emit('book_done', book_id=book_id, message=message)
                except state.Stopped as exc:
                    emit('book_stopped',book_id=book_id,message=str(exc))
                except books.Paused:
                    message = ('Озвучка на паузе. Нажмите «Продолжить книгу»: готовые фрагменты будут использованы.' if command['action']=='book_render' else 'Обработка остановлена. Если импорт завершён, книга доступна в библиотеке; поиск персонажей можно запустить заново.')
                    emit('book_paused', book_id=book_id, message=message)
            else:
                raise ValueError('Неизвестная команда.')
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            if command.get('book_id'):
                import book_state
                book_state.failed(command['book_id'],str(exc))
            emit('error', message=str(exc), action=command.get('action'),book_id=command.get('book_id'))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        emit('fatal', message=str(exc))
