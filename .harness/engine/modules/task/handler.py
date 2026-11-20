"""task hook behavior: what every prompt is told, which subagent may be called, and the two reminders at Stop.

  SessionStart, UserPromptSubmit   the session id; a session that holds a task: where the task stands, its checks;
                                   a session that holds none: which tasks are open and when to open one.
                                   `[review]=n` in the user's prompt, or the task page, sets the n of the task. Admin mode: the admin rules
  PreToolUse(subagent)             a session that holds a task: only the reviewer, and only with a check open
                                   (`task review start`). A session that holds none, or is in admin mode: no subagent.
                                   The one other subagent is the read-only `mapper`, and only after the user typed
                                   `/generic-mapreduce`: that prompt gives the session a number of calls (mapreduce.py)
  SubagentStart                    the reviewer is told where its package is; a mapper is told it only reads; the worker of a task in autorun, its task and its rule
  SubagentStop                     the worker's call ends: the `end` line of the run ledger (autorun.py)
  PreToolUse(ask)                  a task in autorun: the question tool is refused while TODO.md has an open step, and always for the worker; the time a person
                                   takes to answer is added back to the run
  UserPromptSubmit (rewind)        a message of the person: a restore point of the task folder (rewind.py)
  PostToolUse                      a write inside the task is remembered; a write of its REQ.md or PLAN.md is noted with its time (once a prompt
                                   each, for the stages of the report); the reviewer's answer closes the open check
  Stop                             a task in autorun: the next open step, until a fact says stop (autorun.py);
                                   once per prompt: the result has not passed its checks; task files were written and
                                   TASK.md was not; once per session: the knowledge base is not built yet, offer the
                                   next step (kb_offer). A Stop that goes through leaves a mark in the task for the board:
                                   the agent stopped, the person is next. The next prompt takes the mark away

Hook failures are fail-open: hook.py rolls back this module's state changes and carries on.
"""

from __future__ import annotations

import json
import re
import time

from typing import Any, Dict, List, Optional

from core import guardrails, messages, repo_paths, tasks
from core.context import Context
from core.events import Decision, HookEvent
from core.paths import cli_command, utc_now
from core.state import atomic_write, state_lock

from . import commitmsg, mapreduce
from .policy import POLICY_NAME, validate_policy

NAME = "task"
OPEN_TASKS_SHOWN = 5
DOC_WRITES_KEPT = 100  # the moments REQ.md and PLAN.md were written, newest last


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def open_task(ctx: Context) -> Optional[Dict[str, Any]]:
    """The open task this session holds, or None."""
    return tasks.open_of(ctx.root, ctx.state)


def after_task(ctx: Context) -> Optional[Dict[str, Any]]:
    """The closed task this session checks after the close (`task review after`, 1.8.16), or None. Only while it is closed and the person asked for checks."""
    from . import taskreview

    name = ctx.state.get("after_review")
    if not name:
        return None
    data = tasks.read(ctx.root, name)
    return data if data and taskreview.is_after(data) and taskreview.after_n(data) > 0 else None


def is_subagent_session(ctx: Context) -> bool:
    """A subagent runs in a session of its own, linked to its parent by core."""
    return bool(ctx.state.get("parent_session_id"))


def relay(ctx: Context) -> Dict[str, Any]:
    return ctx.module_state(NAME).setdefault("relay", {"wrote": False, "task_file": False, "reminded": False})


# --- what a prompt is told -------------------------------------------------------------------------


def admin_rules(ctx: Context) -> str:
    try:
        locked = guardrails.admin_locked(ctx.policy("gate"))
    except Exception:  # noqa: BLE001 - a broken gate.json must not take the rules away; the gate reports it
        locked = list(guardrails.ADMIN_LOCKED)
    return say("rules.admin", locked=messages.joined(f"`{item}`" for item in locked), session_id=ctx.state["session_id"])


def user_review(event: HookEvent) -> Optional[int]:
    """The n of `[review]=n` in the person's words, or None when they wrote none. Never the text of a skill: a slash command brings it in, with its examples (1.6.109)."""
    from . import taskreview

    return taskreview.marker(event.words)


def keep_review(ctx: Context, data: Dict[str, Any], number: Optional[int]) -> Dict[str, Any]:
    """The marker in a prompt of an open task sets the task's n. It holds until the user writes another."""
    from . import taskreview

    if number is None or number == taskreview.state_of(data)["n"]:
        return data
    return taskreview.set_n(ctx.root, data["task"], number)


