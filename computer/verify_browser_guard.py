"""Isolated real-Chromium guard proof. NVMe profile, separate CDP, local pages only."""
import json
import os
from pathlib import Path
from deployment_paths import desktop_root
import pwd
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import browser_tools
import desktop_browser


def main():
    import websocket
    account=pwd.getpwnam('deskpet-desktop')
    with tempfile.TemporaryDirectory(prefix='guard-proof-',dir=desktop_root()) as tmp:
        root=Path(tmp);os.chown(root,account.pw_uid,account.pw_gid);root.chmod(0o700)
        pages={
            '/register.html':'<h1>注册演示</h1><form><input aria-label="昵称"><a href="#" onclick="window.submissions++">继续</a></form>',
            '/pay.html':'<h1>支付演示</h1><form onsubmit="event.preventDefault();window.submissions++"><input aria-label="姓名"><button type="submit">确认支付</button></form>',
            '/normal.html':'<h1>普通查询</h1><form onsubmit="event.preventDefault();window.submissions++"><input aria-label="查询内容"><button type="submit">查询</button></form>'}
        class PageHandler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_GET(self):
                raw=('<!doctype html><meta charset="utf-8"><script>window.submissions=0</script>'+pages.get(self.path,'')).encode()
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),PageHandler);thread=threading.Thread(target=server.serve_forever);thread.start()
        log=(root/'chromium.log').open('wb')
        child=subprocess.Popen(['runuser','-u','deskpet-desktop','--','/usr/bin/chromium','--headless=new','--remote-debugging-address=127.0.0.1','--remote-debugging-port=19442','--user-data-dir='+str(root/'profile'),'--disk-cache-dir='+str(root/'cache'),'--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run','--disable-extensions','about:blank'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        class FixtureCDP(browser_tools.CDP):
            def __init__(self,url,cancelled=lambda:False):
                assert url.startswith('ws://127.0.0.1:19442/')
                self.ws=websocket.create_connection(url,timeout=.5,suppress_origin=True,http_proxy_host=None,http_no_proxy=['127.0.0.1']);self.serial=0;self.cancelled=cancelled
        b=object.__new__(desktop_browser.DesktopBrowser);browser_tools.Browser.__init__(b,'a'*32,root/'work');b.heartbeat=lambda:None
        try:
            with patch.object(browser_tools,'ENDPOINT','http://127.0.0.1:19442'),patch.object(browser_tools,'CDP',FixtureCDP):
                deadline=time.monotonic()+20
                while True:
                    try:info=b.json_request('/json/version');break
                    except OSError:
                        if time.monotonic()>deadline:raise
                        time.sleep(.1)
                b.control=FixtureCDP(info['webSocketDebuggerUrl']);b.ready=True;b.ensure=lambda:None
                results={}
                for route,blocked in [('/register.html',True),('/pay.html',True),('/normal.html',False)]:
                    b.open('http://127.0.0.1:'+str(server.server_port)+route)
                    deadline=time.monotonic()+5
                    while True:
                        view=b.snapshot()
                        if view['elements']:break
                        if time.monotonic()>deadline:raise RuntimeError('fixture page did not load')
                        time.sleep(.05)
                    rejected=False
                    try:
                        if route.startswith('/register'):
                            b.click(next(x['ref'] for x in view['elements'] if x['name']=='继续'))
                        else:
                            b.type(next(x['ref'] for x in view['elements'] if x['role']=='textbox'),'演示输入');b.snapshot();b.key('Enter')
                    except browser_tools.BrowserBlocked:rejected=True
                    count=b.page().evaluate('window.submissions')
                    assert rejected==blocked,(route,rejected)
                    assert count==(0 if blocked else 1),(route,count)
                    results[route]={'blocked':rejected,'submissions':count}
                    b.close_tab()
                print(json.dumps({'real_chromium':True,'isolated_cdp':19442,'public_pages_visited':False,'results':results},ensure_ascii=False))
        finally:
            with patch.object(browser_tools,'ENDPOINT','http://127.0.0.1:19442'):b.close()
            server.shutdown();server.server_close();thread.join(2)
            try:os.killpg(child.pid,15)
            except ProcessLookupError:pass
            try:child.wait(5)
            except subprocess.TimeoutExpired:os.killpg(child.pid,9);child.wait(5)
            log.close()

if __name__=='__main__':main()
