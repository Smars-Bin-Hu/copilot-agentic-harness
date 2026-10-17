"""Questions on the repository map (M15-10d): the objects and uses `kb map` cached, read back as one graph.

  kb near   what one object uses and what uses it, a few steps out: the impact of a change across domains
  kb split  a first cut of the domains: from each entry point, what it reaches; objects reached from many entry points
            are shared (a log procedure, a calendar table) and are taken out first, or everything joins into one domain
  kb gaps   what runs or is used but has no code: names defined in no file, retired code in use, files deleted in
            git; against a list of production objects a person exported, what production runs that no repository has

Names are resolved here, over every mapped repository at once. How the map is built is core/kbmap.py.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Set, Tuple

from . import messages, paths, repo_paths, targets

SCHEMA_VERSION = 2  # of the cache: a cache of another version is built again
SAMPLE = 10
NEAR_LIMIT = 200
GIT_TIMEOUT = 300


class MapError(ValueError):
    """The map cannot be built or read as asked."""


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def matches(pattern: str, path: str) -> bool:
    """A glob of toolkit.json. `**/` also stands for no folder: `**/*.sql` matches `a.sql`, `templates/**/*.html`
    matches `templates/welcome.html`."""
    if repo_paths.glob_regex(pattern).match(path):
        return True
    if "**/" not in pattern:
        return False
    shorter = re.sub(r"(^|/)\*\*/", r"\1", pattern)
    return bool(repo_paths.glob_regex(shorter).match(path))


# --- SQL names ------------------------------------------------------------------------------------------


def parts(raw: str) -> List[str]:
    """`[Db].dbo.[My Table]` -> ["Db", "dbo", "My Table"]. `Db..t` keeps the empty schema."""
    found, current, index = [], "", 0
    while index < len(raw):
        char = raw[index]
        if char in "[\"":
            close = "]" if char == "[" else "\""
            end = raw.find(close, index + 1)
            end = len(raw) if end < 0 else end
            current += raw[index + 1:end]
            index = end + 1
            continue
        if char == ".":
            found.append(current.strip())
            current = ""
        elif not char.isspace():
            current += char
        index += 1
    found.append(current.strip())
    return found


def sql_name(raw: str, db: str = "") -> str:
    """`db.schema.name` when the database is known, `schema.name` when not; `dbo` for a missing schema; no server part."""
    pieces = parts(raw)[-3:]
    if len(pieces) == 1:
        pieces = ["dbo"] + pieces
    if len(pieces) == 3 and not pieces[1]:
        pieces[1] = "dbo"
    if len(pieces) == 2 and db:
        pieces = [db] + pieces
    return ".".join(pieces)


# --- the cache -------------------------------------------------------------------------------------------


def cache_file(root: Path, name: str) -> Path:
    return paths.runtime_dir(root) / "kbmap" / f"{name}.json"


def read_cache(root: Path, name: str) -> Dict[str, Any]:
    try:
        data = json.loads(cache_file(root, name).read_text(encoding="utf-8"))
        return data if data.get("schema_version") == SCHEMA_VERSION else {}
    except (OSError, ValueError):
        return {}


# --- the graph -----------------------------------------------------------------------------------------


def keys_of(name: str) -> List[str]:
    """The names an object can be called by: `Db.dbo.t`, `dbo.t`, `t`; `Project/Load` also `Load`."""
    low = name.lower()
    dotted = low.split(".")
    found = [low, ".".join(dotted[-2:]), dotted[-1]]
    if "/" in low:
        found.append(low.rsplit("/", 1)[-1])
    return list(dict.fromkeys(found))


class Graph:
    """The objects and uses of the mapped repositories, with the names resolved across all of them.

    A use that resolves to no object is `missing` when its name looks like one of this system (no database, or a
    database the map knows): a file may have been deleted or never committed. It is `external` when it names another
    system (a database the map has no object of): a boundary, not a gap.
    """

    def __init__(self) -> None:
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.out: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        self.into: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        self.missing: Dict[str, Set[str]] = defaultdict(set)
        self.external: Dict[str, Set[str]] = defaultdict(set)
        self.duplicates: List[str] = []
        self.failed: List[Dict[str, str]] = []
        self.empty: List[str] = []
        self.entry_types: Set[str] = set()
        self.executable_types: Set[str] = set()
        self.stop_words: Set[str] = set()
        self.shared_min = 3

    @classmethod
    def load(cls, root: Path, names: Optional[List[str]] = None) -> "Graph":
        graph = cls()
        folder = paths.runtime_dir(root) / "kbmap"
        files = [cache_file(root, name) for name in names] if names else sorted(folder.glob("*.json")) if folder.is_dir() else []
        records = [record for record in (read_cache(root, file.stem) for file in files) if record]
        pending = []
        for record in records:
            rules = record.get("rules") or {}
            graph.entry_types.update(rules.get("entry_types") or [])
            graph.executable_types.update(rules.get("executable_types") or [])
            graph.stop_words.update(word.lower() for word in rules.get("stop_words") or [])
            obsolete = rules.get("obsolete") or []
            style = rules.get("names") or "sql"
            for path, item in sorted(record["files"].items()):
                if item.get("error"):
                    graph.failed.append({"path": f"{record['repo']}/{path}", "error": item["error"]})
                elif not item["objects"]:
                    graph.empty.append(f"{record['repo']}/{path}")
                retired = any(matches(pattern, path) for pattern in obsolete)
                for obj in item["objects"]:
                    if obj["id"] in graph.nodes:
                        graph.duplicates.append(obj["id"])
                        continue
                    graph.nodes[obj["id"]] = {
                        "id": obj["id"], "type": obj["type"], "name": obj["name"], "repo": record["repo"], "path": path,
                        "line": obj.get("line", 1), "dynamic": bool(obj.get("dynamic")),
                        **({"obsolete": True} if retired else {}), **({"scheduled": True} if obj.get("scheduled") else {}),
                    }
                    pending.append((obj["id"], obj.get("refs") or [], style))
        graph.shared_min = max([int((record.get("rules") or {}).get("shared_min") or 3) for record in records] or [3])
        graph.resolve(pending)
        return graph

    def resolve(self, pending: List[Tuple[str, List[Dict[str, Any]], str]]) -> None:
        index: Dict[str, List[str]] = defaultdict(list)
        for node in self.nodes.values():
            index["=" + node["name"]].append(node["id"])  # the name as written, case and all: `Vets` the class, not `vets` the table
            for key in keys_of(node["name"]):
                index[key].append(node["id"])
        databases = {item["name"].split(".")[0].lower() for item in self.nodes.values() if item["name"].count(".") == 2}
        for source, refs, style in pending:
            seen = set()
            for ref in refs:
                target = self.find(index, ref, style, databases)
                if target is None:
                    continue
                if target[0] in "?!":
                    (self.missing if target[0] == "?" else self.external)[target[1:]].add(source)
                    continue
                if target == source or (ref["kind"], target) in seen:
                    continue
                seen.add((ref["kind"], target))
                self.out[source].append((target, ref["kind"]))
                self.into[target].append((source, ref["kind"]))

    def find(self, index: Dict[str, List[str]], ref: Dict[str, Any], style: str, databases: Set[str]) -> Optional[str]:
        """The id a use points at; `?<name>` when it is missing; `!<name>` when it is outside the system; None for a
        bare name nothing has (an alias, a local name)."""
        raw, wanted_type = str(ref["name"]), ref.get("as", "")
        sql = style == "sql" and not wanted_type

        def pick(candidates: List[str]) -> Optional[str]:
            if wanted_type:
                candidates = [item for item in candidates if self.nodes[item]["type"] == wanted_type]
            return candidates[0] if len(candidates) == 1 else None

        if not sql:
            low = raw.lower()
            for key in dict.fromkeys(["=" + raw, low, low.rsplit("/", 1)[-1], low.split(".")[-1]]):
                hit = pick(index.get(key, []))
                if hit:
                    return hit
            if wanted_type:
                return f"?{raw}"
            return f"!{raw}" if "." in raw or "/" in raw else None
        pieces = parts(raw)
        wanted = sql_name(raw, str(ref.get("db") or ""))
        low = wanted.lower()
        dotted = low.split(".")
        hit = pick(index.get(low, []))
        if hit:
            return hit
        near = index.get(".".join(dotted[-2:]), [])
        if len(dotted) == 3:  # a database was named or known: an object of another database is not it
            near = [item for item in near if self.nodes[item]["name"].count(".") < 2 or self.nodes[item]["name"].lower() == low]
        hit = pick(near)
        if hit:
            return hit
        if len(pieces) == 1:
            return pick(index.get(dotted[-1], []))
        if len(pieces) >= 3 and pieces[-3].lower() not in databases:
            return f"!{wanted}"
        return f"?{wanted}"

    # --- questions ---

    def entries(self) -> List[str]:
        live = {node: item for node, item in self.nodes.items() if not item.get("obsolete")}
        typed = sorted(node for node, item in live.items() if item["type"] in self.entry_types)
        if typed or self.entry_types:
            return typed
        return sorted(node for node in live if not self.into.get(node) and self.out.get(node))

    def reach(self, start: str) -> Set[str]:
        seen, queue = {start}, deque([start])
        while queue:
            for target, _kind in self.out.get(queue.popleft(), []):
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        return seen

    def obsolete_used(self) -> Dict[str, List[str]]:
        """Obsolete objects that a live object still uses: id -> the live users."""
        found: Dict[str, List[str]] = {}
        for node, item in self.nodes.items():
            if item.get("obsolete"):
                users = sorted({source for source, _kind in self.into.get(node, []) if not self.nodes[source].get("obsolete")})
                if users:
                    found[node] = users
        return found

    def check_facts(self, facts: List[Dict[str, str]]) -> Dict[str, Any]:
        missing = []
        for fact in facts:
            links = self.out.get(fact["from"], [])
            if not any(target == fact["to"] and (not fact["kind"] or kind == fact["kind"]) for target, kind in links):
                missing.append(f"{fact['from']} -{fact['kind'] or 'any'}-> {fact['to']}")
        return {"checked": len(facts), "found": len(facts) - len(missing), "missing": missing}

    @staticmethod
    def ranked(found: Dict[str, Set[str]]) -> List[Dict[str, Any]]:
        return [{"name": name, "used_by": len(users)} for name, users in sorted(found.items(), key=lambda item: (-len(item[1]), item[0]))]

    def summary(self) -> Dict[str, Any]:
        entries = self.entries()
        unused = sorted(
            node for node, item in self.nodes.items()
            if item["type"] in self.executable_types and not self.into.get(node) and node not in entries and not item.get("obsolete")
        )
        dynamic = sorted(node for node, item in self.nodes.items() if item["dynamic"])
        used = sorted(self.nodes, key=lambda node: (-len(self.into.get(node, [])), node))
        retired = self.obsolete_used()
        return {
            "objects": dict(sorted(Counter(item["type"] for item in self.nodes.values()).items())),
            "uses": dict(sorted(Counter(kind for links in self.out.values() for _target, kind in links).items())),
            "entry_points": len(entries), "entry_sample": entries[:SAMPLE],
            "unused": len(unused), "unused_sample": unused[:SAMPLE],
            "dynamic": len(dynamic), "dynamic_sample": dynamic[:SAMPLE],
            "missing": len(self.missing), "missing_sample": self.ranked(self.missing)[:SAMPLE],
            "obsolete_used": len(retired), "obsolete_used_sample": sorted(retired)[:SAMPLE],
            "external": len(self.external), "external_sample": self.ranked(self.external)[:SAMPLE],
            "most_used": [{"id": node, "used_by": len(self.into.get(node, []))} for node in used[:SAMPLE] if self.into.get(node)],
            "empty_files": len(self.empty), "empty_sample": self.empty[:SAMPLE],
            "failed_files": len(self.failed), "failed_sample": self.failed[:SAMPLE],
            "duplicates": sorted(set(self.duplicates))[:SAMPLE],
        }

    def lookup(self, query: str) -> List[str]:
        if query in self.nodes:
            return [query]
        low = query.lower()
        exact = [node for node, item in self.nodes.items() if low in keys_of(item["name"]) or node.lower() == low]
        return sorted(exact) if exact else sorted(node for node in self.nodes if low in node.lower())

    def walk(self, start: str, links: Dict[str, List[Tuple[str, str]]], depth: int) -> List[Dict[str, Any]]:
        rows, seen, queue = [], {start}, deque([(start, 0)])
        while queue and len(rows) < NEAR_LIMIT:
            node, step = queue.popleft()
            if step >= depth:
                continue
            for other, kind in sorted(links.get(node, [])):
                if other in seen:
                    continue
                seen.add(other)
                item = self.nodes[other]
                rows.append({"id": other, "how": kind, "via": node if step else "", "step": step + 1, "repo": item["repo"], "path": item["path"]})
                queue.append((other, step + 1))
        return rows


def need_map(root: Path) -> Graph:
    graph = Graph.load(root)
    if not graph.nodes:
        raise MapError(say("kbmap.none"))
    return graph


def near(root: Path, query: str, depth: int = 1, direction: str = "both") -> Dict[str, Any]:
    """`kb near`: what an object uses and what uses it, up to `depth` steps."""
    graph = need_map(root)
    found = graph.lookup(query)
    if len(found) != 1:
        if not found:
            raise MapError(say("kbmap.near.none", query=query))
        return {"query": query, "matches": found[:50], "next": say("kbmap.near.many")}
    node = graph.nodes[found[0]]
    result: Dict[str, Any] = {key: node[key] for key in ("id", "type", "repo", "path", "line", "dynamic")}
    if direction in ("both", "up"):
        result["used_by"] = graph.walk(node["id"], graph.into, depth)
    if direction in ("both", "down"):
        result["uses"] = graph.walk(node["id"], graph.out, depth)
    for key, found in (("uses_missing", graph.missing), ("uses_outside", graph.external)):
        names = sorted(name for name, users in found.items() if node["id"] in users)
        if names:
            result[key] = names
    if node.get("obsolete"):
        result["obsolete"] = True
    if node["dynamic"]:
        result["note"] = say("kbmap.near.dynamic")
    return result


# --- domains ---------------------------------------------------------------------------------------------


def words(text: str, stop: Set[str]) -> List[str]:
    found = []
    for piece in text.replace("/", " ").replace(".", " ").replace("-", " ").replace("_", " ").split():
        for word in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+", piece):
            low = word.lower()
            if len(low) > 2 and low not in stop and not low.isdigit():
                found.append(low)
    return found


def split(root: Path, shared_min: Optional[int] = None) -> Dict[str, Any]:
    """`kb split`: a first cut of the domains, for a person to confirm once."""
    graph = need_map(root)
    entries = graph.entries()
    limit = shared_min or graph.shared_min
    reached: Dict[str, Set[str]] = defaultdict(set)
    for entry in entries:
        for node in graph.reach(entry):
            reached[node].add(entry)
    shared = sorted((node for node, by in reached.items() if len(by) >= limit and node not in entries), key=lambda node: (-len(reached[node]), node))
    left = set(graph.nodes) - set(shared)
    neighbours: Dict[str, Set[str]] = defaultdict(set)
    for source, links in graph.out.items():
        for target, _kind in links:
            if source in left and target in left:
                neighbours[source].add(target)
                neighbours[target].add(source)
    seen: Set[str] = set()
    groups = []
    for entry in entries:
        if entry in seen:
            continue
        group, queue = {entry}, deque([entry])
        while queue:
            for other in neighbours.get(queue.popleft(), ()):
                if other not in group:
                    group.add(other)
                    queue.append(other)
        seen |= group
        groups.append(group)
    everywhere = Counter(word for entry in entries for word in set(words(graph.nodes[entry]["name"], graph.stop_words)))
    domains = []
    for group in sorted(groups, key=lambda item: (-len(item), min(item))):
        starts = sorted(node for node in group if node in entries)
        local = Counter(word for entry in starts for word in set(words(graph.nodes[entry]["name"], graph.stop_words)))
        common = {word for word, count in everywhere.items() if len(entries) > 1 and count == len(entries)}
        hint = sorted((word for word in local if word not in common), key=lambda word: (-local[word] * local[word] / everywhere[word], word))[:2]
        folders = Counter("/".join(PurePosixPath(graph.nodes[node]["path"]).parent.parts[:2]) or "." for node in group)
        domains.append({
            "name_hint": "-".join(hint) or starts[0].split(":", 1)[-1].lower(),
            "entry_points": starts, "objects": len(group),
            "types": dict(sorted(Counter(graph.nodes[node]["type"] for node in group).items())),
            "repos": sorted({graph.nodes[node]["repo"] for node in group}),
            "folders": [folder for folder, _count in folders.most_common(3)],
            "uses_shared": sorted({target for node in group for target, _kind in graph.out.get(node, []) if target in shared})[:SAMPLE],
        })
    unreached = sorted(set(graph.nodes) - seen - set(shared))
    result: Dict[str, Any] = {
        "entry_points": len(entries), "shared_min": limit, "domains": domains,
        "shared": [{"id": node, "entry_points": len(reached[node])} for node in shared],
        "unreached": len(unreached), "unreached_types": dict(sorted(Counter(graph.nodes[node]["type"] for node in unreached).items())),
        "unreached_sample": unreached[:SAMPLE],
        "next": say("kbmap.split.next"),
    }
    if domains and graph.nodes and domains[0]["objects"] > 0.6 * len(graph.nodes) and len(entries) > 1:
        result["note"] = say("kbmap.split.one_big", size=domains[0]["objects"], limit=limit)
    return result


# --- gaps: what runs but has no code in the repositories --------------------------------------------------


def stem_key(path: str) -> str:
    """`db/dbo.usp_x.sql` -> `usp_x`: the name a file of a deleted object most likely had."""
    return PurePosixPath(path).stem.lower().split(".")[-1]


def deleted_files(root: Path, repos: List[str]) -> Dict[str, List[Dict[str, str]]]:
    """name -> the files of that name deleted on the base branch, newest first: `git log --diff-filter=D`, one call per
    repository. The last version is `git show <commit>^:<path>`."""
    found: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    configured = targets.load(root)
    for name in repos:
        repo = configured.repos.get(name)
        if repo is None:
            continue
        raw = targets.git(repo, "log", repo.base_ref, "--diff-filter=D", "--name-only", "--format=@%H", timeout=GIT_TIMEOUT, allow_failure=True)
        commit = ""
        for line in raw.decode("utf-8", errors="replace").splitlines():
            if line.startswith("@"):
                commit = line[1:]
            elif line.strip():
                found[stem_key(line)].append({"repo": name, "path": line, "deleted_in": commit[:12], "last_version": f"git -C <{name}> show {commit[:12]}^:\"{line}\""})
    return found


def read_inventory(file: Path) -> List[str]:
    """Ids, one per line: plain `type:name`, a JSON object with `id`, or CSV with an `id` column. `#` starts a comment."""
    try:
        lines = file.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        raise MapError(say("kbmap.gaps.inventory", file=file, problem=error)) from None
    column = -1
    ids = []
    for number, line in enumerate(lines):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("{"):
            try:
                text = str(json.loads(text).get("id") or "")
            except (ValueError, AttributeError):
                continue
        elif "," in text:
            cells = [cell.strip().strip('"') for cell in text.split(",")]
            if number == 0 or column < 0:
                if "id" in [cell.lower() for cell in cells]:
                    column = [cell.lower() for cell in cells].index("id")
                    continue
            text = cells[column] if 0 <= column < len(cells) else cells[0]
        if ":" in text:
            ids.append(text)
    if not ids:
        raise MapError(say("kbmap.gaps.inventory", file=file, problem=say("kbmap.gaps.no_ids")))
    return sorted(set(ids))


def match(graph: Graph, wanted: str) -> Optional[str]:
    """The node an id of a production list names: the same type, and the same name or the same `schema.name`."""
    if wanted in graph.nodes:
        return wanted
    kind, _, name = wanted.partition(":")
    low = name.lower()
    tail = ".".join(low.split(".")[-2:])
    same = [node for node, item in graph.nodes.items() if item["type"] == kind]
    exact = [node for node in same if graph.nodes[node]["name"].lower() == low]
    if exact:
        return exact[0]
    near = [node for node in same if tail in keys_of(graph.nodes[node]["name"]) and graph.nodes[node]["name"].count(".") < low.count(".")]
    return near[0] if len(near) == 1 else None


def gaps(root: Path, inventory: Optional[Path] = None) -> Dict[str, Any]:
    """`kb gaps`: what runs, or is used, but has no code in the repositories. From the map and git history; with a
    list of production objects a person exported, also what production runs that no repository holds."""
    graph = need_map(root)
    repos = sorted({item["repo"] for item in graph.nodes.values()})
    history = deleted_files(root, repos)

    def where(name: str) -> List[Dict[str, str]]:
        return history.get(name.lower().split(".")[-1].rsplit("/", 1)[-1], [])[:3]

    def users(name: str) -> List[str]:
        tail = ".".join(name.lower().split(".")[-2:])
        return sorted({user for missing, found in graph.missing.items() if ".".join(missing.lower().split(".")[-2:]) == tail for user in found})[:SAMPLE]

    result: Dict[str, Any] = {
        "missing": [{"name": name, "used_by": sorted(users)[:SAMPLE], "deleted": where(name)} for name, users in sorted(graph.missing.items())],
        "obsolete_used": [{"id": node, "path": f"{graph.nodes[node]['repo']}/{graph.nodes[node]['path']}", "used_by": users[:SAMPLE]} for node, users in sorted(graph.obsolete_used().items())],
    }
    if inventory is not None:
        ids = read_inventory(inventory)
        kinds = {item.partition(":")[0] for item in ids}
        matched: Dict[str, Optional[str]] = {item: match(graph, item) for item in ids}
        found = {node for node in matched.values() if node}
        result["inventory"] = {"file": str(inventory), "objects": len(ids), "types": sorted(kinds)}
        result["in_production_not_in_repos"] = [
            {"id": item, "used_by": users(item.partition(":")[2]), "deleted": where(item.partition(":")[2])}
            for item, node in matched.items() if node is None
        ]
        result["in_production_but_obsolete"] = sorted(node for node in found if graph.nodes[node].get("obsolete"))
        result["in_repos_not_in_production"] = sorted(
            node for node, item in graph.nodes.items() if item["type"] in kinds and node not in found and not item.get("obsolete")
        )
    result["next"] = say("kbmap.gaps.next" if inventory is not None else "kbmap.gaps.next_no_inventory")
    return result
