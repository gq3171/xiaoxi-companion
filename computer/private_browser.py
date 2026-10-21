"""Adapter-owned, document-bound private form filling, separate from model tools."""
import hashlib
import json
import re
import secrets
from urllib.parse import urlsplit
from form_policy import classify, owner_requests_optional, necessary_auth

from browser_tools import Browser, BrowserUnavailable, BrowserBlocked

FIELD_SELECTOR = 'input,textarea,select'
BUTTON_SELECTOR = 'button,input[type=submit],input[type=button]'
_SCAN = r'''(()=>{
 const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return e.isConnected&&r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled&&!e.readOnly&&!e.closest('[inert]');};
 const label=e=>(e.getAttribute('aria-label')||Array.from(e.labels||[]).map(x=>x.innerText).join(' ')||e.getAttribute('placeholder')||e.getAttribute('name')||'').trim().slice(0,120);
 const forms=Array.from(document.forms), group=e=>forms.indexOf(e.form);
 const fields=Array.from(document.querySelectorAll('input,textarea,select')).map((e,index)=>({
  index,tag:e.tagName.toLowerCase(),type:(e.type||'text').toLowerCase(),autocomplete:e.autocomplete||'',
  name:e.name||'',id:e.id||'',label:label(e),group:group(e),visible:visible(e),empty:!String(e.value||'').trim(),
  options:e.tagName==='SELECT'?Array.from(e.options).slice(0,100).map((o,i)=>({index:i,label:o.label.slice(0,100),value:o.value,disabled:o.disabled})):null
 })).filter(e=>e.visible&&!['hidden','checkbox','radio','submit','button','file','image','reset','range','color'].includes(e.type));
 const buttons=Array.from(document.querySelectorAll('button,input[type=submit],input[type=button]')).map((e,index)=>({index,group:group(e),visible:visible(e),label:(e.getAttribute('aria-label')||e.innerText||e.value||'').trim().slice(0,120)})).filter(e=>e.visible);
 const groups=forms.map((f,index)=>({index,id:f.id||'',name:f.getAttribute('name')||'',role:f.getAttribute('role')||'',modal:!!f.closest('[role=dialog],[aria-modal=true]'),action:f.getAttribute('action')||'',pathname:location.pathname,
  text:(f.innerText||'').slice(0,1500),heading:Array.from(f.querySelectorAll('legend,h1,h2,h3')).map(x=>x.innerText).join(' ').slice(0,300),
  captcha:Array.from(document.querySelectorAll('iframe[src*=recaptcha],iframe[src*=hcaptcha],[class*=geetest]')).some(x=>visible(x)&&(f.contains(x)||(!x.closest('form,footer,nav,aside')&&f.closest('main,[role=dialog]')?.contains(x)))),
  peripheral:!!f.closest('footer,nav,aside,[role=contentinfo],[role=navigation],[role=complementary]'),
  primary_heading:Array.from(document.querySelectorAll('h1')).filter(x=>!x.closest('footer,nav,[role=contentinfo]')).map(x=>x.innerText).join(' ').slice(0,300)}));
 return {url:location.href,fields,buttons,groups,captcha:Array.from(document.querySelectorAll('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],[class*="geetest"]')).some(visible)};
})()'''


def origin(url):
    parsed = urlsplit(url)
    # Passwords never travel to an ordinary cleartext website. Loopback is only
    # for local integration fixtures, without real credentials.
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')):
        raise BrowserUnavailable('当前网站不是 HTTPS，未打开隐私填写')
    if not parsed.hostname or parsed.username or parsed.password:
        raise BrowserUnavailable('网站地址无法核对')
    host = parsed.hostname.encode('idna').decode('ascii')
    if ':' in host:
        host = '[' + host + ']'
    port = parsed.port
    return parsed.scheme + '://' + host + ((':' + str(port)) if port and port != (443 if parsed.scheme == 'https' else 80) else '')


