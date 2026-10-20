"""Job-scoped CDP adapter. Chromium runs in a separate non-root service.

Element references come only from the current AX snapshot, never selectors or
JavaScript invented by the model. This module doesn't start any browser on import.
"""
from __future__ import annotations
import base64
import hashlib
import json
import math
import os
from runtime_config import settings, cdp_port, allowed_cdp_ports
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler
from execution import Identity, write_artifact

ENDPOINT='http://127.0.0.1:'+str(cdp_port())
from deployment_paths import browser_root, storage_ready
BROWSER_HOME=browser_root()


class BrowserUnavailable(RuntimeError): pass
class BrowserBlocked(RuntimeError):
    def __init__(self,message,page=None):
        super().__init__(message);self.page=page
class BrowserCancelled(RuntimeError): pass


class CDP:
    def __init__(self, url, cancelled=lambda:False):
        import websocket
        parsed=urlsplit(url)
        if parsed.scheme!='ws' or parsed.hostname!='127.0.0.1' or parsed.port!=cdp_port():
            raise ValueError('unexpected local debugger endpoint')
        self.ws=websocket.create_connection(url,timeout=.5,suppress_origin=True,skip_utf8_validation=True,
                                            http_proxy_host=None,http_no_proxy=['127.0.0.1'])
        self.serial=0;self.cancelled=cancelled

    def call(self, method, params=None):
        import websocket
        if self.cancelled():raise BrowserCancelled('任务已停止')
        self.serial+=1;serial=self.serial
        self.ws.send(json.dumps(dict(id=serial,method=method,params=params or {})))
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            if self.cancelled():raise BrowserCancelled('任务已停止，网页操作结果需核对')
            try:wire=self.ws.recv()
            except websocket.WebSocketTimeoutException:continue
            if not wire or len(wire)>12*1024*1024:raise BrowserUnavailable('浏览器响应中断或超出预算')
            value=json.loads(wire)
            if value.get('id')!=serial:continue
            if 'error' in value:raise BrowserUnavailable('网页元素已变化或浏览器操作失败，请重新读取页面')
            return value.get('result',{})
        raise BrowserUnavailable('浏览器操作超时，未自动重试可能有副作用的动作')

    def evaluate(self, expression):
        value=self.call('Runtime.evaluate',dict(expression=expression,returnByValue=True))
        if 'exceptionDetails' in value:raise BrowserUnavailable('无法读取当前网页')
        return value.get('result',{}).get('value')

    def close(self):self.ws.close()


