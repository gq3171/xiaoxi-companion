"""A monotonic external fence prevents old backups resurrecting forgotten data.

    Written before the forget transaction commits. If power fails between the
    fence and DB commit, or an old DB is restored, startup fails closed and keeps
    both copies for deliberate reconciliation; it never serves stale memories.
"""
import json
import os
from pathlib import Path
import secrets
import tempfile


class ForgetFence:
    def __init__(self, db, path):
        self.db,self.path=db,Path(path)
        db.execute('CREATE TABLE IF NOT EXISTS privacy_meta(id INTEGER PRIMARY KEY CHECK(id=1),fence TEXT NOT NULL)')
        db.execute("INSERT OR IGNORE INTO privacy_meta VALUES(1,'')")
        expected=db.execute('SELECT fence FROM privacy_meta WHERE id=1').fetchone()[0]
        present=''
        if self.path.exists() or self.path.is_symlink():
            with os.fdopen(os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as handle:
                raw=handle.read(4097)
            if len(raw)>4096:raise ValueError('invalid forget fence')
            present=json.loads(raw)['fence']
        self.current=present
        if expected!=present:
            raise ValueError('memory backup predates forget fence; reconciliation required')

    def verify(self):
        if self.db.execute('SELECT fence FROM privacy_meta WHERE id=1').fetchone()[0]!=self.current:
            raise ValueError('forget transaction requires reconciliation')

    def advance(self, operation):
        fence=secrets.token_hex(16)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent,delete=False) as handle:
                temporary=Path(handle.name)
                handle.write(json.dumps(dict(fence=fence,operation=operation)).encode())
                handle.flush();os.fsync(handle.fileno())
            temporary.replace(self.path);temporary=None
            self.current=fence
            directory=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
            self.db.execute('UPDATE privacy_meta SET fence=? WHERE id=1',(fence,))
        finally:
            if temporary:temporary.unlink(missing_ok=True)
