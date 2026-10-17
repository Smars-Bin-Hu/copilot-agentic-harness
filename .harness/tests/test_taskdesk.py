"""The task page (M16): markdown read into a tree that the page draws without markup, and /task/<name> on the board server."""

from __future__ import annotations

import json
import unittest

import support  # noqa: F401  (puts the engine on sys.path)
from test_boardserve import ServeCase

from modules.task import mdtree, taskdesk


def kinds(spans):
    return [span["t"] for span in spans]


class MarkdownTests(unittest.TestCase):
    def test_what_task_files_use(self) -> None:
        tree = mdtree.parse("# Plan\n\nSee **this** and `code` and *that*.\n\n| a | b |\n| --- | ---: |\n| 1 | x \\| y |\n\n```sql\nselect 1;\n```\n\n> note\n\n---\n")
        self.assertEqual([block["t"] for block in tree["blocks"]], ["h", "p", "table", "code", "quote", "hr"])
        self.assertEqual(kinds(tree["blocks"][1]["spans"]), ["text", "b", "text", "code", "text", "i", "text"])
        self.assertEqual(tree["blocks"][2]["align"], ["", "right"])
        self.assertEqual(tree["blocks"][2]["rows"][0][1], [{"t": "text", "v": "x | y"}])
        self.assertEqual(tree["blocks"][3], {"t": "code", "lang": "sql", "text": "select 1;"})

    def test_nested_checklists_and_their_progress(self) -> None:
        tree = mdtree.parse("- [x] one\n- [ ] two\n  - [x] two a\n  - [ ] two b\n- plain\n\n3. three\n4. four\n")
        items = tree["blocks"][0]["items"]
        self.assertEqual([item["check"] for item in items], [True, False, None])
        self.assertEqual([item["check"] for item in items[1]["blocks"][0]["items"]], [True, False])
        self.assertEqual(tree["blocks"][1]["start"], 3)
        self.assertEqual(mdtree.checkboxes(tree), (2, 4))

    def test_nothing_an_agent_writes_becomes_markup_or_a_dangerous_link(self) -> None:
        tree = mdtree.parse('<script>alert(1)</script>\n\n[a](javascript:alert(1)) [b](data:text/html,x) [c](vbscript:x) [d](https://ok.example/a_(b)) [e](PLAN.md) [f](C:\\x\\y.sql)\n')
        self.assertEqual(tree["blocks"][0], {"t": "p", "spans": [{"t": "text", "v": "<script>alert(1)</script>"}]})
        links = [span for span in tree["blocks"][1]["spans"] if span["t"] == "a"]
        self.assertEqual([link["href"] for link in links], ["https://ok.example/a_(b)", "PLAN.md", "C:\\x\\y.sql"])
        self.assertNotIn("javascript", json.dumps(tree).replace('"v": "a"', ""))

    def test_names_with_underscores_stay_names(self) -> None:
        self.assertEqual(mdtree.spans("usp__load__orders and snake_case_name"), [{"t": "text", "v": "usp__load__orders and snake_case_name"}])

    def test_a_very_long_file_is_cut(self) -> None:
        self.assertTrue(mdtree.parse("line\n" * (mdtree.MAX_LINES + 5))["cut"])


class DeskTests(ServeCase):
    def test_the_page_of_a_task_with_its_documents(self) -> None:
        (self.task / "TODO.md").write_text("- [x] a\n- [ ] b\n", encoding="utf-8")
        (self.task / "IMPACT.md").write_text("# Impact\n", encoding="utf-8")
        desk = taskdesk.desk(self.root, "job1", ("approve-plan",))
        self.assertEqual([doc["name"] for doc in desk["docs"]][:3], ["TASK.md", "REQ.md", "PLAN.md"])
        self.assertIn("IMPACT.md", [doc["name"] for doc in desk["docs"]])
        self.assertEqual(desk["todo"], {"done": 1, "total": 2})
        self.assertEqual(desk["waiting_why"], "plan")
        self.assertIn("approve-plan", [item["action"] for item in desk["actions"]])
        self.assertTrue(desk["history"])

    def test_the_server_sends_it_with_a_policy_that_keeps_it_from_talking_elsewhere(self) -> None:
        status, data, headers = self.request("GET", "/task/job1")
        self.assertEqual(status, 200)
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
        self.assertIn('"desk"', data["text"])
        self.assertEqual(self.request("GET", "/task/../../etc/passwd")[0], 404)
        self.assertEqual(self.request("GET", "/task/no_such_task")[0], 404)

    def test_the_page_asks_for_the_task_again(self) -> None:
        status, data, _headers = self.request("POST", "/api/desk", {"task": "job1"})
        self.assertEqual(status, 200)
        self.assertEqual(data["desk"]["name"], "job1")
        self.assertEqual(self.request("POST", "/api/desk", {"task": "nope"})[0], 404)

    def test_the_agent_is_told_the_address_of_the_page_while_the_board_runs(self) -> None:
        context = self.context(self.prompt("go on"))
        self.assertIn(f"http://127.0.0.1:{self.port}/task/job1", context)
        self.stop()
        self.assertNotIn("/task/job1", self.context(self.prompt("go on")))

    def test_every_action_is_on_the_page_by_default(self) -> None:
        self.assertEqual(sorted(boardserve_actions(self.root)), sorted(["pause", "resume", "approve-plan", "approve-promote", "review extend", "review waive", "autorun on", "recover"]))


def boardserve_actions(root):
    from modules.task import boardserve

    return boardserve.settings(root)["actions"]


if __name__ == "__main__":
    unittest.main()
