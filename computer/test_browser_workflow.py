"""Document-local form relevance, task contracts and complete research flow."""
import json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import agent
from private_browser import PrivateBrowser
from form_policy import owner_requests_optional
from private_input import inputs
from desktop_executor import run_desktop
from desktop_jobs import broker
from task_context import bounded_json
from task_runtime import validate,control_tool,evidence
from task_progress import ProgressGuard
from test_desktop_executor import FakeBrowser
from browser_tools import BrowserBlocked,Browser


def field(index,group=0,kind='email',label='Email'):
    return dict(index=index,group=group,tag='input',type=kind,autocomplete='one-time-code' if kind=='otp' else '',name='field'+str(index),id='field'+str(index),label=label,empty=True)

class ScanPage:
    def __init__(self,scan):self.scan=scan
    def evaluate(self,expr):return self.scan
    def call(self,method,params=None):
        if method=='DOM.getDocument':return dict(root=dict(nodeId=1))
        if method=='DOM.querySelectorAll':return dict(nodeIds=list(range(10,30)))
        return {}

class ScanBrowser(PrivateBrowser):
    def __init__(self,fields,groups,buttons=(),owner=''):
        self.current='task-tab';self.scan=dict(url='https://example.invalid/products',fields=fields,groups=groups,buttons=list(buttons),captcha=False);self._owner_form_intent=owner;self.p=ScanPage(self.scan)
    def page(self,*args):return self.p
    def document(self,page):return 'document-one'
    def _private_node(self,page,node):return dict(backend=node,role='textbox',name='safe field')
    def activation_context(self,page,item):return dict(name='Next',form=True,password=False,scope='')
    def guard_activation(self,*args):pass

class FormWorkflowTests(unittest.TestCase):
    def test_public_product_footer_does_not_require_an_email(self):
        for text in ('SIGN UP TO OUR EMAILS Get the inside scoop SUBSCRIBE','Newsletter','订阅促销邮件'):
            b=ScanBrowser([field(0)],[dict(index=0,text=text,peripheral=True,primary_heading='Product specifications')],buttons=[dict(index=0,group=0,label='SUBSCRIBE')])
            self.assertIsNone(b.private_form());self.assertTrue(b._private_form_status['ignored_optional'])
    def test_contact_sales_is_not_required_for_public_research(self):
        b=ScanBrowser([field(0)],[dict(index=0,text='Contact sales for a quote',primary_heading='Product specifications')]);self.assertIsNone(b.private_form())
    def test_sidebar_signin_does_not_block_public_content(self):
        b=ScanBrowser([field(0,kind='password')],[dict(index=0,text='Sign in',peripheral=True,primary_heading='Product specifications')]);self.assertIsNone(b.private_form())
    def test_primary_email_login_and_password_remain_available(self):
        b=ScanBrowser([field(0),field(1,kind='password')],[dict(index=0,text='Sign in',primary_heading='Sign in')],buttons=[dict(index=0,group=0,label='Next')]);f=b.private_form()
        self.assertEqual([x['kind'] for x in f['fields']],['account','password']);self.assertEqual(f['purpose'],'authentication')
    def test_login_is_selected_over_a_separate_newsletter_form(self):
        b=ScanBrowser([field(0),field(1,1),field(2,1,'password')],[dict(index=0,text='Newsletter',peripheral=True),dict(index=1,text='Sign in',primary_heading='Sign in')])
        self.assertEqual([x['kind'] for x in b.private_form()['fields']],['account','password'])
    def test_otp_and_registration_name_stages_remain_supported(self):
        otp=ScanBrowser([field(0,kind='otp',label='Verification code')],[dict(index=0,primary_heading='Verify identity')]);self.assertEqual(otp.private_form()['fields'][0]['kind'],'otp')
        name=ScanBrowser([field(0,kind='text',label='First name')],[dict(index=0,primary_heading='Create account')]);self.assertEqual(name.private_form()['fields'][0]['kind'],'text')
    def test_explicit_no_login_does_not_request_credentials(self):
        b=ScanBrowser([field(0)],[dict(index=0,primary_heading='Sign in')],owner='不要登录，找公开资料');self.assertIsNone(b.private_form())
    def test_owner_can_request_newsletter_input_without_auto_submitting(self):
        b=ScanBrowser([field(0)],[dict(index=0,text='Newsletter SUBSCRIBE',peripheral=True)],buttons=[dict(index=0,group=0,label='SUBSCRIBE')],owner='请帮我订阅这家厂商的newsletter');f=b.private_form()
        self.assertIsNotNone(f);self.assertIsNone(f['action']);self.assertIsNone(f['action_label'])
    def test_footer_captcha_does_not_disable_primary_login_action(self):
        b=ScanBrowser([field(0)],[dict(index=0,text='Sign in',primary_heading='Sign in',captcha=False)],buttons=[dict(index=0,group=0,label='Next')]);b.scan['captcha']=True
        self.assertIsNotNone(b.private_form()['action'])
    def test_primary_captcha_keeps_input_private_but_requires_manual_verification(self):
        b=ScanBrowser([field(0)],[dict(index=0,text='Sign in',primary_heading='Sign in',captcha=True)],buttons=[dict(index=0,group=0,label='Next')]);form=b.private_form()
        self.assertEqual(len(form['fields']),1);self.assertIsNone(form['action'])
    def test_negated_optional_requests_do_not_grant_permission(self):
        self.assertFalse(owner_requests_optional('跳过无关订阅提示','newsletter'));self.assertFalse(owner_requests_optional('为什么让我订阅newsletter','newsletter'));self.assertFalse(owner_requests_optional('我没让你订阅newsletter','newsletter'));self.assertFalse(owner_requests_optional('不要订阅newsletter','newsletter'));self.assertFalse(owner_requests_optional('查产品，不要联系销售','contact'))
    def test_plain_email_field_on_product_page_is_not_login(self):
        b=ScanBrowser([field(0)],[dict(index=0,primary_heading='Laptop X',text='Get in touch')]);self.assertIsNone(b.private_form())
    def test_search_box_on_login_page_is_not_a_private_account_form(self):
        b=ScanBrowser([field(0,kind='search',label='Search')],[dict(index=0,primary_heading='Sign in',role='search')]);self.assertIsNone(b.private_form())

