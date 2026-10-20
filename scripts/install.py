#!/usr/bin/env python3
"""Xiaoxi Debian/Ubuntu brain bootstrap. Default: read-only checks. No shell eval.

See docs/INSTALL_FOR_AGENTS.md for the deployment contract and exit codes.
The installer deliberately refuses software upgrades; use reviewed release bundles.
"""
from __future__ import annotations
import argparse
import getpass
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
sys.path.insert(0, str(SOURCE/'computer'))
import deployment_paths as layout
import runtime_config
import backend_config
LOCATION = layout.DEFAULT_LOCATOR
BASE = layout.LEGACY_ROOT if (layout.LEGACY_ROOT/'config/service.env').exists() else Path('/var/lib/xiaoxi')
CURRENT_LAYOUT = None
INSTALL = Path('/opt/deskpet-computer')
UNIT = Path('/etc/systemd/system/deskpet-computer.service')
PACKAGES = ['python3', 'python3-pil', 'python3-websocket', 'build-essential',
            'openssl', 'ffmpeg', 'ca-certificates', 'acl']
ALLOWED = {'MINIMAX_API_KEY', 'MINIMAX_API_HOST', 'MINIMAX_MODEL', 'LLM_PROVIDER', 'LLM_API_TYPE', 'LLM_BASE_URL', 'LLM_MODEL', 'LLM_API_KEY', 'TTS_VOICE'}
ALLOWED |= {kind+'_'+field for kind in ('ASR','TTS','SEARCH') for field in ('PROVIDER','BASE_URL','MODEL','API_KEY')}
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
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*=[A-Za-z0-9_./:@+?%\[\]=-]*', line):
            raise InstallError('Invalid env syntax; use unquoted KEY=value, one entry per line')
        k, v = line.split('=', 1)
        if k in values:
            raise InstallError('Duplicate env field')
        values[k] = v
    return values


def private_input(path, model=None, provider=None, api_base=None, api_type=None):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_mode & 0o077:
        raise InstallError('The input env file must be a regular private file (chmod 600)')
    values = env_read(p)
    if values.keys() - ALLOWED:
        raise InstallError('Unsupported provider env field; use the documented LLM/ASR/TTS/SEARCH fields')
    overrides={'LLM_PROVIDER':provider,'LLM_BASE_URL':api_base,'LLM_API_TYPE':api_type}
    for name,value in overrides.items():
        if value is not None:
            if values.get(name) and values[name]!=value:raise InstallError('CLI provider setting differs from the private env file')
            values[name]=value
    if model:
        name='LLM_MODEL' if any(k.startswith('LLM_') for k in values) else 'MINIMAX_MODEL'
        if values.get(name) and values[name]!=model:raise InstallError('CLI model differs from the private env file')
        values[name]=model
    return provider_values(values)


def provider_values(values):
    if not values.get('LLM_MODEL') and not values.get('MINIMAX_MODEL'):raise InstallError('Provide your actual backend model with LLM_MODEL or MINIMAX_MODEL')
    try:
        options=(CURRENT_LAYOUT or {}).get('options',runtime_config.DEFAULTS)['llm']
        config=backend_config.text_config(values,options)
        if not config.ready:raise ValueError('Provide the selected backend model and its own API key (local HTTP may omit a key)')
        if config.key.startswith('replace-'):raise ValueError('Replace the placeholder backend API key')
        for kind in ('ASR','TTS','SEARCH'):
            service=backend_config.auxiliary(kind,config,values)
            if service['provider']!='none' and not service['key'] and not service['base_url'].startswith('http://'):
                raise ValueError('An enabled auxiliary service needs its own API key')
            if values.get(kind+'_MODEL') and not backend_config.model_valid(values[kind+'_MODEL']):raise ValueError('invalid auxiliary model name')
        if values.get('TTS_VOICE') and not runtime_config.voice_valid(values['TTS_VOICE']):raise ValueError('invalid TTS voice ID')
    except ValueError as error:raise InstallError(str(error)) from None
    # Keep existing private env names readable; new installations use generic ones.
    if any(k.startswith('LLM_') for k in values):
        values.update(LLM_PROVIDER=config.provider,LLM_API_TYPE=config.api_type,LLM_BASE_URL=config.base_url,LLM_MODEL=config.model,LLM_API_KEY=config.key)
    else:
        if not values.get('MINIMAX_MODEL'):raise InstallError('Provide your backend model name with LLM_MODEL or MINIMAX_MODEL')
        values['MINIMAX_API_HOST']=config.base_url
    return values


