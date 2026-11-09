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

from typing import Any, Dict, List, Optional, Tuple

import json
import re

from core import calls, launchenv, messages, pinfiles, reach, repo_paths, connections, targets, tasks, unseen
from core import systems as systems_mod
from core.paths import board_serve_port
from core.context import Context
from core.events import Decision, HookEvent, merge

from . import approvals, external, failclosed, gitcmd, harnesscmd, outbox, rules, terminal
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
    said = harnesscmd.check(event.command, compiled)  # 1.7.38 (C13 F2): the harness commands only a person may run, read as the shell reads them (a quote, a variable, `xargs`, `python -m cli` hide nothing)
    if said:
        return Decision(permission="deny", reason=said)
    verdict = terminal.check(event.command, compiled, network_judged(ctx))
    if verdict is None or verdict[0] != "deny":  # 1.7.38 (C13 F2): a command string a shell is given (`pwsh -Command '...'`, `bash -c '...'`) goes through the same rules as a bare line; the strictest answer stands
        for inner in external.nested(event.command):
            found = terminal.check(inner, compiled, network_judged(ctx))
            if found is not None and (verdict is None or (found[0] == "deny" and verdict[0] != "deny")):
                verdict = found
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


FILE_OPTIONS = re.compile(r"(?:^|\s)(?:-[A-Za-z]*[oODK]|--(?:output|remote-name|remote-header-name|dump-header|trace|trace-ascii|stderr|config|create-dirs|libcurl)\b)")
WEB_PROGRAM = re.compile(r"(?:^|[\s/])(curl|wget|invoke-webrequest|iwr|invoke-restmethod|irm)(?:\.exe)?(?=\s|$)", re.IGNORECASE)
WGET_STDOUT = re.compile(r"(?:^|\s)(?:-[A-Za-z]*O\s*-(?=\s|$)|--output-document(?:=|\s+)-(?=\s|$))")  # wget prints to the terminal only when its output file is `-`; otherwise it saves a file named after the address
WGET_FILES = re.compile(r"(?:^|\s)(?:-[A-Za-z]*[oaPrmxcNi]|--(?:output-file|append-output|directory-prefix|recursive|mirror|input-file|force-directories|continue|timestamping|warc-file|save-cookies|save-headers|post-file|body-file|config|ca-certificate)\b)")
POWERSHELL_FILE = re.compile(r"(?:^|\s)-o[a-z]*(?=[\s:=]|$)", re.IGNORECASE)  # -OutFile and its short forms (-OutVariable too: it asks, which is safe)


def writes_a_file(segment: str) -> bool:
    """(1.7.38, D1-7) Does this web call save to a file? `curl -o`, `wget` unless its output is `-`, PowerShell `-OutFile`. Such a call could write a guardrail file, so the rule of the network still asks, whatever the address."""
    found = WEB_PROGRAM.search(segment)
    program = found.group(1).lower() if found else "curl"
    args = segment[found.end():] if found else segment
    if program == "wget":
        return not WGET_STDOUT.search(args) or bool(WGET_FILES.search(args))
    if program != "curl":
        return bool(POWERSHELL_FILE.search(args))  # PowerShell's own commands: curl's letters (`-Method` has an `o` and a `d`) mean nothing there
    return bool(FILE_OPTIONS.search(args) or POWERSHELL_FILE.search(args))


def network_judged(ctx: Context) -> Optional[Any]:
    """For the ask rule of the network (1.7.38, Q20): says of one command whether a system the gate knows has judged it, so a `curl` to an Azure DevOps address is not asked about twice. A curl owns by the
    addresses it names only when every one is the system's (`external.addresses_fit`): a curl to the cloud that also names another place is judged as any other curl. Nothing when the list cannot be read."""
    try:
        listed = ctx.policy("tools").get("systems") or {}
        if not listed or external.validate(listed):
            return None
    except Exception:  # noqa: BLE001 - the rule asks as before
        return None

    def judged(segment: str) -> bool:
        if writes_a_file(segment):  # a web call that writes a file (`curl -o`, `-O`, `--output`, `-D`, a config file, `wget` that does not print, `-OutFile`) could write a guardrail file: it asks, as before
            return False
        try:
            found = external.classify(segment, listed)
            if not found or not all(action.system for action, _decision in found):
                return False
            return True  # a program that only an address makes a call is owned only when every address it names is the system's (external.addresses_fit)
        except Exception:  # noqa: BLE001 - when in doubt, ask
            return False

    return judged


