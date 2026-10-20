"""Non-root shell identity and no-follow task file writes.

The brain keeps credentials/private state. A child gets a fixed public runtime
environment and a task-owned HOME/TMPDIR. This is OS identity separation, not a
complete container or network sandbox. No account or permission edits on import.
"""
import os
from pathlib import Path
import pwd
import secrets


class ExecutionUnavailable(RuntimeError):
    pass


class Identity:
    def __init__(self):
        self.account = None
        name = os.environ.get('DESKPET_EXECUTOR_USER', '')
        if name:
            self.account = pwd.getpwnam(name)
            if not self.account.pw_uid:
                raise ExecutionUnavailable('executor must not be root')

    def prepare(self, workspace):
        if os.geteuid() == 0 and self.account is None:
            raise ExecutionUnavailable('non-root executor is not configured')
        root=os.open(workspace,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            if self.account and os.geteuid()==0:
                os.fchown(root,self.account.pw_uid,self.account.pw_gid)
            for name in ('home','tmp','cache'):
                try:os.mkdir(name,mode=0o700,dir_fd=root)
                except FileExistsError:pass
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
                try:
                    if self.account and os.geteuid()==0:os.fchown(child,self.account.pw_uid,self.account.pw_gid)
                finally:os.close(child)
        finally:os.close(root)

    def process(self, workspace):
        self.prepare(workspace)
        env = {'PATH':'/usr/local/bin:/usr/bin:/bin', 'LANG':'C.UTF-8',
               'HOME':str(workspace/'home'), 'TMPDIR':str(workspace/'tmp'),
               'XDG_CACHE_HOME':str(workspace/'cache'),
               'XDG_DATA_HOME':str(workspace/'home'), 'XDG_STATE_HOME':str(workspace/'home')}
        kwargs = {}
        if self.account:
            if os.geteuid() == 0:
                kwargs = dict(user=self.account.pw_uid, group=self.account.pw_gid, extra_groups=[])
            elif os.geteuid() != self.account.pw_uid:
                raise ExecutionUnavailable('service cannot adopt the executor identity')
        return env, kwargs


def write_artifact(workspace, name, text, account=None):
    """All path resolution is relative to open directory FDs; never follow links.

    The untrusted task user owns its workspace and can race path changes. Root
    must therefore never use Path.write_text on a task-controlled parent.
    """
    if not isinstance(name,str) or not name or name in ('.','..') or '/' in name or '\\' in name:
        raise ValueError('artifact basename required')
    root = os.open(workspace, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    directory = None
    temporary = '.write-'+secrets.token_hex(12)
    try:
        try: os.mkdir('artifacts', mode=0o700, dir_fd=root)
        except FileExistsError: pass
        directory = os.open('artifacts', os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW, dir_fd=root)
        if account and os.geteuid()==0:
            os.fchown(directory, account.pw_uid, account.pw_gid)
        fd = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd,'wb') as stream:
            stream.write(text.encode() if isinstance(text,str) else text);stream.flush();os.fsync(stream.fileno())
            if account and os.geteuid()==0:
                os.fchown(stream.fileno(),account.pw_uid,account.pw_gid)
        os.replace(temporary,name,src_dir_fd=directory,dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        if directory is not None:
            try: os.unlink(temporary,dir_fd=directory)
            except FileNotFoundError: pass
            os.close(directory)
        os.close(root)
    return 'artifacts/'+name
