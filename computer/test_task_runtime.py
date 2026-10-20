"""Task-continuity contracts using synthetic jobs, pages and ordinary processes."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import agent
from desktop_jobs import broker, DesktopBusy
from desktop_executor import run_desktop
from task_runtime import completion, control_tool, history, memory, validate, window
from test_desktop_executor import FakeBrowser


class TaskRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=agent.Store(Path(self.tmp.name)/'state/jobs.sqlite3')
        self.id='a'*32;self.store.submit(self.id,'生成报告、核对三项并展示',original_request='比较三个演示来源，保存并展示报告')
        self.job=self.store.next();self.worker=agent.Worker(self.store,lambda _:None)
    def tearDown(self):
        self.worker.managed.close();self.store.db.close();self.tmp.cleanup()
    def record(self,n,kind='check',code=0,text='synthetic verified',rev=0):
        self.store.record(self.id,n,kind,'synthetic command',code,text)
        self.store.tasks.outcome(self.id,n,kind,code,text,code==0 and kind in ('check','browser_check','workspace_check'),revision=rev)
    def test_history_is_task_scoped_and_redacted_and_preserves_action_pair(self):
        self.record(1,text='FIRST_RESULT_123')
        self.store.record('b'*32,1,'check','unrelated','0','OTHER_TASK_PRIVATE')
        with patch.dict(os.environ,{'ANOTHER_API_TOKEN':'SYNTHETIC_SECRET_123'}):  # gitleaks:allow — synthetic redaction fixture, never a service credential
            self.record(2,text='token=SYNTHETIC_SECRET_123')  # gitleaks:allow — synthetic redaction fixture, never a service credential
            result=history(self.store,self.id)
        self.assertIn('FIRST_RESULT_123',str(result));self.assertNotIn('OTHER_TASK_PRIVATE',str(result));self.assertNotIn('SYNTHETIC_SECRET_123',str(result))
        self.assertEqual(result['steps'][0]['command'],'synthetic command')
        self.assertEqual(history(self.store,self.id,'FIRST_RESULT',limit=1)['next_after'],1)
    def test_history_rejects_cross_job_parameters_and_invalid_budgets(self):
        for value in (dict(action='task_history',job='b'*32),dict(action='task_history',limit=True),dict(action='task_history',after=-1),dict(action='command_status',handle='x',wait_seconds=21)):
            with self.subTest(value=value),self.assertRaises(ValueError):validate(value)
    def test_memory_is_derived_and_needs_real_current_revision_refs(self):
        self.record(1)
        self.assertTrue(memory(self.store,self.id,'核对已通过，仍需保存展示',[1],0))
        with self.assertRaises(ValueError):memory(self.store,self.id,'虚构事实',[9],0)
        self.store.tasks.note(self.id,'b'*32,'只用最近七天的数据')
        with self.assertRaises(ValueError):memory(self.store,self.id,'沿用旧证据',[1],1)
        self.assertIn('最近七天',str(self.store.tasks.context(self.id)))
        self.assertEqual(self.store.tasks.snapshot(self.id)['working_memory']['input_revision'],0)
    def test_compaction_retains_pairs_and_history_after_twenty_steps(self):
        messages=[dict(role='user',content='OWNER_ANCHOR')]
        for i in range(1,22):
            self.record(i,text='first evidence' if i==1 else 'synthetic '+str(i))
            messages += [dict(role='assistant',content='action '+str(i)),dict(role='user',content='result '+str(i)+'x'*2000)]
        self.worker.summarize_model=lambda value:dict(summary='早期结果已核对，仍待展示',steps=[1])
        bounded=window(self.worker,self.id,messages)
        self.assertEqual(bounded[0]['content'],'OWNER_ANCHOR');self.assertEqual(bounded[1]['role'],'assistant')
        self.assertLess(len(bounded),len(messages));self.assertIn('first evidence',str(history(self.store,self.id,'first evidence')))
        self.assertEqual(self.store.tasks.snapshot(self.id)['working_memory']['steps'],[1])
    def test_summary_failure_keeps_retrievable_exact_history(self):
        self.record(1,text='SURVIVING_RESULT')
        self.worker.summarize_model=lambda _:(_ for _ in ()).throw(ValueError('bad summary'))
        result=window(self.worker,self.id,[dict(role='user',content='anchor')]+[dict(role='assistant' if i%2==0 else 'user',content='x'*2200) for i in range(20)])
        self.assertEqual(result[0]['content'],'anchor');self.assertIn('SURVIVING_RESULT',str(history(self.store,self.id)))
    def test_structured_plan_cannot_fake_done_or_verified_evidence(self):
        self.record(1)
        self.store.tasks.plan(self.id,dict(plan=[dict(id='observe',text='核对来源',status='done',evidence=[1]),dict(id='save',text='保存报告',depends_on=['observe'],status='pending')]),revision=0)
        for value in (dict(plan=[dict(id='a',text='假完成',status='done')]),dict(plan=[dict(id='a',text='循环',depends_on=['a'])]),dict(completion_conditions=[dict(id='a',text='假证据',evidence=[22])]),dict(owner_decisions=['fake'])):
            with self.assertRaises(ValueError):self.store.tasks.plan(self.id,value,revision=0)
    def test_multi_objective_completion_needs_evidence_for_each_criterion(self):
        self.record(1)
        self.store.tasks.plan(self.id,dict(completion_conditions=[dict(id='compare',text='比较',evidence=[1]),dict(id='show',text='展示',evidence=[])]))
        result=completion(self.worker,self.id,dict(message='全部完成'),0)
        self.assertFalse(result['passed']);self.assertEqual(result['missing'],['展示'])
        self.record(2,'browser_check')
        self.store.tasks.plan(self.id,dict(completion_conditions=[dict(id='compare',text='比较',evidence=[1]),dict(id='show',text='展示',evidence=[2])]))
        self.assertTrue(completion(self.worker,self.id,{},0)['passed'])
    def test_independent_judge_checks_original_even_if_plan_omits_a_requirement(self):
        self.record(1)
        seen=[]
        def judge(payload):
            seen.append(payload)
            return dict(passed=False,requirements=[dict(text='保存并展示报告',met=False,evidence=[])])
        self.worker.review_model=judge
        result=completion(self.worker,self.id,dict(message='完成比较'),0)
        self.assertFalse(result['passed']);self.assertIn('三个',seen[0]['owner_request'])
    def test_judge_cannot_cite_mutation_or_failed_or_other_revision_as_proof(self):
        self.record(1,'run');self.record(2,code=1);self.record(3,rev=1)
        for step in (1,2,3,999):
            self.worker.review_model=lambda _,step=step:dict(passed=True,requirements=[dict(text='报告',met=True,evidence=[step])])
            self.assertFalse(completion(self.worker,self.id,{},0)['passed'])
    def test_late_judge_cannot_finish_or_change_new_revision(self):
        self.record(1)
        def judge(_):
            self.store.tasks.note(self.id,'b'*32,'先不要展示，只保存')
            return dict(passed=True,requirements=[dict(text='展示',met=True,evidence=[1])])
        self.worker.review_model=judge
        self.assertFalse(completion(self.worker,self.id,{},0)['passed'])
        self.assertNotIn('completion_audit',self.store.tasks.snapshot(self.id))
    def test_audit_repair_rounds_are_bounded(self):
        self.record(1);self.worker.review_model=lambda _:dict(passed=False,requirements=[dict(text='未核验',met=False,evidence=[])])
        for _ in range(3):result=completion(self.worker,self.id,{},0)
        self.assertTrue(result['exhausted']);self.assertFalse(result['passed'])
    def test_queue_accepts_independent_jobs_but_never_claims_two_running(self):
        self.store.submit('b'*32,'独立任务');self.assertIsNone(self.store.next())
        self.store.update(self.id,'succeeded','fixture')
        self.assertEqual(self.store.next()['id'],'b'*32);self.assertIsNone(self.store.next())
        self.assertEqual(self.store.db.execute("select count(*) from jobs where state='running'").fetchone()[0],1)
    def test_queue_bound_and_cancel_does_not_cancel_other_jobs(self):
        for i in range(1,8):self.store.submit(f'{i:032x}','synthetic task '+str(i))
        with self.assertRaises(ValueError):self.store.submit('f'*32,'overflow')
        self.store.cancel(f'{1:032x}');self.assertFalse(self.store.get(self.id)['cancel'])
        self.assertEqual(self.store.submit('f'*32,'replacement')['state'],'queued')
    def test_paused_gui_reserves_actual_desktop_but_not_command_queue(self):
        state=broker(self.store);state.save(self.id,dict(messages=[],browser={}),phase='interrupted');self.store.update(self.id,'interrupted','fixture')
        other='b'*32;self.store.submit(other,'独立命令');self.assertEqual(self.store.next()['id'],other)
        with self.assertRaises(DesktopBusy):state.reserve(other)
        self.store.cancel(self.id);state.reserve(other)
    def test_managed_command_executes_once_and_is_observed_by_handle(self):
        result=self.worker.managed.start(self.id,"sleep .1; printf report > report.txt",1,0)
        self.assertFalse(completion(self.worker,self.id,{},0)['passed'])
        result=control_tool(self.worker,self.id,dict(action='command_status',handle=result['handle']),2,0)
        self.assertEqual(result['state'],'succeeded');self.assertEqual(result['result']['exit_code'],0)
        self.assertEqual((self.worker.workspace(self.id)/'report.txt').read_text(),'report')
        self.assertEqual(self.store.db.execute("select count(*) from steps where kind='run'").fetchone()[0],1)
    def test_managed_handle_is_not_a_gui_shell_escape_or_cross_task_lookup(self):
        with self.assertRaises(ValueError):control_tool(self.worker,self.id,dict(action='command_start',command='true'),1,0,desktop=True)
        with self.assertRaises(ValueError):self.worker.managed.status('b'*32,'f'*32)
    def test_cancellation_drains_managed_process_and_prevents_late_artifact(self):
        started=self.worker.managed.start(self.id,'sleep 1; printf late > late',1,0)
        time.sleep(.1);self.store.cancel(self.id);self.worker.managed.close()
        self.assertNotEqual(self.worker.managed.status(self.id,started['handle'])['result']['exit_code'],0)
        time.sleep(1);self.assertFalse((self.worker.workspace(self.id)/'late').exists())
    def test_restart_marks_handle_unknown_and_does_not_replay(self):
        with self.store.lock,self.store.db:self.store.db.execute('insert into task_handles values(?,?,?,?,?,?,?)',('b'*32,self.id,'running',0,1,'',0))
        self.store.db.close();self.store=agent.Store(Path(self.tmp.name)/'state/jobs.sqlite3');self.worker.store=self.store
        self.assertEqual(self.store.db.execute('select state from task_handles').fetchone()[0],'interrupted')
        self.assertEqual(self.store.get(self.id)['state'],'interrupted');self.assertIsNone(self.store.next())
        self.assertFalse(completion(self.worker,self.id,{},0)['passed'])
    def test_gui_success_learns_method_with_applicability_and_pitfalls(self):
        class Checked(FakeBrowser):
            def check(self,*a):return dict(passed=True)
        replies=iter([dict(action='browser_open',url='https://example.invalid'),dict(action='browser_check',expected='synthetic'),dict(action='finish',state='succeeded',skill=dict(name='生成报告',when='生成报告并展示',method='先观察演示页面，再核对保存结果',check='核对报告完成文字',applicability='演示站点的报告页',pitfalls='过期定位需重读页面'))])
        self.worker.model=lambda _:next(replies)
        with patch('desktop_executor.DesktopBrowser',Checked):self.worker.run_job(self.job)
        self.assertEqual(self.store.get(self.id)['state'],'succeeded')
        learned=self.store.lessons('生成报告');self.assertTrue(learned);self.assertIn('过期定位',learned[0]['content'])
    def test_known_failure_nudges_replanning_before_hard_stop(self):
        seen=[]
        def model(messages):seen.append(str(messages));return dict(action='run',command='synthetic')
        self.worker.model=model;self.worker.command=lambda *a:(1,'Permission denied')
        self.worker.run_job(self.job)
        self.assertEqual(self.store.get(self.id)['state'],'interrupted')
        self.assertTrue(any('更新task_plan' in x for x in seen))

    def test_background_completion_invalidates_a_check_made_while_it_ran(self):
        release=threading.Event();entered=threading.Event()
        def command(*args,**kwargs):entered.set();release.wait(3);return 0,'new result'
        self.worker.command=command
        handle=self.worker.managed.start(self.id,'synthetic',1,0)
        self.assertTrue(entered.wait(1));self.record(2)
        release.set();self.worker.managed.thread.join(3)
        self.assertFalse(completion(self.worker,self.id,{},0)['passed'])
        self.record(3)
        self.assertTrue(completion(self.worker,self.id,{},0)['passed'])
    def test_expired_ref_is_known_not_dispatched_then_new_snapshot_can_replan(self):
        from browser_tools import BrowserNotDispatched
        class Stale(FakeBrowser):
            def click(self,ref,*args):
                if ref=='expired':raise BrowserNotDispatched('元素引用已过期，请重新读取页面')
                self.registered=True;self.clicks+=1;return dict(dispatched=True)
        replies=iter([dict(action='browser_open',url='https://example.invalid'),dict(action='browser_click',ref='expired'),dict(action='browser_snapshot'),dict(action='browser_click',ref='fresh'),dict(action='browser_check',expected='synthetic'),dict(action='finish',state='succeeded')])
        self.worker.model=lambda _:next(replies)
        with patch('desktop_executor.DesktopBrowser',Stale):self.worker.run_job(self.job)
        self.assertEqual(self.store.get(self.id)['state'],'succeeded');self.assertEqual(FakeBrowser.instances[-1].clicks,1)
    def test_independent_review_failure_preserves_progress_without_claiming_success(self):
        self.record(1);self.worker.review_model=lambda _:(_ for _ in ()).throw(TimeoutError())
        result=completion(self.worker,self.id,{},0)
        self.assertFalse(result['passed']);self.assertTrue(result['exhausted'])
    def test_cancel_during_compaction_cannot_publish_late_memory(self):
        self.record(1)
        def summarize(_):self.store.cancel(self.id);return dict(summary='late summary',steps=[1])
        self.worker.summarize_model=summarize
        window(self.worker,self.id,[dict(role='user',content='owner')]+[dict(role='assistant' if i%2==0 else 'user',content='x'*2200) for i in range(20)])
        self.assertNotIn('working_memory',self.store.tasks.snapshot(self.id))

    def test_tool_catalog_matches_both_executor_capabilities(self):
        from task_runtime import CATALOG,DESKTOP_TOOLS,TOOLS
        from desktop_executor import ACTIONS,MUTATIONS
        self.assertEqual(set(DESKTOP_TOOLS),ACTIONS)
        self.assertTrue(MUTATIONS <= {name for name,spec in CATALOG.items() if spec['mutation']})
        self.assertTrue(set(TOOLS)<=CATALOG.keys())

    def test_background_spawn_uses_captured_revision_not_workers_later_revision(self):
        self.store.tasks.note(self.id,'b'*32,'不要运行旧步骤')
        self.worker.task_revision=1
        with patch('task_process.Scope') as spawn:
            code,_=self.worker.command(self.id,'must not run',revision=0)
        spawn.assert_not_called();self.assertEqual(code,130)

    def test_preview_capacity_error_is_known_before_dispatch(self):
        from browser_tools import Browser,BrowserNotDispatched
        browser=Browser(self.id,self.tmp.name);browser.tabs={str(i):None for i in range(3)};browser.ensure=lambda:None
        with self.assertRaises(BrowserNotDispatched):browser.preview_text('synthetic report')

    def test_unfocused_status_prefers_running_task_to_new_queued_job(self):
        from task_status import select
        self.store.submit('b'*32,'later queued task')
        self.assertEqual(select(self.store)[0]['id'],self.id)

    def test_review_keeps_check_text_instead_of_encoded_preview_url(self):
        from task_runtime import evidence
        self.record(1,'browser_check',text=json.dumps(dict(passed=True,expected='标题',page=dict(url='data:'+('x'*14000),text='标题 source=A amount=17 difference=6')),ensure_ascii=False))
        proof=evidence(self.store,self.id)
        self.assertIn('difference=6',str(proof));self.assertNotIn('data:',str(proof))

    def test_judge_accepts_operation_plus_real_observation_as_evidence_chain(self):
        self.record(1,'workspace_write');self.record(2,'browser_snapshot');self.record(3,'browser_check')
        self.worker.review_model=lambda _:dict(passed=True,requirements=[dict(text='保存并展示',met=True,evidence=[1,2,3])])
        self.assertTrue(completion(self.worker,self.id,{},0)['passed'])

    def test_compaction_keeps_handoff_notifications_with_their_action_group(self):
        messages=[dict(role='user',content='anchor')]
        for i in range(15):
            messages.extend([dict(role='assistant',content='action '+str(i)),dict(role='user',content='result '+str(i)+'x'*2000),dict(role='user',content='owner hand-back '+str(i))])
        bounded=window(self.worker,self.id,messages)
        self.assertEqual(bounded[1]['role'],'assistant')
        for i,message in enumerate(bounded):
            if isinstance(message.get('content'),str) and message['content'].startswith('result '):
                self.assertEqual(bounded[i-1]['role'],'assistant')


if __name__=='__main__':unittest.main()
