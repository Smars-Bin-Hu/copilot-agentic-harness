"""External actions (M43-2): the protocol for a call that reaches a system outside this repository (a cloud, a database, a ticket system).

The harness ships no system. A company lists its own under `systems`, in a tool pack (`rules.json`, copied from the knowledge base) or in `tools.override.json`; each entry says how a call to
it is recognised (`reach`), in which environment it runs (`env`), what the call does (`verbs`) and what the gate decides
(`rules`). Every call becomes one action: `{system, env, verb, target}`. This file only turns a terminal command into actions
and the policy into a decision; the handler applies the decision.

  verb       read, write, destroy, exec
  env        dev, ist, qat, prod, none (a system that has no environments, such as a ticket system)
  decision   allow, task (an open task with an approved plan), outbox, human, deny   (the order is from loosest to strictest)

Two floors, written down here so no company file can lower them by leaving something out:
  - a call to a listed system that no `verbs` rule names is a write;
  - an environment that no `env` rule names is prod.

A system may say what it needs before a call can reach it (`needs`, 1.7.1): `probe`, a read-only command that answers only when the
session has the right identity (a database that takes the identity of the process: `SELECT SUSER_SNAME()`), `expect`, a pattern its
output must match, and `launch`, the sentence for the person when it does not (how to start VS Code so that the identity is there).
The harness runs the probe for `tools check`, `doctor` and the board's Enter screen; it never stores a password or an identity.

Only a terminal command (`reach.cli`) is recognised for now. One program may serve several systems (one command line tool can run a ticket board and a cloud):
give each one a `reach.when` pattern, matched against the arguments after the program; the first system that matches owns the call. Like the git rules, this is a net, not a sandbox: a script that
starts the program itself is not seen.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.systems import (  # noqa: F401 - the names the handler, doctor and the tests use from here
    ALLOW, DECISIONS, DEFAULT_RULES, DENY, DESTROY, ENVS, EXEC, HUMAN, OUTBOX, PROBE_SECONDS, PROD, PROD_RULES, READ, TASK, VERBS, WRITE, clis, reach, run_probe, validate, warnings,
)

from .gitcmd import MAX_DEPTH, SHELLS, SHELL_FLAGS, WRAPPERS, _is_environment, _name, split_segments


@dataclass(frozen=True)
class Action:
    system: str
    env: str
    verb: str
    target: str
    text: str  # the command it came from, one command of the line
    named: bool = True  # False: no verbs rule matched, the verb is the write floor (a query in a shell variable or a file the gate cannot read)
    call: str = ""  # this one command from the program on (the program as its plain name): what a system's `item` pattern is matched against (1.7.21)
    unseen: bool = False  # a segment the gate cannot read (a program in a variable it cannot expand): held, never guessed (1.7.21)

    def facts(self) -> Dict[str, Any]:
        facts: Dict[str, Any] = {"system": self.system, "env": self.env, "verb": self.verb, "target": self.target}
        if not self.named:
            facts["named"] = False  # said only when it matters: the log and the draft stay as they were for a named verb
        return facts


def environment(system: Dict[str, Any], text: str) -> str:
    if system.get("env"):
        return system["env"]
    for rule in system.get("env_from") or []:
        if re.search(rule["pattern"], text, re.IGNORECASE):
            return rule["env"]
    return system.get("default_env") or PROD


def verb_named(system: Dict[str, Any], text: str) -> Optional[str]:
    """The verb of the first `verbs` rule that matches; None when none does (the gate then counts a write: the floor)."""
    for rule in system.get("verbs") or []:
        if re.search(rule["pattern"], text, re.IGNORECASE):
            return rule["verb"]
    return None


def verb_of(system: Dict[str, Any], text: str) -> str:
    return verb_named(system, text) or WRITE


def decide(system: Dict[str, Any], env: str, verb: str) -> str:
    rules = system.get("rules") or {}
    for key in ((env,) if env == PROD else (env, "*")):  # prod takes only a rule written for prod by name: a catch-all never loosens it (1.7.10)
        found = (rules.get(key) or {}).get(verb)
        if found:
            return found
    return (PROD_RULES if env == PROD else DEFAULT_RULES)[verb]


def _program(token: str) -> str:
    name = _name(token)
    for suffix in (".cmd", ".bat"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _start(tokens: List[str], programs: Dict[str, List[str]]) -> Optional[int]:
    """Index of the program of a listed system, when only wrappers, environment settings, options and numbers stand before it."""
    for index, token in enumerate(tokens):
        if _program(token) in programs:
            return index
        if not (_name(token) in WRAPPERS or _is_environment(token) or token.startswith("-") or token.isdigit()):
            return None
    return None


def _owner(systems: Dict[str, Any], names: List[str], args: str) -> Optional[str]:
    """The system a call belongs to, of those that use the program: the one whose `when` pattern matches the most of the arguments (1.7.10: two servers on
    one host, told apart by the port, both match `-S host`; the one that also matches the port wins); on a tie the first; one with no `when` only when no other matches."""
    best, best_len, fallback = None, -1, None
    for name in names:
        when = (systems[name].get("reach") or {}).get("when")
        if not when:
            fallback = fallback or name
            continue
        found = re.search(when, args, re.IGNORECASE)
        if found and len(found.group(0)) > best_len:
            best, best_len = name, len(found.group(0))
    return best or fallback


INTERPRETERS = frozenset("python python3 py node bash sh zsh dash pwsh powershell ruby perl".split())
_SCRIPT_EXTENSIONS = (".py", ".js", ".mjs", ".ps1", ".sh", ".rb", ".pl", ".cmd", ".bat")
_VALUE_OPTIONS = {"-m": 1, "-w": 1, "-x": 1, "-file": 1, "-f": 1, "-r": 1, "-p": 1}
MAX_SCRIPT_BYTES = 200 * 1024
_REDIRECT = re.compile(r"^\d*(?:>>?|<)$")  # a redirection operator alone: its file is the next word
_REDIRECT_WITH_FILE = re.compile(r"^\d*(?:>>?|<)\S")  # `>f`, `2>/dev/null`, `<f`
_UNREADABLE = (
    re.compile(r"\b(?:ba|z|da)?sh\b[^|;&\n]*<<", re.IGNORECASE),  # a shell given a here-string or a here-document
    re.compile(r"\b(?:pwsh|powershell)\b[^|;&\n]*<<", re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|(])(?:source|\.)\s+<\(", re.IGNORECASE),  # source <( ... )
    re.compile(r"\|\s*(?:sudo\s+|env\s+)?(?:ba|z|da)?sh\b(?!\s+\S*[^\s|;&])", re.IGNORECASE),  # ... | bash
    re.compile(r"\|\s*(?:pwsh|powershell)\b(?!\s+\S)", re.IGNORECASE),
    re.compile(r"\|\s*(?:ba|z|da)?sh\s+(?:-s\b|-)", re.IGNORECASE),
    re.compile(r"\b(?:iex|invoke-expression|start-process|invoke-command|icm)\b", re.IGNORECASE),
    re.compile(r"\b(?:python[\d.]*|py|node|ruby|perl)\b(?:\s+-\S+)*?\s+-(?:c|e)\b", re.IGNORECASE),  # python -c, node -e
    re.compile(r"\|\s*(?:python[\d.]*|py|node|ruby|perl)\b(?!\s+[^-\s|;&])", re.IGNORECASE),  # ... | python
)


def _plain_name(token: str) -> str:
    name = _name(token)
    for suffix in _SCRIPT_EXTENSIONS:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _is_interpreter(token: str) -> bool:
    name = _name(token)
    return name in INTERPRETERS or bool(re.fullmatch(r"python\d(?:\.\d+)?", name))


def _script_index(tokens: List[str], at: int) -> Optional[int]:
    """Index of the script (or module) an interpreter at `tokens[at]` is given, or None (no script: `-c`, a pipe, a prompt)."""
    index = at + 1
    while index < len(tokens):
        word = tokens[index]
        low = word.lower()
        if low in ("-c", "-e", "-command", "/c", "-encodedcommand"):
            return None
        if low in _VALUE_OPTIONS:
            index += 2 if low != "-m" else 1
            if low == "-m":
                return index if index < len(tokens) else None
            continue
        if word.startswith("-") and word != "-":
            index += 1
            continue
        return index if word != "-" else None
    return None


def _through_interpreter(tokens: List[str], programs: Dict[str, List[str]]) -> List[str]:
    """`python3 <pack>/bin/ado comment ...`, `bash tools/ado ...`, `node ado.js ...`: the script is the call when its file name is the program of a listed system (1.7.23)."""
    for at, token in enumerate(tokens):
        if _is_interpreter(token):
            index = _script_index(tokens, at)
            if index is not None and _plain_name(tokens[index]) in programs:
                return tokens[:0] + [_plain_name(tokens[index])] + tokens[index + 1:]
            return tokens
        if not (_name(token) in WRAPPERS or _is_environment(token) or token.startswith("-") or token.isdigit()):
            return tokens
    return tokens


def _without_redirects(tokens: List[str]) -> List[str]:
    """The arguments of a command without its redirections (`2>&1`, `> f`, `2>/dev/null`, `>> f`, `< f`): they are not words of the call (1.7.23)."""
    out: List[str] = []
    skip = False
    for token in tokens:
        if skip:
            skip = False
            continue
        if _REDIRECT.match(token):
            skip = True
            continue
        if _REDIRECT_WITH_FILE.match(token):
            continue
        out.append(token)
    return out


def _unescaped(tokens: List[str]) -> List[str]:
    """The words with a lone backslash in them read as the shell does: `a\\do` is `ado`. A Windows path (a drive, `.\\`, two backslashes) is left."""
    out = []
    for token in tokens:
        if "\\" in token and not (re.match(r"^(?:[A-Za-z]:|\.{1,2}\\|\\\\)", token) or token.count("\\") > 1):
            token = re.sub(r"\\(.)", r"\1", token)
        out.append(token)
    return out


def _word_in(programs: List[str], text: str) -> str:
    """The first program (a word, not a part of one) that the text names, or an empty string."""
    for program in programs:
        if re.search(r"(?<![\w-])" + re.escape(program) + r"(?![\w-])", text, re.IGNORECASE):
            return program
    return ""


def _script_text(command: str, root: Optional[Any], cwd: str) -> str:
    """The text of every script file an interpreter in the line runs (in the repository, up to 200 KB); not the harness's own engine and tests."""
    if root is None:
        return ""
    found: List[str] = []
    for tokens in split_segments(command):
        for at, token in enumerate(tokens):
            if not _is_interpreter(token):
                if _name(token) in WRAPPERS or _is_environment(token) or token.startswith("-") or token.isdigit():
                    continue
                break
            index = _script_index(tokens, at)
            if index is None or tokens[index - 1].lower() == "-m":
                break
            for base in [cwd, str(root)]:
                if not base:
                    continue
                path = os.path.normpath(os.path.join(base, os.path.expanduser(tokens[index])))
                try:
                    inside = os.path.commonpath([os.path.realpath(path), os.path.realpath(str(root))]) == os.path.realpath(str(root))
                except ValueError:
                    inside = False
                relative = os.path.relpath(os.path.realpath(path), os.path.realpath(str(root))).replace("\\", "/") if inside else ""
                if not inside or relative.startswith((".harness/engine/", ".harness/tests/")):
                    continue
                try:
                    if os.path.isfile(path) and os.path.getsize(path) <= MAX_SCRIPT_BYTES:
                        with open(path, encoding="utf-8", errors="replace") as handle:
                            found.append(handle.read())
                        break
                except OSError:
                    continue
            break
    return "\n".join(found)


