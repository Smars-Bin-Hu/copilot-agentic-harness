"""Free text cut into statements (1.7.38, C12: pass, refuse, ask).

A tool pack type whose program takes its work as text (`sqlcmd -Q "..."`, a script file) cannot be judged by a word here and there: the gate must know what every statement of the text is. This module
prepares the text and cuts it; `judge` (in this file too) answers by the type's lists.

Prepare, in one pass over a batch:
  - `--` and `/* */` comments go (a block comment nests; both stand for one space, as the server reads them: `DR/**/OP` is two words);
  - a string literal becomes `''` (an `N` before it stays), so a `;` or a `DROP` inside a string changes nothing;
  - a `[name]` or `"name"` becomes the plain name (its other characters `_`): `EXEC [master]..[xp_cmdshell]` is seen as it is;
  - `EXEC(` and every `$(` stay visible: a `$(` inside a comment or a string is marked with ` $( `, because sqlcmd fills a variable in there too.
Cut: at `;` (outside strings and comments), at a line that is only `GO` (an optional count) and at a sqlcmd line (`:` and a letter, or `!!`), which is its own item and marked as a directive.
These lines are found first, on the raw lines, before any string or comment is read: sqlcmd looks at them whatever surrounds them, so a `GO` inside a string still ends the batch for it.
White space inside a statement becomes one space. A character that looks like the end of what hides text (a curly quote inside a string, a fullwidth `]` inside a name, a fullwidth `*` or `/` inside a
block comment) marks the statement `odd`: the gate sees the text as hidden, and a program that folds such characters to plain ones would not. An odd statement is on no list: it asks. Stdlib only.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

PLACEHOLDER = "''"  # what a string literal becomes
_LINES = re.compile(r"\r\n|\r|\n")
_GO = re.compile(r"^[ \t]*go(?:[ \t]+\d+)?[ \t]*(?:--.*)?$", re.IGNORECASE)
_DIRECTIVE = re.compile(r"^[ \t]*(?:!!|:[A-Za-z])")
_SPACE = re.compile(r"\s+")
_NOT_WORD = re.compile(r"\W")
_VARIABLE = " $( "


@dataclass(frozen=True)
class Statement:
    text: str  # prepared: no comments, strings are `''`, one space between words
    directive: bool = False  # a sqlcmd line (`:r file`, `!! command`): its text is the line as written, trimmed
    odd: bool = False  # a look-alike of the end of a string, a name or a block comment is inside one: see the top of this file
    raw: str = ""  # (1.7.38, F1 L3) the statement as it was written, for a text to the agent or the person: comments gone, strings and names as they were (`text` is the form that is judged). Empty: the same as `text`


# What may be folded into the character that ends a hidden span, besides the fullwidth forms that NFKC folds (`＇` is `'`): the curly and modifier quotes, the fullwidth bracket.
_ALIKE = {"'": "\u2018\u2019\u201a\u201b\u02b9\u02bc\u02c8\u2032", '"': "\u201c\u201d\u201e\u201f\u02ba\u2033", "]": "", "*": "\u2217\u204e", "/": "\u2044\u2215"}


def _alike(text: str, ends: str) -> bool:
    """Does the text hold a character that is not one of `ends` but could be folded into one of them?"""
    for char in text:
        if ord(char) > 127 and any(char in _ALIKE[end] or unicodedata.normalize("NFKC", char) == end for end in ends):
            return True
    return False


def _closing(text: str, start: int, quote: str) -> int:
    """Index after the closing `quote` of a quoted span that starts at `start` (a doubled quote is part of it); the end of the text when it never closes."""
    index = start + 1
    while index < len(text):
        if text[index] == quote:
            if text[index + 1: index + 2] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    return len(text)


_DEFINITION = re.compile(r"^(?:CREATE(?: OR ALTER)?|ALTER) (?:PROCEDURE|PROC|FUNCTION|VIEW)\b", re.IGNORECASE)  # a batch that is one definition (1.7.38, C13 F2)


def _batch(text: str) -> List[Statement]:
    """The statements of one batch (no `GO` and no sqlcmd line in it): prepared, cut at `;`. SQL Server reads `CREATE [OR ALTER] | ALTER` `PROCEDURE`, `FUNCTION` and `VIEW` as the only statement of its batch,
    its body running to the end of the batch: such a batch is one statement here too (the `;` inside the body cuts nothing), so the lists judge the definition and the refuse list reads the whole body (1.7.38, C13 F2).
    A `TRIGGER` is not one: it is cut as before and asks."""
    whole = _cut(text, False)
    if len(whole) == 1 and _DEFINITION.match(whole[0].text):
        return whole
    return _cut(text, True)


def _cut(text: str, at_semicolon: bool) -> List[Statement]:
    out: List[Statement] = []
    current: List[str] = []
    shown: List[str] = []  # the same text with the strings and the names as they were written
    odd = False
    index = 0

    def flush() -> None:
        nonlocal odd
        statement = _SPACE.sub(" ", "".join(current)).strip()
        written = _SPACE.sub(" ", "".join(shown)).strip()
        current.clear()
        shown.clear()
        if statement:
            out.append(Statement(statement, odd=odd, raw=written if written != statement else ""))
        odd = False

    while index < len(text):
        char = text[index]
        if char == "-" and text.startswith("--", index):
            end = text.find("\n", index)
            end = len(text) if end == -1 else end
            current.append(" " + (_VARIABLE if "$(" in text[index:end] else ""))
            shown.append(" ")
            index = end
            continue
        if char == "/" and text.startswith("/*", index):
            depth, end = 1, index + 2
            while end < len(text) and depth:
                if text.startswith("/*", end):
                    depth, end = depth + 1, end + 2
                elif text.startswith("*/", end):
                    depth, end = depth - 1, end + 2
                else:
                    end += 1
            odd = odd or _alike(text[index + 2:end], "*/")
            current.append(" " + (_VARIABLE if "$(" in text[index:end] else ""))
            shown.append(" ")
            index = end
            continue
        if char == "'":
            end = _closing(text, index, "'")
            odd = odd or _alike(text[index + 1:end], "'")
            current.append(PLACEHOLDER + (_VARIABLE if "$(" in text[index:end] else ""))
            shown.append(text[index:end])
            index = end
            continue
        if char in '"[':
            end = _closing(text, index, '"' if char == '"' else "]")
            inner = text[index + 1: end - 1] if end - index >= 2 else ""
            odd = odd or _alike(inner, '"' if char == '"' else "]")
            current.append(_NOT_WORD.sub("_", inner.replace('""' if char == '"' else "]]", "_")) + (_VARIABLE if "$(" in inner else ""))
            shown.append(text[index:end])
            index = end
            continue
        if char == ";" and at_semicolon:
            flush()
        else:
            current.append(char)
            shown.append(char)
        index += 1
    flush()
    return out


def split(text: str) -> List[Statement]:
    """The statements and the sqlcmd lines of a text, in order."""
    items: List[Statement] = []
    lines: List[str] = []

    def batch() -> None:
        items.extend(_batch("\n".join(lines)))
        lines.clear()

    for line in _LINES.split(text):
        if _GO.match(line):
            batch()
        elif _DIRECTIVE.match(line):
            batch()
            items.append(Statement(line.strip(), True))
        else:
            lines.append(line)
    batch()
    return items


# --- the answer ---------------------------------------------------------------------------------------------------------------------------------------

REFUSE, READ, WRITE, ASK = "refuse", "read", "write", "ask"  # the zones of a call (docs/12): refuse list, pass list, pass list of an opened connection, the rest asks the person


@dataclass
class Verdict:
    zone: str  # REFUSE, READ, WRITE (every statement is on the read or the write list, one at least on the write list), ASK
    statement: str = ""  # REFUSE: the statement (or line) the refuse list caught; ASK: the first that is on no list (empty: there was nothing to read)
    reason: str = ""  # REFUSE: the reason of the entry that caught it, as the type wrote it (a string, or {"en": ..., "zh": ...})
    quote: str = ""  # that statement as it was written (strings and names not blanked), for a text to the agent; `statement` stays the form that is judged and looked up


def _compiled(patterns: Any) -> List[Any]:
    """The patterns of a list that compile (a broken one matches nothing: the call then asks, which is the safe side)."""
    out = []
    for item in patterns or []:
        try:
            out.append(re.compile(str(item), re.IGNORECASE | re.DOTALL))
        except re.error:
            continue
    return out


def refuse_entry(system: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
    """The first entry of the type's `refuse` list that has its pattern anywhere in the text (best effort: it names what is forbidden, it is not complete)."""
    for entry in system.get("refuse") or []:
        try:
            if isinstance(entry, dict) and re.search(str(entry.get("pattern") or "(?!)"), text, re.IGNORECASE | re.DOTALL):
                return entry
        except re.error:
            continue
    return None


