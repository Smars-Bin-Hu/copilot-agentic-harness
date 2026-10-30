"""The company's code standards, written by the company, read by the skill `generic-code-standards`: `<knowledge base>/company/standards/code-standards.md`
when it is there, else `.harness/standards/code-standards.md`, so that a copy of the harness can stay clean.

A rule is a `###` heading. The file ships without any, so "plugged in" means it has at least one rule outside an HTML comment.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from . import domainskills, messages, targets

STANDARDS_FILE = ".harness/standards/code-standards.md"
COMPANY_FILE = "standards/code-standards.md"
COMMENT = re.compile(r"<!--.*?-->", re.S)
FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.M | re.S)
HEADING = re.compile(r"^###\s+(\S.*)$", re.M)
FIELDS = ("Applies to", "Rule")


def source(root: Path) -> Path:
    folder = targets.company_folder(root)
    return folder / COMPANY_FILE if folder is not None and (folder / COMPANY_FILE).is_file() else root / STANDARDS_FILE


def shown(root: Path) -> str:
    return domainskills.shown_path(root, source(root))


def rules(root: Path) -> List[Dict[str, Any]]:
    """[{"title", "missing"}] for every rule of the file; `missing` names the fields (Applies to, Rule) a rule lacks. Empty when the file is missing or unreadable."""
    path = source(root)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    text = FENCE.sub("", COMMENT.sub("", text))  # the example rule in a fence is not a rule
    parts = HEADING.split(text)
    found = []
    for index in range(1, len(parts), 2):
        body = parts[index + 1]
        found.append({"title": parts[index].strip(), "missing": [name for name in FIELDS if f"**{name}**" not in body]})
    return found


def plugged_in(root: Path) -> bool:
    return bool(rules(root))


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)
