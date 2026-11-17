"""autorun 1.8, steps 7 and 8: the board's relay (it wakes the agent) and the pit stop (it ends a turn to compact the chat).

`autorun_relay.step` is tested with a made chat state, a fake send and a made clock. The last class runs the link thread against a fake host.
"""

from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest import mock

import support  # noqa: F401  (puts the engine on sys.path)
from taskcase import SESSION, TASK
from test_ahp import FakeHost, TOKEN
from test_autorun import AutorunCase
from test_vslink import summary, until

from core import ahp
from modules.task import autorun, autorun_relay, vslink

MODEL = {"id": "gpt-6-luna", "config": {"thinkingLevel": "low"}}
WINDOWS: Dict[str, Dict[str, int]] = {}


def chat(result: str = "complete", turn: str = "t1", percent: Optional[float] = 10, model: Optional[Dict[str, Any]] = MODEL, error: str = "", started: Optional[str] = None, running: bool = False) -> Dict[str, Any]:
    """A trimmed chat whose last turn ended as `result`; `percent` of a window of 100 is used."""
    done = {"id": turn, "state": result, "message": {"text": "go", "model": model} if model else {"text": "go"}, "responseParts": [{"kind": "error", "message": error}] if error else [],
            "usage": {"model": "gpt-6-luna", "inputTokens": percent, "outputTokens": 0, "contextUsage": {"tokenLimit": 100}} if percent is not None else None}
    if started:
        done["startedAt"] = started
    state: Dict[str, Any] = {"turns": [done], "activeTurn": None}
    if running:
        state["turns"], state["activeTurn"] = [], {key: value for key, value in done.items() if key != "state"}
    return state


class RelayCase(AutorunCase):
    def setUp(self) -> None:
        super().setUp()
        self.prepare()
        self.on()
        self.t0 = datetime.now(timezone.utc)
        self.sent: List[Any] = []
        self.answer: Optional[BaseException] = None

    def send(self, text: str, model: Optional[Dict[str, Any]]) -> Optional[BaseException]:
        self.sent.append((text, model))
        return self.answer

    def look(self, state: Dict[str, Any], status: str = "idle", after: float = 0, windows: Optional[Dict[str, Any]] = None) -> str:
        return autorun_relay.step(self.root, TASK, state, status, windows or WINDOWS, self.send, self.t0 + timedelta(seconds=after))

    def run_state(self) -> Dict[str, Any]:
        return self.data()["autorun"]

    def set_run(self, **fields: Any) -> None:
        path = self.task / ".task" / "task.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["autorun"].update(fields)
        path.write_text(json.dumps(data), encoding="utf-8")

    def set_config(self, **fields: Any) -> None:
        path = self.task / ".task" / autorun.CONFIG_FILE
        found = json.loads(path.read_text(encoding="utf-8"))
        found.update(fields)
        path.write_text(json.dumps(found), encoding="utf-8")


