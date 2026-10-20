#!/usr/bin/env python3
"""Public site diagnostic, run on RK after capacity_benchmark.py stops.

Keeps site failures and relevance failures in results; no CAPTCHA bypass.
Requires the benchmark copy in /mnt/nvme/deskpet/data/capacity-test.
"""
import importlib.util,json,subprocess,time,contextlib
from pathlib import Path
base=Path('/mnt/nvme/deskpet/data/capacity-test');out=base/'public-probe';out.mkdir(exist_ok=True)
assert subprocess.run(['systemctl','is-active','--quiet','deskpet-capacity-benchmark-v3']).returncode != 0, 'wait for soak completion'
spec=importlib.util.spec_from_file_location('capacity',base/'benchmark.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.BASE=out
rows=[]
m.event=lambda name,**values: rows.append({'name':name,**values})
def nav(page,url):
 start=time.monotonic()
 page.call('Page.enable');page.call('Page.bringToFront')
 old=page.call('Page.getFrameTree')['frameTree']['frame'].get('loaderId')
 result=page.call('Page.navigate',{'url':url})
 if result.get('errorText'):raise RuntimeError(result['errorText'])
 last={}
 until=time.monotonic()+25
 while time.monotonic()<until:
  try:
   frame=page.call('Page.getFrameTree')['frameTree']['frame']
   last=page.evaluate('({title:document.title,url:location.href,ready:document.readyState,body_chars:document.body?.innerText.length||0,text:document.body?.innerText.slice(0,250)||""})')
   if frame.get('loaderId')!=old and last['url']!='about:blank' and last['ready']!='loading' and last['body_chars']>200:
    last['seconds_to_readable']=round(time.monotonic()-start,3)
    return last
  except RuntimeError:pass
  time.sleep(.15)
 raise TimeoutError('page not readable: '+json.dumps(last,ensure_ascii=False)[:400])
try:
 browser=m.browser(True)
 for url in ['https://www.python.org/doc/','https://github.com/any1/wayvnc','https://www.bing.com/search?q=NanoPC+T4+RK3399+specifications','https://www.baidu.com/s?wd=NanoPC%20T4%20RK3399']:
  page=m.new_page();start=time.monotonic()
  try:
   item=nav(page,url)
   tree=page.call('Accessibility.getFullAXTree')['nodes']
   item.update(url_requested=url,readable=True,ax_nodes=len(tree),ax_named=sum(bool(n.get('name',{}).get('value')) for n in tree))
   if 'bing.com/search' in url or 'baidu.com/s?' in url:
    selector='#b_results .b_algo h2 a' if 'bing.com' in url else '#content_left h3 a'
    time.sleep(1)
    links=page.evaluate('Array.from(document.querySelectorAll('+json.dumps(selector)+')).slice(0,10).map(a=>({title:a.innerText.trim(),url:a.href}))')
    item['search_results']=links
    item['query_relevant_results']=any(x['title'] and any(k in x['title'].lower() for k in ['nanopc','rk3399','friendlyelec']) for x in links)
    item['query_input']=page.evaluate('(document.querySelector("input[name=q],input[name=wd]")||{}).value||""')
   rows.append(item)
  except Exception as err:
   rows.append({'url_requested':url,'readable':False,'error':type(err).__name__+': '+str(err)[:550],'seconds':round(time.monotonic()-start,3)})
  finally:page.close()
  (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
finally:
 for proc in reversed(m.PROCS):m.stop_process(proc)
 (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(json.dumps(rows,ensure_ascii=False),flush=True)
