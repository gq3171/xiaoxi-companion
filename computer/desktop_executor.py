"""Narrow v1 browser execution extension; existing command/media worker stays intact."""
import json,re,time
from pathlib import Path
from task_context import redact
from browser_tools import BrowserBlocked,BrowserUnavailable,BrowserCancelled
from desktop_browser import DesktopBrowser
from desktop_jobs import broker,DesktopBusy
from private_input import inputs,wipe

ACTIONS={'browser_open','browser_tabs','browser_snapshot','browser_click','browser_type','browser_key','browser_scroll','browser_check','browser_screenshot','browser_close','browser_look','browser_visual_click','handoff'}
def requires_browser(goal):return bool(re.search(r'浏览器|网页交互|注册|表单|登录|填写.{0,8}网站|点击.{0,8}网页',goal,re.I))

def run_desktop(worker,job,messages=None,first=None,ordinal=1,checked=False,last_code=None):
    store=worker.store;job_id=job['id'];state=broker(store);private=inputs(store);saved=state.load(job_id)
    workspace=store.path.parent.parent/'work/browser'/job_id;workspace.mkdir(parents=True,exist_ok=True,mode=0o700)
    browser=DesktopBrowser(store,job_id,workspace,lambda:worker.cancelled(job_id));worker.active_job_id=job_id
    if saved:
        messages=saved['messages'];first=None;checked=False;last_code=None
        with store.lock:ordinal=1+store.db.execute('SELECT coalesce(max(ordinal),0) FROM steps WHERE job=?',(job_id,)).fetchone()[0]
    messages=messages or [{'role':'user','content':json.dumps({'task':job['goal'],'work_directory':str(workspace)},ensure_ascii=False)}]
    def checkpoint(uncertain=False,phase='running'):
        nonlocal messages
        if len(messages)>11:messages=messages[:1]+messages[-10:]
        state.save(job_id,dict(messages=messages,browser=browser.checkpoint(),uncertain=uncertain),phase)
    def observe(result):
        raw=redact(json.dumps(browser.private_redact(result) if hasattr(browser,"private_redact") else result,ensure_ascii=False))
        if len(raw.encode())>14000:raw=raw.encode()[:14000].decode('utf8','ignore')+' [观察内容已截短，必要时重新读取]'
        messages.append({'role':'user','content':json.dumps({'untrusted_tool_result':raw},ensure_ascii=False)})
    decisions=0;pending_image=None
    def handoff(message):
        form=None
        if hasattr(browser,'private_form'):
            try:form=browser.private_form()
            except (ValueError,BrowserUnavailable,BrowserBlocked):pass
        if form:message='有一步需要你补充信息。我已打开网站专用的私密填写窗，请到已授权的网页填写；提交后我会继续。'
        # Publish pause, checkpoint and private request atomically; a fast
        # hand-back must never be overwritten by a delayed pause publication.
        with state.condition:
            checkpoint(phase='waiting_user');state.phase(job_id,'waiting_user',message[:500])
            if form:private.offer(job_id,form)
    def apply_private():
        submission=private.consume(job_id)
        if not submission:return False
        success=False
        try:
            with state.private_action(job_id):
                checkpoint(uncertain=True,phase='waiting_user')
                valid=lambda:not worker.cancelled(job_id) and private.valid(submission['id'])
                browser.private_apply(submission['form'],submission['values'],submission['activate'],valid)
                success=True
            messages.append({'role':'user','content':'主人已通过专用私密填写窗提供并核对本页信息。字段值不提供给模型。'+('主人授权的当前继续按钮已点击；不要重复点击。' if submission['activate'] else '本次只填写，没有授权点击继续按钮。')+'重新观察当前实际页面后继续原任务，不重放之前操作。'})
            checkpoint();state.phase(job_id,'running','私密填写已送到当前网站，正在核对实际页面并继续任务。')
        except Exception:
            # An input/CDP timeout may already have changed the page. Never log
            # its exception or replay values; owner must review the actual page.
            state.phase(job_id,'waiting_user','本次填写结果需要核对，内容没有自动重发。请查看实际页面，核对后点继续任务。')
        finally:
            wipe(submission['values']);private.finish(submission['id'],success)
        return success
    def stopped():
        status='interrupted' if worker.stop.is_set() else 'cancelled';store.update(job_id,status,'桌面任务已停止，页面和进度保留，未重复提交。');state.phase(job_id,'interrupted' if status=='interrupted' else 'done')
    try:
        if saved:
            browser.restore(saved.get('browser'))
            if browser.tabs:
                value=browser.snapshot();observe(value)
                if value.get('needs_human'):handoff(value['blocked_reason'])
                elif hasattr(browser,'private_form'):
                    try:
                        form=browser.private_form()
                        if form and form['fields']:handoff('当前页面需要主人补充信息。')
                    except (ValueError,BrowserUnavailable,BrowserBlocked):pass
            messages.append({'role':'user','content':'恢复核对：之前的操作可能已经生效。以刚读取的实际页面为准，不重放旧点击或注册提交。'})
        while ordinal<=80 and decisions<160:
            if worker.cancelled(job_id):stopped();return
            paused=False
            while state.waiting(job_id):
                paused=True
                if worker.cancelled(job_id):stopped();return
                if apply_private():break
                browser.heartbeat();worker.stop.wait(.25)
            if paused or state.state().get('phase')=='resume_requested':
                first=None;checked=False;last_code=None;pending_image=None;browser.snapshots.clear()
                if hasattr(browser,"visual_clear"):browser.visual_clear()
                if browser.tabs:observe(browser.snapshot())
                messages.append({'role':'user','content':'主人已交回桌面。重新核对页面，继续原任务；接管前未发出的操作全部作废。'})
                state.phase(job_id,'running')
            ephemeral=messages+([pending_image] if pending_image else [])
            try:reply=first if first is not None else worker.model(ephemeral)
            finally:pending_image=None;ephemeral=None
            first=None
            decisions+=1
            if not isinstance(reply,dict):raise ValueError('invalid browser task response')
            if worker.cancelled(job_id):stopped();return
            if state.waiting(job_id):continue # Discard a model reply arriving after takeover.
            action=reply.get('action');tab=reply.get('tab')
            if action not in ('browser_look','browser_visual_click') and hasattr(browser,'visual_clear'):browser.visual_clear()
            if action=='handoff':
                if not browser.tabs:observe({'error':'请先用browser_open打开本任务页面，再交给主人处理。'});continue
                handoff(str(reply.get('message') or '请在桌面完成当前验证，然后点“交回小溪”。'));continue
            if action=='finish':
                status=reply.get('state')
                if status not in ('succeeded','failed'):raise ValueError('invalid browser task terminal state')
                if status=='succeeded' and (not checked or last_code!=0):
                    observe({'error':'尚未通过当前实际页面的验证，请browser_check核对，不能假报成功。'});continue
                checkpoint();store.update(job_id,status,str(reply.get('message') or '当前任务已结束。'));state.phase(job_id,'done');return
            if action not in ACTIONS and action not in ('run','check'):raise ValueError('unknown desktop task action')
            checkpoint(uncertain=True);result={};code=0;passed=False
            try:
                with state.action(job_id):
                    store.update(job_id,'running',str(reply.get('message') or '正在核对并操作实际网页。'))
                    if action=='browser_open':result=browser.open(reply.get('url',''))
                    elif action=='browser_tabs':result={'tabs':browser.list_tabs()}
                    elif action=='browser_snapshot':result=browser.snapshot(tab)
                    elif action=='browser_click':result=browser.click(reply.get('ref'),tab)
                    elif action=='browser_type':result=browser.type(reply.get('ref'),reply.get('text'),tab)
                    elif action=='browser_key':result=browser.key(reply.get('key'),tab)
                    elif action=='browser_scroll':result=browser.scroll(reply.get('dy'),tab)
                    elif action=='browser_check':result=browser.check(reply.get('expected'),tab);passed=result.get('passed') is True;code=0 if passed else 1
                    elif action=='browser_screenshot':result=browser.screenshot(tab)
                    elif action=='browser_look':
                        result=browser.visual_look(tab);pending_image=browser.visual_message(result['visual'])
                    elif action=='browser_visual_click':result=browser.visual_click(reply.get('visual'),reply.get('box'),reply.get('target'),tab)
                    elif action=='browser_close':result=browser.close_tab(tab)
                    elif action in ('run','check'):
                        # Do not grant arbitrary shell execution in the GUI path.
                        result={'error':'网页任务请使用浏览器工具操作和验证；不能用命令绕过密码、条款或人工验证。'};code=1
                    if result.get('needs_human'):raise BrowserBlocked(result.get('blocked_reason','请在桌面完成当前验证。'))
            except DesktopBusy:continue
            except BrowserBlocked as error:
                # Never persist a password/OTP candidate from a rejected type action.
                store.record(job_id,ordinal,'desktop_handoff','protected step',0,'等待主人处理；未发送受保护输入。');ordinal+=1;handoff(str(error));continue
            except (ValueError,BrowserUnavailable) as error:
                result={'error':str(error)[:240],'observe_again':True};code=1
            if action=='browser_snapshot' and hasattr(browser,'private_form'):
                try:
                    form=browser.private_form()
                    if form and form['fields']:
                        handoff('这一步需要主人补充信息。')
                except (ValueError,BrowserUnavailable,BrowserBlocked):pass
            if action in ('browser_open','browser_click','browser_type','browser_key','browser_scroll','browser_close','browser_visual_click','run'):
                checked=False
                if hasattr(browser,'visual_clear'):browser.visual_clear()
            if passed:checked=True
            last_code=code
            # Ordinary form values may be task data; credentials never reach this path.
            command=redact(json.dumps(browser.private_redact(reply) if hasattr(browser,'private_redact') else reply,ensure_ascii=False));output=redact(json.dumps(browser.private_redact(result) if hasattr(browser,'private_redact') else result,ensure_ascii=False))
            if worker.key:command=command.replace(worker.key,'[服务凭据已隐藏]');output=output.replace(worker.key,'[服务凭据已隐藏]')
            store.record(job_id,ordinal,str(action),command,code,output);ordinal+=1
            messages.append({'role':'assistant','content':command});observe(result);checkpoint()
        store.update(job_id,'failed','浏览器步骤预算已用完；实际页面和步骤保留，没有假报完成。');state.phase(job_id,'done')
    except BrowserCancelled:stopped()
    finally:
        private.close_job(job_id)
        browser.detach()
        try:browser.desktop.heartbeat()
        except Exception:pass
