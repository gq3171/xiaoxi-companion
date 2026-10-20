"""Daytime-only regressions, authored but not executed during preparation."""
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from runtime_support import InferenceLanes, Deferred, Diagnostics, CircuitBreaker, ProviderBackoff
from recall import Recall
from privacy import ForgetFence
from projects import Projects
from speech_pipeline import SpeechPipeline, segments
from capabilities import describe, validate
from execution import Identity, ExecutionUnavailable, write_artifact
import test_agent as tasks


class InferenceTests(unittest.TestCase):
    def test_foreground_enters_while_background_yields_without_network_lock(self):
        lanes=InferenceLanes();background_ready=threading.Event();foreground_ready=threading.Event();release=threading.Event()
        observed=[]
        def background():
            with lanes.enter('reflection',lambda:True) as current:
                background_ready.set()
                foreground_ready.wait(2)
                observed.append(current())
                release.set()
        def foreground():
            with lanes.enter('dialogue',lambda:True):
                foreground_ready.set();release.wait(2)
        one=threading.Thread(target=background);one.start()
        self.assertTrue(background_ready.wait(1))
        two=threading.Thread(target=foreground);two.start()
        one.join(3);two.join(3)
        self.assertFalse(one.is_alive() or two.is_alive());self.assertEqual(observed,[False])
        with lanes.enter('dialogue',lambda:True):
            with self.assertRaises(Deferred):
                with lanes.enter('plan',lambda:True):pass

    def test_cancelled_waiter_does_not_occupy_capacity_or_starve_followup(self):
        lanes=InferenceLanes()
        with lanes.enter('dialogue',lambda:True):
            with self.assertRaises(Deferred):
                with lanes.enter('birth',lambda:False):pass
        with lanes.enter('reflection',lambda:True) as current:self.assertTrue(current())

    def test_diagnostics_exclude_text_and_group_transport_failure_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            diagnostics=Diagnostics(Path(tmp)/'timings.sqlite3')
            try:
                with diagnostics.trace({'session':'private-session','generation':1},'dialogue') as trace:
                    trace.mark('provider_first_text',bytes=3,text='private-owner-text')
                raw=diagnostics.db.execute('SELECT phases,turn FROM timings').fetchone()
                self.assertNotIn('private',str(raw));self.assertEqual(diagnostics.summary()['window'],1)
            finally:diagnostics.db.close()

    def test_endpoint_backoff_does_not_replay_requests_or_block_other_services(self):
        now=[100.];breaker=CircuitBreaker(lambda:now[0])
        error=HTTPError('https://example.invalid',429,'sensitive provider body',{},None)
        breaker.result('/tts',error)
        with self.assertRaises(ProviderBackoff):breaker.before('/tts')
        breaker.before('/asr')
        now[0]+=31;breaker.before('/tts');breaker.result('/tts')
        self.assertEqual(breaker.summary(),{})


