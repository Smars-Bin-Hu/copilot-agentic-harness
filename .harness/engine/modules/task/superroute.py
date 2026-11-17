"""Asking a task from the super agent view (1.8.2, step 3): the person's question goes to one task's chat with the `/harness-ask` marker; the gate makes that turn read only.

  ask    `ask(brain, data)`: `{task, text, lang}` -> `{ok: true, id, state}` or `{ok: false, why}`. Sent when the task's chat is idle, queued when it works, never steered (a steer would
         break into the turn that runs). The question is recorded in today's super record, under `asks`. `why`: `empty`, `long`, `unknown`, `paused`, `nochat`, `asleep`, `error`, or the reason
         of `vslink.Refused` as it is.
  read   `read(brain, rec)`: take the answers into `rec["asks"]` from what the link already holds of each task's chat (the cache; no call to the host). True when something changed.
  An ask is `{id, task, text, at, state, turn, answer, answer_at, end}` (+ `why` on `failed`). `state`: sent, queued, answered, failed. `sent` and `sent_ts` are kept in the record only.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from core import tasks
from core.paths import utc_now

from . import chatsend, task as task_ops, tasklife, vslink
from .common import CommandError

MARKER = "/harness-ask"  # the same as `modules/gate/askturn.MARKER`: the gate makes the turn that starts with it read only
MAX_ASK = 1000  # characters of what the person types
LOST_AFTER = 180.0  # seconds after which a question that the chat shows nowhere is given up
OPEN = ("sent", "queued")
PUBLIC = ("id", "task", "text", "at", "state", "turn", "answer", "answer_at", "end", "why")


def public(entry: Dict[str, Any]) -> Dict[str, Any]:
    """The entry as the page and the history see it."""
    return {key: entry[key] for key in PUBLIC if key in entry}


def valid(entry: Any) -> bool:
    return isinstance(entry, dict) and bool(entry.get("id")) and isinstance(entry.get("task"), str) and isinstance(entry.get("text"), str)


def message_of(text: str) -> str:
    return MARKER + "\n" + text


def refusal(why: str) -> Dict[str, Any]:
    return {"ok": False, "why": why}


def open_task(brain: Any, raw: Any) -> Optional[Dict[str, Any]]:
    """The task (`{task, data}`) when `raw` names an open one; None when there is none."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        task = task_ops.resolve(brain.root, text)
        found = tasks.read(brain.root, task)
    except (CommandError, ValueError, OSError):
        return None
    if not found or found.get("status") != "open":
        return None
    return {"task": task, "data": found}


