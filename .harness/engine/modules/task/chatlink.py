"""Which chat of VS Code belongs to which task (1.6, B71). Never a guess: when it is not sure, the task is unbound.

Two ways to bind, the first wins:
1. The chat was made by the board for this task (B73 writes `chat.how = "board"` in the task state when it creates it). It stands while the chat exists.
2. The id Copilot gave the session behind a chat (`sdkSessionId`, found in the chat's turns) is the `session_id` of the task. The hook calls that id `session_id`.

It is not sure, so the task stays unbound, when: no chat has the id (a chat has no id until the model was called once), two chats have it, or two open tasks have the
same session id and the session does not hold exactly one of them.

The result is kept in the task state as `chat: {session, chat, title, how, bound_at, sdk}` (`sdk` only for `how = "sdk"`). Writing it does not change `updated_at`:
a binding is not something the person did, and the board lights a row whose time changed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from core import tasks
from core.paths import utc_now
from core.state import atomic_write, state_lock

Entry = Dict[str, Any]  # {task, name, session_id, held, chat}: an open task as the binding sees it


def decide(entries: List[Entry], summaries: Dict[str, Dict[str, Any]], sdk: Dict[str, Set[str]]) -> Dict[str, Tuple[Optional[Dict[str, Any]], str]]:
    """For each open task: (binding or None, why). `why` of an unbound task: `no-chat` (no chat has its session id), `ambiguous`, `no-session` (the task has no session).
    `summaries`: the chats of the folder, by resource; `sdk`: the Copilot ids found in each, by resource (a chat not read yet is not in it)."""
    by_sdk: Dict[str, List[str]] = {}
    for resource, ids in sdk.items():
        if resource in summaries:
            for one in ids:
                by_sdk.setdefault(one, []).append(resource)
    sharing: Dict[str, List[Entry]] = {}
    for entry in entries:
        if entry.get("session_id"):
            sharing.setdefault(entry["session_id"], []).append(entry)
    out: Dict[str, Tuple[Optional[Dict[str, Any]], str]] = {}
    for entry in entries:
        task, stored = entry["task"], entry.get("chat") or {}
        if stored.get("how") == "board" and stored.get("session") in summaries:
            out[task] = (dict(stored), "")
            continue
        session = str(entry.get("session_id") or "")
        if not session:
            out[task] = (None, "no-session")
            continue
        found = by_sdk.get(session, [])
        if len(found) != 1:
            out[task] = (None, "ambiguous" if len(found) > 1 else "no-chat")
            continue
        owners = sharing.get(session, [])
        if len(owners) > 1 and [owner["task"] for owner in owners if owner.get("held")] != [task]:
            out[task] = (None, "ambiguous")
            continue
        summary = summaries[found[0]]
        out[task] = ({"session": found[0], "chat": str(summary.get("defaultChat") or ""), "title": str(summary.get("title") or ""), "how": "sdk", "bound_at": utc_now(), "sdk": session}, "")
    return out


def same(left: Optional[Dict[str, Any]], right: Optional[Dict[str, Any]]) -> bool:
    """The same binding: the same chat found the same way (the title and the time do not make a new one)."""
    if not left or not right:
        return not left and not right
    return all(left.get(key) == right.get(key) for key in ("session", "chat", "how", "sdk"))


def keep(root: Any, task: str, binding: Optional[Dict[str, Any]]) -> bool:
    """Write the binding into the task state (or take it out); True when the file changed. `updated_at` stays."""
    path = tasks.state_file(root, task)
    if not path.exists():
        return False
    with state_lock(path):
        data = tasks.read(root, task)
        if data is None or same(data.get("chat"), binding):
            return False
        if binding:
            data["chat"] = binding
        else:
            data.pop("chat", None)
        atomic_write(path, data)
        return True
