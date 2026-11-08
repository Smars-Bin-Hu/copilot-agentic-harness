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

There is no installed copy (1.7.30). A pack is read where it lies:

  .harness/toolpacks/<name>/               the factory packs, shipped with the harness (a guardrail path: read only for the agent)
  <knowledge base>/company/tools/packs.json   {"use": ["ado", ...]}: the factory packs this company turns on
  <knowledge base>/company/tools/packs/<name>/ a pack the company wrote (always on)
  .harness/runtime/toolpacks.json `paths`    folders this computer added to try a pack (`harness toolpack add <folder>`)

Its types, rules, `bin/` and MCP servers are read in place. A pack that is off still guards its connections (1.7.38): while a connection uses a type
of an off pack, the gate reads that pack's types, rules and MCP rules (`guarded`); turning a pack off takes back only its skills and its `bin/` on the PATH. The only thing copied is the skills: `sync_skills` (run by `company sync`) puts the
skills of the active packs into `.github/skills/`, renamed `<prefix>-<pack>-<skill>` when the company has a `skill_prefix`, takes away the skills of
a pack no longer active, and puts them again when the pack's version changed (`ado 0.4.5 -> 0.5.0 updated`). `.harness/runtime/toolpacks.json`
`packs` keeps what was put there, so a removal takes back that and nothing else. To update the harness is to unzip it over the old one.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import messages, skillcheck, targets
from .paths import runtime_dir, utc_now
from .registry import harness_version

FOLDER = Path(".harness") / "toolpacks"
MANIFEST = "toolpack.json"
TYPES = "types"  # the connection types it brings
RULES = "rules.json"  # gate rules written by hand
MCP_FILE = "mcp.json"  # MCP servers for VS Code, `{"servers": {...}}`: added to .vscode/mcp.json only where MCP is allowed (1.7.17)
VSCODE_MCP = Path(".vscode") / "mcp.json"
COMPANY_PACKS = Path("tools") / "packs"  # where the company pack keeps the packs it wrote
USE_FILE = Path("tools") / "packs.json"  # `{"use": [...]}`: the factory packs the company turns on
LEDGER = "toolpacks.json"  # in .harness/runtime/
SKILLS_DIR = Path(".github") / "skills"
NAME = re.compile(r"^[a-z][a-z0-9]{1,30}$")  # one word: it starts the names of the tool pack's skills (`<name>-...`)
BACKUP_DIR = "toolpack-backup"
MCP_VERBS = ("read", "write", "exec", "destroy")
COMPANY = "company"
HARNESS = "harness"
TEXT_SUFFIXES = (".md", ".txt", ".json", ".yaml", ".yml")  # the files of a skill in which a pack's own skill names are renamed
SKIP_FILES = {".DS_Store", "Thumbs.db"}
UPDATED_SHOWN_DAYS = 7


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
    except FileNotFoundError:
        raise ToolpackError(say("toolpack.not_a_pack", folder=folder.name or str(folder))) from None
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
    if not NAME.match(name) or name in skillcheck.RESERVED or name == skillcheck.effective_prefix(root):
        out.append(say("toolpack.name.bad", name=name or "-"))
    if not found.get("version"):
        out.append(say("toolpack.version.none"))
    lowest = str(found.get("harness") or "")
    if lowest and _numbers(lowest) > _numbers(harness_version(root)):
        out.append(say("toolpack.harness.old", wanted=lowest, have=harness_version(root)))
    needs = found.get("needs") or {}
    if not isinstance(needs, dict) or not all(isinstance(needs.get(key, []), list) for key in ("programs", "trust")):
        out.append(say("toolpack.needs.bad"))
    commands = found.get("commands")
    if commands is not None and (not isinstance(commands, list) or not all(isinstance(one, str) and one for one in commands)):
        out.append(say("toolpack.commands.bad"))
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
    if not isinstance(links, dict) or any(not re.match(r"^[a-z][a-z0-9]{0,15}$", str(key)) or not isinstance(spec, dict) or not str(spec.get("url") or "").startswith(("https://", "{url}")) for key, spec in links.items()):
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
        company = skillcheck.effective_prefix(root)
        owner = name if skill.name.startswith(name + "-") else company if company and skill.name.startswith(f"{company}-{name}-") else ""  # the company's prefix may lead (1.7.18)
        if not owner:
            out.append(say("toolpack.skill.prefix", skill=skill.name, name=name, company=company or "<prefix>"))
            continue
        out.extend(f"skills/{skill.name}: {problem}" for problem in skillcheck.check(skill, owner)["errors"])
    return out


def _skills(folder: Path) -> List[Path]:
    base = folder / "skills"
    return sorted(item for item in base.iterdir() if item.is_dir()) if base.is_dir() else []


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def ledger(root: Path) -> Dict[str, Any]:
    """`.harness/runtime/toolpacks.json`: `{"packs": {name: {source, version, skills, mcp, updated}}, "paths": [folders]}`. Written by the harness only."""
    found = _json(runtime_dir(root) / LEDGER)
    found = found if isinstance(found, dict) else {}
    packs = found.get("packs") if isinstance(found.get("packs"), dict) else {}
    paths = found.get("paths") if isinstance(found.get("paths"), list) else []
    return {"packs": {str(name): item for name, item in packs.items() if isinstance(item, dict)}, "paths": [str(item) for item in paths if isinstance(item, str) and item]}


def _write_ledger(root: Path, found: Dict[str, Any]) -> None:
    target = runtime_dir(root) / LEDGER
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"packs": found.get("packs") or {}, "paths": found.get("paths") or []}, indent=2, sort_keys=True), encoding="utf-8")


