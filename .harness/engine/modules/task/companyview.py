"""The Company tab of the knowledge base window (1.7.32): what this company's agent can do, from the files that are in place.

One section for each part of `company/`: the company itself, its tools (one block for each active tool pack), its skills (three groups by name,
core/skillgroups.py), its standards and instructions, and the domains. Only reads. Nothing is configured for it. The page draws it (dock.js).
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config, connections, launchenv, messages, reach, skillboard, skillcheck, skillgroups, standards, targets, toolpacks

FIRST_LINE = 160
NO_WORD = re.compile(r"\\.")
OPTION = re.compile(r"(?<![\w-])--?[A-Za-z][\w-]*")  # `--json`, `-h`: an option is no command
WORD = re.compile(r"[A-Za-z][\w-]*")
SKILL_DIR = skillcheck.SKILLS_DIR


def _json(path: Path) -> Dict[str, Any]:
    try:
        found = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def first_line(path: Path) -> str:
    """The first line with words in it, without the Markdown marks; the front matter of a file is skipped."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return ""
    if lines and lines[0].strip() == "---":
        end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
        lines = lines[end + 1:] if end is not None else lines
    for line in lines:
        text = line.strip().lstrip("#>*- ").strip()
        if text:
            return text if len(text) <= FIRST_LINE else text[:FIRST_LINE].rsplit(" ", 1)[0] + "..."
    return ""


