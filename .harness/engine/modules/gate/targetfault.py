"""A `target.json` that cannot be read (1.7.38, C13 F2b).

The gate used to read a target policy it could not parse as "no target repositories": a write into a target's working tree and a git write in one passed, and only the `.git` floor was left. A check that cannot decide does
not pass. While the target policy (`target.json` and its company and override layers) cannot be read, the gate does not know where the target repositories are, so it takes every git repository other than this one
for a possible target:

  a write tool (edit, create)    whose path is inside such a repository is refused;
  a git command that writes      is refused unless it certainly runs in this repository (the terminal is in this folder or in no repository, and the line names no other place: `-C`, `--git-dir`,
                                 `--work-tree`, `cd`);
  a shell command                that writes inside such a repository (the rules of `gate.json`: `>`, `tee`, `cp`, `sed -i` ...) is refused, with the repositories the line names, and the one the terminal is in.

Work in the task folder and every read stay free. The reason names the file that is wrong and what is wrong. Stdlib only; it never raises. A failure here refuses a call that may write; a read and a local command are left to the other checks.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

from core import messages, repo_paths
from core.events import Decision

from . import gitcmd, terminal
from .policy import Compiled

_SLASH_WORD = re.compile(r"(?:[A-Za-z]:)?[^\s\"'`;&|()<>=,{}]*[/\\][^\s\"'`;&|()<>=,{}]*")
_OTHER_PLACE = re.compile(r"(?:^|[\s;&|(])(?:-C|--git-dir|--work-tree)(?:\s|=|$)|(?:^|[\s;&|(])(?:cd|pushd|chdir|set-location|push-location|sl)\s|\bGIT_(?:DIR|WORK_TREE)=", re.IGNORECASE)


def git_root(path: str) -> Optional[str]:
    """The folder, as written, whose `.git` holds the repository that this path is in (the path itself too); None when it is in none."""
    try:
        here = os.path.normpath(os.path.expanduser(path))
        while True:
            if os.path.exists(os.path.join(here, ".git")):
                return here
            parent = os.path.dirname(here)
            if not parent or parent == here:
                return None
            here = parent
    except (OSError, ValueError):
        return None


def _same(one: Optional[str], other: Optional[str]) -> bool:
    try:
        return bool(one and other) and os.path.normcase(os.path.realpath(str(one))) == os.path.normcase(os.path.realpath(str(other)))
    except (OSError, ValueError):
        return False


def foreign(path: str, root: Path) -> Optional[str]:
    """The root of the git repository this path is in, when it is not the repository of the harness folder; else None."""
    found = git_root(path)
    return found if found and not _same(found, git_root(str(root))) else None


def _here(event: Any, root: Path) -> str:
    return str(event.cwd or root)


def _named(command: str, event: Any, root: Path) -> List[str]:
    """The other git repositories a line names by a path in it, and the one the terminal is in."""
    found: List[str] = []
    base = _here(event, root)
    candidates = [base] + [word for word in _SLASH_WORD.findall(command)]
    for word in candidates:
        word = word.strip()
        if not word:
            continue
        absolute = word if os.path.isabs(os.path.expanduser(word)) or re.match(r"^[A-Za-z]:[\\/]", word) else os.path.join(base, word)
        one = foreign(absolute, root)
        if one and one not in found:
            found.append(one)
    return found


def _absolute(command: str, event: Any, root: Path) -> str:
    """The line with every path in it written out from the terminal's folder (`..` and `.` folded), so a write that spells its path another way is the same text as the repository's own path."""
    base = _here(event, root)
    text = command
    for word in sorted(set(_SLASH_WORD.findall(command)), key=len, reverse=True):
        shown = word.strip()
        if not shown or shown.startswith(("-", "/dev/")):
            continue
        absolute = os.path.expanduser(shown)
        absolute = absolute if os.path.isabs(absolute) or re.match(r"^[A-Za-z]:[\\/]", absolute) else os.path.join(base, absolute)
        text = text.replace(word, os.path.normpath(absolute).replace("\\", "/"))
    return text


def reason(what: str, file: str, problem: str) -> str:
    return messages.text("gate.target.unreadable", what=what, file=file, problem=problem)


def check(event: Any, ctx: Any, policy: dict, write_kinds: tuple, file: str, problem: str) -> Optional[Decision]:
    """The refusal of a call that may reach a target repository while the target policy cannot be read, or None. `file` and `problem` say what is wrong (`diagnose`)."""
    try:
        root = ctx.root
        if event.tool_kind in write_kinds:
            for raw in event.paths or []:
                for absolute in repo_paths.resolve(raw, root, event.cwd):
                    one = foreign(absolute, root)
                    if one:
                        return Decision(permission="deny", reason=reason(messages.text("gate.target.unreadable.path", path=absolute), file, problem), facts={"kind": "target-unreadable"})
            return None
        if event.tool_kind != "terminal":
            return None
        command = event.command or ""
        if gitcmd.classify(command).kind != gitcmd.NONE:
            here = foreign(_here(event, root), root)
            if here or _OTHER_PLACE.search(command) or _named(command, event, root):
                return Decision(permission="deny", reason=reason(messages.text("gate.target.unreadable.git"), file, problem), facts={"kind": "target-unreadable"})
        repos = _named(command, event, root)
        if repos:
            compiled = Compiled(policy, [(Path(one).name or "repo", Path(one), [".git/**"]) for one in repos], admin=ctx.admin)
            base = _here(event, root)
            for text in (command, f"cd {base} && {command}", _absolute(command, event, root)):
                why = terminal.tree_write(text, compiled)
                if why:
                    return Decision(permission="deny", reason=reason(messages.text("gate.target.unreadable.tree", path=repos[0]), file, problem), facts={"kind": "target-unreadable"})
    except Exception:  # noqa: BLE001 - this check failed while the policy is unreadable: a call that may write (a write tool, a git command that writes) does not pass; a read and a local command are left to the other checks
        try:
            writes = event.tool_kind in write_kinds or (event.tool_kind == "terminal" and gitcmd.classify(event.command or "").kind != gitcmd.NONE)
        except Exception:  # noqa: BLE001
            writes = event.tool_kind in write_kinds or event.tool_kind == "terminal"
        if writes:
            return Decision(permission="deny", reason=messages.text("gate.target.unreadable", what=messages.text("gate.target.unreadable.failed"), file=file, problem=problem), facts={"kind": "target-unreadable"})
    return None
