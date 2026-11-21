"""What an open task runs right now (`taskagents.of`, the `agents` key of a board row)."""

from __future__ import annotations

import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from support import subagent_start, subagent_stop
from taskcase import NAME, SESSION, TASK, TaskCase

from core import tasks
from core.autorunfiles import ledger_append
from core.paths import utc_now
from core.state import update_state
from modules.task import taskagents, taskboard


class AgentsCase(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.new()

    def agents(self) -> Any:
        return taskagents.of(self.root, TASK, tasks.read(self.root, TASK))

    def edit_task(self, change: Any) -> None:
        path = self.task / ".task" / "task.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def subs(self) -> Dict[str, int]:
        return {item["type"]: item["n"] for item in self.agents()["subs"]}

    def test_nothing_runs(self) -> None:
        self.assertEqual(self.agents(), {"subs": [], "autorun": None, "review": None, "mapper": None})

    def test_running_subagents_are_grouped_and_a_stop_takes_one_away(self) -> None:
        for name in ("reviewer", "worker", "reviewer"):
            self.hook(subagent_start(SESSION, name))
        found = self.agents()["subs"]
        self.assertEqual([(item["type"], item["n"]) for item in found], [("reviewer", 2), ("worker", 1)])
        self.assertTrue(all(item["since"].endswith("Z") for item in found))
        self.hook(subagent_stop(SESSION, "reviewer"))
        self.assertEqual(self.subs(), {"reviewer": 1, "worker": 1})

    def test_an_entry_older_than_the_ttl_is_not_counted(self) -> None:
        old = {"agent_id": "reviewer@1", "agent_type": "reviewer", "at": time.time() - 7200, "awaiting_child": False}
        update_state(self.root, "vscode", SESSION, lambda state: state["subagents"]["active"].append(old))
        self.assertEqual(self.agents()["subs"], [])

    def test_the_since_is_the_oldest_of_the_group(self) -> None:
        now = time.time()
        update_state(self.root, "vscode", SESSION, lambda state: state["subagents"]["active"].extend(
            {"agent_id": f"worker@{n}", "agent_type": "worker", "at": now - age, "awaiting_child": False} for n, age in enumerate((10, 100))))
        found = self.agents()["subs"][0]
        self.assertEqual(found["n"], 2)
        self.assertEqual(found["since"], taskagents.iso(now - 100))

    def test_a_closed_task_has_no_agents(self) -> None:
        self.run_cli("task", "close", "--task", TASK)
        rows = {row["task"]: row for row in taskboard.board_rows(self.root, True)[0]["tasks"]}
        self.assertIsNone(rows[TASK]["agents"])

    def test_the_board_row_carries_agents(self) -> None:
        self.hook(subagent_start(SESSION, "reviewer"))
        rows = {row["task"]: row for row in taskboard.board_rows(self.root, True)[0]["tasks"]}
        self.assertEqual(rows[TASK]["agents"]["subs"][0]["n"], 1)

    def test_a_running_autorun_step(self) -> None:
        (self.task / "TODO.md").write_text("- [x] one\n- [ ] " + "long " * 40 + "\n- [ ] three\n", encoding="utf-8")
        began = utc_now()
        self.edit_task(lambda data: data.__setitem__("autorun", {"state": "on", "started_at": began}))
        self.assertIsNone(self.agents()["autorun"], "no worker call yet")
        ledger_append(self.root, TASK, {"event": "start", "call": 1, "at": utc_now(), "step": 2, "text": "long " * 40})
        found = self.agents()["autorun"]
        self.assertEqual((found["step"], found["total"], len(found["text"])), (2, 3, 120))
        ledger_append(self.root, TASK, {"event": "end", "call": 1, "at": utc_now(), "result": "done"})
        self.assertIsNone(self.agents()["autorun"])

    def test_autorun_off_or_an_earlier_run_shows_nothing(self) -> None:
        ledger_append(self.root, TASK, {"event": "start", "call": 1, "at": utc_now(), "step": 1, "text": "x"})
        self.assertIsNone(self.agents()["autorun"], "autorun is off")
        later = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        self.edit_task(lambda data: data.__setitem__("autorun", {"state": "on", "started_at": later}))
        self.assertIsNone(self.agents()["autorun"], "the start line is from before this run")

    def test_a_check_round_without_a_verdict_is_pending(self) -> None:
        def pending(data: Dict[str, Any]) -> None:
            data["review"] = {"n": 1, "rounds": [{"number": 1, "task_round": data["round"], "verdict": "FAIL"}, {"number": 2, "task_round": data["round"]}]}
        self.edit_task(pending)
        self.assertEqual(self.agents()["review"], {"round": 2})
        self.edit_task(lambda data: data["review"]["rounds"][1].update(verdict="PASS"))
        self.assertIsNone(self.agents()["review"])

    def test_the_mapper_grant_counts_only_while_it_is_good(self) -> None:
        def grant(until: datetime) -> None:
            update_state(self.root, "vscode", SESSION, lambda state: state["modules"].setdefault("task", {}).__setitem__("mapreduce", {"limit": 5, "used": 2, "until": until.isoformat()}))
        grant(datetime.now(timezone.utc) + timedelta(minutes=10))
        self.assertEqual(self.agents()["mapper"], {"started": 2, "limit": 5})
        grant(datetime.now(timezone.utc) - timedelta(minutes=1))
        self.assertIsNone(self.agents()["mapper"])

    def test_a_broken_state_file_gives_empty_values(self) -> None:
        self.state_file(SESSION).write_text("{not json", encoding="utf-8")
        self.assertEqual(self.agents(), {"subs": [], "autorun": None, "review": None, "mapper": None})
        self.state_file(SESSION).write_text(json.dumps({"subagents": {"active": [{"at": "x"}, 5, {"agent_type": "worker", "at": time.time()}]}, "modules": 3}), encoding="utf-8")
        self.assertEqual(self.subs(), {"worker": 1})

    def test_a_task_json_that_is_not_known_gives_none(self) -> None:
        self.assertIsNone(taskagents.of(self.root, TASK, None))


if __name__ == "__main__":
    unittest.main()
