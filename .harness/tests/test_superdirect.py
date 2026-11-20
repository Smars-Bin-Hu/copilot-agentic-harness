"""A direct message to a task from the super agent view (1.8.4, step 8): `/api/super/send`, one decision (paused, a command to allow, a new chat, a question to skip, a busy chat, an idle one),
the model, language and files on the message, the 10000 characters, and the record with `by: "super"`."""

from __future__ import annotations

import base64
import json
import re
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

import support  # noqa: F401 - puts the engine on the path
from taskcase import TASK
from test_boardserve import ServeCase

from modules.task import boardserve, chatnew, chatsend, superdirect, task as task_ops, tasklife, vslink

MODELS = [{"id": "m1", "name": "One", "thinking": {"levels": ["low", "high"], "labels": {}}}, {"id": "m2", "name": "Two"}]


class DirectLink(vslink.VsLink):
    """A ready link with one task and a chat in the state the test sets: idle, busy, input or error; `bound` false: no chat. It records what is dispatched and created."""

    def __init__(self, root: Any) -> None:
        super().__init__(root, enabled=False)
        self.ready = True
        self.why = "ok"
        self.state = "idle"
        self.bound_ok = True
        self.confirm = False
        self.off = ""
        self.fail: Optional[BaseException] = None
        self.sent: List[Dict[str, Any]] = []
        self.made: List[Dict[str, Any]] = []
        self.opened = 0

    def check(self, task: str, kind: str) -> str:
        if self.off:
            return self.off
        if not self.bound_ok:
            return "unbound"
        need = vslink.NEEDS[kind]
        return "not-" + need if need and need != self.state else ""

    def ask_of(self, task: str) -> Optional[Dict[str, Any]]:
        return {"kind": "confirm"} if self.confirm else {"kind": "question"} if self.state == "input" else None

    def model_list(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in MODELS]

    def dispatch(self, kind: str, task: str, text: str = "", model: Any = None, attachments: Any = None, plan: Any = None) -> Dict[str, Any]:
        if self.fail is not None:
            raise self.fail
        self.sent.append({"kind": kind, "task": task, "text": text, "model": model, "files": attachments})
        return {"chat": "c1", "title": "job", "turn": "t1", "skipped": ["q"] if kind == "say" else []}

    def create(self, plan: Dict[str, Any], text: str, attachments: Any = None) -> Dict[str, Any]:
        if self.fail is not None:
            raise self.fail
        self.made.append({"plan": plan, "text": text, "files": attachments})
        return {"session": "s2", "chat": "c2", "title": "new one", "initiator": "vscode"}

    def open_window(self) -> str:
        self.opened += 1
        return "queued"


class DirectCase(ServeCase):
    def make_link(self) -> Any:
        self.vs = DirectLink(self.root)
        return self.vs

    def setUp(self) -> None:
        super().setUp()
        self.cookie = self.pair()

    def post(self, body: Dict[str, Any], cookie: Optional[str] = None) -> Dict[str, Any]:
        status, found, _ = self.request("POST", "/api/super/send", dict({"task": TASK}, **body), cookie=self.cookie if cookie is None else cookie)
        self.assertEqual(status, 200, found)
        return {key: value for key, value in found.items() if key != "language"}

    def sent_lines(self) -> List[Dict[str, Any]]:
        path = chatsend.sent_file(self.root, TASK)
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


