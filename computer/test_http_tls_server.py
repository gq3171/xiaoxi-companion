"""A slow ClientHello must not prevent other clients using the real TLS server."""
import http.client,socket,ssl,subprocess,tempfile,threading,time,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from http_tls_server import ThreadedTLSServer

class TLSServerTests(unittest.TestCase):
 def test_stalled_handshake_isolated_bounded_and_expires(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(p/'key'),'-out',str(p/'cert'),'-days','1','-subj','/CN=localhost'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def do_GET(self):self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'ok')
   server=ThreadedTLSServer(('127.0.0.1',0),Handler);server.handshake_timeout=.6
   server.tls_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server.tls_context.load_cert_chain(p/'cert',p/'key');thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();stalled=[]
   try:
    stalled=[socket.create_connection(server.server_address) for _ in range(3)]
    # Trust only this ephemeral test certificate, retaining hostname verification.
    ctx=ssl.create_default_context(cafile=str(p/'cert'));start=time.monotonic();c=http.client.HTTPSConnection('localhost',server.server_port,context=ctx,timeout=2);c.request('GET','/');r=c.getresponse();self.assertEqual((r.status,r.read()),(200,b'ok'));c.close();self.assertLess(time.monotonic()-start,.6)
    for s in stalled:s.settimeout(2);self.assertEqual(s.recv(1),b'')
    self.assertTrue(all(server._handshakes.acquire(timeout=1) for _ in range(8)));self.assertFalse(server._handshakes.acquire(blocking=False))
    for _ in range(8):server._handshakes.release()
   finally:
    for s in stalled:s.close()
    server.shutdown();server.server_close();thread.join(2)
