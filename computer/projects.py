"""One persistent virtual storybook project, advanced by actual body events.

The text is a fictional page authored by the model, not evidence of reading a
real source or learning a real-world fact. No advance while the body is offline.
"""
import hashlib
import json
import secrets
import time


class Projects:
    def __init__(self, db, clock=time.time):
        self.db,self.clock=db,clock
        db.executescript('''
        CREATE TABLE IF NOT EXISTS home_projects(
          id TEXT PRIMARY KEY,title TEXT NOT NULL,page_text TEXT NOT NULL,
          page INTEGER NOT NULL,completed_pages INTEGER NOT NULL,status TEXT NOT NULL,
          expected_goal TEXT NOT NULL,started INTEGER NOT NULL,owner_paused INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS home_project_events(event TEXT PRIMARY KEY,project TEXT NOT NULL);
        ''')

    def current(self):
        row=self.db.execute("SELECT * FROM home_projects WHERE status IN ('active','paused','next_page') ORDER BY started DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def context(self):
        row=self.current()
        if not row:return None
        return row|{'virtual':True,'page_text_is_fiction':True,
                    'rule':'只有实际read完成事件才增加页数；主人暂停的项目不能自主恢复；新页可由interest_project.page_text续写。'}

    def prepare(self, answer):
        """Normalize a proposal without writing state; receipts own acceptance."""
        row=self.current()
        value=answer.get('interest_project')
        control=answer.get('project_control')
        metadata={}
        if control in ('pause','resume','cancel') and row:
            metadata={'control':control,'id':row['id']}
            if control in ('pause','cancel') and row['status']!='next_page':
                answer=answer|{'life_control':control}
        if answer.get('home_action')=='rest' or (isinstance(answer.get('life_plan'),dict) and answer['life_plan'].get('steps',[])[-1:]==['rest']):
            if row:metadata={'control':'pause','id':row['id']}
            return answer,metadata
        if row and row['status']=='paused' and control!='resume':
            return answer,metadata
        if isinstance(value,dict):
            title=value.get('title','');content=value.get('page_text','')
            if not isinstance(title,str) or not 0<len(title.encode())<=120 or not isinstance(content,str) or not 0<len(content.encode())<=720 or value.get('kind','storybook')!='storybook':
                return answer,metadata
            if row and row['title']!=title:
                return answer,metadata  # An existing unfinished project wins.
            if row and row['status']=='active':
                content=row['page_text']
            identity=row['id'] if row else secrets.token_hex(12)
            page=(row['completed_pages']+1) if row and row['completed_pages']>=row['page'] else row['page'] if row else 1
            if page>64:return answer,metadata
            goal='绘本：'+title+'（第'+str(page)+'页）'
            metadata={'id':identity,'title':title,'page_text':content,'page':page,'goal':goal,'control':control}
            answer=answer|{'life_plan':{'goal':goal,'reason':'继续自己的虚拟绘本小项目','steps':['read']}}
        elif row and row['completed_pages']<row['page'] and (control=='resume' or (row['status']=='active' and answer.get('home_action')=='read')):
            answer=answer|{'life_plan':{'goal':row['expected_goal'],'reason':'主人明确继续绘本项目','steps':['read']}}
        return answer,metadata

    def accept(self, metadata, created, by_owner=False):
        if not isinstance(metadata,dict) or not metadata:return
        row=self.current();control=metadata.get('control')
        if control in ('pause','cancel','resume') and row and metadata.get('id')==row['id']:
            if control=='resume' and row['owner_paused'] and not by_owner:return
            status={'pause':'paused','cancel':'cancelled','resume':'next_page' if row['completed_pages']>=row['page'] else 'active'}[control]
            self.db.execute('UPDATE home_projects SET status=?,owner_paused=?,started=? WHERE id=?',
                (status,int(control=='pause' and (by_owner or row['owner_paused'])),created,row['id']))
            if control!='resume':return
        if 'page_text' not in metadata:return
        if row and row['owner_paused'] and not by_owner:return
        self.db.execute('INSERT INTO home_projects VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET page_text=excluded.page_text,page=excluded.page,status=\'active\',expected_goal=excluded.expected_goal,started=CASE WHEN home_projects.status=\'active\' AND home_projects.page=excluded.page THEN home_projects.started ELSE excluded.started END,owner_paused=0',
            (metadata['id'],metadata['title'],metadata['page_text'],metadata['page'],row['completed_pages'] if row else 0,'active',metadata['goal'],created,0))
        self.db.execute("DELETE FROM home_projects WHERE id IN (SELECT id FROM home_projects WHERE status NOT IN ('active','paused','next_page') ORDER BY started DESC LIMIT -1 OFFSET 8)")

    def completed(self, item):
        row=self.current()
        if not row or row['status']!='active' or item.get('step')!='read' or item.get('goal')!=row['expected_goal']:
            return
        epoch=item.get('epoch')
        if type(epoch) not in (int,float) or not row['started']-10<=epoch<=self.clock() or self.clock()-epoch>120:return
        event=hashlib.sha256(json.dumps(item,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if not self.db.execute('INSERT OR IGNORE INTO home_project_events VALUES(?,?)',(event,row['id'])).rowcount:return
        self.db.execute('UPDATE home_projects SET completed_pages=page,status=? WHERE id=?',('completed' if row['page']>=64 else 'next_page',row['id']))
        self.db.execute('DELETE FROM home_project_events WHERE event IN (SELECT event FROM home_project_events ORDER BY rowid DESC LIMIT -1 OFFSET 128)')

    def forget(self):
        self.db.execute('DELETE FROM home_project_events')
        self.db.execute('DELETE FROM home_projects')
