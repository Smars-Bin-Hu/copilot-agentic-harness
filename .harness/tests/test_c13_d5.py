"""1.7.38, wording and board changes of C13 D5: one test class for each change."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import support  # noqa: F401 - the engine on sys.path
from support import HarnessTestCase, pre_tool, use_packs
from taskcase import NAME, SESSION, TASK, TaskCase
from test_c12_fb import SYSTEMS

from test_connection_find import FindCase
from test_connections import KIND, ConnectionsCase

from core import approval, connections, messages, systems
from modules.gate import rules
from modules.task import boardserve, cmdview, taskboard, taskdesk

ENGINE = Path(__file__).resolve().parents[1] / "engine"
WEB = ENGINE / "modules" / "task" / "web"


class VerbInChineseOnlyTests(HarnessTestCase):
    """The zh screen names the kind of a call in Chinese only (`写`, not `写（write）`); the English word stays in hovers and logs."""

    def test_the_word_of_a_call_is_chinese_only_in_zh_and_the_protocol_word_in_en(self) -> None:
        self.assertEqual([systems.verb_word(verb) for verb in ("read", "write", "exec", "destroy")], ["读", "写", "执行", "销毁"])
        self.assertEqual(rules.word("write"), "写")
        self.assertEqual(systems.verb_word("something-else"), "something-else")  # a word the harness does not know stays
        try:
            messages._LANGUAGE = "en"
            self.assertEqual([systems.verb_word(verb) for verb in ("read", "write", "exec", "destroy")], ["read", "write", "exec", "destroy"])
        finally:
            messages.reset()

    def test_no_zh_text_to_the_agent_has_the_protocol_word_in_brackets(self) -> None:
        class Action:
            system, env, verb, file = "finance", "IST", "write", "x.sql"

        for text in (rules.external_denied(Action, "sqlcmd -Q x"), rules.external_task(Action, "sqlcmd -Q x"), rules.external_human(Action, "sqlcmd -Q x")):
            self.assertIn("「写」", text)
            self.assertNotIn("write", text)

    def test_the_card_hover_has_the_protocol_word(self) -> None:
        source = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn("item.named === false ? null : item.verb", source)


class OwnConnectionFormTests(ConnectionsCase):
    """The form of a connection of one's own: no kind is chosen for the person, and a type that says it has no environment hides the Environment field."""

    def test_a_type_may_say_it_has_no_environment_and_nothing_else_about_it(self) -> None:
        self.assertEqual(connections.type_problems(dict(KIND, env="none")), [])
        self.assertTrue(any("env" in problem for problem in connections.type_problems(dict(KIND, env="dev"))))

    def test_the_board_hands_the_page_the_environment_word_of_each_type(self) -> None:
        from support import put_type

        put_type(self.root, dict(KIND, type="tracker2", label="Tracker", env="none"))
        kinds = boardserve.servers_view(self.root, False)["types"]
        self.assertEqual((kinds["fakedb"]["env"], kinds["tracker2"]["env"]), ("", "none"))

    def test_the_tickets_packs_of_the_harness_say_they_have_no_environment(self) -> None:
        import json

        for pack, name in (("ado", "azure-devops"), ("demotracker", "demotracker")):
            kind = json.loads((ENGINE.parent / "toolpacks" / pack / "types" / f"{name}.json").read_text(encoding="utf-8"))
            self.assertEqual((kind["env"], connections.type_problems(kind)), ("none", []))

    def test_the_form_has_no_kind_chosen_and_hides_the_environment_for_a_type_without_one(self) -> None:
        source = (WEB / "servers.js").read_text(encoding="utf-8")
        self.assertIn('h("option", {value: ""}, t("connections.own.env.pick")), names.map(', source)  # a first, empty kind
        self.assertIn('envField.hidden = noEnv', source)
        self.assertIn('spec.env === "none"', source)
        self.assertIn(".sv-field[hidden]{display:none}", (WEB / "setup.css").read_text(encoding="utf-8"))


