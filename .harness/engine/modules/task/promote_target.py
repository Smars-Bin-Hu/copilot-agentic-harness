"""promote to target repositories: the result of a task goes onto a new branch of each repository.

The plan is checked for every repository before anything is written: a clean working tree, a branch name that is free,
and files whose version on the base branch is still the one the task fetched (new files must not exist there yet).
Only when all repositories pass does the real run start. Per repository it makes the branch from the base branch and
writes the files. It never commits, never resets, never switches back: the person reviews the files and commits them.

Before the first repository is touched, a patch of the whole result is saved next to it (`<task>/DEV/<name>.patch`).
A knowledge base (target.json: `knowledge_base: true`) is the one exception (M8-7): it has one keeper, so its files are
written straight onto the base branch and committed once, with nothing but those files in the commit. It must be on its
base branch with a clean working tree. Knowledge bases are written last, after every other repository went through.

When a step fails halfway there is no automatic undo across repositories: the run stops, the task is marked `partial`,
and the message says what is done, what is not, and the commands that put each touched repository back.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import messages, repo_paths, targets
from core.paths import cli_command, utc_now

from . import basesync, common, taskqueue


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)
from .common import CommandError

DIFF_PREVIEW_LINES = 40
ALWAYS_REFUSED = (".git/**",)
PROBLEMS_SHOWN = 6
def _lines(blob: bytes) -> int:
    try:
        return len(blob.decode("utf-8").splitlines())
    except UnicodeDecodeError:
        return 0


def _diff(old: bytes, new: bytes, name: str) -> Dict[str, Any]:
    try:
        before, after = old.decode("utf-8").splitlines(), new.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return {"added": 0, "removed": 0, "diff": [say("diff.binary")]}
    lines = list(difflib.unified_diff(before, after, f"a/{name}", f"b/{name}", lineterm="", n=1))
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    return {"added": added, "removed": removed, "diff": lines[:DIFF_PREVIEW_LINES]}


def _names_in(repo: targets.Repo, commit: str, folder: str, timeout: int) -> List[Tuple[str, str]]:
    """(type, name) of what `commit` has directly in `folder` ("" is the top)."""
    spec = [f"{folder}/"] if folder else []
    raw = targets.git(repo, "ls-tree", "-z", commit, "--", *spec, timeout=timeout).decode("utf-8", errors="replace")
    found = []
    for line in raw.split("\0"):
        if line:
            info, _, path = line.partition("\t")
            found.append((info.split(" ")[1], path.rsplit("/", 1)[-1]))
    return found


def _file_problem(
    repo: targets.Repo, commit: str, relative: str, key: str, target_files: Dict[str, Any], timeout: int, hints: Dict[str, str],
) -> Tuple[str, str, Optional[bytes]]:
    """(problem, "", None) or ("", blob of the base branch or "", its bytes). "" blob means a new file."""
    recorded = target_files.get(key)
    listed = targets.tracked_files(repo, commit, relative, timeout)
    exact = [item for item in listed if item[2] == relative]
    if listed and not exact:
        return say("promote.file.folder", key=key, base_ref=repo.base_ref), "", None
    if exact:
        mode, blob, _path = exact[0]
        if mode not in targets.REGULAR_FILE_MODES:
            return say("promote.file.not_regular", key=key, base_ref=repo.base_ref), "", None
        if recorded is None:
            return say("promote.file.not_fetched", key=key, base_ref=repo.base_ref) + hints["fetch"].format(key=key), "", None
        if recorded["blob"] != blob:
            return say("promote.file.changed", key=key, base_ref=repo.base_ref, old=recorded["blob"][:10], new=blob[:10]) + hints["refetch"], "", None
        return "", blob, targets.read_blob(repo, blob, timeout)
    if recorded is not None:
        return say("promote.file.gone", key=key, base_ref=repo.base_ref), "", None
    parts = relative.split("/")
    for index in range(1, len(parts)):  # a file (or link) where a folder is needed
        folder = "/".join(parts[: index - 1])
        names = _names_in(repo, commit, folder, timeout)
        clash = [kind for kind, name in names if name == parts[index - 1]]
        if clash and clash != ["tree"]:
            return say("promote.file.parent_file", key=key, parent="/".join(parts[:index]), base_ref=repo.base_ref), "", None
        for _kind, name in names:
            if name != parts[index - 1] and name.lower() == parts[index - 1].lower():
                return say("promote.file.parent_case", key=key, parent=parts[index - 1], base_ref=repo.base_ref, name=name), "", None
    for kind, name in _names_in(repo, commit, "/".join(parts[:-1]), timeout):  # same name in another letter case
        if name != parts[-1] and name.lower() == parts[-1].lower():
            return say("promote.file.case", key=key, base_ref=repo.base_ref, name=name), "", None
    return "", "", None


def direct_problems(repo: targets.Repo, timeout: int) -> List[str]:
    """What stops a knowledge base from being written on its base branch and committed."""
    found: List[str] = []
    current = targets.current_branch(repo, timeout)
    if current != repo.base_ref:
        found.append(say("promote.kb.branch", current=current, base_ref=repo.base_ref))
    for key in ("user.name", "user.email"):
        if not targets.git(repo, "config", "--get", key, timeout=timeout, allow_failure=True).strip():
            found.append(say("promote.kb.git_config", key=key))
    return found


def plan_digest(branch: str, repos: List[Dict[str, Any]], files: List[Dict[str, Any]]) -> str:
    # `direct` is in the code only for a knowledge base, so the code of every other plan stays what it was
    return common.sha256_text(json.dumps([
        branch, [[r["name"], r["base_commit"]] + (["direct"] if r.get("direct") else []) for r in repos], [[f["path"], f["action"], f["sha256"]] for f in files],
    ]))


def plan_files(
    root: Path, items: List[Dict[str, Any]], target_files: Dict[str, Any], branch: str, hints: Dict[str, str], notes: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Check every repository and file of a result. `items`: {key `<repo>/<path>`, source file, sha256, delete}.
    `notes` (a dry run): each base branch is first brought up to its remote (basesync), and what that did is added to it.

    Returns (repos, files) when everything passes; raises CommandError listing every problem otherwise. Nothing is written.
    """
    found = common.load_targets(root)
    problems: List[str] = []
    if not branch:
        problems.append(say("promote.branch.none") + hints["set_branch"])
    elif not targets.valid_branch(branch):
        problems.append(say("promote.branch.bad", branch=branch) + hints["set_branch"])
    by_repo: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        name, _, relative = item["key"].partition("/")
        by_repo.setdefault(name, []).append({**item, "relative": relative})
    repos: List[Dict[str, Any]] = []
    same: List[str] = []  # repositories whose files in DEV/ are all as on the base: only read, nothing to write there
    files: List[Dict[str, Any]] = []
    for name in sorted(by_repo):
        if name not in found.repos or not by_repo[name][0]["relative"]:
            problems.append(say("promote.repo.unknown", name=name, known=messages.joined(found.names()) or say("promote.repo.unknown.none")) + hints.get("stray", ""))
            continue
        repo = found.repos[name]
        timeout = found.timeout
        mine: List[str] = []
        if notes is not None:
            try:
                basesync.sync_all([repo], timeout, notes)
            except (CommandError, targets.TargetError) as error:
                problems.append(messages.text("note.detail", what=name, detail=error))
                continue
        try:
            commit = targets.ref_commit(repo, timeout)
            if not commit:
                mine.append(say("promote.repo.no_branch", base_ref=repo.base_ref))
            else:
                dirty = targets.dirty_paths(repo, timeout)
                if dirty:
                    shown = messages.joined(dirty[:PROBLEMS_SHOWN]) + (say("promote.repo.dirty.more", count=len(dirty)) if len(dirty) > PROBLEMS_SHOWN else "")
                    whose = taskqueue.holder_text(root, repo, targets.current_branch(repo, timeout))
                    mine.append(say("promote.repo.dirty", shown=shown) + (whose or say("promote.repo.dirty.fix")))
                if repo.knowledge_base:
                    mine += direct_problems(repo, timeout)
                elif branch and targets.valid_branch(branch) and targets.git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", timeout=timeout, allow_failure=True).strip():
                    mine.append(say("promote.repo.branch_exists", branch=branch) + hints["rename_branch"])
        except targets.TargetError as error:
            problems.append(messages.text("note.detail", what=name, detail=error))
            continue
        entries: List[Dict[str, Any]] = []
        for item in by_repo[name]:
            key, relative = item["key"], item["relative"]
            refused = [pattern for pattern in list(ALWAYS_REFUSED) + list(repo.refused_paths) if repo_paths.glob_regex(pattern).match(relative)]
            if refused:
                mine.append(say("promote.repo.refused", key=key, pattern=refused[0]) + hints["drop"])
                continue
            if not commit:
                continue
            try:
                problem, blob, old_bytes = _file_problem(repo, commit, relative, key, target_files, timeout, hints)
            except targets.TargetError as error:
                mine.append(str(error))
                continue
            if problem:
                mine.append(problem)
                continue
            entry: Dict[str, Any] = {"path": key, "repo": name, "relative": relative, "sha256": item["sha256"]}
            if item["delete"]:
                if old_bytes is None:
                    mine.append(say("promote.repo.delete_missing", key=key, base_ref=repo.base_ref))
                    continue
                entry.update(action="delete", base_blob=blob, **_diff(old_bytes, b"", key))
                entries.append(entry)
                continue
            new_bytes = item["source"].read_bytes()
            entry["source"] = str(item["source"])
            if old_bytes is None:
                entry.update(action="create", added=_lines(new_bytes), removed=0, diff=[])
            elif old_bytes == new_bytes:
                entry.update(action="unchanged", added=0, removed=0, diff=[])
            else:
                entry.update(action="modify", base_blob=blob, **_diff(old_bytes, new_bytes, key))
            entries.append(entry)
        if entries and all(item["action"] == "unchanged" for item in entries):
            same.append(messages.text("note.detail", what=name, detail=say("promote.repo.same", base_ref=repo.base_ref)))
            continue  # nothing is written there, so nothing about it (a dirty tree, a branch) holds the others back
        problems += [messages.text("note.detail", what=name, detail=text) for text in mine]
        if not mine:
            repos.append({
                "name": name, "path": str(repo.path), "base_ref": repo.base_ref, "base_commit": commit,
                "current_branch": targets.current_branch(repo, timeout), "files": entries, **({"direct": True} if repo.knowledge_base else {}),
            })
    repos.sort(key=lambda item: bool(item.get("direct")))  # a knowledge base is committed: it goes last, when the others are through
    for item in repos:
        files += item["files"]
    if not repos and not problems:
        problems = same  # nothing to write back anywhere
    if problems:
        raise CommandError(say("promote.blocked", problems="\n".join(f"- {text}" for text in problems)))
    return repos, files


