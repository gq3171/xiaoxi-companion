"""Scoped, content-bounded task state for dialogue; never raw command output."""
import json,re

LABELS={'queued':'等待执行','running':'正在执行','succeeded':'检查通过并完成','failed':'执行未完成',
        'interrupted':'已中断，需核对实际进度','cancelled':'已停止','waiting_user':'等你补充信息或核对页面',
        'needs_verification':'有一步结果需要核对'}


def select(store,job=None,history=False,focus=None):
    if store is None:return []
    for value in (job,focus):
        if value is not None and (not isinstance(value,str) or not re.fullmatch('[0-9a-f]{32}',value)):
            raise ValueError('invalid task reference')
    with store.lock:
        if job or (focus and not history):
            rows=store.db.execute('SELECT id,goal,state,message FROM jobs WHERE id=?',(job or focus,)).fetchall()
            if not rows and job:return []
        else:rows=[]
        if not rows:
            rows=store.db.execute("SELECT id,goal,state,message FROM jobs ORDER BY CASE WHEN state IN ('running','queued') THEN 0 ELSE 1 END,created DESC,rowid DESC LIMIT ?",(3 if history else 1,)).fetchall()
        desktop=store.db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_jobs'").fetchone()
        result=[]
        for row in rows:
            item=dict(row);item['goal']=item['goal'][:200];item['message']=item['message'][:600]
            d=store.db.execute('SELECT phase,checkpoint FROM desktop_jobs WHERE job=?',(item['id'],)).fetchone() if desktop else None
            value=json.loads(d['checkpoint']) if d else {}
            item['phase']=('needs_verification' if value.get('uncertain') else d['phase']) if d and item['state'] in ('queued','running','interrupted') else item['state']
            doc=store.tasks.snapshot(item['id'])
            active=item['state'] in ('queued','running','interrupted')
            blocker=item['message'] if active and item['phase'] in ('waiting_user','needs_verification','interrupted') else ''
            item.update(next_step=doc['next_step'][:200] if active else '',blocker=blocker,verified_checks=len(doc['verified_facts']),input_revision=doc['input_revision'])
            from private_input import attention
            if attention(store,item['id']):item['phase']='waiting_user';item['blocker']='需要主人在网站专用私密填写窗补充信息。'
            item['label']=LABELS.get(item['phase'],LABELS.get(item['state'],'状态待核对'))
            result.append(item)
        return result


def describe(rows):
    if not rows:return '目前没有找到对应的电脑任务。'
    return '\n'.join('任务“'+r['goal'][:70]+'”'+r['label']+'。'+(r['blocker'] or r['message']) for r in rows)[:1600]
