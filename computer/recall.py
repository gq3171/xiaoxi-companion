"""Bounded, on-demand Chinese/Latin recall over already admitted archive rows.

    Search results are dated historical data, never fresh owner evidence. No
    embeddings, cloud calls, or second raw transcript. All calls use BrainStore's
    transaction and mutex, including forgetting and index maintenance.
"""
from collections import Counter
from datetime import datetime, timedelta
import re
import time
from zoneinfo import ZoneInfo


def terms(text):
    text = text.casefold()
    latin = re.findall(r'[a-z0-9_]{2,40}', text)
    han = re.findall(r'[\u3400-\u9fff]+', text)
    grams = [part[i:i+2] for part in han for i in range(len(part)-1)]
    return list(dict.fromkeys(latin + grams))[:64]


class Recall:
    LIMIT = 4096
    def __init__(self, db, clock=time.time):
        self.db, self.clock = db, clock
        db.executescript('''
        CREATE TABLE IF NOT EXISTS recall_terms(source TEXT NOT NULL, term TEXT NOT NULL, PRIMARY KEY(source,term));
        CREATE INDEX IF NOT EXISTS recall_lookup ON recall_terms(term,source);
        CREATE TABLE IF NOT EXISTS recall_indexed(source TEXT PRIMARY KEY);
        ''')
        # No extra transcript; catch up a bounded existing archive at startup.
        rows = db.execute('SELECT op_id,content FROM archive ORDER BY created DESC,rowid DESC LIMIT ?', (self.LIMIT,)).fetchall()
        for row in rows:
            if not db.execute('SELECT 1 FROM recall_indexed WHERE source=?', (row['op_id'],)).fetchone():
                self.add(row['op_id'], row['content'])

    def add(self, source, text):
        self.db.executemany('INSERT OR IGNORE INTO recall_terms VALUES(?,?)', ((source, t) for t in terms(text)))
        self.db.execute('INSERT OR IGNORE INTO recall_indexed VALUES(?)', (source,))

    def prune(self):
        # Keep a 90-day/4096-row rolling archive. Durable facts remain governed by
        # the native reducer, not by this cache. Idempotency tombstones are intact.
        self.db.execute('DELETE FROM archive WHERE created<?', (int(self.clock())-90*86400,))
        self.db.execute('DELETE FROM archive WHERE op_id IN (SELECT op_id FROM archive ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET ?)', (self.LIMIT,))
        self.db.execute('DELETE FROM recall_terms WHERE source NOT IN (SELECT op_id FROM archive)')
        self.db.execute('DELETE FROM recall_indexed WHERE source NOT IN (SELECT op_id FROM archive)')

    def search(self, query, limit=4):
        if not isinstance(query, str) or not query.strip() or len(query.encode()) > 1024:
            return []
        now = int(self.clock())
        before, after = now+1, now-90*86400
        day = datetime.fromtimestamp(now, ZoneInfo('Asia/Shanghai')).replace(hour=0, minute=0, second=0, microsecond=0)
        if '昨天' in query or '昨日' in query:
            after, before = int((day-timedelta(days=1)).timestamp()), int(day.timestamp())
        elif '前天' in query:
            after, before = int((day-timedelta(days=2)).timestamp()), int((day-timedelta(days=1)).timestamp())
        keys = [t for t in terms(query) if t not in ('昨天', '昨日', '前天', '之前', '记得', '我们', '什么', '说过', '上次')][:32]
        scores = Counter()
        if keys:
            marks = ','.join('?' for _ in keys)
            rows = self.db.execute('SELECT source,count(*) AS n FROM recall_terms WHERE term IN ('+marks+') GROUP BY source ORDER BY n DESC LIMIT 128', keys)
            scores.update({r['source']: r['n'] for r in rows})
        elif after > now-90*86400:
            scores.update({r[0]: 1 for r in self.db.execute('SELECT op_id FROM archive WHERE created>=? AND created<? ORDER BY created DESC LIMIT 24', (after,before))})
        result = []
        for source, score in scores.items():
            row = self.db.execute('SELECT role,content,owner,created FROM archive WHERE op_id=? AND created>=? AND created<?', (source,after,before)).fetchone()
            if not row:
                continue
            result.append(dict(source=source, role=row['role'], owner=bool(row['owner']),
                               date=datetime.fromtimestamp(row['created'], ZoneInfo('Asia/Shanghai')).isoformat(),
                               text=row['content'].encode()[:720].decode('utf-8','ignore'), score=score,
                               historical=True, fresh_evidence=False, created=row['created']))
        result.sort(key=lambda x:(x['score'],x['created']), reverse=True)
        return [{k:v for k,v in item.items() if k!='created'} for item in result[:max(1,min(limit,6))]]

    def forget(self):
        self.db.execute('DELETE FROM recall_terms')
        self.db.execute('DELETE FROM recall_indexed')
