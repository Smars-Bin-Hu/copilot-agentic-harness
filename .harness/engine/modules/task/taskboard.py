"""The task board (M12-1): which task waits for the person, and for how long. Code only, no agent, no token.

  task list --text     the list as a table a person reads
  task list --watch    the same table, drawn again every few seconds, until Ctrl+C
  task board           .workspace/reports/board.html: every task, what it waits for, its time and usage, a link to its page

What a task waits for is told from facts (`tasklife.waiting`): the promote state, the plan file, the checks, and the
mark the Stop hook leaves when the agent of the task's session stops.
"""

from __future__ import annotations

import os
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

from core import messages
from core.paths import utc_now

from . import common, task as task_ops, taskhtml, taskinsight, tasklife

BOARD_NAME = "board.html"
MIN_INTERVAL = 1.0


def say(key: str, **values: Any) -> str:
    return messages.text(key, **values)


def width(text: str) -> int:
    """How many terminal columns a text takes: a Chinese character takes two."""
    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)


def pad(text: str, size: int) -> str:
    return text + " " * max(0, size - width(text))


def table(result: Dict[str, Any]) -> str:
    """The list as text. Waiting tasks first, the one that waited longest on top."""
    head = say("board.text.head", open=result["open"], waiting=result["waiting"], paused=result.get("paused", 0), as_of=utc_now()[11:19])
    if not result["tasks"]:
        return head + "\n" + say("board.empty")
    names = [say("board.col.task"), say("board.col.kind"), say("board.col.waiting"), say("board.col.waited"), say("board.col.updated")]
    lines: List[List[str]] = []
    for row in result["tasks"]:
        if row["status"] == "new":
            kind, state = "-", say("board.state.new")
        else:
            kind = say(f"task.kind.{row['kind'] or 'none'}") + "·" + say(f"task.tier.{row['tier'] or 'none'}")
            state = row["waiting"] or say("board.state.paused" if row.get("paused_since") else "board.state.running" if row["status"] == "open" else "board.state.closed")
        waited = taskinsight.clock(row["waited_s"]) if row["waiting"] and row["waited_s"] is not None else "-"
        lines.append([("! " if row["waiting"] else "  ") + row["name"], kind, state, waited, row["updated_at"][5:16].replace("T", " ")])
    sizes = [max(width(names[index]) + (2 if index == 0 else 0), *(width(line[index]) for line in lines)) for index in range(len(names))]
    out = [head, "", "  ".join(pad(("  " if index == 0 else "") + name, sizes[index]) for index, name in enumerate(names))]
    out += ["  ".join(pad(value, sizes[index]) for index, value in enumerate(line)).rstrip() for line in lines]
    return "\n".join(out)


def clear(out: TextIO) -> None:
    if not getattr(out, "isatty", lambda: False)():
        return
    os.system("cls" if os.name == "nt" else "clear")  # noqa: S605 - a fixed word, nothing from outside


def watch(root: Path, everything: bool, interval: float, out: Optional[TextIO] = None, rounds: Optional[int] = None) -> Dict[str, Any]:
    """Draw the list again every `interval` seconds until Ctrl+C. `rounds`: stop after that many (the tests)."""
    out = out or sys.stdout
    interval = max(MIN_INTERVAL, interval)
    drawn = 0
    try:
        while rounds is None or drawn < rounds:
            text = table(tasklife.list_tasks(root, everything))
            clear(out)
            out.write(text + "\n\n" + say("board.text.watch", seconds=f"{interval:g}") + "\n")
            out.flush()
            drawn += 1
            if rounds is None or drawn < rounds:
                time.sleep(interval)
    except KeyboardInterrupt:
        pass
    return {"_text": ""}


def write_task_page(root: Path, task: str, info: Dict[str, Any]) -> Path:
    path = root / common.REPORTS_DIR / f"task-{task_ops.name_of(task)}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(taskhtml.task_page(info), encoding="utf-8")
    return path


def board(root: Path, everything: bool = False, refresh: int = 0) -> Dict[str, Any]:
    """Write the board and the page of every task on it. A task whose numbers cannot be worked out is listed without them."""
    result = tasklife.list_tasks(root, everything)
    use_events = taskinsight.events_allowed(root)
    problems = []
    for row in result["tasks"]:
        row["brief"], row["report"] = None, ""
        if row["status"] == "new":
            continue
        try:
            info = taskinsight.of_task(root, row["task"], use_events)
            row["brief"] = taskinsight.brief(info)
            row["report"] = write_task_page(root, row["task"], info).name
        except Exception as error:  # noqa: BLE001 - one bad task must not take the board away
            problems.append({"task": row["task"], "error": f"{type(error).__name__}: {error}"})
    path = root / common.REPORTS_DIR / BOARD_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(taskhtml.board_page(result["tasks"], utc_now(), refresh), encoding="utf-8")
    out: Dict[str, Any] = {"board": path.relative_to(root).as_posix(), "tasks": len(result["tasks"]), "open": result["open"], "waiting": result["waiting"]}
    if problems:
        out["problems"] = problems
    return out


def open_in_browser(root: Path, relative: str) -> bool:
    try:
        import webbrowser

        return bool(webbrowser.open((root / relative).resolve().as_uri()))
    except Exception:  # noqa: BLE001 - no browser, no display
        return False
