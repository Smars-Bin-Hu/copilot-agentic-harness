"""The calls to outside systems that wrote or ran something, each with how it ended (the Runs and Scripts tabs; 1.8.54).

Two records are put together, and nothing new is written:
- `.task/calls.jsonl` (`core.calls`): what the gate noted when it let a call through: the command, the system, the environment, the verb, what let it through.
- `.task/stream.jsonl` (`chatstream`): what the board saw of the chat: each tool call with its output and exit code, and when it began and ended.

A call is listed when its verb is a write, an exec or a destroy, or when the person approved it (a read too). A read the policy let through is not: the Agent actions tab has those.

A noted call and a call of the stream are the same one when the command is the same (white space aside; one may hold the other, as `calls.leave_of` reads it) and the stream's call
began in the window before the note (`callmatch.HOOK_LAG_S`: the note is written when the hook is done). Never by time alone: an output shown under the wrong command is worse than none.
A call with no match has the outcome `unknown` and a reason; it is never shown as one that worked.

`listing` gives the rows without the outputs (the page asks for one with `detail` when a row opens); `with_outputs` puts a bounded output on each, for a saved copy of the page.
The pairing is kept while `calls.jsonl` and the stream do not change. When the stream changed it is read again only while a call is open or unknown, at most every AGAIN_S.
"""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import approvals, calls, copilot_events, redact, tasks

from . import callmatch, chatlive, chatstream, cmdview, outview

WRITES = ("write", "exec", "destroy")
OUTCOMES = ("ok", "failed", "running", "unknown")
OUTPUT_CHARS = 20_000  # of an output the page shows when a row opens
SAVED_CHARS = 4_000  # of an output in a saved copy of the page
SAVED_TOTAL = 600_000  # of all the outputs of a saved copy together
AGAIN_S = 10.0  # while a call is open or unknown, the stream is read again no sooner than this
MAX_ROWS = 2000  # as `calls.MAX_LINES`
MAX_TURN_S = 4 * 3600.0  # a call the stream gives no time for is looked for in a turn only this long after the turn began

_lock = threading.Lock()
_kept: Dict[str, Tuple[Any, Any, float, List[Dict[str, Any]]]] = {}  # task folder -> (the stat of calls.jsonl and the scripts, the stat of the stream, when paired, rows)


def wanted(line: Dict[str, Any]) -> bool:
    return str(line.get("verb") or "") in WRITES or line.get("how") == "approved"


def ident(line: Dict[str, Any]) -> str:
    """A name for one noted call that stays the same between two readings."""
    return hashlib.sha256((str(line.get("at") or "") + "\n" + str(line.get("command") or "")).encode("utf-8")).hexdigest()[:12]


def _same(noted: str, seen: str) -> bool:
    return bool(noted and seen) and (noted == seen or (len(seen) > 12 and seen in noted) or (len(noted) > 40 and noted in seen))


def _stream_calls(root: Path, task: str) -> Tuple[List[Dict[str, Any]], bool, Optional[float]]:
    """`(calls, cut, first)`: every command of the stream `{command, t0, t1, call, turn, chat, ended}`, whether the stream is known to miss something, and when its first turn began."""
    try:
        found = chatstream.read(root, task)
    except Exception:  # noqa: BLE001 - the stream is an extra
        return [], False, None
    out: List[Dict[str, Any]] = []
    first: Optional[float] = None
    turns = found.get("turns") or []
    for number, turn in enumerate(turns):
        began = copilot_events.seconds(turn.get("at"))
        later = [copilot_events.seconds(other.get("at")) for other in turns[number + 1:] if other.get("chat") == turn.get("chat")]
        until = next((value for value in later if value is not None), None)  # when the next turn of the same chat began: a call of this turn began before it
        if began is not None and (first is None or began < first):
            first = began
        for part in turn.get("parts") or []:
            call = part.get("toolCall") if isinstance(part, dict) and part.get("kind") == "toolCall" else None
            if not isinstance(call, dict):
                continue
            try:
                command = chatlive._command_of(chatlive._given(call))
            except Exception:  # noqa: BLE001 - a shape not expected: not a command
                command = ""
            if not command:
                continue
            stamp = lambda key: part[key] / 1000.0 if isinstance(part.get(key), (int, float)) and not isinstance(part.get(key), bool) and part[key] > 0 else None  # noqa: E731
            out.append({"command": approvals.collapse(command), "t0": stamp("t0"), "t1": stamp("t1"), "call": call, "turn": str(turn.get("id") or ""), "chat": str(turn.get("chat") or ""),
                        "ended": bool(turn.get("state")), "began": began, "until": until})
    return out, bool(found.get("cut")), first


