"""External actions (M43-2): the protocol for a call that reaches a system outside this repository (a cloud, a database, a ticket system).

The harness ships no system. A company lists its own under `systems`, in the company pack (`tools.company.json`, copied from the knowledge base) or in `tools.override.json`; each entry says how a call to
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
    """The system a call belongs to: the first of those that use the program whose `when` pattern matches the arguments (none: always)."""
    for name in names:
        when = (systems[name].get("reach") or {}).get("when")
        if not when or re.search(when, args, re.IGNORECASE):
            return name
    return None


def _scan(text: str, systems: Dict[str, Any], programs: Dict[str, List[str]], depth: int, found: List[Action]) -> None:
    for tokens in split_segments(text):
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
            found.append(Action(name, environment(system, line), verb or WRITE, target, " ".join(tokens), named=verb is not None))
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


def classify(command: str, systems: Dict[str, Any]) -> List[Tuple[Action, str]]:
    """Each call to a listed system in a command line, with what the policy decides for it. Empty when there is none."""
    if not systems or not command.strip():
        return []
    programs: Dict[str, List[str]] = {}
    for name, system in systems.items():
        for program in clis(system):
            programs.setdefault(program, []).append(name)
    found: List[Action] = []
    _scan(command, systems, programs, 0, found)
    return [(action, decide(systems[action.system], action.env, action.verb)) for action in found]


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
