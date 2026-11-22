"""The stream of a task's chats, stored by the board (1.8.x): what the board sees of a chat while it runs, kept in `.task/stream.jsonl`.

Copilot's own `events.jsonl` is not ours to rely on: when it is gone the history of a task is gone with it. The board reads every action of the chat from the agent host anyway
(`vslink._notice`), so it keeps what it sees: the person's message, each part of the reply (text, thinking, tool calls with their results), and how the turn ended.

The file is one JSON object per line, and each line starts with the key `k` (so a reader can test the start of a line without parsing it):

  turn  {k, chat, turn, at, text, files?, sub?}      a turn began: the person's message (attachments by label only, never their bytes); `sub`: this chat is a subagent's
  part  {k, chat, turn, i, open?, part}              one part of the reply; `i`: its index in the turn counting the parts the board's memory dropped; `open`: written before it ended
  end   {k, chat, turn, state, duration, usage}      the turn ended (complete, cancelled, error)
  cut   {k, chat, turn}                              `chat/truncated` (an undo or a rewind): the turns after `turn` are gone; null: all of them

The rule of the file: a later record with the same `(chat, turn, i)` replaces an earlier one. So writing a part twice is always safe; not writing it never is.

`take` and `backfill` are pure and cheap (they run for every action while the link's lock is held); `append`, `known` and `read` do the file work and are called after the lock is let go.
Everything stored goes through `redact.text`. A reader treats the file as untrusted bytes: one pass, a bound on the size, a line it cannot use is skipped and counted.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from core import ahp, redact, tasks
from core.state import state_lock

FILE_NAME = "stream.jsonl"
RECORD_MAX = 120000  # characters of one record's JSON; a bigger one is reduced
PART_TEXT = 20000  # characters kept of a result's first text, and of a tool call's input, in a reduced record
SKELETON_TEXT = 2000  # characters of a text or thinking part in a skeleton
TEXT_MAX = 200000  # characters of the person's message
SOFT_BYTES = 32 * 1024 * 1024  # over this size the parts are stored as skeletons
HARD_BYTES = 64 * 1024 * 1024  # over this size nothing more is written; a reader reads no more than this
LINE_MAX = 4 * TEXT_MAX + 8192  # bytes of one line a reader accepts (the longest record, in UTF-8)
OPEN_MARGIN = 10  # a part that is not final is written when it is within this many parts of falling out of the board's memory
DEPTH = 12  # levels of a part the redaction walks
USAGE_KEYS = ("inputTokens", "outputTokens", "cacheReadTokens")
ENDS = {"chat/turnComplete": "complete", "chat/turnCancelled": "cancelled", "chat/error": "error"}
STATES = ("complete", "cancelled", "error")
WATCHED = frozenset(["chat/turnStarted", "chat/turnResume", "chat/responsePart", "chat/toolCallStart", "chat/toolCallConfirmed", "chat/toolCallComplete", "chat/toolCallResultConfirmed",
                     "chat/truncated"] + list(ENDS))  # the actions after which a record can be due; the hundreds of deltas, reasoning and usage actions are not here
FINAL = ("completed", "failed", "cancelled")  # a tool call in one of these takes no second result


def stream_file(root: Path, task: str) -> Path:
    return tasks.state_file(root, task).parent / FILE_NAME


def wants(action: Any) -> bool:
    """True when `take` may return something for this action: a cheap test, so the caller looks up the task of the chat only then."""
    return isinstance(action, dict) and action.get("type") in WATCHED


# --- what a record holds -----------------------------------------------------------------------------------------

PLAIN = frozenset(["kind", "id", "type", "status", "toolCallId", "toolName", "confirmed", "reason", "startedAt"])  # fields that are names and ids, never free text: a long id must not be masked as a key (records are matched by it)
PLAIN_MAX = 200  # characters; a longer value of such a field is treated as text after all


def _clean(value: Any, depth: int = 0) -> Any:
    """`value` copied, with each string masked by `redact.text` (keys stay; the short names and ids of `PLAIN` stay as they are). The copy also keeps the record from changing when the chat's
    state does. Deeper than `DEPTH` levels is cut."""
    if isinstance(value, str):
        return redact.text(value)
    if depth >= DEPTH:
        return None
    if isinstance(value, dict):
        return {key: item if key in PLAIN and isinstance(item, str) and len(item) <= PLAIN_MAX else _clean(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item, depth + 1) for item in value]
    return value if value is None or isinstance(value, (bool, int, float)) else redact.text(value)


def _size(record: Dict[str, Any]) -> int:
    return len(json.dumps(record, ensure_ascii=False))


def _skeleton(part: Any) -> Dict[str, Any]:
    """What is left of a part when the file is big: a tool call keeps its name, status and the line it says about itself, a text or thinking part its first characters. Marked `cut`."""
    if not isinstance(part, dict):
        return {"cut": True}
    call = part.get("toolCall")
    if isinstance(call, dict):
        kept = {key: call[key] for key in ("toolCallId", "toolName", "displayName", "status", "success", "pastTenseMessage", "_meta") if key in call}
        return {"kind": part.get("kind", "toolCall"), "toolCall": kept, "cut": True}
    out = {key: part[key] for key in ("kind", "id", "startedAt", "duration") if key in part}
    if isinstance(part.get("content"), str):
        out["content"] = part["content"][:SKELETON_TEXT]
    out["cut"] = True
    return out


def _reduced(part: Dict[str, Any]) -> Dict[str, Any]:
    """A part whose record is too long, in steps: the result of a tool call kept as its first text (cut) and the other items as `{type, cut}`, the input cut; then no result and no input; then the skeleton."""
    call = part.get("toolCall")
    if isinstance(call, dict):
        call = dict(call)
        if isinstance(call.get("content"), list):
            found = False
            items = []
            for item in call["content"]:
                if not found and isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    found = True
                    items.append(dict(item, text=item["text"][:PART_TEXT]))
                else:
                    kind = item.get("type") if isinstance(item, dict) else None
                    items.append({"type": kind if isinstance(kind, str) else "unknown", "cut": True})
            call["content"] = items
        if isinstance(call.get("toolInput"), str):
            call["toolInput"] = call["toolInput"][:PART_TEXT]
        return dict(part, toolCall=call)
    if isinstance(part.get("content"), str):
        return dict(part, content=part["content"][:RECORD_MAX // 2], cut=True)
    return part


def _fit(record: Dict[str, Any]) -> Dict[str, Any]:
    """A part record no longer than `RECORD_MAX` (its `part` reduced when it is)."""
    if _size(record) <= RECORD_MAX:
        return record
    part = record["part"]
    record = dict(record, part=_reduced(part))
    if _size(record) <= RECORD_MAX:
        return record
    call = part.get("toolCall") if isinstance(part, dict) else None
    if isinstance(call, dict):
        stripped = {key: item for key, item in call.items() if key not in ("content", "toolInput")}
        record = dict(record, part=dict(part, toolCall=stripped, cut=True))
        if _size(record) <= RECORD_MAX:
            return record
    record = dict(record, part=_skeleton(part))
    if _size(record) > RECORD_MAX:  # even the skeleton is too long (a huge `_meta`)
        record["part"] = {"kind": part.get("kind") if isinstance(part, dict) else None, "cut": True}
    return record


def _turn_record(chat: str, turn: Dict[str, Any], sub: Optional[Dict[str, str]]) -> Dict[str, Any]:
    message = turn.get("message") if isinstance(turn.get("message"), dict) else {}
    record: Dict[str, Any] = {"k": "turn", "chat": chat, "turn": str(turn.get("id") or ""), "at": turn.get("startedAt"), "text": redact.text(str(message.get("text") or "")[:TEXT_MAX])}
    labels = []
    for item in message.get("attachments") if isinstance(message.get("attachments"), list) else []:
        label = (item.get("label") or item.get("name") or item.get("uri")) if isinstance(item, dict) else None
        if isinstance(label, str) and label:
            labels.append(redact.text(label[:500]))
    if labels:
        record["files"] = labels
    if sub:
        record["sub"] = {"parent": sub.get("parent"), "call": sub.get("call")}
    return record


def _part_record(chat: str, turn: str, i: int, part: Dict[str, Any], opened: bool) -> Dict[str, Any]:
    record: Dict[str, Any] = {"k": "part", "chat": chat, "turn": turn, "i": i}
    if opened:
        record["open"] = True
    record["part"] = _clean(part)
    return _fit(record)


def _end_record(chat: str, turn: str, state: str, duration: Any, usage: Any) -> Dict[str, Any]:
    kept = {key: usage[key] for key in USAGE_KEYS if isinstance(usage, dict) and isinstance(usage.get(key), (int, float)) and not isinstance(usage.get(key), bool)}
    return {"k": "end", "chat": chat, "turn": turn, "state": state, "duration": duration if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None, "usage": kept}


def _length(part: Dict[str, Any]) -> int:
    return len(part["content"]) if isinstance(part.get("content"), str) else 0


# --- what is due -------------------------------------------------------------------------------------------------

def take(cached: Dict[str, Any], chat: str, action: Dict[str, Any], sub: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """The records that became due with `action`. Call it right after `ahp.reduce_chat` moved `cached["state"]`. It keeps its own memory in `cached["stream"]`: `turn` (the turn it has
    announced), `w` (absolute part index -> `(written while open, length of the text then)`), `o` (the calls written open that the memory may lose, with the part as written: a result that comes
    after the cut is given to that copy) and `end` (the turn it ended last, so the host's push of the same end after the board's own
    adds nothing). A part is due when it is final (a tool call that ended; a text or thinking part that is no longer the last), and when it is about to fall out of the board's memory
    (`ahp.PARTS_KEEP`) it is written open. At the end of the turn every part not on disk is written, a text that grew since is written again, and the turn's `end` follows."""
    kind = str(action.get("type") or "") if isinstance(action, dict) else ""
    if kind not in WATCHED:
        return []
    state = cached.get("state") if isinstance(cached.get("state"), dict) else {}
    memory = cached.setdefault("stream", {"turn": None, "w": {}, "end": None})
    if kind == "chat/truncated":
        memory.update(turn=None, w={}, o={}, end=None)
        found = action.get("turnId")
        return [{"k": "cut", "chat": chat, "turn": found if isinstance(found, str) else None}]
    ending = kind in ENDS
    if ending:
        turns = state.get("turns") if isinstance(state.get("turns"), list) else []
        turn = turns[-1] if turns and isinstance(turns[-1], dict) else None
        if turn is None or turn.get("id") != action.get("turnId"):
            return []  # the reducer did not take this end (no such running turn)
    else:
        turn = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
        if turn is None:
            return []
    ident = str(turn.get("id") or "")
    if not ident or (ending and memory.get("end") == ident):
        return []
    out: List[Dict[str, Any]] = []
    if memory.get("turn") != ident:  # the first sight of this turn: its start, or the board subscribed in the middle
        memory.update(turn=ident, w={}, o={})
        out.append(_turn_record(chat, turn, sub))
    memory["end"] = ident if ending else None
    held: Dict[str, Tuple[int, Dict[str, Any]]] = memory.setdefault("o", {})  # tool call id -> (index, the part as written) of a call written open
    asked = action.get("toolCallId")
    if held and isinstance(asked, str) and asked in held and kind.startswith("chat/toolCall") and not any(
            isinstance(part, dict) and isinstance(part.get("toolCall"), dict) and part["toolCall"].get("toolCallId") == asked for part in turn.get("responseParts") or []):
        # the call fell out of the board's memory while it ran, so the reducer has no part to give the result to: it goes to the copy written open, and the final part replaces it
        index, snapshot = held[asked]
        ahp.reduce_chat({"activeTurn": {"id": ident, "responseParts": [snapshot]}, "turns": []}, action)
        if snapshot.get("toolCall", {}).get("status") in FINAL:
            out.append(_part_record(chat, ident, index, snapshot, False))
            memory["w"][index] = (False, 0)
            del held[asked]
    parts = turn.get("responseParts") if isinstance(turn.get("responseParts"), list) else []
    base = int(turn.get("dropped") or 0) if isinstance(turn.get("dropped"), int) else 0
    written: Dict[int, Tuple[bool, int]] = memory["w"]
    if len(written) > 4 * ahp.PARTS_KEEP:
        written = memory["w"] = {i: item for i, item in written.items() if i >= base}  # what fell out of memory will not be asked for again
    last = len(parts) - 1
    horizon = len(parts) - ahp.PARTS_KEEP + OPEN_MARGIN
    for position, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        i = base + position
        before = written.get(i)
        call = part.get("toolCall") if part.get("kind") == "toolCall" and isinstance(part.get("toolCall"), dict) else None
        if call is not None:
            ended = call.get("status") in FINAL
        else:
            ended = position < last or ending  # a text that is no longer the last is finished
        if ended:
            if before is None or before[0] or (ending and call is None and before[1] != _length(part)):
                out.append(_part_record(chat, ident, i, part, False))
                written[i] = (False, _length(part))
        elif ending:  # a call that never ended
            out.append(_part_record(chat, ident, i, part, True))
            written[i] = (True, 0)
        elif before is None and position < horizon:  # not final, and the next cut of the memory takes it
            out.append(_part_record(chat, ident, i, part, True))
            written[i] = (True, _length(part))
            if call is not None and isinstance(call.get("toolCallId"), str):
                held[call["toolCallId"]] = (i, copy.deepcopy(out[-1]["part"]))  # a copy: the record is written after the lock, this one changes with the next action
    if ending:
        state_name = ENDS[kind]
        held.clear()
        out.append(_end_record(chat, ident, state_name, action.get("duration") if action.get("duration") is not None else turn.get("duration"), turn.get("usage")))
        memory["w"] = {}
    return out


