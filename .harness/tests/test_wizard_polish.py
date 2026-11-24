"""1.8.32: the setup wizard's pages after the first new-colleague walk: rules that can be read in the page script, the sheet and the texts."""
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
NEW = ("wizard.job.tip", "wizard.c.st.restart", "wizard.c.st.ok", "wizard.c.st.prep", "wizard.v.title.check", "wizard.r.nomatch", "wizard.y.lang.hint.save")


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

    # --- walkthrough 2 (1.8.32) ---------------------------------------------------------------------------------------------------------------------------------------

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

    # ---- 1.8.34: how the wizard moves (spec W1-W10, E6); everything goes through motion.js and robot.js
    def test_the_shell_is_built_once_and_a_turn_changes_the_page_only(self) -> None:  # W1 W4
        self.assertIn("function buildShell(root)", SCRIPT)
        start = SCRIPT.split("  function start() {")[1]
        self.assertLess(start.index("buildShell(root)"), start.index("load().then("))  # the top line, bar and robot are there before the data is read
        render = SCRIPT.split("  function render() {")[1].split("  // W2:")[0]
        self.assertNotIn("put(root, el(\"div\", \"wz-top\"", render)  # no page rebuilds the whole frame
        self.assertNotIn("wz-bot", SCRIPT + SHEET)  # the robot is drawn by robot.js only

    def test_a_turn_is_two_steps_that_never_overlap(self) -> None:  # W4, round 2: the old page is gone first; the new page, foot, count and bar change together after it
        render = SCRIPT.split("  function render() {")[1].split("  // W2:")[0]
        self.assertIn("ms: 100, ease: MOTION.OUT", render)  # the old page leaves in 100 ms
        self.assertIn("ms: 180", render)  # the new one comes in over 180 ms
        self.assertLess(render.index("leaves()"), render.index("MOTION.glide(shell.foot, change)"))  # the swap waits for the old page
        swap = render.split("const change = () => {")[1].split("    };")[0]
        for part in ("old.replaceWith(content)", "shell.count.textContent", "drawFoot()"):
            self.assertIn(part, swap)  # one moment: page, count, foot
        self.assertIn("paintBar(final)", render.split("MOTION.glide(shell.foot, change)")[1])  # and the bar, at the same moment
        self.assertNotIn("MOTION.turn", render)  # no copy of the old page stays on screen while the new one is drawn
        self.assertNotIn("ghostOf", SCRIPT)
        self.assertIn("flight.then(leaves)", render)  # W6: pages skipped: the head lands first, then the page turns
        self.assertLess(render.index("shell.body.scrollTop = 0"), render.index("old.replaceWith(content)"))  # nothing forces a layout after the swap

    def test_the_robot_is_the_shells_and_moves_with_the_bar(self) -> None:  # W2 W3 W6
        self.assertIn("ROBOT.svg({glow: true})", SCRIPT)
        self.assertIn("ROBOT.svg({head: true})", SCRIPT)
        for kind in ('"hop"', '"cheer"'):
            self.assertIn("ROBOT.act(", SCRIPT)
            self.assertIn(kind, SCRIPT)
        self.assertIn("MOTION.MS.micro", SCRIPT.split("async function walk")[1].split("// A copy")[0])  # several cells: 120 ms each
        self.assertIn("arrived(i)", SCRIPT)  # the bar ticks a cell as the head reaches it
        self.assertIn("const barState = (i, idx)", SCRIPT)
        self.assertRegex(SHEET, r"\.wz-mate\{[^}]*pointer-events:none")  # the robot never blocks a button
        self.assertIn(".wz-slot{", SHEET)
        welcome = SCRIPT.split("parts.welcome = function")[1].split("parts.you =")[0]
        self.assertNotIn("ROBOT.svg", welcome)  # the welcome page keeps a slot; the shell's robot stands in it

    def test_a_step_done_hops_and_the_signed_in_card_stays(self) -> None:  # W7
        self.assertIn("HOLD = 1500", SCRIPT)
        self.assertGreaterEqual(int(re.search(r"const HOLD = (\d+)", SCRIPT).group(1)), 900)
        copilot = SCRIPT.split("parts.copilot = function")[1].split("parts.kb =")[0]
        self.assertIn("hopHead()", copilot)
        self.assertIn("}, HOLD);", copilot)
        programs = SCRIPT.split("parts.programs = function")[1].split("parts.copilot =")[0]
        self.assertIn("hopHead()", programs)
        self.assertIn("ROBOT.act(svg, \"hop\")", SCRIPT)

    def test_a_burst_of_presses_moves_one_page_and_the_main_button_stays_one_node(self) -> None:  # W8
        self.assertIn("MOTION.guard(", SCRIPT)
        self.assertIn("if (!turning && !busy) pressed(go)", SCRIPT)
        foot = SCRIPT.split("  function drawFoot() {")[1].split("\n  }\n")[0]
        self.assertIn("shell.mainBtn", foot)  # the same node, so off to on is a fade
        self.assertNotIn("put(shell.footRow", foot)
        self.assertRegex(SHEET, r"\.wz \.wz-btn:active[^{]*\{transform:scale\(\.97\)\}")
        self.assertRegex(SHEET, r"opacity var\(--m-show\)")  # off and on: 200 ms
        self.assertIn("transform var(--m-micro)", SHEET)  # a press: 120 ms

    def test_the_bar_fills_to_the_end_and_nothing_moves_in_lite_or_reduced_motion(self) -> None:  # W5, GOAL 11
        self.assertIn(".wz-bars i.cur b.f{transform:scaleX(1)}", SHEET)
        self.assertNotIn("--part", SHEET + SCRIPT)  # no half-filled part
        self.assertIn("transition:transform var(--m-page) var(--m-in)", SHEET)
        self.assertIn("html.lite .wz-bars b", SHEET)
        self.assertIn("@media (prefers-reduced-motion:reduce){", SHEET.split("html.lite .wz .wz-btn")[1])
        for token in ("left", "top", "width", "height"):
            self.assertNotRegex(SHEET.split(".wz-bars b{")[1].split("}")[0], r"transition:[^;]*\b" + token + r"\b")  # only transform and opacity move

    def test_confirm_cheers_and_leaves_through_the_veil_to_the_enter_screen(self) -> None:  # W9 W10
        confirm = SCRIPT.split("const confirm = () =>")[1].split("const lacking")[0]
        self.assertIn("return toEnter()", confirm)
        enter = SCRIPT.split("function toEnter() {")[1].split("  // The foot.")[0]
        self.assertIn('"cheer"', enter)
        self.assertIn('MOTION.mark("from-wizard")', enter)
        self.assertIn('{cls: "enter-bg"}', enter)  # the Enter screen's backdrop, light or dark (motion.css)
        self.assertIn("ms: 120", enter)  # the page is gone in 120 ms, when the veil starts

    def test_a_language_saved_in_you_loads_the_page_again_through_the_veil_with_three_dots(self) -> None:  # E6
        you = SCRIPT.split("parts.you = function")[1].split("parts.programs =")[0]
        self.assertIn("MOTION.leave(again, {content: thinking()})", you)
        self.assertIn("holding = !FAKE && M.lang !== document.documentElement.lang", you)  # serve.js would reload at once otherwise
        self.assertIn("SERVE.stay(() => holding)", SCRIPT)
        self.assertEqual(SCRIPT.split("function thinking() {")[1].split("  }\n")[0].count('h("i", null)'), 3)


    def test_the_bare_copilot_page_has_a_status_line_and_two_actions(self) -> None:  # 1.8.35: built from the copilot check; Sign out is Settings' own, Start Copilot again only for a failed or stuck host
        status = SCRIPT[SCRIPT.index("function copilotStatus"):SCRIPT.index("parts.copilot = ")]
        for field in ("line.gh_version", "line.host_version", "line.host_seconds", "line.gh", "line.n", "host.percent", "host.seconds"):
            self.assertIn(field, status)
        self.assertIn('why === "host-failed"', status)
        self.assertIn('why === "host-starting"', status)
        self.assertIn("Math.max(HOST_SLOW, 2 * (Number(line.host_last) || 0))", SCRIPT)  # a slow computer waits twice its last start, 90 s at least
        card = SCRIPT[SCRIPT.index("function statusCard"):SCRIPT.index("function paint()")]
        self.assertIn("SETTINGS.signOut(tick)", card)
        self.assertIn("if (st.restart)", card)
        self.assertIn('wizard.c.st.restart', card)
        self.assertIn("MOTION.appear(again", card)
        self.assertIn('api.host({do: "restart"})', SCRIPT)
        self.assertIn("opts.bare && !ONLY", SCRIPT)
        settings = (WEB / "settings.js").read_text(encoding="utf-8")
        self.assertRegex(settings, r"const signOut = \(done\) => signOutAsk\(")
        self.assertRegex(settings, r"return \{open, signOut,")


