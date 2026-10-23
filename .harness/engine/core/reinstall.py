"""`harness reinstall --from <old copy>`: carry what only this machine holds from an older copy of the harness to this one (1.5.8).

A new copy of the repository has the shipped files only. What git ignores is the person's: the tasks, the reports, the
goals, `.harness/runtime/` (which session holds which task, the logs the reports read, the repository map cache), the
`*.override.json` policies and the knowledge base with its own `.git`. Lose `runtime/` and a chat that goes on in an old
session no longer finds its task. This copies all of it; the old copy is not changed.

Without `--apply` nothing is written (an agent may run that). With it, only a person at a terminal may run it.
Never overwritten: what the new copy already has is skipped and listed, so a run can be repeated.
Not carried: `runtime/capture/` (debug input, large, holds code), `runtime/board-serve.json` (the old process's port),
the target repositories (outside the harness), the short command (in PATH; `doctor` says when it points at the old copy).
Shipped files the company changed (the code standards, the knowledge base instructions, `domain-*` skills and the skills that start with the company's `skill_prefix`) are carried
when git in the old copy says they were changed there. Any other changed file is only listed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import approval, config, messages, skillcheck, tasks
from .paths import runtime_dir
from .registry import harness_version

KB_DIR = "knowledge-base"
GOALS_DIR = ".workspace/goals"
REPORTS_DIR = ".workspace/reports/tasks"
POLICIES_DIR = ".harness/policies"
SKILLS_DIR = ".github/skills"
DOMAIN_PREFIX = "domain-"
RUNTIME_LEFT_OUT = {"capture", "board-serve.json"}
COMPANY_FILES = (".harness/standards/code-standards.md", ".github/instructions/knowledgebase.instructions.md")
PLACEHOLDER = {"README.md", ".gitkeep"}  # what an empty knowledge base ships with
LEFT_ALONE_SHOWN = 20
GIT_SECONDS = 60


class ReinstallError(Exception):
    pass


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def numbers(version: str) -> tuple:
    try:
        return tuple(int(part) for part in str(version).split(".")[:3])
    except ValueError:
        return (0,)


def source_of(root: Path, raw: str) -> Path:
    """The old copy, checked: an absolute path, a folder with a registry, not this copy and not inside or around it, not newer."""
    path = Path(raw).expanduser() if raw else Path("")
    if not raw or not path.is_absolute():
        raise ReinstallError(say("reinstall.from.relative", path=raw))
    old = path.resolve()
    if not (old / ".harness" / "registry.json").is_file():
        raise ReinstallError(say("reinstall.from.not_harness", path=str(old)))
    here = root.resolve()
    if old == here or old in here.parents or here in old.parents:
        raise ReinstallError(say("reinstall.from.same", path=str(old)))
    try:  # the file as it is: an older release has an older registry form that the schema of this one would refuse
        before = str(json.loads((old / ".harness" / "registry.json").read_text(encoding="utf-8-sig"))["version"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ReinstallError(say("reinstall.from.not_harness", path=f"{old} ({error})")) from None
    if numbers(before) > numbers(harness_version(root)):
        raise ReinstallError(say("reinstall.from.newer", old=before, new=harness_version(root)))
    return old


def git_changes(path: Path) -> Optional[List[str]]:
    """The files git says were changed or added in a copy; None when git cannot say (not a repository, no git)."""
    if not (path / ".git").exists():
        return None
    try:
        done = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "-z", "--untracked-files=all"], capture_output=True, text=True, encoding="utf-8", timeout=GIT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return [entry[3:] for entry in done.stdout.split("\0") if len(entry) > 3]


def is_placeholder(folder: Path) -> bool:
    return not (folder / ".git").exists() and all(item.name in PLACEHOLDER for item in folder.iterdir())


def files_under(folder: Path) -> List[Path]:
    return sorted(item for item in folder.rglob("*") if item.is_file() and item.name != ".gitkeep")


class Plan:
    def __init__(self) -> None:
        self.steps: List[Dict[str, Any]] = []  # what to copy: {group, name, kind, src, dst, count}
        self.skipped: List[Dict[str, str]] = []

    def copy(self, group: str, name: str, kind: str, src: Path, dst: Path, count: int = 1) -> None:
        self.steps.append({"group": group, "name": name, "kind": kind, "src": src, "dst": dst, "count": count})

    def skip(self, what: str, why: str) -> None:
        self.skipped.append({"what": what, "why": why})

    def folders(self, group: str, src: Path, dst: Path) -> None:
        """Each folder in `src` (a task, a report, a goal) goes whole to `dst`, unless it is there."""
        if not src.is_dir():
            return
        for item in sorted(src.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue
            if (dst / item.name).exists():
                self.skip(f"{group}/{item.name}", say("reinstall.why.exists"))
            else:
                self.copy(group, item.name, "dir", item, dst / item.name)

    def runtime(self, old: Path, root: Path) -> None:
        """The files of each runtime folder that this copy does not have yet. A session id is unique, so a file seldom collides."""
        source, target = runtime_dir(old), runtime_dir(root)
        if not source.is_dir():
            return
        for item in sorted(source.iterdir()):
            if item.name in RUNTIME_LEFT_OUT:
                continue
            files = files_under(item) if item.is_dir() else [item]
            base = item if item.is_dir() else source
            new = [path for path in files if not (target / path.relative_to(source)).exists()]
            if new:
                self.copy("runtime", item.name, "files", base, target / item.name if item.is_dir() else target, len(new))
                self.steps[-1]["files"] = new
                self.steps[-1]["root"] = (source, target)
            if len(files) > len(new):
                self.skip(f"runtime/{item.name}", say("reinstall.why.files_exist", count=len(files) - len(new)))

    def policies(self, old: Path, root: Path) -> None:
        source = old / POLICIES_DIR
        if not source.is_dir():
            return
        for item in sorted(source.glob(f"*{config.OVERRIDE_SUFFIX}")):
            if (root / POLICIES_DIR / item.name).exists():
                self.skip(f"policies/{item.name}", say("reinstall.why.exists"))
            else:
                self.copy("policies", item.name, "file", item, root / POLICIES_DIR / item.name)

    def knowledge_base(self, old: Path, root: Path) -> None:
        source, target = old / KB_DIR, root / KB_DIR
        if not source.is_dir() or is_placeholder(source):
            return  # nothing of the team's in the old one
        if target.is_dir() and not is_placeholder(target):
            self.skip(KB_DIR, say("reinstall.why.kb_has_content"))
        else:
            self.copy("knowledge-base", KB_DIR, "dir", source, target, len(files_under(source)))

    def company(self, old: Path, root: Path, before: Optional[List[str]], now: Optional[List[str]]) -> None:
        """Shipped files the company changed, and the `domain-*` skills and the `<skill_prefix>-*` skills it added. Carried only when git in the old copy says it changed them."""
        for relative in COMPANY_FILES:
            source, target = old / relative, root / relative
            if not source.is_file() or (target.is_file() and source.read_bytes() == target.read_bytes()):
                continue
            if before is None:
                self.skip(relative, say("reinstall.why.not_git"))
            elif relative not in before:
                continue  # the old one is the shipped one: this copy has the newer shipped file
            elif now is None or relative in now:
                self.skip(relative, say("reinstall.why.both_changed"))
            else:
                self.copy("company", relative, "file", source, target)
        skills = old / SKILLS_DIR
        if skills.is_dir():
            company = old_prefix(old) or skillcheck.company_prefix(root)  # the company's own skills: the old copy says which word they start with
            names = {item for pattern in (f"{DOMAIN_PREFIX}*", f"{company}-*" if company else "") if pattern for item in skills.glob(pattern)}
            for item in sorted(names):
                if not item.is_dir():
                    continue
                if (root / SKILLS_DIR / item.name).exists():
                    self.skip(f"{SKILLS_DIR}/{item.name}", say("reinstall.why.exists"))
                else:
                    self.copy("company", f"{SKILLS_DIR}/{item.name}", "dir", item, root / SKILLS_DIR / item.name)


def old_prefix(old: Path) -> str:
    """The company's skill prefix as the old copy has it, read from its override file (an old copy may lack the default policy that names it)."""
    try:
        return skillcheck.usable(config.read_json(config.override_path(old, "user")).get("skill_prefix", ""))
    except (OSError, ValueError, AttributeError):
        return ""


