"""Classify document-local forms, never field values or website instructions.

Optional page furniture does not establish a task prerequisite. Only literal
owner requests can opt into newsletter/contact flows; sensitive entry still
uses the document-bound private channel and protected activation rules.
"""
import re

OPTIONAL=re.compile(r'newsletter|mailing.?list|marketing|subscribe|subscription|sign.?up to (?:our|the)|订阅|营销|促销|获取优惠',re.I)
CONTACT=re.compile(r'contact.?us|contact.?sales|sales.?inquir|联系销售|商务咨询|留言',re.I)
AUTH=re.compile(r'log.?in|sign.?in|create.{0,15}account|register|registration|登录|登入|注册|创建.{0,4}(?:账号|账户|帐户)',re.I)
OTP=re.compile(r'one.?time|verification|security.?code|verify.{0,12}(?:identity|email|phone|account)|验证码|验证.{0,3}(?:邮箱|身份)',re.I)


def owner_requests_optional(text,purpose):
    pattern=OPTIONAL if purpose=='newsletter' else CONTACT
    for clause in re.split(r'[，,。；;\n]',text or ''):
        if not pattern.search(clause):continue
        if re.search(r'不要|不用|不必|无需|别|不想|没让|未要求|跳过|忽略|避免|勿|do not|don.t|without|skip|ignore|avoid',clause,re.I):continue
        if re.search(r'(?:帮我|替我|给我|请|我要|我想|需要你).{0,12}(?:订阅|联系销售)|^(?:订阅|联系销售)(?!是什么|的|有|会)|(?:please|help me|i want).{0,24}(?:subscribe|contact)|^(?:subscribe|contact sales|sign me up)\b',clause.strip(),re.I):return True
    return False


def classify(meta,fields,buttons):
    """Return a purpose based on the selected form, not unrelated page text."""
    local=' '.join(str(meta.get(k,'')) for k in ('id','name','action','text','heading'))
    strong=any(f.get('type')=='password' or f.get('autocomplete') in ('current-password','new-password','one-time-code') or OTP.search(f.get('label','')) for f in fields)
    # A genuine password/OTP form is not demoted just because it mentions a
    # separate optional marketing preference; its own sensitive step remains.
    if strong:return 'authentication'
    if meta.get('role')=='search' or any(f.get('type')=='search' for f in fields):return 'optional'
    if OPTIONAL.search(local) or any(OPTIONAL.search(b.get('label','')) for b in buttons):return 'newsletter'
    if CONTACT.search(local):return 'contact'
    if meta.get('peripheral'):return 'optional'
    if AUTH.search(local+' '+str(meta.get('primary_heading',''))+' '+str(meta.get('pathname',''))):return 'authentication'
    if any(re.fullmatch(r'next|continue|sign in|log in|create account|下一步|继续|登录|注册',b.get('label','').strip(),re.I) for b in buttons):return 'authentication'
    return 'optional'


def necessary_auth(meta,owner_text):
    if re.search(r'(?:不要|不用|无需|不必|禁止).{0,4}(?:登录|登入)|do not (?:log|sign) in',owner_text or '',re.I):return False
    if AUTH.search(owner_text or ''):return True
    if meta.get('peripheral'):return False
    primary=str(meta.get('primary_heading',''));path=str(meta.get('pathname',''))
    return bool(meta.get('modal') or AUTH.search(primary+' '+path) or OTP.search(primary+' '+path) or not primary.strip())

DISMISSAL=re.compile(r'no thanks|not now|close|cancel|skip|dismiss|×|✕|以后再说|暂不|不用了|关闭|取消|跳过',re.I)
