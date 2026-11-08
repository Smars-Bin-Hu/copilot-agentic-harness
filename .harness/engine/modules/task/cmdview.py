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

from core import messages, pinfiles

LONG = 40  # a quoted value this long, or with a line break, is a block of its own
SCRIPT_CHARS = 60_000  # how much of a file the command reads is shown
SCRIPT_SUFFIXES = (".sql", ".ps1", ".sh", ".py", ".txt", ".csv", ".json", ".yaml", ".yml", ".cmd", ".bat")


OPERATORS = ("&&", "||", ";", "|", "\n", "&")  # what ends a command in a line of several (outside quotes); `&&` and `||` before the single characters


def _operator_at(command: str, index: int) -> str:
    """The operator that stands at this place of the line, or "" (a `>&` or `&>` of a redirection is no operator; nor is a `\\;` of `find -exec`)."""
    for operator in OPERATORS:
        if command.startswith(operator, index):
            if operator == "&" and ((index > 0 and command[index - 1] in "<>") or command.startswith("&>", index)):
                return ""
            if index > 0 and command[index - 1] == "\\":
                return ""
            return operator
    return ""


def tokens(command: str) -> List[Dict[str, Any]]:
    """`[{text, quoted}]`, the tokens of one command line: spaces split, quotes group, `\\"` inside double quotes is a quote character of the value. Outside quotes `;`, `&&`, `||`, `|` and a line
    break are tokens of their own, `{text, quoted: False, op: True}` (1.7.38): a `;` is not part of the value before it."""
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
        operator = "" if quote else _operator_at(command, index)
        if operator:
            if text is not None:
                out.append({"text": text, "quoted": quoted})
            text, quoted = None, False
            out.append({"text": operator.strip() or "\\n", "quoted": False, "op": True})
            index += len(operator)
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


def commands(command: str) -> List[str]:
    """The commands of a line, as written (1.7.38): cut at `;`, `&&`, `||`, `|` and a line break that stand outside quotes. A `;` inside a quoted text (`--text "done; checked"`) cuts nothing."""
    out: List[str] = []
    start, quote, index = 0, "", 0
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'" and index + 1 < len(command):
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        else:
            operator = _operator_at(command, index)
            if operator:
                if command[start:index].strip():
                    out.append(command[start:index].strip())
                index += len(operator)
                start = index
                continue
        index += 1
    if command[start:].strip():
        out.append(command[start:].strip())
    return out


def layout(command: str, folder: Optional[Path] = None, root: Optional[Path] = None, cwd: str = "") -> Dict[str, Any]:
    """The lines of a command for the small window: `{program, lines: [{kind, text, value?}], script?}`. `kind`: program, option (with its value), flag (no value), block (a long quoted
    value on its own), arg (a bare value). `script`: a file the command names that is in `folder` (the task), with its text (capped) and its line count. 1.7.38: a relative path is looked for
    where the agent's terminal was (`cwd`), then from the root of the repository (`root`, where its terminal starts), then in the task folder (`core.pinfiles.find`)."""
    found = tokens(command)
    if not found:
        return {"program": "", "lines": [], "script": None}
    lines: List[Dict[str, Any]] = [{"kind": "program", "text": found[0]["text"]}]
    script = None
    index = 1
    while index < len(found):
        item = found[index]
        nxt = found[index + 1] if index + 1 < len(found) else None
        if item.get("op"):  # 1.7.38: the next command of the line starts again with its program
            lines.append({"kind": "sep", "text": item["text"]})
            if nxt is not None and not nxt.get("op"):
                lines.append({"kind": "program", "text": nxt["text"]})
                index += 1
            index += 1
            continue
        if nxt is not None and nxt.get("op"):
            nxt = None  # an option at the end of a command takes no value from the next one
        if item["text"].startswith("-") and not item["quoted"] and len(item["text"]) > 1:
            if nxt is not None and (nxt["quoted"] or not nxt["text"].startswith("-") or nxt["text"] == "-1"):
                if nxt["quoted"] and (len(nxt["text"]) >= LONG or "\n" in nxt["text"]):
                    lines.append({"kind": "option", "text": item["text"], "value": ""})
                    lines.append({"kind": "block", "text": nxt["text"]})
                else:
                    lines.append({"kind": "option", "text": item["text"], "value": nxt["text"], **({"quoted": True} if nxt["quoted"] else {})})  # quoted: the body of the call when there is no block (a short query)
                    if script is None and folder is not None:
                        script = script_of(folder, nxt["text"], root, cwd, command)
                index += 2
                continue
            lines.append({"kind": "flag", "text": item["text"]})
        elif item["quoted"] and (len(item["text"]) >= LONG or "\n" in item["text"]):
            lines.append({"kind": "block", "text": item["text"]})
        else:
            lines.append({"kind": "arg", "text": item["text"], **({"quoted": True} if item["quoted"] else {})})
            if script is None and folder is not None:
                script = script_of(folder, item["text"], root, cwd, command)
        index += 1
    return {"program": found[0]["text"], "lines": lines, "script": script}


