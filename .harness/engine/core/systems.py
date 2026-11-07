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
            "show": {"type": "object", "additionalProperties": {"type": "string", "minLength": 1}},
            "say": {  # 1.7.20: `[{"pattern": <on the arguments after the program>, "text": "Add a comment to work item {1}"}]`: the first match is the one line a held call's card opens with
                "type": "array",
                "items": {"type": "object", "required": ["pattern", "text"], "properties": {"pattern": {"type": "string", "minLength": 1}, "text": {"type": "string", "minLength": 1}}},
            },
            "body": {  # 1.7.20: `[{"pattern": <first group is the value>, "from": "file"|"text"}]`: the text a held call writes, shown on its card (a file of the task, or the text as written)
                "type": "array",
                "items": {"type": "object", "required": ["pattern", "from"], "properties": {"pattern": {"type": "string", "minLength": 1}, "from": {"type": "string", "enum": ["file", "text"]}}},
            },
            "toolpack": {"type": "string", "minLength": 1},  # 1.7.12: written by the harness for a system an installed tool pack brings
            "openable": {"type": "boolean"},
            "item": {"type": "string", "minLength": 1},  # 1.7.18: a pattern whose first group is the id of the item a write names (a work item)
            "link": {"type": "string", "minLength": 1},  # 1.7.18: the link type of `harness task link` that names such an item (ado)  # 1.7.13: may Open to the agent let its writes through? Default: yes, but not for a tool pack's system  # 1.7.7: {name: pattern}; the first group is the fact a card shows beside a command (server, port)
            "needs": {  # 1.7.9: `probes` names one probe per environment (another server, another account); `denied` is what a call prints when the identity is not let in
                "type": "object",
                "properties": {"probe": {"type": "string", "minLength": 1}, "probes": {"type": "object", "additionalProperties": {"type": "string", "minLength": 1}},
                               "expect": {"type": "string"}, "denied": {"type": "string", "minLength": 1}, "down": {"type": "string", "minLength": 1}, "launch": {"type": "string"}},
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
        patterns = [("target", system.get("target") or ""), ("reach.when", when or ""), ("needs.expect", (system.get("needs") or {}).get("expect") or ""), ("needs.denied", (system.get("needs") or {}).get("denied") or ""), ("needs.down", (system.get("needs") or {}).get("down") or "")] + [(f"show.{key}", value) for key, value in (system.get("show") or {}).items()] + [(f"{key}[{index}]", item["pattern"]) for key in ("env_from", "verbs", "say", "body") for index, item in enumerate(system.get(key) or [])]
        for where, pattern in (item for item in patterns if item[1]):
            try:
                re.compile(pattern)
            except re.error as error:
                errors.append(f"systems.{name}.{where}: bad pattern {pattern!r}: {error}")
        if system.get("needs") and not probes(system):
            errors.append(f"systems.{name}.needs: give a `probe`, or `probes` with one per environment")
        for env in ((system.get("needs") or {}).get("probes") or {}):
            if str(env).lower() not in ENVS:
                errors.append(f"systems.{name}.needs.probes: {env!r} is not an environment ({', '.join(ENVS)})")
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


def environments(systems: Dict[str, Any]) -> Dict[str, List[str]]:
    """The environments the listed systems reach, `{env: [system names]}`, from `env`, `env_from` and `default_env`; prod and none left out (nothing is opened there).
    For the task page: which environments a person may open for a task (1.7.6)."""
    found: Dict[str, List[str]] = {}
    for name, system in (systems or {}).items():
        envs = {system["env"]} if system.get("env") else {rule["env"] for rule in system.get("env_from") or []} | ({system["default_env"]} if system.get("default_env") else set())
        for env in sorted(envs):
            if env not in (PROD, "none"):
                found.setdefault(env, []).append(name)
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


def probes(system: Dict[str, Any]) -> Dict[str, str]:
    """`{env: probe}` of a system: `needs.probes` names one per environment; `needs.probe` alone is the probe of every environment the system reaches
    (`any` for a system with none). Nothing when the system has no `needs`."""
    needs = system.get("needs") or {}
    if needs.get("probes"):
        return {str(env).lower(): str(command) for env, command in needs["probes"].items() if command}
    if not needs.get("probe"):
        return {}
    return {env: needs["probe"] for env in environments({"one": system})} or {"any": needs["probe"]}


def reach(systems: Dict[str, Any], run: Callable[[str], Tuple[Optional[int], str]] = run_probe) -> Dict[str, Dict[str, Any]]:
    """For each system that has `needs`: is it reachable from here? `{name: {reachable, why, launch}}`. `why` is short and holds no output
    of the probe (it could name the identity); `launch` is the company's sentence for the person. A system without `needs` is not listed: nothing is known of it."""
    found: Dict[str, Dict[str, Any]] = {}
    for name, system in (systems or {}).items():
        needs = system.get("needs")
        if not needs:
            continue
        lines = []
        for command in sorted(set(probes(system).values())):  # one run per distinct probe
            code, output = run(command)
            if code is None:
                lines.append({"reachable": False, "why": output})
            elif code != 0:
                lines.append({"reachable": False, "why": f"the probe ended with exit code {code}"})
            elif needs.get("expect") and not re.search(needs["expect"], output):
                lines.append({"reachable": False, "why": "the probe answered, but not as `expect` says"})
            else:
                lines.append({"reachable": True, "why": ""})
        bad = [line for line in lines if not line["reachable"]]
        found[name] = {"reachable": not bad, "why": bad[0]["why"] if bad else "", "launch": needs.get("launch") or ""}
    return found