class Browser:
    def __init__(self, job_id, workspace, cancelled=lambda:False):
        self.job_id=job_id;self.workspace=Path(workspace);self.cancelled=cancelled
        self.tabs={};self.snapshots={};self.current=None;self.owned_targets=set()
        self.opener=build_opener(ProxyHandler({}))
        self.ready=False;self.control=None

    def json_request(self, path, method='GET', cleanup=False):
        if self.cancelled() and not cleanup:raise BrowserCancelled('任务已停止')
        with self.opener.open(Request(ENDPOINT+path,method=method),timeout=3) as response:
            data=response.read(1024*1024+1)
        if len(data)>1024*1024:raise BrowserUnavailable('调试响应超过预算')
        return json.loads(data)

    def heartbeat(self):
        marker=BROWSER_HOME/'runtime/last-use'
        if marker.exists():marker.touch()

    def ensure(self):
        if self.ready:
            self.heartbeat();return
        if not storage_ready():raise BrowserUnavailable('配置的数据盘未挂载，浏览器未启动')
        subprocess.run(['systemctl','start','deskpet-browser.service'],check=True,timeout=8,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            if self.cancelled():raise BrowserCancelled('任务已停止')
            try:
                info=self.json_request('/json/version')
                self.control=CDP(info['webSocketDebuggerUrl'],self.cancelled)
                self.control.call('Browser.setDownloadBehavior',dict(behavior='deny'))
                self.ready=True;self.heartbeat();return
            except (OSError,ValueError):time.sleep(.2)
        raise BrowserUnavailable('浏览器服务尚未就绪')

    def page(self, tab=None):
        tab=tab or self.current
        if tab not in self.tabs:raise ValueError('先打开页面或选择本任务已有标签')
        self.current=tab;self.heartbeat();return self.tabs[tab]

    def document(self, page):
        frame=page.call('Page.getFrameTree')['frameTree']['frame']
        return frame.get('loaderId','')+':'+frame.get('id','')

    def list_tabs(self):
        infos=[]
        if self.control:
            infos=self.control.call('Target.getTargets').get('targetInfos',[])
            sockets={x['id']:x for x in self.json_request('/json/list') if 'webSocketDebuggerUrl' in x}
            owned=set(self.owned_targets)|set(self.tabs)
            for _ in range(3):
                for item in infos:
                    target=item['targetId']
                    if target in owned or item.get('openerId') not in owned or item.get('type')!='page':continue
                    owned.add(target);self.owned_targets.add(target)
                    if len(self.tabs)>=3:
                        self.control.call('Target.closeTarget',dict(targetId=target));continue
                    if target in sockets:
                        self.tabs[target]=CDP(sockets[target]['webSocketDebuggerUrl'],self.cancelled)
        metadata={x['targetId']:x for x in infos}
        return [dict(tab=tab,title=metadata.get(tab,{}).get('title',''),url=metadata.get(tab,{}).get('url','')) for tab in self.tabs]

    def open(self, url):
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('网页地址需要无内嵌凭据的HTTP或HTTPS地址')
        self.ensure()
        if len(self.tabs)>=3:raise BrowserUnavailable('本任务最多三个标签，请先关闭不用的页面')
        info=self.json_request('/json/new?about:blank','PUT');tab=info['id']
        page=CDP(info['webSocketDebuggerUrl'],self.cancelled);self.tabs[tab]=page;self.current=tab
        self.owned_targets.add(tab)
        page.call('Page.enable');page.call('Accessibility.enable')
        result=page.call('Page.navigate',dict(url=url))
        if result.get('errorText'):raise BrowserUnavailable('页面未能打开')
        # Do not wait for every ad/resource; a following snapshot observes readiness.
        return dict(tab=tab,navigation_requested=True,verification=False)

    def preview_text(self,text):
        # An opaque data origin and escaped preformatted text: local HTML is
        # displayed as source, never executable code with host/file privileges.
        import html
        if not isinstance(text,str) or len(text.encode())>65536:raise ValueError('preview text budget')
        self.ensure()
        if len(self.tabs)>=3:raise BrowserUnavailable('本任务最多三个标签')
        info=self.json_request('/json/new?about:blank','PUT');tab=info['id']
        page=CDP(info['webSocketDebuggerUrl'],self.cancelled);self.tabs[tab]=page;self.current=tab;self.owned_targets.add(tab)
        page.call('Page.enable');page.call('Accessibility.enable')
        content='<meta charset="utf-8"><title>任务文件预览</title><pre>'+html.escape(text)+'</pre>'
        page.call('Page.navigate',dict(url='data:text/html;base64,'+base64.b64encode(content.encode()).decode()))
        return dict(tab=tab,navigation_requested=True,verification=False,scope='task_artifact_preview')

    def snapshot(self, tab=None):
        page=self.page(tab);tab=self.current
        before=self.document(page)
        info=page.evaluate('''({url:location.href,title:document.title,ready:document.readyState,
          text:(document.body?.innerText||'').slice(0,18000),
          password:Array.from(document.querySelectorAll('input[type="password"]')).some(x=>x.getClientRects().length>0),
          captcha:!!document.querySelector('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],[class*="geetest"]')})''')
        nodes=page.call('Accessibility.getFullAXTree',dict(depth=18)).get('nodes',[])
        if before!=self.document(page):raise BrowserUnavailable('页面在读取中跳转，请重新读取')
        serial=os.urandom(6).hex();elements=[];refs={}
        for node in nodes:
            role=node.get('role',{}).get('value','');name=str(node.get('name',{}).get('value',''))[:240]
            if node.get('ignored') or not node.get('backendDOMNodeId'):continue
            if role not in ('button','link','textbox','searchbox','combobox','checkbox','radio','menuitem','tab','option','slider'):continue
            ref=serial+':'+str(len(elements)+1)
            props={x.get('name'):x.get('value',{}).get('value') for x in node.get('properties',[])}
            refs[ref]=dict(backend=node['backendDOMNodeId'],role=role,name=name,disabled=props.get('disabled',False))
            elements.append(dict(ref=ref,role=role,name=name,disabled=props.get('disabled',False)))
            if len(elements)>=160:break
        self.snapshots[tab]=dict(document=before,refs=refs)
        # No password field values are exported or cached.
        info.update(tab=tab,snapshot=serial,elements=elements,tabs=self.list_tabs(),untrusted_page_data=True)
        info['needs_human']=bool(info.get('password') or info.get('captcha'))
        if info['needs_human']:info['blocked_reason']='页面包含登录或验证码入口，需要人工处理；未尝试绕过'
        return info

    def element(self, ref, tab=None):
        page=self.page(tab);snapshot=self.snapshots.get(self.current,{})
        item=snapshot.get('refs',{}).get(ref)
        if not item or snapshot['document']!=self.document(page):raise BrowserUnavailable('元素引用已过期，请重新读取页面')
        if item['disabled']:raise BrowserUnavailable('该控件当前不可操作')
        return page,item

    def before_activate(self, page, item, mode):
        pass

    def click(self, ref, tab=None):
        page,item=self.element(ref,tab)
        self.snapshots.pop(self.current,None)
        x,y=self.action_point(page,item)
        self.before_activate(page,item,'click')
        try:
            page.call('Input.dispatchMouseEvent',dict(type='mousePressed',x=x,y=y,button='left',clickCount=1))
        finally:
            # A timeout doesn't prove the press failed to reach Chrome. Release
            # once, propagate failure, and require observation before any retry.
            page.call('Input.dispatchMouseEvent',dict(type='mouseReleased',x=x,y=y,button='left',clickCount=1))
        return dict(dispatched=True,verification=False)

    def action_point(self,page,item,editable=False):
        page.call('DOM.scrollIntoViewIfNeeded',dict(backendNodeId=item['backend']))
        nodes=page.call('Accessibility.getPartialAXTree',dict(backendNodeId=item['backend'],fetchRelatives=False)).get('nodes',[])
        node=next((n for n in nodes if n.get('backendDOMNodeId')==item['backend']),{})
        if node.get('ignored') or node.get('role',{}).get('value')!=item['role'] or str(node.get('name',{}).get('value',''))[:240]!=item['name']:
            raise BrowserUnavailable('控件身份或文字已变化，请重新读取页面')
        remote=page.call('DOM.resolveNode',dict(backendNodeId=item['backend'])).get('object',{}).get('objectId')
        if not remote:raise BrowserUnavailable('控件已经离开页面，请重新读取')
        # Fixed adapter-owned read-only JS; never source or selectors supplied
        # by the model. A bounding-box center alone may hit an overlay instead.
        function='''function(){
          const r=this.getBoundingClientRect(),s=getComputedStyle(this),d=this.ownerDocument,w=d.defaultView;
          const enabled=!this.matches(':disabled')&&!this.closest('[aria-disabled="true"],[inert]');
          const visible=this.isConnected&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity)!==0&&r.width>0&&r.height>0;
          const l=Math.max(0,r.left),t=Math.max(0,r.top),rr=Math.min(w.innerWidth,r.right),bb=Math.min(w.innerHeight,r.bottom);
          const candidates=[[(l+rr)/2,(t+bb)/2],[l+(rr-l)*.25,t+(bb-t)*.25],[l+(rr-l)*.75,t+(bb-t)*.75]];
          const root=this.getRootNode();let point=null;
          if(visible&&rr>l&&bb>t)for(const [x,y] of candidates){
            let hit=(root.elementFromPoint?root:d).elementFromPoint(x,y);
            if(hit===this||this.contains(hit)){point={x,y};break;}
          }
          return {visible,enabled,framed:w!==w.top,editable:!this.readOnly&&this.getAttribute('aria-readonly')!=='true',
            left:r.left,top:r.top,width:r.width,height:r.height,point};
        }'''
        previous=None
        try:
            for sample in range(2):
                value=page.call('Runtime.callFunctionOn',dict(objectId=remote,functionDeclaration=function,returnByValue=True)).get('result',{}).get('value',{})
                if not value.get('visible') or not value.get('enabled') or not value.get('point') or value.get('framed') or (editable and not value.get('editable')):
                    raise BrowserUnavailable('控件隐藏、遮挡、不可编辑或框架坐标尚不能核对；请重新观察')
                bounds=[value.get(k) for k in ('left','top','width','height')]
                point=[value['point'].get(k) for k in ('x','y')]
                if any(type(x) not in (int,float) or not math.isfinite(x) for x in bounds+point):raise BrowserUnavailable('控件位置无效')
                if previous and any(abs(a-b)>1 for a,b in zip(previous,bounds)):raise BrowserUnavailable('控件仍在移动，请等待并重新读取')
                previous=bounds
                if sample==0:time.sleep(.05)
            return point
        finally:
            try:page.call('Runtime.releaseObject',dict(objectId=remote))
            except Exception:pass

    def type(self, ref, text, tab=None):
        if not isinstance(text,str) or len(text.encode())>4096:raise ValueError('输入文字超出预算')
        page,item=self.element(ref,tab)
        if item['role'] not in ('textbox','searchbox','combobox'):raise ValueError('该元素不是输入框')
        self.snapshots.pop(self.current,None)
        self.action_point(page,item,editable=True)
        # DOM focus + keyboard editing preserve normal input events; no JS setter.
        page.call('DOM.focus',dict(backendNodeId=item['backend']))
        page.call('Input.dispatchKeyEvent',dict(type='keyDown',key='a',code='KeyA',modifiers=2))
        page.call('Input.dispatchKeyEvent',dict(type='keyUp',key='a',code='KeyA',modifiers=2))
        if text:page.call('Input.insertText',dict(text=text))
        else:
            page.call('Input.dispatchKeyEvent',dict(type='keyDown',key='Backspace',code='Backspace'))
            page.call('Input.dispatchKeyEvent',dict(type='keyUp',key='Backspace',code='Backspace'))
        self.snapshots.pop(self.current,None)
        return dict(dispatched=True,verification=False)

    def key(self, key, tab=None):
        if key not in ('Enter','Tab','Escape','ArrowDown','ArrowUp','Backspace'):raise ValueError('不支持该按键')
        page=self.page(tab)
        if key=='Enter':self.before_activate(page,None,'Enter')
        for kind in ('keyDown','keyUp'):
            params=dict(type=kind,key=key,code=key)
            if key=='Enter':
                params.update(windowsVirtualKeyCode=13,nativeVirtualKeyCode=13)
                if kind=='keyDown':params['text']='\r'
            page.call('Input.dispatchKeyEvent',params)
        self.snapshots.pop(self.current,None);return dict(dispatched=True,verification=False)

    def scroll(self, dy, tab=None):
        if type(dy) is not int or not -1200<=dy<=1200:raise ValueError('滚动距离超出预算')
        page=self.page(tab);page.call('Input.dispatchMouseEvent',dict(type='mouseWheel',x=640,y=360,deltaX=0,deltaY=dy))
        self.snapshots.pop(self.current,None);return dict(dispatched=True,verification=False)

    def check(self, expected, tab=None):
        if not isinstance(expected,str) or not 0<len(expected.encode())<=1024:raise ValueError('需要具体要核对的可见文字')
        page=self.snapshot(tab)
        if page['needs_human']:raise BrowserBlocked(page['blocked_reason'],page)
        return dict(passed=expected in page.get('text',''),expected=expected,page=page)

    def screenshot(self, tab=None):
        page=self.page(tab);data=page.call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=False))['data']
        if len(data)>8*1024*1024:raise BrowserUnavailable('截图超过预算')
        name='browser-'+os.urandom(6).hex()+'.png'
        image=base64.b64decode(data,validate=True)
        relative=write_artifact(self.workspace,name,image,Identity().account)
        return dict(path=relative,bytes=len(image),sha256=hashlib.sha256(image).hexdigest())

    def downloads(self):
        # Deliberately not enabled in phase one: no unobserved background downloads.
        raise BrowserUnavailable('当前浏览器阶段不自动下载文件；网页摘录和截图可保存为任务产物')

    def close_tab(self, tab=None):
        tab=tab or self.current
        if tab not in self.tabs:raise ValueError('不是本任务标签')
        if self.cancelled():raise BrowserCancelled('任务已停止')
        if not self.control:raise BrowserUnavailable('浏览器连接未就绪，标签关闭结果未确认')
        try:self.control.call('Target.closeTarget',dict(targetId=tab))
        except BrowserCancelled:raise
        except Exception:pass # Lost acknowledgement: only fresh target evidence counts.
        deadline=time.monotonic()+3
        while True:
            targets=self.control.call('Target.getTargets').get('targetInfos',[])
            if all(item.get('targetId')!=tab for item in targets):break
            if time.monotonic()>=deadline:raise BrowserUnavailable('标签仍存在，关闭结果未确认')
            time.sleep(.1)
        page=self.tabs.pop(tab);page.close();self.snapshots.pop(tab,None);self.owned_targets.discard(tab)
        self.current=next(iter(self.tabs),None)
        return dict(closed=True,verification='task_target_absent',tab=tab)

    def close(self):
        # Popups opened by owned pages are part of this task as well.
        if self.control:
            self.control.cancelled=lambda:False
            try:
                targets=self.control.call('Target.getTargets').get('targetInfos',[])
                owned=set(self.owned_targets)|set(self.tabs)
                for _ in range(3):
                    owned.update(t['targetId'] for t in targets if t.get('openerId') in owned)
                for target in owned-set(self.tabs):
                    try:self.control.call('Target.closeTarget',dict(targetId=target))
                    except Exception:pass
            except Exception:pass
        for tab in list(self.tabs):
            try:self.json_request('/json/close/'+tab,cleanup=True)
            except Exception:pass
            try:self.tabs[tab].close()
            except Exception:pass
        self.tabs.clear();self.snapshots.clear();self.owned_targets.clear()
        if self.control:
            try:self.control.close()
            except Exception:pass
