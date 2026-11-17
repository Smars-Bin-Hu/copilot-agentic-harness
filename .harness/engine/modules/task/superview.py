"""The super agent view (1.8.1): what waits for the person across all open tasks, as a list of short items, from the rows the board already computed (`BoardServer.rows()`). A pure function: no file, no model, no text of its own.

Order of `items`: three groups, then the longest wait first inside a group (`waited_s`, then `since`; a wait with no time goes last, then board order).
1. blocks running work: the chat asks or waits for a tool confirmation (`confirm`, `question`, `asking`), a held outside call (`outbox`), autorun that stopped (`autorun`);
2. decisions: `req`, `plan`, `promote`, `review`, `recover`, `accept`;
3. the rest (hand-offs, `commit`, `stopped`, `cancelled`).
`go-*` marks are left out: the person approved and the board tells the agent; nothing waits for the person. A task that waits for the person is `you` even while its agent works.
A row has one `waiting_why`, so a task has at most one item. A closed task is left out; a task put aside waits for nothing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from . import taskboard

BLOCKS = ("confirm", "question", "asking", "outbox", "autorun")
DECISIONS = ("req", "plan", "promote", "review", "recover", "accept")
ANSWERS = {name for names in taskboard.ACTIONS_BY_WAIT.values() for name in names} | {"confirm", "question", "send", "answer", "accept", "review dismiss"}  # the actions that answer a wait; pause, close, steer and the like stay on the task page


def group_of(why: str) -> int:
    return 0 if why in BLOCKS else 1 if why in DECISIONS else 2


def name_of(row: Dict[str, Any]) -> str:
    """The task's short name (the folder name), as the page shows it and `/task/<name>` takes it; `task` of a row is its path."""
    return str(row.get("name") or row["task"])


def item_of(row: Dict[str, Any]) -> Dict[str, Any]:
    why, since = str(row.get("waiting_why") or ""), str(row.get("waiting_since") or "")
    return {
        "id": f"{name_of(row)}|{why}|{since}", "task": name_of(row), "why": why, "since": since, "waited_s": row.get("waited_s"),
        "title": row.get("waiting") or "", "detail": row.get("waiting_tip") or "",
        "actions": [dict(action) for action in row.get("actions") or [] if action.get("action") in ANSWERS],
    }


def order_key(entry: Tuple[int, Dict[str, Any]]) -> Tuple[Any, ...]:
    index, item = entry
    waited = item["waited_s"]
    return (group_of(item["why"]), waited is None, -(waited or 0), item["since"], index)


def build(result: Dict[str, Any]) -> Dict[str, Any]:
    """`result`: what `BoardServer.rows()` returns. Returns `status`, `mates` (one per open task, in board order) and `items`."""
    open_rows = [row for row in result.get("rows") or [] if row.get("status") == "open"]
    found = sorted(((index, item_of(row)) for index, row in enumerate(open_rows) if row.get("waiting_why") and not str(row.get("waiting_why")).startswith("go-") and not row.get("paused_since")), key=order_key)
    items = [item for _index, item in found]
    counts: Dict[str, int] = {}
    for item in items:
        counts[item["task"]] = counts.get(item["task"], 0) + 1
    mates: List[Dict[str, Any]] = []
    for row in open_rows:
        count = counts.get(name_of(row), 0)
        mates.append({"task": name_of(row), "kind": row.get("kind") or "", "state": "you" if count else "work" if row.get("state") == "working" else "idle", "count": count})
    tally = [mate["state"] for mate in mates]
    return {"status": {"watching": len(mates), "working": tally.count("work"), "waiting": tally.count("you"), "idle": tally.count("idle"), "as_of": result.get("as_of") or ""}, "mates": mates, "items": items}
