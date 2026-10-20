"""Non-secret component fingerprints for authenticated diagnostics."""
from functools import lru_cache
import hashlib
from pathlib import Path

@lru_cache(maxsize=1)
def manifest():
    root=Path(__file__).parent
    names=('agent.py','brain.py','home_chat.py','desktop_executor.py','desktop_browser.py',
           'task_runtime.py','skills.py','task_context.py','task_dossier.py','task_control.py','task_status.py','private_browser.py','network_guard.py',
           'desktop_lifecycle.py','task_progress.py','task_process.py','workspace_tools.py','execution.py','browser_tools.py','desktop_jobs.py')
    return dict(contract='desktop-v1',task_protocol=2,privacy_observation_protocol=2,
                components={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names})
