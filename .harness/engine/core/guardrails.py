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


# --- a path built at run time (hook speed round 3, red team: `d=.harness; printf x > $d/runtime/x.json`) -------------------------------------------------------------------------------------------------
# A terminal command whose write target is not written out (`$d/...`, `${d}`, `$(...)`, a backtick pair, `%X%`, `$env:X`) is refused when a word of the target names a part of a guardrail folder. The parts are the names the
# runtime folder holds and the folders of the guardrails; a name that is common elsewhere (`bin`, `hooks`, `engine`, `LICENSE`) counts only with the folder before it (`.github/hooks`), as a whole.
SERVICE_PARTS = ("hookserve", "approvals", "state")  # what `.harness/runtime/` holds: the key of the hook service, the approvals, the session state
FRAGMENT_VARIABLE = "harness_integrity_dir"  # the variable that names the folder of the lists the guardrails trust
_SHORT_NAME = re.compile(r"harnes~\d+|hookse~\d+(?:\.\w*)?")  # the 8.3 names of Windows for `.harness` and `hookserve.json`
_PART_SPLIT = re.compile(r"[/\\\x01\x02\x03(),=]")  # `/`, `\`, the marks `shellvars` leaves where a substitution begins and ends, and what PowerShell puts round a path (`(Join-Path $d runtime)`)
_STREAM_NAME = re.compile(r"::\$\w*$")


def dynamic_fragments(policy: Dict[str, Any], admin: bool = False) -> List[Tuple[str, ...]]:
    """The parts of the guardrail folders as tuples of names (lower case) for `dynamic_hit`: one name alone (`runtime`, `hookserve`, `.harness`), or the names of a folder in a row (`.github`, `hooks`). In an admin session
    only what stays closed there; the folders outside the workspace (`.copilot-harness`), the key of the hook service and the programs of the root are closed in every session."""
    found: List[Tuple[str, ...]] = [(HOME_FOLDER,), (FRAGMENT_VARIABLE,)] + [(item,) for item in SERVICE_PARTS] + [(item,) for item in PROGRAM_GUARDRAILS]
    own = [str(item) for item in policy.get("admin_locked_paths", [])]
    for path in admin_locked(policy) if admin else guardrail_paths(policy):
        parts = tuple(item.lower() for item in str(path).replace("\\", "/").split("/") if item and "*" not in item and "?" not in item)
        if not parts or parts[0] in ROOT_LEVEL_GUARDRAILS:
            continue
        if parts[0] == ".harness":
            if not admin:
                found.append((".harness",))
            if len(parts) > 1 and parts[1] == "runtime":
                found.append(("runtime",))
        elif len(parts) > 1 or str(path) in own:
            found.append(parts)
    return list(dict.fromkeys(found))


def _part(text: str) -> str:
    """One name of a path as the file system reads it: lower case, no quote mark, no `::$DATA`, no trailing dots or spaces (`..` is no name)."""
    return _STREAM_NAME.sub("", text.replace('"', "").replace("'", "").lower()).rstrip(" .")


def dynamic_hit(word: str, fragments: Sequence[Tuple[str, ...]]) -> str:
    """The fragment (`runtime`, `.github/hooks`...) that a word of a write target names in one of its parts, or "". The word is cut at `/`, `\\` and the marks a substitution leaves in it (`shellvars`): `$(echo .harness)/runtime/x`
    has the parts `$`, `echo`, `.harness`, `runtime`, `x`. Never raises."""
    try:
        parts = [item for item in (_part(piece) for piece in _PART_SPLIT.split(word)) if item]
        seen = set(parts)
        for fragment in fragments:
            name = fragment[0]
            if name == FRAGMENT_VARIABLE:
                if name in word.lower():
                    return name
            elif len(fragment) == 1:
                if name in seen or (name == "hookserve" and any(item.startswith("hookserve") or _SHORT_NAME.fullmatch(item) for item in parts)) or (name == ".harness" and any(item.startswith("harnes~") and _SHORT_NAME.fullmatch(item) for item in parts)):
                    return name
            elif name in seen:
                for index, item in enumerate(parts):
                    if item == name and tuple(parts[index:index + len(fragment)]) == fragment:
                        return "/".join(fragment)
    except Exception:  # noqa: BLE001 - a word that cannot be read names nothing
        return ""
    return ""


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
