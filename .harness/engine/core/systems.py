"""The outside systems a company lists (`systems` in tools.json, its company and override layers): what the list may hold, what is wrong with it,
and whether a system is reachable from here (its `needs.probe`). The gate's own part, turning a command into actions, is `modules/gate/external.py`;
this file holds what `company.py`, the board's Enter screen and `doctor` need without a module.

  verb       read, write, destroy, exec
  env        dev, ist, qat, prod, none (a system that has no environments, such as a ticket system)
  decision   allow, task (an open task with an approved plan), outbox, human, deny   (the order is from loosest to strictest)
  needs      probe (a read-only command that answers only with the right identity), expect (a pattern on its output), launch (what to tell the person)

The probe is run as a person would type it, with a short deadline; its output is never kept or logged (it could name the identity).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import schema

ALLOW, TASK, OUTBOX, HUMAN, DENY = "allow", "task", "outbox", "human", "deny"
DECISIONS = (ALLOW, TASK, OUTBOX, HUMAN, DENY)  # from loosest to strictest
READ, WRITE, DESTROY, EXEC = "read", "write", "destroy", "exec"
VERBS = (READ, WRITE, DESTROY, EXEC)
ENVS = ("dev", "ist", "qat", "prod", "none")
PROD = "prod"
PROBE_SECONDS = 5  # a probe that takes longer than this is "not reachable": the Enter screen and doctor must not hang on it
PROBE_OUTPUT = 4000  # what is kept of a probe's output, for the pattern

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
            "needs": {
                "type": "object",
                "required": ["probe"],
                "properties": {"probe": {"type": "string", "minLength": 1}, "expect": {"type": "string"}, "launch": {"type": "string"}},
                "additionalProperties": False,
            },
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
        patterns = [("target", system.get("target") or ""), ("reach.when", when or ""), ("needs.expect", (system.get("needs") or {}).get("expect") or "")] + [(f"{key}[{index}]", item["pattern"]) for key in ("env_from", "verbs") for index, item in enumerate(system.get(key) or [])]
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


def run_probe(command: str, cwd: Optional[Path] = None) -> Tuple[Optional[int], str]:
    """(exit code, output) of a probe, run in the shell as a person would type it. (None, why) when it could not run or took too long."""
    try:
        done = subprocess.run(command, shell=True, cwd=str(cwd) if cwd else None, capture_output=True, text=True, errors="replace", timeout=PROBE_SECONDS)
    except subprocess.TimeoutExpired:
        return None, f"no answer in {PROBE_SECONDS} s"
    except (OSError, ValueError) as error:
        return None, f"{type(error).__name__}: {error}"
    return done.returncode, (done.stdout + done.stderr)[:PROBE_OUTPUT]


def reach(systems: Dict[str, Any], run: Callable[[str], Tuple[Optional[int], str]] = run_probe) -> Dict[str, Dict[str, Any]]:
    """For each system that has `needs`: is it reachable from here? `{name: {reachable, why, launch}}`. `why` is short and holds no output
    of the probe (it could name the identity); `launch` is the company's sentence for the person. A system without `needs` is not listed: nothing is known of it."""
    found: Dict[str, Dict[str, Any]] = {}
    for name, system in (systems or {}).items():
        needs = system.get("needs")
        if not needs:
            continue
        code, output = run(needs["probe"])
        if code is None:
            line = {"reachable": False, "why": output}
        elif code != 0:
            line = {"reachable": False, "why": f"the probe ended with exit code {code}"}
        elif needs.get("expect") and not re.search(needs["expect"], output):
            line = {"reachable": False, "why": "the probe answered, but not as `expect` says"}
        else:
            line = {"reachable": True, "why": ""}
        found[name] = {**line, "launch": needs.get("launch") or ""}
    return found
