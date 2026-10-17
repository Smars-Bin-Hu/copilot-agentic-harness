"""Building the repository map (M15-10d, layer one of learning a code base): every object and every use, by script.

  kb survey  what each repository holds, before there is a toolkit
  kb map     read the base branch of each target repository with the extractors of the team's toolkit
             (`<knowledge base>/toolkit/`, contract in .harness/contracts/kb/map.md); keep the result per file, by git
             blob sha, in .harness/runtime/kbmap/<repo>.json. A file that did not change is not read again. The map is
             a cache: it can be built again at any time, so it is not knowledge and does not go into the knowledge base.
             Each run checks the toolkit against the uses a person knows (`facts.jsonl`)

The harness ships no toolkit: what a procedure or a class looks like in a file depends on the stack and is made by each
team with /generic-kb-toolkit-design and /generic-kb-toolkit-build. No model reads anything here. The questions on the
map (`kb near`, `kb split`, `kb gaps`) are in core/kbgraph.py.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import gitread, kbextract, messages, state, targets, tasks
from .kbgraph import SAMPLE, SCHEMA_VERSION, Graph, MapError, cache_file, matches, read_cache

TOOLKIT_DIR = "toolkit"
TOOLKIT_FILE = "toolkit.json"
FACTS_FILE = "facts.jsonl"
MAX_FILE_BYTES = 5_000_000  # a bigger file is listed under `skipped`, not read
GIT_TIMEOUT = 300
NAME_STYLES = ("sql", "plain")
SURVEY_KINDS = 15  # kinds of file shown per repository
SURVEY_FOLDERS = 15


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