class RecallPrivacyTests(unittest.TestCase):
    def test_dated_chinese_recall_does_not_turn_assistant_text_into_owner_evidence(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE archive(op_id TEXT PRIMARY KEY,role TEXT,content TEXT,owner INTEGER,created INTEGER)')
        now=1800000000;recall=Recall(db,lambda:now)
        for key,role,text,owner in [('a','user','周末约好一起看星星',1),('b','assistant','我猜主人喜欢海边',0)]:
            db.execute('INSERT INTO archive VALUES(?,?,?,?,?)',(key,role,text,owner,now-60));recall.add(key,text)
        found=recall.search('还记得看星星的约定吗')
        self.assertEqual(found[0]['source'],'a');self.assertFalse(found[0]['fresh_evidence'])
        self.assertFalse(recall.search('海边')[0]['owner'])
        recall.forget();db.execute('DELETE FROM archive')
        self.assertFalse(recall.search('星星'));db.close()

    def test_old_backup_is_rejected_after_a_committed_forget(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);db=sqlite3.connect(path/'current.sqlite3')
            fence=ForgetFence(db,path/'forget-fence.json');db.commit()
            old=sqlite3.connect(path/'old.sqlite3');db.backup(old)
            with db:fence.advance('a'*32)
            fence.verify()
            with self.assertRaises(ValueError):ForgetFence(old,path/'forget-fence.json')
            old.close();db.close()

    def test_failed_forget_commit_cannot_continue_serving_the_old_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=sqlite3.connect(':memory:');fence=ForgetFence(db,Path(tmp)/'fence.json');db.commit()
            try:
                with db:
                    fence.advance('b'*32)
                    raise RuntimeError('simulated transaction failure')
            except RuntimeError:pass
            with self.assertRaises(ValueError):fence.verify()
            db.close()


class SpeechTests(unittest.TestCase):
    def provider(self, fail_second=False):
        class Provider:
            def __init__(self):self.requests=[]
            def request(self,path,body):
                request=json.loads(body);self.requests.append(request)
                if fail_second and len(self.requests)==2:return io.BytesIO(b'not an audio terminal\n')
                pcm='01000200' if len(self.requests)==1 else '03000400'
                return io.BytesIO(('data: '+json.dumps({'data':{'status':1,'audio':pcm}})+'\n\ndata: {"data":{"status":2,"audio":""}}\n\n').encode())
        return Provider()

    def test_unicode_segments_reassemble_exactly_and_have_a_real_byte_budget(self):
        text=('星星落在窗前，我们翻开小小绘本。A short pause! '*20)
        parts=segments(text)
        self.assertEqual(''.join(parts),text);self.assertTrue(all(len(x.encode())<=150 for x in parts))

    def test_multiple_vendor_segments_become_one_ordered_terminal(self):
        provider=self.provider();pipeline=SpeechPipeline(provider)
        speech={'text':'甲'*70,'voice_setting':{'voice_id':'female-shaonv'}}
        with pipeline.events(speech,lambda:True) as events:values=[json.loads(event) for event in events]
        self.assertEqual(len(provider.requests),2)
        self.assertEqual([x['data']['audio'] for x in values[:-1]],['01000200','03000400'])
        self.assertEqual(sum(x['data']['status']==2 for x in values),1)
        self.assertTrue(all(r['stream_options']['exclude_aggregated_audio'] for r in provider.requests))

    def test_incomplete_lookahead_never_emits_success_or_replays_first_audio(self):
        provider=self.provider(fail_second=True);pipeline=SpeechPipeline(provider);seen=[]
        with self.assertRaises(ValueError):
            with pipeline.events({'text':'乙'*70},lambda:True) as events:
                for value in events:seen.append(json.loads(value))
        self.assertTrue(seen);self.assertFalse(any(x['data']['status']==2 for x in seen))

    def test_cancellation_prevents_a_success_terminal(self):
        provider=self.provider();pipeline=SpeechPipeline(provider);live=[True]
        with pipeline.events({'text':'丙'*70},lambda:live[0]) as events:
            first=json.loads(next(events));self.assertEqual(first['data']['status'],1)
            live[0]=False
            with self.assertRaises(ValueError):list(events)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.now=[1000];self.projects=Projects(self.db,lambda:self.now[0])
    def tearDown(self):self.db.close()

    def test_page_needs_acceptance_matching_goal_and_actual_completion(self):
        answer,proposal=self.projects.prepare({'action':'wait','interest_project':{'title':'窗边的小星星','page_text':'一颗小星星坐在窗边。'}})
        self.assertIsNone(self.projects.current())
        self.projects.accept(proposal,1000)
        self.assertEqual(self.projects.current()['completed_pages'],0)
        self.now[0]=1030
        self.projects.completed({'step':'read','goal':'另一本书','epoch':1030})
        self.assertEqual(self.projects.current()['completed_pages'],0)
        actual={'step':'read','goal':answer['life_plan']['goal'],'epoch':1030}
        self.projects.completed(actual);self.projects.completed(actual)
        self.assertEqual(self.projects.current()['completed_pages'],1)
        self.assertEqual(self.projects.current()['status'],'next_page')

    def test_owner_pause_survives_autonomous_rest_and_forget_removes_the_project(self):
        _,proposal=self.projects.prepare({'action':'wait','interest_project':{'title':'小屋','page_text':'小屋安静下来。'}})
        self.projects.accept(proposal,1000)
        identity=self.projects.current()['id']
        self.projects.accept({'id':identity,'control':'pause'},1001,by_owner=True)
        self.projects.accept({'id':identity,'control':'pause'},1002)
        self.projects.accept({'id':identity,'control':'resume'},1003)
        self.assertEqual(self.projects.current()['status'],'paused')
        self.projects.forget();self.assertIsNone(self.projects.current())


class CapabilityAndIdentityTests(unittest.TestCase):
    def test_old_body_cannot_receive_new_home_or_resume_actions(self):
        with self.assertRaises(ValueError):validate({'action':'speak','home_action':'read'},'dialogue',{})
        with self.assertRaises(ValueError):validate({'action':'computer_resume'},'dialogue',{})
        self.assertIn('read',describe({'home_protocol':2})['home'])
        with self.assertRaises(ValueError):validate({'action':'computer_task','task':'unattended'},'plan',{})

    def test_root_without_executor_fails_closed_and_writes_never_follow_parent_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'DESKPET_EXECUTOR_USER':''}):
            identity=Identity()
            with patch('os.geteuid',return_value=0):
                with self.assertRaises(ExecutionUnavailable):identity.process(Path(tmp))
            target=Path(tmp)/'private';target.mkdir()
            workspace=Path(tmp)/'job';workspace.mkdir();(workspace/'artifacts').symlink_to(target)
            with self.assertRaises(OSError):write_artifact(workspace,'secret.txt','must not escape')
            self.assertFalse((target/'secret.txt').exists())

    def test_skill_requires_actual_post_mutation_verification_and_failed_updates_preserve_old_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=tasks.agent.Store(Path(tmp)/'jobs.sqlite3')
            try:
                job='a'*32;store.submit(job,'整理网页资料');store.next()
                candidate={'name':'网页资料整理','when':'整理网页资料','method':'读取来源后组织段落','check':'检查正文与来源'}
                self.assertIsNone(store.skills.learn(job,candidate))
                store.record(job,1,'check','true',0,'checked')
                store.record(job,2,'run','change',0,'modified')
                store.update(job,'succeeded','simulated state alone is insufficient')
                self.assertIsNone(store.skills.learn(job,candidate))
                store.record(job,3,'check','true',0,'checked after change')
                first=store.skills.learn(job,candidate);self.assertTrue(first)
                failed='b'*32;store.submit(failed,'整理网页资料');store.next();store.update(failed,'failed','真实失败')
                self.assertIsNone(store.skills.learn(failed,candidate|{'method':'未验证的新方法'}))
                self.assertEqual(store.skills.select('整理网页资料')[0]['id'],first)
            finally:store.db.close()


if __name__=='__main__':unittest.main()
