"""Owner-requested lifecycle, empty-page proof, cancellation and loop regressions."""
import json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import agent
from browser_tools import BrowserUnavailable
from desktop_lifecycle import BrowserSession,authorize_shutdown
from desktop_executor import run_desktop
from desktop_jobs import broker
from task_progress import ProgressGuard
from test_desktop_executor import FakeBrowser
import test_home_chat as web

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=agent.Store(Path(self.tmp.name)/'state/jobs.sqlite3');self.id='e'*32
        self.original='把你那边电脑的浏览器关闭吧'
        self.store.submit(self.id,'关闭专用浏览器；不要继续注册',original_request=self.original);self.job=self.store.next();self.stop=threading.Event()
    def tearDown(self):self.stop.set();self.store.db.close();self.tmp.cleanup()
    def run_task(self,replies,session):
        def model(messages):return next(replies) if not callable(replies) else replies(messages)
        worker=SimpleNamespace(store=self.store,model=model,key='',stop=self.stop,active_job_id=None,cancelled=lambda job:self.stop.is_set() or self.store.get(job)['cancel'])
        with patch('desktop_executor.DesktopBrowser',FakeBrowser),patch('desktop_lifecycle.BrowserSession',return_value=session):run_desktop(worker,self.job)
    def test_complete_owner_quote_required_not_goal_or_negated_or_unrelated_text(self):
        authorize_shutdown(self.store,self.id,self.original)
        for value in ('关闭浏览器','关闭专用浏览器；不要继续注册','读取当前网页'):
            with self.assertRaises(ValueError):authorize_shutdown(self.store,self.id,value)
        for text in ('不要关闭浏览器','打开浏览器帮我注册','Do not close the browser'):
            with self.store.lock,self.store.db:
                self.store.db.execute('UPDATE task_dossiers SET value=? WHERE job=?',(json.dumps(dict(original_request=text,original_request_source='owner_submission',owner_decisions=[])),self.id))
            with self.assertRaises(ValueError):authorize_shutdown(self.store,self.id,text)
    def test_explicit_shutdown_gets_os_proof_and_finishes_without_opening_a_page(self):
        closed=dict(scope='desktop_browser',closed=True,passed=True,verification='desktop_browser_closed')
        session=SimpleNamespace(shutdown=lambda cancelled:closed)
        class NoPages(FakeBrowser):
            def restore(self,*a):raise AssertionError('page restoration must not be needed')
            def open(self,*a):raise AssertionError('shutdown must not open a page')
            def snapshot(self,*a):raise AssertionError('OS shutdown is not verified by page text')
        replies=iter([dict(action='browser_shutdown',authorization=self.original),dict(action='finish',state='succeeded',message='浏览器已关闭')])
        with patch('desktop_executor.DesktopBrowser',NoPages),patch('desktop_lifecycle.BrowserSession',return_value=session):
            worker=SimpleNamespace(store=self.store,model=lambda _:next(replies),key='',stop=self.stop,active_job_id=None,cancelled=lambda job:self.stop.is_set())
            run_desktop(worker,self.job)
        self.assertEqual(self.store.get(self.id)['state'],'succeeded');self.assertTrue(broker(self.store).load(self.id)['browser_session_closed'])
    def test_cannot_shutdown_without_owner_authorization(self):
        session=SimpleNamespace(shutdown=lambda *a: self.fail('unauthorized shutdown'))
        self.run_task(iter([dict(action='browser_shutdown',authorization='关闭浏览器')]),session)
        self.assertEqual(self.store.get(self.id)['state'],'interrupted')
    def test_wrong_tab_scope_is_known_not_dispatched_and_can_replan_shutdown(self):
        closed=dict(closed=True,passed=True,verification='desktop_browser_closed')
        session=SimpleNamespace(shutdown=lambda cancelled:closed)
        self.run_task(iter([dict(action='browser_close'),dict(action='browser_shutdown',authorization=self.original),dict(action='finish',state='succeeded')]),session)
        self.assertEqual(self.store.get(self.id)['state'],'succeeded')
        row=self.store.db.execute('SELECT output FROM steps WHERE ordinal=1').fetchone()
        self.assertFalse(json.loads(row[0])['dispatched']);self.assertFalse(broker(self.store).load(self.id)['uncertain'])
    def test_original_empty_tabs_and_page_error_cycle_is_bounded(self):
        calls=[]
        def model(messages):
            action='browser_snapshot' if len(calls)%2==0 else 'browser_tabs';calls.append(action);return dict(action=action)
        class Empty(FakeBrowser):
            def snapshot(self,*a):raise ValueError('先打开页面或选择本任务已有标签')
            def list_tabs(self):return []
        worker=SimpleNamespace(store=self.store,model=model,key='',stop=self.stop,active_job_id=None,cancelled=lambda job:False)
        with patch('desktop_executor.DesktopBrowser',Empty):run_desktop(worker,self.job)
        self.assertLessEqual(len(calls),9);self.assertEqual(self.store.get(self.id)['state'],'interrupted');self.assertIn('无效重试',self.store.get(self.id)['message'])
    def test_recovery_of_verified_closed_session_does_not_restore_or_restart_browser(self):
        state=broker(self.store);state.save(self.id,dict(messages=[dict(role='user',content='fixture')],browser=dict(tabs=['a'*32]),browser_session_closed=True))
        session=SimpleNamespace(status=lambda:dict(closed=True,passed=True,verification='desktop_browser_closed'))
        self.run_task(iter([dict(action='finish',state='succeeded',message='浏览器已关闭')]),session)
        self.assertEqual(self.store.get(self.id)['state'],'succeeded')
    def test_closed_session_is_not_proof_of_an_unknown_registration_click(self):
        state=broker(self.store);state.save(self.id,dict(messages=[dict(role='user',content='fixture')],browser=dict(tabs=[]),pending_effect=dict(action='browser_click',step=1,observed=False),uncertain=True))
        session=SimpleNamespace(status=lambda:dict(closed=True,passed=True,verification='desktop_browser_closed'))
        self.run_task(iter([dict(action='browser_session_status'),dict(action='finish',state='failed',message='unknown registration result')]),session)
        self.assertEqual(self.store.get(self.id)['state'],'interrupted');self.assertTrue(state.load(self.id)['uncertain'])
    def test_pending_shutdown_ack_can_be_recovered_passively_after_restart(self):
        state=broker(self.store);state.save(self.id,dict(messages=[dict(role='user',content='fixture')],browser=dict(tabs=['a'*32]),pending_effect=dict(action='browser_shutdown',step=1,observed=False),uncertain=True))
        session=SimpleNamespace(status=lambda:dict(closed=True,passed=True,verification='desktop_browser_closed'))
        self.run_task(iter([dict(action='finish',state='succeeded',message='恢复后确认已关闭')]),session)
        self.assertEqual(self.store.get(self.id)['state'],'succeeded');self.assertFalse(state.load(self.id)['uncertain'])
    def test_interrupted_task_can_be_cancelled_and_never_resumed(self):
        state=broker(self.store);state.save(self.id,dict(messages=[],browser=dict(tabs=[])),phase='interrupted');self.store.update(self.id,'interrupted','fixture')
        self.assertEqual(self.store.cancel(self.id)['state'],'cancelled');self.assertTrue(self.store.get(self.id)['cancel'])
        self.assertEqual(self.store.cancel(self.id)['state'],'cancelled')
        with self.assertRaises(ValueError):state.resume(self.id)
    def test_status_is_passive_and_requires_both_port_and_process_to_be_gone(self):
        session=BrowserSession()
        with patch.object(session,'_port_open',return_value=False),patch.object(session,'_profile_running',return_value=True):self.assertFalse(session.status()['closed'])
        with patch.object(session,'_port_open',return_value=True),patch.object(session,'_profile_running',return_value=False):self.assertFalse(session.status()['closed'])
        with patch.object(session,'_port_open',return_value=False),patch.object(session,'_profile_running',return_value=False):self.assertTrue(session.status()['closed'])
    def test_lost_close_ack_is_resolved_by_fresh_os_observation_without_replay(self):
        session=BrowserSession();opened=dict(closed=False);closed=dict(closed=True,passed=True)
        with patch.object(session,'status',side_effect=[opened,closed]),patch.object(session,'_port_open',return_value=True),patch('desktop_stop.close_browser',side_effect=OSError('lost acknowledgement')) as close:
            self.assertTrue(session.shutdown()['closed']);close.assert_called_once()
    def test_already_closed_does_not_send_close_or_start_browser(self):
        session=BrowserSession()
        with patch.object(session,'status',return_value=dict(closed=True)),patch('desktop_stop.close_browser') as close:
            self.assertTrue(session.shutdown()['already_closed']);close.assert_not_called()
    def test_cancel_during_connection_is_checked_before_actual_browser_close_send(self):
        import io,types,desktop_stop
        stopped=[False];sent=[]
        class Connection:
            def send(self,value):sent.append(value)
            def close(self):pass
        def connect(*a,**k):stopped[0]=True;return Connection()
        fake=types.SimpleNamespace(create_connection=connect)
        opener=types.SimpleNamespace(open=lambda *a,**k:io.BytesIO(json.dumps({'webSocketDebuggerUrl':'ws://127.0.0.1:19224/devtools/browser/test'}).encode()))
        with patch.object(desktop_stop,'build_opener',return_value=opener),patch.dict('sys.modules',websocket=fake):
            with self.assertRaises(InterruptedError):desktop_stop.close_browser(19224,cancelled=lambda:stopped[0])
        self.assertFalse(sent)
    def test_progress_guard_allows_real_mutations_but_stops_identical_empty_reads(self):
        guard=ProgressGuard()
        for _ in range(20):self.assertFalse(guard.stalled('browser_click',{'dispatched':True},0,mutation=True))
        for _ in range(3):self.assertFalse(guard.stalled('browser_tabs',{'tabs':[]},0))
        self.assertTrue(guard.stalled('browser_tabs',{'tabs':[]},0))

class WebCancellation(web.HomeChatTests):
    # Inherit only fixture support; normal discovery already runs parent tests.
    def test_focus_can_stop_interrupted_task_without_cancelling_an_unrelated_running_job(self):
        self.provider.responses=[dict(input='direct',remember=False,action='computer_task',task='fixture 注册',say='')];self.start('帮我注册演示账户');first=self.finished()['reply']['job_id']
        self.computer.update(first,'interrupted','service upgrade')
        other='d'*32;self.computer.submit(other,'unrelated fixture')
        self.provider.responses=[dict(input='direct',remember=False,action='computer_cancel',say='')];self.start('注册任务先停止吧');result=self.finished()['reply']
        self.assertEqual(result['job_id'],first);self.assertEqual(self.computer.get(first)['state'],'cancelled');self.assertEqual(self.computer.get(other)['state'],'queued')

# Avoid rerunning inherited parent test methods in the additional fixture class.
for _name in list(vars(web.HomeChatTests)):
    if _name.startswith('test_'):setattr(WebCancellation,_name,None)