def private_args(args):
    return private_input(args.env_file,getattr(args,'model',None),getattr(args,'provider',None),getattr(args,'api_base',None),getattr(args,'api_type',None))


def is_ip(host):
    try:ipaddress.ip_address(host);return True
    except ValueError:return False


def hostname_valid(host):
    if not host or len(host) > 253:
        return False
    try:
        ipaddress.ip_address(host)
        return True  # LAN-only installations can use an IP SAN.
    except ValueError:
        pass
    return bool(re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}', host)) and not host.endswith('.example')


def existing_parent(path):
    path=Path(path)
    while not path.exists() and path.parent!=path:path=path.parent
    if not path.is_dir():raise InstallError('Data path parent must be a directory')
    return path


def mounted_parent(path):
    path=existing_parent(path)
    while not path.is_mount() and path.parent!=path:path=path.parent
    return path


def absolute_path(value):
    path=Path(value).expanduser()
    if not path.is_absolute() or any(ord(c)<32 for c in str(path)):
        raise InstallError('Use an absolute directory without control characters')
    return path.resolve()


def configure(args):
    global BASE, INSTALL, LOCATION, CURRENT_LAYOUT
    LOCATION=absolute_path(getattr(args,'config_file',None) or LOCATION)
    saved=layout.validate_layout(json.loads(LOCATION.read_text())) if LOCATION.exists() else None
    root=absolute_path(getattr(args,'data_dir',None) or (saved['data_root'] if saved else BASE))
    if root!=Path('/') and root.is_mount() and not saved:
        root=root/'xiaoxi'
    software=absolute_path(getattr(args,'install_dir',None) or (saved['install_dir'] if saved else INSTALL))
    if root==Path('/') or root==software or root.is_relative_to(software) or software.is_relative_to(root):
        raise InstallError('Keep data and application software in separate directories')
    if saved and (root!=Path(saved['data_root']) or software!=Path(saved['install_dir'])):
        raise InstallError('An installation already uses a different path; moving live data requires a separate migration')
    mount=absolute_path(getattr(args,'require_mount',None) or (saved['storage_mount'] if saved else mounted_parent(root)))
    if saved and mount!=Path(saved['storage_mount']):raise InstallError('Changing the registered mount requires a separate migration')
    if not root.is_relative_to(mount):raise InstallError('Data directory must be inside its required mount')
    requested_port=getattr(args,'port',None)
    port=requested_port if requested_port is not None else (saved.get('port',8791) if saved else 8791)
    if type(port) is not int or not 1<=port<=65535:raise InstallError('Port must be in 1..65535')
    if saved and port!=saved.get('port',8791):raise InstallError('Changing an existing service port requires a separate update')
    legacy=not saved and root==layout.LEGACY_ROOT and (root/'config/service.env').exists()
    CURRENT_LAYOUT=saved or dict(schema=1,data_root=str(root),storage_mount=str(mount),install_dir=str(software),
        desktop_root='/mnt/nvme/deskpet-desktop' if legacy else str(root/'desktop'),
        browser_root='/mnt/nvme/deskpet-browser' if legacy else str(root/'browser'),port=port)
    options=getattr(args,'settings_file',None)
    if options:
        requested_options=runtime_config.validate(json.loads(Path(options).read_text()))
        if saved and requested_options!=runtime_config.validate(saved.get('options',{})):
            raise InstallError('Runtime settings updates are separate from first installation')
        CURRENT_LAYOUT['options']=requested_options
    else:CURRENT_LAYOUT['options']=runtime_config.validate(CURRENT_LAYOUT.get('options',{}))
    CURRENT_LAYOUT.setdefault('users',{'computer':'deskpet-work','desktop':'deskpet-desktop','browser':'deskpet-browser'})
    task_user=getattr(args,'task_user',None)
    if task_user:
        if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}',task_user) or task_user=='root':raise InstallError('Use a non-root POSIX task username')
        if saved and task_user!=saved['users']['computer']:raise InstallError('Task account migration must be handled separately')
        CURRENT_LAYOUT['users']['computer']=task_user
    CURRENT_LAYOUT.setdefault('desktop_install_dir',str(software.parent/'deskpet-desktop'))
    CURRENT_LAYOUT.setdefault('browser_install_dir',str(software.parent/'deskpet-browser'))
    BASE,INSTALL=root,software


def public_origin(host,port):
    return 'https://'+('['+host+']' if ':' in host else host)+':'+str(port)


