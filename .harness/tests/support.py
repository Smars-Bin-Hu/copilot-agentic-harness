"""Shared test helpers. Tests run hook.py and cli.py as real subprocesses, with HARNESS_ROOT pointing at a temp root."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / ".harness" / "engine"
HOOK = ENGINE / "hook.py"
CLI = ENGINE / "cli.py"
FIXTURES = REPO / ".harness" / "eval" / "fixtures" / "hooks" / "copilot-sdk"

if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

# The texts the tests compare are the Chinese ones. The hook and the CLI run as subprocesses and inherit this.
# test_language.py checks the other language: every name has both texts, with the same placeholders.
os.environ["HARNESS_LANGUAGE"] = "zh"


def iter_session(name: str) -> Iterator[Dict[str, Any]]:
    with (FIXTURES / "sessions" / name).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def load_payload(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / "payloads" / name).read_text(encoding="utf-8"))


def payload(event: str, session_id: str, **fields: Any) -> Dict[str, Any]:
    """A Copilot (SDK) session payload in the recorded shape."""
    base = {
        "hook_event_name": event,
        "session_id": session_id,
        "timestamp": "2026-01-01T00:00:00.000Z",
        "cwd": "/workspace",
    }
    base.update(fields)
    return base


def pre_tool(session_id: str, tool_name: str, tool_input: Optional[dict] = None) -> Dict[str, Any]:
    return payload("PreToolUse", session_id, tool_name=tool_name, tool_input=tool_input or {})


def post_tool(session_id: str, tool_name: str, tool_input: Optional[dict] = None, response: str = "") -> Dict[str, Any]:
    result = {"result_type": "success", "text_result_for_llm": response}
    return payload("PostToolUse", session_id, tool_name=tool_name, tool_input=tool_input or {}, tool_result=result)


def subagent_start(session_id: str, agent: str) -> Dict[str, Any]:
    """The parent session's SubagentStart: camelCase, no event name (recorded 2026-10-01)."""
    return {
        "sessionId": session_id,
        "timestamp": 1790907432584,
        "cwd": "/workspace",
        "transcriptPath": "<COPILOT_HOME>/session-state/events.jsonl",
        "agentName": agent,
        "agentDescription": "",
    }


def subagent_stop(session_id: str, agent: str, child_session_id: str = "", message: str = "") -> Dict[str, Any]:
    """The parent session's SubagentStop. `agent_id` is the child's session id."""
    return payload(
        "SubagentStop",
        session_id,
        agent_id=child_session_id,
        agent_type=agent,
        agent_name=agent,
        last_assistant_message=message,
        stop_reason="end_turn",
    )


def make_root(root: Path, with_registry: bool = True, with_policy: bool = True) -> None:
    """Minimal harness root: registry and policies. The engine code always comes from the real repo."""
    (root / ".harness").mkdir(parents=True, exist_ok=True)
    if with_registry:
        shutil.copy(REPO / ".harness" / "registry.json", root / ".harness" / "registry.json")
    if with_policy:
        # Not the override files: they are the user's own settings (a target repository, a gate rule) and must not leak into a test
        shutil.copytree(REPO / ".harness" / "policies", root / ".harness" / "policies", ignore=shutil.ignore_patterns("*.override.json"))
        shutil.copytree(REPO / ".harness" / "contracts", root / ".harness" / "contracts")


class HarnessTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        make_root(self.root)
        # COPILOT_HOME: the report reads Copilot's own session record; a test must not read the real one of this machine
        self.env = {**os.environ, "HARNESS_ROOT": str(self.root), "COPILOT_HOME": str(self.root / "copilot-home")}

    # --- running the engine -------------------------------------------------------------------

    def run_script(self, script: Path, *arguments: str, stdin: Optional[str] = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            input=stdin,
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=self.env,
            check=False,
        )

    def hook(self, data: Dict[str, Any]) -> Dict[str, Any]:
        completed = self.run_script(HOOK, stdin=json.dumps(data))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def cli(self, *arguments: str) -> subprocess.CompletedProcess:
        return self.run_script(CLI, *arguments)

    def cli_json(self, *arguments: str) -> Dict[str, Any]:
        completed = self.cli(*arguments)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    # --- state --------------------------------------------------------------------------------

    def session_state(self, session_id: str) -> Dict[str, Any]:
        """The state file of a session, as it is on disk."""
        return json.loads(self.state_file(session_id).read_text(encoding="utf-8"))

    def module_state(self, session_id: str, name: str = "task") -> Dict[str, Any]:
        return self.session_state(session_id)["modules"].get(name, {})

    def state_file(self, session_id: str) -> Path:
        return self.root / ".harness" / "runtime" / "state" / "vscode" / f"{session_id}.json"

    def log_lines(self, filename: str) -> List[Dict[str, Any]]:
        path = self.root / ".harness" / "runtime" / "logs" / filename
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def session_log(self, session_id: str, surface: str = "vscode") -> List[Dict[str, Any]]:
        """The call log of one session: one line per hook call."""
        return self.log_lines(f"{surface}/{session_id}.jsonl")

    def call_lines(self) -> List[Dict[str, Any]]:
        """Every call of every session, oldest first."""
        base = self.root / ".harness" / "runtime" / "logs"
        rows: List[Dict[str, Any]] = []
        for path in sorted(base.glob("*/*.jsonl")):
            rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        return sorted(rows, key=lambda row: row["at"])


# --- git repositories for tests ---------------------------------------------------------------------

GIT = shutil.which("git")
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def run_git(path: Path, *arguments: str) -> str:
    done = subprocess.run(["git", "-C", str(path), *arguments], capture_output=True, text=True, env={**os.environ, **IDENTITY}, check=True)
    return done.stdout.strip()


def make_repo(path: Path, files: Optional[Dict[str, str]] = None, branch: str = "main") -> Path:
    """A git repository with one commit on `branch`."""
    path.mkdir(parents=True)
    run_git(path, "init", "-q")
    run_git(path, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    for name, body in (files or {"README.md": "x\n"}).items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body.encode("utf-8"))  # the text as written: Windows must not turn \n into \r\n
    run_git(path, "add", "-A")
    run_git(path, "commit", "-q", "-m", "first")
    return path
