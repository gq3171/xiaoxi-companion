"""Non-secret installation layout shared by the broker and its child services.

New installs publish a root-owned JSON locator; credentials stay in private env
files. Legacy paths are read-only fallbacks for installations predating it.
"""
import json
import os
from pathlib import Path
import re

DEFAULT_LOCATOR = Path('/etc/xiaoxi/install.json')
LEGACY_ROOT = Path('/mnt/nvme/deskpet')


def validate_layout(value):
    if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1:
        raise ValueError('invalid installation layout; preserve it for inspection')
    if value.keys()-{'schema','data_root','storage_mount','install_dir','desktop_root','browser_root',
                     'desktop_install_dir','browser_install_dir','port','users','options','public_origin'}:
        raise ValueError('unknown installation field; credentials belong in private env files')
    for name in ('data_root', 'storage_mount', 'install_dir', 'desktop_root', 'browser_root',
                 'desktop_install_dir', 'browser_install_dir'):
        if name not in value and name.endswith('_install_dir'):
            continue
        path = value.get(name)
        if not isinstance(path, str) or not Path(path).is_absolute() or any(ord(c)<32 for c in path):
            raise ValueError('invalid installation path')
    if type(value.get('port')) is not int or not 1 <= value['port'] <= 65535:
        raise ValueError('invalid installation port')
    users = value.get('users', {})
    if not isinstance(users, dict) or users.keys()-{'computer', 'desktop', 'browser'}:
        raise ValueError('invalid service accounts')
    for user in users.values():
        if not isinstance(user, str) or user=='root' or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', user):
            raise ValueError('invalid service account')
    return value


def read_layout():
    locator = Path(os.environ.get('DESKPET_INSTALL_CONFIG', DEFAULT_LOCATOR))
    if locator.exists():
        value = json.loads(locator.read_text())
        return validate_layout(value)
    legacy = (LEGACY_ROOT/'config/service.env').is_file()
    root = LEGACY_ROOT if legacy else Path('/var/lib/xiaoxi')
    return dict(schema=1, data_root=str(root), storage_mount='/mnt/nvme' if legacy else '/',
                install_dir='/opt/deskpet-computer',
                desktop_root='/mnt/nvme/deskpet-desktop' if legacy else str(root/'desktop'),
                browser_root='/mnt/nvme/deskpet-browser' if legacy else str(root/'browser'),
                port=8791)


def data_root():
    return Path(os.environ.get('DESKPET_DATA_ROOT', read_layout()['data_root']))


def desktop_root():
    return Path(os.environ.get('DESKPET_DESKTOP_ROOT', read_layout()['desktop_root']))


def browser_root():
    return Path(os.environ.get('DESKPET_BROWSER_ROOT', read_layout()['browser_root']))


def install_dir():
    return Path(read_layout()['install_dir'])


def storage_ready():
    return os.path.ismount(read_layout()['storage_mount'])


def service_quote(value):
    """Quote one systemd token; escape specifiers independently of shell syntax."""
    value = str(value)
    if any(c in value for c in ('\0', '\r', '\n')):
        raise ValueError('control character in installation path')
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'


def service_path(value):
    """Whole-line path directives do not use systemd's token quote parser."""
    value=str(value)
    if any(ord(c)<32 for c in value):
        raise ValueError('control character in service path')
    return value.replace('%','%%')


def render_service(kind, config, locator=DEFAULT_LOCATOR):
    validate_layout(config)
    if kind not in ('computer','desktop','browser'):
        raise ValueError('unknown service')
    root = Path(config['data_root'] if kind=='computer' else config[kind+'_root'])
    software = Path(config['install_dir']) if kind=='computer' else Path(config.get(kind+'_install_dir',str(Path(config['install_dir']).parent/('deskpet-'+kind))))
    q=service_quote
    lines=['[Unit]','Description=Xiaoxi '+kind+' service','After=network-online.target',
           'Wants=network-online.target','RequiresMountsFor='+q(config['storage_mount']),
           'ConditionPathIsMountPoint='+service_path(config['storage_mount']),'','[Service]','Type=simple']
    if kind!='computer':
        lines += ['User='+config.get('users',{}).get(kind,'deskpet-'+kind),'Group='+config.get('users',{}).get(kind,'deskpet-'+kind)]
        if kind=='desktop':lines+=['SupplementaryGroups=render video']
    lines += ['WorkingDirectory='+service_path(root/'work' if kind=='computer' else root),
              'Environment='+q('DESKPET_INSTALL_CONFIG='+str(locator)),
              'Environment='+q('HOME='+str(root)),
              'Environment='+q('XDG_CACHE_HOME='+str(root/'cache')),
              'Environment='+q('TMPDIR='+str(root/'tmp'))]
    if kind=='computer':
        lines += ['EnvironmentFile='+q(root/'config/service.env'),
                  'EnvironmentFile='+q(root/'config/brain.env'),
                  'Environment='+q('DESKPET_EXECUTOR_USER='+config.get('users',{}).get('computer','deskpet-work')),
                  'Environment='+q('DESKPET_WORK_ROOT='+str(root/'work')),
                  'Environment='+q('XDG_DATA_HOME='+str(root/'data')),
                  'Environment='+q('XDG_STATE_HOME='+str(root/'state')),
                  'Environment='+q('PIP_CACHE_DIR='+str(root/'cache/pip')),
                  'Environment='+q('UV_CACHE_DIR='+str(root/'cache/uv'))]
        argv=['/usr/bin/python3',software/'agent.py','--host','0.0.0.0','--port',str(config['port']),
              '--data',root/'state/jobs.sqlite3','--tls-cert',root/'config/server.pem','--tls-key',root/'config/server.key']
    else:
        argv=['/usr/bin/python3',software/(kind+'_daemon.py')]
    lines += ['ExecStartPre=/usr/bin/mountpoint -q '+q(config['storage_mount']),
              'ExecStart='+' '.join(q(s) for s in argv),
              'StandardOutput=append:'+service_path(root/'logs/service.log' if kind=='computer' else root/(kind+'.log')),
              'StandardError=append:'+service_path(root/'logs/service.log' if kind=='computer' else root/(kind+'.log')),
              'UMask=0077','KillMode=control-group','TimeoutStopSec=15']
    if kind=='computer':lines+=['Restart=on-failure','RestartSec=5','MemoryHigh=768M','MemoryMax=1G','TasksMax=256','','[Install]','WantedBy=multi-user.target']
    else:lines+=['PrivateTmp=yes','Restart=no','MemoryMax=1200M','TasksMax=192']
    return '\n'.join(lines)+'\n'


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Render a unit from the saved layout; stdout only, no service changes.')
    parser.add_argument('--service',choices=('computer','desktop','browser'),required=True)
    args=parser.parse_args()
    print(render_service(args.service,read_layout(),Path(os.environ.get('DESKPET_INSTALL_CONFIG',DEFAULT_LOCATOR))),end='')
