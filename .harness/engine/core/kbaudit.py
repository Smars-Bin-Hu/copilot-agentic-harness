"""How right is the map? A measured answer, not a feeling (M27).

  kb audit                      a sample of objects of each type, spread from short to long, without their uses: what
                                someone reads in the code, blind, before looking at the map
  kb audit --answers <file>     those readings against the map, per type: recall (of the uses read, how many the map
                                has) and precision (of the uses the map has, how many were read), with every difference

`facts.jsonl` checks 5 to 10 uses a person knew; this checks a sample of every type, both ways. A reading is not
truth either: every difference is looked up again at the line the reading gives, before the score counts.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from . import kbgraph, messages
from .kbgraph import Graph, MapError, keys_of

PER_TYPE = 5
MIN_SCORE = 0.95
SHOWN = 100


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def audited_types(graph: Graph, wanted: Optional[List[str]]) -> List[str]:
    """The types asked for; else the types whose objects use something (a table that uses nothing has nothing to audit)."""
    if wanted:
        unknown = sorted(set(wanted) - {item["type"] for item in graph.nodes.values()})
        if unknown:
            raise MapError(say("kbaudit.type", types=", ".join(unknown)))
        return sorted(set(wanted))
    return sorted({graph.nodes[node]["type"] for node, links in graph.out.items() if links})


def sample(root: Path, per_type: int = PER_TYPE, types: Optional[List[str]] = None, seed: int = 1) -> Dict[str, Any]:
    """`kb audit`: per type, `per_type` live objects spread over their sizes (one from each slice, short to long), picked
    the same way for the same seed and map. Where each is, not what it uses."""
    graph = kbgraph.need_map(root)
    pick = random.Random(seed)
    found = []
    for kind in audited_types(graph, types):
        nodes = sorted((node for node, item in graph.nodes.items() if item["type"] == kind and not item.get("obsolete")),
                       key=lambda node: (graph.nodes[node].get("size") or 0, node))
        count = min(per_type, len(nodes))
        for number in range(count):
            part = nodes[len(nodes) * number // count:len(nodes) * (number + 1) // count]
            node = pick.choice(part)
            item = graph.nodes[node]
            found.append({"id": node, "type": kind, "repo": item["repo"], "path": item["path"], "line": item["line"],
                          "lines": item.get("size") or 0, **({"dynamic": True} if item["dynamic"] else {})})
    return {"objects": found, "kinds": sorted({kind for links in graph.out.values() for _t, kind in links}),
            "answer_form": {"from": "<id>", "to": "<name as the code writes it, or an id>", "kind": "<a kind above>", "line": 0},
            "next": say("kbaudit.sample.next")}


def read_answers(path: Path) -> Tuple[Dict[str, List[Dict[str, Any]]], List[str]]:
    """from -> its readings. A line `{"from": id, "none": true}` says the object was read and uses nothing."""
    found: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    bad = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise MapError(say("kbaudit.answers.unreadable", file=path, error=error)) from None
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad.append(say("kbaudit.answers.line", line=number))
            continue
        if not isinstance(row, dict) or not row.get("from") or not (row.get("to") or row.get("none")):
            bad.append(say("kbaudit.answers.line", line=number))
            continue
        found[str(row["from"])].extend([] if row.get("none") else [row])
    return found, bad


def target(graph: Graph, name: str, names: Dict[str, str], mapped: Set[str]) -> str:
    """The key a reading's `to` is compared by: an id when one object fits (or one of those that fit is a use the map
    has); else the missing or outside name of the map that it names; else the name itself, lower case."""
    if name in graph.nodes:
        return name
    if "[" in name or '"' in name:
        name = ".".join(kbgraph.parts(name))  # `[dbo].[t]` as the code writes it -> `dbo.t`
    low = name.lower()
    fits = [node for node, item in graph.nodes.items() if low in keys_of(item["name"]) or node.lower() == low]
    if len(fits) > 1:
        fits = [node for node in fits if node in mapped] or fits
    if len(fits) == 1:
        return fits[0]
    for key in keys_of(name):
        if key in names:
            return names[key]
    return "?" + low


def score(root: Path, answers: Path, least: float = MIN_SCORE) -> Dict[str, Any]:
    """`kb audit --answers`: per type, recall and precision of the map against the readings, and every difference."""
    graph = kbgraph.need_map(root)
    readings, bad = read_answers(answers)
    unknown = sorted(node for node in readings if node not in graph.nodes)
    per: Dict[str, Dict[str, int]] = defaultdict(lambda: {"objects": 0, "read": 0, "map": 0, "both": 0})
    left_out, extra, kinds = [], [], []
    for node, rows in sorted(readings.items()):
        if node not in graph.nodes:
            continue
        outside = {name: "!" + name for name, users in list(graph.missing.items()) + list(graph.external.items()) if node in users}
        names = {key: value for name, value in outside.items() for key in keys_of(name)}
        mapped: Dict[str, Set[str]] = defaultdict(set)
        for other, kind in graph.out.get(node, []):
            mapped[other].add(kind)
        for value in outside.values():
            mapped[value].add("")
        read: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            if row.get("dynamic"):
                continue  # built at run time: out of reach of any map, not scored
            read.setdefault(target(graph, str(row["to"]), names, set(mapped)), row)
        stats = per[graph.nodes[node]["type"]]
        stats["objects"] += 1
        stats["read"] += len(read)
        stats["map"] += len(mapped)
        stats["both"] += len(set(read) & set(mapped))
        show = lambda key: key[1:] if key[0] in "!?" else key
        for key in sorted(set(read) - set(mapped)):
            row = read[key]
            left_out.append({"object": node, "uses": show(key), "line": row.get("line"), "path": graph.nodes[node]["path"]})
        for key in sorted(set(mapped) - set(read)):
            extra.append({"object": node, "uses": show(key), "kind": ",".join(sorted(mapped[key] - {""})) or "-", "path": graph.nodes[node]["path"]})
        for key in sorted(set(read) & set(mapped)):
            said = str(read[key].get("kind") or "")
            if said and mapped[key] - {""} and said not in mapped[key]:
                kinds.append({"object": node, "uses": show(key), "read": said, "map": ",".join(sorted(mapped[key]))})
    types = []
    for kind, stats in sorted(per.items()):
        recall = stats["both"] / stats["read"] if stats["read"] else 1.0
        precision = stats["both"] / stats["map"] if stats["map"] else 1.0
        types.append({"type": kind, **stats, "recall": round(recall, 3), "precision": round(precision, 3), "pass": recall >= least and precision >= least})
    passed = bool(types) and all(item["pass"] for item in types) and not bad
    return {
        "types": types, "min": least, "pass": passed,
        "map_misses": left_out[:SHOWN], "map_misses_count": len(left_out),
        "map_only": extra[:SHOWN], "map_only_count": len(extra),
        "kind_differs": kinds[:SHOWN], "not_in_map": unknown, "bad_lines": bad,
        "next": say("kbaudit.score.pass" if passed else "kbaudit.score.fail"),
        "exit_code": 0 if passed else 1,
    }
