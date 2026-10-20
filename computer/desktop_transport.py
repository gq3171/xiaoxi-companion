"""Authenticated HTTP-to-local wayvnc WebSocket tunnel, without public VNC ports."""
import base64,select,socket,ssl,time,os
from urllib.parse import urlsplit

ORIGIN=os.environ.get('DESKPET_PUBLIC_ORIGIN','https://xiaoxi.example:8791').rstrip('/')
def upgrade_headers(headers):
    try:key=base64.b64decode(headers.get('Sec-WebSocket-Key',''),validate=True)
    except (ValueError,TypeError):raise ValueError('invalid websocket key') from None
    if len(key)!=16 or headers.get('Sec-WebSocket-Version')!='13' or headers.get('Upgrade','').lower()!='websocket' or 'upgrade' not in [s.strip() for s in headers.get('Connection','').lower().split(',')] or headers.get('Transfer-Encoding') or headers.get('Content-Length','0')!='0':raise ValueError('invalid websocket upgrade')
    result={k:headers[k] for k in ('Sec-WebSocket-Key','Sec-WebSocket-Version')}
    result.update(Upgrade='websocket',Connection='Upgrade')
    if headers.get('Sec-WebSocket-Protocol'):
        if headers['Sec-WebSocket-Protocol'].strip()!='binary':raise ValueError('unsupported websocket protocol')
        result['Sec-WebSocket-Protocol']='binary'
    return result

def handshake(h,upstream,headers):
    request='GET / HTTP/1.1\r\n'+''.join(k+': '+v+'\r\n' for k,v in headers.items())+'\r\n'
    upstream.sendall(request.encode('ascii'));data=bytearray()
    while b'\r\n\r\n' not in data:
        part=upstream.recv(4096)
        if not part or len(data)+len(part)>16384:raise OSError('upstream upgrade failed')
        data+=part
    if data.split(b'\r\n',1)[0].split()[1:2]!=[b'101']:raise OSError('upstream did not upgrade')
    h.close_connection=True;h.wfile.write(data);h.wfile.flush()

def relay(left,right,valid=lambda:True,heartbeat=lambda:None,seconds=600,forwarded=lambda client,n:None):
    """Bounded chunks, backpressure, revocation checks and no payload logging."""
    left.settimeout(2);right.settimeout(2);end=time.monotonic()+seconds;next_check=0
    while time.monotonic()<end:
        now=time.monotonic()
        if now>=next_check:
            if not valid():return
            heartbeat();next_check=now+1
        ready=[s for s in (left,right) if isinstance(s,ssl.SSLSocket) and s.pending()]
        if not ready:ready=select.select([left,right],[],[],.5)[0]
        for source in ready:
            data=source.recv(65536)
            if not data:return
            (right if source is left else left).sendall(data)
            forwarded(source is left,len(data))

def serve(h,world,session,desktop,broker):
    from pathlib import Path
    query=urlsplit(h.path).query
    if query not in ('','mode=control'):raise ValueError('unknown desktop channel')
    if h.headers.get('Origin')!=ORIGIN:raise PermissionError('desktop origin denied')
    headers=upgrade_headers(h.headers);headers['Host']='localhost'
    control=query=='mode=control'
    if control and not broker.controls(session):raise PermissionError('desktop control is not leased')
    if not desktop.real_status()['ready']:raise OSError('desktop not ready')
    path=desktop.path.parent/('vnc-control.sock' if control else 'vnc-view.sock')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as upstream:
        upstream.settimeout(3);upstream.connect(str(path));handshake(h,upstream,headers)
        def valid():
            if world.session(h)!=session:broker.revoke(session);return False
            return not control or broker.controls(session)
        channel=broker.transport_open(session) if control else None
        try:relay(h.connection,upstream,valid,lambda:desktop.heartbeat(),forwarded=lambda client,n:broker.transport_bytes(channel,n) if control and client else None)
        except (OSError,ValueError):pass
        finally:
            if control:broker.transport_close(channel)

def preview(h,context,host,port,local_port):
    local=tuple('http://'+x+':'+str(local_port) for x in ('localhost','127.0.0.1'))
    if h.headers.get('Origin') not in local:raise PermissionError('preview origin denied')
    headers=upgrade_headers(h.headers);headers.update(Host=host+':'+str(port),Origin=ORIGIN)
    if h.headers.get('Cookie'):
        if any(c in h.headers['Cookie'] for c in '\r\n') or len(h.headers['Cookie'])>4096:raise ValueError('invalid preview cookie')
        headers['Cookie']=h.headers['Cookie']
    with socket.create_connection((host,port),timeout=8) as raw:
        with context.wrap_socket(raw,server_hostname=host) as upstream:
            request='GET '+h.path+' HTTP/1.1\r\n'+''.join(k+': '+v+'\r\n' for k,v in headers.items())+'\r\n'
            upstream.sendall(request.encode('ascii'));data=bytearray()
            while b'\r\n\r\n' not in data:
                part=upstream.recv(4096)
                if not part or len(data)+len(part)>16384:raise OSError('preview upgrade failed')
                data+=part
            if data.split(b'\r\n',1)[0].split()[1:2]!=[b'101']:raise OSError('preview upgrade rejected')
            h.close_connection=True;h.wfile.write(data);h.wfile.flush()
            try:relay(h.connection,upstream)
            except OSError:pass