def setup_values(args):
    if not sys.stdin.isatty():raise InstallError('--setup needs a terminal; agents should use --data-dir, --hostname and --env-file instead')
    if os.geteuid()!=0:raise InstallError('--setup requires sudo for system installation')
    print('小溪安装向导：确认数据目录、访问地址、对话服务与按需语音服务。密钥隐藏输入。',file=sys.stderr)
    def ask(title,default=''):
        print(title+((' ['+str(default)+']') if default else '')+': ',file=sys.stderr,end='',flush=True)
        value=input().strip()
        return value or str(default)
    if not LOCATION.exists():
        args.data_dir=ask('小溪专用数据目录（填写数据盘挂载点时会创建 xiaoxi 子目录）',args.data_dir or BASE)
        args.hostname=ask('浏览器/板子访问的域名或本机局域网 IP',args.hostname or '')
    configure(args)
    if not inspect():raise InstallError('Fix the preflight requirements before entering a credential')
    if (BASE/'config/install.json').exists():return None
    if not hostname_valid(args.hostname):raise InstallError('Provide a valid DNS name or IP address')
    if args.env_file:return private_args(args)
    provider=ask('对话服务商（'+', '.join(backend_config.PRESETS)+'）',getattr(args,'provider',None) or 'minimax')
    if provider not in backend_config.PRESETS:raise InstallError('Unknown provider; select custom for another compatible service')
    preset=backend_config.PRESETS[provider]
    base=ask('API Base URL（确认套餐/地域，勿填聊天接口的完整路径）',getattr(args,'api_base',None) or preset['base_url'])
    protocol=getattr(args,'api_type',None) or preset['api_type']
    if provider=='custom':protocol=ask('接口类型（openai-chat / openai-responses / anthropic）',protocol)
    name=ask('你实际开通/安装的后端模型名称',args.model or preset['suggested_model'])
    key=getpass.getpass('对话 API Key（隐藏输入；无鉴权的本地服务可留空）: ',stream=sys.stderr)
    values=dict(LLM_PROVIDER=provider,LLM_API_TYPE=protocol,LLM_BASE_URL=base,LLM_MODEL=name,LLM_API_KEY=key)
    if provider!='minimax':
        voice=ask('语音服务（none=稍后配置 / minimax / openai-compatible）','none')
        values.update(ASR_PROVIDER=voice,TTS_PROVIDER=voice,SEARCH_PROVIDER='none')
        if voice!='none':
            default_base='https://api.minimaxi.com' if voice=='minimax' else 'https://api.openai.com/v1'
            audio_base=ask('语音 API Base URL',default_base)
            audio_key=getpass.getpass('语音 API Key（隐藏输入；地址相同可留空复用对话 Key）: ',stream=sys.stderr)
            if not audio_key and backend_config.base_url(audio_base)==backend_config.base_url(base):audio_key=key
            speech=runtime_config.DEFAULTS['speech'];prefix='openai_' if voice=='openai-compatible' else ''
            asr=ask('语音识别模型名称',speech[prefix+'asr_model']);tts=ask('语音合成模型名称',speech[prefix+'tts_model'])
            values.update(ASR_BASE_URL=audio_base,TTS_BASE_URL=audio_base,ASR_API_KEY=audio_key,TTS_API_KEY=audio_key,ASR_MODEL=asr,TTS_MODEL=tts)
            values['TTS_VOICE']=ask('音色 ID',speech['openai_voice' if prefix else 'default_voice'])
    return provider_values(values)


def source_files():
    files = list((SOURCE/'computer').rglob('*'))
    return sorted(p for p in files if p.is_file() and not p.is_symlink()
                  and '__pycache__' not in p.parts and p.suffix != '.pyc'
                  and not p.name.startswith('test_') and '.private.' not in p.name
                  and 'experimental' not in p.parts
                  and (p.suffix in ('.py','.c','.h','.js','.html','.css')
                       or p.name in ('runtime.defaults.json','providers.defaults.json','LICENSE','LICENSE.txt','COPYRIGHT.Debian','AUTHORS','LOCAL_PATCHES.md')))


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
    mount=Path(CURRENT_LAYOUT['storage_mount']) if CURRENT_LAYOUT else mounted_parent(BASE)
    if not mount.is_mount():
        problems.append('The configured data filesystem is not mounted; no disk formatting or fallback writes are performed')
    if shutil.disk_usage(existing_parent(BASE)).free < 2*1024**3:
        problems.append('At least 2 GiB free space is required on the data disk')
    if sys.version_info < (3, 11):
        problems.append('Python >=3.11 is required')
    if not shutil.which('apt-get') or not Path('/run/systemd/system').is_dir():
        problems.append('A running Debian/Ubuntu system with apt and systemd is required')
    event('preflight', 'blocked' if problems else 'passed', problems=problems,
          architecture=platform.machine(), packages=PACKAGES,
          paths=dict(software=str(INSTALL), data=str(BASE), storage_mount=str(mount), service=str(UNIT)),
          separate_storage=mount!=Path('/'))
    return not problems


