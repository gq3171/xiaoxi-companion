"""Real native room motion, persistence, conflicts and authenticated HTTP/SSE."""
import ctypes as C
import hashlib,json,os,secrets,shutil,subprocess,tempfile,threading,unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from http.client import HTTPConnection
import agent
import home_sync as home

ROOT=Path(__file__).resolve().parent.parent
class Clock:
    def __init__(self):self.now=0.
    def mono(self):return self.now
    def wall(self):return self.now+12*3600-8*3600

class HomeSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build=tempfile.TemporaryDirectory();cls.library=Path(cls.build.name)/'scene.so'
        external=os.environ.get('DESKPET_TEST_HOME_LIBRARY')
        if external:shutil.copyfile(external,cls.library)
        else:subprocess.run(['cc','-shared','-fPIC','-O2','-I',str(ROOT/'firmware/main'),str(ROOT/'computer/home_scene_native.c'),*[str(ROOT/'firmware/main'/name) for name in ['pet_scene.c','pet_scene_wire.c','pet_home.c']],'-lm','-o',str(cls.library)],check=True)
    @classmethod
    def tearDownClass(cls):cls.build.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.clock=Clock()
        self.world=home.HomeWorld(self.root/'state/home-sync.json',self.library,self.root/'assets',clock=self.clock.wall,monotonic=self.clock.mono,start=False)
    def tearDown(self):
        self.world.close();self.tmp.cleanup()
    def event(self,action='rest',**extra):
        state=self.world.snapshot();return dict(id=secrets.token_hex(16),epoch=state['epoch'],revision=state['revision'],action=action)|extra
    def advance(self,seconds):
        for _ in range(round(seconds*20)):
            self.clock.now+=.05;self.world.snapshot()
    def body(self,seq=1,**extra):return dict(boot=12,seq=seq,body=dict(listening=False,speaking=False,thinking=False,blocked=False,tired=False,resting=False,computer=1))|extra
    def test_reminder_web_priority_body_ack_and_cancelled_mailbox_validation(self):
        now=self.clock.wall();a=self.world.reminders.create('a',dict(text='休息一下'),'五秒后提醒我',now,origin='body');self.clock.now+=5
        token=self.world.login(self.world.pair_code()['code']);session=self.world.session(self.cookie(token));self.world.reminder_presence[session]=self.clock.mono()
        body=self.body();body['body']['reminder_ready']=True
        self.assertEqual(self.world.body_poll(body)['reminder']['id'],a['id'])
        self.clock.now+=26;body['seq']=2;notice=self.world.body_poll(body)['reminder'];self.assertEqual(notice['id'],a['id'])
        body['seq']=3;body['reminder_current']=notice;self.assertTrue(self.world.body_poll(body)['reminder_current_valid'])
        self.world.reminders.cancel(a['id']);body['seq']=4;self.assertFalse(self.world.body_poll(body)['reminder_current_valid'])
        body['seq']=5;body['reminder_ack']=notice|dict(delivery='played');self.assertTrue(self.world.body_poll(body)['reminder_ack_processed'])
    def test_browser_reminder_never_falls_back_to_body_when_browser_offline(self):
        token=self.world.login(self.world.pair_code()['code']);session=self.world.session(self.cookie(token));now=self.clock.wall()
        a=self.world.reminders.create('web-only',dict(text='起来走走'),'五秒后提醒我',now,origin=session);self.clock.now+=5
        body=self.body();body['body']['reminder_ready']=True;self.assertIsNone(self.world.body_poll(body)['reminder'])
        self.clock.now+=100;body['seq']=2;self.assertIsNone(self.world.body_poll(body)['reminder']);self.assertEqual(self.world.reminders.due('body'),[]);self.assertEqual(self.world.reminders.claim(session)['id'],a['id'])

    def test_real_shared_engine_goes_to_bed_and_completes_chair_approach_before_sitting(self):
        self.world.command(self.event('work'),'web');self.advance(2);state=self.world.snapshot()
        self.assertEqual(state['wire'][16],1);self.assertNotIn(state['wire'][14],(14,15))
        self.advance(15);state=self.world.snapshot();self.assertEqual(state['wire'][17],3);self.assertIn(state['wire'][16],(6,7));self.assertEqual(state['wire'][:2],[329,237])
        self.world.command(self.event('rest'),'web');self.advance(24);state=self.world.snapshot();self.assertEqual(state['wire'][16],3);self.assertEqual(state['projection'],[98,130,128])
    def test_replayed_event_survives_restart_and_stale_other_client_is_rejected(self):
        one=self.event('rest');stale=self.event('work');ack=self.world.command(one,'web')
        with self.assertRaises(home.HomeConflict):self.world.command(stale,'web')
        self.advance(2);wire=self.world.snapshot()['wire'];self.world.save()
        other=home.HomeWorld(self.world.path,self.library,self.world.assets,clock=self.clock.wall,monotonic=self.clock.mono,start=False)
        try:
            self.assertEqual(other.snapshot()['wire'][:6],wire[:6]);self.assertEqual(other.command(one,'web')['revision'],ack['revision']);self.assertTrue(other.command(one,'web')['duplicate'])
            with self.assertRaises(home.HomeConflict):other.command(self.event('wash'),'web')
            with self.assertRaises(home.HomeConflict):other.command(one|dict(action='work'),'web')
        finally:other.close()
    def test_offline_body_expressions_expire_and_late_boot_cannot_override_current_body(self):
        self.world.body_poll(self.body(name='小溪',caption='我在呀',phase='说'));self.assertEqual(self.world.snapshot()['caption'],'我在呀')
        with self.assertRaises(home.HomeConflict):self.world.body_poll(self.body())
        with self.assertRaises(home.HomeConflict):self.world.body_poll(self.body(2,boot=11))
        self.advance(3.1);state=self.world.snapshot();self.assertFalse(state['body_online']);self.assertEqual(state['caption'],'');self.assertEqual(state['phase'],'')
    def test_seed_is_first_import_only_and_body_command_conflict_returns_snapshot(self):
        s=self.world.scene.wire();s[0]=s[4]=0 # valid precise coordinate may differ; use real engine dump instead
        seed=self.world.scene.wire();seed[0]=180;seed[4]=180000
        self.world.body_poll(self.body(seed=seed,seed_ms=0));self.assertEqual(self.world.snapshot()['wire'][0],180)
        changed=seed[:];changed[0]=300;changed[4]=300000
        self.world.body_poll(self.body(2,seed=changed,seed_ms=0));self.assertEqual(self.world.snapshot()['wire'][0],180)
        old=self.event('wash');self.world.command(self.event('rest'),'web');r=self.world.body_poll(self.body(3,event=old));self.assertFalse(r['ack']['accepted']);self.assertTrue(r['ack']['conflict'])
    def test_invalid_geometry_bool_revision_and_external_actions_are_rejected(self):
        original=self.world.snapshot()['wire']
        for extra in [dict(action='run'),dict(action='move',x=999),dict(action='move',y=True),dict(revision=True),dict(action='react',x=5)]:
            with self.assertRaises(ValueError):self.world.command(self.event()|extra,'web')
        bad=original[:];bad[16]=1;bad[32]=bad[33]=3
        with self.assertRaises(ValueError):self.world.body_poll(self.body(seed=bad,seed_ms=0))
        self.assertEqual(self.world.snapshot()['wire'],original)
    def test_pairing_is_one_use_expiring_rate_limited_and_never_persisted(self):
        code=self.world.pair_code()['code'];token=self.world.login(code);self.assertEqual(len(token),43)
        with self.assertRaises(PermissionError):self.world.login(code)
        code=self.world.pair_code()['code'];self.clock.now+=181
        with self.assertRaises(PermissionError):self.world.login(code)
        self.world.save();raw=self.world.path.read_text();self.assertNotIn(code,raw);self.assertNotIn(token,raw)
        self.world.pair_code()
        for _ in range(8):
            with self.assertRaises(PermissionError):self.world.login('bad')
        with self.assertRaises(PermissionError):self.world.login(self.world.pair[0])
    def test_correct_token_survives_global_and_source_failures(self):
        owner=self.world.login(self.world.pair_code()['code'])
        key=self.world.token_key(self.world.session(self.cookie(owner)))['token']
        for i in range(20):
            with self.assertRaises(PermissionError):self.world.login('bad',source='stranger')
        self.assertTrue(self.world.login(None,key,source='owner'))
        self.assertTrue(self.world.login(None,key,source='stranger'))
        self.assertLessEqual(len(self.world.login_sources['stranger']),8)
        with self.assertRaises(PermissionError):self.world.login(None,'x'*43,source='stranger')

    def test_custom_name_survives_restart_and_brain_identity_wins_over_body(self):
        self.world.body_poll(self.body(name='自定义小名'));self.world.save();self.reopen()
        self.assertEqual(self.world.snapshot()['name'],'自定义小名')
        identity={'name':'主脑中的名字'}
        self.world.identity_provider=lambda:identity['name']
        self.assertEqual(self.world.snapshot()['name'],'主脑中的名字')
        self.world.body_poll(self.body(name='旧板端缓存'))
        self.assertEqual(self.world.snapshot()['name'],'主脑中的名字')
        identity['name']='新的名字';self.assertEqual(self.world.snapshot()['name'],'新的名字')

    def cookie(self,token):
        from types import SimpleNamespace
        return SimpleNamespace(headers={'Cookie':'xiaoxi_home='+token})
    def reopen(self):
        self.world.close();self.world=home.HomeWorld(self.world.path,self.library,self.world.assets,clock=self.clock.wall,monotonic=self.clock.mono,start=False)
    def test_browser_trust_survives_service_restart_and_expires_after_90_days(self):
        token=self.world.login(self.world.pair_code()['code']);handler=self.cookie(token)
        self.assertTrue(self.world.session(handler));self.reopen();self.assertTrue(self.world.session(handler))
        self.clock.now+=89*86400;self.assertTrue(self.world.session(handler))
        self.clock.now+=86400;self.assertIsNone(self.world.session(handler));self.reopen();self.assertIsNone(self.world.session(handler))
    def test_access_token_is_persistent_reusable_replaceable_and_never_stores_raw_secrets(self):
        owner=self.world.login(self.world.pair_code()['code']);current=self.world.session(self.cookie(owner))
        first=self.world.token_key(current)['token'];key=self.world.token_key(current)['token']
        with self.assertRaises(PermissionError):self.world.login(None,first)
        self.reopen();a=self.world.login(None,key);self.reopen();b=self.world.login(None,key)
        self.assertTrue(self.world.session(self.cookie(a)));self.assertTrue(self.world.session(self.cookie(b)))
        raw=self.world.access_path.read_text()
        for secret in (a,b,key,first):self.assertNotIn(secret,raw)
        self.assertEqual(self.world.access_path.stat().st_mode&0o777,0o600)
    def test_revoke_others_invalidates_other_cookies_pending_invites_and_recovery_across_restart(self):
        a=self.world.login(self.world.pair_code()['code']);b=self.world.login(self.world.pair_code()['code'])
        recovery=self.world.token_key(self.world.session(self.cookie(a)))['token'];b=self.world.login(self.world.pair_code()['code']);pending=self.world.pair_code()['code']
        self.world.revoke_others(self.world.session(self.cookie(a)));self.reopen()
        self.assertTrue(self.world.session(self.cookie(a)));self.assertIsNone(self.world.session(self.cookie(b)))
        with self.assertRaises(PermissionError):self.world.login(None,recovery)
        with self.assertRaises(PermissionError):self.world.login(pending)
        self.world.logout(self.world.session(self.cookie(a)));self.reopen();self.assertIsNone(self.world.session(self.cookie(a)))

    def test_token_rotation_revokes_old_browser_sessions_without_body(self):
        a=self.world.login(self.world.pair_code()['code']);current=self.world.session(self.cookie(a))
        old=self.world.token_key(current)['token'];b=self.world.login(None,old)
        self.assertFalse(self.world.snapshot()['body_online'])
        new=self.world.token_key(current)['token'];self.reopen()
        self.assertTrue(self.world.session(self.cookie(a)));self.assertIsNone(self.world.session(self.cookie(b)))
        with self.assertRaises(PermissionError):self.world.login(None,old)
        self.assertTrue(self.world.login(None,new))

    def test_corrupt_snapshot_uses_previous_without_erasing_both_copies(self):
        self.world.command(self.event('rest'),'web');self.world.save();self.world.path.write_text('torn')
        other=home.HomeWorld(self.world.path,self.library,self.world.assets,clock=self.clock.wall,monotonic=self.clock.mono,start=False)
        self.assertTrue(other.seeded);other.close();self.world.path.write_text('bad');self.world.path.with_suffix('.previous').write_text('also bad')
        with self.assertRaises(ValueError):home.HomeWorld(self.world.path,self.library,self.world.assets,start=False)
    def test_web_intent_is_reported_once_as_new_revision_for_body_plan_override(self):
        self.assertEqual(self.world.snapshot()['web_revision'],0)
        event=self.event('rest');self.world.command(event,'web');revision=self.world.snapshot()['web_revision']
        self.assertEqual(revision,1);self.world.command(event,'web');self.assertEqual(self.world.snapshot()['web_revision'],revision)
        self.world.command(self.event('react',x=5),'body');self.assertEqual(self.world.snapshot()['web_revision'],revision)

    def test_shutdown_saves_current_motion_and_rejects_late_handlers_safely(self):
        self.world.command(self.event('rest'),'web');self.advance(2);expected=self.world.snapshot()['wire'][:6]
        self.world.close()
        with self.assertRaises(ValueError):self.world.snapshot()
        self.world.close() # idempotent; in-flight handlers cannot call freed native state
        other=home.HomeWorld(self.world.path,self.library,self.world.assets,clock=self.clock.wall,monotonic=self.clock.mono,start=False)
        self.assertEqual(other.snapshot()['wire'][:6],expected);other.close()

    def test_actual_http_pairing_static_assets_sse_csrf_and_body_routes(self):
        store=agent.Store(self.root/'http/state/jobs.sqlite3');key=str(Path(store.media.root).resolve());home._instances[key]=self.world
        server=ThreadingHTTPServer(('127.0.0.1',0),agent.handler(store,'t'*48,lambda:True));server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();port=server.server_port
        def request(method,path,body=None,**headers):
            c=HTTPConnection('127.0.0.1',port,timeout=3);raw=home.compact(body) if body is not None else None
            headers={'Content-Type':'application/json','Origin':f'https://127.0.0.1:{port}',**headers};c.request(method,path,raw,headers);r=c.getresponse();data=r.read();result=(r.status,dict(r.getheaders()),data);c.close();return result
        try:
            self.assertEqual(request('GET','/home/')[0],200);self.assertEqual(request('GET','/home/api/state')[0],401)
            for path in ('/home/api/desktop/session','/home/api/desktop/ws','/home/novnc/core/rfb.js'):
                self.assertEqual(request('GET',path)[0],401)
            self.assertEqual(request('POST','/home/api/desktop/control/take',{})[0],401)
            self.assertEqual(request('POST','/v1/home/pair',{})[0],401)
            for path in ('pair','token','revoke-others'):
                self.assertEqual(request('POST','/home/api/'+path,{})[0],401)
            code=json.loads(request('POST','/v1/home/pair',{},Authorization='Bearer '+'t'*48)[2])['code']
            self.assertEqual(request('POST','/home/api/login',dict(code=code),Origin='https://evil.example')[0],403)
            status,headers,_=request('POST','/home/api/login',dict(code=code));self.assertEqual(status,200);cookie=headers['Set-Cookie'];self.assertIn('HttpOnly',cookie);self.assertIn('Secure',cookie);self.assertIn('SameSite=Strict',cookie);cookie=cookie.split(';')[0]
            self.assertEqual(request('GET','/home/assets/../../brain.env',Cookie=cookie)[0],404)
            self.assertEqual(request('POST','/home/api/desktop/control/take',{},Cookie=cookie,Origin='https://evil.example')[0],403)
            self.assertEqual(request('GET','/home/novnc/../../brain.env',Cookie=cookie)[0],404)
            self.assertEqual(request('GET','/home/novnc/core/rfb.js',Cookie=cookie)[0],200)
            upgrade={'Upgrade':'websocket','Connection':'Upgrade','Sec-WebSocket-Version':'13','Sec-WebSocket-Key':'eHh4eHh4eHh4eHh4eHh4eA=='}
            self.assertEqual(request('GET','/home/api/desktop/ws',Cookie=cookie,Origin='https://evil.example',**upgrade)[0],403)
            self.assertEqual(request('GET','/home/api/desktop/ws?mode=control',Cookie=cookie,Origin='https://xiaoxi.example:8791',**upgrade)[0],403)

            for path in ('pair','token','revoke-others'):
                self.assertEqual(request('POST','/home/api/'+path,{},Cookie=cookie,Origin='https://evil.example')[0],403)
            self.assertEqual(request('POST','/home/api/pair',{},Cookie=cookie)[0],200)
            status,_,key=request('POST','/home/api/token',{},Cookie=cookie);self.assertEqual(status,200)
            self.assertEqual(len(json.loads(key)['token']),43)
            self.assertEqual(request('POST','/home/api/revoke-others',{},Cookie=cookie)[0],200)
            self.world.assets.mkdir();(self.world.assets/'idle.png').write_bytes(b'panel-png-fixture')
            self.assertEqual(request('GET','/home/assets/idle.png',Cookie=cookie)[0],200)
            for name in ('cat_stand','cat_turn','front_pass_a','front_pass_b'):
                (self.world.assets/(name+'.png')).write_bytes(b'panel-png-fixture');self.assertEqual(request('GET','/home/assets/'+name+'.png',Cookie=cookie)[0],200)
            status,_,raw=request('GET','/home/api/state',Cookie=cookie);self.assertEqual(status,200)
            event=self.event('work');self.assertEqual(request('POST','/home/api/command',event,Cookie=cookie)[0],200)
            self.assertEqual(request('POST','/home/api/command',event|dict(id='f'*32,action='rest'),Cookie=cookie)[0],409)
            c=HTTPConnection('127.0.0.1',port,timeout=3);c.request('GET','/home/events',headers={'Cookie':cookie});r=c.getresponse();self.assertEqual(r.status,200);line=r.fp.readline()
            while not line.startswith(b'data: '):line=r.fp.readline()
            self.assertTrue(line.startswith(b'data: '));self.assertEqual(json.loads(line[6:])['revision'],self.world.revision);r.close();c.close()
            self.assertEqual(request('POST','/v1/home/poll',self.body(),Authorization='Bearer '+'t'*48)[0],200)
            self.assertFalse(store.db.execute('SELECT 1 FROM jobs').fetchone())
            self.assertEqual(request('POST','/home/api/logout',{},Cookie=cookie)[0],200);self.assertEqual(request('GET','/home/api/state',Cookie=cookie)[0],401)
        finally:server.shutdown();server.server_close();thread.join();store.db.close();home._instances.pop(key,None)
