"""gate.json: schema, validation and the compiled form the handler uses."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Tuple

from core import config, guardrails, messages, procenv, repo_paths, schema
from core.paths import policies_dir
from core.guardrails import CORE_GUARDRAILS, HOME_FOLDER, PROGRAM_GUARDRAILS, ROOT_LEVEL_GUARDRAILS, ROOT_ONLY_GUARDRAILS, admin_locked, guardrail_paths, home_folders, missing_core

POLICY_NAME = "gate"
# Any `.git` folder (in a target repository or anywhere else) in a terminal command, with the spellings Windows treats as the same.
GIT_FOLDER = r"(?<![\w.-])(?:\.git|git~\d+)\.*(?:::\$\w+)?(?:/[^\s\"']*)?(?![\w.-])"
GUARD_PLACEHOLDER = "{guard}"
# Where a command can start: the beginning, or after `;`, `&`, `|`, `(`, a new line. An optional `sudo` may lead.
# Patterns use it so that `grep "rm -rf" file` (rm inside an argument) does not look like a command.
COMMAND_PLACEHOLDER = "{cmd}"
# The `\n` branch starts only at the beginning of a run of white space (`(?<!\s)`, the spaces and tabs before the `\n` are part of the match): started at each `\n` of a run, the old branch `[;&|(\n]\s*` went over the run again from each one
# (8 runs of 1 900 newlines took 40 s in the whole gate). Every rule that follows starts with a letter, so the place where it can go on is the end of the run, the same for both; a test compares the two over the rules of the policy.
COMMAND_START = r"(?:^|[;&|(]\s*|(?<!\s)[^\S\n]*\n\s*)(?:sudo\s+)?"

_RULE_SCHEMA = {
    "type": "object",
    "required": ["pattern", "why"],
    # `why` is one text, or one text per language: {"en": "...", "zh": "..."}.
    "properties": {"pattern": {"type": "string"}, "why": {"type": ["string", "object"], "additionalProperties": {"type": "string"}}},
}
_RULES_SCHEMA = {"type": "array", "items": _RULE_SCHEMA}

POLICY_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "guardrail_paths", "terminal"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "guardrail_paths": {"type": "array", "items": {"type": "string"}},
        "extra_guardrail_paths": {"type": "array", "items": {"type": "string"}},
        "admin_locked_paths": {"type": "array", "items": {"type": "string"}},
        "cli_owned_paths": {"type": "array", "items": {"type": "string"}},
        "terminal": {
            "type": "object",
            "required": ["guardrail_write", "deny", "ask"],
            "properties": {"guardrail_write": _RULES_SCHEMA, "deny": _RULES_SCHEMA, "ask": _RULES_SCHEMA},
        },
        "git": {"type": "object", "properties": {"approval_minutes": {"type": "integer", "minimum": 1}}},
        "circuit_breaker": {
            "type": "object",
            "properties": {"repeat_limit": {"type": "integer", "minimum": 0}},
        },
    },
}


def expand(pattern: str, guard: str) -> str:
    return pattern.replace(COMMAND_PLACEHOLDER, COMMAND_START).replace(GUARD_PLACEHOLDER, guard)


def validate_policy(policy: Dict[str, Any], floor: bool = True) -> None:
    """`floor=False` is for the gate at run time: a missing core guardrail is not fatal there, the gate adds it back."""
    schema.check(policy, POLICY_SCHEMA, POLICY_NAME + ".json")
    patterns = guardrail_paths(policy)
    for core in missing_core(policy) if floor else ():
        raise ValueError(
            f"Invalid {POLICY_NAME}.json: guardrail_paths must keep {core!r} (core guardrails cannot be removed, also not by an override; use 'guardrail_paths+' to add more)"
        )
    if any(not item.strip() for item in patterns + list(policy.get("cli_owned_paths", [])) + list(policy.get("admin_locked_paths", []))):
        raise ValueError(f"Invalid {POLICY_NAME}.json: empty guardrail path")
    for group in ("guardrail_write", "deny", "ask"):
        for rule in policy["terminal"][group]:
            if group == "guardrail_write" and GUARD_PLACEHOLDER not in rule["pattern"]:
                raise ValueError(f"Invalid {POLICY_NAME}.json: a guardrail_write pattern must contain {GUARD_PLACEHOLDER}")
            try:
                re.compile(expand(rule["pattern"], "x"))
            except re.error as error:
                raise ValueError(f"Invalid {POLICY_NAME}.json: bad pattern {rule['pattern']!r}: {error}") from error


def diagnose(root: Path, error: BaseException) -> Tuple[str, str]:
    """`(file, what is wrong)` for a gate policy that cannot be read (1.7.38, C13 F2c): the first of its three files (`gate.json`, the company's, the person's) that is missing (the first one), not valid JSON or not an object; else
    the first layer that makes the merged policy one the schema refuses; else `gate.json` with the fault as it was raised. For the gate, which runs on its built-in copy meanwhile, and for `harness doctor`. Never raises."""
    try:
        merged: Any = {}
        seen: List[Tuple[str, Any]] = []
        for suffix in ("", ".company", ".override"):
            name = f"{POLICY_NAME}{suffix}.json"
            path = policies_dir(root) / name
            if not path.is_file():
                if not suffix:
                    return name, "the file is missing"
                continue
            try:
                data = config.read_json(path)
            except (OSError, ValueError) as problem:
                return name, " ".join(str(problem).split())[:200]
            if not isinstance(data, dict):
                return name, "the file is not an object"
            seen.append((name, data))
        for name, data in seen:
            try:
                merged = config.deep_merge(merged, data)
                validate_policy(merged, floor=False)
            except Exception as problem:  # noqa: BLE001 - the layer that made the policy wrong
                return name, " ".join(str(problem).split())[:200]
    except Exception:  # noqa: BLE001 - a name for the text only
        pass
    return f"{POLICY_NAME}.json", " ".join(str(error).split())[:200]


def guard_pattern(paths: List[str], roots: Optional[List[str]] = None) -> str:
    """The guardrail paths as one pattern over a terminal command (`{guard}` of a rule). The names that are files at the root (`ROOT_LEVEL_GUARDRAILS`) are found as `core.guardrails` says: the programs (`python.exe`, ...)
    in any folder, `python` and `python3` only where the root is meant (`./`, `../`, `$PWD/`, the full path of the workspace: `roots`), so a folder `src/python` is not one."""
    programs = [item for item in paths if item in PROGRAM_GUARDRAILS]
    rooted = [item for item in paths if item in ROOT_ONLY_GUARDRAILS]
    found = repo_paths.command_regex([item for item in paths if item not in ROOT_LEVEL_GUARDRAILS]).pattern
    more = ([guardrails.program_pattern(programs)] if programs else []) + ([guardrails.root_pattern(rooted, roots or [])] if rooted else [])
    return "(?:" + "|".join([found] + more) + ")" if more else found


ROOT_MOVE_WHY = {"en": "it moves, copies or links a file named like a program of Python into the root of the workspace", "zh": "它会把名字像 Python 程序的文件移到、复制或链接到工作区根目录"}


def root_texts(root: Optional[Path]) -> List[str]:
    """The root of the workspace as a command says it (normal form: `/` as separator), as given and as resolved. Nothing when the root is not known."""
    found: List[str] = []
    if root is None:
        return found
    spelled = [str(root), procenv.realpath(str(root))]
    for text in list(spelled):
        if text.startswith(("/private/var/", "/private/tmp/", "/private/etc/")):
            spelled.append(text[len("/private"):])  # macOS: `/var` is a link to `/private/var`; a command may say either
    for text in spelled:
        try:
            item = repo_paths.normal(text)
        except (OSError, ValueError):
            continue
        if item not in found and item.strip("/."):
            found.append(item)
    return found


def root_move_patterns(paths: List[str], roots: Optional[List[str]] = None) -> List[str]:
    """Patterns over a terminal command that moves, copies or links a file named `python` or `python3` (from any folder) INTO the root: `mv sub/python .`, `cp x/python3 ./`, `ln -s /opt/x/python $PWD`. The name is
    then written in the root though the command never says it there. Where the folder is meant by `.` the command's own folder is taken for the root: a net (no cwd is known)."""
    rooted = [item for item in paths if item in ROOT_ONLY_GUARDRAILS]
    if not rooted:
        return []
    names = "|".join(re.escape(item) for item in sorted(rooted, key=len, reverse=True))
    here = r"(?:\.{1,2}/?|" + guardrails.HERE + "/?" + "".join("|" + re.escape(item.rstrip("/")) + "/?" for item in (roots or []) if item.strip("/")) + ")"
    return [COMMAND_PLACEHOLDER + r"(?:cp|mv|ln|install|rsync|ditto|copy|move|xcopy|copy-item|move-item|robocopy)\b[^;&|\n]*?(?<![\w.-])(?:" + names + r")" + guardrails.NAME_TAIL + r"[\"']?\s+[\"']?" + here + r"[\"']?(?=\s|$|[;&|])"]


