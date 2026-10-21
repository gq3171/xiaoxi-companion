"""Narrow v1 browser execution extension; existing command/media worker stays intact."""
import json,re,time
from pathlib import Path
from task_context import redact,bounded_json
from browser_tools import BrowserBlocked,BrowserUnavailable,BrowserCancelled,BrowserNotDispatched,BrowserSearchFailed
from desktop_browser import DesktopBrowser
from desktop_jobs import broker,DesktopBusy
from private_input import inputs,wipe

from task_runtime import DESKTOP_TOOLS
ACTIONS=set(DESKTOP_TOOLS)
MUTATIONS={'browser_open','browser_click','browser_type','browser_key','browser_scroll','browser_close','browser_visual_click','browser_shutdown','workspace_write','workspace_preview'}
def requires_browser(goal):return bool(re.search(r'浏览器|网页交互|注册|表单|登录|填写.{0,8}网站|点击.{0,8}网页',goal,re.I))

def run_desktop(worker,job,messages=None,first=None,ordinal=1,checked=False,last_code=None,first_revision=None,verified_revision=None):
    store=worker.store;job_id=job['id'];state=broker(store);private=inputs(store);saved=state.load(job_id)
    try:state.reserve(job_id)
    except DesktopBusy:
        store.update(job_id,'interrupted','另一项桌面任务仍保留页面，先继续或停止原任务；本次未操作桌面。');return
    workspace=worker.workspace(job_id) if hasattr(worker,'workspace') else store.path.parent.parent/'work/browser'/job_id
    workspace.mkdir(parents=True,exist_ok=True,mode=0o700)
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
    browser.search_guard=lambda:not pending_effect or pending_effect.get('action')=='browser_open'
    progress=ProgressGuard();session_closed=bool((saved or {}).get('browser_session_closed'))
    def checkpoint(uncertain=None,phase='running'):
        nonlocal messages
        from task_runtime import window
        messages=window(worker,job_id,messages)
        state.save(job_id,dict(messages=messages,browser=browser.checkpoint(),uncertain=bool(pending_effect) if uncertain is None else uncertain,pending_effect=pending_effect,browser_session_closed=session_closed),phase)
    def observe(result):
        raw=bounded_json(json.loads(redact(json.dumps(browser.private_redact(result) if hasattr(browser,"private_redact") else result,ensure_ascii=False))))
        messages.append({'role':'user','content':json.dumps({'untrusted_tool_result':raw},ensure_ascii=False)})
    decisions=0;pending_image=None
    def handoff(message,protected=False):
        form=None
        if hasattr(browser,'private_form'):
            try:form=browser.private_form()
            except (ValueError,BrowserUnavailable,BrowserBlocked):pass
        status=getattr(browser,'_private_form_status',{})
        if not form and status.get('ignored_optional') and not protected:
            observe(dict(private_input_required=False,optional_form_ignored=True,reason='本页只有与任务无关的订阅或联系表单，不需要邮箱。继续查阅资料或使用站内链接。'))
            if progress.stalled('irrelevant_private_handoff',{'optional_form_ignored':True},1):
                checkpoint(phase='interrupted');store.update(job_id,'interrupted','模型反复把可选表单当成任务前提，已暂停；没有索要或发送邮箱。');state.phase(job_id,'interrupted')
                return False
            return False
        if form:message='有一步需要你补充信息。我已打开网站专用的私密填写窗，请到已授权的网页填写；提交后我会继续。'
        # Publish pause, checkpoint and private request atomically; a fast
        # hand-back must never be overwritten by a delayed pause publication.
        with state.condition:
            checkpoint(phase='waiting_user');state.phase(job_id,'waiting_user',message[:500])
            if form:private.offer(job_id,form)
        return True
    def apply_private():
        nonlocal pending_effect,ordinal
        submission=private.consume(job_id)
        if not submission:return False
        success=False
        try:
            with state.private_action(job_id):
                if hasattr(browser,'private_mark'):browser.private_mark()
                pending_effect=dict(step=ordinal,action='private_input',observed=False)
                checkpoint(phase='waiting_user')
                valid=lambda:not worker.cancelled(job_id) and private.valid(submission['id'])
                receipt=browser.private_apply(submission['form'],submission['values'],submission['activate'],valid)
                # Record the effect, never labels, URLs or private field values.
                # The independent reviewer must be able to distinguish a real
                # owner-approved input from the model merely proposing one.
                proof=json.dumps(dict(filled=receipt.get('filled') is True,continuation_clicked=receipt.get('continuation_clicked') is True,owner_approved=True))
                store.record(job_id,ordinal,'private_input','document-bound owner submission',0,proof)
                store.tasks.outcome(job_id,ordinal,'private_input',0,proof,verified=receipt.get('filled') is True,revision=store.tasks.revision(job_id));ordinal+=1
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
    recovery_revision=store.tasks.revision(job_id)
    def search_status(result,related_step):
        nonlocal ordinal
        from browser_search import request as search_request
        search=search_request(result.get('search_url'))
        if not search or result.get('search_navigation_reconciled') is not True:return
        proof=dict(proof='search_connection_unavailable',related_step=related_step,search_failed=True,search_engine=search['engine'],search_url=search['url'],search_navigation_reconciled=True,information_verified=False,error='此搜索连接失败已确认；没有核实该引擎上的资料。')
        output=redact(json.dumps(proof,ensure_ascii=False));store.record(job_id,ordinal,'browser_search_status','native task-owned search observation',0,output)
        store.tasks.outcome(job_id,ordinal,'browser_search_status',0,output,verified=True,revision=store.tasks.revision(job_id));ordinal+=1
    def recovery_proof(action,value,verified=True):
        nonlocal ordinal
        output=redact(json.dumps(value,ensure_ascii=False))
        store.record(job_id,ordinal,action,'passive recovery verification',0,output)
        store.tasks.outcome(job_id,ordinal,action,0,output,verified,revision=recovery_revision);ordinal+=1
    try:
        if saved and (session_closed or pending_effect and pending_effect.get('action')=='browser_shutdown'):
            # No page exists after browser shutdown. Verify the passive session
            # state without restore()/ensure(), which could reopen Chromium.
            value=BrowserSession().status();observe(value)
            if value['closed']:
                session_closed=True
                if not pending_effect or pending_effect.get('action') in ('browser_shutdown','browser_close'):
                    pending_effect=None;checked=True;last_code=0;verified_revision=recovery_revision
                    recovery_proof('browser_session_status',value)
        elif saved:
            restored=saved.get('browser')
            if pending_effect and pending_effect.get('action')=='browser_close' and pending_effect.get('tab'):
                target=pending_effect['tab']
                actual=BrowserSession().status()
                if actual['closed']:
                    present=False;session_closed=True
                else:
                    browser.ensure()
                    present=any(x.get('targetId')==target for x in browser.control.call('Target.getTargets').get('targetInfos',[]))
                observe(dict(scope='task_owned_target',tab=target,closed=not present,verification='task_target_absent' if not present else None))
                pending_effect=None
                if not present:
                    checked=True;last_code=0;verified_revision=recovery_revision
                    recovery_proof('browser_check',dict(closed=True,tab=target,verification='task_target_absent'))
                    restored=dict(restored or {})
                    restored['tabs']=[x for x in restored.get('tabs',[]) if x!=target]
                    restored['owned']=[x for x in restored.get('owned',[]) if x!=target]
                    if restored.get('current')==target:restored['current']=next(iter(restored['tabs']),None)
            if pending_effect and pending_effect.get('action')=='browser_open' and hasattr(browser,'restore_search'):browser.restore_search(restored)
            else:browser.restore(restored)
            recovery_search=browser.arm_search_recovery() if pending_effect and pending_effect.get('action')=='browser_open' and hasattr(browser,'arm_search_recovery') else None
            if browser.tabs:
                try:
                    if recovery_search:
                        with state.action(job_id,recovery_revision):value=browser.snapshot()
                    else:value=browser.snapshot()
                except BrowserSearchFailed as error:
                    if not recovery_search or error.result.get('search_url')!=recovery_search or not error.result.get('search_navigation_reconciled'):raise
                    pending_effect=None;value=None;observe(error.result);recovery_proof('browser_search_failure',error.result,verified=False);search_status(error.result,None);checkpoint()
                except DesktopBusy:
                    # Recovery must not return with an orphaned running job
                    # when the owner takes control before the first read.
                    with state.condition:
                        if store.tasks.revision(job_id)==recovery_revision:
                            checkpoint(phase='interrupted');store.update(job_id,'interrupted','桌面正由主人接管，任务与待核对页面已保留，交回后可继续。',expected_revision=recovery_revision)
                    return
                if value is not None:
                    observe(value)
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
            if state.state().get('phase')=='interrupted':return
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
            if first is not None and first_revision != revision:first=None
            worker.task_revision=revision
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
            from task_runtime import control_tool
            try:control_result=control_tool(worker,job_id,reply,ordinal,revision,desktop=True)
            except ValueError as error:control_result=dict(error=str(error),dispatched=False)
            if control_result is not None:
                store.record(job_id,ordinal,action,json.dumps(reply,ensure_ascii=False) if action!='command_start' else 'rejected command capability',0 if 'error' not in control_result else 1,json.dumps(control_result,ensure_ascii=False));ordinal+=1
                messages.append(dict(role='assistant',content=json.dumps(dict(action=action),ensure_ascii=False)));observe(control_result);checkpoint()
                if control_result.get('requires_reconciliation'):
                    checkpoint(phase='interrupted');store.update(job_id,'interrupted','受管理命令的结果需要核对，没有重放。');state.phase(job_id,'interrupted');return
                if 'error' in control_result and progress.stalled(action,control_result,1):
                    checkpoint(phase='interrupted');store.update(job_id,'interrupted','任务工具连续无效，页面与进度保留。');state.phase(job_id,'interrupted');return
                continue
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
                if status=='succeeded' and (not checked or last_code!=0 or verified_revision!=revision):
                    observe({'error':'尚未通过当前实际页面的验证，请browser_check核对，不能假报成功。'});continue
                if status=='succeeded':
                    from task_runtime import completion
                    result=completion(worker,job_id,reply,revision)
                    if not result['passed']:
                        if result.get('exhausted'):
                            checkpoint(phase='interrupted');store.update(job_id,'interrupted','逐项验收仍有缺项，页面与进度已保存，未宣称完成。');state.phase(job_id,'interrupted');return
                        observe(dict(completion_review=result));continue
                manager=getattr(worker,'managed',None)
                if manager and manager.thread and manager.thread.is_alive():
                    observe(dict(error='受管理命令仍在执行，请先查询handle。'));continue
                with store.lock:unknown=store.db.execute("SELECT 1 FROM task_handles WHERE job=? AND state='interrupted'",(job_id,)).fetchone()
                if unknown:
                    checkpoint(phase='interrupted');store.update(job_id,'interrupted','受管理命令结果尚未核对，没有自动重做。');state.phase(job_id,'interrupted');return
                checkpoint()
                if not store.update(job_id,status,str(reply.get('message') or '当前任务已结束。'),expected_revision=revision):continue
                if store.get(job_id)['state']=='succeeded':store.learn(job_id,reply.get('skill'))
                state.phase(job_id,'done');return
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
            if action in MUTATIONS:
                pending_effect=dict(step=ordinal,action=action,observed=False)
                if action=='browser_open':pending_effect['url']=reply.get('url','')
                if action=='browser_close':pending_effect['tab']=tab or browser.current
                if action=='workspace_write':
                    import hashlib
                    pending_effect.update(name=reply.get('name'),sha256=hashlib.sha256(str(reply.get('text','')).encode()).hexdigest())
            checkpoint();result={};code=0;passed=False;search_observed=False
            try:
                with state.action(job_id,revision):
                    store.update(job_id,'running',str(reply.get('message') or '正在核对并操作实际网页。'))
                    if action=='browser_open':result=browser.open(reply.get('url',''),tab) if tab else browser.open(reply.get('url',''))
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
                    elif action in ('workspace_write','workspace_check'):
                        from workspace_tools import action as file_action
                        result=file_action(workspace,reply);passed=result.get('passed') is True
                        if action=='workspace_check' and not passed:code=1
                    elif action=='workspace_preview':
                        from workspace_tools import read
                        result=browser.preview_text(read(workspace,reply.get('name')).decode('utf8'))
                    elif action in ('run','check'):
                        # Do not grant arbitrary shell execution in the GUI path.
                        result={'error':'混合任务的文件步骤用workspace_write/check/preview；网页步骤用浏览器工具。不能用任意命令绕过密码、条款或人工验证。'};code=1
                    if result.get('needs_human'):raise BrowserBlocked(result.get('blocked_reason','请在桌面完成当前验证。'))
                if action in MUTATIONS:pending_effect=None
                elif action=='workspace_check' and passed and pending_effect and pending_effect.get('action')=='workspace_write':
                    if reply.get('name')==pending_effect.get('name') and result.get('sha256')==pending_effect.get('sha256'):pending_effect=None
                    else:passed=False;code=1
                elif action=='browser_snapshot' and pending_effect:pending_effect['observed']=True
                elif action=='browser_check' and passed and pending_effect:
                    if pending_effect.get('observed'):pending_effect=None
                    else:passed=False;code=1;result={'error':'先重新观察页面，再核对未知操作的实际结果。'}
            except DesktopBusy:
                if action in MUTATIONS:pending_effect=None
                checkpoint();continue
            except BrowserSearchFailed as error:
                result=error.result;code=1;search_observed=result.get('search_navigation_reconciled') is True
                if result.get('search_navigation_reconciled') and (not pending_effect or pending_effect.get('action')=='browser_open' and pending_effect.get('url')==result.get('search_url')):pending_effect=None
            except BrowserBlocked as error:
                # Never persist a password/OTP candidate from a rejected type action.
                if action in MUTATIONS:pending_effect=None
                if action=='browser_look':
                    # A screenshot can be unsafe because of an unrelated frame
                    # or previously filled field. Keep pixels private without
                    # turning this read-only capability failure into a mandatory
                    # owner takeover. DOM actions retain their own guards.
                    result=dict(error='截图因私密内容或框架不可用；改用browser_snapshot的元素定位，先关闭无关弹窗，再继续原任务。只有真实登录或人工验证阻碍任务时才需要主人。',visual_unavailable=True,dispatched=False,next_action='browser_snapshot');code=1
                else:
                    store.record(job_id,ordinal,'desktop_handoff','protected step',0,'等待主人处理；未发送受保护输入。');ordinal+=1;handoff(str(error),protected=True);continue
            except BrowserNotDispatched as error:
                if action in MUTATIONS:pending_effect=None
                result=dict(error=str(error)[:240],error_class='not_dispatched',observe_again=True,next_action='browser_snapshot');result.update(getattr(error,'navigation',{}));code=1
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
            if passed:checked=True;verified_revision=revision
            last_code=code
            # Ordinary form values may be task data; credentials never reach this path.
            command=redact(json.dumps(browser.private_redact(reply) if hasattr(browser,'private_redact') else reply,ensure_ascii=False));output=redact(json.dumps(browser.private_redact(result) if hasattr(browser,'private_redact') else result,ensure_ascii=False))
            if worker.key:command=command.replace(worker.key,'[服务凭据已隐藏]');output=output.replace(worker.key,'[服务凭据已隐藏]')
            store.record(job_id,ordinal,str(action),command,code,output);ordinal+=1
            store.tasks.outcome(job_id,ordinal-1,str(action),code,output,passed,revision=revision)
            if search_observed:search_status(result,ordinal-1)
            messages.append({'role':'assistant','content':command});observe(result);checkpoint()
            nav_replan,nav_stalled=progress.navigation(result)
            if nav_replan:observe(dict(replan_required=True,no_navigation=True,next='输入已发出但没有导航进展；不要重复点击，核对新标签或在已有任务tab打开工具返回的requested_url。'))
            stalled=progress.stalled(action,json.loads(output),code,action in MUTATIONS,passed) or nav_stalled
            if code and progress.errors==2:observe(dict(replan_required=True,next='重新观察当前页面并更新task_plan；无效ref不是未知提交结果，先刷新定位；未知提交结果仍只读核对。'))
            if stalled:
                checkpoint(phase='interrupted');store.update(job_id,'interrupted','连续核对未获得新进展，已暂停无效重试。现有页面和待核对结果保留，需要修正工具或补充要求后再继续。');state.phase(job_id,'interrupted');return
        terminal='interrupted' if pending_effect else 'failed'
        store.update(job_id,terminal,'浏览器步骤预算已用完；实际页面和待核对结果保留，没有假报完成。');state.phase(job_id,'interrupted' if pending_effect else 'done')
    except BrowserCancelled:stopped()
    finally:
        private.close_job(job_id)
        browser.detach()
        try:browser.desktop.heartbeat()
        except Exception:pass
