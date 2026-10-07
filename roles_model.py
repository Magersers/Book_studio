"""Local llama.cpp process, bounded context and interruptible streamed JSON."""
import json,os,queue,socket,subprocess,threading,time,secrets,re
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parent
from runtime_config import config
MODEL_ID=os.environ.get('VOX_ROLES_MODEL',config().get('roles','qwen4'))
GEMMA=MODEL_ID in ('gemma12','gemma12-thinking')
THINKING=MODEL_ID in ('qwen9-thinking','gemma12-thinking')
NATIVE_CHAT=GEMMA or THINKING
UPGRADED=MODEL_ID in ('qwen9','qwen9-thinking','gemma12','gemma12-thinking')
CONTEXT=12288 if GEMMA else (24576 if UPGRADED else 32768)
MODEL=ROOT/('models/Gemma-4-12B-Roles/gemma-4-12b-it-Q3_K_M.gguf' if GEMMA else ('models/Qwen3.5-9B-Roles/Qwen3.5-9B-Q4_K_M.gguf' if UPGRADED else 'models/Qwen3-4B-Roles/Qwen3-4B-Instruct-2507-Q4_K_M.gguf'))
LABEL=('Gemma-4-12B-Q3_K_M'+('-Thinking' if THINKING else '')) if GEMMA else ('Qwen3.5-9B-Thinking' if THINKING else ('Qwen3.5-9B' if UPGRADED else 'Qwen3-4B'))
REASONING_BUDGET=(1024 if MODEL_ID=='qwen9-thinking' else 512) if THINKING else 0

def chat_messages(prompt):
    # Prompts are generated internally. Parse only the outer framing, never tags inside book text.
    prefix='<|im_start|>system\n';separator='<|im_end|>\n<|im_start|>user\n';suffix='<|im_end|>\n<|im_start|>assistant\n'
    if not prompt.startswith(prefix) or not prompt.endswith(suffix) or separator not in prompt:
        raise ValueError('Некорректный шаблон запроса разметки')
    system,user=prompt[len(prefix):-len(suffix)].split(separator,1)
    return [dict(role='system',content=system),dict(role='user',content=user)]

def needs_reasoning(prompt):
    if not THINKING:return False
    try:return isinstance(json.loads(chat_messages(prompt)[1]['content']).get('target_fragments'),list)
    except (ValueError,AttributeError):return False
