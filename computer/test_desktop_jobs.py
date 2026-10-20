import json,tempfile,threading,unittest
from pathlib import Path
import agent
from desktop_jobs import DesktopJobs,DesktopBusy

class DesktopJobTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=agent.Store(Path(self.tmp.name)/'jobs.sqlite3');self.now=100.;self.jobs=DesktopJobs(self.store,lambda:self.now);self.id='a'*32;self.store.submit(self.id,'测试网页表单');self.store.next();self.jobs.save(self.id,{'messages':[]})
 def tearDown(self):self.store.db.close();self.tmp.cleanup()
 def test_takeover_freezes_actions_until_explicit_handback(self):
  self.assertFalse(self.jobs.waiting(self.id));self.jobs.take('owner');self.assertTrue(self.jobs.waiting(self.id))
  with self.assertRaises(DesktopBusy):
   with self.jobs.action(self.id):self.fail('must not execute during takeover')
  self.jobs.give_back('owner');self.assertFalse(self.jobs.waiting(self.id))
 def test_expiration_never_automatically_resumes_a_protected_step(self):
  self.jobs.take('owner');self.now+=121;self.assertFalse(self.jobs.controls('owner'));self.assertTrue(self.jobs.waiting(self.id))
  self.jobs.resume(self.id);self.assertFalse(self.jobs.waiting(self.id))
 def test_one_control_owner_and_no_takeover_mid_action(self):
  with self.jobs.action(self.id):
   with self.assertRaises(DesktopBusy):self.jobs.take('owner')
  self.jobs.take('owner')
  with self.assertRaises(DesktopBusy):self.jobs.take('other')
  with self.assertRaises(PermissionError):self.jobs.give_back('other')
 def test_checkpoint_after_takeover_cannot_clear_the_pause(self):
  self.jobs.take('owner');self.jobs.save(self.id,{'messages':['late observation']});self.assertTrue(self.jobs.waiting(self.id));self.jobs.revoke('owner');self.assertTrue(self.jobs.waiting(self.id))
 def test_restart_preserves_checkpoint_and_requires_explicit_resume(self):
  self.jobs.save(self.id,{'browser':{'tabs':['b'*32]},'uncertain':True});self.store.update(self.id,'interrupted','模拟重启')
  other=DesktopJobs(self.store,lambda:self.now);self.assertTrue(other.load(self.id)['uncertain']);self.assertTrue(other.state('owner')['can_resume']);other.resume(self.id);self.assertEqual(self.store.get(self.id)['state'],'queued')
 def test_cancelled_tasks_cannot_be_resumed(self):
  self.store.cancel(self.id)
  with self.assertRaises(ValueError):self.jobs.resume(self.id)
 def test_terminal_task_with_stale_checkpoint_does_not_own_desktop(self):
  self.store.update(self.id,'failed','模拟异常后未写终态checkpoint')
  self.assertIsNone(self.jobs.current());self.assertEqual(self.jobs.state()['phase'],'idle')
  self.jobs.take('owner');self.jobs.give_back('owner');self.assertFalse(self.jobs.controls('owner'))

 def test_input_counters_are_lease_scoped_and_never_accept_payloads(self):
  import contextlib,io
  value=dict(down=1,up=1,pointerDown=1,pointerUp=1,nonzero=1,click=1,wheel=0,keys=0,connected=1)
  with self.assertRaises(PermissionError):self.jobs.input_report('owner',value)
  self.jobs.take('owner');channel=self.jobs.transport_open('owner');self.jobs.transport_bytes(channel,50);self.assertTrue(self.jobs.state('owner')['control_connected']);self.assertFalse(self.jobs.state('other')['control_connected'])
  output=io.StringIO()
  with contextlib.redirect_stdout(output):self.jobs.input_report('owner',value);self.jobs.input_report('owner',value)
  self.assertEqual(output.getvalue().count('desktop_input '),1)
  report=json.loads(output.getvalue().split(' ',1)[1]);self.assertEqual(report['channels'],1);self.assertEqual(report['forwarded_bytes'],50);self.assertNotIn('session',report)
  with self.assertRaises(ValueError):self.jobs.input_report('owner',value|{'key':'secret'})
  self.jobs.transport_close(channel);self.assertEqual(self.jobs.transports,{});self.assertFalse(self.jobs.state('owner')['control_connected'])
 def test_return_revokes_transport_ownership_and_counters(self):
  self.jobs.take('owner');channel=self.jobs.transport_open('owner');self.jobs.give_back('owner')
  with self.assertRaises(PermissionError):self.jobs.transport_open('owner')
  self.jobs.transport_close(channel);self.assertFalse(self.jobs.transports)
