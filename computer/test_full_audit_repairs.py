"""Synthetic end-to-end contracts for audit repairs; no real accounts/providers."""
import json,os,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import agent,brain
from browser_tools import Browser,BrowserUnavailable,BrowserBlocked
from desktop_browser import DesktopBrowser
from desktop_executor import run_desktop
from desktop_jobs import broker
from execution import Identity,ExecutionUnavailable
from task_control import control
from task_status import select
import test_desktop_executor as desktop
import test_home_chat as web


class Permissions(unittest.TestCase):
    def test_root_empty_missing_and_root_account_fail_before_process_or_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            store=agent.Store(Path(folder)/'state/jobs.sqlite3');worker=agent.Worker(store)
            try:
                store.submit('a'*32,'fixture')
                with patch.dict(os.environ,{'DESKPET_EXECUTOR_USER':''}),patch('os.geteuid',return_value=0),patch('agent.subprocess.Popen') as spawn:
                    with self.assertRaises(ExecutionUnavailable):worker.command('a'*32,'true')
                    spawn.assert_not_called()
                with patch.dict(os.environ,{'DESKPET_EXECUTOR_USER':'root'}):
                    with self.assertRaises(ExecutionUnavailable):Identity()
                with patch.dict(os.environ,{'DESKPET_EXECUTOR_USER':'missing-fixture-account'}):
                    with self.assertRaises(ExecutionUnavailable):Identity()
            finally:store.db.close()

    def test_dedicated_network_policy_never_admits_task_uid_or_flushes_host_rules(self):
        import network_guard as guard
        rule,marker=guard.policy({19492,19493},{0,101,102})
        self.assertIn('19492',rule);self.assertIn('meta skuid != { 0, 101, 102 } reject',rule)
        calls=[]
        def runner(argv,**kw):
            calls.append((argv,kw))
            return SimpleNamespace(returncode=0,stdout=json.dumps({'nftables':[{'rule':{'comment':marker}}]}))
        with patch('os.geteuid',return_value=0),patch.object(guard,'configured',return_value=(rule,marker)):
            guard.ensure(runner)
        script=next(kw['input'] for argv,kw in calls if 'input' in kw)
        self.assertNotIn('flush ruleset',script);self.assertIn('delete table inet xiaoxi_cdp',script)
        with patch.object(guard,'read_layout',return_value={'users':{'computer':'same','desktop':'same','browser':'same'}}),patch.object(guard.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=123)):
            with self.assertRaises(ValueError):guard.configured()


class PrivacyRecovery(unittest.TestCase):
    def test_values_never_survive_via_body_title_url_ax_or_images_after_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            old=object.__new__(DesktopBrowser);Browser.__init__(old,'a'*32,Path(folder))
            old.tabs={'b'*32:None};old.current='b'*32;old.owned_targets={'b'*32}
            old.private_mark();old._private_values=[bytearray(b'SYNTHETIC_PRIVATE_VALUE')]
            saved=old.checkpoint();self.assertTrue(saved['privacy_tainted'])
            self.assertNotIn('SYNTHETIC_PRIVATE_VALUE',json.dumps(saved))
            restored=object.__new__(DesktopBrowser);Browser.__init__(restored,'a'*32,Path(folder))
            restored.ensure=lambda:None
            restored.json_request=lambda *_:[dict(id='b'*32,webSocketDebuggerUrl='fixture')]
            with patch('desktop_browser.CDP',return_value=SimpleNamespace(call=lambda *a:{})):
                restored.restore(saved)
            raw=dict(text='Verify your email SYNTHETIC_PRIVATE_VALUE',title='SYNTHETIC_PRIVATE_VALUE',url='https://example.invalid/SYNTHETIC_PRIVATE_VALUE',password=False,captcha=False,tab='b'*32,snapshot='snapshot',tabs=[dict(tab='b'*32,title='SYNTHETIC_PRIVATE_VALUE',url='SYNTHETIC_PRIVATE_VALUE')],elements=[dict(ref='x',role='textbox',name='SYNTHETIC_PRIVATE_VALUE'),dict(ref='y',role='button',name='Next')])
            with patch.object(Browser,'snapshot',return_value=raw):result=restored.snapshot()
            self.assertNotIn('SYNTHETIC_PRIVATE_VALUE',json.dumps(restored.private_redact(result)))
            self.assertIn('等待邮箱',result['text']);self.assertEqual(len(result['elements']),1)
            self.assertNotIn('SYNTHETIC_PRIVATE_VALUE',json.dumps(restored.private_redact(dict(privacy_projection=True,text='SYNTHETIC_PRIVATE_VALUE'))))
            with self.assertRaises(BrowserUnavailable):restored.screenshot()
            with self.assertRaises(BrowserBlocked):restored.visual_surface(None)
            old.private_clear()


