"""Own a whole command scope, including double-forked and setsid children.

Production uses a transient systemd cgroup, owned by the broker, running only as
its configured ordinary account. Non-root Linux fixtures use a child subreaper.
The macOS development fallback drains the process group; Linux is the supported
work executor. Long-running services need a separately managed service capability.
"""
import ctypes,json,os,re,signal,subprocess,sys,time,uuid
from pathlib import Path

def scope_limits(root=Path('/sys/fs/cgroup'),membership=Path('/proc/self/cgroup')):
    # Moving work into its own service must not escape the broker's memory and
    # process ceilings. Preserve the tightest ancestor limit, with bounded
    # defaults for a development launcher outside the installed service.
    limits={'memory.max':1024**3,'pids.max':256}
    try:
        entry=next(line[3:] for line in membership.read_text().splitlines() if line.startswith('0::'))
        if '..' in Path(entry).parts:raise ValueError('invalid cgroup path')
        node=root/entry.lstrip('/')
        while node==root or node.is_relative_to(root):
            for key in limits:
                try:
                    value=(node/key).read_text().strip()
                    if value.isdecimal() and int(value)>0:limits[key]=min(limits[key],int(value))
                except OSError:pass
            if node==root:break
            node=node.parent
    except (OSError,StopIteration):pass
    return ['--property=MemoryMax='+str(limits['memory.max']),'--property=TasksMax='+str(limits['pids.max']),'--property=OOMPolicy=stop']

class DrainPending(RuntimeError):pass

def drain_unit(unit):
    if not re.fullmatch(r'xiaoxi-task-[0-9a-f]{32}-[0-9a-f]{32}\.service',unit):raise ValueError('invalid task scope')
    subprocess.run(['/usr/bin/systemctl','stop',unit],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8)
    state=subprocess.run(['/usr/bin/systemctl','is-active',unit],capture_output=True,text=True,timeout=3).stdout.strip()
    if state not in ('inactive','failed','unknown'):raise DrainPending('command scope has not stopped')

class Scope:
    def __init__(self,command,workspace,env,options,output,timeout,job_id,register):
        self.unit=None
        if sys.platform=='linux' and os.geteuid()==0:
            uid=options.get('user');gid=options.get('group')
            if not isinstance(uid,int) or uid==0 or not isinstance(gid,int):raise ValueError('ordinary task identity required')
            self.unit='xiaoxi-task-'+job_id+'-'+uuid.uuid4().hex+'.service'
            register(self.unit)
            args=['/usr/bin/systemd-run','--quiet','--wait','--pipe','--collect','--unit='+self.unit,
                  '--service-type=exec','--property=ExitType=cgroup','--property=KillMode=control-group',
                  '--property=TimeoutStopSec=3s','--property=NoNewPrivileges=yes','--property=ProtectControlGroups=yes',
                  '--property=RuntimeMaxSec='+str(max(1,int(timeout)+3)),
                  '--uid='+str(uid),'--gid='+str(gid),'--working-directory='+str(workspace)]
            args += scope_limits()
            args += ['--setenv='+key+'='+value for key,value in env.items()]
            args += ['/bin/sh','-c',command]
            self.proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        elif sys.platform=='linux':
            self.proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--supervise',command],
                stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,cwd=workspace,env=env,start_new_session=True,**options)
        else:
            self.proc=subprocess.Popen(command,shell=True,executable='/bin/sh',stdin=subprocess.DEVNULL,
                stdout=output,stderr=subprocess.STDOUT,cwd=workspace,env=env,start_new_session=True,**options)
    def drain(self):
        if self.unit:
            drain_unit(self.unit)
        elif sys.platform=='linux':
            if self.proc.poll() is None:self.proc.send_signal(signal.SIGTERM)
        else:
            try:os.killpg(self.proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        try:self.proc.wait(timeout=12)
        except subprocess.TimeoutExpired:raise DrainPending('command descendants have not stopped') from None


def supervise(command):
    if ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)!=0:raise RuntimeError('subreaper unavailable')
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    main=subprocess.Popen(['/bin/sh','-c',command],start_new_session=True)
    status=None
    def children():
        # Only direct children of this supervisor, including adopted orphans.
        try:return [int(x) for x in Path('/proc/self/task/'+str(os.getpid())+'/children').read_text().split()]
        except FileNotFoundError:return []
    while True:
        if stopping:
            # Freeze before killing: a child cannot keep forking out of a scan.
            for pid in children():
                try:os.kill(pid,signal.SIGSTOP)
                except ProcessLookupError:pass
            # Kill direct children; their descendants become our children next.
            for pid in children():
                try:os.kill(pid,signal.SIGKILL)
                except ProcessLookupError:pass
        try:
            while True:
                pid,code=os.waitpid(-1,os.WNOHANG)
                if not pid:break
                if pid==main.pid:status=os.waitstatus_to_exitcode(code)
        except ChildProcessError:return 130 if stopping else 128-status if status is not None and status<0 else status or 0
        time.sleep(.02)

if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--supervise':raise SystemExit(2)
    raise SystemExit(supervise(sys.argv[2]))
