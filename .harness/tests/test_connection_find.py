"""1.7.38 (C12 D1): the agent finds a connection a little at a time. Layer 0: one line at the start of a chat (kinds and counts). Layer 1: `harness connections find`. Layer 2: the details, when a prompt names a
connection and the first time a command of the agent that ran reached it. Layer 3 (what a held call says) is in test_open_connection."""

from __future__ import annotations

import json
from typing import Any, Dict

from support import HarnessTestCase, payload, post_tool, pre_tool, use_packs

from core import connections, messages

SESSION = "sess-find"
LISTED = {
    "orders-dev": {"type": "sqlserver", "env": "dev", "host": "localhost", "port": "14332", "auth": "sql", "label": "Orders, DEV", "about": "Sales orders and invoices, development", "repos": ["acme_dw"], "domains": ["sales"]},
    "orders-ist": {"type": "sqlserver", "env": "ist", "host": "localhost", "port": "14331", "auth": "sql", "about": "Sales orders and invoices, integration tests", "repos": "acme_dw, acme_etl_jobs", "domains": "sales"},
    "hr-dev": {"type": "sqlserver", "env": "dev", "host": "localhost", "port": "14330", "auth": "sql", "about": "People data, development", "domains": ["hr"]},
    "ado": {"type": "azure-devops", "env": "none", "org": "acme", "project": "demo", "about": "Work items and pipelines of the data platform"},
}


class FindCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        use_packs(self.root, "sqlserver", "ado")
        self.company(LISTED)

    def company(self, listed: Dict[str, Any]) -> None:
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": listed}), encoding="utf-8")

    def start(self, **extra: Any) -> str:
        data = payload("SessionStart", SESSION, **extra)
        data["cwd"] = str(self.root)
        return self.hook(data).get("additionalContext", "")

    def prompt(self, text: str) -> str:
        data = payload("UserPromptSubmit", SESSION, prompt=text)
        data["cwd"] = str(self.root)
        return self.hook(data).get("additionalContext", "")

    def ran(self, command: str, session: str = SESSION) -> Dict[str, Any]:
        """The agent's call and, when it was let through, its result: layer 2 is read after a call that ran."""
        before = pre_tool(session, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        before["cwd"] = str(self.root)
        decided = self.hook(before)
        if decided.get("permissionDecision") == "deny":
            return decided
        after = post_tool(session, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False}, "ok")
        after["cwd"] = str(self.root)
        return self.hook(after)


