"""The rounds of a task's chat (1.6.55): each prompt of the person, with all the text the agent wrote for it, for the Live tab.

The record is Copilot's own `events.jsonl` (`core/copilot_events.py`). It has every model call's text, also what the chat window folds away, and it can be read with VS Code closed.
Kept: the prompt, the agent's text, the names of the tools, when the round's last step ended and the credits it cost (1.6.98: the session's running total of
`session.usage_checkpoint`, minus what it was before the round; a subagent's credits count with the round that started it). Left out: thinking, tool results, hooks and
the other usage numbers (they are in VS Code), and all a subagent says.

When a task closes the rounds are saved in `.task/transcript.jsonl`, because Copilot's file is not ours to rely on. A closed task reads that file. `taskarchive.prune_transcripts` deletes
it `transcript.keep_days` after the archive; the task's audit files stay. Copilot's own files are never touched.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import copilot_events, tasks

from . import mdtree

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
    spent = 0.0  # the session's credits so far
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
            if kind == "session.usage_checkpoint":
                total = copilot_events.number(found.get("totalNanoAiu"))
                if total is not None:
                    if rounds:
                        rounds[-1]["aiu"] = (rounds[-1]["aiu"] or 0.0) + max(0.0, total / copilot_events.NANO - spent)
                    spent = total / copilot_events.NANO
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
    return kept if kept is not None else live(data)


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


def save(root: Path, task: str) -> int:
    """Written when the task closes. How many rounds: 0 writes nothing."""
    found = live(tasks.read(root, task) or {})
    if not found:
        return 0
    path = transcript(root, task)
    part = path.with_suffix(".tmp")
    part.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in found), encoding="utf-8")
    os.replace(part, path)
    return len(found)
