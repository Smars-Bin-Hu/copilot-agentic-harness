"""Closing is the person's acceptance (1.7.38, C12 Q14). The agent never asks "close the task?".

  a look (Q&A) and a chore on a ticket   the agent closes the task itself (`task close`): the writes were already approved on their cards
  a development task                      the promote is the acceptance; the board closes the task after it when nothing else waits (`sweep`)
  testing, RCA, design, analysis          the agent writes a short summary and stops: `task deliver --summary "<text>"`. The task then shows "to accept"
                                          with **Accept and close** (the board closes it: no chat, no tokens) and **Not yet** (the reply box opens)

The mark: `deliver` saves the summary in `task.json`; the Stop hook turns it into the waiting mark `accept` once the agent really stopped; the person's next message takes both away
(`tasklife.set_waiting`). A test where the person skipped an environment says so in `--skipped`, with the reason: it is shown on the card.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import messages, outbox, tasks
from core.paths import cli_command, utc_now

from . import task as task_ops, tasklife
from .common import CommandError

DELIVER_KINDS = ("rca", "design", "test", "other", "dev", "kb")  # not qa: a look closes itself
SUMMARY_CHARS = 1500
SKIPPED_CHARS = 300
SKIPPED_MAX = 6


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def one_line(text: str, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def paragraphs(text: str, limit: int) -> str:
    """The summary as written (line breaks kept), cut at `limit`."""
    lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").strip().split("\n")]
    return "\n".join(lines)[:limit].strip()


def deliver(root: Path, raw_task: str = "", summary: str = "", skipped: Optional[List[str]] = None, todo_open: str = "") -> Dict[str, Any]:
    """The agent says the work is done and stops for the person to accept it. Refused for a look (it closes itself) and for a development task whose promote is the acceptance."""
    task = task_ops.resolve(root, raw_task)
    text = paragraphs(summary, SUMMARY_CHARS)
    if not text:
        raise CommandError(say("accept.summary.none"))
    left = task_ops.todo_left(root, task)
    if left and not todo_open.strip():
        shown = "\n".join(f"- {line[:100]}" for line in left[:5]) + (f"\n- ... (+{len(left) - 5})" if len(left) > 5 else "")
        raise CommandError(say("accept.todo", count=len(left), steps=shown, task=task))
    with task_ops.locked(root, task) as data:
        task_ops.require_open(data)
        kind = data.get("kind")
        if kind == "qa":
            raise CommandError(say("accept.qa", name=task_ops.name_of(task)))
        if kind in ("dev", "kb") and (data.get("promote") or {}).get("state") == "done":
            raise CommandError(say("accept.promoted"))
        data["deliver"] = {
            "at": utc_now(), "summary": text, "skipped": [one_line(line, SKIPPED_CHARS) for line in (skipped or []) if one_line(line, SKIPPED_CHARS)][:SKIPPED_MAX],
            **({"todo_open": one_line(todo_open, 300)} if left else {}),
        }
        task_ops.note(data, "deliver", one_line(text, 100))
        links = tasklife.links_hint(root, data, still_open=True)  # a ticket the task names: the agent may offer to update it in its summary
    outbox.agent_left(root, task)  # a call it held and never waited on is left behind now: the task shows "to accept", not "waits for your approval" (1.7.38, C12 TB-03)
    return {"task": task, "delivered": True, "next": say("accept.delivered") + (" " + links if links else "")}


def view(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What the task page shows on the card "to accept": the summary, what was skipped. None when the task waits for no acceptance."""
    mark = data.get("waiting") if isinstance(data.get("waiting"), dict) else {}
    found = data.get("deliver") if isinstance(data.get("deliver"), dict) else None
    if data.get("status") != "open" or mark.get("why") != "accept" or not found:
        return None
    return {"summary": str(found.get("summary") or ""), "skipped": [str(line) for line in found.get("skipped") or []], "at": str(found.get("at") or ""), "todo_open": str(found.get("todo_open") or "")}


