"""The super agent view (1.8.1): what waits for the person across all open tasks, as a list of short items, from the rows the board already computed (`BoardServer.rows()`). A pure function: no file, no model, no text of its own.

Order of `items`: three groups, then the longest wait first inside a group (`waited_s`, then `since`; a wait with no time goes last, then board order).
1. blocks running work: the chat asks or waits for a tool confirmation (`confirm`, `question`, `asking`), a held outside call (`outbox`), autorun that stopped (`autorun`);
2. decisions: `req`, `plan`, `promote`, `review`, `recover`, `accept`;
3. the rest (hand-offs, `commit`, `stopped`, `cancelled`).
`go-*` marks are left out: the person approved and the board tells the agent; nothing waits for the person. A task that waits for the person is `you` even while its agent works.
A row has one `waiting_why`, so a task has at most one item. A closed task is left out; a task put aside waits for nothing.

1.8.4: two items that are not waits of the task's own. `error` (group 0): the chat's last turn ended in an error and the row waits as `stopped` or for nothing; it takes the place of that wait; `resumable` says whether Try again can run it. `stuck` (group 0): the chat runs a turn and the session log
has been quiet for `board.stuck_seconds`; `idle_s` is the quiet, and its actions are `steer` and `stop`, the actions of the mate menu. A task that waits for the person for another reason is not stuck: its item is that wait.
The more an item says (`calls` of `outbox`, `question` of `asking`, `deliver` of `accept`) and the two above are facts the caller puts on the rows before `build`: `row["super"]` (`superfacts.put`, which reads the task folders and the logs). `build` stays a pure function of the rows; with no `row["super"]` it gives
the items of 1.8.3 and no more.
`status` also says `oldest_s` (the longest wait among the items, or None), `stuck` and `error` (how many items are of that kind). A mate is `stuck` or `error` when it has such an item, else `you` (it has another), `work` or `idle`; `status.waiting` counts the `you` mates.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from . import taskboard

BLOCKS = ("confirm", "question", "asking", "outbox", "autorun", "error", "stuck")
DECISIONS = ("req", "plan", "promote", "review", "recover", "accept")
ANSWERS = {name for names in taskboard.ACTIONS_BY_WAIT.values() for name in names} | {"confirm", "question", "send", "answer", "accept", "review dismiss"}  # the actions that answer a wait; pause, close, steer and the like stay on the task page


def group_of(why: str) -> int:
    return 0 if why in BLOCKS else 1 if why in DECISIONS else 2


def name_of(row: Dict[str, Any]) -> str:
    """The task's short name (the folder name), as the page shows it and `/task/<name>` takes it; `task` of a row is its path."""
    return str(row.get("name") or row["task"])


CHAT_ACTIONS = ("steer", "stop")  # what a person may do to a chat that runs: the mate menu's two calls


def item_of(row: Dict[str, Any]) -> Dict[str, Any]:
    """The item of the row's wait, or, when `row["super"]` says the chat failed or is stuck, that item (an `error` takes the place of `stopped`)."""
    facts = row.get("super") if isinstance(row.get("super"), dict) else {}
    why, since = str(row.get("waiting_why") or ""), str(row.get("waiting_since") or "")
    kind = str(facts.get("kind") or "")
    if kind in ("error", "stuck"):
        why = kind
        since = str(facts.get("idle_at") or since) if kind == "stuck" or not since else since  # an error keeps the time the row waits since; with none, the time of the last hook call
        wanted = CHAT_ACTIONS if kind == "stuck" else None
        waited = facts.get("idle_s") if kind == "stuck" or row.get("waited_s") is None else row.get("waited_s")
        item = {"id": f"{name_of(row)}|{why}|{since}", "task": name_of(row), "why": why, "since": since, "waited_s": waited, "title": facts.get("title") or "", "detail": facts.get("detail") or "",
                "actions": [dict(action) for action in row.get("actions") or [] if action.get("action") in (wanted or ANSWERS)]}
        if kind == "error":
            item["resumable"] = bool(facts.get("resumable"))
        else:
            item["idle_s"] = facts.get("idle_s")
        return item
    item = {
        "id": f"{name_of(row)}|{why}|{since}", "task": name_of(row), "why": why, "since": since, "waited_s": row.get("waited_s"),
        "title": row.get("waiting") or "", "detail": row.get("waiting_tip") or "",
        "actions": [dict(action) for action in row.get("actions") or [] if action.get("action") in ANSWERS],
    }
    if why == "outbox" and "calls" in facts:
        item["calls"] = [dict(call) for call in facts["calls"] if isinstance(call, dict)]
    elif why == "asking" and facts.get("question"):
        item["question"] = {"message": str(facts["question"].get("message") or ""), "options": list(facts["question"].get("options") or [])}
    elif why == "accept" and facts.get("deliver"):
        item["deliver"] = dict(facts["deliver"])
    return item


def counts(row: Dict[str, Any]) -> bool:
    """Does this row have an item? A wait of its own (not a `go-*` mark, not put aside), or an error or stuck chat."""
    if row.get("paused_since"):
        return False
    facts = row.get("super") if isinstance(row.get("super"), dict) else {}
    why = str(row.get("waiting_why") or "")
    return facts.get("kind") in ("error", "stuck") or bool(why and not why.startswith("go-"))


def order_key(entry: Tuple[int, Dict[str, Any]]) -> Tuple[Any, ...]:
    index, item = entry
    waited = item["waited_s"]
    return (group_of(item["why"]), waited is None, -(waited or 0), item["since"], index)


def build(result: Dict[str, Any]) -> Dict[str, Any]:
    """`result`: what `BoardServer.rows()` returns. Returns `status`, `mates` (one per open task, in board order) and `items`."""
    open_rows = [row for row in result.get("rows") or [] if row.get("status") == "open"]
    found = sorted(((index, item_of(row)) for index, row in enumerate(open_rows) if counts(row)), key=order_key)
    items = [item for _index, item in found]
    per_task: Dict[str, int] = {}
    kinds: Dict[str, str] = {}
    for item in items:
        per_task[item["task"]] = per_task.get(item["task"], 0) + 1
        if item["why"] in ("error", "stuck"):
            kinds[item["task"]] = item["why"]
    mates: List[Dict[str, Any]] = []
    for row in open_rows:
        count = per_task.get(name_of(row), 0)
        state = kinds.get(name_of(row)) or ("you" if count else "work" if row.get("state") == "working" else "idle")
        mates.append({"task": name_of(row), "kind": row.get("kind") or "", "state": state, "count": count})
    tally = [mate["state"] for mate in mates]
    waited = [item["waited_s"] for item in items if isinstance(item["waited_s"], (int, float))]
    status = {"watching": len(mates), "working": tally.count("work"), "waiting": tally.count("you"), "idle": tally.count("idle"), "as_of": result.get("as_of") or "",
              "oldest_s": max(waited) if waited else None, "stuck": sum(1 for item in items if item["why"] == "stuck"), "error": sum(1 for item in items if item["why"] == "error")}
    return {"status": status, "mates": mates, "items": items}
