"""Synthetic private input: document scope, revocation, no replay or persistence."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from private_input import PrivateInputs, InputConflict, inputs, wipe
from private_browser import origin
from browser_tools import BrowserUnavailable


def form():
    return dict(origin='https://example.invalid', document='document-1', tab='tab',
                fields=[dict(id='account', kind='account', label='邮箱'),
                        dict(id='password', kind='password', label='密码')],
                action_label='下一步', bindings=[], action=None)


class PrivateInputTests(unittest.TestCase):
    def setUp(self):
        self.now=100.;self.private=PrivateInputs(lambda:self.now)
        self.request=self.private.offer('a'*32,form())
        self.claim=self.private.claim(self.request['id'],'owner')
    def submit(self,**kw):
        return self.private.submit(self.request['id'],'owner',self.claim['lease'],
            dict(account='test@example.invalid',password='SYNTHETIC_PRIVATE_SENTINEL'),True,lambda:True,**kw)
    def test_values_are_not_in_status_and_duplicate_submit_never_replays(self):
        self.submit();public=json.dumps(self.private.pending('owner'))
        self.assertNotIn('SYNTHETIC_PRIVATE_SENTINEL',public)
        submission=self.private.consume('a'*32)
        self.assertTrue(self.private.valid(submission['id']))
        self.assertEqual(self.submit()['state'],'applying');self.assertIsNone(self.private.consume('a'*32))
        raw=submission['values']['password'];wipe(submission['values']);self.assertFalse(any(raw))
        self.private.finish(submission['id'],True)
        self.assertEqual(self.submit()['state'],'filled');self.assertIsNone(self.private.consume('a'*32))
    def test_other_device_claims_and_renewal_do_not_steal_or_rotate_live_lease(self):
        with self.assertRaises(InputConflict):self.private.claim(self.request['id'],'other')
        self.assertTrue(self.private.pending('other')['claimed_elsewhere'])
        self.assertEqual(self.private.claim(self.request['id'],'owner')['lease'],self.claim['lease'])
        self.now+=91;other=self.private.claim(self.request['id'],'other')
        self.assertNotEqual(other['lease'],self.claim['lease'])
        with self.assertRaises(InputConflict):self.submit()
    def test_schema_budget_and_no_unreviewed_action(self):
        with self.assertRaises(ValueError):
            self.private.submit(self.request['id'],'owner',self.claim['lease'],{'password':'secret'},True,lambda:True)
        with self.assertRaises(ValueError):
            self.private.submit(self.request['id'],'owner',self.claim['lease'],dict(account='x',password='x'*1025),True,lambda:True)
        self.assertIsNone(self.private.consume('a'*32))
    def test_cancel_expiry_and_job_close_erase_queued_values(self):
        self.submit();raw=self.private.requests[self.request['id']]['values']['password']
        self.private.cancel(self.request['id'],'owner');self.assertFalse(any(raw))
        self.assertIsNone(self.private.consume('a'*32))
        new=self.private.offer('a'*32,form());claim=self.private.claim(new['id'],'owner')
        self.private.submit(new['id'],'owner',claim['lease'],dict(account='x',password='secret'),True,lambda:True)
        raw=self.private.requests[new['id']]['values']['password'];self.now+=601
        self.assertEqual(self.private.pending('owner')['state'],'expired');self.assertFalse(any(raw))
        self.assertIsNone(self.private.consume('a'*32));self.private.close_job('a'*32)
    def test_revocation_is_rechecked_after_submission_before_application(self):
        live=[True]
        self.private.submit(self.request['id'],'owner',self.claim['lease'],dict(account='x',password='secret'),True,lambda:live[0])
        submission=self.private.consume('a'*32);live[0]=False
        self.assertFalse(self.private.valid(submission['id']));wipe(submission['values'])
        self.private.finish(submission['id'],False)
    def test_release_preserves_request_without_input_and_allows_another_device(self):
        self.private.release(self.request['id'],'owner',self.claim['lease'])
        self.assertEqual(self.private.claim(self.request['id'],'other')['state'],'claimed')
    def test_board_rpc_is_job_bound_and_never_routes_values_to_status(self):
        import agent
        from private_input import body_rpc
        with tempfile.TemporaryDirectory() as temporary:
            store=agent.Store(Path(temporary)/'state/jobs.sqlite3')
            try:
                job='a'*32;store.submit(job,'合成板端填写');store.next()
                private=inputs(store);request=private.offer(job,form())
                claim=body_rpc(store,dict(job_id=job,id=request['id'],action='claim'))['request']
                payload=dict(job_id=job,id=request['id'],action='submit',lease=claim['lease'],values=dict(account='synthetic@example.invalid',password='BOARD_SYNTHETIC_SECRET'),activate=True)
                self.assertTrue(body_rpc(store,payload)['ok']);self.assertNotIn('values',payload)
                submission=private.consume(job);store.cancel(job)
                self.assertFalse(private.valid(submission['id']));wipe(submission['values']);private.finish(submission['id'],False)
                with self.assertRaises(InputConflict):body_rpc(store,dict(job_id='b'*32,id=request['id'],action='claim'))
                self.assertNotIn('BOARD_SYNTHETIC_SECRET',json.dumps(private.pending('owner')))
            finally:store.db.close()

    def test_owner_submission_resumes_only_a_safe_waiting_checkpoint(self):
        import agent
        from desktop_jobs import broker
        from private_input import submit_web
        with tempfile.TemporaryDirectory() as temporary:
            store=agent.Store(Path(temporary)/'state/jobs.sqlite3')
            try:
                job='a'*32;store.submit(job,'合成中断恢复');store.next();state=broker(store)
                state.save(job,dict(uncertain=False,messages=[],browser={}),phase='waiting_user')
                store.update(job,'interrupted','合成重启')
                private=inputs(store);request=private.offer(job,form());claim=private.claim(request['id'],'owner')
                result=submit_web(store,request['id'],'owner',claim['lease'],dict(account='synthetic@example.invalid',password='SAFE_RESTART_SENTINEL'),True,lambda:True)
                self.assertEqual(result['state'],'queued');self.assertEqual(store.get(job)['state'],'queued')
                self.assertEqual(state.state()['phase'],'resume_requested')
                submission=private.consume(job);wipe(submission['values']);private.finish(submission['id'],False)
            finally:store.db.close()

    def test_private_numeric_values_do_not_corrupt_tool_references_and_model_cannot_submit(self):
        from desktop_browser import DesktopBrowser
        from browser_tools import BrowserBlocked
        browser=object.__new__(DesktopBrowser);browser._private_values=[bytearray(b'1')]
        redacted=browser.private_redact(dict(text='private value 1',ref='a1b2c3d4e5f6:1',tab='1'*32,snapshot='1'*12))
        self.assertNotIn('1',redacted['text']);self.assertEqual(redacted['ref'],'a1b2c3d4e5f6:1')
        self.assertEqual(redacted['tab'],'1'*32)
        browser.activation_context=lambda *args:dict(name='Next',form=True,password=False,submit=True)
        browser.registration=lambda *args:False
        with self.assertRaises(BrowserBlocked):browser.before_activate(object(),dict(backend=1),'click')
        browser.private_clear()

    def test_origins_are_canonical_and_cleartext_public_sites_are_denied(self):
        self.assertEqual(origin('https://example.org:443/register?private=ignored'),'https://example.org')
        self.assertEqual(origin('http://127.0.0.1:18924/register'),'http://127.0.0.1:18924')
        for url in ('http://example.org','https://user:pass@example.org','javascript:alert(1)'):
            with self.assertRaises(BrowserUnavailable):origin(url)


class PrivateExecutorTests(unittest.TestCase):
    def test_private_submission_continues_same_job_without_exposing_values_to_model_or_disk(self):
        import agent
        from desktop_jobs import broker
        from desktop_executor import run_desktop
        from test_desktop_executor import FakeBrowser
        from types import SimpleNamespace
        class Browser(FakeBrowser):
            def private_form(self):return form() if not self.registered else None
            def private_apply(self,prepared,values,activate,valid):
                if not valid():raise BrowserUnavailable('revoked')
                self.registered=True
                return dict(filled=True)
            def private_redact(self,value):return value
        with tempfile.TemporaryDirectory() as tmp:
            store=agent.Store(Path(tmp)/'state/jobs.sqlite3');job_id='a'*32
            store.submit(job_id,'本地合成隐私填写演示，不创建真实账户');job=store.next();stop=threading.Event();prompts=[]
            replies=iter([dict(action='browser_open',url='https://example.invalid'),dict(action='handoff',message='需要填写'),dict(action='browser_check',expected='注册演示已完成'),dict(action='finish',state='succeeded',message='合成演示完成')])
            def model(messages):prompts.append(json.dumps(messages));return next(replies)
            worker=SimpleNamespace(store=store,model=model,key='',stop=stop,active_job_id=None,cancelled=lambda _:stop.is_set())
            with patch('desktop_executor.DesktopBrowser',Browser):
                thread=threading.Thread(target=run_desktop,args=(worker,job));thread.start()
                try:
                    private=inputs(store);deadline=time.monotonic()+3
                    while not private.pending('owner') and time.monotonic()<deadline:time.sleep(.01)
                    request=private.pending('owner');self.assertIsNotNone(request)
                    claim=private.claim(request['id'],'owner')
                    private.submit(request['id'],'owner',claim['lease'],dict(account='test@example.invalid',password='SYNTHETIC_PRIVATE_SENTINEL'),True,lambda:True)
                    thread.join(4);self.assertFalse(thread.is_alive());self.assertEqual(store.get(job_id)['state'],'succeeded')
                    data=' '.join(prompts)+' '.join(str(tuple(r)) for r in store.db.execute('SELECT command,output FROM steps'))
                    data+=store.db.execute('SELECT checkpoint FROM desktop_jobs').fetchone()[0]
                    self.assertNotIn('SYNTHETIC_PRIVATE_SENTINEL',data);self.assertNotIn('test@example.invalid',data)
                    self.assertEqual(private.pending('owner')['state'],'filled')
                    receipt=store.db.execute("SELECT output FROM steps WHERE kind='private_input'").fetchone();self.assertIsNotNone(receipt)
                    self.assertEqual(json.loads(receipt[0]),dict(filled=True,continuation_clicked=False,owner_approved=True))
                    self.assertEqual(store.db.execute("SELECT verified FROM task_events WHERE action='private_input'").fetchone()[0],1)
                finally:stop.set();thread.join(3);store.db.close()


if __name__=='__main__':unittest.main()
