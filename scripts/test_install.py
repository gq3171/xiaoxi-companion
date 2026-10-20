import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('installer',Path(__file__).with_name('install.py'))
i=importlib.util.module_from_spec(spec);spec.loader.exec_module(i)

class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.base=self.root/'data';self.dest=self.root/'installed';self.unit=self.root/'unit'
        self.patch=patch.multiple(i,BASE=self.base,INSTALL=self.dest,UNIT=self.unit);self.patch.start()
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def test_default_check_is_read_only_and_returns_machine_report(self):
        import contextlib,io
        output=io.StringIO()
        with patch.object(i,'run',side_effect=AssertionError('must not mutate')),patch('sys.argv',['install.py','--json']),contextlib.redirect_stdout(output):
            code=i.main()
        report=json.loads(output.getvalue());self.assertEqual(report['schema'],1)
        self.assertEqual(report['exit_code'],code);self.assertFalse(self.base.exists())
    def test_env_permissions_symlinks_duplicates_and_shell_syntax_rejected_without_secret_output(self):
        p=self.root/'provider.env';secret='test-'+'a'*32
        p.write_text('MINIMAX_API_KEY='+secret+'\n');p.chmod(0o644)
        with self.assertRaises(i.InstallError) as e:i.private_input(p)
        self.assertNotIn(secret,str(e.exception));p.chmod(0o600)
        self.assertEqual(i.private_input(p)['MINIMAX_API_KEY'],secret)
        link=self.root/'link';link.symlink_to(p)
        with self.assertRaises(i.InstallError):i.private_input(link)
        for text in ('MINIMAX_API_KEY=$(whoami)\n','MINIMAX_API_KEY='+secret+'\nMINIMAX_API_KEY=other\n','SSH_PASSWORD='+secret+'\n'):
            p.write_text(text)
            with self.assertRaises(i.InstallError) as e:i.private_input(p)
            self.assertNotIn(secret,str(e.exception))
    def test_existing_config_and_modified_release_are_never_overwritten(self):
        config=self.base/'config';config.mkdir(parents=True);private=config/'service.env';private.write_text('DO_NOT_TOUCH')
        with self.assertRaises(i.InstallError):i.check_existing()
        self.assertEqual(private.read_text(),'DO_NOT_TOUCH')
        self.dest.mkdir();code=self.dest/'agent.py';code.write_text('reviewed')
        (config/'install.json').write_text(json.dumps({'source':'fixture','files':{'agent.py':i.digest(code)}}))
        with patch.object(i,'fingerprint',return_value='fixture'):
            self.assertTrue(i.check_existing());code.write_text('external modification')
            with self.assertRaises(i.InstallError):i.check_existing()
        self.assertEqual(code.read_text(),'external modification');self.assertEqual(private.read_text(),'DO_NOT_TOUCH')
    def test_private_creation_is_exclusive_and_hostname_cannot_inject_openssl_arguments(self):
        p=self.root/'secret';i.atomic_private(p,'preserve')
        self.assertEqual(p.stat().st_mode&0o777,0o600)
        with self.assertRaises(FileExistsError):i.atomic_private(p,'overwrite')
        self.assertEqual(p.read_text(),'preserve')
        for value in ('','xiaoxi.example','127.0.0.1','https://home.example.org','test.example.org/CN=other','test.example.org\nDNS:evil'):
            self.assertFalse(i.hostname_valid(value))
        self.assertTrue(i.hostname_valid('companion.example.org'))

if __name__=='__main__':unittest.main()
