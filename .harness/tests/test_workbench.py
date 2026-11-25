"""The super agent workbench (workbench.js, workbench.css): the served board carries it, its words are in both languages, and the page files keep the repository's rules.
No browser here: the page's text is read. The layout is checked in the lab (superlab) with screenshots."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401 - puts the engine on the path

from modules.task import taskhtml

WEB = Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "web"
CORE = Path(__file__).resolve().parents[1] / "engine" / "core"
SERVE = {"actions": [], "refresh": 10}
NODE = shutil.which("node")


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class WorkbenchPageTests(unittest.TestCase):
    def test_the_served_board_has_the_workbench_after_super_and_before_the_board(self) -> None:
        page = taskhtml.board_page([], "2026-11-20T00:00:00+00:00", 0, SERVE)
        self.assertIn("const WORKBENCH = (function", page)
        self.assertLess(page.index("const SUPER = (function"), page.index("const WORKBENCH = (function"))
        self.assertLess(page.index("const WORKBENCH = (function"), page.index("WORKBENCH.create("))
        self.assertIn(".wb-root{", page)
        self.assertLess(page.index(".sa{position:relative"), page.index(".wb-root{"))  # the style of the view first, the style of its layer over it

    def test_a_linked_board_page_has_it_in_its_assets(self) -> None:
        page = taskhtml.board_page([], "2026-11-20T00:00:00+00:00", 0, SERVE, linked=True)
        names = re.findall(r'(?:href|src)="/asset/([0-9a-f]{20}\.(?:css|js))"', page)
        bodies = [taskhtml.asset_of(name)[0].decode("utf-8") for name in names]
        self.assertTrue(any("const WORKBENCH = (function" in body for body in bodies))
        self.assertTrue(any(".wb-root{" in body for body in bodies))

    def test_a_board_that_is_a_file_has_no_workbench(self) -> None:
        page = taskhtml.board_page([], "2026-11-20T00:00:00+00:00", 0, None)
        self.assertNotIn("const WORKBENCH = (function", page)
        self.assertNotIn(".wb-root{", page)

    def test_the_task_page_does_not_carry_it(self) -> None:
        page = taskhtml.desk_page({"name": "a", "task": "t"}, SERVE)
        self.assertNotIn("const WORKBENCH = (function", page)


class WorkbenchWordsTests(unittest.TestCase):
    def tables(self) -> list:
        return [json.loads((CORE / f"messages.{lang}.json").read_text(encoding="utf-8")) for lang in ("en", "zh")]

    def test_every_key_the_workbench_names_is_in_both_languages(self) -> None:
        used = {key for name in ("workbench.js", "wbpanels.js") for key in re.findall(r'"((?:super|board|stage|waits|desk)\.[a-z0-9.]+)"', source(name)) if not key.endswith(".")}
        self.assertGreater(len(used), 20)
        for key in sorted(used):
            for table in self.tables():
                self.assertIn(key, table, key)

    def test_the_workbench_words_have_the_same_places_in_both_languages_and_reach_the_page(self) -> None:
        en, zh = self.tables()
        keys = [key for key in en if key.startswith("super.wb.")]
        self.assertGreater(len(keys), 30)
        for key in keys:
            self.assertIn(key, zh, key)
            self.assertEqual(set(re.findall(r"\{(\w+)\}", en[key])), set(re.findall(r"\{(\w+)\}", zh[key])), key)
            self.assertTrue(key.startswith(taskhtml.TEXT_PREFIXES), key)  # the page gets the messages with these prefixes

    def test_the_page_files_have_no_chinese_and_no_hard_coded_english_label(self) -> None:
        for name in ("workbench.js", "workbench.css", "wbpanels.js", "wbpanels.css"):
            self.assertIsNone(re.search("[一-鿿]", source(name)), name)
            for word in ("written back", "write back"):
                self.assertNotIn(word, source(name))

    def test_the_task_pane_asks_for_the_embedded_page_and_keeps_its_frames(self) -> None:
        self.assertIn("TASKFRAMES.create(", source("workbench.js"))  # 1.8.36: the tabs and frames are taskframes.js, shared with the task window
        script = source("taskframes.js")
        self.assertIn('"?embed=1"', script)
        self.assertIn("MAX = 6", script)
        self.assertIn("tab.frame.hidden = !on", script)  # a loaded frame is hidden, not destroyed

    def test_the_task_link_is_read_only_from_a_task_page_address(self) -> None:
        script = source("workbench.js")
        self.assertIn(r"/^\/task\/([^/?#]+)(?:[?#].*)?$/", script)


class WorkbenchDeckTests(unittest.TestCase):
    """The command deck: the shell's own behaviour is read from the page text; the look is checked in the lab with screenshots."""

    def test_the_top_bar_has_only_the_way_out_the_name_the_battery_and_focus(self) -> None:
        script = source("workbench.js")
        for needle in ('class: "wb-back"', 'class: "wb-batt"', 'class: "wb-focus"', 'class: "wb-tools"'):
            self.assertIn(needle, script)
        for gone in ("wb-seg", "wb-tg", "modeBtns", "super.wb.side.left", "super.wb.mode.wb", "waitEl"):
            self.assertNotIn(gone, script)  # no View switch, no Left/Right panel toggles, no "N wait" text

    def test_the_board_chrome_is_hidden_under_the_lock_class_not_removed(self) -> None:
        style = source("workbench.css")
        rule = re.search(r"html\.wb-lock :is\(([^)]*)\)\{display:none!important\}", style)
        self.assertIsNotNone(rule)
        for name in (".sh-pill", ".hd-menu", ".dock-btn", ".hd-acct", ".term-toggle"):
            self.assertIn(name, rule.group(1))
        for gone in ("--wb-corner", "margin-right:64px", "right:80px"):
            self.assertNotIn(gone, style)  # the room kept for the board's buttons is gone

    def test_the_deck_is_always_dark_and_uses_no_blur(self) -> None:
        self.assertIn('html[data-theme="dark"],:where(.wb-root){', source("tokens.css"))  # the dark set also on the layer (no weight: the board's file pages carry tokens.css too)
        style = source("workbench.css")
        self.assertNotIn("backdrop-filter", style)
        self.assertIn(".wb-root::after{", style)
        self.assertIn(".wb-root.wb-down::after{", style)  # the lit edge, and its red form when VS Code is not linked
        self.assertIn("pointer-events:none", style.split(".wb-root::after{", 1)[1].split("}", 1)[0])

    def test_panels_fold_and_a_folded_side_is_a_rail(self) -> None:
        script, style = source("workbench.js"), source("workbench.css")
        for needle in ("function foldPanel", "wb-fold-btn", "wb-rail", 'store.set("fold"', 'SIDES = {l: ["q", "t"], r: ["d", "p"]}'):
            self.assertIn(needle, script)
        self.assertIn("--wb-lw:44px", style)
        self.assertIn(".wb-pn.wb-fold .wb-pb", style)

    def test_the_two_bars_resize_the_sides_and_keep_the_widths(self) -> None:
        script = source("workbench.js")
        for needle in ("setPointerCapture", '"pointermove"', '"dblclick"', 'store.set("widths"', "--wb-\" + side + \"wu"):
            self.assertIn(needle, script)
        self.assertIn("var(--wb-lwu,", source("workbench.css"))

    def test_minimize_leaves_the_mode_and_a_pill_brings_it_back(self) -> None:
        script = source("workbench.js")
        for needle in ("minimized = true", 'class: "wb-orb"', "options.open", "orb.hidden = !minimized", "SUPER.waiting(rowsOf())"):
            self.assertIn(needle, script)
        board = source("board.js")
        self.assertIn("open: () => setMode(\"super\")", board)
        self.assertIn("(workbench || superView).setVscode(", board)  # the layer hears of a VS Code that is down

    def test_the_battery_reads_super_js_and_the_popover_recharges_by_post(self) -> None:
        script = source("workbench.js")
        for needle in (".sa-cost .sa-cell", "MutationObserver(costChanged)", 'SERVE.post("/api/super/recharge", {amount: amountNow})', 'SERVE.call("/api/super/talk"', "RECHARGE = [25, 50]", "super.wb.batt.added", "super.wb.batt.today"):
            self.assertIn(needle, script)

    def test_the_bridge_gets_its_four_calls_and_its_container(self) -> None:
        script = source("workbench.js")
        self.assertIn("WBPANELS.create(Object.assign({rows: rowsOf, more: options.more}, bridgeCalls))", script)  # 1.8.40: `more`, the closed tasks the board does not list
        for call in ("pick(task)", "menu(task, x, y)", "closed(x, y)", "target()"):
            self.assertIn(call, script)
        for needle in ('"contextmenu"', ".sa-team .sa-mate[data-task]", ".sa-team .sa-closed", ".sa-team .sa-mate.on[data-task]", "if (panels2.bridge) bridge.append(panels2.bridge)", "bridge: mode === \"wb\""):
            self.assertIn(needle, script)
        style = source("workbench.css")
        self.assertIn(".wb-center .sa-team,.wb-center .sa-head,.wb-center .sa-pet{display:none!important}", style)

    def test_the_pet_of_super_js_is_replaced_by_a_stand_in_that_does_nothing(self) -> None:
        script = source("workbench.js")
        self.assertIn("return {create, taskOf, stillPet};", script)
        self.assertIn("(options.makePet || PET.create)(sv)", source("super.js"))
        self.assertIn("makePet: typeof WORKBENCH !== \"undefined\" ? WORKBENCH.stillPet : undefined", source("board.js"))
        self.assertIn("new Proxy(own", script)
        self.assertIn("held: () => true", script)  # review 1 of the deck: "held" keeps super.js from sending it to carry items (a new item shows at once) or to patrol
        self.assertIn("if (answer && answer.ok === false) popError = String(answer.reason", script)  # a refused recharge says why
        self.assertIn("extra + n > RECHARGE_MAX", script)
        self.assertNotIn("requestAnimationFrame", script)


