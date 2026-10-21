"""Keep secrets out of model/tool summaries; raw old jobs are never new context."""
import os
import re

_SECRET_NAMES = ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL')
_REDACTED = '[凭据已隐藏]'


def redact(text):
    if not isinstance(text, str):
        return text
    for key, value in os.environ.items():
        if len(value) >= 8 and any(part in key.upper() for part in _SECRET_NAMES):
            text = text.replace(value, _REDACTED)
    text = re.sub(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)', _REDACTED, text)
    text = re.sub(r'(?i)(\b(?:authorization\s*:\s*bearer|api[_-]?key|api[_-]?secret|access[_-]?token|password|passwd|secret|token)\b["\s:=]+)([^\s,;"\'}]{8,})', lambda m: m[1] + _REDACTED, text)
    return text


def clean_skill(candidate):
    if not isinstance(candidate, dict):
        return None
    fields = ('name', 'when', 'method', 'check')
    if any(not isinstance(candidate.get(key), str) or redact(candidate[key]) != candidate[key] for key in fields):
        return None
    for key in ('applicability','pitfalls'):
        if key in candidate and (not isinstance(candidate[key],str) or len(candidate[key].encode())>800 or redact(candidate[key])!=candidate[key]):return None
    return {key:candidate[key] for key in fields+('applicability','pitfalls') if key in candidate}


def bounded_json(value,limit=14000):
    """Keep an observation valid JSON when a text/list exceeds its budget.

    Never byte-slice a serialized object, an opaque reference or a URL. A
    dropped/shortened field is explicitly marked; booleans/proof stay typed.
    Callers redact secrets before this serializer, as before.
    """
    import copy,json
    value=copy.deepcopy(value)
    def dump():return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    if len(dump().encode())<=limit:return dump()
    truncated=[]
    def candidates(node,path=()):
        found=[]
        if isinstance(node,dict):
            for key,child in node.items():
                if key in ('ref','tab','snapshot','id','sha256','evidence_id'):continue
                if isinstance(child,(str,list)) and len(child)>1:found.append((len(json.dumps(child,ensure_ascii=False).encode()),node,key,path+(str(key),)))
                found.extend(candidates(child,path+(str(key),)))
        elif isinstance(node,list):
            for i,child in enumerate(node):found.extend(candidates(child,path+(str(i),)))
        return found
    for _ in range(256):
        if len(dump().encode())<=limit:break
        choices=candidates(value)
        if not choices:return json.dumps(dict(truncated=True,reason='observation_budget'),separators=(',',':'))
        _,parent,key,path=max(choices,key=lambda x:x[0]);old=parent[key]
        if isinstance(old,list):parent[key]=old[:len(old)//2]
        elif key in ('url','requested_url','link','href'):parent[key]='[地址超出观察预算，已省略]'
        else:parent[key]=old[:max(1,len(old)//2)]+'…'
        if '.'.join(path) not in truncated:truncated.append('.'.join(path))
    if isinstance(value,dict):
        value['observation_truncated']=True;value['truncated_fields']=truncated[:16]
        # Metadata itself has a small, explicit budget.
        while len(dump().encode())>limit and value['truncated_fields']:value['truncated_fields'].pop()
    if len(dump().encode())>limit:return json.dumps(dict(truncated=True,reason='observation_budget'),separators=(',',':'))
    return dump()
