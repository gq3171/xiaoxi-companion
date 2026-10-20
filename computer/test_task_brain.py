"""Prepared task/chat isolation checks, not run during quiet hours."""
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
import test_brain as fixtures
import test_agent as tasks

brain=fixtures.brain

class TaskBrainTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.BrainTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.BrainTests.tearDownClass.__func__)
    setUp=fixtures.BrainTests.setUp
    tearDown=fixtures.BrainTests.tearDown
    def test_background_job_and_new_chat_are_independent_and_only_explicit_cancel_stops_job(self):
        computer=tasks.agent.Store(self.store.path.with_name('jobs.sqlite3'))
        entered,release=threading.Event(),threading.Event()
        def slow_task_model(messages):
            entered.set()
            if not release.wait(5):raise RuntimeError('fixture timeout')
            return {'action':'finish','state':'failed','message':'夹具结束'}
        worker=tasks.agent.Worker(computer,model=slow_task_model)
        provider=fixtures.FakeProvider([json.dumps({'input':'direct','action':'speak','say':'任务在后台继续，我们可以聊天。','remember':False})])
        service=brain.Brain(self.store,provider,'x'*48,computer=computer)
        server=ThreadingHTTPServer(('127.0.0.1',0),tasks.agent.handler(computer,'y'*48,lambda:True,service))
        listener=threading.Thread(target=server.serve_forever,daemon=True);listener.start()
        executor=None
        def rpc(path,payload,token):
            request=Request(f'http://127.0.0.1:{server.server_port}/v1/'+path,json.dumps(payload).encode(),{'Authorization':'Bearer '+token})
            with urlopen(request,timeout=3) as response:return json.load(response)
        try:
            job_id='b'*32
            rpc('computer/submit',{'job_id':job_id,'goal':'并行任务夹具'},'y'*48)
            executor=threading.Thread(target=worker.run_job,args=(computer.next(),),daemon=True);executor.start()
            self.assertTrue(entered.wait(2))
            result=rpc('brain/model',self.env|dict(generation=2,kind='dialogue',candidate='我们继续聊别的',microphone=True,system=''), 'x'*48)
            self.assertIn('可以聊天',brain.parse_answer(result['text'])['say'])
            self.assertTrue(executor.is_alive());self.assertFalse(release.is_set())
            self.assertEqual(computer.get(job_id)['state'],'running');self.assertFalse(computer.get(job_id)['cancel'])
            rpc('computer/cancel',{'job_id':job_id},'y'*48)
            release.set();executor.join(3)
            self.assertFalse(executor.is_alive());self.assertEqual(computer.get(job_id)['state'],'cancelled')
        finally:
            release.set()
            if executor:executor.join(3)
            server.shutdown();server.server_close();listener.join()
            service.diagnostics.db.close();computer.db.close()


if __name__=='__main__':unittest.main()
