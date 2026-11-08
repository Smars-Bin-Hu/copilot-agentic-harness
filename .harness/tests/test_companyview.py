"""The Company tab of the knowledge base window (1.7.32): the sections, the naming rule of skills, and what is marked as missing."""

from __future__ import annotations

import json
import shutil
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

SAY = [{"pattern": r"\bcomment\s+(\S+)", "text": {"en": "Add a comment to ticket {1}", "zh": "给工单 {1} 加评论"}}, {"pattern": r"\bclose\s+(\S+)", "text": "Close ticket {1}"}, {"pattern": r"\bset-state\s+(\S+)", "text": "Set the state of ticket {1}"}]
VERBS = [{"pattern": r"\b(?:get|list)\b", "verb": "read"}, {"pattern": r"\bwhoami\b", "verb": "read"}, {"pattern": r"^(?:--json\s+)*(?:comment|close|set-state)\b", "verb": "write"}, {"pattern": r"\bmerge\b", "verb": "exec"}, {"pattern": r"\bdelete\b", "verb": "destroy"}]


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
        toolpacks.sync_skills(self.root)  # 1.7.30: adding records the folder; the skills are put into .github/skills/ by sync, with the company's prefix when one is set

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
        self.assertEqual(found["name"], "")  # no name in company.json: none shown, never the folder name (1.7.35)
        self.assertIn({"file": "naming.md", "first": "Names", "state": "other"}, found["standards"])
        self.assertEqual([row["file"] for row in found["instructions"]], ["knowledgebase.instructions.md"])
        self.assertGreater(found["stale"], 0, "nothing was copied yet")

    def test_a_standard_or_instruction_says_whether_it_reaches_copilot(self) -> None:
        put(self.kb, {**FILES, "company/standards/code-standards.md": "# Code\n\nNo select star", "company/standards/naming.md": "# Names", "company/instructions/pipelines.instructions.md": "# Pipelines"})
        set_prefix(self.root)
        states = lambda: {row["file"]: row["state"] for row in (lambda found: found["standards"] + found["instructions"])(companyview.company(self.root, "en"))}  # noqa: E731
        self.assertEqual(states(), {"code-standards.md": "inplace", "naming.md": "other", "knowledgebase.instructions.md": "not-copied", "pipelines.instructions.md": "never"})
        from core import company

        company.sync(self.root)
        self.assertEqual(states()["knowledgebase.instructions.md"], "copied")
        self.assertEqual(states()["pipelines.instructions.md"], "never", "only knowledgebase.instructions.md is ever copied")
        self.assertFalse((self.root / ".github/instructions/pipelines.instructions.md").exists())

    def test_a_use_name_no_factory_pack_has_is_listed(self) -> None:
        shutil.copytree(support.REPO / ".harness/toolpacks/ado", self.root / ".harness/toolpacks/ado")
        put(self.kb, {**FILES, "company/tools/packs.json": '{"use": ["ado", "nope"]}'})
        self.assertEqual(companyview.company(self.root, "en")["unknown_use"], ["nope"])

    def test_skills_are_grouped_by_name_and_one_in_the_knowledge_base_but_not_copied_is_marked(self) -> None:
        put(self.kb, {**FILES, "company/skills/acme-tracker-sop/SKILL.md": SKILL.format(name="acme-tracker-sop")})
        set_prefix(self.root)
        self.install()
        self.assertTrue((self.root / ".github/skills/acme-tracker-ticket").is_dir(), "1.7.30: the prefix is put on the pack's skills by sync")
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
            self.assertEqual([row["text"] for row in pack["writes"]], [comment, "Close ticket …", "Set the state of ticket …"])
            self.assertEqual(pack["execs"], [{"text": "", "pattern": r"\bmerge\b"}], "no words for it: the pattern")
            self.assertEqual(pack["destroys"][0]["pattern"], r"\bdelete\b")

    def test_reads_are_the_commands_of_the_pack_less_its_writes_and_runs(self) -> None:
        self.install()
        found = next(iter(toolpacks.active(self.root).values()))
        manifest_file = found["folder"] / "toolpack.json"
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        manifest["commands"] = ["get", "list", "whoami", "comment", "close", "set-state", "merge", "delete", "version"]
        manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
        pack = companyview.company(self.root, "en")["tools"][0]
        self.assertEqual(pack["reads"], 4, "9 commands, less 3 writes, 1 run and 1 destroy")

    def test_the_shipped_ado_pack_has_27_reads_6_writes_4_runs(self) -> None:
        shutil.copytree(support.REPO / ".harness/toolpacks/ado", self.root / ".harness/toolpacks/ado")
        put(self.kb, {**FILES, "company/tools/packs.json": '{"use": ["ado"]}'})
        pack = next(item for item in companyview.company(self.root, "en")["tools"] if item["name"] == "ado")
        self.assertEqual((pack["reads"], len(pack["writes"]), len(pack["execs"])), (27, 6, 4))

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


