#!/usr/bin/env python3
"""One unprivileged Wayland desktop, private noVNC channels and native app dock."""
import html,json,os,signal,socket,struct,subprocess,threading,time
from desktop_shell import prepare as prepare_shell
from desktop_stop import close_browser
from desktop_launcher import browser_args,browser_running
from runtime_config import settings, cdp_port, allowed_cdp_ports
from pathlib import Path

from deployment_paths import desktop_root, storage_ready
ROOT=desktop_root()
FRAME_LIMIT=768*1024
class Desktop:
 def __init__(self,root=ROOT,clock=time.monotonic):
  self.root=Path(root);self.clock=clock;self.stop=threading.Event();self.browser_requested=threading.Event();self.lock=threading.Lock();self.frame=b'';self.sequence=0;self.captured_at=0.;self.last_view=clock();self.last_png=clock();self.task=None;self.failed=False;self.vnc_ready=False
 def update(self,task):
  if task is not None and (not isinstance(task,dict) or len(json.dumps(task,ensure_ascii=False).encode())>6000):raise ValueError('task budget')
  with self.lock:self.last_view=self.clock();changed=task!=self.task;self.task=task
  if changed:self.write_dashboard()
 def write_dashboard(self):
  with self.lock:t=self.task or {}
  states={'queued':'等待执行','running':'正在执行','succeeded':'已完成','failed':'未完成','interrupted':'已中断','cancelled':'已停止'}
  active=t.get('state') in ('queued','running');title='我正在做' if active else '最近的一项工作' if t else '工作台已准备好'
  esc=lambda value:html.escape(str(value))
  step=t.get('step') or {};detail=('第 '+str(step.get('ordinal',0))+' 步 · '+('检查' if step.get('kind')=='check' else '执行')) if step else ''
  body='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="4"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>小溪的工作电脑</title><style>body{margin:0;background:#202b37;color:#e6e8ed;font:18px 'Noto Sans CJK SC',sans-serif}main{max-width:1000px;margin:60px auto;padding:0 40px}small{color:#a9bdc7;letter-spacing:.15em}h1{font-size:34px;font-weight:500;margin:12px 0 32px}article{padding:30px;background:#2d3c49;border:1px solid #455764;border-radius:16px}h2{font-size:22px;color:#edceb4}p{line-height:1.8;overflow-wrap:anywhere}.state{color:#abd6bc}.foot{font-size:14px;color:#9dafbb;margin-top:28px}</style><main><small>XIAOXI · LINUX WORKSPACE</small><h1>小溪的工作电脑</h1><article><h2>'''+esc(title)+'''</h2><p>'''+esc(t.get('goal') or '你可以继续和我聊天，也可以交给我一件事。')+'''</p><p class="state">'''+esc(states.get(t.get('state'), '空闲'))+'　'+esc(detail)+'''</p><p>'''+esc(t.get('message') or '浏览器和图形程序会在这个桌面上显示。')+'''</p></article><p class="foot">这是小主机上的真实专用桌面。后台命令的进度显示在这里；未完成的事情不会标为完成。</p></main></html>'''
  p=self.root/'desk.new';p.write_text(body);p.replace(self.root/'desk.html')
 def capture(self):
  while not self.stop.wait(1):
   if self.clock()-self.last_png>6:continue
   try:
    result=subprocess.run(['/usr/bin/grim','-t','png','-l','1','-s','0.75','-'],capture_output=True,timeout=3,check=True)
    data=result.stdout
    if not 100<len(data)<=FRAME_LIMIT or data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('frame budget')
    with self.lock:self.frame=data;self.sequence+=1;self.captured_at=time.time();self.failed=False
   except (OSError,subprocess.SubprocessError,ValueError):
    with self.lock:self.failed=True
 def respond(self,conn):
  conn.settimeout(2)
  try:
   raw=bytearray()
   while b'\n' not in raw:
    part=conn.recv(min(1024,8193-len(raw)))
    if not part or len(raw)+len(part)>8192:raise ValueError('request budget')
    raw+=part
   req=json.loads(raw.split(b'\n',1)[0]);op=req.get('op')
   if op=='view':self.update(req.get('task'));self.last_png=self.clock()
   elif op=='heartbeat':
    self.update(req.get('task'))
   elif op=='stop':self.stop.set()
   elif op=='browser':self.browser_requested.set()
   elif op!='frame':raise ValueError('unknown operation')
   with self.lock:
    fresh=bool(self.frame) and not self.failed and time.time()-self.captured_at<5
    data=self.frame if op=='frame' and fresh else json.dumps(dict(protocol=1,ready=self.vnc_ready if op in ('heartbeat','browser') else fresh,sequence=self.sequence,captured_at=self.captured_at)).encode()
   conn.sendall(struct.pack('!I',len(data))+data)
  except (OSError,ValueError,TypeError):pass
  finally:conn.close()

