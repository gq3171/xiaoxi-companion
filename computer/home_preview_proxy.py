"""Loopback-only developer preview; always validates the upstream project CA.

No browser/body tokens are configured here, and no request bodies are logged.
"""
import argparse,http.client,json,ssl,os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ORIGIN=os.environ.get('DESKPET_PUBLIC_ORIGIN','https://xiaoxi.example:8791').rstrip('/')
HOST=urlsplit(ORIGIN).hostname;PORT=urlsplit(ORIGIN).port or 443

def handler(context,port=18791):
 class Proxy(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*_):pass
    def error(self,status):
        data=json.dumps(dict(ok=False,error='preview_connection_unavailable')).encode();self.close_connection=True
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.send_header('Connection','close');self.end_headers();self.wfile.write(data)
    def relay(self):
        local=('localhost:'+str(port),'127.0.0.1:'+str(port));path=urlsplit(self.path).path
        if self.headers.get('Host') not in local or not path.startswith('/home/') or self.headers.get('Transfer-Encoding'):self.error(403);return
        if path=='/home/api/desktop/ws' and self.headers.get('Upgrade','').lower()=='websocket':
            from desktop_transport import preview
            try:preview(self,context,HOST,PORT,port)
            except (OSError,ValueError,PermissionError):
                if not self.close_connection:self.error(502)
            return
        try:n=int(self.headers.get('Content-Length','0'))
        except ValueError:self.error(400);return
        maximum=960044 if path=='/home/api/asr' else 8192
        if n<0 or n>maximum:self.error(413);return
        headers={'Host':HOST+':'+str(PORT)}
        for key in ('Content-Type','Cookie','Last-Event-ID','X-Chat-Id'):
            if self.headers.get(key):headers[key]=self.headers[key]
        if self.command=='POST':
            if self.headers.get('Origin') not in tuple('http://'+h for h in local):self.error(403);return
            headers['Origin']=ORIGIN
        upstream=http.client.HTTPSConnection(HOST,PORT,context=context,timeout=45 if path in ('/home/api/asr','/home/api/chat/audio','/home/api/reminders/audio') else 8);sent=False
        try:
            self.connection.settimeout(20);body=self.rfile.read(n) if n else None
            if n and len(body)!=n:self.error(400);return
            upstream.request(self.command,self.path,body,headers);response=upstream.getresponse();events=path in ('/home/events','/home/alerts')
            data=None if events else response.read(5*1024*1024+1)
            if data is not None and len(data)>5*1024*1024:self.error(502);return
            self.send_response(response.status)
            for key,value in response.getheaders():
                if key.lower() not in ('server','date','connection','transfer-encoding'):self.send_header(key,value)
            self.send_header('Connection','close');self.end_headers();sent=True;self.close_connection=True
            if events:
                while True:
                    line=response.fp.readline()
                    if not line:break
                    self.wfile.write(line);self.wfile.flush()
            else:self.wfile.write(data)
        except (OSError,TimeoutError,http.client.HTTPException):
            if not sent:
                try:self.error(502)
                except OSError:pass
        finally:upstream.close()
    do_GET=relay
    do_POST=relay
 return Proxy

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--ca',type=Path,default=Path(__file__).resolve().parents[1]/'firmware/private/computer-ca.pem');args=parser.parse_args()
    context=ssl.create_default_context(cafile=str(args.ca));server=ThreadingHTTPServer(('127.0.0.1',18791),handler(context));server.daemon_threads=True
    print('Loopback home preview http://localhost:18791/home/; upstream CA validation enabled.',flush=True);server.serve_forever()

if __name__=='__main__':main()
