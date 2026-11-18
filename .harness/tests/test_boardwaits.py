"""1.8.5: the board between "sent" and "the agent works" (starting), a chat whose last turn failed (error), chats the board made whose task is not there yet (making), and a task's display name."""

from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from typing import Any, Dict, Tuple

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off
from test_chatnew import GOOD, CreateCase
from test_chatsend import SendCase
from test_vslink import until

from core import ahp, messages, tasks
from modules.task import boardserve, chatlive, superview, vslink
from taskcase import TASK


class FakeLink:
    """What `settle` asks of the link: the chat of a task and where its turns stand."""

    def __init__(self) -> None:
        self.chat: Dict[str, Any] = {"bound": True, "state": "idle"}
        self.mark: Tuple[str, str, str] = ("c1", "t1", "")

    def chat_of(self, _task: str, _name: str = "") -> Dict[str, Any]:
        return dict(self.chat)

    def turn_mark(self, _task: str) -> Tuple[str, str, str]:
        return self.mark

    def made_stage(self, _name: str) -> str:
        return getattr(self, "making", "")


def board() -> Any:
    return SimpleNamespace(started={}, started_lock=threading.Lock(), link=FakeLink())


def row(link: FakeLink, **extra: Any) -> Dict[str, Any]:
    base = {"task": "t/a", "status": "open", "paused_since": "", "state": "waiting", "active": False, "held": True, "waiting": "Approve the plan", "waiting_why": "go-plan",
            "waiting_tip": "", "waiting_since": "2026-11-18T00:00:00+00:00", "waiting_from": "x", "chat": dict(link.chat)}
    base.update(extra)
    return base


def settle(fake: Any, found: Dict[str, Any]) -> bool:
    found["chat"] = dict(fake.link.chat)
    return boardserve.Board.settle(fake, found)


def begin(fake: Any, what: str = "go") -> None:
    boardserve.Board.begin(fake, "t/a", what, boardserve.Board.before(fake, "t/a"))


