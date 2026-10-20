import base64,hashlib,json,os,threading,tempfile,unittest,zlib
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import agent

class PanelResourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=agent.Store(self.root/'state/jobs.sqlite3')
        self.assets=self.root/'data/panel-resources';self.assets.mkdir(parents=True)
        self.payload=bytes(range(256))*100;self.sha=hashlib.sha256(self.payload).hexdigest()
        (self.assets/(self.sha+'.bin')).write_bytes(self.payload)
        (self.assets/'manifest.json').write_text(json.dumps({'version':1,'font':dict(bytes=len(self.payload),sha256=self.sha,kind=1)}))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),agent.handler(self.store,'x'*48,lambda:True));self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.store.db.close();self.tmp.cleanup()
    def call(self,body=None,token='x'*48):
        body=body or dict(sha256=self.sha,offset=0,bytes=16384)
        r=Request(f'http://127.0.0.1:{self.server.server_port}/v1/computer/resource',json.dumps(body).encode(),{'Authorization':'Bearer '+token})
        with urlopen(r,timeout=3) as response:return json.load(response)
    def denied(self,body=None,token='x'*48):
        with self.assertRaises(HTTPError) as e:self.call(body,token)
        self.assertNotIn(self.tmp.name,e.exception.read().decode());e.exception.close()
    def test_pairing_and_exact_bounded_byte_ranges_do_not_schedule_tasks(self):
        self.denied(token='wrong');parts=[]
        for offset in (0,16384):
            r=self.call(dict(sha256=self.sha,offset=offset,bytes=16384));data=base64.b64decode(r['data'])
            self.assertEqual(r['offset'],offset);self.assertEqual(r['total'],len(self.payload));self.assertEqual(r['sha256'],self.sha)
            self.assertLessEqual(len(data),16384);self.assertEqual(r['crc32'],zlib.crc32(data));parts.append(data)
        self.assertEqual(b''.join(parts),self.payload)
        self.assertFalse(self.store.db.execute('SELECT 1 FROM jobs').fetchone())
    def test_traversal_unregistered_digest_oversize_and_boolean_offsets_are_rejected(self):
        for extra in [dict(sha256='../service.env'),dict(sha256='f'*64),dict(bytes=16385),dict(bytes=True),dict(offset=-1),dict(offset=True),dict(offset=1),dict(offset=32768)]:
            self.denied(dict(sha256=self.sha,offset=0,bytes=16384)|extra)
    def test_corruption_and_symlinks_are_rejected_even_after_a_valid_read(self):
        self.call();path=self.assets/(self.sha+'.bin');path.write_bytes(b'X'*len(self.payload));self.denied()
        path.unlink();outside=self.root/'outside.bin';outside.write_bytes(self.payload);path.symlink_to(outside);self.denied()
