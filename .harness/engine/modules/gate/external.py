"""External actions (M43-2): the protocol for a call that reaches a system outside this repository (a cloud, a database, a ticket system).

The harness ships no system. A company lists its own under `systems` in `tools.override.json`; each entry says how a call to
it is recognised (`reach`), in which environment it runs (`env`), what the call does (`verbs`) and what the gate decides
(`rules`). Every call becomes one action: `{system, env, verb, target}`. This file only turns a terminal command into actions
and the policy into a decision; the handler applies the decision.

  verb       read, write, destroy, exec
  env        dev, ist, qat, prod, none (a system that has no environments, such as a ticket system)
  decision   allow, task (an open task with an approved plan), outbox, human, deny   (the order is from loosest to strictest)

Two floors, written down here so no company file can lower them by leaving something out:
  - a call to a listed system that no `verbs` rule names is a write;
  - an environment that no `env` rule names is prod.

Only a terminal command (`reach.cli`) is recognised for now. One program may serve several systems (one command line tool can run a ticket board and a cloud):
give each one a `reach.when` pattern, matched against the arguments after the program; the first system that matches owns the call. Like the git rules, this is a net, not a sandbox: a script that
starts the program itself is not seen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from core import schema

from .gitcmd import MAX_DEPTH, SHELLS, SHELL_FLAGS, WRAPPERS, _is_environment, _name, split_segments

ALLOW, TASK, OUTBOX, HUMAN, DENY = "allow", "task", "outbox", "human", "deny"
DECISIONS = (ALLOW, TASK, OUTBOX, HUMAN, DENY)  # from loosest to strictest
READ, WRITE, DESTROY, EXEC = "read", "write", "destroy", "exec"
VERBS = (READ, WRITE, DESTROY, EXEC)
ENVS = ("dev", "ist", "qat", "prod", "none")
PROD = "prod"

# What the gate decides when the company wrote no rule for that verb. Prod is read only.
DEFAULT_RULES = {READ: ALLOW, WRITE: OUTBOX, EXEC: HUMAN, DESTROY: DENY}
PROD_RULES = {READ: ALLOW, WRITE: DENY, EXEC: DENY, DESTROY: DENY}

_NAME = r"^[a-z][a-z0-9_-]*$"
_RULE_SET = {"type": "object", "properties": {verb: {"type": "string", "enum": list(DECISIONS)} for verb in VERBS}, "additionalProperties": False}
_PATTERN_RULE = {"type": "object", "required": ["pattern"], "properties": {"pattern": {"type": "string", "minLength": 1}}}
SYSTEMS_SCHEMA = {
    "type": "object",
    "additionalProperties": {
        "type": "object",
        "required": ["reach"],
        "properties": {
            "reach": {
                "type": "object",
                "properties": {
                    "cli": {"type": ["string", "array"], "items": {"type": "string", "minLength": 1}},
                    "when": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            "env": {"type": "string", "enum": list(ENVS)},
            "default_env": {"type": "string", "enum": list(ENVS)},
            "env_from": {
                "type": "array",
                "items": {"type": "object", "required": ["pattern", "env"], "properties": {"pattern": {"type": "string", "minLength": 1}, "env": {"type": "string", "enum": list(ENVS)}}},
            },
            "verbs": {
                "type": "array",
                "items": {"type": "object", "required": ["pattern", "verb"], "properties": {"pattern": {"type": "string", "minLength": 1}, "verb": {"type": "string", "enum": list(VERBS)}}},
            },
            "target": {"type": "string"},
            "rules": {"type": "object", "additionalProperties": _RULE_SET},
        },
        "additionalProperties": False,
    },
}


def clis(system: Dict[str, Any]) -> List[str]:
    """The program names a system is reached with, in lower case."""
    reach = (system.get("reach") or {}).get("cli") or []
    return [item.lower() for item in ([reach] if isinstance(reach, str) else reach)]


def validate(systems: Any) -> List[str]:
    """What is wrong with the `systems` of a policy: a list of texts, empty when it is fine. Never raises."""
    if systems in (None, {}):
        return []
    errors = schema.validate(systems, SYSTEMS_SCHEMA, "systems")
    if errors:
        return errors
    owner: Dict[str, str] = {}  # a program that has no `when` yet, and who claimed it
    for name, system in systems.items():
        if not re.match(_NAME, name):
            errors.append(f"systems.{name}: a name is lower case letters, digits, - and _, and starts with a letter")
        if not clis(system):
            errors.append(f"systems.{name}.reach: give at least one program in `cli`")
        when = (system.get("reach") or {}).get("when")
        for program in clis(system) if not when else ():
            if program in owner:
                errors.append(f"systems.{name}.reach: {program!r} is also the reach of {owner[program]!r}; give one of them a `when`")
            owner[program] = name
        patterns = [("target", system.get("target") or ""), ("reach.when", when or "")] + [(f"{key}[{index}]", item["pattern"]) for key in ("env_from", "verbs") for index, item in enumerate(system.get(key) or [])]
        for where, pattern in (item for item in patterns if item[1]):
            try:
                re.compile(pattern)
            except re.error as error:
                errors.append(f"systems.{name}.{where}: bad pattern {pattern!r}: {error}")
        if "env" in system and system.get("env_from"):
            errors.append(f"systems.{name}: `env` fixes the environment, so `env_from` is never read; keep one of them")
    return errors


def warnings(systems: Dict[str, Any]) -> List[str]:
    """What is allowed but is likely a mistake. For `tools check`."""
    found: List[str] = []
    for name, system in (systems or {}).items():
        if not system.get("verbs"):
            found.append(f"{name}: no `verbs`, so every call counts as a write")
        if system.get("default_env") not in (None, PROD) and "env" not in system:
            found.append(f"{name}: `default_env` is {system['default_env']}: a call that names no environment is NOT treated as prod")
        for env, rules in (system.get("rules") or {}).items():
            for verb, decision in rules.items():
                if verb != READ and env in (PROD, "*") and decision in (ALLOW, TASK):
                    found.append(f"{name}: rules.{env}.{verb} is {decision}: {env if env == PROD else 'every environment, prod too,'} lets an agent {verb} without a person")
                elif verb == DESTROY and decision == ALLOW:
                    found.append(f"{name}: rules.{env}.destroy is allow")
    return found


@dataclass(frozen=True)
class Action:
    system: str
    env: str
    verb: str
    target: str
    text: str  # the command it came from, one command of the line

    def facts(self) -> Dict[str, str]:
        return {"system": self.system, "env": self.env, "verb": self.verb, "target": self.target}


def environment(system: Dict[str, Any], text: str) -> str:
    if system.get("env"):
        return system["env"]
    for rule in system.get("env_from") or []:
        if re.search(rule["pattern"], text, re.IGNORECASE):
            return rule["env"]
    return system.get("default_env") or PROD


def verb_of(system: Dict[str, Any], text: str) -> str:
    for rule in system.get("verbs") or []:
        if re.search(rule["pattern"], text, re.IGNORECASE):
            return rule["verb"]
    return WRITE


def decide(system: Dict[str, Any], env: str, verb: str) -> str:
    rules = system.get("rules") or {}
    for key in (env, "*"):
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
            found.append(Action(name, environment(system, line), verb_of(system, " ".join(tokens[start + 1:])), target, " ".join(tokens)))
            continue
        shell_at = next((i for i, item in enumerate(tokens) if _name(item) in SHELLS), None)
        if shell_at is not None and depth < MAX_DEPTH:
            for i in range(shell_at + 1, len(tokens)):
                if tokens[i].lower() in SHELL_FLAGS and i + 1 < len(tokens):
                    _scan(" ".join(tokens[i + 1:]) if len(tokens) > i + 2 else tokens[i + 1], systems, programs, depth + 1, found)
                    break


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


def report(systems: Any) -> Dict[str, Any]:
    """For `tools check`: what the policy lists, what the gate decides for each environment, what is wrong, what looks like a mistake."""
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
        "ok": not errors,
        **({"exit_code": 1} if errors else {}),
    }
