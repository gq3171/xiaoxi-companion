"""Persistent virtual affect, grounded shared threads and evidence-checked practice.

All writes run inside BrainStore's transaction/lock. No autonomous cloud calls.
A proposed reply changes nothing until the body accepts it. A promise is never
completion evidence, and lack of complaints is never proof of improvement.
"""
import hashlib
import json
import math
import re
import secrets
import time
from interaction import Preferences


def raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(raw(value).encode()).hexdigest()


def clipped(value, n):
    return value if isinstance(value, str) and 0 < len(value.encode()) <= n else ''


class Companion:
    def __init__(self, db, clock=time.time):
        self.db, self.clock = db, clock
        db.executescript('''
        CREATE TABLE IF NOT EXISTS companion_state(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS companion_turns(
          id TEXT PRIMARY KEY, boot INTEGER NOT NULL, session TEXT NOT NULL, generation INTEGER NOT NULL,
          candidate_hash TEXT NOT NULL, proposal TEXT NOT NULL, rules TEXT NOT NULL,
          source_id INTEGER NOT NULL DEFAULT 0, accepted INTEGER NOT NULL DEFAULT 0,
          delivery TEXT NOT NULL DEFAULT 'pending', created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS companion_threads(
          id TEXT PRIMARY KEY, topic TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
          source_id INTEGER NOT NULL, trace TEXT NOT NULL, expected TEXT NOT NULL,
          created INTEGER NOT NULL, updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS companion_events(
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, detail TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS companion_checks(
          trial TEXT NOT NULL, lesson TEXT NOT NULL, verdict TEXT NOT NULL,
          source_id INTEGER NOT NULL, reason TEXT NOT NULL, created INTEGER NOT NULL,
          PRIMARY KEY(trial,lesson,source_id));
        ''')
        if not db.execute('SELECT 1 FROM companion_state').fetchone(): self.shift()

    def affect(self):
        now = int(self.clock())
        row = self.db.execute('SELECT value FROM companion_state WHERE id=1').fetchone()
        state = json.loads(row[0]) if row else dict(energy=65., curiosity=55., calm=70., updated=now)
        elapsed = max(0, now - state['updated'])
        # Offline time only relaxes towards neutral; never invent offline activity.
        decay = math.exp(-min(elapsed, 7*86400) / 21600)
        for key, baseline in (('energy', 65), ('curiosity', 55), ('calm', 70)):
            state[key] = max(15., min(90., baseline + (state[key]-baseline)*decay))
        state['updated'] = now
        return state

    def shift(self, **changes):
        state = self.affect()
        for key, amount in changes.items():
            state[key] = max(15., min(90., state[key]+amount))
        self.db.execute('INSERT INTO companion_state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value', (raw(state),))

    def event(self, key, kind, detail):
        inserted = self.db.execute('INSERT OR IGNORE INTO companion_events VALUES(?,?,?,?)',
                                   (key, kind, raw(detail), int(self.clock()))).rowcount
        self.db.execute('DELETE FROM companion_events WHERE id IN (SELECT id FROM companion_events ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET 128)')
        return bool(inserted)

    @staticmethod
    def rules(memory, query):
        def grams(s):
            s = re.sub(r'\s+', '', s)
            return {s[i:i+2] for i in range(max(0,len(s)-1))}
        q = grams(query)
        ranked = []
        for rule in memory.get('growth', []):
            if not rule.get('active') or rule.get('kind') not in ('style','lesson'):
                continue
            relevance = len(q & grams(' '.join(str(rule.get(k,'')) for k in ('slot','trigger','text'))))
            if relevance or rule.get('kind') == 'style':
                identity = {k:rule.get(k,'') for k in ('kind','slot','text','trigger','check')}
                ranked.append((relevance, {'id':digest(identity)[:16], **identity}))
        ranked.sort(key=lambda x:x[0], reverse=True)
        return [rule for _,rule in ranked[:4]]

    def context(self, memory, query=''):
        state = self.affect()
        mood = 'sleepy' if state['energy'] < 38 else 'concerned' if state['calm'] < 40 else 'curious' if state['curiosity'] > 68 else 'calm'
        threads = [dict(r) for r in self.db.execute("SELECT id,topic,kind,status FROM companion_threads ORDER BY CASE WHEN status='open' THEN 0 ELSE 1 END,updated DESC LIMIT 8")]
        events = [dict(r) for r in self.db.execute('SELECT kind,detail,created FROM companion_events ORDER BY created DESC,rowid DESC LIMIT 6')]
        checks = [dict(r) for r in self.db.execute('SELECT trial,lesson,verdict,reason FROM companion_checks ORDER BY created DESC,rowid DESC LIMIT 8')]
        rules=self.rules(memory,query)
        practice=[]
        for rule in rules:
            attempted=sum(rule['id'] in {r['id'] for r in json.loads(t['rules'])} for t in self.db.execute("SELECT rules FROM companion_turns WHERE accepted=1 AND delivery IN ('played','displayed')"))
            counts={r['verdict']:r['n'] for r in self.db.execute('SELECT verdict,count(*) AS n FROM companion_checks WHERE lesson=? GROUP BY verdict',(rule['id'],))}
            practice.append(dict(lesson=rule['id'],delivered_attempts=attempted,owner_feedback=counts))
        return dict(affect={k:round(state[k],1) for k in ('energy','curiosity','calm')}, mood=mood,
                    shared_threads=threads, actual_experiences=events, applicable_rules=rules, practice=practice,recent_checks=checks)

    def propose(self, request, answer, memory, candidate=''):
        # Pending hypotheses aren't events, memories, emotions or completed work.
        if answer.get('action') not in ('speak','wait','computer_task','computer_cancel','list_reminders','cancel_reminder'):
            return answer
        if request['kind']=='dialogue' and request.get('microphone') and answer.get('input')!='direct':
            return answer
        trace = secrets.token_hex(16)
        rules = self.rules(memory, candidate or request.get('request','')[:1000])
        selected = answer.get('lesson_use', [])
        if not isinstance(selected,list): selected=[]
        used = [r for r in rules if r['id'] in selected]
        proposal = {k:answer[k] for k in ('action','say','text','mood','life_plan','home_action','reminder','task','shared_thread','self_update') if k in answer}
        if request.get('kind')=='dialogue' and answer.get('remember') is True:
            preference=Preferences.prepare(answer.get('behavior_update'), candidate)
            if preference:proposal['behavior_update']=preference
        if len(raw(proposal).encode()) > 8192:
            return answer
        self.db.execute('INSERT INTO companion_turns(id,boot,session,generation,candidate_hash,proposal,rules,created) VALUES(?,?,?,?,?,?,?,?)',
                        (trace, request['boot'], request['session'], request['generation'], hashlib.sha256(candidate.encode()[:1024].decode('utf-8','ignore').encode()).hexdigest(), raw(proposal), raw(used), int(self.clock())))
        # Keep active unresolved threads independently; bound only turn diagnostics.
        self.db.execute('DELETE FROM companion_turns WHERE id IN (SELECT id FROM companion_turns ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET 64)')
        return answer | {'_trace':trace, 'mood':answer.get('mood', self.context(memory)['mood'])}

    def feedback(self, op, memory):
        trace, stage = op.get('trace'), op.get('stage')
        if not isinstance(trace,str) or not re.fullmatch('[0-9a-f]{32}',trace) or stage not in ('accepted','played','displayed','incomplete','autonomous'):
            raise ValueError('invalid companion feedback')
        row = self.db.execute('SELECT * FROM companion_turns WHERE id=?',(trace,)).fetchone()
        if not row: return 0  # A delayed receipt for an expired diagnostic cannot invent history.
        answer = json.loads(row['proposal'])
        if stage == 'accepted':
            source = next((x for x in memory.get('history',[]) if x.get('id')==op.get('source_id') and x.get('role')=='user'),None)
            if not source or hashlib.sha256(source['content'].encode()).hexdigest()!=row['candidate_hash']:
                return 0
            if row['accepted']:return 0
            self.db.execute('UPDATE companion_turns SET accepted=1,source_id=? WHERE id=?',(source['id'],trace))
            self.shift(curiosity=1, calm=.5)
            self.create_thread(trace,answer,source)
        elif stage == 'autonomous':
            # No personal agreements can be created from an autonomous thought.
            if row['accepted']:return 0
            if row['candidate_hash'] != hashlib.sha256(b'').hexdigest():
                raise ValueError('dialogue cannot be self-accepted')
            self.db.execute('UPDATE companion_turns SET accepted=1 WHERE id=?',(trace,))
        else:
            if not row['accepted'] or row['delivery']!='pending':return 0
            self.db.execute('UPDATE companion_turns SET delivery=? WHERE id=?',(stage,trace))
            if stage=='incomplete':self.shift(calm=-2)
            self.event('delivery:'+trace,'delivery',dict(trace=trace,status=stage))
        return 1

    def create_thread(self, trace, answer, source):
        thread = answer.get('shared_thread')
        if not source.get('owner') or not isinstance(thread,dict):return
        topic, quote = clipped(thread.get('topic'),180), clipped(thread.get('source_quote'),384)
        if not topic or not quote or quote not in source['content']:return
        kind=thread.get('kind')
        if kind not in ('agreement','shared_activity'):return
        expected={}
        plan=answer.get('life_plan')
        if isinstance(plan,dict) and clipped(plan.get('goal'),240) and isinstance(plan.get('steps'),list) and 1<=len(plan['steps'])<=4 and all(x in ('roam','rest','wake','wash','work','window') for x in plan['steps']):
            expected={'type':'life','goal':plan.get('goal',''),'steps':plan['steps']}
        elif answer.get('action')=='computer_task' and clipped(answer.get('task'),1024):
            expected={'type':'computer','goal':answer['task']}
        elif isinstance(answer.get('reminder'),dict) and clipped(answer['reminder'].get('text'),240):
            expected={'type':'reminder','text':answer['reminder']['text']}
        elif answer.get('home_action') in ('rest','wake','wash','window'):
            expected={'type':'home','action':answer['home_action']}
        else:expected={'type':'conversation'}
        if self.db.execute("SELECT count(*) FROM companion_threads WHERE status IN ('open','scheduled')").fetchone()[0]>=24:return
        if self.db.execute("SELECT 1 FROM companion_threads WHERE topic=? AND status IN ('open','scheduled')",(topic,)).fetchone():return
        now=int(self.clock())
        started=self.db.execute('SELECT created FROM companion_turns WHERE id=?',(trace,)).fetchone()[0]
        # Receipts can arrive after a long reply or reconnection. The intention
        # existed before execution, not only when its receipt finally arrived.
        self.db.execute('INSERT INTO companion_threads VALUES(?,?,?,?,?,?,?,?,?)',
            (secrets.token_hex(8),topic,kind,'open',source['id'],trace,raw(expected),started,now))
        self.event('agreement:'+trace,'agreement',dict(topic=topic,status='open',source_id=source['id']))
        self.db.execute("DELETE FROM companion_threads WHERE id IN (SELECT id FROM companion_threads WHERE status NOT IN ('open','scheduled') ORDER BY updated DESC LIMIT -1 OFFSET 24)")

    def body(self, parts, previous):
        """Authenticated body checkpoints; replays/initial historic import are inert."""
        now=int(self.clock())
        sensors=parts.get('feedback',{});old_sensors=previous.get('feedback',{})
        if isinstance(sensors,dict) and isinstance(old_sensors,dict):
            dt=sensors.get('uptime_ms',0)-old_sensors.get('uptime_ms',0)
            if 0<dt<=90000 and 0<=now-previous.get('_received',0)<=90 and sensors.get('activity')==old_sensors.get('activity'):
                hours=dt/3600000
                if sensors.get('activity')==3:self.shift(energy=hours*10,calm=hours*3)
                elif sensors.get('activity') in (1,7):self.shift(energy=-hours*4)
        life=parts.get('life',{})
        if isinstance(life,dict):
            old=previous.get('life',{});old_journal=old.get('journal',[]) if isinstance(old,dict) else []
            for item in life.get('journal',[]) if isinstance(life.get('journal',[]),list) else []:
                if not isinstance(item,dict) or item in old_journal:continue
                epoch=item.get('epoch',0)
                # Record only fresh reported completions, never make offline events.
                if type(epoch) not in (int,float) or not 0<=now-epoch<=120:continue
                if not self.event('life:'+digest(item),'virtual_life',item):continue
                step=item.get('step');self.shift(**({'energy':4,'calm':2} if step=='rest' else {'calm':2} if step=='wash' else {'curiosity':2,'energy':-1} if step=='window' else {'energy':-1}))
            plan=life.get('plan',{})
            for row in self.db.execute("SELECT * FROM companion_threads WHERE status='open'").fetchall():
                expected=json.loads(row['expected'])
                if expected['type']!='life' or not isinstance(plan,dict):continue
                if plan.get('goal')!=expected['goal'] or plan.get('steps')!=expected['steps'] or not plan.get('by_owner'):continue
                if type(plan.get('created')) not in (int,float) or plan['created']<row['created']-10:continue
                completed=plan.get('index')
                if type(completed) is int and completed>=len(expected['steps']):
                    # Completion must also have the final actual journal event.
                    if any(isinstance(x,dict) and x.get('goal')==expected['goal'] and x.get('step')==expected['steps'][-1] and type(x.get('epoch')) in (int,float) and x['epoch']>=row['created']-10 for x in life.get('journal',[])):
                        self.finish(row,'completed','板端生活步骤实际完成')
        computer=parts.get('computer',{})
        agency=parts.get('agency',{})
        for row in self.db.execute("SELECT * FROM companion_threads WHERE status='open'").fetchall():
            expected=json.loads(row['expected'])
            if expected['type']=='home' and isinstance(agency,dict):
                actual=agency.get('last_virtual_life',{})
                if isinstance(actual,dict) and type(actual.get('epoch')) in (int,float) and actual['epoch']>=row['created']:
                    events={'rest':'结束了一段床上休息','wake':'洗漱完成','wash':'洗漱完成','window':'在窗边看了一会儿'}
                    if actual.get('event')==events[expected['action']]:self.finish(row,'completed','板端报告虚拟活动实际完成')
            if expected['type']=='computer' and isinstance(computer,dict) and computer.get('goal')==expected['goal']:
                # Only the executor's own DB can attest a real task terminal state.
                # Verified by BrainStore against the separate executor DB.
                verified=computer.get('_verified_state')
                if verified in ('succeeded','failed','cancelled','interrupted') and computer.get('_created',0)>=row['created']:
                    self.finish(row,'completed' if verified=='succeeded' else verified,'实际电脑执行结果')
            if expected['type']=='reminder' and isinstance(agency,dict):
                old_agency=previous.get('agency',{})
                old_reminders=old_agency.get('reminders',[]) if isinstance(old_agency,dict) else []
                if any(isinstance(x,dict) and x not in old_reminders and x.get('text')==expected['text'] and type(x.get('due')) in (int,float) and x['due']>now for x in agency.get('reminders',[])):
                    self.finish(row,'scheduled','提醒已实际保存，尚未触发')

    def finish(self, row, status, reason):
        self.db.execute('UPDATE companion_threads SET status=?,updated=? WHERE id=?',(status,int(self.clock()),row['id']))
        self.event('thread:'+row['id']+':'+status,'agreement_result',dict(topic=row['topic'],status=status,reason=reason))

    def review_context(self, memory):
        trials=[]
        for row in self.db.execute("SELECT * FROM companion_turns WHERE accepted=1 AND delivery IN ('played','displayed') ORDER BY created DESC,rowid DESC LIMIT 8"):
            rules=json.loads(row['rules'])
            if rules:trials.append(dict(id=row['id'],source_id=row['source_id'],reply=json.loads(row['proposal']).get('say',json.loads(row['proposal']).get('text','')),rules=rules,delivery=row['delivery']))
        return dict(trials=trials,open_threads=[dict(r) for r in self.db.execute("SELECT id,topic,source_id FROM companion_threads WHERE status IN ('open','scheduled') LIMIT 24")])

    def reviews(self, response, memory):
        owners={x['id']:x for x in memory.get('history',[]) if x.get('role')=='user' and x.get('owner')}
        reviews=response.get('growth_reviews',[])
        if not isinstance(reviews,list):return
        for item in reviews[:8]:
            if not isinstance(item,dict):continue
            row=self.db.execute("SELECT * FROM companion_turns WHERE id=? AND accepted=1 AND delivery IN ('played','displayed')",(str(item.get('trial_id','')),)).fetchone()
            source=owners.get(item.get('source_id')) if type(item.get('source_id')) is int else None
            quote=clipped(item.get('source_quote'),384);reason=clipped(item.get('reason'),240)
            if not row or not source or source['id']<=row['source_id'] or not quote or quote not in source['content'] or not reason:continue
            lesson=item.get('lesson_id');allowed={r['id'] for r in json.loads(row['rules'])}
            if not isinstance(lesson,str) or lesson not in allowed:continue
            verdict=item.get('verdict')
            if verdict=='improved' and not any(x in quote for x in ('好多了','这样很好','这次对了','现在对了','没有再','不再','改好了')):continue
            if verdict=='repeated' and not any(x in quote for x in ('还是','仍然','又','还在','没有改','没改')):continue
            if verdict not in ('improved','repeated','uncertain'):continue
            self.db.execute('INSERT OR IGNORE INTO companion_checks VALUES(?,?,?,?,?,?)',(row['id'],lesson,verdict,source['id'],reason,int(self.clock())))
        # Close conversational agreements only with explicit later owner evidence.
        updates=response.get('thread_reviews',[])
        if not isinstance(updates,list):return
        for item in updates[:4]:
            if not isinstance(item,dict):continue
            row=self.db.execute('SELECT * FROM companion_threads WHERE id=?',(str(item.get('thread_id','')),)).fetchone()
            source=owners.get(item.get('source_id')) if type(item.get('source_id')) is int else None
            quote=clipped(item.get('source_quote'),384)
            if not row or not source or source['id']<=row['source_id'] or not quote or quote not in source['content']:continue
            status=item.get('status')
            if status=='cancelled' and any(x in quote for x in ('取消','不做了','算了','不用了')):self.finish(row,status,'主人明确取消')
            elif status=='completed' and json.loads(row['expected'])['type']=='conversation' and any(x in quote for x in ('完成了','聊完了','说好了','已经做过','已经一起')):self.finish(row,status,'主人明确确认共同活动完成')
        self.db.execute('DELETE FROM companion_checks WHERE rowid IN (SELECT rowid FROM companion_checks ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET 128)')

    def forget(self):
        for table in ('companion_turns','companion_threads','companion_events','companion_checks','companion_state'):
            self.db.execute('DELETE FROM '+table)
