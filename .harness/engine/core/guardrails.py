"""The guardrail files every Level must protect. Core knows them so the gate and promote share one floor."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

from . import procenv

# The files at the root of the workspace that Copilot may start in place of the Python of the person (1.8.53): a hook runs with the workspace root as its folder, and on Windows the search for `python` may look there
# first (`python.exe`, `python.com`), a `.bat` or `.cmd` is found by a shell. Only the root: `src/python/` is an ordinary folder. A write tool is refused at the root; for a terminal command see below.
ROOT_LEVEL_GUARDRAILS = ("python.exe", "python.com", "python.bat", "python.cmd", "python", "python3")
# (hook speed round 3, red team N3) A terminal command that writes to a program of these names is refused in ANY folder, by any path: they have no use in a data workspace, and `mv sub/python.exe .`, `../python.exe`, an
# absolute path or `py''thon.exe` reach the root all the same. `python` and `python3` (no extension) are refused at the root only (`.venv/bin/python` is an ordinary file), by every way a command can say the root:
# bare, `./`, `../`, `$PWD/`, the full path of the workspace, `sub/../`, and `mv sub/python .` (moved into the root).
PROGRAM_GUARDRAILS = ("python.exe", "python.com", "python.bat", "python.cmd")
ROOT_ONLY_GUARDRAILS = ("python", "python3")

# Without these the gate would not protect the harness itself. They are always guarded, even when a policy or an
# override drops them from guardrail_paths; doctor reports that as an error.
CORE_GUARDRAILS = (
    ".github/hooks/**",
    ".harness/policies/**",
    ".harness/engine/**",
    ".harness/bin/**",  # the short commands: a changed launcher could run anything under the name `harness`
    ".harness/registry.json",
    ".harness/runtime/**",
    ".vscode/settings.json",  # it holds chat.useHooks: an agent that turns it off turns every hook off
) + ROOT_LEVEL_GUARDRAILS

# What stays closed in admin mode. The session state and the approvals live in the runtime folder: a session that could
# write it could make itself admin or forge a person's approval.
ADMIN_LOCKED = (".harness/runtime/**",)


def listed(policy: Dict[str, Any]) -> List[str]:
    """What the gate policy lists itself (guardrail_paths and extra_guardrail_paths)."""
    return list(policy.get("guardrail_paths", [])) + list(policy.get("extra_guardrail_paths", []))


def guardrail_paths(policy: Dict[str, Any]) -> List[str]:
    """The core guardrails, then the policy's own. The core ones are always there."""
    return list(dict.fromkeys(list(CORE_GUARDRAILS) + listed(policy)))


def admin_locked(policy: Dict[str, Any]) -> List[str]:
    """The guardrails an admin session still cannot write: the core ones, then the policy's own (`admin_locked_paths`)."""
    return list(dict.fromkeys(list(ADMIN_LOCKED) + list(policy.get("admin_locked_paths", []))))


def missing_core(policy: Dict[str, Any]) -> List[str]:
    have = listed(policy)
    return [item for item in CORE_GUARDRAILS if item not in have]


# What the guardrails trust lies outside the workspace too (1.7.38, C13 FR2 11b): the lists of the guardrail files the person accepted (`integrity.py`) are kept in the person's home. A list an agent can rewrite is a list
# that accepts anything, so the folder is guarded as a guardrail path is: write tools and terminal writes are refused, in admin mode too (`admin off` writes the list itself).
HOME_FOLDER = ".copilot-harness"


def home_folders() -> List[str]:
    """The folders outside the workspace that are guarded: `~/.copilot-harness`, and the folder `HARNESS_INTEGRITY_DIR` names. As absolute paths, `/` as separator. Never raises."""
    found: List[str] = []
    try:
        found.append(str(procenv.home() / HOME_FOLDER))
    except (RuntimeError, KeyError, OSError):
        pass
    custom = (procenv.getenv("HARNESS_INTEGRITY_DIR") or "").strip()
    if custom:
        found.append(custom)
    return [item.replace("\\", "/").rstrip("/") for item in found if item]


# --- how a terminal command says those names (patterns over the text of a command, `\\` already `/`) --------------------------------------------------------------------------------------------------------
# No pattern here nests a quantifier over a quantifier, and the alternatives of the repeated prefix start with different characters (`.`, a letter, `$`, `%`, `/`): a command cannot make them backtrack (red team N1).

NAME_TAIL = r"\.*(?:::\$\w*)?(?![\w.-])"  # Windows reads `python.exe.` and `python.exe::$DATA` as `python.exe`
HERE = r"(?:\$\{?(?:pwd|oldpwd)\}?|\$env:pwd|%cd%|\$\(pwd\)|`pwd`)"  # the folder the command runs in, said by a variable. One way to read each (an alternative that also matched `$pwd` made the repeated prefix go back 2^n ways)


def program_pattern(names: Sequence[str]) -> str:
    """The programs (`python.exe`...) named in any folder: `src/python.exe`, `..\\python.exe`, `python.exe.`, `python.exe::$DATA`."""
    return r"(?<![\w.-])(?:" + "|".join(re.escape(item) for item in sorted(names, key=len, reverse=True)) + ")" + NAME_TAIL


def root_pattern(names: Sequence[str], roots: Sequence[str] = ()) -> str:
    """The names at the root of the workspace, said in any way that is the root: bare, `./x`, `../x`, `a/../x`, `$PWD/x`, and the full path of a root in `roots` (normal form, `/` as separator). `src/python` is not one."""
    prefix = r"\.{1,2}/|\.?[\w-][\w.-]*/\.\./|" + HERE + "/" + "".join("|" + re.escape(item.rstrip("/")) + "/" for item in roots if item.strip("/"))
    return r"(?<![\w./\\-])(?:" + prefix + r")*(?:" + "|".join(re.escape(item) for item in sorted(names, key=len, reverse=True)) + ")" + NAME_TAIL
