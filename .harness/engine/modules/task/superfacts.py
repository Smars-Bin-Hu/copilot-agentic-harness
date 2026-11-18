"""The facts the super agent view needs and the board rows do not hold (1.8.4): held calls, the question the agent asks, the delivery, and whether the agent's chat has failed or is stuck.

`put(root, rows)` reads a little from the task folders and the session logs and puts `row["super"]` on each open row that needs it; `superview.build` (a pure function of the rows) turns it into items. Only what the item of the row's wait needs is read:
  outbox  `calls`: `[{code, command, system, env, verb, title, draft}]`, the held calls of the task, oldest first. `command` is one line, with the values of passwords and tokens replaced (`core/redact.py`), cut to `COMMAND_CHARS`; the page of the task shows the whole command, and so does `/api/super/preview` `kind: call`.
  asking  `question`: `{message, options}`, from the `asking` mark the hook left (`handler.ask_mark`); a mark of an older version has none.
  accept  `deliver`: `{summary, at, todo_open}` from the delivery, the summary cut to `SUMMARY_CHARS`.
  a chat that failed or runs: `idle_s` and `idle_at`, the seconds and the time since the session log was last written (the same clock `tasklife.active_now` reads); `error` `{message, resumable}` from the link; `kind` `error` or `stuck` with its `title` and `detail` when the chat says so.
Error: the chat's last turn ended in an error and the row waits for the person (`stopped`) or for nothing. Stuck: the chat runs a turn (`busy`), the log has been quiet for `board.stuck_seconds` (default 600), the row waits for nothing, and the quiet is not a good one:
the agent sits in `harness wait`, a subagent runs, or the task is paused. Nothing here fails a look: a fact that cannot be read is left out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from core import config, messages, outbox, redact, tasks

from . import tasklife, taskdesk

COMMAND_CHARS = 400
SUMMARY_CHARS = 600
CALLS_MAX = 20  # held calls listed on one card; more are left out (the task page lists them all)


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def one_line(text: Any, size: int) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= size else line[: size - 1].rstrip() + "…"


def calls_of(root: Path, task: str) -> List[Dict[str, Any]]:
    """The held calls of the task for the card. `title` is what the call's type says of it in words, else the start of the command."""
    systems = config.policy_or_empty(root, "tools").get("systems") or {}
    folder = tasks.task_dir(root, task)
    out: List[Dict[str, Any]] = []
    for item in outbox.pending_for(root, task)[:CALLS_MAX]:
        try:
            said = " · ".join(taskdesk.call_words(str(item["command"]), systems.get(item.get("system", "")) or {}, folder, root, systems)["says"])
        except Exception:  # noqa: BLE001 - the words are help
            said = ""
        draft = outbox.draft_of(item)
        out.append({"code": str(item["code"]), "command": one_line(redact.text(str(item["command"])), COMMAND_CHARS), "system": str(item.get("system", "")), "env": str(item.get("env", "")), "verb": str(item.get("verb", "")),
                    "title": said or one_line(redact.text(str(item["command"])), 80), "draft": draft.split("/", 4)[-1] if draft else ""})
    return out


def question_of(data: Dict[str, Any]) -> Dict[str, Any]:
    """`{message, options}` from the `asking` mark, or an empty dict for a mark with no question."""
    mark = data.get("waiting") if isinstance(data.get("waiting"), dict) else {}
    message = str(mark.get("question") or "")
    if mark.get("why") != "asking" or not message:
        return {}
    options = [str(one) for one in mark.get("options") or [] if isinstance(one, str)] if isinstance(mark.get("options"), list) else []
    return {"message": message, "options": options[:8]}


def deliver_of(data: Dict[str, Any]) -> Dict[str, Any]:
    found = data.get("deliver") if isinstance(data.get("deliver"), dict) else None
    if not found:
        return {}
    return {"summary": str(found.get("summary") or "")[:SUMMARY_CHARS], "at": str(found.get("at") or ""), "todo_open": str(found.get("todo_open") or "")}


def chat_facts(root: Path, row: Dict[str, Any], data: Dict[str, Any], limit: int) -> Dict[str, Any]:
    """The `error` and `stuck` facts of a row (see the head of this file); `{}` when neither holds."""
    chat = row.get("chat") or {}
    state, why = chat.get("state"), str(row.get("waiting_why") or "")
    if row.get("paused_since") or not chat.get("bound") or state not in ("busy", "error"):
        return {}
    age = tasklife.log_age(root, data)
    if state == "error" and why in ("", "stopped"):
        found = chat.get("error") if isinstance(chat.get("error"), dict) else {}
        out: Dict[str, Any] = {"kind": "error", "title": say("super.error.title"), "detail": str(found.get("message") or "") or say("super.error.detail"), "resumable": bool(found.get("resumable"))}
        if age:
            out.update(idle_s=age[0], idle_at=age[1])
        return out
    if state == "busy" and (not why or why.startswith("go-")) and age and age[0] >= limit and not tasklife.waits_quietly(root, data):
        return {"kind": "stuck", "idle_s": age[0], "idle_at": age[1], "title": say("super.stuck.title", minutes=age[0] // 60), "detail": say("super.stuck.detail", minutes=age[0] // 60)}
    return {}


def put(root: Path, rows: List[Dict[str, Any]], stuck_seconds: int = 0) -> None:
    """Put `row["super"]` on the open rows that need facts. `stuck_seconds`: the limit, default `board.stuck_seconds`. A row whose facts cannot be read is left as it was."""
    limit = stuck_seconds or tasklife.stuck_limit(root)
    for row in rows:
        if row.get("status") != "open":
            continue
        try:
            data = tasks.read(root, str(row["task"]))
            if not data:
                continue
            why = str(row.get("waiting_why") or "")
            found: Dict[str, Any] = dict(chat_facts(root, row, data, limit))
            if why == "outbox":
                found["calls"] = calls_of(root, str(row["task"]))
            elif why == "asking":
                found["question"] = question_of(data)
            elif why == "accept":
                found["deliver"] = deliver_of(data)
            if found:
                row["super"] = found
        except Exception:  # noqa: BLE001 - a look at the tasks must not fail over one task
            continue
