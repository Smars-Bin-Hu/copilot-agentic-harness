"""request hook behavior: a subagent call in L3 needs a dispatch, and the subagent is told where its package is.

  PreToolUse(subagent)   L3: only builder and reviewer, and only with a pending dispatch record. The call uses the record up.
                         Other names are refused by task_level. A subagent session cannot call a subagent.
  SubagentStart          the subagent that was just called is told its request, attempt, assignment path and output folder
  Stop, SubagentStop, UserPromptSubmit   the end checks of an L3 request (verify.py)
  UserPromptSubmit       a session that holds a task is told where the task stands
  PostToolUse, Stop      a task with a TASK.md: files of the task were written in this prompt and TASK.md was not, so the
                         agent is asked once, at its Stop, to bring it up to date (M11-8). A reminder, said once per prompt.

The pending records live in request.json (written by `dispatch`). The calls waiting for their SubagentStart live in this
module's state of the session that made the call. Both engines report SubagentStart on that session.
A call the tool refuses after this hook let it pass (a missing required argument) never reaches SubagentStart. The call
stays in the waiting list, so the same role may be called again for that attempt without a new dispatch.
Hook failures are fail-open: hook.py rolls back this module's state changes and carries on.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core import messages, repo_paths, tasks
from core.context import Context
from core.events import Decision, HookEvent
from core.paths import cli_command, mkdir_command

from . import layout, store, verify

NAME = "request"
ROLES = layout.ROLES
CALLS_KEPT = 8


def dispatch_command(request_id: str, role: str) -> str:
    return f"{cli_command()} dispatch --request {request_id} --role {role}"


def refuse(reason: str) -> Decision:
    return Decision(permission="deny", reason=reason)


def on_subagent_call(event: HookEvent, ctx: Context) -> Optional[Decision]:
    request_id = ctx.state.get("active_request")
    if not request_id or ctx.level != 3:
        return None
    if ctx.state.get("parent_session_id"):
        return refuse("子 agent 不能再调用子 agent。做自己的任务，做完用 handoff submit 交接。")
    role = event.subagent_target.strip().lower()
    if role not in ROLES:
        return None  # task_level refuses every name that is not allowed at L3
    with store.locked(ctx.root, request_id) as data:
        pending = [item for item in data["pending_dispatch"] if item["role"] == role]
        if not pending:
            number = data["attempt"]
            used = number >= 1 and role in data["attempts"][number - 1]["dispatched"]
            if used and any(item["role"] == role and item["attempt"] == number for item in ctx.module_state(NAME).get("calls", [])):
                return None  # the earlier call never started: this is the retry
            if used:
                return refuse(
                    f"第 {number} 轮的 {role} 已经调用过了。每次 dispatch 只对应一次调用。"
                    "要再来一轮，先 `attempt new`，再 dispatch；不够就 `request set-status hitl`。"
                )
            return refuse(
                f"L3 调用 {role} 前必须先 dispatch。先填好 to-{role}/assignment.md，再运行 "
                f"`{dispatch_command(request_id, role)}`，然后再调用 {role}。"
            )
        chosen = pending[0]
        data["pending_dispatch"].remove(chosen)
    calls = ctx.module_state(NAME).setdefault("calls", [])
    calls[:] = [item for item in calls if item["role"] != role]  # a call that never started is replaced by this one
    calls.append({"role": role, "attempt": chosen["attempt"]})
    del calls[:-CALLS_KEPT]
    return None


def start_text(request_id: str, role: str, number: int, target_repos: str = "") -> str:
    base = f"{layout.REQUESTS_DIR}/{request_id}"
    where = (
        f"这个请求改的是目标仓库里的文件，成果路径的第一段是仓库名（{target_repos}），例如 `bdtt_repo/src/a.sql`。"
        if target_repos
        else "位置按将来在仓库里的相对路径。"
    )
    package = f"{base}/handoffs/orchestrator/{layout.attempt_name(number)}/to-{role}"
    outputs = f"{base}/{role}/outputs/{layout.attempt_name(number)}"
    return (
        f"你是请求 {request_id} 第 {number} 轮的 {role}。\n"
        f"第一步：读 {package}/assignment.md 和同目录的 manifest.json，按它们工作。\n"
        f"成果和证据写在 {outputs}/ 下，{where}`handoff submit` 的 --output、--evidence 写相对于该目录的路径，不要写完整路径；先用终端 `{mkdir_command()}` 建好父目录（编辑工具不会建）。\n"
        f"做完用 `{cli_command()} handoff submit --request {request_id} --role {role} ...` 交接。"
    )


def target_repo_names(root: Any, request_id: str) -> str:
    """The names of the target repositories when this request has them, else an empty string. Never raises: this is a hint."""
    try:
        if not store.read_request(root, request_id).get("target_mode"):
            return ""
        from core import targets

        return "、".join(targets.load(root).names())
    except Exception:
        return ""


def open_task(ctx: Context) -> Optional[Dict[str, Any]]:
    """The open L2 task of this session, or None. Never raises: this only adds a hint."""
    return tasks.open_of(ctx.root, ctx.state)


def prompt_marker(ctx: Context) -> str:
    """The verifier marker the user wrote in this prompt (`on`, `off` or ``), as task_level read it just before this module."""
    return ((ctx.state["modules"].get("task_level") or {}).get("prompt") or {}).get("verify", "")


def user_review(event: HookEvent, ctx: Context) -> Optional[int]:
    """The n of `[review]=n` in this prompt (or of the old `[verify]`, `[no-verify]`), or None when the user wrote none."""
    from . import taskreview

    return taskreview.marker(event.prompt, prompt_marker(ctx))


def keep_review(event: HookEvent, ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    """The marker in a prompt of an open task sets the task's n. It holds until the user writes another."""
    from . import taskreview

    number = user_review(event, ctx)
    if number is None or number == taskreview.state_of(data)["n"]:
        return data
    return taskreview.set_n(ctx.root, data["task"], number)


