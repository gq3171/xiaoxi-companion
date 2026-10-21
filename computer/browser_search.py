"""Public search navigation policy; no account pages or private submissions.

Only known HTTPS search endpoints are recognized. A suggestion is data for the
model, never permission to submit a form or repeat an unknown click.
"""
import re,time
from urllib.parse import urlsplit,parse_qs,urlencode
from runtime_config import settings

ENGINES={
 'google':dict(hosts=('www.google.com','google.com'),path='/search',parameter='q',url='https://www.google.com/search'),
 'bing':dict(hosts=('cn.bing.com','www.bing.com','bing.com'),path='/search',parameter='q',url='https://cn.bing.com/search'),
 'baidu':dict(hosts=('www.baidu.com','baidu.com'),path='/s',parameter='wd',url='https://www.baidu.com/s'),
}

def request(url):
    if not isinstance(url,str):return None
    try:p=urlsplit(url);port=p.port
    except ValueError:return None
    if p.scheme!='https' or p.username or p.password or port not in (None,443) or p.fragment:return None
    for name,spec in ENGINES.items():
        if p.hostname not in spec['hosts'] or p.path not in ('','/',spec['path']):continue
        values=parse_qs(p.query,keep_blank_values=True)
        # Authentication, redirects and opaque token-bearing endpoints are not
        # treated as disposable searches, even on a known engine hostname.
        allowed={spec['parameter'],'hl','lr','ie','oe','source','sourceid','client','form','FORM','first','start','pn','rn','num','safe','ensearch'}
        if set(values)-allowed:return None
        query=values.get(spec['parameter'],[])
        if not query and p.path in ('','/'):return dict(engine=name,query='',url=url)
        if len(query)!=1 or not query[0].strip() or len(query[0].encode())>2048:return None
        return dict(engine=name,query=query[0],url=url)
    return None


def alternatives(search,failed,owner='',now=None):
    now=time.time() if now is None else now
    names=settings()['desktop']['search_engines']
    # Explicit source-only instructions constrain suggestions. A generic
    # discussion of a failed engine does not turn into an exclusive mandate.
    aliases={'google':r'google|谷歌','bing':r'bing|必应','baidu':r'baidu|百度'}
    only={name for name,pattern in aliases.items() if re.search(r'(?:只用|仅用|只使用|仅使用|只能用|only use|use only)\s*(?:'+pattern+')',owner or '',re.I)}
    result=[]
    for name in names:
        if name==search['engine'] or (only and name not in only) or now-failed.get(name,0)<120:continue
        spec=ENGINES[name];url=spec['url']+'?'+urlencode({spec['parameter']:search['query']}) if search['query'] else 'https://'+spec['hosts'][0]+'/'
        result.append(dict(engine=name,url=url))
    return result
