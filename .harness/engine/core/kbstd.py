"""The knowledge base standard, v1 (M15-10): a fixed form, so that scripts can check it and find what went stale.

  <knowledge base>/domains/<domain>/
    domain.yaml              who the domain is: scope, sources (repo, branch, commit), entry points, boundaries,
                             open questions, the files. It lists no objects: they are in the index, once
    architecture.md          the flows, the entry points, the traps, where to start for each kind of task
    objects/index.jsonl      one line per object: id, type, repo, sources [{path, sha}], card, level
    objects/<type>.md        the cards: one `## <id>` section per object

What is checked here is the form, by code: no model reads anything. `stale` asks git which source files changed
since the knowledge was written (the `sha` of each source is the git blob of that file).
The contract with the field lists is `.harness/contracts/kb/README.md`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import domainskills, gitread, messages, miniyaml, targets, tasks

SCHEMA_VERSION = 1
DOMAIN_FILE = "domain.yaml"
INDEX_FILE = "objects/index.jsonl"
LEVELS = ("verified", "supported", "inferred", "unknown", "conflict")
DOMAIN_REQUIRED = ("schema_version", "domain", "description", "sources", "entry_points")
DOMAIN_KNOWN = DOMAIN_REQUIRED + ("updated", "generated_by", "boundaries", "shared", "excluded", "systems", "files", "open_questions", "environment")
OBJECT_LISTS = ("included_objects", "core_objects", "objects")  # belong in the index, not in domain.yaml
OBJECT_REQUIRED = ("id", "type", "card", "level")
ID = re.compile(r"^[a-z][a-z0-9_-]*:\S(?:[^\t\r\n]*\S)?\Z")  # the name may hold spaces ("job:Daily Load"), not at its ends
LOCAL_PATH = re.compile(r"(?i)(?:[a-z]:\\users\\|/users/[^/\s]+/|/home/[^/\s]+/|%localappdata%|%userprofile%|~[/\\])")
TEXT_SUFFIXES = (".md", ".yaml", ".yml", ".json", ".jsonl")
HEADING = re.compile(r"^#{2,6}\s+(.+?)\s*#*\s*$")
CARD_MAX_LINES = 120
ARCHITECTURE_MAX_LINES = 300
GIT_TIMEOUT = 30
DIFF_LINES = 120  # per source: longer is cut, and the source is read instead


class KbError(ValueError):
    """A knowledge base command cannot do what was asked; the message says why."""


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def read_index(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(the objects, the problems of lines that are not one JSON object each)."""
    rows, problems = [], []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as error:
            problems.append(say("kb.index.bad_line", line=number, error=error))
            continue
        if not isinstance(row, dict):
            problems.append(say("kb.index.bad_line", line=number, error="not an object"))
            continue
        row["_line"] = number
        rows.append(row)
    return rows, problems


def anchors(path: Path) -> Dict[str, int]:
    """{the text of each heading below the title (`##` to `######`): how many lines its section has}."""
    found: Dict[str, int] = {}
    current = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        heading = HEADING.match(line)
        if heading:
            current = heading.group(1).strip().strip("`")
            found[current] = 0
        elif current:
            found[current] += 1
    return found