def atomic_private(path, text):
    """Create only. An existing configuration or key is never overwritten."""
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(text); f.flush(); os.fsync(f.fileno())


def public_parent(path):
    """Create readable software/locator ancestors without changing existing ones."""
    missing=[];current=Path(path)
    while not current.exists():missing.append(current);current=current.parent
    for parent in reversed(missing):parent.mkdir(mode=0o755);parent.chmod(0o755)


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
    if INSTALL.exists() or UNIT.exists() or (BASE.exists() and any(BASE.iterdir())):
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
    san=('IP:' if is_ip(hostname) else 'DNS:')+hostname
    run(['openssl', 'req', '-new', '-newkey', 'rsa:3072', '-nodes', '-keyout', config/'server.key',
         '-out', config/'server.csr', '-subj', '/CN='+hostname])
    ext = config/'server.ext'
    ext.write_text('subjectAltName='+san+'\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n')
    run(['openssl', 'x509', '-req', '-in', config/'server.csr', '-CA', ca_cert, '-CAkey', ca_key,
         '-CAcreateserial', '-out', config/'server.pem', '-days', '365', '-sha256', '-extfile', ext])
    run(['openssl', 'verify', '-CAfile', ca_cert, '-verify_ip' if is_ip(hostname) else '-verify_hostname', hostname, config/'server.pem'])
    for p in config.iterdir():
        if p.is_file(): p.chmod(0o600)
    event('tls', 'passed', public_ca=str(ca_cert), renewal='Server certificate expires after 365 days; renew before expiry')


