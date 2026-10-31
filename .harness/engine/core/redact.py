"""Take what looks like a secret out of a text before it leaves the machine's logs (a sample kept for eval).

It keeps the shape of the text so a rule can still be tested on it, and replaces only the value. It is a net with
wide holes by design: a person looks at a sample before it is shared. It does not make a text safe to publish.
"""

from __future__ import annotations

import re
from typing import Any, List, Pattern, Tuple

MASK = "***"

_NAMES = r"(?:pass(?:word|wd)?|pwd|secret|token|api[_-]?key|access[_-]?key|auth(?:orization)?|credential|private[_-]?key|sas|signature|sig)"
_RULES: List[Tuple[Pattern[str], str]] = [
    (re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + MASK),
    (re.compile(r"(?i)(\b[\w.-]*" + _NAMES + r"[\w.-]*\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s;&\"',]+)"), r"\1" + MASK),  # key=value, key: value, --password=x
    (re.compile(r"(?i)(--?[\w-]*" + _NAMES + r"[\w-]*[ ]+)(\"[^\"]*\"|'[^']*'|[^\s;&|\-][^\s;&|]*)"), r"\1" + MASK),  # --password x
    (re.compile(r"(://[^/\s:@]+:)[^@\s/]+(@)"), r"\1" + MASK + r"\2"),  # user:password@host
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{12,}|xox[abprs]-[A-Za-z0-9-]{10,})\b"), MASK),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\b"), MASK),  # a JWT
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), MASK),
    (re.compile(r"\b[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/_-])"), MASK),  # a long run with no space: a key or a hash
]
_HOME = re.compile(r"(?i)(?:/Users/|/home/|[A-Z]:[\\/]+Users[\\/]+)[^/\\\s\"']+")


def text(value: Any) -> str:
    """The text with secret-looking values and the home folder name replaced."""
    out = str(value or "")
    for pattern, replacement in _RULES:
        out = pattern.sub(replacement, out)
    return _HOME.sub("~", out)
