"""autorun 1.8, step 9: the Start form, the Start order, Stop, the run card, and the Trace of a run.

The server tests run the board with a link to a fake host (as test_chatsend does) that has one chat of this folder and a model list with a Claude and a GPT model.
"""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from support import HarnessTestCase
from taskcase import TASK
from test_chatsend import HAIKU, ROOT_STATE, SendCase
import test_chatsend
from test_vslink import until

from core import autorunfiles, logs
from modules.task import autorun, autorun_board, autorun_start, task as task_ops, tasktrace, vslink

TODO = "# TODO\n\n- [ ] edit a.sql (model: claude-sonnet-5.5)\n- [ ] write the test note\n"
GPT = {"id": "gpt-6-luna", "name": "GPT 6 Luna", "policyState": "enabled", "configSchema": {"properties": {"thinkingLevel": {"enum": ["low", "medium"], "default": "low"}}}}
SONNET = {"id": "claude-sonnet-5.5", "name": "Claude Sonnet 5.5", "policyState": "enabled"}
MODELS = {"agents": [{"provider": ROOT_STATE["agents"][0]["provider"], "models": [GPT, SONNET, HAIKU]}]}


class BoardCase(SendCase):
    """The board with a bound idle chat, a task ready for autorun, and a paired browser."""

    def setUp(self) -> None:
        for patch in (mock.patch.object(test_chatsend, "ROOT_STATE", MODELS), mock.patch.object(vslink, "RELAY_EVERY", 0.05), mock.patch.object(autorun_start, "COMPACT_SETTLE", 0.2)):
            patch.start()
            self.addCleanup(patch.stop)
        super().setUp()
        self.approve_plan()
        (self.root / TASK / "TODO.md").write_text(TODO, encoding="utf-8")
        self.prompt("[review]=1 go")
        self.agent_stopped()

    def body(self, **fields: Any) -> Dict[str, Any]:
        return {"step": "act", "code": autorun.code_source(self.root, TASK, self.data())[:6], "manager_model": "claude-haiku-5.5", "worker": {"default": "claude-sonnet-5.5"},
                "compact_percent": 70, "minutes": 60, "budget": {"add_credits": 500}, **fields}

    def sends(self) -> List[Dict[str, Any]]:
        return [item["action"] for item in self.dispatched() if item["action"].get("type") == "chat/turnStarted"]

    def config_actions(self) -> List[Dict[str, Any]]:
        return [item["action"] for item in self.dispatched() if item["action"].get("type") == "chat/configChanged"]

    def idle(self) -> None:
        self.items[0]["status"] = 1
        self.host.push({"jsonrpc": "2.0", "method": "root/sessionSummaryChanged", "params": {"session": "ahp-session:/abc", "changes": {"status": 1}}})