class RoleModel:
    semantic_chapters=UPGRADED
    compact_roles=True
    def __init__(self,check,progress):
        self.check=check; self.progress=progress; self.process=None; self.log=None;self.template_cache={}
    def __enter__(self):
        exe=next((ROOT/'vendor/llama-cpp').rglob('llama-server.exe'),None)
        if not exe or not MODEL.exists():
            installer='download_gemma_roles.py' if GEMMA else ('download_upgrade.py' if UPGRADED else 'download_roles.py')
            raise RuntimeError(f'Не установлена модель ролей {LABEL}. Запустите {installer}.')
        with socket.socket() as sock:sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        self.url=f'http://127.0.0.1:{port}'
        token=secrets.token_urlsafe(32)
        self.headers={'Authorization':'Bearer '+token}
        (ROOT/'logs').mkdir(exist_ok=True); self.log=(ROOT/'logs/roles-model.log').open('ab',buffering=0)
        self.process=subprocess.Popen([str(exe),'-m',str(MODEL),'-c',str(CONTEXT),'--device','CUDA0','-ngl','all','--fit','off','-np','1','-fa','on','-ctk','q8_0','-ctv','q8_0','-b','256' if GEMMA else '512','-ub','64' if GEMMA else '128','-t','6','--cache-ram','8192','--ctx-checkpoints','16','--checkpoint-min-step','1024','--reasoning-budget',str(REASONING_BUDGET),'--host','127.0.0.1','--port',str(port),'--api-key',token],stdout=self.log,stderr=self.log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.progress(.02,f'Загружаем {LABEL} для анализа книги…')
        start=time.monotonic()
        try:
            while True:
                self.check()
                if self.process.poll() is not None:raise RuntimeError(f'Не удалось загрузить {LABEL}. Подробности: logs/roles-model.log')
                try:
                    if requests.get(self.url+'/health',headers=self.headers,timeout=1).status_code==200:break
                except requests.RequestException:pass
                if time.monotonic()-start>120:raise RuntimeError('Превышено время загрузки модели ролей.')
                time.sleep(.2)
            return self
        except BaseException:self.close();raise
    def close(self):
        if self.process:
            if self.process.poll() is None:self.process.terminate()
            try:self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            self.process=None
        if self.log:self.log.close();self.log=None
    def __exit__(self,*args):self.close()
    def prepare_prompt(self,prompt):
        if not NATIVE_CHAT or not prompt.startswith('<|im_start|>system\n'):return prompt
        if prompt not in self.template_cache:
            self.check()
            response=requests.post(self.url+'/apply-template',headers=self.headers,json={'messages':chat_messages(prompt),'chat_template_kwargs':{'enable_thinking':needs_reasoning(prompt)}},timeout=30)
            response.raise_for_status()
            if len(self.template_cache)>=8:self.template_cache.clear()
            self.template_cache[prompt]=response.json()['prompt']
        return self.template_cache[prompt]
    def tokens(self,text):
        text=self.prepare_prompt(text)
        self.check(); r=requests.post(self.url+'/tokenize',headers=self.headers,json={'content':text,'add_special':True},timeout=30);r.raise_for_status();return len(r.json()['tokens'])
    def complete(self,prompt,schema,budget,callback):
        chat_prompt=prompt
        prompt=self.prepare_prompt(prompt)
        if UPGRADED and not NATIVE_CHAT and prompt.endswith('<|im_start|>assistant\n'):
            prompt+='<think>\n\n</think>\n\n'
        messages=queue.Queue()
        endpoint='/completion'
        payload={'prompt':prompt,'n_predict':budget,'temperature':0,'seed':42,'json_schema':schema,'stream':True,'cache_prompt':True}
        if NATIVE_CHAT:
            endpoint='/v1/chat/completions'
            payload={'messages':chat_messages(chat_prompt),'max_tokens':budget,'temperature':0,'seed':42,'stream':True,'cache_prompt':True,
                     'chat_template_kwargs':{'enable_thinking':needs_reasoning(chat_prompt)},'reasoning_budget':REASONING_BUDGET,
                     'response_format':{'type':'json_schema','json_schema':{'name':'book_markup','strict':True,'schema':schema}}}
        def reader():
            try:
                with requests.post(self.url+endpoint,headers=self.headers,json=payload,stream=True,timeout=(10,180)) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line.startswith(b'data: ') and line[6:]!=b'[DONE]':messages.put(json.loads(line[6:]))
                messages.put(None)
            except Exception as exc:messages.put(exc)
        threading.Thread(target=reader,daemon=True).start()
        output=[]; count=0; stopped=False
        while True:
            self.check()
            try:event=messages.get(timeout=.15)
            except queue.Empty:continue
            if isinstance(event,Exception):raise event
            if event is None:break
            if event.get('error'):raise RuntimeError(str(event['error']))
            if NATIVE_CHAT:
                choices=event.get('choices',[])
                if not choices:continue
                choice=choices[0];delta=choice.get('delta',{})
                if delta.get('reasoning_content'):
                    count+=1
                    if count%24==0:callback(count,0)
                event={'content':delta.get('content',''),'stop':choice.get('finish_reason') is not None,'stopped_limit':choice.get('finish_reason')=='length'}
            if event.get('content'):
                output.append(event['content']);count+=1
                if count%24==0:callback(count,len(re.findall(r'"id"\s*:\s*\d+', ''.join(output))))
            if event.get('stop'):
                if event.get('stop_type')=='limit' or event.get('stopped_limit'):raise ValueError('Ответ модели не поместился в лимит. Повторите разметку меньшего раздела.')
                stopped=True
        if not stopped:raise RuntimeError('Ответ модели оборвался.')
        return json.loads(''.join(output))

# Each analysis worker imports this module afresh, so a UI provider change applies
# to the next job without restarting the application or loading local weights.
LocalRoleModel=RoleModel
CACHE_ID=LABEL
import analysis_settings as _api_preferences
_provider=_api_preferences.settings()
if _api_preferences.is_remote(_provider['provider']) and not os.environ.get('VOX_ROLES_MODEL'):
    import hashlib
    from deepseek_model import DeepSeekModel,CONTEXT
    RoleModel=DeepSeekModel
    LABEL=_api_preferences.label()
    CACHE_ID='deepseek-'+_provider['model']+'-'+hashlib.sha256(_provider['base_url'].encode()).hexdigest()[:12]+'-direct-v1'
