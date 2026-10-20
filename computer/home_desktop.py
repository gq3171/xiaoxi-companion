"""Authenticated, view-only desktop adapter. Fixed local service; no input RPC."""
import json,os,socket,struct,subprocess,threading,time
from pathlib import Path

SOCKET=Path('/mnt/nvme/deskpet-desktop/runtime/view.sock')
MAX_FRAME=768*1024
class DesktopUnavailable(Exception):pass

class HostDesktop:
 def __init__(self,store,path=SOCKET):
  self.store=store;self.path=Path(path);self.lock=threading.Lock();self.last_start=-1000.;self.last_status=None;self.last_seen=0.
 def task(self):
  with self.store.lock:
   row=self.store.db.execute("SELECT id,goal,state,message,updated FROM jobs ORDER BY CASE WHEN state IN ('queued','running') THEN 0 ELSE 1 END,created DESC LIMIT 1").fetchone()
   if not row:return None
   row=dict(row);steps=self.store.db.execute('SELECT ordinal,kind,exit_code FROM steps WHERE job=? ORDER BY ordinal DESC LIMIT 1',(row['id'],)).fetchone()
  # Raw commands/stdout can contain credentials and are deliberately excluded.
  return dict(id=row['id'],goal=row['goal'][:400],state=row['state'],message=row['message'][:600],updated=row['updated'],step=dict(steps) if steps else None)
 def rpc(self,op):
  body={'op':op}
  if op in ('view','heartbeat'):body['task']=self.task()
  raw=json.dumps(body,ensure_ascii=False).encode()
  if len(raw)>8192:raise DesktopUnavailable('desktop request budget')
  try:
   with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(2);s.connect(str(self.path));s.sendall(raw+b'\n')
    prefix=self.read(s,4);length=struct.unpack('!I',prefix)[0]
    if not 1<=length<=MAX_FRAME:raise DesktopUnavailable('desktop response budget')
    data=self.read(s,length)
  except (OSError,ValueError,struct.error):raise DesktopUnavailable('desktop not ready') from None
  if op=='frame':
   if data[:8]!=b'\x89PNG\r\n\x1a\n':raise DesktopUnavailable('desktop frame unavailable')
   return data
  try:value=json.loads(data)
  except ValueError:raise DesktopUnavailable('invalid desktop status') from None
  if not isinstance(value,dict) or value.get('protocol')!=1:raise DesktopUnavailable('invalid desktop protocol')
  # Relay only a small typed status, never daemon exception bodies/paths.
  return dict(ok=True,ready=value.get('ready') is True,sequence=int(value.get('sequence',0)),captured_at=float(value.get('captured_at',0)),width=960,height=540,desktop_width=1280,desktop_height=720,view_only=True,task=self.task())
 @staticmethod
 def read(s,n):
  out=bytearray()
  while len(out)<n:
   part=s.recv(n-len(out))
   if not part:raise DesktopUnavailable('short desktop response')
   out+=part
  return bytes(out)
 def open(self):
  with self.lock:
   try:return self.rpc('view')
   except DesktopUnavailable:pass
   now=time.monotonic()
   if now-self.last_start>=15:
    self.last_start=now
    try:subprocess.run(['/usr/bin/systemctl','start','deskpet-desktop.service'],check=True,timeout=5,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except (OSError,subprocess.SubprocessError):raise DesktopUnavailable('desktop service unavailable') from None
  return dict(ok=True,ready=False,view_only=True,task=self.task())
 def status(self):
  try:return self.rpc('view')
  except DesktopUnavailable:return dict(ok=True,ready=False,view_only=True,task=self.task())
 def frame(self):return self.rpc('frame')
 def heartbeat(self):return self.rpc('heartbeat')
 def ensure_browser(self):return self.rpc('browser')
 def real_status(self):
  try:value=self.heartbeat()
  except DesktopUnavailable:
   self.open();return dict(ok=True,ready=False,view_only=True,task=self.task())
  value['transport']='novnc';return value
