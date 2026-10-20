"""Durable owner-requested reminders, leased to one ready web/body recipient."""
from datetime import datetime,timezone,timedelta
import math,re,secrets,sqlite3,threading,time
from pathlib import Path
TZ=timezone(timedelta(hours=8))

def chinese_number(text):
    if text.isdecimal():return int(text)
    digits={'零':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    if text in digits:return digits[text]
    if text.count('十')==1:
        a,b=text.split('十');return (digits.get(a,1) if a else 1)*10+(digits.get(b,0) if b else 0)
    raise ValueError('unsupported duration')

def deadline(spec,candidate,created):
    match=re.search(r'([0-9零一二三四五六七八九十两]+)\s*(秒钟?|分钟?|小时|天)(?:之?后|以后)',candidate)
    if match:
        delay=chinese_number(match[1])*({'天':86400,'小时':3600}.get(match[2],60 if match[2].startswith('分') else 1))
        if not 1<=delay<=366*86400:raise ValueError('duration out of range')
        return created+delay
    if re.search(r'半(?:个)?小时(?:之?后|以后)',candidate):return created+1800
    due=spec.get('due')
    if not isinstance(due,str):raise ValueError('missing due')
    return int(datetime.strptime(due,'%Y-%m-%d %H:%M').replace(tzinfo=TZ).timestamp())

class ReminderStore:
    def __init__(self,path,clock=time.time):
        self.clock=clock;self.lock=threading.RLock();self.path=Path(path);self.db=sqlite3.connect(self.path,check_same_thread=False);self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('''CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id TEXT UNIQUE NOT NULL,text TEXT NOT NULL,due INTEGER NOT NULL,repeat_minutes INTEGER NOT NULL,state TEXT NOT NULL,recipient TEXT NOT NULL,lease TEXT NOT NULL,lease_until INTEGER NOT NULL,delivered TEXT NOT NULL,created INTEGER NOT NULL)''')
        with self.db:
            columns={r['name'] for r in self.db.execute('PRAGMA table_info(reminders)')}
            for name in ('origin','delivery_scope'):
                if name not in columns:self.db.execute("ALTER TABLE reminders ADD COLUMN "+name+" TEXT NOT NULL DEFAULT ''")
            self.db.execute('''CREATE TABLE IF NOT EXISTS reminder_deliveries(reminder INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,target TEXT NOT NULL,due INTEGER NOT NULL,state TEXT NOT NULL,lease TEXT NOT NULL DEFAULT '',lease_until INTEGER NOT NULL DEFAULT 0,delivered TEXT NOT NULL DEFAULT '',PRIMARY KEY(reminder,target))''')
            self.migrate_sources()
        self.path.chmod(0o600);self.closed=False
    def migrate_sources(self):
        # Recover old web origins from existing turn IDs, never from current presence.
        origins={};web=self.path.with_name('web-chat.sqlite3')
        if web.exists():
            try:
                with sqlite3.connect('file:'+str(web)+'?mode=ro',uri=True) as d:origins=dict(d.execute('SELECT id,session FROM turns'))
            except sqlite3.DatabaseError:pass
        for row in self.db.execute("SELECT * FROM reminders WHERE NOT EXISTS(SELECT 1 FROM reminder_deliveries d WHERE d.reminder=reminders.id)").fetchall():
            origin=row['origin'] or origins.get(row['request_id'],'')
            if not origin and row['recipient']:origin=row['recipient']
            if not origin:
                self.db.execute("UPDATE reminders SET delivery_scope='unassigned' WHERE id=?",(row['id'],));continue
            self.db.execute("UPDATE reminders SET origin=?,delivery_scope='local' WHERE id=?",(origin,row['id']))
            target=row['recipient'] if row['state']=='delivered' and row['recipient'] else origin
            matched=row['recipient']==target
            state=row['state'] if matched or row['state'] in ('delivered','cancelled') else 'scheduled'
            self.db.execute('INSERT INTO reminder_deliveries VALUES(?,?,?,?,?,?,?)',(row['id'],target,row['due'],state,row['lease'] if matched else '',row['lease_until'] if matched else 0,row['delivered']))
    @staticmethod
    def targets(spec,candidate,origin):
        if not isinstance(origin,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',origin):raise ValueError('source endpoint required')
        scope=spec.get('delivery','local')
        if scope not in ('local','body','both'):raise ValueError('unknown reminder destination')
        if scope!='local' and origin!='body':
            quote=spec.get('delivery_request','')
            if not isinstance(quote,str) or not quote or quote not in candidate or len(quote)>256 or not any(w in quote for w in ('小板子','板子','家里','两边','两端','同步')) or re.search(r'(不要|别|不能|不在|不用|不让)[^，。；,;]{0,8}(板子|家里|两边|两端|同步)',candidate[max(0,candidate.find(quote)-6):candidate.find(quote)+len(quote)]):raise ValueError('explicit cross-endpoint request required')
        if scope=='both' and origin=='body':raise ValueError('a particular web endpoint is required')
        return scope,list(dict.fromkeys([origin] if scope=='local' else ['body'] if scope=='body' else [origin,'body']))
    def create(self,request_id,spec,candidate,created,*,origin=None):
        if not isinstance(spec,dict) or not any(word in candidate for word in ('提醒','闹钟','闹铃','叫我','喊我')):raise ValueError('explicit reminder required')
        scope,targets=self.targets(spec,candidate,origin)
        with self.lock:
            old=self.db.execute('SELECT * FROM reminders WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['origin']!=origin:raise ValueError('reminder source mismatch')
                return dict(old)
        text=spec.get('text');repeat=spec.get('repeat_minutes',0)
        if not isinstance(text,str) or not text.strip() or len(text.encode())>240 or type(repeat) is not int or repeat<0 or repeat>10080 or 0<repeat<5 or (repeat and '每' not in candidate):raise ValueError('invalid reminder')
        due=deadline(spec,candidate,created);now=int(self.clock())
        if not now<due<=now+366*86400:raise ValueError('invalid reminder time')
        with self.lock,self.db:
            old=self.db.execute('SELECT * FROM reminders WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['origin']!=origin:raise ValueError('reminder source mismatch')
                return dict(old)
            if self.db.execute("SELECT count(*) FROM reminders WHERE state IN ('scheduled','claimed')").fetchone()[0]>=8:raise ValueError('reminder budget')
            cursor=self.db.execute("INSERT INTO reminders(request_id,text,due,repeat_minutes,state,recipient,lease,lease_until,delivered,created,origin,delivery_scope) VALUES(?,?,?,?,'scheduled','','',0,'',?,?,?)",(request_id,text.strip(),due,repeat,now,origin,scope));identifier=cursor.lastrowid
            for target in targets:self.db.execute("INSERT INTO reminder_deliveries(reminder,target,due,state) VALUES(?,?,?,'scheduled')",(identifier,target,due))
            self.db.execute("DELETE FROM reminders WHERE id IN (SELECT id FROM reminders WHERE state IN ('delivered','cancelled') ORDER BY created DESC,id DESC LIMIT -1 OFFSET 128)")
            return dict(self.db.execute('SELECT * FROM reminders WHERE id=?',(identifier,)).fetchone())
    def route_states(self,identifier):
        return [dict(channel='body' if r['target']=='body' else 'web',state=r['state'],due=r['due'],delivered=r['delivered']) for r in self.db.execute('SELECT * FROM reminder_deliveries WHERE reminder=? ORDER BY target',(identifier,))]
    def active(self):
        with self.lock:
            rows=[dict(r) for r in self.db.execute("SELECT id,text,due,repeat_minutes,state,delivery_scope FROM reminders WHERE state IN ('scheduled','claimed') ORDER BY due,id")]
            for r in rows:r['targets']=self.route_states(r['id'])
            return rows
    def recent(self):
        since=int(self.clock())-86400
        with self.lock:
            rows=[dict(r) for r in self.db.execute("SELECT id,text,due,repeat_minutes,state,delivered,delivery_scope,CASE WHEN recipient='body' THEN 'body' ELSE 'web' END AS channel FROM reminders WHERE (state='delivered' AND due>=?) OR (state='cancelled' AND created>=?) ORDER BY CASE WHEN state='delivered' THEN due ELSE created END DESC,id DESC LIMIT 4",(since,since))]
            for r in rows:r['targets']=self.route_states(r['id'])
            return rows
    def due(self,recipient=None):
        if not isinstance(recipient,str):return []
        with self.lock:return [dict(r) for r in self.db.execute("SELECT r.id,r.text,d.due,r.repeat_minutes,d.state,r.delivery_scope FROM reminders r JOIN reminder_deliveries d ON r.id=d.reminder WHERE d.target=? AND d.due<=? AND d.state IN ('scheduled','claimed') AND r.state!='cancelled' ORDER BY d.due,r.id",(recipient,self.clock()))]
    def cancel(self,identifier):
        if type(identifier) is not int:raise ValueError('invalid reminder id')
        with self.lock,self.db:
            changed=bool(self.db.execute("UPDATE reminders SET state='cancelled',lease='',lease_until=0 WHERE id=? AND state IN ('scheduled','claimed')",(identifier,)).rowcount)
            if changed:self.db.execute("UPDATE reminder_deliveries SET state='cancelled',lease='',lease_until=0 WHERE reminder=?",(identifier,))
            return changed
    def refresh(self,identifier,recipient=None,delivery=None):
        rows=self.db.execute('SELECT * FROM reminder_deliveries WHERE reminder=?',(identifier,)).fetchall()
        if not rows:return
        active=[r for r in rows if r['state'] in ('scheduled','claimed')]
        state='claimed' if any(r['state']=='claimed' for r in active) else 'scheduled' if active else 'delivered' if any(r['state']=='delivered' for r in rows) else 'cancelled'
        self.db.execute('UPDATE reminders SET state=? WHERE id=?',(state,identifier))
        if active:self.db.execute('UPDATE reminders SET due=? WHERE id=?',(min(r['due'] for r in active),identifier))
        if recipient is not None:self.db.execute('UPDATE reminders SET recipient=?,delivered=? WHERE id=?',(recipient,delivery,identifier))
    def claim(self,recipient,identifier=None):
        if identifier is not None and (type(identifier) is not int or identifier<1):raise ValueError('invalid reminder id')
        now=int(self.clock())
        with self.lock,self.db:
            expired=[r[0] for r in self.db.execute("SELECT reminder FROM reminder_deliveries WHERE target=? AND state='claimed' AND lease_until<=?",(recipient,now))]
            self.db.execute("UPDATE reminder_deliveries SET state='scheduled',lease='',lease_until=0 WHERE target=? AND state='claimed' AND lease_until<=?",(recipient,now))
            for key in expired:self.refresh(key)
            candidates=self.due(recipient)
            for candidate in candidates:
                if identifier is not None and candidate['id']!=identifier:continue
                row=self.db.execute('SELECT * FROM reminder_deliveries WHERE reminder=? AND target=?',(candidate['id'],recipient)).fetchone()
                if row['state']!='claimed':
                    lease=secrets.token_hex(16);self.db.execute("UPDATE reminder_deliveries SET state='claimed',lease=?,lease_until=? WHERE reminder=? AND target=?",(lease,now+90,candidate['id'],recipient));self.refresh(candidate['id'])
                    row=self.db.execute('SELECT * FROM reminder_deliveries WHERE reminder=? AND target=?',(candidate['id'],recipient)).fetchone()
                return candidate|dict(lease=row['lease'],recipient=recipient,lease_until=row['lease_until'])
            return None
    def acknowledge(self,recipient,identifier,lease,delivery):
        if type(identifier) is not int or not isinstance(lease,str) or not re.fullmatch('[0-9a-f]{32}',lease) or delivery not in ('played','displayed'):raise ValueError('invalid receipt')
        now=int(self.clock())
        with self.lock,self.db:
            row=self.db.execute('SELECT d.*,r.repeat_minutes FROM reminder_deliveries d JOIN reminders r ON r.id=d.reminder WHERE d.reminder=? AND d.target=?',(identifier,recipient)).fetchone()
            if not row or row['lease']!=lease:return False
            if row['state']=='delivered':return True
            if row['state']!='claimed' or row['lease_until']<=now:return False
            if row['repeat_minutes']:
                gap=row['repeat_minutes']*60;due=row['due']+(max(1,(now-row['due'])//gap+1)*gap)
                self.db.execute("UPDATE reminder_deliveries SET state='scheduled',due=?,delivered=?,lease='',lease_until=0 WHERE reminder=? AND target=?",(due,delivery,identifier,recipient))
            else:self.db.execute("UPDATE reminder_deliveries SET state='delivered',delivered=? WHERE reminder=? AND target=?",(delivery,identifier,recipient))
            self.refresh(identifier,recipient,delivery);return True
    def validate_claim(self,recipient,identifier,lease):
        with self.lock:
            row=self.db.execute("SELECT r.id,r.text,d.due,d.lease FROM reminders r JOIN reminder_deliveries d ON r.id=d.reminder WHERE r.id=? AND d.target=? AND d.lease=? AND d.state='claimed' AND d.lease_until>? AND r.state!='cancelled'",(identifier,recipient,lease,int(self.clock()))).fetchone()
            if not row:raise ValueError('claim expired')
            return dict(row)
    def close(self):
        with self.lock:
            if not self.closed:self.closed=True;self.db.close()

def describe_reminders(store):
    now=store.clock();rows=store.active()
    def at(value):
        stamp=datetime.fromtimestamp(value,TZ)
        return stamp.strftime('%H:%M:%S' if stamp.date()==datetime.fromtimestamp(now,TZ).date() else '%m月%d日 %H:%M:%S')
    def progress(target):
        place='小板子' if target['channel']=='body' else '网页'
        if target['state']=='delivered':return place+('回报已播完' if target['delivered']=='played' else '已在屏幕上确认，还没有播放声音的记录')
        left=max(0,math.ceil(target['due']-now))
        if not left:return place+'的提醒已经到点啦，正在等提醒播完的确认'
        hours,seconds=divmod(left,3600);minutes,seconds=divmod(seconds,60)
        wait=(str(hours)+'小时' if hours else '')+(str(minutes)+'分' if minutes else '')+(str(seconds)+'秒' if seconds or not hours and not minutes else '')
        return place+'还有'+wait+'，'+at(target['due'])+'提醒你'
    if rows:
        messages=[]
        for row in rows:
            states=row.get('targets',[])
            if not states:messages.append('这条旧提醒的来源还没确认，暂不跨端播放，请重新指定提醒端：'+row['text']+'。');continue
            messages.append((str(row['id'])+'：' if len(rows)>1 else '')+'；'.join(progress(t) for t in states)+'：'+row['text']+'。')
        return '\n'.join(messages)
    rows=store.recent()
    if not rows:return '目前没有待提醒的事情。'
    row=rows[0];when=at(row['due'])
    if row['state']=='cancelled':return '最近那条提醒已经取消了：'+row['text']+'。'
    targets=row.get('targets',[])
    if len(targets)>1:return when+'就到点啦。'+'；'.join(progress(t) for t in targets)+'，不过我还不知道你有没有听到。内容是：'+row['text']+'。'
    if row['delivered']=='played':return when+'就到点啦。'+('小板子' if row['channel']=='body' else '网页')+'回报已经播完提醒，不过我还不知道你有没有听到。内容是：'+row['text']+'。'
    if row['delivered']=='displayed':return when+'已经到点，那条提醒已在屏幕上确认，还没有播放声音的记录。内容是：'+row['text']+'。'
    return when+'已经到点，那条提醒有完成记录，但没有明确的声音播放记录。内容是：'+row['text']+'。'
