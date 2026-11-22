"""What the Live tab shows of a chat (1.6, B88): the whole last turn that the cached state holds, redacted. Nothing here reads a file or the whole conversation (`items_of` can be given a turn the
caller read from the stream file: the older steps and the earlier rounds).

`build(state, marks, root, memo, have, rev)` gives the items of the last turn (see its docstring for `before`, the memo and the stubs); `latest` the newest few of the last turns (the steps of a subagent). Items, oldest first: agent text (`text`), tool calls (`tool`) and thinking (`think`). Every field of a tool call may be missing (the host does not always send
`displayName`, `invocationMessage`, `pastTenseMessage`, `intention`, `toolInput` or `success`); a missing one is left out, never made up. The text of a `think` item is there only when the host sent some
(it often sends none). Every shown text goes through `core/redact.py` first and is cut after, at a guard far above any real text; a cut is marked (`cut: true`), so the page can say so.

`stamp` notes when each part was first seen, from the actions of the host (the host sends no times): a tool's run time and the length of a thought are counted from that. A part that was already there
when the board subscribed has no time, and the page shows none.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import ahp, redact

from . import mdtree

LATEST = 8  # items of `latest`: the newest few steps of a chat (no longer used for a subagent: its row is `sub_summary`, its whole chat `build_all`)
TEXT_CAP = 200000  # characters of agent text: a guard, not a design limit (a text longer than this is cut and says so)
THINK_CAP = 200000  # the same for thinking
ERROR_CAP = 300  # 1.8.5: the words of an error part, as `ahp.last_error` keeps them
SAY_CAP = 200
TARGET_CAP = 500
MARKS_MAX = 240  # part times kept for one turn
RUNNING = ("running", "streaming")
PATH_KEYS = ("path", "filePath", "file_path", "file", "filename", "paths", "uri", "url")
RUN_KEYS = ("command", "commandLine", "cmd", "script", "query", "pattern", "input")
WORD_CAP = 24  # characters of the program word of a command
SCAN_CAP = 4000  # characters of a command looked at to find its program (the target takes the rest, cut)
DETAIL_TEXT = 50000  # characters of one result text an opened call shows
DETAIL_CMD = 20000  # of a command and of an input
DIFF_TEXT = 300000  # characters of a diff text read for an opened call
DIFF_LINES = 4000  # lines of diff over all the files of an opened call
DIFF_FILES = 500
HITS_MAX = 9999
PARTS_MAX = 40
KINDS = ("read", "search", "edit", "create", "run", "agent", "web", "other")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MARKS = re.compile(r"`+|\*\*+")  # a `_` is not taken out: it is in names (load_orders)


def part_id(part: Any) -> str:
    """The id a part is told apart by: the id of text and thinking, the call id of a tool call. Empty: none."""
    if not isinstance(part, dict):
        return ""
    if part.get("kind") == "toolCall":
        return str((part.get("toolCall") or {}).get("toolCallId") or "") if isinstance(part.get("toolCall"), dict) else ""
    if part.get("kind") == "inputRequest":  # B8: a question of the agent, by its request id
        request = part.get("request") if isinstance(part.get("request"), dict) else {}
        return "q:" + str(request["id"]) if isinstance(request.get("id"), str) and request["id"] else ""
    return str(part.get("id") or "")


def stamp(cached: Dict[str, Any], action: Dict[str, Any], now: int) -> None:
    """Note, from one action of the host, when a part began and ended (milliseconds since 1970). The caller holds the lock of the link."""
    kind = str(action.get("type") or "")
    marks = cached.setdefault("marks", {})
    if kind == "chat/turnStarted":
        marks.clear()
        return
    ident = str(action.get("toolCallId") or "") if kind.startswith("chat/toolCall") else part_id(action.get("part")) if kind == "chat/responsePart" else ""
    if kind == "chat/inputRequested" and isinstance(action.get("request"), dict) and isinstance(action["request"].get("id"), str):
        ident = "q:" + action["request"]["id"]
    elif kind == "chat/inputCompleted" and isinstance(action.get("requestId"), str):
        ident = "q:" + action["requestId"]
    if not ident:
        return
    if kind in ("chat/responsePart", "chat/toolCallStart", "chat/inputRequested"):
        marks.setdefault(ident, [now, 0])
    elif kind == "chat/inputCompleted":
        mark = marks.setdefault(ident, [0, 0])
        mark[1] = now
    elif kind == "chat/toolCallConfirmed" and action.get("approved"):
        mark = marks.setdefault(ident, [now, 0])
        mark[:] = [now, 0, now]  # B8: it runs from now, and this is when it was let go
    elif kind == "chat/toolCallReady" and action.get("confirmed"):
        marks[ident] = [now, 0]  # it runs from now: the wait for a person's yes is not run time
    elif kind == "chat/toolCallComplete":
        mark = marks.setdefault(ident, [0, 0])
        mark[1] = now
    while len(marks) > MARKS_MAX:
        del marks[next(iter(marks))]


def cut(value: Any, cap: int, path: bool = False) -> Tuple[str, bool]:
    """Redacted, then cut at `cap` characters. (text, was it cut). Only twice the cap is read: a text of 20,000 characters is not run through the redaction whole, once a second."""
    raw = str(value or "")
    source = raw[:cap * 2 + 200]
    text = (redact.path(source.strip()) if path else redact.text(source)).strip()
    return (text[:cap].rstrip(), True) if len(text) > cap or len(raw) > len(source) else (text, False)


def words(value: Any) -> str:
    """A message of the host as plain words: it may be a string or an object with the text in one of a few fields; links and marks of markdown are taken out."""
    if isinstance(value, dict):
        value = next((value[key] for key in ("markdown", "text", "value", "message") if isinstance(value.get(key), str)), "")
    if not isinstance(value, str):
        return ""
    return " ".join(MARKS.sub("", LINK.sub(lambda found: found.group(1), value)).split())


def target_of(call: Dict[str, Any], root: Optional[Path] = None) -> Tuple[str, bool]:
    """Where a tool call works: its path or address; else its command, query or pattern (shown redacted and cut); else the words Copilot gave for it. (text, cut)"""
    try:
        given = json.loads(call.get("toolInput") or "{}") if isinstance(call.get("toolInput"), str) else call.get("toolInput") or {}
    except (ValueError, TypeError):
        given = {}
    if isinstance(given, dict):
        for keys, is_path in ((PATH_KEYS, True), (RUN_KEYS, False)):
            for key in keys:
                value = given.get(key)
                if isinstance(value, list) and value:
                    value = value[0]
                if isinstance(value, str) and value.strip():
                    if is_path and root is not None:
                        flat = value.strip().replace("\\", "/")
                        plain = str(root).replace("\\", "/").rstrip("/") + "/"
                        for folder in (plain, redact.path(plain.rstrip("/")) + "/"):  # the second: a path read back from the task's stream has its home folder masked already
                            if flat.startswith(folder):
                                flat = flat[len(folder):]
                                break
                        else:
                            flat = value.strip()
                        value = flat
                    return cut(value, TARGET_CAP, is_path)
    return cut(words(call.get("intention")), TARGET_CAP)


def state_of(call: Dict[str, Any], active: bool) -> str:
    """`run`, `wait` (a person must allow it, check its result or sign in: B5), `done` or `fail`. (`tool_item` adds `stop`: the turn ended with the call still open.)"""
    status = str(call.get("status") or "")
    if status in RUNNING:
        return "run"
    if status in ("pending-confirmation", "pending-result-confirmation", "auth-required"):  # before `fail`: a result that waits may be a failed one
        return "wait"
    if status in ("failed", "cancelled", "denied", "error") or call.get("success") is False:
        return "fail"
    if status == "completed" or call.get("success") is True:
        return "done"
    return "run" if active else "done"  # a status this code does not know: still going while the turn runs, else over


# --- what a tool call is: its kind, program, numbers (the closed line) and its whole content (`detail`) ----------------------------------------------------------------------------

RUN_NAME = re.compile(r"(bash|shell|terminal|command|powershell|\brun\b|exec)")  # the rules of `kindOf` in web/live.js, in its order
EDIT_NAME = re.compile(r"(edit|write|patch|replace|create|apply|insert|delete|rename|move)")
SEARCH_NAME = re.compile(r"(grep|glob|search|find|list|\bls\b)")
WEB_NAME = re.compile(r"(fetch|web|http|browse|url)")
READ_NAME = re.compile(r"(read|view|open|cat|get_file|file)")
CREATE_NAME = re.compile(r"(^|[^a-z])create([^a-z]|$)")
COMMAND_KEYS = ("command", "commandLine", "cmd", "script")
SEPARATORS = re.compile(r"&&|;|\||\n")
WHOLE_SKIP = frozenset(["cd", "export", "set", "source", ".", "unset", "pushd", "popd"])  # a setup step: the whole of it, its arguments too
WRAPPERS = frozenset(["sudo", "time", "env", "nohup"])  # the program is the next word
SHELL_WORDS = frozenset(["if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case", "esac", "function", "!", "{", "}"])
TOKEN = re.compile(r"\s*(?:\"((?:[^\"\\]|\\.)*)\"|'([^']*)'|(\S+))")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
PATCH_FILE = re.compile(r"^\*\*\* (Update|Add|Delete) File: (.+)$", re.M)
SHELL_END = re.compile(r"\n?<shellId: [^>\n]*>\s*$")
EXIT_CODE = re.compile(r"exit code (-?\d+)>\s*$")


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _given(call: Dict[str, Any]) -> Any:
    """What the agent gave the call: a dict (a JSON object), a string (the text of a JSON string, as a patch; or a text that is not JSON), else None."""
    value = call.get("toolInput")
    if isinstance(value, str):
        if len(value) > DIFF_TEXT:
            return value
        try:
            found = json.loads(value)
        except (ValueError, TypeError, RecursionError):
            return value
        return found if isinstance(found, (dict, str)) else None
    return value if isinstance(value, (dict, str)) else None


def _items(call: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The items of the result: dicts only, at most `PARTS_MAX`. A result that is a text becomes one text item; any other shape is nothing."""
    content = call.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [item for item in content[:PARTS_MAX] if isinstance(item, dict)] if isinstance(content, list) else []