def main():
 if os.geteuid()==0 or not storage_ready():raise SystemExit('unprivileged user and configured storage mount required')
 os.umask(0o077)
 for name in ('runtime','cache','profile','tmp','config','downloads'):(ROOT/name).mkdir(mode=0o700,exist_ok=True)
 env=os.environ.copy();env.update(HOME=str(ROOT),XDG_RUNTIME_DIR=str(ROOT/'runtime'),XDG_CACHE_HOME=str(ROOT/'cache'),TMPDIR=str(ROOT/'tmp'),WAYLAND_DISPLAY='wayland-0',WLR_BACKENDS='headless',WLR_HEADLESS_OUTPUTS='1',WLR_RENDERER=settings()['desktop']['renderer'],WLR_RENDER_DRM_DEVICE=settings()['desktop']['drm_device'],LIBSEAT_BACKEND='noop')
 env.update(XDG_CONFIG_HOME=str(ROOT/'config'),XDG_DATA_HOME=str(ROOT/'data'),XDG_STATE_HOME=str(ROOT/'state'),LANG='C.UTF-8',XDG_CURRENT_DESKTOP='labwc',FONTCONFIG_FILE='/etc/fonts/fonts.conf')
 os.environ.update(env);dock_config,dock_style=prepare_shell(ROOT);desktop=Desktop();desktop.write_dashboard();processes=[];critical=[];chrome=None
 def stop(*_):desktop.stop.set()
 signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
 try:
  lab=subprocess.Popen(['/usr/bin/labwc','--config-dir',str(ROOT/'config')],env=env,start_new_session=True);processes.append(lab)
  deadline=time.monotonic()+10
  while not (ROOT/'runtime/wayland-0').exists():
   if lab.poll() is not None or time.monotonic()>deadline:raise RuntimeError('compositor not ready')
   if desktop.stop.wait(.1):return
  for name,readonly in [('view',True),('control',False)]:
   path=ROOT/'runtime'/('rfb-'+name+'.sock');path.unlink(missing_ok=True)
   args=['/usr/local/libexec/deskpet-wayvnc-headless','--unix-socket','--disable-resizing','--max-fps='+str(settings()['desktop']['max_fps']),'--log-level=warning','--socket='+str(ROOT/'runtime'/('wayvnc-'+name+'.ctl'))]
   if readonly:args.append('--disable-input')
   args.append(str(path));processes.append(subprocess.Popen(args,env=env,start_new_session=True))
   ws=ROOT/'runtime'/('vnc-'+name+'.sock');ws.unlink(missing_ok=True)
   processes.append(subprocess.Popen(['/usr/bin/websockify','--unix-listen='+str(ws),'--unix-listen-mode=0600','--unix-target='+str(path)],env=env,start_new_session=True))
  deadline=time.monotonic()+8
  while not all((ROOT/'runtime'/('vnc-'+n+'.sock')).exists() for n in ('view','control')):
   if time.monotonic()>deadline or any(p.poll() is not None for p in processes):raise RuntimeError('VNC service not ready')
   time.sleep(.1)
  for name in ('view','control'):os.chmod(ROOT/'runtime'/('vnc-'+name+'.sock'),0o600)
  desktop.vnc_ready=True
  background=subprocess.Popen(['/usr/bin/swaybg','--color','#eee0d4'],env=env,start_new_session=True);processes.append(background)
  dock_args=['/usr/bin/waybar','--config',str(dock_config),'--style',str(dock_style)]
  panel=subprocess.Popen(dock_args,env=env,start_new_session=True);processes.append(panel);panel_retry=0.;panel_restarts=0
  critical=list(processes[:-2])
  port=str(cdp_port())
  chrome=subprocess.Popen(browser_args(ROOT,(ROOT/'desk.html').as_uri(),port),env=env,start_new_session=True);processes.append(chrome)
  socket_path=ROOT/'runtime/view.sock';socket_path.unlink(missing_ok=True)
  with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
   listener.bind(str(socket_path));os.chmod(socket_path,0o600);listener.listen(8);listener.settimeout(.5)
   capture=threading.Thread(target=desktop.capture,daemon=True);capture.start()
   while not desktop.stop.is_set():
    if any(p.poll() is not None for p in critical):raise RuntimeError('desktop process stopped')
    if panel.poll() is not None and panel_restarts<3 and time.monotonic()>=panel_retry:
     panel=subprocess.Popen(dock_args,env=env,start_new_session=True);processes.append(panel);panel_restarts+=1;panel_retry=time.monotonic()+10
    if desktop.browser_requested.is_set():
     desktop.browser_requested.clear()
     if not browser_running(port):
      chrome=subprocess.Popen(browser_args(ROOT,(ROOT/'desk.html').as_uri(),port),env=env,start_new_session=True);processes.append(chrome)
    try:conn,_=listener.accept()
    except socket.timeout:continue
    desktop.respond(conn)
 except BaseException:
  desktop.stop.set();raise
 finally:
  desktop.stop.set()
  try:
   close_browser(str(cdp_port()),ROOT)
   if chrome is not None and chrome.poll() is None:chrome.wait(timeout=4)
  except Exception:pass
  for p in reversed(processes):
   if p.poll() is None:
    try:os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=5)
    except (ProcessLookupError,subprocess.TimeoutExpired):
     if p.poll() is None:os.killpg(p.pid,signal.SIGKILL);p.wait()
  (ROOT/'runtime/view.sock').unlink(missing_ok=True)
if __name__=='__main__':main()
