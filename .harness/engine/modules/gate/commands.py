"""CLI commands of the gate module.

  approve-command    the person approves one git command the gate refused (terminal only)
  admin on           the person switches admin mode on for one session (terminal only): guardrail files open up for it
  admin off          switch it off again (anyone may: it only takes rights away)
  admin status       the sessions that are in admin mode
"""

from __future__ import annotations

import sys
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import approval, config, guardrails, messages, tasks
from core.paths import cli_command, repo_root, state_dir, utc_now
from core.state import admin_on, session, state_path

from . import approvals
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
    is talking, so choosing the admin agent in the picker cannot be what opens the guardrail files."""
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


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser("approve-command", help="the person approves a git command the gate refused (terminal only)")
    parser.set_defaults(handler=cmd_approve_command)

    admin = subparsers.add_parser("admin", help="admin mode of a session: it may change guardrail files")
    commands = admin.add_subparsers(dest="admin_command", required=True)
    on = commands.add_parser("on", help="the person switches admin mode on for one session (terminal only)")
    off = commands.add_parser("off", help="switch admin mode off for one session")
    for item in (on, off):
        item.add_argument("--surface", default="vscode", choices=list(SURFACES))
        item.add_argument("--session-id", required=True)
    on.set_defaults(handler=lambda args: admin_switch_on(repo_root(), args.session_id, args.surface))
    off.set_defaults(handler=lambda args: admin_switch_off(repo_root(), args.session_id, args.surface))
    status = commands.add_parser("status", help="the sessions that are in admin mode")
    status.set_defaults(handler=lambda args: {"admin_sessions": admin_sessions(repo_root())})
