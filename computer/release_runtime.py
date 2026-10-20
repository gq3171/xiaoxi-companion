"""Deploy only an audited desktop-v1 source bundle, with exact-baseline rollback.

No config, credentials, resources, desktop processes or database rollback writes.
Run on the host: python3 release_runtime.py --release /YOUR_DATA/reviewed-release
"""
from contextlib import closing
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import ssl
import subprocess
import time
from deployment_paths import data_root, install_dir, storage_ready, read_layout

CONTRACT='desktop-v1'
GATES=('active_unit','arm_unit','frontend','browser_guard','rollback')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked_path(root,name):
    p=Path(name)
    if not isinstance(name,str) or p.is_absolute() or not p.parts or any(x in ('..','.') for x in p.parts) or p.as_posix()!=name:
        raise ValueError('invalid release path')
    target=root/p
    if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():raise ValueError('release path escapes root')
    return target


def validate(release,install):
    release,install=Path(release),Path(install)
    manifest=json.loads((release/'manifest.json').read_text())
    if manifest.get('format')!=1 or manifest.get('runtime_contract')!=CONTRACT:raise ValueError('unsupported runtime baseline')
    files=manifest.get('files',{});baseline=manifest.get('baseline',{})
    if not files or not {'agent.py','brain.py','companion.py'}<=files.keys() or not files.keys()<=baseline.keys():raise ValueError('incomplete entrypoint baseline')
    for name,digest in files.items():
        if (Path(name).suffix not in ('.py','.js','.html','.css','.so','.c','.h') and name not in ('runtime.defaults.json','providers.defaults.json')) or name.startswith(('experimental/','vendor/')):raise ValueError('not a runtime update path')
        if sha(checked_path(release,name))!=digest:raise ValueError('staged source changed')
    for name,expected in baseline.items():
        p=checked_path(install,name)
        if (sha(p) if p.exists() else None)!=expected:raise ValueError('installed baseline changed')
    for name in GATES:
        record=manifest.get('checks',{}).get(name,{})
        if record.get('status')!='passed' or sha(checked_path(release,record.get('evidence','')))!=record.get('sha256'):raise ValueError('release evidence missing or changed: '+name)
    return manifest


def idle(base):
    for name,query in [('jobs',"SELECT count(*) FROM jobs WHERE state IN ('queued','running')"),('web-chat',"SELECT count(*) FROM turns WHERE state='working'")]:
        with closing(sqlite3.connect('file:'+str(base/'state'/(name+'.sqlite3'))+'?mode=ro',uri=True)) as db:
            if db.execute(query).fetchone()[0]:raise RuntimeError('active work; deploy later')


def system(action):subprocess.run(['systemctl',action,'deskpet-computer.service'],check=True,timeout=25)


def strict_health(base):
    values={}
    for name in ('service.env','brain.env'):
        for line in (base/'config'/name).read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k,v=line.split('=',1);values[k]=v.strip()
    with closing(sqlite3.connect('file:'+str(base/'state/brain.sqlite3')+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row;row=dict(db.execute('SELECT device,boot,session,generation FROM device WHERE singleton=1').fetchone())
    from urllib.parse import urlsplit
    origin=urlsplit(values['DESKPET_PUBLIC_ORIGIN'])
    context=ssl.create_default_context(cafile=str(base/'config/ca.pem'));results={}
    for purpose,payload,token in [('brain',row,values['DESKPET_BRAIN_TOKEN']),('computer',{},values['DESKPET_COMPUTER_TOKEN'])]:
        raw=json.dumps(payload).encode()
        sock=socket.create_connection(('127.0.0.1',int(read_layout()['port'])),timeout=8)
        with context.wrap_socket(sock,server_hostname=origin.hostname) as stream:
            headers=('POST /v1/'+purpose+'/health HTTP/1.1\r\nHost: '+origin.netloc+'\r\nAuthorization: Bearer '+token+'\r\nContent-Type: application/json\r\nContent-Length: '+str(len(raw))+'\r\nConnection: close\r\n\r\n').encode()
            stream.sendall(headers+raw);response=http.client.HTTPResponse(stream);response.begin();value=json.loads(response.read(65536))
            if response.status!=200 or not value.get('ok') or not value.get('ready'):raise RuntimeError('health not ready')
            results[purpose]={'status':200,'ready':True,'version':value.get('version')}
    return results


def activate(release,install,base,control=system,health=strict_health):
    release,install,base=Path(release),Path(install),Path(base)
    manifest=validate(release,install);idle(base)
    backup=base/'backups'/('before-audit-repair-'+time.strftime('%Y%m%d-%H%M%S'));backup.mkdir(parents=True,mode=0o700)
    existing={name:checked_path(install,name).exists() for name in manifest['files']};replaced=[];stopped=False
    try:
        control('stop');stopped=True;idle(base)
        # Recheck after draining in-flight requests and before the first write.
        validate(release,install)
        for name in manifest['files']:
            if existing[name]:
                dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(checked_path(install,name),dest)
        for db in (base/'state').glob('*.sqlite3'):
            with closing(sqlite3.connect(db)) as source,closing(sqlite3.connect(backup/db.name)) as target:source.backup(target)
        for name in manifest['files']:
            dest=checked_path(install,name);dest.parent.mkdir(parents=True,exist_ok=True)
            tmp=dest.with_name(dest.name+'.release-new');shutil.copy2(checked_path(release,name),tmp);tmp.chmod(0o600);tmp.replace(dest);replaced.append(name)
        control('start');stopped=False;deadline=time.monotonic()+30
        while True:
            try:checks=health(base);break
            except (OSError,RuntimeError,ValueError,sqlite3.Error):
                if time.monotonic()>=deadline:raise
                time.sleep(.5)
        for name,digest in manifest['files'].items():
            if sha(checked_path(install,name))!=digest:raise RuntimeError('installed file changed')
        result={'backup':str(backup),'runtime_contract':CONTRACT,'installed':manifest['files'],'health':checks,'database_restore_performed':False,'config_or_resources_modified':False}
        (release/'activation.json').write_text(json.dumps(result,indent=2)+'\n');return result
    except BaseException:
        if replaced:
            control('stop');stopped=True
            for name in replaced:
                dest=checked_path(install,name)
                if existing[name]:shutil.copy2(backup/name,dest)
                else:dest.unlink(missing_ok=True)
        if stopped:control('start')
        raise


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--release',required=True,type=Path);args=parser.parse_args()
    os.umask(0o077)
    if os.geteuid()!=0 or not storage_ready():raise SystemExit('requires root maintenance and configured storage mount')
    print(json.dumps(activate(args.release,install_dir(),data_root())))

if __name__=='__main__':main()
