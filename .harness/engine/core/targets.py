"""Target repositories: git repositories outside the harness folder that a task reads from and promotes into.

Policy `target.json` (override: `target.override.json`):
  repos_root  a folder; every subfolder that is a git repository is a target, named after the folder
  repos       name -> {path?, base_ref?, refused_paths?}: a repository elsewhere, or settings for a found one
  base_ref    the branch files are read from (default main)

A repository with `knowledge_base: true` is the team's knowledge base (M8-7): promote writes it straight onto its base
branch and commits once, instead of making a branch and leaving the commit to the person. Reads of its files are
logged (M8-8). A `path` that is not absolute is taken from the harness folder (`knowledge-base`).

Everything here reads. Nothing writes to a target repository. git is run with an argument list, never through a shell.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config, gitread, messages, repo_paths, schema

POLICY_NAME = "target"
REPO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
DEFAULT_GIT_TIMEOUT = 30
BRANCH = re.compile(r"^feature/[A-Za-z0-9_]{1,60}$")
REGULAR_FILE_MODES = ("100644", "100755")
LONG_PATH_WARNING = 90  # characters; a request folder and a repository path add about 150 more, Windows stops at 260

_PATHS = {"type": "array", "items": {"type": "string", "minLength": 1}}
POLICY_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "repos_root", "repos", "base_ref", "refused_paths"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "repos_root": {"type": "string"},
        "repos": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "base_ref": {"type": "string", "minLength": 1}, "refused_paths": _PATHS, "knowledge_base": {"type": "boolean"}},
                "additionalProperties": False,
            },
        },
        "base_ref": {"type": "string", "minLength": 1},
        "refused_paths": _PATHS,
        "git_timeout_seconds": {"type": "integer", "minimum": 1},
    },
}


TargetError = gitread.GitError  # a target repository cannot be found or read


@dataclass
class Repo:
    name: str
    path: Path
    base_ref: str
    refused_paths: List[str] = field(default_factory=list)
    knowledge_base: bool = False  # promote commits onto the base branch; reads are logged


@dataclass
class Targets:
    configured: bool
    repos: Dict[str, Repo]
    problems: List[str]
    timeout: int = DEFAULT_GIT_TIMEOUT

    def names(self) -> List[str]:
        return sorted(self.repos)

    def get(self, name: str) -> Repo:
        if name not in self.repos:
            known = messages.joined(self.names()) or messages.text("target.none")
            raise TargetError(messages.text("target.unknown", name=name, known=known))
        return self.repos[name]


def validate_policy(policy: Dict[str, Any]) -> None:
    schema.check(policy, POLICY_SCHEMA, POLICY_NAME + ".json")
    for name in policy["repos"]:
        if not REPO_NAME.match(name):
            raise ValueError(f"Invalid {POLICY_NAME}.json: repo name {name!r} may only hold letters, digits, `_`, `.` and `-`")
    patterns = list(policy["refused_paths"])
    for entry in policy["repos"].values():
        patterns += entry.get("refused_paths", [])
    for pattern in patterns:
        repo_paths.glob_regex(pattern)


def expand(raw: str, root: Optional[Path] = None) -> Path:
    """`~` and environment variables (`%USERPROFILE%`, `$HOME`) in a configured path. With `root`: a path that is not absolute is under it."""
    path = Path(os.path.expandvars(os.path.expanduser(raw.strip())))
    return path if root is None or path.is_absolute() else root / path


def is_repo(path: Path) -> bool:
    return path.is_dir() and (path / ".git").exists()


def load(root: Path) -> Targets:
    """The configured repositories. Problems (a missing folder, a settings-only entry for an unknown name) are listed, not raised."""
    policy = config.load_policy(root, POLICY_NAME)
    validate_policy(policy)
    timeout = policy.get("git_timeout_seconds", DEFAULT_GIT_TIMEOUT)
    base_ref, refused = policy["base_ref"], list(policy["refused_paths"])
    problems: List[str] = []
    repos: Dict[str, Repo] = {}
    base = policy["repos_root"].strip()
    if base:
        folder = expand(base)
        if not folder.is_dir():
            problems.append(messages.text("target.root.missing", folder=folder))
        else:
            for child in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
                if REPO_NAME.match(child.name) and is_repo(child):
                    repos[child.name] = Repo(child.name, child, base_ref, list(refused))
    for name, entry in policy["repos"].items():
        if entry.get("path", "").strip():
            location = expand(entry["path"], root)
            if not is_repo(location):
                problems.append(messages.text("target.not_git", name=name, location=location))
                continue
            repos[name] = Repo(name, location, base_ref, list(refused))
        elif name not in repos:
            problems.append(messages.text("target.no_path", name=name))
            continue
        repo = repos[name]
        repo.base_ref = entry.get("base_ref", repo.base_ref)
        repo.refused_paths = list(entry.get("refused_paths", repo.refused_paths))
        repo.knowledge_base = bool(entry.get("knowledge_base", False))
    return Targets(configured=bool(base or policy["repos"]), repos=repos, problems=problems, timeout=timeout)


KB_DIR = "knowledge-base"  # where a team puts its knowledge base when it is not registered as a repository
COMPANY_DIR = "company"  # in a knowledge base: the company's standards, skills and instructions (`company.py`)
KB_IGNORED = {"README.md", ".gitkeep", ".gitignore", ".DS_Store"}  # what is no content: the shipped placeholder and housekeeping files


def knowledge_base_content(folder: Path) -> List[Path]:
    """The items of a knowledge base folder that are content (not the README, not hidden files). Empty when the folder is missing."""
    if not folder.is_dir():
        return []
    return [item for item in sorted(folder.iterdir()) if item.name not in KB_IGNORED and not item.name.startswith(".")]


def kb_registered(root: Path) -> bool:
    """Is `knowledge-base/` registered as a target repository (an entry with `knowledge_base: true` that points at it)?"""
    try:
        kb = (root / KB_DIR).resolve()
        return any(folder.resolve() == kb for name, folder in knowledge_bases(root) if name != KB_DIR)
    except OSError:
        return True  # cannot tell: do not nag


def company_folder(root: Path) -> Optional[Path]:
    """`company/` of the first knowledge base that has one. Reads the policy only, as `knowledge_bases` does."""
    return next((path / COMPANY_DIR for _name, path in knowledge_bases(root) if (path / COMPANY_DIR).is_dir()), None)


def knowledge_bases(root: Path) -> List[Tuple[str, Path]]:
    """(name, folder) of every knowledge base: the registered ones and `knowledge-base/` of the harness folder.

    Reads the policy only (no git, no listing of repos_root): a hook calls it for every tool call. Never raises.
    """
    found: List[Tuple[str, Path]] = []
    try:
        policy = config.load_policy(root, POLICY_NAME)
        base = str(policy.get("repos_root") or "").strip()
        for name, entry in (policy.get("repos") or {}).items():
            if not isinstance(entry, dict) or not entry.get("knowledge_base"):
                continue
            raw = str(entry.get("path") or "").strip()
            if raw:
                found.append((name, expand(raw, root)))
            elif base:
                found.append((name, expand(base) / name))
    except Exception:  # noqa: BLE001 - a broken policy must not stop a hook
        found = []
    default = root / KB_DIR
    try:
        known = {path.resolve() for _name, path in found}
        if default.resolve() not in known:
            found.append((KB_DIR, default))
    except OSError:
        pass
    return found


# --- reading a repository ---------------------------------------------------------------------


def git(repo: Repo, *arguments: str, timeout: int = DEFAULT_GIT_TIMEOUT, allow_failure: bool = False) -> bytes:
    """Run `git -C <repo> ...` and return its stdout as bytes. Raises TargetError on failure unless `allow_failure`."""
    return gitread.run(repo.path, repo.name, *arguments, timeout=timeout, allow_failure=allow_failure)


def run_step(path: Path, arguments: List[str], timeout: int = DEFAULT_GIT_TIMEOUT) -> Tuple[int, str]:
    """`git -C <path> <arguments>` as one step of something a person asked for: (exit code, what git said). Never raises."""
    try:
        done = subprocess.run(gitread.command(path, arguments), capture_output=True, timeout=timeout, env=gitread.env(), check=False)
    except (FileNotFoundError, PermissionError):
        return 127, messages.text("target.git.missing")
    except subprocess.TimeoutExpired:
        return 124, messages.text("target.timeout", timeout=timeout)
    said = (done.stderr or done.stdout).decode("utf-8", errors="replace").strip()
    return done.returncode, said


def valid_branch(name: str) -> bool:
    """`feature/` and then letters, digits and `_`: no `-`, `.` or `/` in the name."""
    return bool(BRANCH.match(name))


def tracked_files(repo: Repo, commit: str, relative: str, timeout: int = DEFAULT_GIT_TIMEOUT) -> List[Tuple[str, str, str]]:
    """(mode, blob sha, path) of every file `commit` has at `relative`: that file, or everything under that folder."""
    raw = git(repo, "ls-tree", "-r", "-z", commit, "--", relative, timeout=timeout).decode("utf-8", errors="replace")
    found = []
    for line in raw.split("\0"):
        if not line:
            continue
        info, _, path = line.partition("\t")
        mode, _kind, blob = info.split(" ")
        found.append((mode, blob, path))
    return found


def read_blob(repo: Repo, blob: str, timeout: int = DEFAULT_GIT_TIMEOUT) -> bytes:
    """The bytes of a file as git stores it: no line-ending conversion."""
    return git(repo, "cat-file", "blob", blob, timeout=timeout)


def text(repo: Repo, *arguments: str, timeout: int = DEFAULT_GIT_TIMEOUT) -> str:
    return git(repo, *arguments, timeout=timeout).decode("utf-8", errors="replace").strip()


def ref_commit(repo: Repo, timeout: int = DEFAULT_GIT_TIMEOUT) -> str:
    """The commit `base_ref` points to now, or an empty string when the repository has no such branch."""
    out = git(repo, "rev-parse", "--verify", "--quiet", f"{repo.base_ref}^{{commit}}", timeout=timeout, allow_failure=True)
    return out.decode("ascii", errors="replace").strip()


def commit_date(repo: Repo, commit: str, timeout: int = DEFAULT_GIT_TIMEOUT) -> str:
    return text(repo, "log", "-1", "--format=%cI", commit, timeout=timeout)


def current_branch(repo: Repo, timeout: int = DEFAULT_GIT_TIMEOUT) -> str:
    """The checked-out branch, or `(detached)`."""
    out = git(repo, "symbolic-ref", "--short", "-q", "HEAD", timeout=timeout, allow_failure=True)
    return out.decode("utf-8", errors="replace").strip() or "(detached)"


def dirty_paths(repo: Repo, timeout: int = DEFAULT_GIT_TIMEOUT) -> List[str]:
    """Paths with uncommitted changes, untracked files included. Empty means a clean working tree."""
    raw = git(repo, "status", "--porcelain", "-z", "--untracked-files=all", timeout=timeout)
    found = []
    for entry in raw.decode("utf-8", errors="replace").split("\0"):
        if len(entry) > 3:
            found.append(entry[3:])
    return found


def summary(repo: Repo, timeout: int = DEFAULT_GIT_TIMEOUT) -> Dict[str, Any]:
    """What a person needs to see about one repository."""
    commit = ref_commit(repo, timeout)
    dirty = dirty_paths(repo, timeout)
    return {
        "name": repo.name,
        "path": str(repo.path),
        "base_ref": repo.base_ref,
        "base_commit": commit[:12],
        "base_commit_date": commit_date(repo, commit, timeout) if commit else "",
        "has_base_ref": bool(commit),
        "current_branch": current_branch(repo, timeout),
        "clean": not dirty,
        "uncommitted_files": len(dirty),
        "refused_paths": repo.refused_paths,
        "knowledge_base": repo.knowledge_base,
    }


# --- where the harness itself lives -----------------------------------------------------------


def location_warnings(root: str, windows: Optional[bool] = None) -> List[str]:
    """Paths that cause trouble for request folders: a long one (Windows stops at 260) and a synced one (OneDrive)."""
    found = []
    on_windows = os.name == "nt" if windows is None else windows
    if on_windows and len(root) > LONG_PATH_WARNING:
        found.append(messages.text("target.windows.long", length=len(root)))
    if "onedrive" in root.lower():
        found.append(messages.text("target.windows.onedrive"))
    return found
