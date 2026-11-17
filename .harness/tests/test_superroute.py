"""Asking a task from the super agent view (1.8.2, step 3): `/api/super/route`, the `/harness-ask` marker, sent or queued, the answer read back into `asks`, the refusals, and the history."""

from __future__ import annotations

import json
import time
import unittest
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from unittest import mock

import support  # noqa: F401 - puts the engine on the path
from taskcase import TASK
from test_boardserve import ServeCase
from test_superview import result, row

from core import ahp
from modules.task import boardserve, chatsend, superbrain, superroute, task as task_ops, tasklife, vslink

CHAT, SESSION = "ahp-chat:/job", "ahp-session:/job"


class RouteLink(vslink.VsLink):
    """A link that is ready and knows one task's chat. It does what `dispatch` does to the cache, and says what `check` says, with no host."""

    def __init__(self, root: Any) -> None:
        super().__init__(root, enabled=False)
        self.ready = True
        self.why = "ok"
        self.sent: List[Dict[str, Any]] = []
        self.refuse = ""  # a reason `check` gives, whatever the state
        self.fail: Optional[BaseException] = None  # raised by `dispatch`
        self.busy = False
        self.bound[TASK] = {"session": SESSION, "chat": CHAT, "how": "test", "title": "job"}
        self.sessions[SESSION] = {"status": ahp.IDLE, "title": "job"}
        self.chats[CHAT] = {"state": {"status": 1, "turns": [], "activeTurn": None, "queuedMessages": []}, "tool_at": ""}

    def check(self, task: str, kind: str) -> str:
        if self.refuse:
            return self.refuse
        if task not in self.bound:
            return "unbound"
        need = vslink.NEEDS[kind]
        state = "busy" if self.busy else "idle"
        return "not-" + need if need and need != state else ""

    def dispatch(self, kind: str, task: str, text: str = "", model: Any = None, attachments: Any = None, plan: Any = None) -> Dict[str, Any]:
        if self.fail is not None:
            raise self.fail
        state = self.chats[CHAT]["state"]
        self.sent.append({"kind": kind, "task": task, "text": text, "model": model})
        if kind == "send":
            turn = f"turn-{len(self.sent)}"
            state["activeTurn"] = {"id": turn, "message": {"text": text}, "responseParts": [], "usage": None}
            self.busy = True
            return {"chat": CHAT, "title": "job", "turn": turn}
        state["queuedMessages"].append({"id": f"q-{len(self.sent)}", "kind": "queued", "text": text})
        return {"chat": CHAT, "title": "job", "turn": ""}

    def finish(self, reply: str, end: str = "complete") -> None:
        """The running turn ends with `reply`; a queued message then starts its turn."""
        state = self.chats[CHAT]["state"]
        active = state["activeTurn"]
        done = dict(active, state=end, responseParts=[{"kind": "toolCall", "toolCall": {"toolName": "view"}}, {"kind": "markdown", "id": "m", "content": reply}])
        state["turns"] = (state["turns"] + [done])[-2:]
        state["activeTurn"] = None
        self.busy = False

    def start_queued(self) -> str:
        """Copilot sends the first queued message as the next turn: its id is only known now."""
        state = self.chats[CHAT]["state"]
        item = state["queuedMessages"].pop(0)
        turn = f"turn-q{len(state['turns']) + 1}"
        state["activeTurn"] = {"id": turn, "message": {"text": item["text"]}, "responseParts": [], "usage": None}
        self.busy = True
        return turn


class RouteCase(ServeCase):
    def make_link(self) -> Any:
        self.vs = RouteLink(self.root)
        return self.vs

    def route(self, body: Dict[str, Any], cookie: Optional[str] = None) -> Dict[str, Any]:
        status, found, _ = self.request("POST", "/api/super/route", body, cookie=self.cookie if cookie is None else cookie)
        self.assertEqual(status, 200, found)
        return {key: found[key] for key in ("ok", "why", "id", "state") if key in found}  # the server adds `language` to every answer

    def talk(self) -> Dict[str, Any]:
        return self.request("POST", "/api/super/talk", {})[1]

    def setUp(self) -> None:
        super().setUp()
        self.cookie = self.pair()


