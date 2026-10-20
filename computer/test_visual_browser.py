import base64,io,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
from browser_tools import Browser, BrowserUnavailable, BrowserBlocked, BrowserCancelled
from visual_browser import VisualBrowser,_SURFACE

class Page:
 def __init__(self):
  self.surface=dict(url='https://example.invalid/',width=800,height=600,x=0,y=0,scale=1,sensitive=False,captcha=False,framed=False)
  self.document='doc';self.events=[];self.backend=8;self.modified=False;self.block=False;self.press_failure=False;self.change_on_move=False
 def image(self):
  image=Image.new('RGB',(1600,1200),'white');draw=ImageDraw.Draw(image)
  draw.rectangle((640,480,960,720),fill='blue' if not self.modified else 'red')
  out=io.BytesIO();image.save(out,format='PNG');return base64.b64encode(out.getvalue()).decode()
 def evaluate(self,expression):return dict(self.surface) if expression==_SURFACE else True
 def call(self,method,params=None):
  params=params or {};self.events.append((method,params))
  if method=='Page.getFrameTree':return dict(frameTree=dict(frame=dict(loaderId=self.document,id='root')))
  if method=='Page.captureScreenshot':return dict(data=self.image())
  if method=='Runtime.evaluate':return dict(result=dict(objectId='target'))
  if method=='DOM.describeNode':return dict(node=dict(backendNodeId=self.backend))
  if method in ('Accessibility.getFullAXTree','Accessibility.getPartialAXTree'):return dict(nodes=[dict(backendDOMNodeId=self.backend,role=dict(value='button'),name=dict(value='View details'))])
  if method=='Runtime.callFunctionOn':return dict(result=dict(value=dict(left=320,top=240,right=480,bottom=360,tag='button')))
  if method=='Input.dispatchMouseEvent':
   if params['type']=='mouseMoved' and self.change_on_move:self.modified=True
   if params['type']=='mousePressed' and self.press_failure:raise BrowserUnavailable('ack lost')
  return {}

class Fixture(VisualBrowser,Browser):
 def before_activate(self,page,item,mode):
  if page.block:raise BrowserBlocked('protected')

class VisualTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.browser=Fixture('a'*32,Path(self.tmp.name));self.page=Page();self.browser.tabs['t']=self.page;self.browser.current='t';self.browser.heartbeat=lambda:None
 def tearDown(self):self.tmp.cleanup()
 def observe(self):return self.browser.visual_look()['visual']
 def click(self,token):return self.browser.visual_click(token,[400,400,600,600],'View details')
 def presses(self):return [p for m,p in self.page.events if m=='Input.dispatchMouseEvent' and p['type']=='mousePressed']
 def test_real_pixel_dimensions_map_to_css_and_image_is_ephemeral(self):
  token=self.observe();message=self.browser.visual_message(token)
  self.assertEqual(message['content'][1]['type'],'image');self.assertEqual(len(list(Path(self.tmp.name).iterdir())),0)
  self.assertTrue(self.click(token)['dispatched']);self.assertEqual((self.presses()[0]['x'],self.presses()[0]['y']),(400,300))
  with self.assertRaises(BrowserUnavailable):self.click(token)
  self.assertEqual(len(self.presses()),1)
 def test_stale_viewport_navigation_and_expired_tokens_rejected(self):
  for field in ('document','scroll','expired','tab'):
   with self.subTest(field=field):
    self.page=Page();self.browser.tabs={'t':self.page};self.browser.current='t';token=self.observe()
    if field=='document':self.page.document='new'
    elif field=='scroll':self.page.surface['x']=10
    elif field=='expired':self.browser._visual['created']-=61
    else:self.browser.tabs['other']=self.page;self.browser.current='other'
    with self.assertRaises(BrowserUnavailable):self.click(token)
    self.assertFalse(self.presses())
 def test_target_pixel_change_hover_change_and_protected_action_rejected(self):
  for field in ('modified','change_on_move','block','backend'):
   with self.subTest(field=field):
    token=self.observe();setattr(self.page,field,9 if field=='backend' else True)
    with self.assertRaises((BrowserUnavailable,BrowserBlocked)):self.click(token)
    self.assertFalse(self.presses());setattr(self.page,field,8 if field=='backend' else False)
 def test_sensitive_frame_captcha_and_private_values_never_capture(self):
  for field in ('sensitive','captcha','framed'):
   self.page.surface[field]=True
   with self.assertRaises(BrowserBlocked):self.observe()
   self.page.surface[field]=False
  self.browser._private_values=[bytearray(b'synthetic')]
  with self.assertRaises(BrowserBlocked):self.observe()
  self.assertFalse(any(m=='Page.captureScreenshot' for m,p in self.page.events))
 def test_cancel_invalid_boxes_and_inference_disable(self):
  for box in ([0,0,1000,1000],[400,400,600,600.0],[True,400,600,600],[600,400,400,600]):
   token=self.observe()
   with self.assertRaises(ValueError):self.browser.visual_click(token,box,'target')
  self.browser.cancelled=lambda:True
  with self.assertRaises(BrowserCancelled):self.observe()
  self.assertFalse(self.presses())
  with patch.dict('os.environ',{'DESKPET_BROWSER_VISION':'0'}):
   with self.assertRaises(BrowserUnavailable):self.observe()
 def test_uncertain_press_released_and_not_replayed(self):
  token=self.observe();self.page.press_failure=True
  with self.assertRaises(BrowserUnavailable):self.click(token)
  events=[p['type'] for m,p in self.page.events if m=='Input.dispatchMouseEvent']
  self.assertEqual(events,['mouseMoved','mousePressed','mouseReleased'])
  with self.assertRaises(BrowserUnavailable):self.click(token)
  self.assertEqual(len(self.presses()),1)
