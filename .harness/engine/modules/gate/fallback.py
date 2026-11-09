"""The gate when its own policy cannot be read (1.7.38, C13 F2c).

`gate.json` (or the company's or the person's layer on it) that cannot be read used to make the whole handler raise. The hook counted that as "no opinion", so every local protection passed: guardrail files, writes outside
the task folder, git writes. A guardrail that cannot decide does not pass. Now the handler runs on `builtin.py`, a copy of the shipped policy (the guardrail paths, the terminal rules, the git setting), and this module
adds the strict part on top of what those rules say:

  a write tool (edit, create)   passes only inside the folder of an open task (no open task: no folder, no write);
  a git command that writes     is refused;
  a shell command that writes   a file outside that folder is refused: `>`, `tee`, `rm`, `mv`, `cp`, `mkdir`, `touch`, `sed -i`, `dd of=`, the PowerShell writers. A path it cannot read (a variable, a command
                                inside it) counts as outside. A script, an interpreter's own code and a build tool write in ways this does not see: a net, not a sandbox.

Reads, work inside the task folder and every other call stay free. An admin session (the person switched it on to extend the harness) gets the built-in rules and nothing more, so the file can be mended through it.
Every refusal names the file that is wrong and what is wrong. Stdlib only; it never raises.
"""

from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, List, Optional

from core import messages, tasks
from core.events import Decision

from . import external, gitcmd

_EVERY = frozenset("mkdir touch rm rmdir unlink del erase rd truncate shred mv move ren rename".split())  # every word that is no option is a file the command changes
_FIRST_IS_NOT_A_FILE = frozenset("chmod chown chgrp".split())  # `chmod +x f`: the first word is the mode
_LAST = frozenset("cp install rsync ln copy xcopy".split())  # the last word (or `-t dir`) is where it writes
_POWERSHELL = frozenset("set-content add-content out-file new-item remove-item copy-item move-item rename-item clear-content set-itemproperty tee-object export-csv export-clixml ni sc ac ri cpi mi rni".split())
_POWERSHELL_PATHS = ("-path", "-literalpath", "-filepath", "-destination", "-outfile", "-newname")
_SWITCHES = frozenset("-force -recurse -append -noclobber -whatif -confirm -nonewline -passthru -verbose".split())  # options with no value
_UNKNOWN = re.compile(r"[$`]")  # a variable or a command inside the word: where it goes is not in the line


def task_folder(ctx: Any) -> Optional[Path]:
    """The folder of the task this session holds, when it is open (as `handler.check_task_write` reads it); else None."""
    task = ctx.state.get("active_task")
    data = tasks.read(ctx.root, task) if task else None
    return ctx.root / str(task) if data and data.get("status") == "open" else None


def _same_or_inside(path: str, folder: Path) -> bool:
    try:
        real, base = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(str(folder)))
        return os.path.commonpath([real, base]) == base
    except (OSError, ValueError):
        return False


def _absolute(word: str, base: Optional[str]) -> Optional[str]:
    """The word as an absolute path, or None when it cannot be told (a variable, a relative path after a `cd` the line does not show)."""
    word = word.strip().strip("\"'")
    if not word or _UNKNOWN.search(word):
        return None
    word = os.path.expanduser(word)
    if re.match(r"^[A-Za-z]:[\\/]", word) or os.path.isabs(word):
        return os.path.normpath(word)
    return os.path.normpath(os.path.join(base, word)) if base else None


def _paths_written(tokens: List[str]) -> List[str]:
    """The words a command (one segment, redirections taken out) names as files it writes or removes, as the line writes them."""
    at = external._head_index(tokens)  # noqa: SLF001 - one reading of "which word is the program" for the gate
    if at is None:
        return []
    name = external._program(tokens[at])  # noqa: SLF001
    rest = tokens[at + 1:]
    plain = [word for word in rest if not word.startswith("-")]
    if name in _EVERY:
        return plain
    if name in _FIRST_IS_NOT_A_FILE:
        return plain[1:]
    if name in _LAST:
        for index, word in enumerate(rest):
            if word in ("-t", "--target-directory") and index + 1 < len(rest):
                return [rest[index + 1]]
            if word.startswith("--target-directory="):
                return [word.split("=", 1)[1]]
        return plain[-1:]
    if name == "tee":
        return plain
    if name in ("sed", "perl", "ruby"):
        if any(word == "--in-place" or word.startswith("--in-place=") or (word.startswith("-") and not word.startswith("--") and "i" in word[1:]) for word in rest):
            scripted = any(word in ("-e", "-f", "--expression", "--file") for word in rest)
            return plain if scripted else plain[1:]
        return []
    if name == "dd":
        return [word[3:] for word in rest if word.startswith("of=")]
    if name in _POWERSHELL:
        found: List[str] = []
        positional: List[str] = []
        index = 0
        while index < len(rest):
            word = rest[index]
            low = word.lower()
            if low.startswith("-"):
                key, colon, _value = low.partition(":")
                if key in _POWERSHELL_PATHS:
                    if colon:
                        found.append(word.partition(":")[2])
                    elif index + 1 < len(rest):
                        found.append(rest[index + 1])
                        index += 1
                elif not colon and low not in _SWITCHES and index + 1 < len(rest) and not rest[index + 1].startswith("-"):
                    index += 1  # the value of an option that names no path (`-Value text`)
            else:
                positional.append(word)
            index += 1
        return found or positional[: 2 if name in ("copy-item", "move-item", "cpi", "mi") else 1]
    return []


