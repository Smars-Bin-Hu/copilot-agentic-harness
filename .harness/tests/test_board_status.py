"""The status marks of the list and the lobby card (1.6.14, B85b): what the server adds to a row (the start of the turn that runs, the TODO counts, read once for each change of TODO.md),
and what the page files must keep (one shared part, one timer, a message for each text, the card in place of the old hover)."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401 - puts the engine on the path

from core import messages, tasks
from modules.task import autorun, taskboard, taskhtml, tasksub

WEB = taskhtml.WEB


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class ServerTests(unittest.TestCase):
    def test_a_chat_with_a_turn_that_runs_tells_when_it_began_and_an_idle_one_does_not(self) -> None:
        running = {"activeTurn": {"id": "t", "startedAt": "2026-10-31T11:00:00.000Z", "responseParts": [], "usage": None}, "turns": []}
        self.assertEqual(tasksub.facts(running)["started"], "2026-10-31T11:00:00.000Z")
        idle = {"activeTurn": None, "turns": [{"id": "t", "startedAt": "2026-10-31T10:00:00.000Z", "responseParts": []}]}
        self.assertEqual(tasksub.facts(idle)["started"], "")
        self.assertEqual(tasksub.facts({})["started"], "")

    def test_the_todo_counts_are_read_again_only_when_the_file_changed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root, task = Path(folder), "tasks/t1"
            (root / "tasks" / "t1").mkdir(parents=True)
            path = root / "tasks" / "t1" / tasks.TODO_FILE
            path.write_text("- [x] one\n- [ ] two\n- [ ] three\n", encoding="utf-8")
            taskboard._todo.clear()
            with mock.patch.object(tasks, "task_dir", lambda base, name: Path(base) / name):
                with mock.patch.object(autorun, "steps_of", wraps=autorun.steps_of) as reads:
                    self.assertEqual(taskboard.todo_counts(root, task), {"done": 1, "total": 3})
                    for _ in range(5):  # the board asks every 3 seconds: a quiet task costs one stat
                        taskboard.todo_counts(root, task)
                    self.assertEqual(reads.call_count, 1)
                    path.write_text("- [x] one\n- [x] two\n- [ ] three\n- [ ] four\n", encoding="utf-8")
                    self.assertEqual(taskboard.todo_counts(root, task), {"done": 2, "total": 4})
                    self.assertEqual(reads.call_count, 2)
                    path.write_text("# nothing to tick\n", encoding="utf-8")
                    self.assertIsNone(taskboard.todo_counts(root, task))  # no step: no bar, never "0/0"
                    path.unlink()
                    self.assertIsNone(taskboard.todo_counts(root, task))


class PageTests(unittest.TestCase):
    def page(self, serve: bool) -> str:
        row = {"task": "a", "name": "a", "status": "open", "kind": "dev", "tier": "full", "state": "working", "waiting": None, "waiting_why": "", "waited_s": None, "brief": None, "report": "", "actions": [],
               "todo": {"done": 3, "total": 8}, "chat": {"bound": True, "state": "busy", "model": "claude-sonnet-5-5", "started_at": "2026-10-31T11:00:00.000Z"}}
        return taskhtml.board_page([row], "2026-10-31T00:00:00+00:00", serve={"actions": [], "refresh": 3} if serve else None)

    def test_the_part_is_before_what_uses_it_and_its_style_after_the_look(self) -> None:
        for served in (False, True):
            page = self.page(served)
            self.assertLess(page.index("function stateOf("), page.index("const Status = (function"))
            self.assertLess(page.index("const Status = (function"), page.index("const Lobby = (function"))
            self.assertLess(page.index("/* The look of the board and the task page"), page.index(".st-row{display:flex"))
        self.assertNotIn("const Status", taskhtml.task_page({"name": "a"}))  # the report page does not have it

    def test_one_timer_for_every_run_time_and_the_animations_keep_step_with_the_clock(self) -> None:
        status, lobby, board = source("status.js"), source("lobby.js"), source("board.js")
        self.assertEqual(status.count("setInterval("), 1)
        self.assertNotIn("setInterval(", lobby + board.replace("pollEvery", ""))
        css = source("status.css")
        for name in ("stspin", "stblink", "stlive"):
            self.assertRegex(css, r"animation:%s [^;}]*;animation-delay:calc\(var\(--t,0ms\)\*-1\)" % name)
        self.assertIn("setProperty(\"--t\"", status)

    def test_the_list_draws_the_marks_and_no_longer_the_last_tool_or_reply(self) -> None:
        board = source("board.js")
        self.assertIn("Status.row(row, {live})", board)
        self.assertNotIn("subNodes(", board)
        self.assertNotIn("subLine(", board)
        self.assertIn("subNodes(", source("common.js"))  # the task page still draws `sub`
        self.assertNotIn(".sub-line", source("ui.css") + source("page.css"))

    def test_the_card_replaces_the_old_hover(self) -> None:
        lobby, css = source("lobby.js"), source("lobby.css")
        self.assertNotIn("lb-mini", lobby + css)
        self.assertNotIn("STATE_TEXT", lobby)
        for name in ("actions: actionStrip", "figures"):
            self.assertIn(name, source("board.js"))
        self.assertIn("Status.place(card", lobby)
        self.assertIn("matchMedia(\"(hover: none), (max-width: 700px)\")", lobby)  # touch or a narrow window: a click opens it
        self.assertIn("event.key !== \"Escape\"", lobby)
        self.assertIn(".lb-card{position:fixed", css)
        # the poll fills the card in place: nothing in update() builds it again
        update = lobby[lobby.index("function update(rows, live)"):]
        self.assertIn("fill(same)", update)
        self.assertNotIn("card.replaceChildren", lobby)

    def test_every_text_of_the_marks_is_in_both_languages(self) -> None:
        used = set()
        for name in ("status.js", "lobby.js", "board.js"):
            used |= set(re.findall(r'\bt\("(board\.status\.[\w.]+)"', source(name)))
        used |= {"board.status.stage." + word for word in ("done", "run", "wait", "now", "bad", "todo")}  # chosen by name in stages()
        self.assertTrue(used)
        for language in ("en", "zh"):
            table = messages.table(language)
            self.assertEqual([key for key in sorted(used) if key not in table], [], language)
            data = json.loads((Path(messages.__file__).parent / f"messages.{language}.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(key for key in data if key.startswith("board.status.")), sorted(key for key in messages.table("en") if key.startswith("board.status.")))
        for key in used:
            self.assertTrue(key.startswith("board.status."))  # the page gets only the prefixes it is told (taskhtml.TEXT_PREFIXES)

    def test_the_stage_colours_are_tokens_of_both_themes(self) -> None:
        tokens = source("tokens.css")
        light, dark = tokens.split('html[data-theme="dark"]')
        for name in ("--run:", "--run-bg:", "--run-line:", "--st-todo:", "--st-todo-ring:"):
            self.assertIn(name, light)
            self.assertIn(name, dark)
        css = source("status.css")
        self.assertNotRegex(re.sub(r"/\*.*?\*/", "", css, flags=re.S), r"#[0-9a-fA-F]{3,8}\b")  # no colour of its own: tokens only
        for kind in ("done", "run", "wait", "now", "bad", "todo"):
            self.assertIn(".st-d.k-%s" % kind, css) if kind != "todo" else self.assertIn("var(--st-todo)", css)


if __name__ == "__main__":
    unittest.main()