def judge_external(event: HookEvent, ctx: Context) -> Optional[Dict[str, Any]]:
    """A call to a system the company listed under `systems` (tools.override.json), or None.

    `{action, decision, passes, approved}`. `decision` is what the policy says (external.py); `passes` is whether the call goes
    through: `allow`, or `task` in a task whose plan the person approved, or in a test task for an environment the person let the agent run (an `outbox` call passes later, when `check_external`
    finds the person's approval: then `approved` is set). No list, or a list that does not validate, means no rule here:
    doctor and `tools check` report the break, and the gate does not guess what a broken policy meant (a hook that fails
    itself must not hurt normal work).

    A command line of several commands is judged one command at a time (1.7.21): it goes through only when every command does; the answer is the one that stops it, the strictest first.
    """
    try:
        systems = ctx.policy("tools").get("systems") or {}
        invalid = external.validate(systems) if systems else []
        if invalid:  # 1.7.38 (C13 F2): a list the gate cannot trust judges nothing, so a line that names a program a tool pack governs is refused (the old way passed every call)
            return failclosed.refusal(ctx.root, event.command, invalid[0], "invalid")
        bare = connections.unconnected(ctx.root, systems)  # 1.7.38 (C13 F2b): the programs a tool pack declares that no connection lists: a call of one is refused, it names no place to be judged for
        if not systems and not bare:
            return None
        task = ctx.state.get("active_task")
        every = external.classify(event.command, {**systems, **bare}, unseen=True, root=ctx.root, cwd=event.cwd or "", folder=(ctx.root / str(task)) if task else None)
        results = [_judge_one(event, ctx, {**systems, **bare}, action, decision) for action, decision in every]
    except Exception as error:  # noqa: BLE001 - 1.7.38 (C13 F2): the gate failed on this line: refused when the line names a program a tool pack governs, as before (no opinion) when it names none
        return failclosed.refusal(ctx.root, event.command, error)
    if not results:
        return None
    stopped = [item for item in results if not item["passes"]]
    pool = stopped or results
    best = pool[0]
    for item in pool:
        if external.DECISIONS.index(item["decision"]) > external.DECISIONS.index(best["decision"]):
            best = item
    best["offers"] = _offers([item["offer"] for item in stopped if item.get("offer")])
    best["hint"] = (({**systems, **bare}).get(best["action"].system) or {}).get("hint")  # what to do instead: the system may be one made for a pack that is off, which the tools policy does not list
    return best


