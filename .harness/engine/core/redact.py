"""Secrets out of the text the log keeps (M43-3). The log keeps the command of a refused call and the reason, which repeats it.

A command an agent writes may hold a password or a token: `sqlcmd -P <password>`, `TOKEN=<value> tool ...`, a connection
string with `Password=...`, an `Authorization:` header, a URL with `user:password@`. Each value is replaced by `***`; the
name stays, so a person can still see what kind of thing was there. This is a net for the common spellings, not a proof:
keep secrets out of commands (an environment variable set outside the chat, or the tool's own sign-in).
"""

from __future__ import annotations

import re
from typing import Any

MASK = "***"
_SECRET_WORD = r"(?:password|passwd|pwd|token|secret|apikey|api_key|api-key|pat(?![a-z])|credential|client_secret|access_key|sas)"
_PATTERNS = [
    # VAR=value in front of a command, or an environment variable set inline: SQLCMDPASSWORD=..., AZURE_DEVOPS_EXT_PAT=...
    (re.compile(r"(?i)\b([A-Z0-9_]*" + r"(?:PASSWORD|PASSWD|PWD|TOKEN|SECRET|APIKEY|API_KEY|_PAT(?![A-Za-z])|CREDENTIAL|ACCESS_KEY)" + r"[A-Z0-9_]*)=(\"[^\"]*\"|'[^']*'|[^\s;&|]+)"), r"\1=" + MASK),
    # --password value, --password=value, --token value, --client-secret value ...
    (re.compile(r"(?i)(--?" + _SECRET_WORD + r"[\w-]*)(=|\s+)(\"[^\"]*\"|'[^']*'|[^\s;&|]+)"), r"\1\2" + MASK),
    # sqlcmd and bcp: -P <password> (capital P only: -p means something else for most tools)
    (re.compile(r"(\s-P)(\s+)(\"[^\"]*\"|'[^']*'|[^\s;&|]+)"), r"\1\2" + MASK),
    # Password=...; in a connection string, or "token": "..." in a JSON body
    (re.compile(r"(?i)(\b" + _SECRET_WORD + r"\b\"?\s*[:=]\s*\"?)([^;\s\"',}]+)"), r"\1" + MASK),
    # Authorization: Bearer <token>, Basic <token>
    (re.compile(r"(?i)(authorization:?\s*(?:bearer|basic|token)\s+)([^\s'\"]+)"), r"\1" + MASK),
    # https://user:password@host
    (re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)([^@\s/]+)(@)"), r"\1" + MASK + r"\3"),
]


def redact(text: Any) -> Any:
    """`text` with the values of secrets replaced by `***`. Anything that is not a string comes back as it is. Never raises."""
    if not isinstance(text, str) or not text:
        return text
    try:
        for pattern, replacement in _PATTERNS:
            text = pattern.sub(replacement, text)
    except Exception:  # noqa: BLE001 - redaction must not break the log
        return text
    return text
