"""Regression cases for the six audited defects; no cloud or live desktop."""
import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler
import agent
from browser_tools import Browser
from desktop_browser import DesktopBrowser, BrowserBlocked, BrowserUnavailable
from http_tls_server import ThreadedTLSServer, bounded_request
from task_context import redact


class BudgetTests(unittest.TestCase):
    def test_connections_remain_bounded_after_handshake_and_release_after_finish(self):
        release=threading.Event();started=[]
        class Held(BaseHTTPRequestHandler):
            def handle(self):started.append(True);release.wait(3)
        class Limited(ThreadedTLSServer):connection_limit=4
        server=Limited(('127.0.0.1',0),Held);peers=[]
        try:
            for _ in range(12):
                a,b=socket.socketpair();peers.append(b);server.process_request(a,('127.0.0.1',1))
            deadline=time.monotonic()+1
            while len(started)<4 and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(len(started),4)
            self.assertFalse(server._connections.acquire(blocking=False))
            release.set()
            deadline=time.monotonic()+2;available=0
            while available<4 and time.monotonic()<deadline:
                available+=int(server._connections.acquire(timeout=.1))
            self.assertEqual(available,4)
            for _ in range(4):server._connections.release()
        finally:
            release.set()
            for s in peers:s.close()
            server.server_close()

    def test_saturated_web_and_stream_lanes_do_not_consume_rpc_lane(self):
        class Handler(BaseHTTPRequestHandler):
            _rpc_tokens=('t'*48,)
            def log_message(self,*a):pass
            @bounded_request
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'ok')
        class Limited(ThreadedTLSServer):lane_limits={'web':1,'rpc':1,'events':1,'desktop':1}
        server=Limited(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever);thread.start()
        def get(path,token=''):
            c=http.client.HTTPConnection(*server.server_address,timeout=2)
            c.request('GET',path,headers={'Authorization':'Bearer '+token});r=c.getresponse();result=r.status;r.read();c.close();return result
        try:
            with server.request_lane('web'),server.request_lane('events'),server.request_lane('desktop'):
                self.assertEqual(get('/home/'),503)
                self.assertEqual(get('/home/events'),503)
                self.assertEqual(get('/home/api/desktop/ws'),503)
                self.assertEqual(get('/v1/computer/health','bad'),503)
                self.assertEqual(get('/v1/computer/health','t'*48),200)
            self.assertEqual(get('/home/'),200)
        finally:server.shutdown();server.server_close();thread.join(2)