def unreadable(command: str, programs: Dict[str, List[str]], root: Optional[Any] = None, cwd: str = "") -> str:
    """The program of an outside system that this line names as a word when the gate cannot read what the line will run (1.7.23): a string piped into a shell, a here-string,
    `source <(...)`, `python -c`, `node -e`, `iex`, `Start-Process`, `xargs` with a placeholder, a script file. An empty string when the line is readable or names no program."""
    if not programs:
        return ""
    names = list(programs)
    hidden = any(pattern.search(command) for pattern in _UNREADABLE)
    scripted = False
    for tokens in split_segments(command):
        if any(_name(item) == "xargs" for item in tokens[:3]) and _start(tokens, programs) is None:
            hidden = True
        for at, token in enumerate(tokens):
            if _is_interpreter(token):
                index = _script_index(tokens, at)
                if index is not None and tokens[index - 1].lower() != "-m" and _plain_name(tokens[index]) not in programs:
                    scripted = True
                break
            if not (_name(token) in WRAPPERS or _is_environment(token) or token.startswith("-") or token.isdigit()):
                break
    if scripted:
        found = _word_in(names, command) or _word_in(names, _script_text(command, root, cwd))
        if found:
            return found
    return _word_in(names, command) if hidden else ""


_VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
_DECLARE = frozenset(["export", "declare", "typeset", "local", "readonly"])


