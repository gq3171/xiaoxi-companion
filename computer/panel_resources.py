"""Paired, immutable panel resource slices from NVMe; no tasks or model calls."""
import base64,hashlib,json,os,re,stat,zlib
from pathlib import Path

_verified={}

def resource_rpc(store,path,request):
    if path!='/v1/computer/resource':return None
    identity=request.get('sha256');offset=request.get('offset');amount=request.get('bytes')
    if not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity) or type(offset) is not int or offset<0 or offset%16384 or type(amount) is not int or not 1<=amount<=16384:
        raise ValueError('invalid resource range')
    root=Path(store.media.root).parent.parent/'data/panel-resources'
    manifest=root/'manifest.json'
    with manifest.open('rb') as source:raw=source.read(8193)
    if len(raw)>8192:raise ValueError('invalid resource catalog')
    metadata=json.loads(raw)
    row=next((metadata.get(k) for k in ('font','art') if isinstance(metadata.get(k),dict) and metadata[k].get('sha256')==identity),None)
    if not row or type(row.get('bytes')) is not int or not 0<row['bytes']<=2*1024*1024 or offset>=row['bytes']:
        raise ValueError('resource not available')
    descriptor=os.open(root/(identity+'.bin'),os.O_RDONLY|os.O_NOFOLLOW)
    try:
        with os.fdopen(descriptor,'rb') as source:
            descriptor=None;info=os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size!=row['bytes']:raise ValueError('invalid resource file')
            key=(str(root),identity,info.st_ino,info.st_size,info.st_mtime_ns)
            if key not in _verified:
                digest=hashlib.sha256()
                for block in iter(lambda:source.read(65536),b''):digest.update(block)
                if digest.hexdigest()!=identity:raise ValueError('resource integrity')
                if len(_verified)>=8:_verified.pop(next(iter(_verified)))
                _verified[key]=True
            source.seek(offset);data=source.read(min(amount,info.st_size-offset))
            after=os.fstat(source.fileno())
            if (after.st_size,after.st_mtime_ns)!=(info.st_size,info.st_mtime_ns):raise ValueError('resource changed')
    finally:
        if descriptor is not None:os.close(descriptor)
    return dict(ok=True,sha256=identity,total=info.st_size,offset=offset,crc32=zlib.crc32(data),data=base64.b64encode(data).decode())
