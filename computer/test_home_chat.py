"""Web and real native brain sharing, independent admission, and audio contracts."""
import io,json,secrets,tempfile,threading,time,unittest,wave,zlib
from pathlib import Path
from types import SimpleNamespace
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import agent,brain,home_sync as home,home_chat
import test_brain as native_fixture
import test_home_sync as scene_fixture

class Provider:
    key='test-only'
    def __init__(self):self.calls=0;self.responses=[];self.audio_calls=0;self.wait=None;self.entered=threading.Event()
    def complete(self,*args,**kwargs):
        self.calls+=1;self.entered.set()
        if self.wait:self.wait.wait(4)
        return json.dumps(self.responses.pop(0) if self.responses else dict(input='direct',remember=True,action='speak',say='好呀，我记得。',mood='happy'))
    def search(self,q):return []
    def request(self,path,body,*args):
        self.audio_calls+=1
        if path.endswith('speech_to_text'):return io.BytesIO(json.dumps(dict(text='你好小溪',base_resp=dict(status_code=0))).encode())
        return io.BytesIO(json.dumps(dict(data=dict(audio=(b'\0\0'*1600).hex()),base_resp=dict(status_code=0))).encode())

class HomeChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        native_fixture.BrainTests.setUpClass();scene_fixture.HomeSyncTests.setUpClass()
    @classmethod
    def tearDownClass(cls):native_fixture.BrainTests.tearDownClass();scene_fixture.HomeSyncTests.tearDownClass()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.memory=brain.BrainStore(self.root/'brain.sqlite3',brain.NativeMemory(native_fixture.BrainTests.library))
        self.body=dict(device='001122334455',boot=5,session='a'*32,generation=1)
        raw=brain.encode(brain.empty_memory()).decode();self.memory.open(self.body|dict(memory_raw=raw,memory_crc=zlib.crc32(raw.encode()),identity_raw='{"name":"小溪","soul":"逐渐成长"}'))
        self.computer=agent.Store(self.root/'jobs.sqlite3');self.provider=Provider();self.brain=brain.Brain(self.memory,self.provider,'t'*48,self.computer)
        self.world=home.HomeWorld(self.root/'home-sync.json',scene_fixture.HomeSyncTests.library,self.root/'assets',start=False)
        token=self.world.login(self.world.pair_code()['code']);self.cookie='xiaoxi_home='+token;self.session=self.world.session(SimpleNamespace(headers={'Cookie':self.cookie}))
        self.chat=home_chat.HomeChat(self.world,self.brain,self.computer,self.root/'web-chat.sqlite3');self.world.chat=self.chat
    def tearDown(self):
        self.chat.stop.set()
        if self.provider.wait:self.provider.wait.set()
        for thread in list(self.chat.threads):thread.join(5)
        self.world.close();self.brain.diagnostics.db.close();self.memory.db.close();self.computer.db.close();self.tmp.cleanup()
    def start(self,text='我喜欢温暖的小房间',**kwargs):
        data=dict(id=secrets.token_hex(16),text=text)|kwargs;self.chat.start(self.session,data);return data
    def finished(self):
        end=time.monotonic()+5
        while time.monotonic()<end:
            rows=self.chat.history(self.session)
            if rows and rows[-1]['state']!='working':return rows[-1]
            time.sleep(.01)
        self.fail('web chat did not finish')
    def test_room_snapshot_does_not_wait_for_brain_write_and_refreshes_name_later(self):
        # A web receipt holds the brain lock while rechecking room authorization.
        # Concurrent room snapshots must never wait for that lock in reverse.
        key=str(self.computer.media.root.resolve())
        previous=home._instances.get(key)
        home._instances[key]=self.world
        self.world.desktop=object()
        finished=threading.Event();result=[];errors=[]
        def snapshot():
            try:result.append(self.world.snapshot())
            except Exception as error:errors.append(error)
            finally:finished.set()
        worker=None
        try:
            home.for_store(self.computer,self.brain)
            self.assertEqual(self.world.snapshot()['name'],'小溪')
            with self.memory.lock:
                with self.memory.db:
                    self.memory.db.execute('UPDATE device SET identity=?',('{"name":"溪溪"}',))
                worker=threading.Thread(target=snapshot,daemon=True);worker.start()
                completed_while_brain_busy=finished.wait(1)
                # Exercise the same authorization recheck only if the room lock
                # is available; never leave an intentionally deadlocked fixture.
                if completed_while_brain_busy:
                    facade,request=self.chat.envelope(self.session,'c'*32)
                    self.assertTrue(facade.admit(request))
            worker.join(2)
            self.assertTrue(completed_while_brain_busy,'room snapshot blocked on brain write lock')
            self.assertFalse(worker.is_alive());self.assertFalse(errors)
            self.assertEqual(result[0]['name'],'小溪')
            self.assertEqual(self.world.snapshot()['name'],'溪溪')
        finally:
            if worker:worker.join(2)
            if previous is None:home._instances.pop(key,None)
            else:home._instances[key]=previous

    def test_concurrent_receipts_room_sync_and_page_requests_keep_http_available(self):
        from concurrent.futures import ThreadPoolExecutor
        from http_tls_server import ThreadedTLSServer
        self.start();turn=self.finished()['id']
        key=str(self.computer.media.root.resolve());previous=home._instances.get(key)
        home._instances[key]=self.world;self.world.desktop=object()
        server=ThreadedTLSServer(('127.0.0.1',0),agent.handler(self.computer,'test-token',lambda:True,self.brain))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(index):
            connection=HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            try:
                if index%3==0:
                    connection.request('POST','/home/api/chat/receipt',json.dumps({'id':turn}),
                        {'Cookie':self.cookie,'Content-Type':'application/json','Origin':'https://127.0.0.1:'+str(server.server_port)})
                else:
                    connection.request('GET','/home/api/state' if index%3==1 else '/home/',headers={'Cookie':self.cookie})
                response=connection.getresponse();response.read();return response.status
            finally:connection.close()
        try:
            with ThreadPoolExecutor(max_workers=12) as clients:
                self.assertEqual(list(clients.map(request,range(120))),[200]*120)
            self.assertTrue(self.chat.authorized(self.session))
        finally:
            server.shutdown();server.server_close();thread.join(2)
            if previous is None:home._instances.pop(key,None)
            else:home._instances[key]=previous

    def test_model_uses_real_identity_shared_memory_and_never_changes_body_envelope(self):
        before=dict(self.memory.row());self.start();row=self.finished();self.assertEqual(row['state'],'done');self.assertEqual(row['reply']['say'],'好呀，我记得。')
        after=dict(self.memory.row());self.assertEqual([after[k] for k in ('device','boot','session','generation')],[before[k] for k in ('device','boot','session','generation')])
        self.assertTrue(any('温暖' in item['content'] for item in self.memory.query('小房间')['history']));self.assertEqual(self.memory.snapshot()['identity']['name'],'小溪')
        self.chat.receipt(self.session,row['id']);self.assertEqual(self.memory.db.execute('SELECT delivery FROM companion_turns').fetchone()[0],'displayed')
        self.chat.receipt(self.session,row['id']);self.assertEqual(self.memory.db.execute("SELECT count(*) FROM operations WHERE op_id=?",(home_chat.op_id(row['id'],'feedback:displayed'),)).fetchone()[0],1)
    def test_retry_is_idempotent_and_foreign_session_cannot_read_or_reuse_turn(self):
        data=self.start();row=self.finished();self.chat.start(self.session,data);self.assertEqual(self.provider.calls,1)
        with self.assertRaises(ValueError):self.chat.start(self.session,data|dict(text='另一个请求'))
        with self.assertRaises(PermissionError):self.chat.start('f'*64,data)
        self.assertEqual(self.chat.history('f'*64),[])
        with self.assertRaises(ValueError):self.chat.receipt('f'*64,row['id'])
    def test_live_body_generation_and_web_turn_do_not_cancel_each_other(self):
        self.provider.wait=threading.Event();self.start();self.assertTrue(self.provider.entered.wait(2));self.memory.admit(self.body|dict(generation=2));self.provider.wait.set()
        self.assertEqual(self.finished()['state'],'done');self.assertTrue(self.memory.live(self.body|dict(generation=2)))
    def test_revocation_blocks_late_model_commit_and_actions(self):
        self.provider.wait=threading.Event();self.provider.responses=[dict(input='direct',remember=True,action='computer_task',task='只在测试库排队',say='好')]
        self.start();self.assertTrue(self.provider.entered.wait(2));self.world.logout(self.session);self.provider.wait.set();self.finished()
        self.assertFalse(self.memory.db.execute('SELECT 1 FROM archive').fetchone());self.assertFalse(self.computer.db.execute('SELECT 1 FROM jobs').fetchone())
        facade,request=self.chat.envelope(self.session,'c'*32)
        with self.assertRaises(ValueError):facade.admit(dict(request,_web_permit={}))
    def test_computer_queue_is_real_but_asynchronous_and_home_command_is_shared(self):
        self.provider.responses=[dict(input='direct',remember=False,action='computer_task',task='测试工作，不运行执行器',say='好呀')]
        data=self.start('请帮我做个任务');row=self.finished();job=self.computer.get(row['reply']['job_id']);self.assertEqual(job['state'],'queued');self.assertRegex(job['id'],r'^[0-9a-f]{32}$')
        self.chat.start(self.session,data);self.assertEqual(self.computer.db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
        self.provider.responses=[dict(input='direct',remember=False,action='speak',say='我去床上歇会儿。',home_action='rest')]
        self.start('去休息吧');self.assertEqual(self.finished()['state'],'done');self.assertEqual(self.world.snapshot()['revision'],1)
    def test_unsupported_body_actions_do_not_falsely_report_execution(self):
        self.provider.responses=[dict(input='direct',remember=False,action='speak',say='已熄屏',screen_action='off')]
        self.start('把板子熄屏');row=self.finished();self.assertIn('暂时',row['reply']['say']);self.assertNotIn('已熄屏',row['reply']['say'])
    def test_explicit_web_reminder_is_persisted_then_listed_and_cancelled(self):
        self.provider.responses=[dict(input='direct',remember=False,action='speak',say='好呀',reminder=dict(text='起来休息一下',due='2000-01-01 00:00',repeat_minutes=0))]
        data=self.start('5分钟后喊我吧');row=self.finished();a=self.world.reminders.active()[0]
        created=self.chat.db.execute('SELECT created FROM turns WHERE id=?',(data['id'],)).fetchone()[0]
        self.assertEqual(a['due'],created+300);self.assertIn('叫你',row['reply']['say']);self.chat.start(self.session,data);self.assertEqual(len(self.world.reminders.active()),1)
        self.provider.responses=[dict(input='direct',remember=False,action='list_reminders',say='')];self.start('看看提醒');self.assertIn('休息',self.finished()['reply']['say'])
        self.provider.responses=[dict(input='direct',remember=False,action='cancel_reminder',reminder_id=a['id'],say='')];self.start('取消这个提醒');self.assertIn('取消了',self.finished()['reply']['say']);self.assertEqual(self.world.reminders.active(),[])
    def test_finished_reminder_followup_reads_delivery_instead_of_empty_todo_list(self):
        now=time.time();self.world.reminders.clock=lambda:now
        a=self.world.reminders.create('followup',dict(text='喊我一下'),'五分钟后喊我',int(now),origin=self.session);now=a['due']+1
        claim=self.world.reminders.claim(self.session,a['id']);self.world.reminders.acknowledge(self.session,a['id'],claim['lease'],'played')
        self.provider.responses=[dict(input='direct',remember=False,action='list_reminders',say='目前没有待提醒的事情。')]
        self.start('离喊我还有多久？');reply=self.finished()['reply']['say']
        self.assertIn('到点',reply);self.assertIn('网页',reply);self.assertIn('不知道你有没有听到',reply);self.assertNotIn('没有待提醒',reply)
        self.assertEqual(self.world.reminders.active(),[]);self.assertEqual(len(self.world.reminders.recent()),1)

    def test_web_reminder_routes_to_exact_origin_and_explicit_body_is_validated(self):
        self.provider.responses=[dict(input='direct',remember=False,action='speak',reminder=dict(text='休息一下'))]
        self.start('五分钟后喊我');self.assertIn('这个网页',self.finished()['reply']['say']);a=self.world.reminders.active()[0];self.world.reminders.clock=lambda:a['due']+1
        self.assertIsNone(self.world.reminders.claim('body'));self.assertIsNone(self.world.reminders.claim('other-web'));self.assertEqual(self.world.reminders.claim(self.session)['id'],a['id'])
        self.world.reminders.cancel(a['id']);self.world.reminders.clock=time.time
        self.provider.responses=[dict(input='direct',remember=False,action='speak',reminder=dict(text='休息一下',delivery='body',delivery_request='家里的小板子提醒我'))]
        self.start('五分钟后让家里的小板子提醒我');self.assertIn('家里的小板子',self.finished()['reply']['say']);a=self.world.reminders.active()[0];self.world.reminders.clock=lambda:a['due']+1
        self.assertIsNone(self.world.reminders.claim(self.session));self.assertEqual(self.world.reminders.claim('body')['id'],a['id'])

    def test_world_actions_execute_and_cat_care_does_not_cancel_a_journey(self):
        self.provider.responses=[dict(input='direct',remember=False,action='speak',say='好',world_action='yard',home_action='roam')]
        self.start('带小猫去小院走走');self.assertIn('小院',self.finished()['reply']['say']);self.assertEqual(self.world.life.pending['to'],'yard')
        self.world.life.cat['hunger']=20
        self.provider.responses=[dict(input='direct',remember=False,action='speak',say='好',world_action='catfeed')]
        self.start('给小猫添点饭');self.assertIn('添好',self.finished()['reply']['say']);self.assertLessEqual(self.world.life.cat['hunger'],20);self.assertEqual(self.world.life.cat['mode'],8);self.assertEqual(self.world.life.pending['to'],'yard')
    def test_model_cannot_create_reminder_without_explicit_owner_request(self):
        self.provider.responses=[dict(input='direct',remember=False,action='speak',say='已设好',reminder=dict(text='看看我',due='2099-01-01 00:00'))]
        self.start('你好呀');self.assertIn('没有保存',self.finished()['reply']['say']);self.assertEqual(self.world.reminders.active(),[])
    def wav(self):
        output=io.BytesIO()
        with wave.open(output,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*8000)
        return output.getvalue()
    def test_asr_only_returns_editable_transcript_and_audio_is_not_persisted(self):
        data=self.wav();rid='1'*32;self.assertEqual(self.chat.transcribe(self.session,rid,data)['text'],'你好小溪');self.assertEqual(self.chat.transcribe(self.session,rid,data)['text'],'你好小溪');self.assertEqual(self.provider.audio_calls,1)
        self.assertFalse(self.memory.db.execute('SELECT 1 FROM archive').fetchone());self.assertFalse(self.chat.history(self.session));self.assertNotIn(b'RIFF',self.chat.path.read_bytes())
        with self.assertRaises(ValueError):self.chat.transcribe(self.session,'2'*32,b'not wav')
    def test_reply_audio_uses_saved_reply_fixed_voice_and_memory_cache(self):
        self.start();row=self.finished();first=self.chat.audio(self.session,row['id']);self.assertTrue(first.startswith(b'RIFF'));self.assertEqual(self.chat.audio(self.session,row['id']),first);self.assertEqual(self.provider.audio_calls,1)
        with self.assertRaises(ValueError):self.chat.audio('b'*64,row['id'])
    def test_restart_keeps_completed_turn_but_never_reissues_uncertain_turn(self):
        data=self.start();row=self.finished();self.chat.close();self.chat=home_chat.HomeChat(self.world,self.brain,self.computer,self.chat.path);self.world.chat=self.chat
        self.chat.start(self.session,data);self.assertEqual(self.provider.calls,1);self.assertEqual(self.chat.history(self.session)[0]['reply'],row['reply'])
    def test_forget_authoritative_archive_also_clears_web_display_and_cached_reply(self):
        self.start();row=self.finished();self.chat.audio(self.session,row['id'])
        with self.memory.lock,self.memory.db:self.memory.db.execute('DELETE FROM archive')
        self.assertEqual(self.chat.history(self.session),[]);self.assertFalse(self.chat.audio_cache)
        self.assertEqual(self.chat.db.execute('SELECT text FROM turns WHERE id=?',(row['id'],)).fetchone()[0],'')
    def test_restart_marks_uncertain_turn_interrupted_and_does_not_execute_it(self):
        turn='e'*32
        with self.chat.lock,self.chat.db:self.chat.db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?,?)',(turn,self.session,'fingerprint','待确认的原句','working','{}','',int(time.time())))
        self.chat.close();self.chat=home_chat.HomeChat(self.world,self.brain,self.computer,self.chat.path);self.world.chat=self.chat
        self.assertEqual(self.chat.history(self.session)[0]['state'],'interrupted');self.assertEqual(self.provider.calls,0)

    def test_http_chat_and_binary_asr_are_cookie_origin_gated(self):
        key=str(Path(self.computer.media.root).resolve());home._instances[key]=self.world
        server=ThreadingHTTPServer(('127.0.0.1',0),agent.handler(self.computer,'test-token',lambda:True,self.brain));server.daemon_threads=True;thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def call(path,body,auth=True,origin=True,kind='application/json'):
            c=HTTPConnection('127.0.0.1',server.server_port,timeout=3);headers={'Content-Type':kind,'Origin':('https://127.0.0.1:'+str(server.server_port)) if origin else 'https://wrong.example','X-Chat-Id':'3'*32}
            if auth:headers['Cookie']=self.cookie
            c.request('POST',path,body if isinstance(body,bytes) else json.dumps(body),headers);r=c.getresponse();result=(r.status,r.read());c.close();return result
        try:
            private=HTTPConnection('127.0.0.1',server.server_port,timeout=3);private.request('POST','/v1/home/world',json.dumps(dict(id='d'*32,action='catpet')),{'Content-Type':'application/json','Authorization':'Bearer test-token'});res=private.getresponse();self.assertEqual(res.status,200);self.assertTrue(json.loads(res.read())['accepted']);private.close();self.assertIn(self.world.life.cat['mode'],(5,9))
            self.assertEqual(call('/v1/home/world',dict(id='e'*32,action='catfeed'))[0],401)
            self.assertEqual(call('/home/api/desktop/open',{},auth=False)[0],401)
            self.assertEqual(call('/home/api/desktop/open',{},origin=False)[0],403)
            for path in ('/home/api/desktop','/home/api/desktop/frame'):
                check=HTTPConnection('127.0.0.1',server.server_port,timeout=3);check.request('GET',path);denied=check.getresponse();self.assertEqual(denied.status,401);denied.read();check.close()
            self.assertEqual(call('/home/api/reminders/claim',{},auth=False)[0],401)
            self.assertEqual(call('/home/api/reminders/presence',dict(ready=True),origin=False)[0],403)
            reminder=self.world.reminders.create('http',dict(text='休息一下'),'一秒后提醒我',time.time(),origin=self.session)
            self.world.reminders.clock=lambda:time.time()+2
            connection=HTTPConnection('127.0.0.1',server.server_port,timeout=3);connection.request('GET','/home/alerts',headers={'Cookie':self.cookie});response=connection.getresponse();self.assertEqual(response.status,200);event=response.readline();self.assertIn('休息一下',json.loads(event.decode().removeprefix('data: '))['reminders'][0]['text']);response.close();connection.close()
            other='xiaoxi_home='+self.world.login(self.world.pair_code()['code'])
            c=HTTPConnection('127.0.0.1',server.server_port,timeout=3);c.request('POST','/home/api/reminders/claim',json.dumps(dict(id=reminder['id'])),{'Cookie':other,'Content-Type':'application/json','Origin':'https://127.0.0.1:'+str(server.server_port)});result=c.getresponse();self.assertIsNone(json.loads(result.read())['reminder']);c.close()
            status,raw=call('/home/api/reminders/claim',dict(id=reminder['id']));self.assertEqual(status,200);claim=json.loads(raw)['reminder'];self.assertEqual(set(claim),{'id','text','due','lease'})
            self.assertEqual(call('/home/api/reminders/audio',dict(id=claim['id'],lease=claim['lease']))[0],200)
            self.assertEqual(call('/home/api/reminders/ack',dict(id=claim['id'],lease=claim['lease'],delivery='played'))[0],200)
            self.assertEqual(call('/home/api/chat',dict(id='c'*32,text='你好'),auth=False)[0],401)
            self.assertEqual(call('/home/api/chat',dict(id='c'*32,text='你好'),origin=False)[0],403)
            self.assertEqual(call('/home/api/asr',self.wav(),auth=False,kind='audio/wav')[0],401)
            self.assertEqual(call('/home/api/asr',self.wav(),kind='audio/wav')[0],200)
            self.assertEqual(call('/home/api/chat',dict(id='c'*32,text='你好'))[0],202);self.assertEqual(self.finished()['state'],'done')
        finally:server.shutdown();server.server_close();thread.join();home._instances.pop(key,None)