class StartingTests(unittest.TestCase):
    def test_after_a_send_the_row_is_starting_and_waits_for_nothing_until_the_chat_works(self) -> None:
        fake = board()
        begin(fake)
        found = row(fake.link)
        self.assertTrue(settle(fake, found))
        self.assertEqual((found["state"], found["starting"]["what"], found["starting"]["late"]), ("working", "go", False))
        self.assertEqual([found[key] for key in boardserve.WAIT_FIELDS], [""] * len(boardserve.WAIT_FIELDS))
        fake.link.chat["state"] = "busy"
        found = row(fake.link, state="working", waiting="", waiting_why="")
        settle(fake, found)
        self.assertNotIn("starting", found)
        self.assertEqual(fake.started, {})

    def test_a_turn_that_ran_and_ended_before_the_board_looked_ends_it_too(self) -> None:
        fake = board()
        begin(fake)
        fake.link.mark = ("c1", "t1", "t2")  # the chat has the new turn; the list of sessions still says idle: still starting
        found = row(fake.link)
        settle(fake, found)
        self.assertEqual(found["state"], "working")
        fake.link.mark = ("c1", "t2", "")  # a new last turn; the chat is idle again
        found = row(fake.link, waiting="", waiting_why="", state="quiet")
        settle(fake, found)
        self.assertNotIn("starting", found)
        self.assertEqual(found["state"], "quiet")

    def test_a_running_turn_answers_the_marks_the_hooks_have_not_taken_away_yet(self) -> None:
        fake = board()
        fake.link.chat = {"bound": True, "state": "busy"}
        for why in boardserve.ANSWERED_BY_A_TURN:
            found = row(fake.link, waiting_why=why)
            settle(fake, found)
            self.assertEqual((found["state"], found["waiting_why"], found["waiting"]), ("working", "", ""), why)
        found = row(fake.link, waiting_why="outbox")  # a held call still waits for the person while the agent works on
        settle(fake, found)
        self.assertEqual(found["waiting_why"], "outbox")

    def test_an_unknown_chat_state_does_not_end_it(self) -> None:
        fake = board()
        begin(fake, "newchat")
        fake.link.chat = {"bound": True, "state": "unknown"}
        fake.link.mark = ("c2", "", "")  # the new chat is bound; the host lists it only once its first turn runs
        found = row(fake.link)
        settle(fake, found)
        self.assertEqual(found["starting"]["what"], "newchat")
        fake.link.chat = {"bound": True, "state": "busy"}
        found = row(fake.link)
        settle(fake, found)
        self.assertNotIn("starting", found)

    def test_after_two_minutes_it_is_late_and_the_row_is_as_it_is(self) -> None:
        fake = board()
        begin(fake)
        fake.started["t/a"]["mono"] -= boardserve.START_LATE + 1
        found = row(fake.link)
        settle(fake, found)
        self.assertTrue(found["starting"]["late"])
        self.assertEqual((found["state"], found["waiting_why"]), ("waiting", "go-plan"))
        fake.started["t/a"]["mono"] -= boardserve.START_FORGET
        found = row(fake.link)
        settle(fake, found)
        self.assertNotIn("starting", found)
        self.assertEqual(fake.started, {})

    def test_a_new_chat_vs_code_is_still_making_is_never_late(self) -> None:
        """1.8.7: Go on in a new chat on a slow computer: VS Code may take minutes to make the chat; the row keeps saying starting, not "no start seen"."""
        fake = board()
        begin(fake, "newchat")
        fake.started["t/a"]["mono"] -= boardserve.START_LATE + 1
        fake.link.making = "asking"
        found = row(fake.link, name="a")
        settle(fake, found)
        self.assertFalse(found["starting"]["late"])
        fake.link.making = ""
        found = row(fake.link, name="a")
        settle(fake, found)
        self.assertTrue(found["starting"]["late"])

    def test_a_closed_or_paused_task_lets_go(self) -> None:
        for extra in ({"status": "closed"}, {"paused_since": "2026-11-18T00:00:00+00:00"}):
            fake = board()
            begin(fake)
            found = row(fake.link, **extra)
            settle(fake, found)
            self.assertNotIn("starting", found, extra)
            self.assertEqual(fake.started, {}, extra)

    def test_try_again_on_a_failed_chat_is_starting_until_the_chat_leaves_the_error(self) -> None:
        fake = board()
        fake.link.chat = {"bound": True, "state": "error", "error": {"message": "rate limit", "resumable": True}}
        begin(fake, "retry")
        found = row(fake.link)
        settle(fake, found)
        self.assertEqual((found["state"], found["starting"]["what"]), ("working", "retry"))
        self.assertNotIn("error", found)
        fake.link.chat = {"bound": True, "state": "busy"}
        found = row(fake.link)
        settle(fake, found)
        self.assertNotIn("starting", found)

    def test_a_chat_that_fails_after_the_send_ends_it_with_the_error(self) -> None:
        fake = board()
        begin(fake)
        fake.link.chat = {"bound": True, "state": "error", "error": {"message": "rate limit", "resumable": True}}
        found = row(fake.link)
        settle(fake, found)
        self.assertNotIn("starting", found)
        self.assertEqual((found["state"], found["error"]["message"]), ("error", "rate limit"))