def _text_of(item: Dict[str, Any]) -> str:
    return item["text"] if item.get("type") == "text" and isinstance(item.get("text"), str) else ""


def _meta_of(call: Dict[str, Any]) -> Dict[str, Any]:
    return call["_meta"] if isinstance(call.get("_meta"), dict) else {}


def _command_of(given: Any) -> str:
    """The command a `run` call was given: the first of `COMMAND_KEYS` in its input (a text input is not taken for one)."""
    if isinstance(given, dict):
        for key in COMMAND_KEYS:
            if isinstance(given.get(key), str):
                return given[key]
    return ""


def _patch_of(given: Any) -> str:
    """The text of a patch (`*** Begin Patch`) an edit was given, as a string or in a field of an object; else empty."""
    values = [given] + (list(given.values())[:8] if isinstance(given, dict) else [])
    return next((value for value in values if isinstance(value, str) and "*** Begin Patch" in value[:200]), "")


def _patch_files(patch: str) -> List[Tuple[str, str]]:
    """`(operation, path)` of each file section of a patch, in order (at most `DIFF_FILES`)."""
    return [(found.group(1), found.group(2).strip()) for found in PATCH_FILE.finditer(patch[:DIFF_TEXT * 4])][:DIFF_FILES]


def _relative(value: str, root: Optional[Path]) -> str:
    """`value` as a path below `root` when it is one (also with the home folder masked, as a path read back from the stream file is); else as it is."""
    flat = value.strip().replace("\\", "/")
    if root is not None:
        plain = str(root).replace("\\", "/").rstrip("/") + "/"
        for folder in (plain, redact.path(plain.rstrip("/")) + "/"):
            if flat.startswith(folder) and len(flat) > len(folder):
                return flat[len(folder):]
    return flat


def program_of(command: str) -> Tuple[str, str]:
    """`(word, rest)` of a command: the program of the first command that is not a setup step (`cd`, `export`, `set`, `source`, `.`, `X=1`, `sudo`, `time`, `env`), without its folder and its `.exe`
    (at most `WORD_CAP` characters), and what follows the program in the command, on one line. Commands are split on `&&`, `;`, `|` and newlines; quotes are read only to take a program path with
    spaces whole. `("", "")`: no command, or only setup steps. Looks at the first `SCAN_CAP` characters; never raises."""
    try:
        text = command[:SCAN_CAP]
        starts = [0] + [found.end() for found in SEPARATORS.finditer(text)]
        ends = [found.start() for found in SEPARATORS.finditer(text)] + [len(text)]
        for begin, end in zip(starts, ends):
            at, wrapped = begin, False
            while at < end:
                found = TOKEN.match(text, at, end)
                if not found:
                    break
                at = found.end()
                value = next((group for group in found.groups() if group is not None), "").strip()
                value = value.lstrip("({").strip()
                if not value:
                    continue
                if value.startswith("#"):
                    break  # a comment: the rest of the line
                if wrapped and value.startswith("-"):
                    continue  # an option of `sudo` or `time`
                if value in WHOLE_SKIP:
                    break
                if value in WRAPPERS:
                    wrapped = True
                    continue
                if ASSIGN.match(value) or value in SHELL_WORDS:
                    continue
                name = re.split(r"[\\/]", value)[-1]
                if name.lower().endswith(".exe"):
                    name = name[:-4]
                if not name:
                    break
                tail = command[at:at + TARGET_CAP * 4]
                return name[:WORD_CAP], " ".join(tail.split())
        return "", ""
    except Exception:  # noqa: BLE001 - a command comes from outside; the line is shown without a program
        return "", ""


