import json
import unittest
import test_brain as fixtures
import self_model


class SelfModelTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.BrainTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.BrainTests.tearDownClass.__func__)
    setUp=fixtures.BrainTests.setUp
    tearDown=fixtures.BrainTests.tearDown
    add=fixtures.BrainTests.add

    def profile(self):return tuple(self.store.db.execute('SELECT gender,revision,source_id FROM self_profile').fetchone())
    def proposal(self,text,**fields):return self.store.propose(self.env|dict(kind='dialogue',microphone=True),dict(input='direct',action='speak',say='好')|fields,text)
    def accept(self,trace,source,op='7'*32):return self.store.mutate(self.env|dict(operation=dict(kind='feedback',op_id=op,trace=trace,stage='accepted',source_id=source)))
    def test_default_survives_reopen_and_does_not_invent_age(self):
        self.assertEqual(self.profile(),('female',1,0))
        context=self_model.context(self.store.db,self.store.snapshot()['identity'])
        self.assertIn('未设定',context);self.assertIn('female',context)
        other=fixtures.brain.BrainStore(self.store.path,fixtures.brain.NativeMemory(self.library))
        try:self.assertEqual(tuple(other.db.execute('SELECT gender,revision,source_id FROM self_profile').fetchone()),self.profile())
        finally:other.db.close()
    def test_owner_edit_commits_only_after_accepted_source_and_replay_is_inert(self):
        text='以后你的性别设定改为男生吧'
        proposal=self.proposal(text,self_update=dict(gender='male',source_quote='性别设定改为男生'))
        self.assertEqual(self.profile(),('female',1,0))
        sid=self.add(text)['result'];self.accept(proposal['_trace'],sid)
        self.assertEqual(self.profile(),('male',2,sid))
        self.accept(proposal['_trace'],sid,'8'*32);self.assertEqual(self.profile(),('male',2,sid))
    def test_background_unowned_source_bad_quote_and_mismatched_source_cannot_edit(self):
        result=self.store.propose(self.env|dict(kind='dialogue',microphone=True),dict(input='background',action='ignore',self_update=dict(gender='male',source_quote='男生')),'电视里的男生')
        self.assertNotIn('_trace',result)
        for i,(owner,quote,matched) in enumerate(((False,'男生',True),(True,'原文不存在的内容',True),(True,'男生',False))):
            text='把你的角色改为男生'+str(i)
            p=self.proposal(text,self_update=dict(gender='male',source_quote=quote))
            sid=self.add(text if matched else '另一句话',format(i+10,'032x'),owner=owner)['result']
            self.accept(p['_trace'],sid,format(i+20,'032x'))
            self.assertEqual(self.profile(),('female',1,0))
    def test_model_sees_actual_identity_and_environment_without_claiming_vision(self):
        provider=fixtures.FakeProvider([json.dumps(dict(input='direct',action='speak',say='我在房间里'))])
        service=fixtures.brain.Brain(self.store,provider,'x'*48)
        try:
            service.model(self.env|dict(kind='dialogue',candidate='你是谁',system='实际位置=床边；音量=0',microphone=True))
            # FakeProvider's recorded field differs between old and v2 fixtures;
            # direct context above tests persistence, real-model routing is separate.
            self.assertIn('实际位置=床边',provider.prompts[0][0])
            self.assertIn('持续自我档案',provider.prompts[0][0])
            self.assertIn('没有摄像头视觉',provider.prompts[0][0])
            self.assertIn('320x240',__import__('media').BRAIN_RULE)
        finally:
            if hasattr(service,'diagnostics'):service.diagnostics.db.close()
