"""Servers and the person's identities for them (1.7.10). The harness knows no kind of server: a kind is a file.

Three layers, each with one owner:

  kinds       `.harness/kinds/<kind>.json`, copied from the company pack (`company/tools/kinds/`) by `company sync`. What a server of that kind needs
              (fields), how an identity reaches its commands (`auth`: env, netonly, keyfile), the command that tests the way in, the words of its answer
              (`expect`, `denied`, `down`), and for the gate the programs (`cli`), how a command names one server (`match`) and the verbs and rules.
  servers     `.harness/policies/servers.company.json` (from `company/tools/servers.json`): `{"servers": {alias: {kind, env, auth, <fields>}}}`. The
              person's own servers live in `.harness/.env` with their identities.
  identities  `.harness/.env`: `HARNESS_SERVER_<ALIAS>_<FIELD>=value`, written by Get ready after a test passed. Never in git, a log, a page or the
              knowledge base; `reinstall` carries it; the gate refuses the agent a read of it.

Each server becomes a system of the tools policy (`derived`): the gate judges its commands, the reach check probes it, with nothing written by hand.
When VS Code is opened, the person picks the identities for that window (`plan`, `launch`); those that cannot share it (two Windows accounts, two
identities that want the same variable) are reached through `harness as <alias> -- <command>` (`wrapped`), each command with its own identity.
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

from . import messages, netonly
from .paths import utc_now

KINDS_DIR = Path(".harness") / "kinds"
SERVERS_POLICY = "servers"
ENV_FILE = Path(".harness") / ".env"
STATE_FILE = Path(".harness") / "runtime" / "state" / "identities.json"
PREFIX = "HARNESS_SERVER_"
ALIAS = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
IDENTITIES = ("env", "netonly", "keyfile", "tool")  # tool (1.7.13): the program keeps its own sign-in (`az login`); the harness keeps no account, only who the test answered
SECRET_FIELDS = ("password",)
OWN_FIELDS = ("kind", "env", "auth", "label")  # what a server of the person's own has besides the kind's fields
TEST_SECONDS = 15
ENVS = ("dev", "ist", "qat", "prod", "none")  # none (1.7.13): a ticket board or a pipeline service, which has no environments


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


# --- kinds ------------------------------------------------------------------------------------------------------------------------------------------------

def kinds(root: Path) -> Dict[str, Dict[str, Any]]:
    """Every kind this copy knows, `{name: kind}`; a file that cannot be read is left out (`problems` says why)."""
    from . import connectors  # it reads this module for its checks

    found: Dict[str, Dict[str, Any]] = {}
    folder = root / KINDS_DIR
    own = sorted(folder.glob("*.json")) if folder.is_dir() else []
    for path in own + connectors.kind_files(root):  # the company's kinds first: a connector's kind of the same name does not replace one (1.7.12)
        try:
            kind = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if path not in own and isinstance(kind, dict):
            kind = dict(kind, connector=path.parent.parent.name)  # its servers' systems are the connector's: Open to the agent leaves them closed
        if isinstance(kind, dict) and kind.get("kind") and str(kind["kind"]) not in found:
            found[str(kind["kind"])] = kind
    return found


def kind_problems(kind: Dict[str, Any]) -> List[str]:
    """What is wrong with a kind file; empty when it is fine."""
    name = kind.get("kind", "?")
    out = []
    if not isinstance(kind.get("fields"), dict) or not kind["fields"]:
        out.append(f"kinds.{name}: `fields` names what a server of this kind needs (host, port, ...)")
    if not isinstance(kind.get("auth"), dict) or not kind["auth"]:
        out.append(f"kinds.{name}: `auth` names at least one way in")
    for mode, auth in (kind.get("auth") or {}).items():
        if not isinstance(auth, dict) or auth.get("identity") not in IDENTITIES:
            out.append(f"kinds.{name}.auth.{mode}: `identity` is one of {', '.join(IDENTITIES)}")
    if not kind.get("test"):
        out.append(f"kinds.{name}: `test` is the command that tests the way in")
    texts = [kind.get("test") or "", kind.get("match") or ""] + [str((auth or {}).get("args") or "") for auth in (kind.get("auth") or {}).values()]
    if any("{password}" in text for text in texts):
        out.append(f"kinds.{name}: a password never goes on a command line; give it through `env` of the auth")
    for key in ("expect", "denied", "down", "match"):
        try:
            re.compile(_fill(kind.get(key) or "", {}, escape=True) if key == "match" else kind.get(key) or "")
        except re.error as error:
            out.append(f"kinds.{name}.{key}: bad pattern: {error}")
    return out


# --- the .env file ----------------------------------------------------------------------------------------------------------------------------------------

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
        lines = [say("servers.env.head")]
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

def company_servers(policy: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    found = policy.get("servers") if isinstance(policy.get("servers"), dict) else {}
    return {str(alias): dict(item) for alias, item in found.items() if isinstance(item, dict)}


def own_servers(env: Dict[str, str], known: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The person's own servers, from the `.env`: each has an `..._ALIAS` line, and its fields beside it."""
    out: Dict[str, Dict[str, Any]] = {}
    for key, value in env.items():
        if key.startswith(PREFIX) and key.endswith("_ALIAS") and ALIAS.match(value):
            stem = key[: -len("ALIAS")]
            out[value] = {field[len(stem):].lower(): item for field, item in env.items() if field.startswith(stem) and field != key and not field.endswith(("_ACCOUNT", "_PASSWORD", "_KEYFILE"))}
            out[value]["own"] = True
    return {alias: item for alias, item in out.items() if alias not in known}


