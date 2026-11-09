"""1.7.38, wording and board changes of C13 D5: one test class for each change."""

from __future__ import annotations

import unittest
from pathlib import Path

import support  # noqa: F401 - the engine on sys.path
from support import HarnessTestCase

from test_connections import KIND, ConnectionsCase

from core import connections, messages, systems
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


if __name__ == "__main__":
    unittest.main()
