"""View-only socket, bounded frames and dashboard escaping with no GUI/service."""
import json,socket,struct,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import agent
from home_desktop import HostDesktop,DesktopUnavailable,MAX_FRAME
from desktop_daemon import Desktop
class DesktopTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=agent.Store(self.root/'jobs.sqlite3');self.screen=Desktop(self.root);self.path=self.root/'view.sock';self.listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.listener.bind(str(self.path));self.listener.listen(4);self.listener.settimeout(.1);self.stop=threading.Event()
  def run():
   while not self.stop.is_set():
    try:c,_=self.listener.accept()
    except socket.timeout:continue
    self.screen.respond(c)
  self.thread=threading.Thread(target=run);self.thread.start();self.client=HostDesktop(self.store,self.path)
 def tearDown(self):self.stop.set();self.thread.join(2);self.listener.close();self.store.db.close();self.tmp.cleanup()
 def test_real_socket_view_reports_task_without_commands_or_output(self):
  job=self.store.submit('a'*32,'只测试工作进度');self.store.record(job['id'],1,'check','secret command',0,'secret output');self.screen.frame=b'\x89PNG\r\n\x1a\nframe';self.screen.captured_at=time.time();self.screen.sequence=4
  value=self.client.status();self.assertTrue(value['ready']);self.assertTrue(value['view_only']);self.assertEqual(value['sequence'],4);self.assertEqual(value['task']['step']['ordinal'],1);self.assertNotIn('secret',json.dumps(value));self.assertEqual(self.client.frame(),self.screen.frame)
 def test_expired_frame_is_not_reported_live_or_returned_as_image(self):
  self.screen.frame=b'\x89PNG\r\n\x1a\nframe';self.screen.captured_at=time.time()-6;self.assertFalse(self.client.status()['ready'])
  with self.assertRaises(DesktopUnavailable):self.client.frame()
 def test_dashboard_escapes_task_markup_and_rejects_large_requests(self):
  self.screen.update(dict(goal='<script>bad()</script>',state='running',message='literal <&>'));text=(self.root/'desk.html').read_text();self.assertIn('&lt;script&gt;',text);self.assertNotIn('<script>bad',text)
  with self.assertRaises(ValueError):self.screen.update(dict(goal='x'*6001))
 def test_only_known_socket_operations_are_served(self):
  with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:s.settimeout(1);s.connect(str(self.path));s.sendall(b'{"op":"run","command":"no"}\n');self.assertEqual(s.recv(4),b'')
 def test_missing_service_start_is_fixed_and_rate_limited(self):
  client=HostDesktop(self.store,self.root/'missing.sock')
  with patch('home_desktop.subprocess.run') as run:
   self.assertFalse(client.open()['ready']);client.open();self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.args[0],['/usr/bin/systemctl','start','deskpet-desktop.service'])
 def test_oversized_socket_frame_is_rejected_before_body_read(self):
  self.screen.frame=b'\x89PNG\r\n\x1a\n'+b'x'*(MAX_FRAME+1);self.screen.captured_at=time.time()
  with self.assertRaises(DesktopUnavailable):self.client.frame()
 def test_private_stop_request_acknowledges_and_stops_daemon(self):
  with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
   s.settimeout(1);s.connect(str(self.path));s.sendall(b'{"op":"stop"}\n');n=struct.unpack('!I',self.client.read(s,4))[0];self.assertEqual(json.loads(self.client.read(s,n))['protocol'],1)
  self.assertTrue(self.screen.stop.is_set())
 def test_task_can_request_browser_without_restarting_desktop(self):
  value=self.client.ensure_browser();self.assertTrue(self.screen.browser_requested.is_set());self.assertEqual(value['task'],None)
