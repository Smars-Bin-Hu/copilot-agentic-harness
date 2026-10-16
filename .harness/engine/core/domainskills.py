"""Domain skills (M15-8): skills of one business domain live in the knowledge base, not in `.github/skills/`.

  <knowledge base>/domains/<domain>/skills/<skill>/SKILL.md     the same form as a skill in .github/skills/

Copilot finds skills only in fixed folders (`.github/skills/` and the like). So these are not in the `/` menu and not
in the context of every prompt. The harness finds them instead: a task names its domains (`task set-domain`), and
the agent is told which skills those domains have and when each is used; it reads the SKILL.md and follows it.
A knowledge base is `knowledge-base/` or a repository registered with `knowledge_base: true` (target.json).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from . import skillcheck, targets

DOMAINS_DIR = "domains"
SKILLS_DIR = "skills"
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def domains(root: Path) -> Dict[str, Path]:
    """{domain: its folder}, over every knowledge base. The first knowledge base that has a domain wins."""
    found: Dict[str, Path] = {}
    for _name, base in targets.knowledge_bases(root):
        folder = base / DOMAINS_DIR
        try:
            items = sorted(folder.iterdir()) if folder.is_dir() else []
        except OSError:
            items = []
        for item in items:
            if item.is_dir() and NAME.match(item.name) and item.name not in found:
                found[item.name] = item
    return found


def shown_path(root: Path, path: Path) -> str:
    """A path the agent can read: from the harness root when it is inside, else as it is on this computer."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def skills(root: Path, only: List[str] | None = None) -> List[Dict[str, Any]]:
    """The skills of the domains in `only` (all domains when None): domain, name, description, who starts it, path."""
    out: List[Dict[str, Any]] = []
    for domain, folder in domains(root).items():
        if only is not None and domain not in only:
            continue
        base = folder / SKILLS_DIR
        try:
            items = sorted(base.iterdir()) if base.is_dir() else []
        except OSError:
            items = []
        for item in items:
            page = item / "SKILL.md"
            if not page.is_file():
                continue
            try:
                fields, _body = skillcheck.frontmatter(page.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            user_only = str(fields.get("disable-model-invocation", "")).lower() == "true"
            out.append({
                "domain": domain, "name": fields.get("name") or item.name, "description": fields.get("description", ""),
                "start": "user-only" if user_only else "agent", "path": shown_path(root, page),
            })
    return out


def folders(root: Path) -> List[Path]:
    """Every domain skill folder, for `skill check`."""
    return [(Path(item["path"]) if Path(item["path"]).is_absolute() else root / item["path"]).parent for item in skills(root)]
