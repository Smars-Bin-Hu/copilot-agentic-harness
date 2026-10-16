"""A command result as text a person reads at a terminal. The CLI prints JSON on a pipe and this on a terminal.

Every field of the result is shown: the text must hold all that the JSON holds, for an agent may read it too.
Keys that start with `_` are the CLI's own and are left out. `next` and `note` come last, after an empty line.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import messages

MAX_WIDTH = 100
INDENT = "  "
CLOSING = ",.;:!?)]，。；：！？）】、"  # never starts a line: it stays on the line before, one column over the width
LAST_KEYS = {"note": "render.note", "next": "render.next"}  # field -> the word before it
NAME_KEYS = ("name", "task", "skill", "id", "repo", "session_id", "path", "title")
TABLE_MAX_COLUMNS = 7
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")  # a UTC stamp the harness wrote


def width(text: str) -> int:
    """How many terminal columns a text takes: a Chinese character takes two."""
    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)


def pad(text: str, size: int) -> str:
    return text + " " * max(0, size - width(text))


def local_time(stamp: str) -> str:
    """A UTC stamp as "YYYY-MM-DD HH:MM:SS" in the time of this machine. What cannot be read is given back as it is."""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(stamp or "").replace("T", " ")


def duration(seconds: Optional[float]) -> str:
    """A length of time in words: 45 s, 3 min 20 s, 2 h 5 min, 3 d 4 h."""
    if seconds is None:
        return "-"
    total = int(max(0.0, seconds) + 0.5)  # half goes up, as Math.round does on the pages: the sentences and the cards must agree
    if total < 60:
        return messages.text("unit.seconds", s=total)
    if total < 3600:
        return messages.text("unit.minutes", m=total // 60, s=total % 60)
    if total < 86400:
        return messages.text("unit.hours", h=total // 3600, m=total % 3600 // 60)
    return messages.text("unit.days", d=total // 86400, h=total % 86400 // 3600)


def columns() -> int:
    return max(40, min(MAX_WIDTH, shutil.get_terminal_size((MAX_WIDTH, 24)).columns))


def wrap(text: str, size: int, indent: str = "") -> List[str]:
    """Break a text into lines of at most `size` columns. Words stay whole; Chinese breaks between any two characters."""
    out: List[str] = []
    for number, paragraph in enumerate(str(text).split("\n")):
        line = indent if number else ""  # a line break in the text keeps the indent of the field
        for token in tokens(paragraph):
            if line and width(line + token) > size and token[0] not in CLOSING:
                out.append(line.rstrip())
                line = indent + token.lstrip()
            else:
                line += token
        out.append(line.rstrip())
    return out


def tokens(text: str) -> List[str]:
    """The pieces a line may break between: a word with the spaces before it, one wide character, or a whole
    `code span`, so that a command a person copies never breaks across two lines."""
    found: List[str] = []
    word = ""
    code = False
    for char in text:
        if char == "`":
            if not code and word.strip():
                found.append(word)
                word = ""
            word += char
            code = not code
            if not code:
                found.append(word)
                word = ""
            continue
        if code:
            word += char
        elif unicodedata.east_asian_width(char) in ("W", "F"):
            if word:
                found.append(word)
                word = ""
            found.append(char)
        elif char == " " and word.strip():
            found.append(word)
            word = char
        else:
            word += char
    if word:
        found.append(word)
    return found


def label(key: str) -> str:
    return key.replace("_", " ")


def value_text(key: str, value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return messages.text("render.yes" if value else "render.no")
    if isinstance(value, (int, float)) and (key.endswith("_s") or key == "seconds"):
        return duration(value)
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, str) and STAMP.match(value):
        return local_time(value.replace("Z", "+00:00"))
    return str(value)


def scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def flat_list(value: Any) -> bool:
    return isinstance(value, list) and all(scalar(item) for item in value)


def empty(value: Any) -> bool:
    return isinstance(value, (list, dict)) and not value


def cell(key: str, value: Any) -> str:
    if empty(value):
        return "-"
    if flat_list(value):
        return ", ".join(value_text(key, item) for item in value) or "-"
    return value_text(key, value)


def render(result: Any) -> str:
    """The whole result as text."""
    size = columns()
    if not isinstance(result, dict):
        return "\n".join(block("", result, size, ""))
    shown = {key: value for key, value in result.items() if not str(key).startswith("_")}
    body = {key: value for key, value in shown.items() if key not in LAST_KEYS}
    lines = fields(body, size, "")
    for key in LAST_KEYS:
        if shown.get(key):
            lines.append("")
            head = messages.text(LAST_KEYS[key]) + " "
            lines += wrap(head + cell(key, shown[key]), size, " " * width(head))
    while lines and not lines[0]:
        lines.pop(0)
    return "\n".join(lines)


def fields(data: Dict[str, Any], size: int, indent: str) -> List[str]:
    """Short fields first, as aligned `key  value` lines; then each list or nested object under its own heading."""
    short = [(key, value) for key, value in data.items() if scalar(value) or empty(value) or (flat_list(value) and len(cell(key, value)) <= size // 2)]
    long = [(key, value) for key, value in data.items() if (key, value) not in short]
    lines: List[str] = []
    if short:
        name_size = max(width(label(key)) for key, _ in short) + 2
        for key, value in short:
            head = indent + pad(label(key), name_size)
            lines += wrap(head + cell(key, value), size, " " * width(head))
    for key, value in long:
        lines.append("")
        lines += block(key, value, size, indent)
    return lines


def block(key: str, value: Any, size: int, indent: str) -> List[str]:
    head = [indent + label(key) + ":"] if key else []
    inner = indent + INDENT if key else indent
    if isinstance(value, dict):
        if not value:
            return [indent + label(key) + "  -"] if key else ["-"]
        if all(isinstance(item, dict) for item in value.values()):  # {name: {same fields}}: one row per name
            rows = table([{"": name, **item} for name, item in value.items()], size, inner)
            if rows:
                return head + rows
        return head + fields(value, size, inner)
    if isinstance(value, list):
        if not value:
            return [indent + label(key) + "  " + messages.text("render.none")] if key else [messages.text("render.none")]
        if flat_list(value):
            return head + [line for item in value for line in wrap(inner + "- " + value_text(key, item), size, inner + "  ")]
        if all(isinstance(item, dict) for item in value):
            rows = table(value, size, inner)
            if rows:
                return head + rows
            return head + [line for item in value for line in item_block(item, size, inner)]
        return head + [line for item in value for line in wrap(inner + "- " + str(item), size, inner + "  ")]
    return wrap(indent + pad(label(key), width(label(key)) + 2) + cell(key, value), size)


def table(rows: List[Dict[str, Any]], size: int, indent: str) -> List[str]:
    """Rows of the same short fields as a table; an empty list when they do not fit one."""
    keys: List[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    if len(keys) > TABLE_MAX_COLUMNS or not all(scalar(row.get(key)) or flat_list(row.get(key)) for row in rows for key in keys):
        return []
    cells = [[cell(key, row.get(key)) for key in keys] for row in rows]
    if any("\n" in text for line in cells for text in line):
        return []
    sizes = [max(width(label(key)), *(width(line[index]) for line in cells)) for index, key in enumerate(keys)]
    if width(indent) + sum(sizes) + 2 * (len(keys) - 1) > size:
        return []
    out = [indent + "  ".join(pad(label(key), sizes[index]) for index, key in enumerate(keys)).rstrip()]
    out += [indent + "  ".join(pad(text, sizes[index]) for index, text in enumerate(line)).rstrip() for line in cells]
    return out


def item_block(item: Dict[str, Any], size: int, indent: str) -> List[str]:
    """One object of a list that does not fit a table: its name as the heading, the rest under it."""
    name_key = next((key for key in NAME_KEYS if scalar(item.get(key)) and item.get(key) not in (None, "")), None)
    rest = {key: value for key, value in item.items() if key != name_key}
    head = indent + "- " + (value_text(name_key, item[name_key]) if name_key else "")
    lines = [head.rstrip()]
    lines += fields(rest, size, indent + "    ")
    return lines