class RelayTests(RelayCase):
    def test_a_completed_turn_is_relayed_after_the_grace_with_the_model_of_the_chat_and_counted(self) -> None:
        grace = autorun.settings(self.root)["relay"]["grace_seconds"]
        self.assertEqual(self.look(chat()), "wait")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.look(chat(), after=grace - 1), "wait")
        self.assertEqual(self.sent, [])
        self.set_run(relay_wanted="2026-11-16T00:00:00+00:00", in_row=5)
        self.assertEqual(self.look(chat(), after=grace + 1), "relayed")
        self.assertEqual(self.sent, [(autorun.relay_text(self.root, TASK), MODEL)])  # fixed words; the model object of the chat's message, never another
        run = self.run_state()
        self.assertEqual((run["steps"], run["relay"]["count"], run["relay_wanted"], run["in_row"], run["relay"]["next_at"]), (1, 1, "", 0, ""))
        self.assertEqual(run["state"], "on")

    def test_the_model_falls_back_on_the_model_the_last_turn_ran_with_and_a_message_with_none_adds_nothing(self) -> None:
        self.look(chat(model=None))
        self.look(chat(model=None), after=60)
        self.assertEqual(self.sent[0][1], {"id": "gpt-6-luna"})
        self.assertIsNone(autorun_relay.model_of({"turns": [], "activeTurn": None}))

    def test_a_cancelled_turn_means_a_person_pressed_stop_and_nothing_is_sent(self) -> None:
        self.assertEqual(self.look(chat("cancelled")), "person")
        self.assertEqual(self.look(chat("cancelled"), after=600), "off")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.run_state()["stopped"]["why"], "person")
        self.assertEqual(self.run_state()["state"], "off")

    def test_a_turn_that_ended_before_the_run_began_is_not_the_runs_to_judge(self) -> None:
        old = (self.t0 - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        self.assertEqual(self.look(chat("cancelled", started=old)), "wait")
        self.assertEqual(self.run_state()["state"], "on")

    def test_a_chat_that_waits_for_the_person_or_works_is_left_alone(self) -> None:
        before = (self.task / ".task" / "task.json").read_bytes()
        self.assertEqual(self.look(chat(), "input", after=600), "input")
        self.assertEqual(self.look(chat(running=True), "busy", after=600), "busy")
        self.assertEqual(self.look(chat(), "unknown", after=600), "unsure")
        self.assertEqual(self.sent, [])
        self.assertEqual((self.task / ".task" / "task.json").read_bytes(), before)  # no write for nothing

    def test_a_run_that_is_off_is_never_relayed(self) -> None:
        autorun.turn_off(self.root, TASK, interactive=True)
        self.assertEqual(self.look(chat(), after=600), "off")
        self.assertEqual(self.sent, [])

    def test_a_wait_is_void_when_the_chat_gets_busy_and_the_grace_starts_again(self) -> None:
        self.look(chat())
        self.assertTrue(self.run_state()["relay"]["next_at"])
        self.look(chat(running=True), "busy", after=5)
        self.assertEqual(self.run_state()["relay"]["next_at"], "")
        self.assertEqual(self.look(chat(), after=600), "wait")  # a new wait, not an old one that has run out
        self.assertEqual(self.sent, [])

    def test_the_stop_facts_are_checked_before_a_relay_and_a_run_that_should_end_is_ended(self) -> None:
        self.set_run(steps=autorun.MIN_STEPS)
        self.look(chat())
        self.assertEqual(self.look(chat(), after=60), "steps")
        self.assertEqual((self.sent, self.run_state()["stopped"]["why"]), ([], "steps"))

    def test_the_end_of_time_ends_it_and_nothing_left_to_do_is_done(self) -> None:
        self.set_run(until=(self.t0 - timedelta(minutes=1)).isoformat())
        self.look(chat())
        self.assertEqual(self.look(chat(), after=60), "time")
        self.assertEqual(self.sent, [])

    def test_relays_and_pushes_share_the_step_limit(self) -> None:
        self.set_run(steps=autorun.MIN_STEPS - 1)
        self.look(chat())
        self.assertEqual(self.look(chat(), after=60), "relayed")
        self.assertEqual(self.run_state()["steps"], autorun.MIN_STEPS)
        self.look(chat(), after=61)
        self.assertEqual(self.look(chat(), after=200), "steps")

    def test_a_refused_send_counts_nothing_and_the_host_saying_no_counts_as_an_error(self) -> None:
        self.look(chat())
        self.answer = vslink.Refused("not-idle")
        self.assertEqual(self.look(chat(), after=60), "refused")
        self.assertEqual((self.run_state()["steps"], self.run_state().get("errors")), (0, 0))
        self.answer = ahp.AhpError("host said no")
        self.assertEqual(self.look(chat(), after=61), "backoff")
        self.assertEqual((self.run_state()["steps"], self.run_state()["errors"]), (0, 1))


class ErrorTests(RelayCase):
    def test_an_error_backs_off_60_300_900_and_the_third_in_a_row_ends_the_run_with_the_hosts_words(self) -> None:
        self.assertEqual(self.look(chat("error", "t1", error="rate limited\nsoon"), "error"), "backoff")
        self.assertEqual((self.run_state()["errors"], self.sent), (1, []))
        self.assertEqual(self.look(chat("error", "t1", error="x"), "error", after=59), "wait")
        self.assertEqual(self.look(chat("error", "t1", error="x"), "error", after=61), "relayed")  # the chat takes the next message after an error
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.look(chat("error", "t2", error="rate limited"), "error", after=70), "backoff")
        self.assertEqual(self.run_state()["errors"], 2)
        self.assertEqual(self.look(chat("error", "t2"), "error", after=70 + 299), "wait")
        self.assertEqual(self.look(chat("error", "t2"), "error", after=70 + 301), "relayed")
        self.assertEqual(self.look(chat("error", "t3", error="rate limited\nsoon"), "error", after=400), "error")
        self.assertEqual(len(self.sent), 2)
        run = self.run_state()
        self.assertEqual((run["state"], run["stopped"]["why"], run["stopped"]["detail"]), ("off", "error", "rate limited soon"))

    def test_the_wait_after_the_second_error_is_300_and_after_the_third_try_900(self) -> None:
        with mock.patch.object(autorun, "settings", return_value=dict(autorun.settings(self.root), relay={"grace_seconds": 0, "backoff": [60, 300, 900], "max_errors": 5})):
            for number, wait in enumerate((60, 300, 900, 900), 1):
                at = number * 5000
                self.look(chat("error", f"t{number}", error="x"), "error", after=at)
                found = datetime.fromisoformat(self.run_state()["relay"]["next_at"])
                self.assertEqual((found - (self.t0 + timedelta(seconds=at))).total_seconds(), wait)
                self.look(chat("error", f"t{number}"), "error", after=at + wait + 1)

    def test_progress_starts_the_count_again_and_so_does_a_completed_turn(self) -> None:
        self.look(chat("error", "t1", error="x"), "error")
        self.look(chat("error", "t2", error="x"), "error", after=5)
        self.assertEqual(self.run_state()["errors"], 2)
        self.tick(1)  # a step ticked: progress
        self.look(chat("error", "t3", error="x"), "error", after=10)
        self.assertEqual((self.run_state()["errors"], self.run_state()["state"]), (1, "on"))
        self.look(chat("complete", "t4"), after=20)
        self.assertEqual(self.run_state()["errors"], 0)

    def test_the_same_error_turn_is_counted_once_however_often_it_is_looked_at(self) -> None:
        for second in range(5):
            self.look(chat("error", "t1", error="x"), "error", after=second)
        self.assertEqual(self.run_state()["errors"], 1)


