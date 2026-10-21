"""Search fallback never grants permission to replay private/unknown effects."""
from contextlib import contextmanager,nullcontext
import itertools,json,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from browser_search import request,alternatives
from browser_tools import Browser,CDP,BrowserTimedOut,BrowserSearchFailed,BrowserCancelled,BrowserUnavailable
from desktop_executor import run_desktop
from desktop_jobs import broker,DesktopBusy
from runtime_config import validate
from test_desktop_executor import FakeBrowser
import agent

GOOGLE='https://www.google.com/search?q=%E9%A3%8E+%E8%AF%97'
BING='https://cn.bing.com/search?q=%E9%A3%8E+%E8%AF%97'

def receipt(url=GOOGLE):
    return dict(error='search unavailable',search_failed=True,search_url=url,closed_tab='b'*32,search_navigation_reconciled=True,verification=False,alternatives=[dict(engine='bing',url=BING)])

class PolicyTests(unittest.TestCase):
    def test_known_queries_preserve_chinese_and_symbols_across_engines(self):
        s=request('https://www.google.com/search?q=%E9%A3%8E%20%2B%20%26%20%22%E8%AF%97%22')
        result=alternatives(s,{})
        self.assertEqual([v['engine'] for v in result],['bing','baidu'])
        for value in result:self.assertEqual(next(iter(parse_qs(urlsplit(value['url']).query).values()))[0],s['query'])
    def test_search_homepage_failure_can_suggest_another_entry_without_inventing_a_query(self):
        value=request('https://www.google.com/');self.assertEqual(value['query'],'')
        self.assertEqual([v['url'] for v in alternatives(value,{})],['https://cn.bing.com/','https://www.baidu.com/'])
        self.assertIsNone(request('https://www.google.com/?authuser=0'))
    def test_accounts_forms_redirects_credentials_and_lookalikes_are_not_searches(self):
        for url in ('https://accounts.google.com/signin','https://www.google.com/search?q=x&token=secret','https://www.google.com/url?q=x','http://www.google.com/search?q=x','https://user:pw@www.google.com/search?q=x','https://www.google.com.evil.invalid/search?q=x','https://www.google.com:bad/search?q=x','https://www.google.com/search?q=x&q=y','https://www.baidu.com/s?wd='):
            self.assertIsNone(request(url),url)
    def test_failed_engines_are_skipped_but_recover_after_cooldown(self):
        self.assertEqual([x['engine'] for x in alternatives(request(GOOGLE),{'bing':990},now=1000)],['baidu'])
        self.assertEqual(len(alternatives(request(GOOGLE),{'bing':800},now=1000)),2)
    def test_source_only_request_does_not_recommend_other_engines(self):
        self.assertEqual(alternatives(request(GOOGLE),{},'只用 Google 查询'),[])
        self.assertEqual(len(alternatives(request(GOOGLE),{},'Google 不通时换别的')),2)
    def test_engine_order_and_time_budget_are_validated_and_configurable(self):
        value=validate({'desktop':{'search_engines':['baidu','bing'],'search_timeout_seconds':3}})
        with patch('browser_search.settings',return_value=value):self.assertEqual([x['engine'] for x in alternatives(request(GOOGLE),{})],['baidu','bing'])
        for value in (['unknown'],['bing','bing'],[],['google',3]):
            with self.assertRaises(ValueError):validate({'desktop':{'search_engines':value}})
        for value in (True,0,21):
            with self.assertRaises(ValueError):validate({'desktop':{'search_timeout_seconds':value}})

