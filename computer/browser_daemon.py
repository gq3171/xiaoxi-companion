#!/usr/bin/env python3
"""Unprivileged Chromium lifetime; no CDP endpoint is published externally."""
import os
from runtime_config import settings, cdp_port, allowed_cdp_ports
from pathlib import Path
import signal
import subprocess
import time

from deployment_paths import browser_root, storage_ready
HOME=browser_root()

def main():
    if os.geteuid()==0 or not storage_ready():
        raise SystemExit('需要非root浏览器用户及配置的数据目录挂载')
    os.umask(0o077)
    for name in ('runtime','cache','profile','downloads','tmp'):(HOME/name).mkdir(exist_ok=True,mode=0o700)
    marker=HOME/'runtime/last-use';marker.touch()
    environment=os.environ.copy();environment.update(HOME=str(HOME),XDG_CACHE_HOME=str(HOME/'cache'),XDG_RUNTIME_DIR=str(HOME/'runtime'),TMPDIR=str(HOME/'tmp'))
    command=['/usr/bin/chromium','--headless=new','--no-first-run','--no-default-browser-check',
             '--disable-background-networking','--disable-component-update','--disable-sync',
             '--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(cdp_port()),
             '--user-data-dir='+str(HOME/'profile'),'--disk-cache-dir='+str(HOME/'cache'),
             '--window-size=1280,720','--mute-audio','about:blank']
    process=subprocess.Popen(command,env=environment,start_new_session=True)
    stopping=False;idle=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        while process.poll() is None and not stopping:
            if time.time()-marker.stat().st_mtime>settings()['desktop']['headless_idle_seconds']:idle=True;break
            time.sleep(1)
    finally:
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
    if process.returncode and not stopping and not idle:raise SystemExit(1)

if __name__=='__main__':main()
