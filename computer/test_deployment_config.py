"""Custom paths/settings must reach services and actual provider requests."""
import copy,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import deployment_paths as paths
import runtime_config as config
from desktop_launcher import browser_args

class ConfigurationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.locator=self.root/'installation.json'
  self.doc=dict(schema=1,data_root=str(self.root/'data with 空格 %'),storage_mount='/',install_dir=str(self.root/'software'),
                desktop_root=str(self.root/'desktop'),browser_root=str(self.root/'browser'),port=19491,
                public_origin='https://127.0.0.1:19491',options={'desktop':{'cdp_port':19492,'probe_cdp_port':19493},'speech':{'asr_model':'configured-asr'}})
  self.locator.write_text(json.dumps(self.doc));self.env=patch.dict(os.environ,{'DESKPET_INSTALL_CONFIG':str(self.locator)});self.env.start()
 def tearDown(self):self.env.stop();self.tmp.cleanup()
 def test_shared_helpers_use_saved_custom_roots_origin_and_debug_port(self):
  self.assertEqual(paths.data_root(),Path(self.doc['data_root']))
  self.assertEqual(paths.desktop_root(),Path(self.doc['desktop_root']))
  self.assertEqual(paths.browser_root(),Path(self.doc['browser_root']))
  self.assertEqual(config.public_origin(),self.doc['public_origin'])
  argv=browser_args(paths.desktop_root(),'about:blank')
  self.assertIn('--remote-debugging-port=19492',argv)
  self.assertIn('--remote-debugging-address=127.0.0.1',argv)
 def test_mount_loss_is_not_treated_as_available_system_disk(self):
  self.doc['storage_mount']=str(self.root/'absent-mount');self.locator.write_text(json.dumps(self.doc))
  self.assertFalse(paths.storage_ready())
 def test_services_share_custom_layout_and_quote_spaces_unicode_and_specifiers(self):
  unit=paths.render_service('computer',self.doc,self.locator)
  self.assertNotIn('/mnt/nvme',unit);self.assertIn('data with 空格 %%',unit)
  self.assertIn('"--port" "19491"',unit);self.assertIn('DESKPET_INSTALL_CONFIG=',unit)
  self.assertIn('WorkingDirectory='+str(self.doc['data_root']).replace('%','%%')+'/work\n',unit)
  self.assertIn('ConditionPathIsMountPoint=/\n',unit)
  for kind in ('desktop','browser'):
   unit=paths.render_service(kind,self.doc,self.locator)
   self.assertIn(str(self.doc[kind+'_root']),unit);self.assertNotIn('/mnt/nvme',unit)
 def test_unknown_and_unsafe_options_are_rejected_without_including_values(self):
  for options in ({'extra_key':'hidden-sentinel'},{'desktop':{'cdp_port':True}},{'desktop':{'renderer':'bad-renderer'}},
                  {'llm':{'api_host':'http://unsafe.example'}},{'http':{'connection_limit':0}}):
   with self.assertRaises(ValueError) as e:config.validate(options)
   self.assertNotIn('hidden-sentinel',str(e.exception))
 def test_asr_override_changes_only_form_header_never_pcm_audio(self):
  prefix=b'------deskpet\r\nContent-Disposition: form-data; name="model"\r\n\r\n'
  tail=b'\r\n------deskpet\r\nRIFF asr-1.0 audio bytes'
  result=config.rewrite_asr_model(prefix+b'asr-1.0'+tail)
  self.assertEqual(result,prefix+b'configured-asr'+tail)
  with self.assertRaises(ValueError):config.rewrite_asr_model(b'RIFF alone')
 def test_bad_locator_fails_closed_instead_of_falling_back(self):
  self.locator.write_text('{broken')
  with self.assertRaises(ValueError):paths.data_root()
 def test_layout_rejects_control_characters_and_privileged_accounts(self):
  for change in ({'port':True},{'users':{'computer':'root'}},{'data_root':'/tmp/line\nbreak'},
                 {'users':{'desktop':'user\nGroup=root'}},{'schema':True}):
   value=dict(self.doc,**change)
   with self.assertRaises(ValueError):paths.validate_layout(value)
 def test_legacy_path_is_only_selected_when_legacy_config_exists(self):
  self.locator.unlink()
  with patch.object(paths,'LEGACY_ROOT',self.root/'legacy'):
   self.assertEqual(paths.data_root(),Path('/var/lib/xiaoxi'))
   (self.root/'legacy/config').mkdir(parents=True);(self.root/'legacy/config/service.env').touch()
   self.assertEqual(paths.data_root(),self.root/'legacy')

if __name__=='__main__':unittest.main()
