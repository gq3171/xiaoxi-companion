"""Synthetic regressions for revision, cancellation and mixed-tool continuity."""
import json,os,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import agent
from desktop_jobs import broker
from desktop_executor import run_desktop
from test_desktop_executor import FakeBrowser
from browser_tools import Browser,BrowserUnavailable,BrowserCancelled
from desktop_lifecycle import authorize_shutdown

class CommandChainTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=agent.Store(Path(self.tmp.name)/'state/jobs.sqlite3');self.id='a'*32
  self.store.submit(self.id,'合成任务',original_request='请检查合成结果');self.job=self.store.next()
 def tearDown(self):self.store.db.close();self.tmp.cleanup()
 def worker(self,replies):return agent.Worker(self.store,lambda _:next(replies))
 def test_new_revision_requires_new_check(self):
  calls=0;checks=[]
  def model(_):
   nonlocal calls
   calls+=1
   if calls==1:return dict(action='check',command='old')
   if calls==2:self.store.tasks.note(self.id,'b'*32,'另外生成新结果')
   if calls<5:return dict(action='finish',state='succeeded')
   if calls==5:return dict(action='check',command='new')
   return dict(action='finish',state='succeeded')
  worker=agent.Worker(self.store,model);worker.command=lambda j,c:checks.append(c) or (0,'verified');worker.run_job(self.job)
  self.assertEqual(checks,['old','new']);self.assertEqual(self.store.get(self.id)['state'],'succeeded')
  self.assertEqual([x['input_revision'] for x in self.store.tasks.snapshot(self.id)['verified_facts']],[0,1])
 def test_finish_compare_and_swap_rejects_concurrent_owner_amendment(self):
  worker=self.worker(iter([dict(action='check',command='old'),dict(action='finish',state='succeeded'),dict(action='check',command='new'),dict(action='finish',state='succeeded')]))
  worker.command=lambda *a:(0,'verified');update=self.store.update;raced=False
  def race(job,state,message,**kw):
   nonlocal raced
   if state=='succeeded' and not raced:raced=True;self.store.tasks.note(job,'b'*32,'最后一刻修改要求')
   return update(job,state,message,**kw)
  with patch.object(self.store,'update',side_effect=race):worker.run_job(self.job)
  self.assertEqual(self.store.get(self.id)['state'],'succeeded')
  self.assertEqual(self.store.db.execute('SELECT count(*) FROM steps').fetchone()[0],2)
 def test_transfer_cannot_relabel_old_action(self):
  replies=iter([dict(action='browser_open',url='https://example.invalid'),dict(action='finish',state='failed')]);opened=[]
  class Track(FakeBrowser):
   def open(self,url):opened.append(url);return super().open(url)
  def transfer(*args,**kwargs):
   self.store.tasks.note(self.id,'b'*32,'不要打开网页，只检查文件');return run_desktop(*args,**kwargs)
  with patch('agent.run_desktop',side_effect=transfer),patch('desktop_executor.DesktopBrowser',Track):self.worker(replies).run_job(self.job)
  self.assertFalse(opened)
 def test_four_identical_command_errors_pause(self):
  worker=agent.Worker(self.store,lambda _:dict(action='run',command='synthetic'));calls=[]
  worker.command=lambda *a:calls.append(True) or (1,'Permission denied');worker.run_job(self.job)
  self.assertEqual(len(calls),4);self.assertEqual(self.store.get(self.id)['state'],'interrupted')
 def test_background_child_cannot_write_after_cancellation(self):
  worker=agent.Worker(self.store);marker=worker.workspace(self.id)/'late';results=[]
  command="(sleep 1; printf late > late) >/dev/null 2>&1 & wait"
  thread=threading.Thread(target=lambda:results.append(worker.command(self.id,command)));thread.start();time.sleep(.15)
  self.store.cancel(self.id);thread.join(4);self.assertFalse(thread.is_alive());self.assertNotEqual(results[0][0],0)
  time.sleep(1.1);self.assertFalse(marker.exists())
 @unittest.skipUnless(sys.platform=='linux','Linux subreaper/cgroup contract')
 def test_setsid_double_fork_is_drained(self):
  worker=agent.Worker(self.store);marker=worker.workspace(self.id)/'late';results=[]
  command="setsid /bin/sh -c '(sleep 1; printf late > late) & exit 0' >/dev/null 2>&1 &"
  thread=threading.Thread(target=lambda:results.append(worker.command(self.id,command)));thread.start();time.sleep(.2)
  self.store.cancel(self.id);thread.join(5);self.assertFalse(thread.is_alive());time.sleep(1.1);self.assertFalse(marker.exists())
 def test_paused_command_amendment_ack_does_not_claim_execution(self):
  from home_chat import HomeChat
  self.store.update(self.id,'interrupted','未确认结果');literal='请继续核对并改成中文'
  result=HomeChat.actions(SimpleNamespace(computer=self.store),SimpleNamespace(admit=lambda *a:True,live=lambda *a:True),{},'c'*32,dict(action='computer_update',task_note=literal,job_id=self.id),literal)
  self.assertEqual(result['job_state'],'interrupted');self.assertIn('仍暂停',result['say']);self.assertIsNone(self.store.next())
 def test_shutdown_negation_is_action_scoped(self):
  for literal,allowed in [('不要继续注册，把浏览器关闭吧',True),('不要关闭浏览器',False),('不要关闭浏览器，继续注册',False),('关闭浏览器',True)]:
   with self.store.lock,self.store.db:
    doc=self.store.tasks.snapshot(self.id);doc['original_request']=literal;self.store.tasks._save(self.id,doc)
   if allowed:authorize_shutdown(self.store,self.id,literal)
   else:
    with self.assertRaises(ValueError):authorize_shutdown(self.store,self.id,literal)
 def test_tab_close_requires_fresh_absence_evidence(self):
  browser=Browser(self.id,self.tmp.name);tab='b'*32;closed=[];browser.current=tab;browser.tabs[tab]=SimpleNamespace(close=lambda:closed.append(True))
  browser.control=SimpleNamespace(call=lambda *a:(_ for _ in ()).throw(BrowserUnavailable('lost ack')))
  with self.assertRaises(BrowserUnavailable):browser.close_tab()
  self.assertIn(tab,browser.tabs);self.assertFalse(closed)
  browser.control=SimpleNamespace(call=lambda method,*a: {'targetInfos':[]} if method=='Target.getTargets' else (_ for _ in ()).throw(BrowserUnavailable('lost ack')))
  self.assertTrue(browser.close_tab()['closed']);self.assertNotIn(tab,browser.tabs)
 def test_cancelled_tab_close_never_sends(self):
  browser=Browser(self.id,self.tmp.name,lambda:True);browser.current='b'*32;browser.tabs[browser.current]=None
  with self.assertRaises(BrowserCancelled):browser.close_tab()
 def test_provider_failure_keeps_unknown_effect_reconcilable(self):
  from urllib.error import URLError
  self.store.update(self.id,'failed','replace fixture');job='c'*32;self.store.submit(job,'浏览器合成测试');calls=0
  def model(_):
   nonlocal calls
   calls+=1
   if calls==1:return dict(action='browser_open',url='https://example.invalid')
   if calls==2:return dict(action='browser_click',ref='test')
   raise URLError('provider unavailable')
  class Lost(FakeBrowser):
   def click(self,*a):raise BrowserUnavailable('lost ack')
  worker=agent.Worker(self.store,model);update=self.store.update
  def terminal(j,state,message,**kw):
   result=update(j,state,message,**kw)
   if j==job and state in ('failed','interrupted'):worker.stop.set()
   return result
  with patch('desktop_executor.DesktopBrowser',Lost),patch.object(self.store,'update',side_effect=terminal):worker.serve()
  self.assertEqual(self.store.get(job)['state'],'interrupted');self.assertTrue(broker(self.store).load(job)['uncertain'])
  from task_control import control
  self.assertEqual(control(self.store,'computer_resume','d'*32,job_id=job)['state'],'queued')
 def test_local_artifact_and_browser_steps_share_task_and_revision(self):
  replies=iter([dict(action='workspace_write',name='report.txt',text='synthetic report'),dict(action='workspace_check',name='report.txt',expected='synthetic'),dict(action='browser_open',url='https://example.invalid'),dict(action='browser_check',expected='registered'),dict(action='finish',state='succeeded')])
  class Checked(FakeBrowser):
   def check(self,*a):return dict(passed=True)
  with patch('desktop_executor.DesktopBrowser',Checked):self.worker(replies).run_job(self.job)
  self.assertEqual(self.store.get(self.id)['state'],'succeeded');self.assertEqual(self.store.db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
  from workspace_tools import read
  self.assertEqual(read(agent.Worker(self.store).workspace(self.id),'report.txt'),b'synthetic report')
 def test_workspace_symlink_and_fifo_are_not_read(self):
  from workspace_tools import read
  workspace=agent.Worker(self.store).workspace(self.id);(workspace/'artifacts').mkdir();os.symlink('/etc/passwd',workspace/'artifacts/leak')
  with self.assertRaises(OSError):read(workspace,'leak')
  os.mkfifo(workspace/'artifacts/pipe')
  with self.assertRaises(ValueError):read(workspace,'pipe')

 def test_restart_drains_registered_scope_before_confirming_cancel(self):
  unit='xiaoxi-task-'+self.id+'-'+'e'*32+'.service'
  self.store.register_scope(self.id,unit)
  self.store.db.close()
  with patch('task_process.drain_unit') as drain:
   self.store=agent.Store(Path(self.tmp.name)/'state/jobs.sqlite3')
   drain.assert_called_once_with(unit)
  self.assertEqual(self.store.get(self.id)['state'],'interrupted')
  self.assertEqual(self.store.cancel(self.id)['state'],'cancelled')
 def test_unconfirmed_drain_does_not_acknowledge_cancellation(self):
  self.store.update(self.id,'interrupted','unknown')
  self.store.register_scope(self.id,'xiaoxi-task-'+self.id+'-'+'e'*32+'.service')
  with patch('task_process.drain_unit',side_effect=RuntimeError('still active')):
   value=self.store.cancel(self.id)
  self.assertEqual(value['state'],'interrupted');self.assertTrue(value['cancel'])
 def test_later_owner_negation_revokes_browser_shutdown(self):
  literal='关闭浏览器'
  with self.store.lock,self.store.db:
   doc=self.store.tasks.snapshot(self.id);doc['original_request']=literal;self.store.tasks._save(self.id,doc)
  self.store.tasks.note(self.id,'b'*32,'不要关闭浏览器，先保留当前页面')
  with self.assertRaises(ValueError):authorize_shutdown(self.store,self.id,literal)

 def test_explicit_local_command_is_not_rejected_by_browser_keyword(self):
  literal='先在本地生成合成报告，再用浏览器查看它'
  with self.store.lock,self.store.db:
   doc=self.store.tasks.snapshot(self.id);doc['original_request']=literal;self.store.tasks._save(self.id,doc)
   self.store.db.execute('UPDATE jobs SET goal=? WHERE id=?',(literal,self.id))
  replies=iter([dict(action='run',command='printf report'),dict(action='check',command='printf verified'),dict(action='browser_open',url='https://example.invalid'),dict(action='browser_check',expected='done'),dict(action='finish',state='succeeded')]);executed=[]
  worker=self.worker(replies);worker.command=lambda j,c:executed.append(c) or (0,'verified')
  class Checked(FakeBrowser):
   def check(self,*a):return dict(passed=True)
  with patch('desktop_executor.DesktopBrowser',Checked):worker.run_job(self.store.get(self.id))
  self.assertEqual(len(executed),2);self.assertEqual(self.store.get(self.id)['state'],'succeeded')

 def test_lost_tab_close_can_resume_without_restoring_closed_target(self):
  state=broker(self.store);tab='b'*32
  state.save(self.id,dict(messages=[dict(role='user',content='fixture')],browser=dict(tabs=[tab],current=tab),pending_effect=dict(action='browser_close',tab=tab,step=1),uncertain=True))
  worker=self.worker(iter([dict(action='finish',state='succeeded')]))
  with patch('desktop_executor.DesktopBrowser',FakeBrowser),patch('desktop_lifecycle.BrowserSession',return_value=SimpleNamespace(status=lambda:dict(closed=True))):run_desktop(worker,self.job)
  self.assertEqual(self.store.get(self.id)['state'],'succeeded');self.assertFalse(state.load(self.id)['uncertain'])

 def test_closed_browser_cannot_verify_unknown_non_close_effect(self):
  state=broker(self.store)
  state.save(self.id,dict(messages=[dict(role='user',content='fixture')],browser=dict(tabs=[]),browser_session_closed=True,pending_effect=dict(action='browser_click',step=1),uncertain=True))
  worker=self.worker(iter([dict(action='finish',state='succeeded'),dict(action='finish',state='failed')]))
  with patch('desktop_executor.DesktopBrowser',FakeBrowser),patch('desktop_lifecycle.BrowserSession',return_value=SimpleNamespace(status=lambda:dict(closed=True))):run_desktop(worker,self.job)
  self.assertEqual(self.store.get(self.id)['state'],'interrupted');self.assertTrue(state.load(self.id)['uncertain'])

 def test_cgroup_scope_preserves_broker_resource_ceilings(self):
  from task_process import scope_limits
  root=Path(self.tmp.name)/'cgroup';node=root/'system.slice/broker.service';node.mkdir(parents=True)
  (node/'memory.max').write_text('536870912');(node.parent/'pids.max').write_text('96')
  membership=Path(self.tmp.name)/'membership';membership.write_text('0::/system.slice/broker.service')
  limits=scope_limits(root,membership)
  self.assertIn('--property=MemoryMax=536870912',limits);self.assertIn('--property=TasksMax=96',limits)

 def test_model_cannot_remove_negation_from_owner_amendment(self):
  from home_chat import HomeChat
  literal='不要关闭浏览器，只检查页面'
  result=HomeChat.actions(SimpleNamespace(computer=self.store),SimpleNamespace(admit=lambda *a:True,live=lambda *a:True),{},'c'*32,dict(action='computer_update',task_note='关闭浏览器',job_id=self.id),literal)
  self.assertEqual(self.store.tasks.snapshot(self.id)['owner_decisions'][-1]['text'],literal)
  with self.assertRaises(ValueError):authorize_shutdown(self.store,self.id,'关闭浏览器')
