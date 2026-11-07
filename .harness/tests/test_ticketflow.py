"""1.7.20: a small ticket chore is a Q&A task (its writes still go through the gate; the close tells of a held one), tickets can be linked from the New task window and the task page,
and a connection named in a prompt brings its fields."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from test_outbox import OutboxCase, COMMENT
from taskcase import TaskCase

from core import toolpacks
from modules.task import boardserve, chatnew, task as task_ops, tasklife
from modules.task.common import CommandError

import support  # noqa: F401
from test_toolpacks import make


class QaChore(OutboxCase):
    def test_a_write_in_a_qa_task_is_held_and_the_close_tells_of_it(self) -> None:
        self.new(kind="qa")
        refused = self.term(COMMENT)
        self.assertEqual(refused["permissionDecision"], "deny")
        self.assertEqual(len(self.drafts()), 1, "held, with a draft, in a light task as in a full one")
        done = task_ops.close(self.root, "job1", check_todo=False)
        self.assertIn(task_ops.say("task.close.held", count=1, name="job1"), done["next"])

    def test_a_close_with_nothing_held_says_nothing_of_it(self) -> None:
        self.new(kind="qa")
        self.assertNotIn("next", task_ops.close(self.root, "job1", check_todo=False))


class Links(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        toolpacks.add(self.root, str(make(Path(holder.name) / "tracker", links={"trk": {"label": "Ticket", "type": "tracker", "url": "https://tracker.example.org/{org}/item/{id}"}})))
        self.new()

    def test_the_link_types_come_from_the_installed_tool_packs(self) -> None:
        self.assertEqual(toolpacks.link_types(self.root), [{"type": "trk", "label": "Ticket", "toolpack": "tracker"}])

    def test_the_new_task_window_takes_several_tickets_and_checks_each(self) -> None:
        self.assertEqual(chatnew.links_of({"links": "trk:42, ado:300100  trk:42"}), ["trk:42", "ado:300100"])
        self.assertEqual(chatnew.links_of({}), [])
        self.assertEqual(chatnew.links_of({"links": ["trk:1"]}), ["trk:1"])
        for bad in ("nonsense", "TRK:1", "trk:", "trk:a b"):
            with self.assertRaises(CommandError):
                chatnew.links_of({"links": bad.replace("a b", "a|b")})
        with self.assertRaises(CommandError):
            chatnew.links_of({"links": " ".join(f"t:{n}" for n in range(chatnew.MAX_LINKS + 1))})
        with self.assertRaises(CommandError):
            chatnew.links_of({"links": 5})

    def test_the_first_message_asks_the_agent_to_link_them(self) -> None:
        plan = {"name": "n", "kind": "qa", "source": "", "text": "Read it.", "lang": "en", "links": ["trk:42"], "domains": [], "domain_choice": False}
        self.assertIn("Tickets to link: trk:42", chatnew.first_message(plan))
        self.assertNotIn("Tickets to link", chatnew.first_message(dict(plan, links=[])))

    def test_the_page_adds_and_takes_away_a_link_with_one_click(self) -> None:
        board = boardserve.Board(self.root, False, 8798, ["task link"])
        self.assertEqual(board.act("task link", "job1", "act", env_name="trk:42", who="on")["links"], ["trk:42"])
        self.assertEqual(board.act("task link", "job1", "act", env_name="trk:42", who="off")["links"], [])
        with self.assertRaises(CommandError):
            board.act("task link", "job1", "act", env_name="nonsense", who="on")
        with self.assertRaises(CommandError):
            boardserve.Board(self.root, False, 8798, ["pause"]).act("task link", "job1", "act", env_name="trk:42", who="on")
        self.assertIn("task link", json.loads((self.root / ".harness/policies/task.json").read_text())["board"]["actions"])


class HeldCallCard(TaskCase):
    """1.7.20 (⑫): the sample pack's `say` and `body` make the card of a held comment: a sentence, the text it writes, the raw command folded away."""

    def setUp(self) -> None:
        super().setUp()
        from support import REPO

        toolpacks.add(self.root, str(REPO / ".harness" / "examples" / "toolpacks" / "demotracker"))
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {"demo": {"type": "demotracker", "env": "none", "project": "DEMO"}}}), encoding="utf-8")
        self.new(kind="qa")
        for ref in ("demo:7", "demo:9"):
            tasklife.link(self.root, "job1", ref, True)  # a write names an item the task is linked to
        (self.task / "notes.md").write_text("Checked the load.\nAll good.\n", encoding="utf-8")

    def held(self, command: str) -> dict:
        from support import pre_tool
        from modules.task import taskdesk

        data = pre_tool("sess-main", "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        self.assertEqual(self.hook(data)["permissionDecision"], "deny")
        return taskdesk.outbox_view(self.root, f"{tasks_dir()}/job1")[-1]  # the newest

    def test_a_comment_from_a_file_shows_the_sentence_and_the_file(self) -> None:
        card = self.held("demotracker --project DEMO comment 7 --file notes.md")
        self.assertEqual(card["say"], "Add a comment to ticket 7")
        self.assertEqual((card["body"]["from"], card["body"]["path"], card["body"]["lines"], card["body"]["text"]), ("file", "notes.md", 2, "Checked the load.\nAll good.\n"))

    def test_a_comment_as_text_and_a_comment_after_the_id(self) -> None:
        card = self.held('demotracker --project DEMO comment 7 --text "PR \\"12\\" merged"')
        self.assertEqual(card["body"], dict(card["body"], text='PR "12" merged', **{"from": "text"}))

    def test_a_path_from_the_repository_root_and_a_full_path_are_found_and_a_line_break_in_text_is_one(self) -> None:
        relative = self.task.relative_to(self.root).as_posix() + "/notes.md"  # the agent's terminal starts at the repository root
        card = self.held(f"demotracker --project DEMO comment 7 --file {relative}")
        self.assertEqual((card["body"].get("missing"), card["body"]["lines"]), (None, 2))
        card = self.held(f"demotracker --project DEMO comment 7 --file {self.task / 'notes.md'}")
        self.assertEqual((card["body"].get("missing"), card["body"]["lines"]), (None, 2))
        card = self.held('demotracker --project DEMO comment 7 --text "one\\ntwo \\"q\\""')
        self.assertEqual(card["body"]["text"], 'one\ntwo "q"')

    def test_a_file_that_is_not_in_the_task_is_marked_not_read(self) -> None:
        card = self.held("demotracker --project DEMO comment 7 --file ../../outside.md")
        self.assertTrue(card["body"]["missing"])
        self.assertEqual(card["body"]["text"], "")

    def test_a_long_file_is_cut_and_a_call_without_words_has_none(self) -> None:
        from modules.task import cmdview

        (self.task / "big.md").write_text("line\n" * 5000, encoding="utf-8")
        big = self.held("demotracker --project DEMO comment 7 --file big.md")["body"]
        self.assertEqual((len(big["text"]), big["lines"], big["cut"]), (cmdview.BODY_CHARS, 5000, True))
        self.assertEqual(self.held("demotracker --project DEMO set-state 9 Done")["say"], "Set ticket 9 to Done")

    def test_the_rules_are_checked_when_the_type_is_read(self) -> None:
        from core import connections
        from core import systems

        kind = dict(connections.types(self.root)["demotracker"])
        self.assertEqual(connections.type_problems(kind), [])
        self.assertTrue(any("bad pattern" in item for item in connections.type_problems(dict(kind, say=[{"pattern": "(", "text": "x"}]))))
        self.assertTrue(any("from" in item for item in connections.type_problems(dict(kind, body=[{"pattern": "a(b)", "from": "net"}]))))
        self.assertTrue(systems.validate({"x": {"reach": {"cli": "x"}, "body": [{"pattern": "(a)", "from": "net"}]}}))
        self.assertEqual(systems.validate({"x": {"reach": {"cli": "x"}, "say": [{"pattern": "(a)", "text": "t {1}"}], "body": [{"pattern": "(a)", "from": "file"}]}}), [])


def tasks_dir() -> str:
    from core import tasks

    return tasks.TASKS_DIR