if __name__ == "__main__":
    unittest.main()


class ProgramIconsTest(unittest.TestCase):
    """1.8.34: each program of the wizard's rows shows its own logo, drawn in programicons.js; every page that loads wizard.js loads it first."""

    def test_five_programs_have_an_icon_and_the_file_loads_first(self):
        icons = (WEB / "programicons.js").read_text(encoding="utf-8")
        for pid in ("python", "git", "vscode", "gh", "harness"):
            self.assertRegex(icons, r"\b%s\(\) \{" % pid)
        self.assertIn("ROBOT.svg({head: true})", icons)
        self.assertIn("PROGRAM_ICONS.svg(id)", SCRIPT)
        html = (WEB.parent / "taskhtml.py").read_text(encoding="utf-8")
        lists = re.findall(r"\[[^\[\]]*\"wizard\.js\"[^\[\]]*\]", html)
        self.assertGreaterEqual(len(lists), 4)
        for one in lists:
            self.assertLess(one.index('"programicons.js"'), one.index('"wizard.js"'))
            if '"robot.js"' in one:
                self.assertLess(one.index('"robot.js"'), one.index('"programicons.js"'))


class SettingsGroupsTest(unittest.TestCase):
    """1.8.34: Settings' left list sits under three headings; every section keeps its id; the Skill prefix field is gone from Advanced."""

    def test_groups_cover_every_section_once_and_prefix_field_is_gone(self):
        code = (WEB / "settings.js").read_text(encoding="utf-8")
        groups = re.search(r"const GROUPS = (\[.*\]);", code).group(1)
        ids = re.findall(r'"([a-z]+)"', re.sub(r'"settings\.g\.[a-z]+"', "", groups))
        sections = re.search(r"const SECTIONS = \[(.*?)\]", code).group(1)
        self.assertEqual(sorted(ids + ["adv"]), sorted(re.findall(r'"([a-z]+)"', sections)))  # Advanced stands alone, under no heading
        self.assertNotIn('"network"', sections)  # Network is the first part of Advanced; `network` and `local` are aliases of it
        self.assertIn('local: "adv", network: "adv"', code)
        self.assertEqual(len(ids), len(set(ids)))
        for lang in ("en", "zh"):
            texts = json.loads((Path(taskhtml.__file__).resolve().parents[2] / "core" / f"messages.{lang}.json").read_text(encoding="utf-8"))
            for key in ("harness", "company"):
                self.assertTrue(texts["settings.g." + key])
            self.assertNotIn("setup.prefix", texts)
        self.assertNotIn("setup.prefix", code)

