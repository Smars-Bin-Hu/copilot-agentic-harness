"""The task page (M16): markdown read into a tree that the page draws without markup, and /task/<name> on the board server."""

from __future__ import annotations

import io
import json
import unittest

import support  # noqa: F401  (puts the engine on sys.path)
from support import confirm_requirement
from test_boardserve import ServeCase

from taskcase import TASK

from core import messages, tasks
from modules.task.common import CommandError
from modules.task import mdtree, task as task_ops, taskdesk


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

    def test_a_file_from_windows_keeps_its_first_heading(self) -> None:
        """Windows PowerShell and Notepad write a BOM and CRLF; the BOM used to turn `# TODO` into a paragraph."""
        for text in ("# TODO\n\n- [ ] a\n", "\ufeff# TODO\n\n- [ ] a\n", "# TODO\r\n\r\n- [ ] a\r\n", "\ufeff# TODO\r\n\r\n- [ ] a\r\n"):
            self.assertEqual([block["t"] for block in mdtree.parse(text)["blocks"]], ["h", "ul"], repr(text))

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
        self.assertEqual(desk["state"], "waiting")
        self.assertIn("held", desk)
        self.assertIn("approve-plan", [item["action"] for item in desk["actions"]])
        self.assertTrue(desk["history"])

    def test_the_review_tab_has_every_round_with_its_answer_newest_first(self) -> None:
        from modules.task import taskreview, tasksnap

        self.assertEqual(taskdesk.desk(self.root, "job1")["review"]["rounds"], [])
        digest = tasksnap.results_digest(self.root, TASK)
        folder = self.task / "REVIEW"
        for number, text in ((1, "\ufeff# VERDICT: FAIL\n\n- `a.sql:3` wrong join\n"), (2, "VERDICT: PASS\n")):
            (folder / f"round-{number:03d}").mkdir(parents=True)
            (folder / f"round-{number:03d}" / "verdict.md").write_text(text, encoding="utf-8")
        (folder / "round-002" / "package.md").write_text("# Package\n", encoding="utf-8")
        with task_ops.locked(self.root, TASK) as data:
            review = taskreview.state_of(data)
            review["n"] = 1
            review["rounds"] += [
                {"number": 1, "task_round": data["round"], "ordinal": 1, "verdict": "FAIL", "digest": "an-older-version", "started_at": "2026-10-20T01:00:00+00:00"},
                {"number": 2, "task_round": data["round"], "ordinal": 2, "verdict": "PASS", "digest": digest, "started_at": "2026-10-20T02:00:00+00:00"},
                {"number": 3, "task_round": data["round"], "ordinal": 3, "verdict": "", "digest": digest, "started_at": "2026-10-20T03:00:00+00:00"},
            ]
        found = taskdesk.desk(self.root, "job1")["review"]
        self.assertEqual([item["number"] for item in found["rounds"]], [3, 2, 1])
        self.assertEqual((found["n"], found["passes"], found["pending"]), (1, 1, 3))
        by = {item["number"]: item for item in found["rounds"]}
        self.assertEqual((by[2]["current"], by[1]["current"]), (True, False))
        self.assertEqual(by[1]["answer"]["blocks"][0]["t"], "h", "the first heading is a heading, a BOM or not")
        self.assertIsNone(by[3]["answer"])
        self.assertEqual(by[2]["package"]["blocks"][0]["t"], "h")
        self.assertIsNone(by[1]["package"])

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

    def test_the_board_asks_for_its_rows_and_they_hold_the_closed_tasks_too(self) -> None:
        self.prompt("hello", session="s-done")
        self.new(name="done_one", kind="qa", session="s-done")
        task_ops.close(self.root, "done_one")
        status, data, _headers = self.request("POST", "/api/board", {})
        self.assertEqual(status, 200)
        rows = {row["name"]: row for row in data["rows"]}
        self.assertEqual((rows["job1"]["status"], rows["done_one"]["status"], data["hidden"]), ("open", "closed", 0))
        self.assertIsNotNone(rows["done_one"]["brief"])
        self.assertEqual(self.request("POST", "/api/board", {}, header=False)[0], 403)  # as every other request: the header is needed

    def test_a_paired_browser_archives_closed_tasks_from_the_page_and_nothing_else_does(self) -> None:
        import tempfile
        from pathlib import Path

        self.prompt("hello", session="s-arch")
        self.new(name="to_shelf", kind="qa", session="s-arch")
        task_ops.close(self.root, "to_shelf")
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        shelf = Path(holder.name) / "shelf"
        asked = {"tasks": ["to_shelf"], "to": str(shelf), "step": "preview"}
        self.assertEqual(self.request("POST", "/api/archive", asked)[0], 403)  # not paired
        cookie = self.pair()
        status, data, _headers = self.request("POST", "/api/archive", asked, cookie=cookie)
        self.assertEqual((status, [item["name"] for item in data["result"]["would_move"]]), (200, ["to_shelf"]))
        self.assertFalse(shelf.exists())  # a look moves nothing
        self.assertEqual(self.request("POST", "/api/archive", {"tasks": ["job1"], "to": str(shelf), "step": "act"}, cookie=cookie)[0], 409)  # an open task stays
        self.assertEqual(self.request("POST", "/api/archive", {"tasks": [], "to": str(shelf)}, cookie=cookie)[0], 409)
        status, data, _headers = self.request("POST", "/api/archive", {**asked, "step": "act", "remember": True}, cookie=cookie)
        self.assertEqual((status, data["result"]["archived"]), (200, ["to_shelf"]))
        self.assertTrue((shelf / "to_shelf" / ".task").is_dir())
        rows = {row["name"] for row in self.request("POST", "/api/board", {})[1]["rows"]}
        self.assertNotIn("to_shelf", rows)
        self.assertEqual(self.request("POST", "/api/board", {})[1]["archive_to"], str(shelf.resolve()))

    def test_the_person_confirms_the_requirement_on_the_page_and_the_harness_fills_the_line(self) -> None:
        import hashlib

        from modules.task import taskreview

        names = lambda: [item["action"] for item in taskdesk.desk(self.root, "job1", ("confirm-req", "pause"))["actions"]]
        req = self.task / "REQ.md"
        self.assertEqual(task_ops.req_state(self.root, TASK), "unwritten")
        self.assertNotIn("confirm-req", names())  # the template is still empty: nothing to confirm
        req.write_text(req.read_text(encoding="utf-8").replace("<One or two paragraphs. What the user meant, with nothing of your own added>", "Stop the nightly load from failing.").replace("<一两段。用户的原意，不加你自己的设想>", "别让夜间加载失败。"), encoding="utf-8")
        self.assertEqual(task_ops.req_state(self.root, TASK), "open")
        self.assertEqual(names()[0], "confirm-req")
        body = {"action": "confirm-req", "task": TASK}
        self.assertEqual(self.request("POST", "/api/act", {**body, "step": "preview"})[0], 403)  # not paired
        cookie = self.pair()
        status, data, _ = self.request("POST", "/api/act", {**body, "step": "preview"}, cookie=cookie)
        self.assertEqual(status, 200, data)
        code = hashlib.sha256(req.read_bytes()).hexdigest()[:8]
        self.assertIn(code, data["result"]["ask"])
        self.assertEqual(task_ops.req_state(self.root, TASK), "open")  # a look confirms nothing
        self.assertEqual(self.request("POST", "/api/act", {**body, "code": "00000000"}, cookie=cookie)[0], 409)
        self.assertEqual(self.request("POST", "/api/act", {**body, "code": code}, cookie=cookie)[0], 200)
        self.assertTrue(taskreview.req_confirmed(self.root, TASK))
        self.assertRegex(req.read_text(encoding="utf-8"), r"(confirmed|已确认) \d{4}-\d{2}-\d{2}")
        self.assertNotIn("confirm-req", names())
        self.assertIn("confirm-req", [event["what"] for event in self.data()["events"]])

    def test_a_requirement_changed_while_the_person_confirms_is_not_confirmed(self) -> None:
        req = self.task / "REQ.md"
        req.write_text(req.read_text(encoding="utf-8").replace("<One or two paragraphs. What the user meant, with nothing of your own added>", "A.").replace("<一两段。用户的原意，不加你自己的设想>", "甲。"), encoding="utf-8")

        def reader(_asked: str) -> str:  # the person types the right code of the version they read; then the agent edits the file
            import hashlib

            code = hashlib.sha256(req.read_bytes()).hexdigest()[:8]
            req.write_text(req.read_text(encoding="utf-8") + "\nMore.\n", encoding="utf-8")
            return code

        with self.assertRaises(CommandError) as raised:
            task_ops.confirm_req(self.root, TASK, reader=reader, interactive=True, out=io.StringIO())
        self.assertEqual(str(raised.exception), messages.text("req.changed"))
        self.assertEqual(task_ops.req_state(self.root, TASK), "open")

    def test_a_paired_browser_closes_a_task_from_the_page_and_the_agent_is_told_to_ask_first(self) -> None:
        self.assertEqual(self.request("POST", "/api/close", {"task": "job1"})[0], 403)  # not paired
        self.assertIn("close", [item["action"] for item in taskdesk.desk(self.root, "job1", ("close", "pause"))["actions"]])
        cookie = self.pair()
        self.assertEqual(self.request("POST", "/api/close", {"task": "nope"}, cookie=cookie)[0], 409)
        status, data, _headers = self.request("POST", "/api/close", {"task": "job1"}, cookie=cookie)
        self.assertEqual((status, data["result"]["status"]), (200, "closed"))
        self.assertEqual(self.data()["status"], "closed")
        self.assertEqual(self.data()["events"][-1]["detail"], messages.text("serve.close.reason"))
        self.assertNotIn("close", [item["action"] for item in taskdesk.desk(self.root, "job1", ("close",))["actions"]])  # a closed task offers none
        self.assertTrue(any(row["name"] == "job1" and row["status"] == "closed" for row in self.request("POST", "/api/board", {})[1]["rows"]))

    def test_the_step_of_a_task_without_a_plan_says_to_ask_the_user_before_closing(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["plan"] = {}
        (self.task / "PLAN.md").unlink()
        said = task_ops.next_step(self.root, TASK, self.data())
        self.assertIn("task close", said)
        self.assertTrue("whether to close" in said or "要不要关闭" in said)

    def test_the_agent_is_told_the_address_of_the_page_while_the_board_runs(self) -> None:
        context = self.context(self.prompt("go on"))
        self.assertIn(f"http://127.0.0.1:{self.port}/task/job1", context)
        self.stop()
        self.assertNotIn("/task/job1", self.context(self.prompt("go on")))

    def test_the_next_step_of_a_task_that_waits_for_its_plan_names_the_page(self) -> None:
        self.assertIn(f"http://127.0.0.1:{self.port}/task/job1", self.run_cli("task", "status", "--task", TASK)["next"])
        self.stop()
        self.assertNotIn("/task/job1", self.run_cli("task", "status", "--task", TASK)["next"])

    def test_every_action_is_on_the_page_by_default(self) -> None:
        self.assertEqual(sorted(boardserve_actions(self.root)), sorted(["pause", "resume", "approve-plan", "approve-promote", "review extend", "review waive", "autorun on", "recover", "archive", "close", "confirm-req"]))


    def test_a_page_action_is_one_line_with_a_tag_and_the_session_note_follows_the_language(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            task_ops.note(data, "pause")
            task_ops.note(data, "board", "pause")
            task_ops.note(data, "start", "会话 abc-123")
        found = taskdesk.desk(self.root, "job1", ())["history"]
        self.assertEqual([item["what"] for item in found[:2]], ["start", "pause"])
        self.assertEqual(found[1]["via"], "board")
        self.assertEqual(found[0]["detail"], "会话 abc-123" if messages.language() == "zh" else "session abc-123")
        self.assertNotIn("board", [item["what"] for item in found])

    def test_a_promote_record_that_is_not_complete_is_refused_in_words(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["promote"] = {"state": "partial"}
        with self.assertRaises(CommandError) as raised:
            task_ops.recover(self.root, TASK, reader=lambda _prompt: "x", interactive=True, out=io.StringIO())
        self.assertIn("job1", str(raised.exception))
        self.assertNotIn("plan_sha256", str(raised.exception))

    def test_a_decision_on_the_checks_and_a_recovery_leave_the_same_mark(self) -> None:
        from modules.task import taskreview, tasksnap

        code = (tasksnap.results_digest(self.root, TASK) or "0" * 64)[:8]
        taskreview.extend(self.root, TASK, 2, reader=lambda _prompt: code, interactive=True, out=io.StringIO())
        self.assertEqual(self.data()["waiting"]["why"], "go-review")  # the plan of this case is not approved: it would be named first
        self.prompt("go on")
        with task_ops.locked(self.root, TASK) as data:
            data["promote"] = {"state": "partial", "plan_sha256": "ab" * 32, "branch": "feature/job1", "recovery": [], "recovery_steps": []}
        task_ops.recover(self.root, TASK, reader=lambda _prompt: "abababab", interactive=True, out=io.StringIO())
        self.assertEqual(self.data()["waiting"]["why"], "go-recover")

    def test_an_approval_leaves_a_mark_until_the_next_prompt_and_the_page_says_what_to_tell_the_agent(self) -> None:
        confirm_requirement(self.root, TASK)
        digest = tasks.plan_digest(self.root, TASK)
        task_ops.approve_plan(self.root, TASK, reader=lambda _prompt: digest[:8], interactive=True, out=io.StringIO())
        desk = taskdesk.desk(self.root, "job1", ())
        self.assertEqual((desk["waiting_why"], [item["action"] for item in desk["actions"]]), ("go-plan", ["pause"]))  # no button is the point: the word is to the agent
        self.assertEqual(self.data()["waiting"]["why"], "go-plan")
        self.prompt("go on")  # the person told the agent: the mark goes
        self.assertIsNone(self.data()["waiting"])
        self.assertEqual(taskdesk.desk(self.root, "job1", ())["waiting_why"], "")


def boardserve_actions(root):
    from modules.task import boardserve

    return boardserve.settings(root)["actions"]


if __name__ == "__main__":
    unittest.main()