def kind_of(call: Dict[str, Any], given: Any = None, created: bool = False) -> str:
    """One of `KINDS`. From the kind the host gave (`_meta.toolKind`), else a subagent, else the tool's name and display name by the rules of `kindOf` in `web/live.js`. An edit that only adds new files
    (`created`, or a patch with only `*** Add File:` sections, or a create tool) is `create`."""
    meta = _meta_of(call)
    given = _given(call) if given is None else given
    base = ""
    if meta.get("subagentChatUri") or meta.get("subagentAgentName") or any(item.get("type") == "subagent" for item in _items(call)):
        return "agent"
    tool_kind = meta.get("toolKind")
    if tool_kind in ("read", "search"):
        base = tool_kind
    elif tool_kind == "terminal":
        base = "run"
    else:
        text = (str(call.get("toolName") or "") + " " + str(call.get("displayName") or "")).lower()[:300]
        base = "run" if RUN_NAME.search(text) else "edit" if EDIT_NAME.search(text) else "search" if SEARCH_NAME.search(text) else "web" if WEB_NAME.search(text) else "read" if READ_NAME.search(text) else "other"
    if base != "edit":
        return base
    ops = {operation for operation, _path in _patch_files(_patch_of(given))}
    name = str(call.get("toolName") or "").lower()[:100]
    if created or ops == {"Add"} or (CREATE_NAME.search(name) and not re.search(r"dir|folder", name)):
        return "create"
    return "edit"


def _diff_texts(items: List[Dict[str, Any]]) -> List[str]:
    """The result texts that are a git-style diff."""
    found = []
    for item in items:
        text = _text_of(item)
        if text.startswith("diff --git ") or "\ndiff --git " in text[:DIFF_TEXT * 4]:
            found.append(text)
    return found


def parse_diff(text: str, root: Optional[Path] = None, keep: int = 0) -> Tuple[List[Dict[str, Any]], bool]:
    """The files of a git-style diff text: `[{path, new, gone, add, del, lines}]` and whether anything was left out. One pass over at most `DIFF_TEXT * 4` characters. `lines` of a file are its lines from the first
    `@@` on, as the unified diff of the Changes tab (`desk.changes.diff.lines`) holds them, at most `keep` over all the files (0: none are kept, only counted). The path comes from the `+++ b<path>` line
    (`--- a<path>` for a deleted file); a path under `root` is made relative. `add` and `del` count the lines of the hunks that start with `+` and `-`. A text with no `diff --git` line gives no file."""
    files: List[Dict[str, Any]] = []
    left_out = False
    room = keep
    cur: Optional[Dict[str, Any]] = None
    hunk = False

    def close() -> None:
        if cur is None:
            return
        while cur["lines"] and not cur["lines"][-1]:
            cur["lines"].pop()
        path = cur.pop("_old") if cur["gone"] and cur["_old"] else cur["path"] or cur["_old"]
        found = _relative(path, root)
        cur["path"] = found[1:] if root is not None and found.startswith("/") and found == path.strip().replace("\\", "/") and not Path(found).exists() and (root / found[1:]).exists() else found  # `+++ b/src/x` of plain git: the `b/` is a side, not a folder (Copilot writes `b` + an absolute path)
        cur.pop("_old", None)

    for line in text[:DIFF_TEXT * 4].split("\n"):
        if line.startswith("diff --git "):
            close()
            if len(files) >= DIFF_FILES:
                cur, left_out = None, True
                break
            fallback = line[11:].rpartition(" b")[2]
            cur = {"path": fallback, "new": False, "gone": False, "add": 0, "del": 0, "lines": [], "_old": ""}
            files.append(cur)
            hunk = False
            continue
        if cur is None:
            continue
        if not hunk:
            if line.startswith("@@"):
                hunk = True
            elif line.startswith("create file mode") or line.startswith("new file mode"):
                cur["new"] = True
                continue
            elif line.startswith("deleted file mode"):
                cur["gone"] = True
                continue
            elif line.startswith("--- "):
                old = line[4:].strip()
                if old in ("/dev/null", "a/dev/null"):
                    cur["new"] = True
                else:
                    cur["_old"] = old[1:] if old.startswith("a") else old
                continue
            elif line.startswith("+++ "):
                new = line[4:].strip()
                if new in ("/dev/null", "b/dev/null"):
                    cur["gone"] = True
                else:
                    cur["path"] = new[1:] if new.startswith("b") else new
                continue
            else:
                continue
        if line.startswith("+"):
            cur["add"] += 1
        elif line.startswith("-"):
            cur["del"] += 1
        if room > 0:
            cur["lines"].append(line)
            room -= 1
        else:
            left_out = True
    close()
    return files, left_out


def _clip(value: Any, cap: int, keep_indent: bool = False) -> Tuple[str, int]:
    """`value` redacted and cut at `cap` characters: (text, how many characters were left out). Blank lines at both ends and spaces at the end are taken off; the spaces in front of the first line stay when `keep_indent`."""
    raw = value if isinstance(value, str) else str(value or "")
    source = raw[:cap * 2 + 200]
    text = redact.text(source)
    text = text.strip("\n") if keep_indent else text.strip()
    left = max(0, len(raw) - len(source))
    if len(text) > cap:
        left += len(text) - cap
        text = text[:cap]
    return text.rstrip(), left


def _output_of(items: List[Dict[str, Any]]) -> Tuple[str, Optional[int], bool]:
    """`(output, exit code, known)` of a command's result: the terminal's output, else the first text without its last `<shellId: ...>` line."""
    code: Optional[int] = None
    for item in items:
        if item.get("type") == "terminal" and isinstance(item.get("result"), dict):
            result = item["result"]
            if isinstance(result.get("exitCode"), int) and not isinstance(result["exitCode"], bool):
                code = result["exitCode"]
            return (result["preview"] if isinstance(result.get("preview"), str) else ""), code, True
    for item in items:
        text = _text_of(item)
        if text or item.get("type") == "text":
            found = EXIT_CODE.search(text[-200:])
            return SHELL_END.sub("", text), int(found.group(1)) if found else None, True
    return "", None, False


def _line_count(text: str) -> int:
    return text.count("\n") + 1 if text.strip() else 0


def _facts(call: Dict[str, Any], given: Any, st: str, root: Optional[Path]) -> Dict[str, Any]:
    """The numbers of the closed line of a call (`kind`, `word`, `target` for a command, `add`, `del`, `files`, `hits`, `exit`, `lines`): cheap, bounded, and only what is known. The numbers come from the
    result, so only a call that completed has them."""
    items = _items(call)
    ended = st in ("done", "fail")  # a diff and a search result count only when the call completed; the output of a command is there while it runs
    files: List[Dict[str, Any]] = []
    kind = kind_of(call, given)
    if ended and items and kind in ("edit", "create"):
        files = parse_diff("\n".join(_diff_texts(items)), root)[0]
        kind = "create" if files and all(one["new"] for one in files) else kind
    out: Dict[str, Any] = {"kind": kind}
    if kind == "run":
        word, rest = program_of(_command_of(given))
        if word:
            out["word"] = cut(word, WORD_CAP)[0]
            out["rest"] = rest
        if items:
            output, code, known = _output_of(items)
            if code is not None:
                out["exit"] = code
            if known and _line_count(output):
                out["lines"] = _line_count(output)
    elif kind in ("edit", "create") and ended and items:
        if files:
            out["add"], out["del"] = sum(one["add"] for one in files), sum(one["del"] for one in files)
            if len(files) > 1:
                out["files"] = len(files)
        else:
            edits = [item for item in items if item.get("type") == "fileEdit" and isinstance(item.get("diff"), dict)]
            if edits:
                out["add"], out["del"] = sum(_count(item["diff"].get("added")) for item in edits), sum(_count(item["diff"].get("removed")) for item in edits)
                if len(edits) > 1:
                    out["files"] = len(edits)
    elif kind == "search" and ended and items and any(item.get("type") == "text" for item in items):
        out["hits"] = sum(1 for item in items for line in _text_of(item)[:DIFF_TEXT * 4].split("\n") if line.strip())
        out["hits"] = min(out["hits"], HITS_MAX)
    return out


