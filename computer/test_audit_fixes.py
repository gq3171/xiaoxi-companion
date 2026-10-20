"""Task reports keep bounded summaries, full results and credential-free errors."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import test_agent as fixtures

agent=fixtures.agent


class AuditFixTests(unittest.TestCase):
    def test_full_terminal_report_survives_while_wire_summary_is_bounded_and_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=agent.Store(Path(tmp)/'jobs.sqlite3')
            try:
                job='a'*32;store.submit(job,'读取配置')
                report='系统版本已确认。'+('内存和磁盘的详细配置。'*150)+'最后一条校验结果。'
                store.update(job,'succeeded',report)
                summary=store.get(job)['message']
                self.assertLessEqual(len(summary.encode()),1024);self.assertIn('已截短',summary)
                self.assertEqual(store.db.execute('SELECT report FROM job_reports WHERE job=?',(job,)).fetchone()[0],report)
            finally:store.db.close()

    def test_failure_categories_never_echo_provider_body_or_credentials(self):
        for status in (401,429,503):
            error=HTTPError('https://example.invalid',status,'private-api-token-do-not-copy',{},None)
            message=agent.task_failure_message(error)
            self.assertNotIn('private',message);self.assertIn('没有完成',message)
        self.assertIn('无法解析',agent.task_failure_message(json.JSONDecodeError('private','',0)))

    def test_worker_uses_existing_streaming_provider_and_cancellation_callback(self):
        observations=[]
        class Provider:
            def __init__(self,key,host):pass
            def complete(self,system,messages,live=None):
                observations.append(live());return '{"action":"finish","state":"failed"}'
        fake=types.SimpleNamespace(Provider=Provider,parse_answer=json.loads)
        with tempfile.TemporaryDirectory() as tmp:
            store=agent.Store(Path(tmp)/'jobs.sqlite3')
            try:
                worker=agent.Worker(store)
                with patch.dict('sys.modules',{'brain':fake}):
                    self.assertEqual(worker.complete([])['action'],'finish')
                    worker.stop.set();worker.complete([])
                self.assertEqual(observations,[True,False])
            finally:store.db.close()