def _pair(noted: List[Dict[str, Any]], seen: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """For each noted call (by its place in `noted`), the stream's call it is. Each stream call is given once; the noted calls are taken oldest first."""
    taken: set = set()
    out: Dict[int, Dict[str, Any]] = {}
    for index, line in enumerate(noted):
        text = approvals.collapse(redact.text(str(line.get("command") or "")))
        raw = approvals.collapse(str(line.get("command") or ""))
        at = copilot_events.seconds(line.get("at"))
        best, best_gap = None, None
        for number, item in enumerate(seen):
            if number in taken or not (_same(text, item["command"]) or _same(raw, item["command"])):
                continue
            began = item["t0"] if item["t0"] is not None else item["began"]
            if at is None or began is None:
                continue
            gap = at - began  # the note comes after the call began
            if item["t0"] is None:  # only the start of the turn is known: the call is somewhere in it, so the note is no later than the next turn of that chat (or, for its last turn, MAX_TURN_S)
                if gap < -callmatch.HOOK_EARLY_S or at > (item["until"] + callmatch.HOOK_LAG_S if item["until"] is not None else began + MAX_TURN_S):
                    continue
                gap = gap + 1e6  # any call with its own time is a better match
            elif gap < -callmatch.HOOK_EARLY_S or gap > callmatch.HOOK_LAG_S:
                continue
            if best_gap is None or abs(gap) < best_gap:
                best, best_gap = number, abs(gap)
        if best is not None:
            taken.add(best)
            out[index] = seen[best]
    return out


def _result(item: Dict[str, Any]) -> Dict[str, Any]:
    """`{outcome, exit, seconds, output, known}` of a stream call."""
    call = item["call"]
    state = chatlive.state_of(call, not item["ended"])
    try:
        output, code, known = chatlive._output_of(chatlive._items(call))
    except Exception:  # noqa: BLE001 - a result of a shape not expected
        output, code, known = "", None, False
    took = round(item["t1"] - item["t0"], 1) if item["t0"] is not None and item["t1"] is not None and item["t1"] >= item["t0"] else None
    if state in ("run", "wait"):
        if item["ended"]:  # the turn is over and the call never ended: stopped, how it ended is not known
            return {"outcome": "unknown", "why": "stopped", "exit": None, "seconds": None, "output": output, "known": known}
        return {"outcome": "running", "why": "", "exit": None, "seconds": None, "output": "", "known": False}
    failed = state == "fail" or (code is not None and code != 0)
    if not failed and not known and code is None:  # the record says the call ended and holds no result of it: how it ended is not known
        return {"outcome": "unknown", "why": "noresult", "exit": None, "seconds": took, "output": "", "known": False}
    error = call.get("error")
    if failed and not output:
        output = str(error.get("message") or "") if isinstance(error, dict) else str(error or "")
        known = known or bool(output)
    return {"outcome": "failed" if failed else "ok", "why": "", "exit": code, "seconds": took, "output": output, "known": known}


def _script_of(command: str, scripts: List[Tuple[str, Any, float]]) -> str:
    return next((path for path, pattern, _changed in scripts if pattern.search(command)), "")


def _rows(root: Path, task: str, scripts: List[Tuple[str, Any, float]]) -> List[Dict[str, Any]]:
    """A row for each noted call that is listed (`wanted`) or that names a script of `DEV/_server/` (a read too: the Scripts tab shows every run of a script)."""
    noted = calls.read(root, task)[-MAX_ROWS:]
    named = [_script_of(str(line.get("command") or ""), scripts) for line in noted]
    if not any(wanted(line) or named[index] for index, line in enumerate(noted)):
        return []
    seen, cut, first = _stream_calls(root, task)
    pairs = _pair(noted, seen)  # every noted call takes part, so a read does not lose its own call to a write of the same words
    rows: List[Dict[str, Any]] = []
    for index, line in enumerate(noted):
        if not (wanted(line) or named[index]):
            continue
        at = copilot_events.seconds(line.get("at"))
        row: Dict[str, Any] = {"listed": wanted(line), "script": named[index], "id": ident(line), "at": str(line.get("at") or ""), "command": redact.text(str(line.get("command") or "")),  # the page and a saved copy get no secret of a command
                               "_at": at, "_words": approvals.collapse(str(line.get("command") or "")), "system": str(line.get("system") or ""), "env": str(line.get("env") or ""),
                               "verb": str(line.get("verb") or ""), "floor": line.get("floor") if isinstance(line.get("floor"), bool) else None, "how": str(line.get("how") or calls.UNKNOWN), "code": str(line.get("code") or ""),
                               "outcome": "unknown", "why": "", "exit": None, "seconds": None, "turn": "", "chat": "", "has_output": False}
        found = pairs.get(index)
        if found is None:
            row["why"] = "board" if not seen or first is None or (at is not None and at < first - callmatch.HOOK_EARLY_S) else "cut" if cut else "unmatched"
        else:
            result = _result(found)
            row.update({"outcome": result["outcome"], "why": result["why"], "exit": result["exit"], "seconds": result["seconds"], "turn": found["turn"], "chat": found["chat"], "has_output": bool(result["known"])})
            row["_output"] = result["output"]
        rows.append(row)
    return rows


def _stat(path: Path) -> Any:
    try:
        found = path.stat()
        return (found.st_mtime_ns, found.st_size)
    except OSError:
        return None


def _paired(root: Path, task: str) -> Tuple[List[Dict[str, Any]], List[Tuple[str, Any, float]]]:
    key = str(tasks.task_dir(root, task))
    try:
        scripts = _scripts(root, task)
    except Exception:  # noqa: BLE001 - no script is named then
        scripts = []
    mark = (_stat(calls.path(root, task)), tuple(path for path, _pattern, _changed in scripts))
    stream = _stat(chatstream.stream_file(root, task))
    now = time.monotonic()
    with _lock:
        kept = _kept.get(key)
    if kept is not None and kept[0] == mark:
        settled = all(row["outcome"] in ("ok", "failed") for row in kept[3])
        if kept[1] == stream or settled or now - kept[2] < AGAIN_S:  # the stream did not change: reading it again gives the same; it changed: only an open or unknown call can gain from it
            return kept[3], scripts
    try:
        rows = _rows(root, task, scripts)
    except Exception:  # noqa: BLE001 - the tabs show the rest of the task
        rows = []
    with _lock:
        _kept[key] = (mark, stream, now, rows)
        while len(_kept) > 64:
            _kept.pop(next(iter(_kept)))
    return rows, scripts


def paired(root: Path, task: str) -> List[Dict[str, Any]]:
    """The rows with their outputs (`_output`), oldest first; kept as the module's head says. Never raises."""
    return _paired(root, task)[0]


def forget() -> None:
    with _lock:
        _kept.clear()


def _scripts(root: Path, task: str) -> List[Tuple[str, Any, float]]:
    """The scripts of `DEV/_server/`: `(path from the task folder, the pattern a command names it by, when it last changed)`."""
    import re
    folder = tasks.task_dir(root, task)
    out: List[Tuple[str, Any, float]] = []
    base = folder / tasks.DEV_NAME
    for top in (tasks.SERVER_NAME, *tasks.OLD_SERVER_NAMES):
        where = base / top
        if not where.is_dir():
            continue
        for path in sorted(where.rglob("*")):
            if len(out) >= 500:
                break
            if not path.is_file() or path.is_symlink():
                continue
            try:
                changed = path.stat().st_mtime
            except OSError:
                continue
            out.append((path.relative_to(folder).as_posix(), re.compile(r"(?:^|[\\/\s\"'=])" + re.escape(path.name) + r"(?:$|[\s\"';])"), changed))
    return out


def _public(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def listing(root: Path, task: str, evidence_items: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """The rows of the page, oldest first, without their outputs: `{listed, id, at, command, system, env, verb, floor, how, code, outcome, why, exit, seconds, turn, chat, has_output, evidence, script,
    script_changed}`. `listed`: it belongs on the Runs tab (a write, an exec, a destroy, or approved by the person); a row that is not listed is a read that names a script. `evidence`: the numbers of the saved runs that ran this command; `script`: the script of `DEV/_server/` the command names; `script_changed`: that file changed after the call."""
    held, scripts = _paired(root, task)
    if not held:
        return []
    rows = [_public(row) for row in held]
    changed_at = {path: changed for path, _pattern, changed in scripts}
    for row, kept in zip(rows, held):
        row["evidence"] = []
        row["script_changed"] = bool(row["script"]) and kept["_at"] is not None and changed_at.get(row["script"], 0.0) > kept["_at"] + 1.0
    for item in evidence_items or []:
        if item.get("by") != "agent":
            continue
        ran = [step.get("command") or "" for step in item.get("steps") or []] or [item.get("command") or ""]
        saved = copilot_events.seconds(item.get("at"))
        for want in {approvals.collapse(line) for text in ran for line in text.splitlines()} - {""}:
            for index in range(len(held) - 1, -1, -1):  # the latest call of these words before the run was saved, as `calls.leave_of`
                at, have = held[index]["_at"], held[index]["_words"]
                if saved is not None and at is not None and at > saved + 1.0:
                    continue
                if have == want or want in have or (len(want) > 40 and have in want):
                    if item["id"] not in rows[index]["evidence"]:
                        rows[index]["evidence"].append(item["id"])
                    break
    return rows


def _shown(root: Path, task: str, row: Dict[str, Any], cap: int) -> Dict[str, Any]:
    text = redact.text(str(row.get("_output") or ""))
    out: Dict[str, Any] = {"id": row["id"], "command": row["command"], "output": text[:cap], "output_cut": len(text) > cap, "has_output": bool(row.get("has_output"))}
    try:
        out["layout"] = cmdview.layout(row["command"], tasks.task_dir(root, task)) if row["command"] else None
    except Exception:  # noqa: BLE001 - the command shows as plain text
        out["layout"] = None
    try:
        out["output_view"] = outview.layout(text[:cap]) if text else None
    except Exception:  # noqa: BLE001 - the output shows as plain text
        out["output_view"] = None
    return out


def detail(root: Path, task: str, call_id: str) -> Optional[Dict[str, Any]]:
    """What an opened row shows: `{id, command, layout, output, output_cut, output_view, has_output}`; None when there is no such call."""
    for row in paired(root, task):
        if row["id"] == call_id:
            return _shown(root, task, row, OUTPUT_CHARS)
    return None


def with_outputs(root: Path, task: str, rows: List[Dict[str, Any]]) -> None:
    """For a saved copy of the page: each row gets `detail`, its output cut to SAVED_CHARS, the newest first until SAVED_TOTAL characters are given."""
    held = {row["id"]: row for row in paired(root, task)}
    left = SAVED_TOTAL
    for row in reversed(rows):
        found = held.get(row["id"])
        if found is None:
            continue
        shown = _shown(root, task, found, SAVED_CHARS if left > 0 else 0)
        left -= len(shown["output"])
        row["detail"] = shown
