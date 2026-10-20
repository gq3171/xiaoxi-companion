"""Root-managed, dedicated nftables table protecting local Chromium CDP.

Does not flush the host firewall, persist credentials, or change networking on
import. Installation/service startup explicitly applies an atomic transaction.
"""
import argparse,hashlib,json,os,pwd,shutil,subprocess
from deployment_paths import read_layout
from runtime_config import allowed_cdp_ports

TABLE='xiaoxi_cdp'


def policy(ports,allowed):
    ports=sorted(set(ports));allowed=sorted(set(allowed))
    if not ports or any(type(p) is not int or not 1<=p<=65535 for p in ports):raise ValueError('invalid CDP ports')
    if not allowed or any(type(u) is not int or u<0 for u in allowed):raise ValueError('invalid CDP identities')
    body='oifname "lo" tcp dport { '+', '.join(map(str,ports))+' } meta skuid != { '+', '.join(map(str,allowed))+' } reject'
    marker='xiaoxi-cdp:'+hashlib.sha256(body.encode()).hexdigest()[:24]
    return body+' comment "'+marker+'"',marker


def configured(document=None):
    users=(document if document is not None else read_layout()).get('users',{})
    identities={0}
    for kind in ('desktop','browser'):
        try:identities.add(pwd.getpwnam(users.get(kind,'deskpet-'+kind)).pw_uid)
        except KeyError:pass # Optional services refresh the policy before startup.
    work=os.environ.get('DESKPET_EXECUTOR_USER') or users.get('computer','deskpet-work')
    try:
        uid=pwd.getpwnam(work).pw_uid
        if uid in identities:raise ValueError('task and trusted browser identities must differ')
    except KeyError:pass
    if document is None:ports=allowed_cdp_ports()
    else:
        from runtime_config import validate
        desktop=validate(document.get('options',{}))['desktop']
        ports={int(os.environ.get('DESKPET_DESKTOP_CDP_PORT',desktop['cdp_port'])),desktop['probe_cdp_port']}
    return policy(ports,identities)


def inspect(runner=subprocess.run,document=None):
    rule,marker=configured(document)
    nft=shutil.which('nft') or '/usr/sbin/nft'
    result=runner([nft,'-j','list','table','inet',TABLE],capture_output=True,text=True,timeout=5)
    if result.returncode:return False
    value=json.loads(result.stdout)
    return any(item.get('rule',{}).get('comment')==marker for item in value.get('nftables',[]))


def ensure(runner=subprocess.run):
    if os.geteuid()!=0:raise PermissionError('CDP policy requires the root service installer')
    rule,marker=configured();nft=shutil.which('nft') or '/usr/sbin/nft'
    old=runner([nft,'list','table','inet',TABLE],capture_output=True,text=True,timeout=5)
    script=('delete table inet '+TABLE+'\n' if old.returncode==0 else '')
    script+='add table inet '+TABLE+'\nadd chain inet '+TABLE+' output { type filter hook output priority -10; policy accept; }\n'
    script+='add rule inet '+TABLE+' output '+rule+'\n'
    # nft applies the complete batch atomically; an error leaves the old table.
    runner([nft,'-f','-'],input=script,capture_output=True,text=True,timeout=5,check=True)
    if not inspect(runner):raise RuntimeError('CDP policy verification failed')
    return dict(ok=True,policy=marker)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--ensure',action='store_true');args=parser.parse_args()
    print(json.dumps(ensure() if args.ensure else dict(ok=inspect())))