def _content_sig(call: Dict[str, Any]) -> Tuple[Any, ...]:
    """What tells that the result of a call is not the one an item was built from: the type and size of each item (a result can change while the call runs)."""
    content = call.get("content")
    if isinstance(content, str):
        return (len(content),)
    if not isinstance(content, list):
        return ()
    sig: List[Any] = [len(content)]
    for item in content[:PARTS_MAX]:
        if not isinstance(item, dict):
            sig.append(0)
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        sig.append((item.get("type"), len(item["text"]) if isinstance(item.get("text"), str) else 0, len(result["preview"]) if isinstance(result.get("preview"), str) else 0, result.get("exitCode")))
    return tuple(sig)


def _file_part(text: str, root: Optional[Path]) -> Optional[Dict[str, Any]]:
    """A read result in the shape of a one-file diff (a `diff --git` header, then every line of the file after the first `@@` with a space in front) as the file's own text; None: another shape."""
    head = text[:DIFF_TEXT * 4].lstrip("\n")
    if not head.startswith("diff --git "):
        return None
    lines = head.split("\n")
    at = next((number for number, line in enumerate(lines) if line.startswith("@@")), -1)
    if at < 0:
        return None
    path = ""
    for line in lines[:at]:
        if line.startswith("+++ ") and line[4:].strip() not in ("/dev/null", "b/dev/null"):
            path = line[4:].strip()[1:]
        elif line.startswith("--- ") and not path and line[4:].strip() not in ("/dev/null", "a/dev/null"):
            path = line[4:].strip()[1:]
    body = [line[1:] if line else "" for line in lines[at + 1:] if not line.startswith("@@") and not line.startswith("\\")]
    while body and not body[-1]:
        body.pop()  # the end of the text, not lines of the file
    shown, left = _clip("\n".join(body), DETAIL_TEXT, True)
    part: Dict[str, Any] = {"k": "file", "path": cut(_relative(path, root), TARGET_CAP, True)[0], "text": shown, "lines": len(body)}
    if left:
        part["cut"] = left
    return part


def detail(call: Dict[str, Any], root: Optional[Path] = None) -> Dict[str, Any]:
    """What an opened tool call shows (1.8.x): its kind, program, the whole command, the words the agent gave, its input, and its result in order (`parts`), every string redacted and bounded;
    `cut: true` when anything was left out. `call`: the `toolCall` of a part, from the board's memory or the stream file. A shape not expected gives less; `{}` for a call that is not a dict."""
    try:
        return _detail(call, root) if isinstance(call, dict) else {}
    except Exception:  # noqa: BLE001 - the result of a tool comes from outside
        return {}


def _detail(call: Dict[str, Any], root: Optional[Path]) -> Dict[str, Any]:
    given = _given(call)
    st = state_of(call, False)
    items = _items(call)
    kind = kind_of(call, given)
    files: List[Dict[str, Any]] = []
    over = False
    diff_texts = _diff_texts(items) if kind in ("edit", "create") else []
    if diff_texts:
        safe, left = _clip("\n".join(diff_texts), DIFF_TEXT, True)  # redacted first: the lines of the diff are shown
        files, over = parse_diff(safe, root, DIFF_LINES)
        over = over or bool(left)
        kind = "create" if files and all(one["new"] for one in files) else kind
    out: Dict[str, Any] = {"id": str(call.get("toolCallId") or "")[:200], "kind": kind, "st": st, "name": cut(words(call.get("displayName")) or words(call.get("toolName")), 60)[0]}
    any_cut = False
    command = _command_of(given) if kind == "run" else ""
    if command:
        word = program_of(command)[0]
        if word:
            out["word"] = cut(word, WORD_CAP)[0]
        shown, left = _clip(command, DETAIL_CMD)
        out["command"] = shown
        if left:
            out["command_cut"] = True
            any_cut = True
    why = words(given.get("description")) if isinstance(given, dict) else ""
    why = why or words(call.get("intention"))
    if why:
        out["why"] = cut(why, SAY_CAP)[0]
    if given is not None and not (kind == "run" and isinstance(given, dict) and set(given) <= {"command"}):
        try:
            shown_input = given if isinstance(given, str) else json.dumps(given, indent=2, ensure_ascii=False, default=str)
        except (TypeError, ValueError, RecursionError):
            shown_input = ""
        shown, left = _clip(shown_input, DETAIL_CMD)
        if shown:
            out["input"] = shown
            if left:
                out["input_cut"] = True
                any_cut = True
    parts: List[Dict[str, Any]] = []
    terminal_out = ""
    has_diff = bool(diff_texts)
    diff_done = False
    for item in items:
        kind_item = str(item.get("type") or "unknown")[:40]
        stored = _count(item.get("cut")) if item.get("cut") is not True else 1
        if kind_item == "terminal":
            result = item.get("result") if isinstance(item.get("result"), dict) else None
            if result is None:
                continue
            terminal_out = result["preview"] if isinstance(result.get("preview"), str) else ""
            shown, left = _clip(terminal_out, DETAIL_TEXT, True)
            code = result.get("exitCode") if isinstance(result.get("exitCode"), int) and not isinstance(result.get("exitCode"), bool) else None
            part: Dict[str, Any] = {"k": "term", "exit": code, "text": shown, "lines": _line_count(terminal_out), "truncated": result.get("truncated") is True}
            if left + _count(result.get("cut")):
                part["cut"] = left + _count(result.get("cut"))
            parts.append(part)
            continue
        if kind_item == "fileEdit":
            if not has_diff:
                parts.append({"k": "other", "type": "fileEdit"})
            continue
        text = _text_of(item)
        if kind_item == "text":
            if any(one["k"] == "term" for one in parts):
                plain = SHELL_END.sub("", text)
                if (terminal_out.strip() and plain.strip().startswith(terminal_out.strip())) or not plain.strip():
                    continue  # the same output again, with the line that tells the shell's end
            if text in diff_texts:
                if not diff_done:
                    diff_done = True
                    parts.append({"k": "diff", "files": files, "cut": over})
                    any_cut = any_cut or over
                continue
            if kind == "read":
                filed = _file_part(text, root)
                if filed is not None:
                    parts.append(filed)
                    continue
            if not text.strip() and not stored:
                continue
            shown, left = _clip(text, DETAIL_TEXT, True)
            part = {"k": "text", "text": shown, "lines": _line_count(text)}
            if left + stored:
                part["cut"] = left + stored
            parts.append(part)
            continue
        parts.append({"k": "other", "type": kind_item})
        if kind_item == "more" or item.get("cut") is True:
            any_cut = True
    out["parts"] = parts
    if isinstance(call.get("error"), dict) and call["error"].get("message"):
        out["error"] = cut(call["error"]["message"], ERROR_CAP * 4)[0]
    elif isinstance(call.get("error"), str) and call["error"]:
        out["error"] = cut(call["error"], ERROR_CAP * 4)[0]
    if st == "fail":
        reason = words(call.get("reasonMessage")) or words(call.get("reason"))
        if reason:
            out["reason"] = cut(reason, SAY_CAP)[0]
    if any_cut or any(part.get("cut") for part in parts):
        out["cut"] = True
    return out


