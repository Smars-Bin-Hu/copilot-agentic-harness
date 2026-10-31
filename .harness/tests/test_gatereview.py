"""Gate blocks in the report of a task (1.6, B76): the list, the verdicts only a person sets, the samples of wrong blocks, and the page served or saved."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from taskcase import SESSION, TASK
from test_boardserve import ServeCase

from core import logs, messages, redact
from core.paths import utc_now
from modules.task import gatereview, task as task_ops, taskboard, taskhtml

KEY = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3"  # looks like a token
PASSWORD = "Hunter2Hunter2"


def deny(command: str = "", paths: List[str] = (), kind: str = "", tool: str = "run_in_terminal", reason: str = "it deletes a resource group", session: str = SESSION, at: str = "") -> None:
    """One deny line as the hook writes it, in the log of a session."""
    record: Dict[str, Any] = {"surface": "vscode", "session_id": session, "event": "PreToolUse", "tool_name": tool, "decision": "deny", "judge": "rule", "by": ["gate"], "reason": reason,
                              "target": {"paths": list(paths), "command": command}}
    if kind:
        record["kind"] = kind
    record["at"] = at or utc_now()
    path = logs.session_log_path(Path(deny.root), "vscode", session)  # type: ignore[attr-defined]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def page_data(text: str) -> Dict[str, Any]:
    return json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', text, re.S).group(1))  # type: ignore[union-attr]


class GateCase(ServeCase):
    def setUp(self) -> None:
        super().setUp()
        deny.root = self.root  # type: ignore[attr-defined]
        deny(command="az group delete -n rg1 --yes", at="2999-01-01T13:12:00+00:00")
        deny(command=f"curl -H 'Authorization: Bearer {KEY}' https://u:{PASSWORD}@x.example/a --password {PASSWORD}", reason=f"token={KEY} is sent", at="2999-01-01T12:40:00+00:00")
        deny(paths=["knowledge-base/jobs/daily.md"], tool="Edit", kind="task-scope", at="2999-01-01T11:05:00+00:00")
        # not blocks: a call that went through, an ask, and a deny of another session
        logs.log_call(self.root, {"surface": "vscode", "session_id": SESSION, "event": "PreToolUse", "decision": "allow"})
        logs.log_call(self.root, {"surface": "vscode", "session_id": SESSION, "event": "PreToolUse", "decision": "ask", "target": {"paths": [], "command": "git push"}})
        deny(command="rm -rf /", session="other-session")

    def blocks(self) -> List[Dict[str, Any]]:
        return gatereview.denies(self.root, self.data())

    def post(self, path: str, body: Dict[str, Any], cookie: str = "") -> Any:
        return self.request("POST", path, {"task": "job1", **body}, cookie=cookie)


class ListTests(GateCase):
    def test_each_deny_of_the_task_is_listed_oldest_first_with_its_rule(self) -> None:
        found = self.blocks()
        self.assertEqual([(item["tool"], item["rule"]) for item in found], [("Edit", "task-scope"), ("run_in_terminal", "gate.run_in_terminal"), ("run_in_terminal", "gate.run_in_terminal")])
        self.assertEqual(found[0]["paths"], ["knowledge-base/jobs/daily.md"])
        self.assertEqual(len({item["id"] for item in found}), 3)
        self.assertEqual(found, self.blocks())  # the ids do not move

    def test_the_section_counts_and_shows_the_newest(self) -> None:
        section = gatereview.section(self.root, self.data())
        self.assertEqual((section["count"], section["shown"], section["wrong_open"]), (3, 3, 0))
        self.assertEqual(section["counts"], {"right": 0, "wrong": 0, "unsure": 0})

    def test_a_task_with_no_blocks_has_an_empty_section_and_a_page_that_says_so(self) -> None:
        logs.session_log_path(self.root, "vscode", SESSION).unlink()
        self.assertEqual(gatereview.section(self.root, self.data())["count"], 0)
        info, now = taskboard.insight(self.root, TASK)
        page = taskhtml.task_page(taskboard.with_gate(self.root, TASK, info), 0, now)
        self.assertEqual(page_data(page)["info"]["gate"]["count"], 0)
        self.assertIn("report.gate.none", page_data(page)["text"])
        self.assertEqual(gatereview.export(self.root, TASK)["files"], [])


class VerdictTests(GateCase):
    def test_a_person_sets_a_verdict_and_takes_it_back(self) -> None:
        cookie = self.pair()
        first = self.blocks()[1]["id"]
        status, data, _ = self.post("/api/verdict", {"id": first, "verdict": "wrong"}, cookie)
        self.assertEqual(status, 200, data)
        self.assertEqual(self.data()["gate_verdicts"][first]["v"], "wrong")
        self.assertEqual(data["result"]["gate"]["counts"]["wrong"], 1)
        self.assertIn("gate-verdict", [event["what"] for event in self.data()["events"]])
        self.assertEqual(self.post("/api/verdict", {"id": first, "verdict": ""}, cookie)[0], 200)
        self.assertNotIn("gate_verdicts", self.data())

    def test_a_verdict_needs_the_paired_browser_the_header_and_this_origin(self) -> None:
        first = self.blocks()[0]["id"]
        self.assertEqual(self.post("/api/verdict", {"id": first, "verdict": "right"})[0], 403)  # not paired
        cookie = self.pair()
        self.assertEqual(self.request("POST", "/api/verdict", {"task": "job1", "id": first, "verdict": "right"}, cookie=cookie, header=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/verdict", {"task": "job1", "id": first, "verdict": "right"}, cookie=cookie, origin="https://evil.example")[0], 403)
        self.assertEqual(self.request("GET", "/api/verdict", cookie=cookie)[0], 404)
        self.assertEqual(self.post("/api/export", {})[0], 403)
        self.assertNotIn("gate_verdicts", self.data())

    def test_only_a_block_of_the_log_gets_a_verdict_and_only_a_known_verdict(self) -> None:
        cookie = self.pair()
        first = self.blocks()[0]["id"]
        self.assertEqual(self.post("/api/verdict", {"id": "nothing", "verdict": "wrong"}, cookie)[0], 409)
        self.assertEqual(self.post("/api/verdict", {"id": first, "verdict": "great"}, cookie)[0], 409)
        self.assertEqual(self.request("POST", "/api/verdict", {"id": first, "verdict": "wrong"}, cookie=cookie)[0], 409)  # no task named: it does not pick the open one
        self.assertNotIn("gate_verdicts", self.data())

    def test_an_agent_cannot_write_the_state_and_no_command_sets_a_verdict(self) -> None:
        first = self.blocks()[0]["id"]
        self.assertEqual(self.decision(self.edit(f"{TASK}/.task/task.json")), "deny")  # the file is the CLI's
        for arguments in (("task", "verdict", first, "wrong"), ("task", "gate", "verdict", first, "wrong")):
            self.assertNotEqual(self.cli(*arguments).returncode, 0)
        self.assertNotIn("gate_verdicts", self.data())

    def test_a_verdict_is_kept_for_a_closed_task_and_shown_in_the_file_of_its_report(self) -> None:
        cookie = self.pair()
        first = self.blocks()[0]["id"]
        self.cli_json("task", "close")
        self.assertEqual(self.post("/api/verdict", {"id": first, "verdict": "right"}, cookie)[0], 200)
        shown = page_data((self.root / ".workspace/reports/tasks/job1/report.html").read_text(encoding="utf-8"))["info"]["gate"]
        self.assertEqual([item["verdict"] for item in shown["items"] if item["id"] == first], ["right"])


class ExportTests(GateCase):
    def judge_wrong(self) -> str:
        cookie = self.pair()
        target = self.blocks()[1]
        self.assertEqual(self.post("/api/verdict", {"id": target["id"], "verdict": "wrong"}, cookie)[0], 200)
        self.assertEqual(self.post("/api/verdict", {"id": self.blocks()[0]["id"], "verdict": "right"}, cookie)[0], 200)
        return cookie

    def test_only_the_wrong_blocks_become_samples_in_the_folder_of_their_rule(self) -> None:
        cookie = self.judge_wrong()
        status, data, _ = self.post("/api/export", {}, cookie)
        self.assertEqual(status, 200, data)
        target = self.blocks()[1]
        expected = f".harness/eval/fixtures/gate/{target['rule']}/{target['id']}.json"
        self.assertEqual(data["result"]["files"], [expected])
        sample = json.loads((self.root / expected).read_text(encoding="utf-8"))
        self.assertEqual(sorted(sample), ["command", "expect", "harness", "id", "kind", "paths", "reason", "rule", "schema", "tool"])
        self.assertEqual((sample["kind"], sample["expect"], sample["schema"], sample["rule"], sample["tool"]), ("gate-false-block", "allow", 1, target["rule"], "run_in_terminal"))
        self.assertEqual(len(list((self.root / ".harness/eval/fixtures/gate").rglob("*.json"))), 1)
        self.assertEqual(data["result"]["gate"]["wrong_open"], 0)
        self.assertTrue(self.data()["gate_verdicts"][target["id"]]["exported_at"])

    def test_no_secret_reaches_a_sample(self) -> None:
        self.post("/api/export", {}, self.judge_wrong())
        text = "\n".join(path.read_text(encoding="utf-8") for path in (self.root / ".harness/eval/fixtures/gate").rglob("*.json"))
        self.assertTrue(text)
        for secret in (KEY, PASSWORD):
            self.assertNotIn(secret, text)
        self.assertNotIn(self.root.as_posix(), text)
        self.assertNotIn(SESSION, text)  # nor the session or the task
        self.assertNotIn("job1", text)
        self.assertIn("az group", redact.text("az group delete -n rg1"))  # what a rule needs stays

    def test_redact_masks_short_password_options_of_known_tools_only(self) -> None:
        for command, wanted in (
            ("sqlcmd -S srv -U sa -P secret -Q 'select 1'", "sqlcmd -S srv -U sa -P *** -Q 'select 1'"),
            ("sqlcmd -S srv -Psecret", "sqlcmd -S srv -P ***"),
            ("C:\\bin\\sqlcmd.exe -P pw", "C:\\bin\\sqlcmd.exe -P ***"),
            ("bcp t out f -P pw -U u", "bcp t out f -P *** -U u"),
            ("mysql -uroot -pSecret db", "mysql -uroot -p*** db"),
            ("mysql -p'a b' db", "mysql -p*** db"),
            ("mongosh -u u -p pw", "mongosh -u u -p ***"),
            ("redis-cli -a pw ping", "redis-cli -a *** ping"),
            ("sqlplus scott/tiger@db", "sqlplus scott/***@db"),
            ("ssh -p 22 h && mysql -pS3 x", "ssh -p 22 h && mysql -p*** x"),
            ("tool -Password hunter2", "tool -Password ***"),
            ("Connect -Password:abc", "Connect -Password:***"),
            ("mysql --password=abc", "mysql --password=***"),
        ):
            with self.subTest(command=command):
                self.assertEqual(redact.text(command), wanted)
        for command in ("grep -P 'pat' f", "mkdir -p dir", "ssh -p 22 host", "mysql -P 3306 -h x", "mysql -p db", "sqlcmd -p x", "echo sqlcmd; ls -P a", "echo mysql | grep -pfoo", "psql -p 5432 -U u db"):
            with self.subTest(command=command):
                self.assertEqual(redact.text(command), command)

    def test_redact_takes_out_values_and_keeps_the_shape(self) -> None:
        self.assertEqual(redact.text("export API_KEY=abc12345 && run"), "export API_KEY=*** && run")
        self.assertEqual(redact.text("curl https://u:pw@h/x"), "curl https://u:***@h/x")
        self.assertEqual(redact.text("tool --password 'a b' x"), "tool --password *** x")
        self.assertEqual(redact.text("/Users/smars/work/a.sql"), "~/work/a.sql")
        self.assertEqual(redact.text("git config user.name Bob"), "git config user.name Bob")

    def test_a_second_export_writes_the_same_file_and_a_taken_back_verdict_exports_nothing(self) -> None:
        cookie = self.judge_wrong()
        first = self.post("/api/export", {}, cookie)[1]["result"]["files"]
        self.assertEqual(self.post("/api/export", {}, cookie)[1]["result"]["files"], first)
        self.assertEqual(len(list((self.root / ".harness/eval/fixtures/gate").rglob("*.json"))), 1)
        self.post("/api/verdict", {"id": self.blocks()[1]["id"], "verdict": "unsure"}, cookie)
        self.assertEqual(self.post("/api/export", {}, cookie)[1]["result"]["files"], [])

    def test_the_sample_folder_is_not_a_guardrail_and_not_ignored(self) -> None:
        from core import guardrails  # noqa: F401 - imported to fail loudly if the module moves

        self.assertEqual(self.decision(self.edit(".harness/eval/fixtures/gate/x/y.json", session="no-task-session")), "")  # a session with no task: no rule guards the folder
        ignore = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("fixtures", ignore)


class PageTests(GateCase):
    def test_the_served_report_has_buttons_and_the_file_on_disk_has_none(self) -> None:
        status, data, headers = self.request("GET", "/tasks/job1/report.html")
        self.assertEqual(status, 200)
        served = page_data(data["text"])
        self.assertIn("steer", served["serve"]["actions"])
        self.assertIn("/api/verdict", data["text"])  # serve.js and task.js are in
        self.assertEqual(served["info"]["gate"]["count"], 3)
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
        self.cli_json("task", "report")
        disk = (self.root / ".workspace/reports/tasks/job1/report.html").read_text(encoding="utf-8")
        self.assertNotIn('"serve"', disk)
        self.assertNotIn("X-Harness-Board", disk)  # no call to a server in a file on disk
        self.assertEqual(page_data(disk)["info"]["gate"]["count"], 3)
        self.assertNotIn(KEY, disk)

    def test_the_saved_copy_is_one_file_with_the_verdicts_and_no_buttons_or_calls(self) -> None:
        cookie = self.pair()
        self.post("/api/verdict", {"id": self.blocks()[0]["id"], "verdict": "right"}, cookie)
        status, data, headers = self.request("GET", "/report-save/job1")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("job1-report-", headers["Content-Disposition"])
        text = data["text"]
        saved = page_data(text)
        self.assertTrue(saved["snapshot"])
        self.assertNotIn("serve", saved)
        self.assertNotIn("X-Harness-Board", text)
        self.assertNotIn("connect-src", text)
        self.assertIn("default-src 'none'", text)
        for banned in ("<script src", "<link ", "<img", "@import"):
            self.assertNotIn(banned, text)
        for secret in (KEY, PASSWORD):  # the commands in the page are the ones of the log, taken through redact
            self.assertNotIn(secret, text)
        self.assertEqual([item["verdict"] for item in saved["info"]["gate"]["items"] if item["verdict"]], ["right"])
        self.assertEqual(self.request("GET", "/report-save/nothing")[0], 404)
        self.assertEqual(self.request("GET", "/report-save/job1", host="evil.example:80")[0], 403)

    def test_the_served_link_to_save_is_in_the_script_of_the_page_and_the_texts_exist_in_both_languages(self) -> None:
        text = self.request("GET", "/tasks/job1/report.html")[1]["text"]
        self.assertIn("/report-save/", text)
        en, zh = (json.loads((Path(__file__).resolve().parents[1] / "engine" / "core" / f"messages.{name}.json").read_text(encoding="utf-8")) for name in ("en", "zh"))
        for key in [key for key in en if key.startswith(("report.gate", "report.save", "report.kpi.gate", "gate.refused", "event.gate"))]:
            self.assertIn(key, zh)
        self.assertIn(messages.text("report.kpi.gate"), json.dumps(page_data(text)["text"], ensure_ascii=False))