def ask(brain: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    """Send the person's question to the chat of one task. See the head of this file."""
    words = str(data.get("text") or "").strip()
    if not words:
        return refusal("empty")
    if len(words) > MAX_ASK:
        return refusal("long")
    named = open_task(brain, data.get("task"))
    if named is None:
        return refusal("unknown")
    task, found = named["task"], named["data"]
    if tasklife.paused_since(found):
        return refusal("paused")
    lang = str(data.get("lang") or "")
    body, problem = chatsend.steer_text(words, lang)
    if problem:
        return refusal("long" if problem == "long" else "empty")
    text = message_of(chatsend.with_english(brain.root, task, lang, body))
    try:
        why = brain.link.check(task, "send")
        kind = "send"
        if why == "not-idle":  # it works: the question waits for the end of the turn
            why, kind = brain.link.check(task, "queue"), "queue"
        if why:
            raise vslink.Refused(why)
        done = brain.link.dispatch(kind, task, text, chatsend.model_of(found))
    except vslink.Refused as error:
        return refusal(reason(error.why))
    except Exception as error:  # noqa: BLE001 - the host's words are not for the page
        try:
            brain.link.host_said(error)
        except Exception:  # noqa: BLE001
            pass
        return refusal("error")
    state = "sent" if kind == "send" else "queued"
    entry = {"id": "ask-" + uuid.uuid4().hex[:12], "task": task, "text": words, "at": utc_now(), "state": state, "turn": str(done.get("turn") or "") if kind == "send" else "",
             "answer": "", "answer_at": "", "end": "", "sent": text, "sent_ts": time.time()}
    with brain.lock:
        rec = brain.load()
        rec["asks"].append(entry)
        brain.save(rec)
    return {"ok": True, "id": entry["id"], "state": state}


def reason(why: str) -> str:
    """A refusal of the link in the words of SPEC B: the chat of the task is not there, or VS Code is not linked."""
    if why in ("off", "not-ready"):
        return "asleep"
    if why in ("unbound", "unsure"):
        return "nochat"
    return why


# --- the answers -----------------------------------------------------------------------------------------------------

def chat_state(link: Any, task: str) -> Optional[Dict[str, Any]]:
    """The cached, trimmed snapshot of the chat the task is bound to; None when the link does not know it (not ready, not bound, not read yet). A copy of what is needed, taken under the lock of the link."""
    try:
        with link.lock:
            binding = link.bound.get(task) if link.ready else None
            held = link.chats.get(binding["chat"]) if binding else None
            state = held.get("state") if held else None
            if not isinstance(state, dict):
                return None
            return {"turns": [dict(turn) for turn in state.get("turns") or [] if isinstance(turn, dict)],
                    "activeTurn": dict(state["activeTurn"]) if isinstance(state.get("activeTurn"), dict) else None,
                    "queued": [str(item.get("text") or "") for item in state.get("queuedMessages") or [] if isinstance(item, dict)]}
    except (AttributeError, TypeError, KeyError):
        return None


def text_of(turn: Dict[str, Any]) -> str:
    """What the agent wrote in a turn: its text parts, in order."""
    return "\n".join(str(part.get("content") or "").strip() for part in turn.get("responseParts") or [] if isinstance(part, dict) and part.get("kind") == "markdown" and str(part.get("content") or "").strip())


def message_text(turn: Dict[str, Any]) -> str:
    message = turn.get("message")
    return str(message.get("text") or "") if isinstance(message, dict) else ""


def find_turn(entry: Dict[str, Any], snapshot: Dict[str, Any], taken: List[str]) -> Optional[Dict[str, Any]]:
    """The turn of this question in the snapshot: by its id when it has one, else (it was queued) the first turn that holds its words and no other question has. `{turn, ended}`."""
    turns = [(turn, True) for turn in snapshot["turns"]] + ([(snapshot["activeTurn"], False)] if snapshot["activeTurn"] else [])
    for turn, ended in turns:
        ident = str(turn.get("id") or "")
        if entry.get("turn") and ident == entry["turn"]:
            return {"turn": turn, "ended": ended}
        if not entry.get("turn") and ident and ident not in taken and message_text(turn) == entry.get("sent"):
            return {"turn": turn, "ended": ended}
    return None


def read(brain: Any, rec: Dict[str, Any]) -> bool:
    """Take the answers of the questions that wait into `rec["asks"]`. True when `rec` changed."""
    changed = False
    snapshots: Dict[str, Optional[Dict[str, Any]]] = {}
    taken = [str(item.get("turn")) for item in rec["asks"] if item.get("turn")]
    for entry in rec["asks"]:
        if entry.get("state") not in OPEN:
            continue
        task = str(entry["task"])
        if task not in snapshots:
            snapshots[task] = chat_state(brain.link, task)
        snapshot = snapshots[task]
        if snapshot is None:
            continue  # the link does not know the chat now: nothing is judged
        found = find_turn(entry, snapshot, taken)
        if found is None:
            if entry["state"] == "queued" and str(entry.get("sent")) in snapshot["queued"]:
                continue  # still waits for its turn
            if time.time() - float(entry.get("sent_ts") or 0) > LOST_AFTER:
                entry.update(state="failed", why="lost", end="lost", answer_at=utc_now())
                changed = True
            continue
        turn = found["turn"]
        if not entry.get("turn"):
            entry["turn"] = str(turn.get("id"))
            taken.append(entry["turn"])
            changed = True
        if entry["state"] == "queued":
            entry["state"] = "sent"  # its turn began
            changed = True
        if found["ended"]:
            end = str(turn.get("state") or "complete")
            entry.update(answer=text_of(turn), answer_at=utc_now(), end=end, state="answered" if end == "complete" else "failed")
            if end != "complete":
                entry["why"] = end
            changed = True
    return changed
