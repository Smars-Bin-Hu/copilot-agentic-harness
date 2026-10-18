"""The language switch: `user.json` picks `en` or `zh` for what the CLI and the hooks say and for the task templates.

The other tests run in Chinese (support.py pins it). These check that the two tables say the same things by the same
names, that the switch is read the way the docs say, and that English comes out end to end.
"""

from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path
from typing import Dict, List

from support import ENGINE, REPO, HarnessTestCase, payload, pre_tool

from core import messages, tasks
from modules.task import taskreview

HAN = re.compile(r"[一-鿿]")
WIDE_PUNCTUATION = re.compile(r"[，。：；（）、“”]")
HOLE = re.compile(r"(?<!\{)\{([a-z_]+)\}(?!\})")
SESSION = "sess-language"
# Chinese that stays in the code on purpose: the sample line doctor prints, and the labels a task made in Chinese has.
CHINESE_ALLOWED = {
    "core/output.py": ("SAMPLE = ",),
    "modules/task/taskinsight.py": ("SESSION_IN_DETAIL = ",),
    "modules/task/taskreview.py": ("_CONFIRM_LABEL = ", "_CONFIRMED = ", "_NOT_CONFIRMED = ", "_VERDICT = "),
}


def holes(text: str) -> List[str]:
    return sorted(set(HOLE.findall(text)))


class TableTests(unittest.TestCase):
    def test_both_tables_have_the_same_names_in_the_same_order(self) -> None:
        self.assertTrue(messages.table("en"))
        self.assertEqual(list(messages.table("en")), list(messages.table("zh")))

    def test_a_message_has_the_same_placeholders_in_both_languages(self) -> None:
        english, chinese = messages.table("en"), messages.table("zh")
        different = [name for name in english if holes(english[name]) != holes(chinese.get(name, ""))]
        self.assertEqual(different, [])

    def test_the_english_table_has_no_chinese(self) -> None:
        english = messages.table("en")
        self.assertEqual([name for name, text in english.items() if HAN.search(text) or WIDE_PUNCTUATION.search(text)], [])

    def test_every_message_has_a_chinese_text_that_is_chinese(self) -> None:
        plain = ("task.kind.rca", "report.kpi.premium", "log.count.item", "list.", "mdreport.fetched.more", "board.brand", "board.copyright", "board.action.archive")  # a product word or a pattern: the same in both
        chinese = messages.table("zh")
        self.assertEqual([name for name, text in chinese.items() if not HAN.search(text) and not WIDE_PUNCTUATION.search(text) and not name.startswith(plain)], [])

    def test_the_engine_has_no_chinese_text_outside_the_tables(self) -> None:
        found = []
        for path in sorted(ENGINE.rglob("*.py")):
            name = path.relative_to(ENGINE).as_posix()
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0] if line.lstrip().startswith("#") else line
                if not HAN.search(code) or '"""' in line:
                    continue
                if not any(mark in line for mark in CHINESE_ALLOWED.get(name, ())):
                    found.append(f"{name}:{number}")
        self.assertEqual(found, [])

    def test_the_pages_have_no_chinese_text_outside_the_tables(self) -> None:
        web = ENGINE / "modules" / "task" / "web"
        self.assertEqual([path.name for path in sorted(web.iterdir()) if path.is_file() and HAN.search(path.read_text(encoding="utf-8"))], [])


class SwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = os.environ.get(messages.ENVIRONMENT)
        self.addCleanup(self.restore)

    def restore(self) -> None:
        if self.saved is None:
            os.environ.pop(messages.ENVIRONMENT, None)
        else:
            os.environ[messages.ENVIRONMENT] = self.saved
        messages.reset()

    def speak(self, language: str) -> None:
        os.environ[messages.ENVIRONMENT] = language
        messages.reset()

    def test_the_shipped_default_is_english(self) -> None:
        self.assertEqual(messages.DEFAULT_LANGUAGE, "en")
        self.assertEqual(json.loads((REPO / ".harness" / "policies" / "user.json").read_text(encoding="utf-8"))["language"], "en")

    def test_the_environment_picks_the_language(self) -> None:
        self.speak("en")
        self.assertEqual(messages.text("task.name.empty"), "The task name cannot be empty.")
        self.speak("zh")
        self.assertEqual(messages.text("task.name.empty"), "任务名不能为空。")

    def test_a_language_that_is_not_known_falls_back_to_the_default(self) -> None:
        self.speak("fr")
        self.assertEqual(messages.language(), "en")

    def test_a_policy_text_can_be_one_string_or_one_per_language(self) -> None:
        self.speak("zh")
        self.assertEqual(messages.pick({"en": "it deletes files", "zh": "删除文件"}), "删除文件")
        self.assertEqual(messages.pick("改线上资源"), "改线上资源")
        self.assertEqual(messages.pick({"en": "only english"}), "only english")
        self.speak("en")
        self.assertEqual(messages.pick({"en": "it deletes files", "zh": "删除文件"}), "it deletes files")

    def test_every_reason_in_the_gate_policy_has_both_languages(self) -> None:
        terminal = json.loads((REPO / ".harness" / "policies" / "gate.json").read_text(encoding="utf-8"))["terminal"]
        for group in ("guardrail_write", "deny", "ask"):
            for rule in terminal[group]:
                self.assertEqual(sorted(rule["why"]), ["en", "zh"], rule["pattern"])
                self.assertFalse(HAN.search(rule["why"]["en"]), rule["why"]["en"])


