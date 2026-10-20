"""Installed task commands must honor the isolated OS identity and fixed env."""
import json,os,pwd,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import agent

class InstalledIdentityTests(unittest.TestCase):
    def test_configured_command_does_not_inherit_broker_keys(self):
        account=pwd.getpwuid(os.geteuid())
        if not account.pw_uid:self.skipTest('Run the ordinary command tests as a non-root test user')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);store=agent.Store(root/'jobs.sqlite3');job='a'*32
            store.submit(job,'local fixture');worker=agent.Worker(store)
            previous=Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(os.environ,{'DESKPET_EXECUTOR_USER':account.pw_name,'MINIMAX_API_KEY':'test-key-'+'a'*32,'UNRELATED_CREDENTIAL':'test-key-'+'b'*32,'LLM_API_KEY':'fixture-llm-key','ASR_API_KEY':'fixture-asr-key','TTS_API_KEY':'fixture-tts-key'}):
                    code,text=worker.command(job,"python3 -c 'import os,json; print(json.dumps(dict(uid=os.geteuid(),keys=sorted(os.environ))))'")
                result=json.loads(text);self.assertEqual(code,0);self.assertEqual(result['uid'],account.pw_uid)
                self.assertNotIn('MINIMAX_API_KEY',result['keys']);self.assertNotIn('UNRELATED_CREDENTIAL',result['keys'])
                self.assertNotIn('DESKPET_COMPUTER_TOKEN',result['keys'])
                for key in ('LLM_API_KEY','ASR_API_KEY','TTS_API_KEY'):self.assertNotIn(key,result['keys'])
            finally:os.chdir(previous);store.db.close()

if __name__=='__main__':unittest.main()