class SettingsLoadingTest(unittest.TestCase):
    """1.8.41: a section of Settings never stays grey. It waits only for what it shows, every read has a time limit, and a slow section that was switched to still lands."""

    def test_a_slow_section_lands_and_reads_only_what_it_needs(self):
        code = (WEB / "settings.js").read_text(encoding="utf-8")
        lines = [row for row in code.splitlines() if "leaveBars().then(land)" in row]
        self.assertTrue(lines)
        for row in lines:  # since 1.8.33 the `else` sat inside the comment of the line above: a section that took more than 120 ms stayed grey
            self.assertNotIn("//", row.split("leaveBars().then(land)")[0])
        self.assertIn("WIZARD.prepare(id)", code)
        self.assertIn('t("wizard.p.again")', code)  # a read that failed or was late: the reason and Try again
        needs = re.search(r"const NEEDS = \{(.*?)\};", SCRIPT).group(1)
        self.assertIn('programs: ["progs"]', needs)
        self.assertIn('copilot: ["ready"]', needs)
        self.assertNotIn("scan", re.sub(r'repos: \[[^\]]*\]', "", needs))  # only Code repositories waits for the scan of the repository folders
        self.assertIn("needs ? api.poll(step) : api.setup(step)", SCRIPT)  # api.poll has a time limit; the wizard's own start keeps its reads as they were


class InlineCodeTest(unittest.TestCase):
    """1.8.41: `code` in what the agent wrote is a violet chip in Live, Rounds and every document, in both themes; a code block keeps its own colours. The grey chip of 1.8.32 could not be seen on a work screen."""

    def test_inline_code_is_a_violet_chip_and_a_block_is_not(self):
        tokens = (WEB / "tokens.css").read_text(encoding="utf-8")
        for theme in (r':root,html\[data-theme="light"\]\{', r'html\[data-theme="dark"\][^{]*\{'):
            block = re.search(theme + r"(.*?)\n\}", tokens, re.S).group(1)
            for name in ("--code-ink:", "--code-bg:", "--code-line:"):
                self.assertIn(name, block)
        for sheet, chip, plain in (("live.css", ".tx.md code{", ".tx.md pre code{"), ("ui.css", "article.md code{", "article.md pre code{"), ("page.css", "article.md code{", "pre.code code{")):
            text = (WEB / sheet).read_text(encoding="utf-8")
            rule = text[text.index(chip):].split("}", 1)[0]
            for part in ("color:var(--code-ink)", "background:var(--code-bg)", "border:1px solid var(--code-line)"):
                self.assertIn(part, rule, sheet)
            reset = text[text.index(plain):].split("}", 1)[0]
            self.assertIn("color:inherit", reset, sheet)
            self.assertIn("background:none", reset, sheet)
