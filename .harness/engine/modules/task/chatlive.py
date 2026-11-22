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

from core import redact

from . import mdtree

LATEST = 8  # items of `latest`: the newest few steps of a subagent
TEXT_CAP = 200000  # characters of agent text: a guard, not a design limit (a text longer than this is cut and says so)
THINK_CAP = 200000  # the same for thinking
ERROR_CAP = 300  # 1.8.5: the words of an error part, as `ahp.last_error` keeps them
SAY_CAP = 200
TARGET_CAP = 500
MARKS_MAX = 240  # part times kept for one turn
RUNNING = ("running", "streaming")
PATH_KEYS = ("path", "filePath", "file_path", "file", "filename", "paths", "uri", "url")
RUN_KEYS = ("command", "commandLine", "cmd", "script", "query", "pattern", "input")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MARKS = re.compile(r"`+|\*\*+")  # a `_` is not taken out: it is in names (load_orders)


def part_id(part: Any) -> str:
    """The id a part is told apart by: the id of text and thinking, the call id of a tool call. Empty: none."""
    if not isinstance(part, dict):
        return ""
    if part.get("kind") == "toolCall":
        return str((part.get("toolCall") or {}).get("toolCallId") or "") if isinstance(part.get("toolCall"), dict) else ""
    return str(part.get("id") or "")


def stamp(cached: Dict[str, Any], action: Dict[str, Any], now: int) -> None:
    """Note, from one action of the host, when a part began and ended (milliseconds since 1970). The caller holds the lock of the link."""
    kind = str(action.get("type") or "")
    marks = cached.setdefault("marks", {})
    if kind == "chat/turnStarted":
        marks.clear()
        return
    ident = str(action.get("toolCallId") or "") if kind.startswith("chat/toolCall") else part_id(action.get("part")) if kind == "chat/responsePart" else ""
    if not ident:
        return
    if kind in ("chat/responsePart", "chat/toolCallStart"):
        marks.setdefault(ident, [now, 0])
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
    """`run`, `wait` (a person must allow it), `done` or `fail`. (`tool_item` adds `stop`: the turn ended with the call still open.)"""
    status = str(call.get("status") or "")
    if status in RUNNING:
        return "run"
    if status == "pending-confirmation":
        return "wait"
    if status in ("failed", "cancelled", "denied", "error") or call.get("success") is False:
        return "fail"
    if status == "completed" or call.get("success") is True:
        return "done"
    return "run" if active else "done"  # a status this code does not know: still going while the turn runs, else over


def tool_item(call: Dict[str, Any], ident: str, active: bool, root: Optional[Path]) -> Dict[str, Any]:
    st = state_of(call, active)
    if not active and st in ("run", "wait"):
        st = "stop"  # its turn is over and the host never said how the call ended (stopped, skipped): not running, and not known to have worked
    first = (words(call.get("pastTenseMessage")) if st in ("done", "fail") else "") or words(call.get("intention")) or words(call.get("invocationMessage")) or words(call.get("displayName"))
    say, said = cut(first, SAY_CAP)
    target, cut_target = target_of(call, root)
    name, _ = cut(words(call.get("displayName")) or words(call.get("toolName")), 60)
    item: Dict[str, Any] = {"id": ident, "k": "tool", "tool": str(call.get("toolName") or "")[:60], "name": name, "st": st}
    if say:
        item["say"] = say
    if target and target != say:  # words of Copilot, not a place: once is enough
        item["target"] = target
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
        if was_cut or part.get("cut") is True:
            item["cut"] = True
    elif kind == "toolCall" and isinstance(part.get("toolCall"), dict):
        item = tool_item(part["toolCall"], ident, running, root)
    elif kind == "error":  # 1.8.5: the turn ended in an error; the page draws it red, with its words
        text, _was_cut = cut(part.get("message"), ERROR_CAP)
        item = {"id": ident, "k": "err", "text": text, "resumable": part.get("resumable") is True}
    else:
        return None
    if mark and mark[0]:
        item["t0"] = mark[0]
        if mark[1] and item["k"] == "tool":
            item["t1"] = mark[1]
    return item


