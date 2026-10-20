import io,ssl,types,unittest
import test_brain as fixtures


class DisconnectTests(unittest.TestCase):
    def test_cancelled_upload_does_not_raise_when_tls_is_already_closed(self):
        brain=fixtures.brain.Brain.__new__(fixtures.brain.Brain);brain.token='x'*48
        for error in (BrokenPipeError('closed'),ssl.SSLEOFError('closed')):
            for fail_headers in (True,False):
                class Handler:
                    headers={'Authorization':'Bearer '+'x'*48,'Content-Length':'20'}
                    path='/v1/brain/model'
                    connection=types.SimpleNamespace(settimeout=lambda seconds:None)
                    rfile=io.BytesIO(b'{}')
                    wfile=types.SimpleNamespace(write=lambda body:(_ for _ in ()).throw(error))
                    def send_response(self,code):self.code=code
                    def send_header(self,*args):pass
                    def end_headers(self):
                        if fail_headers:raise error
                handler=Handler();brain.handle_http(handler)
                self.assertEqual(handler.code,400);self.assertTrue(handler.close_connection)