def judge(system: Dict[str, Any], items: List[Statement]) -> Verdict:
    """Which zone these statements are in, by the lists of the type (`refuse`, `reads`, `writes`). Order: any statement or line on the refuse list refuses; every statement
    whole on the read list (and no sqlcmd line left) is a read; every statement on the read or write list is what an opened connection passes; else the person is asked. Reads
    and writes are matched on the whole statement, so a word after the first words cannot slip by: the patterns say what may follow."""
    for item in items:
        entry = refuse_entry(system, item.text)
        if entry:
            return Verdict(REFUSE, item.text, entry.get("reason") or "", quote=item.raw or item.text)
    reads = _compiled(system.get("reads"))
    writes = _compiled(system.get("writes"))
    first_unlisted = quote = ""
    all_reads = all_listed = bool(items)
    wrote = False
    for item in items:
        if item.directive or item.odd:
            all_reads = all_listed = False
            if not first_unlisted:
                first_unlisted, quote = item.text, item.raw or item.text
            continue
        if any(rule.fullmatch(item.text) for rule in reads):
            continue
        all_reads = False
        if any(rule.fullmatch(item.text) for rule in writes):
            wrote = True
            continue
        all_listed = False
        if not first_unlisted:
            first_unlisted, quote = item.text, item.raw or item.text
    if all_reads:
        return Verdict(READ)
    if all_listed and wrote:
        return Verdict(WRITE)
    return Verdict(ASK, first_unlisted, quote=quote)
