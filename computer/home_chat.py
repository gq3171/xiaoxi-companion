"""Cookie-authorized web chat, sharing the existing brain without posing as its body.

Browser recordings exist only in request memory. No provider or body credential is
sent to the browser. Durable turn IDs prevent retrying actions after a reconnect.
"""
from runtime_config import settings
import copy,hashlib,io,json,re,secrets,sqlite3,threading,time,wave
from pathlib import Path

ID=re.compile('[0-9a-f]{32}')
class ChatBusy(ValueError):pass

def encode(v):return json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def short(v,n=1024):return str(v).encode()[:n].decode('utf-8','ignore')
def op_id(turn,kind):return hashlib.sha256((turn+':'+kind).encode()).hexdigest()[:32]

class TurnStore:
    """Reuses the authoritative reducer, with a private in-process admission gate.

    It never calls body.open/admit or changes the singleton body generation.
    A browser JSON object cannot construct the identity-checked gate capability.
    """
    def __init__(self,base,gate,session,turn,epoch=None):self.base,self.gate,self.session,self.turn,self.epoch=base,gate,session,turn,base.forget_epoch if epoch is None else epoch
    def __getattr__(self,name):return getattr(self.base,name)
    @property
    def forget_epoch(self):return self.base.forget_epoch
    @forget_epoch.setter
    def forget_epoch(self,value):self.base.forget_epoch=value
    def admit(self,request,advance=True):
        from brain import Conflict
        if self.epoch!=self.base.forget_epoch or request.get('_web_permit') is not self or request.get('session')!=self.turn or not self.gate.authorized(self.session):raise Conflict('web turn no longer authorized')
        return True
    def live(self,request):
        try:self.admit(request);return True
        except ValueError:return False
    def mutate(self,request):return type(self.base).mutate(self,request)
    def propose(self,request,answer,candidate=''):return type(self.base).propose(self,request,answer,candidate)