def _offers(found: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One offer for each connection of a held line (the same connection twice is one offer; its linked items are joined)."""
    out: Dict[str, Dict[str, Any]] = {}
    for item in found:
        have = out.setdefault(item["system"], dict(item))
        if item.get("refs"):
            have["refs"] = sorted(set(have.get("refs") or []) | set(item["refs"]))
    return list(out.values())


def _judge_one(event: HookEvent, ctx: Context, systems: Dict[str, Any], action: external.Action, decision: str) -> Dict[str, Any]:
    passes = decision == external.ALLOW
    how = "allow" if passes else ""  # what let it through (core.calls): the evidence says it (1.7.9)
    if action.unseen:  # a command whose program the gate cannot read: it may be a listed one, so it is held, whatever the task allows
        return {"action": action, "decision": decision, "passes": False, "approved": False, "opened": False, "how": "", "code": "", "unseen": True}
    if action.zone in ("unpinned", "blocked"):  # 1.7.38 (C13 F2): a call that reaches no connection the gate can name, or a program it cannot judge: refused, nothing to approve
        return {"action": action, "decision": external.DENY, "passes": False, "approved": False, "opened": False, "how": "", "code": "", "refused": action.zone}
    if action.why == "command":  # the pack's own program has no such command (1.7.38): nothing to approve, nothing runs
        return {"action": action, "decision": external.DENY, "passes": False, "approved": False, "opened": False, "how": "", "code": "", "unknown": action.target}
    if event.agent_type.strip():  # a subagent (the reviewer, the mapper) reads only: the person's leave (a plan, a grant, an open connection, an approval) is the main agent's, never its own (1.7.9)
        return {"action": action, "decision": decision, "passes": passes, "approved": False, "opened": False, "how": how, "code": "", "subagent": not passes}
    opened = False
    system = systems.get(action.system) or {}
    scope = systems_mod.open_scope(system, action.env)  # 1.7.38: how far the person may open this connection: all, items or no (prod is always no)
    if decision == external.TASK:
        data = _open_task(ctx)
        if data and _test_granted(data, action.env):
            passes, how = True, "runner"
        elif data and tasks.plan_approved(ctx.root, data["task"], data):
            passes, how = True, "plan"
    scoped = _item_scope(action.call or action.text, system, action.verb, _open_task(ctx)) if decision in (external.TASK, external.OUTBOX, external.HUMAN) else None
    if scoped and scoped[0] == "unlinked":  # a write to an item the task does not name: refused, with the line that links it (1.7.18)
        return {"action": action, "decision": external.DENY, "passes": False, "approved": False, "opened": False, "how": "", "code": "", "unlinked": scoped[1]}
    if scoped and scoped[0] == "opened" and scope in (systems_mod.ITEMS, systems_mod.ALL):  # a write to an item the task names, and the person opened it (`task allow --links`, with the items named then)
        return {"action": action, "decision": decision, "passes": True, "approved": False, "opened": True, "how": "opened", "code": ""}
    if scoped and scoped[0] == "opened":  # the person opened the linked items, but this connection's type does not let them through (a company lowered it to `no`): held as before
        scoped = ("linked", scoped[1])
    held = decision in (external.TASK, external.OUTBOX, external.HUMAN) and not passes
    unjudged = getattr(action, "zone", "") in ("ask", "broken")  # a call of a type with lists that is in no list (a script the gate could not read, a statement off the write list): opening the connection does not let it through, each run waits for the person
    if held and scope == systems_mod.ALL and action.verb != external.DESTROY and not unjudged:  # the person opened this connection for this task (`task allow --conn`, 1.7.38): no further approval. A destroy never passes
        data = _open_task(ctx)
        opened = bool(data and _conn_opened(data, action.system, action.env))
        passes = opened
        how = "opened" if opened else ""
    result = {"action": action, "decision": decision, "passes": passes, "approved": False, "opened": opened, "how": how, "code": ""}
    if decision == external.OUTBOX and not passes:  # what the card can offer: open this connection (or its linked items) for the task. A line with writes to two connections has one offer for each
        if scope == systems_mod.ALL and action.verb != external.DESTROY and not unjudged:
            result["offer"] = {"system": action.system, "env": action.env, "scope": systems_mod.ALL}
        elif scope == systems_mod.ITEMS and scoped and scoped[0] == "linked":
            result["offer"] = {"system": action.system, "env": action.env, "scope": systems_mod.ITEMS, "refs": [scoped[1]]}
    return result


def check_mcp(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """An MCP tool an installed tool pack names (1.7.14): a read goes through, a write or an exec waits for the person's yes in Copilot (`ask`), a destroy
    is refused, and a subagent may only read. Logged as a call to the tool pack. A tool no tool pack names is left as it was."""
    try:
        from core import toolpacks

        found = toolpacks.mcp_verb(ctx.root, event.tool_name)
    except Exception as error:  # noqa: BLE001 - 1.7.38 (C13 F2): a tool pack that cannot be read must not let its own MCP tool through: refused when the tool is one the packs' files name, left as it was when none does
        return failclosed.decision(ctx.root, event, error)
    if not found:
        return None
    facts = {"external": {"system": found["toolpack"], "env": "none", "verb": found["verb"], "target": event.tool_name, "mcp": True}}
    if found["verb"] == "read":
        return Decision(facts=facts)
    if found["verb"] == "destroy" or event.agent_type.strip():
        return Decision(permission="deny", reason=rules.say("gate.mcp.deny", tool=event.tool_name, toolpack=found["toolpack"], verb=rules.word(found["verb"])), facts=facts)
    return Decision(permission="ask", reason=rules.say("gate.mcp.ask", tool=event.tool_name, toolpack=found["toolpack"], verb=rules.word(found["verb"])), facts=facts)


def _item_scope(call: str, system: Dict[str, Any], verb: str, data: Optional[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
    """A write that names one item of a tool (a work item, a ticket), when the system says how to find it (`item`, its first group) and which link type
    names it (`link`) (1.7.18). `call` is one command from its program on, and the pattern must match from its first word: the words after it are not read for an
    item (a title that spells another command names nothing; 1.7.21). Answers `(state, ref)`. "unlinked": the task does not name that item; "opened": it
    does and the person opened it (`task allow --links` lists the items named at that time; 1.7.21); "linked": it does, not opened (held as before); None: not
    such a write (a read, a new item, no `item` pattern)."""
    if verb != external.WRITE or not system.get("item") or not system.get("link"):
        return None
    patterns = system["item"] if isinstance(system["item"], list) else [system["item"]]
    ids: List[str] = []
    try:
        for index, pattern in enumerate(patterns):
            # the first pattern must match from the program's first word; the others (1.7.25: `--to <id>`) are looked for anywhere in the command, every place they match
            matches = [re.match(str(pattern), call, re.IGNORECASE)] if index == 0 else list(re.finditer(str(pattern), call, re.IGNORECASE))
            for found in matches:
                if found and found.groups():
                    ids.extend(group for group in found.groups() if group)
    except re.error:
        return None
    if not ids:
        return None
    from core import toolpacks

    refs_named = list(dict.fromkeys(toolpacks.normal_ref(f"{system['link']}:{item}") for item in ids))  # every item this command writes
    names = {toolpacks.normal_ref(str(item.get("ref"))) for item in ((data or {}).get("links") or []) if isinstance(item, dict)}
    for ref in refs_named:
        if ref not in names:
            return "unlinked", ref
    opened = (data or {}).get("allow_links")
    refs = {toolpacks.normal_ref(str(item)) for item in ((opened or {}).get("refs") or [])} if isinstance(opened, dict) else set()
    shut = [ref for ref in refs_named if ref not in refs]
    return ("linked", shut[0]) if shut else ("opened", refs_named[0])


def _conn_opened(data: Dict[str, Any], name: str, env: str = "") -> bool:
    """The person opened this connection for the task (`task allow --conn <name> --on`, or the button on a held card, 1.7.38: `allow_conn` in task.json, written by tasklife.set_allow).
    A gate module reads the task's data only. The old `allow_env` (environments, before 1.7.38) is not read: nothing is opened by it."""
    found = data.get("allow_conn") if isinstance(data.get("allow_conn"), dict) else {}
    held = found.get(str(name))
    if held is None:
        return False
    kept = str((held or {}).get("env") or "").lower() if isinstance(held, dict) else ""
    return not kept or kept == str(env).lower()  # a system of several environments opened from a card is open there only; a connection has one environment


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
        changed = _changed_files(ctx, event, minutes)  # the person approved the command with the files it names as they were then (1.7.38, C12 TB-05)
        used = approvals.consume(ctx.root, event.session_id, event.command, minutes, file=approvals.ACTIONS)
        if used and not changed:
            judged["approved"], judged["how"], judged["code"] = True, "approved", str(used.get("code", ""))
            outbox.mark(ctx.root, outbox.draft_of(used), "sent")
            return None  # the person read this command and approved it: it runs once
        task = data["task"] if data else None
        offers = (judged.get("offers") or []) if task else []  # an opening is for a task: with no task open, the card offers none
        cwd = event.cwd or ""
        code = outbox.merge_into_waiting(ctx.root, task or "", event.session_id, event.command, action, minutes, offers, cwd) or approvals.request(ctx.root, event.surface, event.session_id, event.command, minutes, file=approvals.ACTIONS, extra=outbox.entry_extra(action, task, offers, cwd))
        draft = outbox.write_draft(ctx.root, task, code, action, command, event.session_id, minutes) if task else ""
        return Decision(permission="deny", reason=rules.external_outbox(action, command, code, minutes, draft, offers, changed), facts=dict(facts, kind="external-outbox", **({"changed": changed} if changed else {})))
    if judged.get("refused") == "unpinned":
        return Decision(permission="deny", reason=rules.external_unpinned(action, command), facts=dict(facts, kind="external-unpinned"))
    if judged.get("refused") == "blocked":
        return Decision(permission="deny", reason=rules.external_blocked(action, command), facts=dict(facts, kind="external-blocked"))
    if judged.get("unseen"):
        named = action.target if action.unseen else ""
        key = {"file": "gate.external.unreadable_file", "encoded": "gate.external.encoded"}.get(action.why) or ("gate.external.unreadable" if named else "gate.external.unseen")
        return Decision(permission="deny", reason=rules.say(key, call=command, program=named, path=named), facts=dict(facts, kind="external-unseen"))
    if judged.get("unknown"):
        program = (action.call.split(" ", 1)[0] if action.call else "") or action.system
        return Decision(permission="deny", reason=rules.say("gate.external.unknown_command", program=program, word=judged["unknown"], call=command), facts=dict(facts, kind="external-unknown"))
    if judged.get("unlinked"):
        return Decision(permission="deny", reason=rules.say("gate.external.unlinked", system=action.system, ref=judged["unlinked"], call=command, step=_link_step(ctx, judged["unlinked"], data)), facts=dict(facts, kind="external-unlinked"))
    reason = {external.DENY: rules.external_refused if action.zone == "refuse" else rules.external_denied_file if action.file_why == "destroy" else rules.external_denied, external.TASK: rules.external_task}.get(decision, rules.external_human)(action, command)
    if decision == external.DENY and not action.zone and not action.file_why:  # 1.7.38 (D1-7): a system may say what to do instead of the refused call (`hint`)
        hint = judged.get("hint") or ((ctx.policy("tools").get("systems") or {}).get(action.system) or {}).get("hint")
        if hint:
            reason = rules.external_denied(action, command, hint)
    return Decision(permission="deny", reason=reason, facts=facts)


def _changed_files(ctx: Context, event: HookEvent, minutes: int) -> List[str]:
    """The files this command names, inside its task, that are not as they were when the person approved it: changed, gone, or new (`core.pinfiles`). Empty when no approval is waiting for the command,
    when it was approved with no files kept (before 1.7.38), or when all are the same. Never raises. A read of the files that fails (1.7.38, C13 F2) says they changed: the approval is for the files as the person saw them,
    and a gate that cannot tell does not let the call through on it; the card is asked again."""
    try:
        text = approvals.collapse(event.command)
        entry = next((item for item in approvals.approved(ctx.root, event.session_id, minutes, file=approvals.ACTIONS) if item.get("command") == text), None)
        if entry is None or entry.get("files") is None:
            return []
    except Exception:  # noqa: BLE001 - nothing approved can be found: there is nothing to compare, and the approval is not used either
        return []
    try:
        return pinfiles.changed(entry["files"], pinfiles.pins(event.command, ctx.root, str(entry.get("task") or ""), event.cwd or str(entry.get("cwd") or "")))
    except Exception:  # noqa: BLE001 - see above
        return ["?"]


def settle_opened(ctx: Context, command: str) -> None:
    """The agent runs again a command whose connection the person opened from its card (1.7.38): the green card of the page has done its work. Never in the way of the call."""
    try:
        data = _open_task(ctx)
        if data:
            outbox.settle_opened(ctx.root, data["task"], command)
    except Exception:  # noqa: BLE001 - a card that stays a little longer is no harm
        pass


def _link_step(ctx: Context, ref: str, data: Optional[Dict[str, Any]]) -> str:
    """What to do to write an item the task does not name (1.7.21): no task open yet: open a Q&A one first; several open: name the task."""
    if not data:
        return rules.say("gate.external.unlinked.none", ref=ref)
    many = len(tasks.folders(ctx.root)) > 1 and sum(1 for name in tasks.folders(ctx.root) if (tasks.read(ctx.root, name) or {}).get("status") == "open") > 1
    return rules.say("gate.external.unlinked.some", ref=ref, task=str(data["task"]).replace("\\", "/").rsplit("/", 1)[-1]) if many else rules.say("gate.external.unlinked.one", ref=ref)


def approved_context(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """At a prompt: the outside calls the person approved for this session and that are not used yet, so the agent runs them."""
    try:
        waiting = approvals.approved(ctx.root, event.session_id, approvals.minutes(ctx.policy(POLICY_NAME)), file=approvals.ACTIONS)
    except Exception:  # noqa: BLE001 - a reminder must not get in the way
        return None
    if not waiting:
        return None
    return Decision(context=rules.external_approved([item["command"] for item in waiting]))


def named_line(ctx: Context, one: Dict[str, str]) -> str:
    """One connection a prompt names (1.7.20): its fields and the tool pack's skills and program. With no tool pack to point at, the test command is all there is, and it is given as that."""
    try:
        info = connections.brief(ctx.root, one["alias"], one["call"])
    except Exception:  # noqa: BLE001 - a line must not be lost for one broken type
        info = {"alias": one["alias"], "env": one["env"], "fields": {}, "skills": [], "program": "", "toolpack": "", "label": "", "call": one["call"]}
    info.setdefault("missing", [])
    info.setdefault("signin", False)
    info.setdefault("about", "")
    env = "" if info["env"] in ("", "none") else f" ({info['env'].upper()})"
    fields = ", ".join(f"{key}={value}" for key, value in info["fields"].items())
    head = f"- {info['alias']}{env}" + (f": {info['label']}" if info["label"] else "") + (f" [{fields}]" if fields else "") + (rules.say("connections.named.about", about=info["about"]) if info.get("about") else "")
    wrap = rules.say("connections.named.wrap", alias=info["alias"]) if one["call"].startswith(f"harness as {info['alias']} --") else ""
    lacks = "".join(messages.gap() + rules.say("connections.named.missing", program=program) for program in info["missing"])  # 1.7.37: a program the pack needs is not on this computer
    lacks += messages.gap() + rules.say("connections.named.signin", alias=info["alias"]) if info["signin"] else ""
    lacks += open_text(ctx, info["alias"], info["env"])
    if info["skills"]:
        return head + rules.say("connections.named.pack", toolpack=info["toolpack"], skills=", ".join(info["skills"]), program=info["program"] or "-") + wrap + lacks
    return head + rules.say("connections.named.test", call=info["call"]) + lacks


def open_text(ctx: Context, alias: str, env: str) -> str:
    """Layer 2 (1.7.38): whether the person opened this connection for the task in hand, in a few words. Nothing when it is not open (a held call says what to do)."""
    try:
        data = _open_task(ctx)
        if not data:
            return ""
        if _conn_opened(data, alias, env):
            return rules.say("connections.named.opened")
        system = (ctx.policy("tools").get("systems") or {}).get(alias) or {}
        if data.get("allow_links") and system.get("item") and systems_mod.open_scope(system, env) in (systems_mod.ITEMS, systems_mod.ALL):
            return rules.say("connections.named.items")
    except Exception:  # noqa: BLE001 - a line of help must not be lost for this
        pass
    return ""


def named_servers(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """At a prompt that names a server by its alias: a command that reaches it, so the agent does not search for its host and port. Only those named."""
    text = event.words or event.prompt
    if not text:
        return None
    try:
        found = [one for one in connections.calls(ctx.root, every=True) if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(one['alias'])}(?![A-Za-z0-9_-])", text, re.IGNORECASE)]
    except Exception:  # noqa: BLE001 - a reminder must not get in the way
        return None
    if not found:
        return None
    told = ctx.module_state(NAME).setdefault("told", [])
    told.extend(one["alias"] for one in found if one["alias"] not in told)  # the details are given: the first call to it needs not give them again
    return Decision(context=rules.say("connections.named.context", lines="\n".join(named_line(ctx, one) for one in found)))


def first_reach(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """Layer 2 (1.7.38): the first time a command of the agent that reached a connection has run in a chat (read after it ran, whether it worked or not), the connection's details once: fields, the
    tool pack's skill and program, whether the sign-in is saved, and whether the person opened it for this task. A connection a prompt named has had them already. A call that was held did not
    run: the card and the hold message speak then, and the details come with the next call that does. Never in the way of anything."""
    try:
        listed = ctx.policy("tools").get("systems") or {}
        if not listed or external.validate(listed):
            return None
        known = connections.listed(ctx.root)
        names = list(dict.fromkeys(action.system for action, _decision in external.classify(event.command, listed) if action.system in known))
        told = ctx.module_state(NAME).setdefault("told", [])
        fresh = [name for name in names if name not in told]
        if not fresh:
            return None
        calls_of = {one["alias"]: one for one in connections.calls(ctx.root, every=True)}
        told.extend(fresh)
        lines = [named_line(ctx, calls_of.get(name) or {"alias": name, "env": str(known[name].get("env") or ""), "call": ""}) for name in fresh]
        return Decision(context=rules.say("connections.first.context", names=", ".join(fresh), lines="\n".join(lines)))
    except Exception:  # noqa: BLE001 - details are help; nothing is stopped for them
        return None


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
        if event.event == "SessionStart":
            launchenv.note_seen(ctx.root)  # the hook has the environment VS Code was started with (1.7.21)
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
    names = {connections.PREFIX}
    for kind in connections.types(ctx.root, guard=True).values():  # also the kinds of an off pack a connection uses (1.7.38)
        for auth in (kind.get("auth") or {}).values():
            names.update(str(name) for name in ((auth or {}).get("env") or {}))
    return sorted(names)


def check_secrets(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """The person's identities stay out of the agent's hands (1.7.10): no read of `.harness/.env`, no print of a variable that carries one, no dump of
    the whole environment. A net, not a wall: the person's account is the real limit (docs/03-configure.md)."""
    secret = (ctx.root / connections.ENV_FILE).resolve()
    for path in event.paths or []:
        try:
            target = (ctx.root / path).resolve() if not path.startswith(("/", "\\")) and ":" not in path[:3] else type(ctx.root)(path).resolve()
        except (OSError, ValueError):
            continue
        if target == secret:
            return Decision(permission="deny", reason=rules.say("gate.connections.secret"), facts={"kind": "secret"})
    if event.tool_kind == "terminal" and event.command:
        text = event.command
        named = {name for name in secret_names(ctx) if re.search(r"(?<![\w])" + re.escape(name), text)}
        if SECRET_FILE.search(text) or DUMP_ALL.search(text) or (named and not named <= owned_names(event, ctx)):
            return Decision(permission="deny", reason=rules.say("gate.connections.secret"), facts={"kind": "secret"})
    return None


def owned_names(event: HookEvent, ctx: Context) -> set:
    """The secret variables a command may name: those of the kinds of the servers it calls, and only when every call in it is one of those servers
    (curl needs `$TOKEN` on its own command line; `echo $TOKEN` or a call elsewhere does not get it)."""
    try:
        listed = ctx.policy("tools").get("systems") or {}
        found = external.classify(event.command, listed)
        known, servers_of = connections.types(ctx.root, guard=True), connections.listed(ctx.root)
        if not found or any(action.system not in servers_of for action, _decision in found):
            return set()
        if len(gitcmd.split_segments(event.command)) != len(found):  # another command beside the calls (an `echo`, a pipe to elsewhere): nothing named
            return set()
        names: set = set()
        for action, _decision in found:
            kind = known.get(str(servers_of[action.system].get("type"))) or {}
            for auth in (kind.get("auth") or {}).values():
                names.update(str(name) for name in ((auth or {}).get("env") or {}))
        return names
    except Exception:  # noqa: BLE001 - when in doubt, nothing is allowed
        return set()


def check_wrapped(event: HookEvent, ctx: Context, judged: Optional[Dict[str, Any]]) -> Optional[Decision]:
    """A server whose identity this window does not hold is reached through `harness as <alias> --` (1.7.10): a call without it, or with another alias, is refused with the line to run."""
    if not judged or judged["action"].zone in ("unpinned", "blocked"):
        return None
    alias = judged["action"].system
    wrapped = set(connections.state(ctx.root).get("wrap") or [])
    given = next((found for found in (external.as_run(tokens) for tokens in gitcmd.split_segments(event.command)) if found), None)
    if given and given[0] != alias and alias not in connections.listed(ctx.root):  # 1.7.38 (C13 F2, U1): a system of a tool pack (`ado-web`) is no connection: the text names the connections that own it, never the system
        owners = connections.serving(ctx.root, (ctx.policy("tools").get("systems") or {}).get(alias) or {})
        if given[0] in owners:
            return Decision(permission="deny", reason=rules.say("gate.connections.wrap.web", given=given[0]), facts={"kind": "wrap"})
        if owners:
            return Decision(permission="deny", reason=rules.say("gate.connections.wrap.other", given=given[0], alias=" or ".join(owners)), facts={"kind": "wrap"})
        return Decision(permission="deny", reason=rules.say("gate.connections.wrap.none", given=given[0]), facts={"kind": "wrap"})
    if given and given[0] != alias:
        return Decision(permission="deny", reason=rules.say("gate.connections.wrap.other", given=given[0], alias=alias), facts={"kind": "wrap"})
    if alias in wrapped and not given:
        return Decision(permission="deny", reason=rules.say("gate.connections.wrap", alias=alias, call=f"harness as {alias} -- {gitcmd.collapse(event.command)}"), facts={"kind": "wrap"})
    return None


def wrapped_context(ctx: Context) -> Optional[Decision]:
    """At the start of a chat: one line with the kinds of connection and how many of each (1.7.38; before it listed every name), all of them (C12 FB-3), and which go through `harness as`:
    the ones the window holds by the prefix, and how many the window was not opened with (they work through the prefix too; `harness connections find` marks them).
    The connection a task needs is found with `harness connections find` (layer 1); its details come when a prompt names it (`named_servers`) or at the first call that reaches it (`first_reach`)."""
    try:
        found = connections.calls(ctx.root, every=True)
    except Exception:  # noqa: BLE001 - a server list that cannot be read must not stop the chat
        found = []
    wrapped = connections.state(ctx.root).get("wrap") or []
    parts = [rules.say("connections.kinds.context", kinds=connections.kind_counts(ctx.root, [one["alias"] for one in found]))] if found else []  # layer 0 (1.7.38): kinds and counts, not names
    away = [one for one in found if one.get("away")]
    if away:
        parts.append(rules.say("connections.away.context", n=len(away)))
    if wrapped:
        parts.append(rules.say("connections.wrap.context", aliases=", ".join(wrapped), first=wrapped[0]))
    try:
        lacks = launchenv.seen(ctx.root)
        if lacks.get("ok") is False and lacks.get("missing"):
            parts.append(rules.say("reach.vscode_env.context", missing=", ".join(str(item) for item in lacks["missing"][:6])))
    except Exception:  # noqa: BLE001
        pass
    return Decision(context="\n".join(parts)) if parts else None


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """The gate. When the whole handler raises (hook.py then counts the gate as having no opinion, and the call goes through), a call to a program or an MCP tool of a tool pack is refused instead (1.7.38, C13 F2)."""
    try:
        return _handle(event, ctx)
    except Exception as error:  # noqa: BLE001 - see above; everything else is left as it was: the error is raised again
        refused = failclosed.decision(ctx.root, event, error)
        if refused is not None:
            return refused
        raise


def _handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.event == "SessionStart" or (event.event in ("PostToolUse", "PostToolUseFailure") and event.tool_kind == "terminal"):
        watch_reach(event, ctx)
        return wrapped_context(ctx) if event.event == "SessionStart" else first_reach(event, ctx)
    if event.event == "UserPromptSubmit":
        told = merge([approved_context(event, ctx), named_servers(event, ctx)])
        return None if told.is_empty() else told
    if event.event == "PreToolUse" and event.tool_kind != "terminal":
        # A web fetch, a browser or an MCP tool, whatever its name: its input names the address of the board server.
        port = asks_board(ctx, json.dumps(event.raw, ensure_ascii=False, default=str))
        if port:
            return Decision(permission="deny", reason=rules.board_request(port))
        if event.tool_kind == "other":  # an MCP or browser tool: no file and no command line
            judged = check_mcp(event, ctx)
            if judged:
                return judged
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
        if judged:
            settle_opened(ctx, event.command)
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