def script_of(folder: Path, value: str, root: Optional[Path] = None, cwd: str = "", command: str = "") -> Optional[Dict[str, Any]]:
    """A file the command names, when it is inside the task folder: its text, capped, and its line count. A path outside the task, or no file, is None. A relative path is found as the command finds it
    (`core.pinfiles.find`): from the agent's terminal, from the repository root, then in the task folder; the card showed no script for `-i .workspace/sandbox/tasks/<task>/DEV/_manual/x.sql` before (1.7.38)."""
    if not value or value.startswith("-") or not value.lower().endswith(SCRIPT_SUFFIXES):
        return None
    try:
        path = pinfiles.find(value, root or folder, folder, cwd, command)
        if path is None:
            return None
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except (OSError, ValueError):
        return None
    return {"path": value, "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0), "text": text[:SCRIPT_CHARS], "cut": len(text) > SCRIPT_CHARS}


def facts(command: str, show: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """The facts the pack says to show beside a command: `{name: first group of the pattern}` for each pattern that matches. A pattern that does not compile is skipped. A pattern that
    matches several times (an option given twice: `--tag a --tag b`) gives all of them, in order, joined with a comma (1.7.25)."""
    out: Dict[str, str] = {}
    for name, pattern in (show or {}).items():
        try:
            found = list(re.finditer(str(pattern), command, re.IGNORECASE))
        except re.error:
            continue
        values = list(dict.fromkeys((item.group(1) if item.groups() else item.group(0)) for item in found if (item.group(1) if item.groups() else item.group(0))))
        if values:
            out[str(name)] = ", ".join(values)[:120]
    return out


# --- what a held call says in words, and the text it writes (1.7.20) ---------------------------------------------------------------------------------------

BODY_CHARS = 20_000  # how much of the text a call writes is shown
SAY_CHARS = 200


def args_of(command: str, programs: Optional[List[str]] = None) -> str:
    """What stands after the program of the command: the text the `say` and `body` patterns of a connection type read. The program is the first of `programs` (a name, a path or a Windows
    `.cmd`) found as a whole word; with none found, the whole command."""
    for program in programs or []:
        found = re.search(rf"(?:^|[\s/\\=])({re.escape(program)})(?:\.cmd|\.bat|\.exe)?(?=\s|$)", command, re.IGNORECASE)
        if found:
            return command[found.end():].strip()
    return command.strip()


def all_args(command: str, programs: Optional[List[str]] = None) -> List[str]:
    """What stands after the program, once for each place the program is a whole word and a command of its own (1.7.27): in a line of several commands (`ado states; echo ---; ado update 1`)
    each part has its own words, up to the next `;`, `&&`, `||`, `|` or new line. `args_of` is the first."""
    out: List[str] = []
    for program in programs or []:
        for found in re.finditer(rf"(?:^|[\s/\\=;&|(])({re.escape(program)})(?:\.cmd|\.bat|\.exe)?(?=\s|$)", command, re.IGNORECASE):
            out.append(re.split(r"\n|;|&&|\|\||\|", command[found.end():].strip(), maxsplit=1)[0].strip())
    return out


def _in_language(text: Any) -> str:
    """A `say` text as the language of the session reads it (1.7.23): a plain string as it is; `{"en": ..., "zh": ...}` the language asked for, else `en`."""
    if isinstance(text, dict):
        return str(text.get(messages.language()) or text.get("en") or "")
    return str(text or "")


def say_of(args: str, rules: Optional[List[Dict[str, Any]]]) -> str:
    """The one-line title of the card: the `text` of the first rule whose `pattern` matches, with `{1}`, `{2}`, ... filled from its groups. A group that did not match is empty; a pattern that
    does not compile is skipped."""
    for rule in rules or []:
        try:
            found = re.search(str(rule.get("pattern")), args, re.IGNORECASE)
        except (re.error, AttributeError):
            continue
        if found:
            groups = found.groups()
            return re.sub(r"\{(\d+)\}", lambda part: (groups[int(part.group(1)) - 1] or "") if 0 < int(part.group(1)) <= len(groups) else "", _in_language(rule.get("text")))[:SAY_CHARS].strip()
    return ""


def _shell_value(text: str, quote: str) -> str:
    r"""What the shell passes on for a value written between these quotes (1.7.25): in double quotes `\\` is a backslash, `\"` a quote, `\$` a dollar, a backtick after a backslash a backtick, any other
    backslash stays as it is; in single quotes everything stays; with no quote a backslash is dropped and the character after it stays."""
    if quote == "'":
        return text
    if quote == '"':
        return re.sub(r'\\([\\"$`])', lambda found: found.group(1), text)
    return re.sub(r"\\(.)", lambda found: found.group(1), text)


def _unescape(text: str) -> str:
    r"""The text as a program reads it that turns `\n` into a line break and `\\` into one backslash (the ado program, `unescaped`: keep the two the same, 1.7.38). Every other backslash stays
    as written, so a Windows path or a regular expression is shown whole. Run on what the shell passed on (`_shell_value`), as the program gets it."""
    return re.sub(r"\\([n\\])", lambda found: "\n" if found.group(1) == "n" else "\\", text)


def body_of(args: str, rules: Optional[List[Dict[str, Any]]], folder: Optional[Path], root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """The text the call writes: `{text, from, path?, lines, cut}` or None. For each rule in order: `file` reads the file the first group names, inside the task folder; `text` is the first group as
    written (a `\\"` in it is a quote). A value that starts with `@` is a file too (`--body @notes.md`). A file that is not there gives `{from: "file", path, missing: true}`."""
    for rule in rules or []:
        try:
            found = re.search(str(rule.get("pattern")), args, re.IGNORECASE)
        except (re.error, AttributeError):
            continue
        if not found or not found.groups() or found.group(1) is None:
            continue
        value = found.group(1)
        label = _in_language(rule.get("label"))  # 1.7.38: what the block is called when "The text that will be written" is not the word (a statement that will run)
        if rule.get("from") == "text" and not value.startswith("@"):
            quote = args[found.start(1) - 1] if found.start(1) > 0 and args[found.start(1) - 1] in "\"'" else ""
            text = _shell_value(value, quote)
            return _shown({"text": text if rule.get("raw") else _unescape(text), "from": "text", **({"label": label} if label else {})})  # `raw`: a backslash-n in it is not a line break (a statement)
        path = value[1:] if value.startswith("@") else value
        return {**_from_file(folder, path.strip("\"'"), root), **({"label": label} if label else {})}
    return None


def _from_file(folder: Optional[Path], value: str, root: Optional[Path] = None) -> Dict[str, Any]:
    """The file a call names, found as the command finds it: a relative path from the repository root (an agent's terminal starts there; 1.7.23: the task folder is no longer tried
    first, a bare `result.md` in the task folder is not found by the program), a full path as it is. With no root given the task folder is the base. Only a file inside the task folder
    is shown."""
    gone = {"text": "", "from": "file", "path": value[:200], "missing": True, "lines": 0, "cut": False}
    if folder is None or not value:
        return gone
    named = Path(value).expanduser()
    for base in ([root] if root is not None and not named.is_absolute() else [folder]):
        try:
            path = (base / named).resolve()
            if folder.resolve() in path.parents and path.is_file():
                text = path.read_text(encoding="utf-8-sig", errors="replace")
                return _shown({"text": text, "from": "file", "path": path.relative_to(folder.resolve()).as_posix() if base is root else value})
        except (OSError, ValueError):
            continue
    return gone


def _shown(found: Dict[str, Any]) -> Dict[str, Any]:
    text = found["text"]
    return dict(found, text=text[:BODY_CHARS], lines=text.count("\n") + (1 if text and not text.endswith("\n") else 0), cut=len(text) > BODY_CHARS)