def card_limit(row: Dict[str, Any]) -> int:
    """120 lines; a card of a long object (its `lines` in the index, from `kb index`) may have one line per 10 of code."""
    span = row.get("lines")
    if isinstance(span, list) and len(span) == 2 and all(isinstance(item, int) for item in span):
        return max(CARD_MAX_LINES, (span[1] - span[0] + 1) // 10)
    return CARD_MAX_LINES


def check_domain(root: Path, folder: Path) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    spec = folder / DOMAIN_FILE
    data: Dict[str, Any] = {}
    if not spec.is_file():
        errors.append(say("kb.domain.missing", file=DOMAIN_FILE))
    else:
        try:
            loaded = miniyaml.loads(spec.read_text(encoding="utf-8"))
            data = loaded if isinstance(loaded, dict) else {}
            if not isinstance(loaded, dict):
                errors.append(say("kb.domain.not_mapping"))
        except miniyaml.YamlError as error:
            errors.append(say("kb.domain.unreadable", error=error))
    if data:
        if data.get("schema_version") != SCHEMA_VERSION:
            errors.append(say("kb.domain.version", found=data.get("schema_version"), wanted=SCHEMA_VERSION))
        errors += [say("kb.domain.field", field=field) for field in DOMAIN_REQUIRED if field not in data]
        if data.get("domain") is not None and str(data.get("domain")).lower() != folder.name.lower():
            errors.append(say("kb.domain.name", found=data.get("domain"), folder=folder.name))
        scope = data.get("scope") if isinstance(data.get("scope"), dict) else {}
        listed = [key for key in OBJECT_LISTS if key in data or key in scope]
        if listed:
            warnings.append(say("kb.domain.object_list", keys=", ".join(listed)))
        unknown = [key for key in data if key not in DOMAIN_KNOWN and key not in OBJECT_LISTS]
        if unknown:
            warnings.append(say("kb.domain.unknown_keys", keys=", ".join(unknown)))
        for source in data.get("sources") or []:
            if not isinstance(source, dict) or not source.get("repo") or not source.get("commit"):
                errors.append(say("kb.domain.source", source=source))
        for name, relative in (data.get("files") or {}).items() if isinstance(data.get("files"), dict) else []:
            if isinstance(relative, str) and not (folder / relative).exists():
                errors.append(say("kb.domain.file_missing", name=name, path=relative))
    rows: List[Dict[str, Any]] = []
    index = folder / INDEX_FILE
    if not index.is_file():
        errors.append(say("kb.index.missing", file=INDEX_FILE))
    else:
        rows, bad = read_index(index)
        errors += bad
    seen: Dict[str, int] = {}
    cards: Dict[str, Dict[str, int]] = {}
    for row in rows:
        line = row["_line"]
        missing = [field for field in OBJECT_REQUIRED if not row.get(field)]
        if missing:
            errors.append(say("kb.object.field", line=line, fields=", ".join(missing)))
            continue
        if not ID.match(str(row["id"])):
            errors.append(say("kb.object.id", line=line, id=row["id"]))
        if row["id"] in seen:
            errors.append(say("kb.object.twice", id=row["id"], first=seen[row["id"]], line=line))
        seen.setdefault(row["id"], line)
        if row["level"] not in LEVELS:
            errors.append(say("kb.object.level", id=row["id"], level=row["level"], levels=", ".join(LEVELS)))
        gap = row.get("source_missing")
        if gap is not None:
            if not isinstance(gap, dict) or not gap.get("seen_in"):
                errors.append(say("kb.object.source_missing", id=row["id"]))
            elif row.get("level") not in ("unknown", "conflict"):
                warnings.append(say("kb.object.gap_level", id=row["id"]))
        elif row["type"] != "family":
            sources = row.get("sources")
            if not isinstance(sources, list) or not all(isinstance(item, dict) and item.get("path") for item in sources):
                warnings.append(say("kb.object.sources", id=row["id"]))
            elif not row.get("repo"):
                errors.append(say("kb.object.repo", id=row["id"]))
        card_file, _, anchor = str(row["card"]).partition("#")
        path = folder / card_file
        if not path.is_file():
            errors.append(say("kb.object.card_file", id=row["id"], card=row["card"]))
            continue
        if card_file not in cards:
            cards[card_file] = anchors(path)
        if not anchor:
            warnings.append(say("kb.object.no_anchor", id=row["id"], card=row["card"]))
        elif anchor not in cards[card_file]:
            errors.append(say("kb.object.anchor", id=row["id"], card=row["card"]))
        elif cards[card_file][anchor] > card_limit(row):
            warnings.append(say("kb.object.card_long", id=row["id"], lines=cards[card_file][anchor], limit=card_limit(row)))
    for entry in data.get("entry_points") or [] if data else []:
        if isinstance(entry, str) and rows and entry not in seen:
            errors.append(say("kb.domain.entry", id=entry))
    architecture = folder / "architecture.md"
    if not architecture.is_file():
        warnings.append(say("kb.domain.no_architecture"))
    elif len(architecture.read_text(encoding="utf-8", errors="replace").splitlines()) > ARCHITECTURE_MAX_LINES:
        warnings.append(say("kb.domain.architecture_long", limit=ARCHITECTURE_MAX_LINES))
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace")
            hit = LOCAL_PATH.search(text)
            if hit:
                errors.append(say("kb.local_path", file=path.relative_to(folder).as_posix(), found=hit.group(0)))
    return {"domain": folder.name, "objects": len(rows), "errors": errors, "warnings": warnings}


def check(root: Path, only: Optional[List[str]] = None) -> Dict[str, Any]:
    known = domainskills.domains(root)
    asked = {name: domainskills.find(known, name) for name in only or []}
    wanted = [name for name in known if not only or name in asked.values()]
    missing = [name for name, found in asked.items() if found is None]
    results = [check_domain(root, known[name]) for name in wanted]
    errors = sum(len(item["errors"]) for item in results)
    return {
        "domains": len(results), "errors": errors, "warnings": sum(len(item["warnings"]) for item in results),
        "problems": [item for item in results if item["errors"] or item["warnings"]],
        "missing": missing,
        "next": say("kb.check.errors" if errors else "kb.check.ok" if results else "kb.check.none"),
        "exit_code": 1 if errors or missing else 0,
    }


def stale(root: Path, domain: str, diff: bool = False) -> Dict[str, Any]:
    """Which objects of the domain were written from a source that has changed since, on the base branch.
    With `diff`: what changed in each source, so that the card can be checked against the change, not the whole file."""
    known = domainskills.domains(root)
    name = domainskills.find(known, domain)
    if name is None:
        raise ValueError(say("kb.stale.no_domain", domain=domain, known=", ".join(known) or "-"))
    domain = name
    rows, _bad = read_index(known[domain] / INDEX_FILE)
    found = targets.load(root)
    by_repo: Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]] = {}
    for row in rows:
        for source in row.get("sources") or []:
            if isinstance(source, dict) and source.get("path"):
                by_repo.setdefault(str(row.get("repo") or ""), []).append((row, source))
    changed, gone, unstamped, unknown_repos, unreadable = [], [], [], [], []
    for name, items in by_repo.items():
        repo = found.repos.get(name)
        if repo is None:
            unknown_repos.append(name)
            continue
        try:
            current = gitread.blob_shas(repo.path, name, repo.base_ref, sorted({source["path"] for _row, source in items}))
        except gitread.GitError as error:  # a wrong base branch must not read as "every source is gone"
            unreadable.append({"repo": name, "error": str(error)})
            continue
        for row, source in items:
            path = source["path"]
            entry = {"id": row["id"], "path": f"{name}/{path}", "card": row.get("card", "")}
            if path not in current:
                gone.append(entry)
            elif not source.get("sha"):
                unstamped.append(entry)
            elif not current[path].startswith(str(source["sha"])):
                if diff:
                    entry["diff"], cut = gitread.blob_diff(repo.path, name, str(source["sha"]), current[path], DIFF_LINES)
                    if cut:
                        entry["diff_cut"] = True
                    if not entry["diff"]:
                        entry["diff_note"] = say("kb.stale.no_diff")
                changed.append(entry)
    return {
        "domain": domain, "objects": len(rows), "changed": changed, "gone": gone, "unstamped": unstamped, "unknown_repos": unknown_repos,
        **({"unreadable_repos": unreadable} if unreadable else {}),
        "next": say("kb.stale.unreadable" if unreadable else "kb.stale.next" if changed or gone else "kb.stale.fresh"),
    }


