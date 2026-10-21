"""Opt-in Linux Chromium search failover, with an isolated HTTPS proxy fixture.

No external site, real desktop, account or private browser profile is accessed.
--model additionally calls only the configured provider; synthetic task data.
"""
import argparse,base64,ctypes,hashlib,html,json,os,pwd,shutil,socket,socketserver,ssl,subprocess,tempfile,threading,time,unittest
from pathlib import Path
from urllib.parse import parse_qs,urlsplit


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--work-root',type=Path,required=True);parser.add_argument('--browser-user');parser.add_argument('--port',type=int,default=19224);parser.add_argument('--model',action='store_true');parser.add_argument('--regression-source',type=Path);parser.add_argument('--report',type=Path,required=True);args=parser.parse_args();os.umask(0o077)
    if not 1024<=args.port<=65535:raise SystemExit('invalid fixture port')
    account=pwd.getpwnam(args.browser_user) if args.browser_user else pwd.getpwuid(os.geteuid())
    if account.pw_uid==0:raise SystemExit('select an unprivileged --browser-user')
    if os.geteuid()==0:assert ctypes.CDLL(None).prctl(38,1,0,0,0)==0
    os.environ['DESKPET_DESKTOP_CDP_PORT']=str(args.port)
    if args.regression_source:
        import sys
        if not (args.regression_source/'browser_tools.py').is_file():raise SystemExit('invalid regression source')
        sys.path.insert(0,str(args.regression_source))
    import agent
    from browser_tools import Browser,CDP,BrowserUnavailable,BrowserNotDispatched
    from desktop_browser import DesktopBrowser
    from browser_search import request
    from unittest.mock import patch
    root=Path(tempfile.mkdtemp(prefix='search-recovery-',dir=args.work_root));root.chmod(0o711)
    results=[];mode={'failed':{'google'}};reads=[];finish=threading.Event()
    key=root/'key.pem';cert=root/'cert.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=SearchFixture'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=15)
    public=subprocess.check_output(['openssl','x509','-in',str(cert),'-pubkey','-noout'])
    der=subprocess.run(['openssl','pkey','-pubin','-outform','DER'],input=public,capture_output=True,check=True).stdout
    pin=base64.b64encode(hashlib.sha256(der).digest()).decode();tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key)
    hosts={'www.google.com':'google','cn.bing.com':'bing','www.bing.com':'bing','www.baidu.com':'baidu'}
    class Proxy(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(5)
            try:
                line=self.rfile.readline(8192).decode('ascii','ignore').split()
                if len(line)!=3 or line[0]!='CONNECT':return
                host=line[1].split(':')[0]
                while self.rfile.readline(8192) not in (b'\r\n',b'\n',b''):pass
                if host not in hosts:self.wfile.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n');return
                self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n');self.wfile.flush()
                with tls.wrap_socket(self.connection,server_side=True) as stream:
                    source=stream.makefile('rb');first=source.readline(8192).decode('utf8','replace').split()
                    if len(first)!=3:return
                    while source.readline(8192) not in (b'\r\n',b'\n',b''):pass
                    engine=hosts[host];reads.append(engine)
                    if engine in mode['failed']:
                        # No HTTP status, headers or document ever arrives.
                        finish.wait(120);return
                    q=parse_qs(urlsplit(first[1]).query);query=(q.get('q') or q.get('wd') or [''])[0]
                    body=('<!doctype html><meta charset="utf-8"><title>'+engine+' fixture results</title><main><h1>Search results</h1><p>source='+engine+' recovered=42</p><p>query='+html.escape(query)+'</p></main>').encode()
                    stream.sendall(('HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: '+str(len(body))+'\r\nConnection: close\r\n\r\n').encode()+body)
            except (OSError,ssl.SSLError):pass
    class Server(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True
    proxy=Server(('127.0.0.1',0),Proxy);threading.Thread(target=proxy.serve_forever,daemon=True).start()
    profile=root/'profile';profile.mkdir(mode=0o700);os.chown(profile,account.pw_uid,account.pw_gid)
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',args.port))!=0,'fixture CDP port is busy'
    argv=[shutil.which('chromium') or 'chromium','--headless=new','--no-sandbox','--disable-gpu','--no-first-run','--disable-background-networking','--disable-quic','--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(args.port),'--user-data-dir='+str(profile),'--proxy-server=http://127.0.0.1:'+str(proxy.server_address[1]),'--ignore-certificate-errors-spki-list='+pin,'about:blank']
    process=subprocess.Popen(argv,user=account.pw_uid if os.geteuid()==0 else None,group=account.pw_gid if os.geteuid()==0 else None,extra_groups=[] if os.geteuid()==0 else None,env=dict(PATH='/usr/bin:/bin',HOME=str(profile),LANG='C.UTF-8'),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    class Probe(DesktopBrowser):
        def __init__(self,*a,**kw):super().__init__(*a,**kw);self.desktop=type('Heartbeat',(),{'heartbeat':lambda s:None})()
        def heartbeat(self):pass
        def ensure(self):
            if not self.ready:self.control=CDP(self.json_request('/json/version')['webSocketDebuggerUrl'],self.cancelled);self.ready=True
        def open(self,url,tab=None):
            if not request(url):raise BrowserNotDispatched('this fixture only permits recognized public search URLs')
            return super().open(url,tab) if tab else super().open(url)
        def detach(self):self.close();super().detach()
    start=time.monotonic()
    try:
        while True:
            try:
                with socket.create_connection(('127.0.0.1',args.port),.2):break
            except OSError:
                if process.poll() is not None or time.monotonic()-start>15:raise RuntimeError('isolated browser did not start')
                time.sleep(.1)
        class Integration(unittest.TestCase):
            def setUp(self):
                self.folder=root/str(time.time_ns());self.folder.mkdir(mode=0o711);self.store=agent.Store(self.folder/'state/jobs.sqlite3');self.job='a'*32;self.store.submit(self.job,'查询风字诗句',original_request='查询风字诗句');self.b=Probe(self.store,self.job,self.folder);mode['failed']={'google'}
            def tearDown(self):self.b.detach();self.store.db.close()
            def fail_search(self,url):
                began=time.monotonic()
                with self.assertRaises(BrowserUnavailable) as caught:self.b.open(url)
                result=getattr(caught.exception,'result',{})
                self.assertTrue(result.get('search_navigation_reconciled'),str(caught.exception));self.assertFalse(result['verification']);self.assertFalse(self.b.tabs)
                self.assertLess(time.monotonic()-began,15)
                return result
            def observe(self):
                end=time.monotonic()+5
                while True:
                    v=self.b.snapshot()
                    if 'recovered=42' in v.get('text',''):return v
                    if time.monotonic()>end:self.fail('fixture results not readable')
                    time.sleep(.1)
            def test_hanging_google_is_closed_then_bing_is_readable(self):
                result=self.fail_search('https://www.google.com/search?q='+__import__('urllib.parse',fromlist=['quote']).quote('风+诗'))
                next_page=result['alternatives'][0];self.assertEqual(next_page['engine'],'bing');self.b.open(next_page['url']);self.assertIn('query=风+诗',self.observe()['text'])
                self.assertTrue(self.b.check('source=bing recovered=42')['passed'])
            def test_search_homepage_also_has_a_bounded_fallback(self):
                result=self.fail_search('https://www.google.com/')
                self.assertEqual(result['query'],'');self.b.open(result['alternatives'][0]['url']);self.assertIn('source=bing',self.observe()['text'])
            def test_two_unreachable_engines_switch_to_baidu_without_repeating_google(self):
                mode['failed']={'google','bing'};first=self.fail_search('https://www.google.com/search?q=fixture');second=self.fail_search(first['alternatives'][0]['url'])
                self.assertEqual([x['engine'] for x in second['alternatives']],['baidu']);self.b.open(second['alternatives'][0]['url']);self.assertIn('source=baidu',self.observe()['text'])
            def test_all_unreachable_engines_exhaust_candidates_in_bounded_time(self):
                mode['failed']={'google','bing','baidu'};url='https://www.google.com/search?q=fixture';begin=time.monotonic()
                for _ in range(3):
                    result=self.fail_search(url)
                    if result['alternatives']:url=result['alternatives'][0]['url']
                self.assertEqual(result['alternatives'],[]);self.assertLess(time.monotonic()-begin,42)
            def test_unresolved_search_checkpoint_can_be_reconciled_after_restore(self):
                self.b.ensure();info=self.b.json_request('/json/new?about:blank','PUT');tab=info['id'];self.b.tabs[tab]=CDP(info['webSocketDebuggerUrl']);self.b.owned_targets.add(tab);self.b.current=tab
                url='https://www.google.com/search?q=fixture';self.b.requested_urls[tab]=url;self.assertEqual(self.b.arm_search_recovery(),url)
                # Begin a real loading attempt without waiting for its reply,
                # matching a retained Page.navigate from the previous process.
                page=self.b.tabs[tab];page.serial+=1;page.ws.send(json.dumps(dict(id=page.serial,method='Page.navigate',params=dict(url=url))))
                saved=self.b.checkpoint();DesktopBrowser.detach(self.b)
                self.b=Probe(self.store,self.job,self.folder);self.b.restore_search(saved);self.b.arm_search_recovery()
                with self.assertRaises(BrowserUnavailable) as caught:self.b.snapshot()
                self.assertTrue(getattr(caught.exception,'result',{}).get('search_navigation_reconciled'));self.assertFalse(self.b.tabs)
        suite=unittest.TestSuite([Integration('test_hanging_google_is_closed_then_bing_is_readable')]) if args.regression_source else unittest.defaultTestLoader.loadTestsFromTestCase(Integration)
        test=unittest.TextTestRunner(verbosity=2).run(suite);results.append(dict(kind='chromium',tests=test.testsRun,passed=test.wasSuccessful()))
        if args.model and test.wasSuccessful():
            for number,failed in enumerate(({'google'},{'google','bing'},{'google','bing','baidu'}),1):
                mode['failed']=failed;folder=root/('model-'+str(number));folder.mkdir(mode=0o711);store=agent.Store(folder/'state/jobs.sqlite3');job=str(number)*32
                goal='用浏览器先打开 https://www.google.com/search?q=fixture 搜索本地演示资料。如果这个搜索引擎不可达，保留搜索词，自己选择别的搜索引擎继续，不要一直等待。可达时核对实际页面的recovered=42，并告诉我最终读到了哪个来源。如果所有引擎都不可达，请说明未查到并结束失败，不要宣称资料已核验。不要执行shell或填写任何表单。'
                store.submit(job,goal,original_request=goal);worker=agent.Worker(store);error=[];error_locations=[];finished=threading.Event()
                def run():
                    try:
                        with patch('desktop_executor.DesktopBrowser',Probe):worker.run_job(store.next())
                    except Exception as exc:
                        import traceback
                        error.append(type(exc).__name__);error_locations.extend(dict(file=Path(frame.filename).name,function=frame.name,line=frame.lineno) for frame in traceback.extract_tb(exc.__traceback__))
                    finally:finished.set()
                began=time.monotonic();thread=threading.Thread(target=run,daemon=True);thread.start()
                while not finished.wait(.2):
                    if time.monotonic()-began>240:worker.stop.set();break
                thread.join(30);state=store.get(job);steps=[dict(v) for v in store.db.execute('SELECT ordinal,kind,command,exit_code,output FROM steps ORDER BY ordinal')]
                destinations=[request(json.loads(v['command']).get('url')) for v in steps if v['kind']=='browser_open']
                expected='bing' if number==1 else 'baidu' if number==2 else None;audit=store.tasks.snapshot(job).get('completion_audit',{})
                passed=state['state']=='succeeded' and not error and audit.get('passed') and destinations and destinations[0]['engine']=='google' and any(x and x['engine']==expected for x in destinations) and '42' in state['message']
                if number==3:passed=state['state']=='failed' and not error and {x['engine'] for x in destinations if x}=={'google','bing','baidu'} and time.monotonic()-began<180
                result=dict(kind='model',failed_engines=sorted(failed),passed=bool(passed),state=state['state'],seconds=round(time.monotonic()-began,2),expected_source=expected,error=error,error_locations=error_locations,message=state['message'],completion_audit=audit,steps=steps)
                results.append(result);args.report.write_text(json.dumps(dict(results=results,owner_pages_touched=False,external_sites_accessed=False,synthetic_data_only=True),ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ('steps','completion_audit')}),flush=True);store.db.close()
        args.report.write_text(json.dumps(dict(results=results,owner_pages_touched=False,external_sites_accessed=False,synthetic_data_only=True),ensure_ascii=False,indent=2)+'\n')
        if not all(x['passed'] for x in results):raise SystemExit(1)
    finally:
        finish.set()
        if process.poll() is None:process.terminate();process.wait(timeout=10)
        proxy.shutdown();proxy.server_close();shutil.rmtree(root)

if __name__=='__main__':main()
