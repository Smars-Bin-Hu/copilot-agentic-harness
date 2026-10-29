"""Snapshots of a task at its gates (M11-10): what the results were when the plan was approved, before each check,
before a promote dry-run.

A snapshot is a copy of the task's result files under `SNAPSHOT/<gate>-<time>/`, with a manifest of their sha256.
What changes between two gates is not kept. The one made before a check is also what the reviewer was given.
Only the CLI writes here (gate.json: cli_owned_paths). Old snapshots are removed when a new one is made.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core import config, tasks
from core.paths import utc_now

from . import commitmsg, common
from .policy import POLICY_NAME

SNAPSHOT_DIR = "SNAPSHOT"
REVIEW_DIR = "REVIEW"
MANIFEST = "manifest.json"
DEFAULTS = {"keep_days": 14, "max_file_mb": 5}
# Not results: the CLI's own files, the person's material, the files that only say where the work stands.
# COMMIT-MESSAGE.md is written after the checks, for the person's commit: a check of it would undo the passes (1.5.34).
SKIP_TOP = (tasks.STATE_DIR, *tasks.PERSON_DIRS, SNAPSHOT_DIR.lower(), REVIEW_DIR.lower(), "_deleted")
SKIP_FILES = (tasks.TASK_FILE.lower(), tasks.TODO_FILE.lower(), tasks.LOG_FILE.lower(), tasks.CHANGES_NAME.lower(), tasks.REVIEW_NAME.lower(), commitmsg.FILE.lower())


def settings(root: Path) -> Dict[str, Any]:
    """`snapshots` of task.json. A missing or broken policy gives the defaults: a snapshot must not stop a gate."""
    try:
        found = config.load_policy(root, POLICY_NAME).get("snapshots") or {}
    except Exception:  # noqa: BLE001
        found = {}
    return {key: found.get(key, value) if isinstance(found.get(key, value), (int, float)) and not isinstance(found.get(key, value), bool) else value for key, value in DEFAULTS.items()}


def is_result(relative: str) -> bool:
    """`relative` is a path inside the task folder. Earlier rounds (`DEV_r1/`, `PLAN_r1.md`) are not this round's result, nor is what promote writes
    into DEV/ itself (the patch and the backups of deleted files), nor what a tool or a file manager makes (`.DS_Store`, `Thumbs.db`)."""
    parts = relative.split("/")
    top = parts[0].lower()
    if any(part in common.SKIP_NAMES for part in parts) or (top == tasks.DEV_NAME.lower() and common.is_promote_backup(parts[1:])):
        return False
    if top in SKIP_TOP or top.startswith("dev_r") or (len(parts) == 1 and (top in SKIP_FILES or top.startswith(("plan_r", "changes_r")))):
        return False
    return True


def result_files(root: Path, task: str) -> List[Tuple[str, Path]]:
    """Every result file of the task, as (path inside the task, file), sorted."""
    folder = tasks.task_dir(root, task)
    found = []
    for path in sorted(folder.rglob("*")) if folder.is_dir() else []:
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(folder).as_posix()
        if is_result(relative):
            found.append((relative, path))
    return found


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def listing(root: Path, task: str) -> List[Dict[str, Any]]:
    return [{"path": relative, "sha256": file_digest(path), "bytes": path.stat().st_size} for relative, path in result_files(root, task)]


def digest_of(files: List[Dict[str, Any]]) -> str:
    """One sha256 for the whole result: it changes when any result file is added, removed or changed."""
    if not files:
        return ""
    text = "\n".join(f"{item['path']}\t{item['sha256']}" for item in files)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def results_digest(root: Path, task: str) -> str:
    return digest_of(listing(root, task))


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def take(root: Path, task: str, gate: str) -> Dict[str, Any]:
    """Copy the result files to `SNAPSHOT/<gate>-<time>/`. A file over the size limit is listed, not copied."""
    limits = settings(root)
    files = listing(root, task)
    folder = tasks.task_dir(root, task)
    name = f"{gate}-{stamp()}"
    target = folder / SNAPSHOT_DIR / name
    number = 1
    while target.exists():
        number += 1
        target = folder / SNAPSHOT_DIR / f"{name}-{number}"
    target.mkdir(parents=True)
    limit = int(limits["max_file_mb"] * 1024 * 1024)
    for item in files:
        item["copied"] = item["bytes"] <= limit
        if item["copied"]:
            copy = target / "files" / item["path"]
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(folder / item["path"]), str(copy))
    manifest = {"gate": gate, "at": utc_now(), "task": task, "digest": digest_of(files), "files": files}
    (target / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prune(root, task, limits["keep_days"], keep=target.name)
    return {"snapshot": f"{task}/{SNAPSHOT_DIR}/{target.name}", "digest": manifest["digest"], "files": files}


def snapshots(root: Path, task: str) -> List[Dict[str, Any]]:
    base = tasks.task_dir(root, task) / SNAPSHOT_DIR
    found = []
    for path in sorted(base.iterdir()) if base.is_dir() else []:
        try:
            manifest = json.loads((path / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        found.append({
            "snapshot": f"{task}/{SNAPSHOT_DIR}/{path.name}", "gate": manifest.get("gate", ""), "at": manifest.get("at", ""),
            "files": len(manifest.get("files") or []), "digest": manifest.get("digest", ""), "age_days": round((time.time() - path.stat().st_mtime) / 86400, 1),
        })
    return found


def prune(root: Path, task: str, days: float, keep: str = "", dry_run: bool = False) -> List[str]:
    """Remove snapshots older than `days`. The newest one, and `keep`, always stay."""
    base = tasks.task_dir(root, task) / SNAPSHOT_DIR
    folders = sorted((path for path in base.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime) if base.is_dir() else []
    removed = []
    for path in folders[:-1]:
        if path.name == keep or time.time() - path.stat().st_mtime <= days * 86400:
            continue
        removed.append(f"{task}/{SNAPSHOT_DIR}/{path.name}")
        if not dry_run:
            shutil.rmtree(str(path), ignore_errors=True)
    return removed