def skill_about(path: Path) -> str:
    try:
        fields, _body = skillcheck.frontmatter(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    return skillboard.first_sentence(fields.get("description", ""))


# --- tools --------------------------------------------------------------------------------------------------------------------------------------------

def _text(value: Any, lang: str) -> str:
    if isinstance(value, dict):
        return str(value.get(lang) or value.get("en") or "")
    return str(value or "")


def _words(pattern: str) -> List[str]:
    """The command words a verb pattern names (`\\b(?:comment|set-state)\\b` gives comment, set-state)."""
    return list(dict.fromkeys(word for word in WORD.findall(OPTION.sub(" ", NO_WORD.sub(" ", pattern))) if len(word) > 1))


def _lines(kinds: List[Dict[str, Any]], verb: str, lang: str) -> List[Dict[str, str]]:
    """One line for each thing of this verb that a type allows: its `say` text in the language of the page, else the pattern. `{1}` in a text shows as an ellipsis."""
    out: List[Dict[str, str]] = []
    for kind in kinds:
        says = [item for item in kind.get("say") or [] if isinstance(item, dict) and item.get("pattern")]
        for entry in kind.get("verbs") or []:
            if not isinstance(entry, dict) or entry.get("verb") != verb or not entry.get("pattern"):
                continue
            found: List[str] = []
            for word in _words(str(entry["pattern"])):
                for item in says:
                    try:
                        hit = re.search(str(item["pattern"]), word + " 1 1 1")
                    except re.error:
                        continue
                    if hit:
                        found.append(re.sub(r"\{\d+\}", "…", _text(item.get("text"), lang)))
                        break
            lines = [{"text": text, "pattern": ""} for text in dict.fromkeys(found) if text]
            out += lines or [{"text": "", "pattern": str(entry["pattern"])}]
    return out


def _kinds(folder: Path) -> List[Dict[str, Any]]:
    return [found for found in (_json(path) for path in sorted((folder / "types").glob("*.json"))) if found.get("type")] if (folder / "types").is_dir() else []


def _state(lines: List[Dict[str, Any]]) -> str:
    states = [line["state"] for line in lines]
    return reach.DENIED if reach.DENIED in states else reach.FAILED if reach.FAILED in states else reach.UNKNOWN if reach.UNKNOWN in states or not states else reach.OK


def reason(line: Dict[str, Any]) -> str:
    """Why a connection was not reached, in words (the same words as the Enter screen's table)."""
    if line["state"] == reach.DENIED:
        return str(line.get("launch") or messages.text("desk.reach.why.identity"))
    if line.get("why") == "no-answer":
        return messages.text("desk.reach.why.no-answer")
    return messages.text("desk.reach.why.exit", why=line.get("why") or "")


def _read_names(manifest: Dict[str, Any], kinds: List[Dict[str, Any]]) -> List[str]:
    """The commands the agent may run without asking, by name: a pack that lists its `commands`, less those a write, exec or destroy verb names (1.7.35)."""
    commands = [str(one) for one in manifest.get("commands") or [] if isinstance(one, str)]
    held = {word for kind in kinds for entry in kind.get("verbs") or [] if isinstance(entry, dict) and entry.get("verb") in ("write", "exec", "destroy") for word in _words(str(entry.get("pattern") or ""))}
    return [one for one in commands if one not in held]


def _reads(manifest: Dict[str, Any], kinds: List[Dict[str, Any]]) -> int:
    """How many commands the agent may run without asking. A pack that lists its `commands`: those that no write, exec or destroy verb names (ado: 37 - 6 - 4 = 27).
    One that does not: the command words of its read verbs."""
    commands = [str(one) for one in manifest.get("commands") or [] if isinstance(one, str)]
    if commands:
        held = {word for kind in kinds for entry in kind.get("verbs") or [] if isinstance(entry, dict) and entry.get("verb") in ("write", "exec", "destroy") for word in _words(str(entry.get("pattern") or ""))}
        return len([one for one in commands if one not in held])
    return sum(max(1, len(_words(str(entry.get("pattern") or "")))) for kind in kinds for entry in kind.get("verbs") or [] if isinstance(entry, dict) and entry.get("verb") == "read")


def tools(root: Path, lang: str) -> List[Dict[str, Any]]:
    packs = skillgroups.active_packs(root)
    if not packs:
        return []
    systems = config.policy_or_empty(root, "tools").get("systems") or {}
    seen = reach.view(root, systems) if systems else []
    listed = connections.listed(root)
    needs = toolpacks.needs_report(root)
    out: List[Dict[str, Any]] = []
    for name, item in packs.items():
        manifest, folder = item["manifest"], item["folder"]
        kinds = _kinds(folder)
        types = {str(kind["type"]): kind for kind in kinds}
        programs = [{"name": row["program"], "found": row["found"], "path": row["path"], "why": row["why"]} for row in needs.get(name, [])]  # the pack's own and its connections' sign-in ways (1.7.37)
        links: List[Dict[str, Any]] = []
        for alias, server in listed.items():
            if str(server.get("type")) not in types:
                continue
            rows = [line for line in seen if line["system"] == alias]
            via_mcp = types[str(server["type"])].get("via") == "mcp"
            state = _state(rows) if rows and not via_mcp else "none" if via_mcp else reach.UNKNOWN
            links.append({"name": alias, "type": str(server["type"]), "env": str(server.get("env") or ""), "own": bool(server.get("own")), "state": state,
                          "who": ", ".join(dict.fromkeys(line["who"] for line in rows if line.get("who"))), "why": "; ".join(dict.fromkeys(reason(line) for line in rows if line["state"] in (reach.DENIED, reach.FAILED))),
                          "at": max([str(line.get("at") or "") for line in rows] or [""]), "envs": [{"env": line["env"], "state": line["state"]} for line in rows]})
        missing: List[str] = []
        if any(kind.get("via") != "mcp" for kind in kinds) and not links:
            missing.append("connection")
        if links and all(link["state"] == reach.UNKNOWN for link in links):
            missing.append("untested")
        missing += list(dict.fromkeys(f"program:{program['name']}" for program in programs if not program["found"]))
        reads = _reads(manifest, kinds)
        out.append({"name": name, "source": str(item.get("source") or ""), "version": str(manifest.get("version") or ""), "about": str(manifest.get("description") or ""), "programs": programs, "reads": reads, "read_names": _read_names(manifest, kinds),
                    "writes": _lines(kinds, "write", lang), "execs": _lines(kinds, "exec", lang), "destroys": _lines(kinds, "destroy", lang),
                    "types": [{"type": key, "label": str(kind.get("label") or key), "via": str(kind.get("via") or "cli")} for key, kind in types.items()], "connections": links, "missing": missing})
    return out


# --- skills -------------------------------------------------------------------------------------------------------------------------------------------

def skills(root: Path, company: Optional[Path], prefix: str, packs: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """The skills in `.github/skills/`, in the three groups, then those in the knowledge base or in a tool pack that are not copied there yet (`synced: False`)."""
    out: Dict[str, List[Dict[str, Any]]] = {"harness": [], "company": [], "pack": []}
    here = root / SKILL_DIR
    have = {path.parent.name: path for path in sorted(here.glob("*/SKILL.md"))} if here.is_dir() else {}

    def add(name: str, path: Path, synced: bool) -> None:
        kind, pack = skillgroups.group(name, prefix, packs)
        out[kind].append({"name": name, "about": skill_about(path), "pack": pack, "synced": synced})

    for name, path in have.items():
        add(name, path, True)
    wanted = sorted(item for item in (company / "skills").iterdir() if item.is_dir() and (item / "SKILL.md").is_file()) if company and (company / "skills").is_dir() else []
    for folder in wanted:
        if folder.name not in have:
            add(folder.name, folder / "SKILL.md", False)
    for pack, item in packs.items():
        for folder in sorted((item["folder"] / "skills").glob("*/SKILL.md")) if (item["folder"] / "skills").is_dir() else []:
            named = f"{prefix}-{folder.parent.name}" if prefix else folder.parent.name  # the name its copy gets
            if folder.parent.name not in have and named not in have:
                add(named, folder, False)
    for kind in out.values():
        kind.sort(key=lambda row: (row["pack"], row["name"]))
    return out


def files(folder: Path, suffix: str = ".md") -> List[Dict[str, str]]:
    try:
        found = sorted(path for path in folder.iterdir() if path.is_file() and path.suffix == suffix and path.name not in ("README.md", ".gitkeep"))
    except OSError:
        return []
    return [{"file": path.name, "first": first_line(path)} for path in found]


def instruction_state(root: Path, path_name: str, source: Path) -> str:
    """`copied` / `not-copied` for the one instruction file the engine copies (`company sync`); `never` for every other file: it is listed but nothing copies it."""
    from core import company as company_core

    if path_name not in company_core.INSTRUCTION_FILES:
        return "never"
    return "copied" if company_core.same(source, root / company_core.INSTRUCTIONS_DIR / path_name) else "not-copied"


def standard_state(path_name: str) -> str:
    """`inplace` for the file the code-standards skill reads where it lies; `other` for the rest: not copied and not read by the harness itself."""
    return "inplace" if "standards/" + path_name == standards.COMPANY_FILE else "other"


def company(root: Path, lang: str = "") -> Dict[str, Any]:
    lang = lang or messages.language()
    folder = targets.company_folder(root)
    packs = skillgroups.active_packs(root)
    prefix = skillcheck.company_prefix(root)
    out: Dict[str, Any] = {"found": folder is not None, "prefix": prefix, "name": "", "version": "", "made": "", "stale": 0, "domains": [], "standards": [], "instructions": [], "tools": tools(root, lang),
                           "unknown_use": toolpacks.unknown_use(root), "skills": skills(root, folder, prefix, packs)}
    if folder is None:
        return out
    config_file = _json(folder / "company.json")
    kb = folder.parent
    out.update(name=str(config_file.get("name") or ""), version=str(_json(folder / "manifest.json").get("version") or ""), made=str(_json(folder / "manifest.json").get("made") or ""),
               standards=[dict(row, state=standard_state(row["file"])) for row in files(folder / "standards")],
               instructions=[dict(row, state=instruction_state(root, row["file"], folder / "instructions" / row["file"])) for row in files(folder / "instructions")])
    try:
        out["domains"] = sorted(item.name for item in (kb / "domains").iterdir() if item.is_dir() and not item.name.startswith("."))
    except OSError:
        pass
    try:
        from core import company as company_core

        stale = company_core.drift(root)
        out["stale"] = len(stale["stale"]) if stale else 0
    except Exception:  # noqa: BLE001 - a view must not fail for a broken copy
        pass
    return out