def task_text(ctx: Context, data: Dict[str, Any]) -> str:
    """Injected with every user prompt while a task is open: where the task stands, so the rules need not be read again."""
    from . import task as task_ops  # the CLI side of the task; imported late, a hook call rarely needs it
    from . import taskreview

    name = data["task"]
    if data.get("tier") and tasks.task_file(ctx.root, name).is_file():
        head = messages.text(
            "task.inject.head", task=name, round=data["round"],
            kind=messages.text(f"task.kind.{data.get('kind') or 'none'}"), tier=messages.text(f"task.tier.{data['tier']}"),
        )
    else:
        head = messages.text("task.inject.head.plain", task=name, round=data["round"])
    review = ""
    if taskreview.state_of(data)["n"]:  # the count needs the digest of every result file: only when checks are on
        info = taskreview.summary(ctx.root, name, data)
        review = "\n" + messages.text(
            "review.inject", n=info["n"], passes=info["passes"], used=info["checks_used"], limit=info["checks_limit"], agent=taskreview.AGENT, command=cli_command(),
        )
    requirement = ""
    if (tasks.task_dir(ctx.root, name) / tasks.REQ_FILE).is_file():
        requirement = "\n" + messages.text("task.inject.req", task=name)
    return f"{head}{task_ops.next_step(ctx.root, name, data)}{requirement}{review}\n" + messages.text("task.inject.scope", task=name, command=cli_command())


