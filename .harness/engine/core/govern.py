"""The programs a tool pack or the tools policy governs, read as plain text (1.7.38, C13 F2). Used when the gate failed, so it uses none of the code that may have failed.

It reads the files one by one, in every pack folder this computer knows (the factory's, the company's, the folders added here) and in the tools policy files, whether or not the file is valid JSON, and takes the words of
every `cli` and `programs` list it finds, and the files of a pack's `bin/`. `by_address` programs (`curl`) are not among them: they are a call of a system only by the address they name. Stdlib only; nothing here raises."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set

_LISTS = re.compile(r'"(?:cli|programs)"\s*:\s*(\[[^\]]*\]|"[^"]*")')
_OPEN_LISTS = re.compile(r'"(?:cli|programs)"\s*:\s*\[((?:\s*"[^"]*"\s*,?)*)')  # a list the file ends in the middle of (`"cli": ["sqlcmd"` and nothing more): the words it has
_STRINGS = re.compile(r'"([^"\\]+)"')
_WORD = re.compile(r"[^\s;&|(){}<>`'\"=,:$]+")
_PATTERNS = re.compile(r'"pattern"\s*:\s*"((?:[^"\\]|\\.)*)"')


def folders(root: Path) -> List[Path]:
    """Every folder a tool pack may be in: the factory's, the company's, the ones added on this computer, and (1.7.38, C13 F2c) the company packs of a knowledge base that the target policy registers and cannot be read of."""
    found: List[Path] = []
    try:
        factory = root / ".harness" / "toolpacks"
        found += [item for item in sorted(factory.iterdir()) if item.is_dir()] if factory.is_dir() else []
    except OSError:
        pass
    try:
        from core import targets, toolpacks

        company = targets.company_folder(root)
        base = company / toolpacks.COMPANY_PACKS if company else None
        found += [item for item in sorted(base.iterdir()) if item.is_dir()] if base is not None and base.is_dir() else []
        found += [Path(raw) for raw in toolpacks.paths(root)]
    except Exception:  # noqa: BLE001 - what cannot be asked is skipped: the files that can be read are still read
        pass
    found += [folder for folder in kb_pack_folders(root) if folder not in found]
    return found


_KB_PATH = re.compile(r'"(path|repos_root)"\s*:\s*("(?:[^"\\]|\\.)*")')
MAX_KB_CHILDREN = 300


def kb_pack_folders(root: Path) -> List[Path]:
    """The company tool pack folders of the knowledge bases that the target policy files name, found from their text, when the list of knowledge bases cannot be read (`targets.kb_fault`); else (and for the knowledge bases the
    gate already sees) none. The files are read as plain text: every `path` and `repos_root` string of `target.json`, the company's and the person's layer, whether or not the file is valid JSON; a folder that holds a
    `company/` folder is a knowledge base, and so is each such folder directly in `repos_root`. Never raises."""
    try:
        from core import targets, toolpacks
        from core.paths import policies_dir

        if targets.kb_fault(root) is None:
            return []
        seen = {str(path.resolve()) for _name, path in targets.knowledge_bases(root)}
        kbs: List[Path] = []
        for suffix in ("", ".company", ".override"):
            for key, raw in _KB_PATH.findall(_text(policies_dir(root) / f"target{suffix}.json")):
                try:
                    value = str(json.loads(raw)).strip()
                except ValueError:
                    continue
                if not value:
                    continue
                place = targets.expand(value, root)
                options = [place]
                if key == "repos_root" and place.is_dir():
                    options = sorted(item for item in place.iterdir() if item.is_dir())[:MAX_KB_CHILDREN]
                kbs += [item for item in options if (item / targets.COMPANY_DIR).is_dir() and str(item.resolve()) not in seen]
        out: List[Path] = []
        for kb in kbs:
            base = kb / targets.COMPANY_DIR / toolpacks.COMPANY_PACKS
            out += [item for item in sorted(base.iterdir()) if item.is_dir() and item not in out] if base.is_dir() else []
        return out
    except Exception:  # noqa: BLE001 - the last net: what cannot be found is not found
        return []


LEDGER = "kb-programs.json"  # in `.harness/runtime/`: `{pack: [programs]}` of the company tool packs the gate saw in a knowledge base registered somewhere else, the last time the list of knowledge bases could be read


def _ledger(root: Path) -> Dict[str, List[str]]:
    try:
        from core.paths import runtime_dir

        found = json.loads((runtime_dir(root) / LEDGER).read_text(encoding="utf-8"))
        return {str(pack): [str(one) for one in names if isinstance(one, str) and one] for pack, names in found.items() if isinstance(names, list)} if isinstance(found, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def remember(root: Path) -> None:
    """(1.7.38, C13 F2c) While the list of knowledge bases can be read: keep the programs of the company packs in a knowledge base registered somewhere else (not `knowledge-base/` of this folder, which is always seen) in
    `.harness/runtime/kb-programs.json`, and drop the file when there are none. When the list cannot be read later, even a file with nothing left in it, the programs are still known (`kb_systems`). Written only when it changes.
    Called by the gate; never raises, never changes what the gate decides."""
    try:
        from core import targets, toolpacks
        from core.paths import runtime_dir

        if targets.kb_fault(root) is not None:
            return
        folder = targets.company_folder(root)
        default = root / targets.KB_DIR / targets.COMPANY_DIR
        base = folder / toolpacks.COMPANY_PACKS if folder is not None and folder.resolve() != default.resolve() else None
        known = {pack.name: sorted(_pack_programs(pack)) for pack in sorted(base.iterdir()) if pack.is_dir()} if base is not None and base.is_dir() else {}
        known = {pack: names for pack, names in known.items() if names}
        if known == _ledger(root):
            return
        path = runtime_dir(root) / LEDGER
        if not known:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(known, indent=1) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 - a note for later must not get in the way of a call
        pass


def kb_systems(root: Path) -> Dict[str, Any]:
    """(1.7.38, C13 F2c) For the gate: when the list of knowledge bases cannot be read, one system `broken-kb-<pack>` for each company tool pack found in the text of the target policy files (`kb_pack_folders`) that owns every
    program of the pack, so a call of one waits for the user and the card names the file and the fault. The gate cannot place those programs otherwise: the packs are in a knowledge base it does not see. A pack the gate saw while the list could
    be read (`remember`) is held too, even when no file names its folder any more. `{}` when the list is fine or no pack was found or remembered (the fault is then `harness doctor`'s). Never raises."""
    try:
        from core import targets

        fault = targets.kb_fault(root)
        if fault is None:
            return {}
        out: Dict[str, Any] = {}
        said = f"{fault[0]}: {fault[1]} (the list of knowledge bases: the tool pack %s cannot be placed)"
        for folder in kb_pack_folders(root):
            names = sorted(_pack_programs(folder))
            if names:
                out[f"broken-kb-{folder.name}"] = {"reach": {"cli": names}, "env": "none", "toolpack": folder.name, "broken": (said % folder.name)[:400]}
        for pack, names in _ledger(root).items():  # the packs the gate saw before the list could not be read, wherever they were
            if f"broken-kb-{pack}" not in out and names:
                out[f"broken-kb-{pack}"] = {"reach": {"cli": sorted(set(names))}, "env": "none", "toolpack": pack, "broken": (said % pack)[:400]}
        return out
    except Exception:  # noqa: BLE001
        return {}


def cli_words(text: str) -> List[str]:
    """The words of every `cli` and `programs` list in a text that may not be valid JSON, in lower case."""
    names: Set[str] = set()
    for found in _LISTS.findall(text or "") + _OPEN_LISTS.findall(text or ""):
        names.update(word.lower() for word in _STRINGS.findall(found) if word.strip())
    return sorted(names)


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def _pack_programs(folder: Path) -> Set[str]:
    """The programs one pack folder names, read as plain text: its `cli` and `programs` lists and the files of its `bin/`."""
    names: Set[str] = set()
    try:
        files = [folder / "toolpack.json", folder / "rules.json"] + sorted((folder / "types").glob("*.json"))
        for one in sorted((folder / "bin").iterdir()) if (folder / "bin").is_dir() else []:
            if one.is_file():
                names.add(re.sub(r"\.(?:cmd|bat|exe|ps1|py|sh)$", "", one.name.lower()))
    except OSError:
        return names
    for path in files:
        names.update(cli_words(_text(path)))
    names.discard("")
    return names


def programs(root: Path) -> Set[str]:
    """The programs the tool packs and the tools policy name, in lower case, read as plain text (see the top of this file)."""
    names: Set[str] = set()
    for folder in folders(root):
        names |= _pack_programs(folder)
    files: List[Path] = []
    try:
        files += sorted((root / ".harness" / "policies").glob("tools*.json"))
    except OSError:
        pass
    for path in files:
        names.update(cli_words(_text(path)))
    names.discard("")
    return names


_MENTION_ONLY = frozenset("echo printf which type whereis whatis man apropos grep egrep fgrep rg cat head tail wc ls dir command git get-command gcm get-help test [ [[".split())  # a line that starts so only talks about a program


def named(root: Path, command: str) -> str:
    """The first governed program that the command names as a word (`/usr/bin/sqlcmd`, `sqlcmd.exe` and `sqlcmd` are one name); empty when it names none, or when this cannot be told. A command whose first word only
    talks about a program (`echo`, `which`, `grep`, `git log -S`...) does not name it."""
    try:
        have = programs(root)
        if not have:
            return ""
        for segment in re.split(r"[;&|\n]", command):
            words = _WORD.findall(segment)
            if not words or _base(words[0]) in _MENTION_ONLY:
                continue
            for word in words:
                if _base(word) in have:
                    return _base(word)
    except Exception:  # noqa: BLE001 - a question that cannot be answered leaves the line as it was
        pass
    return ""


def _base(word: str) -> str:
    return re.sub(r"\.(?:cmd|bat|exe)$", "", word.strip(".!?*#@%+").replace("\\", "/").rsplit("/", 1)[-1].lower())


def names_tool(root: Path, tool: str) -> str:
    """The tool pack whose MCP tool rules match this tool name (read as plain text from `toolpack.json`), or empty."""
    try:
        for folder in folders(root):
            raw = _text(folder / "toolpack.json")
            if '"mcp"' not in raw:
                continue
            for pattern in _PATTERNS.findall(raw):
                try:
                    if re.search(json.loads(f'"{pattern}"'), tool, re.IGNORECASE):
                        return folder.name
                except (re.error, ValueError):
                    return folder.name  # a rule that cannot be read: the tool may be its own
    except Exception:  # noqa: BLE001
        pass
    return ""