class BranchTests(DirectCase):
    def test_an_idle_chat_gets_it_sent(self) -> None:
        found = self.post({"text": "  hello there  "})
        self.assertEqual((found["ok"], found["how"], found["task"]), (True, "sent", task_ops.name_of(TASK)))
        self.assertEqual([(item["kind"], item["task"], item["text"]) for item in self.vs.sent], [("send", TASK, "hello there")])
        self.assertEqual(self.vs.made, [])

    def test_a_busy_chat_queues_by_default_and_steers_when_asked(self) -> None:
        self.vs.state = "busy"
        self.assertEqual(self.post({"text": "later"})["how"], "queued")
        self.assertEqual(self.post({"text": "now", "busy": "steer"})["how"], "steered")
        self.assertEqual([item["kind"] for item in self.vs.sent], ["queue", "steer"])

    def test_a_chat_that_waits_on_its_question_gets_say(self) -> None:
        self.vs.state = "input"
        found = self.post({"text": "skip it, do this"})
        self.assertEqual(found["how"], "said")
        self.assertEqual([item["kind"] for item in self.vs.sent], ["say"])
        self.assertEqual(self.sent_lines()[-1]["skipped"], ["q"])

    def test_a_command_to_allow_refuses(self) -> None:
        self.vs.state, self.vs.confirm = "input", True
        self.assertEqual(self.post({"text": "x"}), {"ok": False, "why": "confirm-waits"})
        self.assertEqual(self.post({"text": "x", "new_chat": True}), {"ok": False, "why": "confirm-waits"})
        self.assertEqual((self.vs.sent, self.vs.made), ([], []))

    def test_paused_refuses_first(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["paused"] = {"since": "2026-11-18T00:00:00+00:00"}
        self.vs.state, self.vs.confirm = "input", True
        self.assertEqual(self.post({"text": "x"}), {"ok": False, "why": "paused"})
        self.assertEqual((self.vs.sent, self.vs.made), ([], []))

    def test_a_chat_in_error_takes_no_message(self) -> None:
        self.vs.state = "error"
        self.assertEqual(self.post({"text": "x"}), {"ok": False, "why": "not-idle"})

    def test_a_task_without_a_chat_gets_a_new_one(self) -> None:
        self.vs.bound_ok = False
        found = self.post({"text": "do the thing"})
        self.assertEqual((found["ok"], found["how"]), (True, "new-chat"))
        self.assertEqual(len(self.vs.made), 1)
        made = self.vs.made[0]
        self.assertEqual(made["plan"]["name"], task_ops.name_of(TASK))  # bound to the task at once
        self.assertEqual(made["text"], "/harness-my-task Go on with the task " + task_ops.name_of(TASK) + ".\n\ndo the thing")
        self.assertEqual((self.vs.sent, self.vs.opened), ([], 0))  # the person stays in the super view: VS Code is not brought forward

    def test_a_new_chat_is_wanted_while_the_old_one_is_idle_or_in_error(self) -> None:
        self.assertEqual(self.post({"text": "a", "new_chat": True})["how"], "new-chat")
        self.vs.state = "error"
        self.assertEqual(self.post({"text": "b", "new_chat": True})["how"], "new-chat")
        self.assertEqual(len(self.vs.made), 2)

    def test_a_new_chat_is_refused_while_the_old_one_works_or_waits(self) -> None:
        for state in ("busy", "input"):
            self.vs.state = state
            self.assertEqual(self.post({"text": "a", "new_chat": True}), {"ok": False, "why": "not-idle"})
        self.assertEqual(self.vs.made, [])

    def test_the_link_being_down_or_unsure_refuses_with_its_reason(self) -> None:
        for why in ("off", "not-ready", "unsure"):
            self.vs.off = why
            self.assertEqual(self.post({"text": "a"}), {"ok": False, "why": why})
            self.assertEqual(self.post({"text": "a", "new_chat": True}), {"ok": False, "why": why})
        self.assertEqual((self.vs.sent, self.vs.made), ([], []))

    def test_a_refusal_of_the_link_thread_and_a_host_error(self) -> None:
        self.vs.fail = vslink.Refused("changed")
        self.assertEqual(self.post({"text": "a"}), {"ok": False, "why": "changed"})
        self.vs.fail = RuntimeError("secret words")
        found = self.post({"text": "a"})
        self.assertEqual((found["ok"], found["why"], found["error"]), (False, "host", "RuntimeError"))
        self.assertNotIn("secret", json.dumps(found))
        self.vs.bound_ok = False
        self.assertEqual(self.post({"text": "a"})["why"], "host")

    def test_unknown_task_unpaired_and_bad_requests(self) -> None:
        self.assertEqual(self.post({"task": "ghost", "text": "a"}), {"ok": False, "why": "unknown"})
        status, _, _ = self.request("POST", "/api/super/send", {"task": TASK, "text": "a"}, cookie="")
        self.assertEqual(status, 403)
        self.assertEqual(self.post({"text": "a", "busy": "shout"}), {"ok": False, "why": "request"})
        self.assertEqual(self.post({"text": "a", "lang": "fr"}), {"ok": False, "why": "request"})
        self.assertEqual(self.post({"text": ["a"]}), {"ok": False, "why": "text.empty"})
        self.assertEqual(self.vs.sent, [])


class TextTests(DirectCase):
    def test_empty_and_the_limit_of_10000(self) -> None:
        self.assertEqual(self.post({"text": "   "}), {"ok": False, "why": "text.empty"})
        self.assertEqual(superdirect.MAX_TEXT, 10000)
        self.assertEqual(chatnew.MAX_TEXT, 10000)
        self.assertEqual(self.post({"text": "x" * 10001}), {"ok": False, "why": "text.long"})
        self.assertEqual(self.vs.sent, [])
        self.assertTrue(self.post({"text": "x" * 10000})["ok"])

    def test_the_text_is_kept_whole_with_its_lines_and_signs(self) -> None:
        words = "Line one\n\n  indented `code` <b>&</b> 中文\n- item\nlast\ttab"
        self.post({"text": words})
        self.assertEqual(self.vs.sent[0]["text"], words)
        self.assertEqual(self.sent_lines()[-1]["text"], words)
        big = ("Z" * 99 + "\n") * 100
        self.post({"text": big})
        self.assertEqual(self.vs.sent[1]["text"], big.strip())
        self.vs.bound_ok = False
        self.post({"text": words})
        self.assertTrue(self.vs.made[0]["text"].endswith("\n\n" + words))

    def test_zh_puts_the_mark_first_en_does_not(self) -> None:
        self.post({"text": "hello", "lang": "zh"})
        self.assertEqual(self.vs.sent[0]["text"], chatsend.ZH_MARK + " hello")
        self.post({"text": "hello", "lang": "en"})
        self.assertNotIn(chatsend.ZH_MARK, self.vs.sent[1]["text"])
        self.assertTrue(self.vs.sent[1]["text"].endswith("hello"))  # `[EN]` is added only when the chat replies in Chinese

    def test_a_new_chat_in_zh_says_it_in_chinese_after_the_skill(self) -> None:
        self.post({"text": "hello", "lang": "zh", "new_chat": True})
        text = self.vs.made[0]["text"]
        self.assertTrue(text.startswith("/harness-my-task "), text)
        self.assertIn("继续任务 " + task_ops.name_of(TASK), text)
        self.assertIn(chatsend.ZH_MARK, text.split("\n")[0])
        self.assertTrue(text.endswith("\n\n" + chatsend.ZH_MARK + " hello"), text)

    def test_the_drafts_of_the_task_do_not_go_in(self) -> None:
        chatsend.add_draft(self.root, TASK, "a saved note")
        self.post({"text": "plain"})
        self.assertEqual(self.vs.sent[0]["text"], "plain")
        self.assertEqual(len(chatsend.drafts(self.root, TASK)), 1)


class ModelTests(DirectCase):
    def test_the_chosen_model_goes_on_the_message(self) -> None:
        self.post({"text": "a", "model": "m1", "thinking": "high"})
        self.assertEqual(self.vs.sent[0]["model"]["id"], "m1")
        self.assertIn("high", json.dumps(self.vs.sent[0]["model"]))

    def test_a_new_chat_carries_the_chosen_model(self) -> None:
        self.post({"text": "a", "model": "m2", "new_chat": True})
        self.assertEqual(self.vs.made[0]["plan"]["model"]["id"], "m2")

    def test_no_model_key_means_the_model_of_the_task_and_an_empty_one_the_hosts_own(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["chat"] = {"model": {"id": "m2"}}
        self.post({"text": "a"})
        self.post({"text": "b", "model": ""})
        self.assertEqual((self.vs.sent[0]["model"], self.vs.sent[1]["model"]), ({"id": "m2"}, None))

    def test_a_model_the_host_does_not_list_is_refused(self) -> None:
        self.assertEqual(self.post({"text": "a", "model": "ghost"}), {"ok": False, "why": "model"})
        self.assertEqual(self.post({"text": "a", "model": "m1", "thinking": "wild"}), {"ok": False, "why": "thinking"})
        self.assertEqual(self.post({"text": "a", "model": "m2", "context": "999"})["why"], "context")
        self.assertEqual(self.vs.sent, [])


class FilesAndRecordTests(DirectCase):
    def files(self, count: int = 1, size: int = 10) -> List[Dict[str, Any]]:
        return [{"name": f"f{n}.txt", "type": "text/plain", "data": base64.b64encode(b"x" * size).decode()} for n in range(count)]

    def test_files_go_on_the_message_and_on_a_new_chat(self) -> None:
        self.post({"text": "a", "files": self.files(2)})
        self.assertEqual([item["label"] for item in self.vs.sent[0]["files"]], ["f0.txt", "f1.txt"])
        self.vs.bound_ok = False
        self.post({"text": "b", "files": self.files(1)})
        self.assertEqual(len(self.vs.made[0]["files"]), 1)
        self.assertEqual(self.sent_lines()[0]["files"][0]["name"], "f0.txt")

    def test_the_limits_of_send_hold(self) -> None:
        self.assertEqual(self.post({"text": "a", "files": self.files(chatsend.MAX_FILES + 1)})["why"], "file-count")
        self.assertEqual(self.post({"text": "a", "files": [{"name": "x", "data": "!!"}]})["why"], "file-bad")
        self.assertEqual(self.post({"text": "a", "files": self.files(1, chatsend.MAX_FILE + 1)})["why"], "file-big")
        self.assertEqual(self.vs.sent, [])

    def test_the_body_may_hold_files_like_send(self) -> None:
        text = self.post({"text": "a", "files": self.files(1, 200000)})
        self.assertEqual(text["how"], "sent")  # larger than the 4 KB of an ordinary request

    def test_the_record_says_who_and_how(self) -> None:
        self.post({"text": "one", "model": "m1"})
        self.vs.state = "busy"
        self.post({"text": "two"})
        self.vs.state = "idle"
        self.vs.bound_ok = False
        self.post({"text": "three"})
        lines = self.sent_lines()
        self.assertEqual([(line["kind"], line["by"], line["text"][-5:]) for line in lines], [("send", "super", "one"[-5:]), ("queue", "super", "two"[-5:]), ("new-chat", "super", "three")])
        self.assertEqual(lines[0]["model"]["id"], "m1")
        self.assertEqual(lines[2]["chat"], "c2")
        found = task_ops.read(self.root, TASK)
        self.assertEqual([event["what"] for event in found["events"][-3:]], ["send", "queue", "new-chat"])

    def test_a_message_that_went_is_not_an_error_when_the_record_cannot_be_written(self) -> None:
        path = chatsend.sent_file(self.root, TASK)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir()  # a folder where the file should be
        found = self.post({"text": "a"})
        self.assertEqual((found["ok"], found["how"], found["recorded"]), (True, "sent", False))


class ReopenTests(DirectCase):
    def close(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["status"] = "closed"
            task_ops.note(data, "close", "done")

    def state(self) -> Dict[str, Any]:
        return task_ops.read(self.root, TASK)

    def test_a_closed_task_is_reopened_in_a_new_chat_with_the_words(self) -> None:
        self.close()
        found = self.post({"text": "  one more thing\nplease  "})
        self.assertEqual((found["ok"], found["how"], found["task"]), (True, "reopened", task_ops.name_of(TASK)))
        self.assertNotIn("checks", found)
        self.assertEqual(len(self.vs.made), 1)
        self.assertEqual(self.vs.sent, [])
        made = self.vs.made[0]
        self.assertEqual(made["plan"]["name"], task_ops.name_of(TASK))
        name = task_ops.name_of(TASK)
        self.assertEqual(made["text"], f"/harness-my-task The task {name} is closed. Open it again with `harness task open {name}`, then go on with it.\n\none more thing\nplease")
        line = self.sent_lines()[-1]
        self.assertEqual((line["by"], line["kind"], line["reopen"]), ("super", "new-chat", True))
        self.assertEqual(self.state()["status"], "closed")  # the agent opens it, not the board

    def test_a_reopen_may_go_with_no_message(self) -> None:  # 1.8.21: "Reopen and hand to the agent" with the message box left empty
        self.close()
        found = self.post({"text": ""})
        self.assertEqual((found["ok"], found["how"]), (True, "reopened"))
        name = task_ops.name_of(TASK)
        self.assertEqual(self.vs.made[0]["text"], f"/harness-my-task The task {name} is closed. Open it again with `harness task open {name}`, then go on with it.")

    def test_an_open_task_still_needs_words(self) -> None:
        self.assertEqual(self.post({"text": ""}), {"ok": False, "why": "text.empty"})

    def test_a_reopen_that_cannot_happen_is_refused_before_a_chat_is_made(self) -> None:  # 1.8.21: a promote that wrote part of it
        self.close()
        with task_ops.locked(self.root, TASK) as data:
            data["promote"] = {"state": "partial"}
        self.assertEqual(self.post({"text": "go on"}), {"ok": False, "why": "reopen.partial"})
        self.assertEqual(self.vs.made, [])

    def test_a_card_that_said_another_mode_makes_no_chat(self) -> None:  # review 1 of 1.8.21
        self.close()
        self.assertEqual(self.post({"text": "go on", "seen": {"mode": "new", "round": 1}}), {"ok": False, "why": "reopen.changed"})
        self.assertEqual(self.vs.made, [])
        self.assertEqual(self.post({"text": "go on", "seen": {"mode": "same", "round": 1}})["how"], "reopened")

    def test_zh_reopen_words_come_in_chinese(self) -> None:
        self.close()
        self.post({"text": "x", "lang": "zh"})
        self.assertIn("已关闭", self.vs.made[0]["text"])

    def test_the_old_chat_that_works_or_waits_refuses_and_an_idle_one_is_left(self) -> None:
        self.close()
        self.vs.state = "busy"
        self.assertEqual(self.post({"text": "x"}), {"ok": False, "why": "not-idle"})
        self.vs.state = "idle"
        self.assertEqual(self.post({"text": "x"})["how"], "reopened")  # a bound idle chat: still a new chat, never a message into the old one
        self.assertEqual(self.vs.sent, [])

    def test_a_task_that_is_gone_or_not_a_task_is_unknown(self) -> None:
        self.assertEqual(self.post({"task": "ghost-archived", "text": "x"}), {"ok": False, "why": "unknown"})
        with task_ops.locked(self.root, TASK) as data:
            data["status"] = "weird"
        self.assertEqual(self.post({"text": "x"}), {"ok": False, "why": "unknown"})

    def test_checks_on_an_open_task_are_set_through_review_set(self) -> None:
        found = self.post({"text": "x", "checks": 2})
        self.assertEqual((found["how"], found["checks"]), ("sent", 2))
        self.assertNotIn("checks_pending", found)
        review = self.state()["review"]
        self.assertEqual((review["n"], review["set"]["n"]), (2, 2))
        self.assertEqual(self.post({"text": "y", "checks": 0})["checks"], 0)
        self.assertEqual(self.state()["review"]["n"], 0)
        self.assertNotIn("checks", self.post({"text": "z"}))  # absent: no change
        self.assertEqual(self.state()["review"]["n"], 0)

    def test_checks_on_a_closed_task_are_checks_after_the_close_and_it_is_not_reopened(self) -> None:
        self.close()
        found = self.post({"text": "check it", "checks": 2})
        self.assertEqual((found["ok"], found["how"], found["checks"]), (True, "after", 2))
        self.assertNotIn("checks_pending", found)
        state = self.state()
        self.assertEqual(state["status"], "closed")
        self.assertEqual(state["review"]["after"]["n"], 2)
        self.assertNotEqual(state["review"].get("n"), 2)  # not the checks during the work
        self.assertNotIn("pending_checks", state)
        name = task_ops.name_of(TASK)
        text = self.vs.made[0]["text"]
        self.assertIn(f"`harness task review after {name} --session-id <session id>`", text)
        self.assertNotIn("task open", text)
        self.assertTrue(text.endswith("\n\ncheck it"))
        line = self.sent_lines()[-1]
        self.assertEqual((line["kind"], line.get("after"), line.get("reopen")), ("new-chat", True, None))
        self.request("POST", "/api/board", {}, cookie=self.cookie)  # the board sets nothing more
        self.assertEqual(self.state()["review"]["after"]["n"], 2)
        self.assertNotEqual(self.state()["review"].get("n"), 2)

    def test_zero_checks_on_a_closed_task_still_reopen_it(self) -> None:
        self.close()
        found = self.post({"text": "x", "checks": 0})
        self.assertEqual((found["how"], found["checks_pending"]), ("reopened", 0))
        self.assertIn("task open", self.vs.made[0]["text"])

    def test_a_refused_send_sets_no_checks_after_the_close(self) -> None:
        self.close()
        self.vs.state = "busy"
        self.assertEqual(self.post({"text": "x", "checks": 2}), {"ok": False, "why": "not-idle"})
        self.assertEqual(((self.state().get("review") or {}).get("after") or {}).get("n", 0), 0)

    def test_zh_after_words_come_in_chinese(self) -> None:
        self.close()
        self.post({"text": "x", "checks": 1, "lang": "zh"})
        self.assertIn("事后检查", self.vs.made[0]["text"])

    def test_a_bad_checks_value_refuses_before_anything_goes(self) -> None:
        for value in (-1, 6, 10, "2", 2.5, True, [2], {"n": 2}):
            self.assertEqual(self.post({"text": "x", "checks": value}), {"ok": False, "why": "checks"}, value)
        self.close()
        self.assertEqual(self.post({"text": "x", "checks": 99}), {"ok": False, "why": "checks"})
        self.assertEqual((self.vs.sent, self.vs.made), ([], []))
        self.assertNotIn("pending_checks", self.state())

    def test_checks_null_is_no_change(self) -> None:
        self.assertNotIn("checks", self.post({"text": "x", "checks": None}))

    def test_a_paused_closed_task_refuses(self) -> None:
        self.close()
        with task_ops.locked(self.root, TASK) as data:
            data["paused"] = {"since": "2026-11-18T00:00:00+00:00"}
        self.assertEqual(self.post({"text": "x"}), {"ok": False, "why": "paused"})


WEB = Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "web"
CORE = Path(__file__).resolve().parents[1] / "engine" / "core"
NOT_WORDS = {"super.chatfold", "super.morning", "super.direct"}  # keys of the browser's storage, not message keys


class PageWords(unittest.TestCase):
    """1.8.21, the page side of the reopen modes (super.js, superdirect.js, super.css): no browser here, so the page's text is read."""

    def source(self, name: str) -> str:
        return (WEB / name).read_text(encoding="utf-8")

    def test_every_key_the_super_view_names_is_in_both_languages(self) -> None:
        tables = [json.loads((CORE / f"messages.{lang}.json").read_text(encoding="utf-8")) for lang in ("en", "zh")]
        for name in ("super.js", "superdirect.js"):
            for key in set(re.findall(r'"((?:super|send\.refused)\.[a-z0-9.]+)"', self.source(name))) - NOT_WORDS:
                for table in tables:
                    self.assertIn(key, table, f"{name}: {key}")

    def test_the_new_words_sit_in_one_block_after_the_last_direct_key(self) -> None:
        for lang in ("en", "zh"):
            keys = list(json.loads((CORE / f"messages.{lang}.json").read_text(encoding="utf-8")))
            at = keys.index("super.direct.how.after")
            self.assertEqual(keys[at + 1], "super.closed.mode.new", lang)
            self.assertEqual(keys[at + 29], "super.act.reopen.after.go", lang)

    def test_a_chinese_text_is_in_no_page_file(self) -> None:
        for name in ("super.js", "superdirect.js", "super.css"):
            self.assertIsNone(re.search("[\u4e00-\u9fff]", self.source(name)), name)

    def test_reopen_only_is_a_click_on_the_board_action_and_nothing_else_makes_it(self) -> None:
        page = self.source("super.js")
        self.assertEqual(len(re.findall(r'action: "reopen"', page)), 1)  # one place posts it: reopenCall
        self.assertIn('SERVE.post("/api/act", {action: "reopen", task, step: "act", ...(info ? {seen: {mode: info.mode, round: info.round}} : {})})', page)
        self.assertEqual(len(re.findall(r"reopenCall\(", page)), 3)  # its definition, the mark's click and the card's click
        self.assertNotIn("/api/act", self.source("superdirect.js"))

    def test_the_checks_of_a_closed_task_are_named_checks_after_the_close(self) -> None:
        menu = self.source("superdirect.js")
        self.assertIn('t(shut ? "super.direct.checks.after.name" : "super.direct.checks.name")', menu)
        self.assertIn("super.direct.checks.after.hint", menu)
        self.assertIn("allowEmpty", menu)  # a closed task is reopened or checked with an empty box

    def test_the_mark_and_the_card_keep_the_send_off_for_a_reopen_that_cannot_happen(self) -> None:
        page = self.source("super.js")
        self.assertIn('sendCant = shut && !after && Boolean(info) && info.mode === "refused"', page)
        self.assertIn("if (target && sendCant) return;", page)
        self.assertIn("go.disabled = cant;", page)  # the card

    def test_the_closed_list_shows_the_mode_and_the_page_never_sends_nothing_to_an_open_task(self) -> None:
        page = self.source("super.js")
        self.assertIn('h("span", {class: "sa-cl-top"}, h("span", {class: "sa-cl-name"}, one.task), modeTag(one.reopen))', page)
        self.assertIn("if (!typed && !bare) return;", page)  # Enter on an empty box sends nothing; only the Send button of a closed task does
        self.assertIn("submit(true)", page)
        self.assertEqual(superdirect.MAX_TEXT, 10000)


if __name__ == "__main__":
    unittest.main()
