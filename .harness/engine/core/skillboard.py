"""What skills show on the board (1.6.62). A skill says it in its frontmatter, so a company skill appears when it writes the same lines; the board holds no list.

Keys, all optional, one line each:
  board-opens: chat | task | reply    how a click starts it. A skill with no `board-opens` is not on the board.
  board-place: ask, kb, task, all     where it is offered, several with commas
  board-kind:  <task kind>            with `task`
  board-cost:  high                   the window says it costs more
  board-label: <short name>
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from . import skillcheck

OPENS = ("chat", "task", "reply")
PLACES = ("ask", "kb", "task", "all")
COSTS = ("high",)
KEYS = ("board-opens", "board-place", "board-kind", "board-cost", "board-label")


def problems(fields: Dict[str, str]) -> List[str]:
    """The `board-*` values that are not allowed: for `skill check`."""
    wrong: List[str] = []
    if fields.get("board-opens") and fields["board-opens"] not in OPENS:
        wrong.append("board-opens")
    if any(place.strip() not in PLACES for place in fields.get("board-place", "").split(",") if place.strip()):
        wrong.append("board-place")
    if fields.get("board-cost") and fields["board-cost"] not in COSTS:
        wrong.append("board-cost")
    if any(key.startswith("board-") and key not in KEYS for key in fields):
        wrong.extend(key for key in fields if key.startswith("board-") and key not in KEYS)
    return wrong


def first_sentence(text: str) -> str:
    return text.split(". ")[0].strip().rstrip(".")[:200]


def skills(root: Path) -> List[Dict[str, Any]]:
    """The skills a person can start from the board, by name."""
    out: List[Dict[str, Any]] = []
    folder = root / skillcheck.SKILLS_DIR
    for path in sorted(folder.glob("*/SKILL.md")) if folder.is_dir() else []:
        try:
            fields, _body = skillcheck.frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        opens = fields.get("board-opens", "")
        if opens not in OPENS:
            continue
        out.append({"name": path.parent.name, "label": fields.get("board-label") or path.parent.name, "about": first_sentence(fields.get("description", "")), "opens": opens,
                    "place": [place.strip() for place in fields.get("board-place", "all").split(",") if place.strip()], "kind": fields.get("board-kind", ""), "costly": fields.get("board-cost") == "high",
                    "hint": fields.get("argument-hint", ""), "own": path.parent.name.split("-")[0] not in ("harness", "generic")})
    return out
