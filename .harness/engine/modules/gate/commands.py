"""CLI commands of the gate module.

  approve-command    the person approves one git command the gate refused (terminal only)
  approve-action     the person approves one call to an outside system the gate held in the outbox (terminal only)
  admin on           the person switches admin mode on for one session (terminal only): guardrail files open up for it
  admin off          switch it off again (anyone may: it only takes rights away)
  admin status       the sessions that are in admin mode
  tools check        the systems listed in tools.json / tools.override.json, and what the gate decides for each of them
"""

from __future__ import annotations

import argparse

import sys
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import approval, config, guardrails, messages, tasks
from core.paths import cli_command, repo_root, state_dir, utc_now
from core.state import admin_on, session, state_path

from . import approvals, external, outbox
from .policy import POLICY_NAME


class CommandError(Exception):
    """A refused command. The message says why and what to do next."""


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def approve(
    root: Any,
    reader: Optional[Callable[[str], str]] = None,
    interactive: Optional[bool] = None,
    out: Any = None,
) -> Dict[str, Any]:
    """Show the git commands waiting for a person, then approve the one whose code is typed. Terminal only, like `approve-promote`."""
    out = out or sys.stdout
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:
        raise CommandError(say("gate.approve.terminal_only"))
    minutes = approvals.minutes(config.load_policy(root, POLICY_NAME))
    waiting = approvals.pending(root, minutes)
    if not waiting:
        raise CommandError(say("gate.approve.none", minutes=minutes))
    print(say("gate.approve.header", minutes=minutes), file=out)
    for number, item in enumerate(waiting, 1):
        print(say("gate.approve.item", number=number, session_id=item["session_id"], surface=item["surface"], created_at=item["created_at"]), file=out)
        print(f"      {item['command']}", file=out)
    answer = (reader or input)(say("gate.approve.prompt")).strip()
    done = approvals.approve(root, answer, minutes) if answer else None
    if done is None:
        raise CommandError(say("gate.approve.refused"))
    return {"approved": True, "command": done["command"], "valid_minutes": minutes, "next": say("gate.approve.next")}


def approve_action(root: Any, reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None) -> Dict[str, Any]:
    """`harness approve-action`: see core.outbox.approve_action (the board calls the same)."""
    try:
        return outbox.approve_action(root, reader, interactive, out)
    except ValueError as error:
        raise CommandError(str(error)) from None


def cmd_approve_command(args: Any) -> Dict[str, Any]:
    return approve(repo_root())


SURFACES = ("vscode",)


def _known_session(root: Path, surface: str, session_id: str) -> None:
    if not state_path(root, surface, session_id).exists():
        raise CommandError(say("gate.session.missing", session_id=session_id))


def admin_switch_on(
    root: Path,
    session_id: str,
    surface: str = "vscode",
    reader: Optional[Callable[[str], str]] = None,
    interactive: Optional[bool] = None,
    out: Any = None,
) -> Dict[str, Any]:
    """Admin mode for one session. Terminal only, with a typed code, like `approve-plan`: a hook cannot tell which agent
    is talking, so choosing an agent in the picker cannot be what opens the guardrail files."""
    try:
        approval.require_person("admin on", interactive)
    except approval.Refused as error:
        raise CommandError(str(error)) from error
    _known_session(root, surface, session_id)
    locked = guardrails.admin_locked(config.load_policy(root, POLICY_NAME))
    with session(root, surface, session_id) as state:
        if state.get("parent_session_id"):
            raise CommandError(say("gate.admin.subagent"))
        if tasks.open_of(root, state) is not None:
            raise CommandError(say("gate.admin.has_task", task=state.get("active_task")))
        if admin_on(state):
            return {"admin": True, "session_id": session_id, "note": say("gate.admin.already")}
        approval.say(
            out,
            say("gate.admin.on.1", session_id=session_id, surface=surface),
            say("gate.admin.on.2"),
            say("gate.admin.on.3", locked=messages.joined(locked)),
            say("gate.admin.on.4"),
        )
        try:
            approval.ask(say("gate.admin.on.question"), hashlib.sha256(f"admin\n{surface}\n{session_id}".encode("utf-8")).hexdigest(), say("gate.admin.on.refused"), reader)
        except approval.Refused as error:
            raise CommandError(str(error)) from error
        state["admin"] = {"on": True, "at": utc_now()}
    return {"admin": True, "session_id": session_id, "locked": locked, "next": say("gate.admin.on.next", session_id=session_id)}


