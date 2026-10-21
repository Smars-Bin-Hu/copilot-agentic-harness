"""The defects of a test task (`TEST/defects.md`) and their status, kept by a script, not by hand (1.5.27).

Each defect is one section: `## D1 [open] IST: what failed`, then lines under it. `[open]` becomes `[fixed]` only when the verdict of that
environment is PASS in its results file, and only `harness task defects sync` does it (it also runs at `task handoff`). The verdict is the
one the page shows: the last `Verdict for ...` line of the results file of the environment (taskstages.test_results). A section marked `[fixed]`
without the line the script writes is a hand edit: it is made `[fixed]` properly when the environment passed, and `[open]` again when it did not.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from core import messages, tasks
from core.paths import utc_now

from . import taskstages

FILE = "defects.md"
HEADING = re.compile(r"^##\s+(D\d+)\s+\[(open|fixed)\]\s+([A-Za-z][A-Za-z0-9_-]{0,11}):\s*(.*?)\s*$")
ANY_DEFECT = re.compile(r"^##\s+D\d+\b")
MARK = "- Fixed by `task defects sync`:"


def path_of(root: Path, task: str) -> Path:
    return tasks.task_dir(root, task) / "TEST" / FILE


def split(text: str) -> List[List[Any]]:
    """The file as `[heading line or None, lines under it]`: the first has no heading (what comes before the first `## `)."""
    sections: List[List[Any]] = [[None, []]]
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append([line, []])
        else:
            sections[-1][1].append(line)
    return sections


def parse(text: str) -> Dict[str, Any]:
    """`intro`: the text before the first section. `items`: each defect `{id, status, env, title, body}`. `other`: sections that are not defects
    (they are shown as they are). `odd`: headings that start like a defect (`## D3 ...`) but are not in the form."""
    sections = split(text)
    items: List[Dict[str, Any]] = []
    other: List[Dict[str, str]] = []
    odd: List[str] = []
    for heading, body in sections[1:]:
        found = HEADING.match(heading)
        if found:
            items.append({"id": found.group(1), "status": found.group(2), "env": found.group(3), "title": found.group(4), "body": "\n".join(body).strip()})
        else:
            if ANY_DEFECT.match(heading):
                odd.append(heading.strip())
            other.append({"title": heading[3:].strip(), "body": "\n".join(body).strip()})
    return {"intro": "\n".join(sections[0][1]).strip(), "items": items, "other": other, "odd": odd}


def verdicts(root: Path, task: str) -> Dict[str, tuple]:
    """`{ENV: (verdict, file name)}` as the page shows them."""
    _guide, _envs, found = taskstages.test_results(root, task)
    return {env: (pair[0], pair[1].name) for env, pair in found.items()}


def sync(root: Path, task: str) -> Dict[str, Any]:
    """Make the status of every defect agree with the results: `[open]` to `[fixed]` when its environment is PASS, a hand-made `[fixed]` checked.
    Nothing else is changed. Safe to run again and again."""
    path = path_of(root, task)
    result: Dict[str, Any] = {"file": f"TEST/{FILE}", "changed": [], "open": 0, "fixed": 0, "warnings": []}
    if not path.is_file():
        result["file"] = ""
        return result
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    found = verdicts(root, task)
    today = utc_now()[:10]
    sections = split(text)
    for section in sections[1:]:
        heading, body = section
        match = HEADING.match(heading)
        if not match:
            if ANY_DEFECT.match(heading):
                result["warnings"].append(messages.text("task.defects.odd", line=heading.strip()))
            continue
        ident, status, env, title = match.groups()
        verdict, name = found.get(env.upper(), ("", ""))
        marked = any(line.startswith(MARK) for line in body)
        new, mark = status, False
        if status == "open" and verdict == "PASS":
            new, mark = "fixed", True
        elif status == "fixed" and not marked:
            if verdict == "PASS":
                mark = True
            else:
                new = "open"
                result["warnings"].append(messages.text("task.defects.by_hand", id=ident, env=env))
        if new != status or mark:
            result["changed"].append({"id": ident, "env": env, "to": new})
        if mark:
            blanks = []
            while body and not body[-1].strip():
                blanks.append(body.pop())
            body.append(f"{MARK} {today}, {env} is PASS in {name}.")
            body.extend(reversed(blanks))
        section[0] = f"## {ident} [{new}] {env}: {title}"
        result["fixed" if new == "fixed" else "open"] += 1
    lines: List[str] = []
    for heading, body in sections:
        if heading is not None:
            lines.append(heading)
        lines.extend(body)
    new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return result