def _expand(tokens: List[str], variables: Dict[str, str]) -> List[str]:
    """The simple shell variables of this command line that were set in it (`A=ado; $A item 1`, `export X=...`), put in. What is not known stays as it is."""
    out: List[str] = []
    for token in tokens:
        whole = _VARIABLE.fullmatch(token)
        value = _VARIABLE.sub(lambda m: variables.get(m.group(1) or m.group(2), m.group(0)), token)
        if whole and value != token:
            out.extend(value.split())  # a variable that stands for a whole word may stand for a command and its words
        else:
            out.append(value)
    return out


def _head(tokens: List[str]) -> Optional[str]:
    """The word that names the program of a segment: the first one that is not a wrapper, an environment setting, an option or a number."""
    for token in tokens:
        if not (_name(token) in WRAPPERS or _is_environment(token) or token.startswith("-") or token.isdigit()):
            return token
    return None


def _substitutions(token: str) -> List[str]:
    """The commands inside `$( ... )` and `` ` ... ` `` of one word: a double quote does not hide them from the shell (1.7.21)."""
    found: List[str] = []
    index = token.find("$(")
    while index != -1:
        depth, end = 1, index + 2
        while end < len(token) and depth:
            depth += {"(": 1, ")": -1}.get(token[end], 0)
            end += 1
        found.append(token[index + 2: end - 1 if depth == 0 else end])
        index = token.find("$(", end)
    if "`" in token:
        parts = token.split("`")
        found.extend(parts[1::2])
    return found