def tool_item(call: Dict[str, Any], ident: str, active: bool, root: Optional[Path]) -> Dict[str, Any]:
    st = state_of(call, active)
    if not active and st in ("run", "wait"):
        st = "stop"  # its turn is over and the host never said how the call ended (stopped, skipped): not running, and not known to have worked
    first = (words(call.get("pastTenseMessage")) if st in ("done", "fail") else "") or words(call.get("intention")) or words(call.get("invocationMessage")) or words(call.get("displayName"))
    say, said = cut(first, SAY_CAP)
    target, cut_target = target_of(call, root)
    name, _ = cut(words(call.get("displayName")) or words(call.get("toolName")), 60)
    item: Dict[str, Any] = {"id": ident, "k": "tool", "tool": str(call.get("toolName") or "")[:60], "name": name, "st": st}
    given = _given(call)
    facts = _facts(call, given, st, root)
    rest = facts.pop("rest", None)
    if "word" in facts and not (isinstance(given, dict) and any(isinstance(given.get(key), (str, list)) and given.get(key) for key in PATH_KEYS)):  # a command: the line says the program once (`word`), the target is what follows it
        target, cut_target = cut(rest, TARGET_CAP) if rest else ("", False)
    elif facts["kind"] == "search" and isinstance(given, dict) and isinstance(given.get("pattern"), str) and given["pattern"].strip():
        target, cut_target = cut(given["pattern"], TARGET_CAP)  # what is looked for says more than where (`paths` is often the whole repository)
    elif facts["kind"] in ("edit", "create"):
        found = _patch_files(_patch_of(given))
        if found:
            target, cut_target = cut(_relative(found[0][1], root), TARGET_CAP, True)
    if say:
        item["say"] = say
    reason = call.get("reason") if str(call.get("status") or "") == "cancelled" else None
    if isinstance(reason, str) and reason:
        item["reason"] = reason[:40]  # why a call was cancelled (`denied`, `result-denied`, ...): a call the person refused is drawn as stopped, not failed, before it is opened
    if call.get("confirmed") == "user-action":
        item["ok"] = "you"  # B8: it waited for a person, who let it go
    if target and target != say:  # words of Copilot, not a place: once is enough
        item["target"] = target
    item.update(facts)
    if said or cut_target:
        item["cut"] = True
    return item


def said_item(turn: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What the person said to start a turn: a small mark in the stream, with the words in its card. None for a turn no person started. A turn read from the stream file (`chatstream.read`) has
    no `message`: its `text` and `files` are the person's words, so it counts as the person's (a turn no person started has no text there)."""
    message = _message_of(turn)
    if (message.get("origin") or {}).get("kind") != "user":
        return None
    text, was_cut = cut(message.get("text"), TEXT_CAP)
    if not text:
        return None
    item: Dict[str, Any] = {"id": f"{turn.get('id')}.me", "k": "me", "text": text}
    files = [str(entry["label"]) for entry in message.get("attachments") or [] if isinstance(entry, dict) and entry.get("label")]
    if files:
        item["files"] = files
    if was_cut:
        item["cut"] = True
    return item


def _message_of(turn: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(turn.get("message"), dict):
        return turn["message"]
    if "text" in turn:  # a turn of the stream file
        files = turn.get("files") if isinstance(turn.get("files"), list) else []
        return {"origin": {"kind": "user"}, "text": turn.get("text"), "attachments": [{"label": name} for name in files if isinstance(name, str)]}
    return {}


def _own_mark(part: Dict[str, Any]) -> List[int]:
    """The times a part carries itself (a part read from the stream file: `t0`, `t1`); 0: unknown."""
    return [value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0 for value in (part.get("t0"), part.get("t1"))]


def part_item(part: Dict[str, Any], ident: str, running: bool, last: bool, mark: Optional[List[int]], root: Optional[Path]) -> Optional[Dict[str, Any]]:
    """The item of one part of a turn, or None (an empty text, a part of a kind not shown). `running`: the turn runs; `last`: this is its last part and it runs; `mark`: when it began and ended."""
    kind = part.get("kind")
    if kind == "markdown":
        text, was_cut = cut(part.get("content"), TEXT_CAP)
        if not text:
            return None
        item: Dict[str, Any] = {"id": ident, "k": "text", "text": text, "blocks": mdtree.parse(text)["blocks"]}  # the page draws it as it draws the documents of a task
        if was_cut or part.get("cut") is True:
            item["cut"] = True
        if last:
            item["live"] = True
    elif kind == "reasoning":
        text, was_cut = cut(part.get("content"), THINK_CAP)
        item = {"id": ident, "k": "think", "run": last}
        if text:
            item["text"] = text
            item["blocks"] = mdtree.parse(text)["blocks"]  # drawn as Markdown when opened (a thought often has **bold** headings)
        took = part.get("duration")
        if isinstance(took, (int, float)) and not isinstance(took, bool) and took > 0:
            item["ms"] = int(took)  # how long the host says it thought; the page prefers it to the gap to the next item
        if was_cut or part.get("cut") is True:
            item["cut"] = True
    elif kind == "toolCall" and isinstance(part.get("toolCall"), dict):
        call = part["toolCall"]
        if isinstance(part.get("_meta"), dict) and not isinstance(call.get("_meta"), dict):  # `sub_calls` reads the meta from the part too
            call = dict(call, _meta=part["_meta"])
        item = tool_item(call, ident, running, root)
    elif kind == "inputRequest" and isinstance(part.get("request"), dict):
        item = ask_item(part, ident)
    elif kind == "error":  # 1.8.5: the turn ended in an error; the page draws it red, with its words
        text, _was_cut = cut(part.get("message"), ERROR_CAP)
        item = {"id": ident, "k": "err", "text": text, "resumable": part.get("resumable") is True}
    else:
        return None
    if mark and mark[0]:
        item["t0"] = mark[0]
        if mark[1] and item["k"] in ("tool", "ask"):
            item["t1"] = mark[1]
    if item["k"] == "tool" and mark and len(mark) > 2 and mark[2]:
        item["okAt"] = mark[2]  # B8: when the person let it go
    return item


ASK_LINE = 300  # characters of an answer on the closed line of a question


def answer_words(value: Any, options: Optional[List[Dict[str, Any]]] = None) -> str:
    """An answer as words: the host's `{state, value: {kind, value}}` unwrapped, an option id turned into its label, a list joined. Empty: no answer."""
    labels = {str(item.get("id")): str(item.get("label") or "") for item in options or [] if isinstance(item, dict)}
    for _ in range(4):
        if isinstance(value, dict) and "value" in value:
            value = value["value"]
        else:
            break
    if isinstance(value, dict):
        value = value.get("selectedValues") or value.get("selected") or value.get("text") or value.get("label") or ""
    if isinstance(value, list):
        return ", ".join(answer_words(one, options) for one in value[:20] if answer_words(one, options))
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value or "")
    return labels.get(text) or text