class StartTests(BoardCase):
    def test_the_form_offers_claude_models_only_four_spend_choices_and_the_open_steps(self) -> None:
        status, data, _headers = self.post("/api/autorun/on", {"step": "preview"})
        self.assertEqual(status, 200, data)
        self.assertEqual([item["id"] for item in data["manager_models"]], ["claude-sonnet-5.5", "claude-haiku-5.5"])
        self.assertEqual((data["manager_default"], data["worker_default"]), ("claude-haiku-5.5", "claude-sonnet-5.5"))  # the model the steps name is the worker's default
        self.assertEqual(data["budget"]["choices"], [None, 500, 1000, 2000])
        self.assertEqual([(item["n"], item["model"]) for item in data["steps"]], [(1, "claude-sonnet-5.5"), (2, "")])
        self.assertEqual((data["problems"], data["ask"] != ""), ([], True))
        self.assertIn("gpt-6-luna", [item["id"] for item in data["models"]])
        self.assertFalse(self.data().get("autorun"))  # a preview switches nothing on

    def test_a_gpt_scheduler_model_is_refused_and_nothing_is_switched_on(self) -> None:
        status, data, _headers = self.post("/api/autorun/on", self.body(manager_model="gpt-6-luna"))
        self.assertEqual((status, data["ok"]), (409, False))
        self.assertIn("Claude", data["error"])
        status, data, _headers = self.post("/api/autorun/on", self.body(manager_model="nothing-like-it"))
        self.assertEqual(status, 409)
        status, data, _headers = self.post("/api/autorun/on", self.body(worker={"default": "not-listed"}))
        self.assertEqual(status, 409)
        for bad in ({"minutes": 0}, {"compact_percent": 120}, {"budget": {"add_credits": -5}}, {"budget": {}}):
            self.assertEqual(self.post("/api/autorun/on", self.body(**bad))[0], 409, bad)
        self.assertFalse(self.data().get("autorun"))
        self.assertEqual((self.sends(), self.config_actions()), ([], []))

    def test_a_wrong_code_and_an_unpaired_browser_are_refused(self) -> None:
        status, data, _headers = self.post("/api/autorun/on", self.body(code="nope"))
        self.assertEqual((status, data["ok"]), (409, False))
        self.assertFalse(self.data().get("autorun"))
        self.assertEqual(self.request("POST", "/api/autorun/on", {"task": TASK, **self.body()})[0], 403)
        self.assertEqual(self.request("POST", "/api/autorun/stop", {"task": TASK})[0], 403)
        self.assertEqual(self.request("GET", "/api/autorun?task=" + TASK)[0], 403)
        self.assertEqual(self.config_actions(), [])

    def test_haiku_is_accepted_the_options_are_kept_and_the_start_order_runs_on_the_chat_as_it_is(self) -> None:
        status, data, _headers = self.post("/api/autorun/on", self.body())
        self.assertEqual((status, data["ok"], data["autorun"]), (200, True, "on"))
        made = autorun.config_of(self.root, TASK)
        self.assertEqual(made["manager_model"]["id"], "claude-haiku-5.5")
        self.assertEqual(made["manager_model"]["config"]["thinkingLevel"], "low")
        self.assertEqual((made["worker"]["default"], made["worker"]["allowed"], made["minutes"], made["compact_percent"], made["budget"]["add_credits"]),
                         ("claude-sonnet-5.5", ["claude-sonnet-5.5"], 60, 70, 500))
        self.assertTrue(until(lambda: self.config_actions()), self.vs.status())
        self.assertEqual(self.config_actions()[0]["config"], {"autoApprove": "autoApprove"})  # Allow all first
        self.assertTrue(until(lambda: [item for item in self.sends() if item["message"]["text"] == "/compact"]))  # the chat has history: compact
        self.assertEqual(self.sends()[0]["message"].get("model"), None)
        self.assertFalse(until(lambda: len(self.sends()) > 1, 0.6))  # nothing else is sent while it compacts (the relay waits too)
        self.idle()  # the compaction is over
        self.assertTrue(until(lambda: len(self.sends()) == 2), self.vs.status())
        first = self.sends()[1]["message"]
        self.assertEqual(first["text"], "/harness-autorun")
        self.assertEqual(first["model"]["id"], "claude-haiku-5.5")
        self.assertEqual(first["model"]["config"]["thinkingLevel"], "low")
        self.assertEqual(self.run_state()["state"], "on")

    def run_state(self) -> Dict[str, Any]:
        return self.data()["autorun"]


