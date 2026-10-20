#!/usr/bin/env python3
"""Fixed native app entries; no RPC, shell interpolation or root privileges."""
import os,subprocess,sys,socket
from runtime_config import settings, cdp_port, allowed_cdp_ports
from pathlib import Path
from deployment_paths import desktop_root, storage_ready

def browser_args(root,url,port=None):
 root=Path(root);port=str(port or cdp_port())
 if int(port) not in allowed_cdp_ports():raise ValueError('unexpected private browser port')
 return ['/usr/bin/chromium','--ozone-platform=wayland','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-sync','--mute-audio','--remote-debugging-address=127.0.0.1','--remote-debugging-port='+port,'--user-data-dir='+str(root/'profile'),'--disk-cache-dir='+str(root/'cache'),'--window-size=1280,720','--start-maximized','--new-tab',url]

def browser_running(port):
 try:
  with socket.create_connection(('127.0.0.1',int(port)),timeout=.2):return True
 except OSError:return False

def foreground(action,env):
 app={'browser':'chromium','home':'chromium','files':'thunar'}.get(action)
 if app:
  try:subprocess.run(['/usr/bin/wlrctl','toplevel','focus','app_id:'+app],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=2,check=False)
  except (OSError,subprocess.TimeoutExpired):pass

def command(root,action):
 root=Path(root)
 if action=='terminal':return ['/usr/bin/foot','--app-id=xiaoxi-terminal','--title=小溪的终端','--working-directory='+str(root/'work'),'/bin/bash','--noprofile','--norc']
 if action=='files':return ['/usr/bin/thunar',str(root/'work')]
 if action in ('browser','home'):
  url=(root/'desk.html').as_uri() if action=='home' else 'about:blank'
  return browser_args(root,url)
 if action=='apps':return ['/usr/bin/wofi','--show','drun','--allow-images','--insensitive','--no-actions','--prompt','应用','--width','560','--height','420','--style',str(root/'config/wofi/deskpet.css'),'--term','/usr/bin/foot']
 raise ValueError('unknown desktop app')

def main():
 if os.geteuid()==0 or not storage_ready():raise SystemExit('unprivileged desktop and configured storage mount required')
 root=desktop_root()
 if len(sys.argv)!=2:raise SystemExit('one app entry required')
 argv=command(root,sys.argv[1]);env=os.environ.copy();env.update(HOME=str(root),XDG_CONFIG_HOME=str(root/'config'),XDG_CACHE_HOME=str(root/'cache'),XDG_DATA_HOME=str(root/'data'),XDG_STATE_HOME=str(root/'state'),TMPDIR=str(root/'tmp'),LANG='C.UTF-8')
 env.setdefault('TERM','xterm-256color');foreground(sys.argv[1],env);os.chdir(root/'work');os.execve(argv[0],argv,env)
if __name__=='__main__':main()