def shlex_quote(token: str) -> str:
    return "'" + token.replace("'", "'\"'\"'") + "'" if re.search(r"[\s;&|()$`<>\"'\\]", token) or not token else token


def _scan(text: str, systems: Dict[str, Any], programs: Dict[str, List[str]], depth: int, found: List[Action], variables: Optional[Dict[str, str]] = None) -> None:
    variables = {} if variables is None else variables
    for tokens in split_segments(text):
        if tokens and tokens[0] in _DECLARE:
            tokens = tokens[1:]
        if tokens and all(_is_environment(item) for item in tokens):  # `A=ado`, `export A=ado`: remembered, not a call
            for item in tokens:
                key, _, value = item.partition("=")
                variables[key] = value
            continue
        tokens = _without_redirects(_expand(tokens, variables))
        if not tokens:
            continue
        plain = _unescaped(tokens)
        if plain != tokens:
            _scan(" ".join(shlex_quote(item) for item in plain), systems, programs, depth + 1, found, variables) if depth < MAX_DEPTH else None
        tokens = _through_interpreter(tokens, programs)
        if depth < MAX_DEPTH:
            for token in tokens:
                for inner in (_substitutions(token) if ("$(" in token or "`" in token) else []):
                    _scan(inner, systems, programs, depth + 1, found, variables)
        start = _start(tokens, programs)
        name = _owner(systems, programs[_program(tokens[start])], " ".join(tokens[start + 1:])) if start is not None else None
        if name is not None:
            system = systems[name]
            line = " ".join(tokens)  # the environment settings in front of the program say something too
            target = ""
            if system.get("target"):
                match = re.search(system["target"], line, re.IGNORECASE)
                target = (match.group(1) if match and match.groups() else match.group(0) if match else "")[:120]
            verb = verb_named(system, " ".join(tokens[start + 1:]))
            found.append(Action(name, environment(system, line), verb or WRITE, target, " ".join(tokens), named=verb is not None, call=" ".join([_program(tokens[start])] + tokens[start + 1:])))
            continue
        if _evaluated(tokens) is not None and depth < MAX_DEPTH:  # `eval "<command>"`: the string is the call
            _scan(_evaluated(tokens) or "", systems, programs, depth + 1, found, variables)
            continue
        head = _head(tokens)
        if head is not None and (head.startswith("$") or "`" in head):  # a program the gate cannot read the name of: it may be a listed one
            found.append(Action("", "none", WRITE, "", " ".join(tokens), named=False, call=" ".join(tokens), unseen=True))
            continue
        waited = _wait_run(tokens)
        if waited is not None and depth < MAX_DEPTH:  # `harness wait --run "<command>"` (1.7.5): the command inside is the call
            _scan(waited, systems, programs, depth + 1, found)
            continue
        wrapped = as_run(tokens)
        if wrapped is not None and depth < MAX_DEPTH:  # `harness as <alias> -- <command>` (1.7.10): the command inside is the call
            _scan(wrapped[1], systems, programs, depth + 1, found)
            continue
        shell_at = next((i for i, item in enumerate(tokens) if _name(item) in SHELLS), None)
        if shell_at is not None and depth < MAX_DEPTH:
            for i in range(shell_at + 1, len(tokens)):
                if tokens[i].lower() in SHELL_FLAGS and i + 1 < len(tokens):
                    _scan(" ".join(tokens[i + 1:]) if len(tokens) > i + 2 else tokens[i + 1], systems, programs, depth + 1, found)
                    break


