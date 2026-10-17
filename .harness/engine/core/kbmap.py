"""The repository map (M15-10d, layer one of learning a code base): every object and every use, by script.

  kb map    read the base branch of each target repository with the extractors of the team's toolkit
            (`<knowledge base>/toolkit/`, contract in .harness/contracts/kb/map.md); keep the result per file, by git
            blob sha, in .harness/runtime/kbmap/<repo>.json. A file that did not change is not read again. The map is
            a cache: it can be built again at any time, so it is not knowledge and does not go into the knowledge base.
            Each run checks the toolkit against the uses a person knows (`facts.jsonl`)
  kb near   what one object uses and what uses it, a few steps out: the impact of a change across domains
  kb split  a first cut of the domains: from each entry point, what it reaches; objects reached from many entry points
            are shared (a log procedure, a calendar table) and are taken out first, or everything joins into one domain

The harness ships no toolkit: what a procedure or a class looks like in a file depends on the stack and is made by each
team with /generic-kb-toolkit-design and /generic-kb-toolkit-build. No model reads anything here.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import gitread, kbextract, messages, paths, repo_paths, state, targets, tasks

SCHEMA_VERSION = 2
TOOLKIT_DIR = "toolkit"
TOOLKIT_FILE = "toolkit.json"
FACTS_FILE = "facts.jsonl"
MAX_FILE_BYTES = 5_000_000  # a bigger file is listed under `skipped`, not read
GIT_TIMEOUT = 300
SAMPLE = 10
NEAR_LIMIT = 200
NAME_STYLES = ("sql", "plain")
SURVEY_KINDS = 15  # kinds of file shown per repository
SURVEY_FOLDERS = 15


class MapError(ValueError):
    """The map cannot be built or read as asked."""


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


# --- toolkits -----------------------------------------------------------------------------------------


@dataclass
class Toolkit:
    name: str
    folder: Path
    data: Dict[str, Any]
    signature: str
    extractors: Dict[Tuple[str, str], kbextract.Extractor] = field(default_factory=dict)

    def rule_for(self, path: str) -> Optional[Dict[str, Any]]:
        if any(matches(pattern, path) for pattern in self.data.get("ignore") or []):
            return None
        return next((rule for rule in self.data["extractors"] if matches(rule["glob"], path)), None)

    def extractor(self, rule: Dict[str, Any]) -> kbextract.Extractor:
        if rule.get("builtin"):
            return kbextract.BUILTIN[rule["builtin"]]
        key = (rule["file"], rule.get("function", "extract"))
        if key not in self.extractors:
            try:
                self.extractors[key] = kbextract.load(self.folder / key[0], key[1])
            except kbextract.ToolkitError as error:
                raise MapError(say("kbmap.toolkit_bad", folder=self.folder, problem=error)) from None
        return self.extractors[key]

    def facts(self) -> List[Dict[str, str]]:
        file = self.folder / FACTS_FILE
        if not file.is_file():
            return []
        found = []
        for line in file.read_text(encoding="utf-8").splitlines():
            try:
                fact = json.loads(line) if line.strip() else None
            except ValueError:
                fact = None
            if isinstance(fact, dict) and fact.get("from") and fact.get("to"):
                found.append({"from": str(fact["from"]), "kind": str(fact.get("kind") or ""), "to": str(fact["to"])})
        return found


def problems_of(data: Any) -> List[str]:
    """What is wrong with a toolkit.json, in the words of map.md."""
    if not isinstance(data, dict):
        return ["not a JSON object"]
    found = [f"no `{key}`" for key in ("schema_version", "name", "extractors") if key not in data]
    for number, rule in enumerate(data.get("extractors") or [], 1):
        if not isinstance(rule, dict) or not rule.get("glob"):
            found.append(f"extractors[{number}] has no glob")
        elif rule.get("builtin"):
            if rule["builtin"] not in kbextract.BUILTIN:
                found.append(f"extractors[{number}]: no builtin `{rule['builtin']}` ({', '.join(kbextract.BUILTIN)})")
        elif not rule.get("file"):
            found.append(f"extractors[{number}] names no file")
        elif Path(rule["file"]).is_absolute() or ".." in Path(rule["file"]).parts:
            found.append(f"extractors[{number}]: the file must be inside the toolkit folder")
    if data.get("names", "sql") not in NAME_STYLES:
        found.append(f"`names` is one of {', '.join(NAME_STYLES)}")
    return found


def load_toolkit(folder: Path) -> Toolkit:
    """The toolkit in `folder`. A broken one stops the map: its owner must know what is wrong."""
    file = folder / TOOLKIT_FILE
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MapError(say("kbmap.toolkit_bad", folder=folder, problem=error)) from None
    problems = problems_of(data)
    if problems:
        raise MapError(say("kbmap.toolkit_bad", folder=folder, problem="; ".join(problems)))
    digest = sha256(file.read_bytes())
    for name in sorted({rule["file"] for rule in data["extractors"] if rule.get("file")}):
        target = folder / name
        digest.update(target.read_bytes() if target.is_file() else b"-")
    return Toolkit(str(data["name"]), folder, data, digest.hexdigest()[:16])


def toolkits(root: Path, trial: Optional[Path] = None) -> List[Toolkit]:
    """The toolkit of each knowledge base that has one; or only `trial`, a toolkit being built inside a task."""
    if trial is not None:
        folder = trial.resolve()
        try:
            folder.relative_to((root / tasks.TASKS_DIR).resolve())
        except ValueError:
            raise MapError(say("kbmap.trial_outside", folder=folder)) from None
        return [load_toolkit(folder)]
    return [load_toolkit(folder / TOOLKIT_DIR) for _name, folder in targets.knowledge_bases(root) if (folder / TOOLKIT_DIR / TOOLKIT_FILE).is_file()]


def toolkit_for(choices: List[Toolkit], repo: str) -> Optional[Toolkit]:
    named = [kit for kit in choices if repo in (kit.data.get("repos") or [])]
    if named:
        return named[0]
    return next((kit for kit in choices if not kit.data.get("repos")), None)


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


# --- reading a repository ---------------------------------------------------------------------------------


def nearest(path: str, markers: Dict[str, str]) -> str:
    """The stem of the nearest marker file (`markers` in toolkit.json) in a folder above the file, or an empty string."""
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


def build_one(root: Path, repo: targets.Repo, kit: Optional[Toolkit], fresh: bool) -> Dict[str, Any]:
    """Map one repository. Reads only the files whose blob changed since the last map."""
    if kit is None:
        return {"repo": repo.name, "toolkit": "-", "note": say("kbmap.no_toolkit")}
    commit = targets.ref_commit(repo)
    if not commit:
        return {"repo": repo.name, "toolkit": kit.name, "note": say("kbmap.no_branch", branch=repo.base_ref)}
    files = gitread.listing(repo.path, repo.name, commit, timeout=GIT_TIMEOUT)
    old = {} if fresh else read_cache(root, repo.name)
    kept = old.get("files", {}) if old.get("signature") == kit.signature else {}
    all_paths = [path for _sha, _size, path in files]
    marks = {key: markers(all_paths, str(suffix).lower()) for key, suffix in (kit.data.get("markers") or {}).items()}
    chosen: Dict[str, Tuple[str, int, Dict[str, Any]]] = {}
    for sha, size, path in files:
        rule = kit.rule_for(path)
        if rule:
            chosen[path] = (sha, size, rule)
    todo = [path for path, (sha, _size, _rule) in chosen.items() if kept.get(path, {}).get("sha") != sha]
    skipped = sorted(path for path in todo if chosen[path][1] > MAX_FILE_BYTES)
    todo = [path for path in todo if path not in skipped]
    data = gitread.blobs(repo.path, repo.name, sorted({chosen[path][0] for path in todo}), timeout=GIT_TIMEOUT)
    result: Dict[str, Any] = {path: kept[path] for path in chosen if path not in todo and path in kept}
    unread = sorted(path for path in todo if chosen[path][0] not in data)  # not cached: read again next time
    todo = [path for path in todo if path not in unread]
    for path in todo:
        sha, _size, rule = chosen[path]
        pure = PurePosixPath(path)
        context = {"path": path, "stem": pure.stem, "folder": pure.parent.name, "repo": repo.name, "rule": rule, **{key: nearest(path, found) for key, found in marks.items()}}
        objects, error = kbextract.run(kit.extractor(rule), data.get(sha, b""), context)
        result[path] = {"sha": sha, "objects": objects, **({"error": error} if error else {})}
    record = {
        "schema_version": SCHEMA_VERSION, "repo": repo.name, "ref": repo.base_ref, "commit": commit, "toolkit": kit.name, "signature": kit.signature,
        "folder": str(kit.folder), "rules": {key: kit.data.get(key) for key in ("names", "entry_types", "executable_types", "stop_words", "shared_min", "obsolete")},
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "skipped": skipped, "files": result,
    }
    state.atomic_write(cache_file(root, repo.name), record, compact=True)
    return {
        "repo": repo.name, "toolkit": kit.name, "commit": commit[:12], "files": len(chosen), "read": len(todo),
        "objects": sum(len(item["objects"]) for item in result.values()),
        "empty": sum(1 for item in result.values() if not item["objects"] and not item.get("error")),
        "failed": sum(1 for item in result.values() if item.get("error")) + len(unread), "skipped": len(skipped),
        **({"unread": unread[:SAMPLE]} if unread else {}),
    }


def chosen_repos(root: Path, names: Optional[List[str]]) -> List[targets.Repo]:
    found = targets.load(root)
    if names:
        try:
            return [found.get(name) for name in names]
        except targets.TargetError as error:
            raise MapError(str(error)) from None
    return [repo for name, repo in sorted(found.repos.items()) if not repo.knowledge_base]


def build(root: Path, names: Optional[List[str]] = None, fresh: bool = False, trial: Optional[Path] = None) -> Dict[str, Any]:
    """`kb map`: map the repositories (all target repositories but the knowledge base, or the ones named), then sum up.
    `trial`: use the toolkit being built in a task instead of the knowledge base's (its map replaces the cached one)."""
    choices = toolkits(root, trial)
    if not choices:
        raise MapError(say("kbmap.no_toolkit"))
    repos = chosen_repos(root, names)
    if not repos:
        raise MapError(say("kbmap.no_repos"))
    rows = []
    for repo in repos:
        try:
            rows.append(build_one(root, repo, toolkit_for(choices, repo.name), fresh))
        except gitread.GitError as error:  # one repository git cannot read: say so, map the others
            rows.append({"repo": repo.name, "toolkit": "-", "note": str(error)})
    graph = Graph.load(root, [repo.name for repo in repos])
    facts = graph.check_facts([fact for kit in choices for fact in kit.facts()])
    result = {"mapped": rows, **graph.summary(), "facts": facts}
    if not graph.nodes:
        result["next"] = say("kbmap.empty")
    elif facts.get("missing") or not facts.get("checked"):
        result["next"] = say("kbmap.next.facts")
    else:
        result["next"] = say("kbmap.next")
    return result


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