class FindTests(FindCase):
    def names(self, words: str) -> list:
        return [one["alias"] for one in connections.find(self.root, words)["matches"]]

    def test_a_word_fits_the_name_the_type_the_environment_and_the_sentence(self) -> None:
        self.assertEqual(self.names("hr"), ["hr-dev"])  # the name
        self.assertEqual(self.names("sql"), ["orders-dev", "orders-ist", "hr-dev"])  # the start of the type
        self.assertEqual(self.names("azure"), ["ado"])  # the label of the type
        self.assertEqual(self.names("integration"), ["orders-ist"])  # the sentence `about`
        self.assertEqual(self.names("invoices"), ["orders-dev", "orders-ist"])
        self.assertEqual(self.names("acme_etl_jobs"), ["orders-ist"], "a repository, written as one text with commas, and the name is not cut at the underscore")
        self.assertEqual(self.names("etl"), ["orders-ist"], "a part of the name of a repository")
        self.assertEqual(self.names("acme_dw"), ["orders-dev", "orders-ist"], "a repository, written as a list")
        self.assertEqual(self.names("sales"), ["orders-dev", "orders-ist"], "a domain")
        self.assertEqual(self.names("people"), ["hr-dev"])

    def test_an_environment_is_the_word_itself_and_dev_is_not_devops(self) -> None:
        self.assertEqual(self.names("dev"), ["orders-dev", "hr-dev"], "the type Azure DevOps is no `dev`")
        self.assertEqual(self.names("ist"), ["orders-ist"])
        self.assertEqual(self.names("devops"), ["ado"])

    def test_the_connection_that_fits_the_most_words_comes_first(self) -> None:
        self.assertEqual(self.names("sales orders"), ["orders-dev", "orders-ist"])
        self.assertEqual(self.names("sales orders ist"), ["orders-ist"], "an environment word filters: the DEV copy fits `sales orders` and is left out")
        self.assertEqual(self.names("sales warehouse dev"), ["orders-dev", "hr-dev"], "an unknown word counts for nothing; a name beats a sentence; the IST copy is another environment")
        self.assertEqual(self.names("Orders, DEV!"), ["orders-dev", "hr-dev"], "case and punctuation do not matter")

    def test_nothing_fits_or_no_words(self) -> None:
        found = connections.find(self.root, "payroll")
        self.assertEqual((found["matches"], found["total"], found["all"]), ([], 0, 4))
        self.assertEqual(connections.find(self.root, "   ")["matches"], [])

    def test_only_a_few_lines_are_listed_and_the_rest_is_counted(self) -> None:
        self.company({f"db-{n}": {"type": "sqlserver", "env": "dev", "host": f"h{n}", "auth": "sql", "about": "orders"} for n in range(8)})
        found = connections.find(self.root, "orders")
        self.assertEqual((len(found["matches"]), found["total"]), (connections.FIND_LIMIT, 8))

    def test_the_command_answers_in_a_few_lines_and_asks_when_two_could_be_the_one(self) -> None:
        done = self.cli("connections", "find", "sales", "orders")  # no environment named: the DEV and the IST copy both fit
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.strip().splitlines()
        self.assertTrue(lines[0].startswith("orders-dev  (SQL Server, DEV)  Sales orders and invoices, development"), lines[0])
        self.assertIn(messages.text("connections.find.many", n=2), lines[-1])
        self.assertLessEqual(len(lines), connections.FIND_LIMIT + 2)
        one = self.cli("connections", "find", "sales", "orders", "ist").stdout  # an environment named: only that one (C12 TB-06)
        self.assertTrue(one.splitlines()[0].startswith("orders-ist  (SQL Server, IST)"), one)
        self.assertIn(messages.text("connections.find.one.env", env="IST"), one)
        self.assertNotIn("orders-dev", one)

    def test_one_match_none_and_no_connection_at_all(self) -> None:
        one = self.cli("connections", "find", "people").stdout
        self.assertIn(messages.text("connections.find.one"), one)
        self.assertIn(messages.text("connections.find.none", words="payroll", n=4), self.cli("connections", "find", "payroll").stdout)
        self.company({})
        self.assertIn(messages.text("connections.find.empty"), self.cli("connections", "find", "payroll").stdout)

    def test_find_is_a_read_the_gate_lets_through(self) -> None:
        for command in ("harness connections find sales dev", "python3 .harness/engine/cli.py connections find hr"):
            event = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
            event["cwd"] = str(self.root)
            self.assertEqual(self.hook(event), {}, command)

    def test_a_connection_of_ones_own_can_say_what_it_is_for(self) -> None:
        connections.save(self.root, "mine", {"account": "me", "password": "x"}, own={"type": "sqlserver", "env": "dev", "auth": "sql", "host": "db9", "port": "1433", "about": "my scratch copy of the warehouse"})
        self.assertEqual(connections.listed(self.root)["mine"]["about"], "my scratch copy of the warehouse")
        self.assertEqual(self.names("scratch"), ["mine"])
        self.assertEqual(connections.export(self.root)["connections"]["mine"]["about"], "my scratch copy of the warehouse")
        self.assertIn("about", connections.OWN_FIELDS)


