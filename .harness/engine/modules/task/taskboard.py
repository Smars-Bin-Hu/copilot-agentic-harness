"""The task board (M12-1): which task waits for the person, and for how long. Code only, no agent, no token.

  task list --text     the list as a table a person reads
  task list --watch    the same table, drawn again every few seconds, until Ctrl+C
  task board           .workspace/reports/board.html: every task, what it waits for, its time and usage, a link to its page
  task board --refresh N   the same, written again every N seconds until Ctrl+C; the pages load themselves again

What a task waits for is told from facts (`tasklife.waiting`): the promote state, the plan file, the checks, and the
mark the Stop hook leaves when the agent of the task's session stops.
"""

from __future__ import annotations

import os
from datetime import datetime
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


def local_time(stamp: str) -> str:
    """A UTC stamp as "YYYY-MM-DD HH:MM:SS" in the time of this machine. What cannot be read is given back as it is."""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(stamp or "").replace("T", " ")


def table(result: Dict[str, Any]) -> str:
    """The list as text. Waiting tasks first, the one that waited longest on top."""
    head = say("board.text.head", open=result["open"], waiting=result["waiting"], paused=result.get("paused", 0), as_of=local_time(utc_now())[11:19])
    line = result.get("promote_queue") or []
    if line:
        names = [item["name"] + "（" + say(f"board.queue.{item['stage']}") + "）" for item in line]
        head += "\n" + say("board.text.queue", names=" → ".join(names))
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
        lines.append([("! " if row["waiting"] else "  ") + row["name"], kind, state, waited, local_time(row["updated_at"])[5:16]])
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


def write_task_page(root: Path, task: str, info: Dict[str, Any], refresh: int = 0) -> Path:
    path = common.task_report_file(root, task_ops.name_of(task), common.REPORT_HTML)
    try:  # the wait that is still going on: the numbers of the page end at the last prompt and do not have it
        now = tasklife.waiting_now(root, task, task_ops.read(root, task))
    except Exception:  # noqa: BLE001 - one line of the page
        now = None
    common.replace_text(path, taskhtml.task_page(info, refresh, now))
    return path


def board(root: Path, everything: bool = False, refresh: int = 0) -> Dict[str, Any]:
    """Write the board and the page of every task on it, over the ones of before. A task whose numbers cannot be worked out is listed without them."""
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
            row["report"] = write_task_page(root, row["task"], info, refresh).relative_to(root / common.REPORTS_DIR).as_posix()
        except Exception as error:  # noqa: BLE001 - one bad task must not take the board away
            problems.append({"task": row["task"], "error": f"{type(error).__name__}: {error}"})
    path = root / common.REPORTS_DIR / BOARD_NAME
    common.replace_text(path, taskhtml.board_page(result["tasks"], utc_now(), refresh))
    out: Dict[str, Any] = {"board": path.relative_to(root).as_posix(), "tasks": len(result["tasks"]), "open": result["open"], "waiting": result["waiting"]}
    if problems:
        out["problems"] = problems
    return out


def keep_fresh(root: Path, everything: bool, refresh: int, opened: Any = None, out: Optional[TextIO] = None, rounds: Optional[int] = None) -> Dict[str, Any]:
    """`task board --refresh N`: write the board again every N seconds until Ctrl+C, so the page that loads itself
    again shows new numbers. The same files are written over; nothing piles up. `opened`: called once, after the
    first board is there. `rounds`: stop after that many (the tests)."""
    out = out or sys.stdout
    seconds = max(int(MIN_INTERVAL), refresh)
    result: Dict[str, Any] = {}
    written = 0
    try:
        while rounds is None or written < rounds:
            try:
                result = board(root, everything, seconds)
            except OSError:  # the page could not be written over this time (Windows, a program reading it): the one of before stays
                if not written:
                    raise
            written += 1
            if written == 1:
                if opened:
                    result["opened"] = opened(result["board"])
                out.write(say("board.text.fresh", board=result["board"], seconds=seconds) + "\n")
                out.flush()
            if rounds is None or written < rounds:
                time.sleep(seconds)
    except KeyboardInterrupt:
        pass
    return {"_text": ""} if rounds is None else dict(result, written=written)


def open_in_browser(root: Path, relative: str) -> bool:
    try:
        import webbrowser

        return bool(webbrowser.open((root / relative).resolve().as_uri()))
    except Exception:  # noqa: BLE001 - no browser, no display
        return False