class PolicyCase(HarnessTestCase):
    """The language comes from `user.json` of the root the engine runs in, not from the environment."""

    def setUp(self) -> None:
        super().setUp()
        self.env.pop(messages.ENVIRONMENT, None)

    def override(self, language: str) -> None:
        path = self.root / ".harness" / "policies" / "user.override.json"
        path.write_text(json.dumps({"language": language}), encoding="utf-8")

    def rules(self) -> str:
        return self.hook(payload("UserPromptSubmit", SESSION, prompt="hello")).get("additionalContext", "")

    def denied(self) -> str:
        output = self.hook(pre_tool(SESSION, "create_file", {"filePath": ".harness/policies/gate.json", "content": "{}"}))
        return json.dumps(output, ensure_ascii=False)


class EnglishTests(PolicyCase):
    def test_the_rules_are_in_english_and_ask_for_english(self) -> None:
        rules = self.rules()
        self.assertIn("Current session id: " + SESSION, rules)
        self.assertIn("Language: answer the user in English", rules)
        self.assertFalse(HAN.search(rules), rules)

    def test_a_refusal_is_in_english(self) -> None:
        self.rules()
        said = self.denied()
        self.assertIn("is a guardrail file", said)
        self.assertFalse(HAN.search(said), said)

    def test_a_refused_terminal_command_gives_the_english_reason_of_the_policy(self) -> None:
        self.rules()
        said = json.dumps(self.hook(pre_tool(SESSION, "run_in_terminal", {"command": "sudo ls"})), ensure_ascii=False)
        self.assertIn("it runs with administrator rights", said)
        self.assertFalse(HAN.search(said), said)

    def test_a_new_task_gets_the_english_templates_and_an_english_next_step(self) -> None:
        self.rules()
        result = self.cli_json("task", "new", "job-en", "--kind", "design", "--session-id", SESSION)
        self.assertFalse(HAN.search(json.dumps(result, ensure_ascii=False)), result)
        folder = self.root / tasks.TASKS_DIR / "job-en"
        self.assertIn("- **Kind**: design, development plan", (folder / "TASK.md").read_text(encoding="utf-8"))
        request = (folder / "REQ.md").read_text(encoding="utf-8")
        self.assertIn("- **User confirmed**: <not yet / confirmed yyyy-mm-dd>", request)
        self.assertIs(taskreview.req_confirmed(self.root, f"{tasks.TASKS_DIR}/job-en"), False)
        (folder / "REQ.md").write_text(request.replace("<not yet / confirmed yyyy-mm-dd>", "confirmed 2026-10-13"), encoding="utf-8")
        self.assertIs(taskreview.req_confirmed(self.root, f"{tasks.TASKS_DIR}/job-en"), True)

    def test_doctor_speaks_english(self) -> None:
        said = self.cli("doctor").stdout
        self.assertIn("Language: en (from user.json or its override)", said)
        chinese = [line for line in said.splitlines() if HAN.search(line) and "中文样例" not in line]
        self.assertEqual(chinese, [])


class ChineseTests(PolicyCase):
    def setUp(self) -> None:
        super().setUp()
        self.override("zh")

    def test_the_override_switches_everything_to_chinese(self) -> None:
        rules = self.rules()
        self.assertIn("当前会话 id：" + SESSION, rules)
        self.assertIn("语言：用中文回答用户", rules)
        self.assertIn("是 guardrail 文件", self.denied())
        self.cli_json("task", "new", "job-zh", "--kind", "design", "--session-id", SESSION)
        self.assertIn("- **用户确认**：<还没确认 / yyyy-mm-dd 已确认>", (self.root / tasks.TASKS_DIR / "job-zh" / "REQ.md").read_text(encoding="utf-8"))

    def test_doctor_refuses_a_language_it_does_not_know(self) -> None:
        self.override("fr")
        said = self.cli("doctor").stdout
        self.assertIn("[ERROR] language in user.json is `fr`", said)


class TemplateTests(unittest.TestCase):
    FOLDER = REPO / ".harness" / "contracts" / "templates" / "task"

    def names(self, language: str) -> Dict[str, str]:
        return {path.name: path.read_text(encoding="utf-8") for path in sorted((self.FOLDER / language).glob("*.md"))}

    def test_both_languages_have_the_same_templates_with_the_same_shape(self) -> None:
        english, chinese = self.names("en"), self.names("zh")
        self.assertEqual(sorted(english), ["LOG.md", "REQ.md", "TASK.md", "TODO.md"])
        self.assertEqual(sorted(english), sorted(chinese))
        for name in english:
            for mark in (r"^## ", r"^- \*\*", r"^> ", r"\{[a-z]+\}"):
                self.assertEqual(len(re.findall(mark, english[name], re.M)), len(re.findall(mark, chinese[name], re.M)), f"{name} {mark}")
            self.assertFalse(HAN.search(english[name]), name)

    def test_no_template_is_left_outside_a_language_folder(self) -> None:
        self.assertEqual(sorted(path.name for path in self.FOLDER.glob("*.md")), [])


if __name__ == "__main__":
    unittest.main()
