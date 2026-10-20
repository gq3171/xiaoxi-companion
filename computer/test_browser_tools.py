"""Prepared adapter replay; no live browser/network. Run only in daytime batch."""
from pathlib import Path
import tempfile
import unittest
from browser_tools import Browser,BrowserUnavailable,BrowserBlocked

class Page:
    def __init__(self):self.document='first';self.events=[];self.password=False;self.name='确认';self.covered=False;self.moving=False;self.samples=0;self.press_failure=False
    def call(self,method,params=None):
        self.events.append((method,params))
        if method=='Page.getFrameTree':return {'frameTree':{'frame':{'loaderId':self.document,'id':'root'}}}
        if method in ('Accessibility.getFullAXTree','Accessibility.getPartialAXTree'):return {'nodes':[{'role':{'value':'button'},'name':{'value':self.name},'backendDOMNodeId':8}]}
        if method=='DOM.resolveNode':return {'object':{'objectId':'node8'}}
        if method=='Runtime.callFunctionOn':
            self.samples+=1
            return {'result':{'value':dict(visible=True,enabled=True,framed=False,editable=True,left=self.samples*10 if self.moving else 0,top=0,width=100,height=40,point=None if self.covered else dict(x=50,y=20))}}
        if method=='Input.dispatchMouseEvent' and params['type']=='mousePressed' and self.press_failure:raise BrowserUnavailable('fixture lost acknowledgement')
        if method=='DOM.getBoxModel':return {'model':{'content':[0,0,100,0,100,40,0,40]}}
        return {}
    def evaluate(self,expression):return {'url':'https://example.org','title':'fixture','ready':'complete','text':'已经完成','password':self.password,'captcha':False}
    def close(self):self.events.append(('closed',None))

class BrowserToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.browser=Browser('a'*32,Path(self.tmp.name))
        self.page=Page();self.browser.tabs['t']=self.page;self.browser.current='t'
        self.browser.heartbeat=lambda:None
    def tearDown(self):self.tmp.cleanup()
    def test_only_observed_current_refs_can_be_clicked(self):
        observed=self.browser.snapshot();ref=observed['elements'][0]['ref']
        self.page.document='next'
        with self.assertRaises(BrowserUnavailable):self.browser.click(ref)
        fresh=self.browser.snapshot()['elements'][0]['ref'];self.browser.click(fresh)
        with self.assertRaises(BrowserUnavailable):self.browser.click(fresh)
        self.assertEqual(sum(x[0]=='Input.dispatchMouseEvent' for x in self.page.events),2)
    def test_login_cannot_pass_a_visible_text_check(self):
        self.page.password=True
        with self.assertRaises(BrowserBlocked):self.browser.check('已经完成')
    def test_unknown_target_and_javascript_urls_never_dispatch(self):
        with self.assertRaises(ValueError):self.browser.page('other-task-tab')
        with self.assertRaises(ValueError):self.browser.open('javascript:alert(1)')
        self.assertFalse(self.page.events)
    def test_cancellation_still_closes_owned_tabs(self):
        calls=[];self.browser.cancelled=lambda:True
        self.browser.json_request=lambda path,method='GET',cleanup=False:calls.append((path,cleanup)) or {}
        self.browser.close();self.assertEqual(calls,[('/json/close/t',True)])
        self.assertFalse(self.browser.tabs)
    def test_changed_label_overlay_and_moving_target_never_receive_a_click(self):
        for change in ('name','covered','moving'):
            with self.subTest(change=change):
                self.page=Page();self.browser.tabs['t']=self.page
                ref=self.browser.snapshot()['elements'][0]['ref']
                setattr(self.page,change,'另一个按钮' if change=='name' else True)
                with self.assertRaises(BrowserUnavailable):self.browser.click(ref)
                self.assertFalse(any(m=='Input.dispatchMouseEvent' for m,_ in self.page.events))
    def test_uncertain_press_releases_button_and_cannot_be_blindly_retried(self):
        ref=self.browser.snapshot()['elements'][0]['ref'];self.page.press_failure=True
        with self.assertRaises(BrowserUnavailable):self.browser.click(ref)
        events=[p['type'] for m,p in self.page.events if m=='Input.dispatchMouseEvent']
        self.assertEqual(events,['mousePressed','mouseReleased'])
        with self.assertRaises(BrowserUnavailable):self.browser.click(ref)
        self.assertEqual(sum(m=='Input.dispatchMouseEvent' for m,_ in self.page.events),2)

if __name__=='__main__':unittest.main()
