"""Opt-in real Chromium grounding probe; synthetic local page and isolated profile.

Called by a deployment agent in an isolated temporary source tree. Does not read
credentials. Optional infer(system,messages) callback may use a configured model;
only synthetic geometric images are supplied. Never attach to the live desktop.
"""
import json,os,pathlib,pwd,signal,subprocess,tempfile,threading,time
import urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
import browser_tools as bt
from browser_tools import Browser,BrowserUnavailable,BrowserBlocked
from desktop_browser import DesktopBrowser

HTML=b'''<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#eee}h1{height:60px;margin:0;padding:12px;box-sizing:border-box;font:24px sans-serif}canvas{display:block;margin:20px}</style><h1 id="status">Choose the shape</h1><canvas width="900" height="540" aria-label="Geometric selection demo"></canvas><script>
const q=new URLSearchParams(location.search),n=Number(q.get('n')||0),c=document.querySelector('canvas'),g=c.getContext('2d');
const places=[[160,140],[450,390],[740,180]],s=n%3;g.fillStyle='#fff';g.fillRect(0,0,900,540);
places.forEach(([x,y],i)=>{g.beginPath();if(i===s){for(let k=0;k<10;k++){const a=k*Math.PI/5-Math.PI/2,r=k%2?25:58;g.lineTo(x+Math.cos(a)*r,y+Math.sin(a)*r)}g.closePath();g.fillStyle='#e5a800';g.fill()}else if(i===(s+1)%3){g.fillStyle='#2876dd';g.fillRect(x-48,y-48,96,96)}else{g.fillStyle='#dd4242';g.arc(x,y,48,0,Math.PI*2);g.fill()}});
c.addEventListener('click',e=>{const r=c.getBoundingClientRect(),x=(e.clientX-r.left)*900/r.width,y=(e.clientY-r.top)*540/r.height,p=places[s];document.querySelector('#status').textContent=Math.abs(x-p[0])<40&&Math.abs(y-p[1])<40?'Target confirmed':'Wrong target';});
</script>'''

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(HTML)));self.end_headers();self.wfile.write(HTML)

def run(root,port,account,infer=None):
 import websocket
 root=pathlib.Path(root);user=pwd.getpwnam(account)
 with tempfile.TemporaryDirectory(prefix='visual-probe-',dir=root) as tmp:
  folder=pathlib.Path(tmp);folder.chmod(0o711);profile=folder/'profile';profile.mkdir(mode=0o700);os.chown(profile,user.pw_uid,user.pw_gid)
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  process=subprocess.Popen(['/usr/bin/chromium','--headless=new','--no-sandbox','--disable-gpu','--no-first-run','--disable-background-networking','--window-size=1080,840','--force-device-scale-factor=1.5','--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(port),'--user-data-dir='+str(profile)],user=user.pw_uid,group=user.pw_gid,extra_groups=[],env={'PATH':'/usr/bin:/bin','HOME':str(profile),'LANG':'C.UTF-8'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
  browser=None
  def transport(self,url,cancelled=lambda:False):
   from urllib.parse import urlsplit
   p=urlsplit(url)
   if p.scheme!='ws' or p.hostname!='127.0.0.1' or p.port!=port:raise ValueError('probe endpoint only')
   self.ws=websocket.create_connection(url,timeout=.5,suppress_origin=True,skip_utf8_validation=True,http_proxy_host=None,http_no_proxy=['127.0.0.1']);self.serial=0;self.cancelled=cancelled
  try:
   deadline=time.monotonic()+15
   while True:
    try:
     with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version',timeout=1) as response:info=json.load(response)
     break
    except Exception:
     if time.monotonic()>deadline:raise RuntimeError('isolated Chromium not ready')
     time.sleep(.1)
   with patch.object(bt.CDP,'__init__',transport),patch.object(bt,'ENDPOINT',f'http://127.0.0.1:{port}'):
    browser=object.__new__(DesktopBrowser);Browser.__init__(browser,'a'*32,folder/'work');browser.ready=True;browser.heartbeat=lambda:None;browser.desktop=SimpleNamespace(heartbeat=lambda:None);browser.control=bt.CDP(info['webSocketDebuggerUrl'])
    browser.open(f'http://127.0.0.1:{server.server_port}/?n=0');page=browser.page();deadline=time.monotonic()+6
    while True:
     if 'Choose the shape' in browser.snapshot().get('text',''):break
     if time.monotonic()>deadline:raise RuntimeError('local fixture not ready')
     time.sleep(.1)
    # First verify actual CDP/Canvas hit and HiDPI mapping without model inference.
    view=browser.visual_look();surface=browser._visual['surface'];x,y=180,220
    box=[round((x-15)*1000/surface['width']),round((y-15)*1000/surface['height']),round((x+15)*1000/surface['width']),round((y+15)*1000/surface['height'])]
    browser.visual_click(view['visual'],box,'gold star');assert browser.check('Target confirmed')['passed']
    checks=0
    if infer:
     for n in (1,2,0):
      page.call('Page.navigate',dict(url=f'http://127.0.0.1:{server.server_port}/?n={n}'));time.sleep(.3)
      view=browser.visual_look()
      system='You locate UI targets using only the supplied screenshot. Return one JSON object: {"action":"browser_visual_click","visual":"'+view['visual']+'","box":[left,top,right,bottom],"target":"gold star"}. Coordinates are integers 0..1000 relative to the entire supplied image. Find the GOLD FIVE-POINTED STAR, use a small 20x20 pixel box at its center. Do not choose the red circle or blue square.'
      answer=infer(system,[browser.visual_message(view['visual'])])
      if answer.get('action')!='browser_visual_click':raise RuntimeError('model did not produce grounded click')
      browser.visual_click(answer.get('visual'),answer.get('box'),answer.get('target'))
      if not browser.check('Target confirmed')['passed']:raise RuntimeError('model target was not confirmed by actual page')
      checks+=1
    # A target-region change must stop the actual input, not merely warn.
    view=browser.visual_look();page.evaluate("document.querySelector('canvas').getContext('2d').fillRect(0,0,900,540)")
    try:browser.visual_click(view['visual'],box,'gold star')
    except BrowserUnavailable:pass
    else:raise AssertionError('changed target clicked')
    # Sensitive values prevent capturing a subsequent screenshot at all.
    page.evaluate("document.body.insertAdjacentHTML('beforeend','<input type=password value=synthetic>')")
    try:browser.visual_look()
    except BrowserBlocked:pass
    else:raise AssertionError('private page captured')
    return dict(real_chromium=True,isolated_profile=True,unprivileged=True,device_scale_factor=1.5,canvas_click_confirmed=True,changed_target_rejected=True,private_page_blocked=True,model_grounded_clicks=checks,model_successes=checks,real_accounts_touched=False)
  finally:
   if browser:browser.detach()
   os.killpg(process.pid,signal.SIGTERM)
   try:process.wait(timeout=8)
   except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
   server.shutdown();server.server_close();thread.join(2)