class WorkbenchPanelsTests(unittest.TestCase):
    def test_the_panels_file_is_served_before_the_workbench_with_its_style(self) -> None:
        page = taskhtml.board_page([], "2026-11-20T00:00:00+00:00", 0, SERVE)
        self.assertIn("const WBPANELS = (function", page)
        self.assertLess(page.index("const WBPANELS = (function"), page.index("const WORKBENCH = (function"))
        self.assertIn(".wbp-av{", page)
        self.assertLess(page.index(".wb-root{"), page.index(".wbp-av{"))
        self.assertNotIn("const WBPANELS = (function", taskhtml.board_page([], "2026-11-20T00:00:00+00:00", 0, None))

    def test_the_panels_are_drawn_from_the_rows_and_ask_for_nothing(self) -> None:
        script = source("wbpanels.js")
        for needle in ("function treeNode", "function dataNode", "function sceneSVG", "function hoverCard", "function decorate", "function intro", "function idOf", "function paint",
                       "function bridgeGroups", "function placeOf", "function askBlock", "function fitOf", "function lookBlock", "function pipeBlock", "function timeBlock", "function spendBlock", "function openList", "function paintBridge"):
            self.assertIn(needle, script)
        for call in ("fetch(", "XMLHttpRequest", "EventSource", "WebSocket"):
            self.assertNotIn(call, script)  # no request of its own: the rows are the board's

    def test_a_panel_is_drawn_again_only_when_its_signature_changed(self) -> None:
        script = source("wbpanels.js")
        self.assertIn("if (sigs[key] === sig && node.firstChild) return;", script)

    def test_the_scene_and_the_entrance_stand_still_under_reduced_motion_and_lite(self) -> None:
        script, style = source("wbpanels.js"), source("wbpanels.css")
        self.assertIn('document.documentElement.classList.contains("lite")', script)
        self.assertIn("prefers-reduced-motion: reduce", script)
        self.assertIn("if (still()) return;", script)  # no entrance
        self.assertIn("html.lite .wbp-intro", style)
        self.assertIn("prefers-reduced-motion:reduce", style)

    def test_the_queue_item_finds_its_task_in_the_data_task_of_the_item(self) -> None:
        script = source("wbpanels.js")
        self.assertIn("node.dataset.task", script)
        self.assertIn('node.classList.contains("item")', script)

    def test_before_the_first_answer_the_view_does_not_say_nothing_waits_or_that_the_agent_is_gone(self) -> None:
        sup, bench = source("super.js"), source("workbench.js")
        self.assertIn("talk = null, heard = false,", sup)  # not heard yet is its own state
        self.assertIn("heard = true;", sup.split("function apply(")[1].split("function morning")[0])  # set by an answer of /api/super
        self.assertIn('!talk && heard ? "none" : ""', sup)  # the red bar only from a real answer, never from the initial null
        self.assertIn('const talkOff = () => (!talk ? (heard ? "none" : "") :', sup)  # the input stays enabled until then
        self.assertIn('heard ? "" : failed || t("board.enter.checking")', sup)  # a failed request shows as the failure, otherwise "Checking"
        self.assertIn("superView.note()", bench)
        self.assertIn("superView.note() || t(\"super.wb.queue.empty\")", bench)
        self.assertIn("superView.subscribe", bench)  # the list is drawn again when the first answer (or its failure) comes
        self.assertIn("unsubscribe()", bench)
        for name in ("en", "zh"):
            self.assertIn('"board.enter.checking"', (CORE / f"messages.{name}.json").read_text(encoding="utf-8"))

    def test_the_send_button_keeps_its_own_colours(self) -> None:
        self.assertIn(":where(.wb-root) button{font:inherit;color:inherit}", source("workbench.css"))

    def test_the_bridge_takes_its_options_and_flags_and_is_optional(self) -> None:
        script = source("wbpanels.js")
        for needle in ("options.pick", "options.menu", "options.closed", "options.target", "vis.bridge", "vis.down", "ResizeObserver", "contextmenu", "pointerdown", "data-wbp-more", "data-wbp-closed", "const DOTS = 12", "gate.tip"):
            self.assertIn(needle, script)
        self.assertIn("return {tree, data, scene, bridge, update,", script)
        self.assertIn("if (!down) for (const dot of dots)", script)  # no moving dot when VS Code is not linked
        self.assertIn("if (quiet)", script)  # a still dot under reduced motion and lite

    def test_what_is_not_sent_yet_is_never_made_up(self) -> None:
        script = source("wbpanels.js")
        self.assertIn("time.known !== true", script)  # a task without Copilot's record is not counted
        self.assertIn("row.agents.gate", script)
        self.assertIn("agents.gate", source("wbpanels.js"))
        self.assertNotIn("Math.random", script)

    def test_the_tree_and_the_data_say_what_they_hold_and_do_not_poll_for_it(self) -> None:
        script = source("wbpanels.js")
        self.assertIn("const TREE_FLAT = 12", script)
        self.assertIn("a folded group is not drawn", script)
        self.assertIn("row.sub", script)
        self.assertNotIn("setInterval(() => { refresh", script)
        self.assertEqual(script.count("setInterval("), 1)  # the one-second timer of the cells that run

    def test_the_new_style_has_the_bridge_the_list_and_the_blocks(self) -> None:
        style = source("wbpanels.css")
        for needle in (".wbp-bridge{", ".wbp-closed{", ".wbp-pop{", ".wbp-blk{", ".wbp-grp{", ".wbp-gate{", ".wbp-dim{", ".wbp-pipe{"):
            self.assertIn(needle, style)

    def test_every_identity_colour_has_a_light_and_a_dark_value(self) -> None:
        style = source("wbpanels.css")
        for number in range(8):
            self.assertEqual(len(re.findall(rf"--wbp-id{number}:", style)), 2, number)
            self.assertIn(f".wbp-i{number}{{--id:var(--wbp-id{number})}}", style)