def cards_of(root: Path, repo_name: str, paths: List[str]) -> List[Dict[str, str]]:
    """The objects of every domain whose sources include one of these repository paths, with their cards. For `task fetch`."""
    wanted = set(paths)
    hits = []
    for domain, folder in domainskills.domains(root).items():
        index = folder / INDEX_FILE
        if not index.is_file():
            continue
        rows, _bad = read_index(index)
        for row in rows:
            if row.get("repo") != repo_name:
                continue
            for source in row.get("sources") or []:
                if isinstance(source, dict) and source.get("path") in wanted:
                    card_file, mark, anchor = str(row.get("card", "")).partition("#")
                    shown = domainskills.shown_path(root, folder / card_file) + mark + anchor if card_file else ""
                    hits.append({"domain": domain, "id": row["id"], "path": source["path"], "sha": str(source.get("sha") or ""), "card": shown})
    return hits


def knowledge_for(root: Path, keys: List[str]) -> List[Dict[str, Any]]:
    """For fetched `<repo>/<path>` keys: the cards that describe those files, each marked stale when the file on the
    base branch is not the one the card was written from. Never raises: a fetch must not fail over the knowledge base."""
    try:
        if not domainskills.domains(root):
            return []
        found = targets.load(root)
        by_repo: Dict[str, List[str]] = {}
        for key in keys:
            name, _, path = key.partition("/")
            if name in found.repos and path:
                by_repo.setdefault(name, []).append(path)
        out = []
        for name, paths in by_repo.items():
            hits = cards_of(root, name, paths)
            if not hits:
                continue
            repo = found.repos[name]
            try:
                current = gitread.blob_shas(repo.path, name, repo.base_ref, sorted({hit["path"] for hit in hits}))
            except gitread.GitError:  # cannot tell: say nothing rather than call every card stale
                continue
            for hit in hits:
                now = current.get(hit["path"], "")
                out.append({"id": hit["id"], "card": hit["card"], "file": f"{name}/{hit['path']}", "stale": bool(hit["sha"]) and not now.startswith(hit["sha"])})
        return out
    except Exception:  # noqa: BLE001
        return []


