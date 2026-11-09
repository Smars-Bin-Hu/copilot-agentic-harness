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
# How far Open to the agent may go for one connection (1.7.38, C12): `no` (a write or a run always waits for the person), `items` (only the items the task is linked to), `all` (every
# write and run of the connection). From the loosest to the strictest is the reverse of the order here; a company can only lower a type's scope.
NO, ITEMS, ALL = "no", "items", "all"
OPEN_SCOPES = (NO, ITEMS, ALL)
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
                    "by_address": {"type": "array", "items": {"type": "string", "minLength": 1}},  # 1.7.38: programs (`curl`) that are a call of this system only when their arguments match `when`; any other use of the program is not the system's, and its name alone holds nothing
                    "when": {"type": "string", "minLength": 1},
                    "also": {"type": "object", "required": ["type", "field"], "properties": {"type": {"type": "string", "minLength": 1}, "field": {"type": "string", "minLength": 1}}, "additionalProperties": False},  # 1.7.38: the hosts that the connections of this type have in this field are part of `when`
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
            "commands": {"type": "array", "items": {"type": "string", "minLength": 1}},  # 1.7.38: the subcommands of the system's own program (a tool pack's `commands`): a call whose subcommand is none of them is refused, with a line, not held
            "command": {"type": "string", "minLength": 1},  # 1.7.38: a pattern on the arguments after the program whose first group is the subcommand (default: the first word)
            "rules": {"type": "object", "additionalProperties": _RULE_SET},
            "show": {"type": "object", "additionalProperties": {"type": "string", "minLength": 1}},
            "say": {  # 1.7.20: `[{"pattern": <on the arguments after the program>, "text": "Add a comment to work item {1}"}]`: the first match is the one line a held call's card opens with
                "type": "array",
                "items": {"type": "object", "required": ["pattern", "text"], "properties": {"pattern": {"type": "string", "minLength": 1}, "text": {"type": ["string", "object"], "minLength": 1, "required": ["en"], "additionalProperties": {"type": "string", "minLength": 1}}}},  # 1.7.23: `text` is a string, or {"en": "...", "zh": "..."} (a language that is missing reads en)
            },
            "body": {  # 1.7.20: `[{"pattern": <first group is the value>, "from": "file"|"text"}]`: the text a held call writes, shown on its card (a file of the task, or the text as written)
                "type": "array",
                "items": {"type": "object", "required": ["pattern", "from"], "properties": {"pattern": {"type": "string", "minLength": 1}, "from": {"type": "string", "enum": ["file", "text"]}}},
            },
            "input": {  # 1.7.38 (C12 RC-G1): the options that name a file the call reads its statements from (`["-i"]`), the options whose next word is statement text (`["-Q"]`), and a pattern for the files such a file names itself (`:r file`): the gate reads them and judges their statements by the lists of the type
                "type": "object",
                "properties": {"options": {"type": "array", "items": {"type": "string", "minLength": 1}}, "include": {"type": "string", "minLength": 1}, "unjudged": {"type": "string", "minLength": 1}, "text": {"type": "array", "items": {"type": "string", "minLength": 1}}},  # `unjudged` is the key of the first 1.7.38 build: read, no effect (the `refuse` list does its work)
                "additionalProperties": False,
            },
            "reads": {"type": "array", "items": {"type": "string", "minLength": 1}},  # 1.7.38: the pass list of a type whose program takes statements as text: a pattern each statement must match whole (modules/gate/statements.py)
            "writes": {"type": "array", "items": {"type": "string", "minLength": 1}},  # 1.7.38: the statements an opened connection passes (the same patterns)
            "refuse": {  # 1.7.38: what is refused at once, with the reason that tells the agent the right way (a string, or {"en": ..., "zh": ...}); a pattern found anywhere in a statement or a sqlcmd line
                "type": "array",
                "items": {"type": "object", "required": ["pattern", "reason"], "properties": {"pattern": {"type": "string", "minLength": 1}, "reason": {"type": ["string", "object"], "minLength": 1}}},
            },
            "toolpack": {"type": "string", "minLength": 1},  # 1.7.12: written by the harness for a system an installed tool pack brings
            "openable": {"type": "boolean"},
            "open": {"type": "string", "enum": list(OPEN_SCOPES)},  # 1.7.38: how far Open to the agent goes for this system; see `open_scope`
            "item": {"type": ["string", "array"], "minLength": 1, "items": {"type": "string", "minLength": 1}},  # 1.7.18: a pattern whose first group is the id of the item a write names (a work item); 1.7.25: a pattern, or a list of them; every group of every match names an item
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


