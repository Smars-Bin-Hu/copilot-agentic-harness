"""`kb migrate`: a domain of before the standard (v0) into the standard form v1, by code (M15-10b).

v0 is the form many knowledge bases were first built in: `domain.yaml` with `metadata`, `scope` (with
`included_objects`), `entry_points`, `core_objects`, `dynamic_object_families`, `knowledge_files`, `systems`,
`servers`, `databases`, `sources`, `environment_validation`, `unresolved_items`; and `objects/indexes.json`
(`metadata` with `sourceBranch` and `sourceCommit`, `objects` with `id`, `sourceRepo`, `sourcePaths`, `artifactFile`).

What it does: one `domain.yaml` without object lists; `objects/index.jsonl` with one line per object; the members of
a dynamic family folded into one `family` line; the sha of each source at the commit the knowledge was learned from
(git, when the repository is set up here); `environment.md` from what v0 said of servers and environments; each
card pointed at the heading that names the object, when there is one. The cards themselves are not changed.
Everything it could not map is in the report. It writes only into a task's `DEV/`.
"""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import gitread, kbstd, miniyaml, targets, tasks
from .registry import harness_version

LEVEL_OF = {"confirmed": "verified", "verified": "verified", "partial": "supported", "supported": "supported", "inferred": "inferred", "unknown": "unknown", "conflict": "conflict"}
OLD_INDEX = "objects/indexes.json"
MAPPED = {
    "metadata", "scope", "entry_points", "core_objects", "dynamic_object_families", "knowledge_files", "systems", "servers",
    "databases", "sources", "environment_validation", "unresolved_items",
}


class MigrateError(ValueError):
    pass


def level(value: Any, default: str = "supported") -> str:
    text = str(value or "").strip().lower()
    if text in LEVEL_OF:
        return LEVEL_OF[text]
    if text.startswith("assumed"):
        return "inferred"
    return default


def inside_dev(root: Path, folder: Path) -> bool:
    """Is the folder inside the DEV/ of a task? The only place this command writes."""
    try:
        parts = folder.resolve().relative_to((root / tasks.TASKS_DIR).resolve()).parts
    except ValueError:
        return False
    return len(parts) >= 2 and parts[1] == tasks.DEV_NAME


def pattern_regex(pattern: str) -> re.Pattern:
    """`dbo.usp_run_<Rule_Id>` -> a regex that matches every member name."""
    parts = re.split(r"<[^>]+>", pattern)
    return re.compile("^(?:[^.]+\\.)?" + ".+".join(re.escape(part) for part in parts) + "$", re.IGNORECASE)


def headings(path: Path) -> List[str]:
    if not path.is_file():
        return []
    return [match.group(1).strip().strip("`") for line in path.read_text(encoding="utf-8", errors="replace").splitlines() for match in [kbstd.HEADING.match(line)] if match]


def card_for(folder: Path, artifact: str, object_id: str, name: str, cache: Dict[str, List[str]]) -> Tuple[str, bool]:
    """(the card, whether a heading names the object). Prefers a heading that is the id, then one that holds the name."""
    if not artifact:
        return "", False
    if artifact not in cache:
        cache[artifact] = headings(folder / artifact)
    found = cache[artifact]
    short = name.split(".")[-1] if name else ""
    for text in found:
        if text == object_id:
            return f"{artifact}#{text}", True
    for wanted in (name, short):
        if wanted:
            for text in found:
                if re.search(rf"(?<![\w]){re.escape(wanted)}(?![\w])", text):
                    return f"{artifact}#{text}", True
    return artifact, False


def shas_at(root: Path, repo_name: str, commit: str, paths: List[str]) -> Dict[str, str]:
    if not commit or not paths:
        return {}
    try:
        repo = targets.load(root).repos.get(repo_name)
    except Exception:  # noqa: BLE001 - no target set up: the shas stay empty and the report says so
        return {}
    if repo is None:
        return {}
    try:
        return gitread.blob_shas(repo.path, repo_name, commit, paths)
    except gitread.GitError:  # the old commit is not here (a shallow clone, another remote): the report lists the sources as unstamped
        return {}


