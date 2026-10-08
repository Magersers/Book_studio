import hashlib,tempfile,unittest,threading
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from unittest.mock import patch
from download_upgrade import fetch,DownloadError
BODY=b'0123456789'*5000
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  if self.path=='/fail':self.send_error(503);return
  begin,end=map(int,self.headers['Range'][6:].split('-'))
  self.send_response(206);self.send_header('Content-Range',f'bytes {begin}-{end}/{len(BODY)}');self.end_headers();self.wfile.write(BODY[begin:end+1])
class DownloadTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=cls.server.serve_forever,daemon=True).start();cls.url='http://127.0.0.1:'+str(cls.server.server_port)
 @classmethod
 def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
 def test_fallback_resume_and_cache(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'model.gguf';p.with_suffix('.gguf.part').write_bytes(BODY[:137])
   fetch([self.url+'/fail',self.url+'/ok'],p,hashlib.sha256(BODY).hexdigest(),len(BODY))
   self.assertEqual(p.read_bytes(),BODY)
   fetch(self.url+'/fail',p,hashlib.sha256(BODY).hexdigest(),len(BODY))
 def test_wrong_hash_is_quarantined_and_next_attempt_recovers(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'model.gguf';p.with_suffix('.gguf.part').write_bytes(b'x'*len(BODY))
   with self.assertRaises(DownloadError):fetch(self.url+'/ok',p,hashlib.sha256(BODY).hexdigest(),len(BODY))
   self.assertFalse(p.exists());self.assertFalse(p.with_suffix('.gguf.part').exists())
   fetch(self.url+'/ok',p,hashlib.sha256(BODY).hexdigest(),len(BODY));self.assertEqual(p.read_bytes(),BODY)
 def test_failure_retains_prefix(self):
  with tempfile.TemporaryDirectory() as tmp,patch('time.sleep'):
   p=Path(tmp)/'model.gguf';partial=p.with_suffix('.gguf.part');partial.write_bytes(BODY[:100])
   with self.assertRaises(DownloadError):fetch(self.url+'/fail',p,hashlib.sha256(BODY).hexdigest(),len(BODY))
   self.assertEqual(partial.read_bytes(),BODY[:100])
if __name__=='__main__':unittest.main()
