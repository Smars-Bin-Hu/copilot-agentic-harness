"""The programs a tool pack or the tools policy governs, read as plain text (1.7.38, C13 F2). Used when the gate failed, so it uses none of the code that may have failed.

It reads the files one by one, in every pack folder this computer knows (the factory's, the company's, the folders added here) and in the tools policy files, whether or not the file is valid JSON, and takes the words of
every `cli` and `programs` list it finds, and the files of a pack's `bin/`. `by_address` programs (`curl`) are not among them: they are a call of a system only by the address they name. Stdlib only; nothing here raises."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Set

_LISTS = re.compile(r'"(?:cli|programs)"\s*:\s*(\[[^\]]*\]|"[^"]*")')
_OPEN_LISTS = re.compile(r'"(?:cli|programs)"\s*:\s*\[((?:\s*"[^"]*"\s*,?)*)')  # a list the file ends in the middle of (`"cli": ["sqlcmd"` and nothing more): the words it has
_STRINGS = re.compile(r'"([^"\\]+)"')
_WORD = re.compile(r"[^\s;&|(){}<>`'\"=,:$]+")
_PATTERNS = re.compile(r'"pattern"\s*:\s*"((?:[^"\\]|\\.)*)"')


def folders(root: Path) -> List[Path]:
    """Every folder a tool pack may be in: the factory's, the company's, and the ones added on this computer."""
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
    return found


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


def programs(root: Path) -> Set[str]:
    """The programs the tool packs and the tools policy name, in lower case, read as plain text (see the top of this file)."""
    files: List[Path] = []
    names: Set[str] = set()
    for folder in folders(root):
        try:
            files += [folder / "toolpack.json", folder / "rules.json"] + sorted((folder / "types").glob("*.json"))
            for one in sorted((folder / "bin").iterdir()) if (folder / "bin").is_dir() else []:
                if one.is_file():
                    names.add(re.sub(r"\.(?:cmd|bat|exe|ps1|py|sh)$", "", one.name.lower()))
        except OSError:
            continue
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
