"""1.7.38, wording and board changes of C13 D5: one test class for each change."""

from __future__ import annotations

import unittest
from pathlib import Path

import support  # noqa: F401 - the engine on sys.path
from support import HarnessTestCase

from test_connection_find import FindCase
from test_connections import KIND, ConnectionsCase

from core import approval, connections, messages, systems
from modules.gate import rules
from modules.task import boardserve

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


if __name__ == "__main__":
    unittest.main()