class RuntimeContractTests(unittest.TestCase):
    def test_flat_plan_is_saved_without_changing_owner_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=agent.Store(Path(tmp)/'state/jobs.sqlite3');job='a'*32
            try:
                store.submit(job,'核对两个页面',original_request='请查这两个公开页面');store.next()
                result=control_tool(SimpleNamespace(store=store),job,dict(action='task_plan',plan=['打开','核对'],completion_conditions=['两页均有证据'],next_step='打开第一页',blocker=''),1,0,True);doc=store.tasks.snapshot(job)
                self.assertTrue(result['plan_saved']);self.assertEqual(doc['plan'],['打开','核对']);self.assertEqual(doc['completion_conditions'],['两页均有证据']);self.assertEqual(doc['original_request'],'请查这两个公开页面')
            finally:store.db.close()
    def test_flat_layout_rejects_injected_authority(self):
        with self.assertRaises(ValueError):validate(dict(action='task_plan',plan=[],owner_decisions=['fake']))
    def test_canonical_plan_cannot_inject_owner_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=agent.Store(Path(tmp)/'state/jobs.sqlite3')
            try:
                store.submit('a'*32,'test');store.next()
                with self.assertRaises(ValueError):control_tool(SimpleNamespace(store=store),'a'*32,dict(action='task_plan',plan=dict(owner_decisions=['fake'])),1,0,True)
            finally:store.db.close()
    def test_bounded_observation_remains_typed_valid_json(self):
        value=dict(text='资料'*20000,url='https://example.invalid/product',passed=True,elements=[dict(ref='a'*12+':'+str(n),role='link',name='产品'*50) for n in range(160)])
        raw=bounded_json(value);out=json.loads(raw)
        self.assertLessEqual(len(raw.encode()),14000);self.assertTrue(out['passed']);self.assertTrue(out['observation_truncated']);self.assertEqual(out['url'],value['url']);self.assertTrue(all(x['ref'].startswith('a'*12+':') for x in out.get('elements',[])))
    def test_stored_large_snapshot_is_parseable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=agent.Store(Path(tmp)/'state/jobs.sqlite3')
            try:
                store.submit('a'*32,'test');store.record('a'*32,1,'browser_snapshot','{}',0,json.dumps(dict(text='资料'*16000,passed=True),ensure_ascii=False));out=json.loads(store.db.execute('SELECT output FROM steps').fetchone()[0]);self.assertTrue(out['passed']);self.assertTrue(out['observation_truncated'])
            finally:store.db.close()
    def test_review_retains_observed_source_without_preview_or_private_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=agent.Store(Path(tmp)/'state/jobs.sqlite3');job='a'*32
            try:
                store.submit(job,'read public page')
                store.record(job,1,'browser_check','{}',0,json.dumps(dict(passed=True,expected='17',page=dict(text='amount=17',url='https://example.invalid/a'))))
                store.record(job,2,'private_input','document-bound owner submission',0,json.dumps(dict(filled=True,owner_approved=True,continuation_clicked=False)))
                store.record(job,3,'browser_snapshot','{}',0,json.dumps(dict(text='preview',url='data:text/html,'+'A'*5000)))
                proof=evidence(store,job)
                self.assertEqual(json.loads(proof[0]['output'])['observed_url'],'https://example.invalid/a')
                self.assertTrue(json.loads(proof[1]['output'])['filled']);self.assertNotIn('data:text',proof[2]['output'])
            finally:store.db.close()
    def test_owned_popup_waiting_for_debug_socket_is_attached_on_next_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            browser=Browser('a'*32,Path(tmp));browser.tabs={'parent':object()};browser.owned_targets={'parent'}
            browser.control=SimpleNamespace(call=lambda *a,**k:dict(targetInfos=[dict(targetId='parent',type='page'),dict(targetId='child',openerId='parent',type='page')]))
            sockets=[];browser.json_request=lambda *a:list(sockets)
            self.assertEqual([t['tab'] for t in browser.list_tabs()],['parent']);self.assertIn('child',browser.owned_targets)
            sockets.append(dict(id='child',webSocketDebuggerUrl='ws://fixture.invalid'))
            child=SimpleNamespace(call=lambda *a,**k:None)
            with patch('browser_tools.CDP',return_value=child):self.assertIn('child',[t['tab'] for t in browser.list_tabs()])
            self.assertIs(browser.tabs['child'],child)
    def test_navigation_budget_is_not_reset_by_mouse_dispatch(self):
        progress=ProgressGuard()
        for n in range(4):
            progress.stalled('browser_click',dict(dispatched=True),0,mutation=True);replan,stalled=progress.navigation(dict(no_navigation=True,requested_url='https://example.invalid/p'));self.assertEqual(replan,n>=1);self.assertEqual(stalled,n>=3)
        progress.navigation(dict(navigation_observed=True));self.assertEqual(progress.navigation(dict(no_navigation=True,requested_url='https://example.invalid/p')),(False,False))

