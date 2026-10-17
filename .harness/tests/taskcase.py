"""Shared bases for the task tests: a session, target repositories made with `git init`, a task with its helpers.

Not a test module itself (no `test_` prefix): the classes here hold no tests.
"""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from support import HarnessTestCase, payload, pre_tool

from core import tasks
from modules.task import task as task_ops
from support import GIT, make_repo, run_git

SESSION = "sess-main"
NAME = "job1"
TASK = f"{tasks.TASKS_DIR}/{NAME}"
PLAN = "# 计划\n\n给 a.sql 加一列。只改 repo_b/src/a.sql。\n"


class SessionCase(HarnessTestCase):
    """A session that has had a hook call, so it has state."""

    def setUp(self) -> None:
        super().setUp()
        self.prompt("start")

    def prompt(self, text: str, session: str = SESSION) -> Dict[str, Any]:
        return self.hook(payload("UserPromptSubmit", session, prompt=text))

    def context(self, output: Dict[str, Any]) -> str:
        return output.get("additionalContext", "")

    def run_cli(self, *arguments: str, ok: bool = True) -> Dict[str, Any]:
        completed = self.cli(*arguments)
        if ok:
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            return json.loads(completed.stdout)
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        return {"stderr": completed.stderr, "stdout": completed.stdout}

    def refused(self, *arguments: str) -> str:
        return self.run_cli(*arguments, ok=False)["stderr"]

    def write(self, relative: str, text: str = "x\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))  # the text as written: Windows must not turn \n into \r\n
        return path

    def decision(self, output: Dict[str, Any]) -> str:
        return output.get("permissionDecision", "")

    def reason(self, output: Dict[str, Any]) -> str:
        return output["permissionDecisionReason"]

    def edit(self, path: str, session: str = SESSION) -> Dict[str, Any]:
        """The agent's edit tool on a path (absolute, or relative to the root)."""
        data = pre_tool(session, "Write", {"path": path, "file_text": "x"})
        data["cwd"] = str(self.root)
        return self.hook(data)


@unittest.skipUnless(GIT, "git is not installed")
class TargetCase(SessionCase):
    """Two target repositories: repo_b (src/a.sql, src/b.sql, docs/x.md) and repo_a (a.sql)."""

    def setUp(self) -> None:
        super().setUp()
        self.repos = self.root / "source" / "repos"
        self.repo_b = make_repo(self.repos / "repo_b", {"src/a.sql": "select 1;\n", "src/b.sql": "select 2;\n", "docs/x.md": "doc\n"})
        self.repo_a = make_repo(self.repos / "repo_a", {"a.sql": "select 9;\n"})
        self.override({"repos_root": str(self.repos)})

    def override(self, data: dict) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps(data), encoding="utf-8")

    def main_commit(self, repo: Path) -> str:
        return run_git(repo, "rev-parse", "main")

    def blob(self, repo: Path, path: str) -> str:
        return run_git(repo, "rev-parse", f"main:{path}")


class TaskCase(TargetCase):
    """One task, `job1`. `new()` makes it (kind dev, so it has DEV/); `ready()` also approves a plan."""

    def setUp(self) -> None:
        super().setUp()
        self.task = self.root / TASK

    def new(self, *extra: str, name: str = NAME, kind: str = "dev", session: str = SESSION, ok: bool = True) -> Any:
        return self.run_cli("task", "new", name, "--kind", kind, "--session-id", session, *extra, ok=ok)

    def open(self, name: str = NAME, session: str = SESSION, ok: bool = True) -> Any:
        return self.run_cli("task", "open", name, "--session-id", session, ok=ok)

    def data(self, task: str = TASK) -> Dict[str, Any]:
        return json.loads((self.root / task / ".task" / "task.json").read_text(encoding="utf-8"))

    def write_plan(self, text: str = PLAN, task: str = TASK) -> None:
        (self.root / task / "PLAN.md").write_text(text, encoding="utf-8")

    def approve_plan(self, code: Optional[str] = None, out: Any = None, task: str = TASK) -> Dict[str, Any]:
        typed = code if code is not None else tasks.plan_digest(self.root, task)[:8]
        return task_ops.approve_plan(self.root, task, reader=lambda _prompt: typed, interactive=True, out=out or io.StringIO())

    def ready(self, name: str = NAME) -> None:
        """A task with an approved plan."""
        task = f"{tasks.TASKS_DIR}/{name}"
        if not (self.root / task / ".task").exists():
            self.new(name=name)
        self.write_plan(task=task)
        self.approve_plan(task=task)

    def dev(self, key: str, text: Optional[str] = None, task: str = TASK) -> Path:
        path = self.root / task / "DEV" / key
        if text is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        return path

    def fetch(self, *specs: str, task: str = TASK, ok: bool = True) -> Any:
        return self.run_cli("task", "fetch", "--task", task, *specs, ok=ok)

    def approve_promote(self, code: Optional[str] = None, out: Any = None, task: str = TASK) -> Dict[str, Any]:
        typed = code if code is not None else self.data(task)["promote"].get("plan_sha256", "")[:8]
        return task_ops.approve_promote(self.root, task, reader=lambda _prompt: typed, interactive=True, out=out or io.StringIO())

    def promoted(self) -> Dict[str, Any]:
        """A task with one changed file, promoted for real."""
        self.ready()
        self.fetch("repo_b/src/a.sql")
        self.dev("repo_b/src/a.sql", "select 1, 2;\n")
        self.run_cli("task", "promote", "--dry-run")
        self.approve_promote()
        return self.run_cli("task", "promote")

    def branches(self, repo: Path) -> List[str]:
        return run_git(repo, "branch", "--format=%(refname:short)").split()