def task_text(ctx: Context, data: Dict[str, Any]) -> str:
    """Where the task stands, so the rules need not be read again."""
    from . import task as task_ops  # the CLI side of the task; imported late, a hook call rarely needs it
    from . import taskreview

    name = data["task"]
    if data.get("tier") and tasks.task_file(ctx.root, name).is_file():
        head = say(
            "task.inject.head", task=name, round=data["round"],
            kind=messages.text(f"task.kind.{data.get('kind') or 'none'}"), tier=messages.text(f"task.tier.{data['tier']}"),
        )
    else:
        head = say("task.inject.head.plain", task=name, round=data["round"])
    lines = [head + task_ops.next_step(ctx.root, name, data)]
    if (tasks.task_dir(ctx.root, name) / tasks.REQ_FILE).is_file():
        lines.append(say("task.inject.req", task=name))
    if taskreview.state_of(data)["n"]:  # the count needs the digest of every result file: only when checks are on
        info = taskreview.summary(ctx.root, name, data)
        lines.append(say("review.inject", n=info["n"], passes=info["passes"], used=info["checks_used"], limit=info["checks_limit"], agent=taskreview.AGENT))
    elif taskreview.state_of(data).get("set"):  # the person set it to 0 on the task page: an agent that was told n before is told it is off
        lines.append(say("review.inject.off"))
    lines.append(say("task.inject.scope", task=name))
    page = task_ops.page_url(ctx.root, name)
    if page:  # the person follows the task on its page: links to task files can point there
        lines.append(say("task.inject.board", url=page))
    from . import tasklife  # imported late, as task_ops above

    hint = tasklife.domain_hint(ctx.root, data)
    if hint:
        lines.append(hint)
    run = data.get("autorun") if isinstance(data.get("autorun"), dict) else {}
    if run.get("state") == "on":
        lines.append(say("autorun.inject", step=run.get("steps", 0), limit=run.get("max_steps", 0), task=name))
    return "\n".join(lines)


def open_tasks_text(ctx: Context) -> str:
    """A session that holds no task is told which tasks are open, so "go on with that task" leads to `task open`."""
    names = []
    for folder in tasks.folders(ctx.root):
        data = tasks.read(ctx.root, folder)
        if data and data.get("status") == "open":
            names.append((data.get("updated_at", ""), data.get("name") or folder.rsplit("/", 1)[-1], data.get("kind", "")))
    if not names:
        return ""
    names.sort(reverse=True)
    shown = messages.joined(say("rules.task.open_item", name=name, kind=messages.text(f"task.kind.{kind or 'none'}")) for _stamp, name, kind in names[:OPEN_TASKS_SHOWN])
    if len(names) > OPEN_TASKS_SHOWN:
        shown += say("rules.task.open_more")
    return say("rules.task.open_list", count=len(names), names=shown)


REPLY = re.compile(r"\[(ZH|EN)\]", re.IGNORECASE)


def reply_marker(prompt: str) -> Optional[str]:
    """`zh` or `en` when the user wrote `[ZH]` or `[EN]`: the language of the replies of this session (the last one wins)."""
    found = REPLY.findall(prompt or "")
    return found[-1].lower() if found else None


def language_text(ctx: Context) -> str:
    """The language rule, and the language of the replies when the user chose one for this session that differs."""
    reply = ctx.module_state(NAME).get("reply")
    if reply in messages.LANGUAGES and reply != messages.language():
        return say("rules.language") + "\n" + say(f"rules.reply.{reply}")
    return say("rules.language")


def prompt_text(ctx: Context, asked: Optional[int] = None) -> str:
    """Injected at session start and with every user prompt. `asked`: the `[review]=n` of this prompt, if any."""
    if ctx.admin:
        return admin_rules(ctx) + "\n" + language_text(ctx)
    lines = [say("rules.session", session_id=ctx.state["session_id"]), language_text(ctx)]
    data = open_task(ctx)
    if data is not None:
        lines.append(task_text(ctx, keep_review(ctx, data, asked)))
        return "\n".join(lines)
    lines.append(say("rules.task.entry"))
    checked = after_task(ctx)
    if checked is not None:
        from . import task as task_ops, taskreview

        if asked:  # the person's words: the n of the closed task this session checks
            with task_ops.locked(ctx.root, checked["task"]) as again:
                taskreview.set_after(ctx.root, checked["task"], again, asked, "prompt")
        lines.append(say("rules.review.after", task=checked["task"], next=taskreview.after_next(ctx.root, checked["task"], tasks.read(ctx.root, checked["task"]) or checked)))
    elif asked:
        lines.append(say("rules.review.no_task", n=asked, session_id=ctx.state["session_id"]))
    listed = open_tasks_text(ctx)
    if listed:
        lines.append(listed)
    return "\n".join(lines)


