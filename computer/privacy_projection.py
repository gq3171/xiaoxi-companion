"""Closed, value-free observations when old private redactions cannot be rebuilt.

No raw string from the retained page crosses this boundary. The browser can
still report known workflow stages and fixed navigation controls. Unknown pages
remain owner-visible in noVNC/private forms without sending them to the model.
"""
import re

STAGES=(
    (r'account (?:has been |was |is )?(?:successfully )?created|账户.{0,3}创建成功|账号.{0,3}创建成功|帐户.{0,3}创建成功','账户创建完成'),
    (r'verify your email|enter.{0,12}(?:verification|security) code|验证.{0,3}邮箱|输入.{0,4}验证码','等待邮箱或验证码核验'),
    (r'looks like you have an account|account already exists|账户已存在|账号已存在','该账号已经存在'),
    (r'create.{0,15}account|sign up|创建.{0,4}(?:账户|账号|帐户)|注册账户','创建账户页面'),
    (r'signed in successfully|登录成功|登入成功','登录完成'),
)
CONTROLS=re.compile(r'(?:next|continue|back|cancel|close|sign in|log in|create account|create microsoft account|下一步|继续|返回|取消|关闭|登录|创建账户|创建账号)',re.I)

class Projected(dict):pass

def project(info):
    text=str(info.get('text',''))
    stages=[label for pattern,label in STAGES if re.search(pattern,text,re.I)]
    elements=[]
    for item in info.get('elements',[]):
        name=item.get('name','')
        if isinstance(name,str) and CONTROLS.fullmatch(name.strip()):
            elements.append(dict(ref=item['ref'],role=item['role'],name=name.strip(),disabled=bool(item.get('disabled'))))
    known=bool(stages)
    return Projected(privacy_projection=True,privacy_recovery=True,
                tab=info.get('tab'),snapshot=info.get('snapshot'),
                url='[私密页面地址已隐藏]',title='受保护的恢复页面',
                text='；'.join(stages) if known else '恢复后的页面涉及私密信息，请在专用填写窗或真实桌面核对。',
                elements=elements,tabs=[dict(tab=t.get('tab'),title='受保护页面',url='[已隐藏]') for t in info.get('tabs',[])],
                sensitive_fields=bool(info.get('password')),captcha_required=bool(info.get('captcha')),
                needs_human=not known,blocked_reason='恢复后的私密页面不能安全完整读取，请在私密填写窗或真实桌面核对。',
                untrusted_page_data=True)
