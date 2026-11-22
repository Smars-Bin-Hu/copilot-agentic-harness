"""The rounds of a task's chat (1.6.55): each prompt of the person, with all the text the agent wrote for it, for the Live tab.

The record is Copilot's own `events.jsonl` (`core/copilot_events.py`). It has every model call's text, also what the chat window folds away, and it can be read with VS Code closed.
Kept: the prompt, the agent's text, the names of the tools, when the round's last step ended and the credits it cost (`copilot_events` CREDITS, the same rule as the
task report: each model call's credits, a subagent's too, go to the round they ran in). Left out: thinking, tool results, hooks and
the other usage numbers (they are in VS Code), and all a subagent says.

When a task closes the rounds are saved in `.task/transcript.jsonl`, because Copilot's file is not ours to rely on. A closed task reads that file. `taskarchive.prune_transcripts` deletes
it `transcript.keep_days` after the archive; the task's audit files stay. Copilot's own files are never touched.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import copilot_events, tasks

from . import chatlive, chatstream, mdtree

FILE_NAME = "transcript.jsonl"
MAX_ROUNDS = 1000  # the newest
MAX_CHARS = 200000  # characters of one round's text; the rest is in VS Code
HEAD_CHARS = 160  # characters of a prompt in the list
_cache: Dict[str, Tuple[Tuple[int, int], List[Dict[str, Any]]]] = {}
_lock = threading.Lock()


def transcript(root: Path, task: str) -> Path:
    return tasks.state_file(root, task).parent / FILE_NAME


def read_events(path: Path) -> List[Dict[str, Any]]:
    """The rounds of one events file, oldest first. A line it cannot read is skipped: the file is not ours."""
    rounds: List[Dict[str, Any]] = []
    credits = copilot_events.Credits()
    in_turn = False  # the main agent is in a turn: a compaction then is Copilot's own, not a /compact of the person
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("type") if isinstance(event, dict) else None
            found = event.get("data") if isinstance(event, dict) else None
            if not isinstance(found, dict) or not isinstance(kind, str):
                continue
            added = credits.row(kind, found)  # the credits of a model call (a subagent's too) or a checkpoint's rest: the round running then (copilot_events CREDITS)
            if added is not None:
                if rounds:
                    rounds[-1]["aiu"] = (rounds[-1]["aiu"] or 0.0) + added[0]
                continue
            if not event.get("agentId") and kind in ("user.message", "assistant.turn_start", "assistant.turn_end"):
                in_turn = kind != "assistant.turn_end"  # from the message to the end of the turn (copilot_events.asked_compact)
            if not event.get("agentId") and kind == "session.compaction_start" and copilot_events.asked_compact(found, in_turn):
                at = str(event.get("timestamp") or "")  # a round of its own (1.6.113): Copilot writes no message for /compact, so Live did not show it
                rounds.append({"at": at, "prompt": copilot_events.COMPACT_TEXT, "texts": [], "tools": [], "cut": False, "end": at, "aiu": None, "compact": {"removed": None}})
                continue
            if rounds and kind == "session.compaction_complete" and rounds[-1].get("compact") and not event.get("agentId"):
                rounds[-1]["end"] = str(event.get("timestamp") or rounds[-1]["end"])
                rounds[-1]["compact"] = {"removed": copilot_events.whole_number(found.get("messagesRemoved"))}
                continue
            if rounds and kind.startswith(("assistant.", "tool.")) and not event.get("agentId") and event.get("timestamp"):
                rounds[-1]["end"] = str(event["timestamp"])
            if kind not in ("user.message", "assistant.message", "tool.execution_start"):
                continue
            if kind == "user.message":
                at = str(event.get("timestamp") or "")
                rounds.append({"at": at, "prompt": str(found.get("content") or ""), "texts": [], "tools": [], "cut": False, "end": at, "aiu": None})
            elif rounds and not found.get("parentToolCallId"):  # a subagent's own work is not this conversation
                last = rounds[-1]
                if kind == "tool.execution_start":
                    last["tools"].append(str(found.get("toolName") or "?")[:80])
                    continue
                text = str(found.get("content") or "").strip()
                room = MAX_CHARS - sum(len(item) for item in last["texts"])
                if text and room > 0:
                    last["texts"].append(text[:room])
                last["cut"] = last["cut"] or len(text) > room
    return rounds


def of_session(session_id: str) -> List[Dict[str, Any]]:
    path = copilot_events.events_path(session_id)
    if path is None:
        return []
    try:
        info = path.stat()
        mark = (info.st_size, info.st_mtime_ns)
        with _lock:
            kept = _cache.get(str(path))
        if kept and kept[0] == mark:
            return kept[1]
        rounds = read_events(path)
    except OSError:
        return []
    with _lock:
        _cache[str(path)] = (mark, rounds)
    return rounds


def _stamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (int(round(seconds * 1000)) % 1000)


def of_stream(root: Path, task: str) -> List[Dict[str, Any]]:
    """The rounds of the task from the board's own stream (`chatstream`), in the shape `of_session` gives: one per turn of the main chat (a subagent's turn is not a round). The prompt is the turn's
    text, the texts are its non-empty markdown parts, the tools are the names of its tool calls in order. `end` is the start plus the duration for a turn that ended, else the start (as for a round
    that still runs). `aiu` is None: the stream does not know the credits. Never raises: a stream that cannot be read is no rounds. Not cached: the reader is bounded, and a stream that grows is read again."""
    try:
        turns = chatstream.read(root, task)["turns"]
    except Exception:  # noqa: BLE001 - the file is untrusted, and the list must not fail for it
        return []
    rounds: List[Dict[str, Any]] = []
    for turn in turns:
        if not isinstance(turn, dict) or turn.get("sub"):
            continue
        at = str(turn.get("at") or "")
        end = at
        began, length = copilot_events.seconds(at), turn.get("duration")
        if turn.get("state") and began is not None and isinstance(length, (int, float)) and not isinstance(length, bool) and length >= 0:
            end = _stamp(began + length / 1000.0)
        item: Dict[str, Any] = {"at": at, "prompt": str(turn.get("text") or ""), "texts": [], "tools": [], "cut": False, "end": end, "aiu": None}
        for part in turn.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if part.get("kind") == "toolCall":
                call = part.get("toolCall")
                item["tools"].append(str((call.get("toolName") if isinstance(call, dict) else None) or "?")[:80])
            elif part.get("kind") == "markdown":
                text = str(part.get("content") or "").strip()
                room = MAX_CHARS - sum(len(each) for each in item["texts"])
                if text and room > 0:
                    item["texts"].append(text[:room])
                item["cut"] = item["cut"] or len(text) > room
        rounds.append(item)
    return rounds[-MAX_ROUNDS:]


def live(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The rounds of the task from Copilot's record: its sessions, from the round that opened the task. A session can hold other work before it and after it."""
    ids = list(dict.fromkeys([str(item.get("session_id") or "") for item in data.get("sessions") or [] if isinstance(item, dict)] + [str(data.get("session_id") or "")]))
    found = sorted((item for ident in ids if ident for item in of_session(ident)), key=lambda item: copilot_events.seconds(item["at"]) or 0.0)
    start = copilot_events.seconds(data.get("created_at")) or 0.0
    stamps = [copilot_events.seconds(item["at"]) or 0.0 for item in found]
    first = next((at for at, stamp in reversed(list(enumerate(stamps))) if stamp <= start), 0)
    closes = [copilot_events.seconds(event.get("at")) for event in data.get("events") or [] if isinstance(event, dict) and event.get("what") == "close"]
    end = (closes[-1] or 0.0) if closes and data.get("status") == "closed" else 0.0
    return [item for item, stamp in list(zip(found, stamps))[first:] if not end or stamp <= end][-MAX_ROUNDS:]


