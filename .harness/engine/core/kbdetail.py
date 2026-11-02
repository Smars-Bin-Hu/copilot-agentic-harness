"""What the knowledge base window shows beside `kb status` (1.6.86): the stale cards, the form errors, when a task last read a domain, and the gaps of the map.

These ask git and read the logs, so they are their own views: the window draws `kb status` at once and fills these in. On a work computer a process takes more than a second.
Only reads. One domain that cannot be read must not lose the others.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from . import domainskills, kbgraph, kbmap, kbreads, kbstd, messages

MAX_LIST = 50  # lines of one list in the Health tab; the commands give the rest


def stale_of(root: Path) -> Dict[str, Dict[str, Any]]:
    """domain -> what `kb stale` says of it, or {"error": words}."""
    found: Dict[str, Dict[str, Any]] = {}
    for name in sorted(domainskills.domains(root), key=str.lower):
        try:
            found[name] = kbstd.stale(root, name)
        except FileNotFoundError:  # a domain with no cards yet is no failure, and a person has no use for a path and an errno
            found[name] = {"error": messages.text("dock.kb.health.nocards")}
        except Exception as error:  # noqa: BLE001 - told in the window
            found[name] = {"error": str(error)[:300]}
    return found


def count(item: Dict[str, Any]) -> int:
    return len(item.get("changed") or []) + len(item.get("gone") or [])


def form_errors(root: Path) -> int:
    try:
        return int(kbstd.check(root).get("errors") or 0)
    except Exception:  # noqa: BLE001 - the Health tab says why
        return 0


def detail(root: Path) -> Dict[str, Any]:
    """{domains: {name: {stale, read}}, stale, form_errors}. `read`: the time a task last read the domain, "" for never. `stale` is null when it could not be told."""
    reads = kbreads.last_by_domain(root)
    stale = stale_of(root)
    return {
        "domains": {name: {"stale": None if "error" in item else count(item), "read": reads.get(name.lower(), "")} for name, item in stale.items()},
        "stale": sum(count(item) for item in stale.values()),
        "form_errors": form_errors(root),
    }


def gaps(root: Path) -> Dict[str, Any]:
    """The names the code uses that no repository defines. {} with no map yet."""
    try:
        found = kbgraph.gaps(root)
    except kbmap.MapError:
        return {}
    return {"missing": len(found["missing"]), "names": [item["name"] for item in found["missing"][:MAX_LIST]],
            "obsolete_used": len(found["obsolete_used"]), "obsolete": [item["id"] for item in found["obsolete_used"][:MAX_LIST]]}


def health(root: Path) -> Dict[str, Any]:
    """`kb check`, and beside it the stale cards by domain and the gaps."""
    result = kbstd.check(root)
    rows = []
    for name, item in stale_of(root).items():
        lost = [{"domain": name, "repo": entry["repo"], "error": entry["error"]} for entry in item.get("unreadable_repos") or []]
        if item.get("error") or count(item) or lost:
            rows.append({"domain": name, "error": item.get("error", ""), "unreadable": lost, "total": count(item),
                         "changed": [entry["id"] for entry in item.get("changed") or []][:MAX_LIST], "gone": [entry["id"] for entry in item.get("gone") or []][:MAX_LIST]})
    return {**result, "stale": rows, "gaps": gaps(root)}