def on_task_subagent_call(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """A session that holds a task may call one subagent: the reviewer, and only with a check open (`task review start`)."""
    from . import taskreview

    data = open_task(ctx)
    if data is None or ctx.state.get("parent_session_id"):
        return None
    called = event.subagent_target.strip() or "通用子 agent"
    if called.lower() != taskreview.AGENT:
        return Decision(permission="deny", reason=messages.text("review.call.other", agent=taskreview.AGENT, called=called), facts={"kind": "task-subagent"})
    if taskreview.state_of(data)["n"] == 0:
        return Decision(permission="deny", reason=messages.text("review.off"), facts={"kind": "task-subagent"})
    if taskreview.pending(data) is None:
        return Decision(permission="deny", reason=messages.text("review.call.no_round", agent=taskreview.AGENT, command=cli_command()), facts={"kind": "task-subagent"})
    return None


def on_task_review_done(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """The reviewer's call has finished: what it said closes the open check."""
    from . import taskreview

    data = open_task(ctx)
    if data is None or event.tool_kind != "subagent" or event.subagent_target.strip().lower() != taskreview.AGENT:
        return None
    info = taskreview.record(ctx.root, data["task"], event.tool_response)
    if info is None:
        return None
    return Decision(facts={"judge": "verifier", "verdict": info["verdict"], "kind": "task-review"})


def on_task_review_stop(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """The result has not passed its checks: say so once per prompt. Past the limit the agent is to stop and ask the person."""
    from . import taskreview

    if event.stop_hook_active or ctx.state.get("parent_session_id"):
        return None
    data = open_task(ctx)
    if data is None:
        return None
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
    return Decision(block=True, reason=messages.text("review.stop", task=name, next=taskreview.next_text(ctx.root, name, data)), facts={"kind": "task_review_missing"})


OPEN_TASKS_SHOWN = 5


def open_tasks_hint(ctx: Context) -> Optional[Decision]:
    """A session that holds no task is told which tasks are open, so "go on with that task" leads to `task open`."""
    names = []
    for folder in tasks.folders(ctx.root):
        data = tasks.read(ctx.root, folder)
        if data and data.get("status") == "open":
            names.append((data.get("updated_at", ""), data.get("name") or folder.rsplit("/", 1)[-1], data.get("kind", "")))
    if not names:
        return None
    names.sort(reverse=True)
    shown = "、".join(f"{name}（{messages.text('task.kind.' + (kind or 'none'))}）" for _stamp, name, kind in names[:OPEN_TASKS_SHOWN])
    if len(names) > OPEN_TASKS_SHOWN:
        shown += " 等"
    return Decision(context=messages.text("rules.task.open_list", count=len(names), names=shown, command=cli_command()))


def relay(ctx: Context) -> Dict[str, Any]:
    return ctx.module_state(NAME).setdefault("relay", {"wrote": False, "task_file": False, "reminded": False})


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


def on_task_stop(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.stop_hook_active or ctx.state.get("parent_session_id") or not verify.rules(ctx).get("task_file_reminder", True):
        return None
    data = open_task(ctx)
    if data is None or not tasks.task_file(ctx.root, data["task"]).is_file():
        return None
    state = relay(ctx)
    if not state["wrote"] or state["task_file"] or state["reminded"]:
        return None
    state["reminded"] = True
    return Decision(block=True, reason=messages.text("task.relay.reminder", task=data["task"]), facts={"kind": "task_file_not_updated"})


def on_subagent_start(event: HookEvent, ctx: Context) -> Optional[Decision]:
    task_data = open_task(ctx)
    if task_data is not None and ctx.level != 3:
        from . import taskreview

        waiting = taskreview.pending(task_data)
        if waiting is None or event.agent_type.strip().lower() != taskreview.AGENT:
            return None
        package = f"{taskreview.round_dir(task_data['task'], waiting['number'])}/{taskreview.PACKAGE}"
        return Decision(context=messages.text("review.start.context", package=package))
    request_id = ctx.state.get("active_request")
    role = event.agent_type.strip().lower()
    if not request_id or role not in ROLES:
        return None
    calls = ctx.module_state(NAME).get("calls", [])
    found = next((item for item in calls if item["role"] == role), None)
    if found is None:
        return None
    calls.remove(found)
    return Decision(context=start_text(request_id, role, found["attempt"], target_repo_names(ctx.root, request_id)))


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.event == "PreToolUse" and event.tool_kind == "subagent":
        return on_subagent_call(event, ctx) if ctx.level == 3 else on_task_subagent_call(event, ctx)
    if event.event == "SubagentStart":
        return on_subagent_start(event, ctx)
    if event.event == "PostToolUse":
        on_task_write(event, ctx)
        return on_task_review_done(event, ctx)
    if event.event == "Stop":
        blocks = [item for item in (verify.on_stop(event, ctx), on_task_review_stop(event, ctx), on_task_stop(event, ctx)) if item is not None]
        if not blocks:
            return None
        facts: Dict[str, Any] = {}
        for item in reversed(blocks):
            facts.update(item.facts)
        return Decision(block=True, reason="\n".join(item.reason for item in blocks), facts=facts)
    if event.event == "SubagentStop":
        return verify.on_subagent_stop(event, ctx)
    if event.event == "UserPromptSubmit":
        if not (event.from_subagent or event.continuation):
            ctx.module_state(NAME)["relay"] = {"wrote": False, "task_file": False, "reminded": False}  # a new prompt, a new count
            ctx.module_state(NAME)["review_n"] = user_review(event, ctx)  # for a task this prompt goes on to make or open
        task_data = None if (event.from_subagent or event.continuation) else open_task(ctx)
        if task_data is not None:
            return Decision(context=task_text(ctx, keep_review(event, ctx, task_data)), facts={"kind": "task"})
        if ctx.level != 3 and not (event.from_subagent or event.continuation) and not ctx.admin:
            return open_tasks_hint(ctx)
        return verify.on_user_prompt(event, ctx)
    return None