class SentTests(RouteCase):
    def test_an_idle_chat_gets_it_at_once_with_the_marker_first(self) -> None:
        found = self.route({"task": TASK, "text": "  why is step 2 slow?  "})
        self.assertEqual((found["ok"], found["state"]), (True, "sent"))
        self.assertEqual([(item["kind"], item["task"]) for item in self.vs.sent], [("send", TASK)])
        self.assertEqual(self.vs.sent[0]["text"], "/harness-ask\nwhy is step 2 slow?")
        self.assertTrue(self.vs.sent[0]["text"].startswith(superroute.MARKER + "\n"))
        asks = self.talk()["asks"]
        self.assertEqual(len(asks), 1)
        self.assertEqual((asks[0]["id"], asks[0]["task"], asks[0]["text"], asks[0]["state"], asks[0]["turn"], asks[0]["answer"], asks[0]["end"]), (found["id"], task_ops.name_of(TASK), "why is step 2 slow?", "sent", "turn-1", "", ""))
        self.assertTrue(asks[0]["at"])
        self.assertNotIn("sent", asks[0])  # what was sent and when stay in the record only
        self.assertNotIn("sent_ts", asks[0])
        self.assertNotIn("path", asks[0])
        self.assertNotIn("/", asks[0]["task"])  # the short name: a filter on it finds the row

    def test_an_old_record_with_the_path_in_task_reads_as_the_short_name_and_still_gets_its_answer(self) -> None:
        self.route({"task": TASK, "text": "old?"})
        path = self.root / ".harness" / "runtime" / "super.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["asks"][0]["task"] = TASK  # as 1.8.2 wrote it before: the folder path, no `path`
        del stored["asks"][0]["path"]
        path.write_text(json.dumps(stored), encoding="utf-8")
        self.assertEqual(self.talk()["asks"][0]["task"], task_ops.name_of(TASK))
        self.vs.finish("old answer")
        self.assertEqual(self.talk()["asks"][0]["answer"], "old answer")

    def test_the_marker_is_the_one_the_gate_knows_and_zh_comes_after_it(self) -> None:
        self.assertEqual(superroute.MARKER, "/harness-ask")
        self.route({"task": TASK, "text": "hello", "lang": "zh"})
        self.assertEqual(self.vs.sent[0]["text"], "/harness-ask\n" + chatsend.ZH_MARK + " hello")
        self.assertEqual(self.talk()["asks"][0]["text"], "hello")  # the person's own words are kept

    def test_the_task_may_be_named_by_its_folder_or_by_its_name(self) -> None:
        self.assertTrue(self.route({"task": task_ops.name_of(TASK), "text": "a"})["ok"])
        self.assertEqual(self.vs.sent[0]["task"], TASK)


