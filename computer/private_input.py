"""One-shot owner input for a specific browser document. Values live only in RAM.

No model, database, checkpoint, task log or notification receives field values.
The executor alone consumes a submission; a lost response never replays it.
"""
import copy
import secrets
import threading
import time


class InputConflict(ValueError):
    pass


def inputs(store):
    # Reuse the store's initialization lock, never hold it during browser I/O.
    with store.lock:
        if not hasattr(store, '_private_inputs'):
            store._private_inputs = PrivateInputs()
        return store._private_inputs


def attention(store, job):
    private=getattr(store,"_private_inputs",None)
    return private.attention(job) if private else ""


def wipe(values):
    for value in values.values():
        if isinstance(value, bytearray):
            value[:] = b'\0' * len(value)
    values.clear()


class PrivateInputs:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.requests = {}

    def _expire(self):
        for request in self.requests.values():
            if request['state'] in ('pending', 'claimed', 'queued') and self.clock() >= request['expires']:
                wipe(request.pop('values', {}))
                request['state'] = 'expired'

    def offer(self, job, form):
        with self.lock:
            self._expire()
            for request in self.requests.values():
                if request['job_id'] == job and request['state'] in ('pending', 'claimed', 'queued', 'applying'):
                    return self._public(request)
            # Only one desktop job runs; retain a small set of value-free receipts.
            for key in list(self.requests)[:-7]:
                old = self.requests.pop(key)
                wipe(old.pop('values', {}))
            identifier = secrets.token_hex(16)
            request = dict(id=identifier, job_id=job, form=form, state='pending',
                           expires=self.clock() + 600, session=None, lease=None,
                           claim_until=0, valid=None)
            self.requests[identifier] = request
            return self._public(request)

    def _public(self, request):
        form = request['form']
        return dict(id=request['id'], job_id=request['job_id'], state=request['state'],
                    origin=form['origin'], fields=copy.deepcopy(form['fields']),
                    action=form.get('action_label'),
                    expires_in=max(0, int(request['expires'] - self.clock())))

    def pending(self, session):
        with self.lock:
            self._expire()
            request = next(reversed(self.requests.values()), None)
            if not request:
                return None
            value = self._public(request)
            value['claimed_elsewhere'] = bool(request['session'] and request['session'] != session
                                              and request['claim_until'] > self.clock())
            return value

    def attention(self, job):
        with self.lock:
            self._expire()
            request = next((r for r in reversed(self.requests.values()) if r['job_id']==job and r['state'] in ('pending','claimed')),None)
            return request['id'] if request else ''

    def claim(self, identifier, session):
        with self.lock:
            self._expire()
            request = self.requests.get(identifier)
            if not request or request['state'] not in ('pending', 'claimed'):
                raise InputConflict('request no longer pending')
            if request['session'] != session and request['claim_until'] > self.clock():
                raise InputConflict('another device is filling this step')
            lease = request['lease'] if request['session'] == session and request['claim_until'] > self.clock() else secrets.token_hex(16)
            request.update(session=session, lease=lease,
                           claim_until=self.clock() + 90, state='claimed')
            return self._public(request) | dict(lease=request['lease'])

    def release(self, identifier, session, lease):
        with self.lock:
            request = self.requests.get(identifier)
            if request and request['state']=='claimed' and request['session']==session and request['lease']==lease:
                request.update(state='pending',session=None,lease=None,claim_until=0)
            return dict(ok=True)

    def submit(self, identifier, session, lease, values, activate, valid):
        if type(activate) is not bool or not isinstance(values, dict):
            raise ValueError('invalid private input')
        with self.lock:
            self._expire()
            request = self.requests.get(identifier)
            if not request or request['session'] != session or not secrets.compare_digest(str(request['lease']), str(lease)):
                raise InputConflict('private input lease changed')
            # Idempotent acknowledgement without retaining or comparing secrets.
            if request['state'] in ('queued', 'applying', 'filled', 'uncertain'):
                return dict(ok=True, state=request['state'])
            if request['state'] != 'claimed' or request['claim_until'] <= self.clock():
                raise InputConflict('private input expired')
            fields = request['form']['fields']
            if set(values) != {field['id'] for field in fields}:
                raise ValueError('private field set changed')
            if activate and not request['form'].get('action_label'):
                raise ValueError('no reviewed continuation action')
            if sum(len(v.encode()) if isinstance(v,str) else 100000 for v in values.values()) > 6000:
                raise ValueError('private input budget')
            for field in fields:
                value = values[field['id']]
                if not isinstance(value, str) or not value or len(value.encode()) > 1024 or '\0' in value:
                    raise ValueError('invalid private field value')
                if field['kind'] == 'select' and value not in {option['id'] for option in field['options']}:
                    raise ValueError('private option changed')
            request.update(values={key: bytearray(value.encode()) for key, value in values.items()},
                           activate=activate, valid=valid, state='queued')
            return dict(ok=True, state='queued')

    def consume(self, job):
        with self.lock:
            self._expire()
            request = next((r for r in self.requests.values()
                            if r['job_id'] == job and r['state'] == 'queued'), None)
            if not request:
                return None
            request['state'] = 'applying'
            return dict(id=request['id'], form=request['form'],
                        values=request.pop('values'), activate=request['activate'])

    def valid(self, identifier):
        with self.lock:
            request = self.requests.get(identifier)
            verifier = request['valid'] if request and request['state'] == 'applying' and self.clock() < request['expires'] else None
        # Authorization may take the room lock; never call it under this lock.
        return bool(verifier and verifier())

    def finish(self, identifier, success):
        with self.lock:
            request = self.requests.get(identifier)
            if request:
                wipe(request.pop('values', {}))
                request['state'] = 'filled' if success else 'uncertain'
                request['valid'] = None

    def cancel(self, identifier, session):
        with self.lock:
            request = self.requests.get(identifier)
            if not request or request['session'] not in (None, session):
                raise InputConflict('private input not owned')
            if request['state'] == 'applying':
                raise InputConflict('input already dispatched; observe first')
            if request['state'] not in ('pending', 'claimed', 'queued'):
                return dict(ok=True)
            wipe(request.pop('values', {}))
            request.update(state='cancelled', valid=None)
            return dict(ok=True)

    def close_job(self, job):
        with self.lock:
            for request in self.requests.values():
                if request['job_id'] == job:
                    wipe(request.pop('values', {}))
                    request['valid'] = None
                    if request['state'] in ('pending', 'claimed', 'queued', 'applying'):
                        request['state'] = 'cancelled'


