#!/usr/bin/env python3
"""Xiaoxi Debian/Ubuntu brain bootstrap. Default: read-only checks. No shell eval.

See docs/INSTALL_FOR_AGENTS.md for the deployment contract and exit codes.
The installer deliberately refuses software upgrades; use reviewed release bundles.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import platform
import pwd
import re
import secrets
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[1]
BASE = Path('/mnt/nvme/deskpet')
INSTALL = Path('/opt/deskpet-computer')
UNIT = Path('/etc/systemd/system/deskpet-computer.service')
PACKAGES = ['python3', 'python3-pil', 'python3-websocket', 'build-essential',
            'openssl', 'ffmpeg', 'ca-certificates']
ALLOWED = {'MINIMAX_API_KEY', 'MINIMAX_API_HOST'}
EVENTS = []


class InstallError(Exception):
    pass


def event(step, status, **fields):
    row = dict(step=step, status=status, **fields)
    EVENTS.append(row)
    return row


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(args, timeout=300):
    """Never print subprocess output: apt/provider/config diagnostics can contain secrets."""
    try:
        p = subprocess.run([str(x) for x in args], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise InstallError('Command unavailable or timed out: ' + str(args[0])) from None
    if p.returncode:
        raise InstallError('Command failed: ' + str(args[0]) + '; exit=' + str(p.returncode))
    return p.stdout.decode(errors='replace')


def env_read(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*=[A-Za-z0-9_./:@+?%=-]*', line):
            raise InstallError('Invalid env syntax; use unquoted KEY=value, one entry per line')
        k, v = line.split('=', 1)
        if k in values:
            raise InstallError('Duplicate env field')
        values[k] = v
    return values


def private_input(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_mode & 0o077:
        raise InstallError('The input env file must be a regular private file (chmod 600)')
    values = env_read(p)
    if values.keys() - ALLOWED:
        raise InstallError('Input env may contain only MINIMAX_API_KEY and MINIMAX_API_HOST')
    if not values.get('MINIMAX_API_KEY') or values['MINIMAX_API_KEY'].startswith('replace-'):
        raise InstallError('A real MiniMax API key must be supplied in the private env file')
    host = values.get('MINIMAX_API_HOST', 'https://api.minimaxi.com')
    if host not in ('https://api.minimaxi.com', 'https://api.minimax.io'):
        raise InstallError('Use an official MiniMax HTTPS API host')
    values['MINIMAX_API_HOST'] = host
    return values


def hostname_valid(host):
    if not host or len(host) > 253:
        return False
    try:
        ipaddress.ip_address(host)
        return False  # This release uses a DNS SAN, not an IP SAN.
    except ValueError:
        pass
    return bool(re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}', host)) and not host.endswith('.example')


def source_files():
    files = list((SOURCE/'computer').rglob('*'))
    return sorted(p for p in files if p.is_file() and not p.is_symlink()
                  and '__pycache__' not in p.parts and p.suffix != '.pyc'
                  and not p.name.startswith('test_') and '.private.' not in p.name
                  and 'experimental' not in p.parts
                  and (p.suffix in ('.py','.c','.h','.js','.html','.css')
                       or p.name in ('LICENSE','LICENSE.txt','COPYRIGHT.Debian','AUTHORS','LOCAL_PATCHES.md')))


def fingerprint():
    h = hashlib.sha256()
    files = source_files()
    for directory in ('firmware/main', 'firmware/tools'):
        files.extend(p for p in (SOURCE/directory).rglob('*') if p.is_file() and not p.is_symlink() and p.suffix in ('.c','.h','.py'))
    for p in sorted(files):
        h.update(p.relative_to(SOURCE).as_posix().encode()+b'\0'+bytes.fromhex(digest(p)))
    h.update(bytes.fromhex(digest(__file__)))
    h.update(bytes.fromhex(digest(SOURCE/'firmware/assets/character/manifest.json')))
    return h.hexdigest()


def inspect():
    problems = []
    if platform.system() != 'Linux':
        problems.append('Linux is required; this check made no changes')
    if platform.machine() not in ('aarch64', 'arm64', 'x86_64', 'amd64'):
        problems.append('Supported bootstrap architectures: aarch64, x86_64')
    if not Path('/mnt/nvme').is_mount():
        problems.append('Mount the data disk at /mnt/nvme before installation; installer never formats or mounts disks')
    if Path('/mnt/nvme').exists() and shutil.disk_usage('/mnt/nvme').free < 2*1024**3:
        problems.append('At least 2 GiB free space is required on the data disk')
    if sys.version_info < (3, 11):
        problems.append('Python >=3.11 is required')
    if not shutil.which('apt-get') or not Path('/run/systemd/system').is_dir():
        problems.append('A running Debian/Ubuntu system with apt and systemd is required')
    event('preflight', 'blocked' if problems else 'passed', problems=problems,
          architecture=platform.machine(), packages=PACKAGES,
          paths=dict(software=str(INSTALL), data=str(BASE), service=str(UNIT)))
    return not problems


def atomic_private(path, text):
    """Create only. An existing configuration or key is never overwritten."""
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(text); f.flush(); os.fsync(f.fileno())


def check_existing():
    record = BASE/'config/install.json'
    if record.is_file():
        m = json.loads(record.read_text())
        if m.get('source') != fingerprint():
            raise InstallError('Different source version is already installed; use the reviewed release workflow, not bootstrap')
        for relative, expected in m['files'].items():
            p = INSTALL/relative
            if not p.is_file() or p.is_symlink() or digest(p) != expected:
                raise InstallError('Installed software changed; inspect and use the release workflow')
        event('existing_install', 'preserved', detail='Same version; configuration, tokens, databases and service are untouched')
        return True
    if INSTALL.exists() or UNIT.exists() or (BASE/'config').exists():
        raise InstallError('Unmanaged or interrupted installation found; inspect it, do not delete or overwrite it automatically')
    return False


def build(stage):
    """Public, reproducible native compilation; all build products go to the data disk."""
    stage = Path(stage); stage.mkdir(parents=True, exist_ok=True)
    include = SOURCE/'firmware/main'
    run(['cc', '-std=c17', '-D_POSIX_C_SOURCE=200809L', '-shared', '-fPIC', '-O2',
         '-I', include, '-I', SOURCE/'computer/vendor/cjson', SOURCE/'computer/brain_native.c',
         SOURCE/'computer/brain_native_util.c', SOURCE/'computer/vendor/cjson/cJSON.c', '-lm', '-o', stage/'libbrain_memory.so'])
    run(['cc', '-std=c17', '-D_POSIX_C_SOURCE=200809L', '-shared', '-fPIC', '-O2',
         '-I', include, SOURCE/'computer/home_scene_native.c', include/'pet_scene.c',
         include/'pet_scene_wire.c', include/'pet_home.c', '-lm', '-o', stage/'libhome_scene.so'])
    # build_panel_resources also updates generated source tables. Work on a scratch
    # copy, leaving both the checkout and any running release untouched.
    scratch = stage/'source'
    for folder in ('main', 'tools', 'assets/character'):
        shutil.copytree(SOURCE/'firmware'/folder, scratch/'firmware'/folder)
    resources = stage/'panel-resources'
    run([sys.executable, scratch/'firmware/tools/build_panel_resources.py', '--output', resources])
    import importlib.util
    spec = importlib.util.spec_from_file_location('xiaoxi_asset_build', SOURCE/'computer/build_home_assets.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    count = module.build(scratch, stage/'home-assets', resources)
    if count != 52 or len(list((stage/'home-assets').glob('*.png'))) != 54:
        raise InstallError('Resource build did not produce all 52 poses and two rooms')
    # Exercise both shared libraries, not just their presence on disk.
    sys.path.insert(0, str(SOURCE/'computer'))
    from brain import NativeMemory, empty_memory
    native = NativeMemory(stage/'libbrain_memory.so'); native.load(empty_memory())
    if native.dump()['next_id'] != 1:
        raise InstallError('Native memory self-test failed')
    lib = ctypes.CDLL(str(stage/'libhome_scene.so'))
    lib.home_new.restype = ctypes.c_void_p; lib.home_free.argtypes = [ctypes.c_void_p]
    ptr = lib.home_new(0)
    if not ptr: raise InstallError('Native scene self-test failed')
    lib.home_free(ptr)
    event('native_and_assets', 'passed', frames=count, rooms=2)


def tls(config, hostname):
    ca_key, ca_cert = config/'ca.key', config/'ca.pem'
    run(['openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-days', '3650',
         '-keyout', ca_key, '-out', ca_cert, '-subj', '/CN=Xiaoxi private installation CA',
         '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign'])
    run(['openssl', 'req', '-new', '-newkey', 'rsa:3072', '-nodes', '-keyout', config/'server.key',
         '-out', config/'server.csr', '-subj', '/CN='+hostname])
    ext = config/'server.ext'
    ext.write_text('subjectAltName=DNS:'+hostname+'\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n')
    run(['openssl', 'x509', '-req', '-in', config/'server.csr', '-CA', ca_cert, '-CAkey', ca_key,
         '-CAcreateserial', '-out', config/'server.pem', '-days', '365', '-sha256', '-extfile', ext])
    run(['openssl', 'verify', '-CAfile', ca_cert, '-verify_hostname', hostname, config/'server.pem'])
    for p in config.iterdir():
        if p.is_file(): p.chmod(0o600)
    event('tls', 'passed', public_ca=str(ca_cert), renewal='Server certificate expires after 365 days; renew before expiry')


def install(args):
    if os.geteuid() != 0: raise InstallError('--apply requires root for apt, /opt and systemd')
    if not inspect(): raise InstallError('Preflight blocked; fix reported requirements first')
    if check_existing(): return doctor()
    if not hostname_valid(args.hostname):
        raise InstallError('--hostname must be your actual DNS hostname (not an IP, URL or example domain)')
    if not args.env_file: raise InstallError('--env-file is required on first installation')
    values = private_input(args.env_file)
    # Refuse an occupied port before changing the host.
    with socket.socket() as sock:
        try: sock.bind(('0.0.0.0', 8791))
        except OSError: raise InstallError('TCP 8791 is already occupied') from None
    run(['apt-get', 'update'], 600)
    run(['apt-get', 'install', '-y', '--no-install-recommends', *PACKAGES], 900)
    event('packages', 'passed')
    os.umask(0o077)
    BASE.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ('state', 'data', 'logs', 'cache', 'tmp', 'work', 'backups', 'install-staging'):
        (BASE/name).mkdir(mode=0o700, exist_ok=True)
    # Only task subprocesses drop to this account; model credentials stay with
    # the root-owned broker. It has NO passwordless sudo by default.
    try:
        account = pwd.getpwnam('deskpet-work')
        if account.pw_uid == 0:
            raise InstallError('The task account must not have root UID')
        if account.pw_dir != str(BASE/'work'):
            raise InstallError('Existing deskpet-work user has a different home; inspect manually')
    except KeyError:
        run(['useradd', '--system', '--home-dir', BASE/'work', '--shell', '/usr/sbin/nologin', 'deskpet-work'])
        account = pwd.getpwnam('deskpet-work')
    BASE.chmod(0o711)
    os.chown(BASE/'work', account.pw_uid, account.pw_gid); (BASE/'work').chmod(0o700)
    # Provide only a private per-task-user temp/cache, not access to broker data.
    for name in ('cache', 'tmp'):
        p = BASE/'work'/('.'+name); p.mkdir(mode=0o700, exist_ok=True); os.chown(p, account.pw_uid, account.pw_gid)
    with tempfile.TemporaryDirectory(prefix='bootstrap-', dir=BASE/'install-staging') as temp:
        stage = Path(temp); build(stage)
        software = stage/'software'; software.mkdir()
        for p in source_files():
            dest = software/p.relative_to(SOURCE/'computer'); dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, dest)
        for name in ('libbrain_memory.so', 'libhome_scene.so'): shutil.copy2(stage/name, software/name)
        # Include resources only after their integrity and native tests passed.
        shutil.copytree(stage/'panel-resources', BASE/'data/panel-resources')
        shutil.copytree(stage/'home-assets', BASE/'data/home-web')
        shutil.copytree(software, INSTALL)
    config = BASE/'config'; config.mkdir(mode=0o700)
    atomic_private(config/'service.env', '\n'.join(k+'='+v for k,v in {
        'DESKPET_COMPUTER_TOKEN':secrets.token_urlsafe(32), **values,
        'DESKPET_PUBLIC_ORIGIN':'https://'+args.hostname+':8791'}.items())+'\n')
    atomic_private(config/'brain.env', 'DESKPET_BRAIN_TOKEN='+secrets.token_urlsafe(32)+'\n')
    tls(config, args.hostname)
    shutil.copy2(SOURCE/'computer/deskpet-computer.service', UNIT); UNIT.chmod(0o644)
    files = {p.relative_to(INSTALL).as_posix():digest(p) for p in INSTALL.rglob('*') if p.is_file()}
    atomic_private(config/'install.json', json.dumps(dict(format=1, source=fingerprint(), files=files), indent=2)+'\n')
    run(['systemctl', 'daemon-reload']); run(['systemctl', 'enable', '--now', 'deskpet-computer.service'])
    event('service', 'started', detail='No firewall/router changes were made; desktop is a separate optional install')
    for _ in range(15):
        try: return doctor()
        except (InstallError, OSError): time.sleep(1)
    raise InstallError('Service failed its TLS health probe; inspect it without rerunning or deleting state')


def doctor():
    config = BASE/'config'
    values = env_read(config/'service.env')
    origin = values.get('DESKPET_PUBLIC_ORIGIN', '')
    from urllib.parse import urlsplit
    url = urlsplit(origin)
    if url.scheme != 'https' or not url.hostname or url.port != 8791:
        raise InstallError('Installed public origin is missing or invalid')
    context = ssl.create_default_context(cafile=str(config/'ca.pem'))
    def request(path, payload=None, token=None):
        with socket.create_connection(('127.0.0.1',8791),timeout=8) as sock:
            with context.wrap_socket(sock,server_hostname=url.hostname) as stream:
                body=json.dumps(payload).encode() if payload is not None else b''
                headers=('POST' if payload is not None else 'GET')+' '+path+' HTTP/1.1\r\nHost: '+url.netloc+'\r\nConnection: close\r\n'
                if token: headers+='Authorization: Bearer '+token+'\r\n'
                headers+='Content-Type: application/json\r\nContent-Length: '+str(len(body))+'\r\n\r\n'
                stream.sendall(headers.encode()+body)
                response=http.client.HTTPResponse(stream); response.begin(); data=response.read(262144)
                if response.status!=200: raise InstallError('Health endpoint failed: '+path+'; status='+str(response.status))
                return data
    health=json.loads(request('/v1/computer/health',{},values['DESKPET_COMPUTER_TOKEN']))
    if not health.get('ok') or not health.get('ready'): raise InstallError('Computer health is not ready; verify private model configuration')
    request('/home/')
    paired=False
    dbpath=BASE/'state/brain.sqlite3'
    if dbpath.is_file():
        with sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True) as db:
            paired=db.execute('SELECT 1 FROM device WHERE singleton=1').fetchone() is not None
    if paired:
        with sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row; row=dict(db.execute('SELECT device,boot,session,generation FROM device WHERE singleton=1').fetchone())
        brain=json.loads(request('/v1/brain/health',row,env_read(config/'brain.env')['DESKPET_BRAIN_TOKEN']))
        if not brain.get('ok') or not brain.get('ready'): raise InstallError('Paired brain health is not ready')
    event('health', 'passed', tls_verified=True, model_network_tested=False, board_paired=paired,
          public_url=origin+'/home/', pending=[] if paired else ['Configure and connect the ESP32 body; web chat requires its identity import'])
    # Local health verifies configuration/persistence/transport, NOT paid cloud calls.
    return 0 if paired else 2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--check',action='store_true',help='Read-only requirements and installation plan (default)')
    mode.add_argument('--apply',action='store_true',help='Install a new brain; preserve identical installations, reject unreviewed upgrades')
    mode.add_argument('--doctor',action='store_true',help='Probe an installed service using verified TLS; no model calls')
    parser.add_argument('--hostname',help='Actual DNS name used by the browser and ESP32; required on first apply')
    parser.add_argument('--env-file',type=Path,help='Private chmod-600 MiniMax env input; never printed')
    parser.add_argument('--json',action='store_true',help='Emit a single machine-readable JSON report with stable step names')
    args=parser.parse_args(); code=0
    try:
        if args.apply: code=install(args)
        elif args.doctor: code=doctor()
        else:
            code=0 if inspect() else 1
            if args.env_file: private_input(args.env_file);event('private_input','passed')
            if args.hostname and not hostname_valid(args.hostname): raise InstallError('Invalid actual DNS hostname')
            event('plan','read_only',command='sudo python3 scripts/install.py --apply --hostname YOUR_DNS_NAME --env-file /private/provider.env --json',
                  optional_desktop='See docs/DESKTOP.md; not installed by this brain bootstrap')
    except (InstallError, OSError, ValueError, KeyError, sqlite3.Error) as err:
        # Avoid printing raw exception strings from external services/config parsers.
        event('failure','blocked',reason=str(err) if isinstance(err,InstallError) else type(err).__name__)
        code=1
    result=dict(schema=1,ok=code==0,exit_code=code,events=EVENTS)
    if args.json: print(json.dumps(result,ensure_ascii=False))
    else:
        for row in EVENTS: print(json.dumps(row,ensure_ascii=False))
    return code

if __name__=='__main__': sys.exit(main())
