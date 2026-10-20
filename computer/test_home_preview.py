import io,json,threading,unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import home_preview_proxy as preview

class Response:
    status=200
    def __init__(self,data):self.data=data
    def getheaders(self):return [('Content-Type','audio/wav'),('Content-Length',str(len(self.data)))]
    def read(self,n):return self.data[:n]

class HomePreviewTests(unittest.TestCase):
    def setUp(self):
        self.context=object();self.sent=[];self.data=b'voice-response';outer=self
        class Upstream:
            def __init__(self,*args,**kwargs):outer.options=kwargs
            def request(self,*args):outer.sent.append(args)
            def getresponse(self):return Response(outer.data)
            def close(self):pass
        self.patch=patch.object(preview.http.client,'HTTPSConnection',Upstream);self.patch.start()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),preview.handler(self.context));self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.patch.stop()
    def call(self,path,body,origin='http://localhost:18791'):
        c=HTTPConnection('127.0.0.1',self.server.server_port);c.request('POST',path,body,{'Host':'localhost:18791','Origin':origin,'Content-Type':'audio/wav','X-Chat-Id':'a'*32});r=c.getresponse();status,data=r.status,r.read();c.close();return status,data
    def test_recording_budget_identifier_and_tls_context_are_forwarded(self):
        self.assertEqual(self.call('/home/api/asr',b'0'*10000)[0],200);self.assertEqual(self.sent[0][3]['X-Chat-Id'],'a'*32);self.assertEqual(self.sent[0][3]['Origin'],'https://xiaoxi.example:8791');self.assertIs(self.options['context'],self.context);self.assertEqual(self.options['timeout'],45)
    def test_wrong_origin_and_large_body_never_reach_upstream(self):
        self.assertEqual(self.call('/home/api/asr',b'0',origin='https://wrong.example')[0],403);self.assertFalse(self.sent)
        self.assertEqual(self.call('/home/api/chat',b'0'*8193)[0],413);self.assertFalse(self.sent)
    def test_long_reply_audio_is_not_truncated_at_old_two_megabyte_limit(self):
        self.data=b'0'*(3*1024*1024);status,data=self.call('/home/api/chat/audio',b'{}');self.assertEqual(status,200);self.assertEqual(data,self.data)