def note_harness(ctx: Context, event: HookEvent) -> None:
    """The time of the message the harness sent when it held a Stop, in the task's rewind index (1.6.109): the board offers no rewind to before it. Never in the way."""
    try:
        data = open_task(ctx)
        if data is not None:
            from . import rewind

            rewind.note_harness(ctx.root, data["task"], event.session_id)
    except Exception:  # noqa: BLE001
        pass


def ask_marked(prompt: str) -> bool:
    """The prompt starts with the ask marker (`core/askmark.py`; the gate's `askturn` makes the turn read only)."""
    from core import askmark

    return askmark.is_marker(prompt)


def in_ask_turn(ctx: Context) -> bool:
    """The gate marked this turn as a question: its mark is in the session state, until the next normal prompt. A mark that cannot be read counts as not marked (the gate refuses the writes then)."""
    try:
        return bool(ctx.state["modules"]["gate"]["ask"])
    except (KeyError, TypeError):
        return False


def keep_cancel(ctx: Context, data: Dict[str, Any]) -> None:
    """A question turn after a cancelled turn: Copilot's record has a new prompt then, so the cancel would be read as gone. Keep it as a mark of its own (`cancelled`, since the cancel); a normal prompt clears it like any mark. Never in the way of the hook."""
    try:
        from . import tasklife

        if data.get("waiting") or data.get("paused"):
            return
        since = tasklife.cancelled_at(data)
        if since:
            tasklife.set_waiting(ctx.root, data["task"], {"since": since, "why": "cancelled"})
    except Exception:  # noqa: BLE001 - the mark is for the board
        pass


def end_ask_turn(ctx: Context, data: Dict[str, Any]) -> None:
    """The Stop of a question turn: what the task waited for stays. A task that waited for nothing (it had worked, and the turn that ended was lost to the list) gets the mark of any Stop: the agent is not at work."""
    try:
        from . import tasklife

        if data.get("paused") or tasklife.waiting(ctx.root, data["task"], data)["why"]:
            return
        mark_waiting(ctx, data, True)
    except Exception:  # noqa: BLE001
        pass


