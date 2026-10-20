"""Bounded artifact operations; never execute a model-supplied program or path."""
import hashlib,os
from pathlib import Path
from execution import Identity,write_artifact

def read(workspace,name):
    if not isinstance(name,str) or not name or name in ('.','..') or '/' in name or '\\' in name:raise ValueError('artifact basename required')
    root=os.open(workspace,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    directory=None
    try:
        directory=os.open('artifacts',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
        with os.fdopen(fd,'rb') as stream:
            import stat
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('regular artifact required')
            raw=stream.read(65537)
        if len(raw)>65536:raise ValueError('artifact exceeds preview budget')
        return raw
    finally:
        if directory is not None:os.close(directory)
        os.close(root)

def action(workspace,reply):
    name=reply.get('name');kind=reply['action']
    if kind=='workspace_write':
        text=reply.get('text')
        if not isinstance(text,str) or len(text.encode())>65536:raise ValueError('artifact text budget')
        write_artifact(workspace,name,text,Identity().account)
    raw=read(workspace,name)
    expected=reply.get('expected')
    passed=kind=='workspace_check' and isinstance(expected,str) and bool(expected) and expected in raw.decode('utf8')
    return dict(path='artifacts/'+name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),passed=passed,
                text=raw.decode('utf8')[:8000] if kind=='workspace_check' else None)
