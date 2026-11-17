"""autorun spend limit (1.8.0, step 4): the Credits of a run are read from the new bytes of the session's events file."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional
from unittest import mock

import support  # noqa: F401  (puts the engine on sys.path)
from core import copilot_events
from modules.task import autorun, autorun_spend
from taskcase import NAME, SESSION, TASK
from test_autorun import AutorunCase

NANO = 1_000_000_000


def usage(credits: float, agent: str = "") -> str:
    row: Dict[str, Any] = {"type": "session.usage_record", "timestamp": "2026-01-01T00:00:00Z", "data": {"usage": {"model": "m", "copilotUsage": {"totalNanoAiu": int(credits * NANO)}}}}
    if agent:
        row["agentId"] = agent
    return json.dumps(row) + "\n"


def started(agent: str, name: str) -> str:
    return json.dumps({"type": "subagent.started", "timestamp": "2026-01-01T00:00:00Z", "agentId": agent, "data": {"agentName": name}}) + "\n"


class Home:
    """A Copilot home with one session; the events file grows with `add`."""

    def __init__(self, test: unittest.TestCase, session: str = "s-1") -> None:
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        patch = mock.patch.dict(os.environ, {copilot_events.HOME_ENV: folder.name})
        patch.start()
        test.addCleanup(patch.stop)
        self.folder, self.session = Path(folder.name), session
        self.path(session).parent.mkdir(parents=True)
        self.path(session).write_text("", encoding="utf-8")

    def path(self, session: Optional[str] = None) -> Path:
        return self.folder / "session-state" / (session or self.session) / copilot_events.FILE_NAME

    def add(self, text: str, session: Optional[str] = None) -> None:
        target = self.path(session)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(text)


def task_data(session: str = "s-1", cost: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"session_id": session, "autorun": {"state": "on", "cost": cost if cost is not None else {"session": session, "pos": 0, "nano": 0}}}


class SpendReadTests(unittest.TestCase):
    def test_two_reads_add_up_and_the_position_is_stored(self) -> None:
        home = Home(self)
        data = task_data()
        home.add(usage(1.5) + usage(2.0))
        self.assertAlmostEqual(autorun_spend.credits_spent(data) or 0, 3.5)
        first = data["autorun"]["cost"]
        self.assertEqual((first["pos"], first["nano"]), (home.path().stat().st_size, 3.5 * NANO))
        home.add(usage(0.5))
        self.assertAlmostEqual(autorun_spend.credits_spent(data) or 0, 4.0)
        self.assertEqual(autorun_spend.credits_spent(data), 4.0)  # nothing new: the same, and not counted twice

    def test_only_the_new_bytes_are_read(self) -> None:
        home = Home(self)
        home.add(usage(9.0))
        data = task_data(cost={"session": "s-1", "pos": home.path().stat().st_size, "nano": 0})
        home.add(usage(1.0))
        self.assertAlmostEqual(autorun_spend.credits_spent(data) or 0, 1.0)  # what was there before the position is not counted

    def test_a_half_written_last_line_waits_for_the_next_read(self) -> None:
        home = Home(self)
        line = usage(2.0)
        home.add(usage(1.0) + line[:25])
        data = task_data()
        self.assertAlmostEqual(autorun_spend.credits_spent(data) or 0, 1.0)
        self.assertEqual(data["autorun"]["cost"]["pos"], len(usage(1.0).encode()))
        home.add(line[25:])
        self.assertAlmostEqual(autorun_spend.credits_spent(data) or 0, 3.0)

    def test_another_session_is_read_from_the_start_and_what_was_counted_stays(self) -> None:
        home = Home(self)
        data = task_data()
        home.add(usage(1.0))
        autorun_spend.credits_spent(data)
        data["session_id"] = "s-2"
        home.add(usage(2.0) + usage(0.25), session="s-2")
        self.assertAlmostEqual(autorun_spend.credits_spent(data) or 0, 3.25)
        self.assertEqual(data["autorun"]["cost"]["session"], "s-2")

    def test_a_subagent_call_counts_in_the_limit(self) -> None:
        home = Home(self)
        home.add(usage(1.0) + started("a1", "worker") + usage(4.0, "a1"))
        self.assertAlmostEqual(autorun_spend.credits_spent(task_data()) or 0, 5.0)

    def test_it_matches_the_report_on_the_same_file(self) -> None:
        home = Home(self)
        home.add(json.dumps({"type": "user.message", "timestamp": "2026-01-01T00:00:00Z", "data": {"content": "x"}}) + "\n" + usage(1.25) + started("a1", "worker") + usage(2.5, "a1") + usage(0.125))
        report = copilot_events.read(home.path())
        assert report is not None
        self.assertAlmostEqual(autorun_spend.credits_spent(task_data()) or 0, sum(item["aiu"] for item in report["prompts"]))

    def test_unreadable_is_none(self) -> None:
        home = Home(self)
        self.assertEqual(autorun_spend.credits_spent(task_data()), 0.0)  # a file with no usage line: readable, nothing spent
        self.assertIsNone(autorun_spend.credits_spent({"autorun": {"cost": {}}}))  # no session on the task
        self.assertIsNone(autorun_spend.credits_spent(task_data(session="gone")))  # no file
        home.path().chmod(0)
        self.addCleanup(home.path().chmod, 0o600)
        if os.access(home.path(), os.R_OK):
            self.skipTest("this user reads files whatever their mode")
        self.assertIsNone(autorun_spend.credits_spent(task_data()))

    def test_a_run_with_no_start_counts_from_where_the_file_ends_now(self) -> None:
        home = Home(self)
        home.add(usage(7.0))
        data = task_data(cost={"session": "", "pos": 0, "nano": 0})
        self.assertEqual(autorun_spend.credits_spent(data), 0.0)
        home.add(usage(1.0))
        self.assertAlmostEqual(autorun_spend.credits_spent(data) or 0, 1.0)
        self.assertEqual(autorun_spend.fresh_cost(task_data())["pos"], home.path().stat().st_size)


class BetweenTests(unittest.TestCase):
    def test_only_the_calls_of_the_worker_in_the_range_count(self) -> None:
        home = Home(self)
        home.add(usage(1.0))
        start = autorun_spend.position(task_data())
        home.add(started("w1", "worker") + usage(3.0, "w1") + usage(0.5) + started("r1", "reviewer") + usage(2.0, "r1") + usage(1.5, "w1"))
        stop = autorun_spend.position(task_data())
        home.add(usage(100.0))
        found = autorun_spend.credits_between(task_data(), start or 0, stop or 0)
        assert found is not None
        self.assertAlmostEqual(found["credits"], 4.5)
        self.assertAlmostEqual(found["all"], 7.0)
        self.assertFalse(found["approx"])

    def test_a_subagent_whose_start_is_before_the_range_makes_it_approximate(self) -> None:
        home = Home(self)
        home.add(started("w1", "worker"))
        start = autorun_spend.position(task_data())
        home.add(usage(2.0, "w1"))
        found = autorun_spend.credits_between(task_data(), start or 0, autorun_spend.position(task_data()) or 0)
        assert found is not None
        self.assertTrue(found["approx"])
        self.assertEqual(found["credits"], 0.0)

    def test_unreadable_is_none(self) -> None:
        Home(self)
        self.assertIsNone(autorun_spend.credits_between(task_data(session="gone"), 0, 10))
        self.assertIsNone(autorun_spend.position(task_data(session="gone")))


class ModelChangeTests(unittest.TestCase):
    def test_the_report_reads_no_model_change(self) -> None:
        """A `session.model_change` with `source: agent` is one per subagent call. The report takes the model from `session.start`, a subagent's from its own events, so none is read here."""
        home = Home(self)
        home.add(json.dumps({"type": "session.start", "timestamp": "2026-01-01T00:00:00Z", "data": {"selectedModel": "main-model"}}) + "\n"
                 + json.dumps({"type": "user.message", "timestamp": "2026-01-01T00:00:00.500Z", "data": {"content": "x"}}) + "\n"
                 + json.dumps({"type": "session.model_change", "timestamp": "2026-01-01T00:00:01Z", "data": {"source": "agent", "newModel": "sub-model"}}) + "\n")
        report = copilot_events.read(home.path())
        assert report is not None
        self.assertEqual(report["model"], "main-model")


