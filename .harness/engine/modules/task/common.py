"""What the task commands share: the refusal a command raises, clean paths, file copies, the target repositories.

A refusal raises CommandError with the reason and the next step. Files are copied, never retyped.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
import shutil
import stat
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config, repo_paths, targets, tasks
from core.logs import read_lines, read_session, session_files

from .policy import POLICY_NAME


class CommandError(Exception):
    """A refused command. The message says why and what to do next."""


def relative_name(raw: str, what: str = "路径") -> str:
    """A clean relative path inside a folder: no drive, no `..`, no leading slash. Returns it with `/`."""
    text = raw.strip().replace("\\", "/")
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise CommandError(f"{what} `{raw}` 必须是相对路径。")
    clean = posixpath.normpath(text)
    if clean == "." or clean == ".." or clean.startswith("../"):
        raise CommandError(f"{what} `{raw}` 不能指向目录之外。")
    return clean


def inside(root: Path, path: Path) -> Optional[str]:
    """`path` relative to `root` with `/`, after resolving links, or None when it is outside."""
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return relative.as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


SKIP_NAMES = {".git", "__pycache__", "node_modules", ".DS_Store"}


def policy(root: Path) -> Dict[str, Any]:
    from .policy import validate_policy

    value = config.load_policy(root, POLICY_NAME)
    validate_policy(value)
    return value


def writable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | stat.S_IWUSR)
    except OSError:
        pass


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        writable(path)
    path.write_text(text, encoding="utf-8")


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        writable(destination)
    shutil.copyfile(str(source), str(destination))


def load_targets(root: Path) -> targets.Targets:
    try:
        return targets.load(root)
    except Exception as error:
        raise CommandError(f"目标仓库的配置有问题（target.json 或 target.override.json）：{error}") from error


def target_repo(found: targets.Targets, name: str) -> targets.Repo:
    try:
        return found.get(name)
    except targets.TargetError as error:
        raise CommandError(str(error)) from error


def clean_branch(branch: str) -> str:
    name = branch.strip()
    if name and not targets.valid_branch(name):
        raise CommandError(f"分支名 `{name}` 不合法。写成 `feature/<名字>`，名字只能用字母、数字和下划线，不能有 `-`、`.`、`/`。")
    return name


def clean_task(root: Path, raw: str) -> str:
    """A task folder under one of the task directories, as a path relative to the repository. Empty when none is given."""
    text = raw.strip()
    if not text:
        return ""
    path = Path(text)
    path = path if path.is_absolute() else root / path
    relative = inside(root, path)
    if relative is None or not relative.startswith(tasks.TASKS_DIR + "/"):
        raise CommandError(f"--task `{raw}` 要是 {tasks.TASKS_DIR}/ 下的一个任务目录，例如 {tasks.TASKS_DIR}/<任务名>。")
    relative = relative.rstrip("/")
    if not path.is_dir():
        raise CommandError(f"任务目录 `{relative}` 不存在。")
    return relative


def copy_from_target(
    root: Path, data: Dict[str, Any], specs: List[str], target: Path, limit: int, purpose: str
) -> List[Dict[str, str]]:
    """Files of target repositories as `base_ref` has them (the commit is fixed at the first read), not the working tree.

    A spec is `<repo>/<path>`: a file, or a folder (every tracked file under it). Records the repositories and the blob
    of each file in `data`, so promote can tell later whether main moved under the files it is about to write.
    """
    if not specs:
        return []
    found = load_targets(root)
    if not found.configured:
        raise CommandError("还没有配置目标仓库。在 .harness/policies/target.override.json 里写 repos_root，运行 `target list` 确认。")
    records = data.setdefault("targets", {})
    files = data.setdefault("target_files", {})
    wanted: Dict[str, Any] = {}
    for spec in specs:
        name, _, rest = spec.strip().replace("\\", "/").partition("/")
        if not name or not rest.strip("/"):
            raise CommandError(f"`{spec}` 要写成 `<仓库名>/<仓库里的路径>`，例如 bdtt_repo/src/a.sql。")
        repo = target_repo(found, name)
        relative = relative_name(rest, "仓库里的路径")
        if name not in records:
            try:
                commit = targets.ref_commit(repo, found.timeout)
            except targets.TargetError as error:
                raise CommandError(str(error)) from error
            if not commit:
                raise CommandError(f"仓库 {name} 本地没有分支 `{repo.base_ref}`。先在那个仓库里准备好它，运行 `doctor` 确认。")
            records[name] = {"path": str(repo.path), "base_ref": repo.base_ref, "base_commit": commit}
        commit = records[name]["base_commit"]
        try:
            listed = targets.tracked_files(repo, commit, relative, found.timeout)
        except targets.TargetError as error:
            raise CommandError(str(error)) from error
        if not listed:
            raise CommandError(f"仓库 {name} 的 {repo.base_ref}（{commit[:12]}）上没有 `{relative}`。要新建的文件不用取，直接在 DEV/ 下创建。")
        for mode, blob, path in listed:
            if mode not in targets.REGULAR_FILE_MODES:
                if path == relative:
                    raise CommandError(f"`{name}/{path}` 不是普通文件（符号链接或子模块），不能复制。")
                continue
            wanted[f"{name}/{path}"] = (repo, commit, blob, path)
    if len(wanted) > limit:
        raise CommandError(f"一次复制了 {len(wanted)} 个文件，上限 {limit}。只复制这个任务要用的文件。")
    entries = []
    for key, (repo, commit, blob, path) in sorted(wanted.items()):
        try:
            content = targets.read_blob(repo, blob, found.timeout)
        except targets.TargetError as error:
            raise CommandError(str(error)) from error
        destination = target / repo.name / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            writable(destination)
        destination.write_bytes(content)
        entries.append({
            "path": destination.relative_to(target.parent).as_posix(),
            "source": key,
            "purpose": purpose,
            "sha256": sha256_file(destination),
            "repo": repo.name,
            "blob": blob,
            "base_commit": commit,
        })
        files[key] = {"blob": blob, "base_commit": commit}
    return entries


def check_target_output(found: targets.Targets, name: str, label: str = "--output") -> None:
    """Every result path is `<repo>/<path in the repo>`, and not a path promote refuses."""
    repo_name, _, rest = name.partition("/")
    if repo_name not in found.repos or not rest:
        known = "、".join(found.names()) or "（没有）"
        raise CommandError(f"{label} `{name}` 的第一段要是仓库名，后面是仓库里的路径，例如 bdtt_repo/src/a.sql。已知的仓库：{known}。")
    for pattern in found.repos[repo_name].refused_paths:
        if repo_paths.glob_regex(pattern).match(rest):
            raise CommandError(f"{label} `{name}` 属于不能回写的路径（{repo_name} 的 {pattern}）。把它从成果里去掉。")


def shown(result: Dict[str, Any]) -> Dict[str, Any]:
    """The plan as the CLI prints it, for the agent: each file once, with its line counts but without the diff.

    The person sees the diff on the approval screen (`approve-promote`) and in the backup patch; a copy here only costs the agent tokens.
    The per-repository copies in `repos` are for the run.
    """
    out = dict(result)
    if "files" in out:
        out["files"] = [{key: value for key, value in item.items() if key not in ("diff", "source")} for item in out["files"]]
    if "repos" in out:
        out["repos"] = [{key: value for key, value in repo.items() if key != "files"} for repo in out["repos"]]
    return out


REPORTS_DIR = ".workspace/reports"
TASK_REPORTS_DIR = REPORTS_DIR + "/tasks"  # one folder per task: report.md and report.html
REPORT_MD = "report.md"
REPORT_HTML = "report.html"
REPLACE_TRIES = 10
REPLACE_WAIT = 0.05


def task_report_file(root: Path, name: str, file_name: str) -> Path:
    """Where a report of the task `name` goes. The file of before (reports/task-<name>.*, all tasks in one folder) is removed."""
    old = root / REPORTS_DIR / f"task-{name}{Path(file_name).suffix}"
    try:
        if old.is_file():
            writable(old)
            old.unlink()
    except OSError:
        pass
    return root / TASK_REPORTS_DIR / name / file_name


def replace_text(path: Path, text: str) -> None:
    """Write over the file in one step: a browser that loads the page again never gets half of it.

    On Windows the step is refused while another program reads the file, so it is tried a few times. When it is still
    refused, the file of before stays as it is and the OSError goes to the caller.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    half = path.with_name(path.name + ".tmp")
    half.write_text(text, encoding="utf-8")
    for left in range(REPLACE_TRIES - 1, -1, -1):
        try:
            os.replace(half, path)
            return
        except OSError:
            if not left:
                try:
                    half.unlink()
                except OSError:
                    pass
                raise
            time.sleep(REPLACE_WAIT)