class StopTests(BoardCase):
    def test_stop_turns_autorun_off_as_the_person_and_stops_the_turn_of_the_chat(self) -> None:
        self.assertEqual(self.post("/api/autorun/on", self.body())[0], 200)
        self.assertTrue(until(lambda: [item for item in self.sends() if item["message"]["text"] == "/compact"]), self.vs.status())  # a turn runs now
        self.busy()  # and the host says so
        status, data, _headers = self.post("/api/autorun/stop", {})
        self.assertEqual((status, data["ok"], data["autorun"], data["chat_stopped"]), (200, True, "off", True))
        run = self.data()["autorun"]
        self.assertEqual((run["state"], run["stopped"]["why"]), ("off", "person"))
        self.assertTrue(until(lambda: [item for item in self.dispatched() if item["action"].get("type") == "chat/turnCancelled"]))
        self.idle()
        self.assertFalse(until(lambda: len(self.sends()) > 1, 0.8))  # the order was dropped and the relay finds autorun off: nothing wakes the agent
        self.assertEqual(self.post("/api/autorun/stop", {})[0], 409)  # it is off already

    def test_stop_with_no_turn_running_still_turns_autorun_off(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["autorun"] = {"state": "on", "started_at": datetime.now(timezone.utc).isoformat(), "until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), "steps": 0, "max_steps": 20}
        status, data, _headers = self.post("/api/autorun/stop", {})
        self.assertEqual((status, data["autorun"], data["chat_stopped"]), (200, "off", False))
        self.assertEqual(self.data()["autorun"]["stopped"]["why"], "person")


class CardTests(BoardCase):
    def put(self, *rows: Dict[str, Any]) -> None:
        for row in rows:
            autorunfiles.ledger_append(self.root, TASK, row)

    def test_the_card_is_the_status_and_the_ledger_paired_by_call(self) -> None:
        self.assertEqual(self.post("/api/autorun/on", self.body())[0], 200)
        now = datetime.now(timezone.utc)
        at = lambda seconds: (now + timedelta(seconds=seconds)).isoformat()  # noqa: E731
        self.put({"event": "start", "call": 1, "at": at(1), "step": 1, "text": "edit a.sql", "model": "claude-sonnet-5.5"},
                 {"event": "end", "call": 1, "at": at(30), "result": "done", "credits": 4.5, "files": ["DEV/a.sql"], "denied": 1, "held": 2},
                 {"event": "start", "call": 2, "at": at(40), "step": 2, "text": "write the test note", "model": "claude-sonnet-5.5"})
        status, data, _headers = self.request("GET", "/api/autorun?task=" + TASK, cookie=self.cookie)
        self.assertEqual(status, 200, data)
        card = data["card"]
        self.assertEqual((card["autorun"], card["show"], card["total"], card["left"], card["done"], card["parked"]), ("on", True, 2, 2, 0, 0))
        self.assertEqual(card["budget_add"], 500)
        self.assertEqual([(row["call"], row["step"], row["result"], row["held"], row["denied"], row["credits"]) for row in card["rows"]], [(1, 1, "done", 2, 1, 4.5), (2, 2, "running", 0, 0, None)])
        self.assertEqual(card["current"]["n"], 2)  # the step of the call that runs
        self.assertGreater(card["left_s"], 3000)
        self.assertEqual((card["questions_open"], card["questions_file"]), (0, ""))
        self.assertEqual(card["warnings"], [])
        self.post("/api/autorun/stop", {})
        card = self.request("GET", "/api/autorun?task=" + TASK, cookie=self.cookie)[1]["card"]
        self.assertEqual((card["autorun"], card["show"], card["stopped"]["why"]), ("off", True, "person"))
        self.assertTrue(card["stopped"]["text"])
        self.assertIsNone(card["current"])

    def test_the_rows_of_an_earlier_run_are_left_out_and_a_task_with_no_run_shows_no_card(self) -> None:
        card = self.request("GET", "/api/autorun?task=" + TASK, cookie=self.cookie)[1]["card"]
        self.assertEqual((card["show"], card["has_run"], card["rows"]), (False, False, []))
        self.put({"event": "start", "call": 1, "at": "2020-01-01T00:00:00+00:00", "step": 1, "text": "old", "model": "m"}, {"event": "end", "call": 1, "at": "2020-01-01T00:01:00+00:00", "result": "done"})
        self.assertEqual(self.post("/api/autorun/on", self.body())[0], 200)
        self.assertEqual(self.request("GET", "/api/autorun?task=" + TASK, cookie=self.cookie)[1]["card"]["rows"], [])

    def test_a_hundred_steps_and_a_long_text_are_cut_to_what_a_card_lists(self) -> None:
        rows = []
        for call in range(1, 351):
            rows += [{"event": "start", "call": call, "at": "2999-01-01T00:00:00+00:00", "step": call, "text": "x" * 300, "model": "m"}, {"event": "end", "call": call, "at": "2999-01-01T00:00:01+00:00", "result": "done"}]
        self.put(*rows)
        with task_ops.locked(self.root, TASK) as data:
            data["autorun"] = {"state": "off", "started_at": "2000-01-01T00:00:00+00:00", "stopped": {"why": "done", "at": datetime.now(timezone.utc).isoformat()}}
        card = self.request("GET", "/api/autorun?task=" + TASK, cookie=self.cookie)[1]["card"]
        self.assertEqual((len(card["rows"]), card["rows_cut"], len(card["rows"][0]["text"])), (autorun_board.ROWS_SHOWN, 350 - autorun_board.ROWS_SHOWN, autorun_board.TEXT_SHOWN))


class OrderTests(unittest.TestCase):
    """`autorun_start.step` with a made chat and a fake `do`: the order of the stages, the warning, the failures."""

    def setUp(self) -> None:
        self.sent: List[Any] = []
        self.answer: Optional[BaseException] = None

    def do(self, kind: str, text: str, model: Optional[Dict[str, Any]], plan: Optional[Dict[str, Any]]) -> Optional[BaseException]:
        self.sent.append((kind, text, model, plan))
        return self.answer

    def test_the_model_check_is_a_warning_and_never_stops_the_run(self) -> None:
        self.assertTrue(autorun_start.same_model("claude-haiku-5.5", "claude-haiku-5.5"))
        self.assertTrue(autorun_start.same_model("claude-haiku-5.5", "Claude-Haiku-5.5-20261101"))
        self.assertFalse(autorun_start.same_model("claude-haiku-5.5", "gpt-6-luna"))
        self.assertFalse(autorun_start.same_model("claude-haiku-5.5", ""))
        turn = {"id": "t2", "message": {"text": "/harness-autorun"}, "usage": {"model": "gpt-6-luna"}}
        self.assertEqual(autorun_start.usage_model(autorun_start.turn_of({"turns": [{"id": "t1", "message": {"text": "/harness-autorun"}}], "activeTurn": turn}, "/harness-autorun", ["t1"])), "gpt-6-luna")
        self.assertIsNone(autorun_start.turn_of({"turns": [turn]}, "/harness-autorun", ["t2"]))  # an older run's turn is not this one's


class OrderFlowTests(BoardCase):
    def test_a_first_turn_on_another_model_adds_the_warning_and_the_run_goes_on(self) -> None:
        self.assertEqual(self.post("/api/autorun/on", self.body())[0], 200)
        order = {"stage": "verify", "model": {"id": "claude-haiku-5.5"}, "stage_at": datetime.now(timezone.utc).isoformat(), "before": ["t0"], "sent": "", "allow": "", "busy": False}
        state = {"turns": [{"id": "t0", "message": {"text": "/harness-autorun"}, "usage": {"model": "old"}}, {"id": "t1", "message": {"text": "/harness-autorun"}, "usage": {"model": "gpt-6-luna"}}]}
        self.vs.cancel_start(TASK)
        self.assertEqual(autorun_start.step(self.root, TASK, order, state, "busy", lambda *a: None), "done")
        run = self.data()["autorun"]
        self.assertEqual((run["state"], run["warnings"]), ("on", ["model-not-switched"]))
        self.assertEqual((run["start"]["model_wanted"], run["start"]["model_seen"]), ("claude-haiku-5.5", "gpt-6-luna"))
        card = self.request("GET", "/api/autorun?task=" + TASK, cookie=self.cookie)[1]["card"]
        self.assertEqual(card["warnings"], ["model-not-switched"])

    def test_a_chat_with_no_history_is_not_compacted_and_a_compact_that_never_ends_ends_the_run(self) -> None:
        self.assertEqual(self.post("/api/autorun/on", self.body())[0], 200)
        self.vs.cancel_start(TASK)
        sent: List[Any] = []
        now = datetime.now(timezone.utc)
        order = autorun_start.new_order({"id": "claude-haiku-5.5"}, "autoApprove", now)
        do = lambda kind, text, model, plan: sent.append((kind, text)) or None  # noqa: E731
        autorun_start.step(self.root, TASK, order, {"turns": []}, "idle", do, now)
        self.assertEqual((order["stage"], sent), ("send", [("config", "")]))
        autorun_start.step(self.root, TASK, order, {"turns": []}, "idle", do, now)
        self.assertEqual((order["stage"], sent[-1]), ("verify", ("relay", "/harness-autorun")))
        stuck = autorun_start.new_order({"id": "claude-haiku-5.5"}, "", now)
        stuck["stage"], stuck["sent"], stuck["stage_at"] = "compact", now.isoformat(), now.isoformat()
        later = now + timedelta(seconds=autorun_start.COMPACT_WAIT + 5)
        self.assertEqual(autorun_start.step(self.root, TASK, stuck, {"turns": [{"id": "t"}]}, "busy", do, later), "failed")
        run = self.data()["autorun"]
        self.assertEqual((run["state"], run["stopped"]["why"]), ("off", "error"))


class TraceTests(HarnessTestCase):
    """The Trace of a task that had an autorun run lists every worker; another task keeps the newest 12."""

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"COPILOT_HOME": self.env["COPILOT_HOME"]})
        patcher.start()
        self.addCleanup(patcher.stop)
        tasktrace._found.clear()
        self.session = "main-session-1"
        self.created = "2026-10-31T00:00:00+00:00"
        folder = Path(self.env["COPILOT_HOME"]) / "session-state" / self.session
        folder.mkdir(parents=True, exist_ok=True)
        self.agents = [f"{index:08d}-1111-2222-3333-444444444444" for index in range(1, 25)]
        lines = [json.dumps({"type": "subagent.started", "timestamp": f"2026-10-31T01:{index:02d}:00.000Z", "agentId": agent, "data": {"agentName": "worker"}}) for index, agent in enumerate(self.agents, 1)]
        (folder / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        for index, agent in enumerate(self.agents, 1):
            path = logs.session_log_path(self.root, "vscode", agent)
            path.parent.mkdir(parents=True, exist_ok=True)
            stamp = f"2026-10-31T01:{index:02d}:10+00:00"
            row = {"surface": "vscode", "session_id": agent, "at": stamp, "event": "PreToolUse", "tool_name": "Read", "tool_kind": "read", "decision": "none"}
            path.write_text(json.dumps(row) + "\n" + json.dumps(dict(row, at=stamp.replace(":10+", ":11+"), event="PostToolUse")) + "\n", encoding="utf-8")

    def sources(self, data: Dict[str, Any]) -> int:
        return len({item.get("source") and item["at"] for item in tasktrace.of_task(self.root, data)["entries"] if item.get("source")})

    def test_every_worker_of_a_run_is_listed_and_other_tasks_keep_the_newest_twelve(self) -> None:
        plain = {"session_id": self.session, "surface": "vscode", "created_at": self.created}
        self.assertEqual(self.sources(plain), tasktrace.MAX_SUBAGENTS)
        ran = dict(plain, autorun={"state": "off", "started_at": "2026-10-31T01:00:00+00:00"})
        self.assertEqual(self.sources(ran), 24)
        self.assertEqual(len(tasktrace.subagents(self.root, self.session, 0.0)), tasktrace.MAX_SUBAGENTS)  # the default stays for the other callers
        self.assertTrue(tasktrace.has_run(ran))
        self.assertFalse(tasktrace.has_run(plain))
        self.assertFalse(tasktrace.has_run({"autorun": {"state": "off"}}))


if __name__ == "__main__":
    unittest.main()