def listed(root: Path, policy: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Every server: the company's, then the person's own. `{alias: {kind, env, auth, <fields>, own?}}`."""
    from . import config  # config imports this module to derive the systems

    policy = config.policy_or_empty(root, SERVERS_POLICY) if policy is None else policy
    found = company_servers(policy)
    found.update(own_servers(read_env(root), found))
    return found


def identity_of(env: Dict[str, str], alias: str, kind: Dict[str, Any]) -> Dict[str, str]:
    """What the person saved for this server: account, password, keyfile (what is there)."""
    return {field: env[env_key(alias, field)] for field in ("account", "password", "keyfile") if env.get(env_key(alias, field))}


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


def command(kind: Dict[str, Any], server: Dict[str, Any], identity: Dict[str, str]) -> str:
    """The test command of a server with this identity, ready to run (the password never in it)."""
    auth = (kind.get("auth") or {}).get(server.get("auth") or next(iter(kind.get("auth") or {"": {}})), {}) or {}
    values = {**{field: (server.get(field) if server.get(field) not in (None, "") else spec.get("default", "")) for field, spec in (kind.get("fields") or {}).items()},
              "account": identity.get("account", ""), "keyfile": identity.get("keyfile", "")}
    quoted = {key: _quote(str(value)) for key, value in values.items()}
    quoted["auth"] = _fill(str(auth.get("args") or ""), quoted)
    return " ".join(_fill(kind["test"], quoted).split())


def delivery(kind: Dict[str, Any], server: Dict[str, Any]) -> Dict[str, Any]:
    """How an identity reaches this server's commands: `{identity, env: {VAR: field}}`."""
    modes = kind.get("auth") or {}
    auth = modes.get(server.get("auth") or next(iter(modes), "")) or {}
    return {"identity": auth.get("identity", "env"), "env": dict(auth.get("env") or {})}


def variables(kind: Dict[str, Any], server: Dict[str, Any], identity: Dict[str, str]) -> Dict[str, str]:
    """The environment variables that carry this identity (`env` and `keyfile` delivery)."""
    return {var: identity.get(field, "") for var, field in delivery(kind, server)["env"].items() if identity.get(field)}


# --- the gate's view: a system per server -----------------------------------------------------------------------------------------------------------------

def derived(root: Path, tools_policy: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """A system of the tools policy for every server whose kind tells the gate how to see it (`cli`, `match`). A system written by hand with the same name wins."""
    known, env, wrapped = kinds(root), read_env(root), set(state(root).get("wrap") or [])
    out: Dict[str, Dict[str, Any]] = {}
    for alias, server in listed(root).items():
        kind = known.get(str(server.get("kind")))
        if not kind or not kind.get("cli") or not kind.get("match") or kind_problems(kind) or server.get("env") not in ENVS:
            continue
        values = {field: (server.get(field) if server.get(field) not in (None, "") else spec.get("default", "")) for field, spec in kind["fields"].items()}
        probe = command(kind, server, identity_of(env, alias, kind))
        if alias in wrapped:
            probe = f"{_quote(sys.executable)} {_quote(str(root / '.harness' / 'engine' / 'cli.py'))} as {alias} -- {probe}"
        system: Dict[str, Any] = {
            "reach": {"cli": kind["cli"], "when": _fill(kind["match"], values, escape=True)},
            "env": server["env"],
            "needs": {"probes": {server["env"]: probe}, "launch": say("servers.launch", alias=alias)},
        }
        for key in ("expect", "denied", "down"):
            if kind.get(key):
                system["needs"][key] = kind[key]
        for key in ("verbs", "target", "show", "rules"):
            if server.get(key) if key == "rules" else kind.get(key):
                system[key] = server[key] if key == "rules" and server.get(key) else kind[key]
        for key in ("connector", "openable"):
            if kind.get(key) is not None:
                system[key] = kind[key]
        out[alias] = system
    return {alias: system for alias, system in out.items() if alias not in (tools_policy.get("systems") or {})}


def calls(root: Path) -> List[Dict[str, str]]:
    """How the agent reaches each server: `[{alias, env, call}]`, `call` being the server's test command (no password in it), with `harness as <alias> --`
    before it when this window reaches the server through the prefix. Only the servers the window was opened with, when it was opened from the board."""
    known, env, opened = kinds(root), read_env(root), state(root)
    wrapped, held = set(opened.get("wrap") or []), set(opened.get("direct") or []) | set(opened.get("wrap") or [])
    out = []
    for alias, server in listed(root).items():
        kind = known.get(str(server.get("kind")))
        if not kind or kind_problems(kind) or server.get("env") not in ENVS or (held and alias not in held):
            continue
        call = command(kind, server, identity_of(env, alias, kind))
        out.append({"alias": alias, "env": server["env"], "call": f"harness as {alias} -- {call}" if alias in wrapped else call})
    return out


# --- a test of the way in ----------------------------------------------------------------------------------------------------------------------------------

def judge(kind: Dict[str, Any], code: Optional[int], output: str) -> Dict[str, str]:
    """What an answer of the test command says: ok (with the account the kind's `expect` caught), denied, down, failed."""
    if kind.get("denied") and re.search(kind["denied"], output or "", re.IGNORECASE):
        return {"state": "denied", "why": "identity", "who": ""}
    if code is None or (kind.get("down") and re.search(kind["down"], output or "", re.IGNORECASE)):
        return {"state": "down", "why": "no-answer" if code is not None or "no answer" in (output or "") else (output or "")[:160], "who": ""}
    if code != 0:
        return {"state": "failed", "why": f"exit-{code}", "who": ""}
    if kind.get("expect"):
        found = re.search(kind["expect"], output or "", re.MULTILINE)
        if not found:
            return {"state": "denied", "why": "other-identity", "who": ""}
        return {"state": "ok", "why": "", "who": (found.group(1).strip()[:80] if found.groups() and found.group(1) else "")}
    return {"state": "ok", "why": "", "who": ""}


def run_with(kind: Dict[str, Any], server: Dict[str, Any], identity: Dict[str, str], line: str, cwd: Path, timeout: float = TEST_SECONDS,
             launch: Optional[Dict[str, str]] = None) -> Tuple[Optional[int], str]:
    """Run a command line with this identity: in the environment (env, keyfile) or with Windows network credentials (netonly). `launch`: what VS Code is
    started with (tool folders, CA bundle, 1.7.11), so a test finds what the agent will."""
    how = delivery(kind, server)
    extra = {**(launch or {}), **variables(kind, server, identity)}
    if how["identity"] == "netonly":
        if not identity.get("account") or not identity.get("password"):
            return None, say("servers.test.no_identity")
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


def test(root: Path, alias: str, given: Dict[str, str], server: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Test the way in to a server with what the person typed (not saved yet). `{state, why, who, seconds}`; state ok, denied, down, failed, missing."""
    server = server or listed(root).get(alias)
    if not server:
        return {"state": "failed", "why": say("servers.unknown", alias=alias), "who": "", "seconds": 0}
    kind = kinds(root).get(str(server.get("kind")))
    if not kind:
        return {"state": "failed", "why": say("servers.no_kind", kind=server.get("kind")), "who": "", "seconds": 0}
    from . import launchenv  # it reads this module's .env

    identity = {key: value for key, value in given.items() if key in ("account", "password", "keyfile") and value}
    line = command(kind, server, identity)
    launch = launchenv.extra(root)
    if missing_program(line, next((value for key, value in launch.items() if key.upper() == "PATH"), None)):
        return {"state": "missing", "why": say("servers.test.missing", program=shlex.split(line, posix=os.name != "nt")[0]), "who": "", "seconds": 0}
    started = time.time()
    code, output = run_with(kind, server, identity, line, root, launch=launch)
    return {**judge(kind, code, output), "seconds": round(time.time() - started, 1)}


def login(root: Path, alias: str, own: Optional[Dict[str, Any]] = None) -> Tuple[int, str]:
    """Run the sign-in command of a server whose program keeps its own (`auth.login` of a `tool` identity: `az login`), here, with the tool folders and
    the CA bundle VS Code gets (1.7.13). Its output streams to this terminal; the sign-in itself happens in the program's own browser window."""
    from . import launchenv  # it reads this module's .env

    server = own or listed(root).get(alias)  # `own`: a server of the person's own not saved yet (its sign-in comes before its test)
    kind = kinds(root).get(str((server or {}).get("kind")))
    if not server or not kind:
        return 2, say("servers.unknown", alias=alias)
    modes = kind.get("auth") or {}
    auth = modes.get(server.get("auth") or next(iter(modes), "")) or {}
    if auth.get("identity") != "tool" or not auth.get("login"):
        return 2, say("servers.login.none", alias=alias)
    values = {field: _quote(str(server.get(field) if server.get(field) not in (None, "") else spec.get("default", ""))) for field, spec in (kind.get("fields") or {}).items()}
    return subprocess.run(_fill(str(auth["login"]), values), shell=True, cwd=str(root), env={**os.environ, **launchenv.extra(root)}).returncode, ""  # noqa: S602 - the kind's own sign-in, started by the person


def save(root: Path, alias: str, given: Dict[str, str], own: Optional[Dict[str, Any]] = None, who: str = "") -> None:
    """Keep what passed the test in the `.env`. `own`: a server of the person's own (its kind, env, auth and fields) is kept with it. `who`: the name the test
    answered; for a `tool` identity it is all that is kept, to show (the program holds the sign-in)."""
    changes: Dict[str, Optional[str]] = {env_key(alias, key): (given.get(key) or None) for key in ("account", "password", "keyfile")}
    server = own or listed(root).get(alias) or {}
    kind = kinds(root).get(str(server.get("kind"))) or {}
    if kind and delivery(kind, server)["identity"] == "tool":
        changes = {env_key(alias, "account"): (who or say("servers.tool.signed")), env_key(alias, "password"): None, env_key(alias, "keyfile"): None}
    if own:
        changes[env_key(alias, "alias")] = alias
        changes.update({env_key(alias, key): str(value) for key, value in own.items() if key not in ("own",) and value not in (None, "")})
    write_env(root, changes)


def share(root: Path, aliases: List[str]) -> Dict[str, Any]:
    """Put servers of one's own in the company pack (`<knowledge base>/company/tools/servers.json`): the server only, never an account or a password, and
    the kind file too when the pack has none. Then the company content is synced, so the server is the company's here as well; the identity saved for it
    stays in `.env` under the same alias. The person commits the knowledge base and packs it for colleagues as usual."""
    from . import company, targets  # company imports this module

    folder = targets.company_folder(root)
    if folder is None:
        raise ValueError(say("servers.share.none"))
    path = folder / company.TOOLS_DIR / company.SERVERS_FILE
    try:
        found = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
    except (OSError, ValueError):
        raise ValueError(say("servers.share.bad", path=str(path))) from None
    if not isinstance(found, dict) or not isinstance(found.get("servers", {}), dict):
        raise ValueError(say("servers.share.bad", path=str(path)))
    listed_now, here = found.setdefault("servers", {}), listed(root)
    added, kinds_added = [], []
    for alias in aliases:
        server = here.get(alias)
        if not server or not server.get("own"):
            raise ValueError(say("servers.share.notown", alias=alias))
        if alias in listed_now:
            raise ValueError(say("servers.share.taken", alias=alias))
        listed_now[alias] = {key: value for key, value in server.items() if key != "own" and key not in ("account", "password", "keyfile")}
        added.append(alias)
        kind = str(server.get("kind"))
        target = folder / company.TOOLS_DIR / company.KINDS_DIR
        if not any(_kind_name(item) == kind for item in target.glob("*.json")):  # a folder that is not there globs nothing
            source = next((item for item in sorted((root / KINDS_DIR).glob("*.json")) if _kind_name(item) == kind), None)
            if source is not None:
                target.mkdir(parents=True, exist_ok=True)
                (target / source.name).write_bytes(source.read_bytes())
                kinds_added.append(source.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(found, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    synced = company.sync_after(root) or {}
    return {"shared": added, "file": str(path), "kinds": kinds_added, "sync_error": synced.get("error", ""), "next": say("servers.share.done")}


def _kind_name(path: Path) -> str:
    try:
        return str(json.loads(path.read_text(encoding="utf-8-sig")).get("kind", ""))
    except (OSError, ValueError, AttributeError):
        return ""


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
    servers, known, env = listed(root), kinds(root), read_env(root)
    direct: List[str] = []
    wrap: List[str] = []
    missing: List[str] = []
    taken: Dict[str, str] = {}
    windows = ""
    order = sorted(chosen, key=lambda alias: alias != primary)
    for alias in order:
        server = servers.get(alias)
        kind = known.get(str((server or {}).get("kind")))
        if not server or not kind:
            continue
        identity = identity_of(env, alias, kind)
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
    return {"direct": direct, "wrap": wrap, "missing": missing, "primary": next((alias for alias in direct if delivery(known[servers[alias]["kind"]], servers[alias])["identity"] == "netonly"), "")}


def launch(root: Path, chosen: List[str], primary: str, code_argv: List[str]) -> Dict[str, Any]:
    """Open VS Code with the chosen identities and keep which are wrapped for its chat. The caller made sure no VS Code of this folder is open."""
    planned = plan(root, chosen, primary)
    servers, known, env = listed(root), kinds(root), read_env(root)
    from . import launchenv  # it reads this module's .env

    extra: Dict[str, str] = launchenv.extra(root)  # tool folders and the CA bundle (1.7.11)
    for alias in planned["direct"]:
        kind, server = known[servers[alias]["kind"]], servers[alias]
        extra.update(variables(kind, server, identity_of(env, alias, kind)))
    target = root / STATE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"at": utc_now(), "direct": planned["direct"], "wrap": planned["wrap"], "primary": planned["primary"]}, indent=2), encoding="utf-8")
    argv = (["cmd.exe", "/c", *code_argv] if os.name == "nt" and str(code_argv[0]).lower().endswith((".cmd", ".bat")) else code_argv)
    if planned["primary"]:
        identity = identity_of(env, planned["primary"], known[servers[planned["primary"]]["kind"]])
        if not netonly.start(identity["account"], identity["password"], argv, root, extra):
            return {**planned, "started": False, "why": say("servers.netonly.windows")}
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
    servers, known = listed(root), kinds(root)
    server = servers.get(alias)
    kind = known.get(str((server or {}).get("kind")))
    if not server or not kind:
        return 2, say("servers.unknown", alias=alias)
    found = classify(line)
    if not found or any(action.system != alias for action, _decision in found):
        return 2, say("servers.as.other", alias=alias)
    identity = identity_of(read_env(root), alias, kind)
    if not identity:
        return 2, say("servers.as.none", alias=alias)
    own = variables(kind, server, identity)
    swapped = [_swap(word, own) for word in argv]  # the window's shell put its own value of a variable in the line ($TOKEN, $env:TOKEN, %TOKEN%): this server's goes there
    if swapped != argv:
        argv = swapped
        line = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    if delivery(kind, server)["identity"] != "netonly":  # the output streams to the terminal as it comes
        return subprocess.run(line, shell=True, env={**os.environ, **variables(kind, server, identity)}).returncode, ""  # noqa: S602 - the agent's own command, judged by the gate
    code, output = run_with(kind, server, identity, line, Path.cwd(), timeout=3600)
    return (code if code is not None else 1), output