# --- survey: what a repository holds, before there is a toolkit ------------------------------------------------


def survey_one(repo: targets.Repo, samples: int) -> Dict[str, Any]:
    commit = targets.ref_commit(repo)
    if not commit:
        return {"repo": repo.name, "note": say("kbmap.no_branch", branch=repo.base_ref)}
    files = gitread.listing(repo.path, repo.name, commit, timeout=GIT_TIMEOUT)
    by_suffix: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for _sha, size, path in files:
        by_suffix[PurePosixPath(path).suffix.lower() or PurePosixPath(path).name].append((size, path))
    folders = Counter("/".join(PurePosixPath(path).parent.parts[:2]) or "." for _sha, _size, path in files)
    kinds = []
    for suffix, items in sorted(by_suffix.items(), key=lambda item: (-len(item[1]), item[0]))[:SURVEY_KINDS]:
        ordered = sorted(items)
        spread = [ordered[(len(ordered) - 1) * step // max(samples - 1, 1)][1] for step in range(samples)] if ordered else []
        kinds.append({"kind": suffix, "files": len(items), "bytes": sum(size for size, _path in items), "samples": list(dict.fromkeys(spread))})
    return {
        "repo": repo.name, "commit": commit[:12], "files": len(files),
        "top_level": sorted({PurePosixPath(path).parts[0] + ("/" if len(PurePosixPath(path).parts) > 1 else "") for _sha, _size, path in files})[:40],
        "folders": [{"folder": name, "files": count} for name, count in folders.most_common(SURVEY_FOLDERS)],
        "kinds": kinds,
    }


def survey(root: Path, names: Optional[List[str]] = None, samples: int = 3) -> Dict[str, Any]:
    """`kb survey`: per repository, the kinds of files, the folders, and a few sample files of each kind (small, middle,
    large), from the base branch. The first step of designing a toolkit; needs none."""
    repos = chosen_repos(root, names)
    if not repos:
        raise MapError(say("kbmap.no_repos"))
    return {"repos": [survey_one(repo, max(1, min(samples, 10))) for repo in repos], "next": say("kbmap.survey.next")}