def ask_item(part: Dict[str, Any], ident: str) -> Dict[str, Any]:
    """A question of the agent (B8): `{id, k: ask, text, qs: [{title, answer}], st}`. `st`: `wait` (not answered yet), `done` (answered), `skip` (declined or cancelled). `text`: the message, else
    the first question's title. The answers are words (`answer_words`), each cut to `ASK_LINE`."""
    request = part["request"]
    answers = request.get("answers") if isinstance(request.get("answers"), dict) else {}
    qs = []
    for question in request.get("questions") or [] if isinstance(request.get("questions"), list) else []:
        if not isinstance(question, dict):
            continue
        title = words(question.get("title") or question.get("message") or "")
        qs.append({"title": cut(title, SAY_CAP)[0], "answer": cut(answer_words(answers.get(str(question.get("id"))), question.get("options")), ASK_LINE)[0]})
    text = cut(words(request.get("message") or request.get("title") or (qs[0]["title"] if qs else "")), SAY_CAP)[0]
    response = part.get("response")
    st = "wait" if response is None else "done" if response == "accept" else "skip"
    return {"id": ident, "k": "ask", "text": text, "qs": qs[:20], "st": st}


def _thought_ends(items: List[Dict[str, Any]]) -> None:
    """A thought ends where the next item began."""
    for at, item in enumerate(items):
        if item["k"] == "think" and not item.get("run") and item.get("t0") and at + 1 < len(items) and items[at + 1].get("t0"):
            item["t1"] = items[at + 1]["t0"]


def _signature(part: Dict[str, Any], last: bool, running: bool, mark: List[int]) -> Tuple[Any, ...]:
    """What tells that a part is not the one an item was built from: cheap (no redaction, no parse). A text grows, so its length is in; a call changes by its status and the words it says of itself."""
    kind = part.get("kind")
    if kind in ("markdown", "reasoning"):
        return (kind, len(part["content"]) if isinstance(part.get("content"), str) else 0, last, tuple(mark), part.get("duration") if kind == "reasoning" else None)
    call = part.get("toolCall")
    if kind == "toolCall" and isinstance(call, dict):
        return (kind, running, call.get("status"), call.get("success"), tuple(len(str(call.get(key) or "")) for key in ("pastTenseMessage", "intention", "invocationMessage", "displayName", "toolInput")), _content_sig(call), tuple(mark), call.get("confirmed"))
    if kind == "inputRequest" and isinstance(part.get("request"), dict):
        return (kind, part.get("response"), json.dumps(part["request"].get("answers"), sort_keys=True, default=str)[:2000], len(json.dumps(part["request"], default=str)), tuple(mark))
    if kind == "error":
        return (kind, len(str(part.get("message") or "")), part.get("resumable") is True)
    return ("skip", kind if isinstance(kind, str) else "")


def last_turn(state: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], bool]:
    """The turn the Live tab shows: the one that runs, else the last that finished. (turn, it runs)"""
    active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
    if active:
        return active, True
    turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)] if isinstance(state.get("turns"), list) else []
    return (turns[-1], False) if turns else (None, False)


def _walk(turn: Dict[str, Any], running: bool, marks: Dict[str, List[int]], root: Optional[Path], old: Dict[str, Tuple[Any, Optional[Dict[str, Any]], int]], rev: int) -> List[Tuple[str, Optional[Dict[str, Any]], int, Any]]:
    """Every part of a turn as `(id, item, v, signature)` in order, the person's message first. `old`: the entries of the last walk (id -> (signature, item, v)); one whose signature is the same is
    taken as it is, so an item is built once per change (its `v` is the `rev` it last changed at). The item may be None (a part that shows nothing); it is kept, so it is not built again."""
    parts = [part for part in (turn.get("responseParts") if isinstance(turn.get("responseParts"), list) else turn.get("parts") if isinstance(turn.get("parts"), list) else []) if isinstance(part, dict)]
    base = int(turn.get("dropped") or 0) if isinstance(turn.get("dropped"), int) else 0
    out: List[Tuple[str, Optional[Dict[str, Any]], int, Any]] = []
    message = _message_of(turn)
    ident = f"{turn.get('id')}.me"
    sig: Any = ("me", len(str(message.get("text") or "")), len(message.get("attachments") or []), (message.get("origin") or {}).get("kind"))
    held = old.get(ident)
    out.append((ident, held[1], held[2], sig) if held and held[0] == sig else (ident, said_item(turn), rev, sig))
    for at, part in enumerate(parts):
        index = part["i"] if isinstance(part.get("i"), int) and not isinstance(part.get("i"), bool) else base + at
        ident = part_id(part) or f"{turn.get('id')}.{index}"
        last = running and at == len(parts) - 1
        mark = marks.get(ident)
        if not (mark and mark[0]):
            mark = _own_mark(part)
        sig = _signature(part, last, running, mark)
        held = old.get(ident)
        if held and held[0] == sig:
            out.append((ident, held[1], held[2], sig))
        else:
            out.append((ident, part_item(part, ident, running, last, mark, root), rev, sig))
    shown = [at for at, entry in enumerate(out) if entry[1] is not None]
    for place, at in enumerate(shown[:-1]):  # a thought ends where the next item began; in the stored item itself, and a thought whose end moved has changed
        item, after = out[at][1], out[shown[place + 1]][1]
        if item["k"] == "think" and not item.get("run") and item.get("t0") and after.get("t0") and item.get("t1") != after["t0"]:
            item["t1"] = after["t0"]
            out[at] = (out[at][0], item, rev, out[at][3])
    return out