class AllConnectionsTests(FindCase):
    """C12 FB-3: every connection counts and is found; the ones VS Code was not opened with are marked and run through `harness as`."""

    OPENED = {"direct": ["orders-dev"], "wrap": []}

    def opened(self) -> None:
        import json

        path = self.root / connections.STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.OPENED), encoding="utf-8")

    def test_the_calls_of_the_connections_the_window_was_not_opened_with_go_through_harness_as(self) -> None:
        self.opened()
        window = {one["alias"]: one for one in connections.calls(self.root)}
        every = {one["alias"]: one for one in connections.calls(self.root, every=True)}
        self.assertEqual(sorted(window), ["orders-dev"])
        self.assertEqual(sorted(every), ["ado", "hr-dev", "orders-dev", "orders-ist"])
        self.assertTrue(every["hr-dev"]["call"].startswith("harness as hr-dev -- "))
        self.assertNotIn("away", every["orders-dev"])
        self.assertEqual(connections.away_aliases(self.root), ["orders-ist", "hr-dev", "ado"])

    def test_a_prompt_that_names_one_of_them_gets_its_details_with_the_prefix(self) -> None:
        self.opened()
        said = self.prompt("look at hr-dev please")
        self.assertIn("- hr-dev (DEV): SQL Server", said)
        self.assertIn("harness as hr-dev --", said)

    def test_a_window_opened_with_nothing_said_marks_nothing(self) -> None:
        self.assertEqual(connections.away_aliases(self.root), [])
        self.assertNotIn(messages.text("connections.away.context", n=1), self.start())


class OldCodeTests(unittest.TestCase):
    """C12 FC-4: the code of 8 small characters (before 1.7.38) is not taken any more; the code is 6 capitals, typed in either case."""

    def test_only_the_six_character_code_is_taken(self) -> None:
        digest = "6e285378ab12"
        for typed in ("6E2853", "6e2853"):
            approval.ask("go?", digest, "no", reader=lambda _prompt, typed=typed: typed)
        for typed in ("6e285378", "6E285378", "6e2853 78", "", "6E285"):
            with self.assertRaises(approval.Refused, msg=typed):
                approval.ask("go?", digest, "no", reader=lambda _prompt, typed=typed: typed)
        self.assertFalse(hasattr(approval, "LEGACY_LENGTH"))


class ButtonLabelTests(unittest.TestCase):
    """C12 FC-8: every English label of a button of the board starts with a capital, big or small."""

    def test_every_action_label_and_the_two_words_a_button_shows_start_with_a_capital(self) -> None:
        import json

        table = json.loads((ENGINE / "core" / "messages.en.json").read_text(encoding="utf-8"))
        keys = [key for key in table if key.startswith("board.action.") and key != "board.action.busy"] + ["board.copied", "board.serve.working"]
        self.assertGreaterEqual(len(keys), 25)
        self.assertEqual([key for key in keys if not table[key][:1].isupper()], [])

    def test_the_page_no_longer_changes_a_label_by_the_size_of_the_button(self) -> None:
        source = (WEB / "common.js").read_text(encoding="utf-8")
        self.assertNotIn("charAt(0).toUpperCase() + label.slice(1)", source)


