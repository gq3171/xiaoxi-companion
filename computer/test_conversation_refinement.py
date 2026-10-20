"""Conversation, delivery and learning with actual SQLite/native reducer."""
import json
import threading
import time
import unittest
import test_brain as fixtures
from interaction import normalize, yield_requested, Preferences, dialogue_messages
from result_delivery import spoken_result

brain=fixtures.brain

class InteractionTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.BrainTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.BrainTests.tearDownClass.__func__)
    setUp=fixtures.BrainTests.setUp
    tearDown=fixtures.BrainTests.tearDown
    add=fixtures.BrainTests.add

    def receipt(self, trace, stage, source=0, op='7'*32):
        return self.store.mutate(self.env|{'operation':dict(kind='feedback',op_id=op,trace=trace,stage=stage,source_id=source)})

    def preference(self, candidate, **fields):
        value=dict(slot='followup',text='回答后适当留白',trigger='日常聊天',check='不机械追问',source_quote=candidate)
        value.update(fields);return value

    def proposal(self, candidate, update, remember=True):
        return self.store.propose(self.env|{'kind':'dialogue','microphone':True},
             dict(input='direct',action='speak',say='嗯，明白。',remember=remember,behavior_update=update),candidate)['_trace']

    def test_aside_or_uncertain_is_stripped_before_search_or_memory(self):
        for i, addressing in enumerate(('aside','uncertain')):
            p=fixtures.FakeProvider([json.dumps(dict(input='direct',addressing=addressing,action='search',query='外部任务',remember=True,home_action='rest',behavior_update=self.preference('全部写完了')))])
            service=brain.Brain(self.store,p,'x'*48)
            self.addCleanup(service.diagnostics.db.close)
            reply=brain.parse_answer(service.model(self.env|dict(kind='dialogue',candidate='全部写完了',microphone=True,system=''))['text'])
            self.assertEqual(reply['action'],'ignore');self.assertNotIn('home_action',reply)
            self.assertFalse(p.searches);self.assertNotIn('_trace',reply)
        self.assertFalse(self.store.snapshot()['memory']['history'])

    def test_short_ack_and_direct_topic_switch_keep_existing_actions(self):
        for candidate in ('嗯','好的','你今天想干什么','帮我画一个小鸡'):
            value=normalize(dict(input='direct',addressing='to_pet',action='speak',say='嗯。'),candidate,True)
            self.assertEqual(value['action'],'speak')
        self.assertTrue(yield_requested('刚刚不是和你说话，刚刚是和别人说话。'))
        value=normalize(dict(input='direct',action='speak',conversation_action='yield'),'刚才不是跟你说话',True)
        self.assertEqual(value['conversation_action'],'yield')
        for candidate,extra in [('我喜欢你说话',{}),('刚才不是跟你说话，现在帮我画画',{'action':'computer_task'})]:
            value=normalize(dict(input='direct',action='speak',conversation_action='yield')|extra,candidate,True)
            self.assertNotIn('conversation_action',value)

    def test_wire_history_is_json_and_preference_budget_never_cuts_a_condition(self):
        messages=dialogue_messages([dict(role='assistant',content='你呢？')],'换个话题')
        self.assertEqual(json.loads(messages[0]['content'])['say'],'你呢？')
        self.assertEqual(json.loads(messages[-1]['content'])['candidate'],'换个话题')
        value=self.preference('以后喜欢水墨',check='下次绘画任务默认采用淡彩水墨风，并写入任务要求；本次有其他风格要求时以本次为准')
        self.assertEqual(Preferences.prepare(value,'以后喜欢水墨')['check'],'下次绘画任务默认采用淡彩水墨风，并写入任务要求')
        self.assertIsNone(Preferences.prepare(value|dict(check='甲'*100),'以后喜欢水墨'))

    def test_preference_requires_accepted_matching_owner_source_and_quote(self):
        text='以后别每句话都追问'
        trace=self.proposal(text,self.preference(text))
        self.assertFalse(self.store.companion.rules(self.store.snapshot()['memory'],'日常聊天'))
        self.receipt(trace,'accepted',999)
        self.assertFalse(self.store.companion.rules(self.store.snapshot()['memory'],'日常聊天'))
        source=self.add(text)['result'];self.receipt(trace,'accepted',source,op='8'*32)
        saved=self.store.companion.rules(self.store.snapshot()['memory'],'日常聊天');self.assertEqual(len(saved),1)
        self.receipt(trace,'accepted',source,op='9'*32)
        self.assertEqual(saved,self.store.companion.rules(self.store.snapshot()['memory'],'日常聊天'))
        self.assertEqual(saved[0]['text'],'回答后适当留白')
        other=brain.BrainStore(self.store.path,brain.NativeMemory(self.library))
        try:self.assertEqual(saved,other.companion.rules(other.snapshot()['memory'],'日常聊天'))
        finally:other.db.close()

    def test_unowned_bad_quote_and_one_turn_no_remember_cannot_persist(self):
        for n,owner,remember,quote in [(1,False,True,'以后少追问'),(2,True,False,'以后少追问'),(3,True,True,'编造支持')]:
            text='以后少追问'
            trace=self.proposal(text,self.preference(quote),remember)
            source=self.add(text,op_id=str(n)*32,owner=owner)['result']
            self.receipt(trace,'accepted',source,op=str(n+3)*32)
        self.assertFalse(self.store.companion.rules(self.store.snapshot()['memory'],'日常聊天'))

    def test_later_preference_wins_even_when_old_acceptance_arrives_last(self):
        old='以后简短回答';new='认真解释时可以详细一点'
        one=self.proposal(old,self.preference(old,slot='speech_detail',text='简单回答'))
        sid1=self.add(old)['result']
        two=self.proposal(new,self.preference(new,slot='speech_detail',text='解释时展开'))
        sid2=self.add(new,'c'*32)['result']
        self.receipt(two,'accepted',sid2);self.receipt(one,'accepted',sid1,op='8'*32)
        rules=self.store.companion.rules(self.store.snapshot()['memory'],'解释')
        self.assertEqual(len(rules),1);self.assertEqual(rules[0]['text'],'解释时展开')

    def test_new_preference_is_used_and_feedback_is_evidence_checked(self):
        text='以后不要每句话都追问'
        trace=self.proposal(text,self.preference(text));source=self.add(text)['result'];self.receipt(trace,'accepted',source)
        rule=self.store.companion.rules(self.store.snapshot()['memory'],'日常聊天')[0]
        answer=self.store.propose(self.env|{'kind':'dialogue','microphone':True},dict(input='direct',action='speak',say='我在看书。',lesson_use=[rule['id']]),'你在做什么')
        source2=self.add('你在做什么','c'*32,owner=False)['result'];self.receipt(answer['_trace'],'accepted',source2,'8'*32);self.receipt(answer['_trace'],'played',op='9'*32)
        evidence=self.store.companion.review_context(self.store.snapshot()['memory'])
        self.assertEqual(evidence['trials'][0]['rules'][0]['id'],rule['id'])
        correction=self.add('现在好多了，没有再追问','d'*32)['result']
        response=dict(ops=[],growth_ops=[],growth_reviews=[dict(trial_id=answer['_trace'],lesson_id=rule['id'],verdict='improved',source_id=correction,source_quote='没有再追问',reason='相关回答留出了空隙')])
        self.store.mutate(self.env|{'operation':dict(kind='reflection',op_id='e'*32,json=json.dumps(response))})
        self.assertEqual(self.store.db.execute('SELECT verdict FROM companion_checks').fetchone()[0],'improved')
        self.assertEqual(self.store.companion_context('日常聊天')['practice'][0]['owner_feedback']['improved'],1)

    def test_real_forget_path_clears_new_preferences_and_trials(self):
        text='以后不要每句话都追问';trace=self.proposal(text,self.preference(text));sid=self.add(text)['result'];self.receipt(trace,'accepted',sid)
        forgot=self.add('请忘记followup这个偏好','c'*32)['result']
        self.store.mutate(self.env|{'operation':dict(kind='reflection',op_id='d'*32,json=json.dumps({'ops':[],'growth_ops':[dict(op='forget',kind='style',slot='followup',source_ids=[forgot])]}))})
        self.assertFalse(self.store.companion.rules(self.store.snapshot()['memory'],'日常聊天'))
        self.assertFalse(self.store.db.execute('SELECT 1 FROM companion_turns').fetchone())

    def test_protocol_two_tts_http_relays_ordered_audio_with_one_real_terminal(self):
        import io
        from http.server import ThreadingHTTPServer
        from urllib.request import Request,urlopen
        import agent
        requests=[]
        provider=fixtures.FakeProvider()
        def upstream(path,body):
            requests.append(json.loads(body))
            return io.BytesIO(b'data: {"data":{"status":1,"audio":"00000100"}}\n\ndata: {"data":{"status":2,"audio":""}}\n\n')
        provider.request=upstream
        service=brain.Brain(self.store,provider,'x'*48);self.addCleanup(service.diagnostics.db.close)
        jobs=agent.Store(self.store.path.with_name('jobs.sqlite3'))
        server=ThreadingHTTPServer(('127.0.0.1',0),agent.handler(jobs,'y'*48,lambda:True,service))
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        speech=dict(model='speech-2.8-turbo',text='甲'*70,stream=True,voice_setting={'voice_id':'female-shaonv'},audio_setting={'sample_rate':16000,'format':'pcm','channel':1})
        try:
            req=Request(f'http://127.0.0.1:{server.server_port}/v1/brain/tts',brain.encode(self.env|dict(speech=speech,tts_protocol=2)),{'Authorization':'Bearer '+'x'*48})
            with urlopen(req,timeout=3) as response:raw=response.read()
            events=[json.loads(line[6:]) for line in raw.splitlines() if line.startswith(b'data: ')]
            count=2 if hasattr(service,'speech_pipeline') else 1
            self.assertEqual(len(requests),count)
            self.assertEqual([e['data']['status'] for e in events],[1]*count+[2])
            self.assertEqual(''.join(r['text'] for r in requests),speech['text'])
            deadline=time.monotonic()+1
            summary=service.diagnostics.summary()
            while 'tts' not in summary['kinds'] and time.monotonic()<deadline:
                time.sleep(.01);summary=service.diagnostics.summary()
            self.assertEqual(summary['kinds']['tts']['samples'],1)
            self.assertFalse(summary['contents_recorded'])
        finally:server.shutdown();server.server_close();worker.join(3);jobs.db.close()

    def test_foreground_inference_is_not_queued_behind_background_provider(self):
        started=threading.Event();release=threading.Event();seen=[]
        class Slow:
            key='test'
            def complete(self,system,messages,reflection=False,live=None):
                if messages[-1]['content']=='slow-plan':
                    started.set();release.wait(3)
                    if not live():raise brain.Conflict('yielded')
                    return '{"action":"wait","text":""}'
                return '{"input":"direct","action":"speak","say":"嗯。"}'
        service=brain.Brain(self.store,Slow(),'x'*48)
        self.addCleanup(service.diagnostics.db.close)
        def background():
            try:service.model(self.env|dict(kind='plan',request='slow-plan',system=''))
            except Exception as error:seen.append(type(error).__name__)
        worker=threading.Thread(target=background);worker.start();self.assertTrue(started.wait(2))
        try:
            start=time.monotonic();answer=service.model(self.env|dict(kind='dialogue',candidate='你好',microphone=True,system=''))
            self.assertLess(time.monotonic()-start,.8)
            self.assertEqual(brain.parse_answer(answer['text'])['say'],'嗯。')
        finally:release.set();worker.join(4)
        self.assertFalse(worker.is_alive());self.assertIn('queue_admitted',json.loads(service.diagnostics.db.execute("SELECT phases FROM timings WHERE kind='dialogue'").fetchone()[0]))

class ResultTests(unittest.TestCase):
    def test_real_success_visual_gets_short_notice_and_failure_keeps_reason(self):
        item=dict(state='succeeded',message='PNG文件可读，尺寸1024x768，完整解码验证',media=[dict(kind='image',title='圆滚滚的小鸡')])
        self.assertEqual(spoken_result(item),'《圆滚滚的小鸡》做好啦。')
        self.assertEqual(item['message'],'PNG文件可读，尺寸1024x768，完整解码验证')
        self.assertEqual(spoken_result(item|dict(state='failed',message='程序失败')), '程序失败')
        self.assertEqual(spoken_result(item|dict(media=[])),item['message'])

if __name__=='__main__':unittest.main()
