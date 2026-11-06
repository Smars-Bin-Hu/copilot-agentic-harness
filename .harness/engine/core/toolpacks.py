"""Tool packs (1.7.12): what lets the agent work with one outside tool (a ticket board, a pipeline service), as one folder a team installs.

The harness knows no tool pack. A tool pack brings what the harness already reads, each in its usual form:

  toolpack.json   {"schema_version": 1, "name", "version", "harness": the lowest harness version it works with, "description",
                    "needs": {"programs": [...], "trust": [variables that name the CA bundle for its program]}}
  kinds/*.json     kinds of server (core.servers): a ticket board is a "server" with an org and a project, reached by the tool's own sign-in
  systems.json     {"systems": {...}}: systems of the tools policy written by hand; layered after the company pack's, before tools.override.json
  skills/<name>-*  skills, copied to `.github/skills/` (Copilot finds them only there). Each starts with the tool pack's name, so two never clash
  "links" in toolpack.json   {<type>: {"label", "kind", "url"}} (1.7.15): a task can name an item of the tool (`<type>:<id>`, `harness task link`);
                   `url` is filled with `{id}` and the fields of the first server of `kind` (`{org}`, `{project}`). The board shows a chip that opens it
  "mcp" in toolpack.json   {"tools": [{"pattern": <regular expression on the tool's name>, "verb": read|write|exec|destroy}]} (1.7.14): the gate
                   lets a read through, makes Copilot ask the person before a write or an exec, and refuses a destroy. An MCP tool no tool pack names is
                   not judged. Not the outbox: the harness cannot run an MCP call again for the person

Installed in `.harness/toolpacks/<name>/`, by a person at a terminal (`harness toolpack add <folder|zip>`) or by `company sync` from
`<knowledge base>/company/toolpacks/<name>/`. `.harness/toolpacks/installed.json` keeps where each came from and the skills it copied, so
`remove` takes back what it put there and nothing else. The folder is a guardrail: the agent can neither install a tool pack nor change one,
since a tool pack's rules are the gate's rules.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from . import messages, skillcheck
from .paths import runtime_dir, utc_now
from .registry import harness_version

FOLDER = Path(".harness") / "toolpacks"
MANIFEST = "toolpack.json"
TYPES = "types"  # the connection types it brings
RULES = "rules.json"  # gate rules written by hand
MCP_FILE = "mcp.json"  # MCP servers for VS Code, `{"servers": {...}}`: added to .vscode/mcp.json only where MCP is allowed (1.7.17)
VSCODE_MCP = Path(".vscode") / "mcp.json"
COMPANY_PACKS = Path("tools") / "packs"  # where the company pack keeps tool packs
LEDGER = "installed.json"
SKILLS_DIR = Path(".github") / "skills"
NAME = re.compile(r"^[a-z][a-z0-9]{1,30}$")  # one word: it starts the names of the tool pack's skills (`<name>-...`)
BACKUP_DIR = "toolpack-backup"
MCP_VERBS = ("read", "write", "exec", "destroy")
COMPANY = "company"


class ToolpackError(Exception):
    pass


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def _numbers(version: str) -> tuple:
    try:
        return tuple(int(part) for part in str(version).split(".")[:3])
    except ValueError:
        return (0,)


# --- reading ----------------------------------------------------------------------------------------------------------------------------------------------

def manifest(folder: Path) -> Dict[str, Any]:
    try:
        found = json.loads((folder / MANIFEST).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ToolpackError(say("toolpack.manifest.bad", folder=folder.name, error=error)) from None
    if not isinstance(found, dict):
        raise ToolpackError(say("toolpack.manifest.bad", folder=folder.name, error="not an object"))
    return found


def problems(root: Path, folder: Path) -> List[str]:
    """What keeps this folder from being installed here; empty when it may be."""
    from . import connections, systems  # they read this module's installed kinds and systems

    try:
        found = manifest(folder)
    except ToolpackError as error:
        return [str(error)]
    out: List[str] = []
    name = str(found.get("name") or "")
    if not NAME.match(name) or name in skillcheck.RESERVED or name == skillcheck.company_prefix(root):
        out.append(say("toolpack.name.bad", name=name or "-"))
    if not found.get("version"):
        out.append(say("toolpack.version.none"))
    lowest = str(found.get("harness") or "")
    if lowest and _numbers(lowest) > _numbers(harness_version(root)):
        out.append(say("toolpack.harness.old", wanted=lowest, have=harness_version(root)))
    needs = found.get("needs") or {}
    if not isinstance(needs, dict) or not all(isinstance(needs.get(key, []), list) for key in ("programs", "trust")):
        out.append(say("toolpack.needs.bad"))
    mcp = found.get("mcp") or {}
    if not isinstance(mcp, dict) or not isinstance(mcp.get("tools", []), list):
        out.append(say("toolpack.mcp.bad", rule="mcp.tools"))
    if (folder / MCP_FILE).is_file():
        try:
            listed = json.loads((folder / MCP_FILE).read_text(encoding="utf-8-sig")).get("servers")
            if not isinstance(listed, dict) or not listed or not all(isinstance(spec, dict) for spec in listed.values()):
                raise ValueError("`servers` is an object of servers")
        except (OSError, ValueError, AttributeError) as error:
            out.append(f"{MCP_FILE}: {error}")
    links = found.get("links") or {}
    if not isinstance(links, dict) or any(not re.match(r"^[a-z][a-z0-9]{0,15}$", str(key)) or not isinstance(spec, dict) or not str(spec.get("url") or "").startswith("https://") for key, spec in links.items()):
        out.append(say("toolpack.links.bad"))
    for index, rule in enumerate((mcp.get("tools") or []) if isinstance(mcp, dict) else []):
        try:
            ok = isinstance(rule, dict) and rule.get("verb") in MCP_VERBS and bool(re.compile(str(rule.get("pattern") or "")).pattern)
        except re.error:
            ok = False
        if not ok:
            out.append(say("toolpack.mcp.bad", rule=f"mcp.tools[{index}]"))
    for path in sorted((folder / TYPES).glob("*.json")) if (folder / TYPES).is_dir() else []:
        try:
            kind = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            out.append(f"types/{path.name}: {error}")
            continue
        out.extend(f"types/{path.name}: {problem}" for problem in connections.type_problems(kind))
    if (folder / RULES).is_file():
        try:
            listed = json.loads((folder / RULES).read_text(encoding="utf-8-sig")).get("systems")
            out.extend(f"rules.json: {problem}" for problem in systems.validate(listed or {}))
        except (OSError, ValueError, AttributeError) as error:
            out.append(f"rules.json: {error}")
    for skill in _skills(folder):
        if not skill.name.startswith(name + "-"):
            out.append(say("toolpack.skill.prefix", skill=skill.name, name=name))
            continue
        out.extend(f"skills/{skill.name}: {problem}" for problem in skillcheck.check(skill, name)["errors"])
    return out


def _skills(folder: Path) -> List[Path]:
    base = folder / "skills"
    return sorted(item for item in base.iterdir() if item.is_dir()) if base.is_dir() else []


def ledger(root: Path) -> Dict[str, Dict[str, Any]]:
    try:
        found = json.loads((root / FOLDER / LEDGER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _write_ledger(root: Path, found: Dict[str, Dict[str, Any]]) -> None:
    target = root / FOLDER / LEDGER
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(found, indent=2, sort_keys=True), encoding="utf-8")


def installed(root: Path) -> Dict[str, Dict[str, Any]]:
    """`{name: {folder, manifest}}` of the toolpacks in place; a folder whose manifest cannot be read is left out (`check` says why)."""
    base = root / FOLDER
    out: Dict[str, Dict[str, Any]] = {}
    for folder in sorted(item for item in base.iterdir() if item.is_dir()) if base.is_dir() else []:
        try:
            found = manifest(folder)
        except ToolpackError:
            continue
        if found.get("name") == folder.name:
            out[folder.name] = {"folder": folder, "manifest": found}
    return out


def type_files(root: Path) -> List[Path]:
    return [path for item in installed(root).values() for path in sorted((item["folder"] / TYPES).glob("*.json"))]


def rules_layer(root: Path) -> Dict[str, Any]:
    """The systems the installed tool packs write by hand, each marked with its tool pack (`tool pack`), in the form of tools.json."""
    out: Dict[str, Any] = {}
    for name, item in installed(root).items():
        try:
            listed = json.loads((item["folder"] / RULES).read_text(encoding="utf-8-sig")).get("systems") or {}
        except (OSError, ValueError, AttributeError):
            continue
        for system, spec in listed.items():
            if isinstance(spec, dict):
                out[system] = dict(spec, toolpack=name)
    return {"systems": out} if out else {}


LINK = re.compile(r"^([a-z][a-z0-9]{0,15}):([A-Za-z0-9._#/-]{1,64})$")


def link_view(root: Path, ref: str) -> Dict[str, str]:
    """A task's link as the board draws it: `{ref, type, id, label, url, tool pack}`; a type no tool pack knows keeps only its text."""
    from . import connections  # it reads this module's kinds

    found = LINK.match(ref)
    out = {"ref": ref, "type": found.group(1) if found else "", "id": found.group(2) if found else ref, "label": "", "url": "", "toolpack": ""}
    if not found:
        return out
    for name, item in installed(root).items():
        spec = ((item["manifest"].get("links") or {}).get(out["type"]) or {}) if isinstance(item["manifest"].get("links"), dict) else {}
        if not isinstance(spec, dict) or not spec:
            continue
        out.update(label=str(spec.get("label") or ""), toolpack=name)
        server = next((one for one in connections.listed(root).values() if one.get("type") == spec.get("type")), {})
        values = {**{key: str(value) for key, value in server.items() if isinstance(value, (str, int))}, "id": out["id"]}
        url = re.sub(r"\{(\w+)\}", lambda part: values.get(part.group(1), "\0"), str(spec.get("url") or ""))
        if url.startswith("https://") and "\0" not in url:  # every field was there: a link that would go to a wrong place is not drawn
            out["url"] = url
        break
    return out


