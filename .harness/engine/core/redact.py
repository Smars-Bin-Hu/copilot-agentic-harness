"""Take what looks like a secret out of a text before it leaves the machine's logs (a sample kept for eval).

It keeps the shape of the text so a rule can still be tested on it, and replaces only the value. It is a net with
wide holes by design: a person looks at a sample before it is shared. It does not make a text safe to publish.
"""

from __future__ import annotations

import re
from typing import Any, Callable, List, Match, Pattern, Tuple, Union

MASK = "***"

_NAMES = r"(?:pass(?:word|wd)?|pwd|secret|token|api[_-]?key|access[_-]?key|auth(?:orization)?|credential|private[_-]?key|sas|signature|sig|pat(?![a-z]))"  # pat: a personal access token (AZURE_DEVOPS_EXT_PAT=...), not path, patch or pattern
_PATH_PART = re.compile(r"[A-Za-z]?[a-z0-9_-]*|[A-Z0-9_-]+|[A-Z0-9]{1,12}(?:[-_][A-Za-z0-9]{1,16})+")  # the last: a code with a name after it (`435E00-ado`, the draft of a held call; 1.7.21)
_WORD = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")


def _reads_as_name(run: str) -> bool:
    """A long name of code (`ap_Load_Stage_Late_Orders_Fact_Lines_By_Warehouse`, `getAllCheckpointRefsForTheSession`): three words or more a person can read, joined by `_`, `-` or
    capitals, with few digits (1.6.102: such names in an agent's reply were masked). A key or a hash breaks into pieces of one or two letters; base64 with `+`, `/` or `=` is never a name.
    Tried on random keys (url-safe, base64, hex, letters and digits): about one in a thousand reads as a name; the named kinds (GitHub, OpenAI, AWS, a JWT, key=value) have rules of their own."""
    if "+" in run or "/" in run or run.endswith("="):
        return False
    words = _WORD.findall(run)
    digits = sum(char.isdigit() for char in run)
    return len(words) >= 3 and digits <= 0.3 * sum(char.isalnum() for char in run) and sum(map(len, words)) / len(words) >= 3.5 and max(map(len, words)) <= 24


def _long_run(found: Match[str]) -> str:
    """A long run with no space is a key or a hash, unless it reads as a path (at least two slashes and words between them) or as a name of code. A key that has slashes (base64) mixes its cases
    inside a part."""
    parts = found.group(0).split("/")
    if len(parts) >= 3 and all(_PATH_PART.fullmatch(part) and (len(part) < 32 or "-" in part or "_" in part) for part in parts):
        return found.group(0)
    return found.group(0) if _reads_as_name(found.group(0)) else MASK


_RULES: List[Tuple[Pattern[str], Union[str, Callable[[Match[str]], str]]]] = [
    (re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + MASK),
    (re.compile(r"(?i)(\"[\w.-]*" + _NAMES + r"[\w.-]*\"\s*:\s*\")([^\"]*)(\")"), r"\1" + MASK + r"\3"),  # "token": "x" in a JSON body: the quotes stay
    (re.compile(r"(?i)(\b[\w.-]*" + _NAMES + r"[\w.-]*\s*[:=]\s*)(?!(?:bearer|basic)\b)(\"[^\"]*\"|'[^']*'|[^\s;&\"',]+)"), r"\1" + MASK),  # key=value, key: value, --password=x (Authorization: Bearer x is the rule above)
    (re.compile(r"(?i)(--?[\w-]*" + _NAMES + r"[\w-]*[ ]+)(\"[^\"]*\"|'[^']*'|[^\s;&|\-][^\s;&|]*)"), r"\1" + MASK),  # --password x
    (re.compile(r"(://[^/\s:@]+:)[^@\s/]+(@)"), r"\1" + MASK + r"\2"),  # user:password@host
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{12,}|xox[abprs]-[A-Za-z0-9-]{10,})\b"), MASK),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\b"), MASK),  # a JWT
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), MASK),
    (re.compile(r"\b[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/_-])"), _long_run),
]
# Short password options (`-P x`, `-pSecret`, `-a x`) mean a password only for some tools: `grep -P`, `mkdir -p`, `ssh -p 22` and `mysql -P 3306` do not. So they are masked
# only in a command (a part between ; & |) of a known database or login tool. Long names (`--password x`, `-Password x`) are caught by the rules above for every tool.
_SEGMENT = re.compile(r"([;&|\n]+)")
_TOOL = r"(?:^|[\s/\\])(?:%s)(?:\.exe)?(?=\s)"
_SHORT: List[Tuple[Pattern[str], List[Tuple[Pattern[str], str]]]] = [
    (re.compile(_TOOL % "sqlcmd|bcp|mssql-cli|osql|isql", re.I), [(re.compile(r"(?<!\S)(-P)(?:[ ]+(\"[^\"]*\"|'[^']*'|[^\s-]\S*)|(?=\S)(\S+))"), r"\1 " + MASK)]),  # -P is case-sensitive: -p is something else
    (re.compile(_TOOL % "mysql|mysqldump|mysqladmin|mysqlimport|mysqlcheck|mariadb|mariadb-dump", re.I), [(re.compile(r"(?<!\S)-p(?=\S)(?!-)(\"[^\"]*\"|'[^']*'|\S+)"), "-p" + MASK)]),  # -pSecret only: `-p` alone asks, `-P` is the port
    (re.compile(_TOOL % "mongo|mongosh|mongodump|mongorestore|mongoexport|mongoimport", re.I), [(re.compile(r"(?<!\S)(-p)(?:[ ]+|(?=\S))(\"[^\"]*\"|'[^']*'|[^\s-]\S*)"), r"\1 " + MASK)]),
    (re.compile(_TOOL % "redis-cli", re.I), [(re.compile(r"(?<!\S)(-a[ ]+)(\"[^\"]*\"|'[^']*'|[^\s-]\S*)"), r"\1" + MASK)]),
    (re.compile(_TOOL % "sqlplus", re.I), [(re.compile(r"(?<![\w/])([\w$#.]+/)[^\s/@]+(?=@|\s|$)"), r"\1" + MASK)]),  # sqlplus user/password@db
]


def _short(value: str) -> str:
    parts = _SEGMENT.split(value)
    for at in range(0, len(parts), 2):
        for tool, fixes in _SHORT:
            if tool.search(parts[at]):
                for pattern, replacement in fixes:
                    parts[at] = pattern.sub(replacement, parts[at])
    return "".join(parts)


_HOME = re.compile(r"(?i)(?:/Users/|/home/|[A-Z]:[\\/]+Users[\\/]+)[^/\\\s\"']+")


def text(value: Any) -> str:
    """The text with secret-looking values and the home folder name replaced."""
    out = _short(str(value or ""))  # first: a password that is a word like "Secret" must not make the next word look like its value
    for pattern, replacement in _RULES:
        out = pattern.sub(replacement, out)
    return _HOME.sub("~", out)


def path(value: Any) -> str:
    """A path or an address: the home folder name replaced, and each part between slashes checked on its own. `text` would mask a long path as one long run (a key or a hash looks like that); here only a part that is long by itself is."""
    flat = _HOME.sub("~", str(value or ""))
    if re.search(r"\s", flat):
        return text(flat)  # not a plain path (a command, words): the whole text rules apply
    return re.sub(r"[^/\\]+", lambda found: text(found.group(0)), flat)