def admin_switch_off(root: Path, session_id: str, surface: str = "vscode") -> Dict[str, Any]:
    _known_session(root, surface, session_id)
    with session(root, surface, session_id) as state:
        was = admin_on(state)
        if "admin" in state:
            state["admin"] = {"on": False, "at": utc_now()}
    return {"admin": False, "session_id": session_id, "was_on": was}


def admin_sessions(root: Path) -> List[Dict[str, Any]]:
    """Every session that is in admin mode now, newest first. A state file that cannot be read is skipped."""
    found: List[Dict[str, Any]] = []
    for surface in SURFACES:
        directory = state_dir(root, surface)
        for path in directory.glob("*.json") if directory.is_dir() else ():
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(state, dict) and admin_on(state):
                found.append({"surface": surface, "session_id": state.get("session_id", path.stem), "since": state["admin"].get("at", ""), "updated_at": state.get("updated_at", "")})
    return sorted(found, key=lambda item: item["updated_at"], reverse=True)


def tools_check(root: Path) -> Dict[str, Any]:
    try:
        systems = config.load_policy(root, "tools").get("systems")
    except Exception as error:  # noqa: BLE001 - a broken file is what this command is for
        return {"systems": [], "errors": [f"tools.json, a tool pack's rules.json or tools.override.json cannot be read: {error}"], "warnings": [], "ok": False, "exit_code": 1}
    return external.report(systems, run=lambda command: external.run_probe(command, root))


def tools_reach(root: Path, probe: bool) -> Dict[str, Any]:
    from core import reach

    listed = config.policy_or_empty(root, "tools").get("systems") or {}
    if external.validate(listed):
        return {"envs": [], "ok": False, "next": "the list of systems has errors: run `harness tools check`"}
    if probe:
        from core import connections as conn_core

        own = set(conn_core.probe_keys(root))  # 1.7.38, C12 TB-13: the connections the board can check itself (it keeps their identity) are checked the way the board checks them: with the identity, the tool folders and the CA bundle.
        # This run is started at the first step of a chat, in VS Code's environment, which has none of the three for a connection signed in here: it answered "failed" or "denied" and put that over the board's own "ok",
        # and the Enter screen and the lobby said a connection did not answer a few minutes after its test had passed.
        if own:
            conn_core.probe_all(root)
        rest = {name: system for name, system in listed.items() if not all(f"{name}:{env}" in own for env in reach.probes(system))}
        if rest:
            reach.probe_all(root, rest, lambda command: external.run_probe(command, root))
    lines = reach.view(root, listed)
    return {"envs": lines, "ok": all(line["state"] == reach.OK for line in lines)}


def run_as(root: Path, alias: str, rest: List[str]) -> Dict[str, Any]:
    """`harness as <alias> -- <command>` (1.7.10): one command of that server with its saved identity; the output as it comes, its exit code."""
    from core import connections

    words = rest[1:] if rest and rest[0] == "--" else rest
    if not words:
        return {"_text": messages.text("connections.as.other", alias=alias), "exit_code": 2}
    listed = config.policy_or_empty(root, "tools").get("systems") or {}
    code, output = connections.run_as(root, alias, words, lambda line: external.classify(line, listed))
    return {"_text": output, "exit_code": code}


def servers_list(root: Path) -> Dict[str, Any]:
    """`harness servers`: every server with its kind, environment and whether an identity is saved; never a password."""
    from core import connections

    env, known = connections.read_env(root), connections.types(root)
    out = []
    for alias, server in connections.listed(root).items():
        kind = known.get(str(server.get("type"))) or {}
        saved = connections.identity_of(env, alias, kind, server)
        out.append({"alias": alias, "type": server.get("type"), "env": server.get("env"), "auth": server.get("auth", ""), "own": bool(server.get("own")),
                    "account": saved.get("account", ""), "saved": bool(saved), "known_kind": bool(kind),
                    "fields": {key: str(server.get(key)) for key in (kind.get("fields") or {}) if server.get(key) not in (None, "")}})
    calls = {one["alias"]: one["call"] for one in connections.calls(root, every=True)}
    for one in out:
        if one["alias"] in calls:
            one["call"] = calls[one["alias"]]
    return {"connections": out, "state": connections.state(root)}