class LayerZeroTests(FindCase):
    def line(self, told: str) -> str:
        return next((line for line in told.splitlines() if "harness connections find" in line), "")

    def test_the_start_of_a_chat_says_kinds_and_counts_and_never_a_name(self) -> None:
        told = self.start()
        self.assertEqual(self.line(told), messages.text("connections.kinds.context", kinds="3 SQL Server, 1 Azure DevOps"))
        for alias in LISTED:
            self.assertNotIn(alias, self.line(told))
        self.assertIn("never guess" if messages.language() == "en" else "绝不要猜", self.line(told))
        self.assertEqual(len(self.line(told).splitlines()), 1)

    def test_no_connection_no_line(self) -> None:
        self.company({})
        self.assertEqual(self.line(self.start()), "")

    def test_a_connection_reached_through_the_prefix_is_named_in_its_own_line(self) -> None:
        (self.root / connections.STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
        (self.root / connections.STATE_FILE).write_text(json.dumps({"direct": ["orders-ist"], "wrap": ["orders-dev"]}), encoding="utf-8")
        told = self.start()
        self.assertIn("harness as orders-dev --", told)
        self.assertEqual(self.line(told), messages.text("connections.kinds.context", kinds="2 SQL Server"), "only the connections this window was opened with are counted")
        self.assertNotIn("hr-dev", told)


class LayerTwoTests(FindCase):
    SQL = 'sqlcmd -S localhost,14332 -C -Q "SELECT 1"'

    def test_the_first_command_that_ran_gets_the_details_once_and_the_second_gets_none(self) -> None:
        first = self.ran(self.SQL).get("additionalContext", "")
        self.assertIn("orders-dev (DEV): SQL Server [host=localhost, port=14332", first)
        self.assertIn(messages.text("connections.named.about", about="Sales orders and invoices, development").strip(), first)
        self.assertIn("sqlserver-jobs", first)
        self.assertIn("`sqlcmd`", first)
        self.assertEqual(self.ran(self.SQL), {}, "once per connection per session")
        other = self.ran('sqlcmd -S localhost,14331 -C -Q "SELECT 1"').get("additionalContext", "")
        self.assertIn("orders-ist (IST)", other)
        self.assertNotIn("orders-dev", other.replace("Connection", ""))

    def test_another_chat_gets_them_again(self) -> None:
        self.ran(self.SQL)
        self.assertIn("orders-dev", self.ran(self.SQL, session="sess-other").get("additionalContext", ""))

    def test_a_line_that_reaches_two_connections_gets_both(self) -> None:
        both = self.ran(self.SQL + ' && sqlcmd -S localhost,14331 -C -Q "SELECT 1"').get("additionalContext", "")
        self.assertIn("orders-dev", both)
        self.assertIn("orders-ist", both)

    def test_a_connection_the_prompt_named_has_had_its_details(self) -> None:
        said = self.prompt("look at orders-dev please")
        self.assertIn("- orders-dev (DEV): SQL Server", said)
        self.assertIn(messages.text("connections.named.about", about="Sales orders and invoices, development").strip(), said)
        self.assertEqual(self.ran(self.SQL), {}, "told at the prompt: not again at the first command")

    def test_a_call_that_was_held_did_not_run_and_the_details_wait_for_the_next(self) -> None:
        held = self.ran('sqlcmd -S localhost,14332 -C -Q "UPDATE t SET a = 1"')
        self.assertEqual(held.get("permissionDecision"), "deny")
        self.assertNotIn("additionalContext", held)
        self.assertIn("orders-dev", self.ran(self.SQL).get("additionalContext", ""))

    def test_a_command_that_reaches_no_connection_gets_nothing(self) -> None:
        self.assertEqual(self.ran("ls -la"), {})
        self.assertEqual(self.ran("harness connections find sales"), {})

    def test_the_details_say_when_the_person_opened_the_connection_for_the_task(self) -> None:
        from modules.task import tasklife
        from taskcase import NAME

        self.start()  # the chat exists
        self.run_cli("task", "new", NAME, "--kind", "dev", "--session-id", SESSION)
        tasklife.set_allow(self.root, NAME, "orders-dev", True, interactive=True)
        self.assertIn(messages.text("connections.named.opened").strip(), self.prompt("use orders-dev"))

    def run_cli(self, *arguments: str) -> Any:
        done = self.cli(*arguments)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        return done


class SkillsTests(HarnessTestCase):
    def test_the_skills_of_the_packs_start_with_the_way_to_find_the_connection(self) -> None:
        from support import REPO

        for pack, skills in (("ado", ("ado-workitem", "ado-pipeline-triage", "ado-release")), ("sqlserver", ("sqlserver-jobs",))):
            for name in skills:
                text = (REPO / ".harness" / "toolpacks" / pack / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
                body = text.split("---", 2)[2]
                first = next(line for line in body.splitlines() if line.strip() and not line.startswith("#"))
                self.assertIn("harness connections find", first, name)
                self.assertIn("ask", first, name)
