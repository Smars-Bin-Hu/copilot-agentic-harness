"""Tool calls the harness has not seen: a tool name it does not know, or a shape it cannot read. Only for `doctor`.

  <logs>/unseen-tools.jsonl     one line per surface, tool and shape. Names and keys only: never a value, a path or a prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import json

from .events import HookEvent
from .logs import _append
from .paths import logs_dir, utc_now

FILE = "unseen-tools.jsonl"
MAX_LINES = 200
WRITE_KINDS = ("edit", "create")


def shape(value: Any) -> str:
    if isinstance(value, dict):
        return ",".join(sorted(str(key) for key in value))
    return type(value).__name__


def read(root: Path) -> List[Dict[str, Any]]:
    try:
        lines = (logs_dir(root) / FILE).read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]
    except (OSError, ValueError):
        return []


def is_unseen(event: HookEvent) -> bool:
    if event.tool_kind == "other":
        return True
    if event.tool_kind in WRITE_KINDS:
        return not event.paths
    return event.tool_kind == "terminal" and not event.command


def note_call(root: Path, event: HookEvent) -> None:
    """Never raises: this record must not get in the way of a call."""
    try:
        if not is_unseen(event):
            return
        tool_input = event.raw.get("tool_input") if isinstance(event.raw, dict) else None
        record = {"surface": event.surface, "tool": event.tool_name, "kind": event.tool_kind, "shape": shape(tool_input)}
        known = read(root)
        if len(known) >= MAX_LINES or any(all(item.get(key) == value for key, value in record.items()) for item in known):
            return
        _append(root, FILE, dict(record, first_seen=utc_now()))
    except Exception:  # noqa: BLE001
        return