class PageRules(unittest.TestCase):
    """1.7.38 (the C11 test of a whole setup): what the pages do, as far as a test of the files can say. The real look was checked in a browser."""

    WEB = Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "web"

    def source(self, name: str) -> str:
        return (self.WEB / name).read_text(encoding="utf-8")

    def test_the_company_tab_keeps_the_actions_folded_and_a_rule_in_no_words_is_a_count(self) -> None:
        tab = self.source("companytab.js")
        self.assertIn('h("details", {class: "co-verb"}', tab)  # no `open`: only the number shows
        self.assertNotIn("open: open", tab)
        self.assertIn('t(bare.length === 1 ? "dock.co.rules.one" : "dock.co.rules"', tab)
        self.assertIn('h("code", {class: "co-pat"}, row.pattern)', tab)  # the pattern is in the small window

    def test_pack_for_colleagues_checks_before_it_asks_for_a_folder(self) -> None:
        dock = self.source("dock.js")
        start = dock.split("function packStart()")[1].split("function paintPackError")[0]
        self.assertLess(start.index('op: "packcheck"'), start.index('chooseOnPage("folder"'))
        self.assertIn('op: "commit"', dock)  # the button commits; no command to read
        self.assertNotIn("git -C", dock)

    def test_every_tab_of_the_window_says_when_there_is_no_knowledge_base_and_refresh_forgets_every_view(self) -> None:
        dock = self.source("dock.js")
        self.assertIn("if (found.has_kb === false) { emptyState(); return; }", dock)
        self.assertIn('post({op: "forget"})', dock)
        self.assertIn("recheck();", dock)  # the copies are looked at again with Refresh and when the window opens

    def test_a_connection_of_ones_own_is_removed_only_after_the_browser_asked(self) -> None:
        servers = self.source("servers.js")
        self.assertIn('window.confirm(t("connections.forget.ask"', servers)
        self.assertNotIn("connections.forget.sure", servers)
        self.assertIn('"connections.state.notsaved"', servers)  # a failed test of what is not kept says so
        self.assertIn("env.redraw()", servers.split("shareWindow(row, (said, bad) =>")[1].split("));")[0])  # a share draws the list again

    def test_a_row_name_of_an_unfolded_list_opens_its_window(self) -> None:
        enter = self.source("enter.js")
        self.assertNotIn('if (!name || list.classList.contains("folded")) return;', enter)


class Wiring(ViewCase):
    def test_the_window_knows_when_no_knowledge_base_is_in_place_and_forgets_its_views_on_request(self) -> None:
        """1.7.38: every tab shows the empty state with no knowledge base; Refresh and a rebuilt map make every kept view old."""
        shutil.rmtree(self.kb, ignore_errors=True)
        view = kbview.View(self.root)
        with mock.patch.object(kbview.threading, "Thread"):  # no view is worked out here: only the answer's shape is looked at
            self.assertFalse(view.get("status")["has_kb"])
        put(self.kb, {"README.md": "# kb\n", "domains/sales/domain.yaml": "name: sales\n"})
        with mock.patch.object(kbview.threading, "Thread"):
            self.assertTrue(view.get("status")["has_kb"])
        view.kept["status"].update(at=123.0, running=False)
        view.kept["atlas"] = {"result": {"x": 1}, "at": 456.0, "good": 456.0, "running": False, "error": ""}
        view.forget()
        self.assertEqual((view.kept["status"]["at"], view.kept["atlas"]["at"], view.kept["atlas"]["result"]), (0.0, 0.0, {"x": 1}))  # the old answer stays on the page until the new one comes

    def test_the_knowledge_base_window_asks_for_the_view_by_name(self) -> None:
        view = kbview.View(self.root)
        self.assertEqual(set(view.work("company")()), set(companyview.company(self.root)))


if __name__ == "__main__":
    unittest.main()
