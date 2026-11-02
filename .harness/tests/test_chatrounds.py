"""The rounds of a task's chat (1.6.55): read from Copilot's record, saved when the task closes, deleted some days after the archive."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_boardserve import ServeCase, TASK

from core import copilot_events, tasks
from modules.task import chatrounds, taskarchive

SESSION = "s-rounds"


def event(kind: str, at: str, **data: object) -> str:
    return json.dumps({"type": kind, "timestamp": at, "data": data}, ensure_ascii=False) + "\n"


def record(home: Path, session: str, lines: list) -> Path:
    path = home / "session-state" / session / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return path


LINES = [
    event("user.message", "2026-10-01T10:00:00.000Z", content="old work of another task"),
    event("assistant.message", "2026-10-01T10:00:01.000Z", content="old answer"),
    event("user.message", "2026-10-02T10:00:00.000Z", content="fix the load\nsecond line"),
    event("assistant.message", "2026-10-02T10:00:01.000Z", content="first I read the file", reasoningText="private thought"),
    event("assistant.message", "2026-10-02T10:00:02.000Z", content=""),
    event("tool.execution_start", "2026-10-02T10:00:03.000Z", toolName="read_file"),
    event("tool.execution_start", "2026-10-02T10:00:03.500Z", toolName="read_file"),
    event("tool.execution_start", "2026-10-02T10:00:03.600Z", toolName="inner", parentToolCallId="x"),
    event("assistant.message", "2026-10-02T10:00:03.700Z", content="a subagent's words", parentToolCallId="x"),
    "not json\n",
    event("assistant.message", "2026-10-02T10:00:04.000Z", content="done: **fixed**"),
    event("user.message", "2026-10-02T11:00:00.000Z", content="thanks"),
]


class RoundCase(ServeCase):
    def setUp(self) -> None:
        super().setUp()
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patch = mock.patch.dict("os.environ", {copilot_events.HOME_ENV: self.home.name})
        patch.start()
        self.addCleanup(patch.stop)
        chatrounds._cache.clear()
        self.task = tasks.folders(self.root)[0]
        self.path = tasks.state_file(self.root, self.task)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data.update(session_id=SESSION, sessions=[], created_at="2026-10-02T10:00:00.500Z")
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.events = record(Path(self.home.name), SESSION, LINES)


class ReadTests(RoundCase):
    def test_a_round_holds_all_the_agent_wrote_and_starts_at_the_prompt_that_opened_the_task(self) -> None:
        rounds = chatrounds.listing(self.root, self.task)
        self.assertEqual([item["head"] for item in rounds], ["fix the load second line", "thanks"])
        found = chatrounds.one(self.root, self.task, 0)
        self.assertEqual(found["prompt"], "fix the load\nsecond line")
        self.assertEqual(len(found["texts"]), 2)
        self.assertEqual(found["tools"], {"read_file": 2})
        self.assertNotIn("private thought", json.dumps(found))
        self.assertNotIn("subagent", json.dumps(found))

    def test_a_wrong_number_finds_nothing(self) -> None:
        for number in (-1, 2, "0", True, None):
            self.assertIsNone(chatrounds.one(self.root, self.task, number), number)

    def test_no_record_is_no_rounds(self) -> None:
        self.events.unlink()
        chatrounds._cache.clear()
        self.assertEqual(chatrounds.listing(self.root, self.task), [])

    def test_a_huge_round_is_cut_and_says_so(self) -> None:
        record(Path(self.home.name), SESSION, [event("user.message", "2026-10-02T10:00:00.000Z", content="p"), event("assistant.message", "2026-10-02T10:00:01.000Z", content="x" * (chatrounds.MAX_CHARS + 10))])
        chatrounds._cache.clear()
        self.assertTrue(chatrounds.one(self.root, self.task, 0)["cut"])

    def test_the_route_needs_the_paired_browser(self) -> None:
        status, data, _ = self.request("POST", "/api/rounds", {"op": "list", "task": TASK})
        self.assertEqual(status, 403, data)
        status, data, _ = self.request("POST", "/api/rounds", {"op": "list", "task": Path(TASK).name}, self.pair())
        self.assertEqual((status, len(data["result"]["rounds"])), (200, 2), data)


class SaveTests(RoundCase):
    def test_a_closed_task_reads_its_saved_rounds_when_the_record_is_gone(self) -> None:
        self.assertEqual(chatrounds.save(self.root, self.task), 2)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["status"] = "closed"
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.events.unlink()
        chatrounds._cache.clear()
        self.assertEqual(len(chatrounds.listing(self.root, self.task)), 2)


class PruneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "root"
        self.shelf = Path(self.temp.name) / "shelf"
        (self.root / ".harness" / "policies").mkdir(parents=True)
        (self.shelf).mkdir()

    def task(self, name: str, days_ago: float) -> Path:
        folder = self.shelf / name / tasks.STATE_DIR
        folder.mkdir(parents=True)
        (folder / "task.json").write_text("{}", encoding="utf-8")
        (folder / chatrounds.FILE_NAME).write_text("{}\n", encoding="utf-8")
        at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - days_ago * 86400))
        path = self.shelf / taskarchive.INDEX_JSON
        known = json.loads(path.read_text(encoding="utf-8"))["tasks"] if path.exists() else []
        path.write_text(json.dumps({"tasks": known + [{"name": name, "archived_at": at}]}), encoding="utf-8")
        return folder

    def test_only_the_old_transcript_goes_and_the_task_stays(self) -> None:
        old, new = self.task("old", 31), self.task("new", 29)
        self.assertEqual(taskarchive.prune_transcripts(self.root, str(self.shelf)), ["old"])
        self.assertFalse((old / chatrounds.FILE_NAME).exists())
        self.assertTrue((old / "task.json").exists())
        self.assertTrue((new / chatrounds.FILE_NAME).exists())

    def test_zero_days_keeps_all_and_a_broken_index_stops_nothing(self) -> None:
        old = self.task("old", 400)
        with mock.patch("core.config.policy_or_empty", return_value={"transcript": {"keep_days": 0}}):
            self.assertEqual(taskarchive.prune_transcripts(self.root, str(self.shelf)), [])
        self.assertTrue((old / chatrounds.FILE_NAME).exists())
        (self.shelf / taskarchive.INDEX_JSON).write_text("{ broken", encoding="utf-8")
        self.assertEqual(taskarchive.prune_transcripts(self.root, str(self.shelf)), [])
        self.assertEqual(taskarchive.prune_transcripts(self.root, ""), [])


if __name__ == "__main__":
    unittest.main()
