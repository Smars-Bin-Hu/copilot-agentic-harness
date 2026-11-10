"""What skills show on the board (1.6.62). A skill says it in its frontmatter, so a company skill appears when it writes the same lines; the board holds no list.

Keys, all optional, one line each:
  board-opens: chat | task | reply    how a click starts it. A skill with no `board-opens` is not on the board.
  board-place: ask, kb, task, all     where it is offered, several with commas
  board-kind:  <task kind>            with `task`
  board-cost:  high                   the window says it costs more
  board-label: <short name>
  board-group: harness, kb or task    the part of the window; none: task
  board-order: <number>               the place in its part, small first; none: last
  board-step:  start, toolkit, domains, learn or keep    the step of building a knowledge base, a heading in the window
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from . import skillcheck, skillgroups, targets, tasks

OPENS = ("chat", "task", "reply")
PLACES = ("ask", "kb", "task", "all")
COSTS = ("high",)
GROUPS = ("harness", "kb", "task")
STEPS = ("start", "toolkit", "domains", "learn", "keep")
LAST = 999
ABOUT = 200
KEYS = ("board-opens", "board-place", "board-kind", "board-cost", "board-label", "board-group", "board-order", "board-step")


def problems(fields: Dict[str, str]) -> List[str]:
    """The `board-*` values that are not allowed: for `skill check`."""
    wrong: List[str] = []
    if fields.get("board-opens") and fields["board-opens"] not in OPENS:
        wrong.append("board-opens")
    if any(place.strip() not in PLACES for place in fields.get("board-place", "").split(",") if place.strip()):
        wrong.append("board-place")
    if fields.get("board-cost") and fields["board-cost"] not in COSTS:
        wrong.append("board-cost")
    if fields.get("board-group") and fields["board-group"] not in GROUPS:
        wrong.append("board-group")
    if fields.get("board-order") and not fields["board-order"].isdigit():
        wrong.append("board-order")
    if fields.get("board-step") and fields["board-step"] not in STEPS:
        wrong.append("board-step")
    if fields.get("board-kind") and fields["board-kind"] not in tasks.KINDS:
        wrong.append("board-kind")
    if any(key.startswith("board-") and key not in KEYS for key in fields):
        wrong.extend(key for key in fields if key.startswith("board-") and key not in KEYS)
    return wrong


def first_sentence(text: str) -> str:
    """At most ABOUT characters; a cut ends at a word and says so."""
    sentence = text.split(". ")[0].strip().rstrip(".")
    if len(sentence) <= ABOUT:
        return sentence
    return sentence[:ABOUT].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."


def skills(root: Path) -> List[Dict[str, Any]]:
    """The skills a person can start from the board, by name. A value `skill check` would refuse (a copy edited by hand) counts as not written: the skill stays on the board.
    `gone`: a company skill no longer in the knowledge base; `company sync` deletes nothing, so its copy stays."""
    out: List[Dict[str, Any]] = []
    folder = root / skillcheck.SKILLS_DIR
    company, prefix = targets.company_folder(root), skillcheck.company_prefix(root)
    packs = skillgroups.active_packs(root)
    for path in sorted(folder.glob("*/SKILL.md")) if folder.is_dir() else []:
        try:
            fields, _body = skillcheck.frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        opens = fields.get("board-opens", "")
        naming, pack = skillgroups.group(path.parent.name, prefix, packs)
        if opens not in OPENS and naming != "pack":  # a tool pack's skill is listed under its pack even with no click-to-start (1.7.34): name and description only
            continue
        opens = opens if opens in OPENS else ""
        out.append({"name": path.parent.name, "label": fields.get("board-label") or path.parent.name, "about": first_sentence(fields.get("description", "")), "opens": opens,
                    "place": [place.strip() for place in fields.get("board-place", "all" if opens else "").split(",") if place.strip()], "kind": fields.get("board-kind", "") if fields.get("board-kind") in tasks.KINDS else "", "costly": fields.get("board-cost") == "high",
                    "hint": fields.get("argument-hint", ""), "own": path.parent.name.split("-")[0] not in ("harness", "generic"),
                    "group": fields.get("board-group") if fields.get("board-group") in GROUPS else "task", "order": int(fields["board-order"]) if fields.get("board-order", "").isdigit() else LAST, "step": fields.get("board-step") if fields.get("board-step") in STEPS else "",
                    "naming": naming, "pack": pack,
                    "gone": bool(naming != "pack" and company and prefix and path.parent.name.startswith(prefix + "-") and not (company / "skills" / path.parent.name).is_dir())})
    return sorted(out, key=lambda item: (item["order"], item["name"]))
