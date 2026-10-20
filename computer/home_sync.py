"""One persistent virtual room; paired body and cookie-authenticated browser replicas.

No model/provider/owner-memory/task writes. Native scene engine is shared with ESP32.
"""
import ctypes as C
import hashlib,hmac,json,os,re,secrets,ssl,threading,time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

ACTIONS={'roam':1,'rest':2,'wake':3,'wash':4,'work':5,'window':6,'read':7,'touch':20,'move':21,'react':22,'walkto':23,'yard':30,'home':31,'catpet':32,'catfeed':33}
ACTIVITIES=['在家里','正在走路','正在上床','正在休息','正在起床','正在洗漱','在工作台等你','正在工作','在窗边看看','正在走近椅子','正在起身','正在读书']
SESSION_SECONDS=90*86400
WORDS=34
class HomeConflict(ValueError):pass

def compact(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def integer(value,lo,hi):return type(value) is int and lo<=value<=hi

class NativeScene:
    def __init__(self,library,now):
        self.lib=C.CDLL(str(library));l=self.lib
        for name,args,result in [('home_new',[C.c_uint32],C.c_void_p),('home_free',[C.c_void_p],None),('home_load',[C.c_void_p,C.POINTER(C.c_int32),C.c_uint32,C.c_uint32],C.c_int),('home_dump',[C.c_void_p,C.POINTER(C.c_int32)],None),('home_step',[C.c_void_p,C.c_uint32,C.c_uint32,C.c_uint,C.c_int],None),('home_command',[C.c_void_p,C.c_int,C.c_uint32,C.c_int,C.c_int],C.c_int),('home_projection',[C.c_void_p,C.POINTER(C.c_int32)],None),('home_completion',[],C.c_uint)]:
            f=getattr(l,name);f.argtypes=args;f.restype=result
        if hasattr(l,'home_art'):l.home_art.argtypes=[C.c_void_p,C.c_uint32];l.home_art.restype=C.c_uint
        self.ptr=l.home_new(now)
        if not self.ptr:raise MemoryError('scene allocation')
    def load(self,wire,now,remote):
        if not isinstance(wire,list) or len(wire)!=WORDS or not all(integer(x,-2**31,2**31-1) for x in wire) or not integer(remote,0,2**32-1):raise ValueError('invalid scene wire')
        if not self.lib.home_load(self.ptr,(C.c_int32*WORDS)(*wire),now,remote):raise ValueError('invalid scene fields')
    def wire(self):
        out=(C.c_int32*WORDS)();self.lib.home_dump(self.ptr,out);return list(out)
    def projection(self):
        out=(C.c_int32*3)();self.lib.home_projection(self.ptr,out);return list(out)
    def close(self):
        if self.ptr:self.lib.home_free(self.ptr);self.ptr=None

class HomeWorld:
    def __init__(self,path,library,assets,clock=time.time,monotonic=time.monotonic,start=True,identity_provider=None):
        self.path,self.assets=Path(path),Path(assets);self.clock,self.monotonic=clock,monotonic
        self.path.parent.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock();self.stop=threading.Event();self.thread=None;self.identity_provider=identity_provider;self.failure=None
        self.origin_ms=int(monotonic()*1000);self.ms=0;self.scene=NativeScene(library,0)
        self.epoch=secrets.token_hex(16);self.revision=self.frame=0;self.seeded=False;self.events={};self.saved_at=0
        self.body=None;self.body_seen=-1000.;self.caption='';self.phase='';self.caption_until=0;self.name='小溪';self.chat=None;self.web_caption='';self.web_caption_until=0;self.reminder_presence={};self.desktop=None
        self.pair=None;self.sessions={};self.login_attempts=[];self.login_sources={};self.streams={};self.pending_initial=False
        from home_world_life import WorldLife
        self.life=WorldLife(clock)
        from home_reminders import ReminderStore
        self.reminders=ReminderStore(self.path.with_name('reminders.sqlite3'),clock=clock)
        self.access_path=self.path.with_name('home-access.json');self.access_token=None
        if self.access_path.exists():
            try:
                access=json.loads(self.access_path.read_text());sessions=access['sessions'];access_token=access.get('access_token')
                assert access['version']==1 and isinstance(sessions,dict) and len(sessions)<=8
                assert all(re.fullmatch('[0-9a-f]{64}',k) and type(v) in (int,float) and 0<v<2**53 for k,v in sessions.items())
                assert access_token is None or (isinstance(access_token,str) and re.fullmatch('[0-9a-f]{64}',access_token))
                self.sessions={k:v for k,v in sessions.items() if v>self.clock()};self.access_token=access_token
            except (ValueError,KeyError,TypeError,AssertionError):
                self.scene.close();raise ValueError('preserve unreadable browser authorization')
        if self.path.exists() or self.path.with_suffix('.previous').exists():
            for p in (self.path,self.path.with_suffix('.previous')):
                try:
                    value=json.loads(p.read_text());data=value['data'];assert hmac.compare_digest(value['sha256'],hashlib.sha256(compact(data).encode()).hexdigest())
                    assert data['version']==1 and integer(data['revision'],0,2**53-1) and isinstance(data['events'],dict) and len(data['events'])<=128
                    self.scene.load(data['wire'],0,data['remote_ms']);self.revision=data['revision'];self.events=data['events'];self.seeded=bool(data['seeded']);self.life=WorldLife(clock,data.get('world'));self.name=data.get('name','小溪');assert isinstance(self.name,str) and 0<len(self.name.encode())<=96;break
                except (OSError,ValueError,KeyError,TypeError,AssertionError):continue
            else:self.scene.close();raise ValueError('preserve unreadable shared room')
        self.refresh_name()
        if start:
            self.thread=threading.Thread(target=self.run,name='shared-home',daemon=True);self.thread.start()
    def refresh_name(self):
        if self.identity_provider is not None:
            name = self.identity_provider()
            if isinstance(name, str) and 0 < len(name.encode()) <= 96:
                self.name = name
    def now_ms(self):return (int(self.monotonic()*1000)-self.origin_ms)&0xffffffff
    def save(self):
        data=dict(version=1,wire=self.scene.wire(),remote_ms=self.ms,revision=self.revision,events=self.events,seeded=self.seeded,world=self.life.dump(),name=self.name)
        payload=(compact(dict(data=data,sha256=hashlib.sha256(compact(data).encode()).hexdigest()))+'\n').encode()
        temp=self.path.with_suffix('.new');fd=os.open(temp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
        if self.path.exists():os.replace(self.path,self.path.with_suffix('.previous'))
        os.replace(temp,self.path);self.path.chmod(0o600)
        directory=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
        self.saved_at=self.monotonic()
    def advance(self):
        if self.stop.is_set():raise ValueError('shared room stopped')
        now=self.now_ms();elapsed=(now-self.ms)&0xffffffff
        if elapsed>1000: # Suspend/resume freezes missed simulation; no invented offline completion.
            self.scene.load(self.scene.wire(),now,self.ms);self.ms=now
        else:
            while ((now-self.ms)&0xffffffff)>=50:
                self.ms=(self.ms+50)&0xffffffff
                fresh=self.monotonic()-self.body_seen<3;body=self.body if fresh else {}
                body=body or {};flags=sum(bit for key,bit in [('listening',1),('speaking',2),('thinking',4),('blocked',8),('tired',32)] if body.get(key) is True)
                minute=int((self.clock()+8*3600)%86400//60)
                if body.get('resting') is True or minute>=1320 or minute<420:flags|=16
                random=((self.ms*1664525+1013904223)&0xffffffff)
                outside=self.life.location=='yard'
                self.scene.lib.home_step(self.scene.ptr,self.ms,random,flags&~48 if outside else flags,0 if outside else body.get('computer',0));self.frame+=1
                if self.life.tick(self,50,live=bool(flags&7),blocked=bool(flags&8),computer=body.get('computer',0),night=bool(flags&16)):self.save()
        if self.monotonic()-self.saved_at>=30:self.save()
    def snapshot(self):
        with self.lock:
            self.refresh_name();self.advance();w=self.scene.wire();fresh=self.monotonic()-self.body_seen<3
            return dict(ok=True,protocol=1,completion=self.scene.lib.home_completion(),epoch=self.epoch,revision=self.revision,frame=self.frame,server_ms=self.ms,wire=w,projection=self.scene.projection(),web_revision=max((e['revision'] for e in self.events.values() if e.get('source')=='web'),default=0),body_online=fresh,body_render=self.body.get('render') if self.body else None,name=self.name,activity=ACTIVITIES[w[16]],caption=self.web_caption if self.monotonic()<self.web_caption_until and not (fresh and self.body.get('speaking')) else self.caption if self.monotonic()<self.caption_until else '',phase=self.phase if fresh else '',night=bool(w[13]&16),art_frame=self.scene.lib.home_art(self.scene.ptr,self.ms) if hasattr(self.scene.lib,'home_art') else w[14],world=self.life.snapshot(self.ms))
    def run(self):
        while not self.stop.wait(.05):
            try:
                with self.lock:self.advance()
            except Exception as error:
                # Category only: no private payloads or automatic state reset.
                self.failure=type(error).__name__
                self.stop.set()
    def close(self):
        self.stop.set()
        if self.chat:self.chat.close()
        if self.thread:self.thread.join(timeout=2)
        self.reminders.close()
        with self.lock:
            if self.scene.ptr:self.save();self.scene.close()
    def command(self,event,source):
        if not isinstance(event,dict) or not re.fullmatch('[0-9a-f]{32}',str(event.get('id',''))) or event.get('action') not in ACTIONS:raise ValueError('invalid room event')
        action=event['action'];x=event.get('x',0);y=event.get('y',0)
        if not integer(x,0,479) or not integer(y,0,479) or (action=='react' and (source!='body' or x not in (3,5,6,7,4))):raise ValueError('invalid room coordinates')
        fingerprint=hashlib.sha256(compact(dict(action=action,x=x,y=y,source=source)).encode()).hexdigest()
        with self.lock:
            self.advance();old=self.events.get(event['id'])
            if old:
                if old['fingerprint']!=fingerprint:raise HomeConflict('event id reused')
                return dict(id=event['id'],accepted=True,revision=old['revision'],duplicate=True)
            if not integer(event.get('revision'),0,2**53-1) or event.get('epoch')!=self.epoch or event.get('revision')!=self.revision:raise HomeConflict('room changed')
            from home_world_life import ACTIONS as WORLD_ACTIONS
            if action in WORLD_ACTIONS:self.life.request(self,action)
            elif not self.life.intercept(self,action):
                if not self.scene.lib.home_command(self.scene.ptr,ACTIONS[action],self.ms,x,y):raise ValueError('unsupported room action')
            self.revision+=1;self.seeded=True
            self.events[event['id']]=dict(fingerprint=fingerprint,revision=self.revision,source=source,action=action)
            if len(self.events)>128:del self.events[next(iter(self.events))]
            self.save();return dict(id=event['id'],accepted=True,revision=self.revision)
    def body_poll(self,request):
        boot=request.get('boot');seq=request.get('seq');b=request.get('body')
        if not integer(boot,1,2**53-1) or not integer(seq,1,2**32-1) or not isinstance(b,dict):raise ValueError('invalid body envelope')
        for key in ('listening','speaking','thinking','blocked','tired','resting'):
            if type(b.get(key)) is not bool:raise ValueError('invalid body flag')
        if not integer(b.get('computer'),0,4):raise ValueError('invalid computer state')
        render=request.get('seed')
        if not isinstance(render,list) or len(render)!=WORDS or not all(integer(x,-2**31,2**31-1) for x in render) or not integer(render[0],0,479) or not integer(render[1],0,479) or not integer(render[14],0,17) or not integer(render[16],0,11):
            render=None
        with self.lock:
            if self.body and (boot<self.body['boot'] or (boot==self.body['boot'] and seq<=self.body['seq'])):raise HomeConflict('stale body poll')
            self.advance()
            if not self.seeded and isinstance(request.get('seed'),list):
                self.scene.load(request['seed'],self.ms,request.get('seed_ms'));self.seeded=True;self.save()
            self.body=dict(b,boot=boot,seq=seq,render=[render[0],render[1],render[14],render[16]] if render else None);self.body_seen=self.monotonic()
            for key,limit in [('name',96),('caption',1800),('phase',96)]:
                text=request.get(key,'')
                if not isinstance(text,str) or len(text.encode())>limit:raise ValueError('invalid body text')
                if key=='name' and text:
                    if self.identity_provider is None:
                        if self.name!=text:self.name=text;self.save()
                    else:self.refresh_name()
                elif key=='caption':self.caption=text;self.caption_until=self.monotonic()+3 if text else 0
                elif key=='phase':self.phase=text
            ack=None
            if request.get('event'):
                try:ack=self.command(request['event'],'body')
                except HomeConflict:ack=dict(id=request['event'].get('id'),accepted=False,conflict=True)
            reminder_ack=request.get('reminder_ack');processed=False
            if isinstance(reminder_ack,dict):
                try:self.reminders.acknowledge('body',reminder_ack.get('id'),reminder_ack.get('lease'),reminder_ack.get('delivery'));processed=True
                except ValueError:processed=True
            current=request.get('reminder_current');current_valid=None
            if isinstance(current,dict):
                try:self.reminders.validate_claim('body',current.get('id'),current.get('lease'));current_valid=True
                except ValueError:current_valid=False
            reminder=self.reminders.claim('body') if b.get('reminder_ready') is True else None
            return self.snapshot()|dict(ack=ack,reminder=({k:reminder[k] for k in ('id','text','lease')} if reminder else None),reminder_ack_processed=processed,reminder_current_valid=current_valid)
    def save_access(self):
        # Only hashes are stored, separately from the exportable virtual room.
        payload=compact(dict(version=1,sessions=self.sessions,access_token=self.access_token)).encode()
        temp=self.access_path.with_suffix('.new');fd=os.open(temp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
        os.replace(temp,self.access_path);self.access_path.chmod(0o600)
        directory=os.open(self.access_path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    def token_key(self,current):
        with self.lock:
            token=secrets.token_urlsafe(32);self.access_token=hashlib.sha256(token.encode()).hexdigest()
            self.sessions={current:self.sessions[current]};self.pair=None;self.save_access()
            return dict(ok=True,token=token)
    def revoke_others(self,current):
        with self.lock:
            self.sessions={current:self.sessions[current]};self.pair=None;self.access_token=None;self.save_access()
            return dict(ok=True)
    def logout(self,current):
        with self.lock:self.sessions.pop(current,None);self.save_access()
    def pair_code(self):
        with self.lock:
            self.pair=(f'{secrets.randbelow(100000000):08d}',self.monotonic()+180);self.login_attempts=[];self.login_sources={}
            return dict(ok=True,code=self.pair[0],expires_seconds=180)
    def login(self,code,token=None,source='local'):
        with self.lock:
            now=self.monotonic()
            # Verify a known 256-bit token before failed-code budgets. A stranger
            # must not lock its owner out by exhausting the short pairing gate.
            is_token=isinstance(token,str) and re.fullmatch('[A-Za-z0-9_-]{43}',token) and self.access_token and hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(),self.access_token)
            if not is_token:
                self.login_attempts=[t for t in self.login_attempts if now-t<60]
                self.login_sources={k:[t for t in times if now-t<60] for k,times in self.login_sources.items() if times and now-times[-1]<60}
                source=source if isinstance(source,str) and len(source)<=128 else 'unknown'
                attempts=self.login_sources.get(source,[])
                if len(attempts)>=8 or (source not in self.login_sources and len(self.login_sources)>=256):
                    raise PermissionError('login rate limited')
                attempts.append(now);self.login_sources[source]=attempts
                if len(self.login_attempts)>=8:raise PermissionError('pairing rate limited')
                self.login_attempts.append(now)
                is_code=isinstance(code,str) and re.fullmatch('[0-9]{8}',code) and self.pair and now<self.pair[1] and hmac.compare_digest(code,self.pair[0])
                if not is_code:raise PermissionError('pairing denied')
                self.login_sources.pop(source,None)
            else:
                is_code=False
            token=secrets.token_urlsafe(32);self.sessions={k:v for k,v in self.sessions.items() if v>self.clock()}
            if len(self.sessions)>=8:del self.sessions[min(self.sessions,key=self.sessions.get)]
            self.sessions[hashlib.sha256(token.encode()).hexdigest()]=self.clock()+SESSION_SECONDS
            if is_code:self.pair=None
            self.save_access();return token
    def session(self,handler):
        try:
            cookie=SimpleCookie();cookie.load(handler.headers.get('Cookie',''));token=cookie['xiaoxi_home'].value
            if not re.fullmatch('[A-Za-z0-9_-]{43}',token):return None
            key=hashlib.sha256(token.encode()).hexdigest()
            with self.lock:return key if self.sessions.get(key,0)>self.clock() else None
        except (KeyError,ValueError):return None

_instances={};_instance_lock=threading.Lock()
def for_store(store,brain=None):
    with _instance_lock:
        key=str(Path(store.media.root).resolve())
        if key not in _instances:
            base=Path(store.media.root).parent.parent
            _instances[key]=HomeWorld(base/'state/home-sync.json',os.environ.get('DESKPET_HOME_SCENE_LIBRARY',Path(__file__).with_name('libhome_scene.so')),base/'data/home-web')
        world=_instances[key]
        if brain is not None:
            def identity_name():
                # Room snapshots hold world.lock. Web memory commits hold the
                # brain lock and recheck authorization under world.lock. Never
                # wait for the brain here: keep the last committed display name
                # during a write, then refresh it on the next room snapshot.
                if not brain.store.lock.acquire(blocking=False):
                    return None
                try:
                    row=brain.store.row()
                    return json.loads(row['identity']).get('name') if row else None
                finally:
                    brain.store.lock.release()
            with world.lock:
                world.identity_provider=identity_name;world.refresh_name()
        if world.desktop is None:
            from home_desktop import HostDesktop
            world.desktop=HostDesktop(store)
        if brain is not None and world.chat is None:
            from home_chat import HomeChat
            world.chat=HomeChat(world,brain,store,world.path.with_name('web-chat.sqlite3'))
        return world

class HomeHTTP:
    def __init__(self,world):self.world=world
    def respond(self,h,status,value,headers=None,keep=False):
        data=compact(value).encode();self.bytes(h,status,data,'application/json; charset=utf-8',headers,keep)
    def bytes(self,h,status,data,kind,headers=None,keep=False):
        h.close_connection=not keep;h.send_response(status);h.send_header('Content-Type',kind);h.send_header('Content-Length',str(len(data)))
        h.send_header('Cache-Control','no-store');h.send_header('X-Content-Type-Options','nosniff');h.send_header('Referrer-Policy','no-referrer');h.send_header('Connection','keep-alive' if keep else 'close')
        h.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        for k,v in (headers or {}).items():h.send_header(k,v)
        h.end_headers();h.wfile.write(data)
    def body(self,h,token):
        if h.path not in ('/v1/home/poll','/v1/home/pair','/v1/home/world'):self.respond(h,404,dict(ok=False));return
        if not hmac.compare_digest(h.headers.get('Authorization','').encode(),('Bearer '+token).encode()):self.respond(h,401,dict(ok=False));return
        try:
            request=self.read(h)
            if h.path.endswith('/world'):
                from home_world_life import ACTIONS as WORLD_ACTIONS
                if request.get('action') not in WORLD_ACTIONS:raise ValueError('invalid world command')
                with self.world.lock:
                    value=self.world.command(dict(id=request.get('id'),action=request['action'],epoch=self.world.epoch,revision=self.world.revision),'body')|dict(ok=True)
            else:value=self.world.pair_code() if h.path.endswith('/pair') else self.world.body_poll(request)
            self.respond(h,200,value,keep=True)
        except HomeConflict:self.respond(h,409,dict(ok=False,error='stale_body'))
        except (ValueError,TypeError,KeyError):self.respond(h,400,dict(ok=False,error='invalid_request'))
    def read(self,h):
        length=int(h.headers.get('Content-Length','0'))
        if not 0<length<=8192 or h.headers.get('Transfer-Encoding') or h.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('request budget')
        body=h.rfile.read(length)
        if len(body)!=length:raise ValueError('short request')
        request=json.loads(body)
        if not isinstance(request,dict):raise ValueError('invalid object')
        return request
    def post(self,h):
        origin=h.headers.get('Origin','')
        if origin!='https://'+h.headers.get('Host',''):self.respond(h,403,dict(ok=False,error='origin'));return
        try:
            session=self.world.session(h)
            if h.path=='/home/api/asr':
                if not session:self.respond(h,401,dict(ok=False));return
                if not self.world.chat:self.respond(h,503,dict(ok=False));return
                length=int(h.headers.get('Content-Length','0'))
                if h.headers.get('Transfer-Encoding') or h.headers.get('Content-Type')!='audio/wav' or not 44<length<=960044:raise ValueError('recording budget')
                h.connection.settimeout(20);data=h.rfile.read(length)
                if len(data)!=length:raise ValueError('incomplete recording')
                self.respond(h,200,self.world.chat.transcribe(session,h.headers.get('X-Chat-Id',''),data));return
            request=self.read(h)
            if h.path=='/home/api/login':
                token=self.world.login(request.get('code'),request.get('token'),source=h.client_address[0]);self.respond(h,200,dict(ok=True),{'Set-Cookie':'xiaoxi_home='+token+'; Path=/home/; HttpOnly; Secure; SameSite=Strict; Max-Age=7776000'});return
            session=self.world.session(h)
            if not session:self.respond(h,401,dict(ok=False));return
            if h.path.startswith('/home/api/desktop/control/'):
                from desktop_jobs import broker
                controls=broker(self.world.desktop.store);action=h.path.rsplit('/',1)[1]
                if action=='take':value=controls.take(session)
                elif action=='renew':
                    if 'input' in request:controls.input_report(session,request['input'])
                    value=controls.renew(session)
                elif action=='return':value=controls.give_back(session)
                elif action=='resume':controls.resume(request.get('job_id'));value=controls.state(session)
                else:raise ValueError('unknown desktop control action')
                self.respond(h,200,dict(ok=True,**value));return
            if h.path=='/home/api/desktop/open':
                if not self.world.desktop:self.respond(h,503,dict(ok=False));return
                try:self.respond(h,200,self.world.desktop.open())
                except Exception:self.respond(h,503,dict(ok=False,error='desktop_unavailable'))
                return
            if h.path.startswith('/home/api/reminders/'):
                from home_chat import ChatBusy
                action=h.path.rsplit('/',1)[1]
                if action=='presence':
                    with self.world.lock:
                        if request.get('ready') is True:self.world.reminder_presence[session]=self.world.monotonic()
                        else:self.world.reminder_presence.pop(session,None)
                    self.respond(h,200,dict(ok=True));return
                if action=='claim':
                    value=self.world.reminders.claim(session,request.get('id'));self.respond(h,200,dict(ok=True,reminder=({k:value[k] for k in ('id','text','due','lease')} if value else None)));return
                if action=='ack':
                    accepted=self.world.reminders.acknowledge(session,request.get('id'),request.get('lease'),request.get('delivery'));self.respond(h,200,dict(ok=accepted));return
                if action=='audio':
                    reminder=self.world.reminders.validate_claim(session,request.get('id'),request.get('lease'))
                    if not self.world.chat:self.respond(h,503,dict(ok=False));return
                    if not self.world.chat.audio_lock.acquire(blocking=False):raise ChatBusy('voice busy')
                    try:data=self.world.chat.synthesize(session,'时间到了，'+reminder['text'])
                    finally:self.world.chat.audio_lock.release()
                    self.bytes(h,200,data,'audio/wav');return
                self.respond(h,404,dict(ok=False));return
            if h.path in ('/home/api/chat','/home/api/chat/receipt','/home/api/chat/audio'):
                if not self.world.chat:self.respond(h,503,dict(ok=False));return
                if h.path=='/home/api/chat':self.respond(h,202,dict(ok=True,turn=self.world.chat.start(session,request)))
                elif h.path.endswith('/receipt'):self.respond(h,200,self.world.chat.receipt(session,request.get('id','')))
                else:self.bytes(h,200,self.world.chat.audio(session,request.get('id','')),'audio/wav')
                return
            if h.path=='/home/api/command':
                ack=self.world.command(request,'web');self.respond(h,200,self.world.snapshot()|dict(ack=ack))
            elif h.path=='/home/api/pair':self.respond(h,200,self.world.pair_code())
            elif h.path=='/home/api/token':self.respond(h,200,self.world.token_key(session))
            elif h.path=='/home/api/revoke-others':self.respond(h,200,self.world.revoke_others(session))
            elif h.path=='/home/api/logout':
                from desktop_jobs import broker
                broker(self.world.desktop.store).revoke(session)
                self.world.logout(session)
                self.respond(h,200,dict(ok=True),{'Set-Cookie':'xiaoxi_home=; Path=/home/; HttpOnly; Secure; SameSite=Strict; Max-Age=0'})
            else:self.respond(h,404,dict(ok=False))
        except HomeConflict:self.respond(h,409,self.world.snapshot()|dict(error='room_changed'))
        except Exception as error:
            from home_chat import ChatBusy
            from desktop_jobs import DesktopBusy
            if isinstance(error,ChatBusy):self.respond(h,429,dict(ok=False,error='busy'))
            elif isinstance(error,DesktopBusy):self.respond(h,409,dict(ok=False,error='desktop_busy',message=str(error)))
            elif isinstance(error,PermissionError):self.respond(h,403,dict(ok=False,error='pairing_denied'))
            elif isinstance(error,(ValueError,TypeError,KeyError)):self.respond(h,400,dict(ok=False,error='invalid_request'))
            else:self.respond(h,502,dict(ok=False,error='chat_unavailable'))
    def get(self,h):
        path=urlsplit(h.path).path
        public={'/home/':('index.html','text/html; charset=utf-8'),'/home/app.js':('app.js','text/javascript; charset=utf-8'),'/home/style.css':('style.css','text/css; charset=utf-8'),'/home/recorder.js':('recorder.js','text/javascript; charset=utf-8')}
        if path in public:
            file,kind=public[path];self.bytes(h,200,(Path(__file__).parent/'home_web'/file).read_bytes(),kind);return
        session=self.world.session(h)
        if not session:self.respond(h,401,dict(ok=False));return
        if path=='/home/desktop-client.js':self.bytes(h,200,(Path(__file__).parent/'home_web/desktop-client.js').read_bytes(),'text/javascript; charset=utf-8');return
        if path.startswith('/home/novnc/'):
            name=path.removeprefix('/home/novnc/');root=Path(__file__).parent/'vendor/novnc';file=root/name
            if not re.fullmatch(r'(core|vendor)/[A-Za-z0-9_./-]+\.js',name) or any(p in ('','..','.') for p in name.split('/')) or not file.resolve().is_relative_to(root.resolve()) or not file.is_file():self.respond(h,404,dict(ok=False));return
            self.bytes(h,200,file.read_bytes(),'text/javascript; charset=utf-8');return
        if path=='/home/api/desktop/session':
            from desktop_jobs import broker
            value=self.world.desktop.real_status();value.update(broker(self.world.desktop.store).state(session));self.respond(h,200,value);return
        if path=='/home/api/desktop/ws':
            from desktop_jobs import broker
            from desktop_transport import serve
            if h.headers.get('Upgrade','').lower()!='websocket':self.respond(h,426,dict(ok=False));return
            key=(session,'desktop')
            with self.world.lock:
                if self.world.streams.get(key,0)>=2:self.respond(h,429,dict(ok=False));return
                self.world.streams[key]=self.world.streams.get(key,0)+1
            try:serve(h,self.world,session,self.world.desktop,broker(self.world.desktop.store))
            except PermissionError:self.respond(h,403,dict(ok=False))
            except (OSError,ValueError):self.respond(h,503,dict(ok=False,error='desktop_unavailable'))
            finally:
                with self.world.lock:self.world.streams[key]=max(0,self.world.streams.get(key,1)-1)
            return
        if path in ('/home/api/desktop','/home/api/desktop/frame'):
            if not self.world.desktop:self.respond(h,503,dict(ok=False));return
            try:
                if path.endswith('/frame'):self.bytes(h,200,self.world.desktop.frame(),'image/png')
                else:self.respond(h,200,self.world.desktop.status())
            except Exception:self.respond(h,503,dict(ok=False,error='desktop_unavailable'))
            return
        if path=='/home/api/chat':
            self.respond(h,200,dict(ok=True,turns=self.world.chat.history(session))) if self.world.chat else self.respond(h,503,dict(ok=False));return
        if path=='/home/api/state':self.respond(h,200,self.world.snapshot());return
        if path=='/home/events':self.events(h,session);return
        if path=='/home/alerts':self.alerts(h,session);return
        name=path.removeprefix('/home/assets/')
        if path.startswith('/home/assets/') and (name=='manifest.json' or re.fullmatch(r'(room|idle|blink|listen|think|speak|happy|sleep|touch|walk_a|walk_b|lie_sleep|wake|wash_a|wash_b|work_a|work_b|walk_back_a|walk_back_b|yard|side_left_[0-3]|side_right_[0-3]|bed_sit|bed_stretch|stand_stretch|stand_relax|back_right_[ab]|cat_idle|cat_walk_[abcd]|cat_sleep|cat_blink|cat_groom_[ab]|cat_eat_[ab]|cat_pet_[ab]|cat_lie_down|cat_wake|cat_stretch|cat_stand|cat_turn|front_pass_[ab])\.png',name)):
            try:self.bytes(h,200,(self.world.assets/name).read_bytes(),'application/json' if name.endswith('.json') else 'image/png')
            except FileNotFoundError:self.respond(h,404,dict(ok=False))
            return
        self.respond(h,404,dict(ok=False))
    def alerts(self,h,session):
        key=(session,'alerts')
        with self.world.lock:
            if self.world.streams.get(key,0)>=2:self.respond(h,429,dict(ok=False));return
            self.world.streams[key]=self.world.streams.get(key,0)+1
        try:
            h.close_connection=True;h.connection.settimeout(3);h.send_response(200);h.send_header('Content-Type','text/event-stream');h.send_header('Cache-Control','no-store');h.send_header('Connection','close');h.end_headers()
            end=self.world.monotonic()+600
            while self.world.monotonic()<end and not self.world.stop.is_set() and self.world.session(h):
                h.wfile.write(('data: '+compact(dict(reminders=self.world.reminders.due(session)))+'\n\n').encode());h.wfile.flush()
                if self.world.stop.wait(1):break
        except (OSError,ValueError):pass
        finally:
            with self.world.lock:self.world.streams[key]=max(0,self.world.streams.get(key,1)-1)

    def events(self,h,session):
        with self.world.lock:
            if self.world.streams.get(session,0)>=2:self.respond(h,429,dict(ok=False));return
            self.world.streams[session]=self.world.streams.get(session,0)+1
        try:
            h.close_connection=True;h.connection.settimeout(3);h.send_response(200);h.send_header('Content-Type','text/event-stream');h.send_header('Cache-Control','no-store');h.send_header('X-Accel-Buffering','no');h.send_header('Connection','close');h.end_headers();h.wfile.write(b'retry: 1000\n\n');h.wfile.flush()
            end=self.world.monotonic()+600
            while self.world.monotonic()<end and not self.world.stop.is_set() and self.world.session(h):
                h.wfile.write(('data: '+compact(self.world.snapshot())+'\n\n').encode());h.wfile.flush()
                if self.world.stop.wait(.1):break
        except (OSError,ValueError):pass
        finally:
            with self.world.lock:self.world.streams[session]=max(0,self.world.streams.get(session,1)-1)

def dispatch(store,h,token,method,brain=None):
    path=urlsplit(h.path).path
    if not (path.startswith('/home/') or path.startswith('/v1/home/')):return False
    try:
        world=for_store(store,brain)
        if world.stop.is_set():raise ValueError('shared room unavailable')
        api=HomeHTTP(world)
        if method=='GET' and path.startswith('/home/'):api.get(h)
        elif method=='POST' and path.startswith('/v1/home/'):api.body(h,token)
        elif method=='POST':api.post(h)
        else:api.respond(h,404,dict(ok=False))
    except (BrokenPipeError,ConnectionResetError):pass
    except Exception:
        try:HomeHTTP(None).respond(h,503,dict(ok=False,error='home_unavailable'))
        except OSError:pass
    return True

def close_store(store):
    with _instance_lock:world=_instances.get(str(Path(store.media.root).resolve()))
    if world:world.close()
