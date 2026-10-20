"""Actual paired HTTP metadata, without scheduling work or model calls."""
import json
import threading
import types
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import agent


class PresentationContractTests(unittest.TestCase):
    def test_auto_preview_is_derived_from_actual_job_media_and_requires_pairing(self):
        job_id='a'*32
        row={'id':job_id,'state':'succeeded','goal':'测试交付','message':'弄好啦。','media':[]}
        holder=types.SimpleNamespace(get=lambda key:dict(row) if key==job_id else None)
        server=ThreadingHTTPServer(('127.0.0.1',0),agent.handler(holder,'x'*48,lambda:True))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def call(token='x'*48):
            payload={'job_id':job_id,'client_version':2,'auto_preview':True}
            req=Request(f'http://127.0.0.1:{server.server_port}/v1/computer/status',json.dumps(payload).encode(),{'Authorization':'Bearer '+token})
            with urlopen(req,timeout=3) as response:return json.load(response)
        try:
            with self.assertRaises(HTTPError) as denied:call('wrong')
            self.assertEqual(denied.exception.code,401);denied.exception.close()
            for kinds,expected in [([],False),(['audio'],False),(['image'],True),(['video'],True),(['audio','image'],True)]:
                row['media']=[{'kind':kind} for kind in kinds]
                result=call()
                self.assertEqual(result['job_id'],job_id)
                self.assertEqual(result['state'],'succeeded')
                self.assertEqual(result['auto_preview'],expected)
                self.assertNotIn('media',result)  # Only a bounded capability bit.
        finally:
            server.shutdown();server.server_close();thread.join()