class HeldCardTests(HarnessTestCase):
    """C12 FC-5: a card that names two `-i` files shows both scripts; a card with two statements on two systems names each system."""

    def setUp(self) -> None:
        super().setUp()
        self.folder = self.root / ".workspace" / "sandbox" / "tasks" / "t1"
        for name, text in (("a.sql", "SELECT 1;\n"), ("b.sql", "SELECT 2;\nSELECT 3;\n")):
            (self.folder / "DEV").mkdir(parents=True, exist_ok=True)
            (self.folder / "DEV" / name).write_text(text, encoding="utf-8")

    def layout(self, line: str) -> dict:
        return cmdview.layout(line, self.folder, self.root, str(self.root))

    def test_a_line_that_names_two_script_files_shows_both_in_the_order_of_the_line(self) -> None:
        found = self.layout("sqlcmd -S h -i DEV/a.sql -i DEV/b.sql")
        self.assertEqual([(one["path"], one["lines"]) for one in found["scripts"]], [("DEV/a.sql", 1), ("DEV/b.sql", 2)])
        self.assertEqual(found["script"]["path"], "DEV/a.sql", "script is the first, as before")
        self.assertEqual([line["value"] for line in found["lines"] if line["text"] == "-i"], ["DEV/a.sql", "DEV/b.sql"])

    def test_a_file_named_twice_is_shown_once_and_no_file_is_no_script(self) -> None:
        self.assertEqual([one["path"] for one in self.layout("sqlcmd -i DEV/a.sql -i DEV/a.sql")["scripts"]], ["DEV/a.sql"])
        found = self.layout("sqlcmd -S h -Q SELECT")
        self.assertEqual((found["script"], found["scripts"]), (None, []))
        self.assertEqual(cmdview.layout("", self.folder)["scripts"], [])

    def test_the_page_draws_every_script_of_the_line(self) -> None:
        source = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn("scriptsOf(item).map((script)", source)
        self.assertIn('files.map((script) => script.text).join("\\n")', source)
        self.assertIn("scripts.map((script) =>", source)
        self.assertIn('body.system ? [" ", h("b", null, body.system)', source)
        self.assertIn("part.system ? systemFact(part.system, part.env)", source)

    def words(self, line: str) -> dict:
        import json

        from core import config

        use_packs(self.root, "sqlserver")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {
            "acmedw-dev": {"type": "sqlserver", "env": "dev", "host": "localhost", "port": "14332", "database": "AcmeDW", "auth": "sql"},
            "acmedw-ist": {"type": "sqlserver", "env": "ist", "host": "localhost", "port": "14331", "database": "AcmeDW", "auth": "sql"}}}), encoding="utf-8")
        self.systems = config.policy_or_empty(self.root, "tools")["systems"]
        return taskdesk.call_words(line, self.systems["acmedw-dev"], self.folder, self.root, self.systems)

    def test_two_statements_on_two_systems_name_each_system(self) -> None:
        first, second = "UPDATE dbo.orders SET status = 1 WHERE id = 1", "UPDATE dbo.orders SET status = 2 WHERE id = 2"
        line = f'sqlcmd -S localhost,14332 -C -d AcmeDW -Q "{first}" && sqlcmd -S localhost,14331 -C -d AcmeDW -Q "{second}"'
        found = self.words(line)
        self.assertEqual([(part["system"], part["env"]) for part in found["parts"]], [("acmedw-dev", "dev"), ("acmedw-ist", "ist")])
        self.assertNotIn("at", found["parts"][0], "the cut of the line is not sent to the page")
        self.assertEqual([(one["system"], one["env"]) for one in taskdesk.reached(line, self.systems)], [("acmedw-dev", "dev"), ("acmedw-ist", "ist")])

    def test_the_one_statement_of_a_line_on_two_systems_says_whose_it_is(self) -> None:
        found = self.words('sqlcmd -S localhost,14332 -C -i DEV/a.sql && sqlcmd -S localhost,14331 -C -Q "UPDATE dbo.orders SET status = 2 WHERE id = 2"')
        self.assertNotIn("parts", found, "one text only: the script is no statement of the line")
        self.assertEqual((found["body"]["system"], found["body"]["env"]), ("acmedw-ist", "ist"))
        same = self.words('sqlcmd -S localhost,14332 -C -i DEV/a.sql && sqlcmd -S localhost,14332 -C -Q "UPDATE dbo.orders SET status = 2 WHERE id = 2"')
        self.assertNotIn("system", same["body"])

    def test_two_statements_on_one_system_say_nothing_more_and_one_statement_is_as_before(self) -> None:
        first, second = "UPDATE dbo.orders SET status = 1 WHERE id = 1", "UPDATE dbo.orders SET status = 2 WHERE id = 2"
        found = self.words(f'sqlcmd -S localhost,14332 -C -Q "{first}" && sqlcmd -S localhost,14332 -C -Q "{second}"')
        self.assertEqual(len(found["parts"]), 2)
        self.assertNotIn("system", found["parts"][0], "one system: the head of the card names it")
        one = self.words(f'sqlcmd -S localhost,14332 -C -Q "{first}"')
        self.assertNotIn("parts", one)
        self.assertEqual(taskdesk.reached("", self.systems), [])
        self.assertEqual(taskdesk.reached("echo hi", {}), [])


