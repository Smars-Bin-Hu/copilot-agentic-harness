"""1.8.7: the link to VS Code never waits in place. One thread reads the connection and hands each answer to its call; the person's actions have a lane of their own;
a chat is made with no time limit, and one the connection lost on the way is picked up again."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off
from test_ahp import FakeHost, TOKEN
from test_chatsend import ROOT_STATE, SendCase
from test_vslink import until

from core import ahp
from modules.task import vslink
from taskcase import TASK


class SlowHost(FakeHost):
    """A host that answers some methods late, on a thread of its own, so answers can come in any order (as a busy VS Code does)."""

    def __init__(self, answers: Optional[Dict[str, Any]] = None, delays: Optional[Dict[str, float]] = None) -> None:
        self.delays: Dict[str, float] = dict(delays or {})
        self.arrived: List[Dict[str, Any]] = []
        super().__init__(answers)

    def answer(self, message: Dict[str, Any]) -> None:
        self.arrived.append({"t": time.monotonic(), "method": message.get("method"), "params": message.get("params") or {}})
        wait = self.delays.get(str(message.get("method") or ""), 0.0)
        if wait and "id" in message:
            threading.Thread(target=lambda: (time.sleep(wait), FakeHost.answer(self, message)), daemon=True).start()
            return
        super().answer(message)


def open_link(host: FakeHost) -> ahp.Connection:
    link = ahp.Connection(host.transport(), TOKEN)
    link.upgrade()
    link.hello()
    link.start_reader()
    return link


class ReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host = SlowHost({"initialize": {}, "listSessions": {"items": [{"resource": "s"}]}, "subscribe": {"snapshot": {"state": {"ok": 1}}}}, {"listSessions": 0.6})
        self.addCleanup(self.host.close)
        self.link = open_link(self.host)
        self.addCleanup(self.link.close)

    def test_a_fast_call_is_answered_while_a_slow_one_still_waits(self) -> None:
        slow: Dict[str, Any] = {}
        thread = threading.Thread(target=lambda: slow.update(items=self.link.sessions()))
        thread.start()
        time.sleep(0.05)
        start = time.monotonic()
        self.assertEqual(self.link.subscribe("c"), {"ok": 1})
        self.assertLess(time.monotonic() - start, 0.4)  # not behind the slow one
        self.assertNotIn("items", slow)
        thread.join(3)
        self.assertEqual(slow["items"], [{"resource": "s"}])

    def test_an_answer_after_the_wait_is_noted_not_lost_in_the_notices(self) -> None:
        with self.assertRaises(ahp.AhpError) as raised:
            self.link.sessions(timeout=0.1)
        self.assertEqual(ahp.problem_of(raised.exception)[0], "slow")
        self.assertTrue(until(lambda: list(self.link.late), 3))
        self.assertEqual(self.link.late[-1]["method"], "listSessions")
        self.assertIsNone(self.link.next_notice(0.1))  # an answer is never a notice

    def test_a_call_with_no_limit_waits_for_a_late_answer(self) -> None:
        self.host.delays["listSessions"] = 1.0
        self.assertEqual(self.link.sessions(timeout=None), [{"resource": "s"}])

    def test_a_closed_connection_ends_every_call_that_waits(self) -> None:
        self.host.delays["listSessions"] = 30.0
        ended: Dict[str, Any] = {}

        def wait() -> None:
            try:
                self.link.sessions(timeout=None)
            except ahp.ConnectionClosed as error:
                ended["error"] = error

        thread = threading.Thread(target=wait)
        thread.start()
        time.sleep(0.1)
        self.link.close()
        thread.join(3)
        self.assertIn("error", ended)
        with self.assertRaises(ahp.ConnectionClosed):
            self.link.next_notice(0.1)

    def test_notices_still_come_one_by_one(self) -> None:
        self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"n": 1}})
        self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"n": 2}})
        self.assertEqual(self.link.next_notice(2)["params"], {"n": 1})
        self.assertEqual(self.link.next_notice(2)["params"], {"n": 2})
        self.assertIsNone(self.link.next_notice(0.1))


class MakeTests(unittest.TestCase):
    """`_create` on a connection with a reader: no time limit, and a chat picked up after a lost connection."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.states: Dict[str, Dict[str, Any]] = {}
        self.host = SlowHost({"initialize": {}, "listSessions": {"items": []}, "subscribe": self.subscribe, "createSession": self.create})
        self.addCleanup(self.host.close)
        self.link = open_link(self.host)
        self.addCleanup(self.link.close)
        self.vs = vslink.VsLink(self.root, enabled=False)
        patcher = mock.patch.object(vslink, "INITIATOR_WAIT", 0.2)
        patcher.start()
        self.addCleanup(patcher.stop)

    def subscribe(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if params["channel"] not in self.states:
            raise ahp.AhpError("unknown channel")
        return {"snapshot": {"state": self.states[params["channel"]]}}

    def create(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.states[params["channel"]] = {"defaultChat": "ahp-chat:/new"}
        self.states["ahp-chat:/new"] = {"turns": [], "activeTurn": None}
        return {}

    def made(self, stage: str = "asking") -> Dict[str, Any]:
        made = {"name": "late-task", "kind": "dev", "source": "", "lang": "en", "permission": "allow-all", "model": None, "text": "first message", "files": [],
                "session": "ahp-session:/x", "chat": "", "made_at": "", "clock": time.monotonic(), "stage": stage, "stage_at": "", "stage_clock": time.monotonic(), "error": ""}
        self.vs.created.append(made)
        return made

    def job(self, made: Dict[str, Any], again: bool = False) -> vslink.Job:
        plan = {"name": made["name"], "kind": "dev", "source": "", "lang": "en", "permission": "allow-all", "model": None, "approve": "autoApprove", "session": made["session"], "made": made}
        if again:
            plan["again"] = True
        return vslink.Job("create", "", "first message", None, plan)

    def first_messages(self) -> List[Dict[str, Any]]:
        return [item["params"] for item in self.host.arrived if item["method"] == "dispatchAction" and item["params"]["action"].get("type") == "chat/turnStarted"]

    def test_a_chat_vs_code_makes_late_still_gets_its_first_message(self) -> None:
        self.host.delays["createSession"] = 1.0
        made = self.made()
        with mock.patch.object(ahp, "CREATE_TIMEOUT", 0.3):  # the limit a caller without a reader would have: not used here
            job = self.job(made)
            self.vs._do(self.link, job)
        self.assertIsNone(job.error)
        self.assertTrue(until(lambda: self.first_messages(), 3))
        self.assertEqual(self.first_messages()[0]["channel"], "ahp-chat:/new")
        self.assertEqual((made["stage"], made["chat"]), ("sent", "ahp-chat:/new"))

    def test_a_chat_made_while_the_connection_was_lost_gets_its_first_message_once(self) -> None:
        self.create({"channel": "ahp-session:/x"})  # VS Code made it; the board never heard its answer
        made = self.made("lost")
        self.vs._do(self.link, self.job(made, again=True))
        self.assertTrue(until(lambda: self.first_messages(), 3))
        self.assertEqual(made["stage"], "sent")
        self.states["ahp-chat:/new"] = {"turns": [{"id": "t1", "state": "complete", "responseParts": []}], "activeTurn": None}  # its first turn ran
        again = self.made("lost")
        again["session"] = "ahp-session:/x"
        self.vs._do(self.link, self.job(again, again=True))
        time.sleep(0.3)
        self.assertEqual(len(self.first_messages()), 1)  # not sent twice
        self.assertEqual(again["stage"], "sent")

    def test_a_chat_vs_code_never_made_is_refused_with_its_words(self) -> None:
        made = self.made("lost")
        job = self.job(made, again=True)
        self.vs._do(self.link, job)
        self.assertEqual((made["stage"], made["error"]), ("refused", "never"))  # the page says the connection went before VS Code made it
        self.assertEqual(self.first_messages(), [])

    def test_a_chat_never_asked_for_before_the_connection_went_is_made_when_it_is_back(self) -> None:
        made = self.made()
        self.vs.jobs.put(self.job(made))
        self.vs._jobs(None)  # the connection is gone: the job could not even be taken
        self.assertEqual(made["stage"], "lost")
        self.vs._resume_made(self.link)
        self.assertTrue(until(lambda: self.first_messages(), 3))
        self.assertEqual([item["method"] for item in self.host.arrived].count("createSession"), 1)
        self.assertEqual(made["stage"], "sent")

    def test_a_first_message_the_connection_lost_on_the_way_goes_when_it_is_back(self) -> None:
        made = self.made()
        with mock.patch.object(self.link, "dispatch", side_effect=OSError("closed")):
            with self.assertRaises(ahp.ConnectionClosed):
                self.vs._do(self.link, self.job(made))
        self.assertEqual((made["stage"], made["chat"], made.get("asked")), ("lost", "ahp-chat:/new", True))
        self.vs._resume_made(self.link)
        self.assertTrue(until(lambda: self.first_messages(), 3))
        self.assertEqual([item["method"] for item in self.host.arrived].count("createSession"), 1)  # not made twice

    def test_a_refusal_shows_on_the_placeholder_and_can_be_taken_away(self) -> None:
        def refuse(_params: Dict[str, Any]) -> Dict[str, Any]:
            raise ahp.AhpError("Provider copilotcli is not ready")

        self.host.answers["createSession"] = refuse
        made = self.made()
        self.vs._do(self.link, self.job(made))
        found = self.vs.making()[0]
        self.assertEqual((found["stage"], found["error"]), ("refused", "copilot"))
        self.assertFalse(self.vs.dismiss_making("nobody"))
        self.assertTrue(self.vs.dismiss_making("late-task"))
        self.assertEqual(self.vs.making(), [])

    def test_a_chat_still_being_made_cannot_be_taken_away_and_turns_slow(self) -> None:
        made = self.made()
        self.assertFalse(self.vs.dismiss_making("late-task"))
        self.assertFalse(self.vs.making()[0]["slow"])
        made["stage_clock"] = time.monotonic() - vslink.STAGE_SLOW - 1
        self.assertTrue(self.vs.making()[0]["slow"])


class LaneCase(SendCase):
    """The board with a fake VS Code that can be made slow."""

    def make_link(self) -> Any:
        link = super().make_link()
        old = self.host
        self.host = SlowHost(dict(old.answers))
        self.addCleanup(self.host.close)
        old.close()
        return link


class LaneTests(LaneCase):
    def test_a_message_is_not_behind_a_slow_read_of_the_background(self) -> None:
        """In 1.8.6 one thread did all: a send waited until a slow list of the chats came back (on a busy computer the page gave up after 25 s)."""
        looked = self.vs._look

        def slow_look(link: Any) -> None:  # a background step that waits on a slow VS Code (reading 20 chats, say)
            time.sleep(3.0)
            looked(link)

        self.vs._look = slow_look  # type: ignore[method-assign]
        with self.vs.lock:
            self.vs.dirty = True
        time.sleep(0.4)
        start = time.monotonic()
        done = self.vs.dispatch("send", TASK, "go on")
        self.assertLess(time.monotonic() - start, 1.5, "the send waited for the background")
        self.assertTrue(done.get("chat"))

    def test_a_second_send_right_after_the_first_is_refused_whatever_a_slow_list_says(self) -> None:
        """Two lanes (the person, an autorun relay) may send to one chat at once: the second finds the turn the board just started, even when VS Code still lists the chat as idle."""
        self.vs.dispatch("send", TASK, "first")
        with self.vs.lock:
            for item in self.vs.sessions.values():
                item["status"] = ahp.IDLE  # a list of sessions that is not up to date yet
        with self.assertRaises(vslink.Refused) as raised:
            self.vs.dispatch("send", TASK, "second")
        self.assertEqual(raised.exception.why, "not-idle")


class MakingEndpointTests(LaneCase):
    def test_the_cross_takes_away_only_a_refused_placeholder_and_only_for_a_paired_page(self) -> None:
        with self.vs.lock:
            self.vs.created.append({"name": "refused-one", "kind": "dev", "made_at": "2026-11-18T10:00:00+00:00", "session": "s", "chat": "", "clock": time.monotonic(), "stage": "refused", "error": "no"})
            self.vs.created.append({"name": "waiting-one", "kind": "dev", "made_at": "2026-11-18T10:00:00+00:00", "session": "t", "chat": "", "clock": time.monotonic(), "stage": "asking"})
        self.assertEqual(self.request("POST", "/api/making", {"op": "dismiss", "name": "refused-one"})[0], 403)
        status, data, _ = self.request("POST", "/api/making", {"op": "dismiss", "name": "waiting-one"}, cookie=self.cookie)
        self.assertEqual((status, data["result"]["dismissed"]), (200, False))
        status, data, _ = self.request("POST", "/api/making", {"op": "dismiss", "name": "refused-one"}, cookie=self.cookie)
        self.assertEqual((status, data["result"]["dismissed"]), (200, True))
        self.assertEqual([item["name"] for item in self.request("POST", "/api/board", {})[1]["making"]], ["waiting-one"])


if __name__ == "__main__":
    unittest.main()