LOG_ROWS = 40


REASON_CHARS = 100


def cut(text: str, limit: int) -> str:
    one_line = " ".join(str(text).split())
    return one_line if len(one_line) <= limit else one_line[:limit] + "…"


def cell(text: str) -> str:
    return cut(text, REASON_CHARS).replace("|", "\\|")


def child_sessions(root: Path, surface: str, session_id: str, since: str) -> List[Dict[str, Any]]:
    """SDK engine: a subagent runs in a session of its own. Those logs name the session that called them."""
    found: List[Dict[str, Any]] = []
    for found_surface, path in session_files(root):
        if found_surface != surface or path.stem == session_id:
            continue
        rows = read_lines(path)
        if rows and rows[0].get("parent_session_id") == session_id and rows[-1].get("at", "") >= since:
            found.append({"session_id": path.stem, "rows": rows})
    return found


def log_section(root: Path, data: Dict[str, Any]) -> List[str]:
    session_id, surface = data.get("session_id", ""), data.get("surface", "vscode")
    rows = read_session(root, surface, session_id)
    lines = ["", "## hook 日志（会话 " + session_id + "）", ""]
    if not rows:
        return lines + ["没有找到这个会话的日志（observe 没开，或日志已被 `logs prune` 清理）。"]
    children = child_sessions(root, surface, session_id, data["created_at"])
    every = rows + [row for child in children for row in child["rows"]]
    since = data["created_at"]
    window = [row for row in every if row.get("at", "") >= since]
    counted = {
        "hook 调用": len(window),
        "拒绝（deny）": sum(1 for row in window if row.get("decision") == "deny"),
        "要人确认（ask）": sum(1 for row in window if row.get("decision") == "ask"),
        "Stop 被拦": sum(1 for row in window if row.get("decision") == "block"),
        "子 agent 启动": sum(1 for row in window if row.get("event") == "SubagentStart"),
    }
    lines.append("任务开始之后：" + "，".join(f"{name} {number}" for name, number in counted.items()) + "。")
    if children:
        lines.append(f"子 agent 另有 {len(children)} 个会话（SDK 引擎），已一起统计。")
    refusals = [row for row in window if row.get("decision") in ("deny", "ask", "block")]
    if not refusals:
        return lines + ["", "没有拒绝和确认记录。"]
    lines += ["", "拒绝和确认记录（时间是 UTC）：", "", "| 时间 | 事件 | 工具 | 决定 | 谁 | 原因 | 对象 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in refusals[:LOG_ROWS]:
        target = row.get("target") or {}
        about = "、".join(target.get("paths", [])) or target.get("command", "")
        lines.append(
            f"| {row.get('at', '')[11:19]} | {row.get('event', '')} | {row.get('tool_name', '') or '-'} | {row.get('decision', '')}"
            f" | {row.get('judge', '')}:{','.join(row.get('by') or [])} | {cell(row.get('reason', ''))} | {cell(about) or '-'} |"
        )
    if len(refusals) > LOG_ROWS:
        lines.append(f"\n（还有 {len(refusals) - LOG_ROWS} 条，见会话日志。）")
    return lines