def backfill(full_state: Any, chat: str, have: Any, sub: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """For a snapshot just read from the host: each finished turn whose id is not in `have` (the ones that have an `end` record on disk) as `turn`, ALL its parts (each cut as
    `ahp.slim_part` cuts it; the snapshot is whole, so nothing is dropped as the board's memory would) and `end`. The turn that runs is left to `take`."""
    out: List[Dict[str, Any]] = []
    turns = full_state.get("turns") if isinstance(full_state, dict) and isinstance(full_state.get("turns"), list) else []
    for turn in turns:
        if not isinstance(turn, dict) or not turn.get("id") or turn["id"] in have:
            continue
        ident = str(turn["id"])
        out.append(_turn_record(chat, turn, sub))
        base = int(turn.get("dropped") or 0) if isinstance(turn.get("dropped"), int) else 0
        for position, part in enumerate(turn.get("responseParts") if isinstance(turn.get("responseParts"), list) else []):
            if isinstance(part, dict):
                out.append(_part_record(chat, ident, base + position, ahp.slim_part(part), False))
        out.append(_end_record(chat, ident, turn.get("state") if turn.get("state") in STATES else "complete", turn.get("duration"), turn.get("usage")))
    return out


# --- the file ----------------------------------------------------------------------------------------------------

def append(root: Path, task: str, records: List[Dict[str, Any]]) -> int:
    """Write the records, one lock and one open for the batch. The size is looked at once per batch: over `SOFT_BYTES` the parts are written as skeletons, over `HARD_BYTES` nothing is written.
    A failed write must not stop the chat (the same as a missing line of history, `vslink._adopt`): it is swallowed, and the number of records not written is returned (0: all went)."""
    if not records:
        return 0
    path = stream_file(root, task)
    try:
        with state_lock(path):
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                size = 0
            if size > HARD_BYTES:
                return len(records)
            lines = []
            for record in records:
                if size > SOFT_BYTES and record.get("k") == "part":
                    record = dict(record, part=_skeleton(record.get("part")))
                lines.append(json.dumps(record, ensure_ascii=False) + "\n")
            with open(path, "a", encoding="utf-8", errors="replace", newline="\n") as handle:
                handle.write("".join(lines))
        return 0
    except (OSError, ValueError, TypeError, RecursionError):
        return len(records)


def _lines(path: Path) -> Iterator[Optional[bytes]]:
    """The lines of the file, at most `HARD_BYTES` of it. A line longer than `LINE_MAX` comes as None (it is read on to its end and left out). Never raises."""
    total = 0
    try:
        with open(path, "rb") as handle:
            while total < HARD_BYTES:
                line = handle.readline(LINE_MAX + 1)
                if not line:
                    return
                total += len(line)
                if len(line) > LINE_MAX and not line.endswith(b"\n"):
                    while total < HARD_BYTES:
                        rest = handle.readline(LINE_MAX)
                        total += len(rest)
                        if not rest or rest.endswith(b"\n"):
                            break
                    yield None
                    continue
                yield line
    except OSError:
        return


def known(root: Path, task: str) -> Dict[str, Set[str]]:
    """chat -> the ids of its turns that have an `end` record. A line is tested by its start before it is parsed: a file has far more `part` lines than `end` lines."""
    found: Dict[str, Set[str]] = {}
    for line in _lines(stream_file(root, task)):
        if line is None or not line.startswith(b'{"k": "end"'):
            continue
        try:
            record = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if isinstance(record, dict) and isinstance(record.get("chat"), str) and isinstance(record.get("turn"), str):
            found.setdefault(record["chat"], set()).add(record["turn"])
    return found


def read(root: Path, task: str, chat: Optional[str] = None) -> Dict[str, Any]:
    """`{turns, cut, skipped}`: the turns in the order they first appear, each `{chat, id, at, text, files, sub, parts, state, duration, usage}`; the parts ordered by `i` (each with its `i`, and
    `open` when written before it ended); `state` is empty for a turn with no `end`. The replace rule and the `cut` records are applied. `chat`: only the turns of that chat. `cut` is True when
    something is known to be missing: a `cut` record took turns away, a part was stored reduced, or the file was longer than `HARD_BYTES`. `skipped`: lines that could not be used (not JSON, not
    an object, a shape not known). Never raises."""
    order: List[Tuple[str, str]] = []
    turns: Dict[Tuple[str, str], Dict[str, Any]] = {}
    skipped = 0
    cut = False

    def hold(key: Tuple[str, str]) -> Dict[str, Any]:
        if key not in turns:
            turns[key] = {"chat": key[0], "id": key[1], "at": "", "text": "", "files": [], "sub": None, "parts": {}, "state": "", "duration": None, "usage": {}}
            order.append(key)
        return turns[key]

    for line in _lines(stream_file(root, task)):
        if line is None:
            skipped += 1
            continue
        try:
            record = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            skipped += 1
            continue
        kind = record.get("k") if isinstance(record, dict) else None
        where, ident = (record.get("chat"), record.get("turn")) if isinstance(record, dict) else (None, None)
        if kind == "cut" and isinstance(where, str) and (ident is None or isinstance(ident, str)):
            cut = True
            mine = [key for key in order if key[0] == where]
            names = [key[1] for key in mine]
            gone = mine if ident is None else mine[names.index(ident) + 1:] if ident in names else []
            for key in gone:
                turns.pop(key)
                order.remove(key)
            continue
        if kind not in ("turn", "part", "end") or not isinstance(where, str) or not isinstance(ident, str) or not ident:
            skipped += 1
            continue
        if kind == "turn":
            found = hold((where, ident))
            found["at"] = record.get("at") if isinstance(record.get("at"), str) else ""
            found["text"] = record.get("text") if isinstance(record.get("text"), str) else ""
            found["files"] = [item for item in record.get("files") if isinstance(item, str)] if isinstance(record.get("files"), list) else []
            found["sub"] = record["sub"] if isinstance(record.get("sub"), dict) else None
        elif kind == "part":
            index, part = record.get("i"), record.get("part")
            if not isinstance(index, int) or isinstance(index, bool) or index < 0 or not isinstance(part, dict):
                skipped += 1
                continue
            cut = cut or part.get("cut") is True
            found = hold((where, ident))
            found["parts"][index] = dict(part, i=index, **({"open": True} if record.get("open") is True else {}))
        else:
            found = hold((where, ident))
            found["state"] = record.get("state") if isinstance(record.get("state"), str) else ""
            found["duration"] = record.get("duration") if isinstance(record.get("duration"), (int, float)) and not isinstance(record.get("duration"), bool) else None
            found["usage"] = record["usage"] if isinstance(record.get("usage"), dict) else {}
    try:
        cut = cut or stream_file(root, task).stat().st_size > HARD_BYTES
    except OSError:
        pass
    out = []
    for key in order:
        if chat is not None and key[0] != chat:
            continue
        found = dict(turns[key])
        found["parts"] = [found["parts"][index] for index in sorted(found["parts"])]
        out.append(found)
    return {"turns": out, "cut": cut, "skipped": skipped}
