"""Model-free supervisor. TTS and role analysis never coexist as processes."""
import json,os,subprocess,sys,time,traceback
from pathlib import Path
from desktop_job import WorkerJob,join_job
ROOT=Path(__file__).resolve().parent
OUTPUT=sys.stdout;sys.stdout=sys.stderr

def emit(kind,**fields):
    OUTPUT.write(json.dumps(dict(type=kind,**fields),ensure_ascii=False)+'\n');OUTPUT.flush()
def forward(event):
    kind=event.pop('type');emit(kind,**event)
class Child:
    def __init__(self,script):
        self.job=WorkerJob(); env=os.environ.copy();env['VOX_JOB_NAME']=self.job.name
        self.pid=None
        try:
            self.process=subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),'-X','utf8','-u',str(ROOT/script)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=sys.stderr,text=True,encoding='utf-8',env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except BaseException:self.job.close();raise
    def send(self,command):self.process.stdin.write(json.dumps(command,ensure_ascii=False)+'\n');self.process.stdin.flush()
    def events(self):
        for line in self.process.stdout:
            try:event=json.loads(line)
            except ValueError:sys.stderr.write(line);continue
            if event['type']=='hello':self.pid=event['pid'];continue
            yield event
    def close(self):
        self.job.close()
        if self.process.poll() is None:
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        self.process.stdin.close();self.process.stdout.close()
def start_tts(restoring=False):
    child=Child('tts_worker.py')
    try:
        for event in child.events():
            if event['type']=='ready':
                emit('model_state',active='tts',pid=child.pid)
                if not restoring:emit('ready')
                return child
            if event['type']=='fatal':raise RuntimeError(event['message'])
            if restoring and event['type']=='progress':event['phase']='loading'
            forward(event)
        raise RuntimeError('Процесс озвучки завершился при загрузке.')
    except BaseException:child.close();raise

def main():
    join_job(os.environ.get('VOX_JOB_NAME'));emit('hello',pid=os.getpid())
    child=None
    try:
        emit('model_state',active='none',pid=None)
        emit('ready')
        for line in sys.stdin:
            command=json.loads(line)
            if command['action']=='shutdown':break
            if command['action']=='unload':
                if child:child.close();child=None
                emit('model_state',active='none',pid=None)
                emit('models_unloaded')
                continue
            if command['action'] in ('book_import','book_analyze','book_append'):
                emit('progress',value=.005,message='Освобождаем память: завершаем модели озвучки и распознавания…')
                if child:child.close();child=None
                emit('model_state',active='none',pid=None)
                result=None
                roles=Child('roles_worker.py')
                try:
                    roles.send(command)
                    for event in roles.events():
                        if event['type'] in ('book_done','book_paused','book_stopped','error','fatal'):result=event
                        else:forward(event)
                    if result is None:result=dict(type='error',message='Процесс разметки неожиданно завершился. Готовые блоки сохранены.',action=command['action'])
                finally:roles.close()
                emit('model_state',active='none',pid=None)
                forward(result)
            else:
                if command['action']=='generate':
                    from spoken_numbers import NUMBER
                    if NUMBER.search(command['text']):
                        if child:child.close();child=None
                        emit('model_state',active='none',pid=None)
                        preparation=Child('text_worker.py');prepared=None;failed=None
                        try:
                            preparation.send(command)
                            for event in preparation.events():
                                if event['type']=='text_prepared':prepared=event['spoken_text']
                                elif event['type']=='error':failed=event
                                else:forward(event)
                        finally:preparation.close()
                        if prepared is None:
                            forward(failed or dict(type='error',message='Не удалось подготовить числа для озвучки.',action='generate'));continue
                        command['spoken_text']=prepared
                if command['action']=='book_render':
                    import book_engine as books
                    if not books.metadata(command['book_id']).get('analysis_complete'):
                        emit('error',message='Сначала завершите разметку книги до 100%.',action=command['action'])
                        continue
                if child is None:child=start_tts(restoring=True)
                child.send(command)
                for event in child.events():
                    terminal=event['type'] in ('generated','avatar_saved','book_done','book_paused','book_stopped','error','fatal')
                    if event['type']=='book_stopped':
                        child.close();child=None
                        emit('model_state',active='none',pid=None)
                    forward(event)
                    if terminal:break
                else:raise RuntimeError('Голосовой процесс неожиданно завершился.')
    finally:
        if child:child.close()
if __name__=='__main__':
    try:main()
    except Exception as exc:traceback.print_exc(file=sys.stderr);emit('fatal',message=str(exc))