class HeldLineOnTwoSystemsTests(TaskCase):
    """A held line that reaches two systems and names two scripts: the card the page gets has both."""

    def test_the_card_of_a_line_on_two_systems_with_two_scripts_has_each_of_them(self) -> None:
        import json

        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": SYSTEMS}), encoding="utf-8")
        self.new()
        for name in ("a.sql", "b.sql"):
            path = self.root / TASK / "DEV" / "_manual" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"-- {name}\nSELECT 1;\n", encoding="utf-8")
        line = f"sqlctl -S h -i {TASK}/DEV/_manual/a.sql -i {TASK}/DEV/_manual/b.sql && ado comment 7 hello"
        data = pre_tool(SESSION, "run_in_terminal", {"command": line, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        self.assertEqual(self.hook(data)["permissionDecision"], "deny")  # held
        (card,) = taskdesk.outbox_view(self.root, TASK)
        self.assertEqual([one["system"] for one in card["reaches"]], ["sqlsys", "adosys"])
        self.assertEqual([one["path"] for one in card["layout"]["scripts"]], [f"{TASK}/DEV/_manual/a.sql", f"{TASK}/DEV/_manual/b.sql"])
        self.assertEqual(len(card["seen"]), 2, "both files are pinned, and both are shown")


class TaskLinkIconTests(TaskCase):
    """C12 new need: the list and the card of the lobby show a small link icon when the task is linked to tickets; the tip lists them."""

    def setUp(self) -> None:
        super().setUp()
        use_packs(self.root, "ado")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {
            "ado": {"type": "azure-devops", "env": "none", "org": "acme", "project": "demo", "url": "https://dev.azure.com"}}}), encoding="utf-8")
        taskboard._link_views.clear()
        self.new()
        self.prompt("start", session="sess-plain")
        self.new(name="plain", session="sess-plain")

    def test_a_row_carries_the_views_of_its_links_and_a_task_with_none_carries_none(self) -> None:
        self.run_cli("task", "link", "add", "ado:300100", "--task", NAME)
        self.run_cli("task", "link", "add", "zzz:9", "--task", NAME)
        result, _problems = taskboard.board_rows(self.root, False, served=())
        rows = {row["name"]: row for row in result["tasks"]}
        self.assertEqual([(one["ref"], one["url"]) for one in rows[NAME]["links"]], [("ado:300100", "https://dev.azure.com/acme/demo/_workitems/edit/300100"), ("zzz:9", "")])
        self.assertEqual(rows["plain"]["links"], [])

    def test_the_views_are_kept_for_a_moment_and_a_task_with_no_link_costs_nothing(self) -> None:
        data = {"links": [{"ref": "ado:1"}]}
        first = taskboard.link_marks(self.root, data)
        self.assertIs(taskboard.link_marks(self.root, data), first)
        self.assertEqual(taskboard.link_marks(self.root, {"links": []}), [])
        self.assertEqual(taskboard.link_marks(self.root, {}), [])

    def test_both_pages_draw_the_icon_and_the_tip_is_the_card_of_status_js(self) -> None:
        for name in ("board.js", "lobby.js"):
            self.assertIn("Status.links(row.links)", (WEB / name).read_text(encoding="utf-8"), name)
        status = (WEB / "status.js").read_text(encoding="utf-8")
        self.assertIn("return {row: build, links: linkMark, stages,", status)
        self.assertIn('card(chip, () => ({sig: JSON.stringify(links), build: () => linkCard(links)}), words)', status)
        self.assertIn('target: "_blank", rel: "noopener noreferrer"', status)
        css = (WEB / "status.css").read_text(encoding="utf-8")
        self.assertIn(".st-card{position:fixed;", css, "the card is drawn by the board and the task page: its look is in the shared file")
        self.assertNotIn(".st-card{position:fixed;", (WEB / "desk.css").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