def use_list(root: Path) -> List[str]:
    """The factory packs the knowledge base turns on: `use` of `<knowledge base>/company/tools/packs.json`. Nothing when there is no file or it cannot be read."""
    folder = targets.company_folder(root)
    found = _json(folder / USE_FILE) if folder else None
    names = found.get("use") if isinstance(found, dict) else None
    return [str(item) for item in names if isinstance(item, str)] if isinstance(names, list) else []


def paths(root: Path) -> List[str]:
    return ledger(root)["paths"]


def clashes(root: Path) -> List[str]:
    """Names of packs the company wrote in `company/tools/packs/` that a factory pack in `.harness/toolpacks/` already has. While there is one, `company sync` stops before it changes anything
    (1.7.38): `sync_skills` and `company.sync` check this first. Reading goes on as before: the factory pack stays, the company's is not read until it is renamed."""
    company = targets.company_folder(root)
    base = company / COMPANY_PACKS if company else None
    factory = root / FOLDER
    if base is None or not base.is_dir() or not factory.is_dir():
        return []
    have = {item.name for item in factory.iterdir() if item.is_dir()}
    return sorted(item.name for item in base.iterdir() if item.is_dir() and item.name in have)


def clash_lines(root: Path) -> List[str]:
    return [say("toolpack.clash", name=name) for name in clashes(root)]


def clash_stop(root: Path) -> str:
    """The one line `company sync` answers with when a company pack has the name of a factory pack (1.7.38), naming every such pack; "" when there is none."""
    names = clashes(root)
    return say("company.sync.clash", names=", ".join(f"`{name}`" for name in names)) if names else ""


def refuse_on_clash(root: Path) -> None:
    """For `add`, `remove` and the on/off switch, which all end in a sync: while a company pack has the name of a factory pack none of them changes anything (1.7.38)."""
    line = clash_stop(root)
    if line:
        raise ToolpackError(line)


def listed(root: Path) -> Dict[str, Dict[str, Any]]:
    """Every pack this computer knows, `{name: {folder, manifest, source, active}}`: the company's own, the folders added here, the factory packs. `source` is
    `company`, `harness` or the folder's path. A name found twice is kept once: the company's first, then a folder added here, then the factory's. A folder
    whose manifest cannot be read is left out (`check` says why)."""
    company = targets.company_folder(root)
    turned_on = set(use_list(root))
    found: List[tuple] = []
    base = company / COMPANY_PACKS if company else None
    clash = set(clashes(root))
    found += [(item, COMPANY, True) for item in (sorted(base.iterdir()) if base is not None and base.is_dir() else []) if item.is_dir() and item.name not in clash]
    found += [(Path(raw), raw, True) for raw in paths(root)]
    factory = root / FOLDER
    found += [(item, HARNESS, None) for item in (sorted(factory.iterdir()) if factory.is_dir() else []) if item.is_dir()]
    out: Dict[str, Dict[str, Any]] = {}
    for folder, source, active in found:
        try:
            data = manifest(folder)
        except ToolpackError:
            continue
        name = str(data.get("name") or "")
        if not NAME.match(name) or name in out or (source != str(folder) and name != folder.name):
            continue
        out[name] = {"folder": folder, "manifest": data, "source": source, "active": name in turned_on if active is None else active}
    return out


def active(root: Path) -> Dict[str, Dict[str, Any]]:
    """The packs that are on: the company's own, the folders added here, the factory packs `use` names. This is what the gate, the PATH and the types read."""
    return {name: item for name, item in listed(root).items() if item["active"]}


installed = active  # the name the other modules know (before 1.7.30 a pack was copied in)


def type_names(folder: Path) -> List[str]:
    """The connection types a pack's `types/` brings: the `type` of each file (the file's name when it names none)."""
    out: List[str] = []
    for path in sorted((folder / TYPES).glob("*.json")) if (folder / TYPES).is_dir() else []:
        found = _json(path)
        if isinstance(found, dict):
            out.append(str(found.get("type") or path.stem))
    return out


def guarded(root: Path) -> Dict[str, Dict[str, Any]]:
    """The packs the gate reads (1.7.38): the packs that are on, and the packs that are off but whose connection type a connection uses. A connection is a place that
    may be written to; whether a pack's skills and `bin/` are on must not decide whether its calls are judged. Same shape and order as `listed`. A type an active pack
    already brings is not looked for again in an off pack (the first pack that brings a type keeps it)."""
    every = listed(root)
    names = {str(server.get("type")) for server in connections_listed(root).values()}
    names -= {one for item in every.values() if item["active"] for one in type_names(item["folder"])}
    out = {name: item for name, item in every.items() if item["active"]}
    if names:
        for name, item in every.items():
            if item["active"]:
                continue
            brought = set(type_names(item["folder"]))
            if brought & names:
                out[name] = item
                names -= brought
    return {name: out[name] for name in every if name in out}


def guard_only(root: Path) -> Dict[str, List[str]]:
    """`{pack: [connections]}` of the packs that are off but guard a connection (`guarded` minus `active`): for doctor."""
    held = {name: item for name, item in guarded(root).items() if not item["active"]}
    servers = connections_listed(root)
    return {name: sorted(alias for alias, server in servers.items() if str(server.get("type")) in set(type_names(item["folder"]))) for name, item in held.items()}


def unknown_use(root: Path) -> List[str]:
    """Names in `use` that no factory pack has."""
    have = listed(root)
    return [name for name in use_list(root) if name not in have]


def bin_folders(root: Path) -> List[str]:
    """The `bin/` of each active pack that has one: a program the pack brings is on the PATH VS Code gets, with no tool folder to type."""
    return [str((item["folder"] / "bin").resolve()) for item in active(root).values() if (item["folder"] / "bin").is_dir()]


