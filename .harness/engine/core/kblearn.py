"""Learning a domain from the map (M27): the structure is done by script, the words by the model.

  kb order      from the entry points a person named: every object they reach, what is shared or past a stop, and the
                order to learn them in, bottom up (what is used before what uses it), in batches of one type
  kb flows      the paths from each entry point, for the Flows of architecture.md
  kb index      after a batch: the index lines of its cards, from the map, stamped
  kb cardcheck  the Reads / Writes / Calls / Called by of each card against the uses in the map, and the Flows of
                architecture.md against the map: the check that catches a relation the model made up or left out

The graph is core/kbgraph.py. Only `kb index` writes, and only in a task's DEV/.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import kbgraph, kbstd, messages, tasks
from .kbgraph import Graph, MapError

BATCH = 20
BUDGET = 1500  # lines of code a batch reads at most; an object longer than this is a batch of its own
LARGE = 400  # lines: an object this long is read in parts, and its card cites lines for every rule
CITE_FROM = 50  # lines: a card of an object this long should cite lines
FLOW_DEPTH = 6
FLOW_PATHS = 50
FLOW_STEPS = 3  # two ids next to each other in a flow line may skip this many steps of the map
SHOWN = 100
FIELDS = ("reads", "writes", "calls", "called by")
FIELD = re.compile(r"(?<![A-Za-z])(Reads|Writes|Calls|Called by)\s*:\s*(.*?)(?=\s*[·|]\s*[A-Z][A-Za-z ]{1,20}:|$)")
CARD_ID = re.compile(r"^[a-z][a-z0-9_-]*:.+$")
TEXT_ID = re.compile(r"`([a-z][a-z0-9_-]*:[^`]+)`|(?<![\w`])([a-z][a-z0-9_-]*:[^\s,;()`*]+)")
CITE = re.compile(r"\bL(\d+)(?:\s*[-–]\s*L?(\d+))?\b")
NONE = {"", "-", "—", "none", "n/a", "nothing"}
ARROW = re.compile(r"→|->")


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def pick(graph: Graph, query: str) -> str:
    found = graph.lookup(query)
    if not found:
        raise MapError(say("kblearn.none", query=query))
    if len(found) > 1:
        raise MapError(say("kblearn.many", query=query, ids=", ".join(found[:10])))
    return found[0]


def cut(graph: Graph, chosen: List[str], shared_min: Optional[int]) -> Tuple[int, Dict[str, int]]:
    """The objects to leave for shared/: reached from `limit` entry points or more, at least one of them not chosen
    (another domain uses it too). An object only the chosen entry points use belongs to this domain, however often."""
    limit = shared_min or graph.shared_min
    reached: Dict[str, Set[str]] = defaultdict(set)
    for entry in set(graph.entries()) | set(chosen):
        for node in graph.reach(entry):
            reached[node].add(entry)
    return limit, {node: len(by) for node, by in reached.items() if len(by) >= limit and by - set(chosen) and node not in chosen}


def closure(graph: Graph, chosen: List[str], shared: Dict[str, int], stops: Set[str]) -> Tuple[Set[str], Set[str], Set[str]]:
    """What the entry points reach without going into a shared object or past a stop: (inside, shared met, stops met)."""
    inside, met_shared, met_stops = set(chosen), set(), set()
    queue = deque(chosen)
    while queue:
        for target, _kind in graph.out.get(queue.popleft(), []):
            if target in inside:
                continue
            if target in shared:
                met_shared.add(target)
            elif target in stops:
                met_stops.add(target)
            else:
                inside.add(target)
                queue.append(target)
    return inside, met_shared, met_stops


def components(graph: Graph, nodes: Set[str]) -> List[List[str]]:
    """The strongly connected parts of the graph inside `nodes`, used ones first (Tarjan, without recursion)."""
    index: Dict[str, int] = {}
    low: Dict[str, int] = {}
    stack: List[str] = []
    on: Set[str] = set()
    found: List[List[str]] = []
    for start in sorted(nodes):
        if start in index:
            continue
        work = [(start, iter(sorted({t for t, _k in graph.out.get(start, []) if t in nodes})))]
        index[start] = low[start] = len(index)
        stack.append(start)
        on.add(start)
        while work:
            node, rest = work[-1]
            step = next(rest, None)
            if step is not None:
                if step not in index:
                    index[step] = low[step] = len(index)
                    stack.append(step)
                    on.add(step)
                    work.append((step, iter(sorted({t for t, _k in graph.out.get(step, []) if t in nodes}))))
                elif step in on:
                    low[node] = min(low[node], index[step])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                part = []
                while True:
                    item = stack.pop()
                    on.discard(item)
                    part.append(item)
                    if item == node:
                        break
                found.append(sorted(part))
    return found


def heights(graph: Graph, parts: List[List[str]], nodes: Set[str]) -> Dict[str, int]:
    """0 for what uses nothing inside; else one more than the highest thing it uses. A cycle shares one height."""
    owner = {node: number for number, part in enumerate(parts) for node in part}
    height: Dict[int, int] = {}
    for number, part in enumerate(parts):  # Tarjan gives the used parts first
        below = [height[owner[t]] for node in part for t, _k in graph.out.get(node, []) if t in nodes and owner[t] != number]
        height[number] = 1 + max(below) if below else 0
    return {node: height[owner[node]] for node in nodes}


def batches(graph: Graph, todo: List[str], done: Set[str], size: int, budget: int = BUDGET) -> List[Dict[str, Any]]:
    """Each object goes into the first batch of its type (and dynamic or not) that comes no earlier than the batches of
    what it uses and has room: fewer than `size` objects, and its lines still within `budget` (an empty batch always has
    room). `todo` is bottom up, so what an object uses is placed before it, or earlier in its batch."""
    found: List[Dict[str, Any]] = []
    where: Dict[str, int] = {}
    for node in todo:
        item = graph.nodes[node]
        key, lines = (item["type"], item["dynamic"]), int(item.get("size") or 0)
        after = max((where[t] for t, _k in graph.out.get(node, []) if t in where and t not in done), default=0)
        room = lambda batch: batch["key"] == key and len(batch["objects"]) < size and (not batch["objects"] or batch["lines"] + lines <= budget)
        spot = next((number for number in range(after, len(found)) if room(found[number])), None)
        if spot is None:
            found.append({"key": key, "objects": [], "lines": 0})
            spot = len(found) - 1
        found[spot]["objects"].append(node)
        found[spot]["lines"] += lines
        where[node] = spot
    return [
        {"batch": number + 1, "type": batch["key"][0], "card_file": f"objects/{batch['key'][0]}.md", "lines": batch["lines"],
         **({"dynamic": True} if batch["key"][1] else {}), "objects": batch["objects"]}
        for number, batch in enumerate(found)
    ]


def known_ids(folder: Optional[Path]) -> Set[str]:
    if not folder:
        return set()
    index = folder / kbstd.INDEX_FILE
    if not index.is_file():
        raise MapError(say("kb.index.missing", file=index))
    rows, _bad = kbstd.read_index(index)
    return {str(row.get("id")) for row in rows if row.get("id")}


def order(root: Path, entries: List[str], stops: Optional[List[str]] = None, size: int = BATCH,
          shared_min: Optional[int] = None, folder: Optional[Path] = None, budget: int = BUDGET) -> Dict[str, Any]:
    """`kb order`: what to learn for these entry points, and in what order."""
    graph = kbgraph.need_map(root)
    chosen = sorted({pick(graph, query) for query in entries})
    stop = {pick(graph, query) for query in stops or []}
    limit, shared = cut(graph, chosen, shared_min)
    inside, met_shared, met_stops = closure(graph, chosen, shared, stop)
    parts = components(graph, inside)
    height = heights(graph, parts, inside)
    done = known_ids(folder.resolve() if folder else None) & inside
    todo = sorted(inside - done, key=lambda node: (height[node], graph.nodes[node]["type"], node))
    users = lambda found: [{"name": name, "used_by": sorted(by & inside)} for name, by in sorted(found.items()) if by & inside]
    result: Dict[str, Any] = {
        "entry_points": chosen, "objects": len(inside), "already_learned": len(done), "to_learn": len(todo),
        "batches": batches(graph, todo, done, max(1, size), max(1, budget)), "budget": budget,
        "large": [{"id": node, "lines": graph.nodes[node]["size"]} for node in sorted(todo, key=lambda node: -graph.nodes[node]["size"]) if graph.nodes[node]["size"] >= LARGE],
        "shared_min": limit, "shared": [{"id": node, "entry_points": shared[node]} for node in sorted(met_shared)],
        "stopped_at": sorted(met_stops),
        "cycles": [part for part in parts if len(part) > 1],
        "dynamic": sorted(node for node in inside if graph.nodes[node]["dynamic"]),
        "obsolete": sorted(node for node in inside if graph.nodes[node].get("obsolete")),
        "missing": users(graph.missing), "outside": users(graph.external),
        "next": say("kblearn.order.next"),
    }
    return result


def flows(root: Path, entries: List[str], depth: int = FLOW_DEPTH, most: int = FLOW_PATHS,
          stops: Optional[List[str]] = None, shared_min: Optional[int] = None) -> Dict[str, Any]:
    """`kb flows`: from each entry point, every use it reaches, each on the shortest path to it: one line per use, so
    that a table one step writes and a later step reads shows both. Two uses between the same pair are one arrow
    (`-reads,writes->`). A shared object or a stop ends a path; so does `depth`."""
    graph = kbgraph.need_map(root)
    chosen = sorted({pick(graph, query) for query in entries})
    stop = {pick(graph, query) for query in stops or []}
    _limit, shared = cut(graph, chosen, shared_min)
    mark = lambda node: node + (" (shared)" if node in shared else " (stop)" if node in stop else "")
    found = []
    for entry in chosen:
        route = {entry: entry}
        queue, paths = deque([(entry, 0)]), []
        while queue:
            node, step = queue.popleft()
            kinds: Dict[str, List[str]] = defaultdict(list)
            if step < depth and (node == entry or (node not in shared and node not in stop)):
                for target, kind in graph.out.get(node, []):
                    kinds[target].append(kind)
            for target in sorted(kinds):
                line = f"{route[node]} -{','.join(sorted(set(kinds[target])))}-> {mark(target)}"
                if target in route:
                    paths.append(line)  # reached already by a shorter path: the use is still a step of the flow
                else:
                    route[target] = line
                    queue.append((target, step + 1))
            if not kinds and node != entry:
                paths.append(route[node])
        paths.sort()
        found.append({"entry": entry, "paths": paths[:most], **({"more": len(paths) - most} if len(paths) > most else {})})
    return {"flows": found, "dynamic": sorted(node for node in graph.nodes if graph.nodes[node]["dynamic"] and any(node in item for row in found for item in row["paths"])),
            "next": say("kblearn.flows.next")}


# --- index -----------------------------------------------------------------------------------------------


def index(root: Path, folder: Path, ids: List[str], level: str = "verified") -> Dict[str, Any]:
    """`kb index`: after the cards of a batch are written, their lines in `objects/index.jsonl`, from the map (type,
    name, repository, path; the card is `objects/<type>.md#<id>`), stamped with the sha of the base branch now. Only
    in a task's `DEV/`; an id already in the index is left as it is (`kb stamp` is for those)."""
    folder = folder.resolve()
    if level not in kbstd.LEVELS:
        raise MapError(say("kb.object.level", id="-", level=level, levels=", ".join(kbstd.LEVELS)))
    graph = kbgraph.need_map(root)
    wanted = [pick(graph, query) for query in ids]
    path = folder / kbstd.INDEX_FILE
    if not tasks.in_dev(root, folder):
        raise MapError(say("kb.stamp.not_dev", folder=folder))
    rows: List[Dict[str, Any]] = []
    if path.is_file():
        rows, bad = kbstd.read_index(path)
        if bad:
            raise MapError(" ".join(bad))
    known = {row.get("id") for row in rows}
    added = []
    for node in dict.fromkeys(wanted):
        if node in known:
            continue
        item = graph.nodes[node]
        rows.append({"id": node, "type": item["type"], "name": item["name"], "repo": item["repo"],
                     "sources": [{"path": item["path"], "sha": ""}], "lines": [item["line"], item["line"] + max(item.get("size") or 1, 1) - 1],
                     "card": f"objects/{item['type']}.md#{node}", "level": level})
        added.append(node)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda row: str(row.get("id")))
    path.write_text("".join(json.dumps({key: value for key, value in row.items() if key != "_line"}, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    try:
        stamped = kbstd.stamp(root, folder, added) if added else {"gone": [], "unknown_repos": []}
    except kbstd.KbError as error:
        raise MapError(str(error)) from None
    return {"added": added, "already": sorted(set(wanted) & known), "gone": stamped["gone"], "unknown_repos": stamped["unknown_repos"],
            "next": say("kblearn.index.unstamped" if stamped["gone"] or stamped["unknown_repos"] else "kblearn.index.next" if added else "kblearn.index.nothing")}


# --- cardcheck --------------------------------------------------------------------------------------------


def cards(folder: Path) -> Dict[str, Tuple[str, List[str]]]:
    """id -> (file, the lines of its card), from every `objects/*.md` of the domain folder."""
    found: Dict[str, Tuple[str, List[str]]] = {}
    for path in sorted((folder / "objects").glob("*.md")):
        current = None
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            heading = kbstd.HEADING.match(line)
            if heading and line.startswith("## "):
                name = heading.group(1).strip().strip("`")
                current = name if CARD_ID.match(name) else None
                if current:
                    found[current] = (f"objects/{path.name}", [])
            elif current:
                found[current][1].append(line)
    return found


def said(lines: Iterable[str]) -> Dict[str, Set[str]]:
    """What a card names under Reads, Writes, Calls and Called by: ids only (`type:name`), with or without backticks."""
    found: Dict[str, Set[str]] = {field: set() for field in FIELDS}
    for line in lines:
        for label, value in FIELD.findall(line):
            for item in value.split(","):
                item = item.strip().strip("`").strip()
                if item.lower() not in NONE and CARD_ID.match(item):
                    found[label.lower()].add(item)
    return found


def expected(graph: Graph, node: str) -> Dict[str, Set[str]]:
    found: Dict[str, Set[str]] = {field: set() for field in FIELDS}
    for target, kind in graph.out.get(node, []):
        found[kind if kind in ("reads", "writes") else "calls"].add(target)
    found["called by"] = {source for source, _kind in graph.into.get(node, [])}
    return found


def check_cites(graph: Graph, node: str, file: str, lines: List[str], row: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """The line numbers a card cites (`L120`, `L120-L145`) are lines of the object's own code, in its file on the base
    branch. A card of a long object that cites none is flagged: its rules cannot be checked against the code."""
    item = graph.nodes[node]
    cites = [(int(first), int(last or first)) for line in lines for first, last in CITE.findall(line)]
    size, start = int(item.get("size") or 0), int(item.get("line") or 1)
    if not cites:
        if size >= LARGE:
            return [say("kblearn.check.no_cites", id=node, file=file, lines=size)], []
        return [], ([say("kblearn.check.few_cites", id=node, file=file, lines=size)] if size >= CITE_FROM else [])
    if not size:
        return [], []
    shas = [str(source.get("sha") or "") for source in row.get("sources") or [] if isinstance(source, dict) and source.get("path") == item["path"]]
    if shas and shas[0] and item.get("sha") and not str(item["sha"]).startswith(shas[0]):
        return [], [say("kblearn.check.cites_old", id=node, file=file)]  # the card is of older code: kb stale says so
    low, high = int(item.get("from") or start), start + size - 1
    bad = [f"L{first}" + (f"-L{last}" if last != first else "") for first, last in cites if first > last or first < low or last > high]
    if bad:
        return [say("kblearn.check.cite_out", id=node, file=file, cites=", ".join(bad), path=item["path"], low=low, high=high)], []
    return [], []


def check_cards(graph: Graph, found: Dict[str, Tuple[str, List[str]]], absent: Set[str], rows: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    errors, warnings, outside = [], [], set()
    for node, (file, lines) in sorted(found.items()):
        if node not in graph.nodes:
            if node not in absent:
                outside.add(node)
            continue
        wrote, has = said(lines), expected(graph, node)
        dynamic = graph.nodes[node]["dynamic"]
        for field in FIELDS:
            for other in sorted(wrote[field] - has[field]):
                if other not in graph.nodes:
                    if other not in absent:
                        outside.add(other)
                    continue
                elsewhere = [name for name in FIELDS if other in has[name]]
                where = say("kblearn.check.elsewhere", fields=", ".join(elsewhere)) if elsewhere else say("kblearn.check.nowhere")
                text = say("kblearn.check.extra", id=node, file=file, field=field.capitalize(), other=other, where=where)
                (warnings if dynamic and field != "called by" and not elsewhere else errors).append(text)
            for other in sorted(has[field] - wrote[field]):
                text = say("kblearn.check.left_out", id=node, file=file, field=field.capitalize(), other=other)
                (warnings if field == "called by" else errors).append(text)
        bad, doubt = check_cites(graph, node, file, lines, (rows or {}).get(node, {}))
        errors += bad
        warnings += doubt
    return {"errors": errors, "warnings": warnings, "outside": outside}


def check_flows(graph: Graph, path: Path, absent: Set[str]) -> Dict[str, Any]:
    """Each line of the Flows section with an arrow: two ids next to each other must be linked in the map, one way or
    the other (data flows from a table into what reads it), within FLOW_STEPS steps."""
    errors, outside, lines = [], set(), 0
    if not path.is_file():
        return {"errors": errors, "outside": outside, "lines": 0}
    section = False
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        heading = kbstd.HEADING.match(line)
        if heading and line.startswith("## "):
            section = heading.group(1).strip().lower() == "flows"
            continue
        if not section or not ARROW.search(line):
            continue
        ids = [first or second for first, second in TEXT_ID.findall(line)]
        ids = [item.rstrip(".:") for item in ids]
        lines += 1
        for item in ids:
            if item not in graph.nodes and item not in absent:
                outside.add(item)
        known = [item for item in ids if item in graph.nodes]
        for left, right in zip(known, known[1:]):
            if left != right and not near(graph, left, right) and not near(graph, right, left):
                errors.append(say("kblearn.check.flow", line=number, left=left, right=right, steps=FLOW_STEPS))
    return {"errors": errors, "outside": outside, "lines": lines}


def near(graph: Graph, start: str, goal: str) -> bool:
    seen, queue = {start}, deque([(start, 0)])
    while queue:
        node, step = queue.popleft()
        if step >= FLOW_STEPS:
            continue
        for target, _kind in graph.out.get(node, []):
            if target == goal:
                return True
            if target not in seen:
                seen.add(target)
                queue.append((target, step + 1))
    return False


def cardcheck(root: Path, folder: Path) -> Dict[str, Any]:
    """`kb cardcheck`: the relations the cards and the Flows write, against the map. Exit code 1 on an error."""
    graph = kbgraph.need_map(root)
    folder = folder.resolve()
    if not (folder / "objects").is_dir():
        raise MapError(say("kblearn.check.no_objects", folder=folder))
    rows: List[Dict[str, Any]] = []
    if (folder / kbstd.INDEX_FILE).is_file():
        rows, _bad = kbstd.read_index(folder / kbstd.INDEX_FILE)
    absent = {str(row.get("id")) for row in rows if row.get("source_missing")}  # known to have no code: not a surprise
    found = cards(folder)
    result = check_cards(graph, found, absent, {str(row.get("id")): row for row in rows})
    flow = check_flows(graph, folder / "architecture.md", absent)
    errors = result["errors"] + flow["errors"]
    outside = sorted(result["outside"] | flow["outside"])
    return {
        "cards": len(found), "checked": sum(1 for node in found if node in graph.nodes), "flow_lines": flow["lines"],
        "errors": len(errors), "error_list": errors[:SHOWN],
        "warnings": len(result["warnings"]), "warning_list": result["warnings"][:SHOWN],
        "not_in_map": outside[:SHOWN], **({"not_in_map_more": len(outside) - SHOWN} if len(outside) > SHOWN else {}),
        "next": say("kblearn.check.bad" if errors else "kblearn.check.ok"),
        "exit_code": 1 if errors else 0,
    }
