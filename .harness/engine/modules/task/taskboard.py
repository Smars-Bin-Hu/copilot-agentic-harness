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
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO, Tuple

from core import config, messages
from core.render import local_time, pad, width  # noqa: F401 - the page and the tests use them from here too
from core.paths import cli_command, utc_now

from . import common, task as task_ops, taskhtml, taskinsight, tasklife, taskstages

BOARD_NAME = "board.html"
MIN_INTERVAL = 1.0
DEFAULT_REFRESH = 10  # seconds, for a person at a terminal who gave no --refresh


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def table(result: Dict[str, Any]) -> str:
    """The list as text. Waiting tasks first, the one that waited longest on top."""
    head = say("board.text.head", open=result["open"], waiting=result["waiting"], paused=result.get("paused", 0), as_of=local_time(utc_now())[11:19])
    line = result.get("promote_queue") or []
    if line:
        names = [item["name"] + say("note.brackets", text=say(f"board.queue.{item['stage']}")) for item in line]
        head += "\n" + say("board.text.queue", names=" → ".join(names))
    if not result["tasks"]:
        return head + "\n" + say("board.empty")
    names = [say("board.col.task"), say("board.col.kind"), say("board.col.waiting"), say("board.col.waited"), say("board.col.updated")]
    lines: List[List[str]] = []
    for row in result["tasks"]:
        if row["status"] == "new":
            kind, state = "-", say("board.state.new")
        else:
            kind = say(f"task.kind.{row['kind'] or 'none'}") + " · " + say(f"task.tier.{row['tier'] or 'none'}")
            state = row["waiting"] or say(f"board.state.{row['state']}") + (" · " + taskinsight.clock(row["unheld_s"]) if row["state"] == "unheld" and row.get("unheld_s") is not None else "")
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


def insight(root: Path, task: str, use_events: Optional[bool] = None) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """The numbers of a task, with the wait that is still going on counted in, and that wait itself (or None)."""
    try:
        now = tasklife.waiting_now(root, task, task_ops.read(root, task))
    except Exception:  # noqa: BLE001 - one line of the page
        now = None
    return taskinsight.add_open_wait(taskinsight.of_task(root, task, use_events), now), now


def write_task_page(root: Path, task: str, info: Dict[str, Any], refresh: int = 0, now: Optional[Dict[str, Any]] = None) -> Path:
    path = common.task_report_file(root, task_ops.name_of(task), common.REPORT_HTML)
    common.replace_text(path, taskhtml.task_page(info, refresh, now))
    return path


ACTIONS_BY_WAIT = {"req": ("confirm-req",), "plan": ("approve-plan",), "promote": ("approve-promote",), "recover": ("recover",), "review": ("review extend", "review waive")}


def actions(row: Dict[str, Any], served: Tuple[str, ...] = ()) -> List[Dict[str, str]]:
    """What the person can do about a task from the board (a closed one: archive it): the action and the command to run in a terminal.
    What it waits for comes first; then pause, or resume when it is paused. `served`: the actions the board server
    runs from the page; `autorun on` is offered only when it is one of them."""
    if row.get("status") == "closed":
        return [{"action": "archive", "command": f"{cli_command()} task archive {row['name']} --apply"}] if "archive" in served else []
    if row.get("status") != "open":
        return []
    found = list(ACTIONS_BY_WAIT.get(row.get("waiting_why") or "", ()))
    if "autorun on" in served and not row.get("autorun") and not row.get("paused_since"):
        found.append("autorun on")
    found.append("resume" if row.get("paused_since") else "pause")
    if "close" in served:
        found.append("close")
    return [{"action": action, "command": f"{cli_command()} task {action} --task {row['name']}"} for action in found]


CLOSED_SHOWN = 50  # how many closed tasks the board lists (the newest); `board.closed_shown` in task.json
_closed: Dict[Tuple[str, str], Tuple[str, Any, str]] = {}  # a closed task does not change: its numbers and page are made once


def closed_shown(root: Path) -> int:
    return config.whole((config.policy_or_empty(root, "task").get("board") or {}).get("closed_shown"), CLOSED_SHOWN)


def board_rows(root: Path, everything: bool, refresh: int = 0, served: Any = ()) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """The rows of the board, each with its numbers, the page of the task (written over the one of before) and its actions.
    A task whose numbers cannot be worked out is listed without them. With `everything`, the newest closed tasks come
    too (`closed_shown`): the page filters and sorts them; `closed_hidden` counts the older ones that are not listed."""
    result = tasklife.list_tasks(root, everything)
    limit = closed_shown(root)
    closed = [row for row in result["tasks"] if row["status"] == "closed"]
    hidden = closed[limit:]  # the list is newest first within each kind of row
    result["closed_hidden"] = len(hidden)
    if hidden:
        gone = {id(row) for row in hidden}
        result["tasks"] = [row for row in result["tasks"] if id(row) not in gone]
    use_events = taskinsight.events_allowed(root)
    problems = []
    for row in result["tasks"]:
        row["brief"], row["report"], row["actions"], row["stages"] = None, "", actions(row, tuple(served)), None
        if row["status"] == "new":
            continue
        row["stages"] = taskstages.of(root, row["task"])
        row["todo_left"] = len(task_ops.todo_left(root, row["task"])) if row["status"] == "open" else 0
        row["req_unconfirmed"] = row["status"] == "open" and task_ops.req_state(root, row["task"]) in ("open", "changed")
        key = (str(root), row["task"])
        kept = _closed.get(key) if row["status"] == "closed" else None
        if kept and kept[0] == row["updated_at"] and (root / common.REPORTS_DIR / kept[2]).is_file():
            row["brief"], row["report"] = kept[1], kept[2]
            continue
        try:
            info, now = insight(root, row["task"], use_events)
            row["brief"] = taskinsight.brief(info)
            row["report"] = write_task_page(root, row["task"], info, refresh, now).relative_to(root / common.REPORTS_DIR).as_posix()
            if row["status"] == "closed":
                _closed[key] = (row["updated_at"], row["brief"], row["report"])
        except Exception as error:  # noqa: BLE001 - one bad task must not take the board away
            problems.append({"task": row["task"], "error": f"{type(error).__name__}: {error}"})
    return result, problems


def board(root: Path, everything: bool = False, refresh: int = 0) -> Dict[str, Any]:
    """Write the board and the page of every task on it, over the ones of before."""
    result, problems = board_rows(root, everything, refresh)
    path = root / common.REPORTS_DIR / BOARD_NAME
    common.replace_text(path, taskhtml.board_page(result["tasks"], utc_now(), refresh, hidden=result["closed_hidden"]))
    out: Dict[str, Any] = {"board": path.relative_to(root).as_posix(), "tasks": len(result["tasks"]), "open": result["open"], "waiting": result["waiting"]}
    if problems:
        out["problems"] = problems
    return out


def refresh_seconds(asked: Optional[int], once: bool, person: bool) -> int:
    """How often `task board` writes the board again; 0: once, then it returns.

    A person at a terminal wants a page that stays true, so it keeps going by itself. An agent or a script must get its
    answer and go on: a command that never returns would hang it. `--once` and `--refresh N` say it outright.
    """
    if once:
        return 0
    if asked is not None:
        return max(0, asked)
    return DEFAULT_REFRESH if person else 0


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
