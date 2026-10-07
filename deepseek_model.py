"""DeepSeek streaming JSON with bounded, cancellable transient-error recovery."""
import json,queue,re,threading,time
import requests
import analysis_settings as preferences
from analysis_errors import OutputLimitError

CONTEXT=131072  # Bounded working window, independent of the provider's larger maximum.

def status_error(status):
    messages={401:'API-ключ не принят. Проверьте ключ в настройках разметки.',
              402:'На балансе API недостаточно средств.',403:'API запретил доступ к этой модели.',
              404:'Адрес API или выбранная модель не найдены.',429:'API ограничил частоту запросов. Продолжите позже.',
              400:'API отклонил запрос. Проверьте адрес и совместимость выбранной модели.',
              422:'API не поддерживает параметры запроса выбранной модели.'}
    return messages.get(status,f'API вернул HTTP {status}. Готовые блоки сохранены; автоматического повтора нет.')

def probe(base_url,key,model):
    """Read-only authentication/model discovery, never a paid generation."""
    url=preferences.normalize_url(base_url);key=preferences.validate_key(key);model=preferences.validate_model(model)
    try:
        with requests.get(url+'/models',headers={'Authorization':'Bearer '+key},timeout=(10,20),allow_redirects=False) as response:
            if response.status_code!=200:raise RuntimeError(status_error(response.status_code))
            data=response.json()
    except requests.RequestException:raise RuntimeError('Не удалось подключиться к API. Проверьте адрес и интернет.') from None
    except ValueError:raise RuntimeError('Сервер не вернул список моделей в формате JSON.') from None
    if not isinstance(data,dict) or not isinstance(data.get('data'),list):raise RuntimeError('Сервер не вернул список моделей.')
    if model not in [item.get('id') for item in data['data'] if isinstance(item,dict)]:
        raise RuntimeError('Ключ принят, но выбранная модель отсутствует в списке доступных. Проверьте её название.')
    return 'Подключение проверено. Модель доступна; генерация не запускалась.'

def list_models(base_url,key):
    url=preferences.normalize_url(base_url);key=preferences.validate_key(key)
    try:
        with requests.get(url+'/models',headers={'Authorization':'Bearer '+key},timeout=(10,30),allow_redirects=False) as response:
            if response.status_code!=200:raise RuntimeError(status_error(response.status_code))
            data=response.json()
        if not isinstance(data,dict) or not isinstance(data.get('data'),list):raise ValueError('Сервер не вернул список моделей.')
        result=sorted({r['id'] for r in data['data'] if isinstance(r,dict) and isinstance(r.get('id'),str)})
        if not result:raise ValueError('Сервер не вернул список моделей. Введите модель вручную.')
        return result
    except requests.RequestException:raise RuntimeError('Не удалось получить модели. Проверьте адрес API и соединение.') from None

def example(schema):
    if 'enum' in schema:return schema['enum'][0]
    kind=schema.get('type')
    if kind=='object':return {key:example(value) for key,value in schema['properties'].items()}
    if kind=='array':return [example(schema['items'])] if schema.get('minItems',0) else []
    if kind=='integer':return schema.get('minimum',0)
    if kind=='boolean':return False
    return ''

class RetryableAPIError(RuntimeError):pass