# The labels of the template in both languages, written as escapes (the engine has no Chinese text outside the tables): Status = \u72b6\u6001, Updated = \u66f4\u65b0, the full-width colon = \uff1a
_STATUS_LINE = re.compile(r"^(\s*- \*\*(?:Status|\u72b6\u6001)\*\*\s*[:\uff1a]\s*).*$", re.MULTILINE)
_UPDATED_LINE = re.compile(r"^(\s*- \*\*(?:Updated|\u66f4\u65b0)\*\*\s*[:\uff1a]\s*).*$", re.MULTILINE)


def mark_done(root: Path, task: str, key: str) -> bool:
    """The board closed the task (the person accepted, or the promote did): the Status line of `TASK.md` says so (1.7.38, C12 TB-12). The agent wrote it before it stopped and it said "waiting for the user
    to check and promote"; nobody was left to change it, and the closed task's Overview showed the old state. Only the Status and the Updated line, and only when they are there as the template makes them.
    `key`: `accept.status.accepted` or `accept.status.promoted`. True when the file changed. Never raises: the task is closed whatever happens here."""
    try:
        path = tasks.task_dir(root, task) / tasks.TASK_FILE
        text = path.read_text(encoding="utf-8")
        today = utc_now()[:10]
        done = _STATUS_LINE.sub(lambda found: found.group(1) + messages.text(key, date=today), text, count=1)
        if done == text:
            return False
        done = _UPDATED_LINE.sub(lambda found: found.group(1) + today, done, count=1)
        path.write_text(done, encoding="utf-8")
        return True
    except (OSError, UnicodeDecodeError):
        return False


def accept(root: Path, raw_task: str) -> Dict[str, Any]:
    """The person accepts the delivered work on the board: the task closes (the report is written, the session lets go). Nothing is sent to the chat. Refused unless the task waits for acceptance."""
    task = task_ops.resolve(root, raw_task)
    data = tasks.read(root, task) or {}
    if tasklife.waiting(root, task, data)["why"] != "accept":
        raise CommandError(say("accept.not_waiting", name=task_ops.name_of(task)))
    left = (data.get("deliver") or {}).get("todo_open") or ""
    result = task_ops.close(root, task, say("accept.reason"), check_todo=False, todo_note=left or say("accept.reason"))
    mark_done(root, task, "accept.status.accepted")
    return result


# --- a development task: the promote is the acceptance ---------------------------------------------------------------

QUIET_WAITS = ("", "stopped", "commit")  # what may still be on the board when the board closes a promoted task: the agent ended its turn, and the person has nothing more to decide


def promoted_and_quiet(root: Path, task: str, data: Dict[str, Any]) -> bool:
    """Is this development task promoted, with nothing else waiting? The agent has ended its turn (the Stop mark), no check, question, held call, hand-over or recovery is open, and the task is not
    under autorun or put aside. The files to commit are not a wait here: the commit message and the commands stay on the Changes tab of the closed task."""
    if data.get("status") != "open" or data.get("kind") not in ("dev", "kb") or (data.get("promote") or {}).get("state") != "done":
        return False
    if (data.get("autorun") or {}).get("state") == "on" or tasklife.paused_since(data) or data.get("handoff"):
        return False
    mark = data.get("waiting") if isinstance(data.get("waiting"), dict) else {}
    if mark.get("why") != "stopped" or tasklife.at_work(root, data):
        return False
    return tasklife.waiting(root, task, data)["why"] in QUIET_WAITS


def sweep(root: Path) -> List[str]:
    """Close the promoted tasks that wait for nothing (the board runs this every few seconds). The names of the tasks closed. A task that cannot be closed stays open; nothing here raises."""
    done: List[str] = []
    try:
        candidates = [item for item in task_ops.open_tasks(root) if (item.get("promote") or {}).get("state") == "done" and item.get("kind") in ("dev", "kb")]
    except Exception:  # noqa: BLE001 - a look at the tasks must not stop the board
        return done
    for data in candidates:
        task = data["task"]
        try:
            if promoted_and_quiet(root, task, data):
                task_ops.close(root, task, say("accept.promote.reason"), check_todo=False, todo_note=say("accept.promote.reason"))
                mark_done(root, task, "accept.status.promoted")
                done.append(task_ops.name_of(task))
        except Exception:  # noqa: BLE001 - see above
            continue
    return done