# --- the real run ---------------------------------------------------------------------------------


def full_patch(root: Path, result: Dict[str, Any], header: str = "") -> str:
    """The whole change as one unified diff (the plan keeps only a preview). Also what a person reads before approving."""
    out: List[str] = [header or f"# branch {result['branch']}"]
    found = common.load_targets(root)
    for repo in result["repos"]:
        out.append(f"# repository {repo['name']}: {repo['base_ref']} at {repo['base_commit']}")
    for item in result["files"]:
        if item["action"] == "unchanged":
            continue
        out.append(f"diff --git a/{item['path']} b/{item['path']}")
        if item["action"] == "delete":
            out += ["deleted file", f"--- a/{item['path']}", "+++ /dev/null"]
            try:
                out += ["-" + line for line in old_content(found, item).decode("utf-8").splitlines()]
            except UnicodeDecodeError:
                out.append(say("diff.binary.content"))
            continue
        new_bytes = Path(item["source"]).read_bytes()
        if item["action"] == "create":
            out.append("--- /dev/null")
            out.append(f"+++ b/{item['path']}")
            try:
                out += ["+" + line for line in new_bytes.decode("utf-8").splitlines()]
            except UnicodeDecodeError:
                out.append(say("diff.binary.content"))
            continue
        try:
            before, after = old_content(found, item).decode("utf-8").splitlines(), new_bytes.decode("utf-8").splitlines()
            out += list(difflib.unified_diff(before, after, f"a/{item['path']}", f"b/{item['path']}", lineterm="", n=3))
        except UnicodeDecodeError:
            out.append(say("diff.binary"))
    return "\n".join(out) + "\n"