class WakeTests(unittest.TestCase):
    """Review 1: an approval's go-on is sent in the background; the row must say starting from the answer to the approval, not from when VS Code took the message."""

    def fake(self, outcome: str, gate: threading.Event) -> Any:
        fake = board()

        def wake_go(_task: str) -> str:
            gate.wait(5)
            return outcome

        fake.wake_go = wake_go
        fake.before = lambda task: boardserve.Board.before(fake, task)
        fake.begin = lambda task, what, pre: boardserve.Board.begin(fake, task, what, pre)
        return fake

    def test_the_row_is_starting_while_the_go_on_is_still_on_its_way(self) -> None:
        gate = threading.Event()
        fake = self.fake("message", gate)
        boardserve.Board.wake_soon(fake, "t/a")
        found = row(fake.link)
        settle(fake, found)
        self.assertEqual((found["state"], found["starting"]["what"]), ("working", "go"))
        gate.set()
        fake.woken.join(5)
        self.assertIn("t/a", fake.started)  # it went: starting until the chat works

    def test_a_go_on_that_does_not_go_takes_the_mark_away(self) -> None:
        gate = threading.Event()
        gate.set()
        fake = self.fake("", gate)
        boardserve.Board.wake_soon(fake, "t/a")
        fake.woken.join(5)
        self.assertEqual(fake.started, {})
        found = row(fake.link)
        settle(fake, found)
        self.assertNotIn("starting", found)
        self.assertEqual(found["waiting_why"], "go-plan")  # the card that asks to tell the agent comes back

    def test_an_ask_the_host_still_lists_is_not_read_while_starting(self) -> None:
        self.assertTrue(boardserve.starting_now({"starting": {"late": False}}))
        self.assertFalse(boardserve.starting_now({"starting": {"late": True}}))
        self.assertFalse(boardserve.starting_now({}))


class ErrorTests(unittest.TestCase):
    def test_a_failed_chat_makes_the_row_an_error_and_keeps_what_it_waits_for(self) -> None:
        fake = board()
        fake.link.chat = {"bound": True, "state": "error", "error": {"message": "the model call failed", "resumable": False}}
        for state, why in (("working", ""), ("waiting", "req"), ("quiet", "")):
            found = row(fake.link, state=state, waiting_why=why, active=state == "working")
            settle(fake, found)
            self.assertEqual((found["state"], found["active"], found["waiting_why"]), ("error", False, why))
            self.assertEqual(found["error"], {"message": "the model call failed", "resumable": False})

    def test_a_paused_task_or_a_closed_one_is_not_an_error(self) -> None:
        fake = board()
        fake.link.chat = {"bound": True, "state": "error", "error": {}}
        for extra, state in (({"paused_since": "x", "state": "paused"}, "paused"), ({"status": "closed", "state": "closed"}, "closed")):
            found = row(fake.link, **extra)
            settle(fake, found)
            self.assertEqual(found["state"], state)

    def test_error_sorts_first_in_the_list(self) -> None:
        from modules.task import tasklife

        rows = [{"state": "waiting", "waited_s": 50}, {"state": "error", "waited_s": None}]
        tasklife.sort_rows(rows)
        self.assertEqual(rows[0]["state"], "error")


class ChatStateTests(unittest.TestCase):
    FAILED = {"turns": [{"id": "t1", "state": "error", "responseParts": [{"kind": "error", "message": "rate limit", "resumable": True}]}], "activeTurn": None}

    def test_a_failed_last_turn_is_an_error_whatever_the_list_of_sessions_still_says(self) -> None:
        for bits in (ahp.IDLE, ahp.IN_PROGRESS, None):
            self.assertEqual(vslink.chat_state({"status": bits}, {"state": self.FAILED}), "error", bits)
        self.assertEqual(vslink.chat_state({"status": ahp.INPUT_NEEDED}, {"state": self.FAILED}), "input")
        self.assertEqual(vslink.chat_state({"status": ahp.IDLE}, {}), "idle")
        running = dict(self.FAILED, activeTurn={"id": "t2", "responseParts": []})
        self.assertEqual(vslink.chat_state({"status": ahp.IN_PROGRESS}, {"state": running}), "busy")

    def test_live_shows_the_error_part_with_its_words(self) -> None:
        found = chatlive.build(self.FAILED, {})
        self.assertEqual([(item["k"], item["text"], item["resumable"]) for item in found["items"]], [("err", "rate limit", True)])
        long = {"turns": [{"id": "t1", "state": "error", "responseParts": [{"kind": "error", "message": "x" * 900}]}]}
        item = chatlive.build(long, {})["items"][0]
        self.assertLessEqual(len(item["text"]), chatlive.ERROR_CAP + 1)
        self.assertFalse(item["resumable"])