class BudgetReadTests(AutorunCase):
    """The stop check, with the real reading and no patch."""

    def ended(self) -> str:
        autorun.on_stop(self.root, TASK)
        run = self.run_state()
        return run["stopped"]["why"] if run["state"] == "off" else ""

    def start(self, budget: Optional[Dict[str, Any]]) -> Home:
        self.prepare()
        home = Home(self, SESSION)
        home.add(usage(500.0))  # spent before the run: not counted
        self.on(options={"budget": budget})
        return home

    def test_the_limit_reached_ends_the_run_with_budget(self) -> None:
        home = self.start({"base_credits": 0, "add_credits": 100})
        home.add(usage(60.0))
        self.assertEqual(self.ended(), "")
        self.assertAlmostEqual(self.run_state()["cost"]["nano"], 60.0 * NANO)  # saved by the hook
        home.add(usage(45.0))
        self.assertEqual(self.ended(), "budget")

    def test_no_limit_never_stops_it(self) -> None:
        home = self.start(None)
        home.add(usage(10 ** 6))
        self.assertEqual(self.ended(), "")

    def test_an_unreadable_file_never_stops_it(self) -> None:
        home = self.start({"base_credits": 0, "add_credits": 1})
        home.path().unlink()
        self.assertEqual(self.ended(), "")
        self.assertFalse(autorun.status(self.root, NAME)["cost_readable"])


class LedgerCreditsTests(AutorunCase):
    """The `end` line of a worker call carries the worker's Credits between its `start` and its end."""

    def test_the_end_line_has_the_worker_credits_of_that_call(self) -> None:
        self.prepare()
        home = Home(self, SESSION)
        home.add(usage(500.0))
        self.on(options={"budget": None})
        autorun.ledger_start(self.root, TASK, {"prompt": "x"}, SESSION)
        home.add(started("a1", "worker") + usage(4.5, "a1") + usage(1.0))
        autorun.ledger_end(self.root, TASK, "DONE: x | files: - | check: none")
        end = [row for row in autorun.ledger_read(self.root, TASK) if row["event"] == "end"][-1]
        self.assertAlmostEqual(end["credits"], 4.5)
        self.assertNotIn("approx", end)

    def test_an_unreadable_file_leaves_credits_empty(self) -> None:
        self.prepare()
        home = Home(self, SESSION)
        self.on(options={"budget": None})
        autorun.ledger_start(self.root, TASK, {"prompt": "x"}, SESSION)
        home.path().unlink()
        autorun.ledger_end(self.root, TASK, "DONE: x")
        end = [row for row in autorun.ledger_read(self.root, TASK) if row["event"] == "end"][-1]
        self.assertIsNone(end["credits"])


if __name__ == "__main__":
    unittest.main()
