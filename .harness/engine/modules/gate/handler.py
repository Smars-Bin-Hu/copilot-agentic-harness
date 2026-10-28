"""gate hook handler. PreToolUse only. It guards writes and never blocks a read.

  edit / create tools   a guardrail file or a file only the CLI writes is denied; a session that holds a task writes inside the task folder only
  admin mode            the person switched it on for this session (`admin on`): guardrail files are open, except those
                        that stay closed for an admin (the runtime folder). Every other rule here stays as it is
  terminal              a command that writes a guardrail file or is dangerous is denied; some commands ask a person
  git commands          with target repositories configured (A5): a git read passes, a write is refused until a person approves that exact command
                        (`approve-command`), some are never approved (push, clean, reset --hard, branch -D, any force)
  `.git`                a path in a `.git` folder is always denied, in a terminal command too (A4); so is a path a target
                        repository lists in refused_paths

A call with no path the gate can read is allowed: the gate only denies what it can see clearly (AGENTS.md).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import json
import re

from core import repo_paths, targets, tasks
from core.paths import board_serve_port
from core.context import Context
from core.events import Decision, HookEvent

from . import approvals, external, gitcmd, outbox, rules, terminal
from .policy import POLICY_NAME, Compiled, validate_policy

NAME = "gate"
WRITE_KINDS = ("edit", "create")


def check_write(event: HookEvent, ctx: Context, compiled: Compiled) -> Optional[Decision]:
    for raw in event.paths:
        for absolute in repo_paths.resolve(raw, ctx.root, event.cwd):
            if repo_paths.has_git_folder(absolute):
                return Decision(permission="deny", reason=rules.git_folder(absolute))
            hit = compiled.refused_match(absolute)
            if hit:
                return Decision(permission="deny", reason=rules.target_refused_file(*hit))
            tree = compiled.repo_of(absolute)
            if tree:
                return Decision(permission="deny", reason=rules.target_tree_file(tree[0], tree[1]))
        readings = repo_paths.repo_relative(raw, ctx.root, event.cwd)
        for relative in (item for item in readings if item is not None):
            pattern = compiled.guardrail_match(relative)
            if pattern:
                reason = rules.admin_locked_file(relative, pattern) if ctx.admin else rules.guardrail_file(relative, pattern)
                return Decision(permission="deny", reason=reason)
            if compiled.owned_match(relative):
                return Decision(permission="deny", reason=rules.cli_owned_file(relative))
    return check_task_write(event, ctx)


def check_task_write(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """A session that holds a task: the agent writes inside the task folder only. DEV/ holds what goes back to a target repository
    and opens once the person approved PLAN.md; the rest of the folder needs no approval. REQ/ and REF/ are the person's."""
    task = ctx.state.get("active_task")
    if not task:
        return None
    data = tasks.read(ctx.root, task)
    if data is None or data.get("status") != "open":
        return None  # a task that is gone or closed binds nobody
    approved = tasks.plan_approved(ctx.root, task, data)
    dev = f"{task}/{tasks.DEV_NAME}"
    for raw in event.paths:
        for relative in repo_paths.repo_relative(raw, ctx.root, event.cwd):
            shown = relative if relative is not None else raw
            if relative is None or not _within(relative, task) or relative.lower() in (task.lower(), dev.lower()):
                return Decision(permission="deny", reason=rules.task_outside(shown, task), facts={"kind": "task-scope"})
            if _within(relative, dev):
                if not approved:
                    again = tasks.plan_req_changed(ctx.root, task, data)  # approved before, for a requirement that is another one now
                    return Decision(permission="deny", reason=(rules.task_plan_req if again else rules.task_plan_first)(shown, task), facts={"kind": "task-plan-req" if again else "task-plan"})
                continue
            top = relative[len(task) :].strip("/").split("/", 1)[0]
            if top.lower() in tasks.PERSON_DIRS:
                return Decision(permission="deny", reason=rules.task_person_files(shown, task), facts={"kind": "task-scope"})
    return None