class SuperviewTests(unittest.TestCase):
    def test_a_starting_task_is_a_starting_mate_with_its_display_name(self) -> None:
        rows = [{"task": "t/a", "name": "a", "title": "Fix the late orders", "status": "open", "state": "working", "starting": {"what": "go", "since": "x", "late": False}, "actions": []},
                {"task": "t/b", "name": "b", "status": "open", "state": "working", "actions": []}]
        view = superview.build({"rows": rows})
        self.assertEqual([(mate["task"], mate["state"], mate["label"]) for mate in view["mates"]], [("a", "start", "Fix the late orders"), ("b", "work", "")])
        self.assertEqual(view["status"]["working"], 2)
        rows[0]["starting"]["late"] = True
        self.assertEqual(superview.build({"rows": rows})["mates"][0]["state"], "work")

    def test_a_failed_chat_that_still_waits_for_the_person_is_a_red_mate(self) -> None:
        rows = [{"task": "t/a", "name": "a", "status": "open", "state": "error", "waiting_why": "plan", "waiting": "Approve the plan", "actions": []}]
        view = superview.build({"rows": rows})
        self.assertEqual(view["mates"][0]["state"], "error")
        self.assertEqual([item["why"] for item in view["items"]], ["plan"])  # the decision stays in the queue


class HostWordsTests(unittest.TestCase):
    """1.8.6: a host error says what kind it was (a slow VS Code, Copilot not ready, the host's own words); before, only "AhpError" was shown."""

    def test_each_kind_of_host_error_has_its_own_words(self) -> None:
        slow = boardserve.host_words(ahp.AhpError("createSession: no answer in 40 s"))
        self.assertEqual(slow, messages.text("host.slow", seconds="40"))
        for said in ("createSession failed: Provider copilotcli is not ready", "dispatchAction failed: Client is not connected"):
            self.assertEqual(boardserve.host_words(ahp.AhpError(said)), messages.text("host.copilot"))
        own = boardserve.host_words(ahp.AhpError("createSession failed: the folder is not trusted\n  at line 2"))
        self.assertEqual(own, messages.text("host.said", words="createSession failed: the folder is not trusted at line 2"))
        long = ahp.problem_of(ahp.AhpError("x" * 900))[1]
        self.assertEqual(len(long), ahp.WORDS_MAX)

    def test_an_error_that_is_not_the_hosts_shows_only_its_name(self) -> None:
        words = boardserve.host_words(OSError("/Users/someone/private/file"))
        self.assertEqual(words, messages.text("host.other", error="OSError"))
        self.assertNotIn("/Users", boardserve.ahp_scrub(OSError("/Users/someone/private/file")))

    def test_the_page_waits_longer_than_the_host_may_take_to_make_a_chat(self) -> None:
        self.assertGreater(ahp.CREATE_TIMEOUT, ahp.CALL_TIMEOUT)
        self.assertGreaterEqual(vslink.CREATE_WAIT, ahp.CREATE_TIMEOUT + 15)  # room for the calls after createSession