# --- writing, in a task only ------------------------------------------------------------------------


def check_path(root: Path, folder: Optional[Path]) -> Dict[str, Any]:
    """`kb check --path`: one domain folder anywhere (a migration in a task's DEV/)."""
    result = check_domain(root, folder.resolve()) if folder else {}
    result["exit_code"] = 1 if result.get("errors") else 0
    return result


def stamp(root: Path, folder: Path, ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """`kb stamp`: after the cards were checked against the code, set the `sha` of their sources to the base branch now,
    so that `kb stale` counts from here. Only in a task's `DEV/`; only the objects named, or all of them."""
    folder = folder.resolve()
    if not tasks.in_dev(root, folder):
        raise KbError(say("kb.stamp.not_dev", folder=folder))
    index = folder / INDEX_FILE
    if not index.is_file():
        raise KbError(say("kb.index.missing", file=index))
    rows, bad = read_index(index)
    if bad:
        raise KbError(" ".join(bad))
    known = {row.get("id") for row in rows}
    unknown = sorted(set(ids or []) - known)
    if unknown:
        raise KbError(say("kb.stamp.unknown_ids", ids=", ".join(unknown)))
    wanted = set(ids or known)
    found = targets.load(root)
    stamped, unchanged, gone, unknown_repos = [], 0, [], set()
    by_repo: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        if row.get("id") in wanted:
            by_repo.setdefault(str(row.get("repo") or ""), []).append(row)
    for name, items in by_repo.items():
        repo = found.repos.get(name)
        if repo is None:
            unknown_repos.add(name)
            continue
        sources = [source for row in items for source in row.get("sources") or [] if isinstance(source, dict) and source.get("path")]
        try:
            current = gitread.blob_shas(repo.path, name, repo.base_ref, sorted({source["path"] for source in sources}))
        except gitread.GitError as error:  # never stamp from an answer git did not give
            raise KbError(str(error)) from None
        for row in items:
            changed = False
            for source in row.get("sources") or []:
                if not isinstance(source, dict) or not source.get("path"):
                    continue
                now = current.get(source["path"])
                if now is None:
                    gone.append(f"{row['id']}: {name}/{source['path']}")
                elif not now.startswith(str(source.get("sha") or "-")):
                    source["sha"], changed = now[:12], True
            if changed:
                stamped.append(row["id"])
            else:
                unchanged += 1
    if stamped:
        index.write_text("".join(json.dumps({key: value for key, value in row.items() if key != "_line"}, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return {
        "folder": str(folder), "stamped": stamped, "unchanged": unchanged, "gone": gone, "unknown_repos": sorted(unknown_repos),
        "next": say("kb.stamp.next" if stamped else "kb.stamp.nothing"),
    }