def body_rpc(store, payload):
    """Authenticated board channel; no cookie or model impersonation."""
    job=payload.get('job_id');private=inputs(store);request=private.pending('body')
    if not request or request['job_id']!=job or request['id']!=payload.get('id'):
        raise InputConflict('body input request changed')
    current=store.get(job)
    if not current or current.get('cancel') or current['state']!='running':
        raise InputConflict('body task is not live')
    action=payload.get('action')
    if action=='claim':
        # The panel limits response size; a large form stays available on web.
        import json
        if len(json.dumps(request,ensure_ascii=False).encode())>6500:
            return dict(ok=False,error='use_web')
        return dict(ok=True,request=private.claim(request['id'],'body'))
    if action=='release':return private.release(request['id'],'body',payload.get('lease'))
    if action=='submit':
        values=payload.pop('values',{})
        def valid():
            current=store.get(job)
            return bool(current and not current.get('cancel') and current['state']=='running')
        try:return private.submit(request['id'],'body',payload.get('lease'),values,payload.get('activate'),valid)
        finally:values.clear()
    raise ValueError('unknown body input action')


def prepare_waiting_request(store):
    """Read an existing safe checkpoint, without executing or resuming its task.

    One throttled background inspection keeps HTTP polling bounded. Owner form
    submission, rather than this inspection, authorizes continuation after boot.
    """
    private=inputs(store)
    with private.lock:
        if getattr(private,'preparing',False) or private.clock()-getattr(private,'prepared_at',-1000)<20:
            return
        if any(r['state'] in ('pending','claimed','queued','applying') for r in private.requests.values()):return
        private.preparing=True;private.prepared_at=private.clock()
    def inspect():
        browser=None
        try:
            import json,tempfile
            from pathlib import Path
            from browser_tools import Browser
            from desktop_browser import DesktopBrowser
            from home_desktop import HostDesktop
            with store.lock:
                if not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_jobs'").fetchone():return
                row=store.db.execute("SELECT j.id,d.checkpoint FROM jobs j JOIN desktop_jobs d ON d.job=j.id WHERE j.state='interrupted' AND j.cancel=0 AND d.phase!='done' ORDER BY j.updated DESC LIMIT 1").fetchone()
                if not row or store.db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running')").fetchone():return
                job,checkpoint=row['id'],json.loads(row['checkpoint'])
            if checkpoint.get('uncertain') or not checkpoint.get('browser',{}).get('tabs'):return
            desktop=HostDesktop(store)
            if not desktop.real_status().get('ready'):return
            with tempfile.TemporaryDirectory(prefix='private-form-inspect-',dir=store.path.parent.parent/'tmp') as temporary:
                browser=object.__new__(DesktopBrowser);Browser.__init__(browser,job,Path(temporary))
                browser.desktop=desktop;browser.ready=True;browser.heartbeat=lambda:None
                browser.restore(checkpoint['browser']);form=browser.private_form()
                if form:private.offer(job,form)
        except Exception:
            # Inspection cannot execute a task or turn page data into a log.
            pass
        finally:
            if browser:browser.detach()
            with private.lock:private.preparing=False
    threading.Thread(target=inspect,name='private-form-inspect',daemon=True).start()


def submit_web(store, identifier, session, lease, values, activate, valid):
    from desktop_jobs import broker
    private=inputs(store)
    with store.lock:
        request=private.pending(session)
        if not request or request['id']!=identifier:raise InputConflict('private request changed')
        if request['state'] in ('filled','uncertain'):
            return private.submit(identifier,session,lease,values,activate,valid)
        job=store.get(request['job_id'])
        if not job or job['cancel'] or job['state'] not in ('running','interrupted'):
            raise InputConflict('task is not live')
        if job['state']=='interrupted':
            import json
            row=store.db.execute('SELECT phase,checkpoint FROM desktop_jobs WHERE job=?',(job['id'],)).fetchone()
            if not row or row['phase']=='done' or json.loads(row['checkpoint']).get('uncertain'):
                raise InputConflict('checkpoint needs review before continuation')
        result=private.submit(identifier,session,lease,values,activate,valid)
        if job['state']=='interrupted':
            try:broker(store).resume(job['id'])
            except Exception:
                private.cancel(identifier,session)
                raise InputConflict('task could not resume; input was discarded') from None
        return result