def _find_lines(found: Dict[str, Any], away: Optional[List[str]] = None) -> List[str]:
    lines = []
    for one in found["matches"]:
        where = "" if one["env"] in ("", "none") else f", {one['env'].upper()}"
        about = one["about"] or one["label"]
        lines.append(f"{one['alias']}  ({one['type_label']}{where})" + (f"  {about}" if about else "") + (("  " + say("connections.find.away", alias=one["alias"])) if away and one["alias"] in away else ""))  # not in the window: it works through `harness as` (1.7.38)
    return lines


def servers_find(root: Path, words: List[str]) -> Dict[str, Any]:
    """`harness connections find <words>` (1.7.38, layer 1): a few lines, the connections that fit; a read. `_text`, for the agent to read and for a person."""
    from core import connections

    text = " ".join(words).strip()
    window = connections.window_aliases(root)  # the same connections as the line at the start of a chat: all of them (1.7.38, C12 TB-07, FB-3)
    away = connections.away_aliases(root)
    found = connections.find(root, text, aliases=window) if text else {"matches": [], "total": 0, "all": len(window), "envs": []}
    if not found["all"]:
        return {"_text": say("connections.find.empty")}
    if not text:
        return {"_text": say("connections.find.words")}
    if not found["matches"]:
        return {"_text": say("connections.find.none", words=text, n=found["all"])}
    if found.get("envs") and found["total"] == 1:
        return {"_text": "\n".join(_find_lines(found, away)) + "\n" + say("connections.find.one.env", env=", ".join(env.upper() for env in found["envs"]))}
    lines = _find_lines(found, away)
    if found["total"] > len(found["matches"]):
        lines.append(say("connections.find.more", n=found["total"] - len(found["matches"])))
    lines.append(say("connections.find.many", n=found["total"]) + messages.gap() + say("connections.ask") if found["total"] > 1 else say("connections.find.one"))
    return {"_text": "\n".join(lines)}


def servers_test(root: Path, alias: str) -> Dict[str, Any]:
    """`harness servers test <alias>`: test the way in with the saved identity, from this terminal."""
    from core import connections

    server = connections.listed(root).get(alias) or {}
    kind = connections.types(root).get(str(server.get("type"))) or {}
    found = connections.test(root, alias, connections.identity_of(connections.read_env(root), alias, kind, server))
    said = (found.get("layers") or {}).get("text") or ""  # 1.7.38: the first step that broke, in a sentence
    return {**found, "alias": alias, **({"next": said} if said and found["state"] != "ok" else {}), "exit_code": 0 if found["state"] == "ok" else 1}


def servers_login(root: Path, alias: str, kind: str = "", given: Optional[List[str]] = None) -> Dict[str, Any]:
    """`harness servers login <alias>`: the sign-in of a program that keeps its own (1.7.13). `--kind` and `--set field=value`: a server not saved yet."""
    from core import connections

    own = None
    if kind:
        own = {"type": kind}
        for item in given or []:
            field, _, value = str(item).partition("=")
            if field.strip():
                own[field.strip()] = value.strip()
    code, said = connections.login(root, alias, own)
    if code != 0 and said:  # the sign-in did not start: it says why (no connection, no sign-in way, a program that is not there or not allowed to run)
        raise CommandError(said)
    return {"exit_code": code, "_text": say("connections.login.after", alias=alias) if code == 0 else ""}  # a person's command (the board's Sign in runs it in the Terminal window): words, not JSON


def _wait(root: Path, args: Any) -> Dict[str, Any]:
    from . import wait  # it imports this module's CommandError

    if args.approval:  # 1.7.38: wait for the person's answer on a held call
        return wait.run_approval_wait(root, args.approval, min(max(args.timeout, wait.APPROVAL_TIMEOUT[0]), wait.APPROVAL_TIMEOUT[1]))  # never past what VS Code allows a terminal call
    if not args.run or not args.until:
        raise CommandError(say("wait.approval.args"))
    return wait.run_wait(root, args.run, args.until, args.every, args.timeout, args.out, args.task)


