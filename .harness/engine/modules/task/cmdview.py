"""How a command is laid out for a person (1.7.7): the program on the first line, each option on its own line with its value, a quoted value that holds a query
or a script body in its own block, a file the command reads (`-i file`) found in the task and shown whole. Generic: nothing here knows sqlcmd or any program.
The facts a card shows beside the command (server, port) come from the optional `show` patterns of the company pack's system entry; without them the card
names the system, the environment, the verb and the target only. The tokenizer keeps the quotes in mind, and a quote escaped with a backslash inside a quoted value
is part of the value (as the gate reads it).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

LONG = 40  # a quoted value this long, or with a line break, is a block of its own
SCRIPT_CHARS = 60_000  # how much of a file the command reads is shown
SCRIPT_SUFFIXES = (".sql", ".ps1", ".sh", ".py", ".txt", ".csv", ".json", ".yaml", ".yml", ".cmd", ".bat")


def tokens(command: str) -> List[Dict[str, Any]]:
    """`[{text, quoted}]`, the tokens of one command line: spaces split, quotes group, `\\"` inside double quotes is a quote character of the value."""
    out: List[Dict[str, Any]] = []
    text: Optional[str] = None
    quoted = False
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'" and index + 1 < len(command) and command[index + 1] == '"':
            text = (text or "") + '"'
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
            else:
                text = (text or "") + char
        elif char in "\"'":
            quote = char
            quoted = True
            text = text or ""
        elif char.isspace():
            if text is not None:
                out.append({"text": text, "quoted": quoted})
            text, quoted = None, False
        else:
            text = (text or "") + char
        index += 1
    if text is not None:
        out.append({"text": text, "quoted": quoted})
    return out


def layout(command: str, folder: Optional[Path] = None) -> Dict[str, Any]:
    """The lines of a command for the small window: `{program, lines: [{kind, text, value?}], script?}`. `kind`: program, option (with its value), flag (no value), block (a long quoted
    value on its own), arg (a bare value). `script`: a file the command names that is in `folder` (the task), with its text (capped) and its line count."""
    found = tokens(command)
    if not found:
        return {"program": "", "lines": [], "script": None}
    lines: List[Dict[str, Any]] = [{"kind": "program", "text": found[0]["text"]}]
    script = None
    index = 1
    while index < len(found):
        item = found[index]
        nxt = found[index + 1] if index + 1 < len(found) else None
        if item["text"].startswith("-") and not item["quoted"] and len(item["text"]) > 1:
            if nxt is not None and (nxt["quoted"] or not nxt["text"].startswith("-") or nxt["text"] == "-1"):
                if nxt["quoted"] and (len(nxt["text"]) >= LONG or "\n" in nxt["text"]):
                    lines.append({"kind": "option", "text": item["text"], "value": ""})
                    lines.append({"kind": "block", "text": nxt["text"]})
                else:
                    lines.append({"kind": "option", "text": item["text"], "value": nxt["text"]})
                    if script is None and folder is not None:
                        script = script_of(folder, nxt["text"])
                index += 2
                continue
            lines.append({"kind": "flag", "text": item["text"]})
        elif item["quoted"] and (len(item["text"]) >= LONG or "\n" in item["text"]):
            lines.append({"kind": "block", "text": item["text"]})
        else:
            lines.append({"kind": "arg", "text": item["text"]})
            if script is None and folder is not None:
                script = script_of(folder, item["text"])
        index += 1
    return {"program": found[0]["text"], "lines": lines, "script": script}


def script_of(folder: Path, value: str) -> Optional[Dict[str, Any]]:
    """A file the command names, when it is inside the task folder: its text, capped, and its line count. A path outside the task, or no file, is None."""
    if not value or value.startswith("-") or not value.lower().endswith(SCRIPT_SUFFIXES):
        return None
    try:
        path = (folder / value).resolve()
        if folder.resolve() not in path.parents or not path.is_file():
            return None
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except (OSError, ValueError):
        return None
    return {"path": value, "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0), "text": text[:SCRIPT_CHARS], "cut": len(text) > SCRIPT_CHARS}


def facts(command: str, show: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """The facts the pack says to show beside a command: `{name: first group of the pattern}` for each pattern that matches. A pattern that does not compile is skipped."""
    out: Dict[str, str] = {}
    for name, pattern in (show or {}).items():
        try:
            match = re.search(str(pattern), command, re.IGNORECASE)
        except re.error:
            continue
        if match:
            out[str(name)] = (match.group(1) if match.groups() else match.group(0))[:120]
    return out
