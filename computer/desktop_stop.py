#!/usr/bin/env python3
"""Finish the private desktop before systemd signals every GUI child."""
import json,os,socket,struct,time
from urllib.request import build_opener,ProxyHandler
from urllib.parse import urlsplit
from runtime_config import settings, cdp_port, allowed_cdp_ports
from pathlib import Path
from deployment_paths import desktop_root

def close_browser(port,root=None,cancelled=lambda:False):
 # Browser.close performs a normal profile flush; SIGTERM alone marks it crashed.
 port=int(port)
 if port not in allowed_cdp_ports():raise ValueError('unexpected private browser port')
 if cancelled():raise InterruptedError('browser close cancelled before dispatch')
 opener=build_opener(ProxyHandler({}))
 with opener.open('http://127.0.0.1:'+str(port)+'/json/version',timeout=2) as response:info=json.loads(response.read(16384))
 url=info['webSocketDebuggerUrl'];parsed=urlsplit(url)
 if parsed.scheme!='ws' or parsed.hostname!='127.0.0.1' or parsed.port!=port:raise ValueError('unexpected browser endpoint')
 import websocket
 connection=websocket.create_connection(url,timeout=2,suppress_origin=True,http_proxy_host=None,http_no_proxy=['127.0.0.1'])
 try:
  if cancelled():raise InterruptedError('browser close cancelled before dispatch')
  connection.send(json.dumps({'id':1,'method':'Browser.close'}))
  try:connection.recv()
  except (websocket.WebSocketConnectionClosedException,websocket.WebSocketTimeoutException):pass
 finally:connection.close()
 if root is not None:
  deadline=time.monotonic()+4;lock=Path(root)/'profile/SingletonLock'
  while os.path.lexists(lock) and time.monotonic()<deadline:time.sleep(.05)

def stop(root,seconds=9):
 path=Path(root)/'runtime/view.sock'
 if not path.exists():return
 try:
  with socket.socket(socket.AF_UNIX) as s:
   s.settimeout(2);s.connect(str(path));s.sendall(b'{"op":"stop"}\n');prefix=s.recv(4)
   if len(prefix)!=4:raise OSError('short stop reply')
   length=struct.unpack('!I',prefix)[0]
   if not 1<=length<=4096:raise OSError('stop reply budget')
   # Completion is the daemon removing its socket after GUI cleanup, not the ack.
   s.recv(length)
 except FileNotFoundError:return
 deadline=time.monotonic()+seconds
 while path.exists():
  if time.monotonic()>=deadline:raise TimeoutError('desktop did not stop cleanly')
  time.sleep(.1)
if __name__=='__main__':stop(desktop_root())