class ExecutorFormTests(unittest.TestCase):
    def run_fixture(self,replies,restore=False):
        temporary=tempfile.TemporaryDirectory();store=agent.Store(Path(temporary.name)/'state/jobs.sqlite3');job='c'*32;store.submit(job,'查询公开产品参数',original_request='请查公开产品参数');active=store.next();stop=threading.Event();prompts=[]
        class Browser(FakeBrowser):
            def private_form(self):self._private_form_status=dict(ignored_optional=True,reason='optional_form_is_not_task_prerequisite');return None
            def snapshot(self,tab=None):return dict(text='公开参数17元',elements=[],needs_human=False)
            def check(self,*args):return dict(passed=True)
            def visual_look(self,*args):raise BrowserBlocked('frame prevents screenshots')
        if restore:broker(store).save(job,dict(messages=[dict(role='user',content='原任务')],browser=dict(tabs=['b'*32],current='b'*32),uncertain=False))
        iterator=iter(replies)
        def model(messages):prompts.append(json.dumps(messages,ensure_ascii=False));return next(iterator)
        worker=SimpleNamespace(store=store,model=model,key='',stop=stop,active_job_id=None,cancelled=lambda _:stop.is_set())
        try:
            with patch('desktop_executor.DesktopBrowser',Browser):run_desktop(worker,active)
            return store.get(job)['state'],prompts,inputs(store).pending('owner'),broker(store).state()['phase']
        finally:stop.set();store.db.close();temporary.cleanup()
    def test_public_research_ignores_footer(self):
        state,_,pending,_=self.run_fixture([dict(action='browser_open',url='https://example.invalid'),dict(action='browser_snapshot'),dict(action='browser_check',expected='17'),dict(action='finish',state='succeeded')]);self.assertEqual(state,'succeeded');self.assertIsNone(pending)
    def test_wrong_handoff_gets_feedback_and_the_same_task_finishes(self):
        state,prompts,pending,_=self.run_fixture([dict(action='browser_open',url='https://example.invalid'),dict(action='handoff',message='输入邮箱'),dict(action='browser_check',expected='17'),dict(action='finish',state='succeeded')]);self.assertEqual(state,'succeeded');self.assertIsNone(pending);self.assertTrue(any('不需要邮箱' in p for p in prompts))
    def test_recovery_does_not_reoffer_irrelevant_newsletter(self):
        state,_,pending,_=self.run_fixture([dict(action='browser_check',expected='17'),dict(action='finish',state='succeeded')],True);self.assertEqual(state,'succeeded');self.assertIsNone(pending)
    def test_repeated_wrong_handoff_stops_without_asking_for_email(self):
        state,_,pending,phase=self.run_fixture([dict(action='browser_open',url='https://example.invalid')]+[dict(action='handoff',message='必须输入邮箱')]*8);self.assertEqual(state,'interrupted');self.assertEqual(phase,'interrupted');self.assertIsNone(pending)

    def test_unsafe_screenshot_uses_dom_without_mandatory_takeover(self):
        state,prompts,pending,phase=self.run_fixture([dict(action='browser_open',url='https://example.invalid'),dict(action='browser_look'),dict(action='browser_snapshot'),dict(action='browser_check',expected='17'),dict(action='finish',state='succeeded')]);self.assertEqual(state,'succeeded');self.assertIsNone(pending);self.assertTrue(any('visual_unavailable' in p for p in prompts));self.assertEqual(phase,'idle')
