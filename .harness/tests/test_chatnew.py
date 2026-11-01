"""The board makes a task (1.6, B73): the checks of every field, the first message, the chat made on a fake host (the call, the model on the message, the initiator read back, no dispose),
the binding when the agent has made the task, the fork, the refusals, and the rule in `.vscode/settings.json` that lets `harness task open|new|fork|list|status` run without a box."""

from __future__ import annotations

import json
import re
import time
import unittest
from typing import Any, Dict, List

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off
from support import REPO
from taskcase import TASK, TaskCase
from test_ahp import TOKEN
from test_chatsend import ROOT_STATE, SendCase
from test_vslink import summary, until

from core import ahp, messages, tasks
from modules.task import chatlink, chatnew, chatsend, task as task_ops, vslink
from modules.task.common import CommandError

MODELS = ahp.models_of(ROOT_STATE)
GOOD = {"name": "fresh-load", "kind": "dev", "text": "Add a column to the load.", "model": "claude-haiku-5.5", "thinking": "low"}


def refused(key: str, **values: Any) -> str:
    return messages.text("create.refused." + key, **values)


class ValidationTests(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.new()  # a task `job1` exists

    def plan(self, **change: Any) -> Dict[str, Any]:
        return chatnew.validate(self.root, {**GOOD, **change}, MODELS)

    def bad(self, why: str, **change: Any) -> None:
        with self.assertRaises(CommandError) as caught:
            self.plan(**change)
        self.assertEqual(str(caught.exception), refused(why, **{"name": change.get("name"), "kinds": ", ".join(tasks.KINDS), "source": change.get("source"), "limit": chatnew.MAX_TEXT, "field": next(iter(change), "")}), change)

    def test_a_good_request_becomes_a_plan_with_the_defaults(self) -> None:
        found = self.plan()
        self.assertEqual((found["name"], found["kind"], found["source"], found["lang"], found["permission"], found["approve"]), ("fresh-load", "dev", "", "en", "allow-all", "autoApprove"))
        self.assertEqual(found["model"], {"id": "claude-haiku-5.5", "config": {"thinkingLevel": "low"}})
        self.assertIsNone(self.plan(model="", thinking="")["model"])  # no model chosen: the chat keeps VS Code's own
        self.assertEqual(self.plan(model="claude-haiku-4.5", thinking="")["model"], {"id": "claude-haiku-4.5"})
        self.assertEqual(self.plan(source="job1")["source"], "job1")

    def test_a_chat_of_the_board_is_allow_all_and_nothing_else_is_taken(self) -> None:
        self.assertEqual((self.plan()["approve"], self.plan(permission="allow-all")["approve"]), ("autoApprove", "autoApprove"))
        for word in ("default", "assisted", "autoApprove", "plan", "autopilot", "bypass", "ALLOW-ALL", "x"):  # with another, its first command waits in VS Code before there is a task on the board
            with self.subTest(word=word):
                self.bad("permission", permission=word)

    def test_the_mode_and_the_folder_cannot_be_asked_for(self) -> None:
        found = self.plan(mode="autopilot", isolation="worktree", provider="claude", workingDirectories=["file:///etc"])
        self.assertEqual(sorted(found), ["approve", "domain_choice", "domains", "kind", "lang", "model", "name", "permission", "source", "text"])  # nothing of them is carried

    def test_the_name_follows_the_rules_of_task_new_and_is_not_taken(self) -> None:
        for name in ("", "  ", "a/b", "a\\b", ".hidden", "a b", "x" * 81, "..", "a;b", "$(x)", "-x"):
            with self.subTest(name=name):
                with self.assertRaises(CommandError):
                    self.plan(name=name)
        self.bad("exists", name="job1")
        self.bad("exists", name="JOB1")  # a folder that differs by case is the same folder on some systems
        with self.assertRaises(CommandError):
            chatnew.validate(self.root, GOOD, MODELS, waiting=["Fresh-Load"])  # a chat was made for it a moment ago, its task is not there yet

    def test_the_kind_is_one_the_harness_knows(self) -> None:
        for kind in tasks.KINDS:
            self.assertEqual(self.plan(kind=kind)["kind"], kind)
        for kind in ("", "DEV", "prod", "dev; rm"):
            with self.subTest(kind=kind):
                self.bad("kind", kind=kind)

    def test_a_fork_source_must_be_a_task_that_exists(self) -> None:
        for source in ("nope", "../job1", ".workspace/sandbox/tasks/job1", "job1/", "JOB1x"):
            with self.subTest(source=source):
                self.bad("source", source=source)

    def test_the_text_is_needed_and_bounded(self) -> None:
        self.bad("text.empty", text="  \n ")
        self.bad("text.long", text="x" * (chatnew.MAX_TEXT + 1))
        self.bad("text.bad", text="a\x00b")
        self.assertEqual(self.plan(text="line one\nline two")["text"], "line one\nline two")
        self.assertEqual(self.plan(text="x" * chatnew.MAX_TEXT)["text"], "x" * chatnew.MAX_TEXT)

    def test_a_field_that_is_not_text_is_refused(self) -> None:
        for field, value in (("name", ["a"]), ("kind", 1), ("text", {"a": 1}), ("lang", True), ("model", ["m"]), ("source", 5), ("permission", ["default"])):
            with self.subTest(field=field):
                with self.assertRaises(CommandError):
                    self.plan(**{field: value})

    def test_the_language_is_en_or_zh_and_english_is_the_default(self) -> None:
        self.assertEqual(self.plan(lang="")["lang"], "en")
        self.assertEqual(self.plan(lang="zh")["lang"], "zh")
        self.bad("lang", lang="fr")
        self.bad("lang", lang="[ZH]")

    def test_the_model_is_one_the_host_lists_and_the_level_one_it_has(self) -> None:
        self.bad("model", model="not-allowed")  # policy: nothing says it is allowed
        self.bad("model", model="off")  # the policy disables it
        self.bad("model", model="other")  # another provider's
        self.bad("model", model="nobody", thinking="")
        self.bad("thinking", thinking="max")
        self.bad("thinking", model="claude-haiku-4.5", thinking="low")  # this model has no levels
        self.bad("thinking", model="", thinking="low")  # a level with no model
        with self.assertRaises(CommandError):
            chatnew.validate(self.root, GOOD, [])  # the host listed nothing: no model can be taken


class MessageTests(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.new()  # a task `job1` to fork from

    def made(self, **change: Any) -> str:
        return chatnew.first_message(chatnew.validate(self.root, {**GOOD, **change}, MODELS))

    def test_a_new_task_message_is_fixed_english_with_the_name_the_kind_and_the_text_last(self) -> None:
        text = self.made()
        self.assertEqual(text, "This task is made from the board. Use the skill harness-my-task to open it now (harness task new). The name and the kind are given: do not ask for them.\n"
                               "- Task name: fresh-load\n- Kind: dev\n\nWhat to do:\nAdd a column to the load.")
        self.assertNotIn("fork", text)

    def test_a_fork_message_names_the_skill_and_the_source(self) -> None:
        text = self.made(source="job1", kind="test")
        self.assertEqual(text, "This task is made from the board. Use the skill harness-task-fork to start it from the task below (harness task fork). The name, the kind and the source are given: do not ask for them.\n"
                               "- New task name: fresh-load\n- Kind: test\n- Fork from: job1\n\nWhat to do:\nAdd a column to the load.")

    def test_the_language_mark_is_added_only_when_chinese_was_chosen_and_no_other_mark_is_there(self) -> None:
        for source in ("", "job1"):
            en, zh = self.made(source=source), None
            zh = chatnew.first_message(chatnew.validate(self.root, {**GOOD, "source": source, "lang": "zh"}, MODELS))
            self.assertFalse(en.startswith("["))
            self.assertEqual(zh, "[ZH] " + en)
            for text in (en, zh):
                self.assertNotRegex(text, r"(?i)\[\s*review\s*\]")
                self.assertNotIn("[EN]", text)
                self.assertNotIn("/compact", text)
                self.assertNotIn("[verify]", text)

    def test_what_the_person_wrote_is_in_as_typed(self) -> None:
        typed = "First line.\n\n  Indented {braces} and `ticks` and 100% of the rows."
        self.assertTrue(self.made(text=typed).endswith("What to do:\n" + typed))


def add_domains(root: Any, *names: str) -> None:
    for name in names:
        (root / "knowledge-base" / "domains" / name).mkdir(parents=True, exist_ok=True)


class DomainTests(TaskCase):
    """The knowledge base in the first message (1.6.18): the domains the knowledge bases have, none as a choice, the same words in the preview and in the real message."""

    def setUp(self) -> None:
        super().setUp()
        self.new()

    def made(self, **change: Any) -> str:
        return chatnew.first_message(chatnew.validate(self.root, {**GOOD, **change}, MODELS))

    def test_with_no_domain_in_any_knowledge_base_the_message_has_no_line_and_nothing_is_blocked(self) -> None:
        self.assertEqual(chatnew.validate(self.root, GOOD, MODELS)["domains"], [])
        self.assertNotIn("Knowledge base", self.made())
        self.assertNotIn("Knowledge base", chatnew.preview(self.root, {**GOOD, "name": ""}, MODELS)["text"])  # not in a preview with a problem either
        with self.assertRaises(CommandError) as caught:
            chatnew.validate(self.root, {**GOOD, "domains": ["Sales"]}, MODELS)
        self.assertEqual(str(caught.exception), refused("domain", names="Sales", known="-"))

    def test_domains_are_taken_as_their_folders_have_them_without_repeats(self) -> None:
        add_domains(self.root, "Sales", "finance")
        plan = chatnew.validate(self.root, {**GOOD, "domains": ["sales", "FINANCE", "Sales", " "]}, MODELS)
        self.assertEqual((plan["domains"], plan["domain_choice"]), (["Sales", "finance"], True))
        self.assertIn("\n- Knowledge base domains: Sales, finance (set them with harness task set-domain once the task is open; do not ask which)\n", self.made(domains=["sales", "finance"]))

    def test_none_is_a_choice_and_says_not_to_ask(self) -> None:
        add_domains(self.root, "Sales")
        for given in ({}, {"domains": []}, {"domains": None}):
            self.assertIn("- Knowledge base domains: none (do not set a domain and do not ask which)", self.made(**given))

    def test_the_knowledge_base_line_is_in_a_fork_message_too_and_before_the_text(self) -> None:
        add_domains(self.root, "Sales")
        text = self.made(source="job1", domains=["Sales"])
        self.assertLess(text.index("- Fork from: job1"), text.index("- Knowledge base domains: Sales"))
        self.assertLess(text.index("- Knowledge base domains: Sales"), text.index("What to do:"))

    def test_a_domain_that_is_not_there_or_a_value_that_is_not_text_is_refused(self) -> None:
        add_domains(self.root, "Sales")
        for given, names in ((["Nope"], "Nope"), (["Sales", "x/../y"], "x/../y"), (["Sales", "A" * 200], "A" * 80)):
            with self.subTest(given=given):
                with self.assertRaises(CommandError) as caught:
                    chatnew.validate(self.root, {**GOOD, "domains": given}, MODELS)
                self.assertEqual(str(caught.exception), refused("domain", names=names, known="Sales"))
        for bad in ("Sales", {"a": 1}, [1], ["Sales", None], ["x"] * (chatnew.MAX_DOMAINS + 1)):
            with self.subTest(bad=bad):
                with self.assertRaises(CommandError) as caught:
                    chatnew.validate(self.root, {**GOOD, "domains": bad}, MODELS)
                self.assertEqual(str(caught.exception), refused("field", field="domains"))

    def test_the_preview_is_the_real_message_when_the_fields_are_right_and_a_placeholder_one_when_not(self) -> None:
        add_domains(self.root, "Sales", "Finance")
        body = {**GOOD, "domains": ["Sales"]}
        shown = chatnew.preview(self.root, body, MODELS)
        self.assertEqual((shown["problem"], shown["text"]), ("", chatnew.first_message(chatnew.validate(self.root, body, MODELS))))
        for change, mark in (({"name": ""}, "<task name>"), ({"text": ""}, "<what to do>"), ({"kind": "x"}, "<kind>")):
            with self.subTest(change=change):
                part = chatnew.preview(self.root, {**body, **change}, MODELS)
                self.assertIn(mark, part["text"])
                self.assertTrue(part["problem"])
                self.assertIn("- Knowledge base domains: Sales", part["text"])
        junk = chatnew.preview(self.root, {"name": ["a"], "kind": 5, "text": {"x": 1}, "lang": True, "source": 3, "domains": "Sales"}, MODELS)  # nothing the page sends, none of it raises
        self.assertIn("<task name>", junk["text"])
        self.assertIn("<what to do>", junk["text"])
        self.assertIn("none (do not set", junk["text"])
        self.assertTrue(junk["problem"])

    def test_a_long_name_and_long_text_do_not_break_the_preview(self) -> None:
        shown = chatnew.preview(self.root, {**GOOD, "name": "n" * 500, "text": "t" * (chatnew.MAX_TEXT + 500)}, MODELS)
        self.assertTrue(shown["problem"])
        self.assertIn("n" * 80, shown["text"])
        self.assertNotIn("n" * 81, shown["text"])
        self.assertLessEqual(len(shown["text"]), chatnew.MAX_TEXT + 1000)


class WaitingMessageTable(unittest.TestCase):
    def test_every_refusal_has_both_languages(self) -> None:
        en, zh = json.loads((REPO / ".harness/engine/core/messages.en.json").read_text(encoding="utf-8")), json.loads((REPO / ".harness/engine/core/messages.zh.json").read_text(encoding="utf-8"))
        keys = [key for key in en if key.startswith(("create.", "board.new"))]
        self.assertGreater(len(keys), 30)
        self.assertEqual(sorted(keys), sorted(key for key in zh if key.startswith(("create.", "board.new"))))


class CreateCase(SendCase):
    """The board server and a fake host that also makes chats: `createSession` adds the chat to its list, as the host does once the first turn runs."""

    initiator = "vscode"

    def make_link(self) -> Any:
        link = super().make_link()
        self.new_chat = "ahp-chat:/new"
        self.made: List[Dict[str, Any]] = []
        self.listed_new = True
        old = self.host.answers["subscribe"]

        def subscribe(params: Dict[str, Any]) -> Dict[str, Any]:
            channel = params["channel"]
            if channel.startswith("ahp-session:/") and channel != "ahp-session:/abc":
                return {"snapshot": {"state": {"defaultChat": self.new_chat, "config": {"values": {}}}}}
            if channel == self.new_chat:
                return {"snapshot": {"state": {"status": 1, "turns": [], "activeTurn": None}}}
            return old(params)

        def create(params: Dict[str, Any]) -> Dict[str, Any]:
            self.made.append(params)
            if self.listed_new:
                item = summary(params["channel"], self.new_chat, self.folder, status=9, title="New chat")
                if self.initiator:
                    item["_meta"] = {ahp.INITIATOR_KEY: {"name": self.initiator}}  # the shape the real host gives
                self.items.append(item)
            return {}

        self.host.answers["subscribe"] = subscribe
        self.host.answers["createSession"] = create
        return link

    def methods(self) -> List[str]:
        return [str(message.get("method")) for message in self.host.seen]

    def make(self, **body: Any) -> Any:
        return self.request("POST", "/api/create", {**GOOD, "step": "act", **body}, cookie=self.cookie)


class CreateTests(CreateCase):
    def test_the_dialog_is_given_the_listed_models_the_kinds_and_the_tasks(self) -> None:
        status, data, _ = self.request("POST", "/api/create", {"step": "options"}, cookie=self.cookie)
        found = data["result"]
        self.assertEqual(status, 200, data)
        self.assertEqual([item["id"] for item in found["models"]], ["claude-haiku-5.5", "claude-haiku-4.5"])  # only what the policy enables; no other provider's
        self.assertEqual(found["kinds"], list(tasks.KINDS))
        self.assertEqual([item["name"] for item in found["sources"]], ["job1"])
        self.assertTrue(found["ready"])
        self.assertNotIn("permissions", found)

    def test_a_create_makes_the_chat_in_this_folder_without_a_worktree_and_sends_the_first_message_with_the_model(self) -> None:
        status, data, _ = self.make()
        self.assertEqual(status, 200, data)
        self.assertEqual(len(self.made), 1)
        call = self.made[0]
        self.assertTrue(call["channel"].startswith("ahp-session:/"))
        self.assertEqual(call["provider"], "copilotcli")
        self.assertEqual(call["workingDirectories"], [ahp.folder_uri(self.root)])
        self.assertEqual(call["config"], {"isolation": "folder", "mode": "interactive", "autoApprove": "autoApprove"})
        self.assertNotIn("model", call)  # createSession does not honour it: it goes on the message
        self.assertTrue(until(lambda: [item for item in self.dispatched() if item["channel"] == self.new_chat]))
        action = [item for item in self.dispatched() if item["channel"] == self.new_chat][0]["action"]
        self.assertEqual(action["type"], "chat/turnStarted")
        self.assertEqual(action["message"]["model"], {"id": "claude-haiku-5.5", "config": {"thinkingLevel": "low"}})
        self.assertEqual(action["message"]["origin"], {"kind": "user"})
        self.assertEqual(action["message"]["text"], data["result"]["text"])
        self.assertIn("harness-my-task", action["message"]["text"])
        self.assertTrue(action["message"]["text"].endswith("Add a column to the load."))

    def test_the_host_gets_autoApprove(self) -> None:
        self.assertEqual(self.make()[0], 200)
        self.assertEqual(self.made[0]["config"]["autoApprove"], "autoApprove")

    def test_the_client_name_is_not_sent_and_dispose_is_never_called(self) -> None:
        self.assertEqual(self.make()[0], 200)
        hello = [message for message in self.host.seen if message.get("method") == "initialize"][0]
        self.assertNotIn("clientInfo", hello["params"])  # without it the host records the client as vscode
        self.assertNotIn("disposeSession", self.methods())
        self.assertNotIn("disposeSession", (REPO / ".harness/engine/modules/task/vslink.py").read_text(encoding="utf-8").replace("`disposeSession`", ""))

    def test_the_initiator_is_read_back_and_a_different_one_is_warned_about(self) -> None:
        found = self.make()[1]["result"]
        self.assertEqual((found["initiator"], found["warn"], found["unchecked"]), ("vscode", "", False))
        CreateCase.initiator = "copilot-sdk"
        self.addCleanup(setattr, CreateCase, "initiator", "vscode")
        found = self.make(name="other")[1]["result"]
        self.assertEqual(found["initiator"], "copilot-sdk")
        self.assertEqual(found["warn"], messages.text("create.warn.initiator", initiator="copilot-sdk"))
        self.assertIn("copilot-sdk", found["warn"])

    def test_an_initiator_the_host_has_not_told_is_said_to_be_unchecked(self) -> None:
        self.listed_new = False
        old = vslink.INITIATOR_WAIT
        vslink.INITIATOR_WAIT = 0.6
        self.addCleanup(setattr, vslink, "INITIATOR_WAIT", old)
        found = self.make()
        self.assertEqual(found[0], 200, found[1])
        self.assertEqual((found[1]["result"]["initiator"], found[1]["result"]["warn"], found[1]["result"]["unchecked"]), ("", "", True))

    def test_a_fork_names_the_source_and_the_skill(self) -> None:
        status, data, _ = self.make(source="job1", kind="test", lang="zh")
        self.assertEqual(status, 200, data)
        text = data["result"]["text"]
        self.assertTrue(text.startswith("[ZH] This task is made from the board. Use the skill harness-task-fork"))
        self.assertIn("- Fork from: job1", text)
        self.assertIn("- Kind: test", text)

    def test_nothing_reaches_the_host_when_a_field_is_wrong(self) -> None:
        for body in ({"name": ""}, {"name": "job1"}, {"kind": "x"}, {"source": "nope"}, {"text": ""}, {"model": "nobody"}, {"permission": "autopilot"}, {"lang": "fr"}):
            with self.subTest(body=body):
                status, data, _ = self.make(**body)
                self.assertEqual(status, 409, data)
                self.assertTrue(data["error"])
        self.assertEqual(self.made, [])
        self.assertNotIn("createSession", self.methods())
        self.assertEqual([item for item in self.dispatched() if item["channel"] == self.new_chat], [])

    def test_a_second_create_with_the_name_of_a_chat_just_made_is_refused(self) -> None:
        self.assertEqual(self.make()[0], 200)
        status, data, _ = self.make()
        self.assertEqual((status, data["error"]), (409, refused("exists", name="fresh-load")))
        self.assertEqual(len(self.made), 1)

    def test_the_preview_shows_the_message_and_whether_it_can_go(self) -> None:
        status, data, _ = self.make(step="preview")
        self.assertEqual(status, 200, data)
        self.assertEqual((data["result"]["blocked"], data["result"]["permission"]), ("", "allow-all"))
        self.assertTrue(data["result"]["text"].startswith("This task is made from the board."))
        self.assertEqual(self.made, [])  # a preview makes nothing
        found = self.make(step="preview", name="")  # a field that is not right yet: the message still grows (a <placeholder>), and the problem is told
        self.assertEqual(found[0], 200, found[1])
        self.assertIn("- Task name: <task name>", found[1]["result"]["text"])
        self.assertTrue(found[1]["result"]["problem"])
        self.assertEqual(self.made, [])

    def test_the_task_the_agent_opens_is_bound_to_the_chat_and_keeps_the_model(self) -> None:
        text = self.make()[1]["result"]["text"]
        self.assertTrue(until(lambda: self.vs.waiting_names() == ["fresh-load"]))
        self.assertEqual(self.vs.waiting_names(), ["fresh-load"])
        self.prompt("start", session="sess-fresh")
        self.new(name="fresh-load", session="sess-fresh")  # what the agent does when it reads the message
        fresh = f"{tasks.TASKS_DIR}/fresh-load"
        self.assertTrue(until(lambda: (self.data(fresh).get("chat") or {}).get("how") == "board"), self.data(fresh))
        found = self.data(fresh)["chat"]
        self.assertEqual(found["session"], self.made[0]["channel"])
        self.assertEqual(found["chat"], self.new_chat)
        self.assertEqual(found["model"], {"id": "claude-haiku-5.5", "config": {"thinkingLevel": "low"}})  # the next sends carry it
        self.assertEqual(chatsend.model_of(self.data(fresh)), found["model"])
        self.assertTrue(until(lambda: self.vs.waiting_names() == []))
        self.assertTrue(until(lambda: self.vs.status()["bound"] == 2), self.vs.status())  # job1 by its session id, the new one as made by the board
        line = json.loads((self.root / fresh / ".task" / "sent.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((line["kind"], line["text"], line["chat"], line["permission"]), ("create", text, self.new_chat, "allow-all"))
        self.assertIn("create", [item["what"] for item in self.data(fresh)["events"]])
        self.assertEqual(self.data()["chat"]["how"], "sdk")  # the other task is as it was

    def test_a_chat_the_host_does_not_list_yet_is_tracked_at_once_and_asked_for_again_soon_not_after_the_full_relist(self) -> None:
        self.listed_new = False  # the host lists a chat only once its first turn runs
        old = vslink.EXPECT_EVERY
        vslink.EXPECT_EVERY = 0.2
        self.addCleanup(setattr, vslink, "EXPECT_EVERY", old)
        oldwait = vslink.INITIATOR_WAIT
        vslink.INITIATOR_WAIT = 0.3
        self.addCleanup(setattr, vslink, "INITIATOR_WAIT", oldwait)
        self.assertEqual(vslink.RELIST_EVERY, 180.0)
        self.assertEqual(self.make()[0], 200)
        resource = self.made[0]["channel"]
        with self.vs.lock:
            self.assertEqual(self.vs.sessions[resource]["defaultChat"], self.new_chat)  # in the cache before the host lists it
        time.sleep(0.6)  # more lists happen; the stub is not dropped by a list without the chat
        with self.vs.lock:
            self.assertIn(resource, self.vs.sessions)
        self.items.append(summary(resource, self.new_chat, self.folder, status=9, title="Listed now"))
        self.assertTrue(until(lambda: self.vs.sessions.get(resource, {}).get("title") == "Listed now"), "the real entry did not come within seconds")
        self.assertNotIn(resource, self.vs.expect)

    def test_a_task_of_another_name_does_not_take_the_chat(self) -> None:
        self.make()
        self.prompt("start", session="sess-x")
        self.new(name="something-else", session="sess-x")
        with self.vs.lock:
            self.vs.dirty = True
        self.vs.wake.set()
        time.sleep(1.0)  # a pass of the thread at least
        self.assertEqual(self.vs.waiting_names(), ["fresh-load"])
        self.assertNotEqual((self.data(f"{tasks.TASKS_DIR}/something-else").get("chat") or {}).get("how"), "board")


class KnowledgeBaseServerTests(CreateCase):
    def test_the_options_list_the_domains_and_the_act_sends_the_chosen_ones_in_the_first_message(self) -> None:
        options = lambda: self.request("POST", "/api/create", {"step": "options"}, cookie=self.cookie)[1]["result"]  # noqa: E731
        self.assertEqual(options()["domains"], [])  # no knowledge base domain: the dialog says so and goes on
        self.assertEqual(self.make()[0], 200)
        add_domains(self.root, "Sales", "finance")
        self.assertEqual(options()["domains"], ["finance", "Sales"])
        status, data, _ = self.make(name="with-kb", domains=["sales"])
        self.assertEqual(status, 200, data)
        self.assertIn("- Knowledge base domains: Sales (set them with harness task set-domain", data["result"]["text"])
        self.assertTrue(until(lambda: len(self.made) == 2))
        status, data, _ = self.make(name="none-kb")
        self.assertIn("domains: none (do not set", data["result"]["text"])
        before = len(self.made)
        status, data, _ = self.make(name="bad-kb", domains=["../etc"])
        self.assertEqual((status, data["error"]), (409, refused("domain", names="../etc", known="finance, Sales")))
        self.assertEqual(len(self.made), before)

    def test_the_preview_is_the_text_of_the_act_and_needs_no_vs_code(self) -> None:
        add_domains(self.root, "Sales")
        body = {"domains": ["Sales"]}
        shown = self.make(step="preview", **body)[1]["result"]
        self.assertEqual(self.make(name="fresh-load", **body)[1]["result"]["text"], shown["text"])  # the same code path: the same words
        self.vs.ready, self.vs.why = False, "none"
        found = self.make(step="preview", name="other", model="", thinking="", **body)[1]["result"]  # the dialog has no model to pick while the host is out
        self.assertEqual((found["blocked"], found["problem"]), (refused("not-ready"), ""))
        self.assertIn("- Task name: other", found["text"])  # still made, so the person sees what would go
        self.assertEqual(len(self.made), 1)


class NotReadyTests(CreateCase):
    def test_a_create_fails_clearly_when_vs_code_is_not_ready_and_makes_nothing(self) -> None:
        self.vs.ready, self.vs.why = False, "none"
        status, data, _ = self.make()
        self.assertEqual((status, data["error"]), (409, refused("not-ready")))
        self.assertEqual(self.made, [])
        self.assertEqual(self.request("POST", "/api/create", {**GOOD, "step": "preview"}, cookie=self.cookie)[1]["result"]["blocked"], refused("not-ready"))
        found = self.request("POST", "/api/create", {"step": "options"}, cookie=self.cookie)[1]["result"]
        self.assertEqual((found["ready"], found["why"], found["models"]), (False, "none", []))

    def test_a_link_that_is_switched_off_says_so(self) -> None:
        self.vs.enabled = False
        status, data, _ = self.make()
        self.assertEqual((status, data["error"]), (409, refused("off")))
        self.assertEqual(self.made, [])

    def test_a_host_that_refuses_gives_the_name_of_the_error_only(self) -> None:
        def fail(_params: Dict[str, Any]) -> Dict[str, Any]:
            raise ahp.AhpError(f"createSession failed: bad token {TOKEN}")

        self.host.answers["createSession"] = fail
        status, data, _ = self.make()
        self.assertEqual(status, 409)
        self.assertEqual(data["error"], refused("host", error="AhpError"))
        self.assertNotIn(TOKEN, json.dumps(data))


class PairedOnlyTests(CreateCase):
    def test_every_step_needs_the_header_and_the_pairing(self) -> None:
        for step in ("options", "preview", "act"):
            with self.subTest(step=step):
                body = {**GOOD, "step": step}
                self.assertEqual(self.request("POST", "/api/create", body, cookie=self.cookie, header=False)[0], 403)  # another site cannot send it
                self.assertEqual(self.request("POST", "/api/create", body, cookie="")[0], 403)  # not the paired browser
        self.assertEqual(self.request("POST", "/api/create", {**GOOD, "step": "act"}, cookie=self.cookie, origin="http://evil.example")[0], 403)
        self.assertEqual(self.made, [])

    def test_a_get_cannot_create_and_no_answer_holds_the_token(self) -> None:
        self.assertNotEqual(self.request("GET", "/api/create")[0], 200)
        found = json.dumps([self.make()[1], self.request("POST", "/api/create", {"step": "options"}, cookie=self.cookie)[1], self.request("POST", "/api/status", {})[1], self.request("POST", "/api/board", {})[1]])
        self.assertNotIn(TOKEN, found)
        self.assertNotIn("tkn", found)

    def test_the_page_has_the_button_the_dialog_and_the_texts(self) -> None:
        page = self.request("GET", "/")[1]["text"]
        self.assertIn("CHAT.create()", page)
        self.assertIn("function create()", page)
        self.assertIn('"board.new.go"', page)
        self.assertIn('"stop", "create"', page)


class InitiatorTests(unittest.TestCase):
    def test_the_host_gives_a_name_in_an_object_and_a_string_is_taken_too(self) -> None:
        self.assertEqual(ahp.initiator_of({ahp.INITIATOR_KEY: {"name": "vscode"}}), "vscode")
        self.assertEqual(ahp.initiator_of({ahp.INITIATOR_KEY: "vscode"}), "vscode")
        for bad in (None, {}, {ahp.INITIATOR_KEY: {}}, {ahp.INITIATOR_KEY: 5}, "x"):
            self.assertEqual(ahp.initiator_of(bad), "")


class ModelListTests(unittest.TestCase):
    def test_only_copilot_models_the_policy_enables_are_offered_with_their_levels(self) -> None:
        self.assertEqual([item["id"] for item in MODELS], ["claude-haiku-5.5", "claude-haiku-4.5"])
        self.assertEqual(MODELS[0]["thinking"], {"levels": ["low", "medium"], "default": "medium"})
        self.assertIsNone(MODELS[1]["thinking"])


class AdoptTests(TaskCase):
    def test_a_binding_is_written_without_a_new_update_time_and_an_earlier_model_stays(self) -> None:
        self.new()
        before = self.data()["updated_at"]
        made = {"session": "ahp-session:/z", "chat": "ahp-chat:/z", "title": "t", "model": {"id": "m1"}}
        found = chatlink.adopt(self.root, TASK, made)
        self.assertEqual((found["how"], found["session"], found["model"]), ("board", "ahp-session:/z", {"id": "m1"}))
        self.assertEqual(self.data()["updated_at"], before)
        chatlink.adopt(self.root, TASK, dict(made, model={"id": "m2"}))
        self.assertEqual(self.data()["chat"]["model"], {"id": "m1"})  # what the task already holds is not overwritten
        self.assertIsNone(chatlink.adopt(self.root, f"{tasks.TASKS_DIR}/nobody", made))


class SettingsRuleTests(unittest.TestCase):
    """`chat.tools.terminal.autoApprove` in `.vscode/settings.json`. VS Code splits a command into sub-commands (tree-sitter) and tests each rule against each one; a rule with `matchCommandLine`
    is tested against the whole line and approves it when the sub-commands are not all approved (read from `workbench.desktop.main.js`, 1.144). So the rules here are plain `true`, and they also refuse
    every metacharacter that chains, redirects or substitutes, whatever way the line is read."""

    ALLOWED = ("open", "new", "fork", "list", "status")

    @classmethod
    def rules(cls) -> Dict[str, Any]:
        return json.loads((REPO / ".vscode" / "settings.json").read_text(encoding="utf-8"))["chat.tools.terminal.autoApprove"]

    def compiled(self) -> List["re.Pattern[str]"]:
        out = []
        for key in self.rules():
            found = re.match(r"^/(?P<pattern>.+)/(?P<flags>[dgimsuvy]*)$", key)  # the way VS Code reads a key that is a regular expression
            self.assertIsNotNone(found, key)
            self.assertEqual(found.group("flags"), "")
            out.append(re.compile(found.group("pattern")))
        return out

    def approved(self, line: str) -> bool:
        """What VS Code does with a line: split into sub-commands; approved when every one matches a rule (no rule is a command-line rule, so there is no second chance)."""
        parts = [part.strip() for part in re.split(r"&&|\|\||[;|\n]", line) if part.strip()]
        return bool(parts) and all(any(rule.search(part) for rule in self.compiled()) for part in parts)

    def test_the_rules_are_plain_allow_rules_and_two_forms_of_the_command(self) -> None:
        rules = self.rules()
        self.assertEqual(len(rules), 2)
        self.assertEqual(list(rules.values()), [True, True])  # not `{approve, matchCommandLine}`: a whole-line rule would approve a chain that starts with an allowed command
        self.assertTrue(any(key.startswith("/^harness") for key in rules))
        self.assertTrue(any("bin" in key and "harness" in key for key in rules))

    def test_the_shipped_command_forms_are_approved(self) -> None:
        for command in ("harness task new job1 --kind dev --session-id abc-123", "harness task open job1 --session-id abc-123", "harness task fork next --from job1 --kind test --session-id abc",
                        "harness task list", "harness task list --all", "harness task status", "harness task status job1", 'harness task new "x" --kind qa --session-id s',
                        "harness.cmd task new job1 --kind dev --session-id s", "harness.cmd task list",
                        "./.harness/bin/harness task new job1 --kind dev --session-id s", ".harness/bin/harness task open job1 --session-id s", "./.harness/bin/harness.cmd task fork a --from b --kind dev --session-id s",
                        ".\\.harness\\bin\\harness.cmd task status", ".harness\\bin\\harness task list"):
            with self.subTest(command=command):
                self.assertTrue(self.approved(command), command)

    def test_a_chain_a_redirect_a_substitution_or_a_longer_name_is_not_approved(self) -> None:
        for command in ("harness task new x && rm y", "harness task new x; rm -rf .", "harness task list | sh", "harness task list || curl evil", "harness task new x\nrm y", "harness task new x & rm y",
                        "harness task new x > .harness/policies/gate.json", "harness task list >> f", "harness task status < f", "harness task new $(id)", "harness task new `id`", "harness task new x --kind $(id)",
                        "harness task newer", "harness task statusx", "harness task opens", "harness task list-all", "harness tasks list", "xharness task list", "harness  task", "harness task",
                        "./.harness/bin/harness task new x && rm y", "harness.cmd task new x & del y", "./.harness/bin/../../x task new",
                        "python3 .harness/engine/cli.py task new x", "python .harness/engine/cli.py task list", "/usr/bin/harness task new x", "sudo harness task new x", "env X=1 harness task new x"):
            with self.subTest(command=command):
                self.assertFalse(self.approved(command), command)

    def test_a_chain_is_refused_even_if_it_were_read_as_one_line(self) -> None:
        rules = self.compiled()
        for command in ("harness task new x && rm y", "harness task list; rm y", "harness task new x | tee f", "harness task list > f"):
            with self.subTest(command=command):
                self.assertFalse(any(rule.search(command) for rule in rules), command)  # no match of the whole line either

    def test_the_commands_only_a_person_may_run_and_the_ones_that_change_things_are_not_approved(self) -> None:
        for sub in ("approve-plan", "confirm-req", "approve-promote", "recover", "pause", "resume", "offwork", "onwork", "autorun on", "review set --n 2", "review extend", "review waive", "review dismiss",
                    "board", "board --serve", "close", "promote", "delete", "fetch repo/a.sql", "upgrade --tier full", "diff", "archive", "intake convert", "handoff tests", "set-domain x", "goal"):
            for head in ("harness task ", "harness.cmd task ", "./.harness/bin/harness task "):
                with self.subTest(command=head + sub):
                    self.assertFalse(self.approved(head + sub), head + sub)
        for command in ("harness approve-command", "harness admin on", "harness logs prune", "harness kb map", "harness target list", "harness reinstall --from x", "harness company sync"):
            with self.subTest(command=command):
                self.assertFalse(self.approved(command), command)

    def test_the_gate_still_refuses_the_person_only_commands_the_rules_do_not_cover(self) -> None:
        gate = json.loads((REPO / ".harness" / "policies" / "gate.json").read_text(encoding="utf-8"))
        pattern = next(item["pattern"] for item in gate["terminal"]["deny"] if "approve-plan" in item["pattern"])
        person = re.compile(pattern, re.IGNORECASE)
        for command in ("harness task approve-plan", "harness.cmd task confirm-req", "./.harness/bin/harness task review set --n 2"):
            self.assertTrue(person.search(command), command)  # the gate refuses them
            self.assertFalse(self.approved(command), command)  # and the rule would not have approved them
        for command in ("harness task new x --kind dev --session-id s", "harness task list", "./.harness/bin/harness task fork a --from b --kind dev --session-id s"):
            self.assertFalse(person.search(command), command)  # the approved forms are not what the gate refuses


if __name__ == "__main__":
    unittest.main()