def _within(relative: str, folder: str) -> bool:
    relative, folder = relative.lower(), folder.lower().rstrip("/")
    return relative == folder or relative.startswith(folder + "/")


def check_terminal(event: HookEvent, ctx: Context, compiled: Compiled, policy: dict, guard_git: bool, judged: Optional[Dict[str, Any]] = None) -> Optional[Decision]:
    why = terminal.guardrail_write(event.command, compiled)
    if why:
        return Decision(permission="deny", reason=rules.admin_locked_terminal(why) if ctx.admin else rules.guardrail_terminal(why))
    why = terminal.owned_write(event.command, compiled)
    if why:
        return Decision(permission="deny", reason=rules.cli_owned_terminal(why))
    why = terminal.git_write(event.command, compiled)
    if why:
        return Decision(permission="deny", reason=rules.git_folder_terminal(why))
    why = terminal.tree_write(event.command, compiled)
    if why:
        return Decision(permission="deny", reason=rules.target_tree_terminal(why))
    git = gitcmd.classify(event.command) if guard_git else gitcmd.Verdict()
    if git.kind == gitcmd.NEVER:
        return Decision(permission="deny", reason=rules.git_never(git.why, gitcmd.collapse(event.command)))
    verdict = terminal.check(event.command, compiled)
    if verdict is not None and verdict[0] == "deny":
        return Decision(permission="deny", reason=rules.terminal_denied(verdict[1]))
    port = asks_board(ctx, event.command)
    if port:
        return Decision(permission="deny", reason=rules.board_request(port))
    outside = check_external(event, ctx, judged, policy)
    if outside:
        return outside
    if git.kind == gitcmd.APPROVE:
        minutes = approvals.minutes(policy)
        if approvals.consume(ctx.root, event.session_id, event.command, minutes):
            return None  # the person read this command and approved it
        code = approvals.request(ctx.root, event.surface, event.session_id, event.command, minutes)
        return Decision(permission="deny", reason=rules.git_needs_approval(git.why, gitcmd.collapse(event.command), code, minutes), facts={"kind": "git-approval"})
    if verdict is None:
        return None
    permission, why = verdict
    reason = rules.terminal_denied(why) if permission == "deny" else rules.terminal_ask(why)
    return Decision(permission=permission, reason=reason)


def judge_external(event: HookEvent, ctx: Context) -> Optional[Dict[str, Any]]:
    """A call to a system the company listed under `systems` (tools.override.json), or None.

    `{action, decision, passes, approved}`. `decision` is what the policy says (external.py); `passes` is whether the call goes
    through: `allow`, or `task` in a task whose plan the person approved (an `outbox` call passes later, when `check_external`
    finds the person's approval: then `approved` is set). No list, or a list that does not validate, means no rule here:
    doctor and `tools check` report the break, and the gate does not guess what a broken policy meant (a hook that fails
    itself must not hurt normal work).
    """
    try:
        systems = ctx.policy("tools").get("systems") or {}
        if not systems or external.validate(systems):
            return None
        picked = external.strictest(external.classify(event.command, systems))
    except Exception:  # noqa: BLE001 - see above
        return None
    if picked is None:
        return None
    action, decision = picked
    passes = decision == external.ALLOW
    if decision == external.TASK:
        data = _open_task(ctx)
        passes = bool(data and tasks.plan_approved(ctx.root, data["task"], data))
    return {"action": action, "decision": decision, "passes": passes, "approved": False}


def _open_task(ctx: Context) -> Optional[Dict[str, Any]]:
    task = ctx.state.get("active_task")
    data = tasks.read(ctx.root, task) if task else None
    return dict(data, task=task) if data and data.get("status") == "open" else None