def _path_of(root: Path) -> Optional[str]:
    from . import launchenv

    extra = launchenv.extra(root)
    return next((value for key, value in extra.items() if key.upper() == "PATH"), None)


def locate(program: str, path: Optional[str]) -> str:
    """Where `program` is on `path` (the PATH VS Code will get), "" when it is not."""
    return shutil.which(str(program), path=path) or ""


def blocked(program: str, path: Optional[str]) -> str:
    """Where `program` is on `path` when the file is there but has no run bit (macOS and Linux), else "". A pack handed over in a zip that lost the bit brings such a file (1.7.38)."""
    if os.name == "nt" or not program or "/" in str(program):
        return ""
    for folder in (path if path is not None else os.environ.get("PATH", "")).split(os.pathsep):
        try:
            found = Path(folder) / str(program) if folder else None
            if found is not None and found.is_file() and not os.access(found, os.X_OK):
                return str(found)
        except OSError:
            continue
    return ""


def signin_needs(kind: Dict[str, Any], server: Dict[str, Any]) -> List[str]:
    """The programs the sign-in way a connection uses asks for (`auth.<way>.needs`, 1.7.37): az for `signin`, nothing for `token`."""
    modes = kind.get("auth") or {}
    auth = modes.get(server.get("auth") or next(iter(modes), "")) or {}
    return [str(one) for one in (auth.get("needs") or []) if isinstance(one, str) and one]