class EvidenceTests(unittest.TestCase):
    def test_failed_search_keeps_source_for_review_without_becoming_success(self):
        from task_runtime import evidence,judge_refs
        with tempfile.TemporaryDirectory() as tmp:
            store=agent.Store(Path(tmp)/'state/jobs.sqlite3');job='a'*32
            try:
                store.submit(job,'search');store.next();value=receipt()|dict(search_engine='google')
                store.record(job,1,'browser_open','{}',1,json.dumps(value));store.tasks.outcome(job,1,'browser_open',1,json.dumps(value))
                output=json.loads(evidence(store,job)[0]['output'])
                self.assertEqual(output['search_engine'],'google');self.assertEqual(output['requested_search_url'],GOOGLE);self.assertFalse(judge_refs(store,job,[1],0))
            finally:store.db.close()

    def test_only_current_verified_native_status_can_substantiate_a_failed_search(self):
        from task_runtime import judge_refs,valid_refs
        with tempfile.TemporaryDirectory() as tmp:
            store=agent.Store(Path(tmp)/'state/jobs.sqlite3');job='a'*32
            try:
                store.submit(job,'search');store.next();raw=json.dumps(receipt());store.record(job,1,'browser_open','{}',1,raw);store.tasks.outcome(job,1,'browser_open',1,raw)
                value=dict(proof='search_connection_unavailable',related_step=1,search_failed=True,search_url=GOOGLE,search_navigation_reconciled=True,information_verified=False)
                raw=json.dumps(value);store.record(job,2,'browser_search_status','native observation',0,raw);store.tasks.outcome(job,2,'browser_search_status',0,raw,verified=True)
                self.assertTrue(judge_refs(store,job,[1],0));self.assertFalse(valid_refs(store,job,[1],0,True));self.assertFalse(judge_refs(store,job,[1],1))
                with store.db:store.db.execute("UPDATE task_events SET verified=0 WHERE action='browser_search_status'")
                self.assertFalse(judge_refs(store,job,[1],0))
                with store.db:store.db.execute("UPDATE task_events SET verified=1 WHERE action='browser_search_status'");store.db.execute('UPDATE steps SET output=? WHERE ordinal=2',(json.dumps(value|dict(search_url=BING)),))
                self.assertFalse(judge_refs(store,job,[1],0))
            finally:store.db.close()

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.b=Browser('a'*32,Path(self.tmp.name));self.b.ensure=lambda:None;self.b.heartbeat=lambda:None;self.closed=set();self.commands=[]
        def control(method,params=None):
            if method=='Target.closeTarget':self.closed.add(params['targetId']);return dict(success=True)
            return dict(targetInfos=[dict(targetId=t) for t in self.b.tabs if t not in self.closed])
        self.b.control=SimpleNamespace(call=control)
        self.b.json_request=lambda *a,**kw:dict(id='b'*32,webSocketDebuggerUrl='ws://fixture.invalid')
        class Page:
            def call(inner,method,params=None):
                self.commands.append(method)
                if method=='Page.navigate':raise BrowserTimedOut('synthetic hanging navigation')
                return {}
            def close(inner):pass
        self.page=Page()
    def tearDown(self):self.tmp.cleanup()
    def test_timed_out_search_is_confirmed_closed_before_suggesting_an_alternative(self):
        with patch('browser_tools.CDP',return_value=self.page),self.assertRaises(BrowserSearchFailed) as error:self.b.open(GOOGLE)
        self.assertTrue(error.exception.result['search_navigation_reconciled']);self.assertFalse(error.exception.result['verification']);self.assertNotIn('b'*32,self.b.tabs)
        self.assertEqual([v['engine'] for v in error.exception.result['alternatives']],['bing','baidu'])
        count=len(self.commands)
        with self.assertRaises(BrowserSearchFailed):self.b.open(GOOGLE)
        self.assertEqual(len(self.commands),count)
    def test_unconfirmed_close_cannot_clear_the_unknown_navigation(self):
        self.b.control.call=lambda *a,**kw:dict(targetInfos=[dict(targetId='b'*32)])
        with patch('browser_tools.CDP',return_value=self.page),patch('browser_tools.time.monotonic',side_effect=itertools.count(0,4)):
            with self.assertRaises(BrowserUnavailable) as error:self.b.open(GOOGLE)
        self.assertNotIsInstance(error.exception,BrowserSearchFailed);self.assertIn('b'*32,self.b.tabs)
    def test_non_search_and_privacy_tainted_search_keep_unknown_effect_protection(self):
        for url,tainted in (('https://example.invalid/form',False),(GOOGLE,True)):
            self.b._privacy_tainted=tainted
            with patch('browser_tools.CDP',return_value=self.page),self.assertRaises(BrowserTimedOut):self.b.open(url)
            self.assertIn('b'*32,self.b.tabs);self.assertFalse(self.closed)
    def test_snapshot_timeout_can_abandon_only_an_armed_public_search(self):
        self.b.tabs['b'*32]=self.page;self.b.current='b'*32;self.b.requested_urls[self.b.current]=GOOGLE
        self.assertEqual(self.b.arm_search_recovery(),GOOGLE)
        with patch.object(self.b,'_snapshot',side_effect=BrowserTimedOut('pending document')),self.assertRaises(BrowserSearchFailed):self.b.snapshot()
        self.assertFalse(self.b.tabs)
    def test_unknown_click_and_private_data_cannot_arm_search_recovery(self):
        self.b.current='b'*32;self.b.requested_urls[self.b.current]=GOOGLE;self.b.search_guard=lambda:False
        self.assertIsNone(self.b.arm_search_recovery());self.assertFalse(self.b.search_loading)
        self.b.search_guard=lambda:True;self.b._private_values=[bytearray(b'synthetic')];self.assertIsNone(self.b.arm_search_recovery())
    def test_cancelled_task_does_not_close_or_navigate(self):
        self.b.cancelled=lambda:True
        with self.assertRaises(BrowserCancelled):self.b.search_failure(request(GOOGLE),'b'*32)
        self.assertFalse(self.closed)
    def test_recovery_defers_page_enable_until_the_bounded_observation(self):
        from desktop_browser import DesktopBrowser
        b=object.__new__(DesktopBrowser);Browser.__init__(b,'a'*32,Path(self.tmp.name));b.ensure=lambda:None
        b.json_request=lambda *_:[dict(id='b'*32,webSocketDebuggerUrl='ws://fixture.invalid')]
        calls=[];page=SimpleNamespace(call=lambda *a:calls.append(a))
        saved=dict(tabs=['b'*32],current='b'*32,owned=['b'*32],privacy_tainted=False,navigation=dict(requested={'b'*32:GOOGLE}))
        with patch('desktop_browser.CDP',return_value=page):b.restore_search(saved)
        self.assertFalse(calls);self.assertIn('b'*32,b.search_loading)
    def test_failed_engine_cooldown_survives_a_checkpoint_with_no_remaining_tabs(self):
        from desktop_browser import DesktopBrowser
        b=object.__new__(DesktopBrowser);Browser.__init__(b,'a'*32,Path(self.tmp.name));b.ensure=lambda:self.fail('empty checkpoint must not launch a browser')
        b.restore(dict(tabs=[],navigation=dict(engines={'google':123},failed={'www.google.com':123})))
        self.assertEqual(b.failed_engines,{'google':123});self.assertEqual(b.failed_origins,{'www.google.com':123})
    def test_cdp_budget_bounds_a_hung_reply_without_resending(self):
        class WaitTimeout(Exception):pass
        websocket=SimpleNamespace(WebSocketTimeoutException=WaitTimeout)
        sends=[];cdp=object.__new__(CDP);cdp.cancelled=lambda:False;cdp.serial=0;cdp._deadline=None
        cdp.ws=SimpleNamespace(send=lambda value:sends.append(value),recv=lambda:(_ for _ in ()).throw(websocket.WebSocketTimeoutException()))
        begin=time.monotonic()
        with self.assertRaises(BrowserTimedOut):
            with patch.dict('sys.modules',websocket=websocket),cdp.budget(.01):cdp.call('Page.navigate',dict(url=GOOGLE))
        self.assertLess(time.monotonic()-begin,.3);self.assertEqual(len(sends),1);self.assertIsNone(cdp._deadline)

