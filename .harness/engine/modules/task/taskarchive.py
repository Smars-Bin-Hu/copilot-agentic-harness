"""`task archive`: move closed tasks out of `.workspace/sandbox/tasks/` into a folder of the person's choosing (M15-6).

  task archive                                    which tasks can be archived, and the folder last used
  task archive <name>... | --all  [--to DIR]      what would move where (nothing moves)
  task archive <name>... | --all  [--to DIR] --apply [--remember]   move them

One way only: there is no command that brings a task back. Only closed tasks move; an open one is refused, and so is
one whose promote stopped halfway or whose autorun is on. All are checked before the first one moves.

Each task folder moves whole to `DIR/<name>/`, its report folder (`.workspace/reports/tasks/<name>/`) to
`DIR/<name>/_report/`. `DIR/ARCHIVE.md` (for people) and `DIR/archive.json` (for scripts) get one entry per task.
`--remember` keeps DIR in `user.override.json` (`archive_to`), a file of this computer only, that git does not keep.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config, messages, state, tasks
from core.paths import utc_now
from core.registry import harness_version

from . import common, task as task_ops
from .common import CommandError

INDEX_MD = "ARCHIVE.md"
INDEX_JSON = "archive.json"
REPORT_FOLDER = "_report"
SETTING = "archive_to"


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def remembered(root: Path) -> str:
    try:
        value = config.load_policy(root, "user").get(SETTING, "")
    except Exception:  # noqa: BLE001 - a broken policy is doctor's to report
        return ""
    return value if isinstance(value, str) else ""


def remember(root: Path, folder: Path) -> None:
    """Keep the folder in user.override.json, next to what the person already keeps there."""
    path = root / ".harness" / "policies" / f"user{config.OVERRIDE_SUFFIX}"
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError as error:
            raise CommandError(say("archive.override_broken", file=str(path), error=error)) from None
    data[SETTING] = str(folder)
    state.atomic_write(path, data)


def closed_at(data: Dict[str, Any]) -> str:
    return next((event.get("at", "") for event in reversed(data.get("events") or []) if event.get("what") == "close"), data.get("updated_at", ""))


def why_not(data: Optional[Dict[str, Any]]) -> str:
    """Why a task cannot be archived, or an empty string."""
    if data is None:
        return say("archive.why.new")
    if data.get("status") != "closed":
        return say("archive.why.open")
    if (data.get("promote") or {}).get("state") == "partial":
        return say("archive.why.partial")
    if isinstance(data.get("autorun"), dict) and data["autorun"].get("state") == "on":
        return say("archive.why.autorun")
    return ""


def candidates(root: Path) -> List[Dict[str, Any]]:
    rows = []
    for task in tasks.folders(root):
        data = tasks.read(root, task)
        rows.append({
            "name": task_ops.name_of(task), "task": task, "kind": (data or {}).get("kind", ""), "closed_at": closed_at(data) if data else "",
            "why_not": why_not(data),
        })
    return rows


def target_folder(root: Path, raw: str) -> Path:
    value = raw or remembered(root)
    if not value:
        raise CommandError(say("archive.to.missing"))
    folder = Path(value).expanduser()
    if not folder.is_absolute():
        raise CommandError(say("archive.to.relative", to=value))
    folder = folder.resolve()
    tasks_root = (root / tasks.TASKS_DIR).resolve()
    if folder == tasks_root or tasks_root in folder.parents:
        raise CommandError(say("archive.to.inside", to=str(folder)))
    if folder.exists() and not folder.is_dir():
        raise CommandError(say("archive.to.file", to=str(folder)))
    return folder


def archive(root: Path, names: List[str], everything: bool = False, to: str = "", apply: bool = False, keep: bool = False) -> Dict[str, Any]:
    rows = candidates(root)
    if not names and not everything:
        ready = [row for row in rows if not row["why_not"]]
        return {
            "can_archive": [{"name": row["name"], "kind": row["kind"], "closed_at": row["closed_at"]} for row in ready],
            "cannot": [{"name": row["name"], "why": row["why_not"]} for row in rows if row["why_not"]],
            "archive_to": remembered(root),
            "next": say("archive.next.list" if ready else "archive.next.none"),
        }
    folder = target_folder(root, to)
    by_name = {row["name"]: row for row in rows}
    if everything:
        chosen = [row for row in rows if not row["why_not"]]
    else:
        unknown = [name for name in names if task_ops.name_of(name) not in by_name]
        if unknown:
            raise CommandError(say("archive.unknown", names=", ".join(unknown)))
        chosen = [by_name[task_ops.name_of(name)] for name in dict.fromkeys(names)]
    refused = [{"name": row["name"], "why": row["why_not"]} for row in chosen if row["why_not"]]
    taken = [row["name"] for row in chosen if (folder / row["name"]).exists()]
    if refused or taken:
        raise CommandError(say("archive.refused", refused="; ".join(f"{item['name']}: {item['why']}" for item in refused) or "-", taken=", ".join(taken) or "-", to=str(folder)))
    if not chosen:
        raise CommandError(say("archive.next.none"))
    plan = [{"name": row["name"], "from": row["task"], "to": str(folder / row["name"]), "report": (root / common.TASK_REPORTS_DIR / row["name"]).is_dir()} for row in chosen]
    if not apply:
        return {"to": str(folder), "folder_exists": folder.is_dir(), "would_move": plan, "next": say("archive.next.dry", count=len(plan))}
    known = read_index(folder)  # before anything moves: a broken index stops the run, it is never overwritten
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for row, step in zip(chosen, plan):
        data = tasks.read(root, row["task"]) or {}
        source, report = root / row["task"], root / common.TASK_REPORTS_DIR / row["name"]
        shutil.move(str(source), step["to"])
        if report.is_dir():
            shutil.move(str(report), str(Path(step["to"]) / REPORT_FOLDER))
        entry = {
            "name": row["name"], "kind": data.get("kind", ""), "tier": data.get("tier", ""), "closed_at": closed_at(data), "archived_at": utc_now(),
            "from": row["task"], "harness": harness_version(root),
        }
        entries.append(entry)
        write_index(folder, known + entries, [entry])  # after each move: a later failure leaves no task out of the index
    if keep:
        remember(root, folder)
    return {"archived": [entry["name"] for entry in entries], "to": str(folder), "remembered": keep, "next": say("archive.next.done", index=str(folder / INDEX_MD))}


def read_index(folder: Path) -> List[Dict[str, Any]]:
    """The tasks archive.json already lists. A file that is not readable stops the archive: its entries must not be lost."""
    path = folder / INDEX_JSON
    if not path.exists():
        return []
    try:
        known = json.loads(path.read_text(encoding="utf-8")).get("tasks", [])
    except (ValueError, AttributeError) as error:
        raise CommandError(say("archive.index_broken", file=str(path), error=error)) from None
    return known if isinstance(known, list) else []


def write_index(folder: Path, everything: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> None:
    """archive.json with every entry; ARCHIVE.md with the new ones added. The entries of other archive runs stay."""
    state.atomic_write(folder / INDEX_JSON, {"tasks": everything})
    page = folder / INDEX_MD
    lines = [] if page.exists() else [say("archive.index.head"), "", say("archive.index.columns"), "| --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {entry['name']} | {entry['kind']} | {entry['tier']} | {entry['closed_at'][:19].replace('T', ' ')} | {entry['archived_at'][:19].replace('T', ' ')} | {entry['from']} |" for entry in new]
    with page.open("a", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")
