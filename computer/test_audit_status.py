"""Task enquiries read the live store and never dispatch or rewrite jobs."""
import json
import unittest
import test_brain as fixtures
import test_agent as tasks

brain=fixtures.brain


class AuditStatusTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.BrainTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.BrainTests.tearDownClass.__func__)
    setUp=fixtures.BrainTests.setUp
    tearDown=fixtures.BrainTests.tearDown

    def test_error_enquiry_uses_current_record_and_leaves_jobs_unchanged(self):
        computer=tasks.agent.Store(self.store.path.with_name('jobs.sqlite3'))
        service=None
        try:
            job='b'*32
            computer.submit(job,'浏览器查询夹具')
            computer.next();computer.update(job,'failed','旧的笼统报错')
            computer.update(job,'failed','查询未完成；旧记录未保留具体异常。')
            before=list(computer.db.iterdump())
            provider=fixtures.FakeProvider([json.dumps(dict(input='direct',action='computer_status',job_id=job))])
            service=brain.Brain(self.store,provider,'x'*48,computer=computer)
            result=brain.parse_answer(service.model(self.env|dict(kind='dialogue',candidate='服务器返回什么错误？',microphone=True,system='旧的笼统报错'))['text'])
            self.assertEqual(result['action'],'speak')
            self.assertIn('旧记录未保留具体异常',result['say'])
            self.assertNotIn('旧的笼统报错',result['say'])
            self.assertFalse(result['remember'])
            self.assertEqual(before,list(computer.db.iterdump()))
            self.assertEqual(provider.searches,[])
        finally:
            if service and hasattr(service,'diagnostics'):service.diagnostics.db.close()
            computer.db.close()

    def test_background_and_invalid_ids_never_query_tasks(self):
        class Unreadable:
            def __getattribute__(self,name):
                if name=='media':return None # Independent media catalog is optional.
                raise AssertionError('task store must not be read')
        provider=fixtures.FakeProvider([json.dumps(dict(input='background',action='computer_status'))])
        service=brain.Brain(self.store,provider,'x'*48,computer=Unreadable())
        try:
            # Canonical v2 includes read-only task context on every dialogue;
            # this check isolates the status path from that separate feature.
            service.computer_context=lambda:[]
            result=brain.parse_answer(service.model(self.env|dict(kind='dialogue',candidate='电视台词',microphone=True,system=''))['text'])
            self.assertNotEqual(result.get('action'),'speak')
            self.assertIn('没有核对',service.computer_status({'job_id':"' OR 1=1"}))
            self.assertEqual(self.store.snapshot()['memory']['history'],[])
        finally:
            if hasattr(service,'diagnostics'):service.diagnostics.db.close()


if __name__=='__main__':unittest.main()