class DeepSeekModel:
    retry_delays=(5,15,30)
    semantic_chapters=True
    compact_roles=True
    def __init__(self,check,progress):
        self.check=check;self.progress=progress;self.usage_callback=lambda usage:None
        self.options=preferences.settings();self.cancel=threading.Event();self.session=None
    def __enter__(self):
        self.url=preferences.normalize_url(self.options['base_url']);self.model=preferences.validate_model(self.options['model'])
        self.key=preferences.api_key(self.url);self.session=requests.Session()
        self.progress(.02,'Разметка через '+preferences.PROVIDERS[self.options['provider']]['label']+' · '+self.model)
        return self
    def close(self):
        self.cancel.set()
        if self.session:self.session.close()
        self.key=''
    def __exit__(self,*args):self.close()
    def tokens(self,text):
        self.check()
        # Conservative byte bound; no separate paid tokenization call. Reserve schema/framing.
        return len(text.encode('utf-8'))+8192
    def complete(self,prompt,schema,budget,callback):
        for attempt in range(len(self.retry_delays)+1):
            self.check()
            try:return self._complete_once(prompt,schema,budget,callback)
            except RetryableAPIError as exc:
                if attempt==len(self.retry_delays):
                    raise RuntimeError('API не удалось восстановить после четырёх попыток. Готовые блоки сохранены; продолжение начнётся с этого блока. '+str(exc)) from exc
                self.wait_retry(self.retry_delays[attempt],attempt+1)
    def wait_retry(self,seconds,attempt):
        deadline=time.monotonic()+seconds;shown=None
        while True:
            self.check()
            if self.cancel.is_set():raise RuntimeError('Запрос отменён.')
            left=max(0,int(deadline-time.monotonic()+.999))
            if left!=shown:
                shown=left
                getattr(self,'retry_progress',lambda message:self.progress(.02,message))(f'Ожидание API: {left} с · повтор блока {attempt}/3. Готовые блоки сохранены.')
            if not left:return
            self.cancel.wait(min(.15,max(0,deadline-time.monotonic())))
    def _complete_once(self,prompt,schema,budget,callback):
        from roles_model import chat_messages
        self.check();messages=chat_messages(prompt)
        messages[0]['content']+='\nВерни только компактный JSON, без форматирования и пояснений. JSON Schema: '+json.dumps(schema,ensure_ascii=False,separators=(',',':'))+'\nПример формы JSON (заполни по тексту, не копируй пустые значения): '+json.dumps(example(schema),ensure_ascii=False,separators=(',',':'))
        payload=dict(model=self.model,messages=messages,max_tokens=budget,temperature=0,
                     response_format={'type':'json_object'},
                     stream=True,stream_options={'include_usage':True})
        if self.options['provider']=='deepseek':payload['thinking']={'type':'disabled'}
        events=queue.Queue();request_done=threading.Event();responses=[]
        def reader():
            try:
                with self.session.post(self.url+'/chat/completions',headers={'Authorization':'Bearer '+self.key},
                        json=payload,stream=True,timeout=(10,45),allow_redirects=False) as response:
                    responses.append(response)
                    if response.status_code!=200:
                        error=RetryableAPIError if response.status_code in (408,429,500,502,503,504) else RuntimeError
                        raise error(status_error(response.status_code))
                    for line in response.iter_lines():
                        if self.cancel.is_set() or request_done.is_set():break
                        if line.startswith(b'data: '):
                            if line[6:]==b'[DONE]':break
                            events.put(json.loads(line[6:]))
                events.put(None)
            except requests.RequestException:events.put(RetryableAPIError('Соединение с API оборвалось.'))
            except (ValueError,TypeError):events.put(RetryableAPIError('API вернул некорректный поток JSON.'))
            except RuntimeError as exc:events.put(exc)
        threading.Thread(target=reader,daemon=True).start()
        output=[];count=0;finish=None;began=time.monotonic();usage=None
        try:
            while True:
                self.check()
                if time.monotonic()-began>300:raise RetryableAPIError('Превышено время ожидания API.')
                try:event=events.get(timeout=.15)
                except queue.Empty:continue
                if isinstance(event,Exception):raise event
                if event is None:break
                if not isinstance(event,dict) or event.get('error'):raise RetryableAPIError('API прервал генерацию.')
                if isinstance(event.get('usage'),dict):
                    usage={name:max(0,int(event['usage'].get(name,0) or 0)) for name in ('prompt_tokens','completion_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens')}
                for choice in event.get('choices',[]):
                    delta=choice.get('delta',{})
                    if delta.get('content'):
                        output.append(delta['content']);count+=1
                        if count%16==0:callback(count,len(re.findall(r'"id"\s*:\s*\d+',''.join(output))))
                    if choice.get('finish_reason'):finish=choice['finish_reason']
            if finish=='length':raise OutputLimitError('Ответ API не поместился в лимит длины.')
            if finish!='stop':raise RetryableAPIError('API не завершил ответ.')
            raw=''.join(output)
            from model_json import parse
            try:
                parsed=parse(raw)
                if not isinstance(parsed,dict) or any(name not in parsed for name in schema.get('required',[])):raise ValueError('Неполная структура')
                return parsed
            except ValueError:
                # Keep the response, never request headers or credentials, so a
                # malformed reply can be diagnosed without paying for a retry.
                from pathlib import Path
                import uuid
                folder=Path(__file__).resolve().parent/'logs';folder.mkdir(exist_ok=True)
                (folder/('deepseek-invalid-'+uuid.uuid4().hex+'.txt')).write_text(raw,encoding='utf-8')
                raise RetryableAPIError('API вернул пустой или некорректный JSON. Диагностика сохранена в logs/deepseek-invalid-*.txt.') from None
        finally:
            request_done.set()
            for response in responses:response.close()
            if usage is not None:self.usage_callback(dict(usage,model=self.model))
