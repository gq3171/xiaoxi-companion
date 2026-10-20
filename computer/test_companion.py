"""Replay the life loop with real SQLite/native memory, no actual audio or users."""
import json
import sqlite3
import unittest
import test_brain as fixtures

brain=fixtures.brain

class CompanionTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.BrainTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.BrainTests.tearDownClass.__func__)
    setUp=fixtures.BrainTests.setUp
    tearDown=fixtures.BrainTests.tearDown
    add=fixtures.BrainTests.add

    def receipt(self, trace, stage, source=0, op='7'*32):
        return self.store.mutate(self.env|{'operation':dict(kind='feedback',op_id=op,trace=trace,stage=stage,source_id=source)})

    def propose(self, candidate, **fields):
        return self.store.propose(self.env|{'kind':'dialogue','microphone':True},(dict(input='direct',action='speak',say='好的')|fields),candidate)['_trace']

    def reflection(self, extra, op='6'*32):
        return self.store.mutate(self.env|{'operation':dict(kind='reflection',op_id=op,json=json.dumps(dict(ops=[],growth_ops=[])|extra))})

    def test_unaccepted_background_and_retry_do_not_change_emotion_or_create_facts(self):
        before=self.store.companion_context()['affect'];self.store.companion.clock=lambda:10000
        with self.store.lock,self.store.db:self.store.companion.shift()
        before=self.store.companion_context()['affect']
        reply=self.store.propose(self.env|{'kind':'dialogue','microphone':True},dict(input='background',action='ignore'), '电视对白')
        self.assertNotIn('_trace',reply)
        trace=self.propose('一起聊星星',shared_thread=dict(topic='聊聊星星',kind='shared_activity',source_quote='一起聊星星'))
        self.assertEqual(before,self.store.companion_context()['affect'])
        self.assertEqual(self.receipt(trace,'accepted',999)['result'],0)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM companion_threads').fetchone()[0],0)
        source=self.add('一起聊星星')['result'];r=self.receipt(trace,'accepted',source,'8'*32)
        self.assertEqual(r['result'],1);self.assertTrue(self.receipt(trace,'accepted',source,'8'*32)['duplicate'])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM companion_threads').fetchone()[0],1)
        self.assertEqual(self.store.db.execute('SELECT status FROM companion_threads').fetchone()[0],'open')
        changed=self.store.companion_context()['affect'];self.receipt(trace,'accepted',source,'9'*32)
        self.assertEqual(changed,self.store.companion_context()['affect'])

    def test_affect_persists_decays_and_only_continuous_reported_rest_restores_energy(self):
        now=[10000];self.store.companion.clock=lambda:now[0]
        with self.store.lock,self.store.db:self.store.companion.shift(energy=-35,curiosity=20)
        self.store.state(self.env|{'parts':{'feedback':dict(uptime_ms=1000,activity=3)}})
        initial=self.store.companion.affect()['energy'];now[0]+=30
        self.store.state(self.env|{'parts':{'feedback':dict(uptime_ms=31000,activity=3)}})
        self.assertGreater(self.store.companion.affect()['energy'],initial)
        saved=self.store.companion.affect()
        other=brain.BrainStore(self.store.path,brain.NativeMemory(self.library));other.companion.clock=lambda:now[0]
        try:self.assertEqual(other.companion.affect(),saved)
        finally:other.db.close()
        now[0]+=7*86400
        self.store.state(self.env|{'parts':{'feedback':dict(uptime_ms=62000,activity=3)}})
        neutral=self.store.companion.affect()
        self.assertAlmostEqual(neutral['energy'],65,delta=.01)
        self.assertAlmostEqual(neutral['curiosity'],55,delta=.01)

    def test_shared_life_closes_only_after_fresh_matching_actual_completion_and_replay_is_inert(self):
        now=[10000];self.store.companion.clock=lambda:now[0]
        trace=self.propose('洗漱后到窗边看看',shared_thread=dict(topic='洗漱后看窗外',kind='shared_activity',source_quote='洗漱后到窗边'),life_plan=dict(goal='洗漱后看窗外',steps=['wash','window']))
        source=self.add('洗漱后到窗边看看')['result'];self.receipt(trace,'accepted',source)
        plan=dict(goal='洗漱后看窗外',steps=['wash','window'],created=10000,by_owner=True,index=0)
        def state(p,j):return self.store.state(self.env|{'parts':{'life':dict(plan=p,journal=j)}})
        state(plan,[]);self.assertEqual(self.store.db.execute('SELECT status FROM companion_threads').fetchone()[0],'open')
        stale=dict(goal=plan['goal'],step='window',epoch=9000)
        state(plan|dict(index=2),[stale]);self.assertEqual(self.store.db.execute('SELECT status FROM companion_threads').fetchone()[0],'open')
        now[0]+=60;journal=[dict(goal=plan['goal'],step='wash',epoch=10020),dict(goal=plan['goal'],step='window',epoch=10060)]
        state(plan|dict(index=2),journal);self.assertEqual(self.store.db.execute('SELECT status FROM companion_threads').fetchone()[0],'completed')
        affect=self.store.companion_context()['affect'];events=self.store.db.execute('SELECT count(*) FROM companion_events').fetchone()[0]
        state(plan|dict(index=2),journal);self.assertEqual(affect,self.store.companion_context()['affect'])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM companion_events').fetchone()[0],events)

    def test_experience_review_requires_delivered_trial_and_later_real_owner_evidence(self):
        source=self.add('请不要每句话都追问')['result']
        self.reflection({'growth_ops':[dict(op='upsert',kind='style',slot='少追问',text='回答后留白',trigger='日常聊天',check='不机械追问',basis='correction',source_ids=[source])]})
        rule=self.store.companion.rules(self.store.snapshot()['memory'],'日常聊天')[0]
        trace=self.propose('你在做什么',lesson_use=[rule['id']]);sid=self.add('你在做什么','c'*32,owner=False)['result'];self.receipt(trace,'accepted',sid)
        feedback=self.add('还是每句话都追问，又问我了','d'*32)['result']
        review=dict(trial_id=trace,lesson_id=rule['id'],verdict='repeated',source_id=feedback,source_quote='还是每句话都追问',reason='回答后仍机械追问')
        self.reflection({'growth_reviews':[review]},'e'*32);self.assertEqual(self.store.db.execute('SELECT count(*) FROM companion_checks').fetchone()[0],0)
        self.receipt(trace,'played',op='f'*32)
        self.reflection({'growth_reviews':[review|dict(source_id=999),review|dict(lesson_id='invented'),review]},'0'*32)
        self.assertEqual(self.store.db.execute('SELECT verdict FROM companion_checks').fetchone()[0],'repeated')
        self.reflection({'growth_reviews':[review]},'1'*32);self.assertEqual(self.store.db.execute('SELECT count(*) FROM companion_checks').fetchone()[0],1)
        evidence=self.store.companion.review_context(self.store.snapshot()['memory']);self.assertEqual(evidence['trials'][0]['delivery'],'played')
        self.reflection({'growth_reviews':[dict(source_id={}),review|dict(source_quote='我已经改好了',verdict='improved')]},'2'*32)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM companion_checks').fetchone()[0],1)

    def test_claimed_computer_success_is_not_actual_executor_success(self):
        self.store.companion.clock=lambda:10000
        trace=self.propose('帮我检查文件',action='computer_task',task='检查文件',shared_thread=dict(topic='检查文件',kind='agreement',source_quote='检查文件'))
        source=self.add('帮我检查文件')['result'];self.receipt(trace,'accepted',source)
        computer=dict(job_id='a'*32,goal='检查文件',state='succeeded',_verified_state='succeeded')
        self.store.state(self.env|{'parts':{'computer':computer}})
        self.assertEqual(self.store.db.execute('SELECT status FROM companion_threads').fetchone()[0],'open')
        jobs=sqlite3.connect(self.store.path.with_name('jobs.sqlite3'));jobs.execute('CREATE TABLE jobs(id TEXT,state TEXT,goal TEXT,created INTEGER)');jobs.execute('INSERT INTO jobs VALUES(?,?,?,?)',('a'*32,'succeeded','检查文件',10000));jobs.commit();jobs.close()
        self.store.state(self.env|{'parts':{'computer':computer}})
        self.assertEqual(self.store.db.execute('SELECT status FROM companion_threads').fetchone()[0],'completed')

    def test_delayed_receipt_keeps_intention_before_actual_execution(self):
        now=[10000];self.store.companion.clock=lambda:now[0]
        trace=self.propose('洗漱后看窗外',shared_thread=dict(topic='洗漱后看窗外',kind='shared_activity',source_quote='洗漱后看窗外'),life_plan=dict(goal='看窗外',steps=['wash','window']))
        source=self.add('洗漱后看窗外')['result']
        now[0]+=40  # A long reply/reconnection delays the durable acceptance receipt.
        self.receipt(trace,'accepted',source)
        self.assertEqual(self.store.db.execute('SELECT created FROM companion_threads').fetchone()[0],10000)
        plan=dict(goal='看窗外',steps=['wash','window'],created=10002,by_owner=True,index=2)
        self.store.state(self.env|{'parts':{'life':dict(plan=plan,journal=[dict(goal='看窗外',step='window',epoch=10030)])}})
        self.assertEqual(self.store.db.execute('SELECT status FROM companion_threads').fetchone()[0],'completed')

    def test_explicit_forget_removes_derived_shared_threads_and_trials(self):
        source=self.add('我们约好以后聊星星')['result']
        self.reflection({'ops':[dict(op='upsert',kind='commitment',slot='星星',text='以后聊星星',importance=3,source_id=source)]})
        trace=self.propose('我们约好以后聊星星',shared_thread=dict(topic='聊星星',kind='agreement',source_quote='以后聊星星'))
        self.receipt(trace,'accepted',source)
        forget=self.add('请忘记约好聊星星这件事','c'*32)['result']
        self.reflection({'ops':[dict(op='forget',kind='commitment',slot='星星',source_id=forget)]},'d'*32)
        for table in ('companion_turns','companion_threads','companion_events','companion_checks'):
            self.assertEqual(self.store.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

if __name__=='__main__':unittest.main()