def external_facts(judged: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What the log keeps of an outside call: the action and what the policy decided. Never what it returned."""
    if not judged:
        return {}
    found = {**judged["action"].facts(), "decision": judged["decision"]}
    if judged["approved"]:
        found["approved"] = True  # an outbox call the person approved: it went through once
    return {"external": found}


def check_external(event: HookEvent, ctx: Context, judged: Optional[Dict[str, Any]], policy: dict) -> Optional[Decision]:
    if not judged or judged["passes"]:
        return None
    action, decision = judged["action"], judged["decision"]
    command = gitcmd.collapse(event.command)
    data = _open_task(ctx)
    facts = {"kind": "external", **external_facts(judged)}
    if decision in (external.OUTBOX, external.HUMAN) and data and (data.get("autorun") or {}).get("state") == "on":
        return Decision(permission="deny", reason=rules.external_autorun(action, command), facts=facts)  # nobody is there to approve
    if decision == external.OUTBOX:
        minutes = approvals.minutes(policy)
        used = approvals.consume(ctx.root, event.session_id, event.command, minutes, file=approvals.ACTIONS)
        if used:
            judged["approved"] = True
            outbox.mark(ctx.root, outbox.draft_of(used), "sent")
            return None  # the person read this command and approved it: it runs once
        task = data["task"] if data else None
        code = approvals.request(ctx.root, event.surface, event.session_id, event.command, minutes, file=approvals.ACTIONS, extra=outbox.entry_extra(action, task))
        draft = outbox.write_draft(ctx.root, task, code, action, command, event.session_id, minutes) if task else ""
        return Decision(permission="deny", reason=rules.external_outbox(action, command, code, minutes, draft), facts=dict(facts, kind="external-outbox"))
    reason = {external.DENY: rules.external_denied, external.TASK: rules.external_task}.get(decision, rules.external_human)(action, command)
    return Decision(permission="deny", reason=reason, facts=facts)


def approved_context(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """At a prompt: the outside calls the person approved for this session and that are not used yet, so the agent runs them."""
    try:
        waiting = approvals.approved(ctx.root, event.session_id, approvals.minutes(ctx.policy(POLICY_NAME)), file=approvals.ACTIONS)
    except Exception:  # noqa: BLE001 - a reminder must not get in the way
        return None
    if not waiting:
        return None
    return Decision(context=rules.external_approved([item["command"] for item in waiting]))


def asks_board(ctx: Context, text: str) -> int:
    """The port, when `text` sends a request to the board server that runs from this copy: its buttons are the person's."""
    port = board_serve_port(ctx.root)
    if port and re.search(rf"(?:127\.0\.0\.1|localhost|\[::1\]|0\.0\.0\.0)\s*:\s*{port}\b", text, re.IGNORECASE):
        return port
    return 0


def load_targets(ctx: Context) -> Optional[targets.Targets]:
    """The target repositories. A broken target.json gives None: the `.git` floor still holds, and doctor reports it."""
    try:
        return targets.load(ctx.root)
    except Exception:  # noqa: BLE001 - the gate must not fail on a bad target.json
        return None


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.event == "UserPromptSubmit":
        return approved_context(event, ctx)
    if event.event == "PreToolUse" and event.tool_kind != "terminal":
        # A web fetch, a browser or an MCP tool, whatever its name: its input names the address of the board server.
        port = asks_board(ctx, json.dumps(event.raw, ensure_ascii=False, default=str))
        if port:
            return Decision(permission="deny", reason=rules.board_request(port))
    if event.event != "PreToolUse" or event.tool_kind not in WRITE_KINDS + ("terminal",):
        return None
    policy = ctx.policy(POLICY_NAME)
    validate_policy(policy, floor=False)
    found = load_targets(ctx)
    compiled = Compiled(policy, [(repo.name, repo.path, repo.refused_paths) for repo in found.repos.values()] if found else None, admin=ctx.admin)
    if event.tool_kind == "terminal":
        # Without target repositories the harness behaves as before: only the ask rules in gate.json look at git.
        judged = judge_external(event, ctx)
        decided = check_terminal(event, ctx, compiled, policy, guard_git=bool(found and found.configured), judged=judged)
        facts = external_facts(judged)  # after check_terminal: an approved outbox call is marked there
        if facts:  # every call to a listed system leaves its line, whatever rule decided it and also when it went through
            decided = decided or Decision()
            decided.facts.update(facts)
        return decided
    return check_write(event, ctx, compiled)
