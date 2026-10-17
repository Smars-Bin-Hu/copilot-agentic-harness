"""The repository map (M15-10d, layer one of learning a code base): every object and every use, by script.

  kb map    read the base branch of each target repository with the extractors its stack profile names; keep the
            result per file, by git blob sha, in .harness/runtime/kbmap/<repo>.json. A file that did not change is
            not read again. The map is a cache: it can be built again at any time, so it is not knowledge and does
            not go into the knowledge base
  kb near   what one object uses and what uses it, a few steps out: the impact of a change across domains
  kb split  a first cut of the domains: from each entry point, what it reaches; objects reached from many entry points
            are shared (a log procedure, a calendar table) and are taken out first, or everything joins into one domain

A stack profile (`.harness/profiles/<name>.json`; a team's own in `<knowledge base>/profiles/`, which wins on the same
name) says which files go to which extractor (core/kbextract.py), which object types are entry points, and how many
entry points make an object shared. No model reads anything here.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import kbextract, messages, paths, repo_paths, targets

SCHEMA_VERSION = 1
PROFILES = ".harness/profiles"
MAX_FILE_BYTES = 5_000_000  # a bigger file is listed under `skipped`, not read
BATCH = 400  # blobs per `git cat-file --batch` call
GIT_TIMEOUT = 300
SAMPLE = 10
NEAR_LIMIT = 200
EXECUTABLE = ("sp", "package", "fn", "view", "trigger")
STOP_WORDS = {"dbo", "job", "jobs", "sp", "usp", "etl", "daily", "nightly", "weekly", "monthly", "load", "run", "main", "the", "and", "of", "to"}


class MapError(ValueError):
    """The map cannot be built or read as asked."""


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


# --- profiles -----------------------------------------------------------------------------------------


def profiles(root: Path) -> Dict[str, Dict[str, Any]]:
    """name -> profile. The shipped ones, then those of each knowledge base (`profiles/*.json`), which win."""
    folders = [root / PROFILES] + [folder / "profiles" for _name, folder in targets.knowledge_bases(root)]
    found: Dict[str, Dict[str, Any]] = {}
    for folder in folders:
        if not folder.is_dir():
            continue
        for file in sorted(folder.glob("*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if valid(data):
                data["_file"] = str(file)
                found[data["name"]] = data
    return found


def valid(data: Any) -> bool:
    if not isinstance(data, dict) or not isinstance(data.get("name"), str) or not isinstance(data.get("files"), list):
        return False
    return all(isinstance(rule, dict) and rule.get("extractor") in kbextract.EXTRACTORS and rule.get("glob") for rule in data["files"])


def signature(profile: Dict[str, Any]) -> str:
    body = {key: value for key, value in profile.items() if not key.startswith("_")}
    return sha256(json.dumps([kbextract.VERSION, body], sort_keys=True).encode("utf-8")).hexdigest()[:16]


def matches(pattern: str, path: str) -> bool:
    """`**/*.sql` also matches `a.sql` at the top of the repository."""
    if repo_paths.glob_regex(pattern).match(path):
        return True
    return pattern.startswith("**/") and bool(repo_paths.glob_regex(pattern[3:]).match(path))


def detect(choices: Dict[str, Dict[str, Any]], listing: Iterable[str]) -> Optional[str]:
    """The profile whose file kinds (`detect`: suffixes) are most of the repository. None when no file is of any kind."""
    counts: Counter = Counter(PurePosixPath(path).suffix.lower() for path in listing)
    best, score = None, 0
    for name, profile in sorted(choices.items()):
        found = sum(counts[suffix.lower()] for suffix in profile.get("detect") or [])
        if found > score:
            best, score = name, found
    return best


# --- reading a repository ---------------------------------------------------------------------------------


def listing(repo: targets.Repo, commit: str) -> List[Tuple[str, int, str]]:
    """(blob sha, size, path) of every file of the commit."""
    raw = targets.git(repo, "ls-tree", "-r", "-l", "-z", "--full-tree", commit, timeout=GIT_TIMEOUT).decode("utf-8", errors="replace")
    found = []
    for line in raw.split("\0"):
        meta, _, path = line.partition("\t")
        bits = meta.split()
        if len(bits) == 4 and bits[1] == "blob":
            found.append((bits[2], int(bits[3]) if bits[3].isdigit() else 0, path))
    return found


def blobs(repo: targets.Repo, shas: List[str]) -> Dict[str, bytes]:
    """sha -> bytes, a few hundred per git call."""
    out: Dict[str, bytes] = {}
    for start in range(0, len(shas), BATCH):
        chunk = shas[start:start + BATCH]
        done = subprocess.run(
            ["git", "-C", str(repo.path), "cat-file", "--batch"], input=("\n".join(chunk) + "\n").encode("ascii"),
            capture_output=True, timeout=GIT_TIMEOUT, check=False,
        )
        data, index = done.stdout, 0
        while index < len(data):
            end = data.index(b"\n", index)
            header = data[index:end].split()
            index = end + 1
            if len(header) != 3:  # "<sha> missing"
                continue
            size = int(header[2])
            out[header[0].decode("ascii")] = data[index:index + size]
            index += size + 1
    return out


def project_of(path: str, markers: Dict[str, str]) -> str:
    """The stem of the nearest `.sqlproj` / `.dtproj` in a folder above the file, or an empty string."""
    folder = PurePosixPath(path).parent
    while True:
        key = str(folder)
        if key in markers:
            return markers[key]
        if key in ("", "."):
            return ""
        folder = folder.parent


def markers(files: Iterable[str], suffix: str) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for path in files:
        if path.lower().endswith(suffix):
            pure = PurePosixPath(path)
            found.setdefault(str(pure.parent), pure.stem)
    return found


def cache_file(root: Path, name: str) -> Path:
    return paths.runtime_dir(root) / "kbmap" / f"{name}.json"


def read_cache(root: Path, name: str) -> Dict[str, Any]:
    try:
        data = json.loads(cache_file(root, name).read_text(encoding="utf-8"))
        return data if data.get("schema_version") == SCHEMA_VERSION else {}
    except (OSError, ValueError):
        return {}


def build_one(root: Path, repo: targets.Repo, choices: Dict[str, Dict[str, Any]], wanted: str, fresh: bool) -> Dict[str, Any]:
    """Map one repository. Reads only the files whose blob changed since the last map."""
    commit = targets.ref_commit(repo)
    if not commit:
        return {"repo": repo.name, "profile": "-", "note": say("kbmap.no_branch", branch=repo.base_ref)}
    files = listing(repo, commit)
    old = {} if fresh else read_cache(root, repo.name)
    name = wanted or old.get("profile") or detect(choices, [path for _sha, _size, path in files])
    if not name or name not in choices:
        return {"repo": repo.name, "profile": "-", "note": say("kbmap.no_profile", known=messages.joined(sorted(choices)) or "-")}
    profile = choices[name]
    sig = signature(profile)
    kept = old.get("files", {}) if old.get("signature") == sig else {}
    all_paths = [path for _sha, _size, path in files]
    databases, projects = markers(all_paths, ".sqlproj"), markers(all_paths, ".dtproj")
    chosen: Dict[str, Tuple[str, int, Dict[str, Any]]] = {}
    for sha, size, path in files:
        if any(matches(pattern, path) for pattern in profile.get("ignore") or []):
            continue
        rule = next((rule for rule in profile["files"] if matches(rule["glob"], path)), None)
        if rule:
            chosen[path] = (sha, size, rule)
    todo = [path for path, (sha, _size, _rule) in chosen.items() if kept.get(path, {}).get("sha") != sha]
    skipped = sorted(path for path in todo if chosen[path][1] > MAX_FILE_BYTES)
    todo = [path for path in todo if path not in skipped]
    data = blobs(repo, sorted({chosen[path][0] for path in todo}))
    result: Dict[str, Any] = {path: kept[path] for path in chosen if path not in todo and path in kept}
    for path in todo:
        sha, _size, rule = chosen[path]
        pure = PurePosixPath(path)
        context = {"path": path, "stem": pure.stem, "db": project_of(path, databases), "project": project_of(path, projects) or pure.parent.name, "rule": rule}
        result[path] = {"sha": sha, "objects": kbextract.extract(rule["extractor"], data.get(sha, b""), context)}
    record = {
        "schema_version": SCHEMA_VERSION, "repo": repo.name, "ref": repo.base_ref, "commit": commit, "profile": name, "signature": sig,
        "entry_types": profile.get("entry_types") or [], "shared_min": profile.get("shared_min", 3),
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "skipped": skipped, "files": result,
    }
    target = cache_file(root, repo.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    objects = sum(len(item["objects"]) for item in result.values())
    return {"repo": repo.name, "profile": name, "commit": commit[:12], "files": len(chosen), "read": len(todo), "objects": objects, "skipped": len(skipped)}


def chosen_repos(root: Path, names: Optional[List[str]]) -> List[targets.Repo]:
    found = targets.load(root)
    if names:
        try:
            return [found.get(name) for name in names]
        except targets.TargetError as error:
            raise MapError(str(error)) from None
    return [repo for name, repo in sorted(found.repos.items()) if not repo.knowledge_base]


def build(root: Path, names: Optional[List[str]] = None, profile: str = "", fresh: bool = False) -> Dict[str, Any]:
    """`kb map`: map the repositories (all target repositories but the knowledge base, or the ones named), then sum up."""
    choices = profiles(root)
    if profile and profile not in choices:
        raise MapError(say("kbmap.unknown_profile", name=profile, known=messages.joined(sorted(choices)) or "-"))
    repos = chosen_repos(root, names)
    if not repos:
        raise MapError(say("kbmap.no_repos"))
    rows = [build_one(root, repo, choices, profile, fresh) for repo in repos]
    graph = Graph.load(root, [repo.name for repo in repos])
    return {"mapped": rows, **graph.summary(), "next": say("kbmap.next" if graph.nodes else "kbmap.empty")}


# --- the graph -----------------------------------------------------------------------------------------


def keys_of(name: str) -> List[str]:
    """The names an object can be called by: `Db.dbo.t`, `dbo.t`, `t`; a package also by its stem."""
    low = name.lower()
    dotted = low.split(".")
    found = [low, ".".join(dotted[-2:]), dotted[-1]]
    if "/" in low:
        found.append(low.rsplit("/", 1)[-1])
    return list(dict.fromkeys(found))


class Graph:
    """The objects and uses of the mapped repositories, with the names resolved across all of them."""

    def __init__(self) -> None:
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.out: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        self.into: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        self.external: Dict[str, Set[str]] = defaultdict(set)
        self.duplicates: List[str] = []
        self.entry_types: Set[str] = set()
        self.shared_min = 3

    @classmethod
    def load(cls, root: Path, names: Optional[List[str]] = None) -> "Graph":
        graph = cls()
        folder = paths.runtime_dir(root) / "kbmap"
        files = [cache_file(root, name) for name in names] if names else sorted(folder.glob("*.json")) if folder.is_dir() else []
        records = [record for record in (read_cache(root, file.stem) for file in files) if record]
        for record in records:
            graph.entry_types.update(record.get("entry_types") or [])
        graph.shared_min = max([int(record.get("shared_min", 3)) for record in records] or [3])
        pending = []
        for record in records:
            for path, item in sorted(record["files"].items()):
                for obj in item["objects"]:
                    if obj["id"] in graph.nodes:
                        graph.duplicates.append(obj["id"])
                        continue
                    graph.nodes[obj["id"]] = {
                        "id": obj["id"], "type": obj["type"], "name": obj["name"], "repo": record["repo"], "path": path,
                        "line": obj.get("line", 1), "dynamic": bool(obj.get("dynamic")), **({"scheduled": True} if obj.get("scheduled") else {}),
                    }
                    pending.append((obj["id"], obj.get("refs") or []))
        graph.resolve(pending)
        return graph

    def resolve(self, pending: List[Tuple[str, List[Dict[str, Any]]]]) -> None:
        index: Dict[str, List[str]] = defaultdict(list)
        for node in self.nodes.values():
            for key in keys_of(node["name"]):
                index[key].append(node["id"])
        for source, refs in pending:
            seen = set()
            for ref in refs:
                target = self.find(index, ref)
                if target is None:
                    continue
                if target.startswith("?"):
                    self.external[target[1:]].add(source)
                    continue
                if target == source or (ref["kind"], target) in seen:
                    continue
                seen.add((ref["kind"], target))
                self.out[source].append((target, ref["kind"]))
                self.into[target].append((source, ref["kind"]))

    def find(self, index: Dict[str, List[str]], ref: Dict[str, Any]) -> Optional[str]:
        """The id a use points at; `?<name>` when it names something outside the map; None for a bare name nothing has (an alias)."""
        raw, kind_hint = ref["name"], ref.get("as", "")
        sql = kind_hint == "" and ref["kind"] in ("calls", "reads", "writes")
        wanted = kbextract.sql_name(raw, ref.get("db", "")) if sql else raw
        pieces = kbextract.parts(raw) if sql else [raw]

        def pick(candidates: List[str]) -> Optional[str]:
            if kind_hint:
                candidates = [item for item in candidates if self.nodes[item]["type"] == kind_hint]
            return candidates[0] if len(candidates) == 1 else None

        low = wanted.lower()
        for key in (low, *([low.rsplit("/", 1)[-1]] if "/" in low else [])):
            hit = pick(index.get(key, []))
            if hit:
                return hit
        if sql:
            dotted = low.split(".")
            near = index.get(".".join(dotted[-2:]), [])
            if len(dotted) == 3:  # a database was named or known: an object of another database is not it
                near = [item for item in near if len(self.nodes[item]["name"].split(".")) < 3 or self.nodes[item]["name"].lower() == low]
            hit = pick(near)
            if hit:
                return hit
            if len(pieces) == 1:
                hit = pick(index.get(dotted[-1], []))
                if hit:
                    return hit
            return f"?{wanted}" if len(pieces) > 1 else None
        hit = pick(index.get(low.split(".")[-1], []))
        return hit or (f"?{wanted}" if kind_hint or "." in raw or "/" in raw else None)

    # --- questions ---

    def entries(self) -> List[str]:
        typed = sorted(node for node, item in self.nodes.items() if item["type"] in self.entry_types)
        if typed:
            return typed
        return sorted(node for node in self.nodes if not self.into.get(node) and self.out.get(node))

    def reach(self, start: str) -> Set[str]:
        seen, queue = {start}, deque([start])
        while queue:
            for target, _kind in self.out.get(queue.popleft(), []):
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        return seen

    def summary(self) -> Dict[str, Any]:
        entries = self.entries()
        unused = sorted(node for node, item in self.nodes.items() if item["type"] in EXECUTABLE and not self.into.get(node) and node not in entries)
        dynamic = sorted(node for node, item in self.nodes.items() if item["dynamic"])
        used = sorted(self.nodes, key=lambda node: (-len(self.into.get(node, [])), node))
        return {
            "objects": dict(sorted(Counter(item["type"] for item in self.nodes.values()).items())),
            "uses": dict(sorted(Counter(kind for links in self.out.values() for _target, kind in links).items())),
            "entry_points": len(entries), "entry_sample": entries[:SAMPLE],
            "unused": len(unused), "unused_sample": unused[:SAMPLE],
            "dynamic": len(dynamic), "dynamic_sample": dynamic[:SAMPLE],
            "external": [{"name": name, "used_by": len(users)} for name, users in sorted(self.external.items(), key=lambda item: (-len(item[1]), item[0]))[:SAMPLE]],
            "most_used": [{"id": node, "used_by": len(self.into.get(node, []))} for node in used[:SAMPLE] if self.into.get(node)],
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
    external = sorted(name for name, users in graph.external.items() if node["id"] in users)
    if external:
        result["uses_outside_map"] = external
    if node["dynamic"]:
        result["note"] = say("kbmap.near.dynamic")
    return result


# --- domains ---------------------------------------------------------------------------------------------


def words(text: str) -> List[str]:
    found = []
    for piece in text.replace("/", " ").replace(".", " ").replace("-", " ").replace("_", " ").split():
        for word in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+", piece):
            low = word.lower()
            if len(low) > 2 and low not in STOP_WORDS and not low.isdigit():
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
    everywhere = Counter(word for entry in entries for word in set(words(graph.nodes[entry]["name"])))
    domains = []
    for group in sorted(groups, key=lambda item: (-len(item), min(item))):
        starts = sorted(node for node in group if node in entries)
        local = Counter(word for entry in starts for word in set(words(graph.nodes[entry]["name"])))
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