def left_alone(before: Optional[List[str]], plan: Plan) -> List[str]:
    """Files changed in the old copy that nothing here carries: the person decides."""
    if not before:
        return []
    carried = [step["name"] for step in plan.steps if step["group"] == "company"]
    own = (".workspace/", ".harness/runtime/", f"{KB_DIR}/", f"{KB_DIR}")
    return [path for path in before if not path.startswith(own) and not any(path == name or path.startswith(name + "/") for name in carried)]


def make_plan(root: Path, old: Path) -> tuple:
    before, now = git_changes(old), git_changes(root)
    plan = Plan()
    plan.folders("tasks", old / tasks.TASKS_DIR, root / tasks.TASKS_DIR)
    plan.folders("reports", old / REPORTS_DIR, root / REPORTS_DIR)
    plan.folders("goals", old / GOALS_DIR, root / GOALS_DIR)
    plan.runtime(old, root)
    plan.policies(old, root)
    plan.knowledge_base(old, root)
    plan.company(old, root, before, now)
    return plan, left_alone(before, plan)


def carry(step: Dict[str, Any]) -> None:
    kind, source, target = step["kind"], step["src"], step["dst"]
    if kind == "dir":
        shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)
    elif kind == "file":
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    else:
        base, destination = step["root"]
        for path in step["files"]:
            made = destination / path.relative_to(base)
            made.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, made)


