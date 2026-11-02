"""The map of the domains: which domain uses which, for a person. The agent has `kb near`; this is the same knowledge drawn for reading.

Nothing new is stored. Who owns an object is in `objects/index.jsonl` of each domain, who uses what is in the map (`kb map`). A use across two domains is a line.
An object the map knows and no domain owns is `loose`: a boundary, or a gap in what was learned.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from . import domainskills, kbgraph, kbstatus, kbstd, miniyaml

PAIRS = 20  # the uses a line keeps by name
SAMPLE = 20
MAX_OWNERS = 20000  # what the search on the page can find


def spec(folder: Path) -> Dict[str, Any]:
    try:
        found = miniyaml.loads((folder / kbstd.DOMAIN_FILE).read_text(encoding="utf-8"))
    except (OSError, miniyaml.YamlError):
        return {}
    return found if isinstance(found, dict) else {}


def outdated(root: Path, domain: str) -> int:
    """Cards whose source changed since. Unknown (no git, no such repository) counts as none: this view does not judge, `kb stale` does."""
    try:
        found = kbstd.stale(root, domain)
    except Exception:  # noqa: BLE001 - one domain that cannot be read must not lose the map
        return 0
    return len(found.get("changed") or []) + len(found.get("gone") or [])


def atlas(root: Path) -> Dict[str, Any]:
    """{domains, links, loose, owners, audited}. MapError: no map yet; the window says so."""
    graph = kbgraph.need_map(root)
    known = domainskills.domains(root)
    states = {item["domain"]: item for item in kbstatus.status(root, True)["domains"]}
    owners: Dict[str, str] = {}
    twice: List[str] = []
    domains: List[Dict[str, Any]] = []
    for name in sorted(known, key=str.lower):
        try:
            rows, _bad = kbstd.read_index(known[name] / kbstd.INDEX_FILE)
        except OSError:
            rows = []  # listed, nothing learned yet
        for row in rows:
            if row["id"] in owners:
                twice.append(row["id"])
            else:
                owners[row["id"]] = name
        about, state = spec(known[name]), states.get(name, {})
        domains.append({"name": name, "about": str(about.get("description") or ""), "objects": len(rows), "types": dict(Counter(str(row.get("type") or "") for row in rows)),
                        "entries": [str(item) for item in about.get("entry_points") or []], "questions": len(about.get("open_questions") or []), "done": bool(state.get("done")),
                        "left": int(state.get("to_learn") or 0), "requests": int(state.get("requests_open") or 0), "outdated": outdated(root, name)})
    counts: Counter = Counter()
    pairs: Dict[Any, List[List[str]]] = {}
    loose: Counter = Counter()
    for node, name in owners.items():
        for target, _how in graph.out.get(node, []):
            other = owners.get(target)
            if other is None:
                if target in graph.nodes:
                    loose[target] += 1
            elif other != name:
                counts[(name, other)] += 1
                held = pairs.setdefault((name, other), [])
                if len(held) < PAIRS:
                    held.append([node, target])
    steps = {step["step"]: step for step in kbstatus.status(root, False)["steps"]}
    return {"domains": domains, "links": [{"from": one, "to": two, "uses": number, "pairs": pairs[(one, two)]} for (one, two), number in sorted(counts.items())],
            "loose": {"objects": len(loose), "sample": [name for name, _uses in loose.most_common(SAMPLE)]}, "twice": sorted(set(twice))[:SAMPLE],
            "owners": dict(list(owners.items())[:MAX_OWNERS]), "audited": bool(steps.get("audit", {}).get("done"))}
