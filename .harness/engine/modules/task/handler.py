"""task hook behavior: what every prompt is told, which subagent may be called, and the two reminders at Stop.

  SessionStart, UserPromptSubmit   the session id; a session that holds a task: where the task stands, its checks;
                                   a session that holds none: which tasks are open and when to open one.
                                   `[review]=n` in the user's prompt sets the n of the task. Admin mode: the admin rules
  PreToolUse(subagent)             a session that holds a task: only the reviewer, and only with a check open
                                   (`task review start`). A session that holds none, or is in admin mode: no subagent.
                                   The one other subagent is the read-only `mapper`, and only after the user typed
                                   `/generic-mapreduce`: that prompt gives the session a number of calls (mapreduce.py)
  SubagentStart                    the reviewer is told where its package is; a mapper is told it only reads
  PostToolUse                      a write inside the task is remembered; the reviewer's answer closes the open check
  Stop                             a task in autorun: the next open step, until a fact says stop (autorun.py);
                                   once per prompt: the result has not passed its checks; task files were written and
                                   TASK.md was not; once per session: the knowledge base is not built yet, offer the
                                   next step (kb_offer). A Stop that goes through leaves a mark in the task for the board:
                                   the agent stopped, the person is next. The next prompt takes the mark away

Hook failures are fail-open: hook.py rolls back this module's state changes and carries on.
"""

from __future__ import annotations

import re

from typing import Any, Dict, List, Optional

from core import guardrails, messages, repo_paths, tasks
from core.context import Context
from core.events import Decision, HookEvent
from core.paths import cli_command

from . import commitmsg, mapreduce
from .policy import POLICY_NAME, validate_policy

NAME = "task"
OPEN_TASKS_SHOWN = 5


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def open_task(ctx: Context) -> Optional[Dict[str, Any]]:
    """The open task this session holds, or None."""
    return tasks.open_of(ctx.root, ctx.state)


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
    """The n of `[review]=n` in this prompt, or None when the user wrote none."""
    from . import taskreview

    return taskreview.marker(event.prompt)


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
    if asked:
        lines.append(say("rules.review.no_task", n=asked))
    listed = open_tasks_text(ctx)
    if listed:
        lines.append(listed)
    return "\n".join(lines)


def on_user_prompt(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.from_subagent or event.continuation:
        # A subagent call message, or the reason of a Stop block fed back by the engine. Not the user.
        return None
    asked = user_review(event)
    state = ctx.module_state(NAME)
    state["relay"] = {"wrote": False, "task_file": False, "reminded": False}  # a new prompt, a new count
    state["review_n"] = asked  # for a task this prompt goes on to make or open
    reply = reply_marker(event.prompt)
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
    if data is not None and data.get("waiting"):
        mark_waiting(ctx, data, False)  # the person answered
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
        return Decision(permission="deny", reason=say("rules.subagent.no_task", called=called, agent=taskreview.AGENT), facts={"kind": "subagent"})
    if called.lower() != taskreview.AGENT:
        return Decision(permission="deny", reason=say("review.call.other", agent=taskreview.AGENT, called=called), facts={"kind": "task-subagent"})
    if taskreview.state_of(data)["n"] == 0:
        return Decision(permission="deny", reason=say("review.off"), facts={"kind": "task-subagent"})
    if taskreview.pending(data) is None:
        return Decision(permission="deny", reason=say("review.call.no_round", agent=taskreview.AGENT), facts={"kind": "task-subagent"})
    return None


def on_subagent_start(event: HookEvent, ctx: Context) -> Optional[Decision]:
    from . import taskreview

    if event.agent_type.strip().lower() == mapreduce.AGENT:
        return Decision(context=say("mapreduce.start.context") + "\n" + say("rules.language"))
    data = open_task(ctx)
    if data is None or event.agent_type.strip().lower() != taskreview.AGENT:
        return None
    waiting = taskreview.pending(data)
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
    for raw in event.paths:
        for relative in repo_paths.repo_relative(raw, ctx.root, event.cwd):
            if relative is None or not relative.lower().startswith(name + "/"):
                continue
            state = relay(ctx)
            state["wrote"] = True
            if relative.lower() == f"{name}/{tasks.TASK_FILE}".lower():
                state["task_file"] = True


def on_review_done(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """The reviewer's call has finished: what it said closes the open check."""
    from . import taskreview

    data = open_task(ctx)
    if data is None or event.tool_kind != "subagent" or event.subagent_target.strip().lower() != taskreview.AGENT:
        return None
    info = taskreview.record(ctx.root, data["task"], event.tool_response)
    if info is None:
        return None
    return Decision(facts={"judge": "reviewer", "verdict": info["verdict"], "kind": "task-review"})


def review_stop(ctx: Context, data: Dict[str, Any]) -> Optional[Decision]:
    """The result has not passed its checks: say so once per prompt. Past the limit the agent is to stop and ask the person."""
    from . import taskreview

    name = data["task"]
    if taskreview.state_of(data)["n"] == 0:
        return None
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

    from . import tasklife

    try:
        tasklife.set_waiting(ctx.root, data["task"], {"since": utc_now(), "why": "stopped"} if stopped else None)
    except Exception:  # noqa: BLE001 - the mark is for a list; losing it must not turn a Stop into an error
        pass


def autorun_stop(ctx: Context, data: Dict[str, Any]) -> Optional[Decision]:
    """A task in autorun (M13-1): the facts say whether the agent is pushed on to the next step or may stop."""
    if not (isinstance(data.get("autorun"), dict) and data["autorun"].get("state") == "on"):
        return None
    from . import autorun

    text = autorun.on_stop(ctx.root, data["task"])
    if text is None:
        return None  # it ends here; the task says why, and the Stop goes on as any other
    return Decision(block=True, reason=text, facts={"kind": "autorun"})


def on_stop(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if is_subagent_session(ctx) or ctx.admin:
        return None  # a subagent finishing; admin mode has no task
    data = open_task(ctx)
    if data is None:
        return None
    pushed = autorun_stop(ctx, data)
    if pushed is not None:
        return pushed  # autorun: on to the next step, however often the agent has been pushed before
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
    if event.event == "SessionStart":
        return Decision(context=prompt_text(ctx))
    if event.event == "UserPromptSubmit":
        return on_user_prompt(event, ctx)
    if event.event == "PreToolUse" and event.tool_kind == "subagent":
        return on_subagent_call(event, ctx)
    if event.event == "SubagentStart":
        return on_subagent_start(event, ctx)
    if event.event == "PostToolUse":
        on_task_write(event, ctx)
        return on_review_done(event, ctx)
    if event.event == "Stop":
        return on_stop(event, ctx)
    return None
