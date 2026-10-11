"""Which knowledge base files a tool call read (M8-8).

The call log leaves no trace of what a call touched. This is the one exception: a path inside a knowledge base is
kept, so a team can see which files nobody reads and which a failed task never opened. Names only, never content.

A knowledge base is a repository registered with `knowledge_base: true` (target.json) or the folder `knowledge-base/`.
What is seen: the paths of read and search tools, and paths written out in a terminal command (`cat knowledge-base/x.md`).
What is not: a file a command reaches without naming it (`grep -r` over a folder names the folder, not each file).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config, targets
from .events import HookEvent
from .logs import read_lines, session_files

READ_KINDS = ("read", "search", "terminal")
MAX_PATHS = 20
SKIPPED_PARTS = (".git",)
_WORDS = re.compile(r"""[^\s"'`;|&<>()=,]+""")


def named(event: HookEvent) -> List[str]:
    found = list(event.paths)
    if event.tool_kind == "terminal" and event.command:
        found += [word for word in _WORDS.findall(event.command) if "/" in word or "\\" in word or "." in word]
    return found


def inside(bases: List[Tuple[str, Path]], path: Path) -> str:
    """`<knowledge base>/<path in it>` (a folder ends with `/`), or "" when the path is in none."""
    for name, folder in bases:
        try:
            relative = path.relative_to(folder)
        except ValueError:
            continue
        if any(part in SKIPPED_PARTS for part in relative.parts):
            return ""
        text = relative.as_posix()
        if text == ".":
            return name + "/"
        return f"{name}/{text}" + ("/" if path.is_dir() else "")
    return ""


def of_event(root: Path, event: HookEvent) -> List[str]:
    """The knowledge base paths a finished tool call named. Empty for anything else. Never raises."""
    try:
        if event.event != "PostToolUse" or event.tool_kind not in READ_KINDS:
            return []
        candidates = named(event)
        if not candidates:
            return []
        if config.load_policy(root, "observe").get("knowledge_base_reads", True) is False:
            return []
        bases = [(name, folder.resolve()) for name, folder in targets.knowledge_bases(root) if folder.is_dir()]
        if not bases:
            return []
        homes = [Path(event.cwd)] if event.cwd and Path(event.cwd).is_dir() else []
        homes.append(root)
        found: List[str] = []
        for raw in candidates:
            path = Path(raw)
            for candidate in ([path] if path.is_absolute() else [home / path for home in homes]):
                try:
                    resolved = candidate.resolve()
                    if not resolved.exists():
                        continue
                except OSError:
                    continue
                key = inside(bases, resolved)
                if key and key not in found:
                    found.append(key)
                break
            if len(found) >= MAX_PATHS:
                break
        return found
    except Exception:  # noqa: BLE001 - a line in a log; never in the way of a hook
        return []


# --- reading the log back ---------------------------------------------------------------------


def task_name(task: str) -> str:
    return task.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def reads_by_task(root: Path, days: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
    """path -> {reads, tasks, sessions}. The task of a read is the task of the prompt it came after ("" when none)."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() if days is not None else ""
    found: Dict[str, Dict[str, Any]] = {}
    for _surface, path in session_files(root):
        task = ""
        for row in read_lines(path):
            if row.get("event") == "UserPromptSubmit" and not row.get("from_subagent") and not row.get("continuation"):
                task = task_name(row["task"]) if row.get("task") else ""
            if since and row.get("at", "") < since:
                continue
            for name in row.get("kb") or []:
                entry = found.setdefault(str(name), {"reads": 0, "tasks": set(), "sessions": set()})
                entry["reads"] += 1
                entry["sessions"].add(path.stem)
                if task:
                    entry["tasks"].add(task)
    return found


def of_task(root: Path, task: str) -> List[Dict[str, Any]]:
    """The knowledge base files one task read, most read first."""
    name = task_name(task)
    return [
        {"file": path, "reads": entry["reads"]}
        for path, entry in sorted(reads_by_task(root).items(), key=lambda item: (-item[1]["reads"], item[0]))
        if name in entry["tasks"] and not path.endswith("/")
    ]