def outside_write(command: str, cwd: str, root: Path, folder: Optional[Path]) -> str:
    """The first path this command line writes that is not inside `folder` (with no folder, any path is outside); empty when it writes none the gate can see. `/dev/null` and its kin are free."""
    text, _bodies = external._heredocs(external.join_lines(command))  # noqa: SLF001
    base: Optional[str] = cwd or str(root)
    for tokens in gitcmd.split_segments(text):
        tokens = external._setting_words(tokens)  # noqa: SLF001
        if not tokens or all(gitcmd._is_environment(item) for item in tokens):  # noqa: SLF001
            continue
        written = list(external._redirect_targets(tokens))  # noqa: SLF001
        args = external._without_redirects(tokens)  # noqa: SLF001
        at = external._head_index(args)  # noqa: SLF001
        if at is not None and external._program(args[at]) in ("cd", "pushd", "chdir", "set-location", "sl", "push-location"):  # noqa: SLF001
            target = next((word for word in args[at + 1:] if not word.startswith("-")), "")
            base = _absolute(target, base) if target else base
            continue
        written += _paths_written(args)
        for word in written:
            if word.lower() in external._QUIET_FILES:  # noqa: SLF001
                continue
            absolute = _absolute(word, base)
            if absolute is None or folder is None or not _same_or_inside(absolute, folder):
                return word
    return ""


def strict(event: Any, ctx: Any, write_kinds: tuple) -> str:
    """Why the call does not pass while the policy cannot be read, in a few words; empty when it passes."""
    folder = task_folder(ctx)
    if event.tool_kind in write_kinds:
        from core import repo_paths

        for raw in event.paths or []:
            readings = repo_paths.resolve(raw, ctx.root, event.cwd) or [raw]
            if folder is None or any(not _same_or_inside(one, folder) for one in readings):
                return messages.text("gate.policy.unreadable.path", path=raw)
        return ""
    if event.tool_kind != "terminal":
        return ""
    command = event.command or ""
    if gitcmd.classify(command).kind != gitcmd.NONE:
        return messages.text("gate.policy.unreadable.git")
    word = outside_write(command, event.cwd or "", ctx.root, folder)
    return messages.text("gate.policy.unreadable.shell", path=word) if word else ""


def refine(event: Any, ctx: Any, decided: Optional[Decision], file: str, problem: str, write_kinds: tuple) -> Optional[Decision]:
    """The answer for a call the handler judged with the built-in copy: a refusal says what is wrong with the policy; a call that passed or asks is refused when it writes outside the task folder or changes a repository
    (not in an admin session)."""
    try:
        if decided is not None and decided.permission == "deny":
            return replace(decided, reason=f"{decided.reason}\n{messages.text('gate.policy.unreadable.note', file=file, problem=problem)}")
        if ctx.admin:
            return decided
        why = strict(event, ctx, write_kinds)
        if why:
            return Decision(permission="deny", reason=messages.text("gate.policy.unreadable", what=why, file=file, problem=problem), facts={"kind": "policy-unreadable"})
    except Exception:  # noqa: BLE001 - this check failed while the policy is unreadable: a call that may write (a write tool, a git command that writes) does not pass; a read and a local command are left to the other checks
        try:
            writes = event.tool_kind in write_kinds or (event.tool_kind == "terminal" and gitcmd.classify(event.command or "").kind != gitcmd.NONE)
        except Exception:  # noqa: BLE001
            writes = event.tool_kind in write_kinds
        if writes and not ctx.admin:
            return Decision(permission="deny", reason=messages.text("gate.policy.unreadable", what=messages.text("gate.policy.unreadable.failed"), file=file, problem=problem), facts={"kind": "policy-unreadable"})
    return decided