def migrate(root: Path, source: Path, target: Path) -> Dict[str, Any]:
    source, target = source.resolve(), target.resolve()
    if not inside_dev(root, target):
        raise MigrateError(f"--to must be inside the DEV/ of a task (.workspace/sandbox/tasks/<task>/DEV/...): {target}")
    spec = source / kbstd.DOMAIN_FILE
    if not spec.is_file():
        raise MigrateError(f"no {kbstd.DOMAIN_FILE} in {source}")
    old = miniyaml.loads(spec.read_text(encoding="utf-8")) or {}
    if not isinstance(old, dict):
        raise MigrateError(f"{spec} is not a mapping")
    if old.get("schema_version") == kbstd.SCHEMA_VERSION:
        raise MigrateError(f"{spec} is already in the standard form (schema_version {kbstd.SCHEMA_VERSION})")
    index_path = source / OLD_INDEX
    old_index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {"metadata": {}, "objects": []}
    report: Dict[str, List[str]] = {"dropped_keys": [], "unanchored": [], "unstamped": [], "folded": [], "duplicates": [], "listed_not_indexed": [], "notes": []}

    if source != target:
        if target.exists() and any(target.iterdir()):
            raise MigrateError(f"{target} is not empty")
        shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("indexes.json"))
    meta = old.get("metadata") or {}
    index_meta = old_index.get("metadata") or {}
    scope = old.get("scope") or {}
    objects = [item for item in old_index.get("objects") or [] if isinstance(item, dict) and item.get("id")]

    # families first: their members are not listed one by one
    families, member_of = [], {}
    for family in old.get("dynamic_object_families") or []:
        if not isinstance(family, dict) or not family.get("object_pattern"):
            continue
        regex = pattern_regex(str(family["object_pattern"]))
        members = [item for item in objects if regex.match(str(item.get("name") or "")) and str(item.get("name")) != str(family["object_pattern"])]
        for item in members:
            member_of[item["id"]] = family.get("name")
        families.append((family, members))
        report["folded"].append(f"{family.get('name')}: {len(members)} objects -> 1 family line")

    repos = Counter(str(item.get("sourceRepo") or "") for item in objects if item.get("sourceRepo"))
    main_repo = repos.most_common(1)[0][0] if repos else ""
    commit = str(index_meta.get("sourceCommit") or "")
    branch = str(index_meta.get("sourceBranch") or "main")
    shas: Dict[str, Dict[str, str]] = {}
    for repo_name in repos:
        paths = sorted({path for item in objects if item.get("sourceRepo") == repo_name for path in item.get("sourcePaths") or []})
        shas[repo_name] = shas_at(root, repo_name, commit if repo_name == main_repo else "", paths)

    rows, seen, cache = [], set(), {}
    for item in objects:
        if item["id"] in member_of:
            continue
        if item["id"] in seen:
            report["duplicates"].append(item["id"])
            continue
        seen.add(item["id"])
        repo_name = str(item.get("sourceRepo") or "")
        sources = [{"path": path, "sha": shas.get(repo_name, {}).get(path, "")[:12]} for path in item.get("sourcePaths") or []]
        if any(not entry["sha"] for entry in sources):
            report["unstamped"].append(item["id"])
        card, anchored = card_for(target, str(item.get("artifactFile") or ""), item["id"], str(item.get("name") or ""), cache)
        if not anchored:
            report["unanchored"].append(item["id"])
        row: Dict[str, Any] = {"id": item["id"], "type": item.get("type") or item["id"].split(":", 1)[0], "name": item.get("name", "")}
        for key in ("classification", "database", "schema", "configKind"):
            if item.get(key):
                row[key] = item[key]
        row.update(repo=repo_name, sources=sources)
        if item.get("extraSourcePaths"):
            row["extra"] = item["extraSourcePaths"]
        row.update(card=card, level=level(item.get("status")))
        rows.append(row)
    for family, members in families:
        artifact = str(family.get("artifact") or "")
        card, anchored = card_for(target, artifact, f"family:{family.get('name')}", str(family.get("name") or ""), cache)
        row = {
            "id": f"family:{family.get('name')}", "type": "family", "pattern": family.get("object_pattern"), "member_type": family.get("type", ""),
            "members": len(members), "repo": str(members[0].get("sourceRepo") or "") if members else main_repo, "sources": [],
            "card": card, "level": level(family.get("status")),
        }
        for key in ("trigger", "output"):
            if family.get(key):
                row[key] = family[key]
        rows.append(row)
        if not anchored:
            report["unanchored"].append(row["id"])
    rows.sort(key=lambda row: row["id"])

    listed = [entry for key in ("included_objects",) for entry in scope.get(key) or []]
    for group in (old.get("core_objects") or {}).values() if isinstance(old.get("core_objects"), dict) else []:
        listed += list(group or [])
    known_ids = {row["id"] for row in rows} | set(member_of)
    report["listed_not_indexed"] = sorted({entry for entry in listed if isinstance(entry, str) and entry not in known_ids})

    sources = [{"repo": main_repo, "branch": branch, "commit": commit or "unknown"}] if main_repo else []
    sources += [{"repo": name, "branch": "main", "commit": "unknown"} for name in sorted(repos) if name != main_repo]
    if any(item["commit"] == "unknown" for item in sources):
        report["notes"].append("a source has no known commit: write it into domain.yaml sources, then stamp the shas again")
    boundaries = [{"name": str(name), "note": ""} for name in scope.get("traversal_boundaries") or []]
    if meta.get("source_assumption") or index_meta.get("sourceAssumption"):
        boundaries.insert(0, {"name": "source-assumption", "note": str(meta.get("source_assumption") or index_meta.get("sourceAssumption"))})
    files = {}
    for name, relative in (old.get("knowledge_files") or {}).items() if isinstance(old.get("knowledge_files"), dict) else []:
        if isinstance(relative, str) and not relative.startswith("objects/") and (target / relative).exists():
            files[str(name)] = relative
    files.setdefault("architecture", "architecture.md")
    if (target / "environment.md").exists() or old.get("environment_validation") or old.get("servers") or old.get("databases"):
        files["environment"] = "environment.md"
    entry_points = [str(entry.get("object_id")) for entry in old.get("entry_points") or [] if isinstance(entry, dict) and entry.get("object_id")]
    report["notes"] += [f"entry point {entry} is not in the index" for entry in entry_points if entry not in known_ids]
    domain = {
        "schema_version": kbstd.SCHEMA_VERSION,
        "domain": target.name,
        "description": str(scope.get("description") or meta.get("description") or ""),
        "updated": str(meta.get("version_date") or index_meta.get("lastUpdated") or ""),
        "generated_by": f"{meta.get('generated_by_skill') or 'unknown'}; migrated to v1 by harness {harness_version(root)}",
        "sources": sources,
        "entry_points": [entry for entry in entry_points if entry in known_ids],
        "boundaries": boundaries,
        "excluded": [{"name": str(name), "note": ""} for name in scope.get("excluded_objects") or []],
        "systems": [{"name": item.get("name"), "type": item.get("type", ""), "role": item.get("role", ""), "level": level(item.get("status"), "unknown")} for item in old.get("systems") or [] if isinstance(item, dict)],
        "files": files,
        "open_questions": [{"id": str(item.get("id")), "level": "conflict" if level(item.get("status"), "unknown") == "conflict" else "unknown", "note": str(item.get("description") or "")} for item in old.get("unresolved_items") or [] if isinstance(item, dict)],
    }
    report["dropped_keys"] = sorted(key for key in old if key not in MAPPED)
    (target / kbstd.DOMAIN_FILE).write_text(miniyaml.dumps(domain), encoding="utf-8")
    (target / "objects").mkdir(exist_ok=True)
    (target / kbstd.INDEX_FILE).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    old_copy = target / OLD_INDEX
    if old_copy.exists():
        old_copy.unlink()
    write_environment(target, old)
    checked = kbstd.check_domain(root, target)
    return {
        "domain": target.name, "objects": len(rows), "families": len(families), "report": {key: value for key, value in report.items() if value},
        "check": {"errors": checked["errors"], "warnings": checked["warnings"]},
    }