def needs_report(root: Path, only: str = "", include_off: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """For each active pack, every program it needs, looked for on the PATH VS Code will get (`launchenv.extra`): the pack's `needs.programs`
    (`why: "pack"`) and the `auth.<way>.needs` of the ways its connections use (`why: "signin:<connection>"`). `[{program, found, path, why}]`."""
    path = _path_of(root)
    kinds = connections_types(root)
    servers = connections_listed(root)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for name, item in (listed(root) if include_off else active(root)).items():
        if only and name != only:
            continue
        rows: List[Dict[str, Any]] = []
        for program in (item["manifest"].get("needs") or {}).get("programs") or []:
            where = locate(program, path)
            rows.append({"program": str(program), "found": bool(where), "path": where, "why": "pack", "blocked": "" if where else blocked(str(program), path)})
        if item["active"]:
            for alias, server in servers.items():
                kind = kinds.get(str(server.get("type"))) or {}
                if kind.get("toolpack") != name:
                    continue
                for program in signin_needs(kind, server):
                    where = locate(program, path)
                    rows.append({"program": program, "found": bool(where), "path": where, "why": f"signin:{alias}", "blocked": "" if where else blocked(program, path)})
        out[name] = rows
    return out


def connections_types(root: Path) -> Dict[str, Dict[str, Any]]:
    from . import connections

    try:
        return connections.types(root)
    except Exception:  # noqa: BLE001 - a broken type must not hide the packs
        return {}


def connections_listed(root: Path) -> Dict[str, Dict[str, Any]]:
    from . import connections

    try:
        return connections.listed(root)
    except Exception:  # noqa: BLE001
        return {}


def missing_for(root: Path, alias: str) -> List[str]:
    """The programs a connection cannot be reached without and this computer lacks: its pack's `needs.programs` and its sign-in way's `needs`."""
    kinds, servers = connections_types(root), connections_listed(root)
    server = servers.get(alias) or {}
    kind = kinds.get(str(server.get("type"))) or {}
    pack = str(kind.get("toolpack") or "")
    if not pack:
        return []
    path = _path_of(root)
    wanted = list(((listed(root).get(pack) or {}).get("manifest", {}).get("needs") or {}).get("programs") or []) + signin_needs(kind, server)
    return [str(one) for one in dict.fromkeys(wanted) if not locate(one, path)]


def declared_needs(folder: Path, manifest: Dict[str, Any], path: Optional[str]) -> List[Dict[str, Any]]:
    """Every program a pack names, whether it is on or not (1.7.38, the Tool packs window): its own `needs.programs` (`why: "pack"`) and the `needs` of any sign-in way
    of its connection types (`why: "signin"`), looked for on `path`. `[{program, found, path, why}]`, each program once."""
    rows: Dict[str, Dict[str, Any]] = {}
    for program in (manifest.get("needs") or {}).get("programs") or []:
        rows[str(program)] = {"program": str(program), "found": False, "path": "", "why": "pack"}
    for one in sorted((folder / TYPES).glob("*.json")) if (folder / TYPES).is_dir() else []:
        spec = _json(one)
        for auth in (spec.get("auth") or {}).values() if isinstance(spec, dict) and isinstance(spec.get("auth"), dict) else []:
            for program in (auth.get("needs") or []) if isinstance(auth, dict) and isinstance(auth.get("needs"), list) else []:
                if isinstance(program, str) and program:
                    rows.setdefault(program, {"program": program, "found": False, "path": "", "why": "signin"})
    own = folder / "bin"  # a program the pack brings itself (`bin/`) is not something to find on this computer: it shows only when it cannot run (no run bit, 1.7.38)
    brought = {item.stem if item.suffix.lower() in (".cmd", ".bat", ".exe") else item.name: item for item in sorted(own.iterdir(), key=lambda one: one.suffix.lower() not in (".cmd", ".bat", ".exe")) if item.is_file()} if own.is_dir() else {}  # the program itself wins over its `.cmd`
    for row in rows.values():
        row["path"] = locate(row["program"], path)
        row["found"] = bool(row["path"])
        row["blocked"] = "" if row["found"] else blocked(row["program"], path)
    out = [row for row in rows.values() if row["program"] not in brought]
    for name, file in sorted(brought.items()):
        if os.name != "nt" and file.name == name and "." not in name and not os.access(file, os.X_OK):  # the program itself, not its `.cmd` beside it for Windows
            out.append({"program": name, "found": False, "path": "", "why": "own", "blocked": str(file)})
    return out


def skill_label(names: List[str]) -> str:
    """How a pack's skills are shown in one chip: the name of the only one, or the stem they share and a star (`acme-ado-*`)."""
    if len(names) < 2:
        return names[0] if names else ""
    stem = os.path.commonprefix(names)
    return stem[:stem.rfind("-") + 1] + "*" if "-" in stem else ""


def type_entries(root: Path, guard: bool = False) -> List[tuple]:
    """`(pack name, type file)` of each connection type the active packs bring, in the order of the packs. With `guard` also those of the off packs a connection uses (`guarded`, 1.7.38)."""
    return [(name, path) for name, item in (guarded(root) if guard else active(root)).items() for path in sorted((item["folder"] / TYPES).glob("*.json"))]


def type_files(root: Path) -> List[Path]:
    return [path for _name, path in type_entries(root)]


def rules_layer(root: Path) -> Dict[str, Any]:
    """The systems the tool packs write by hand, each marked with its tool pack (`toolpack`), in the form of tools.json: the packs that are on, and the off packs a connection uses (1.7.38)."""
    out: Dict[str, Any] = {}
    for name, item in guarded(root).items():
        try:
            listed = json.loads((item["folder"] / RULES).read_text(encoding="utf-8-sig")).get("systems") or {}
        except (OSError, ValueError, AttributeError):
            continue
        for system, spec in listed.items():
            if isinstance(spec, dict):
                out[system] = dict(spec, toolpack=name)
    return {"systems": out} if out else {}


LINK = re.compile(r"^([a-z][a-z0-9]{0,15}):([A-Za-z0-9._#/-]{1,64})$")


def normal_ref(ref: str) -> str:
    """One spelling of a link: an id of digits only has no leading zeros (`ado:0300114` is `ado:300114`, 1.7.21)."""
    kind, _, ident = str(ref or "").strip().partition(":")
    return f"{kind}:{ident.lstrip('0') or '0'}" if ident.isdigit() else str(ref or "").strip()


def link_types(root: Path) -> List[Dict[str, str]]:
    """The kinds of item a task may be linked to, from the installed tool packs (1.7.20): `{type, label, toolpack}`, one per link type, in the order of the packs. A link type is named by a pack's `links`
    and by the connection types that declare `link`; a type that only a connection declares has no label of its own, and takes the type's."""
    found: Dict[str, Dict[str, str]] = {}
    for name, item in installed(root).items():
        links = item["manifest"].get("links") if isinstance(item["manifest"].get("links"), dict) else {}
        for key, spec in links.items():
            if LINK.match(f"{key}:0") and isinstance(spec, dict):
                found.setdefault(key, {"type": key, "label": str(spec.get("label") or ""), "toolpack": name})
        for path in sorted((item["folder"] / "types").glob("*.json")) if isinstance(item.get("folder"), Path) and (item["folder"] / "types").is_dir() else []:
            try:
                kind = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            key = kind.get("link") if isinstance(kind, dict) else None
            if isinstance(key, str) and LINK.match(f"{key}:0"):
                found.setdefault(key, {"type": key, "label": str(kind.get("label") or ""), "toolpack": name})
    return list(found.values())


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
        defaults = {field: str(item.get("default")) for field, item in ((connections.types(root).get(str(spec.get("type"))) or {}).get("fields") or {}).items() if isinstance(item, dict) and item.get("default")}  # a field left empty has the type's default: `{url}` is the server address (1.7.21)
        values = {**defaults, **{key: str(value) for key, value in server.items() if isinstance(value, (str, int)) and value != ""}, "id": out["id"]}
        url = re.sub(r"\{(\w+)\}", lambda part: values.get(part.group(1), "\0"), str(spec.get("url") or ""))
        if url.startswith("https://") and "\0" not in url:  # every field was there: a link that would go to a wrong place is not drawn
            out["url"] = url
        break
    return out


def mcp_verb(root: Path, tool: str) -> Optional[Dict[str, str]]:
    """What an MCP tool does, by the first rule of a tool pack whose pattern matches its name (the packs that are on, and the off packs a connection uses): `{tool pack, verb}`; None when none names it."""
    for name, item in guarded(root).items():
        for rule in ((item["manifest"].get("mcp") or {}).get("tools") or []):
            try:
                if isinstance(rule, dict) and rule.get("verb") in MCP_VERBS and re.search(str(rule.get("pattern") or ""), tool, re.IGNORECASE):
                    return {"toolpack": name, "verb": rule["verb"]}
            except re.error:
                continue
    return None


def trust_vars(root: Path) -> List[str]:
    return sorted({str(var) for item in installed(root).values() for var in ((item["manifest"].get("needs") or {}).get("trust") or []) if re.match(r"^[A-Z_][A-Z0-9_]*$", str(var))})


# --- adding a folder to try, and the skills ----------------------------------------------------------------------------------------------------------------------

def clean_path(raw: Any) -> str:
    """A path pasted by a person: Windows "Copy as path" brings the quotes along."""
    return str(raw or "").strip().strip("\"'").strip()


def _exists(source: Path, raw: str) -> bool:
    """Does the path exist? A path too long for the system is one sentence (`toolpack.path.long`), not an exception (1.7.21)."""
    try:
        return source.exists()
    except OSError as error:
        if getattr(error, "errno", None) in (36, 63) or getattr(error, "winerror", None) == 206:
            raise ToolpackError(say("toolpack.path.long")) from None
        raise ToolpackError(say("toolpack.source.none", source=raw)) from None


def _folder_to_add(root: Path, raw: str) -> tuple:
    """(clean path, folder, manifest) of a folder the person names; a zip or a missing path is refused with one sentence."""
    raw = clean_path(raw)
    source = Path(raw).expanduser()
    if not _exists(source, raw):
        raise ToolpackError(say("toolpack.source.none", source=raw))
    if source.is_file():
        raise ToolpackError(say("toolpack.zip.no", source=source.name))
    return str(source.resolve()), source.resolve(), manifest(source)


def installed_against(root: Path, raw: str) -> Dict[str, Any]:
    """The folder against what is already on this computer under its name: `{name, version, installed, source}`; `installed` is the version of a folder added before, "" when none."""
    path, _folder, found = _folder_to_add(root, raw)
    name = str(found.get("name") or "")
    have = next((item for key, item in listed(root).items() if key == name and item["source"] not in (HARNESS,)), None)
    return {"name": name, "version": str(found.get("version") or "?"), "installed": str(have["manifest"].get("version") or "?") if have and str(have["folder"]) != path else "",
            "source": have["source"] if have else ""}


def add(root: Path, raw: str, origin: str = "", replace: bool = False) -> Dict[str, Any]:
    """`harness toolpack add <folder>`: this computer records the folder's path to try the pack (1.7.30). Nothing is copied but the skills (`sync_skills`).
    A folder with the name of one added before is taken in its place only with `replace`; a name the company's own packs have is refused."""
    path, folder, found = _folder_to_add(root, raw)
    refuse_on_clash(root)
    problem = problems(root, folder)
    if problem:
        raise ToolpackError(say("toolpack.refused", problems="; ".join(problem)))
    name = str(found["name"])
    book = ledger(root)
    here = listed(root).get(name)
    if here and here["source"] == COMPANY:
        raise ToolpackError(say("toolpack.company.managed", name=name))
    older = [item for item in book["paths"] if item != path and _name_at(item) == name]
    if older and not replace:
        raise ToolpackError(say("toolpack.exists", name=name, version=str((here or {}).get("manifest", {}).get("version") or "?")))
    book["paths"] = [item for item in book["paths"] if item not in older]
    if path not in book["paths"]:
        book["paths"].append(path)
    clash = [final for final in _final_names(root, name, folder) if (root / SKILLS_DIR / final).exists() and final not in set(((book["packs"].get(name) or {}).get("skills")) or [])
             and _rendered(root, name, folder).get(final) != _on_disk(root / SKILLS_DIR / final)]
    if clash:
        raise ToolpackError(say("toolpack.skill.clash", skills=", ".join(clash)))
    _write_ledger(root, book)
    sync_skills(root)
    apply_mcp(root)
    entry = ledger(root)["packs"].get(name) or {}
    return {"installed": name, "version": str(found.get("version")), "path": path, "skills": entry.get("skills") or [], "next": say("toolpack.added", name=name)}


def _name_at(path: str) -> str:
    found = _json(Path(path) / MANIFEST)
    return str(found.get("name") or "") if isinstance(found, dict) else ""


def remove(root: Path, name: str) -> Dict[str, Any]:
    """`harness toolpack remove <name or folder>`: forget a folder added here, and take back the skills it put. A factory pack is turned off by taking it out of `use`
    in the knowledge base (`company/tools/packs.json`); a pack the company wrote, by deleting its folder there. Neither is this command's to change."""
    refuse_on_clash(root)
    book = ledger(root)
    name = clean_path(name)
    mine = [item for item in book["paths"] if item == name or _name_at(item) == name or Path(item).name == name]
    if not mine:
        here = listed(root).get(name)
        if here and here["source"] == HARNESS:
            raise ToolpackError(say("toolpack.remove.factory", name=name))
        if here and here["source"] == COMPANY:
            raise ToolpackError(say("toolpack.remove.company", name=name))
        raise ToolpackError(say("toolpack.none", name=name))
    book["paths"] = [item for item in book["paths"] if item not in mine]
    _write_ledger(root, book)
    done = sync_skills(root)
    apply_mcp(root)
    return {"removed": name, "paths": mine, "skills": done["removed"], "backup": done.get("backup", "")}


def _final_names(root: Path, name: str, folder: Path) -> List[str]:
    prefix = skillcheck.effective_prefix(root)
    return [_final(prefix, skill.name) for skill in _skills(folder)]


def _final(prefix: str, skill: str) -> str:
    return skill if not prefix or skill.startswith(prefix + "-") else f"{prefix}-{skill}"


def _render(folder: Path, names: Dict[str, str]) -> Dict[str, bytes]:
    """The files of one skill as they go to `.github/skills/`: in a text file, each whole-word name of the pack's own skills gets the company prefix (folder name, `name:` and the references between them)."""
    changed = {old: new for old, new in names.items() if old != new}
    pattern = re.compile(r"(?<![\w-])(" + "|".join(re.escape(old) for old in sorted(changed, key=len, reverse=True)) + r")(?![\w-])") if changed else None
    out: Dict[str, bytes] = {}
    for item in sorted(folder.rglob("*")):
        relative = item.relative_to(folder)
        if not item.is_file() or item.name in SKIP_FILES or "__pycache__" in relative.parts or ".git" in relative.parts:
            continue
        data = item.read_bytes()
        if pattern is not None and item.suffix.lower() in TEXT_SUFFIXES:
            try:
                data = pattern.sub(lambda part: changed[part.group(1)], data.decode("utf-8")).encode("utf-8")
            except UnicodeDecodeError:
                pass
        out[relative.as_posix()] = data
    return out


def _on_disk(place: Path) -> Dict[str, bytes]:
    if not place.is_dir():
        return {}
    return {item.relative_to(place).as_posix(): item.read_bytes() for item in sorted(place.rglob("*")) if item.is_file() and item.name not in SKIP_FILES and "__pycache__" not in item.parts}


def _rendered(root: Path, name: str, folder: Path) -> Dict[str, Dict[str, bytes]]:
    """`{final skill name: files}` of a pack's skills."""
    prefix = skillcheck.effective_prefix(root)
    skills = _skills(folder)
    names = {skill.name: _final(prefix, skill.name) for skill in skills}
    return {names[skill.name]: _render(skill, names) for skill in skills}


def _put(place: Path, files: Dict[str, bytes], origin: Path) -> None:
    if place.exists():
        shutil.rmtree(place)
    for relative, data in files.items():
        target = place / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if os.name != "nt":
        for relative in files:  # a script of the skill keeps its execute bit
            source = origin / relative
            if source.is_file() and source.stat().st_mode & 0o111:
                (place / relative).chmod((place / relative).stat().st_mode | 0o111)


def skill_plan(root: Path) -> Dict[str, Any]:
    """What `sync_skills` would do, from files only: `{put: [(final, files, origin folder, names)], keep: {pack: [names]}, drop: [(pack, name)], refused: [...], updated: [...]}`."""
    book = ledger(root)["packs"]
    prefix = skillcheck.effective_prefix(root)
    plan: Dict[str, Any] = {"put": [], "same": [], "drop": [], "refused": [], "updated": [], "renamed": [], "entries": {}}
    plan["refused"] += [{"toolpack": name, "skill": name, "why": say("toolpack.clash", name=name)} for name in clashes(root)]
    on = active(root)
    for name, item in on.items():
        skills = _skills(item["folder"])
        names = {skill.name: _final(prefix, skill.name) for skill in skills}
        old = book.get(name) or {}
        mine = set(old.get("skills") or [])
        got: List[str] = []
        for skill in skills:
            final = names[skill.name]
            files = _render(skill, names)
            have = _on_disk(root / SKILLS_DIR / final)
            if have and final not in mine and have != files:
                plan["refused"].append({"toolpack": name, "skill": final, "why": say("toolpack.skill.clash", skills=final)})
                continue
            got.append(final)
            (plan["same"] if have == files else plan["put"]).append((final, files, skill, name))
        plan["drop"] += [(name, gone) for gone in sorted(mine - set(got))]
        for gone in sorted(mine - set(got)):  # a skill that only changed its company prefix is renamed, not dropped (1.7.35)
            for skill in skills:
                final = names[skill.name]
                if final in got and final not in mine and (gone == skill.name or gone.endswith("-" + skill.name)):
                    plan["renamed"].append({"toolpack": name, "from": gone, "to": final, "base": skill.name})
                    break
        version = str(item["manifest"].get("version") or "")
        entry = {"source": item["source"], "version": version, "skills": sorted(got), "mcp": old.get("mcp") or []}
        if old.get("version") and str(old["version"]) != version:
            entry["updated"] = {"from": str(old["version"]), "to": version, "at": utc_now()}
            plan["updated"].append({"toolpack": name, "from": str(old["version"]), "to": version})
        elif isinstance(old.get("updated"), dict):
            entry["updated"] = old["updated"]
        plan["entries"][name] = entry
    for name, old in book.items():
        if name not in on:
            plan["drop"] += [(name, skill) for skill in old.get("skills") or []]
    return plan


def sync_skills(root: Path) -> Dict[str, Any]:
    """Put the skills of the active packs into `.github/skills/` and take back those of a pack no longer active (they go to the backup folder).
    Returns `{put, removed, updated, refused, lines}` (and `renamed: [{toolpack, from, to}]` when a changed company prefix renamed skills); `lines` are the sentences the board and doctor show.
    1.7.38: when a company pack has the name of a factory pack it stops before it changes anything (no skill put, no skill taken back, no ledger written) and answers
    `{failed: True, clashes: [names], error: <the line>, put: [], removed: [], ...}`; what the last good sync put stays as it was."""
    stop = clash_stop(root)
    if stop:
        return {"put": [], "removed": [], "updated": [], "refused": [{"toolpack": name, "skill": name, "why": say("toolpack.clash", name=name)} for name in clashes(root)], "unknown_use": unknown_use(root),
                "lines": clash_lines(root), "failed": True, "clashes": clashes(root), "error": stop}
    plan = skill_plan(root)
    book = ledger(root)
    put: List[str] = []
    for final, files, origin, _name in plan["put"]:
        _put(root / SKILLS_DIR / final, files, origin)
        put.append(final)
    removed: List[str] = []
    backup = runtime_dir(root) / BACKUP_DIR / time.strftime("%Y%m%d-%H%M%S")
    kept = {skill for entry in plan["entries"].values() for skill in entry["skills"]}
    for pack, skill in plan["drop"]:
        place = root / SKILLS_DIR / skill
        if skill not in kept and place.is_dir():
            backup.mkdir(parents=True, exist_ok=True)
            shutil.move(str(place), str(backup / "skills" / skill))
            removed.append(skill)
    gone_packs = [name for name in book["packs"] if name not in plan["entries"]]
    _drop_mcp(root, [server for name in gone_packs for server in book["packs"][name].get("mcp") or []])
    new_book = {"packs": plan["entries"], "paths": book["paths"]}
    if new_book != {"packs": book["packs"], "paths": book["paths"]}:
        _write_ledger(root, new_book)
    gone = unknown_use(root)
    lines = clash_lines(root) + ([say("doctor.toolpacks.unknown", names=", ".join(gone))] if gone else []) + [say("toolpack.updated", name=item["toolpack"], old=item["from"], new=item["to"]) for item in plan["updated"]]
    renamed = [{"toolpack": item["toolpack"], "from": item["from"], "to": item["to"]} for item in plan["renamed"] if item["to"] in put or item["from"] in removed]
    for pack in dict.fromkeys(item["toolpack"] for item in renamed):
        rows = [item for item in plan["renamed"] if item["toolpack"] == pack]
        stem = os.path.commonprefix([item["base"] for item in rows])
        stem = stem[:stem.rfind("-") + 1] if "-" in stem else ""
        old, new = rows[0]["from"], rows[0]["to"]
        base = len(rows[0]["base"])
        lines.append(say("toolpack.renamed", name=pack, old=old[:len(old) - base] + stem + "*", new=new[:len(new) - base] + stem + "*"))
    return {"put": put, "removed": removed, "updated": plan["updated"], "refused": plan["refused"], "unknown_use": gone, "lines": lines, **({"renamed": renamed} if renamed else {}), **({"backup": str(backup)} if removed else {})}


_CODE = re.compile(r"```.*?```|`[^`\n]+`", re.S)


def command_problems(root: Path) -> List[Dict[str, str]]:
    """Skills of the company (`.github/skills/<prefix>-*`) that write `<program> <word>` in code, where `<program>` is the program of an active pack that lists its `commands`
    and `<word>` is not one of them (1.7.30): `[{skill, program, word, pack}]`. A pack with no `commands` is not checked."""
    prefix = skillcheck.effective_prefix(root)
    if not prefix:
        return []
    programs: Dict[str, tuple] = {}
    for name, item in active(root).items():
        commands = item["manifest"].get("commands")
        if not isinstance(commands, list) or not commands:
            continue
        for _pack, path in [entry for entry in type_entries(root) if entry[0] == name]:
            kind = _json(path)
            if isinstance(kind, dict) and isinstance(kind.get("cli"), list) and kind["cli"]:
                programs.setdefault(str(kind["cli"][0]), (name, {str(one) for one in commands}))
    out: List[Dict[str, str]] = []
    base = root / SKILLS_DIR
    for folder in sorted(base.glob(f"{prefix}-*")) if base.is_dir() and programs else []:
        for file in sorted(folder.rglob("*.md")):
            try:
                text = file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            code = "\n".join(_CODE.findall(text))
            for program, (pack, words) in programs.items():
                for word in dict.fromkeys(re.findall(r"(?<![\w./-])" + re.escape(program) + r"[ \t]+([A-Za-z][\w-]*)", code)):
                    if word not in words:
                        out.append({"skill": folder.name, "program": program, "word": word, "pack": pack})
    return out


def _updated(entry: Dict[str, Any]) -> Dict[str, str]:
    """`{from, to}` when the ledger says the pack's version changed in the last days (the board marks the row), else `{}`."""
    was = entry.get("updated") if isinstance(entry.get("updated"), dict) else None
    if was and _days_ago(str(was.get("at") or "")) <= UPDATED_SHOWN_DAYS:
        return {"from": str(was.get("from") or "?"), "to": str(was.get("to") or entry.get("version") or "?")}
    return {}


def recent_updates(root: Path) -> List[str]:
    """The lines "ado 0.4.5 -> 0.5.0 updated" of the last days, from the ledger: doctor shows them."""
    out = []
    for name, entry in sorted(ledger(root)["packs"].items()):
        was = entry.get("updated") if isinstance(entry.get("updated"), dict) else None
        if was and _days_ago(str(was.get("at") or "")) <= UPDATED_SHOWN_DAYS:
            out.append(say("toolpack.updated", name=name, old=was.get("from", "?"), new=was.get("to", entry.get("version", "?"))))
    return out


def _days_ago(stamp: str) -> float:
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return 9999.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 86400


def share(root: Path, company: Path, name: str) -> bool:
    """For `connections share`: make the pack part of the company's tools. A factory pack goes into `use` of `packs.json`; a folder added here is copied to `packs/<name>/`.
    True when something was written."""
    here = listed(root).get(name)
    if not here or here["source"] == COMPANY:
        return False
    if here["source"] == HARNESS:
        file = company / USE_FILE
        found = _json(file) if file.is_file() else {}
        found = found if isinstance(found, dict) else {}
        use = [str(item) for item in found.get("use") or [] if isinstance(item, str)]
        if name in use:
            return False
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(dict(found, use=use + [name]), indent=2) + "\n", encoding="utf-8")
        return True
    target = company / COMPANY_PACKS / name
    if target.exists():
        return False
    shutil.copytree(here["folder"], target, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", ".git"))
    return True


def set_use(root: Path, name: str, on: bool) -> Dict[str, Any]:
    """Turn a factory pack on or off (the Tools window, 1.7.34): its name goes into, or out of, the `use` list of `<knowledge base>/company/tools/packs.json` (made when missing,
    the other keys and names kept), then the skills are put or taken back at once. The list is the only record of the choice. Raises ToolpackError without a company folder,
    or for a pack that is not a factory pack."""
    here = listed(root).get(name)
    if not here or here["source"] != HARNESS:
        raise ToolpackError(say("toolpack.use.factory", name=name))
    refuse_on_clash(root)
    folder = targets.company_folder(root)
    if folder is None:
        raise ToolpackError(say("toolpack.use.nocompany"))
    file = folder / USE_FILE
    found = _json(file) if file.is_file() else {}
    found = found if isinstance(found, dict) else {}
    use = [str(item) for item in found.get("use") or [] if isinstance(item, str)]
    new = [item for item in use if item != name] + ([name] if on else [])
    if new != use or not file.is_file():
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(dict(found, use=new), indent=2) + "\n", encoding="utf-8")
    done = sync_skills(root)
    apply_mcp(root)
    return {"name": name, "on": bool(on), "use": new, "put": done["put"], "removed": done["removed"]}


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
    """Where MCP is allowed (This computer), each active pack's MCP servers are in `.vscode/mcp.json`; where it is not, the ones a pack put
    there are taken out. A server of the same name that is not a pack's own is never touched (`kept`). The ledger keeps which servers are the packs'."""
    from . import launchenv  # it reads this module

    allowed = launchenv.mcp_allowed(root)
    book = ledger(root)
    found = _read_mcp(root) if (root / VSCODE_MCP).is_file() or allowed else {"servers": {}}
    mine = {server for item in book["packs"].values() for server in item.get("mcp") or []}
    added: List[str] = []
    dropped: List[str] = []
    kept: List[str] = []
    for name, item in active(root).items():
        entry = book["packs"].setdefault(name, {"source": item["source"], "version": str(item["manifest"].get("version") or ""), "skills": []})
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
    if book["packs"]:
        _write_ledger(root, book)
    return {"mcp": "allowed" if allowed else "blocked", "added": added, "dropped": dropped, "kept": kept}


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
    (target / "README.md").write_text(f"# {name}\n\nWhat it is for, in one line.\n\n1. Try it: `harness toolpack add <this folder>`. To keep it, put it in the knowledge base, `company/tools/packs/{name}/`.\n"
                                      "2. Set up: Get ready, Tools, This computer (the program's folder, a CA bundle behind a proxy).\n3. Sign in: Get ready, Tools, Connections.\n"
                                      "4. Try: ask the agent for a read, then for a write: the write waits for you.\n", encoding="utf-8")
    return {"made": str(target), "next": say("toolpack.new.done", path=str(target))}