class PitTests(RelayCase):
    def test_a_busy_chat_over_the_percent_sets_the_pit_once(self) -> None:
        self.assertEqual(self.look(chat(percent=50, running=True), "busy"), "busy")
        self.assertIsNone(self.run_state()["pit"])
        self.assertEqual(self.look(chat(percent=71, running=True), "busy", after=3), "pit")
        pit = self.run_state()["pit"]
        self.assertEqual(pit["why"], "compact")
        self.assertEqual(self.look(chat(percent=80, running=True), "busy", after=6), "busy")
        self.assertEqual(self.run_state()["pit"], pit)  # not set again
        self.assertEqual(self.sent, [])

    def test_compact_percent_0_means_no_pit_stop(self) -> None:
        self.set_config(compact_percent=0)
        self.assertEqual(self.look(chat(percent=99, running=True), "busy"), "busy")
        self.assertIsNone(self.run_state()["pit"])
        self.look(chat(percent=99))
        self.assertEqual(self.look(chat(percent=99), after=60), "relayed")  # no compaction first
        self.assertEqual([text for text, _ in self.sent], [autorun.relay_text(self.root, TASK)])

    def test_an_idle_chat_with_a_pit_gets_compact_at_once_then_the_relay_and_the_pit_is_counted(self) -> None:
        self.look(chat(percent=75, running=True), "busy")
        self.assertEqual(self.run_state()["pit"]["why"], "compact")
        self.assertEqual(self.look(chat(percent=75), "idle", after=5), "compacting")  # no grace for a compaction
        self.assertEqual(self.sent, [("/compact", None)])
        pit = self.run_state()["pit"]
        self.assertTrue(pit["sent"])
        self.assertEqual(self.look(chat(percent=75), "idle", after=6), "compacting")  # not seen working yet, not 10 seconds yet
        self.assertEqual(self.look(chat(percent=75, running=True), "busy", after=8), "compacting")  # it works: no second pit, the turn is not touched
        self.assertEqual(self.look(chat(percent=20, turn="t2"), "idle", after=20), "wait")  # compacted: the pit is counted and cleared, the relay waits its grace
        run = self.run_state()
        self.assertEqual((run["pit"], run["pits"], run["steps"]), (None, 1, 0))
        self.assertEqual(self.look(chat(percent=20, turn="t2"), "idle", after=60), "relayed")
        self.assertEqual([text for text, _ in self.sent], ["/compact", autorun.relay_text(self.root, TASK)])
        self.assertEqual((self.run_state()["steps"], self.run_state()["relay"]["count"], self.sent[1][1]), (1, 1, MODEL))

    def test_the_usage_from_before_the_compaction_does_not_start_a_new_pit(self) -> None:
        self.look(chat(percent=75, running=True), "busy")
        self.look(chat(percent=75), "idle", after=5)
        self.look(chat(percent=75), "idle", after=20)  # compacted; the chat still shows the old usage
        self.assertEqual(self.run_state()["pits"], 1)
        self.assertEqual(self.look(chat(percent=75), "idle", after=60), "relayed")
        working = chat(percent=75)  # the relay turn runs; it has no usage of its own yet, and the old turn is still in the chat
        working["activeTurn"] = {"id": "t2", "responseParts": []}
        self.assertEqual(self.look(working, "busy", after=70), "busy")
        self.assertIsNone(self.run_state()["pit"])

    def test_the_relay_finds_the_percent_over_the_limit_and_compacts_first(self) -> None:
        self.look(chat(percent=72))
        self.assertEqual(self.look(chat(percent=72), after=60), "compacting")
        self.assertEqual(self.sent, [("/compact", None)])
        self.assertEqual(self.run_state()["pit"]["why"], "compact")

    def test_a_pit_older_than_10_minutes_is_cleared_and_so_is_a_compaction_that_never_ends(self) -> None:
        self.set_run(pit={"why": "compact", "at": (self.t0 - timedelta(minutes=11)).isoformat()})
        self.assertEqual(self.look(chat(percent=10, running=True), "busy"), "busy")
        self.assertIsNone(self.run_state()["pit"])
        self.look(chat(percent=75, running=True), "busy", after=1)
        self.look(chat(percent=75), "idle", after=2)
        self.assertTrue(self.run_state()["pit"]["sent"])
        self.assertEqual(self.look(chat(percent=75, running=True), "busy", after=2 + 301), "compacting")
        self.assertIsNone(self.run_state()["pit"])

    def test_a_cancelled_turn_with_a_pit_is_still_the_persons_stop(self) -> None:
        self.look(chat(percent=75, running=True), "busy")
        self.assertEqual(self.look(chat("cancelled", percent=75), "idle", after=5), "person")
        self.assertEqual((self.sent, self.run_state()["pit"]), ([], None))


