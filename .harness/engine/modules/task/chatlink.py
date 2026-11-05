"""Which chat of VS Code belongs to which task (1.6, B71). Never a guess: when it is not sure, the task is unbound.

Two ways to bind, the first wins:
1. The chat was made by the board for this task (B73: the board remembers the chat it made, and writes `chat.how = "board"` in the task state as soon as the task exists: `adopt`). It stands while the chat exists,
   until another chat picks the task up (1.6.109): the task's session id is then neither the one it had when the board bound the chat (`was`) nor one of the board chat's own, and exactly one
   other chat has it. The board then follows that chat by rule 2: the person went on with the task elsewhere, in VS Code.
   The same for a chat made to go on with a task that exists ("go on in a new chat", 1.6.97): bound at once, not when its agent has answered (`was` is the old chat's id, so it does not pull back).
2. The id Copilot gave the session behind a chat (`sdkSessionId`, found in the chat's turns) is the `session_id` of the task. The hook calls that id `session_id`.

It is not sure, so the task stays unbound, when: no chat has the id (a chat has no id until the model was called once), two chats have it, or two open tasks have the
same session id and the session does not hold exactly one of them.

The result is kept in the task state as `chat: {session, chat, title, how, bound_at, sdk}` (`sdk` only for `how = "sdk"`). Writing it does not change `updated_at`:
a binding is not something the person did, and the board lights a row whose time changed.
`chat.model = {id, config}` is the person's (B72, the task page): a binding comes and goes around it, and is never allowed to drop it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from core import tasks
from core.paths import utc_now
from core.state import atomic_write, state_lock

Entry = Dict[str, Any]  # {task, name, session_id, held, chat}: an open task as the binding sees it


def listed_as(session: str, summaries: Dict[str, Dict[str, Any]]) -> str:
    """The resource under which the host lists a session: the one given, or the same id in the other form (`ahp-session:/<id>` and `copilotcli:/<id>` are one session). Empty when it is not listed."""
    if session in summaries:
        return session
    tail = session.rsplit("/", 1)[-1]
    found = [resource for resource in summaries if tail and resource.rsplit("/", 1)[-1] == tail]
    return found[0] if len(found) == 1 else ""


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
        listed = listed_as(str(stored.get("session") or ""), summaries) if stored.get("how") == "board" else ""
        session = str(entry.get("session_id") or "")
        if listed and not moved_on(session, stored, listed, sdk, by_sdk):
            out[task] = (dict(stored, session=listed, chat=str(summaries[listed].get("defaultChat") or stored.get("chat") or "")), "")
            continue
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


def moved_on(session: str, stored: Dict[str, Any], listed: str, sdk: Dict[str, Set[str]], by_sdk: Dict[str, List[str]]) -> bool:
    """Did another chat pick the task up after the board bound its own chat? Only on sure signs: a session id that is new since the binding (`was`), not the board chat's own, and in exactly
    one other chat. A chat not read yet says nothing, so the board chat stands."""
    if not session or session == stored.get("was") or session in sdk.get(listed, set()):
        return False
    found = by_sdk.get(session, [])
    return len(found) == 1 and found[0] != listed


def wants_scan(entries: List[Entry], summaries: Dict[str, Dict[str, Any]], sdk: Dict[str, Set[str]], found: Dict[str, Tuple[Optional[Dict[str, Any]], str]]) -> bool:
    """Must chats be read for their Copilot ids? Yes for a task with a session and no chat, and for a task bound to a chat of the board whose session id is new since (1.6.111): another chat
    may have picked it up, and only a read of that chat lets `moved_on` see it. Before, such a task counted as bound, no chat was read, and the board stayed on the old chat for good."""
    for entry in entries:
        session = str(entry.get("session_id") or "")
        binding = found.get(entry["task"], (None, ""))[0]
        if not session:
            continue
        if binding is None:
            return True
        if binding.get("how") == "board" and session != binding.get("was") and session not in sdk.get(str(binding.get("session") or ""), set()):
            return True
    return False


def same(left: Optional[Dict[str, Any]], right: Optional[Dict[str, Any]]) -> bool:
    """The same binding: the same chat found the same way (the title, the time and the person's model do not make a new one)."""
    left = left if left and left.get("session") else None
    right = right if right and right.get("session") else None
    if not left or not right:
        return not left and not right
    return all(left.get(key) == right.get(key) for key in ("session", "chat", "how", "sdk"))


def keep(root: Any, task: str, binding: Optional[Dict[str, Any]]) -> bool:
    """Write the binding into the task state (or take it out); True when the file changed. `updated_at` stays. The person's `model` stays whatever happens to the binding."""
    path = tasks.state_file(root, task)
    if not path.exists():
        return False
    with state_lock(path):
        data = tasks.read(root, task)
        if data is None or same(data.get("chat"), binding):
            return False
        model = (data.get("chat") or {}).get("model")
        found = dict(binding) if binding else {}
        if model:
            found["model"] = model
        if found:
            data["chat"] = found
        else:
            data.pop("chat", None)
        atomic_write(path, data)
        return True


def adopt(root: Any, task: str, made: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The task a chat of the board was made for now exists: write the binding `how = "board"` (first priority) and keep the model the person chose in the dialog, unless the task already has one.
    `made`: what the board remembered at the create (`chatnew.pending`). With `keep_model` false (a click's model, which the person did not choose) the model is not kept.
    Returns the binding written, or None when the task is gone. `updated_at` stays."""
    path = tasks.state_file(root, task)
    if not path.exists():
        return None
    with state_lock(path):
        data = tasks.read(root, task)
        if data is None:
            return None
        model = (data.get("chat") or {}).get("model") or (made.get("model") if made.get("keep_model", True) else None)
        found: Dict[str, Any] = {"session": made["session"], "chat": made["chat"], "title": made.get("title", ""), "how": "board", "bound_at": utc_now(), "was": str(data.get("session_id") or "")}  # `was`: see `moved_on`
        if model:
            found["model"] = model
        data["chat"] = found
        atomic_write(path, data)
        return found