def _launch_state(root: Path) -> Dict[str, Any]:
    from core import launchenv

    return dict(launchenv.state(root), extra=sorted(launchenv.extra(root)))


def _export(root: Path, out: str) -> Dict[str, Any]:
    from core import connections

    found = connections.export(root)
    if not out:
        return found
    Path(out).expanduser().write_text(json.dumps(found, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"written": str(Path(out).expanduser()), "connections": sorted(found["connections"])}


def _mcp(root: Path, allow: bool, block: bool) -> Dict[str, Any]:
    from core import launchenv

    if allow or block:
        approval.require_person("tools mcp", typed=False)
        return launchenv.set_mcp(root, allow)
    return {"mcp": "allowed" if launchenv.mcp_allowed(root) else "blocked", "detected": launchenv.detect_mcp() or "-"}


def _ca_bundle(root: Path, host: str, proxy: Any) -> Dict[str, Any]:
    from core import launchenv

    try:
        made = launchenv.make(root, host, proxy)
    except ValueError as error:
        raise CommandError(str(error)) from None
    return dict(made, exit_code=0 if made["ok"] else 1)


def register(subparsers: Any) -> None:
    tools = subparsers.add_parser("tools", help="the outside systems the gate knows (the connections, the tool packs' rules.json from the company pack, or tools.override.json)")
    tools_commands = tools.add_subparsers(dest="tools_command", required=True)
    check = tools_commands.add_parser("check", help="is the list well formed, what does the gate decide for each system and environment, and is each system that has a probe reachable from here? Exit code 1 when there is an error")
    check.set_defaults(handler=lambda args: tools_check(repo_root()))
    seen = tools_commands.add_parser("reach", help="can the agent reach each environment from VS Code? What the hooks saw: the probes at the start of a chat and the agent's own calls (--probe runs the probes now, in this terminal's identity)")
    seen.add_argument("--probe", action="store_true", help="run the probes now and keep the answers (the hook does this at the start of a chat, in VS Code's identity)")
    seen.set_defaults(handler=lambda args: tools_reach(repo_root(), args.probe))

    machine = tools_commands.add_parser("launch-env", help="what the board gives VS Code when it starts it: the tool folders put before PATH and the CA bundle (Get ready, This computer)")
    machine.set_defaults(handler=lambda args: _launch_state(repo_root()))
    bundle = tools_commands.add_parser("ca-bundle", help="make the CA bundle for the tools of this computer: the public roots and the chain this computer trusts for an outside address, through the proxy; kept only when a check with it passes")
    bundle.add_argument("--host", default="", help="the outside address to reach (default example.com); any address the proxy inspects will do")
    bundle.add_argument("--proxy", default=None, help="host:port of the proxy; left out, the one this computer names (HTTPS_PROXY or the system setting); \"\" for none")
    bundle.set_defaults(handler=lambda args: _ca_bundle(repo_root(), args.host, args.proxy))

    mcp = tools_commands.add_parser("mcp", help="may tool packs add their MCP servers to VS Code here? Shows the setting; --allow or --block changes it (a person at a terminal only; blocked unless you allow it)")
    mcp_side = mcp.add_mutually_exclusive_group()
    mcp_side.add_argument("--allow", action="store_true")
    mcp_side.add_argument("--block", action="store_true")
    mcp.set_defaults(handler=lambda a: _mcp(repo_root(), a.allow, a.block))

    acting = subparsers.add_parser("as", help="run one command of a server with that server's saved identity (when this window does not hold it): harness as <alias> -- <command>")
    acting.add_argument("alias", help="the server, as Get ready lists it")
    acting.add_argument("rest", nargs=argparse.REMAINDER, help="-- then the command, whole")
    acting.set_defaults(handler=lambda a: run_as(repo_root(), a.alias, a.rest))
    def connections_parser(name: str, help_text: str, wrap: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        listing = subparsers.add_parser(name, help=help_text)
        listing_commands = listing.add_subparsers(dest="connections_command")
        looking = listing_commands.add_parser("find", help="find the connection a task needs by some words (a name, a system, an environment, what it is for); a few lines, a read")
        looking.add_argument("words", nargs="+", help="what you look for, for example: sales warehouse dev")
        looking.set_defaults(handler=lambda a: wrap(servers_find(repo_root(), a.words)))
        probe = listing_commands.add_parser("test", help="test the way in to a connection with its saved identity")
        probe.add_argument("alias")
        probe.set_defaults(handler=lambda a: wrap(servers_test(repo_root(), a.alias)))
        out = listing_commands.add_parser("export", help="your own connections in the form of connections.json (no account, no password), to give the company pack or a colleague")
        out.add_argument("--out", default="", help="a file to write it to; left out, it is printed")
        out.set_defaults(handler=lambda a: wrap(_export(repo_root(), a.out)))
        sign = listing_commands.add_parser("login", help="sign in to a connection whose program keeps its own sign-in (an `auth` of identity `tool`, such as az login), with the tool folders and CA bundle VS Code gets")
        sign.add_argument("alias")
        sign.add_argument("--type", default="", help="a connection of your own not saved yet: its type")
        sign.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE", help="a connection of your own not saved yet: one of its fields (more than once)")
        sign.set_defaults(handler=lambda a: wrap(servers_login(repo_root(), a.alias, a.type, a.set)))
        listing.set_defaults(handler=lambda a: wrap(servers_list(repo_root())))

    connections_parser("connections", "the connections of this copy (the company pack's and your own) and whether an identity is saved for each; `test <alias>` tests the way in", lambda found: found)
    connections_parser("servers", "renamed: use `harness connections`. This old name says so, then does the same", lambda found: dict(found, renamed=say("connections.renamed")))  # 1.7.20

    waiting = subparsers.add_parser("wait", help="wait in one call, with no model call: for an outside system to reach a state (--run, --until: a read of a listed system every N seconds until its output matches, or a timeout; the last output goes to a file of the task), or for the person to decide on a held call (--approval <code>)")
    waiting.add_argument("--approval", default="", metavar="CODE", help="wait for the person to approve the held call with this code, open its connection for the task, or dismiss it: returns at once when they do, after 9 minutes when nobody has")
    waiting.add_argument("--run", default="", help="the read-only command of a listed system to run each round, whole, in quotes")
    waiting.add_argument("--until", default="", help="a pattern (regular expression) the output must match to end the wait")
    waiting.add_argument("--every", type=int, default=30, help="seconds between rounds (5 to 600; default 30)")
    waiting.add_argument("--timeout", type=int, default=540, help="seconds after which the wait ends with exit code 1 (10 to 7200; default 540: VS Code hands a terminal call back after 10 minutes, so a longer job is waited for with one call after another)")
    waiting.add_argument("--out", default="", help="a file inside the task folder where the last output is written whole, to record as evidence: RUNS/DEV/wait-job.txt means the task's own RUNS/")
    waiting.add_argument("--task", default="", help="the task the file belongs to (or just its name); left out, the one open task")
    waiting.set_defaults(handler=lambda a: _wait(repo_root(), a))

    parser = subparsers.add_parser("approve-command", help="the person approves a git command the gate refused (terminal only)")
    parser.set_defaults(handler=cmd_approve_command, person_only=True)
    action = subparsers.add_parser("approve-action", help="the person approves one call to an outside system the gate held in the outbox (terminal only)")
    action.set_defaults(handler=lambda _args: approve_action(repo_root()), person_only=True)

    admin = subparsers.add_parser("admin", help="admin mode of a session: it may change guardrail files")
    commands = admin.add_subparsers(dest="admin_command", required=True)
    on = commands.add_parser("on", help="the person switches admin mode on for one session (terminal only)")
    off = commands.add_parser("off", help="switch admin mode off for one session")
    for item in (on, off):
        item.add_argument("--surface", default="vscode", choices=list(SURFACES))
        item.add_argument("--session-id", required=True)
    on.set_defaults(handler=lambda args: admin_switch_on(repo_root(), args.session_id, args.surface), person_only=True)
    off.set_defaults(handler=lambda args: admin_switch_off(repo_root(), args.session_id, args.surface))
    status = commands.add_parser("status", help="the sessions that are in admin mode")
    status.set_defaults(handler=lambda args: {"admin_sessions": admin_sessions(repo_root())})
