"""Small versioned task methods, promoted only by actual checked success.

    A method is advice, not executable code or a permission grant. The task DB
    owns both the evidence and these records. A failed run never replaces a
    verified method. Only relevant methods enter the task context.
"""
import hashlib
import json
import re
import time
from recall import terms


def bounded(value, budget):
    return value if isinstance(value, str) and 0 < len(value.encode()) <= budget else ''


class Skills:
    def __init__(self, db):
        self.db = db
        db.executescript('''
        CREATE TABLE IF NOT EXISTS task_skills(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
          content TEXT NOT NULL, source_job TEXT NOT NULL, created INTEGER NOT NULL,
          active INTEGER NOT NULL DEFAULT 1, successes INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS skill_uses(job TEXT NOT NULL, skill TEXT NOT NULL, result TEXT NOT NULL DEFAULT 'pending', PRIMARY KEY(job,skill));
        ''')

    def select(self, goal):
        query = set(terms(goal))
        ranked = []
        for row in self.db.execute('SELECT * FROM task_skills WHERE active=1 ORDER BY created DESC LIMIT 16'):
            score = len(query & set(terms(row['name']+' '+row['description'])))
            if score:
                ranked.append((score, dict(row)))
        ranked.sort(key=lambda x:x[0], reverse=True)
        return [{k:r[k] for k in ('id','name','description','content','successes','failures')} for _,r in ranked[:2]]

    def use(self, job, selected):
        self.db.executemany('INSERT OR IGNORE INTO skill_uses(job,skill) VALUES(?,?)', ((job,r['id']) for r in selected))

    def result(self, job, state):
        if state not in ('succeeded','failed'):
            return
        rows = self.db.execute("SELECT skill FROM skill_uses WHERE job=? AND result='pending'", (job,)).fetchall()
        column = 'successes' if state=='succeeded' else 'failures'
        for row in rows:
            self.db.execute('UPDATE task_skills SET '+column+'='+column+'+1 WHERE id=?', (row['skill'],))
        self.db.execute("UPDATE skill_uses SET result=? WHERE job=? AND result='pending'", (state,job))

    def learn(self, job, candidate):
        if not isinstance(candidate, dict):
            return None
        name = bounded(candidate.get('name'), 120)
        description = bounded(candidate.get('when'), 384)
        method = bounded(candidate.get('method'), 2400)
        check = bounded(candidate.get('check'), 640)
        if not all((name,description,method,check)):
            return None
        original = self.db.execute('SELECT state,goal FROM jobs WHERE id=?', (job,)).fetchone()
        verification = self.db.execute("SELECT max(ordinal) FROM steps WHERE job=? AND kind IN ('check','browser_check') AND exit_code=0", (job,)).fetchone()[0]
        mutation = self.db.execute("SELECT max(ordinal) FROM steps WHERE job=? AND kind IN ('run','browser_open','browser_click','browser_type','browser_key','browser_scroll','write_artifact')", (job,)).fetchone()[0] or 0
        if verification is not None and mutation>verification:return None
        if not original or original['state']!='succeeded' or not verification:
            return None
        # Require topical grounding in the actual task, not a model-invented
        # unrelated lesson. This is a relevance guard, not proof of all semantics.
        if not set(terms(name+' '+description)) & set(terms(original['goal'])):
            return None
        content = json.dumps(dict(method=method,check=check,source_job=job), ensure_ascii=False)
        identity = hashlib.sha256((name+'\0'+content).encode()).hexdigest()[:32]
        self.db.execute('UPDATE task_skills SET active=0 WHERE name=?', (name,))
        self.db.execute('INSERT OR IGNORE INTO task_skills(id,name,description,content,source_job,created) VALUES(?,?,?,?,?,?)',
                        (identity,name,description,content,job,int(time.time())))
        self.db.execute('UPDATE task_skills SET active=1 WHERE id=?', (identity,))
        self.db.execute('UPDATE task_skills SET active=0 WHERE id IN (SELECT id FROM task_skills WHERE active=1 ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET 16)')
        self.db.execute('DELETE FROM task_skills WHERE active=0 AND id IN (SELECT id FROM task_skills WHERE active=0 ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET 32)')
        self.db.execute('DELETE FROM skill_uses WHERE skill NOT IN (SELECT id FROM task_skills)')
        return identity