class ExecutorTests(unittest.TestCase):
    def fixture(self,replies,saved=False,busy=False):
        tmp=tempfile.TemporaryDirectory();store=agent.Store(Path(tmp.name)/'state/jobs.sqlite3');job='a'*32;store.submit(job,'用浏览器查询诗句出处',original_request='用浏览器查询诗句出处');active=store.next();stop=threading.Event();seen=[]
        class Search(FakeBrowser):
            def open(self,url,tab=None):
                if url==GOOGLE:raise BrowserSearchFailed(receipt())
                self.registered=True;return super().open(url)
            def arm_search_recovery(self):return GOOGLE
            def snapshot(self,tab=None):
                if not self.registered:raise BrowserSearchFailed(receipt())
                return super().snapshot(tab)
        if saved:broker(store).save(job,dict(messages=[dict(role='user',content='original')],browser=dict(tabs=['b'*32],current='b'*32),pending_effect=dict(step=1,action='browser_open',observed=False),uncertain=True))
        @contextmanager
        def busy_action(*args,**kwargs):raise DesktopBusy('synthetic owner takeover');yield
        iterator=iter(replies)
        def model(messages):seen.append(json.dumps(messages,ensure_ascii=False));return next(iterator)
        worker=SimpleNamespace(store=store,model=model,key='',stop=stop,active_job_id=None,cancelled=lambda _:stop.is_set())
        try:
            with patch('desktop_executor.DesktopBrowser',Search),patch.object(broker(store),'action',busy_action) if busy else nullcontext():run_desktop(worker,active)
            return store.get(job)['state'],seen,broker(store).load(job)
        finally:stop.set();store.db.close();tmp.cleanup()
    def test_model_can_switch_engine_after_native_failure_without_fake_success(self):
        state,seen,saved=self.fixture([dict(action='browser_open',url=GOOGLE),dict(action='finish',state='succeeded'),dict(action='browser_open',url=BING),dict(action='browser_check',expected='注册演示已完成'),dict(action='finish',state='succeeded')])
        self.assertEqual(state,'succeeded');self.assertTrue(any('尚未通过' in x for x in seen));self.assertFalse(saved['uncertain'])
    def test_saved_unknown_search_open_is_reconciled_then_same_task_can_continue(self):
        state,seen,saved=self.fixture([dict(action='browser_open',url=BING),dict(action='browser_check',expected='注册演示已完成'),dict(action='finish',state='succeeded')],saved=True)
        self.assertEqual(state,'succeeded');self.assertTrue(any('search_navigation_reconciled' in x for x in seen));self.assertIsNone(saved['pending_effect'])
    def test_all_sources_unavailable_can_fail_honestly_instead_of_stalling(self):
        state,seen,saved=self.fixture([dict(action='browser_open',url=GOOGLE),dict(action='finish',state='failed',message='允许的引擎暂不可达')]);self.assertEqual(state,'failed');self.assertIsNone(saved['pending_effect'])

    def test_owner_takeover_during_recovery_leaves_a_resumable_job_not_orphaned_running(self):
        state,seen,saved=self.fixture([],saved=True,busy=True)
        self.assertEqual(state,'interrupted');self.assertFalse(seen);self.assertTrue(saved['uncertain']);self.assertEqual(saved['pending_effect']['action'],'browser_open')
