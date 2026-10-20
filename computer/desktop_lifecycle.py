"""Typed lifecycle for the dedicated browser, separate from task-owned pages.

Status never starts a browser. Shutdown uses normal Browser.close, never shell
or process-name matching, and succeeds only after OS state confirms closure.
"""
import os,re,socket,time
from pathlib import Path
from deployment_paths import desktop_root
from runtime_config import cdp_port
from browser_tools import BrowserUnavailable,BrowserCancelled


def authorize_shutdown(store,job,quote):
    doc=store.tasks.snapshot(job) or {}
    sources=[]
    if doc.get('original_request_source') in ('owner_submission','authorized_web_history'):
        sources.append(doc.get('original_request',''))
    sources += [x['text'] for x in doc.get('owner_decisions',[]) if isinstance(x,dict) and isinstance(x.get('text'),str)]
    # The complete literal owner input is required, not a model paraphrase or a
    # substring which could remove a negation. This is capability authorization,
    # not task routing; the model still chooses and plans the tool action.
    if not isinstance(quote,str) or quote not in sources:raise ValueError('关闭整个浏览器需要引用主人原始要求')
    clauses=re.split(r'[，,。；;！!？?]|\b(?:but|then)\b',quote,flags=re.I)
    authorized=False
    for clause in clauses:
        if not re.search(r'浏览器|\bbrowser\b',clause,re.I):continue
        if re.search(r'不要|别|不必|不用|不能|do not|don.t|never',clause,re.I):continue
        if re.search(r'关闭|关掉|关了|退出|结束|close|quit|exit|shut down',clause,re.I):authorized=True
    for source in sources[sources.index(quote)+1:]:
        for clause in re.split(r'[，,。；;！!？?]',source):
            if re.search(r'浏览器|\bbrowser\b',clause,re.I) and re.search(r'不要|别|不必|不用|不能|do not|don.t|never',clause,re.I):
                raise ValueError('主人后续要求保留浏览器，旧关闭授权已失效')
    if not authorized:raise ValueError('这句话没有授权关闭整个浏览器')
    if not re.search(r'(关闭|关掉|关了|退出|结束).{0,24}浏览器|浏览器.{0,24}(关闭|关掉|关了|退出|结束)|(?:close|quit|exit|shut down)\b.{0,40}\bbrowser\b',quote,re.I):
        raise ValueError('这句话没有授权关闭整个浏览器')


class BrowserSession:
    def __init__(self,port=None,root=None):
        self.port=cdp_port() if port is None else int(port)
        from runtime_config import allowed_cdp_ports
        if self.port not in allowed_cdp_ports():raise ValueError('unexpected browser endpoint')
        self.root=desktop_root() if root is None else Path(root)
    def _port_open(self):
        try:
            with socket.create_connection(('127.0.0.1',self.port),timeout=.3):return True
        except ConnectionRefusedError:return False
        except OSError:raise BrowserUnavailable('无法确认浏览器端口状态') from None
    def _profile_running(self):
        expected=os.fsencode('--user-data-dir='+str(self.root/'profile'))
        port=os.fsencode('--remote-debugging-port='+str(self.port))
        # Inspect only process arguments and export a boolean, never command
        # lines, titles, URLs, page contents or another user's desktop.
        try:processes=list(Path('/proc').iterdir())
        except OSError:raise BrowserUnavailable('无法核对浏览器进程状态') from None
        for process in processes:
            if not process.name.isdigit():continue
            try:args=(process/'cmdline').read_bytes().split(b'\0')
            except (FileNotFoundError,ProcessLookupError):continue
            except PermissionError:
                # The broker normally runs with permission to inspect this
                # dedicated profile. Never treat unreadable state as closed.
                raise BrowserUnavailable('无法核对浏览器进程状态') from None
            if expected in args and port in args:return True
        return False
    def status(self):
        port_open=self._port_open();process=self._profile_running()
        closed=not port_open and not process
        return dict(scope='desktop_browser',running=not closed,closed=closed,
                    passed=closed,verification='desktop_browser_closed' if closed else None)
    def shutdown(self,cancelled=lambda:False):
        if cancelled():raise BrowserCancelled('任务已停止')
        before=self.status()
        if before['closed']:return before|dict(already_closed=True)
        if not self._port_open():raise BrowserUnavailable('浏览器进程仍在退出，尚未确认关闭；没有强杀或重新启动')
        from desktop_stop import close_browser
        try:close_browser(self.port,self.root,cancelled=cancelled)
        except InterruptedError:raise BrowserCancelled('任务已停止，未发出关闭操作') from None
        except Exception:
            # A lost close acknowledgement can mean it already exited. Only
            # the fresh OS observation below decides whether shutdown succeeded.
            pass
        deadline=time.monotonic()+5
        while True:
            actual=self.status()
            if actual['closed']:return actual
            if time.monotonic()>=deadline:raise BrowserUnavailable('浏览器尚未确认关闭，没有强制结束其他程序')
            time.sleep(.1)
