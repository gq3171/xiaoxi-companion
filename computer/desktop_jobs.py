"""One desktop owner; durable task checkpoints and explicit human hand-back."""
import contextlib,json,re,sqlite3,threading,time

ID=re.compile(r'[0-9a-f]{32}\Z')
_lock=threading.Lock()
class DesktopBusy(ValueError):pass

def broker(store):
    with _lock:
        if not hasattr(store,'_desktop_jobs'):store._desktop_jobs=DesktopJobs(store)
        return store._desktop_jobs

class DesktopJobs:
    def __init__(self,store,clock=time.monotonic):
        self.store=store;self.clock=clock;self.condition=threading.Condition(store.lock);self.lease=None;self.inflight=False;self.transports={};self.last_input_report=0.
        with store.lock:
            store.db.execute('CREATE TABLE IF NOT EXISTS desktop_jobs(job TEXT PRIMARY KEY,phase TEXT NOT NULL,checkpoint TEXT NOT NULL,updated INTEGER NOT NULL)');store.db.commit()
    def _row(self,job):
        return self.store.db.execute('SELECT * FROM desktop_jobs WHERE job=?',(job,)).fetchone()
    def save(self,job,value,phase='running'):
        if not ID.fullmatch(job):raise ValueError('invalid desktop job')
        with self.condition:
            previous=self._row(job)
            if previous and json.loads(previous['checkpoint']).get('manual_input'):
                value=dict(value,manual_input=True)
                value['browser']=dict(value.get('browser',{}),privacy_tainted=True)
            raw=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
            if len(raw.encode())>160*1024:raise ValueError('desktop checkpoint budget')
            if phase=='running' and (self.lease or previous and previous['phase']=='waiting_user'):phase='waiting_user'
            self.store.db.execute('INSERT INTO desktop_jobs VALUES(?,?,?,?) ON CONFLICT(job) DO UPDATE SET phase=excluded.phase,checkpoint=excluded.checkpoint,updated=excluded.updated',(job,phase,raw,int(time.time())));self.store.db.commit();self.condition.notify_all()
    def load(self,job):
        with self.store.lock:
            row=self._row(job);return json.loads(row['checkpoint']) if row else None
    def phase(self,job,phase,message=None):
        with self.condition:
            self.store.db.execute('UPDATE desktop_jobs SET phase=?,updated=? WHERE job=?',(phase,int(time.time()),job))
            if message:self.store.db.execute('UPDATE jobs SET message=?,updated=? WHERE id=?',(message[:600],int(time.time()),job))
            self.store.db.commit();self.condition.notify_all()
    def _expire(self):
        if self.lease and self.clock()>=self.lease['until']:
            self.lease=None;self.condition.notify_all()
    def controls(self,session):
        with self.condition:
            self._expire();return bool(self.lease and self.lease['session']==session)
    def transport_open(self,session):
        with self.condition:
            if not self.controls(session):raise PermissionError('desktop control expired')
            key=object();self.transports[key]=dict(session=session,bytes=0);return key
    def transport_bytes(self,key,size):
        with self.condition:
            if key in self.transports:self.transports[key]['bytes']+=size
    def transport_close(self,key):
        with self.condition:self.transports.pop(key,None)
    def input_report(self,session,value):
        # Counts only: no keys, coordinates, payloads or session identifiers.
        fields=('down','up','pointerDown','pointerUp','nonzero','click','wheel','keys','connected')
        if not isinstance(value,dict) or set(value)!=set(fields) or any(type(value[k]) is not int or not 0<=value[k]<=1000000000 for k in fields):raise ValueError('invalid input counters')
        with self.condition:
            if not self.controls(session):raise PermissionError('desktop control expired')
            now=self.clock()
            if now-self.last_input_report<5:return
            self.last_input_report=now;channels=[t for t in self.transports.values() if t['session']==session]
            print('desktop_input '+json.dumps(dict(**value,channels=len(channels),forwarded_bytes=sum(t['bytes'] for t in channels)),separators=(',',':')),flush=True)
    def current(self):
        with self.store.lock:
            row=self.store.db.execute("SELECT d.job FROM desktop_jobs d JOIN jobs j ON j.id=d.job WHERE d.phase!='done' AND j.state IN ('queued','running','interrupted') ORDER BY CASE WHEN j.state IN ('running','queued') THEN 0 ELSE 1 END,d.updated DESC LIMIT 1").fetchone()
            return row['job'] if row else None
    def state(self,session=None):
        with self.condition:
            self._expire();job=self.current();row=self._row(job) if job else None
            actual=self.store.db.execute('SELECT state,message FROM jobs WHERE id=?',(job,)).fetchone() if job else None
            phase='interrupted' if actual and actual['state']=='interrupted' else row['phase'] if row else 'idle'
            if actual and actual['state'] in ('succeeded','failed','cancelled'):phase='idle'
            return dict(job_id=job,phase=phase,message=actual['message'] if actual else '',control=self.controls(session) if session else False,control_connected=bool(session and self.controls(session) and any(t['session']==session for t in self.transports.values())),control_busy=bool(self.lease and self.lease['session']!=session),can_resume=bool(actual and actual['state']=='interrupted'),lease_seconds=max(0,int(self.lease['until']-self.clock())) if self.lease and self.lease['session']==session else 0)
    def take(self,session):
        with self.condition:
            self._expire()
            if self.lease and self.lease['session']!=session:raise DesktopBusy('另一台电脑正在接管')
            if self.inflight:raise DesktopBusy('小溪正在结束当前动作，稍后再试')
            self.lease=dict(session=session,until=self.clock()+120)
            job=self.current()
            if job:
                checkpoint=self.load(job)
                if checkpoint:
                    checkpoint['manual_input']=True
                    checkpoint.setdefault('browser',{})['privacy_tainted']=True
                    self.save(job,checkpoint,phase='waiting_user')
                self.phase(job,'waiting_user','桌面已交给你。完成当前步骤后，点“交回小溪”。')
            return self.state(session)
    def renew(self,session):
        with self.condition:
            if not self.controls(session):raise PermissionError('desktop control expired')
            self.lease['until']=self.clock()+120;return self.state(session)
    def give_back(self,session):
        with self.condition:
            if not self.controls(session):raise PermissionError('desktop control is not owned')
            self.lease=None;job=self.current()
            if job:self.resume(job)
            self.condition.notify_all();return self.state(session)
    def revoke(self,session):
        with self.condition:
            if self.controls(session):self.lease=None;self.condition.notify_all()
    def resume(self,job):
        with self.condition:
            if not isinstance(job,str) or not ID.fullmatch(job) or not self._row(job):raise ValueError('没有可续办的桌面任务')
            row=self.store.db.execute('SELECT state,cancel FROM jobs WHERE id=?',(job,)).fetchone()
            if not row or row['cancel'] or row['state'] not in ('running','interrupted'):raise ValueError('任务当前不能续办')
            if self.lease:raise DesktopBusy('请先交回桌面')
            try:self.store.db.execute("UPDATE jobs SET state=?,message=?,updated=? WHERE id=?",('queued' if row['state']=='interrupted' else 'running','正在核对当前页面，再继续原任务。',int(time.time()),job))
            except sqlite3.IntegrityError:
                self.store.db.rollback();raise DesktopBusy('请先结束当前另一项任务') from None
            self.store.db.execute("UPDATE desktop_jobs SET phase='resume_requested',updated=? WHERE job=?",(int(time.time()),job));self.store.db.commit();self.condition.notify_all()
    def waiting(self,job):
        with self.condition:
            self._expire();row=self._row(job)
            return bool(self.lease or row and row['phase']=='waiting_user')
    @contextlib.contextmanager
    def private_action(self,job):
        # Owner input may run while waiting_user, but cannot race a noVNC lease
        # or another in-flight action. Never hold this condition during CDP I/O.
        with self.condition:
            self._expire()
            row=self.store.db.execute('SELECT state,cancel FROM jobs WHERE id=?',(job,)).fetchone()
            if self.lease or self.inflight or not row or row['state']!='running' or row['cancel']:
                raise DesktopBusy('桌面当前不能执行私密填写')
            self.inflight=True
        try:yield
        finally:
            with self.condition:self.inflight=False;self.condition.notify_all()
    @contextlib.contextmanager
    def action(self,job,revision=None):
        with self.condition:
            row=self.store.get(job)
            if not row or row['cancel'] or row['state']!='running':raise DesktopBusy('任务已停止，旧动作未发出')
            if self.waiting(job):raise DesktopBusy('桌面正在等待主人处理')
            if revision is not None and revision!=self.store.tasks.revision(job):raise DesktopBusy('主人已补充要求，旧动作未发出')
            self.inflight=True
        try:yield
        finally:
            with self.condition:self.inflight=False;self.condition.notify_all()