def _evaluated(tokens: List[str]) -> Optional[str]:
    head = _head(tokens)
    if head is None or _name(head) != "eval":
        return None
    return " ".join(tokens[tokens.index(head) + 1:])


def as_run(tokens: List[str]) -> Optional[Tuple[str, str]]:
    """(alias, the command) when this segment is `harness as <alias> -- <command>` (1.7.10); else None."""
    head = [index for index, token in enumerate(tokens) if _program(token) == "harness" or _name(token) == "cli.py"]
    if not head or len(tokens) < head[0] + 5 or tokens[head[0] + 1].lower() != "as" or tokens[head[0] + 3] != "--":
        return None
    return tokens[head[0] + 2], " ".join(tokens[head[0] + 4:])


def _wait_run(tokens: List[str]) -> Optional[str]:
    """The command `harness wait --run` is given, when this segment is such a call (`harness`, `harness.cmd` or `cli.py`, then `wait`); else None."""
    head = [index for index, token in enumerate(tokens) if _program(token) == "harness" or _name(token) == "cli.py"]
    if not head or len(tokens) <= head[0] + 1 or tokens[head[0] + 1].lower() != "wait":
        return None
    for index, token in enumerate(tokens):
        if token == "--run" and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith("--run="):
            return token[len("--run="):]
    return None


def classify(command: str, systems: Dict[str, Any], unseen: bool = False, root: Optional[Any] = None, cwd: str = "") -> List[Tuple[Action, str]]:
    """Each call to a listed system in a command line, with what the policy decides for it. Empty when there is none.
    With `unseen` (the gate), a segment whose program the gate cannot read comes too, as a held call of no system (1.7.21)."""
    if not systems or not command.strip():
        return []
    programs: Dict[str, List[str]] = {}
    for name, system in systems.items():
        for program in clis(system):
            programs.setdefault(program, []).append(name)
    found: List[Action] = []
    _scan(command, systems, programs, 0, found)
    if unseen:
        hidden = unreadable(command, programs, root, cwd)
        if hidden:  # the gate cannot read what runs, and the line names an outside program: held (1.7.23)
            found.append(Action("", "none", WRITE, hidden, command, named=False, call=command, unseen=True))
    return [(action, HUMAN if action.unseen else decide(systems[action.system], action.env, action.verb)) for action in found if unseen or not action.unseen]


def strictest(judged: List[Tuple[Action, str]]) -> Optional[Tuple[Action, str]]:
    """The call that decides the whole line: the strictest decision, the first of them."""
    best: Optional[Tuple[Action, str]] = None
    for item in judged:
        if best is None or DECISIONS.index(item[1]) > DECISIONS.index(best[1]):
            best = item
    return best


def report(systems: Any, run: Optional[Callable[[str], Tuple[Optional[int], str]]] = None) -> Dict[str, Any]:
    """For `tools check`: what the policy lists, what the gate decides for each environment, what is wrong, what looks like a mistake; with `run`, the probes too (`reach`)."""
    errors = validate(systems)
    listed: List[Dict[str, Any]] = []
    if not errors:
        for name, system in (systems or {}).items():
            fixed = system.get("env")
            effective = {
                env: " ".join(f"{verb}={decide(system, env, verb)}" for verb in VERBS)
                for env in ([fixed] if fixed else [item for item in ENVS if item != "none"])
            }
            listed.append({"system": name, "cli": clis(system), "verbs_listed": len(system.get("verbs") or []), "decides": effective})
    return {
        "systems": listed,
        "errors": errors,
        "warnings": [] if errors else warnings(systems or {}),
        **({"reach": reach(systems or {}, run)} if run is not None and not errors else {}),
        "ok": not errors,
        **({"exit_code": 1} if errors else {}),
    }
