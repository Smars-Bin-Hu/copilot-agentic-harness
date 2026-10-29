"""`task fork` (1.5.37): a task is done, the next one starts from what it found. RCA to development, development to test, test (with defects) to development.

The new task is made as `task new` makes it (this session picks it up), then the context of the old one is **copied** into
`REF/from-<old>/`: its conclusions and materials, never its state. Copied, not moved: the old task's report, checks and history
point at those files, and a closed task may be moved out of the repository later (`task archive`). `REF/` is reference: it is not a
result, it is not in the digest a check looks at, and it is never written back. The old task is not changed, but for a line in its history.

`FORK.md` in that folder says where it came from, what was copied, what was left and why, and how the old task stood (its write-back:
repository, branch, base commit; its checks). The new requirement is written by the agent and confirmed by the person, as for any task.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core import messages, tasks
from core.paths import utc_now

from . import task as task_ops, tasklife
from .common import CommandError

REF_DIR = "REF"
FOLDER = "from-{name}"
FORK_FILE = "FORK.md"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
# What is the old task's state, its approvals and checks, or code that belongs to it: never copied.
LEFT_FILES = {tasks.TASK_FILE: "state", tasks.TODO_FILE: "state", "PROMOTE-PLAN.diff": "write-back"}
LEFT_DIRS = {".task": "state", "DEV": "code", "SNAPSHOT": "checks", "REVIEW": "checks"}
COPIED_DIRS = ("REQ", "REF", "RUNS", "TEST")
COPIED_FILES = ("CHANGES.diff",)


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def why_left(path: Path) -> str:
    """Why a top-level entry of the old task is not copied, or "" when it is."""
    name = path.name
    if name in LEFT_FILES:
        return LEFT_FILES[name]
    if path.is_dir():
        if name in LEFT_DIRS:
            return LEFT_DIRS[name]
        if name.startswith("DEV_r"):
            return "rounds"
        return "" if name in COPIED_DIRS else "other"
    if (name.startswith("PLAN_r") and name.endswith(".md")) or (name.startswith("CHANGES_r") and name.endswith(".diff")):
        return "rounds"
    if name.endswith(".md") or name in COPIED_FILES:
        return ""
    return "other"


def plan(source: Path) -> Tuple[List[Path], List[Tuple[str, str]]]:
    """The files to copy (under the old task's folder) and what is left, `(path, why)`, in a stable order."""
    copied: List[Path] = []
    left: List[Tuple[str, str]] = []
    for entry in sorted(source.iterdir(), key=lambda item: item.name.lower()):
        if entry.is_symlink():
            left.append((entry.name, "link"))
            continue
        why = why_left(entry)
        if why:
            left.append((entry.name + ("/" if entry.is_dir() else ""), why))
        elif entry.is_dir():
            for path in sorted(entry.rglob("*")):
                if path.is_symlink():
                    left.append((path.relative_to(source).as_posix(), "link"))
                elif path.is_file() and not (entry.name == "TEST" and path.suffix.lower() != ".md"):
                    copied.append(path)
        elif entry.is_file():
            copied.append(entry)
    return copied, left


def state_lines(root: Path, task: str, data: Dict[str, Any]) -> List[str]:
    """How the old task stood: its kind and round, its write-back (where to, which branch, on which commit), its checks."""
    lines = [say("fork.md.state", kind=data.get("kind", ""), tier=data.get("tier", ""), status=data.get("status", ""), round=data.get("round", 1))]
    promote = data.get("promote") or {}
    if promote.get("state") == "done":
        for name, repo in (promote.get("repos") or {}).items():
            if isinstance(repo, dict):
                lines.append(say("fork.md.written", repo=name, branch=promote.get("branch") or data.get("branch") or "-", base=str(repo.get("base_commit") or "-")[:12],
                                 commit=str(repo["commit"])[:12] if repo.get("commit") else say("fork.md.not_committed")))
    else:
        lines.append(say("fork.md.not_written", state=promote.get("state", "none")))
    try:
        from . import taskreview  # it needs this module

        info = taskreview.summary(root, task, data, settled=True)
        if info["n"] or info["checks_used"]:
            lines.append(say("fork.md.checks", passes=info["passes"], n=info["n"], used=info["checks_used"], verdict=info["last_verdict"] or "-"))
    except Exception:  # noqa: BLE001 - the note is for reading: a check that cannot be read is left out of it
        pass
    return lines


def fork(root: Path, raw_name: str, raw_source: str, kind: str, tier: str, session_id: str, surface: str = "vscode") -> Dict[str, Any]:
    source = task_ops.resolve(root, raw_source)
    old = tasks.read(root, source)
    if not old:
        raise CommandError(say("fork.no_source", task=raw_source))
    copied, left = plan(tasks.task_dir(root, source))
    result = tasklife.new(root, raw_name, kind, tier, session_id, surface)  # fails before anything is copied when the name is taken
    task = result["task"]
    old_name = task_ops.name_of(source)
    folder = tasks.task_dir(root, task) / REF_DIR / FOLDER.format(name=old_name)
    base = tasks.task_dir(root, source)
    total, done, too_big = 0, [], []
    for path in copied:
        size = path.stat().st_size
        relative = path.relative_to(base).as_posix()
        if size > MAX_FILE_BYTES or total + size > MAX_TOTAL_BYTES:
            too_big.append(relative)
            continue
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        total += size
        done.append(relative)
    title, kinds = say("fork.md.title", old=old_name), say("fork.md.kinds", old=old.get("kind", ""), new=kind)
    heads = {"copied": say("fork.md.copied"), "left": say("fork.md.left")}
    note = [
        f"# {title}", "", say("fork.md.intro", old=source, new=task, at=utc_now()[:16].replace("T", " ")), "",
        f"- {kinds}", *[f"- {line}" for line in state_lines(root, source, old)], "",
        f"## {heads['copied']}", "", *([f"- `{item}`" for item in done] or ["- " + say("fork.md.none")]), "",
        f"## {heads['left']}", "", *[f"- `{item}`: {say('fork.why.' + why)}" for item, why in left], *[f"- `{item}`: " + say("fork.why.big") for item in too_big],
    ]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FORK_FILE).write_text("\n".join(note).rstrip() + "\n", encoding="utf-8")
    with task_ops.locked(root, task) as data:
        data["forked_from"] = source
        task_ops.note(data, "fork-from", source)
    with task_ops.locked(root, source) as data:  # the old task gets one line of history, nothing else
        task_ops.note(data, "fork", task)
    where = f"{task}/{REF_DIR}/{FOLDER.format(name=old_name)}/"
    result.update(forked_from=source, copied=done, left=[item for item, _why in left] + too_big, folder=where)
    result["next"] = say("fork.next", folder=where, file=FORK_FILE, old=source, kinds=f"{old.get('kind', '')} -> {kind}") + " " + result.get("next", "")
    return result