class AnswerTests(RouteCase):
    def test_the_answer_comes_back_into_asks_and_talk(self) -> None:
        found = self.route({"task": TASK, "text": "status?"})
        self.assertEqual(self.talk()["asks"][0]["state"], "sent")  # the turn runs
        self.vs.finish("Step 2 waits for the plan.\nNothing else is open.")
        ask = self.talk()["asks"][0]
        self.assertEqual((ask["id"], ask["state"], ask["end"], ask["answer"]), (found["id"], "answered", "complete", "Step 2 waits for the plan.\nNothing else is open."))
        self.assertTrue(ask["answer_at"])
        stored = json.loads((self.root / ".harness" / "runtime" / "super.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["asks"][0]["answer"], ask["answer"])  # kept in today's record, not only in memory
        self.assertEqual(self.talk()["asks"][0]["answer"], ask["answer"])  # read again: the same

    def test_a_huge_answer_is_kept_cut(self) -> None:
        self.route({"task": TASK, "text": "everything?"})
        self.vs.finish("x" * (superroute.MAX_ANSWER + 500))
        self.assertEqual(len(self.talk()["asks"][0]["answer"]), superroute.MAX_ANSWER)

    def test_a_turn_that_did_not_complete_is_a_failed_ask_with_its_end(self) -> None:
        self.route({"task": TASK, "text": "status?"})
        self.vs.finish("half", end="cancelled")
        ask = self.talk()["asks"][0]
        self.assertEqual((ask["state"], ask["end"], ask["why"], ask["answer"]), ("failed", "cancelled", "cancelled", "half"))

    def test_a_question_to_a_working_chat_is_queued_and_found_when_its_turn_ends(self) -> None:
        self.vs.busy = True  # the agent works on something else
        self.vs.chats[CHAT]["state"]["activeTurn"] = {"id": "work-1", "message": {"text": "do it"}, "responseParts": []}
        found = self.route({"task": TASK, "text": "how far are you?"})
        self.assertEqual((found["ok"], found["state"]), (True, "queued"))
        self.assertEqual([(item["kind"], item["text"]) for item in self.vs.sent], [("queue", "/harness-ask\nhow far are you?")])
        self.assertEqual(self.talk()["asks"][0]["state"], "queued")
        self.vs.finish("done")  # the work turn ends: it is not the answer
        ask = self.talk()["asks"][0]
        self.assertEqual((ask["state"], ask["answer"], ask["turn"]), ("queued", "", ""))
        turn = self.vs.start_queued()
        self.assertEqual(self.talk()["asks"][0]["state"], "sent")  # its turn began
        self.assertEqual(self.talk()["asks"][0]["turn"], turn)
        self.vs.finish("Half way.")
        ask = self.talk()["asks"][0]
        self.assertEqual((ask["state"], ask["answer"], ask["turn"]), ("answered", "Half way.", turn))

    def test_a_question_the_chat_shows_nowhere_is_given_up_after_a_while(self) -> None:
        self.vs.busy = True
        self.route({"task": TASK, "text": "q"})
        self.vs.chats[CHAT]["state"]["queuedMessages"] = []  # the host dropped it
        self.assertEqual(self.talk()["asks"][0]["state"], "queued")  # not yet: it may be a moment
        with mock.patch.object(superroute, "LOST_AFTER", -1.0):
            ask = self.talk()["asks"][0]
        self.assertEqual((ask["state"], ask["end"], ask["why"]), ("failed", "lost", "lost"))

    def test_nothing_is_judged_while_the_link_does_not_know_the_chat(self) -> None:
        self.route({"task": TASK, "text": "q"})
        self.vs.ready = False
        with mock.patch.object(superroute, "LOST_AFTER", -1.0):
            self.assertEqual(self.talk()["asks"][0]["state"], "sent")
        self.vs.ready = True


class SaidTests(RouteCase):
    def test_the_last_ended_turns_words_are_found_and_cut(self) -> None:
        self.assertEqual(superroute.said_of(self.vs, TASK), "")  # no turn yet
        self.vs.chats[CHAT]["state"]["turns"] = [{"id": "t1", "state": "complete", "responseParts": [{"kind": "toolCall"}, {"kind": "markdown", "content": "Which table: a or b?"}]}]
        self.assertEqual(superroute.said_of(self.vs, TASK), "Which table: a or b?")
        self.vs.chats[CHAT]["state"]["turns"].append({"id": "t2", "state": "complete", "responseParts": [{"kind": "markdown", "content": "x" * 3000}]})
        said = superroute.said_of(self.vs, TASK)
        self.assertEqual(len(said), superroute.MAX_SAID)
        self.assertTrue(said.endswith("…"))

    def test_a_chat_the_link_does_not_know_says_nothing(self) -> None:
        self.assertEqual(superroute.said_of(self.vs, ".workspace/sandbox/tasks/other"), "")
        self.vs.ready = False
        self.assertEqual(superroute.said_of(self.vs, TASK), "")

    def test_a_stopped_item_carries_said_in_api_super(self) -> None:
        self.vs.chats[CHAT]["state"]["turns"] = [{"id": "t1", "state": "complete", "responseParts": [{"kind": "markdown", "content": "Shall I go on?"}]}]
        rows = result(row(TASK, "stopped", name=task_ops.name_of(TASK)), row(TASK + "x", "plan", name="other"))
        with mock.patch.object(boardserve.Board, "rows", return_value=rows):
            items = self.request("POST", "/api/super", {})[1]["items"]
            self.assertEqual([(item["task"], item["why"], item.get("said")) for item in items], [("other", "plan", None), ("job1", "stopped", "Shall I go on?")])  # only a stopped, accepted or cancelled wait has the words
            self.vs.chats.clear()  # the link does not know the chat now
            item = self.request("POST", "/api/super", {})[1]["items"][1]
        self.assertEqual(item["why"], "stopped")
        self.assertNotIn("said", item)


class RefusalTests(RouteCase):
    def why(self, body: Dict[str, Any]) -> str:
        found = self.route(body)
        self.assertFalse(found["ok"], found)
        self.assertEqual(self.vs.sent, [])
        self.assertEqual(self.talk()["asks"], [])  # a refused question is not recorded
        return found["why"]

    def test_empty_and_long_words(self) -> None:
        self.assertEqual(self.why({"task": TASK, "text": "   "}), "empty")
        self.assertEqual(self.why({"task": TASK}), "empty")
        for odd in (["a"], 5, {"t": "x"}):  # only text is sent: a list or a number is not turned into words
            self.assertEqual(self.why({"task": TASK, "text": odd}), "empty")
        self.assertEqual(self.why({"task": TASK, "text": "x" * (superroute.MAX_ASK + 1)}), "long")
        self.assertTrue(self.route({"task": TASK, "text": "x" * superroute.MAX_ASK})["ok"])  # the limit itself is fine

    def test_no_such_open_task(self) -> None:
        self.assertEqual(self.why({"task": "nothing-here", "text": "hi"}), "unknown")
        self.assertEqual(self.why({"task": "", "text": "hi"}), "unknown")  # no guess at "the one open task"
        self.assertEqual(self.why({"task": "../../etc", "text": "hi"}), "unknown")

    def test_a_closed_task_is_unknown(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["status"] = "closed"
        self.assertEqual(self.why({"task": TASK, "text": "hi"}), "unknown")

    def test_a_paused_task(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["paused"] = {"since": "2026-11-17T08:00:00+00:00"}
        self.assertEqual(tasklife.paused_since(self.data()), "2026-11-17T08:00:00+00:00")
        self.assertEqual(self.why({"task": TASK, "text": "hi"}), "paused")

    def test_a_task_with_no_chat_the_board_can_reach(self) -> None:
        del self.vs.bound[TASK]
        self.assertEqual(self.why({"task": TASK, "text": "hi"}), "nochat")
        self.vs.bound[TASK] = {"session": SESSION, "chat": CHAT}
        self.vs.refuse = "unsure"  # two chats could be the task's
        self.assertEqual(self.why({"task": TASK, "text": "hi"}), "nochat")

    def test_vs_code_is_not_linked(self) -> None:
        for reason in ("off", "not-ready"):
            self.vs.refuse = reason
            self.assertEqual(self.why({"task": TASK, "text": "hi"}), "asleep")

    def test_a_reason_of_the_link_is_passed_through(self) -> None:
        self.vs.refuse = "changed"
        self.assertEqual(self.why({"task": TASK, "text": "hi"}), "changed")
        self.vs.refuse = ""
        self.vs.fail = vslink.Refused("timeout")
        self.assertEqual(self.why({"task": TASK, "text": "hi"}), "timeout")

    def test_a_chat_that_waits_for_the_person_takes_no_question(self) -> None:
        with mock.patch.object(self.vs, "check", side_effect=lambda task, kind: "not-idle" if kind == "send" else "not-busy"):
            self.assertEqual(self.why({"task": TASK, "text": "hi"}), "not-busy")  # not idle, and not working either: it is never steered

    def test_an_error_of_the_host_is_a_plain_error_and_its_words_stay_out(self) -> None:
        self.vs.fail = RuntimeError("secret path /Users/x")
        found = self.route({"task": TASK, "text": "hi"})
        self.assertEqual((found["ok"], found["why"]), (False, "error"))
        self.assertNotIn("secret", json.dumps(found))
        self.assertEqual(self.vs.sent, [])

    def test_it_is_never_a_steer(self) -> None:
        self.vs.busy = True
        self.route({"task": TASK, "text": "hi"})
        self.assertEqual({item["kind"] for item in self.vs.sent}, {"queue"})


class PairingTests(RouteCase):
    def test_without_pairing_there_is_no_ask(self) -> None:
        self.assertEqual(self.request("POST", "/api/super/route", {"task": TASK, "text": "hi"})[0], 403)  # no cookie
        self.assertEqual(self.request("POST", "/api/super/route", {"task": TASK, "text": "hi"}, header=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/super/route", {"task": TASK, "text": "hi"}, cookie=self.cookie, origin="https://evil.example")[0], 403)
        self.assertEqual(self.request("POST", "/api/super/route", {"task": TASK, "text": "hi"}, cookie=self.cookie, host="evil.example:80")[0], 403)
        self.assertEqual(self.vs.sent, [])
        self.assertEqual(self.talk()["asks"], [])


class HistoryTests(RouteCase):
    def test_asks_are_kept_with_the_day_and_the_history_returns_them(self) -> None:
        day = datetime(2026, 11, 17, 9, 30)
        clock = {"now": day}
        brain = superbrain.Brain(self.root, self.vs, lambda: result(), now=lambda: clock["now"])
        sent = brain.route({"task": TASK, "text": "status?"})
        self.assertTrue(sent["ok"])
        self.vs.finish("All good.")
        self.assertEqual(brain.talk()["asks"][0]["state"], "answered")
        clock["now"] = day + timedelta(days=1)
        self.assertEqual(brain.talk()["asks"], [])  # a new day starts empty
        self.assertEqual(brain.history(), {"days": [{"day": "2026-11-17", "turns": 1, "spent": 0.0, "archived": False}]})
        found = brain.history_day("2026-11-17")
        self.assertTrue(found["ok"])
        self.assertEqual(found["messages"], [])
        self.assertEqual([(item["id"], item["task"], item["text"], item["state"], item["answer"], item["end"]) for item in found["asks"]], [(sent["id"], task_ops.name_of(TASK), "status?", "answered", "All good.", "complete")])
        self.assertNotIn("sent", found["asks"][0])

    def test_a_day_with_asks_and_no_chat_with_the_super_agent_is_kept(self) -> None:
        clock = {"now": datetime(2026, 11, 17, 9, 30)}
        brain = superbrain.Brain(self.root, self.vs, lambda: result(), now=lambda: clock["now"])
        brain.route({"task": TASK, "text": "status?"})
        clock["now"] += timedelta(days=1)
        self.assertEqual([item["day"] for item in brain.history()["days"]], ["2026-11-17"])
        self.assertEqual(len(brain.history_day("2026-11-17")["asks"]), 1)

    def test_an_old_record_with_no_asks_and_a_bad_entry_are_read_as_nothing(self) -> None:
        path = superbrain.file_of(self.root)
        brain = superbrain.Brain(self.root, self.vs, lambda: result())
        record = brain.fresh()
        del record["asks"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(brain.talk()["asks"], [])
        record["asks"] = [{"nope": 1}, "text", {"id": "a", "task": TASK, "text": "q", "state": "sent", "at": "", "turn": "", "answer": "", "answer_at": "", "end": ""}]
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual([item["id"] for item in brain.talk()["asks"]], ["a"])


if __name__ == "__main__":
    unittest.main()