@unittest.skipUnless(NODE, "node is not installed")
class WorkbenchPanelsLogicTests(unittest.TestCase):
    """The pure functions of the bridge, run in node with the page's globals stubbed."""

    def run_js(self, body: str) -> str:
        script = r"""
const fs = require("fs"), assert = require("assert");
const code = fs.readFileSync(process.argv[2], "utf8");
const make = new Function("window", "document", "TEXT", "t", "h", "stateOf", "shownName", "clock", code + "\nreturn WBPANELS;");
const W = make({matchMedia: null}, {documentElement: {classList: {contains: () => false}}}, {}, (k) => k, () => null, (row) => row.state, (row) => row.name, (s) => String(s));
""" + body
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "check.js"
            file.write_text(script, encoding="utf-8")
            done = subprocess.run([NODE, str(file), str(WEB / "wbpanels.js")], capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        return done.stdout

    def test_fifty_tasks_are_grouped_by_state_and_each_state_has_one_more_bubble(self) -> None:
        out = self.run_js(r"""
const items = [];
const add = (kind, count, extra) => { for (let i = 0; i < count; i++) items.push(Object.assign({name: kind + String(i).padStart(2, "0"), kind, subsN: 0, waited: 100 - i}, extra ? extra(i) : {})); };
add("wait", 20); add("work", 10, (i) => ({subsN: i >= 7 ? i - 6 : 0})); add("idle", 5); add("err", 5);
assert.strictEqual(W.fitOf(706, false).many, 17);
const plan = W.bridgeGroups(items, W.fitOf(706, false));
assert.ok(plan.grouped);
const by = Object.fromEntries(plan.groups.map((g) => [g.kind, g]));
assert.deepStrictEqual(plan.groups.map((g) => g.kind), ["err", "wait", "work", "idle"]);
assert.strictEqual(by.err.show.length, 3); assert.strictEqual(by.err.more, 2);
assert.strictEqual(by.work.show.length, 4); assert.strictEqual(by.work.more, 6);
assert.strictEqual(by.idle.show.length, 1); assert.strictEqual(by.idle.more, 4);
assert.strictEqual(by.wait.show.length, 5); assert.strictEqual(by.wait.more, 15);
assert.deepStrictEqual(by.work.show.slice(0, 3).map((i) => i.name), ["work09", "work08", "work07"]);  // the three with subagents first
assert.deepStrictEqual(by.wait.show.map((i) => i.name), ["wait00", "wait01", "wait02", "wait03", "wait04"]);  // the longest wait first
const slots = plan.groups.reduce((n, g) => n + g.show.length + (g.more ? 1 : 0), 0);
assert.ok(slots <= 17, "slots " + slots);
console.log("ok");
""")
        self.assertIn("ok", out)

    def test_few_tasks_are_not_grouped_by_count_and_a_narrow_bridge_still_shows_something_of_each_state(self) -> None:
        out = self.run_js(r"""
const few = [{name: "a", kind: "work", subsN: 0}, {name: "b", kind: "err"}, {name: "c", kind: "wait", waited: 5}];
const plan = W.bridgeGroups(few, W.fitOf(700, false));
assert.ok(!plan.grouped);
assert.deepStrictEqual(plan.groups.map((g) => g.kind + g.show.length + g.more), ["err10", "wait10", "work10"]);
const many = [];
for (const kind of ["wait", "work", "idle", "err"]) for (let i = 0; i < 9; i++) many.push({name: kind + i, kind, subsN: 0, waited: i});
const narrow = W.bridgeGroups(many, W.fitOf(380, false));
for (const g of narrow.groups) assert.ok(g.show.length >= 1, g.kind);
const total = narrow.groups.reduce((n, g) => n + g.show.length + (g.more ? 1 : 0), 0);
assert.ok(total <= Math.max(W.fitOf(380, false).many, 6), "total " + total);
const none = W.bridgeGroups([], W.fitOf(700, false));
assert.deepStrictEqual(none.groups, []);
console.log("ok");
""")
        self.assertIn("ok", out)

    def test_each_kind_of_task_has_its_own_lane_and_a_wait_its_decision(self) -> None:
        out = self.run_js(r"""
const P = (kind, now) => W.placeOf(kind, now);
assert.deepStrictEqual(P("dev", {id: "plan"}), {lane: "dev", step: "plan"});
assert.deepStrictEqual(P("kb", {id: "done"}), {lane: "dev", step: "writeback"}, "open at done: waits to be closed");
assert.deepStrictEqual(P("dev", {id: "byhand"}), {lane: "dev", step: "writeback"});
assert.deepStrictEqual(P("test", {id: "env", label: "ist"}), {lane: "test", step: "IST"});
assert.deepStrictEqual(P("test", {id: "guide"}), {lane: "test", step: "guide"});
for (const kind of ["rca", "design", "other"]) assert.deepStrictEqual(P(kind, {id: "doing"}), {lane: "simple", step: "doing"});
assert.deepStrictEqual(P("qa", undefined), {lane: "qa", step: "open"});
assert.deepStrictEqual(P("", undefined), {lane: "qa", step: "open"}, "no kind: the plainest lane");
const want = {asking: "answer", outbox: "call", req: "req", plan: "plan", promote: "promote", commit: "promote", recover: "promote", accept: "accept", stopped: "other", "": "other"};
for (const [why, key] of Object.entries(want)) assert.strictEqual(W.decisionOf(why), key, why);
console.log("ok");
""")
        self.assertIn("ok", out)


if __name__ == "__main__":
    unittest.main()