def old_content(found: targets.Targets, item: Dict[str, Any]) -> bytes:
    """The version of a modified or deleted file on the base branch, read by its blob."""
    return targets.read_blob(found.repos[item["repo"]], item["base_blob"], found.timeout)


def save_dev(root: Path, base: Path, patch_name: str, result: Dict[str, Any], header: str = "") -> Dict[str, str]:
    """Back the result up under `base` (a DEV folder) before any repository is touched. A source already there is left alone."""
    try:
        found = common.load_targets(root)
        for item in result["files"]:
            if item["action"] == "delete":  # keep the file that goes away, apart from the results
                destination = base / "_deleted" / item["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(old_content(found, item))
            elif Path(item["source"]).resolve() != (base / item["path"]).resolve():
                common.copy_file(Path(item["source"]), base / item["path"])
        patch = base / patch_name
        patch.parent.mkdir(parents=True, exist_ok=True)
        patch.write_text(full_patch(root, result, header), encoding="utf-8")
    except (OSError, targets.TargetError) as error:
        raise CommandError(say("promote.backup.failed", error=error)) from error
    return {"dev": common.inside(root, base) or str(base), "patch": common.inside(root, patch) or str(patch)}


def quote(text: str) -> str:
    return '"' + text.replace('"', '\\"') + '"'


def render(step: Dict[str, Any]) -> str:
    """A recovery step as one command line a person can paste: the paths and names in double quotes."""
    first, *rest = step["git"]
    shown = " ".join(item if item.startswith("-") else quote(item) for item in rest)
    return f"git -C {quote(step['repo'])} {first}" + (f" {shown}" if shown else "")


def recovery_steps(repo: Dict[str, Any], branch: str, switched: bool, written: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The steps that put one repository back as it was: the written files, the checkout, the branch."""
    path = repo["path"]
    steps: List[Dict[str, Any]] = []
    if repo.get("direct"):  # a knowledge base: no branch was made; `on`: the branch it must still be on
        if repo.get("commit"):
            return [{"repo": path, "git": ["revert", "--no-edit", repo["commit"]], "on": repo["base_ref"]}]
        switched = False
    modified = [item["relative"] for item in written if item["action"] in ("modify", "delete")]  # a deleted file comes back with `restore`
    created = [item["relative"] for item in written if item["action"] == "create"]
    if modified:
        steps.append({"repo": path, "git": ["restore", "--", *modified]})
    if created:
        steps.append({"repo": path, "git": ["clean", "-f", "--", *created]})
    if repo.get("direct"):
        return [dict(step, on=repo["base_ref"]) for step in steps]
    if switched:
        original = repo["current_branch"] if repo["current_branch"] != "(detached)" else repo["base_ref"]
        steps.append({"repo": path, "git": ["switch", original]})
        steps.append({"repo": path, "git": ["branch", "-d", branch]})
    return steps


def run_recovery(steps: List[Dict[str, Any]], branch: str, timeout: int) -> List[Dict[str, Any]]:
    """Run the steps of a `partial` record, repository by repository. Returns one result per step: command, status, message.

    Only a repository that is still on the promote branch gets its files restored and its checkout changed: a person who
    already switched back may have edits of their own in those files. The branch is deleted when it still exists (`-d`: git
    refuses when it holds commits that no other branch has). A step that fails ends that repository's steps, not the others.
    """
    results: List[Dict[str, Any]] = []
    by_repo: Dict[str, List[Dict[str, Any]]] = {}
    for step in steps:
        by_repo.setdefault(step["repo"], []).append(step)
    for path, own in by_repo.items():
        now_on = targets.run_step(Path(path), ["symbolic-ref", "--short", "-q", "HEAD"], timeout)[1]
        stopped = False
        for step in own:
            result = {"command": render(step), "status": "", "message": ""}
            results.append(result)
            verb = step["git"][0]
            on_branch = now_on == step.get("on", branch)
            if stopped:
                result["status"] = "skipped"
                result["message"] = say("recover.step.earlier")
                continue
            if verb in ("restore", "clean", "switch", "revert") and not on_branch:
                result["status"] = "skipped"
                result["message"] = say("recover.step.moved", branch=step.get("on", branch))
                continue
            if verb == "branch":
                exists = targets.run_step(Path(path), ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], timeout)[0] == 0
                if not exists:
                    result["status"] = "skipped"
                    result["message"] = say("recover.step.no_branch", branch=branch)
                    continue
            code, said = targets.run_step(Path(path), step["git"], timeout)
            result["status"], result["message"] = ("done", said) if code == 0 else ("failed", said)
            stopped = code != 0
    return results


def prune_empty_folders(top: Path, folder: Path) -> None:
    """After a delete: git does not track folders, so a folder that lost its last file goes too. Stops at the repository top."""
    while folder != top and folder.is_dir():
        try:
            folder.rmdir()
        except OSError:
            return
        folder = folder.parent


def write_repo(root: Path, found: targets.Targets, repo: Dict[str, Any], branch: str, written: List[Dict[str, Any]]) -> bool:
    """Make the branch and write the files of one repository. Returns whether the branch was made; fills `written`.

    A knowledge base gets no branch: the files go onto its base branch and are committed with `repo["message"]`."""
    handle = found.repos[repo["name"]]
    direct = bool(repo.get("direct"))
    if direct:  # the plan was checked a moment ago; look again right before writing on the base branch
        if targets.current_branch(handle, found.timeout) != handle.base_ref or targets.ref_commit(handle, found.timeout) != repo["base_commit"]:
            raise CommandError(say("promote.kb.changed", name=repo["name"], base_ref=handle.base_ref))
        if targets.dirty_paths(handle, found.timeout):
            raise CommandError(say("promote.kb.dirty", name=repo["name"]))
    else:
        targets.git(handle, "switch", "-c", branch, handle.base_ref, timeout=found.timeout)
    top = handle.path.resolve()
    for item in repo["files"]:
        if item["action"] == "unchanged":
            continue
        destination = handle.path / item["relative"]
        if common.inside(top, destination) is None:
            raise OSError(say("promote.write.outside", relative=item["relative"]))
        written.append(item)  # before the write: a half-written file is undone like a finished one
        if item["action"] == "delete":
            destination.unlink()
            prune_empty_folders(handle.path, destination.parent)
            if destination.exists():
                raise OSError(say("promote.write.not_deleted", relative=item["relative"]))
            continue
        common.copy_file(Path(item["source"]), destination)
        if common.sha256_file(destination) != item["sha256"]:
            raise OSError(say("promote.write.mismatch", relative=item["relative"]))
    if direct:
        commit_direct(handle, repo, written, repo.get("message") or f"harness task: {len(written)} file(s)", found.timeout)
    return not direct


def commit_direct(handle: targets.Repo, repo: Dict[str, Any], written: List[Dict[str, Any]], message: str, timeout: int) -> None:
    """One commit on the base branch with the written files and nothing else. A failure leaves nothing staged."""
    names = [item["relative"] for item in written]
    try:
        targets.git(handle, "add", "-A", "--", *names, timeout=timeout)
        targets.git(handle, "commit", "-q", "-m", message, "--", *names, timeout=timeout)
    except targets.TargetError:
        targets.git(handle, "reset", "-q", "--", *names, timeout=timeout, allow_failure=True)
        raise
    repo["commit"] = targets.git(handle, "rev-parse", "HEAD", timeout=timeout).decode("ascii", errors="replace").strip()


def written_count(repo: Dict[str, Any]) -> int:
    return len([item for item in repo["files"] if item["action"] != "unchanged"])


def commit_message(result: Dict[str, Any], count: int) -> str:
    name = str(result.get("task", "")).rsplit("/", 1)[-1] or "task"
    return f"harness task {name}: {count} file(s)\n\nWritten by `task promote` after the person approved plan {result['plan_sha256'][:12]} (round {result.get('round', 1)})."


def run_result(
    root: Path, result: Dict[str, Any], base: Path, patch_name: str, approval: Dict[str, Any], recover: str, header: str = "",
) -> Tuple[Dict[str, Any], str]:
    """Write the planned result. Returns (promote record, message). `message` is empty on success; otherwise the run failed
    halfway, the record is `partial`, and the message tells the person what to do."""
    found = common.load_targets(root)
    saved = save_dev(root, base, patch_name, result, header)
    branch = result["branch"]
    done: List[str] = []
    for index, repo in enumerate(result["repos"]):
        written: List[Dict[str, Any]] = []
        switched = False
        try:
            if repo.get("direct"):
                repo["message"] = commit_message(result, written_count(repo))
            switched = write_repo(root, found, repo, branch, written)
        except (OSError, targets.TargetError, CommandError) as error:
            # `switch -c` may have worked before the failure: ask git, do not guess
            try:
                switched = switched or targets.current_branch(found.repos[repo["name"]], found.timeout) == branch
            except targets.TargetError:
                switched = False
            return partial_record(result, saved, done, repo, written, switched, error, result["repos"][index + 1:], recover), "partial"
        done.append(repo["name"])
    record = {
        "state": "done",
        "plan_sha256": result["plan_sha256"],
        "approved_plan_sha256": approval["approved_plan_sha256"],
        "approved_at": approval["approved_at"],
        "at": utc_now(),
        "branch": branch,
        "repos": {
            repo["name"]: {"path": repo["path"], "base_commit": repo["base_commit"], "current_branch": repo["current_branch"], **({"commit": repo["commit"]} if repo.get("commit") else {})}
            for repo in result["repos"]
        },
        "files": [{"path": f["path"], "action": f["action"], "sha256": f["sha256"]} for f in result["files"]],
        **saved,
    }
    return record, ""


def partial_record(
    result: Dict[str, Any], saved: Dict[str, str], done: List[str],
    failed: Dict[str, Any], written: List[Dict[str, Any]], switched: bool, error: Exception, rest: List[Dict[str, Any]], recover: str,
) -> Dict[str, Any]:
    branch = result["branch"]
    by_name = {repo["name"]: repo for repo in result["repos"]}
    steps: List[Dict[str, Any]] = []
    for name in done:
        steps += recovery_steps(by_name[name], branch, True, [f for f in by_name[name]["files"] if f["action"] != "unchanged"])
    steps += recovery_steps(failed, branch, switched, written)
    return {
        "state": "partial",
        "recover_command": recover,
        "plan_sha256": result["plan_sha256"],
        "at": utc_now(),
        "branch": branch,
        "error": str(error),
        "repos_done": done,
        "repo_failed": failed["name"],
        "repos_untouched": [repo["name"] for repo in rest],
        "recovery": [render(step) for step in steps],
        "recovery_steps": steps,
        **saved,
    }


def partial_message(record: Dict[str, Any]) -> str:
    done = messages.joined(record["repos_done"]) or say("output.none_known")
    untouched = messages.joined(record["repos_untouched"]) or say("output.none_known")
    lines = [
        say("promote.partial.head", repo=record["repo_failed"], error=record["error"]),
        say("promote.partial.done", branch=record["branch"], done=done),
        say("promote.partial.failed", repo=record["repo_failed"]),
        say("promote.partial.untouched", untouched=untouched),
        say("promote.partial.backup", dev=record["dev"]),
    ]
    if record["recovery"]:
        recover = record.get("recover_command") or f"{cli_command()} task recover"
        lines.append(say("promote.partial.recover", recover=recover))
        lines.append(say("promote.partial.by_hand"))
        lines += [f"    {command}" for command in record["recovery"]]
    lines.append(say("promote.partial.after"))
    return "\n".join(lines)