def _thought_ends(items: List[Dict[str, Any]]) -> None:
    """A thought ends where the next item began."""
    for at, item in enumerate(items):
        if item["k"] == "think" and not item.get("run") and item.get("t0") and at + 1 < len(items) and items[at + 1].get("t0"):
            item["t1"] = items[at + 1]["t0"]


def _signature(part: Dict[str, Any], last: bool, running: bool, mark: List[int]) -> Tuple[Any, ...]:
    """What tells that a part is not the one an item was built from: cheap (no redaction, no parse). A text grows, so its length is in; a call changes by its status and the words it says of itself."""
    kind = part.get("kind")
    if kind in ("markdown", "reasoning"):
        return (kind, len(part["content"]) if isinstance(part.get("content"), str) else 0, last, tuple(mark))
    call = part.get("toolCall")
    if kind == "toolCall" and isinstance(call, dict):
        return (kind, running, call.get("status"), call.get("success"), tuple(len(str(call.get(key) or "")) for key in ("pastTenseMessage", "intention", "invocationMessage", "displayName", "toolInput")), tuple(mark))
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
    walked = _walk(turn, running, marks, root, kept, rev)
    items: List[Dict[str, Any]] = []
    fresh = {}
    for ident, item, v, sig in walked:
        fresh[ident] = (sig, item, v)
        if item is None:
            continue
        stub = v <= have and ident not in whole and (item["k"] in ("text", "think", "err", "me") or (item["k"] == "tool" and item.get("st") in ("done", "fail", "stop")))
        items.append({"id": item["id"], "k": item["k"], "same": True} if stub else dict(item))
    if memo is not None:
        memo.clear()
        memo.update(fresh)
    base = int(turn.get("dropped") or 0) if isinstance(turn.get("dropped"), int) else 0
    pointer = {"turn": str(turn.get("id") or ""), "i": base} if base > 0 else None
    return {"items": items, "more": pointer is not None, "started": str(turn.get("startedAt") or "") if running else "", "before": pointer, "turn": str(turn.get("id") or "")}


def latest(state: Dict[str, Any], marks: Dict[str, List[int]], root: Optional[Path] = None, count: int = LATEST) -> Dict[str, Any]:
    """`{items, more, started}`: the newest `count` items of the last turns, oldest first; `more`: there is something older. (What `build` was before the Live tab showed a whole turn; the steps of a subagent
    under its tool call (`attach_subs`) are still the newest few.)"""
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


SUB_LATEST = 6  # steps of a subagent shown under its tool call
SUB_TEXT = 400  # characters of a subagent's text there
SUB_THINK = 1200  # and of its thinking


def attach_subs(items: List[Dict[str, Any]], subs: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]], root: Optional[Path] = None) -> None:
    """Put the work of each subagent on the tool call that started it (1.6.105): `sub: {title, st, items, more}`, its latest steps, small; a text is plain and cut. `subs`: the chat of
    each subagent (`ahp.sub_chat`) with its cached state, or None while it is being read. A tool call not among the items shown gets nothing."""
    calls = {item["id"]: item for item in items if item.get("k") == "tool"}
    for sub, held in subs:
        item = calls.get(sub["call"])
        if item is None:
            continue
        state = (held or {}).get("state") or {}
        built = latest(state, (held or {}).get("marks") or {}, root, SUB_LATEST) if held else {"items": [], "more": False}
        steps = [dict({key: value for key, value in step.items() if key != "blocks"}, text=cut(step["text"], SUB_TEXT)[0]) if step["k"] == "text" else step for step in built["items"] if step["k"] != "me"]
        for step in steps:
            if step["k"] == "think" and step.get("text"):
                step["text"] = cut(step["text"], SUB_THINK)[0]  # a thought was cut at 1,200 before the caps were lifted; a subagent's steps stay small
        running = bool(state.get("activeTurn")) or item.get("st") == "run"
        item["sub"] = {"title": sub.get("title") or "", "st": "run" if running else "done", "items": steps, "more": bool(built["more"])}