class Workflow(unittest.TestCase):
    setUp=desktop.ExecutorTests.setUp
    tearDown=desktop.ExecutorTests.tearDown
    worker=desktop.ExecutorTests.worker
    def test_lost_ack_blocks_repeat_until_fresh_observation_and_actual_check(self):
        class LostAck(desktop.FakeBrowser):
            def click(self,*args):self.clicks+=1;self.registered=True;raise BrowserUnavailable('synthetic lost acknowledgement')
        replies=iter([dict(action='browser_open',url='https://example.invalid'),dict(action='browser_click',ref='first'),dict(action='browser_click',ref='repeat'),dict(action='browser_check',expected='done'),dict(action='browser_snapshot'),dict(action='browser_check',expected='done'),dict(action='finish',state='succeeded',message='verified')])
        seen=[]
        def model(messages):
            saved=broker(self.store).load(self.id)
            if saved:seen.append(saved['uncertain'])
            return next(replies)
        with patch('desktop_executor.DesktopBrowser',LostAck):run_desktop(self.worker(model),self.job)
        self.assertEqual(LostAck.instances[-1].clicks,1)
        self.assertIn(True,seen);self.assertFalse(broker(self.store).load(self.id)['uncertain'])
        self.assertEqual(self.store.get(self.id)['state'],'succeeded')

    def test_unknown_outcome_remains_interrupted_and_resumable_across_store_restart(self):
        class LostAck(desktop.FakeBrowser):
            def click(self,*args):raise BrowserUnavailable('synthetic lost acknowledgement')
        replies=iter([dict(action='browser_open',url='https://example.invalid'),dict(action='browser_click',ref='x'),dict(action='finish',state='failed')])
        with patch('desktop_executor.DesktopBrowser',LostAck):run_desktop(self.worker(lambda _:next(replies)),self.job)
        self.assertEqual(self.store.get(self.id)['state'],'interrupted');self.assertTrue(broker(self.store).load(self.id)['uncertain'])
        path=self.store.path;self.store.db.close();self.store=agent.Store(path)
        broker(self.store).resume(self.id);job=self.store.next()
        class Recovered(desktop.FakeBrowser):
            def snapshot(self,*args):self.registered=True;return super().snapshot(*args)
        replies=iter([dict(action='browser_check',expected='done'),dict(action='finish',state='succeeded',message='freshly verified')])
        with patch('desktop_executor.DesktopBrowser',Recovered):run_desktop(self.worker(lambda _:next(replies)),job)
        self.assertEqual(self.store.get(self.id)['state'],'succeeded');self.assertEqual(Recovered.instances[-1].clicks,0)

    def test_thirty_step_task_preserves_owner_decisions_and_discards_late_old_plan(self):
        class Advancing(desktop.FakeBrowser):
            def snapshot(self,*args):
                self.observations=getattr(self,'observations',0)+1
                # A long workflow supplies fresh evidence, rather than polling
                # the same empty page thirty times (now correctly paused).
                return super().snapshot(*args)|dict(text='演示流程实际进度 '+str(self.observations))
        self.store.tasks.note(self.id,'b'*32,'只检查演示页面，不创建真实账户')
        calls=0;seen=[]
        def model(messages):
            nonlocal calls
            calls+=1;seen.append(json.dumps(messages,ensure_ascii=False))
            if calls==1:return dict(action='browser_open',url='https://example.invalid')
            if calls==2:
                self.store.tasks.note(self.id,'c'*32,'结果用中文说明')
                return dict(action='browser_click',ref='stale-do-not-click')
            if calls==3:return dict(action='task_plan',plan=dict(completion_conditions=['看到演示完成状态'],plan=['观察页面','核对结果'],next_step='核对演示'))
            if calls<38:return dict(action='browser_snapshot')
            if calls==38:
                desktop.FakeBrowser.instances[-1].registered=True
                return dict(action='browser_check',expected='演示完成')
            return dict(action='finish',state='succeeded',message='演示核验完成')
        with patch('desktop_executor.DesktopBrowser',Advancing):run_desktop(self.worker(model),self.job)
        self.assertEqual(self.store.get(self.id)['state'],'succeeded')
        self.assertEqual(desktop.FakeBrowser.instances[-1].clicks,0)
        self.assertIn('结果用中文说明',seen[-1]);self.assertIn('只检查演示页面',seen[-1])
        self.assertGreaterEqual(self.store.db.execute('SELECT count(*) FROM steps').fetchone()[0],30)
        self.assertTrue(self.store.tasks.snapshot(self.id)['verified_facts'])
        self.assertLessEqual(len(broker(self.store).load(self.id)['messages']),11)

    def test_status_focus_and_owner_control_are_bound_to_the_existing_job(self):
        broker(self.store).save(self.id,dict(browser={},messages=[],uncertain=False),phase='waiting_user')
        before=self.store.db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        result=control(self.store,'computer_update','b'*32,'按刚才的要求继续',self.id)
        self.assertEqual(result['id'],self.id);self.assertEqual(select(self.store)[0]['input_revision'],1)
        control(self.store,'computer_update','b'*32,'按刚才的要求继续',self.id)
        self.assertEqual(self.store.tasks.revision(self.id),1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM jobs').fetchone()[0],before)
        with self.assertRaises(PermissionError):control(self.store,'computer_update','c'*32,'不得生效',self.id,live=lambda:False)


class WebForgetting(unittest.TestCase):
    setUpClass=classmethod(web.HomeChatTests.setUpClass.__func__)
    tearDownClass=classmethod(web.HomeChatTests.tearDownClass.__func__)
    setUp=web.HomeChatTests.setUp
    tearDown=web.HomeChatTests.tearDown
    start=web.HomeChatTests.start
    finished=web.HomeChatTests.finished
    def test_upgrade_discards_orphan_old_drafts_but_keeps_admitted_chat(self):
        self.start();kept=self.finished()['id']
        with self.chat.lock,self.chat.db:
            for n,state in enumerate(('failed','interrupted','done'),100):
                self.chat.db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?,?)',(f'{n:032x}',self.session,'orphan','SYNTHETIC_ORPHAN_DRAFT',state,'{}','',int(time.time())))
            self.chat.db.execute('DROP TABLE turn_epochs');self.chat.db.execute('DROP TABLE web_memory_control')
        self.chat.close();self.chat=web.home_chat.HomeChat(self.world,self.brain,self.computer,self.chat.path);self.world.chat=self.chat
        self.assertEqual([r['id'] for r in self.chat.history(self.session)],[kept])
        self.assertFalse(self.chat.db.execute("SELECT 1 FROM turns WHERE text='SYNTHETIC_ORPHAN_DRAFT'").fetchone())

    def test_real_forget_through_web_facade_updates_shared_epoch(self):
        self.start();self.finished()
        facade,request=self.chat.envelope(self.session,'1'*32)
        def mutate(kind,identifier,**fields):return facade.mutate(request|dict(operation=dict(kind=kind,op_id=identifier,**fields)))
        source=mutate('add','2'*32,role='user',text='我们约好以后聊星星',owner=True)['result']
        mutate('reflection','3'*32,json=json.dumps({'ops':[dict(op='upsert',kind='commitment',slot='星星',text='以后聊星星',importance=3,source_id=source)]}))
        forget=mutate('add','4'*32,role='user',text='请忘记约好聊星星这件事',owner=True)['result']
        mutate('reflection','5'*32,json=json.dumps({'ops':[dict(op='forget',kind='commitment',slot='星星',source_id=forget)]}))
        self.assertEqual(self.memory.forget_epoch,1)
        self.assertEqual(self.memory.db.execute('SELECT forget_epoch FROM memory_control').fetchone()[0],1)
        self.assertFalse(facade.live(request));self.assertEqual(self.chat.history(self.session),[])

    def test_forget_all_sessions_states_cache_and_fences_inflight_work(self):
        self.start();self.finished()
        for n in range(40):
            identifier=f'{n+100:032x}'
            with self.chat.lock,self.chat.db:
                self.chat.db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?,?)',(identifier,'other-session','fixture','SYNTHETIC_FORGET',('failed','interrupted','done')[n%3],'{}','',int(time.time())))
                self.chat.db.execute('INSERT INTO turn_epochs VALUES(?,0)',(identifier,))
        facade,request=self.chat.envelope(self.session,'f'*32)
        self.chat.audio_cache['fixture']=b'cached';self.chat.asr_cache['fixture']=('digest',{'text':'SYNTHETIC_FORGET'})
        with self.memory.lock,self.memory.db:
            self.memory.db.execute('DELETE FROM archive');self.memory.db.execute('UPDATE memory_control SET forget_epoch=1');self.memory.forget_epoch=1
        for listener in self.memory.forget_listeners:listener(1)
        self.assertFalse(self.chat.db.execute("SELECT 1 FROM turns WHERE text!=''").fetchone())
        self.assertFalse(self.chat.audio_cache);self.assertFalse(self.chat.asr_cache)
        self.assertFalse(facade.live(request))
        self.chat.close();self.chat=web.home_chat.HomeChat(self.world,self.brain,self.computer,self.chat.path);self.world.chat=self.chat
        self.assertEqual(self.chat.history(self.session),[])

    def test_web_amendment_quotes_owner_and_keeps_same_task(self):
        self.provider.responses=[dict(input='direct',action='computer_task',task='合成网页测试任务')]
        self.start('打开演示页面并检查标题');first=self.finished();job=first['reply']['job_id']
        self.assertEqual(self.computer.tasks.snapshot(job)['original_request'],'打开演示页面并检查标题')
        self.provider.responses=[dict(input='direct',action='computer_update',job_id=job,task_note='只读检查标题')]
        self.start('补充一下，只读检查标题');last=self.finished()
        self.assertEqual(last['reply']['job_id'],job);self.assertEqual(self.computer.tasks.revision(job),1)
        self.assertEqual(self.computer.db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
