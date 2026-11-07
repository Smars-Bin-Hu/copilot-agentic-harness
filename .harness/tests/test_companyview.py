"""The Company tab of the knowledge base window (1.7.32): the sections, the naming rule of skills, and what is marked as missing."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401
from support import HarnessTestCase

from core import reach, skillboard, skillgroups, toolpacks
from modules.task import companyview, kbview
from test_company import FILES, SKILL, put, set_prefix
from test_toolpacks import KIND, make

SAY = [{"pattern": r"\bcomment\s+(\S+)", "text": {"en": "Add a comment to ticket {1}", "zh": "给工单 {1} 加评论"}}, {"pattern": r"\bclose\s+(\S+)", "text": "Close ticket {1}"}]
VERBS = [{"pattern": r"\b(?:get|list)\b", "verb": "read"}, {"pattern": r"\bwhoami\b", "verb": "read"}, {"pattern": r"\b(?:comment|close)\b", "verb": "write"}, {"pattern": r"\bmerge\b", "verb": "exec"}, {"pattern": r"\bdelete\b", "verb": "destroy"}]


class ViewCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.outside = Path(holder.name)
        self.kb = self.root / "knowledge-base"

    def install(self, name: str = "tracker", skills=("tracker-ticket",)) -> None:
        source = make(self.outside / name, name=name, skills=skills)
        (source / "types" / "tracker.json").write_text(json.dumps(dict(KIND, say=SAY, verbs=VERBS)), encoding="utf-8")
        toolpacks.add(self.root, str(source))

    def connect(self, alias: str = "main", env: str = "none") -> None:
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {alias: {"type": "tracker", "env": env, "org": "acme"}}}), encoding="utf-8")


class Rule(unittest.TestCase):
    def test_the_name_alone_tells_the_group(self) -> None:
        packs = {"ado": {}, "sql": {}}
        cases = {"harness-my-task": ("harness", ""), "generic-goal-driven": ("harness", ""), "acme-ado-workitem": ("pack", "ado"), "ado-workitem": ("pack", "ado"),
                 "acme-release-notes": ("company", ""), "acme-adobe-x": ("company", ""), "acme-sql-x": ("pack", "sql")}
        for name, want in cases.items():
            self.assertEqual(skillgroups.group(name, "acme", packs), want, name)
        self.assertEqual(skillgroups.group("ado-workitem", "", {"ado": {}}), ("pack", "ado"))


class Sections(ViewCase):
    def test_no_company_folder_and_no_pack_is_an_empty_page_not_an_error(self) -> None:
        (self.root / ".github/skills/harness-demo").mkdir(parents=True)
        (self.root / ".github/skills/harness-demo/SKILL.md").write_text(SKILL.format(name="harness-demo"), encoding="utf-8")
        found = companyview.company(self.root, "en")
        self.assertFalse(found["found"])
        self.assertEqual((found["tools"], found["domains"], found["standards"]), ([], [], []))
        self.assertTrue(found["skills"]["harness"], "the skills that come with the harness are listed")
        self.assertEqual((found["skills"]["company"], found["skills"]["pack"]), ([], []))

    def test_the_company_part_names_what_the_files_say(self) -> None:
        put(self.kb, {**FILES, "company/manifest.json": '{"version": "3", "made": "2026-11-01 10:00"}', "domains/orders/domain.yaml": "x", "domains/.hidden/x": "x", "company/standards/naming.md": "---\nx: y\n---\n\n## Names\n\nBody"})
        set_prefix(self.root)
        found = companyview.company(self.root, "en")
        self.assertEqual((found["found"], found["prefix"], found["version"], found["made"], found["domains"]), (True, "acme", "3", "2026-11-01 10:00", ["orders"]))
        self.assertEqual(found["name"], "knowledge-base")
        self.assertIn({"file": "naming.md", "first": "Names"}, found["standards"])
        self.assertEqual([row["file"] for row in found["instructions"]], ["knowledgebase.instructions.md"])
        self.assertGreater(found["stale"], 0, "nothing was copied yet")

    def test_skills_are_grouped_by_name_and_one_in_the_knowledge_base_but_not_copied_is_marked(self) -> None:
        put(self.kb, {**FILES, "company/skills/acme-tracker-sop/SKILL.md": SKILL.format(name="acme-tracker-sop")})
        set_prefix(self.root)
        self.install()
        copy = self.root / ".github/skills/acme-tracker-ticket"
        (self.root / ".github/skills/tracker-ticket").rename(copy)  # a company that names its pack skills with its prefix
        (self.root / ".github/skills/acme-other").mkdir()
        (self.root / ".github/skills/acme-other/SKILL.md").write_text(SKILL.format(name="acme-other"), encoding="utf-8")
        skills = companyview.company(self.root, "en")["skills"]
        self.assertEqual({row["name"]: row["synced"] for row in skills["company"]}, {"acme-other": True, "acme-ticket": False})
        self.assertEqual({row["name"]: (row["pack"], row["synced"]) for row in skills["pack"]}, {"acme-tracker-ticket": ("tracker", True), "acme-tracker-sop": ("tracker", False)})
        self.assertTrue(all(row["name"].split("-")[0] in ("harness", "generic") for row in skills["harness"]))
        self.assertIn("Open a ticket", skills["company"][0]["about"])

    def test_the_board_list_of_skills_carries_the_same_group(self) -> None:
        self.install()
        path = self.root / ".github/skills/tracker-ticket/SKILL.md"
        path.write_text(path.read_text(encoding="utf-8").replace("type: workflow", "type: workflow\nboard-opens: chat"), encoding="utf-8")
        row = next(item for item in skillboard.skills(self.root) if item["name"] == "tracker-ticket")
        self.assertEqual((row["naming"], row["pack"], row["own"]), ("pack", "tracker", True))


class Tools(ViewCase):
    def test_a_pack_shows_reads_as_a_count_and_writes_as_words_in_the_language_of_the_page(self) -> None:
        self.install()
        for lang, comment in (("en", "Add a comment to ticket …"), ("zh", "给工单 … 加评论")):
            pack = companyview.company(self.root, lang)["tools"][0]
            self.assertEqual((pack["name"], pack["version"], pack["reads"]), ("tracker", "1.0.0", 3))
            self.assertEqual([row["text"] for row in pack["writes"]], [comment, "Close ticket …"])
            self.assertEqual(pack["execs"], [{"text": "", "pattern": r"\bmerge\b"}], "no words for it: the pattern")
            self.assertEqual(pack["destroys"][0]["pattern"], r"\bdelete\b")

    def test_what_is_missing_is_named(self) -> None:
        self.install()
        with mock.patch("shutil.which", return_value=None):
            pack = companyview.company(self.root, "en")["tools"][0]
        self.assertEqual(pack["missing"], ["connection", "program:tracker"])
        self.connect()
        with mock.patch("shutil.which", return_value="/bin/tracker"):
            pack = companyview.company(self.root, "en")["tools"][0]
        self.assertEqual([(link["name"], link["state"]) for link in pack["connections"]], [("main", reach.UNKNOWN)])
        self.assertEqual(pack["missing"], ["untested"])

    def test_a_connection_shows_the_state_the_probe_found_and_why_it_failed(self) -> None:
        self.install()
        self.connect(env="dev")
        with mock.patch("shutil.which", return_value="/bin/tracker"):
            reach._write(self.root, {"main:dev": {"state": reach.OK, "at": "2026-11-07T10:00:00Z", "why": "", "who": "alice", "source": "board"}})
            link = companyview.company(self.root, "en")["tools"][0]["connections"][0]
            self.assertEqual((link["state"], link["who"], link["env"]), (reach.OK, "alice", "dev"))
            reach._write(self.root, {"main:dev": {"state": reach.FAILED, "at": "2026-11-07T10:00:00Z", "why": "no-answer", "who": "", "source": "board"}})
            link = companyview.company(self.root, "en")["tools"][0]["connections"][0]
            self.assertEqual(link["state"], reach.FAILED)
            self.assertTrue(link["why"])

    def test_twelve_packs_and_long_names_come_through(self) -> None:
        for number in range(12):
            self.install(name=f"pack{number}x" + "y" * 20, skills=())
        found = companyview.company(self.root, "en")
        self.assertEqual(len(found["tools"]), 12)


class Wiring(ViewCase):
    def test_the_knowledge_base_window_asks_for_the_view_by_name(self) -> None:
        view = kbview.View(self.root)
        self.assertEqual(set(view.work("company")()), set(companyview.company(self.root)))


if __name__ == "__main__":
    unittest.main()
