import json,shlex,tempfile,unittest,xml.etree.ElementTree as ET
from pathlib import Path
from desktop_shell import prepare
from desktop_launcher import command

class DesktopShellTests(unittest.TestCase):
 def test_native_dock_entries_and_window_manager_defaults_are_present(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);launcher=root/'program path'/'launcher.py';config,style=prepare(root,launcher)
   dock=json.loads(config.read_text());self.assertEqual(dock['position'],'bottom');self.assertTrue(dock['exclusive']);self.assertIn('wlr/taskbar',dock['modules-center'])
   for module in dock['modules-left']:self.assertIn(module,dock,'every launcher module must have a configuration')
   for name in ('terminal','files','browser','apps','home'):self.assertEqual(shlex.split(dock['custom/'+name]['on-click']),['/usr/bin/python3',str(launcher),name])
   rc=ET.parse(root/'config/rc.xml');self.assertIsNotNone(rc.find('keyboard/default'));self.assertIsNotNone(rc.find('mouse/default'));self.assertTrue((root/'work').is_dir());self.assertTrue(style.is_file())
 def test_restarting_does_not_overwrite_manual_window_manager_preferences(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);prepare(root);p=root/'config/rc.xml';p.write_text('<labwc_config><!--owner setting--></labwc_config>');prepare(root);self.assertIn('owner setting',p.read_text())
 def test_launcher_uses_explicit_shell_and_shared_chromium_profile(self):
  root=Path('/mnt/nvme/example desktop');terminal=command(root,'terminal');self.assertEqual(terminal[-3:],['/bin/bash','--noprofile','--norc']);self.assertIn('--working-directory='+str(root/'work'),terminal)
  for action in ('browser','home'):self.assertIn('--user-data-dir='+str(root/'profile'),command(root,action))
  self.assertEqual(command(root,'browser')[-1],'about:blank');self.assertEqual(command(root,'files'),['/usr/bin/thunar',str(root/'work')]);self.assertIn('drun',command(root,'apps'))
 def test_unknown_apps_cannot_be_interpreted_as_shell_commands(self):
  with self.assertRaises(ValueError):command(Path('/mnt/nvme/example'),'terminal; sudo true')

 def test_normal_browser_close_supports_non_context_manager_websocket(self):
  import io,types
  from unittest.mock import patch
  import desktop_stop
  sent=[]
  class Closed(Exception):pass
  class Socket:
   def send(self,value):sent.append(json.loads(value))
   def recv(self):raise Closed()
   def close(self):sent.append('closed')
  fake=types.SimpleNamespace(create_connection=lambda *a,**k:Socket(),WebSocketConnectionClosedException=Closed,WebSocketTimeoutException=TimeoutError)
  opener=types.SimpleNamespace(open=lambda *a,**k:io.BytesIO(json.dumps({'webSocketDebuggerUrl':'ws://127.0.0.1:19224/devtools/browser/test'}).encode()))
  with patch.object(desktop_stop,'build_opener',return_value=opener),patch.dict('sys.modules',websocket=fake):desktop_stop.close_browser(19224)
  self.assertEqual(sent,[{'id':1,'method':'Browser.close'},'closed'])
 def test_reopened_browser_keeps_private_debugger_and_focus_uses_native_protocol(self):
  from unittest.mock import patch
  import desktop_launcher
  args=command(Path('/mnt/nvme/example'),'browser');self.assertIn('--remote-debugging-address=127.0.0.1',args);self.assertIn('--remote-debugging-port=19223',args)
  with patch.object(desktop_launcher.subprocess,'run') as run:
   desktop_launcher.foreground('browser',{})
   self.assertEqual(run.call_args.args[0],['/usr/bin/wlrctl','toplevel','focus','app_id:chromium']);self.assertNotIn('shell',run.call_args.kwargs)
