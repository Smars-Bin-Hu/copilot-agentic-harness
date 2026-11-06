"""gate hook handler. PreToolUse only. It guards writes and never blocks a read.

  edit / create tools   a guardrail file or a file only the CLI writes is denied; a session that holds a task writes inside the task folder only
  admin mode            the person switched it on for this session (`admin on`): guardrail files are open, except those
                        that stay closed for an admin (the runtime folder). Every other rule here stays as it is
  terminal              a command that writes a guardrail file or is dangerous is denied; some commands ask a person
  git commands          with target repositories configured (A5): a git read passes, a write is refused until a person approves that exact command
                        (`approve-command`), some are never approved (push, clean, reset --hard, branch -D, any force)
  `.git`                a path in a `.git` folder is always denied, in a terminal command too (A4); so is a path a target
                        repository lists in refused_paths

A write tool with no path the gate can read is denied: the gate cannot tell what it would change. Any other call it cannot
read is allowed (AGENTS.md). A tool or a shape never seen is kept for `doctor` (core/unseen.py), by name and shape only.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import json
import re

from core import calls, reach, repo_paths, servers, targets, tasks, unseen
from core.paths import board_serve_port
from core.context import Context
from core.events import Decision, HookEvent, merge

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
    through: `allow`, or `task` in a task whose plan the person approved, or in a test task for an environment the person let the agent run (an `outbox` call passes later, when `check_external`
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
    how = "allow" if passes else ""  # what let it through (core.calls): the evidence says it (1.7.9)
    if event.agent_type.strip():  # a subagent (the reviewer, the mapper) reads only: the person's leave (a plan, a grant, an open environment, an approval) is the main agent's, never its own (1.7.9)
        return {"action": action, "decision": decision, "passes": passes, "approved": False, "opened": False, "how": how, "code": "", "subagent": not passes}
    opened = False
    if decision == external.TASK:
        data = _open_task(ctx)
        if data and _test_granted(data, action.env):
            passes, how = True, "runner"
        elif data and tasks.plan_approved(ctx.root, data["task"], data):
            passes, how = True, "plan"
    if decision in (external.TASK, external.OUTBOX, external.HUMAN) and not passes and _openable(systems.get(action.system) or {}):
        data = _open_task(ctx)
        opened = bool(data and _env_opened(data, action.env))  # the person opened this environment for this task (`task allow`, 1.7.4): no further approval
        passes = opened
        how = "opened" if opened else ""
    return {"action": action, "decision": decision, "passes": passes, "approved": False, "opened": opened, "how": how, "code": ""}


def _openable(system: Dict[str, Any]) -> bool:
    """May Open to the agent let this system's held calls through (1.7.13)? A system says so with `openable`; a connector's system (a ticket board, a
    pipeline) is closed unless it says yes: its writes reach people, so the person approves each one."""
    if isinstance(system.get("openable"), bool):
        return system["openable"]
    return not system.get("connector")


def _env_opened(data: Dict[str, Any], env: str) -> bool:
    """The person opened this environment for the task (`task allow --env <E> --on`, 1.7.4: `allow_env` in task.json, written by tasklife.set_allow). A gate module reads the task's data only."""
    found = data.get("allow_env") if isinstance(data.get("allow_env"), dict) else {}
    return str(env).lower() in found


def _test_granted(data: Dict[str, Any], env: str) -> bool:
    """A test task has no plan: the person's grant of an environment to the agent (`task test runner --agent`, 1.7.2) is what lets a `task`-level call of that environment through."""
    found = data.get("test_runner") if isinstance(data.get("test_runner"), dict) else {}
    return data.get("kind") == "test" and found.get(str(env).upper()) == "agent"


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
    if judged.get("opened"):
        found["opened"] = True  # the person opened this environment for the task: it went through on that
    return {"external": found}


def check_external(event: HookEvent, ctx: Context, judged: Optional[Dict[str, Any]], policy: dict) -> Optional[Decision]:
    if not judged or judged["passes"]:
        return None
    action, decision = judged["action"], judged["decision"]
    command = gitcmd.collapse(event.command)
    data = _open_task(ctx)
    facts = {"kind": "external", **external_facts(judged)}
    if judged.get("subagent"):  # no code, no draft: the person is not asked for a subagent's write
        return Decision(permission="deny", reason=rules.external_subagent(action, command, event.agent_type.strip()), facts=dict(facts, kind="external-subagent"))
    if decision in (external.OUTBOX, external.HUMAN) and data and (data.get("autorun") or {}).get("state") == "on":
        return Decision(permission="deny", reason=rules.external_autorun(action, command), facts=facts)  # nobody is there to approve
    if decision == external.OUTBOX:
        minutes = approvals.minutes(policy)
        used = approvals.consume(ctx.root, event.session_id, event.command, minutes, file=approvals.ACTIONS)
        if used:
            judged["approved"], judged["how"], judged["code"] = True, "approved", str(used.get("code", ""))
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


