"""The promote queue (M12-2): several tasks, one branch each, written into the same repositories one after the other.

promote wants a clean working tree. After a task is written onto its branch the files wait for the person's commit, so
the next task that wants the same repository is stopped. This module says who holds a repository and who waits:

  task queue      per repository: its branch, whether it is clean, the task whose files wait for a commit, the tasks in line
  holder_text     the sentence promote adds to "the working tree is not clean": whose branch it is and what to do

Nothing here writes, and nothing commits for the person. `task list` carries the order only (from the task files, no git).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from core import targets, tasks
from core.paths import cli_command

from . import common

READY, ASKED, WORKING = "approved", "dry_run", "working"  # the plan is approved; it waits for the approval; it has results, no plan yet
ORDER = {READY: 0, ASKED: 1, WORKING: 2}
FILES_SHOWN = 5


def name_of(task: str) -> str:
    return task.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def every_task(root: Path) -> List[Dict[str, Any]]:
    found = []
    for task in tasks.folders(root):
        try:
            data = tasks.read(root, task)
        except Exception:  # noqa: BLE001 - one broken task file must not take the queue away
            data = None
        if data is not None:
            found.append(data)
    return found


def repos_of(root: Path, data: Dict[str, Any], known: List[str]) -> List[str]:
    """The target repositories a task has results for: the folders under DEV/, and what it took or will delete."""
    names = set()
    dev = tasks.dev_dir(root, data["task"])
    try:
        for child in dev.iterdir():
            if child.is_dir() and child.name in known and any(item.is_file() for item in child.rglob("*")):
                names.add(child.name)
    except OSError:
        pass
    for key in list(data.get("deletes") or []):
        first = str(key).split("/", 1)[0]
        if first in known:
            names.add(first)
    return sorted(names)


def stage(root: Path, data: Dict[str, Any]) -> str:
    """Where an open task stands on the way to a promote, or "" when it is not in line (done, broken, or nothing to write)."""
    promote = data.get("promote") or {}
    state = promote.get("state", "none")
    if data.get("status") != "open" or state in ("done", "partial"):
        return ""
    if state == "dry_run":
        return READY if promote.get("approved_plan_sha256") == promote.get("plan_sha256") else ASKED
    return WORKING


def moment(data: Dict[str, Any], where: str) -> str:
    promote = data.get("promote") or {}
    if where == READY:
        return str(promote.get("approved_at") or promote.get("at") or "")
    if where == ASKED:
        return str(promote.get("at") or "")
    return str(data.get("updated_at") or "")


def waiting(root: Path, known: List[str], everything: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """The tasks in line, in order: approved first (oldest approval first), then the ones that wait for the approval, then the ones still worked on."""
    rows = []
    for data in everything if everything is not None else every_task(root):
        where = stage(root, data)
        if not where:
            continue
        repos = repos_of(root, data, known)
        if not repos:
            continue
        rows.append({"task": data["task"], "name": data.get("name") or name_of(data["task"]), "stage": where, "since": moment(data, where), "branch": data.get("branch", ""), "repos": repos})
    rows.sort(key=lambda row: (ORDER[row["stage"]], row["since"], row["name"]))
    return rows


def holders(everything: List[Dict[str, Any]], repo: str, branch: str) -> List[Dict[str, Any]]:
    """The tasks whose promote wrote `repo` onto `branch` (newest first). Closed tasks count: their files may still wait for a commit."""
    found = []
    for data in everything:
        promote = data.get("promote") or {}
        if promote.get("state") == "done" and promote.get("branch") == branch and repo in (promote.get("repos") or {}) and not (promote["repos"][repo] or {}).get("commit"):
            found.append({"task": data["task"], "name": data.get("name") or name_of(data["task"]), "branch": branch, "at": str(promote.get("at") or ""), "status": data.get("status", "")})
    found.sort(key=lambda item: item["at"], reverse=True)
    return found


def holder_text(root: Path, repo: targets.Repo, current: str) -> str:
    """Added to "the working tree is not clean": whose files these are and what the person does next. "" when no task is known for the branch."""
    try:
        found = holders(every_task(root), repo.name, current)
    except Exception:  # noqa: BLE001 - a hint; the refusal itself stands without it
        return ""
    if not found:
        return ""
    first = found[0]
    return (
        f"仓库现在在分支 `{current}` 上：这是任务 {first['name']} 回写的，文件还没提交。"
        f"请用户在这个仓库里检查并提交（`git add`、`git commit`），或确认不要了再丢弃；然后重新 --dry-run。"
        f"排队情况：`{cli_command()} task queue`。"
    )


def order(root: Path) -> List[Dict[str, Any]]:
    """For `task list`: the tasks in line and what they wait for. From the task files only, no git."""
    try:
        known = sorted(common.load_targets(root).repos)
    except Exception:  # noqa: BLE001 - a list must not fail over the target settings
        return []
    if not known:
        return []
    return [{"name": row["name"], "stage": row["stage"], "repos": row["repos"]} for row in waiting(root, known)]


def queue(root: Path) -> Dict[str, Any]:
    """Per repository: its state, who holds it, who is in line. Reads git (status, current branch) of each repository that a task wants."""
    found = common.load_targets(root)
    everything = every_task(root)
    line = waiting(root, sorted(found.repos), everything)
    wanted = sorted({name for row in line for name in row["repos"]})
    repos = []
    for name in wanted:
        repo = found.repos[name]
        entry: Dict[str, Any] = {"name": name, "path": str(repo.path), "base_ref": repo.base_ref, "knowledge_base": repo.knowledge_base}
        try:
            dirty = targets.dirty_paths(repo, found.timeout)
            current = targets.current_branch(repo, found.timeout)
        except targets.TargetError as error:
            entry.update(problem=str(error), waiting=[row["name"] for row in line if name in row["repos"]])
            repos.append(entry)
            continue
        held = holders(everything, name, current) if dirty else []
        entry.update(
            current_branch=current, clean=not dirty, uncommitted_files=len(dirty), uncommitted=dirty[:FILES_SHOWN],
            held_by=held[0]["name"] if held else "",
            waiting=[{"name": row["name"], "stage": row["stage"], "branch": row["branch"]} for row in line if name in row["repos"]],
        )
        entry["next"] = next_step(entry)
        repos.append(entry)
    return {
        "repos": repos, "tasks": [{key: row[key] for key in ("name", "stage", "branch", "repos", "since")} for row in line],
        "note": "一个任务一个分支，按顺序回写。harness 不替你提交：上一个任务的文件提交了，下一个才能写进同一个仓库。",
    }


def next_step(entry: Dict[str, Any]) -> str:
    first = entry["waiting"][0] if entry["waiting"] else None
    if not entry["clean"]:
        if entry["held_by"]:
            return f"仓库在分支 {entry['current_branch']} 上，是任务 {entry['held_by']} 回写的，有 {entry['uncommitted_files']} 个文件没提交。你在仓库里检查并提交，排队的任务才能回写。"
        return f"仓库有 {entry['uncommitted_files']} 个没提交的文件，不是 harness 的任务回写的。你先提交、stash 或丢弃。"
    if first is None:
        return ""
    if first["stage"] == READY:
        return f"仓库是干净的。任务 {first['name']} 已批准，告诉它的 agent 运行 task promote。"
    if first["stage"] == ASKED:
        return f"仓库是干净的。任务 {first['name']} 的回写计划等你批准：`{cli_command()} task approve-promote --task {first['name']}`。"
    return f"仓库是干净的。任务 {first['name']} 还在做，没有回写计划。"
