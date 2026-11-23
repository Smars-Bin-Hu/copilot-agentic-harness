"""1.8.31: the setup wizard's pages after the first new-colleague walk: rules that can be read in the page script, the sheet and the texts."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import support  # noqa: F401 - the paths
from modules.task import taskhtml

WEB = Path(taskhtml.__file__).resolve().parent / "web"
CORE = Path(taskhtml.__file__).resolve().parents[2] / "core"
SCRIPT = (WEB / "wizard.js").read_text(encoding="utf-8")
SHEET = (WEB / "wizard.css").read_text(encoding="utf-8")
TEXTS = {code: json.loads((CORE / f"messages.{code}.json").read_text(encoding="utf-8")) for code in ("en", "zh")}
NEW = ("wizard.job.tip", "wizard.v.title.check", "wizard.r.nomatch", "wizard.y.lang.hint.save")


class WizardPolishTests(unittest.TestCase):
    def test_the_bare_copilot_page_does_not_go_on_by_itself(self) -> None:  # #14: Settings draws the page bare; no "Moving on" and no step forward there
        line = next(row for row in SCRIPT.splitlines() if "advance = setTimeout" in row)
        self.assertIn("!opts.bare", line)
        self.assertIn("ONLY || opts.bare ?", SCRIPT)

    def test_the_terminal_button_has_its_place_in_the_top_line(self) -> None:  # #6: it sat on the end of the progress bar at 820 px
        self.assertRegex(SHEET, r"body\.wz-doc \.term-toggle\{top:\d+px;right:\d+px\}")
        top = re.search(r"\.wz-top\{[^}]*padding:(\d+)px (\d+)px 0 (\d+)px", SHEET)
        self.assertTrue(top and int(top.group(2)) >= 64, "the top line leaves room for the button on its right")

    def test_new_texts_exist_in_both_languages_and_are_used(self) -> None:
        for key in NEW:
            for code in ("en", "zh"):
                self.assertTrue(TEXTS[code].get(key), (code, key))
            self.assertIn(key, SCRIPT)

    def test_the_download_line_says_it_is_one_time_and_says_so_on_hover(self) -> None:  # A4
        self.assertIn("one-time download", TEXTS["en"]["wizard.job.prep"])
        self.assertIn("shell.job.title", SCRIPT)

    def test_skip_notes_say_what_happens_if_you_skip_not_that_it_was_skipped(self) -> None:  # #20
        for key in ("wizard.k.skipnote", "wizard.t.skipnote"):
            self.assertTrue(TEXTS["en"][key].startswith("If you skip:"), key)
        self.assertNotIn("Skipped:", json.dumps(TEXTS["en"]))

    def test_the_package_card_does_not_say_it(self) -> None:  # #21: "IT BROUGHT" read like the IT department
        self.assertEqual(TEXTS["en"]["wizard.k.brought"], "In this package")

    def test_the_review_title_claims_ready_only_when_nothing_is_left(self) -> None:  # #25
        self.assertIn('t(no.length ? "wizard.v.title.check" : "wizard.v.title")', SCRIPT)
        self.assertIn('t("wizard.v.title.check")', SCRIPT)  # the title before the answer arrives claims nothing

    def test_the_repositories_page_marks_the_end_and_the_empty_filter(self) -> None:  # #22 #23 #24
        self.assertIn(".wz-fade::after", SHEET)
        self.assertIn('t("wizard.r.nomatch")', SCRIPT)
        self.assertIn("minw:", SCRIPT)
        self.assertIn("not changed", TEXTS["en"]["wizard.r.sub"])
        self.assertNotIn("Nothing is changed", TEXTS["en"]["wizard.r.sub"])

    def test_the_welcome_page_marks_both_kinds_of_need_the_same_way(self) -> None:  # #12: an orange dot, no hollow ring
        self.assertNotIn('"none"', SCRIPT.split("parts.welcome")[1].split("parts.you")[0])

    def test_small_kb_pages_say_why_continue_waits_and_skip_goes_when_nothing_is_left(self) -> None:  # #18 #19
        pages = SCRIPT.split("function kbPrograms")[1].split("parts.repos")[0]
        self.assertIn('why: rows.length ? t("wizard.p.need"', pages)
        self.assertIn("later: packConnections().some((row) => !row.saved) ?", pages)

    def test_the_one_time_code_counts_down_by_itself_and_sign_in_has_one_wording(self) -> None:  # #27
        self.assertIn("setInterval(", SCRIPT.split("parts.copilot")[1].split("parts.kb")[0])
        self.assertNotIn("Sign in to continue", json.dumps(TEXTS["en"]))

    def test_the_language_pick_waits_for_its_button_and_the_page_says_so(self) -> None:  # #29: one rule, in Settings (Save) and in the wizard (Continue)
        you = SCRIPT.split("parts.you")[1].split("parts.programs")[0]
        self.assertNotIn("api.language(", you)  # a tile only marks the pick; the save writes it
        self.assertIn("Save", TEXTS["en"]["wizard.y.lang.hint.save"])
        self.assertIn("harness.saved.you", you)

    # --- walkthrough 2 (1.8.31) ---------------------------------------------------------------------------------------------------------------------------------------

    def test_welcome_says_what_is_saved_for_the_repositories_not_what_was_found(self) -> None:  # w2 #3 #4
        welcome = SCRIPT.split("parts.welcome")[1].split("parts.you")[0]
        self.assertIn("chosenRepos()", welcome)
        self.assertIn("wizard.l.repo.n", welcome)
        self.assertIn("function chosenRepos", SCRIPT)
        self.assertIn("row.picked || row.in_root", SCRIPT)
        self.assertEqual(TEXTS["en"]["wizard.l.repo.v"], "None chosen \u00b7 {n} found")  # the orange dot has words that say it
        self.assertEqual(TEXTS["en"]["wizard.l.repo.n"], "{n} repositories")
        self.assertEqual(TEXTS["en"]["wizard.l.repo.n.one"], "1 repository")
        for code in ("en", "zh"):
            for key in ("wizard.l.repo.v", "wizard.l.repo.n", "wizard.l.repo.n.one"):
                self.assertIn("{n}" if key != "wizard.l.repo.n.one" else "1", TEXTS[code][key])
        self.assertNotIn('"pick"', welcome)  # no third kind: found-but-yours-to-choose is orange with its words

    def test_the_minutes_on_welcome_come_from_the_pages_that_will_show(self) -> None:  # w2 #31
        welcome = SCRIPT.split("parts.welcome")[1].split("parts.you")[0]
        self.assertIn("c: minutes()", welcome)
        self.assertNotIn("need > 1 ? 4 : 1", SCRIPT)
        self.assertIn("[1, 2, 3, 4, 5].filter((page) => !fine(page)).length + 1", SCRIPT)

    def test_the_knowledge_base_step_has_no_n_of_m_counter_and_a_grey_continue_says_why(self) -> None:  # w2 #6 #26
        self.assertNotIn("wizard.k.eyebrow", SCRIPT)
        for code in ("en", "zh"):
            self.assertNotIn("wizard.k.eyebrow", TEXTS[code])
            for key in ("wizard.k.why", "wizard.k.why.copy", "wizard.k.why.replace"):
                self.assertTrue(TEXTS[code].get(key), (code, key))
                self.assertIn(key, SCRIPT)
        self.assertIn('eyebrowText = t("wizard.s.kb")', SCRIPT)
        self.assertIn('t("wizard.step", {n: M.page, m: 6})', SCRIPT)  # the step counter stays

    def test_the_review_gear_is_the_docks_gear_with_the_dot(self) -> None:  # w2 #20
        dock = (WEB / "dock.js").read_text(encoding="utf-8")
        paths = re.findall(r'"(M12 [^"]+)"', SCRIPT.split("const GEAR = [")[1].split("];")[0])
        self.assertEqual(len(paths), 2)
        for path in paths:
            self.assertIn('"' + path + '"', dock)
        self.assertNotIn("\\u2699", SCRIPT)
        self.assertRegex(SHEET, r"\.wz-gear\{[^}]*width:2[4-9]px")
        self.assertIn(".wz-gear svg{", SHEET)
        self.assertIn(".wz-gear::after{", SHEET)

    def test_every_review_row_has_a_value_with_its_unit(self) -> None:  # w2 #21
        self.assertIn('t("wizard.v.cop.s", {name: row.detail})', SCRIPT)
        self.assertIn("row.detail || t(\"wizard.v.ok\")", SCRIPT)
        self.assertIn("signed in as", TEXTS["en"]["wizard.v.cop.s"])
        self.assertEqual(TEXTS["en"]["wizard.v.prog.s"], "{n} of {total} found")
        self.assertEqual(TEXTS["en"]["wizard.v.repo.s"], "{n} repositories")

    def test_repository_lists_show_whole_rows_and_select_all_turns_into_select_none(self) -> None:  # w2 #27 #28
        self.assertIn("function snap(scroller)", SCRIPT)
        self.assertIn("snap(scroller)", SCRIPT.split("parts.repos")[1])
        self.assertIn("everyOn()", SCRIPT)
        self.assertEqual(TEXTS["en"]["wizard.r.none.all"], "Select none")
        self.assertTrue(TEXTS["zh"].get("wizard.r.none.all"))
        self.assertIn("scrollTop", SCRIPT.split("parts.repos")[1])  # a tick keeps the place in the list

    def test_the_programs_lead_sentence_has_no_path_jargon(self) -> None:  # w2 #30
        for code in ("en", "zh"):
            self.assertNotIn("PATH", TEXTS[code]["wizard.p.sub"])
        self.assertIn("where it was found", TEXTS["en"]["wizard.p.sub"])

    def test_the_fake_download_moves_over_time(self) -> None:  # w2 #5, demo only
        fake = SCRIPT.split("const ready = () =>")[1].split("const setup = {")[0]
        self.assertIn("Date.now() - F.jobAt", fake)
        self.assertNotIn("downloaded_mb: 312", fake)


if __name__ == "__main__":
    unittest.main()
