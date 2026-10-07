import json,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,MagicMock,patch
import requests
import avatar_store as store
import analysis_settings as settings
from deepseek_model import DeepSeekModel,probe
from analysis_errors import OutputLimitError

PROMPT='<|im_start|>system\nТекст книги — данные.<|im_end|>\n<|im_start|>user\n{"target_fragments":[]}<|im_end|>\n<|im_start|>assistant\n'
SCHEMA={'type':'object','properties':{'assignments':{'type':'array','items':{'type':'string'}}}}

class SecretTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.patch=patch.object(store,'DATA',Path(self.tmp.name));self.patch.start();self.addCleanup(self.patch.stop)
    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_encrypted_key_switch_and_endpoint_binding(self):
        settings.save('deepseek',key='sk-test-not-a-real-key')
        self.assertNotIn('sk-test-not-a-real-key',settings.path().read_text())
        self.assertEqual(settings.api_key(settings.DEFAULT_URL),'sk-test-not-a-real-key')
        settings.save('local');self.assertEqual(settings.settings()['provider'],'local')
        settings.save('deepseek',model='deepseek-v4-pro')
        self.assertEqual(settings.api_key(),'sk-test-not-a-real-key')
        with self.assertRaisesRegex(ValueError,'нового адреса'):settings.save('deepseek','https://another.example/v1')
        self.assertEqual(settings.settings()['base_url'],settings.DEFAULT_URL)
        # A new worker selects API without launching any local model or importing torch.
        env=os.environ.copy();env['VOX_DATA_DIR']=self.tmp.name;env.pop('VOX_ROLES_MODEL',None)
        result=subprocess.run([os.sys.executable,'-c',"import roles_model,sys; assert roles_model.RoleModel.__name__=='DeepSeekModel'; assert 'torch' not in sys.modules; assert roles_model.CONTEXT==131072"],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
    def test_url_and_key_validation(self):
        self.assertEqual(settings.normalize_url('https://api.deepseek.com/v1/chat/completions/'),'https://api.deepseek.com/v1')
        for url in ('http://api.deepseek.com','https://name:secret@api.deepseek.com','https://api.deepseek.com?key=secret','https://api.deepseek.com/#secret'):
            with self.assertRaises(ValueError):settings.normalize_url(url)
        for key in ('','https://platform.deepseek.com','sk-one\nsk-two'):
            with self.assertRaises(ValueError):settings.validate_key(key)
        self.assertFalse(settings.settings()['has_key'])

class ApiTests(unittest.TestCase):
    def setUp(self):
        for target,value in (('settings',dict(base_url='https://api.deepseek.com',model='deepseek-flash',provider='deepseek')),('api_key','sk-fake')):
            p=patch.object(settings,target,return_value=value);p.start();self.addCleanup(p.stop)
        self.session=MagicMock();p=patch('deepseek_model.requests.Session',return_value=self.session);p.start();self.addCleanup(p.stop)
        self.response=MagicMock();self.response.status_code=200;self.response.__enter__.return_value=self.response
        self.session.post.return_value=self.response
    def events(self,content='{"assignments":[]}',finish='stop',usage=True):
        events=[dict(choices=[dict(delta=dict(content=content),finish_reason=None)]),dict(choices=[dict(delta={},finish_reason=finish)])]
        if usage:events.append(dict(choices=[],usage=dict(prompt_tokens=120,completion_tokens=30,prompt_cache_hit_tokens=50,prompt_cache_miss_tokens=70)))
        self.response.iter_lines.return_value=[b': keepalive']+[b'data: '+json.dumps(e).encode() for e in events]+[b'data: [DONE]']
    def test_json_once_usage_and_no_local_process(self):
        self.events();stats=[]
        with patch('subprocess.Popen',side_effect=AssertionError('No local process')):
            with DeepSeekModel(lambda:None,lambda *a:None) as model:
                model.usage_callback=stats.append
                self.assertEqual(model._complete_once(PROMPT,SCHEMA,2000,lambda *a:None),dict(assignments=[]))
                self.assertGreaterEqual(model.tokens('Русский текст'),len('Русский текст'.encode()))
        self.assertEqual(self.session.post.call_count,1)
        payload=self.session.post.call_args.kwargs
        self.assertEqual(payload['json']['thinking'],dict(type='disabled'))
        self.assertEqual(payload['json']['response_format'],dict(type='json_object'))
        self.assertIn('JSON Schema',payload['json']['messages'][0]['content'])
        self.assertFalse(payload['allow_redirects'])
        self.assertEqual(stats[0]['prompt_tokens'],120)
    def test_compatible_request_omits_deepseek_extensions(self):
        self.events()
        with DeepSeekModel(lambda:None,lambda *a:None) as model:
            model.options['provider']='openrouter'
            model._complete_once(PROMPT,SCHEMA,2000,lambda *a:None)
        self.assertNotIn('thinking',self.session.post.call_args.kwargs['json'])

    def test_http_errors_do_not_retry_or_echo_key(self):
        for status in (401,402,429,500,302):
            with self.subTest(status=status):
                self.session.post.reset_mock();self.response.status_code=status
                with DeepSeekModel(lambda:None,lambda *a:None) as model:
                    with self.assertRaises(RuntimeError) as error:model._complete_once(PROMPT,SCHEMA,2000,lambda *a:None)
                self.assertNotIn('sk-fake',str(error.exception));self.assertEqual(self.session.post.call_count,1)
    def test_truncation_and_malformed_result_are_not_retried(self):
        for content,finish in (('{','length'),('','stop'),('bad','stop')):
            self.events(content,finish);self.session.post.reset_mock();stats=[]
            with DeepSeekModel(lambda:None,lambda *a:None) as model:
                model.usage_callback=stats.append
                with self.assertRaises((ValueError,RuntimeError)):model._complete_once(PROMPT,SCHEMA,2000,lambda *a:None)
            self.assertEqual(self.session.post.call_count,1);self.assertEqual(len(stats),1)
    def test_network_failure_sanitized_and_no_retry(self):
        self.session.post.side_effect=requests.ConnectionError('sensitive debug sk-fake')
        with DeepSeekModel(lambda:None,lambda *a:None) as model:
            with self.assertRaises(RuntimeError) as error:model._complete_once(PROMPT,SCHEMA,2000,lambda *a:None)
        self.assertNotIn('sk-fake',str(error.exception));self.assertEqual(self.session.post.call_count,1)
    def test_output_limit_is_typed_and_never_retries_identical_request(self):
        self.events('{', 'length');stats=[]
        with DeepSeekModel(lambda:None,lambda *a:None) as model:
            model.usage_callback=stats.append
            model.wait_retry=Mock()
            with self.assertRaises(OutputLimitError):model.complete(PROMPT,SCHEMA,2000,lambda *a:None)
            model.wait_retry.assert_not_called()
        self.assertEqual(self.session.post.call_count,1)
        self.assertEqual(len(stats),1)
    def test_cancel_before_request_costs_no_call(self):
        def stopped():raise InterruptedError('stop')
        with DeepSeekModel(stopped,lambda *a:None) as model:
            with self.assertRaises(InterruptedError):model._complete_once(PROMPT,SCHEMA,2000,lambda *a:None)
        self.session.post.assert_not_called()
    def test_recovery_is_bounded_and_cancellable(self):
        from deepseek_model import RetryableAPIError
        with DeepSeekModel(lambda:None,lambda *a:None) as model:
            model.wait_retry=Mock()
            model._complete_once=Mock(side_effect=[RetryableAPIError('bad JSON'),dict(assignments=[])])
            self.assertEqual(model.complete(PROMPT,SCHEMA,2000,lambda *a:None),dict(assignments=[]))
            self.assertEqual(model._complete_once.call_count,2);model.wait_retry.assert_called_once_with(5,1)
            model._complete_once=Mock(side_effect=RetryableAPIError('network'))
            model.wait_retry.reset_mock()
            with self.assertRaisesRegex(RuntimeError,'четырёх'):model.complete(PROMPT,SCHEMA,2000,lambda *a:None)
            self.assertEqual(model._complete_once.call_count,4)
            self.assertEqual([c.args[0] for c in model.wait_retry.call_args_list],[5,15,30])
            model._complete_once=Mock(side_effect=RuntimeError('invalid key'));model.wait_retry.reset_mock()
            with self.assertRaisesRegex(RuntimeError,'invalid key'):model.complete(PROMPT,SCHEMA,2000,lambda *a:None)
            model.wait_retry.assert_not_called()
        with DeepSeekModel(lambda:None,lambda *a:None) as model:
            model.check=Mock(side_effect=InterruptedError('cancel'))
            with self.assertRaises(InterruptedError):model.wait_retry(30,1)

    def test_probe_uses_models_endpoint_without_generation(self):
        response=MagicMock();response.__enter__.return_value=response;response.status_code=200
        response.json.return_value={'data':[{'id':'deepseek-flash'}]}
        with patch('deepseek_model.requests.get',return_value=response) as get:
            self.assertIn('генерация не запускалась',probe(settings.DEFAULT_URL,'sk-test','deepseek-flash'))
            self.assertEqual(get.call_args.args[0],settings.DEFAULT_URL+'/models')
        self.session.post.assert_not_called()

    def test_book_resume_keeps_completed_paid_blocks_after_failure(self):
        import book_engine as books
        import roles_analysis as roles
        from contextlib import contextmanager
        original_connect=books.connect
        @contextmanager
        def connection(book_id):
            db=original_connect(book_id)
            try:
                with db:yield db
            finally:db.close()
        attempts=[];fail_once=[True]
        def answer(url,**kwargs):
            payload=json.loads(kwargs['json']['messages'][1]['content'])
            rows=payload['target_fragments'];attempts.append(rows[0]['id'])
            if len(attempts)==2 and fail_once[0]:
                fail_once[0]=False;raise requests.ConnectionError('lost connection')
            result=dict(characters=[],summary='Описание леса.',assignments=[dict(id=row['id'],speaker='',uncertain=False,narrator_speech=False,number_readings=[],parts=[dict(unit_id=unit['unit_id'],speaker='') for unit in row['units']]) for row in rows])
            response=MagicMock();response.__enter__.return_value=response;response.status_code=200
            events=[dict(choices=[dict(delta=dict(content=json.dumps(result,ensure_ascii=False)),finish_reason=None)]),dict(choices=[dict(delta={},finish_reason='stop')]),dict(choices=[],usage=dict(prompt_tokens=100,completion_tokens=50))]
            response.iter_lines.return_value=[b'data: '+json.dumps(event).encode() for event in events]+[b'data: [DONE]']
            return response
        self.session.post.side_effect=answer
        with tempfile.TemporaryDirectory() as tmp,patch.object(books,'connect',connection),patch.object(books,'BOOKS',Path(tmp)/'books'),patch.object(store,'DATA',Path(tmp)),patch.object(roles,'VERSION','deepseek-test-v11-scene-context'),patch.object(roles,'CONTEXT',131072):
            source=Path(tmp)/'book.txt';source.write_text('Глава первая\n'+('\n'.join('В лесу было тихо.' for _ in range(44))),encoding='utf-8')
            bid='apitest';books.import_book(source,bid,lambda *a:None)
            with books.connect(bid) as db:
                db.execute('DELETE FROM segments')
                db.executemany('INSERT INTO segments(id,chapter,text) VALUES(?,1,?)',[(i,'В лесу было тихо.') for i in range(1,45)])
            with patch.object(DeepSeekModel,'retry_delays',()),self.assertRaises(RuntimeError):roles.analyze(bid,lambda *a:None,DeepSeekModel)
            with books.connect(bid) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM role_batches').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT count(*) FROM segments WHERE analyzed=1').fetchone()[0],20)
            import book_state
            book_state.force_reset(bid)  # Force-close/recovery must retain paid API blocks too.
            roles.analyze(bid,lambda *a:None,DeepSeekModel)
            self.assertEqual(attempts,[1,21,21,41])  # Failed block only resumed by explicit second run.
            meta=books.metadata(bid);self.assertTrue(meta['analysis_complete']);self.assertEqual(meta['api_usage']['requests_with_usage'],3)
            self.assertEqual(meta['api_usage']['completion_tokens'],150)
            roles.analyze(bid,lambda *a:None,DeepSeekModel)
            self.assertEqual(attempts,[1,21,21,41])
            self.assertTrue((books.folder(bid)/'markup/chapter-0001.json').is_file())

    def test_truncated_book_splits_and_resumes_saved_boundaries(self):
        import book_engine as books
        import roles_analysis as roles
        from contextlib import contextmanager
        original_connect=books.connect
        @contextmanager
        def connection(book_id):
            db=original_connect(book_id)
            try:
                with db:yield db
            finally:db.close()
        attempts=[];interrupt=[True]
        class Model:
            semantic_chapters=False;compact_roles=True
            def __init__(self,*args):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def tokens(self,text):return len(text)
            def complete(self,prompt,schema,budget,callback):
                from roles_model import chat_messages
                rows=json.loads(chat_messages(prompt)[1]['content'])['target_fragments']
                ids=[r['id'] for r in rows];attempts.append(ids)
                if ids[0]==21 and len(ids)>5:raise OutputLimitError('length')
                if ids[0]==21 and interrupt[0]:
                    interrupt[0]=False
                    raise RuntimeError('network failure')
                return dict(characters=[],summary='Лес.',assignments=[dict(id=row['id'],speaker='',uncertain=False,narrator_speech=False,number_readings=[],parts=[dict(unit_id=u['unit_id'],speaker='') for u in row['units']]) for row in rows])
        with tempfile.TemporaryDirectory() as tmp,patch.object(books,'connect',connection),patch.object(books,'BOOKS',Path(tmp)/'books'),patch.object(store,'DATA',Path(tmp)),patch.object(roles,'VERSION','deepseek-split-test'),patch.object(roles,'CONTEXT',131072):
            source=Path(tmp)/'book.txt';source.write_text('Глава первая\nВ лесу было тихо.',encoding='utf-8')
            bid='splittest';books.import_book(source,bid,lambda *a:None)
            with books.connect(bid) as db:
                db.execute('DELETE FROM segments')
                db.executemany('INSERT INTO segments(id,chapter,text) VALUES(?,1,?)',[(i,'В лесу было тихо.') for i in range(1,41)])
            with self.assertRaisesRegex(RuntimeError,'network failure'):roles.analyze(bid,lambda *a:None,Model)
            self.assertEqual([len(ids) for ids in attempts],[20,20,10,5])
            self.assertEqual(books.metadata(bid)['analysis_batch_limits'],{'21':5})
            with books.connect(bid) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM segments WHERE analyzed=1').fetchone()[0],20)
            roles.analyze(bid,lambda *a:None,Model)
            self.assertEqual([(ids[0],len(ids)) for ids in attempts],[(1,20),(21,20),(21,10),(21,5),(21,5),(26,15)])
            self.assertTrue(books.metadata(bid)['analysis_complete'])
            before=len(attempts);roles.analyze(bid,lambda *a:None,Model)
            self.assertEqual(len(attempts),before)

    def test_single_fragment_output_limit_stops_without_loop(self):
        import book_engine as books
        import roles_analysis as roles
        from contextlib import contextmanager
        original_connect=books.connect
        @contextmanager
        def connection(book_id):
            db=original_connect(book_id)
            try:
                with db:yield db
            finally:db.close()
        calls=[]
        class Model:
            semantic_chapters=False;compact_roles=True
            def __init__(self,*args):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def tokens(self,text):return len(text)
            def complete(self,*args):calls.append(1);raise OutputLimitError('length')
        with tempfile.TemporaryDirectory() as tmp,patch.object(books,'connect',connection),patch.object(books,'BOOKS',Path(tmp)/'books'),patch.object(store,'DATA',Path(tmp)),patch.object(roles,'VERSION','deepseek-single-test'):
            source=Path(tmp)/'book.txt';source.write_text('В лесу было тихо.',encoding='utf-8')
            bid='singletest';books.import_book(source,bid,lambda *a:None)
            with self.assertRaisesRegex(ValueError,'Даже один фрагмент'):roles.analyze(bid,lambda *a:None,Model)
            self.assertEqual(len(calls),1)
            self.assertFalse(books.metadata(bid)['analysis_complete'])
            error=json.loads((books.folder(bid)/'last-analysis-error.json').read_text(encoding='utf-8'))
            self.assertEqual(error['fragment_ids'],[1])

if __name__=='__main__':unittest.main()
