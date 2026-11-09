"""Connections and the person's identities for them (1.7.10, named so in 1.7.17). The harness knows no type of connection: a type is a file a tool pack brings.

Three layers, each with one owner:

  types        `types/<type>.json` of an installed tool pack (`.harness/toolpacks/<pack>/`, core.toolpacks). What a connection of that type needs
               (fields), how an identity reaches its commands (`auth`: env, netonly, keyfile, tool), the command that tests the way in, the words of its
               answer (`expect`, `denied`, `down`), and for the gate the programs (`cli`), how a command names one connection (`match`), the verbs and rules.
  connections  `.harness/policies/connections.company.json` (from `company/tools/connections.json`): `{"connections": {name: {type, env, auth, <fields>}}}`.
               The person's own connections live in `.harness/.env` with their identities.
  identities   `.harness/.env`: `HARNESS_CONNECTION_<NAME>_<FIELD>=value`, written by Get ready after a test passed. Never in git, a log, a page or the
               knowledge base; `reinstall` carries it; the gate refuses the agent a read of it.

Each connection becomes a system of the tools policy (`derived`): the gate judges its commands, the reach check probes it, with nothing written by hand.
When VS Code is opened, the person picks the identities for that window (`plan`, `launch`); those that cannot share it (two Windows accounts, two
identities that want the same variable) are reached through `harness as <name> -- <command>` (`wrapped`), each command with its own identity.
In this module a connection type is held in a variable called `kind` (`type` is Python's own word).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import clip, messages, netonly
from . import systems as outside
from .paths import utc_now

POLICY = "connections"
ENV_FILE = Path(".harness") / ".env"
STATE_FILE = Path(".harness") / "runtime" / "state" / "identities.json"
PREFIX = "HARNESS_CONNECTION_"
ALIAS = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
IDENTITIES = ("env", "netonly", "keyfile", "tool", "token")  # tool (1.7.13): the program keeps its own sign-in (`az login`); the harness keeps no account, only who the test answered
SECRET_FIELDS = ("password", "token")
IDENTITY_FIELDS = ("account", "password", "keyfile", "token")
OWN_FIELDS = ("type", "env", "auth", "label", "about")  # what a server of the person's own has besides the kind's fields (1.7.38: `about`, one line the agent finds it by)
TEST_SECONDS = 15
TOOL_TEST_SECONDS = 60  # a program that keeps its own sign-in (`az`) is slow to start; a type may set `test.timeout` itself (1.7.19)
VIAS = ("cli", "mcp")  # how a connection of the type is reached: a program in the terminal, or an MCP server VS Code runs (1.7.17)
ENVS = ("dev", "ist", "qat", "prod", "none")  # none (1.7.13): a ticket board or a pipeline service, which has no environments


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


# --- kinds ------------------------------------------------------------------------------------------------------------------------------------------------

def types(root: Path, guard: bool = False) -> Dict[str, Dict[str, Any]]:
    """Every kind this copy knows, `{name: kind}`; a file that cannot be read is left out (`problems` says why). The kinds of the packs that are on. With `guard` (the gate, 1.7.38)
    also those of an off pack that a connection uses: a pack that is off still guards its connections."""
    from . import toolpacks  # it reads this module for its checks

    from . import launchenv  # it reads this module's .env

    mcp = launchenv.mcp_allowed(root)
    found: Dict[str, Dict[str, Any]] = {}
    for pack_name, path, item in toolpacks.typed_entries(root, guard):  # the first tool pack that brings a type keeps it
        try:
            kind = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(kind, dict) and kind.get("via") == "mcp" and not mcp:  # MCP is not allowed here: the type is not offered
            continue
        if isinstance(kind, dict) and kind.get("type") and str(kind["type"]) not in found:
            found[str(kind["type"])] = dict(kind, toolpack=pack_name)  # its connections' systems are the tool pack's: Open to the agent leaves them closed
            own = toolpacks.own_commands(item, kind)  # 1.7.38: a pack that lists the subcommands of its own program: the gate refuses any other word after it
            if own and "commands" not in kind:
                found[str(kind["type"])]["commands"] = own
    return found


def _say_text_ok(text: Any) -> bool:
    """A `say` text (1.7.23): a string, or `{"en": "...", "zh": "..."}` with `en` and every value a non-empty string."""
    if isinstance(text, str):
        return bool(text)
    return isinstance(text, dict) and isinstance(text.get("en"), str) and bool(text["en"]) and all(isinstance(value, str) and value for value in text.values())


def type_problems(kind: Dict[str, Any]) -> List[str]:
    """What is wrong with a connection type; empty when it is fine. A type `via: "mcp"` is reached through an MCP server VS Code runs: it needs no test
    command and no way in of its own (the sign-in is VS Code's)."""
    name = kind.get("type", "?")
    out = []
    if kind.get("via", "cli") not in VIAS:
        out.append(f"types.{name}: `via` is one of {', '.join(VIAS)}")
    if kind.get("env") not in (None, "none"):  # 1.7.38: `"env": "none"` says the type has no environments (a ticket board)
        out.append(f"types.{name}: `env` is `none` (a type with no environments), or left out")
    if not isinstance(kind.get("fields", {}), dict) or (kind.get("via") != "mcp" and not kind.get("fields")):
        out.append(f"types.{name}: `fields` names what a connection of this type needs (host, port, org, ...)")
    if kind.get("via") == "mcp":
        return out
    if not isinstance(kind.get("auth"), dict) or not kind["auth"]:
        out.append(f"types.{name}: `auth` names at least one way in")
    for mode, auth in (kind.get("auth") or {}).items():
        if not isinstance(auth, dict) or auth.get("identity") not in IDENTITIES:
            out.append(f"types.{name}.auth.{mode}: `identity` is one of {', '.join(IDENTITIES)}")
        elif auth.get("needs") is not None and (not isinstance(auth["needs"], list) or not all(isinstance(one, str) and re.match(r"^[\w.\-]+$", one) for one in auth["needs"])):
            out.append(f"types.{name}.auth.{mode}.needs: a list of program names")
    if not test_command(kind):
        out.append(f"types.{name}: `test` is the command that tests the way in (or {{\"command\": ..., \"timeout\": seconds}})")
    if isinstance(kind.get("test"), dict):
        wait = kind["test"].get("timeout", 1)
        if isinstance(wait, bool) or not isinstance(wait, (int, float)) or not 1 <= wait <= 600:
            out.append(f"types.{name}.test.timeout: seconds, from 1 to 600")
    texts = [test_command(kind), kind.get("match") or ""] + [str((auth or {}).get("args") or "") for auth in (kind.get("auth") or {}).values()]
    if any("{password}" in text for text in texts):
        out.append(f"types.{name}: a password never goes on a command line; give it through `env` of the auth")
    if kind.get("open") is not None:  # 1.7.38: how far Open to the agent may go: one word, or {env: word} with "*" for the rest
        given = kind["open"]
        words = [given] if isinstance(given, str) else list(given.values()) if isinstance(given, dict) else [None]
        if not all(isinstance(word, str) and word in outside.OPEN_SCOPES for word in words) or (isinstance(given, dict) and not all(str(env).lower() in outside.ENVS + ("*",) for env in given)):
            out.append(f"types.{name}.open: one of {', '.join(outside.OPEN_SCOPES)}, or {{environment: one of them}} (\"*\" for the rest)")
    for key in ("say", "body"):  # 1.7.20: what a held call's card says and shows
        if kind.get(key) is not None and not isinstance(kind.get(key), list):
            out.append(f"types.{name}.{key}: a list of rules")
            continue
        for index, rule in enumerate(kind.get(key) or []):
            if not isinstance(rule, dict) or not rule.get("pattern") or (key == "say" and not rule.get("text")) or (key == "body" and rule.get("from") not in ("file", "text")):
                out.append(f"types.{name}.{key}[{index}]: {'`pattern` and `text`' if key == 'say' else '`pattern` and `from` (file or text)'}")
                continue
            if key == "say" and not _say_text_ok(rule.get("text")):
                out.append(f"types.{name}.say[{index}]: `text` is a string, or an object with `en` (and `zh`) as strings")
                continue
            try:
                re.compile(str(rule["pattern"]))
            except re.error as error:
                out.append(f"types.{name}.{key}[{index}]: bad pattern: {error}")
    given = kind.get("input")  # 1.7.38 (C12 RC-G1): the options that name a file the call reads its statements from, the options whose next word is statement text, and how such a file names more files
    if given is not None:
        words = isinstance(given, dict) and all(isinstance(given.get(part, []), list) and all(isinstance(one, str) and one for one in given.get(part, [])) for part in ("options", "text"))
        if not (isinstance(given, dict) and set(given) <= {"options", "include", "unjudged", "text"} and words and (given.get("options") or given.get("text")) and isinstance(given.get("include", ""), str) and isinstance(given.get("unjudged", ""), str)):
            out.append(f"types.{name}.input: {{\"options\": [\"-i\"], \"text\": [\"-Q\"], \"include\": <a pattern whose group is a file>}}: `options` are the options that name a file, `text` the options whose next word is statement text (give one of the two); `include` is optional")
    for key in ("reads", "writes"):  # 1.7.38: the pass lists of a type whose program takes statements as text
        if kind.get(key) is not None and not (isinstance(kind[key], list) and all(isinstance(one, str) and one for one in kind[key])):
            out.append(f"types.{name}.{key}: a list of patterns, each matched against a whole statement")
            continue
        for index, pattern in enumerate(kind.get(key) or []):
            try:
                re.compile(pattern)
            except re.error as error:
                out.append(f"types.{name}.{key}[{index}]: bad pattern: {error}")
    if kind.get("refuse") is not None and not isinstance(kind["refuse"], list):
        out.append(f"types.{name}.refuse: a list of {{\"pattern\", \"reason\"}}")
    for index, entry in enumerate(kind.get("refuse") or []):
        if not isinstance(entry, dict) or not entry.get("pattern") or not _say_text_ok(entry.get("reason")):
            out.append(f"types.{name}.refuse[{index}]: `pattern` and `reason` (a string, or an object with `en` and `zh` strings)")
            continue
        try:
            re.compile(str(entry["pattern"]))
        except re.error as error:
            out.append(f"types.{name}.refuse[{index}]: bad pattern: {error}")
    if (kind.get("writes") or kind.get("refuse")) and not kind.get("reads"):
        out.append(f"types.{name}: `writes` and `refuse` work with `reads`, the pass list: give it")
    for key in ("expect", "denied", "down", "match", "signin_lost", "command"):
        value = kind.get(key) or ""
        if not isinstance(value, str):
            out.append(f"types.{name}.{key}: a pattern, as text")
            continue
        try:
            re.compile(_fill(value, {}, escape=True) if key == "match" else value)
        except re.error as error:
            out.append(f"types.{name}.{key}: bad pattern: {error}")
    for part in ("include", "unjudged"):
        if isinstance(given, dict) and isinstance(given.get(part), str) and given[part]:
            try:
                re.compile(given[part])
            except re.error as error:
                out.append(f"types.{name}.input.{part}: bad pattern: {error}")
    if isinstance(kind.get("fields"), dict) and not all(isinstance(spec, dict) for spec in kind["fields"].values()):
        out.append(f"types.{name}.fields: each field is an object (`label`, `placeholder`, `default`, `optional`)")
    return out + _gate_shape(kind, name)


GATE_KEYS = ("verbs", "target", "show", "rules", "item", "link", "commands", "openable", "pin")  # keys the gate reads and that `type_problems` did not check before 1.7.38 (G-1)


def _gate_shape(kind: Dict[str, Any], name: Any) -> List[str]:
    """(1.7.38, G-1) What the gate would find wrong in the system a type makes: a key of the wrong shape or a pattern that does not compile (`verbs`, `target`, `show`, `rules`, `item`, `link`, `commands`).
    Such a type used to be skipped, and one that got past here made the whole list of systems invalid, so no call was judged. The same schema the list is checked with is used; the words are the type's."""
    given = {key: kind[key] for key in GATE_KEYS if key in kind}
    if not given:
        return []
    cli = kind.get("cli")
    system = {"reach": {"cli": cli if isinstance(cli, (str, list)) and cli else ["x"]}, **given}
    return [item.replace("systems.x", f"types.{name}", 1) for item in outside.validate({"x": system})]


# --- the .env file ----------------------------------------------------------------------------------------------------------------------------------------

def test_command(kind: Dict[str, Any]) -> str:
    """The test command of a type: `test` is the text, or {"command", "timeout"}."""
    given = kind.get("test")
    return str(given.get("command") or "") if isinstance(given, dict) else str(given or "")


def test_seconds(kind: Dict[str, Any], server: Optional[Dict[str, Any]] = None) -> float:
    """How long a test may take: `test.timeout` of the type; else 60 s for a program that keeps its own sign-in (a `tool` identity), else 15 s."""
    given = kind.get("test")
    if isinstance(given, dict) and isinstance(given.get("timeout"), (int, float)) and not isinstance(given.get("timeout"), bool):
        return float(given["timeout"])
    return float(TOOL_TEST_SECONDS if delivery(kind, server or {})["identity"] == "tool" else TEST_SECONDS)


UNTESTED = "untested"  # the `why` of a `reach` line: the sign-in is kept and no test has got through to the system yet
UNTESTED_SLOW = "untested-noanswer"  # (1.7.38, C13 D3-1) the same, and the test got no answer in time: the sign-in is kept all the same


def env_key(alias: str, field: str) -> str:
    return PREFIX + alias.upper().replace("-", "_") + "_" + field.upper()


def _parse_value(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return re.sub(r"\\(.)", lambda found: {"n": "\n", "t": "\t"}.get(found.group(1), found.group(1)), raw[1:-1])
    return raw


def _write_value(value: str) -> str:
    if value and re.fullmatch(r"[^\s#'\"=]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def read_env(root: Path) -> Dict[str, str]:
    """The `.env` of this copy, `{KEY: value}`; nothing when there is none."""
    try:
        lines = (root / ENV_FILE).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return {}
    found: Dict[str, str] = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        found[key.strip()] = _parse_value(value)
    return found


def write_env(root: Path, changes: Dict[str, Optional[str]]) -> None:
    """Change keys of the `.env` (None removes one) and keep every other line, comments too. Only this person may read the file."""
    path = root / ENV_FILE
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        lines = [say("connections.env.head")]
    done = set()
    out: List[str] = []
    for line in lines:
        key = line.partition("=")[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in changes:
            done.add(key)
            if changes[key] is not None:
                out.append(f"{key}={_write_value(str(changes[key]))}")
            continue
        out.append(line)
    out += [f"{key}={_write_value(str(value))}" for key, value in changes.items() if key not in done and value is not None]
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(temp, 0o600)
    os.replace(temp, path)


# --- servers ----------------------------------------------------------------------------------------------------------------------------------------------

def company_connections(policy: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    found = policy.get("connections") if isinstance(policy.get("connections"), dict) else {}
    return {str(alias): dict(item) for alias, item in found.items() if isinstance(item, dict)}


def own_connections(env: Dict[str, str], known: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The person's own servers, from the `.env`: each has an `..._ALIAS` line, and its fields beside it."""
    out: Dict[str, Dict[str, Any]] = {}
    for key, value in env.items():
        if key.startswith(PREFIX) and key.endswith("_ALIAS") and ALIAS.match(value):
            stem = key[: -len("ALIAS")]
            out[value] = {field[len(stem):].lower(): item for field, item in env.items() if field.startswith(stem) and field != key and not field.endswith(("_ACCOUNT", "_PASSWORD", "_KEYFILE", "_TOKEN"))}
            out[value]["own"] = True
    return {alias: item for alias, item in out.items() if alias not in known}


def listed(root: Path, policy: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Every server: the company's, then the person's own. `{alias: {kind, env, auth, <fields>, own?}}`."""
    from . import config  # config imports this module to derive the systems

    policy = config.policy_or_empty(root, POLICY) if policy is None else policy
    found = company_connections(policy)
    found.update(own_connections(read_env(root), found))
    return found


def faults(root: Path) -> List[Dict[str, str]]:
    """(1.7.38, C13 F2) What is wrong with the connection list: `[{file, problem}]`, empty when it can be read. The three files that make it (`connections.json`, the company's `connections.company.json`, the person's
    `connections.override.json`) are read one by one: a file that is not JSON, or not an object, a `connections` that is not an object, a connection that is not an object or has no `type`, a `type` that is not text, an `env`
    that is not one of `ENVS`, and the layers that cannot be merged. It used to be swallowed (`config.policy_or_empty`): a list that could not be read had no connections, so none of their programs were judged. Now the gate holds
    every program of the tool packs that bring a connection type (`broken_systems`) and `harness doctor` says which file is wrong."""
    from . import config
    from .paths import policies_dir

    found: List[Dict[str, str]] = []
    for name in [f"{POLICY}.json"] + [f"{POLICY}{suffix}" for suffix in config.LAYERS]:
        path = policies_dir(root) / name
        if not path.exists():
            if name == f"{POLICY}.json":
                found.append({"file": name, "problem": "the file is missing"})
            continue
        try:
            data = config.read_json(path)
        except (OSError, ValueError) as error:
            found.append({"file": name, "problem": str(error)})
            continue
        if not isinstance(data, dict):
            found.append({"file": name, "problem": "the file is an object"})
            continue
        listed_here = data.get("connections")
        if listed_here is None:
            continue
        if not isinstance(listed_here, dict):
            found.append({"file": name, "problem": "`connections` is an object"})
            continue
        for alias, item in listed_here.items():
            if not isinstance(item, dict):
                found.append({"file": name, "problem": f"connection {alias}: an object is needed"})
            elif not isinstance(item.get("type"), str) or not item.get("type"):
                found.append({"file": name, "problem": f"connection {alias}: `type` is the name of a connection type"})
            elif item.get("env") not in ENVS:
                found.append({"file": name, "problem": f"connection {alias}: `env` is one of {', '.join(ENVS)}"})
    if not found:
        try:
            config.load_policy(root, POLICY)  # the layers must merge too
        except Exception as error:  # noqa: BLE001 - a fault is a fault, whatever it raises
            found.append({"file": f"{POLICY}*.json", "problem": f"{type(error).__name__}: {error}"})
    return found


def broken_systems(root: Path) -> Dict[str, Any]:
    """(1.7.38, C13 F2) For the gate: when the connection list cannot be read (`faults`), one system for each tool pack that brings a connection type, named `broken-<pack>`, that owns every program of those types.
    Every call of them is held for the person, and the card says which file is wrong and how. Which pack a connection used cannot be known when the list is unreadable, so every pack with a type counts, on or off.
    The packs whose files are right do not matter: the list is what names the connection a call reaches. `{}` when the list is fine."""
    problems = faults(root)
    if not problems:
        return {}
    from . import toolpacks

    first = problems[0]
    more = f" (+{len(problems) - 1})" if len(problems) > 1 else ""
    out: Dict[str, Any] = {}
    for name, item in toolpacks.listed(root).items():
        programs: List[str] = []
        folder = item["folder"] / toolpacks.TYPES
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                found = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            cli = found.get("cli") if isinstance(found, dict) else None
            programs += [str(one).lower() for one in ([cli] if isinstance(cli, str) else cli if isinstance(cli, list) else []) if isinstance(one, str) and one]
        if programs:
            out[f"broken-{name}"] = {"reach": {"cli": sorted(set(programs))}, "env": "none", "toolpack": name, "broken": f"{name}: {first['file']}: {first['problem']}{more}"[:400]}
    return out


NO_CONNECTION = "no-connection-"  # the name of a system made for a program that no connection of its type lists (`unconnected`)


def _free_words(kind: Dict[str, Any]) -> List[str]:
    """The words of a type that only print help or the version (`free` of the type; `pin.free` for a type with a `pin`): a call with one reaches no server."""
    given = kind.get("free")
    if given is None and isinstance(kind.get("pin"), dict):
        given = kind["pin"].get("free")
    return [str(one) for one in given if isinstance(one, str) and one] if isinstance(given, list) else []


def unconnected(root: Path, systems: Dict[str, Any]) -> Dict[str, Any]:
    """(1.7.38, C13 F2b) For the gate: the systems of the programs that a tool pack declares and no system lists. A connection makes a system (`derived`); a computer with no connection of a type has no system for its program,
    so a call of it was judged by no one and passed (`sqlcmd -S x -Q "UPDATE ..."` with the connection list empty). Now every pack this computer knows is read, on or off (the factory's, the company's, the folders added
    here): the `cli` of each type it brings, and the `rules.json` systems of a pack that is off and guards no connection (a pack that is off still guards what it names). A program no system lists gets one made here, named
    `no-connection-<type>`, with `noconn` (the type, its help-only words `free`, its `pin`) and the lists of the type, so the gate refuses the call with the way (no connection for it: the user adds one) and still reads the
    refuse list first. A file that cannot be read is a `broken-<pack>` system: its programs are read from the text and held. The result is for the gate only: it is not part of the tools policy, so `tools check`
    and the board do not show it. `{}` when there is nothing to add."""
    from . import govern, toolpacks

    have = {program for system in (systems or {}).values() if isinstance(system, dict) for program in outside.clis(system)}
    taken = set(systems or {})
    out: Dict[str, Any] = {}

    def fresh(key: str) -> str:
        while key in taken or key in out:
            key += "_"
        return key

    def hold(pack: str, file: str, problem: Any, names: List[str]) -> None:
        names = [one for one in names if one not in have]
        if names:
            out[fresh(f"broken-{pack}")] = {"reach": {"cli": names}, "env": "none", "toolpack": pack, "broken": f"{pack}: {file}: {' '.join(str(problem).split())}"[:400]}
            have.update(names)

    guarded = set(toolpacks.guarded(root))
    for folder in govern.folders(root):
        pack = folder.name
        for path in sorted((folder / toolpacks.TYPES).glob("*.json")) if (folder / toolpacks.TYPES).is_dir() else []:
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError as error:
                hold(pack, f"{toolpacks.TYPES}/{path.name}", error, [])
                continue
            try:
                kind = json.loads(text)
            except ValueError as error:
                hold(pack, f"{toolpacks.TYPES}/{path.name}", error, govern.cli_words(text))
                continue
            cli = kind.get("cli") if isinstance(kind, dict) else None
            programs = [str(one).lower() for one in ([cli] if isinstance(cli, str) else cli if isinstance(cli, list) else []) if isinstance(one, str) and one]
            programs = [one for one in dict.fromkeys(programs) if one not in have]
            if not programs:
                continue
            system: Dict[str, Any] = {"reach": {"cli": programs}, "env": "none", "toolpack": pack,
                                      "noconn": {"type": str(kind.get("type") or path.stem), "free": _free_words(kind), "pin": kind["pin"] if isinstance(kind.get("pin"), dict) else None}}
            for key in ("verbs", "reads", "writes", "refuse", "input"):  # what the refuse list needs to read the statements of the call
                if kind.get(key) is not None:
                    system[key] = kind[key]
            out[fresh(NO_CONNECTION + str(system["noconn"]["type"]))] = system
            have.update(programs)
        if pack in guarded or not (folder / toolpacks.RULES).is_file():
            continue  # a pack the gate reads already has its rules in the policy (`rules_layer`)
        listed, problems = toolpacks._pack_rules(folder)  # noqa: SLF001 - the same reading `rules_layer` does
        if problems:
            try:
                names = govern.cli_words((folder / toolpacks.RULES).read_text(encoding="utf-8-sig", errors="replace"))
            except OSError:
                names = []
            hold(pack, toolpacks.RULES, problems[0], names)
            continue
        for key, spec in listed.items():
            if isinstance(spec, dict) and fresh(key) == key:
                out[key] = dict(spec, toolpack=pack)
                have.update(outside.clis(spec))
    return out


def unset_fields(root: Path) -> List[Dict[str, Any]]:
    """The company's connections whose type has a field it needs (no `default`, not `optional`) that the connection leaves empty (1.7.30): `[{alias, type, fields}]`.
    A connection of a type no active pack brings is not asked about here."""
    kinds = types(root)
    out = []
    for alias, server in listed(root).items():
        if server.get("own"):
            continue
        kind = kinds.get(str(server.get("type"))) or {}
        gaps = [field for field, spec in (kind.get("fields") or {}).items() if isinstance(spec, dict) and not spec.get("optional") and spec.get("default") in (None, "")
                and field not in SECRET_FIELDS and server.get(field) in (None, "")]
        if gaps:
            out.append({"alias": alias, "type": str(server.get("type")), "fields": gaps})
    return out


TOOL_PREFIX = "HARNESS_TOOL_"  # 1.7.37: the sign-in of a program that keeps its own (`az login`) is one per program: HARNESS_TOOL_<PROGRAM>_USER


def tool_program(auth: Dict[str, Any]) -> str:
    """The program a `tool` identity signs in to: the first word of its `login` command (`az login ...` -> `az`); "" when it names none."""
    words = str(auth.get("login") or "").split()
    return re.sub(r"\.(exe|cmd|bat)$", "", words[0].strip("\"'"), flags=re.IGNORECASE).lower() if words else ""


def tool_key(program: str) -> str:
    return TOOL_PREFIX + re.sub(r"[^A-Za-z0-9]", "_", program).upper() + "_USER"


def _way(kind: Dict[str, Any], server: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    modes = kind.get("auth") or {}
    return modes.get((server or {}).get("auth") or next(iter(modes), "")) or {}


def tool_ways(kind: Dict[str, Any]) -> List[Tuple[str, str]]:
    """`(way, program)` of each way in of a type that is a `tool` identity with a sign-in command."""
    return [(mode, tool_program(auth)) for mode, auth in (kind.get("auth") or {}).items() if isinstance(auth, dict) and auth.get("identity") == "tool" and tool_program(auth)]


def identity_of(env: Dict[str, str], alias: str, kind: Dict[str, Any], server: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """What the person saved for this server: account, password, keyfile (what is there). A `tool` identity is the program's, shared by every connection of the
    type (`HARNESS_TOOL_<PROGRAM>_USER`); the old per-connection account is read still (1.7.37)."""
    found = {field: env[env_key(alias, field)] for field in IDENTITY_FIELDS if env.get(env_key(alias, field))}
    if not found:
        auth = _way(kind, server) if server is not None else None
        program = tool_program(auth) if auth is not None and auth.get("identity") == "tool" else (tool_ways(kind)[0][1] if server is None and len(tool_ways(kind)) == 1 else "")
        if program and env.get(tool_key(program)):
            return {"account": env[tool_key(program)]}
    return found


def _fill(template: str, values: Dict[str, Any], escape: bool = False) -> str:
    def one(found: "re.Match[str]") -> str:
        value = str(values.get(found.group(1), ""))
        return re.escape(value) if escape else value
    return re.sub(r"\{(\w+)\}", one, template)


def _quote(value: str) -> str:
    """A value for a command line, quoted only when it must be (spaces, a quote)."""
    if re.fullmatch(r"[\w.,:@\\/=+-]+", value or ""):
        return value
    return subprocess.list2cmdline([value]) if os.name == "nt" else shlex.quote(value)


def command(kind: Dict[str, Any], server: Dict[str, Any], identity: Dict[str, str], alias: str = "") -> str:
    """The test command of a server with this identity, ready to run (the password never in it). `{conn}` is the name of the connection (1.7.21)."""
    auth = (kind.get("auth") or {}).get(server.get("auth") or next(iter(kind.get("auth") or {"": {}})), {}) or {}
    values = {**{field: (server.get(field) if server.get(field) not in (None, "") else spec.get("default", "")) for field, spec in (kind.get("fields") or {}).items()},
              "account": identity.get("account", ""), "keyfile": identity.get("keyfile", ""), "conn": alias}
    quoted = {key: _quote(str(value)) for key, value in values.items()}
    quoted["auth"] = _fill(str(auth.get("args") or ""), quoted)
    return " ".join(_fill(test_command(kind), quoted).split())


def delivery(kind: Dict[str, Any], server: Dict[str, Any]) -> Dict[str, Any]:
    """How an identity reaches this server's commands: `{identity, env: {VAR: field}}`."""
    modes = kind.get("auth") or {}
    auth = modes.get(server.get("auth") or next(iter(modes), "")) or {}
    return {"identity": auth.get("identity", "env"), "env": dict(auth.get("env") or {})}


def variables(kind: Dict[str, Any], server: Dict[str, Any], identity: Dict[str, str]) -> Dict[str, str]:
    """The environment variables that carry this identity (`env` and `keyfile` delivery)."""
    how = delivery(kind, server)
    token = identity.get("token", "") if how["identity"] == "token" else ""
    return {var: (identity.get(field, "") or token) for var, field in how["env"].items() if identity.get(field) or token}


def connection_env(alias: str, kind: Dict[str, Any], server: Dict[str, Any], identity: Dict[str, str]) -> Dict[str, str]:
    """What a program of a connection can read when the harness runs its test or probe, saved or not (1.7.21): `HARNESS_CONNECTION_<NAME>_<FIELD>` for each non-secret
    field (a field left empty gives its default), and the identity as `_USER`, `_PASSWORD`, `_TOKEN` (and `_KEYFILE`). NAME is the alias in capitals, `-` as `_`."""
    stem = env_key(alias, "")
    out = {stem + field.upper(): str(server.get(field) if server.get(field) not in (None, "") else spec.get("default", ""))
           for field, spec in (kind.get("fields") or {}).items() if field not in SECRET_FIELDS and isinstance(spec, dict)}
    out = {key: value for key, value in out.items() if value}
    for field, name in (("account", "USER"), ("password", "PASSWORD"), ("token", "TOKEN"), ("keyfile", "KEYFILE")):
        if identity.get(field):
            out[stem + name] = identity[field]
    return out


# --- the gate's view: a system per server -----------------------------------------------------------------------------------------------------------------

def derived(root: Path, tools_policy: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """A system of the tools policy for every server whose kind tells the gate how to see it (`cli`, `match`). A system written by hand with the same name wins.
    1.7.38: the kinds of a pack that is off count too when a connection uses them (the gate still judges the calls); such a system has no `needs`, so nothing probes it
    and the board shows no state for it: the pack is off, its program is not on the PATH."""
    from . import toolpacks

    known, env, wrapped = types(root, guard=True), read_env(root), set(state(root).get("wrap") or [])
    on = toolpacks.active(root)
    out: Dict[str, Dict[str, Any]] = {}
    for alias, server in listed(root).items():
        kind = known.get(str(server.get("type")))
        if not kind or not kind.get("cli") or not kind.get("match") or type_problems(kind) or server.get("env") not in ENVS:
            continue
        values = {field: (server.get(field) if server.get(field) not in (None, "") else spec.get("default", "")) for field, spec in kind["fields"].items()}
        probe = command(kind, server, identity_of(env, alias, kind, server), alias)
        if alias in wrapped:
            probe = f"{_quote(sys.executable)} {_quote(str(root / '.harness' / 'engine' / 'cli.py'))} as {alias} -- {probe}"
        system: Dict[str, Any] = {
            "reach": {"cli": kind["cli"], "when": _fill(kind["match"], values, escape=True)},
            "env": server["env"],
        }
        if str(kind.get("toolpack") or "") in on:
            system["needs"] = {"probes": {server["env"]: probe}, "launch": say("connections.launch", alias=alias)}
            for key in ("expect", "denied", "down"):
                if kind.get(key):
                    system["needs"][key] = kind[key]
        for key in ("verbs", "target", "show", "rules", "say", "body"):
            chosen = (server.get(key) or kind.get(key)) if key == "rules" else kind.get(key)  # the connection's own rules win, else the type's (1.7.21)
            if chosen:
                system[key] = chosen
        for key in ("toolpack", "openable", "item", "link", "commands", "command", "input", "reads", "writes", "refuse", "pin"):
            if kind.get(key) is not None:
                system[key] = kind[key]
        system["open"] = connection_scope(kind, server)
        out[alias] = system
    return {alias: system for alias, system in out.items() if alias not in (tools_policy.get("systems") or {})}


def type_scope(kind: Dict[str, Any], env: str) -> str:
    """How far Open to the agent may go for a connection of this type in this environment (1.7.38): the type's `open`; a type that has none and says `openable: true` is `all` in dev, ist and qat
    (the old word); a type that names its items (`item`, `link`) and says nothing is `items` (as before 1.7.38); else `no`. Prod is never opened."""
    if str(env).lower() == outside.PROD:
        return outside.NO
    if kind.get("open") is not None:
        return outside.scope_rule(kind["open"], env)
    if kind.get("openable") is True and str(env).lower() in ("dev", "ist", "qat"):
        return outside.ALL
    return outside.ITEMS if kind.get("item") and kind.get("link") else outside.NO  # a type from before 1.7.38 that names its items had the linked items opened by Open to the agent: it keeps that


def connection_scope(kind: Dict[str, Any], server: Dict[str, Any]) -> str:
    """The scope of one connection: its type's, lowered by the connection's own `open` when the company wrote one (1.7.38: a company can tighten, never loosen)."""
    env = str(server.get("env") or "")
    scope = type_scope(kind, env)
    if server.get("open") is not None:
        scope = outside.lower_scope(scope, outside.scope_rule(server["open"], env))
    return scope


def _host(address: Any) -> str:
    """The `host` or `host:port` of an address (`https://tfs.example.local/tfs` -> `tfs.example.local`); empty when there is none."""
    from urllib.parse import urlsplit

    text = str(address or "").strip()
    try:
        return (urlsplit(text if "//" in text else "//" + text).netloc.rpartition("@")[2]).lower()
    except ValueError:
        return ""


def widen(root: Path, systems: Dict[str, Any]) -> Dict[str, Any]:
    """A system that names `reach.also` = `{"type", "field"}` also owns every call to a host that a connection of that type has in that field (1.7.38, C11 T2-02): the `url` of an
    Azure DevOps connection is a host the system of `az rest` must guard like `dev.azure.com`. The host is added to `reach.when`; a system with no such connection is left as it is."""
    out = dict(systems)
    for name, system in systems.items():
        also = (system.get("reach") or {}).get("also") if isinstance(system, dict) else None
        if not isinstance(also, dict) or not system["reach"].get("when"):
            continue
        hosts = sorted({_host(server.get(str(also.get("field")))) for server in listed(root).values() if server.get("type") == also.get("type")} - {""})
        if hosts:
            found = "|".join(r"(?<![\w.-])" + re.escape(host) + r"(?![\w.-])" for host in hosts)  # not `host.evil.example`, not `evil-host`, not another port
            out[name] = dict(system, reach=dict(system["reach"], when=f"(?:{system['reach']['when']})|{found}"))
    return out


def serving(root: Path, system: Dict[str, Any]) -> List[str]:
    """The connections a system that is not a connection belongs to (1.7.38, C13 F2 U1): a tool pack's own system (`ado-web`, a web call to an Azure DevOps address) is reached with the identity of a connection of its type
    (`reach.also.type`), or else of the tool pack that wrote it. `[]` when it is no one's."""
    try:
        kinds, servers = types(root, guard=True), listed(root)
        wanted = str(((system.get("reach") or {}).get("also") or {}).get("type") or "")
        pack = str(system.get("toolpack") or "")
        return [alias for alias, server in servers.items() if (wanted and server.get("type") == wanted) or (not wanted and pack and str((kinds.get(str(server.get("type"))) or {}).get("toolpack") or "") == pack)]
    except Exception:  # noqa: BLE001 - a name for the text; the call is refused either way
        return []


def calls(root: Path, every: bool = False) -> List[Dict[str, Any]]:
    """How the agent reaches each server: `[{alias, env, call}]`, `call` being the server's test command (no password in it), with `harness as <alias> --`
    before it when this window reaches the server through the prefix. Only the servers the window was opened with, when it was opened from the board. With `every` (1.7.38) the others
    too, each with `away: True` and the prefix: `harness as` runs any connection that has a saved identity, whether or not the window was opened with it."""
    known, env, opened = types(root), read_env(root), state(root)
    wrapped, held = set(opened.get("wrap") or []), set(opened.get("direct") or []) | set(opened.get("wrap") or [])
    out = []
    for alias, server in listed(root).items():
        kind = known.get(str(server.get("type")))
        if not kind or kind.get("via") == "mcp" or type_problems(kind) or server.get("env") not in ENVS:
            continue
        away = bool(held) and alias not in held
        if away and not every:
            continue
        call = command(kind, server, identity_of(env, alias, kind, server), alias)
        out.append({"alias": alias, "env": server["env"], "call": f"harness as {alias} -- {call}" if alias in wrapped or away else call, **({"away": True} if away else {})})
    return out


def brief(root: Path, alias: str, call: str = "") -> Dict[str, Any]:
    """What an agent needs to use a connection that a prompt names (1.7.20): `{alias, env, type, label, fields, toolpack, skills, program, call}`. `fields` are the connection's own (org, project, ...), never the
    identity; `skills` and `program` come from the tool pack of the type; `call` is the test command, a way to see the program and its options only when no tool pack gives skills."""
    from . import toolpacks

    server = listed(root).get(alias) or {}
    kind = types(root).get(str(server.get("type"))) or {}
    fields = {field: str(server.get(field) if server.get(field) not in (None, "") else spec.get("default", "")) for field, spec in (kind.get("fields") or {}).items() if field not in SECRET_FIELDS and isinstance(spec, dict)}
    pack = str(kind.get("toolpack") or "")
    lost = toolpacks.missing_for(root, alias)
    folder = (toolpacks.installed(root).get(pack) or {}).get("folder") if pack else None
    put = (toolpacks.ledger(root)["packs"].get(pack) or {}).get("skills") or []  # the names in .github/skills/: the company's word leads them (1.7.30)
    skills = sorted(str(one) for one in put) or (sorted(item.name for item in (folder / "skills").iterdir() if item.is_dir()) if isinstance(folder, Path) and (folder / "skills").is_dir() else [])
    return {"alias": alias, "env": str(server.get("env") or ""), "type": str(server.get("type") or ""), "label": str(kind.get("label") or ""), "about": " ".join(str(server.get("about") or "").split()),
            "fields": {key: value for key, value in fields.items() if value}, "toolpack": pack, "skills": skills, "program": str((kind.get("cli") or [""])[0]), "call": call, "missing": lost,
            "signin": bool(_way(kind, server).get("identity") == "tool" and not identity_of(read_env(root), alias, kind, server))}


# --- finding a connection (1.7.38): what the agent is told, a little at a time ----------------------------------------------------------------------------

def _words(value: Any) -> List[str]:
    """`repos` and `domains` may be a list or one text with commas; the words of one field, as written."""
    items = value if isinstance(value, list) else str(value or "").split(",")
    return [str(item).strip() for item in items if str(item).strip()]


def kind_counts(root: Path, aliases: Optional[List[str]] = None) -> str:
    """Layer 0 (1.7.38): what kinds of connection there are and how many of each, in a few words (`3 SQL Server, 1 Azure DevOps`). Never a name: the agent finds one with `connections find`."""
    known = types(root)
    count: Dict[str, int] = {}
    for alias, server in listed(root).items():
        if aliases is not None and alias not in aliases:
            continue
        label = str((known.get(str(server.get("type"))) or {}).get("label") or server.get("type") or "?")
        count[label] = count.get(label, 0) + 1
    return ", ".join(f"{n} {label}" for label, n in count.items())


def describe(root: Path, alias: str, servers: Optional[Dict[str, Dict[str, Any]]] = None, kinds: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """What `find` knows of one connection: `{alias, type, type_label, env, label, about, repos, domains}` (the fields the company wrote for finding it; no secret, no sign-in)."""
    server = (listed(root) if servers is None else servers).get(alias) or {}
    kind = (types(root) if kinds is None else kinds).get(str(server.get("type"))) or {}
    return {"alias": alias, "type": str(server.get("type") or ""), "type_label": str(kind.get("label") or server.get("type") or ""), "env": str(server.get("env") or ""),
            "label": str(server.get("label") or ""), "about": " ".join(str(server.get("about") or "").split()), "repos": _words(server.get("repos")), "domains": _words(server.get("domains"))}


_TOKEN = re.compile(r"[a-z0-9]+")
_WORD = re.compile(r"[a-z0-9_]+")
ENV_WORDS = frozenset(("dev", "ist", "qat", "uat", "prod"))  # a word that names an environment fits an environment (or a name that has it as a word), never the start of another word (`dev` is not `devops`)


def _tokens(*texts: Any) -> List[str]:
    """The words of some texts, lower case; a word with underscores (a repository, `acme_etl_jobs`) is kept whole and also in its parts."""
    out: List[str] = []
    for text in texts:
        for word in _WORD.findall(str(text or "").lower()):
            out.append(word)
            out.extend(part for part in _TOKEN.findall(word) if part != word)
    return out


FIND_LIMIT = 5


def window_aliases(root: Path) -> List[str]:
    """Every connection the agent may reach (1.7.38, C12 FB-3): the ones this window was opened with and the others, which work through `harness as`. Layer 0 (the kinds and counts at the start of
    a chat) and layer 1 (`find`) both read this list, so they agree (C12 TB-07); `away_aliases` says which are not in the window."""
    return [one["alias"] for one in calls(root, every=True)]


def away_aliases(root: Path) -> List[str]:
    """The connections VS Code was not opened with (it was opened from the board, and these were left out, or signed in after): they are reached with `harness as <alias> -- <command>`."""
    return [one["alias"] for one in calls(root, every=True) if one.get("away")]


def find(root: Path, text: str, limit: int = FIND_LIMIT, aliases: Optional[List[str]] = None) -> Dict[str, Any]:
    """Layer 1 (1.7.38): the connections that fit some words (`sales warehouse dev`). A word fits when it is, or starts, a word of the name, the type, the sentence `about`, the label, the `repos` or
    the `domains` of a connection; an environment must be the word itself (`dev` is not `devops`). The connection that fits the most words comes first, then the name counts, then the order of the
    list. `{matches: [describe...], total, all, envs}`: `total` fitted, `all` connections there are. An environment word (`dev`, `ist`, `qat`, `prod`) filters (1.7.38, C12 TB-06): a connection of another
    environment is left out, even when it fits the other words; one with no environment (a ticket board) is kept when it fits another word. `envs`: the environments asked for. `aliases`: only these connections."""
    words = list(dict.fromkeys(_WORD.findall(str(text or "").lower())))
    asked = [word for word in words if word in ENVS and word != "none"]
    servers, kinds = listed(root), types(root)
    rows = [describe(root, alias, servers, kinds) for alias in servers if aliases is None or alias in aliases]
    scored = []
    for position, row in enumerate(rows):
        if asked and row["env"] not in ("", "none") and row["env"] not in asked:
            continue
        name, kind, env = _tokens(row["alias"]), _tokens(row["type"], row["type_label"]), _tokens(row["env"])
        other = _tokens(row["about"], row["label"], " ".join(row["repos"]), " ".join(row["domains"]))
        hit, weight = 0, 0
        for word in words:
            if word in ENV_WORDS:
                here = (3 if word in name else 0) or (2 if word in env else 0) or (1 if word in other else 0)
            else:
                fits = lambda tokens: any(token == word or (len(word) >= 3 and token.startswith(word)) for token in tokens)  # noqa: E731
                here = (3 if fits(name) else 0) or (2 if fits(kind) else 0) or (1 if fits(other) else 0)
            if here:
                hit, weight = hit + 1, weight + here
        if hit:
            scored.append((-hit, -weight, position, row))
    scored.sort(key=lambda item: item[:3])
    return {"matches": [item[3] for item in scored[:limit]], "total": len(scored), "all": len(rows), "envs": asked}


# --- a test of the way in ----------------------------------------------------------------------------------------------------------------------------------

def judge(kind: Dict[str, Any], code: Optional[int], output: str) -> Dict[str, str]:
    """What an answer of the test command says: ok (with the account the kind's `expect` caught), denied, down, failed."""
    if kind.get("denied") and re.search(kind["denied"], output or "", re.IGNORECASE):
        return {"state": "denied", "why": "identity", "who": ""}
    if code is None or (kind.get("down") and re.search(kind["down"], output or "", re.IGNORECASE)):
        return {"state": "down", "why": "no-answer" if code is not None or "no answer" in (output or "") else clip.words(output, 160), "who": ""}
    if code != 0:
        from .reach import first_line

        return {"state": "failed", "why": first_line(output) or f"exit-{code}", "who": ""}  # what the program said first (1.7.21)
    if kind.get("expect"):
        found = re.search(kind["expect"], output or "", re.MULTILINE)
        if not found:
            return {"state": "denied", "why": "other-identity", "who": ""}
        return {"state": "ok", "why": "", "who": (found.group(1).strip()[:80] if found.groups() and found.group(1) else "")}
    return {"state": "ok", "why": "", "who": ""}


def run_with(kind: Dict[str, Any], server: Dict[str, Any], identity: Dict[str, str], line: str, cwd: Path, timeout: float = TEST_SECONDS,
             launch: Optional[Dict[str, str]] = None, alias: str = "") -> Tuple[Optional[int], str]:
    """Run a command line with this identity: in the environment (env, keyfile) or with Windows network credentials (netonly). `launch`: what VS Code is
    started with (tool folders, CA bundle, 1.7.11), so a test finds what the agent will."""
    how = delivery(kind, server)
    extra = {**(launch or {}), **(connection_env(alias, kind, server, identity) if alias else {}), **variables(kind, server, identity)}
    if how["identity"] == "netonly":
        if not identity.get("account") or not identity.get("password"):
            return None, say("connections.test.no_identity")
        return netonly.run(identity["account"], identity["password"], line, cwd, extra, timeout)
    try:
        done = subprocess.run(line, shell=True, cwd=str(cwd), env={**os.environ, **extra}, capture_output=True, text=True, errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"no answer in {int(timeout)} s"
    except (OSError, ValueError) as error:
        return None, f"{type(error).__name__}: {error}"
    return done.returncode, (done.stdout + done.stderr)[:4000]


def missing_program(line: str, path: Optional[str] = None) -> bool:
    """The test's program is not on this computer (not on the PATH, or on `path`)."""
    import shutil

    first = shlex.split(line, posix=os.name != "nt")[0] if line.strip() else ""
    return bool(first) and shutil.which(first, path=path) is None


def given_identity(kind: Dict[str, Any], server: Dict[str, Any], given: Dict[str, str]) -> Dict[str, str]:
    """What the person typed, as an identity. A token identity has one secret: the form's password box (or `token`) is the token (1.7.21)."""
    out = {key: value for key, value in given.items() if key in IDENTITY_FIELDS and value}
    if delivery(kind, server)["identity"] == "token":
        token = out.pop("token", "") or out.pop("password", "")
        out = {"token": token} if token else {}
    return out


def test(root: Path, alias: str, given: Dict[str, str], server: Optional[Dict[str, Any]] = None, saved: bool = False) -> Dict[str, Any]:
    """Test the way in to a server with what the person typed (not saved yet), or with what is saved (`saved`, nothing typed). `{state, why, who, seconds}`; state ok, denied, down,
    failed, missing, mcp. A test that did not pass also carries `layers` (1.7.38): the first step that broke (program, sign-in, account access, address) and one sentence (`core.connlayers`)."""
    server = server or listed(root).get(alias)
    if not server:
        return {"state": "failed", "why": say("connections.unknown", alias=alias), "who": "", "seconds": 0}
    kind = types(root).get(str(server.get("type")))
    if not kind:
        return {"state": "failed", "why": say("connections.no_kind", kind=server.get("type")), "who": "", "seconds": 0}
    from . import connlayers, launchenv, toolpacks  # launchenv reads this module's .env

    if kind.get("via") == "mcp":  # VS Code runs the MCP server and holds its sign-in: nothing to test from here
        return {"state": "mcp", "why": say("connections.mcp.vscode"), "who": "", "seconds": 0}
    identity = given_identity(kind, server, given)
    if saved and not identity:
        identity = identity_of(read_env(root), alias, kind, server)
    how = delivery(kind, server)["identity"]
    line = command(kind, server, identity, alias)
    launch = launchenv.extra(root)
    path = next((value for key, value in launch.items() if key.upper() == "PATH"), None)
    lacking = ""
    if missing_program(line, path):
        lacking = shlex.split(line, posix=os.name != "nt")[0]
    else:
        lacking = next((one for one in toolpacks.signin_needs(kind, server) if not toolpacks.locate(one, path)), "")  # the program of the sign-in way (`az`) is needed too
    if lacking:
        no_run = toolpacks.blocked(lacking, path)  # there, but with no run bit (a zip that lost it): told in its own words, not as "not found"
        return {"state": "missing", "why": say("connections.test.blocked" if no_run else "connections.test.missing", program=lacking, path=no_run), "who": "", "seconds": 0,
                "layers": connlayers.classify(kind, server, alias, "missing", "", how, identity, program=lacking, blocked=no_run)}
    if how == "netonly" and not (identity.get("account") and identity.get("password")):  # a Windows account is typed first: nothing to run without it
        return {"state": "denied", "why": "no-identity", "who": "", "seconds": 0, "layers": connlayers.classify(kind, server, alias, "denied", "", how, {})}
    started = time.time()
    wait = test_seconds(kind, server)
    code, output = run_with(kind, server, identity, line, root, timeout=wait, launch=launch, alias=alias)
    timed = code is None and (output or "").startswith("no answer in ")  # the program was still running: told as a timeout with its limit, not as a failure
    found = {**judge(kind, code, output), "seconds": round(time.time() - started, 1), **({"timeout": int(wait)} if timed else {})}
    found["layers"] = connlayers.passed() if found["state"] == "ok" else connlayers.classify(kind, server, alias, found["state"], output or "", how, identity, why=found["why"], timeout=int(wait) if timed else 0)
    return found


def probe_keys(root: Path) -> List[str]:
    """The `reach` keys of the connections the board can check by itself: those with a command-line type whose sign-in the board can supply (a `tool` identity, or one kept here)."""
    known, env = types(root), read_env(root)
    out = []
    for alias, server in listed(root).items():
        kind = known.get(str(server.get("type")))
        if not kind or kind.get("via") == "mcp" or not kind.get("cli") or type_problems(kind) or server.get("env") not in ENVS:
            continue
        if delivery(kind, server)["identity"] != "tool" and not identity_of(env, alias, kind, server):
            continue  # VS Code may hold this identity (a launch script, a window opened with it): the board cannot see it, the first chat's hook does
        out.append(f"{alias}:{server['env']}")
    return out


def unsigned(root: Path) -> List[str]:
    """The connections with no sign-in kept here (1.7.38): a sign-in that has to be typed and is not saved. A program that keeps its own (`az`) is not among them. `harness doctor` names them in one line."""
    known, env = types(root), read_env(root)
    out = []
    for alias, server in listed(root).items():
        kind = known.get(str(server.get("type")))
        if not kind or kind.get("via") == "mcp" or not kind.get("cli") or type_problems(kind):
            continue
        if delivery(kind, server)["identity"] != "tool" and not identity_of(env, alias, kind, server):
            out.append(alias)
    return out


def probe_lines(root: Path, workers: int = 4) -> Dict[str, Dict[str, Any]]:
    """The board's own check of each connection (1.7.19), in the environment VS Code is started with (tool folders, CA bundle) and the identity kept here: `{<alias>:<env>: line}`, as `core.reach` keeps a line.
    It writes nothing: a caller that reports (`harness doctor`) uses this; the one that keeps the answer is `probe_all`. A probe that got no answer is run once more first, and its first line is kept as `said` (1.7.38)."""
    from concurrent.futures import ThreadPoolExecutor

    from . import launchenv, reach  # they read this module

    known, env, launch = types(root), read_env(root), launchenv.extra(root)
    wanted = set(probe_keys(root))
    jobs = [(alias, server, known[str(server["type"])]) for alias, server in listed(root).items() if f"{alias}:{server.get('env')}" in wanted]

    def one(job: Tuple[str, Dict[str, Any], Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
        alias, server, kind = job
        identity = identity_of(env, alias, kind, server)
        line = command(kind, server, identity, alias)
        needs = {key: kind[key] for key in ("expect", "denied", "down") if kind.get(key)}
        if missing_program(line, next((value for key, value in launch.items() if key.upper() == "PATH"), None)):
            answer = {"state": reach.FAILED, "why": "exit-127", "who": ""}
        else:
            answer = reach.judged(needs, lambda: run_with(kind, server, identity, line, root, timeout=test_seconds(kind, server), launch=launch, alias=alias))
        return f"{alias}:{server['env']}", {**answer, "at": utc_now(), "source": "probe"}

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(jobs) or 1))) as pool:
        return dict(pool.map(one, jobs))


def probe_all(root: Path, workers: int = 4) -> Dict[str, str]:
    """`probe_lines`, and the answer goes where the hook's probe puts it (`core.reach`): `{<alias>:<env>: state}`. Only the board's own check and the hook keep an answer; `harness doctor` does not."""
    from . import reach

    answers = probe_lines(root, workers)
    found = reach.read(root)  # read again: a hook may have written meanwhile
    found.update(answers)
    reach._write(root, found)  # noqa: SLF001
    return {key: line["state"] for key, line in answers.items()}


def login(root: Path, alias: str, own: Optional[Dict[str, Any]] = None) -> Tuple[int, str]:
    """Run the sign-in command of a server whose program keeps its own (`auth.login` of a `tool` identity: `az login`), here, with the tool folders and
    the CA bundle VS Code gets (1.7.13). Its output streams to this terminal; the sign-in itself happens in the program's own browser window."""
    from . import launchenv  # it reads this module's .env

    server = own or listed(root).get(alias)  # `own`: a server of the person's own not saved yet (its sign-in comes before its test)
    if not server and not own:  # 1.7.37: the name of a program (`az`): its sign-in needs no connection
        for name, found in types(root).items():
            for mode, program in tool_ways(found):
                if program == alias.lower():
                    server = {"type": name, "auth": mode}
    kind = types(root).get(str((server or {}).get("type")))
    if not server or not kind:
        return 2, say("connections.unknown", alias=alias)
    modes = kind.get("auth") or {}
    auth = modes.get(server.get("auth") or next(iter(modes), "")) or {}
    if auth.get("identity") != "tool" or not auth.get("login"):
        return 2, say("connections.login.none", alias=alias)
    values = {field: _quote(str(server.get(field) if server.get(field) not in (None, "") else spec.get("default", ""))) for field, spec in (kind.get("fields") or {}).items()}
    line = _fill(str(auth["login"]), values)
    launch = launchenv.extra(root)
    path = next((value for key, value in launch.items() if key.upper() == "PATH"), None)
    if missing_program(line, path):  # say it in words before the shell says `Permission denied` or `not found` with a code (1.7.38)
        from . import toolpacks

        program = shlex.split(line, posix=os.name != "nt")[0]
        no_run = toolpacks.blocked(program, path)
        return 126 if no_run else 127, say("connections.login.blocked" if no_run else "connections.login.missing", program=program, path=no_run)
    return subprocess.run(line, shell=True, cwd=str(root), env={**os.environ, **launch}).returncode, ""  # noqa: S602 - the kind's own sign-in, started by the person


def save(root: Path, alias: str, given: Dict[str, str], own: Optional[Dict[str, Any]] = None, who: str = "") -> None:
    """Keep what passed the test in the `.env`. `own`: a server of the person's own (its kind, env, auth and fields) is kept with it. `who`: the name the test
    answered; for a `tool` identity it is all that is kept, to show (the program holds the sign-in)."""
    server = own or listed(root).get(alias) or {}
    kind = types(root).get(str(server.get("type"))) or {}
    given = given_identity(kind, server, given)
    changes: Dict[str, Optional[str]] = {env_key(alias, key): (given.get(key) or None) for key in IDENTITY_FIELDS}
    if kind and delivery(kind, server)["identity"] == "tool":
        program = tool_program(_way(kind, server))
        changes = {env_key(alias, "account"): None, env_key(alias, "password"): None, env_key(alias, "keyfile"): None, env_key(alias, "token"): None}
        if program:  # one per program, shared by every connection of the type (1.7.37)
            changes[tool_key(program)] = who or say("connections.tool.signed")
        else:
            changes[env_key(alias, "account")] = who or say("connections.tool.signed")
    if own:
        changes[env_key(alias, "alias")] = alias
        changes.update({env_key(alias, key): str(value) for key, value in own.items() if key not in ("own",) and value not in (None, "")})
    write_env(root, changes)


def keep_untested(root: Path, alias: str, found: Dict[str, Any], given: Dict[str, str]) -> bool:
    """A sign-in whose test never reached the system is kept, marked "not tested yet" (1.7.38). It broke at the program or at the address: nothing says the account is wrong, and the person would
    have to type it again after fixing a certificate or a proxy. A sign-in that broke at the sign-in or at the account access is not kept (it is wrong), nor one that broke for a reason no step
    can name. 1.7.38 (C13 D3-1): a test that got no answer in time counts as not reaching the server: nothing says the account is wrong, so it is kept too, and the row says "no answer". Nothing typed (a
    program keeps its own sign-in) means nothing to keep. True when it was kept."""
    from . import reach

    server = listed(root).get(alias)
    kind = types(root).get(str((server or {}).get("type")))
    slow = bool(found.get("timeout"))  # the program was still running at the limit (a `down` answer the program printed itself is the address's: the layers say so)
    if not server or not kind or found.get("state") in ("ok", "mcp") or ((found.get("layers") or {}).get("broken") not in ("program", "address") and not slow):
        return False
    if delivery(kind, server)["identity"] == "tool" or not given_identity(kind, server, given):
        return False
    save(root, alias, given)
    reach.record(root, f"{alias}:{server.get('env', '')}", reach.UNKNOWN, UNTESTED_SLOW if slow else UNTESTED)
    return True


def identity_lacks(root: Path) -> List[str]:
    """(1.7.38, C13 D3-3) The connections whose identity must be in the environment of the VS Code window (variables, or a Windows account the window holds) and that the window was not started with: it is
    saved here, and the last start from the board did not carry it (`direct`) nor route it through `harness as` (`wrap`). Such a connection is no reason for VS Code to be "wrong": the agent reaches it
    with `harness as`, and Restart with identities carries it. A connection whose program reads its own sign-in or token (`ado`: a `tool` identity, or a token the program reads itself) needs nothing from the window and
    is not listed. Names, in the order of the list."""
    opened = state(root)
    held = set(opened.get("direct") or []) | set(opened.get("wrap") or [])
    known, env = types(root), read_env(root)
    out: List[str] = []
    for alias, server in listed(root).items():
        kind = known.get(str(server.get("type")))
        if not kind or alias in held or kind.get("via") == "mcp" or not kind.get("cli") or type_problems(kind):
            continue
        how = delivery(kind, server)["identity"]
        identity = identity_of(env, alias, kind, server)
        if how == "tool" or not identity:
            continue
        if how != "netonly" and not variables(kind, server, identity):
            continue
        out.append(alias)
    return out


def forget_tool(root: Path, program: str) -> None:
    """Take the shared sign-in of a program out of the `.env` (and the old per-connection accounts of the connections that used it)."""
    known, env = types(root), read_env(root)
    changes: Dict[str, Optional[str]] = {tool_key(program): None}
    for alias, server in listed(root).items():
        auth = _way(known.get(str(server.get("type"))) or {}, server)
        if auth.get("identity") == "tool" and tool_program(auth) == program.lower():
            changes[env_key(alias, "account")] = None
    write_env(root, {key: value for key, value in changes.items() if key in env})


def signins(root: Path) -> Dict[str, Any]:
    """What the Sign-ins block shows (1.7.37). A connection does not depend on a sign-in. A sign-in hangs on a connection or on a tool, never alone:
    `tools` one row per program that keeps its own sign-in (`az`), shared by the connections of its type; `connections` one row for each connection that
    is signed in another way (token, password, account), `state` none or saved (and what the last check said); `orphans` an identity kept for a connection
    this copy no longer has, which only the person forgets."""
    from . import reach, toolpacks

    known, env, seen = types(root), read_env(root), reach.read(root)
    servers = listed(root)
    on = toolpacks.active(root)
    tools: Dict[str, Dict[str, Any]] = {}
    for name, kind in known.items():
        if kind.get("toolpack") not in on or type_problems(kind):
            continue
        for mode, program in tool_ways(kind):
            row = tools.setdefault(program, {"program": program, "account": env.get(tool_key(program), ""), "shared_by": [], "login": (kind["auth"][mode] or {}).get("login", ""), "types": []})
            if kind.get("label", name) not in row["types"]:
                row["types"].append(kind.get("label", name))
    rows = []
    for alias, server in servers.items():
        kind = known.get(str(server.get("type"))) or {}
        auth = _way(kind, server)
        if kind.get("via") == "mcp":
            continue
        if auth.get("identity") == "tool" and tool_program(auth):
            row = tools.setdefault(tool_program(auth), {"program": tool_program(auth), "account": env.get(tool_key(tool_program(auth)), ""), "shared_by": [], "login": auth.get("login", ""), "types": []})
            row["shared_by"].append(alias)
            if not row["account"] and env.get(env_key(alias, "account")):  # the old per-connection account is read still
                row["account"] = env[env_key(alias, "account")]
            continue
        saved = identity_of(env, alias, kind, server)
        line = seen.get(f"{alias}:{server.get('env', '')}") or {}
        rows.append({"alias": alias, "env": server.get("env", ""), "type": server.get("type", ""), "type_label": kind.get("label", server.get("type", "")), "own": bool(server.get("own")),
                     "identity": auth.get("identity", ""), "auth_label": auth.get("label", ""), "account": saved.get("account", ""), "state": "saved" if saved else "none",
                     "reach": line.get("state", "")})
    stems = {env_key(alias, "") for alias in servers}
    orphans: Dict[str, str] = {}
    for key, value in env.items():
        if key.startswith(PREFIX) and key.endswith(tuple("_" + one.upper() for one in IDENTITY_FIELDS)):
            stem = key[: key.rindex("_") + 1]
            if stem not in stems:
                orphans.setdefault(stem[len(PREFIX):-1].lower().replace("_", "-"), value if key.endswith("_ACCOUNT") else "")
    return {"tools": sorted(tools.values(), key=lambda one: one["program"]), "connections": rows, "orphans": [{"name": name, "account": account} for name, account in sorted(orphans.items())]}


def share(root: Path, aliases: List[str]) -> Dict[str, Any]:
    """Put connections of one's own in the company pack (`<knowledge base>/company/tools/connections.json`): the connection only, never an account or a
    password, and its tool pack too when the company pack has none of that name. Then the company content is synced, so the connection is the company's
    here as well; the identity saved for it stays in `.env` under the same name. The person commits the knowledge base and packs it as usual."""
    from . import company, targets, toolpacks  # company imports this module

    folder = targets.company_folder(root)
    if folder is None:
        raise ValueError(say("connections.share.none"))
    path = folder / company.TOOLS_DIR / company.CONNECTIONS_FILE
    try:
        found = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
    except (OSError, ValueError):
        raise ValueError(say("connections.share.bad", path=str(path))) from None
    if not isinstance(found, dict) or not isinstance(found.get("connections", {}), dict):
        raise ValueError(say("connections.share.bad", path=str(path)))
    listed_now, here, known = found.setdefault("connections", {}), listed(root), types(root)
    added, packs_added = [], []
    for alias in aliases:
        entry = here.get(alias)
        if not entry or not entry.get("own"):
            raise ValueError(say("connections.share.notown", alias=alias))
        if alias in listed_now:
            raise ValueError(say("connections.share.taken", alias=alias))
        listed_now[alias] = {key: value for key, value in entry.items() if key != "own" and key not in IDENTITY_FIELDS}
        added.append(alias)
        pack = str((known.get(str(entry.get("type"))) or {}).get("toolpack") or "")
        if pack and toolpacks.share(root, folder, pack):  # a factory pack goes into `use`; a folder added here is copied to packs/<name>/
            packs_added.append(pack)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(found, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    synced = company.sync_after(root) or {}
    return {"shared": added, "file": str(path), "toolpacks": packs_added, "sync_error": synced.get("error", ""), "next": say("connections.share.done")}


def export(root: Path, names: Optional[List[str]] = None) -> Dict[str, Any]:
    """The person's own connections in the form of `connections.json` (contracts/toolpack/connections.md), to put in the company pack or a file. Never an
    account, a password or a key file."""
    picked = {alias: {key: value for key, value in entry.items() if key not in ("own", "alias") + IDENTITY_FIELDS}
              for alias, entry in listed(root).items() if entry.get("own") and (not names or alias in names)}
    return {"connections": picked}


def forget(root: Path, alias: str) -> None:
    """Take a server's identity (and, for one of the person's own, the server) out of the `.env`."""
    stem = env_key(alias, "")
    write_env(root, {key: None for key in read_env(root) if key.startswith(stem)})


# --- one window, several identities -----------------------------------------------------------------------------------------------------------------------

def state(root: Path) -> Dict[str, Any]:
    """The identities of the VS Code that was opened last from the board: `{at, direct, wrap, primary}`."""
    try:
        found = json.loads((root / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def plan(root: Path, chosen: List[str], primary: str = "") -> Dict[str, Any]:
    """Which of the chosen identities this window holds itself (`direct`) and which go through `harness as` (`wrap`): one Windows account per window
    (the `primary`, else the first), one value per variable (the first that wants it). `missing`: chosen with nothing saved."""
    servers, known, env = listed(root), types(root), read_env(root)
    direct: List[str] = []
    wrap: List[str] = []
    missing: List[str] = []
    taken: Dict[str, str] = {}
    windows = ""
    order = sorted(chosen, key=lambda alias: alias != primary)
    for alias in order:
        server = servers.get(alias)
        kind = known.get(str((server or {}).get("type")))
        if not server or not kind:
            continue
        identity = identity_of(env, alias, kind, server)
        if not identity:
            missing.append(alias)
            continue
        how = delivery(kind, server)
        values = variables(kind, server, identity)
        clash = any(var in taken and taken[var] != value for var, value in values.items())
        if how["identity"] == "netonly":
            clash = clash or bool(windows and windows != identity.get("account", "").lower())
        if clash:
            wrap.append(alias)
            continue
        direct.append(alias)
        taken.update(values)
        if how["identity"] == "netonly":
            windows = identity.get("account", "").lower()
    return {"direct": direct, "wrap": wrap, "missing": missing, "primary": next((alias for alias in direct if delivery(known[servers[alias]["type"]], servers[alias])["identity"] == "netonly"), "")}


def launch(root: Path, chosen: List[str], primary: str, code_argv: List[str]) -> Dict[str, Any]:
    """Open VS Code with the chosen identities and keep which are wrapped for its chat. The caller made sure no VS Code of this folder is open."""
    planned = plan(root, chosen, primary)
    servers, known, env = listed(root), types(root), read_env(root)
    from . import launchenv  # it reads this module's .env

    extra: Dict[str, str] = launchenv.extra(root)  # tool folders and the CA bundle (1.7.11)
    for alias in planned["direct"]:
        kind, server = known[servers[alias]["type"]], servers[alias]
        extra.update(variables(kind, server, identity_of(env, alias, kind, server)))
    target = root / STATE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"at": utc_now(), "direct": planned["direct"], "wrap": planned["wrap"], "primary": planned["primary"]}, indent=2), encoding="utf-8")
    argv = (["cmd.exe", "/c", *code_argv] if os.name == "nt" and str(code_argv[0]).lower().endswith((".cmd", ".bat")) else code_argv)
    if planned["primary"]:
        identity = identity_of(env, planned["primary"], known[servers[planned["primary"]]["type"]])
        if not netonly.start(identity["account"], identity["password"], argv, root, extra):
            return {**planned, "started": False, "why": say("connections.netonly.windows")}
    else:
        subprocess.Popen(argv, cwd=str(root), env={**os.environ, **extra}, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,  # noqa: S603
                         start_new_session=os.name != "nt", close_fds=True)
    return {**planned, "started": True}


# --- harness as <alias> -- <command> ----------------------------------------------------------------------------------------------------------------------

def _swap(word: str, own: Dict[str, str]) -> str:
    """One word of a command with the window's value of each of this server's variables replaced by the server's own (only a value of 4 characters or more, so a short one is not found by chance)."""
    for name, value in own.items():
        window = os.environ.get(name, "")
        if window and value and window != value and len(window) >= 4:
            word = word.replace(window, value)
    return word


def run_as(root: Path, alias: str, argv: List[str], classify: Callable[[str], List[Tuple[Any, str]]]) -> Tuple[int, str]:
    """Run one command of a server with that server's saved identity. Refused (exit 2) when the command is not a call of that server: the identity is for
    its own commands, never for `echo`, `env` or another program. `classify`: the gate's reading of a command line (system, env, verb)."""
    line = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    servers, known = listed(root), types(root)
    server = servers.get(alias)
    kind = known.get(str((server or {}).get("type")))
    if not server or not kind:
        return 2, say("connections.unknown", alias=alias)
    found = classify(line)
    if not found or any(action.system != alias for action, _decision in found):
        return 2, say("connections.as.other", alias=alias)
    identity = identity_of(read_env(root), alias, kind, server)
    if not identity:
        return 2, say("connections.as.none", alias=alias)
    own = variables(kind, server, identity)
    swapped = [_swap(word, own) for word in argv]  # the window's shell put its own value of a variable in the line ($TOKEN, $env:TOKEN, %TOKEN%): this server's goes there
    if swapped != argv:
        argv = swapped
        line = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    if delivery(kind, server)["identity"] != "netonly":  # the output streams to the terminal as it comes
        return subprocess.run(line, shell=True, env={**os.environ, **variables(kind, server, identity)}).returncode, ""  # noqa: S602 - the agent's own command, judged by the gate
    code, output = run_with(kind, server, identity, line, Path.cwd(), timeout=3600)
    return (code if code is not None else 1), output