class ServedTests(SendCase):
    """Through the server, with a fake VS Code."""

    def board_row(self) -> Dict[str, Any]:
        return next(item for item in self.request("POST", "/api/board", {})[1]["rows"] if item["task"] == TASK)

    def test_a_send_makes_the_row_starting_until_the_chat_works(self) -> None:
        self.approve_plan()
        status, data, _ = self.post("/api/send", {"kind": "go", "step": "act"})
        self.assertEqual(status, 200, data)
        found = self.board_row()  # the link already holds the new turn: working at once, as starting or as a busy chat; the go-on card is gone either way
        self.assertEqual((found["state"], found["waiting_why"]), ("working", ""))
        self.busy("t5")
        self.assertTrue(until(lambda: "starting" not in self.board_row()))
        self.assertEqual(self.board_row()["state"], "working")

    def test_try_again_makes_the_row_starting(self) -> None:
        failed = {"id": "t9", "message": {"text": "go"}, "state": "error", "responseParts": [{"kind": "error", "message": "rate limited", "resumable": True}]}
        with self.vs.lock:
            self.vs.chats[self.chat]["state"]["turns"] = [failed]
        found = self.board_row()
        self.assertEqual((found["state"], found["error"]["message"]), ("error", "rate limited"))
        self.assertEqual(self.vs.live(TASK)["state"], "error")
        status, data, _ = self.post("/api/resume", {})
        self.assertEqual(status, 200, data)
        found = self.board_row()
        self.assertEqual((found["state"], found["starting"]["what"]), ("working", "retry"))

    def test_making_lists_the_chats_the_board_made_whose_task_is_not_there(self) -> None:
        with self.vs.lock:
            self.vs.created.append({"name": "new-one", "kind": "dev", "made_at": "2026-11-18T10:00:00+00:00", "session": "s", "chat": "c", "clock": time.monotonic()})
        found = self.request("POST", "/api/board", {})[1]["making"]
        self.assertEqual([(item["name"], item["kind"], item["since"]) for item in found], [("new-one", "dev", "2026-11-18T10:00:00+00:00")])
        self.assertEqual(self.request("POST", "/api/super", {})[1]["making"][0]["name"], "new-one")
        with self.vs.lock:
            self.vs.created.append({"name": "job1", "kind": "dev", "made_at": "2026-11-18T10:01:00+00:00", "session": "s2", "chat": "c2", "clock": time.monotonic()})  # Go on in a new chat
        self.assertEqual([item["name"] for item in self.request("POST", "/api/board", {})[1]["making"]], ["new-one"])

    def test_a_display_name_is_set_shown_and_taken_away(self) -> None:
        status, data, _ = self.post("/api/title", {"title": "  Fix the late orders  "})
        self.assertEqual((status, data["result"]["title"]), (200, "Fix the late orders"))
        self.assertEqual(tasks.read(self.root, TASK)["title"], "Fix the late orders")
        self.assertEqual(self.board_row()["title"], "Fix the late orders")
        self.assertIn("title", [event["what"] for event in tasks.read(self.root, TASK)["events"]])
        status, data, _ = self.post("/api/title", {"title": "x" * (boardserve.TITLE_MAX + 1)})
        self.assertEqual((status, data["error"]), (409, messages.text("title.refused.long", limit=boardserve.TITLE_MAX)))
        for bad in ("two\nlines", "tab\there", "bell\x07", "zero\u200bwidth", "bidi\u202eflip"):
            status, data, _ = self.post("/api/title", {"title": bad})
            self.assertEqual((status, data["error"]), (409, messages.text("title.refused.control")), bad)
        self.assertEqual(self.post("/api/title", {"title": ["a"]})[0], 409)
        self.assertEqual(self.post("/api/title", {"title": False})[0], 409)
        self.assertEqual(tasks.read(self.root, TASK)["title"], "Fix the late orders")  # nothing bad was kept
        self.assertEqual(self.post("/api/title", {"title": "x"}, cookie="")[0], 403)
        self.assertEqual(self.request("POST", "/api/title", {"title": "x"}, cookie=self.cookie)[0], 409)  # no task named
        self.assertEqual(self.post("/api/title", {"title": ""})[0], 200)
        self.assertNotIn("title", tasks.read(self.root, TASK))
        self.assertEqual(self.board_row()["title"], "")


class MakingTests(CreateCase):
    def test_a_task_the_board_makes_is_being_created_since_its_chat_was_made(self) -> None:
        status, data, _ = self.make()
        self.assertEqual(status, 200, data)
        found = [item for item in self.request("POST", "/api/board", {})[1]["making"] if item["name"] == GOOD["name"]]
        self.assertEqual([item["kind"] for item in found], [GOOD["kind"]])
        self.assertRegex(found[0]["since"], r"^\d{4}-\d\d-\d\dT")


if __name__ == "__main__":
    unittest.main()
