"""Bring the base branch of a target repository up to its remote before files are read from it (1.5.39).

`task fetch` reads the committed base branch (`main`) and `promote --dry-run` checks every file against it. Both read the local branch: when
another task's pull request was merged on the remote, the local `main` is behind, the work starts from old files, and the clash shows only in
the pull request. So, at the first fetch of a repository in a round and at every dry run, the engine runs `git fetch` and moves the local
base branch forward, but only when that is a fast-forward and safe:

  not checked out          the branch is moved (`update-ref`, old value checked): nothing in the working tree changes
  checked out and clean    `git merge --ff-only`
  checked out with changes stopped: the person commits or puts away their changes
  local commits not on the remote, the remote moved too (diverged)   stopped: the person decides
  local ahead only         left as it is, said
  no remote, no upstream   nothing to do
  remote not reached       said, and the local branch is used (offline, no access)
"""

from __future__ import annotations

from typing import Any, Dict, List

from core import messages, targets

from .common import CommandError

FETCH_TIMEOUT = 120  # a fetch goes over the network


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def remote_of(repo: targets.Repo, timeout: int) -> str:
    """The remote of the base branch: its upstream's, else `origin`, else the only one. "" when there is none."""
    upstream = targets.git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{repo.base_ref}@{{upstream}}", timeout=timeout, allow_failure=True).decode("utf-8", "replace").strip()
    names = [line.strip() for line in targets.git(repo, "remote", timeout=timeout, allow_failure=True).decode("utf-8", "replace").splitlines() if line.strip()]
    if upstream and "/" in upstream and upstream.split("/", 1)[0] in names:
        return upstream.split("/", 1)[0]
    if "origin" in names:
        return "origin"
    return names[0] if len(names) == 1 else ""


def commit_of(repo: targets.Repo, ref: str, timeout: int) -> str:
    return targets.git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", timeout=timeout, allow_failure=True).decode("ascii", "replace").strip()


def is_ancestor(repo: targets.Repo, older: str, newer: str, timeout: int) -> bool:
    code, _said = targets.run_step(repo.path, ["merge-base", "--is-ancestor", older, newer], timeout)
    return code == 0


def sync(repo: targets.Repo, timeout: int) -> Dict[str, Any]:
    """`{state, note}`: state is `current`, `updated`, `ahead`, `none` (no remote) or `offline`; `note` is what to tell the agent ("" when nothing).
    A state that is not safe raises CommandError and moves nothing."""
    base = repo.base_ref
    remote = remote_of(repo, timeout)
    if not remote:
        return {"state": "none", "note": ""}
    code, said = targets.run_step(repo.path, ["fetch", "--quiet", remote, base], max(timeout, FETCH_TIMEOUT))
    if code != 0:
        return {"state": "offline", "note": say("sync.offline", repo=repo.name, remote=remote, base=base, said=said.splitlines()[-1][:200] if said else "")}
    local, theirs = commit_of(repo, base, timeout), commit_of(repo, f"{remote}/{base}", timeout)
    if not theirs or local == theirs:
        return {"state": "current", "note": ""}
    if not local:
        return {"state": "none", "note": ""}  # no local base branch: the read that follows says so
    if is_ancestor(repo, theirs, local, timeout):
        return {"state": "ahead", "note": say("sync.ahead", repo=repo.name, base=base, remote=remote)}
    if not is_ancestor(repo, local, theirs, timeout):
        raise CommandError(say("sync.diverged", repo=repo.name, base=base, remote=remote, path=str(repo.path)))
    if targets.current_branch(repo, timeout) == base:
        changed = targets.dirty_paths(repo, timeout)
        if changed:
            raise CommandError(say("sync.dirty", repo=repo.name, base=base, remote=remote, path=str(repo.path), files=", ".join(changed[:5])))
        code, said = targets.run_step(repo.path, ["merge", "--ff-only", "--quiet", f"{remote}/{base}"], timeout)
    else:
        code, said = targets.run_step(repo.path, ["update-ref", f"refs/heads/{base}", theirs, local], timeout)  # only from the value read: nobody moved it meanwhile
    if code != 0:
        raise CommandError(say("sync.failed", repo=repo.name, base=base, said=said[:300]))
    return {"state": "updated", "note": say("sync.updated", repo=repo.name, base=base, remote=remote, old=local[:10], new=theirs[:10])}


def sync_all(repos: List[targets.Repo], timeout: int, notes: List[str]) -> None:
    for repo in repos:
        found = sync(repo, timeout)
        if found["note"]:
            notes.append(found["note"])