def listed(plan: Plan) -> Dict[str, List[str]]:
    shown: Dict[str, List[str]] = {}
    for step in plan.steps:
        shown.setdefault(step["group"], []).append(step["name"] if step["group"] != "runtime" else say("reinstall.runtime.files", folder=step["name"], count=step["count"]))
    return shown


def run(root: Path, raw: str, apply: bool = False, interactive: Optional[bool] = None, check: Optional[Callable[[List[str]], Dict[str, Any]]] = None) -> Dict[str, Any]:
    """`check(task names)` runs after the copy (doctor and the task list); its result goes in the answer as `checked`."""
    if apply:
        try:
            approval.require_person("reinstall --apply", interactive, typed=False)
        except approval.Refused as error:
            raise ReinstallError(str(error)) from error
    old = source_of(root, raw)
    plan, others = make_plan(root, old)
    result: Dict[str, Any] = {"from": str(old), "to": str(root)}
    if not plan.steps and not plan.skipped:
        raise ReinstallError(say("reinstall.nothing", path=str(old)))
    if not apply:
        result.update(would_copy=listed(plan), skipped=plan.skipped, changed_in_old_not_copied=others[:LEFT_ALONE_SHOWN])
        result.update(next=say("reinstall.next.dry"), _next_person=say("reinstall.person.dry"))
        return result
    failed: List[Dict[str, str]] = []
    done = Plan()
    for step in plan.steps:
        try:
            carry(step)
            done.steps.append(step)
        except OSError as error:
            failed.append({"what": f"{step['group']}/{step['name']}", "why": str(error)})
    result.update(copied=listed(done), skipped=plan.skipped, failed=failed, changed_in_old_not_copied=others[:LEFT_ALONE_SHOWN])
    if len(others) > LEFT_ALONE_SHOWN:
        result["changed_in_old_more"] = len(others) - LEFT_ALONE_SHOWN
    names = [step["name"] for step in done.steps if step["group"] == "tasks"]
    if check is not None:
        result["checked"] = check(names)
    result["next"] = say("reinstall.next.failed" if failed else "reinstall.next.done")
    return result


def check_tasks(root: Path, names: List[str]) -> Dict[str, Any]:
    """Every task that came over has a state file that reads."""
    broken = [name for name in names if tasks.read(root, f"{tasks.TASKS_DIR}/{name}") is None]
    return {"tasks_copied": len(names), "tasks_unreadable": broken}