class Compiled:
    """The policy with its patterns compiled. Built once per hook call."""

    def __init__(self, policy: Dict[str, Any], repos: Optional[List[Tuple[str, Path, List[str]]]] = None, admin: bool = False, root: Optional[Path] = None) -> None:
        """`repos`: (name, path, refused_paths) of each target repository. Without them only the `.git` floor applies.

        `admin`: the session is in admin mode. Only the guardrails that stay closed for an admin count then.

        `root`: the workspace. A command that names `python` by the full path of the root (`/work/x/python`) is the root's file (red team N3); without it only the relative ways are known.
        """
        self.paths = admin_locked(policy) if admin else guardrail_paths(policy)
        self.path_regexes: List[Tuple[str, Pattern[str]]] = [(item, repo_paths.glob_regex(item)) for item in self.paths]
        self.home = home_folders()  # (1.7.38, C13 FR2 11b) the folders outside the workspace that hold what the guardrails trust: closed in admin mode too
        roots = root_texts(root)
        guard = guard_pattern(self.paths + [f"{HOME_FOLDER}/**"] + self.home, roots)  # a command names the folder as `~/.copilot-harness/...`, `$HOME/...`, or by its full path
        self.guard_writes = [
            (re.compile(expand(rule["pattern"], guard), re.IGNORECASE), messages.pick(rule["why"]))
            for rule in policy["terminal"]["guardrail_write"]
            if not rule.get("inline")  # the code of an inline script is read by `scriptcheck.py` for guardrail paths: it writes to one only when the target of a write is one (1.7.38, C13 FR2 3)
        ] + [(re.compile(expand(pattern, ""), re.IGNORECASE), messages.pick(ROOT_MOVE_WHY)) for pattern in root_move_patterns(self.paths, roots)]
        # Files only the CLI writes (a task's `.task/`, `REVIEW/`, `SNAPSHOT/`, the reports). Same write patterns as for guardrail files.
        self.owned = list(policy.get("cli_owned_paths", []))
        self.owned_regexes: List[Tuple[str, Pattern[str]]] = [(item, repo_paths.glob_regex(item)) for item in self.owned]
        owned_guard = repo_paths.command_regex(self.owned).pattern if self.owned else ""
        self.owned_writes = [
            (re.compile(expand(rule["pattern"], owned_guard), re.IGNORECASE), messages.pick(rule["why"]))
            for rule in policy["terminal"]["guardrail_write"]
        ] if self.owned else []
        self.deny = [(re.compile(expand(rule["pattern"], ""), re.IGNORECASE), messages.pick(rule["why"])) for rule in policy["terminal"]["deny"]]
        self.ask = [(re.compile(expand(rule["pattern"], ""), re.IGNORECASE), messages.pick(rule["why"])) for rule in policy["terminal"]["ask"]]
        # A `.git` folder is never written by an agent (A4); a target repository's refused_paths are not written either.
        self.repos: List[Tuple[str, Path, List[Tuple[str, Pattern[str]]]]] = [
            (name, path, [(item, repo_paths.glob_regex(item)) for item in refused if item.strip() != ".git/**"])
            for name, path, refused in (repos or [])
        ]
        absolute = [
            f"{repo_paths.normal(str(path))}/{item}"
            for _name, path, refused in (repos or []) for item in refused if item.strip() != ".git/**"
        ]
        target_guard = "(?:" + GIT_FOLDER + (("|" + repo_paths.command_regex(absolute).pattern) if absolute else "") + ")"
        self.target_writes = [
            (re.compile(expand(rule["pattern"], target_guard), re.IGNORECASE), messages.pick(rule["why"]))
            for rule in policy["terminal"]["guardrail_write"]
        ]
        # The working tree of a target repository is written by promote only (M7-4). A git command is not judged here:
        # git writes have their own rule (approve-command).
        trees = [f"{repo_paths.normal(str(path))}/**" for _name, path, _refused in (repos or [])]
        tree_guard = repo_paths.command_regex(trees).pattern if trees else ""
        self.tree_writes = [
            (re.compile(expand(rule["pattern"], tree_guard), re.IGNORECASE), messages.pick(rule["why"]))
            for rule in policy["terminal"]["guardrail_write"] if not rule["pattern"].startswith(COMMAND_PLACEHOLDER + "git")
        ] if trees else []

    def home_match(self, absolute: str) -> str:
        """The guarded folder outside the workspace an absolute path (normal form) lies in, or an empty string."""
        for folder in self.home:
            if repo_paths.inside(absolute, Path(folder)):
                return folder
        return ""

    def guardrail_match(self, relative: str) -> str:
        """The guardrail pattern a repo-relative path falls under, or an empty string. The path is read as written and as Windows reads it: no `::$DATA` stream, no trailing dots or spaces in a name (`python.exe.` is `python.exe`)."""
        spellings = [relative]
        windows = "/".join(repo_paths.windows_name(part) for part in relative.split("/"))
        if windows != relative:
            spellings.append(windows)
        for spelled in spellings:
            for pattern, regex in self.path_regexes:
                if regex.match(spelled):
                    return pattern
        return ""

    def owned_match(self, relative: str) -> str:
        """The `cli_owned_paths` pattern a repo-relative path falls under, or an empty string."""
        for pattern, regex in self.owned_regexes:
            if regex.match(relative):
                return pattern
        return ""

    def repo_of(self, absolute: str) -> Optional[Tuple[str, str]]:
        """`(repo name, repo-relative path)` when an absolute path is inside the working tree of a target repository."""
        for name, path, _patterns in self.repos:
            for relative in repo_paths.inside(absolute, path):
                return name, relative
        return None

    def refused_match(self, absolute: str) -> Optional[Tuple[str, str, str]]:
        """`(repo name, repo-relative path, pattern)` when an absolute path falls under a target repository's refused_paths."""
        for name, path, patterns in self.repos:
            for relative in repo_paths.inside(absolute, path):
                for pattern, regex in patterns:
                    if regex.match(relative):
                        return name, relative, pattern
        return None
