"""1.7.38, wording and board changes of C13 D5: one test class for each change."""

from __future__ import annotations

import unittest
from pathlib import Path

import support  # noqa: F401 - the engine on sys.path
from support import HarnessTestCase

from core import messages, systems
from modules.gate import rules

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


if __name__ == "__main__":
    unittest.main()