def install(args):
    if os.geteuid() != 0: raise InstallError('--apply requires root for apt, /opt and systemd')
    if not inspect(): raise InstallError('Preflight blocked; fix reported requirements first')
    if check_existing(): return doctor()
    if not hostname_valid(args.hostname):
        raise InstallError('--hostname must be your DNS hostname or LAN IP (not a URL or placeholder)')
    values=getattr(args,'provider_values',None)
    if values is None:
        if not args.env_file:raise InstallError('Use --setup for hidden key input, or provide --env-file and a model name')
        values=private_args(args)
    if LOCATION.exists():raise InstallError('A registered installation already exists; inspect it rather than overwriting')
    for directory in (BASE,INSTALL,UNIT.parent,LOCATION.parent):
        if directory.exists() and not directory.is_dir():raise InstallError('Installation path conflicts with an existing file')
    # Refuse an occupied port before changing the host.
    with socket.socket() as sock:
        try: sock.bind(('0.0.0.0', CURRENT_LAYOUT['port']))
        except OSError: raise InstallError('The configured TCP port is already occupied') from None
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
        account = pwd.getpwnam(CURRENT_LAYOUT['users']['computer'])
        if account.pw_uid == 0:
            raise InstallError('The task account must not have root UID')
        if account.pw_dir != str(BASE/'work'):
            raise InstallError('Existing deskpet-work user has a different home; inspect manually')
    except KeyError:
        run(['useradd', '--system', '--home-dir', BASE/'work', '--shell', '/usr/sbin/nologin', CURRENT_LAYOUT['users']['computer']])
        account = pwd.getpwnam(CURRENT_LAYOUT['users']['computer'])
    # Traverse only, never list/read: preserve permissions on a private parent
    # such as /media/owner while allowing this named task account to reach work.
    for parent in reversed(BASE.parents):
        if not parent.stat().st_mode & 0o001:
            run(['setfacl','-m','u:'+str(account.pw_uid)+':--x',parent])
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
        public_parent(INSTALL.parent)
        shutil.copytree(software, INSTALL)
    config = BASE/'config'; config.mkdir(mode=0o700)
    CURRENT_LAYOUT['public_origin']=public_origin(args.hostname,CURRENT_LAYOUT['port'])
    atomic_private(config/'service.env', '\n'.join(k+'='+v for k,v in {
        'DESKPET_COMPUTER_TOKEN':secrets.token_urlsafe(32), **values,
        'DESKPET_PUBLIC_ORIGIN':public_origin(args.hostname,CURRENT_LAYOUT['port'])}.items())+'\n')
    atomic_private(config/'brain.env', 'DESKPET_BRAIN_TOKEN='+secrets.token_urlsafe(32)+'\n')
    tls(config, args.hostname)
    public_parent(LOCATION.parent)
    atomic_private(LOCATION,json.dumps(CURRENT_LAYOUT,ensure_ascii=False,indent=2)+'\n'); LOCATION.chmod(0o644)
    generated=config/'systemd';generated.mkdir(mode=0o700)
    for kind in ('computer','desktop','browser'):
        (generated/('deskpet-'+kind+'.service')).write_text(layout.render_service(kind,CURRENT_LAYOUT,LOCATION))
    UNIT.write_text((generated/'deskpet-computer.service').read_text()); UNIT.chmod(0o644)
    files = {p.relative_to(INSTALL).as_posix():digest(p) for p in INSTALL.rglob('*') if p.is_file()}
    atomic_private(config/'install.json', json.dumps(dict(format=2, source=fingerprint(), files=files, layout=CURRENT_LAYOUT), indent=2)+'\n')
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
    if url.scheme != 'https' or not url.hostname or (url.port or 443) != (CURRENT_LAYOUT or layout.read_layout())['port']:
        raise InstallError('Installed public origin is missing or invalid')
    context = ssl.create_default_context(cafile=str(config/'ca.pem'))
    def request(path, payload=None, token=None):
        with socket.create_connection(('127.0.0.1',(CURRENT_LAYOUT or layout.read_layout())['port']),timeout=8) as sock:
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
    mode.add_argument('--setup',action='store_true',help='Interactive first-install wizard; key input is hidden')
    mode.add_argument('--apply',action='store_true',help='Install a new brain; preserve identical installations, reject unreviewed upgrades')
    mode.add_argument('--doctor',action='store_true',help='Probe an installed service using verified TLS; no model calls')
    parser.add_argument('--hostname',help='DNS name or LAN IP used by the browser and ESP32')
    parser.add_argument('--data-dir',type=Path,help='Your chosen data directory on any mounted filesystem')
    parser.add_argument('--require-mount',type=Path,help='Optional expected mount point; refuse writes while it is absent')
    parser.add_argument('--install-dir',type=Path,help='Optional application software directory')
    parser.add_argument('--config-file',type=Path,help='Optional non-secret installation locator (default /etc/xiaoxi/install.json)')
    parser.add_argument('--port',type=int,help='HTTPS port (default 8791 on first install)')
    parser.add_argument('--settings-file',type=Path,help='Optional JSON of non-secret runtime overrides; unknown fields are rejected')
    parser.add_argument('--task-user',help='Optional dedicated non-root task account name')
    parser.add_argument('--provider',choices=tuple(backend_config.PRESETS),help='Backend provider preset; custom allows another compatible service')
    parser.add_argument('--api-base',help='Operator-supplied provider API base URL')
    parser.add_argument('--api-type',choices=backend_config.API_TYPES,help='API protocol, independently of model name')
    parser.add_argument('--model',help='Actual backend model name; may also use LLM_MODEL in private env')
    parser.add_argument('--env-file',type=Path,help='Private chmod-600 provider env input; never printed')
    parser.add_argument('--json',action='store_true',help='Emit a single machine-readable JSON report with stable step names')
    args=parser.parse_args(); code=0
    EVENTS.clear()
    try:
        configure(args)
        if args.setup:
            args.provider_values=setup_values(args);code=install(args)
        if args.apply: code=install(args)
        elif args.doctor: code=doctor()
        elif not args.setup:
            code=0 if inspect() else 1
            if args.env_file: private_args(args);event('private_input','passed')
            if args.hostname and not hostname_valid(args.hostname): raise InstallError('Invalid actual DNS hostname')
            event('plan','read_only',command='sudo ./install.sh --setup', noninteractive='sudo ./install.sh --apply --data-dir YOUR_DATA_DIRECTORY --hostname YOUR_DNS_OR_IP --env-file /private/provider.env --json',
                  optional_desktop='See docs/DESKTOP.md; not installed by this brain bootstrap')
    except KeyboardInterrupt:
        event('failure','cancelled',reason='Cancelled by operator; inspect completed steps before retrying');code=130
    except (InstallError, OSError, ValueError, TypeError, KeyError, sqlite3.Error) as err:
        # Avoid printing raw exception strings from external services/config parsers.
        event('failure','blocked',reason=str(err) if isinstance(err,InstallError) else type(err).__name__)
        code=1
    result=dict(schema=1,ok=code==0,exit_code=code,events=EVENTS)
    if args.json: print(json.dumps(result,ensure_ascii=False))
    else:
        for row in EVENTS: print(json.dumps(row,ensure_ascii=False))
    return code

if __name__=='__main__': sys.exit(main())