def on_user_prompt(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.from_subagent or event.continuation:
        # A subagent call message, or the reason of a Stop block fed back by the engine. Not the user.
        if event.continuation and not ctx.admin:
            note_harness(ctx, event)
        return None
    if not ctx.admin and ask_marked(event.prompt):
        # 1.8.2: a question from the person through the board (`/harness-ask`). The turn is read-only and leaves the task as it was: no wait or delivery cleared, no resume, no restore point, no new count.
        data = open_task(ctx)
        if data is not None:
            keep_cancel(ctx, data)
        return Decision(context=prompt_text(ctx), facts={"kind": "task", "task": data["task"]} if data is not None else {})
    asked = user_review(event)
    state = ctx.module_state(NAME)
    state["relay"] = {"wrote": False, "task_file": False, "reminded": False}  # a new prompt, a new count
    state["review_n"] = asked  # for a task this prompt goes on to make or open
    reply = reply_marker(event.words)
    if reply:
        state["reply"] = reply  # `[ZH]` or `[EN]`: the replies of this session; the files keep the language setting
    if not ctx.admin and mapreduce.asked(event.prompt):
        mapreduce.grant(ctx)  # the user typed /generic-mapreduce: this session may call mappers, up to the limit
    data = open_task(ctx) if not ctx.admin else None
    if data is not None and data.get("paused"):
        try:
            from . import tasklife

            tasklife.resume_on_prompt(ctx.root, data["task"])  # the person is back at a task they had put aside
        except Exception:  # noqa: BLE001 - a mark for a list; never in the way of the prompt
            pass
    if data is not None and (data.get("waiting") or data.get("deliver")):
        mark_waiting(ctx, data, False)  # the person answered (and what was delivered is not, any more)
    if data is not None:
        try:  # the restore point a rewind goes back to (1.6.109); a point that cannot be taken never holds up the message
            from . import rewind

            rewind.take(ctx.root, data["task"], event.session_id)
        except Exception:  # noqa: BLE001
            pass
    # `task`: the log says whose prompt this was, so a report can add up the task's time
    return Decision(context=prompt_text(ctx, asked), facts={"kind": "task", "task": data["task"]} if data is not None else {})


# --- subagents -------------------------------------------------------------------------------------


def on_subagent_call(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """Only the reviewer of a task that has a check open. Everything else is refused, with what to do instead."""
    from . import taskreview

    if is_subagent_session(ctx):
        return None  # the platform does not nest subagents; a subagent's own tools are not this module's business
    called = event.subagent_target.strip() or say("rules.subagent.generic")
    if ctx.admin:
        return Decision(permission="deny", reason=say("rules.subagent.admin", called=called), facts={"kind": "subagent"})
    if called.lower() == mapreduce.AGENT:
        return mapreduce.on_call(ctx)
    data = open_task(ctx)
    if data is None:
        checked = after_task(ctx) if called.lower() == taskreview.AGENT else None
        if checked is None:
            return Decision(permission="deny", reason=say("rules.subagent.no_task", called=called, agent=taskreview.AGENT), facts={"kind": "subagent"})
        if taskreview.pending(checked, True) is None:  # a check after the close (1.8.16): only with its round open, as for an open task
            return Decision(permission="deny", reason=say("review.call.no_round", agent=taskreview.AGENT), facts={"kind": "task-subagent"})
        return None
    if called.lower() == WORKER:
        return worker_call(event, ctx, data)
    if called.lower() != taskreview.AGENT:
        return Decision(permission="deny", reason=say("review.call.other", agent=taskreview.AGENT, called=called), facts={"kind": "task-subagent"})
    if taskreview.state_of(data)["n"] == 0:
        return Decision(permission="deny", reason=say("review.off"), facts={"kind": "task-subagent"})
    if taskreview.pending(data) is None:
        return Decision(permission="deny", reason=say("review.call.no_round", agent=taskreview.AGENT), facts={"kind": "task-subagent"})
    return None


WORKER = "worker"  # autorun.WORKER; the name is needed before autorun.py is imported


def tool_input_of(event: HookEvent) -> Dict[str, Any]:
    given = event.raw.get("tool_input", event.raw.get("toolArgs"))
    if isinstance(given, str):
        try:
            given = json.loads(given)
        except ValueError:
            given = {}
    return given if isinstance(given, dict) else {}


def worker_call(event: HookEvent, ctx: Context, data: Dict[str, Any]) -> Optional[Decision]:
    """The worker is called (autorun.py has the five checks). A refusal here is not a gate refusal and does not end the run. A call that is let through opens a line of the run ledger. Without autorun it is refused."""
    from . import autorun

    given = tool_input_of(event)
    text = autorun.on_subagent_call(ctx.root, data["task"], given)
    if text:
        return Decision(permission="deny", reason=text, facts={"kind": "autorun-call"})
    autorun.ledger_start(ctx.root, data["task"], given, event.session_id)
    return None


def on_subagent_start(event: HookEvent, ctx: Context) -> Optional[Decision]:
    from . import taskreview

    if event.agent_type.strip().lower() == mapreduce.AGENT:
        return Decision(context=say("mapreduce.start.context") + "\n" + say("rules.language"))
    data = open_task(ctx)
    if data is not None and event.agent_type.strip().lower() == WORKER:
        if not (isinstance(data.get("autorun"), dict) and data["autorun"].get("state") == "on"):
            return None
        return Decision(context=say("autorun.start.worker", task=data["task"]) + "\n" + say("rules.language"))
    if event.agent_type.strip().lower() != taskreview.AGENT:
        return None
    after = False
    if data is None:
        data, after = after_task(ctx), True
    if data is None:
        return None
    waiting = taskreview.pending(data, after)
    if waiting is None:
        return None
    package = f"{taskreview.round_dir(data['task'], waiting['number'])}/{taskreview.PACKAGE}"
    return Decision(context=say("review.start.context", package=package) + "\n" + say("rules.language"))


# --- what happened, and the reminders at Stop ----------------------------------------------------


def on_task_write(event: HookEvent, ctx: Context) -> None:
    """A write that went through, inside the task of this session: remember it, and whether it was TASK.md."""
    data = open_task(ctx)
    if data is None or event.tool_kind not in ("edit", "create"):
        return
    name = data["task"].lower().rstrip("/")
    worker = is_subagent_session(ctx) and isinstance(data.get("autorun"), dict) and data["autorun"].get("state") == "on"
    for raw in event.paths:
        for relative in repo_paths.repo_relative(raw, ctx.root, event.cwd):
            if relative is None or not relative.lower().startswith(name + "/"):
                continue
            if worker:
                from . import autorun

                autorun.tally_add(ctx.root, data["task"], "files", relative[len(name) + 1 :])  # what this worker call changed, for its `end` line
            state = relay(ctx)
            state["wrote"] = True
            if relative.lower() == f"{name}/{tasks.TASK_FILE}".lower():
                state["task_file"] = True
            doc = {f"{name}/{tasks.REQ_FILE}".lower(): "req", f"{name}/{tasks.PLAN_NAME}".lower(): "plan"}.get(relative.lower())
            if doc and doc not in state.setdefault("docs", []):
                state["docs"].append(doc)
                note_doc_write(ctx, data["task"], doc)


def note_doc_write(ctx: Context, task: str, doc: str) -> None:
    """REQ.md (`req`) or PLAN.md (`plan`) of the task was written (1.6.109): the moment, once a prompt for each. The report reads the stages from them: the agent began the plan, or
    went back to the requirement. Kept apart from the events (the history keeps its last lines only) and written without a new `updated_at`, like a binding."""
    path = tasks.state_file(ctx.root, task)
    if not path.exists():
        return
    with state_lock(path):
        data = tasks.read(ctx.root, task)
        if data is None:
            return
        writes = data.setdefault("doc_writes", [])
        writes.append({"at": utc_now(), "doc": doc})
        del writes[:-DOC_WRITES_KEPT]
        atomic_write(path, data)


def on_review_done(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """The reviewer's call has finished: what it said closes the open check."""
    from . import taskreview

    if event.tool_kind != "subagent" or event.subagent_target.strip().lower() != taskreview.AGENT:
        return None
    data = open_task(ctx) or after_task(ctx)
    if data is None:
        return None
    info = taskreview.record(ctx.root, data["task"], event.tool_response)
    if info is None:
        return None
    return Decision(facts={"judge": "reviewer", "verdict": info["verdict"], "kind": "task-review"})


def review_stop(ctx: Context, data: Dict[str, Any]) -> Optional[Decision]:
    """The result has not passed its checks: say so once per prompt. Past the limit the agent is to stop and ask the person."""
    from . import taskreview

    name = data["task"]
    if taskreview.state_of(data)["n"] == 0 or data.get("handoff"):
        return None  # off, or the person's run is not back: a check cannot start yet
    info = taskreview.summary(ctx.root, name, data)
    if info["waived"] or info["passes"] >= info["n"] or not taskreview.has_something(ctx.root, name, data):
        return None
    if not info["pending_round"] and info["checks_used"] >= info["checks_limit"]:
        return None
    state = relay(ctx)
    if state.get("review_reminded"):
        return None
    state["review_reminded"] = True
    return Decision(block=True, reason=say("review.stop", task=name, next=taskreview.next_text(ctx.root, name, data)), facts={"kind": "task_review_missing"})


def task_file_stop(ctx: Context, data: Dict[str, Any]) -> Optional[Decision]:
    """Task files were written in this prompt and TASK.md was not (M11-8)."""
    policy = ctx.policy(POLICY_NAME)
    validate_policy(policy)  # a broken policy raises: hook.py logs it and the reminder does not run (fail-open)
    if not policy.get("task_file_reminder", True) or not tasks.task_file(ctx.root, data["task"]).is_file():
        return None
    if isinstance(data.get("deliver"), dict):
        return None  # `task deliver` wrote the Status line of TASK.md itself; the person's next message takes the delivery away (C12 RB-N4)
    state = relay(ctx)
    if not state["wrote"] or state["task_file"] or state["reminded"]:
        return None
    state["reminded"] = True
    return Decision(block=True, reason=say("task.relay.reminder", task=data["task"]), facts={"kind": "task_file_not_updated"})


def write_back_stop(ctx: Context, data: Dict[str, Any]) -> Optional[Decision]:
    """The write-back is done and the task still has loose ends the agent leaves behind: steps of TODO.md not ticked, no COMMIT-MESSAGE.md for the person to copy.
    Said once in a session (never in autorun, which pushes the steps itself). Only the facts of the files are looked at."""
    if (data.get("promote") or {}).get("state") != "done" or data.get("autorun"):
        return None
    state = ctx.module_state(NAME)
    if state.get("done_reminded"):
        return None
    from . import task as task_ops  # it needs this module

    left = task_ops.todo_left(ctx.root, data["task"])
    path = tasks.task_dir(ctx.root, data["task"]) / commitmsg.FILE
    no_message = bool(commitmsg.to_commit(data)) and not (path.is_file() and path.read_text(encoding="utf-8-sig", errors="replace").strip())
    if not left and not no_message:
        return None
    state["done_reminded"] = True
    parts = []
    if left:
        parts.append(say("task.done.todo", count=len(left), steps="; ".join(text[:80] for text in left[:3]), task=data["task"]))
    if no_message:
        parts.append(say("task.done.commit", file=commitmsg.FILE))
    return Decision(block=True, reason=" ".join(parts), facts={"kind": "write_back_open"})


def kb_offer_stop(ctx: Context, data: Dict[str, Any]) -> Optional[Decision]:
    """The knowledge base is not built yet (M28): once per session, at a stop of a task that is not itself about the
    knowledge base, the agent offers the next step in one line. Only where the code repositories and a knowledge base
    are set up (a team that registered none has not chosen to build one; doctor says so), never in autorun (nobody is
    there to answer), and no longer once a first domain is learned. `kb_offer: false` in task.json turns it off. Looks only at which files exist."""
    if not ctx.policy(POLICY_NAME).get("kb_offer", True) or data.get("kind") == "kb" or data.get("autorun"):
        return None
    state = ctx.module_state(NAME)
    if state.get("kb_offered"):
        return None
    try:
        from core import kbstatus

        found = kbstatus.status(ctx.root, deep=False)
    except Exception:  # noqa: BLE001 - an offer is not worth a failed Stop
        return None
    if found["stage"] in ("targets", "kb_repo", "maintain"):
        return None
    if any(item["done"] for item in found["domains"]):  # a first domain is learned: the rest are learned when the team wants
        return None
    state["kb_offered"] = True
    return Decision(block=True, reason=say("kbstatus.stop", step=found["step"], of=found["of"], next=found["next"]), facts={"kind": "kb_offer"})


def mark_waiting(ctx: Context, data: Dict[str, Any], stopped: bool) -> None:
    """The board's mark (M12-1): the agent of this task stopped, so the person is next. Never in the way of the hook."""
    from core.paths import utc_now

    from core import outbox

    from . import tasklife

    try:
        tasklife.set_waiting(ctx.root, data["task"], {"since": utc_now(), "why": "accept" if data.get("deliver") else "stopped"} if stopped else None)  # delivered, then stopped: the person accepts (1.7.38)
        if stopped and data.get("deliver"):
            outbox.agent_left(ctx.root, data["task"])  # a call held between the delivery and the stop that the agent never waited on: left behind now (F3 U4)
    except Exception:  # noqa: BLE001 - the mark is for a list; losing it must not turn a Stop into an error
        pass


ASK_TOOLS = ("ask_user", "askuserquestion")  # the tool that asks the person a question (1.7.20): `ask_user` in a Copilot SDK session (recorded in events.jsonl), `AskUserQuestion` in older recordings


ASK_MESSAGE_CHARS = 600  # the question kept in the `asking` mark (1.8.4): the super view shows it, so the person need not open VS Code to read what is asked
ASK_OPTIONS_MAX = 8
ASK_OPTION_CHARS = 80
ASK_FIELDS_SCANNED = 12  # the properties of the form that are looked at: a form with more is cut, not read to the end


def one_line(text: Any, size: int) -> str:
    """`text` on one line, cut to `size` characters with a mark."""
    line = " ".join(str(text).split())
    return line if len(line) <= size else line[: size - 1].rstrip() + "\u2026"


def ask_options(schema: Any) -> List[str]:
    """The titles of the choices in the form of an `ask_user` call (`requestedSchema`), at most `ASK_OPTIONS_MAX`: the `enum` of a property (plain strings), or its `oneOf` (the `title` of each entry, else its `const`).
    One bounded pass over the first `ASK_FIELDS_SCANNED` properties; anything that is not the expected shape is one entry skipped, never an error."""
    found: List[str] = []
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return found
    for _name, prop in list(props.items())[:ASK_FIELDS_SCANNED]:
        if not isinstance(prop, dict):
            continue
        listed = prop.get("enum") if isinstance(prop.get("enum"), list) else []
        titled = prop.get("oneOf") if isinstance(prop.get("oneOf"), list) else []
        for entry in (listed + titled)[:ASK_OPTIONS_MAX * 2]:
            text = entry if isinstance(entry, str) else (entry.get("title") or entry.get("const")) if isinstance(entry, dict) else None
            if isinstance(text, (str, int, float)) and not isinstance(text, bool) and str(text).strip():
                found.append(one_line(text, ASK_OPTION_CHARS))
            if len(found) >= ASK_OPTIONS_MAX:
                return found
    return found


def ask_mark(event: HookEvent, since: str) -> Dict[str, Any]:
    """The `asking` mark with what the agent asks (1.8.4): `question` (the message, one line, at most `ASK_MESSAGE_CHARS`) and `options` (the titles of the choices). A call whose input cannot be read gives the bare mark of before."""
    mark: Dict[str, Any] = {"since": since, "why": "asking"}
    try:
        given = tool_input_of(event)
        message = given.get("message") if isinstance(given.get("message"), str) else given.get("question")
        if isinstance(message, str) and message.strip():
            mark["question"] = one_line(message, ASK_MESSAGE_CHARS)
            mark["options"] = ask_options(given.get("requestedSchema"))
    except Exception:  # noqa: BLE001 - the words are help; the mark itself must stay
        pass
    return mark


def note_asking(event: HookEvent, ctx: Context) -> None:
    """While the agent waits in the ask-the-person tool it makes no hook call and has not stopped: the board would say "working" for minutes and refuse a held call's Approve (1.7.20).
    The call before the tool leaves the mark `asking` (the person is next); the call after it, or any other tool call, takes it away. Never in the way of the hook.
    1.8.4: the mark keeps the question and the titles of its choices (`ask_mark`), for the super view. A mark of an older version has neither."""
    try:
        if is_subagent_session(ctx) or ctx.admin or event.event not in ("PreToolUse", "PostToolUse"):
            return
        data = open_task(ctx)
        if data is None:
            return
        mark = data.get("waiting") if isinstance(data.get("waiting"), dict) else {}
        asking = event.tool_name.strip().lower() in ASK_TOOLS
        from core.paths import utc_now

        from . import tasklife

        if asking and event.event == "PreToolUse":
            if mark.get("why") != "asking":
                tasklife.set_waiting(ctx.root, data["task"], ask_mark(event, utc_now()))
        elif mark.get("why") == "asking":
            delivered = data.get("deliver") if isinstance(data.get("deliver"), dict) else None  # 1.7.38 (C13 FR 24): a delivered task is still to accept after a question and its answer, until the person accepts or the agent delivers again
            tasklife.set_waiting(ctx.root, data["task"], {"since": str(delivered.get("at") or utc_now()), "why": "accept"} if delivered else None)  # answered (or the agent went on): it is at work again
    except Exception:  # noqa: BLE001 - the mark is for the board; losing it must not turn a tool call into an error
        pass


def autorun_stop(ctx: Context, data: Dict[str, Any], active: bool = False) -> Optional[Decision]:
    """A task in autorun (M13-1): the facts say whether the agent is pushed on to the next step or may stop. `active` is `stop_hook_active` of the Stop event: the count of blocks in a row starts again when it is false."""
    if not (isinstance(data.get("autorun"), dict) and data["autorun"].get("state") == "on"):
        return None
    from . import autorun

    text = autorun.on_stop(ctx.root, data["task"], active)
    if text is None:
        return None  # it ends here; the task says why, and the Stop goes on as any other
    return Decision(block=True, reason=text, facts={"kind": "autorun"})


def autorun_goes_on(ctx: Context, data: Dict[str, Any]) -> bool:
    """The task was in autorun at this Stop and still is: `on_stop` let the Stop through without ending the run. Nothing is read for a task that was not."""
    if not (isinstance(data.get("autorun"), dict) and data["autorun"].get("state") == "on"):
        return False
    found = tasks.read(ctx.root, data["task"])
    return bool(found) and isinstance(found.get("autorun"), dict) and found["autorun"].get("state") == "on"


def on_ask_call(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """The question tool in a task in autorun. Refused while TODO.md has an open step, and always for the worker; not a gate refusal and never a reason to stop.
    Let through (no open step): the moment is kept, and the time until the answer is added back to the run (`note_ask_return`)."""
    if ctx.admin:
        return None
    data = open_task(ctx)
    if data is None or not (isinstance(data.get("autorun"), dict) and data["autorun"].get("state") == "on"):
        return None
    from . import autorun

    if is_subagent_session(ctx):
        return Decision(permission="deny", reason=say("autorun.deny.ask_worker"), facts={"kind": "autorun-ask"})
    if autorun.open_steps_of(autorun.steps_of(ctx.root, data["task"])):
        return Decision(permission="deny", reason=say("autorun.deny.ask", task=data["task"]), facts={"kind": "autorun-ask"})
    ctx.module_state(NAME)["ask_since"] = time.time()
    return None


def note_ask_return(ctx: Context) -> None:
    """The question tool returned: a person answered. Their time does not count against the run. Without the mark of its start (or in a task that is not in autorun) nothing happens."""
    mine = (ctx.state.get("modules") or {}).get(NAME) or {}  # not module_state(): a task with no mark has nothing to write
    since = mine.pop("ask_since", None)
    if not isinstance(since, (int, float)) or is_subagent_session(ctx) or ctx.admin:
        return
    data = open_task(ctx)
    if data is None or not (isinstance(data.get("autorun"), dict) and data["autorun"].get("state") == "on"):
        return
    from . import autorun

    autorun.add_wait(ctx.root, data["task"], time.time() - float(since))


def on_subagent_stop(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """The worker's call ended: the `end` line of the run ledger."""
    if event.agent_type.strip().lower() != WORKER:
        return None
    data = open_task(ctx)
    if data is None or not (isinstance(data.get("autorun"), dict) and data["autorun"].get("state") == "on"):
        return None
    from . import autorun

    raw = event.raw
    # Copilot (recorded 2026-11-17): the reply is `response` and the end is `stopReason`/`stop_reason`; `last_assistant_message` is the Claude Code name.
    message = next((str(raw[key]) for key in ("response", "last_assistant_message", "lastAssistantMessage") if raw.get(key)), "")
    stop = next((str(raw[key]) for key in ("stop_reason", "stopReason") if raw.get(key)), "")
    autorun.ledger_end(ctx.root, data["task"], message, stop)
    return None


def on_stop(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if is_subagent_session(ctx) or ctx.admin:
        return None  # a subagent finishing; admin mode has no task
    data = open_task(ctx)
    if data is None:
        return None
    if in_ask_turn(ctx):
        end_ask_turn(ctx, data)
        return None  # the end of a question turn: the task waits for what it waited for, and nothing is asked of the agent
    pushed = autorun_stop(ctx, data, event.stop_hook_active)
    if pushed is not None:
        return pushed  # autorun: on to the next step, however often the agent has been pushed before
    if autorun_goes_on(ctx, data):
        mark_waiting(ctx, data, True)  # the cap of blocks in a row, or a pit stop: no block; the board wakes the agent. The run stays on
        return None
    if event.stop_hook_active:
        mark_waiting(ctx, data, True)  # the second Stop of a block: this time the agent does stop
        return None
    blocks: List[Decision] = [item for item in (review_stop(ctx, data), task_file_stop(ctx, data), write_back_stop(ctx, data)) if item is not None]
    if not blocks:  # an offer waits until nothing else is asked of the agent
        blocks = [item for item in (kb_offer_stop(ctx, data),) if item is not None]
    if not blocks:
        mark_waiting(ctx, data, True)
        return None
    facts: Dict[str, Any] = {}
    for item in reversed(blocks):
        facts.update(item.facts)
    return Decision(block=True, reason="\n".join(item.reason for item in blocks), facts=facts)


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.event == "PreToolUse" and event.tool_kind == "ask":
        refused = on_ask_call(event, ctx)
        if refused is not None:
            return refused  # refused: the person is not asked, so the board is not told "asking"
    note_asking(event, ctx)
    if event.event == "SubagentStop":
        return on_subagent_stop(event, ctx)
    if event.event == "SessionStart":
        return Decision(context=prompt_text(ctx))
    if event.event == "UserPromptSubmit":
        return on_user_prompt(event, ctx)
    if event.event == "PreToolUse" and event.tool_kind == "subagent":
        return on_subagent_call(event, ctx)
    if event.event == "SubagentStart":
        return on_subagent_start(event, ctx)
    if event.event == "PostToolUse":
        if event.tool_kind == "ask":
            note_ask_return(ctx)
        on_task_write(event, ctx)
        return on_review_done(event, ctx)
    if event.event == "Stop":
        return on_stop(event, ctx)
    return None
