"""Short-lived text preparation, before loading the speech model."""
import json,os,sys,traceback
from desktop_job import join_job
from roles_model import RoleModel
from spoken_numbers import prepare_text
def emit(kind,**fields):print(json.dumps(dict(type=kind,**fields),ensure_ascii=False),flush=True)
if __name__=='__main__':
    join_job(os.environ.get('VOX_JOB_NAME'));emit('hello',pid=os.getpid())
    try:
        command=json.loads(sys.stdin.readline())
        with RoleModel(lambda:None,lambda v,m:emit('progress',value=v,message=m)) as model:
            text=prepare_text(command['text'],model)
        emit('text_prepared',spoken_text=text)
    except Exception as exc:traceback.print_exc(file=sys.stderr);emit('error',message=str(exc),action='generate')
