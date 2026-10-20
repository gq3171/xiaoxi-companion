"""Keep secrets out of model/tool summaries; raw old jobs are never new context."""
import os
import re

_SECRET_NAMES = ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL')
_REDACTED = '[凭据已隐藏]'


def redact(text):
    if not isinstance(text, str):
        return text
    for key, value in os.environ.items():
        if len(value) >= 8 and any(part in key.upper() for part in _SECRET_NAMES):
            text = text.replace(value, _REDACTED)
    text = re.sub(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)', _REDACTED, text)
    text = re.sub(r'(?i)(\b(?:authorization\s*:\s*bearer|api[_-]?key|api[_-]?secret|access[_-]?token|password|passwd|secret|token)\b["\s:=]+)([^\s,;"\'}]{8,})', lambda m: m[1] + _REDACTED, text)
    return text


def clean_skill(candidate):
    if not isinstance(candidate, dict):
        return None
    fields = ('name', 'when', 'method', 'check')
    if any(not isinstance(candidate.get(key), str) or redact(candidate[key]) != candidate[key] for key in fields):
        return None
    return {key: candidate[key] for key in fields}