def mcp_verb(root: Path, tool: str) -> Optional[Dict[str, str]]:
    """What an MCP tool does, by the first rule of an installed tool pack whose pattern matches its name: `{tool pack, verb}`; None when none names it."""
    for name, item in installed(root).items():
        for rule in ((item["manifest"].get("mcp") or {}).get("tools") or []):
            try:
                if isinstance(rule, dict) and rule.get("verb") in MCP_VERBS and re.search(str(rule.get("pattern") or ""), tool, re.IGNORECASE):
                    return {"toolpack": name, "verb": rule["verb"]}
            except re.error:
                continue
    return None


def trust_vars(root: Path) -> List[str]:
    return sorted({str(var) for item in installed(root).values() for var in ((item["manifest"].get("needs") or {}).get("trust") or []) if re.match(r"^[A-Z_][A-Z0-9_]*$", str(var))})


# --- installing ----------------------------------------------------------------------------------------------------------------------------------------------

def _unpack(source: Path, into: Path) -> Path:
    """The folder of a zip: its root, or the one folder at its root. A name that would land outside is refused."""
    with zipfile.ZipFile(source) as archive:
        for member in archive.namelist():
            pure = PurePosixPath(member.replace("\\", "/"))
            if pure.is_absolute() or ".." in pure.parts or (pure.parts and pure.parts[0].endswith(":")):
                raise ToolpackError(say("toolpack.zip.unsafe", name=member))
        archive.extractall(into)
    if (into / MANIFEST).is_file():
        return into
    tops = [item for item in into.iterdir() if item.is_dir() and not item.name.startswith(("__MACOSX", "."))]
    if len(tops) == 1 and (tops[0] / MANIFEST).is_file():
        return tops[0]
    raise ToolpackError(say("toolpack.manifest.none", source=source.name))