class TaskRepairs(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.store=agent.Store(Path(self.tmp.name)/'jobs.sqlite3')
    def tearDown(self):self.store.db.close();self.tmp.cleanup()
    def test_cancel_and_terminal_state_cannot_be_overwritten_by_late_result(self):
        job=self.store.submit('a'*32,'隔离任务');self.store.next();self.store.cancel(job['id'])
        self.store.update(job['id'],'succeeded','迟到成功')
        self.assertEqual(self.store.get(job['id'])['state'],'cancelled')
        self.store.update(job['id'],'running','迟到步骤');self.store.update(job['id'],'failed','迟到失败')
        self.assertEqual(self.store.get(job['id'])['state'],'cancelled')
        job=self.store.submit('b'*32,'已完成任务');self.store.update(job['id'],'succeeded','完成')
        self.store.update(job['id'],'running','旧回调');self.assertEqual(self.store.get(job['id'])['state'],'succeeded')

    def test_cancellation_before_spawn_never_runs_a_command(self):
        job=self.store.submit('a'*32,'隔离任务');self.store.next();self.store.cancel(job['id'])
        with patch('agent.subprocess.Popen') as spawn:
            result=agent.Worker(self.store).command(job['id'],'must not run')
        spawn.assert_not_called();self.assertEqual(result[0],130)

    def test_raw_old_output_is_not_sent_to_an_unrelated_new_task(self):
        self.store.record('a'*32,1,'check','synthetic',0,'UNRELATED_PRIVATE_SYNTHETIC_MARKER')
        job=self.store.submit('b'*32,'核对软件版本');seen=[]
        def model(messages):seen.extend(messages);return {'action':'finish','state':'failed','message':'夹具结束'}
        agent.Worker(self.store,model).run_job(self.store.next())
        self.assertNotIn('UNRELATED_PRIVATE_SYNTHETIC_MARKER',str(seen))
        self.assertEqual(self.store.lessons(),[])

    def test_only_relevant_checked_and_secret_free_methods_are_reused(self):
        job=self.store.submit('a'*32,'核对软件版本');self.store.next();self.store.record(job['id'],1,'check','version-check',0,'RAW_OUTPUT_NOT_A_METHOD');self.store.update(job['id'],'succeeded','完成')
        candidate={'name':'核对软件版本','when':'需要核对软件版本','method':'读取软件报告的版本号','check':'确认版本号与实际运行程序对应'}
        self.assertTrue(self.store.learn(job['id'],candidate))
        self.assertTrue(self.store.lessons('核对软件版本'));self.assertEqual(self.store.lessons('给花浇水'),[])
        self.assertNotIn('RAW_OUTPUT_NOT_A_METHOD',str(self.store.lessons('核对软件版本')))
        with patch.dict('os.environ',{'OTHER_API_TOKEN':'SYNTHETIC_TOKEN_abcdefghi'}):
            self.assertIsNone(self.store.learn(job['id'],candidate|{'method':'SYNTHETIC_TOKEN_abcdefghi'}))
            self.store.record(job['id'],2,'check','API_TOKEN=SYNTHETIC_TOKEN_abcdefghi',0,'password=secret-value123')
        raw=str([tuple(x) for x in self.store.db.execute('select command,output from steps')])
        self.assertNotIn('SYNTHETIC_TOKEN_abcdefghi',raw);self.assertNotIn('secret-value123',raw)


class ActivationGuardTests(unittest.TestCase):
    def test_guard_is_role_independent_and_handles_default_form_submit(self):
        for role in ('link','button','menuitem'):
            with self.subTest(role=role),self.assertRaises(BrowserBlocked):
                DesktopBrowser.guard_activation({'role':role,'submit':False},'继续',True,'click')
        for label in ('确认支付','接受服务条款','立即订阅','永久删除'):
            with self.subTest(label=label),self.assertRaises(BrowserBlocked):
                DesktopBrowser.guard_activation({'form':True},label,False,'Enter')
        DesktopBrowser.guard_activation({'role':'button'},'搜索',False,'click')

    def test_live_guard_runs_after_position_check_and_before_mouse_dispatch(self):
        class Page:
            def __init__(self):self.calls=[]
            def call(self,method,args):self.calls.append(method);return {}
        browser=object.__new__(DesktopBrowser);page=Page();browser.current='tab';browser.snapshots={'tab':{}}
        browser.element=lambda *a:(page,{'backend':1,'name':'旧的普通名称'})
        browser.action_point=lambda *a:(10,10)
        browser.activation_context=lambda *a:{'name':'确认支付','submit':False}
        browser.registration=lambda *a:False
        with self.assertRaises(BrowserBlocked):Browser.click(browser,'observed-ref')
        self.assertFalse(any(x.startswith('Input.dispatch') for x in page.calls))

    def test_enter_checks_live_focus_and_requires_fresh_observation(self):
        browser=object.__new__(DesktopBrowser);page=type('Page',(),{'evaluate':lambda *_:{'name':'搜索','form':True,'submit_names':['确认支付'],'scope':''}})()
        browser.current='tab';browser.snapshots={'tab':{'document':'doc'}};browser.document=lambda *_:'doc'
        browser.registration=lambda *_:False
        with self.assertRaises(BrowserBlocked):browser.before_activate(page,None,'Enter')
        browser.snapshots={}
        with self.assertRaises(BrowserUnavailable):browser.before_activate(page,None,'Enter')
