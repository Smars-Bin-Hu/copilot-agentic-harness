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
White space inside a statement becomes one space. Stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

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


def _batch(text: str) -> List[str]:
    """The statements of one batch (no `GO` and no sqlcmd line in it): prepared, cut at `;`."""
    out: List[str] = []
    current: List[str] = []
    index = 0

    def flush() -> None:
        statement = _SPACE.sub(" ", "".join(current)).strip()
        current.clear()
        if statement:
            out.append(statement)

    while index < len(text):
        char = text[index]
        if char == "-" and text.startswith("--", index):
            end = text.find("\n", index)
            end = len(text) if end == -1 else end
            current.append(" " + (_VARIABLE if "$(" in text[index:end] else ""))
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
            current.append(" " + (_VARIABLE if "$(" in text[index:end] else ""))
            index = end
            continue
        if char == "'":
            end = _closing(text, index, "'")
            current.append(PLACEHOLDER + (_VARIABLE if "$(" in text[index:end] else ""))
            index = end
            continue
        if char in '"[':
            end = _closing(text, index, '"' if char == '"' else "]")
            inner = text[index + 1: end - 1] if end - index >= 2 else ""
            current.append(_NOT_WORD.sub("_", inner.replace('""' if char == '"' else "]]", "_")) + (_VARIABLE if "$(" in inner else ""))
            index = end
            continue
        if char == ";":
            flush()
        else:
            current.append(char)
        index += 1
    flush()
    return out


def split(text: str) -> List[Statement]:
    """The statements and the sqlcmd lines of a text, in order."""
    items: List[Statement] = []
    lines: List[str] = []

    def batch() -> None:
        items.extend(Statement(one) for one in _batch("\n".join(lines)))
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