def named_servers(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """At a prompt that names a server by its alias: a command that reaches it, so the agent does not search for its host and port. Only those named."""
    text = event.words or event.prompt
    if not text:
        return None
    try:
        found = [one for one in servers.calls(ctx.root) if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(one['alias'])}(?![A-Za-z0-9_-])", text, re.IGNORECASE)]
    except Exception:  # noqa: BLE001 - a reminder must not get in the way
        return None
    if not found:
        return None
    return Decision(context=rules.say("servers.named.context", lines="\n".join(f"- {one['alias']} ({one['env'].upper()}): `{one['call']}`" for one in found)))


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


def watch_reach(event: HookEvent, ctx: Context) -> None:
    """Can the agent reach each environment from VS Code (core.reach, 1.7.9)? The hook runs in VS Code's identity: at the start of a chat it starts the
    pack's probes in a process of their own (the chat does not wait); after a call of a listed system it reads what the terminal printed. Never stops anything."""
    try:
        listed = ctx.policy("tools").get("systems") or {}
        if not listed or external.validate(listed):
            return
        if event.event == "SessionStart":
            reach.start(ctx.root, listed)
            return
        answer = event.tool_response or str((event.raw or {}).get("tool_response") or "")
        for action, _decision in external.classify(event.command, listed):
            reach.note_call(ctx.root, action.system, listed[action.system], action.env, answer, event.event == "PostToolUseFailure")
    except Exception:  # noqa: BLE001 - a look at the way in must not hurt the chat
        return


SECRET_FILE = re.compile(r"\.harness[\\/]+\.env(?![\w.-])", re.IGNORECASE)
DUMP_ALL = re.compile(r"(?:^|[;&|(]\s*)(?:env|printenv|set|export\s+-p|Get-ChildItem\s+env:|gci\s+env:|dir\s+env:|ls\s+env:)\s*(?:$|[;&|)>])", re.IGNORECASE)


def secret_names(ctx: Context) -> list:
    """The variables that carry an identity (the kinds' `auth.env`, and the harness's own keys): no kind is known by name here."""
    names = {servers.PREFIX}
    for kind in servers.kinds(ctx.root).values():
        for auth in (kind.get("auth") or {}).values():
            names.update(str(name) for name in ((auth or {}).get("env") or {}))
    return sorted(names)


def check_secrets(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """The person's identities stay out of the agent's hands (1.7.10): no read of `.harness/.env`, no print of a variable that carries one, no dump of
    the whole environment. A net, not a wall: the person's account is the real limit (docs/03-configure.md)."""
    secret = (ctx.root / servers.ENV_FILE).resolve()
    for path in event.paths or []:
        try:
            target = (ctx.root / path).resolve() if not path.startswith(("/", "\\")) and ":" not in path[:3] else type(ctx.root)(path).resolve()
        except (OSError, ValueError):
            continue
        if target == secret:
            return Decision(permission="deny", reason=rules.say("gate.servers.secret"), facts={"kind": "secret"})
    if event.tool_kind == "terminal" and event.command:
        text = event.command
        named = {name for name in secret_names(ctx) if re.search(r"(?<![\w])" + re.escape(name), text)}
        if SECRET_FILE.search(text) or DUMP_ALL.search(text) or (named and not named <= owned_names(event, ctx)):
            return Decision(permission="deny", reason=rules.say("gate.servers.secret"), facts={"kind": "secret"})
    return None


def owned_names(event: HookEvent, ctx: Context) -> set:
    """The secret variables a command may name: those of the kinds of the servers it calls, and only when every call in it is one of those servers
    (curl needs `$TOKEN` on its own command line; `echo $TOKEN` or a call elsewhere does not get it)."""
    try:
        listed = ctx.policy("tools").get("systems") or {}
        found = external.classify(event.command, listed)
        known, servers_of = servers.kinds(ctx.root), servers.listed(ctx.root)
        if not found or any(action.system not in servers_of for action, _decision in found):
            return set()
        if len(gitcmd.split_segments(event.command)) != len(found):  # another command beside the calls (an `echo`, a pipe to elsewhere): nothing named
            return set()
        names: set = set()
        for action, _decision in found:
            kind = known.get(str(servers_of[action.system].get("kind"))) or {}
            for auth in (kind.get("auth") or {}).values():
                names.update(str(name) for name in ((auth or {}).get("env") or {}))
        return names
    except Exception:  # noqa: BLE001 - when in doubt, nothing is allowed
        return set()


def check_wrapped(event: HookEvent, ctx: Context, judged: Optional[Dict[str, Any]]) -> Optional[Decision]:
    """A server whose identity this window does not hold is reached through `harness as <alias> --` (1.7.10): a call without it, or with another alias, is refused with the line to run."""
    if not judged:
        return None
    alias = judged["action"].system
    wrapped = set(servers.state(ctx.root).get("wrap") or [])
    given = next((found for found in (external.as_run(tokens) for tokens in gitcmd.split_segments(event.command)) if found), None)
    if given and given[0] != alias:
        return Decision(permission="deny", reason=rules.say("gate.servers.wrap.other", given=given[0], alias=alias), facts={"kind": "wrap"})
    if alias in wrapped and not given:
        return Decision(permission="deny", reason=rules.say("gate.servers.wrap", alias=alias, call=f"harness as {alias} -- {gitcmd.collapse(event.command)}"), facts={"kind": "wrap"})
    return None


def wrapped_context(ctx: Context) -> Optional[Decision]:
    """At the start of a chat: one line with the servers (alias and environment) and where their commands are, and which go through `harness as`.
    The command of each is given only at a prompt that names it (`named_servers`): a chat that never touches a server pays for one line."""
    try:
        found = servers.calls(ctx.root)
    except Exception:  # noqa: BLE001 - a server list that cannot be read must not stop the chat
        found = []
    wrapped = servers.state(ctx.root).get("wrap") or []
    parts = [rules.say("servers.calls.context", servers=", ".join(f"{one['alias']} ({one['env'].upper()})" for one in found))] if found else []
    if wrapped:
        parts.append(rules.say("servers.wrap.context", aliases=", ".join(wrapped), first=wrapped[0]))
    return Decision(context="\n".join(parts)) if parts else None


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.event == "SessionStart" or (event.event in ("PostToolUse", "PostToolUseFailure") and event.tool_kind == "terminal"):
        watch_reach(event, ctx)
        return wrapped_context(ctx) if event.event == "SessionStart" else None
    if event.event == "UserPromptSubmit":
        told = merge([approved_context(event, ctx), named_servers(event, ctx)])
        return None if told.is_empty() else told
    if event.event == "PreToolUse" and event.tool_kind != "terminal":
        # A web fetch, a browser or an MCP tool, whatever its name: its input names the address of the board server.
        port = asks_board(ctx, json.dumps(event.raw, ensure_ascii=False, default=str))
        if port:
            return Decision(permission="deny", reason=rules.board_request(port))
    if event.event == "PreToolUse":
        unseen.note_call(ctx.root, event)
        refused = check_secrets(event, ctx)
        if refused:
            return refused
    if event.event != "PreToolUse" or event.tool_kind not in WRITE_KINDS + ("terminal",):
        return None
    policy = ctx.policy(POLICY_NAME)
    validate_policy(policy, floor=False)
    found = load_targets(ctx)
    compiled = Compiled(policy, [(repo.name, repo.path, repo.refused_paths) for repo in found.repos.values()] if found else None, admin=ctx.admin)
    if event.tool_kind == "terminal":
        # Without target repositories the harness behaves as before: only the ask rules in gate.json look at git.
        judged = judge_external(event, ctx)
        wrong = check_wrapped(event, ctx, judged)
        if wrong:
            return wrong
        decided = check_terminal(event, ctx, compiled, policy, guard_git=bool(found and found.configured), judged=judged)
        facts = external_facts(judged)  # after check_terminal: an approved outbox call is marked there
        if facts:  # every call to a listed system leaves its line, whatever rule decided it and also when it went through
            decided = decided or Decision()
            decided.facts.update(facts)
        if judged and (judged["passes"] or judged["approved"]) and not (decided and decided.permission == "deny"):
            data = _open_task(ctx)
            if data:  # the call goes through now: the task keeps what let it through, so a run the agent records can say it (core.calls, 1.7.9)
                calls.note(ctx.root, data["task"], event.command, judged["action"].system, judged["action"].env, judged["action"].verb, judged.get("how", ""), judged.get("code", ""))
        return decided
    if not event.paths:
        return Decision(permission="deny", reason=rules.write_no_path(event.tool_name), facts={"kind": "write-no-path"})
    return check_write(event, ctx, compiled)
