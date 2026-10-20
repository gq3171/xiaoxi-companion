#!/usr/bin/env python3
"""Unprivileged Chromium lifetime; no CDP endpoint is published externally."""
import os
from pathlib import Path
import signal
import subprocess
import time

HOME=Path('/mnt/nvme/deskpet-browser')

def main():
    if os.geteuid()==0 or not os.path.ismount('/mnt/nvme'):
        raise SystemExit('需要非root浏览器用户及NVMe挂载')
    os.umask(0o077)
    for name in ('runtime','cache','profile','downloads','tmp'):(HOME/name).mkdir(exist_ok=True,mode=0o700)
    marker=HOME/'runtime/last-use';marker.touch()
    environment=os.environ.copy();environment.update(HOME=str(HOME),XDG_CACHE_HOME=str(HOME/'cache'),XDG_RUNTIME_DIR=str(HOME/'runtime'),TMPDIR=str(HOME/'tmp'))
    command=['/usr/bin/chromium','--headless=new','--no-first-run','--no-default-browser-check',
             '--disable-background-networking','--disable-component-update','--disable-sync',
             '--remote-debugging-address=127.0.0.1','--remote-debugging-port=19223',
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
            if time.time()-marker.stat().st_mtime>300:idle=True;break
            time.sleep(1)
    finally:
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
    if process.returncode and not stopping and not idle:raise SystemExit(1)

if __name__=='__main__':main()
