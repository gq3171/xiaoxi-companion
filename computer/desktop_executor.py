"""Narrow v1 browser execution extension; existing command/media worker stays intact."""
import json,re,time
from pathlib import Path
from task_context import redact
from browser_tools import BrowserBlocked,BrowserUnavailable,BrowserCancelled
from desktop_browser import DesktopBrowser
from desktop_jobs import broker,DesktopBusy
from private_input import inputs,wipe

ACTIONS={'browser_open','browser_tabs','browser_snapshot','browser_click','browser_type','browser_key','browser_scroll','browser_check','browser_screenshot','browser_close','browser_look','browser_visual_click','browser_session_status','browser_shutdown','handoff'}
MUTATIONS={'browser_open','browser_click','browser_type','browser_key','browser_scroll','browser_close','browser_visual_click','browser_shutdown'}
def requires_browser(goal):return bool(re.search(r'浏览器|网页交互|注册|表单|登录|填写.{0,8}网站|点击.{0,8}网页',goal,re.I))

def run_desktop(worker,job,messages=None,first=None,ordinal=1,checked=False,last_code=None):
    store=worker.store;job_id=job['id'];state=broker(store);private=inputs(store);saved=state.load(job_id)
    workspace=store.path.parent.parent/'work/browser'/job_id;workspace.mkdir(parents=True,exist_ok=True,mode=0o700)
    browser=DesktopBrowser(store,job_id,workspace,lambda:worker.cancelled(job_id));worker.active_job_id=job_id
    if saved:
        messages=saved['messages'];first=None;checked=False;last_code=None
        with store.lock:ordinal=1+store.db.execute('SELECT coalesce(max(ordinal),0) FROM steps WHERE job=?',(job_id,)).fetchone()[0]
    messages=messages or [{'role':'user','content':json.dumps({'task':job['goal'],'work_directory':str(workspace)},ensure_ascii=False)}]
    pending_effect=(saved or {}).get('pending_effect')
    if (saved or {}).get('uncertain') and not pending_effect:
        pending_effect=dict(step=ordinal-1,action='interrupted_action',observed=False)
    from task_progress import ProgressGuard
    from desktop_lifecycle import BrowserSession,authorize_shutdown
    progress=ProgressGuard();session_closed=bool((saved or {}).get('browser_session_closed'))
    def checkpoint(uncertain=None,phase='running'):
        nonlocal messages
        if len(messages)>11:messages=messages[:1]+messages[-10:]
        state.save(job_id,dict(messages=messages,browser=browser.checkpoint(),uncertain=bool(pending_effect) if uncertain is None else uncertain,pending_effect=pending_effect,browser_session_closed=session_closed),phase)
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
        nonlocal pending_effect
        submission=private.consume(job_id)
        if not submission:return False
        success=False
        try:
            with state.private_action(job_id):
                if hasattr(browser,'private_mark'):browser.private_mark()
                pending_effect=dict(step=ordinal,action='private_input',observed=False)
                checkpoint(phase='waiting_user')
                valid=lambda:not worker.cancelled(job_id) and private.valid(submission['id'])
                browser.private_apply(submission['form'],submission['values'],submission['activate'],valid)
                success=True
                pending_effect=None
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
        if saved and (session_closed or pending_effect and pending_effect.get('action')=='browser_shutdown'):
            # No page exists after browser shutdown. Verify the passive session
            # state without restore()/ensure(), which could reopen Chromium.
            value=BrowserSession().status();observe(value)
            if value['closed']:pending_effect=None;checked=True;last_code=0;session_closed=True
        elif saved:
            browser.restore(saved.get('browser'))
            if browser.tabs:
                value=browser.snapshot();observe(value)
                if pending_effect:pending_effect['observed']=True
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
                latest=state.load(job_id) or {}
                if latest.get('manual_input') and hasattr(browser,'private_mark'):browser.private_mark(unknown=True)
                if browser.tabs:observe(browser.snapshot())
                if pending_effect:pending_effect['observed']=True
                messages.append({'role':'user','content':'主人已交回桌面。重新核对页面，继续原任务；接管前未发出的操作全部作废。'})
                state.phase(job_id,'running')
            revision=store.tasks.revision(job_id)
            dossier={'role':'user','content':json.dumps(store.tasks.context(job_id),ensure_ascii=False)}
            ephemeral=messages[:1]+[dossier]+messages[1:]+([pending_image] if pending_image else [])
            try:reply=first if first is not None else worker.model(ephemeral)
            finally:pending_image=None;ephemeral=None
            first=None
            decisions+=1
            if not isinstance(reply,dict):raise ValueError('invalid browser task response')
            if worker.cancelled(job_id):stopped();return
            if revision!=store.tasks.revision(job_id):first=None;pending_image=None;continue
            if state.waiting(job_id):continue # Discard a model reply arriving after takeover.
            action=reply.get('action');tab=reply.get('tab')
            if action=='task_plan':
                store.tasks.plan(job_id,reply.get('plan'));checkpoint();continue
            if action not in ('browser_look','browser_visual_click') and hasattr(browser,'visual_clear'):browser.visual_clear()
            if action=='handoff':
                if not browser.tabs:observe({'error':'请先用browser_open打开本任务页面，再交给主人处理。'});continue
                handoff(str(reply.get('message') or '请在桌面完成当前验证，然后点“交回小溪”。'));continue
            if action=='finish':
                status=reply.get('state')
                if status not in ('succeeded','failed'):raise ValueError('invalid browser task terminal state')
                if pending_effect:
                    if status=='succeeded':observe({'error':'有一步结果尚未核对，先重新观察并browser_check，不能宣称完成。'});continue
                    checkpoint(phase='interrupted');store.update(job_id,'interrupted','有一步操作结果尚未核对，未自动重发。');state.phase(job_id,'interrupted');return
                if status=='succeeded' and (not checked or last_code!=0):
                    observe({'error':'尚未通过当前实际页面的验证，请browser_check核对，不能假报成功。'});continue
                checkpoint();store.update(job_id,status,str(reply.get('message') or '当前任务已结束。'));state.phase(job_id,'done');return
            if action not in ACTIONS and action not in ('run','check'):raise ValueError('unknown desktop task action')
            if action=='browser_close' and (tab or browser.current) not in browser.tabs:
                # This is a known pre-dispatch scope error, not a lost close
                # acknowledgement. Preserve the ability to choose the proper
                # lifecycle tool; do not invent an unknown side effect.
                result={'error':'本任务没有这个标签；关闭整个专用浏览器应使用browser_shutdown，不能用空标签列表证明浏览器已关闭。','dispatched':False}
                store.record(job_id,ordinal,action,'invalid task-owned tab',1,json.dumps(result,ensure_ascii=False));ordinal+=1
                observe(result);checkpoint()
                if progress.stalled(action,result,1):
                    checkpoint(phase='interrupted');store.update(job_id,'interrupted','标签范围不匹配，已暂停无效重试；未发出关闭操作。');state.phase(job_id,'interrupted');return
                continue
            if action=='browser_shutdown':
                try:authorize_shutdown(store,job_id,reply.get('authorization'))
                except ValueError:
                    checkpoint(phase='interrupted');store.update(job_id,'interrupted','关闭整个浏览器缺少明确的主人原始授权，未执行关闭。');state.phase(job_id,'interrupted');return
            if pending_effect and action in MUTATIONS:
                observe({'error':'前一步可能已经生效。只能先browser_snapshot，再browser_check核对具体当前结果；未重复操作。'});continue
            if action in MUTATIONS:pending_effect=dict(step=ordinal,action=action,observed=False)
            checkpoint();result={};code=0;passed=False
            try:
                with state.action(job_id,revision):
                    store.update(job_id,'running',str(reply.get('message') or '正在核对并操作实际网页。'))
                    if action=='browser_open':result=browser.open(reply.get('url',''))
                    elif action=='browser_tabs':result={'scope':'task_owned_pages','tabs':browser.list_tabs(),'empty_does_not_mean_browser_closed':True}
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
                    elif action=='browser_session_status':
                        checked=False;result=BrowserSession().status();passed=result['closed'];code=0
                        if passed:
                            session_closed=True
                            if pending_effect and pending_effect.get('action') not in ('browser_shutdown','browser_close'):passed=False
                            else:pending_effect=None
                    elif action=='browser_shutdown':
                        result=BrowserSession().shutdown(lambda:worker.cancelled(job_id));passed=result['closed'];code=0 if passed else 1;session_closed=passed
                    elif action in ('run','check'):
                        # Do not grant arbitrary shell execution in the GUI path.
                        result={'error':'网页任务请使用浏览器工具操作和验证；不能用命令绕过密码、条款或人工验证。'};code=1
                    if result.get('needs_human'):raise BrowserBlocked(result.get('blocked_reason','请在桌面完成当前验证。'))
                if action in MUTATIONS:pending_effect=None
                elif action=='browser_snapshot' and pending_effect:pending_effect['observed']=True
                elif action=='browser_check' and passed and pending_effect:
                    if pending_effect.get('observed'):pending_effect=None
                    else:passed=False;code=1;result={'error':'先重新观察页面，再核对未知操作的实际结果。'}
            except DesktopBusy:
                if action in MUTATIONS:pending_effect=None
                checkpoint();continue
            except BrowserBlocked as error:
                # Never persist a password/OTP candidate from a rejected type action.
                if action in MUTATIONS:pending_effect=None
                store.record(job_id,ordinal,'desktop_handoff','protected step',0,'等待主人处理；未发送受保护输入。');ordinal+=1;handoff(str(error));continue
            except (ValueError,BrowserUnavailable) as error:
                result={'error':str(error)[:240],'observe_again':True};code=1
            if action=='browser_snapshot' and hasattr(browser,'private_form'):
                try:
                    form=browser.private_form()
                    if form and form['fields']:
                        handoff('这一步需要主人补充信息。')
                except (ValueError,BrowserUnavailable,BrowserBlocked):pass
            if action in MUTATIONS or action=='run':
                checked=False
                if action!='browser_shutdown':session_closed=False
                if hasattr(browser,'visual_clear'):browser.visual_clear()
            if passed:checked=True
            last_code=code
            # Ordinary form values may be task data; credentials never reach this path.
            command=redact(json.dumps(browser.private_redact(reply) if hasattr(browser,'private_redact') else reply,ensure_ascii=False));output=redact(json.dumps(browser.private_redact(result) if hasattr(browser,'private_redact') else result,ensure_ascii=False))
            if worker.key:command=command.replace(worker.key,'[服务凭据已隐藏]');output=output.replace(worker.key,'[服务凭据已隐藏]')
            store.record(job_id,ordinal,str(action),command,code,output);ordinal+=1
            store.tasks.outcome(job_id,ordinal-1,str(action),code,output,passed)
            messages.append({'role':'assistant','content':command});observe(result);checkpoint()
            if progress.stalled(action,json.loads(output),code,action in MUTATIONS,passed):
                checkpoint(phase='interrupted');store.update(job_id,'interrupted','连续核对未获得新进展，已暂停无效重试。现有页面和待核对结果保留，需要修正工具或补充要求后再继续。');state.phase(job_id,'interrupted');return
        terminal='interrupted' if pending_effect else 'failed'
        store.update(job_id,terminal,'浏览器步骤预算已用完；实际页面和待核对结果保留，没有假报完成。');state.phase(job_id,'interrupted' if pending_effect else 'done')
    except BrowserCancelled:stopped()
    finally:
        private.close_job(job_id)
        browser.detach()
        try:browser.desktop.heartbeat()
        except Exception:pass