class LinkRelayTests(RelayCase):
    """The link thread against a fake host: a chat of this folder bound to the task."""

    def setUp(self) -> None:
        super().setUp()
        self.folder = str(self.root).replace("\\", "/")
        if not self.folder.startswith("/"):
            self.folder = "/" + self.folder
        self.items = [summary("ahp-session:/abc", "ahp-chat:/abc", self.folder, status=1)]
        self.state = self.chat_state()
        self.host = FakeHost({"initialize": {"protocolVersion": "1.1.0"}, "listSessions": lambda _p: {"items": self.items}, "subscribe": self.subscribe, "unsubscribe": None,
                              "dispatchAction": lambda p: {}})
        self.addCleanup(self.host.close)
        self.link = vslink.VsLink(self.root, opener=self.open_host, turn=0.05, backoff=ahp.Backoff(0.05, 0.2))
        self.addCleanup(self.link.stop)
        patch = mock.patch.object(vslink, "RELAY_EVERY", 0.05)
        patch.start()
        self.addCleanup(patch.stop)
        grace = mock.patch.object(autorun, "settings", return_value=dict(autorun.settings(self.root), relay={"grace_seconds": 0, "backoff": [60, 300, 900], "max_errors": 3}))
        grace.start()
        self.addCleanup(grace.stop)

    def chat_state(self, result: str = "complete", percent: float = 10) -> Dict[str, Any]:
        found = chat(result, percent=percent)
        found["turns"][0]["usage"]["_meta"] = {"vscode.modelCall": {"sdkSessionId": SESSION}}
        found.update(status=1, title="A chat", modifiedAt="2026-10-31T10:00:00.000Z")
        return found

    def subscribe(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"snapshot": {"state": copy.deepcopy(self.state)}}

    def open_host(self) -> ahp.Connection:
        link = ahp.Connection(self.host.transport(), TOKEN)
        link.upgrade()
        link.hello()
        return link

    def sends(self) -> List[Dict[str, Any]]:
        return [message["params"]["action"] for message in self.host.seen if message.get("method") == "dispatchAction" and message["params"]["action"].get("type") == "chat/turnStarted"]

    def test_a_completed_turn_is_woken_with_the_same_model_and_counted(self) -> None:
        self.link.start()
        self.assertTrue(until(lambda: self.sends()), self.link.status())
        message = self.sends()[0]["message"]
        self.assertEqual((message["text"], message["model"]), (autorun.relay_text(self.root, TASK), MODEL))
        self.assertTrue(until(lambda: self.run_state()["relay"]["count"] == 1))
        self.assertEqual(self.run_state()["steps"], 1)
        self.assertEqual(self.link.chat_of(TASK)["state"], "busy")  # not idle at once: no second relay while the host has not answered
        self.assertEqual(len(self.sends()), 1)

    def test_a_cancelled_turn_ends_the_run_and_sends_nothing(self) -> None:
        self.state = self.chat_state("cancelled")
        self.link.start()
        self.assertTrue(until(lambda: self.run_state()["state"] == "off"), self.link.status())
        self.assertEqual((self.run_state()["stopped"]["why"], self.sends()), ("person", []))

    def test_a_chat_that_waits_for_the_person_is_left_alone_and_a_run_that_is_off_is_not_relayed(self) -> None:
        self.items[0]["status"] = 24
        self.link.start()
        self.assertTrue(until(lambda: self.link.status()["bound"] == 1))
        self.assertFalse(until(lambda: self.sends(), 1.0))
        self.items[0]["status"] = 1
        autorun.turn_off(self.root, TASK, interactive=True)
        self.host.push({"jsonrpc": "2.0", "method": "root/sessionSummaryChanged", "params": {"session": "ahp-session:/abc", "changes": {"status": 1}}})
        self.assertFalse(until(lambda: self.sends(), 1.0))

    def test_an_error_turn_is_backed_off_and_the_chat_in_error_is_not_woken_before_its_time(self) -> None:
        self.state = self.chat_state("error")
        self.state["turns"][0]["responseParts"] = [{"kind": "error", "message": "boom"}]
        self.items[0]["status"] = 34
        self.link.start()
        self.assertTrue(until(lambda: self.run_state().get("errors") == 1), self.link.status())
        self.assertFalse(until(lambda: self.sends(), 1.0))
        self.set_run(relay=dict(self.run_state()["relay"], next_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()))
        self.assertTrue(until(lambda: self.sends()))  # the chat in error takes the message: measured status 34 then 33

    def test_a_pit_with_an_idle_chat_sends_compact_without_a_model_then_the_relay(self) -> None:
        self.state = self.chat_state(percent=80)
        self.set_run(pit={"why": "compact", "at": datetime.now(timezone.utc).isoformat()})
        self.link.start()
        self.assertTrue(until(lambda: self.sends()), self.link.status())
        first = self.sends()[0]["message"]
        self.assertEqual((first["text"], first.get("model")), ("/compact", None))
        self.assertEqual(self.run_state()["steps"], 0)
        # the host ends the compaction: the chat is idle again; the usage shown now is the new one
        self.state = self.chat_state(percent=20)
        self.state["turns"][0]["id"] = "t2"
        with self.link.lock:
            self.link.chats["ahp-chat:/abc"]["state"] = copy.deepcopy(self.state)
            self.link.sessions["ahp-session:/abc"]["status"] = 33
        self.assertTrue(until(lambda: len(self.sends()) == 2, 20), self.sends())
        self.assertEqual(self.sends()[1]["message"]["text"], autorun.relay_text(self.root, TASK))
        self.assertEqual(self.sends()[1]["message"]["model"], MODEL)
        self.assertTrue(until(lambda: self.run_state()["steps"] == 1))
        run = self.run_state()
        self.assertEqual((run["pits"], run["pit"]), (1, None))


if __name__ == "__main__":
    unittest.main()
