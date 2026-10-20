"""Bounded inference lanes and content-free diagnostics. No import-time work."""
from contextlib import contextmanager
import contextvars
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time


class Deferred(RuntimeError):
    """A low-priority operation yielded; it must not become a user failure."""


class InferenceLanes:
    """One foreground and one background slot; background never owns both.

    Start background work only during a foreground lull. A new foreground turn
    gets its reserved slot immediately and asks the background stream to yield.
    No memory transaction or scheduler mutex is held across network activity.
    """
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.cv = threading.Condition()
        self.foreground = self.waiting = self.background = 0

    @contextmanager
    def enter(self, kind, live, wait_seconds=20):
        background = kind in ('plan', 'reflection')
        deadline = self.clock() + wait_seconds
        with self.cv:
            if not background:
                self.waiting += 1
            try:
                while (self.background if background else self.foreground):
                    if not live() or self.clock() >= deadline:
                        raise Deferred('admission expired')
                    self.cv.wait(.1)
                if not live():
                    raise Deferred('admission cancelled')
                if background:
                    if self.waiting or self.foreground:
                        raise Deferred('foreground priority')
                    self.background = 1
                else:
                    self.foreground = 1
            finally:
                if not background:
                    self.waiting -= 1
        started = self.clock()
        def current():
            if not live() or self.clock() - started > (45 if background else 65):
                return False
            with self.cv:
                return not background or not (self.foreground or self.waiting)
        try:
            yield current
        finally:
            with self.cv:
                if background:
                    self.background = 0
                else:
                    self.foreground = 0
                self.cv.notify_all()


ACTIVE_TRACE = contextvars.ContextVar('deskpet_trace', default=None)


def phase(name, **counts):
    trace = ACTIVE_TRACE.get()
    if trace:
        trace.mark(name, **counts)


class Diagnostics:
    """Separate bounded SQLite DB; never stores payloads, headers or error text."""
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA max_page_count=2048')
        self.db.execute('CREATE TABLE IF NOT EXISTS timings(id TEXT PRIMARY KEY, turn TEXT, kind TEXT, status TEXT, phases TEXT, created INTEGER)')
        self.db.commit()
        self.path.chmod(0o600)

    @contextmanager
    def trace(self, request, kind):
        parts = [str(request.get(k, '')) for k in ('device', 'boot', 'session', 'generation')]
        trace = Trace(hashlib.sha256('|'.join(parts).encode()).hexdigest()[:24], kind)
        token = ACTIVE_TRACE.set(trace)
        status = 'ok'
        try:
            yield trace
        except Exception as error:
            status = failure_category(error)
            raise
        finally:
            ACTIVE_TRACE.reset(token)
            trace.mark('end')
            # Telemetry failure must not turn an already delivered reply into a retry.
            try:
                with self.lock, self.db:
                    self.db.execute('INSERT INTO timings VALUES(?,?,?,?,?,?)',
                         (trace.id, trace.turn, kind, trace.status or status, json.dumps(trace.snapshot()), int(time.time())))
                    self.db.execute('DELETE FROM timings WHERE id IN (SELECT id FROM timings ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET 512)')
            except sqlite3.Error:
                pass

    def summary(self):
        with self.lock:
            rows = self.db.execute('SELECT kind,status,phases FROM timings ORDER BY rowid DESC LIMIT 128').fetchall()
        kinds = {}
        for kind, status, raw in rows:
            item = kinds.setdefault(kind, {'samples': 0, 'failures': {}, 'durations_ms': []})
            item['samples'] += 1
            if status != 'ok':
                item['failures'][status] = item['failures'].get(status, 0) + 1
            end = json.loads(raw).get('end', {}).get('ms')
            if isinstance(end, int):
                item['durations_ms'].append(end)
        for item in kinds.values():
            values = sorted(item.pop('durations_ms'))
            item['p50_ms'] = values[(len(values)-1)//2] if values else None
            item['p95_ms'] = values[min(len(values)-1, int(len(values)*.95))] if values else None
        return {'window': len(rows), 'kinds': kinds, 'contents_recorded': False}


class Trace:
    def __init__(self, turn, kind):
        self.id, self.turn, self.kind = secrets.token_hex(12), turn, kind
        self.started = time.monotonic()
        self.phases = {}
        self.status = ''
        self.lock = threading.Lock()

    def snapshot(self):
        with self.lock:return dict(self.phases)

    def mark(self, name, **counts):
        # Call sites supply fixed phase names; only numeric metadata is admitted.
        with self.lock:
            if name not in self.phases and len(self.phases) < 40:
                self.phases[name] = {'ms': int((time.monotonic()-self.started)*1000),
                                     **{k: v for k, v in counts.items() if type(v) in (int, float) and len(k) < 32}}


def failure_category(error):
    if isinstance(error, ProviderBackoff): return error.category
    code = getattr(error, 'code', None)
    if code in (401, 403): return 'authentication'
    if code == 429: return 'rate_limit'
    if isinstance(error, Deferred): return 'deferred'
    if isinstance(error, TimeoutError): return 'timeout'
    if type(error).__name__ == 'Conflict': return 'stale_or_cancelled'
    if isinstance(error, (BrokenPipeError, ConnectionResetError)): return 'disconnected'
    if isinstance(error, ValueError): return 'invalid_or_incomplete'
    return 'unavailable'


class ProviderBackoff(RuntimeError):
    def __init__(self, category, seconds):
        super().__init__('provider recovery pending')
        self.category, self.seconds = category, seconds


class CircuitBreaker:
    """Per-endpoint transport backoff; no automatic replay of model/tool work."""
    def __init__(self, clock=time.monotonic):
        self.clock,self.lock,self.states=clock,threading.Lock(),{}

    def before(self, endpoint):
        with self.lock:
            state=self.states.get(endpoint,{})
            remaining=state.get('until',0)-self.clock()
            if remaining>0:raise ProviderBackoff(state['category'],int(remaining)+1)

    def result(self, endpoint, error=None):
        with self.lock:
            if error is None:
                self.states.pop(endpoint,None);return
            category=failure_category(error)
            if category in ('stale_or_cancelled','deferred','disconnected'):return
            state=self.states.get(endpoint,{'failures':0})
            count=state['failures']+1
            wait=300 if category=='authentication' else 30 if category=='rate_limit' or count>=3 else 0
            self.states[endpoint]={'failures':count,'category':category,'until':self.clock()+wait}

    def summary(self):
        with self.lock:
            return {key:{'category':value['category'],'retry_after':max(0,int(value['until']-self.clock()))} for key,value in self.states.items()}


class ManagedResponse:
    def __init__(self, response, breaker, endpoint):
        self.response,self.breaker,self.endpoint=response,breaker,endpoint
    def __enter__(self):return self
    def __iter__(self):return iter(self.response)
    def read(self,*args):return self.response.read(*args)
    def readline(self,*args):return self.response.readline(*args)
    def __exit__(self,kind,error,traceback):
        try:self.response.close()
        finally:self.breaker.result(self.endpoint,error)