def by_address(system: Dict[str, Any]) -> List[str]:
    """The programs that belong to a system only for an address its `when` names (1.7.38: `curl` to an Azure DevOps address), in lower case."""
    reach = (system.get("reach") or {}).get("by_address") or []
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
        if not clis(system) and not by_address(system):
            errors.append(f"systems.{name}.reach: give at least one program in `cli`")
        given = system.get("input")
        if isinstance(given, dict) and not (given.get("options") or given.get("text")):
            errors.append(f"systems.{name}.input: give `options` (the options that name a file) or `text` (the options whose next word is statement text)")
        if (system.get("writes") or system.get("refuse")) and not system.get("reads"):
            errors.append(f"systems.{name}: `writes` and `refuse` work with `reads`, the pass list: give it")
        when = (system.get("reach") or {}).get("when")
        if by_address(system) and not when:
            errors.append(f"systems.{name}.reach: `by_address` needs a `when` that names the address")
        for program in clis(system) if not when else ():
            if program in owner:
                errors.append(f"systems.{name}.reach: {program!r} is also the reach of {owner[program]!r}; give one of them a `when`")
            owner[program] = name
        patterns = [("target", system.get("target") or ""), ("command", system.get("command") or ""), ("reach.when", when or ""), ("needs.expect", (system.get("needs") or {}).get("expect") or ""), ("needs.denied", (system.get("needs") or {}).get("denied") or ""), ("needs.down", (system.get("needs") or {}).get("down") or ""), ("input.include", (system.get("input") or {}).get("include") or ""), ("input.unjudged", (system.get("input") or {}).get("unjudged") or "")] + [(f"show.{key}", value) for key, value in (system.get("show") or {}).items()] + [(f"item[{index}]", value) for index, value in enumerate([system["item"]] if isinstance(system.get("item"), str) else (system.get("item") or [])) if isinstance(value, str)] + [(f"{key}[{index}]", item["pattern"]) for key in ("env_from", "verbs", "say", "body") for index, item in enumerate(system.get(key) or [])]
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


def openable(system: Dict[str, Any]) -> bool:
    """May Open to the agent let this system's held calls through (1.7.13)? A system says so with `openable`; a tool pack's system (a ticket board, a pipeline, a database) is closed unless it
    says yes: its writes reach people or data, so the person approves each one. Since 1.7.38 `open` says how far, and this is only the old way to say `all` or `no`."""
    if isinstance(system.get("openable"), bool):
        return system["openable"]
    return not system.get("toolpack")


def scope_rule(rule: Any, env: str) -> str:
    """The scope a type (or a connection) declares for an environment (1.7.38): `rule` is one word (`"items"`, for every environment) or `{env: word}` with `"*"` for the rest. What is not
    declared, or is not one of the three words, is `no`."""
    if isinstance(rule, str):
        return rule if rule in OPEN_SCOPES else NO
    if isinstance(rule, dict):
        found = rule.get(str(env).lower()) or rule.get("*")
        return found if found in OPEN_SCOPES else NO
    return NO


def lower_scope(first: str, second: str) -> str:
    """The stricter of two scopes: a company can tighten what a type says, never loosen it."""
    return min((first, second), key=OPEN_SCOPES.index)


def open_scope(system: Dict[str, Any], env: str) -> str:
    """How far Open to the agent may go for a call of this system in this environment (1.7.38): `all`, `items` or `no`. Prod is never opened, whatever a system says. A system that gives `open`
    (a connection derives it from its type) is read as it says; a system written by hand without it keeps the old rule: open to the agent where `openable` is true, in dev, ist and qat."""
    if str(env or "").lower() == PROD:
        return NO
    if system.get("open") in OPEN_SCOPES:
        return system["open"]
    return ALL if openable(system) and str(env or "").lower() in ("dev", "ist", "qat") else NO


def environments(systems: Dict[str, Any], only_openable: bool = False) -> Dict[str, List[str]]:
    """The environments the listed systems reach, `{env: [system names]}`, from `env`, `env_from` and `default_env`; prod and none left out (nothing is opened there).
    For the task page: which environments a person may open for a task (1.7.6)."""
    found: Dict[str, List[str]] = {}
    for name, system in (systems or {}).items():
        envs = {system["env"]} if system.get("env") else {rule["env"] for rule in system.get("env_from") or []} | ({system["default_env"]} if system.get("default_env") else set())
        for env in sorted(envs):
            if env not in (PROD, "none") and (openable(system) or not only_openable):
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


def place(system: str, env: str) -> str:
    """Where a call goes, for a sentence: `finance (IST)`; a system with no environment is just its name (1.7.21)."""
    return system if not env or env == "none" else f"{system} ({env})"