def add(root: Path, raw: str, origin: str = "", replace: bool = False) -> Dict[str, Any]:
    """Install a tool pack from a folder or a zip. One installed under the same name is replaced only with `replace` (a newer version, or the company's)."""
    source = Path(raw).expanduser()
    if not source.exists():
        raise ToolpackError(say("toolpack.source.none", source=raw))
    with tempfile.TemporaryDirectory() as holder:
        folder = _unpack(source, Path(holder)) if source.is_file() else source
        found = problems(root, folder)
        if found:
            raise ToolpackError(say("toolpack.refused", problems="; ".join(found)))
        name = manifest(folder)["name"]
        book = ledger(root)
        target = root / FOLDER / name
        if target.exists() and not replace:
            raise ToolpackError(say("toolpack.exists", name=name, version=(book.get(name) or {}).get("version", "?")))
        mine = set((book.get(name) or {}).get("skills") or [])
        skills = _skills(folder)
        clash = [skill.name for skill in skills if (root / SKILLS_DIR / skill.name).exists() and skill.name not in mine]
        if clash:
            raise ToolpackError(say("toolpack.skill.clash", skills=", ".join(clash)))
        for gone in mine - {skill.name for skill in skills}:  # a skill the new version no longer has
            shutil.rmtree(root / SKILLS_DIR / gone, ignore_errors=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(folder, target, ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"))
        for skill in skills:
            place = root / SKILLS_DIR / skill.name
            if place.exists():
                shutil.rmtree(place)
            shutil.copytree(skill, place, ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"))
        version = str(manifest(target).get("version"))
    book[name] = {"version": version, "from": origin or str(source), "at": utc_now(), "skills": [skill.name for skill in skills], "mcp": (book.get(name) or {}).get("mcp") or []}
    _write_ledger(root, book)
    apply_mcp(root)
    return {"installed": name, "version": version, "skills": book[name]["skills"], "next": say("toolpack.added", name=name)}


def remove(root: Path, name: str) -> Dict[str, Any]:
    """Take a tool pack away: its folder and the skills it copied go to the backup folder, so a removal can be undone by hand."""
    book = ledger(root)
    target = root / FOLDER / name
    if not NAME.match(name) or not target.is_dir():
        raise ToolpackError(say("toolpack.none", name=name))
    backup = runtime_dir(root) / BACKUP_DIR / time.strftime("%Y%m%d-%H%M%S") / name
    backup.mkdir(parents=True, exist_ok=True)
    _drop_mcp(root, (book.get(name) or {}).get("mcp") or [])
    moved = []
    for skill in (book.get(name) or {}).get("skills") or []:
        if (root / SKILLS_DIR / skill).is_dir():
            shutil.move(str(root / SKILLS_DIR / skill), str(backup / "skills" / skill))
            moved.append(skill)
    shutil.move(str(target), str(backup / "toolpack"))
    book.pop(name, None)
    _write_ledger(root, book)
    return {"removed": name, "skills": moved, "backup": str(backup)}


def _read_mcp(root: Path) -> Dict[str, Any]:
    try:
        found = json.loads((root / VSCODE_MCP).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"servers": {}}
    if not isinstance(found, dict):
        return {"servers": {}}
    found.setdefault("servers", {})
    return found


def _write_mcp(root: Path, found: Dict[str, Any]) -> None:
    target = root / VSCODE_MCP
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(found, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _drop_mcp(root: Path, names: List[str]) -> None:
    if not names or not (root / VSCODE_MCP).is_file():
        return
    found = _read_mcp(root)
    for name in names:
        found["servers"].pop(name, None)
    _write_mcp(root, found)


def apply_mcp(root: Path) -> Dict[str, Any]:
    """Where MCP is allowed (This computer), each installed tool pack's MCP servers are in `.vscode/mcp.json`; where it is not, the ones a tool pack put
    there are taken out. A server of the same name that is not a tool pack's own is never touched (`kept`)."""
    from . import launchenv  # it reads this module

    allowed = launchenv.mcp_allowed(root)
    book = ledger(root)
    found = _read_mcp(root) if (root / VSCODE_MCP).is_file() or allowed else {"servers": {}}
    mine = {server for item in book.values() for server in item.get("mcp") or []}
    added: List[str] = []
    dropped: List[str] = []
    kept: List[str] = []
    for name, item in installed(root).items():
        entry = book.setdefault(name, {})
        if not allowed:
            for server in entry.get("mcp") or []:
                if found["servers"].pop(server, None) is not None:
                    dropped.append(server)
            entry["mcp"] = []
            continue
        try:
            wanted = json.loads((item["folder"] / MCP_FILE).read_text(encoding="utf-8-sig")).get("servers") or {}
        except (OSError, ValueError, AttributeError):
            wanted = {}
        own = []
        for server, spec in wanted.items():
            if server in found["servers"] and server not in mine:
                kept.append(server)
                continue
            if found["servers"].get(server) != spec:
                found["servers"][server] = spec
                added.append(server)
            own.append(server)
        entry["mcp"] = own
    if added or dropped:
        _write_mcp(root, found)
    if book:
        _write_ledger(root, book)
    return {"mcp": "allowed" if allowed else "blocked", "added": added, "dropped": dropped, "kept": kept}


def from_company(root: Path, company: Path) -> Dict[str, Any]:
    """`company sync`: each tool pack of `<company>/toolpacks/` is installed, or replaced when it changed; one the company put here and no longer has is listed (`gone`), not removed."""
    base = company / COMPANY_PACKS
    book = ledger(root)
    done: List[str] = []
    refused: List[Dict[str, str]] = []
    names = []
    for folder in sorted(item for item in base.iterdir() if item.is_dir()) if base.is_dir() else []:
        names.append(folder.name)
        target = root / FOLDER / folder.name
        if target.is_dir() and _same(folder, target):
            continue
        if target.is_dir() and (book.get(folder.name) or {}).get("from") != COMPANY:
            refused.append({"toolpack": folder.name, "why": say("toolpack.company.own", name=folder.name)})
            continue
        try:
            add(root, str(folder), origin=COMPANY, replace=True)
            done.append(folder.name)
        except ToolpackError as error:
            refused.append({"toolpack": folder.name, "why": str(error)})
    gone = sorted(name for name, item in book.items() if item.get("from") == COMPANY and name not in names)
    return {"installed": done, "refused": refused, "gone": gone}


def _same(source: Path, target: Path) -> bool:
    def files(folder: Path) -> Dict[str, bytes]:
        return {path.relative_to(folder).as_posix(): path.read_bytes() for path in folder.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.name != ".DS_Store"}
    return files(source) == files(target)


# --- writing one ---------------------------------------------------------------------------------------------------------------------------------------------

SKELETON_SKILL = """---
name: {name}-use
description: 'How the agent uses {name}: what to read, how to draft a write for the person to approve, what never to do. Use when a task needs {name}. Keywords: {name}.'
type: unit
specificTo: generic
---

# {name}: read, and draft a write

## When to Use This Skill

- A task needs {name}: say when.

## Step-by-Step Workflows

1. **Find the connection**: `harness connections` shows each one and the command that reaches it (`call`).
2. **Read**: the commands that only read. They run.
3. **Write only when the user asked**: show the command first; the gate holds it until the user approves it.

## Gotchas

- What the agent gets wrong with this tool: write each trap here.
"""


def new(root: Path, name: str, out: str = "") -> Dict[str, Any]:
    """The skeleton of a tool pack (contracts/toolpack/README.md), to fill in: in the company pack when there is one, else where `out` says."""
    from . import targets  # it reads the policies

    if not NAME.match(name) or name in skillcheck.RESERVED:
        raise ToolpackError(say("toolpack.name.bad", name=name))
    company = targets.company_folder(root)
    target = Path(out).expanduser() / name if out else (company / COMPANY_PACKS / name if company else Path.cwd() / name)
    if target.exists():
        raise ToolpackError(say("toolpack.new.exists", path=str(target)))
    (target / TYPES).mkdir(parents=True)
    (target / "skills" / f"{name}-use").mkdir(parents=True)
    (target / MANIFEST).write_text(json.dumps({"schema_version": 1, "name": name, "version": "0.1.0", "harness": harness_version(root),
                                               "description": f"What {name} lets the agent do.", "needs": {"programs": [name], "trust": []}}, indent=2) + "\n", encoding="utf-8")
    (target / TYPES / f"{name}.json").write_text(json.dumps({
        "type": name, "label": name, "fields": {"host": {"label": "Host"}},
        "auth": {"signin": {"identity": "tool", "label": "Its own sign-in", "login": f"{name} login"}},
        "test": f"{name} --host {{host}} whoami", "expect": "^(\\S+)\\s*$", "denied": "not signed in",
        "cli": [name], "match": "--host\\s+{host}\\b",
        "verbs": [{"pattern": "\\bdelete\\b", "verb": "destroy"}, {"pattern": "\\b(?:create|update)\\b", "verb": "write"}, {"pattern": "\\b(?:get|list|whoami)\\b", "verb": "read"}],
        "rules": {"none": {"read": "allow", "write": "outbox", "exec": "human", "destroy": "deny"}}}, indent=2) + "\n", encoding="utf-8")
    (target / "skills" / f"{name}-use" / "SKILL.md").write_text(SKELETON_SKILL.format(name=name), encoding="utf-8")
    (target / "README.md").write_text(f"# {name}\n\nWhat it is for, in one line.\n\n1. Install: `harness toolpack add <this folder>` (or put it in the knowledge base, `company/tools/packs/{name}/`).\n"
                                      "2. Set up: Get ready, Tools, This computer (the program's folder, a CA bundle behind a proxy).\n3. Sign in: Get ready, Tools, Connections.\n"
                                      "4. Try: ask the agent for a read, then for a write: the write waits for you.\n", encoding="utf-8")
    return {"made": str(target), "next": say("toolpack.new.done", path=str(target))}


# --- checking ----------------------------------------------------------------------------------------------------------------------------------------------------

def check_folder(root: Path, folder: Path) -> Dict[str, Any]:
    """`harness toolpack check <folder>`: a tool pack that is not installed yet, file by file."""
    found = problems(root, folder)
    return {"folder": str(folder), "problems": found, "next": say("toolpack.check.ok" if not found else "toolpack.check.bad", n=len(found)), "exit_code": 1 if found else 0}


def check(root: Path, only: str = "") -> Dict[str, Any]:
    """Each tool pack: problems with its files, the programs it needs (found on the PATH VS Code gets), and a CA bundle when it names a trust variable."""
    from . import launchenv

    path = launchenv.extra(root).get("PATH") or None
    bundle = launchenv.bundle_path(root)
    rows = []
    book = ledger(root)
    base = root / FOLDER
    names = sorted(item.name for item in base.iterdir() if item.is_dir()) if base.is_dir() else []
    for name in names:
        if only and name != only:
            continue
        folder = base / name
        errors = problems(root, folder)
        try:
            found = manifest(folder)
        except ToolpackError:
            found = {}
        needs = found.get("needs") or {}
        types_here = []
        for one in sorted((folder / TYPES).glob("*.json")) if (folder / TYPES).is_dir() else []:
            try:
                spec = json.loads(one.read_text(encoding="utf-8-sig"))
                types_here.append({"type": str(spec.get("type") or one.stem), "label": str(spec.get("label") or spec.get("type") or one.stem), "via": str(spec.get("via") or "cli")})
            except (OSError, ValueError, AttributeError):
                continue
        programs = {str(program): bool(shutil.which(str(program), path=path)) for program in needs.get("programs") or []}
        row = {"name": name, "version": (book.get(name) or {}).get("version", ""), "from": (book.get(name) or {}).get("from", ""), "errors": errors,
               "programs": programs, "trust": bool(needs.get("trust")), "bundle": bool(bundle), "description": str(found.get("description") or ""), "types": types_here,
               "skills": len(_skills(folder)), "links": sorted((found.get("links") or {}).keys()) if isinstance(found.get("links"), dict) else [],
               "mcp_rules": len((found.get("mcp") or {}).get("tools") or []) if isinstance(found.get("mcp"), dict) else 0}
        source = Path(str(row["from"])) if row["from"] and row["from"] != COMPANY else None
        row["newer"] = bool(source and source.is_dir() and (source / MANIFEST).is_file() and not _same(source, folder))  # its folder changed since it was installed
        row["ok"] = not errors and all(programs.values())
        rows.append(row)
    if only and not rows:
        raise ToolpackError(say("toolpack.none", name=only))
    return {"toolpacks": rows, "exit_code": 0 if all(row["ok"] for row in rows) else 1}
