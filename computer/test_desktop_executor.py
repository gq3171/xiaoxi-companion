import json,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import agent
from browser_tools import BrowserBlocked
from desktop_jobs import broker
from desktop_executor import run_desktop

class FakeBrowser:
 instances=[]
 def __init__(self,*args):self.tabs={};self.current=None;self.snapshots={};self.registered=False;self.clicks=0;self.desktop=SimpleNamespace(heartbeat=lambda:None);self.instances.append(self)
 def heartbeat(self):pass
 def detach(self):pass
 def checkpoint(self):return dict(tabs=list(self.tabs),current=self.current)
 def restore(self,state):self.tabs={x:None for x in state.get('tabs',[])};self.current=state.get('current')
 def open(self,url):self.tabs['b'*32]=None;self.current='b'*32;return dict(tab=self.current)
 def snapshot(self,tab=None):return dict(text='注册演示已完成' if self.registered else '演示昵称 演示密码',elements=[],needs_human=False)
 def type(self,*args):raise BrowserBlocked('请在桌面完成密码和验证。')
 def click(self,*args):self.clicks+=1;return dict(dispatched=True)
 def check(self,*args):return dict(passed=self.registered)

class ExecutorTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=agent.Store(Path(self.tmp.name)/'state/jobs.sqlite3');self.id='a'*32;self.store.submit(self.id,'测试模拟注册，不创建真实账户');self.job=self.store.next();self.stop=threading.Event();FakeBrowser.instances=[]
 def tearDown(self):self.stop.set();self.store.db.close();self.tmp.cleanup()
 def worker(self,model):
  return SimpleNamespace(store=self.store,model=model,key='',stop=self.stop,active_job_id=None,cancelled=lambda job:self.stop.is_set() or bool(self.store.get(job)['cancel']))
 def wait(self,predicate):
  end=time.monotonic()+3
  while time.monotonic()<end:
   if predicate():return
   time.sleep(.01)
  self.fail('desktop workflow did not reach the expected phase')
 def test_protected_candidate_is_not_recorded_and_handback_continues_same_job(self):
  replies=iter([dict(action='browser_open',url='https://example.invalid/'),dict(action='browser_snapshot'),dict(action='browser_type',ref='secret-field',text='NEVER_PERSIST_CREDENTIAL'),dict(action='browser_check',expected='注册演示已完成'),dict(action='finish',state='succeeded',message='演示流程已核对完成')])
  worker=self.worker(lambda messages:next(replies))
  with patch('desktop_executor.DesktopBrowser',FakeBrowser):
   thread=threading.Thread(target=run_desktop,args=(worker,self.job));thread.start()
   try:
    state=broker(self.store);self.wait(lambda:state.state()['phase']=='waiting_user');state.take('owner');FakeBrowser.instances[0].registered=True;state.give_back('owner');thread.join(3);self.assertFalse(thread.is_alive());self.assertEqual(self.store.get(self.id)['state'],'succeeded')
    with self.store.lock:
     raw=' '.join(str(tuple(r)) for r in self.store.db.execute('SELECT command,output FROM steps'));raw+=self.store.db.execute('SELECT checkpoint FROM desktop_jobs').fetchone()[0]
    self.assertNotIn('NEVER_PERSIST_CREDENTIAL',raw)
   finally:self.stop.set();thread.join(2)
 def test_model_reply_arriving_after_takeover_is_discarded(self):
  started=threading.Event();release=threading.Event();calls=0
  def model(messages):
   nonlocal calls
   calls+=1
   if calls==1:return dict(action='browser_open',url='https://example.invalid/')
   if calls==2:started.set();release.wait(3);return dict(action='browser_click',ref='old-ref')
   if calls==3:return dict(action='browser_check',expected='注册演示已完成')
   return dict(action='finish',state='succeeded',message='已核对')
  worker=self.worker(model)
  with patch('desktop_executor.DesktopBrowser',FakeBrowser):
   thread=threading.Thread(target=run_desktop,args=(worker,self.job));thread.start()
   try:
    self.assertTrue(started.wait(3));state=broker(self.store);state.take('owner');release.set();time.sleep(.05);FakeBrowser.instances[0].registered=True;state.give_back('owner');thread.join(3)
    self.assertFalse(thread.is_alive());self.assertEqual(FakeBrowser.instances[0].clicks,0);self.assertEqual(self.store.get(self.id)['state'],'succeeded')
   finally:self.stop.set();release.set();thread.join(2)
 def test_quick_handback_during_handoff_publication_is_not_overwritten(self):
  replies=iter([dict(action='browser_open',url='https://example.invalid/'),dict(action='browser_type',ref='secret-field',text='NEVER_PERSIST_CREDENTIAL'),dict(action='browser_check',expected='注册演示已完成'),dict(action='finish',state='succeeded',message='完成')])
  worker=self.worker(lambda messages:next(replies));state=broker(self.store)
  published=threading.Event();attempted=threading.Event();returned=threading.Event();save=state.save
  def publish(job,value,phase='running'):
   save(job,value,phase)
   if phase=='waiting_user':
    published.set();attempted.wait(3);returned.wait(.2)
  with patch('desktop_executor.DesktopBrowser',FakeBrowser),patch.object(state,'save',side_effect=publish):
   thread=threading.Thread(target=run_desktop,args=(worker,self.job));thread.start()
   try:
    self.assertTrue(published.wait(3));attempted.set();state.take('owner')
    FakeBrowser.instances[0].registered=True;state.give_back('owner');returned.set()
    thread.join(3);self.assertFalse(thread.is_alive());self.assertEqual(self.store.get(self.id)['state'],'succeeded')
   finally:self.stop.set();attempted.set();returned.set();thread.join(2)