def safe_label(text):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', str(text))[:120]


class PrivateBrowser:
    def private_mark(self,unknown=False):
        self._privacy_tainted=True
        if unknown:self._privacy_recovery=True

    def private_redact(self, value):
        if getattr(self,'_privacy_recovery',False):
            from privacy_projection import Projected
            if isinstance(value,Projected):return value
            if isinstance(value,str):return '[恢复后的私密内容已隐藏]'
        if isinstance(value, str):
            for secret in sorted(getattr(self, '_private_values', []), key=len, reverse=True):
                if secret:
                    value = value.replace(secret.decode('utf-8'), '[私密填写已隐藏]')
            return value
        if isinstance(value, dict):
            return {key: item if key in ('ref','tab','snapshot') else self.private_redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.private_redact(item) for item in value]
        return value

    def private_clear(self):
        for value in getattr(self, '_private_values', []):
            value[:] = b'\0' * len(value)
        self._private_values = []

    def _private_node(self, page, node_id):
        node = page.call('DOM.describeNode', dict(nodeId=node_id))['node']
        backend = node['backendNodeId']
        ax = page.call('Accessibility.getPartialAXTree', dict(backendNodeId=backend, fetchRelatives=False)).get('nodes', [])
        item = next((n for n in ax if n.get('backendDOMNodeId') == backend and not n.get('ignored')), None)
        if not item:
            raise BrowserUnavailable('隐私表单控件尚不能核对')
        return dict(backend=backend, role=item.get('role', {}).get('value', ''),
                    name=str(item.get('name', {}).get('value', ''))[:240], disabled=False)

    def private_form(self):
        if not self.current:
            return None
        page = self.page()
        document = self.document(page)
        scan = page.evaluate(_SCAN)
        site = origin(scan['url'])
        fields = scan['fields']
        self._private_form_status=dict(ignored_optional=False,reason='no_required_private_form')
        candidates=[]
        groups={g['index']:g for g in scan.get('groups',[])}
        for group in dict.fromkeys(f['group'] for f in fields):
            members=[f for f in fields if f['group']==group]
            buttons=[b for b in scan['buttons'] if b['group']==group]
            meta=groups.get(group,dict(primary_heading=''))
            credential=next((f for f in members if f['type'] in ('password','email') or f['autocomplete'] in ('username','current-password','new-password','one-time-code') or re.search(r'用户名|邮箱|账号|账户|验证码|username|e.?mail|verification|one.?time',f['label'],re.I)),None)
            purpose=classify(meta,members,buttons)
            if purpose=='authentication' and not necessary_auth(meta,getattr(self,'_owner_form_intent','')):
                self._private_form_status=dict(ignored_optional=True,reason='authentication_not_required_for_task',purpose=purpose)
                continue
            if purpose!='authentication' and not (purpose in ('newsletter','contact') and owner_requests_optional(getattr(self,'_owner_form_intent',''),purpose)):
                self._private_form_status=dict(ignored_optional=True,reason='optional_form_is_not_task_prerequisite',purpose=purpose)
                continue
            if credential is None:credential=members[0]
            priority=2 if any(f['type']=='password' or f['autocomplete']=='one-time-code' for f in members) else 1
            candidates.append((priority,group,credential,purpose))
        if not candidates:return None
        _,group,credential,purpose=max(candidates,key=lambda x:x[0])
        self._private_form_status=dict(ignored_optional=False,reason='required_private_form',purpose=purpose)
        selected = [f for f in fields if f['group'] == group and (f['empty'] or f['tag'] == 'select')]
        if len(selected) > 12:
            raise BrowserUnavailable('表单过大，请在真实页面核对')
        registration=purpose=='authentication'
        selected_captcha=groups.get(group,{}).get('captcha',scan['captcha'])
        root = page.call('DOM.getDocument', dict(depth=0))['root']['nodeId']
        nodes = page.call('DOM.querySelectorAll', dict(nodeId=root, selector=FIELD_SELECTOR))['nodeIds']
        bindings = []
        public = []
        for field in selected:
            item = self._private_node(page, nodes[field['index']])
            identifier = secrets.token_hex(6)
            kind = ('select' if field['tag'] == 'select' else 'password' if field['type'] == 'password'
                    else 'otp' if field['autocomplete'] == 'one-time-code' or re.search(r'验证码|verification|one.?time', field['label'], re.I)
                    else 'account' if field is credential and (field['type']=='email' or field['autocomplete']=='username' or re.search(r'用户名|邮箱|账号|username|e.?mail',field['label'],re.I)) else 'text')
            value = dict(id=identifier, kind=kind, label=safe_label(field['label']) or {'password': '密码', 'otp': '验证码', 'account': '账号或邮箱'}.get(kind, '网站要求的信息'))
            if kind == 'select':
                value['options'] = [dict(id=str(o['index']), label=safe_label(o['label'])) for o in field['options'] if not o['disabled'] and o['value']]
                if not value['options']:
                    continue
            public.append(value)
            bindings.append(dict(id=identifier, item=item, field=field))
        action = next((b for b in scan['buttons'] if b['group'] == group and re.fullmatch(
            r'(下一步|继续|登录|登入|登陆|注册|创建账户|创建账号|创建帐户|完成|提交|Next|Continue|Sign in|Log in|Sign up|Create account|Submit)\s*[>›»→]?', b['label'], re.I)), None)
        action_item = None
        login_surface=registration or any(f['type']=='password' or f['autocomplete'] in ('username','one-time-code') for f in fields) or bool(re.search(r'login|signin|sign-in|auth|account',urlsplit(scan['url']).path,re.I))
        if action and login_surface and not selected_captcha:
            buttons = page.call('DOM.querySelectorAll', dict(nodeId=root, selector=BUTTON_SELECTOR))['nodeIds']
            action_item = self._private_node(page, buttons[action['index']])
            # Existing guards still deny payment, publication, destructive acts,
            # explicit terms acceptance and human-verification controls.
            context=self.activation_context(page,action_item)
            if re.search(r'确认支付|确认转账|订单总额|信用卡|付款金额|永久删除|payment|credit card|delete account',context.get('scope',''),re.I):
                action_item=None
            else:
                try:self.guard_activation(context,action_item['name'],bool(re.search(r'create account|sign up|register|创建账户|创建账号|注册',action_item['name'],re.I)),'click')
                except BrowserBlocked:action_item=None
        if not public and not action_item:
            return None
        if document != self.document(page):
            raise BrowserUnavailable('网页已跳转，请重新核对隐私表单')
        fingerprint = hashlib.sha256(json.dumps([document, site, group,
            [(b['item']['backend'], b['field']['type'], b['field']['name'], b['field']['id']) for b in bindings],
            action_item], sort_keys=True).encode()).hexdigest()
        return dict(tab=self.current, document=document, url=scan['url'], origin=site, fingerprint=fingerprint,purpose=purpose,group=group,
                    fields=public, bindings=bindings, action=action_item,
                    action_label=safe_label(action_item['name']) if action_item else None,
                    activation_context=self.activation_context(page,action_item) if action_item else None)

    def _private_context(self, form, valid):
        if not valid() or self.cancelled():
            raise BrowserUnavailable('本次私密填写已停止，未重放输入')
        page = self.page(form['tab'])
        url=page.evaluate('location.href')
        if self.document(page) != form['document'] or origin(url) != form['origin'] or url != form['url']:
            raise BrowserUnavailable('目标网页已变化，未把私密内容填到新页面')
        return page

    def private_apply(self, form, values, activate, valid):
        self.private_mark()
        page = self._private_context(form, valid)
        # Validate the entire field set before sending the first character.
        for binding in form['bindings']:
            self.action_point(page, binding['item'], editable=True)
            node = page.call('DOM.describeNode', dict(backendNodeId=binding['item']['backend']))['node']
            attrs = dict(zip(node.get('attributes', [])[::2], node.get('attributes', [])[1::2]))
            old = binding['field']
            if (attrs.get('type', 'text').lower() if old['tag'] == 'input' else old['type']) != old['type'] or attrs.get('name', '') != old['name'] or attrs.get('id', '') != old['id']:
                raise BrowserUnavailable('隐私控件类型或身份已变化，未填写')
        self._private_values = getattr(self, '_private_values', [])
        for binding in form['bindings']:
            page = self._private_context(form, valid)
            raw = values[binding['id']]
            field = binding['field']
            text = raw.decode('utf-8')
            if field['tag'] == 'select':
                option = next((o for o in field['options'] if str(o['index']) == text and not o['disabled'] and o['value']), None)
                if not option:
                    raise BrowserUnavailable('网站选项已变化')
                text = option['value']
            self._private_values.append(bytearray(text.encode()))
            item = binding['item']
            self.action_point(page, item, editable=True)
            page.call('DOM.focus', dict(backendNodeId=item['backend']))
            if field['tag'] == 'select':
                remote = page.call('DOM.resolveNode', dict(backendNodeId=item['backend']))['object']['objectId']
                try:
                    result = page.call('Runtime.callFunctionOn', dict(objectId=remote,
                        functionDeclaration="function(value){this.value=value;this.dispatchEvent(new Event('input',{bubbles:true}));this.dispatchEvent(new Event('change',{bubbles:true}));return this.value===value;}",
                        arguments=[dict(value=text)], returnByValue=True))
                    if result.get('result', {}).get('value') is not True:
                        raise BrowserUnavailable('选项未能核对，未重复填写')
                finally:
                    page.call('Runtime.releaseObject', dict(objectId=remote))
            else:
                for kind in ('keyDown', 'keyUp'):
                    page.call('Input.dispatchKeyEvent', dict(type=kind, key='a', code='KeyA', modifiers=2))
                page.call('Input.insertText', dict(text=text))
                remote = page.call('DOM.resolveNode', dict(backendNodeId=item['backend']))['object']['objectId']
                try:
                    result = page.call('Runtime.callFunctionOn', dict(objectId=remote,
                        functionDeclaration='function(value){return this.value===value;}',
                        arguments=[dict(value=text)], returnByValue=True))
                    if result.get('result', {}).get('value') is not True:
                        raise BrowserUnavailable('填写结果未能核对，未重复发送')
                finally:
                    page.call('Runtime.releaseObject', dict(objectId=remote))
        clicked = False
        if activate:
            page = self._private_context(form, valid)
            item = form['action']
            if not item:
                raise BrowserUnavailable('没有核对过的继续按钮')
            fresh=page.evaluate(_SCAN)
            group=next((g for g in fresh.get('groups',[]) if g['index']==form.get('group')),None)
            if (group.get('captcha') if group is not None else fresh.get('captcha')):
                raise BrowserUnavailable('网站当前需要人机验证，请在真实页面完成后继续')
            context = self.activation_context(page, item)
            if any(context.get(key)!=form['activation_context'].get(key) for key in ('name','form_action','form_method','password','form')):
                raise BrowserUnavailable('继续按钮已变化，未点击')
            self.guard_activation(context, item['name'], False, 'click')
            self.action_point(page, item)
            self._private_context(form, valid)
            # A single owner-approved click, not a capability exposed to models.
            self._private_activation = (item['backend'], form['document'])
            reference = 'private:' + secrets.token_hex(6)
            self.snapshots[self.current] = dict(document=form['document'], refs={reference: item})
            try:
                Browser.click(self, reference)
                clicked = True
            finally:
                self._private_activation = None
        self.snapshots.clear()
        return dict(filled=True, continuation_clicked=clicked)