def items_of(turn: Dict[str, Any], running: bool, marks: Dict[str, List[int]], root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """ALL the items of one turn, oldest first, the person's message first. `turn`: a turn of the board's memory, or one read from the stream file (`chatstream.read`; its parts carry `i`, and `t0` / `t1`
    when the board saw them). A part with no id gets `<turn id>.<absolute index>`."""
    return [item for _ident, item, _v, _sig in _walk(turn, running, marks, root, {}, 0) if item is not None]


def _collect(walked: List[Tuple[str, Optional[Dict[str, Any]], int, Any]], have: int, whole: Any, fresh: Dict[str, Tuple[Any, Optional[Dict[str, Any]], int]]) -> List[Dict[str, Any]]:
    """The items of a walk as the page gets them: new dicts, an unchanged one (`v <= have`) that may be a stub (see `build`) as `{id, k, same: true}`. `fresh` gets the entries for the memo."""
    items: List[Dict[str, Any]] = []
    for ident, item, v, sig in walked:
        fresh[ident] = (sig, item, v)
        if item is None:
            continue
        stub = v <= have and ident not in whole and (item["k"] in ("text", "think", "err", "me") or (item["k"] == "tool" and item.get("st") in ("done", "fail", "stop")))
        items.append({"id": item["id"], "k": item["k"], "same": True} if stub else dict(item))
    return items


def build(state: Dict[str, Any], marks: Dict[str, List[int]], root: Optional[Path] = None, memo: Optional[Dict[str, Any]] = None, have: int = -1, rev: int = 0,
          whole: Any = ()) -> Dict[str, Any]:
    """`{items, more, started, before, turn}`: the last turn only (the one that runs, else the last that finished) with all the items the board's memory holds of it, oldest first.
    `before`: `{turn, i}` (the absolute index of the first part sent) when parts of the turn fell out of memory (`dropped`), else None; `more` is `before is not None` (the older steps are in the
    stream file: `VsLink.older`). `turn`: the id of that turn: the page keeps the items it has seen of a turn (the memory drops the oldest as the turn grows) and starts anew when the id changes.

    `memo`: a dict the caller keeps for the chat; each item is built once per change (see `_walk`) and entries of parts no longer sent are forgotten. `rev`: the number of the chat's last change.
    `have`: the `v` the page already holds; an item that has not changed since (`v <= have`) is sent as the stub `{id, k, same: true}`, but only a text, thought, error, message or a tool call that
    ended (`done`, `fail`, `stop`): a call that runs or waits is always whole, and so is a call in `whole` (the caller puts a subagent's steps on it). A stub never carries `sub`. -1: everything whole.
    The dicts returned are new: the caller adds to them."""
    turn, running = last_turn(state)
    if turn is None:
        return {"items": [], "more": False, "started": "", "before": None, "turn": ""}
    if have > rev:
        have = -1  # the page is ahead of this chat (it was read again, the count began anew): it holds nothing we can name
    kept: Dict[str, Tuple[Any, Optional[Dict[str, Any]], int]] = memo if memo is not None else {}
    fresh: Dict[str, Tuple[Any, Optional[Dict[str, Any]], int]] = {}
    items = _collect(_walk(turn, running, marks, root, kept, rev), have, whole, fresh)
    if memo is not None:
        memo.clear()
        memo.update(fresh)
    base = int(turn.get("dropped") or 0) if isinstance(turn.get("dropped"), int) else 0
    pointer = {"turn": str(turn.get("id") or ""), "i": base} if base > 0 else None
    return {"items": items, "more": pointer is not None, "started": str(turn.get("startedAt") or "") if running else "", "before": pointer, "turn": str(turn.get("id") or "")}


def round_facts(state: Dict[str, Any]) -> Dict[str, Any]:
    """The live numbers of the last turn, for the title of the round that stays at the top of the Live tab (B9): `{calls, credits}`. `calls`: its tool calls, the ones that fell out of memory
    too; `credits`: how much the session's total grew since the turn before ended, None when the host did not say both (as the receipt counts it)."""
    from . import chatctx  # local: only this function needs it
    turn, _running = last_turn(state)
    if turn is None:
        return {"calls": 0, "credits": None}
    parts = turn.get("responseParts") if isinstance(turn.get("responseParts"), list) else []
    calls = sum(1 for part in parts if isinstance(part, dict) and part.get("kind") == "toolCall") + (int(turn.get("droppedCalls") or 0) if isinstance(turn.get("droppedCalls"), int) else 0)
    done = [one for one in state.get("turns") or [] if isinstance(one, dict) and one is not turn]
    before = done[-1] if done else None
    now = chatctx.session_total(turn.get("usage"))
    then = chatctx.session_total(before.get("usage")) if before else (0.0 if not done else None)
    return {"calls": calls, "credits": round(max(0.0, now - then), 2) if now is not None and then is not None else None}


def all_turns(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every turn of a chat state in memory, oldest first, the one that runs last."""
    turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)] if isinstance(state.get("turns"), list) else []
    if isinstance(state.get("activeTurn"), dict):
        turns.append(state["activeTurn"])
    return turns


def build_all(state: Dict[str, Any], marks: Dict[str, List[int]], root: Optional[Path] = None, memo: Optional[Dict[str, Any]] = None, have: int = -1, rev: int = 0) -> Dict[str, Any]:
    """`{items, turn, dropped}`: the items of ALL the turns the memory holds, in order (the side panel of a subagent: usually one turn), memoised and stubbed as `build` does (`memo`, `have`, `rev`).
    The first item of each turn is what started it, as the person's own words: a subagent's turn was started by a tool call (its prompt), the page shows it as the task the subagent was given.
    `turn`: the id of the last turn; `dropped`: parts fell out of memory in some turn (the file has them: the caller may read it)."""
    turns = all_turns(state)
    active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
    if have > rev:
        have = -1
    kept: Dict[str, Tuple[Any, Optional[Dict[str, Any]], int]] = memo if memo is not None else {}
    fresh: Dict[str, Tuple[Any, Optional[Dict[str, Any]], int]] = {}
    items: List[Dict[str, Any]] = []
    for turn in turns:
        message = turn.get("message") if isinstance(turn.get("message"), dict) else {}
        asked = dict(turn, message=dict(message, origin={"kind": "user"})) if message.get("text") else turn
        items.extend(_collect(_walk(asked, turn is active, marks, root, kept, rev), have, (), fresh))
    if memo is not None:
        memo.clear()
        memo.update(fresh)
    return {"items": items, "turn": str(turns[-1].get("id") or "") if turns else "", "dropped": any(isinstance(turn.get("dropped"), int) and turn["dropped"] > 0 for turn in turns)}


def latest(state: Dict[str, Any], marks: Dict[str, List[int]], root: Optional[Path] = None, count: int = LATEST) -> Dict[str, Any]:
    """`{items, more, started}`: the newest `count` items of the last turns, oldest first; `more`: there is something older. (What `build` was before the Live tab showed a whole turn; the steps of a subagent
    under its tool call were the newest few until B4a.)"""
    active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
    turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)] + ([active] if active else [])
    items: List[Dict[str, Any]] = []
    more = len(state.get("turns") or []) > 1 or bool(active and state.get("turns"))
    for turn in reversed(turns):
        running = turn is active
        parts = [part for part in turn.get("responseParts") or [] if isinstance(part, dict)]
        base = int(turn.get("dropped") or 0)
        if base:
            more = True
        whole = True
        for at in range(len(parts) - 1, -1, -1):
            if len(items) >= count:
                more, whole = True, False
                break
            part = parts[at]
            ident = part_id(part) or f"{turn.get('id')}.{base + at}"
            item = part_item(part, ident, running, running and at == len(parts) - 1, marks.get(ident), root)
            if item is not None:
                items.append(item)
        said = said_item(turn) if whole else None
        if said:
            items.append(said)
        if len(items) >= count:
            more = more or len(turns) > 1
            break
    items.reverse()
    _thought_ends(items)
    return {"items": items, "more": more, "started": str(active.get("startedAt") or "") if active else ""}


RECEIPT_FILES = 200  # files a receipt lists (the rest are counted in `more`)
RECEIPT_CALLS = 20  # tool call ids kept for one file: what the page opens to show its diff


def call_files(call: Dict[str, Any], root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """The files an edit or create call that completed changed: `[{path, add, del, new}]`, as its closed line counts them (`_facts`): from the git-style diff of its result, else from the host's
    `fileEdit` items (their `after` uri, else `before`, and their counts). Any other call, one that did not complete, or a result with neither: []."""
    given = _given(call)
    if state_of(call, False) not in ("done", "fail") or kind_of(call, given) not in ("edit", "create"):
        return []
    items = _items(call)
    files = parse_diff("\n".join(_diff_texts(items)), root)[0]
    if files:
        return [{"path": one["path"], "add": one["add"], "del": one["del"], "new": bool(one["new"])} for one in files if one.get("path")]
    out: List[Dict[str, Any]] = []
    for item in items:
        if item.get("type") != "fileEdit":
            continue
        side = item.get("after") if isinstance(item.get("after"), dict) else item.get("before") if isinstance(item.get("before"), dict) else {}
        path = ahp.uri_path(str(side.get("uri") or "")) if isinstance(side.get("uri"), str) else ""
        if not path:
            continue
        diff = item.get("diff") if isinstance(item.get("diff"), dict) else {}
        out.append({"path": _relative(path, root), "add": _count(diff.get("added")), "del": _count(diff.get("removed")), "new": not isinstance(item.get("before"), dict)})
    return out


def receipt(parts: List[Any], root: Optional[Path] = None) -> Dict[str, Any]:
    """What a turn did, for its receipt (B6): `{calls, files: [{path, add, del, new, calls}], add, del, more}`. `calls`: the tool calls among `parts` (a subagent is one call: its own steps are in
    its chat); `files`: each file the edit and create calls changed, in the order first changed, with the lines added and removed summed over the calls and the ids of those calls (at most
    `RECEIPT_CALLS`: the page opens them for the diff); `add`, `del`: over all the files; `more`: files past `RECEIPT_FILES`, which are counted in `add` and `del` but not listed. Only what the calls'
    results say: a file a command changed (`sed -i`, a script) is not in it. `parts` are the parts of one turn, from memory or from the stream file."""
    calls = 0
    files: Dict[str, Dict[str, Any]] = {}
    add = gone = 0
    for part in parts:
        call = part.get("toolCall") if isinstance(part, dict) and part.get("kind") == "toolCall" else None
        if not isinstance(call, dict):
            continue
        calls += 1
        ident = str(call.get("toolCallId") or part_id(part) or "")
        for one in call_files(call, root):
            add += one["add"]
            gone += one["del"]
            held = files.get(one["path"])
            if held is None:
                held = files[one["path"]] = {"path": one["path"], "add": 0, "del": 0, "new": one["new"], "calls": []}
            held["add"] += one["add"]
            held["del"] += one["del"]
            if ident and ident not in held["calls"] and len(held["calls"]) < RECEIPT_CALLS:
                held["calls"].append(ident)
    listed = list(files.values())
    return {"calls": calls, "files": listed[:RECEIPT_FILES], "add": add, "del": gone, "more": max(0, len(listed) - RECEIPT_FILES)}


SUB_SAID = 160  # characters of what a finished subagent said last, on its row
SUB_NOW = ("kind", "word", "target", "name")  # what of a tool item the row of a running subagent keeps


def _calls_of(turn: Any) -> List[Tuple[str, Dict[str, Any]]]:
    """The tool calls of a turn of the memory, `(id, call)`, oldest first (a call without an id gets `<turn id>.<index>`)."""
    parts = turn.get("responseParts") if isinstance(turn, dict) and isinstance(turn.get("responseParts"), list) else []
    base = int(turn.get("dropped") or 0) if isinstance(turn, dict) and isinstance(turn.get("dropped"), int) else 0
    out = []
    for at, part in enumerate(parts):
        if isinstance(part, dict) and part.get("kind") == "toolCall" and isinstance(part.get("toolCall"), dict):
            call = part["toolCall"]
            if isinstance(part.get("_meta"), dict) and not isinstance(call.get("_meta"), dict):
                call = dict(call, _meta=part["_meta"])
            out.append((part_id(part) or f"{turn.get('id')}.{base + at}", call))
    return out


def sub_status(state: Dict[str, Any], main_st: str) -> str:
    """`wait` while a tool call in the subagent's chat waits for a person, `fail` when the call that started it failed, `run` while its turn runs (or the call that started it does), else `done`."""
    active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
    if active and any(state_of(call, True) == "wait" for _ident, call in _calls_of(active)):
        return "wait"
    if main_st == "fail":
        return "fail"
    return "run" if active or main_st == "run" else "done"


def sub_summary(title: str, held: Optional[Dict[str, Any]], main_st: str, root: Optional[Path] = None) -> Dict[str, Any]:
    """What the page shows of a subagent on one row (1.8.x): `{title, st, calls, now?, said?}`. `calls`: the tool calls of its chat that the memory holds (a lower bound when `dropped` parts fell out);
    `now`: while it runs or waits, its newest tool call (`SUB_NOW` of its item); `said`: when it ended, its last text as one line of `SUB_SAID` characters. `held`: its cached chat, None while it is being read."""
    state = (held or {}).get("state") or {}
    st = sub_status(state, main_st)
    turns = all_turns(state)
    calls = [pair for turn in turns for pair in _calls_of(turn)]
    out: Dict[str, Any] = {"title": title, "st": st, "calls": len(calls)}
    if st in ("run", "wait"):
        if calls:
            item = tool_item(calls[-1][1], calls[-1][0], bool(state.get("activeTurn")), root)
            out["now"] = {key: item[key] for key in SUB_NOW if key in item}
    else:
        for turn in reversed(turns):
            texts = [part for part in turn.get("responseParts") or [] if isinstance(part, dict) and part.get("kind") == "markdown" and isinstance(part.get("content"), str) and part["content"].strip()]
            if texts:
                said = cut(words(texts[-1]["content"][:SUB_SAID * 4]), SUB_SAID)[0]  # plain: no marks or links, one line
                if said:
                    out["said"] = said
                break
    return out


def _call_error(state: Optional[Dict[str, Any]], ident: str) -> str:
    """The error message of tool call `ident` in the last turns of a chat state, as one plain line; "" when none."""
    if not isinstance(state, dict):
        return ""
    for turn in reversed(all_turns(state)):
        for part in turn.get("responseParts") or []:
            call = part.get("toolCall") if isinstance(part, dict) else None
            if isinstance(call, dict) and str(call.get("toolCallId") or "") == ident:
                error = call.get("error")
                message = error.get("message") if isinstance(error, dict) else error
                return cut(words(str(message))[:SUB_SAID * 4], SUB_SAID)[0] if isinstance(message, str) and message.strip() else ""
    return ""


def attach_subs(items: List[Dict[str, Any]], subs: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]], root: Optional[Path] = None, state: Optional[Dict[str, Any]] = None) -> None:
    """Put a small summary of each subagent on the tool call that started it (1.6.105, small since B4a): `sub: {title, st, calls, t0?, t1?, now?, said?}` (`sub_summary`; `t0` / `t1` are the call's own
    times). The whole chat of a subagent is `VsLink.sub`. `subs`: the chat of each subagent (`ahp.sub_chat`) with its cached state, or None while it is being read. A tool call not among the items shown gets nothing.
    The items are the new dicts `build` made: the memo's own are not changed."""
    calls = {item["id"]: item for item in items if item.get("k") == "tool"}
    for sub, held in subs:
        item = calls.get(sub["call"])
        if item is None:
            continue
        found = sub_summary(sub.get("title") or "", held, str(item.get("st") or ""), root)
        for key in ("t0", "t1"):
            if item.get(key):
                found[key] = item[key]
        if found["st"] == "fail" and not found.get("said"):  # a subagent that failed before it said anything: the error of the call that started it (`state`: the main chat)
            why = _call_error(state, sub["call"])
            if why:
                found["said"] = why
        item["sub"] = found