# --- checking ----------------------------------------------------------------------------------------------------------------------------------------------------

def check_folder(root: Path, folder: Path) -> Dict[str, Any]:
    """`harness toolpack check <folder>`: a tool pack that is not installed yet, file by file."""
    found = problems(root, folder)
    return {"folder": str(folder), "problems": found, "next": say("toolpack.check.ok" if not found else "toolpack.check.bad", n=len(found)), "exit_code": 1 if found else 0}


def check(root: Path, only: str = "") -> Dict[str, Any]:
    """Each pack this computer knows (`harness toolpack list`): where it lies (`from`: company, harness or a folder), whether it is on, problems with its files, the programs it needs
    (found on the PATH VS Code gets), and a CA bundle when it names a trust variable. A pack that is off is listed but its programs are not asked for."""
    from . import launchenv

    path = launchenv.extra(root).get("PATH") or None
    bundle = launchenv.bundle_path(root)
    rows = []
    book = ledger(root)["packs"]
    needs_all = needs_report(root, only)
    for name, item in listed(root).items():
        if only and name != only:
            continue
        folder, found = item["folder"], item["manifest"]
        errors = problems(root, folder)
        needs = found.get("needs") or {}
        types_here = []
        for one in sorted((folder / TYPES).glob("*.json")) if (folder / TYPES).is_dir() else []:
            try:
                spec = json.loads(one.read_text(encoding="utf-8-sig"))
                types_here.append({"type": str(spec.get("type") or one.stem), "label": str(spec.get("label") or spec.get("type") or one.stem), "via": str(spec.get("via") or "cli")})
            except (OSError, ValueError, AttributeError):
                continue
        report = needs_all.get(name) or []
        programs = {str(program): bool(locate(str(program), path)) for program in needs.get("programs") or []}
        for one in report:
            programs[one["program"]] = one["found"] and programs.get(one["program"], True)
        row = {"name": name, "version": str(found.get("version") or ""), "from": item["source"], "source": item["source"], "active": item["active"], "removable": item["source"] not in (COMPANY, HARNESS),
               "errors": errors, "programs": programs, "needs": report if item["active"] else [], "trust": bool(needs.get("trust")), "bundle": bool(bundle), "description": str(found.get("description") or ""), "types": types_here,
               "skills": len(_skills(folder)), "links": sorted((found.get("links") or {}).keys()) if isinstance(found.get("links"), dict) else [],
               "mcp_rules": len((found.get("mcp") or {}).get("tools") or []) if isinstance(found.get("mcp"), dict) else 0, "commands": [str(one) for one in found.get("commands") or []],
               "put": list((book.get(name) or {}).get("skills") or []), "newer": False, "updated": _updated(book.get(name) or {}), "toggle": "" if item["source"] != HARNESS else "on" if targets.company_folder(root) else "nocompany",
               "used": item["source"] != HARNESS or name in use_list(root), "needs_all": declared_needs(folder, found, path),  # 1.7.38: what the pack names, on or off; `used`: the company's packs.json lists it (a company or folder pack is always used)
               "skill_names": _final_names(root, name, folder) if item["active"] else []}
        row["skill_label"] = skill_label(row["skill_names"])
        row["ok"] = not errors and (all(programs.values()) or not item["active"])
        rows.append(row)
    if only and not rows:
        raise ToolpackError(say("toolpack.none", name=only))
    return {"toolpacks": rows, "company": targets.company_folder(root) is not None, "unknown_use": unknown_use(root), "clashes": clash_lines(root), "exit_code": 0 if all(row["ok"] for row in rows) and not clash_lines(root) else 1}
