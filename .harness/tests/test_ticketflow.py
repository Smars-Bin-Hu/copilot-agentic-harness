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
