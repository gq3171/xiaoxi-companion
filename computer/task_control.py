"""Authenticated owner continuation of an existing task, never a second job."""
from desktop_jobs import broker,DesktopBusy
from private_input import inputs
from task_status import select
from task_dossier import ID


def control(store,action,identifier,note='',job_id=None,focus=None,live=lambda:True):
    if action not in ('computer_update','computer_resume'):raise ValueError('invalid task control')
    if not isinstance(identifier,str) or not ID.fullmatch(identifier):raise ValueError('invalid task control identifier')
    rows=select(store,job_id,focus=focus)
    if not rows:raise ValueError('没有找到可以继续的任务')
    job=rows[0]['id'];state=broker(store)
    with store.lock:
        if not live():raise PermissionError('task control no longer authorized')
        previous=store.db.execute('SELECT job,action FROM task_controls WHERE id=?',(identifier,)).fetchone()
        if previous:
            if previous['job']!=job or previous['action']!=action:raise ValueError('task control id conflict')
            return store.get(job)
        current=store.get(job)
        if current['state'] not in ('queued','running','interrupted') or current['cancel']:
            raise ValueError('这项任务已经结束，不能当作未完成任务继续')
        saved=state.load(job)
        if action=='computer_resume' and current['state']=='interrupted' and saved is None:
            raise ValueError('命令任务的中断结果需要先核对，旧命令没有自动重跑；请明确委托核对当前结果')
        if note:
            previous=store.tasks.revision(job)
            store.tasks.note(job,identifier,note,live)
            if action=='computer_update' and store.tasks.revision(job)!=previous:
                inputs(store).close_job(job)
        if saved and (current['state']=='interrupted' or saved and state._row(job)['phase']=='waiting_user'):
            if state.lease:raise DesktopBusy('请先交回桌面，再继续任务；补充要求已经保留')
            state.resume(job)
        with store.db:store.db.execute('INSERT INTO task_controls VALUES(?,?,?)',(identifier,job,action))
        result=store.get(job)
    return result
