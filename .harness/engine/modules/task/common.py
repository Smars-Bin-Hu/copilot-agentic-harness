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

from core import config, messages, repo_paths, targets, tasks
from core.logs import read_lines, read_session, session_files

from .policy import POLICY_NAME


class CommandError(Exception):
    """A refused command. The message says why and what to do next."""


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def relative_name(raw: str, what: str = "") -> str:
    """A clean relative path inside a folder: no drive, no `..`, no leading slash. Returns it with `/`.

    `what`: the name of a message that says what the path is (`path.what` when empty).
    """
    what = say(what or "path.what")
    text = raw.strip().replace("\\", "/")
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise CommandError(say("path.relative", what=what, raw=raw))
    clean = posixpath.normpath(text)
    if clean == "." or clean == ".." or clean.startswith("../"):
        raise CommandError(say("path.outside", what=what, raw=raw))
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


SKIP_NAMES = {".git", "__pycache__", "node_modules", ".DS_Store", "Thumbs.db", "desktop.ini"}  # the tools and the file manager make these; not work, not results


def is_promote_backup(parts: List[str]) -> bool:
    """`parts`: a path inside DEV/. What promote writes there itself, `_deleted/` and `*.patch` at the top of DEV/, is not a result: it is not written to the
    repository, and it must not change what a check looked at (one list for promote and for the checks: task.dev_files and tasksnap.is_result)."""
    return bool(parts) and (parts[0] == "_deleted" or (len(parts) == 1 and parts[0].endswith(".patch")))


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
        raise CommandError(say("target.config.bad", error=error)) from error


def target_repo(found: targets.Targets, name: str) -> targets.Repo:
    try:
        return found.get(name)
    except targets.TargetError as error:
        raise CommandError(str(error)) from error


def clean_branch(branch: str) -> str:
    name = branch.strip()
    if name and not targets.valid_branch(name):
        raise CommandError(say("branch.bad", name=name))
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
        raise CommandError(say("task.option.bad", raw=raw, tasks_dir=tasks.TASKS_DIR))
    relative = relative.rstrip("/")
    if not path.is_dir():
        raise CommandError(say("task.folder.missing", relative=relative))
    return relative


def changed_lines(diff: List[str]) -> Tuple[int, int]:
    """(added, removed) of a unified diff given as lines. The first two lines are the file headers (`---`, `+++`); every other line that starts with `+` or `-`
    is a changed line, also a removed SQL comment (`-` + `-- layer`, which starts with `---`): it was counted as a header and left out (B66)."""
    body = diff[2:] if len(diff) >= 2 and diff[0].startswith("---") and diff[1].startswith("+++") else diff
    return sum(1 for line in body if line.startswith("+")), sum(1 for line in body if line.startswith("-"))


def copy_from_target(
    root: Path, data: Dict[str, Any], specs: List[str], target: Path, limit: int, purpose: str, notes: Optional[List[str]] = None, rebase: bool = False
) -> List[Dict[str, str]]:
    """Files of target repositories as `base_ref` has them (the commit is fixed at the first read), not the working tree.
    `rebase`: the commit is fixed again, at what `base_ref` is now (after it was brought up to its remote): the way to take a file that changed on main since.

    A spec is `<repo>/<path>`: a file, or a folder (every tracked file under it). Records the repositories and the blob
    of each file in `data`, so promote can tell later whether main moved under the files it is about to write.
    """
    if not specs:
        return []
    found = load_targets(root)
    if not found.configured:
        raise CommandError(say("target.unset"))
    records = data.setdefault("targets", {})
    files = data.setdefault("target_files", {})
    wanted: Dict[str, Any] = {}
    pinned = set()  # repositories whose commit was fixed in this call
    for spec in specs:
        name, _, rest = spec.strip().replace("\\", "/").partition("/")
        if not name or not rest.strip("/"):
            raise CommandError(say("fetch.spec", spec=spec))
        repo = target_repo(found, name)
        relative = relative_name(rest, "path.what.in_repo")
        if name not in records or (rebase and name not in pinned):
            try:
                if notes is not None:  # the first read of this repository in the round: its base branch is brought up to the remote first
                    from . import basesync  # it needs this module

                    basesync.sync_all([repo], found.timeout, notes)
                commit = targets.ref_commit(repo, found.timeout)
            except targets.TargetError as error:
                raise CommandError(str(error)) from error
            if not commit:
                raise CommandError(say("fetch.no_branch", name=name, base_ref=repo.base_ref))
            records[name] = {"path": str(repo.path), "base_ref": repo.base_ref, "base_commit": commit}
            pinned.add(name)
        commit = records[name]["base_commit"]
        try:
            listed = targets.tracked_files(repo, commit, relative, found.timeout)
        except targets.TargetError as error:
            raise CommandError(str(error)) from error
        if not listed:
            raise CommandError(say("fetch.no_file", name=name, base_ref=repo.base_ref, commit=commit[:12], relative=relative))
        for mode, blob, path in listed:
            if mode not in targets.REGULAR_FILE_MODES:
                if path == relative:
                    raise CommandError(say("fetch.not_file", name=name, path=path))
                continue
            wanted[f"{name}/{path}"] = (repo, commit, blob, path)
    if len(wanted) > limit:
        raise CommandError(say("fetch.too_many", count=len(wanted), limit=limit))
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
        known = messages.joined(found.names()) or say("output.none_known")
        raise CommandError(say("output.repo_first", label=label, name=name, known=known))
    for pattern in found.repos[repo_name].refused_paths:
        if repo_paths.glob_regex(pattern).match(rest):
            raise CommandError(say("output.refused", label=label, name=name, repo=repo_name, pattern=pattern))


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
    lines = ["", say("log.section.title", session_id=session_id), ""]
    if not rows:
        return lines + [say("log.section.none")]
    children = child_sessions(root, surface, session_id, data["created_at"])
    every = rows + [row for child in children for row in child["rows"]]
    since = data["created_at"]
    window = [row for row in every if row.get("at", "") >= since]
    counted = {
        "calls": len(window),
        "deny": sum(1 for row in window if row.get("decision") == "deny"),
        "ask": sum(1 for row in window if row.get("decision") == "ask"),
        "block": sum(1 for row in window if row.get("decision") == "block"),
        "subagent": sum(1 for row in window if row.get("event") == "SubagentStart"),
    }
    items = [say("log.count.item", name=say(f"log.count.{name}"), number=number) for name, number in counted.items()]
    lines.append(say("log.count.line", counts=say("list.comma.wide").join(items)))
    if children:
        lines.append(say("log.children", count=len(children)))
    refusals = [row for row in window if row.get("decision") in ("deny", "ask", "block")]
    if not refusals:
        return lines + ["", say("log.refusals.none")]
    lines += ["", say("log.refusals.title"), "", say("log.refusals.header"), "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in refusals[:LOG_ROWS]:
        target = row.get("target") or {}
        about = messages.joined(target.get("paths", [])) or target.get("command", "")
        lines.append(
            f"| {row.get('at', '')[11:19]} | {row.get('event', '')} | {row.get('tool_name', '') or '-'} | {row.get('decision', '')}"
            f" | {row.get('judge', '')}:{','.join(row.get('by') or [])} | {cell(row.get('reason', ''))} | {cell(about) or '-'} |"
        )
    if len(refusals) > LOG_ROWS:
        lines.append(say("log.refusals.more", count=len(refusals) - LOG_ROWS))
    return lines