def saved(root: Path, task: str) -> Optional[List[Dict[str, Any]]]:
    try:
        with open(transcript(root, task), encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except (OSError, ValueError):
        return None


def rounds_of(root: Path, task: str) -> List[Dict[str, Any]]:
    data = tasks.read(root, task) or {}
    kept = saved(root, task) if data.get("status") == "closed" else None
    return kept or live(data) or of_stream(root, task)  # Copilot's record first; the board's own stream when it gives no round (no merging)


def took(item: Dict[str, Any]) -> Optional[float]:
    """The seconds from the prompt to the round's last step; None for a transcript saved before 1.6.98."""
    start, end = copilot_events.seconds(item.get("at")), copilot_events.seconds(item.get("end"))
    return round(max(0.0, end - start)) if start is not None and end is not None else None


def head_of(prompt: str) -> str:
    """The prompt on one line, cut at `HEAD_CHARS` with an ellipsis: the rewind dialog and a narrow window show it whole, and a cut must look cut."""
    text = " ".join(prompt.split())
    return text if len(text) <= HEAD_CHARS else text[:HEAD_CHARS - 1].rstrip() + "…"


def listing(root: Path, task: str) -> List[Dict[str, Any]]:
    """For the list: one short line each, oldest first. `n` is the place of the round: the page asks for the whole round by it. `seconds` and `aiu` (credits) are None when not known."""
    return [{"n": number, "at": item["at"], "head": head_of(item["prompt"]), "tools": len(item["tools"]), "replies": len(item["texts"]),
             "seconds": took(item), "aiu": round(item["aiu"], 1) if isinstance(item.get("aiu"), (int, float)) else None, "compact": bool(item.get("compact"))}
            for number, item in enumerate(rounds_of(root, task))]


def one(root: Path, task: str, number: Any) -> Optional[Dict[str, Any]]:
    """One round whole, the text as blocks the page draws as it draws a document."""
    found = rounds_of(root, task)
    if not isinstance(number, int) or isinstance(number, bool) or not 0 <= number < len(found):
        return None
    item = found[number]
    tools: Dict[str, int] = {}
    for name in item["tools"]:
        tools[name] = tools.get(name, 0) + 1
    return {"n": number, "at": item["at"], "prompt": item["prompt"], "texts": [mdtree.parse(text)["blocks"] for text in item["texts"]], "tools": tools, "cut": bool(item.get("cut")),
            "compact": item.get("compact")}  # {removed}: the messages Copilot summed up; None for a message


def stream_round(root: Path, task: str, found: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """`{items, turn}`: the round `found` as Live items and the id of its turn in the stream (the page asks for one call of the round by it), or None (`stream_items`). Never raises."""
    try:
        turn = chatstream.turn_of_round(chatstream.read(root, task)["turns"], found.get("at"), found.get("prompt"))
        return {"items": chatlive.items_of(turn, False, {}, root), "turn": str(turn.get("id") or "")} if turn is not None else None
    except Exception:  # noqa: BLE001 - an extra the page can do without
        return None


def stream_items(root: Path, task: str, found: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """The round `found` (a result of `one`) as the items of the Live tab, all of them, from the turn of the task's stream file (`chatstream`) that is this round (matched by time and prompt:
    `chatstream.turn_of_round`). None when the stream holds no such turn or cannot be read: the page then shows the round as it always did. Never raises."""
    try:
        turn = chatstream.turn_of_round(chatstream.read(root, task)["turns"], found.get("at"), found.get("prompt"))
        return chatlive.items_of(turn, False, {}, root) if turn is not None else None
    except Exception:  # noqa: BLE001 - an extra the page can do without
        return None


def save(root: Path, task: str) -> int:
    """Written when the task closes. How many rounds: 0 writes nothing."""
    found = live(tasks.read(root, task) or {}) or of_stream(root, task)
    if not found:
        return 0
    path = transcript(root, task)
    part = path.with_suffix(".tmp")
    part.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in found), encoding="utf-8")
    os.replace(part, path)
    return len(found)
