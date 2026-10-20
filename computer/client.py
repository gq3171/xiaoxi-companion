#!/usr/bin/env python3
"""Authenticated task history and artifact retrieval; no SSH or secret output.

This is a prepared client. Do not run acceptance tests until the user's daytime
window. Existing service versions may not implement these additional routes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import ssl
import tempfile
from runtime_config import public_origin
from deployment_paths import data_root
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPSHandler,ProxyHandler


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser()
    parser.add_argument('--origin',default=public_origin())
    parser.add_argument('--config',type=Path,default=data_root()/'config/service.env')
    parser.add_argument('--ca',type=Path,default=data_root()/'config/ca.pem')
    parser.add_argument('--job');parser.add_argument('--artifact');parser.add_argument('--out',type=Path)
    args=parser.parse_args();origin=urlsplit(args.origin)
    if origin.scheme!='https' or not origin.hostname or origin.username or origin.password or origin.path not in ('','/') or origin.query or origin.fragment:
        parser.error('需要HTTPS origin，不包含路径或凭据')
    if args.artifact and (not args.job or not args.out):parser.error('取产物需要--job、--artifact和--out')
    values={}
    for line in args.config.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key,value=line.split('=',1);values[key]=value
    token=values['DESKPET_COMPUTER_TOKEN'];context=ssl.create_default_context(cafile=str(args.ca))
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context))
    route='artifact' if args.artifact else 'detail' if args.job else 'list'
    payload={'job_id':args.job,'artifact_id':args.artifact} if args.artifact else {'job_id':args.job} if args.job else {'limit':8}
    request=Request(args.origin.rstrip('/')+'/v1/computer/'+route,json.dumps(payload).encode(),
                    {'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with opener.open(request,timeout=30) as response:
        if not args.artifact:
            data=response.read(256*1024+1)
            if len(data)>256*1024:raise ValueError('任务信息超过预算')
            print(json.dumps(json.loads(data),ensure_ascii=False,indent=2));return
        expected=response.headers.get('X-Artifact-SHA256','')
        if len(expected)!=64:raise ValueError('服务器未提供产物校验')
        args.out.parent.mkdir(parents=True,exist_ok=True)
        if args.out.exists():raise ValueError('目标文件已存在，请选择新路径')
        temporary=None
        try:
            digest=hashlib.sha256();total=0
            with tempfile.NamedTemporaryFile(dir=args.out.parent,delete=False) as stream:
                temporary=Path(stream.name)
                while True:
                    block=response.read(65536)
                    if not block:break
                    total+=len(block)
                    if total>50*1024*1024:raise ValueError('产物超过预算')
                    digest.update(block);stream.write(block)
                stream.flush();os.fsync(stream.fileno())
            if digest.hexdigest()!=expected:raise ValueError('产物传输校验失败')
            # Exclusive link avoids replacing an existing path created meanwhile.
            os.link(temporary,args.out);temporary.unlink();temporary=None
            print(json.dumps({'saved':str(args.out),'size':total,'sha256':expected},ensure_ascii=False))
        finally:
            if temporary:temporary.unlink(missing_ok=True)

if __name__=='__main__':main()