class HomeChat:
    def __init__(self,world,brain,computer,path):
        initial_epoch=brain.store.forget_epoch
        self.world,self.brain,self.computer=world,brain,computer;self.lock=threading.RLock();self.stop=threading.Event();self.threads=set();self.audio_lock=threading.Lock();self.asr_lock=threading.BoundedSemaphore(2);self.audio_cache={};self.asr_cache={};self.closed=False;self.voice_attempts={}
        self.path=Path(path);self.db=sqlite3.connect(self.path,check_same_thread=False);self.db.row_factory=sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY,session TEXT NOT NULL,fingerprint TEXT NOT NULL,text TEXT NOT NULL,state TEXT NOT NULL,reply TEXT NOT NULL,trace TEXT NOT NULL,created INTEGER NOT NULL)''')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS turn_epochs(id TEXT PRIMARY KEY,epoch INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS web_memory_control(singleton INTEGER PRIMARY KEY,epoch INTEGER NOT NULL);''')
        legacy=self.db.execute('SELECT 1 FROM web_memory_control WHERE singleton=1').fetchone() is None
        if legacy:
            # No epoch existed in old installations. Keep only web copies with
            # an authoritative admitted source; discard orphan private drafts.
            with brain.store.lock:admitted={r[0] for r in brain.store.db.execute('SELECT op_id FROM archive')}
            orphan=[(r[0],) for r in self.db.execute('SELECT id FROM turns') if op_id(r[0],'add:user') not in admitted]
            self.db.executemany("UPDATE turns SET text='',reply='{}',trace='' WHERE id=?",orphan)
        self.db.execute('INSERT OR IGNORE INTO web_memory_control VALUES(1,?)',(initial_epoch,))
        self.db.execute('INSERT OR IGNORE INTO turn_epochs SELECT id,? FROM turns',(initial_epoch,))
        # Uncertain work is displayed as interrupted, never reissued on boot.
        self.db.execute("UPDATE turns SET state='interrupted' WHERE state='working'");self.db.commit();self.path.chmod(0o600)
        self.brain.store.forget_listeners.append(self._forget)
        self.sync_forget()
        # Recover the literal initiating web request for pre-dossier tasks.
        for row in self.db.execute("SELECT text,reply FROM turns WHERE state='done' AND text!='' ORDER BY created,rowid").fetchall():
            job=json.loads(row['reply']).get('job_id')
            if isinstance(job,str) and ID.fullmatch(job):self.computer.tasks.recover_original(job,row['text'])
    def _forget(self,epoch):
        with self.lock,self.db:
            self.db.execute("UPDATE turns SET text='',reply='{}',trace='',state=CASE WHEN state='working' THEN 'interrupted' ELSE state END WHERE id NOT IN (SELECT id FROM turn_epochs WHERE epoch>=?)",(epoch,))
            self.db.execute('UPDATE web_memory_control SET epoch=? WHERE singleton=1',(epoch,))
            self.audio_cache.clear();self.asr_cache.clear()
    def sync_forget(self):
        with self.lock:
            if self.db.execute('SELECT epoch FROM web_memory_control WHERE singleton=1').fetchone()[0]!=self.brain.store.forget_epoch:
                self._forget(self.brain.store.forget_epoch)
    def authorized(self,session):
        with self.world.lock:return not self.stop.is_set() and self.world.sessions.get(session,0)>self.world.clock()
    def start(self,session,value):
        self.sync_forget();epoch=self.brain.store.forget_epoch
        turn,text=value.get('id'),value.get('text');microphone=value.get('microphone',False)
        if not isinstance(turn,str) or not ID.fullmatch(turn) or not isinstance(text,str) or not text.strip() or len(text.encode())>1024 or type(microphone) is not bool:raise ValueError('invalid chat input')
        if not self.authorized(session):raise PermissionError('web authorization expired')
        text=text.strip();fingerprint=hashlib.sha256(encode([text,microphone]).encode()).hexdigest()
        with self.lock:
            if epoch!=self.brain.store.forget_epoch:raise ValueError('chat memory changed')
            row=self.db.execute('SELECT * FROM turns WHERE id=?',(turn,)).fetchone()
            if row:
                if row['session']!=session or row['fingerprint']!=fingerprint:raise ValueError('turn id conflict')
                return self.public(row)
            if self.db.execute("SELECT count(*) FROM turns WHERE state='working'").fetchone()[0]>=4 or self.db.execute("SELECT 1 FROM turns WHERE session=? AND state='working'",(session,)).fetchone():raise ChatBusy('chat busy')
            if self.db.execute('SELECT count(*) FROM turns WHERE session=? AND created>?',(session,int(time.time())-60)).fetchone()[0]>=12:raise ChatBusy('chat rate limited')
            self.db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?,?)',(turn,session,fingerprint,text,'working','{}','',int(time.time())))
            self.db.execute('INSERT INTO turn_epochs VALUES(?,?)',(turn,epoch));self.db.commit()
            worker=threading.Thread(target=self.run,args=(session,turn,text,microphone),name='web-dialogue',daemon=True);self.threads.add(worker);worker.start()
            return dict(id=turn,text=text,state='working',reply={})
    @staticmethod
    def public(row):return dict(id=row['id'],text=row['text'],state=row['state'],reply=json.loads(row['reply']),created=row['created'])
    def history(self,session):
        self.sync_forget();epoch=self.brain.store.forget_epoch
        with self.lock:rows=[self.public(r) for r in reversed(self.db.execute("SELECT * FROM turns WHERE session=? AND text!='' ORDER BY created DESC,rowid DESC LIMIT 24",(session,)).fetchall())]
        # Forgetting the authoritative archive must also remove the web display
        # copy of delivered turns and any cached speech derived from them.
        with self.brain.store.lock:
            forgotten=[r['id'] for r in rows if r['state']=='done' and not self.brain.store.db.execute('SELECT 1 FROM archive WHERE op_id=?',(op_id(r['id'],'add:user'),)).fetchone()]
        if forgotten:
            with self.lock:
                for turn in forgotten:
                    self.db.execute("UPDATE turns SET text='',reply='{}',trace='' WHERE id=?",(turn,));self.audio_cache.pop((session,turn),None)
                self.db.commit()
            rows=[r for r in rows if r['id'] not in forgotten]
        for row in rows:
            job_id=row['reply'].get('job_id')
            if job_id:
                job=self.computer.get(job_id)
                if job:row['reply']['job_state']=job['state'];row['reply']['job_message']=short(job.get('message',''),1200)
        if epoch!=self.brain.store.forget_epoch:self.sync_forget();return []
        return rows
    def focus(self,session):
        with self.lock:
            rows=self.db.execute("SELECT reply FROM turns WHERE session=? AND state='done' ORDER BY created DESC,rowid DESC LIMIT 24",(session,)).fetchall()
        for row in rows:
            identifier=json.loads(row[0]).get('job_id')
            if identifier:
                job=self.computer.get(identifier)
                if job and job['state'] in ('queued','running','interrupted'):return identifier
        return None
    def envelope(self,session,turn):
        with self.lock:row=self.db.execute('SELECT epoch FROM turn_epochs WHERE id=?',(turn,)).fetchone()
        epoch=row[0] if row else self.brain.store.forget_epoch
        store=TurnStore(self.brain.store,self,session,turn,epoch);return store,dict(device='000000000000',boot=1,session=turn,generation=1,_web_permit=store)
    def mutate(self,store,request,turn,kind,**fields):
        return store.mutate(request|dict(operation=dict(op_id=op_id(turn,kind),kind=kind.split(':')[0],**fields)))
    def run(self,session,turn,text,microphone):
        store,request=self.envelope(session,turn)
        try:
            with self.world.lock:self.world.life.last_engaged=self.world.clock()
            shared=self.world.snapshot();state={'channel':'web','input':'主人主动点击网页麦克风并确认发送' if microphone else '主人在已授权网页主动输入','room':{'activity':shared['activity'],'position':shared['wire'][:2]},'world':shared.get('world'),'time_beijing':__import__('datetime').datetime.fromtimestamp(time.time(),__import__('datetime').timezone(__import__('datetime').timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S'),'reminders':self.world.reminders.active(),'recent_reminders':self.world.reminders.recent(),'capabilities':'共同世界已支持小猫和小院。明确去小院、回家、摸小猫、添猫饭时action=speak并附world_action=yard|home|catpet|catfeed；先实际保存/执行再确认。睡觉、洗漱、工作会先回家；当前位置与小猫状态见world。仅要求设提醒时不要立刻执行world_action。不编造未去过的地点。当前网页版支持真实持久定时提醒：创建用reminder={text,due:YYYY-MM-DD HH:MM,repeat_minutes:0,delivery:local|body|both,delivery_request:当前用户原句中明确指定目的端的片段}；默认local，绑定发起的这个网页，网页关闭/断线后在原网页恢复时补送，不转移到板子或其他电脑。只有主人本句明确要求在家里小板子提醒时用body，明确同时在网页和板子提醒时用both；跨端必须附原句中完整肯定的delivery_request片段，否定或含糊时不跨端，不接受旧对话授权。；支持list_reminders/cancel_reminder+reminder_id。用户说5分钟后喊我也是创建提醒，按服务端北京时间理解，不要回答做不到。追问还要多久、刚才是否提醒时使用list_reminders，结合reminders和recent_reminders区分未到点/到点待播/客户端已播完/仅屏幕确认；播放完成回报不表示主人实际听到，不因待办为空就说没有安排过。当前可文字/语音对话、查询资料、单个home_action(roam/rest/wake/wash/work/window)、computer_task/computer_cancel/computer_status。不支持板端电源/熄屏、连续life_plan或life_control、媒体展示控制；不要宣称已执行这些。电脑操作沿用原有权限与限制，不能绕过。'}
            focus=self.focus(session)
            if focus:request['_focus_job']=focus
            state['task_protocol']=2
            state['capabilities']+=' 支持computer_resume和computer_update；附当前job_id，task_note须引用本轮主人明确补充的原句。已有任务补充条件或继续必须沿用原任务，不另建任务。'
            endpoint=copy.copy(self.brain);endpoint.store=store
            result=endpoint.model(request|dict(kind='dialogue',candidate=text,microphone=False,system=encode(state)))
            answer=json.loads(result['text']);store.admit(request)
            if answer.get('input','direct')!='direct' or answer.get('action')=='ignore':answer=dict(say='刚才这句我没弄清楚，你可以换个说法。',action='speak',remember=False)
            source=self.mutate(store,request,turn,'add:user',role='user',text=text,owner=answer.get('remember') is True)
            trace=answer.get('_trace','')
            if ID.fullmatch(trace):self.mutate(store,request,turn,'feedback:accepted',trace=trace,stage='accepted',source_id=source['result'])
            reply=self.actions(store,request,turn,answer,text)
            store.admit(request)
            with self.world.lock:
                store.admit(request);self.world.web_caption=reply.get('say','');self.world.web_caption_until=self.world.monotonic()+20;self.world.web_caption_epoch=store.epoch
            if reply.get('say'):self.mutate(store,request,turn,'add:assistant',role='assistant',text=short(reply['say']),owner=False)
            with self.lock:
                if store.epoch!=self.brain.store.forget_epoch:raise ValueError('chat memory changed')
                self.db.execute("UPDATE turns SET state='done',reply=?,trace=? WHERE id=?",(encode(reply),trace,turn));self.db.execute("UPDATE turns SET text='',reply='{}',trace='' WHERE id IN (SELECT id FROM turns ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET 64)");self.db.execute('DELETE FROM turns WHERE created<? AND state!=\'working\'',(int(time.time())-90*86400,));self.db.commit()
        except Exception:
            # No provider exception, transcript or token enters a log/error response.
            with self.lock:self.db.execute("UPDATE turns SET state='failed',reply=? WHERE id=?",(encode(dict(say='这次没能接上，你可以稍后再跟我说。已提交的任务不会自动重做。')),turn));self.db.commit()
        finally:
            with self.lock:
                self.threads.discard(threading.current_thread())
                if self.closed and not self.threads:self.db.close()
    def actions(self,store,request,turn,answer,candidate):
        action=answer.get('action','speak');say=short(answer.get('say',''),4096);job=None
        if answer.get('reminder'):
            with self.lock:created=self.db.execute('SELECT created FROM turns WHERE id=?',(turn,)).fetchone()[0]
            store.admit(request)
            try:
                reminder=self.world.reminders.create(turn,answer['reminder'],candidate,created,origin=store.session)
                from home_reminders import TZ
                from datetime import datetime
                say='好，'+datetime.fromtimestamp(reminder['due'],TZ).strftime('%H:%M:%S')+{'local':'在这个网页叫你；网页关掉的话，回来后补提醒。','body':'让家里的小板子叫你。','both':'在这个网页和家里的小板子都提醒你。'}[reminder['delivery_scope']]
            except ValueError:say='这次提醒没有保存成功，时间、内容或提醒端需要再确认一下。'
        elif action=='list_reminders':
            from home_reminders import describe_reminders
            say=describe_reminders(self.world.reminders)
        elif action=='cancel_reminder':
            store.admit(request);identifier=answer.get('reminder_id');rows=self.world.reminders.active()
            if identifier is None and len(rows)==1:identifier=rows[0]['id']
            explicit=any(k in candidate for k in ('取消','删除','别提醒','不要提醒'))
            say='这条提醒已经取消了。' if explicit and type(identifier) is int and self.world.reminders.cancel(identifier) else '没有取消提醒，请告诉我是列表中的哪一条。'
        elif answer.get('life_plan') or answer.get('life_control') or answer.get('screen_action') or answer.get('media_action') :
            say='这个操作网页版暂时还没接好，我先不改动原来的安排。'
        elif action=='computer_task':
            goal=answer.get('task');store.admit(request)
            if not isinstance(goal,str) or not goal.strip() or len(goal.encode())>1024:raise ValueError('invalid task')
            try:
                job=self.computer.submit(op_id(turn,'job'),goal,original_request=candidate)
                with self.computer.lock:busy=self.computer.db.execute("SELECT 1 FROM jobs WHERE state='running' AND id!=?",(job['id'],)).fetchone()
                say='好呀，已排进队列，前面的任务结束后接着做。你可以继续和我聊。' if busy else '好呀，我去弄。你可以继续和我聊。'
            except ValueError:say='这次没有提交成功，可能队列已满；我先保留当前任务，请查看任务状态。'
        elif action in ('computer_resume','computer_update'):
            from task_control import control
            note=answer.get('task_note',candidate if action=='computer_update' else '')
            if not isinstance(note,str) or (note and note not in candidate):raise ValueError('owner amendment must quote the current request')
            # Preserve the whole authenticated input: a model-selected substring
            # could otherwise remove a negation and fabricate an authorization.
            if note or action=='computer_update':note=candidate
            try:
                job=control(self.computer,action,op_id(turn,'task-control'),note,answer.get('job_id'),request.get('_focus_job'),lambda:store.live(request))
                say=('补充要求已经保存；原命令的结果还需要核对，任务仍暂停，没有重做。' if job['state']=='interrupted' else '补充要求已记在原任务里，我会按当前进度继续核对。') if note else '好，接着原来的任务，先核对当前实际进度。'
            except ValueError as error:
                say=str(error) if str(error).startswith(('没有找到','这项任务','命令任务','请先交回')) else '这次没有恢复任务，请先核对任务状态；私密信息请用专用填写窗。'
        elif action=='computer_cancel':
            from task_status import select
            rows=select(self.computer,answer.get('job_id'),focus=request.get('_focus_job'))
            target=rows[0] if rows else None
            if target and target['state'] in ('queued','running','interrupted'):
                with self.computer.lock:
                    store.admit(request);job=self.computer.cancel(target['id'])
                say='原任务已经停止，不会再继续执行。' if job['state']=='cancelled' else '已经把停止请求交给电脑了。'
            else:say='现在没有找到需要停止的任务。'
        world_action=answer.get('world_action')
        if world_action and not answer.get('reminder'):
            from home_world_life import ACTIONS as WORLD_ACTIONS
            if world_action not in WORLD_ACTIONS:raise ValueError('unsupported world action')
            with self.world.lock:
                store.admit(request);self.world.command(dict(id=op_id(turn,'world'),epoch=self.world.epoch,revision=self.world.revision,action=world_action),'web')
            say={'yard':'好呀，我带小猫去小院走走。','home':'嗯，我们回家。','catpet':'摸摸，小家伙都眯起眼了。','catfeed':'给小猫添好吃的啦。'}[world_action]
        home=answer.get('home_action')
        if home and not world_action and not any(answer.get(k) for k in ('life_plan','life_control','screen_action')):
            if home not in ('roam','rest','wake','wash','work','window'):raise ValueError('unsupported home action')
            with self.world.lock:
                store.admit(request);self.world.command(dict(id=op_id(turn,'home'),epoch=self.world.epoch,revision=self.world.revision,action=home),'web')
        return dict(say=say or '我在呢。',mood=answer.get('mood','calm'),job_id=job['id'] if job else '',job_state=job['state'] if job else '')
    def receipt(self,session,turn):
        with self.lock:row=self.db.execute('SELECT * FROM turns WHERE id=? AND session=?',(turn,session)).fetchone()
        if not row or row['state']!='done':raise ValueError('missing delivered turn')
        if ID.fullmatch(row['trace']):
            store,request=self.envelope(session,turn);self.mutate(store,request,turn,'feedback:displayed',trace=row['trace'],stage='displayed',source_id=0)
        return dict(ok=True)
    def voice_budget(self,session,kind):
        now=time.monotonic();key=(session,kind)
        with self.lock:
            recent=[t for t in self.voice_attempts.get(key,[]) if now-t<60]
            if len(recent)>=12:raise ChatBusy('voice rate limited')
            self.voice_attempts[key]=recent+[now]
            if len(self.voice_attempts)>32:
                for old in list(self.voice_attempts):
                    if now-self.voice_attempts[old][-1]>60:self.voice_attempts.pop(old)
    def transcribe(self,session,turn,data):
        self.sync_forget();epoch=self.brain.store.forget_epoch
        if not ID.fullmatch(turn):raise ValueError('invalid recording id')
        digest=hashlib.sha256(data).hexdigest();key=(session,turn)
        with self.lock:
            old=self.asr_cache.get(key)
            if old:
                if old[0]!=digest:raise ValueError('recording id reused')
                if old[1] is None:raise ChatBusy('recording in progress')
                return old[1]
            if len(self.asr_cache)>64:self.asr_cache.pop(next(iter(self.asr_cache)))
            self.asr_cache[key]=(digest,None)
        if not self.asr_lock.acquire(blocking=False):
            with self.lock:self.asr_cache.pop(key,None)
            raise ChatBusy('recording busy')
        try:
            self.voice_budget(session,'asr')
            if len(data)<44 or data[:4]!=b'RIFF' or data[8:12]!=b'WAVE':raise ValueError('invalid recording')
            with wave.open(io.BytesIO(data),'rb') as audio:
                if audio.getparams()[:3]!=(1,2,16000) or not 4800<=audio.getnframes()<=480000:raise ValueError('invalid recording format')
                pcm=audio.readframes(audio.getnframes())
                if len(pcm)!=audio.getnframes()*2:raise ValueError('truncated recording')
            clean=io.BytesIO()
            with wave.open(clean,'wb') as out:out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(pcm)
            body=b'------deskpet\r\nContent-Disposition: form-data; name="model"\r\n\r\n'+settings()['speech']['asr_model'].encode()+b'\r\n------deskpet\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n'+clean.getvalue()+b'\r\n------deskpet--\r\n'
            if not self.authorized(session):raise PermissionError('expired')
            with self.brain.provider.request('/v1/speech_to_text',body,'multipart/form-data; boundary=----deskpet',True) as response:raw=response.read(32769)
            if len(raw)>32768 or not self.authorized(session):raise ValueError('expired transcription')
            value=json.loads(raw);text=value.get('text','')
            if value.get('base_resp',{}).get('status_code',0)!=0:raise ValueError('transcription rejected')
            if not isinstance(text,str) or not text.strip() or len(text.encode())>1024:raise ValueError('empty or long transcription')
            result=dict(ok=True,text=text.strip())
            with self.lock:
                if epoch!=self.brain.store.forget_epoch:raise ValueError('chat memory changed')
                self.asr_cache[key]=(digest,result)
            return result
        except (wave.Error,EOFError):raise ValueError('invalid recording') from None
        finally:
            with self.lock:
                if self.asr_cache.get(key,(None,None))[1] is None:self.asr_cache.pop(key,None)
            self.asr_lock.release()
    def audio(self,session,turn):
        self.sync_forget();epoch=self.brain.store.forget_epoch
        with self.lock:
            row=self.db.execute("SELECT reply FROM turns WHERE session=? AND id=? AND state='done' AND text!=''",(session,turn)).fetchone()
            cached=self.audio_cache.get((session,turn))
        if not row:raise ValueError('missing spoken reply')
        if cached:return cached
        if not self.audio_lock.acquire(blocking=False):raise ChatBusy('voice busy')
        try:
            say=short(json.loads(row['reply']).get('say',''),4096)
            data=self.synthesize(session,say)
            with self.lock:
                if epoch!=self.brain.store.forget_epoch:raise ValueError('chat memory changed')
                self.audio_cache[(session,turn)]=data
                while len(self.audio_cache)>2:self.audio_cache.pop(next(iter(self.audio_cache)))
            return data
        finally:self.audio_lock.release()
    def synthesize(self,session,say):
        self.voice_budget(session,'tts')
        speech=dict(model=settings()['speech']['tts_model'],text=say,stream=False,voice_setting=dict(voice_id=settings()['speech']['default_voice'],speed=1,vol=1,pitch=0),audio_setting=dict(sample_rate=16000,format='pcm',channel=1))
        if not self.authorized(session):raise PermissionError('expired')
        with self.brain.provider.request('/v1/t2a_v2',encode(speech).encode()) as response:raw=response.read(8*1024*1024+1)
        if len(raw)>8*1024*1024 or not self.authorized(session):raise ValueError('audio budget')
        value=json.loads(raw)
        if value.get('base_resp',{}).get('status_code',0)!=0:raise ValueError('voice rejected')
        pcm=bytes.fromhex(value['data']['audio'])
        if not pcm or len(pcm)>4*1024*1024 or len(pcm)%2:raise ValueError('audio budget')
        out=io.BytesIO()
        with wave.open(out,'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(pcm)
        return out.getvalue()
    def close(self):
        if self.closed:return
        self.closed=True;self.stop.set()
        if self._forget in self.brain.store.forget_listeners:self.brain.store.forget_listeners.remove(self._forget)
        # In-flight network calls may take time; they lose authorization and can
        # no longer commit or perform a new action. Keep their SQLite handle alive.
        with self.lock:
            self.audio_cache.clear();self.asr_cache.clear()
            if not self.threads:self.db.close()