def write_environment(target: Path, old: Dict[str, Any]) -> None:
    """What v0 said of environments, servers and databases. Only results a person gives may raise a level here."""
    path = target / "environment.md"
    if path.exists():
        return
    lines = ["# Environment", "", "Facts about the environments. Code is evidence for DEV only; fill the others only from results a person gave, cleaned.", ""]
    lines += ["| Environment | State |", "| --- | --- |"]
    for name, state in (old.get("environment_validation") or {}).items() if isinstance(old.get("environment_validation"), dict) else []:
        lines.append(f"| {name} | {state} |")
    for title, key, fields in (("Servers", "servers", ("name", "environment", "status")), ("Databases", "databases", ("name", "server", "role", "status")), ("Sources", "sources", ("name", "type", "status"))):
        items = [item for item in old.get(key) or [] if isinstance(item, dict)]
        if items:
            lines += ["", f"## {title}", "", "| " + " | ".join(fields) + " |", "|" + " --- |" * len(fields)]
            lines += ["| " + " | ".join(str(item.get(field, "")) for field in fields) + " |" for item in items]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_path(root: Path, folder: Optional[Path]) -> Dict[str, Any]:
    """`kb check --path`: one domain folder anywhere (a migration in a task's DEV/)."""
    result = kbstd.check_domain(root, folder.resolve()) if folder else {}
    result["exit_code"] = 1 if result.get("errors") else 0
    return result


def stamp(root: Path, folder: Path, ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """`kb stamp`: after the cards were checked against the code, set the `sha` of their sources to the base branch now,
    so that `kb stale` counts from here. Only in a task's `DEV/`; only the objects named, or all of them."""
    folder = folder.resolve()
    if not inside_dev(root, folder):
        raise MigrateError(kbstd.say("kb.stamp.not_dev", folder=folder))
    index = folder / kbstd.INDEX_FILE
    if not index.is_file():
        raise MigrateError(kbstd.say("kb.index.missing", file=index))
    rows, bad = kbstd.read_index(index)
    if bad:
        raise MigrateError(" ".join(bad))
    known = {row.get("id") for row in rows}
    unknown = sorted(set(ids or []) - known)
    if unknown:
        raise MigrateError(kbstd.say("kb.stamp.unknown_ids", ids=", ".join(unknown)))
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
            raise MigrateError(str(error)) from None
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
        "next": kbstd.say("kb.stamp.next" if stamped else "kb.stamp.nothing"),
    }
