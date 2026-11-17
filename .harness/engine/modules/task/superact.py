"""Proposals of the super agent (1.8.3): the agent never does anything; it may end an answer with one block and the page draws a card from it, with the board's own buttons.

  split   `split(text) -> (shown, raw_items)`: the text without any block, and the items of the last block (None when the answer has no block; `[None]` when the block is broken or has too many items).
  check   `check(raw_items, rows, served_actions) -> [proposal]`: each item checked against the rows of the board as they are now. A proposal is `{kind, task, ..., ok, why?}`; what is not ok has a `why` and no button.
          `rows`: the `rows` of `BoardServer.rows()`; `served_actions`: what the board server runs (None: not known, `review set` is then judged by the row alone).
          `kind` `action`: ok when the task is a row of the board and the board offers the action for that row now (its `actions`), or `review set` (open task, `n` 0-9), or `steer` / `stop` (open task that works).
          `kind` `send`: ok for an open task that is not paused. `kind` `new`: ok for a free, valid folder name. Anything else is `{kind: bad, ok: false, why: bad}`.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from . import superview, tasklife
from .common import CommandError

OPEN, CLOSE = "<harness-proposals>", "</harness-proposals>"
MAX_ITEMS = 8
MAX_TEXT = 2000
MAX_BLOCK = 40000  # characters of one block: more is one bad item, not parsed
TASK_KINDS = ("qa", "rca", "design", "dev", "test", "kb", "other")
BOARD_ACTIONS = {"confirm-req", "approve-plan", "approve-promote", "recover", "review extend", "review waive", "approve-action", "send", "answer", "accept", "review dismiss", "review set",
                 "autorun on", "pause", "resume", "close", "archive", "confirm", "question", "steer", "stop", "dismiss action", "task allow", "task link", "test runner"}
BAD = {"kind": "bad", "ok": False, "why": "bad"}


def split(text: Any) -> Tuple[str, Optional[List[Any]]]:
    """The text the person sees, and the raw items of the last block. A block that is not closed (the answer is still written) is cut out too and gives no items.
    One pass over the text with `find` (no regex): an answer full of opening tags costs the same as any other text."""
    whole = str(text or "")
    parts: List[str] = []
    blocks: List[str] = []
    pos = 0
    while True:
        at = whole.find(OPEN, pos)
        if at < 0:
            parts.append(whole[pos:])
            break
        parts.append(whole[pos:at])
        end = whole.find(CLOSE, at + len(OPEN))
        if end < 0:
            break  # not closed: the rest is cut out
        blocks.append(whole[at + len(OPEN):end])
        pos = end + len(CLOSE)
    shown = "".join(parts).replace(CLOSE, "").strip()  # a stray closing tag (a nested block) is not shown either
    if not blocks:
        return shown, None
    if len(blocks[-1]) > MAX_BLOCK:
        return shown, [None]
    try:
        found = json.loads(blocks[-1])
    except Exception:  # noqa: BLE001 - not JSON, or nested too deep (RecursionError): one bad item, never an error of the whole talk
        return shown, [None]
    if not isinstance(found, list) or len(found) > MAX_ITEMS:
        return shown, [None]
    return shown, found


def words(item: Dict[str, Any], key: str = "text") -> str:
    value = item.get(key)
    return value.strip() if isinstance(value, str) else ""


def row_of(rows: List[Dict[str, Any]], name: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(name, str) or not name:
        return None
    return next((row for row in rows if isinstance(row, dict) and superview.name_of(row) == name), None)


def action_of(item: Dict[str, Any], rows: List[Dict[str, Any]], served: Optional[Any]) -> Dict[str, Any]:
    task, action = item.get("task"), item.get("action")
    out: Dict[str, Any] = {"kind": "action", "task": task if isinstance(task, str) else "", "action": action if isinstance(action, str) else "", "ok": False}
    row = row_of(rows, task)
    if row is None:
        return dict(out, why="unknown")
    if action not in BOARD_ACTIONS:
        return dict(out, why="kind")
    open_row = row.get("status") == "open"
    if action == "review set":
        n = item.get("n")
        if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= 9:
            return dict(out, why="n")
        if not open_row or (served is not None and action not in served):
            return dict(out, why="state")
        return dict(out, n=n, ok=True)
    if action in ("steer", "stop"):
        if not open_row or row.get("state") != "working":
            return dict(out, why="state")
        if action == "stop":
            return dict(out, ok=True)
        text = words(item)
        if not text or len(text) > MAX_TEXT:
            return dict(out, why="text")
        return dict(out, text=text, ok=True)
    if not any(isinstance(one, dict) and one.get("action") == action for one in row.get("actions") or []):
        return dict(out, why="state")
    return dict(out, ok=True)


def send_of(item: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    task = item.get("task")
    text = words(item)
    out: Dict[str, Any] = {"kind": "send", "task": task if isinstance(task, str) else "", "text": text, "ok": False}
    row = row_of(rows, task)
    if row is None:
        return dict(out, why="unknown")
    if row.get("status") != "open":
        return dict(out, why="closed")
    if row.get("paused_since"):
        return dict(out, why="paused")
    if not text:
        return dict(out, why="empty")
    if len(text) > MAX_TEXT:
        return dict(out, why="long")
    return dict(out, ok=True)


def new_of(item: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    name, text = item.get("name"), words(item)
    kind = item.get("task_kind")
    out: Dict[str, Any] = {"kind": "new", "name": name if isinstance(name, str) else "", "task_kind": kind if kind in TASK_KINDS else "dev", "text": text, "ok": False}
    if not isinstance(name, str):
        return dict(out, why="name")
    try:
        clean = tasklife.clean_name(name)
    except CommandError:
        return dict(out, why="name")
    if clean != name:
        return dict(out, why="name")
    if any(isinstance(row, dict) and superview.name_of(row) == name for row in rows):
        return dict(out, why="taken")
    if not text:
        return dict(out, why="empty")
    if len(text) > MAX_TEXT:
        return dict(out, why="long")
    return dict(out, ok=True)


def check(raw_items: Optional[List[Any]], rows: Any, served_actions: Optional[Any] = None) -> List[Dict[str, Any]]:
    """The proposals of one answer (see the head). What cannot be judged is not ok."""
    if raw_items is None:
        return []
    if not isinstance(raw_items, list) or len(raw_items) > MAX_ITEMS or not isinstance(rows, list):
        return [dict(BAD)]
    found: List[Dict[str, Any]] = []
    for item in raw_items:
        kind = item.get("kind") if isinstance(item, dict) else None
        try:
            if kind == "action":
                found.append(action_of(item, rows, served_actions))
            elif kind == "send":
                found.append(send_of(item, rows))
            elif kind == "new":
                found.append(new_of(item, rows))
            else:
                found.append(dict(BAD))
        except Exception:  # noqa: BLE001 - an item that cannot be judged does not pass
            found.append(dict(BAD))
    return found
