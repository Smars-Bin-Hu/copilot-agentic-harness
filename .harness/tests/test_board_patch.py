"""The patch after the first hand test of the board (1.6.11): the refresh rhythm, the VS button, the "nullnull" bug of a board on disk, the health tag in the lobby, the Trace of subagents,
no confirmation code in a chat message, and the one name for the write-back (promote (write-back repo))."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import support  # noqa: F401 - the engine on sys.path, HARNESS_VSCODE_CLI=off
from support import HarnessTestCase

from core import config, copilot_events, logs, messages, redact
from modules.task import boardserve, chatlive, chatsend, setupjob, taskhtml, tasktrace, wallpaper
from modules.task import task as task_ops

ENGINE = Path(__file__).resolve().parents[1] / "engine"
WEB = ENGINE / "modules" / "task" / "web"
NODE = shutil.which("node")
CHROME = next((path for path in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", shutil.which("google-chrome") or "", shutil.which("chromium") or "") if path and Path(path).is_file()), "")


def run_node(script: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as folder:
        file = Path(folder) / "check.js"
        file.write_text(script, encoding="utf-8")
        return subprocess.run([NODE, str(file)], capture_output=True, text=True, check=False)


def between(source: str, start: str, end: str) -> str:
    return source[source.index(start): source.index(end)]


@unittest.skipUnless(NODE, "node is not installed")
class OneWaitOneNumberTests(unittest.TestCase):
    def test_the_step_that_waits_shows_the_wait_and_a_step_at_work_its_own_time(self) -> None:
        """Seen on the page: "waits for you 18 min 49 s" on the stage card and "waited for you 18 min 31 s" on the card of waits: one was the age of the step."""
        source = between((WEB / "status.js").read_text(encoding="utf-8"), "function stages(row, live)", "const dot = (kind, extra)")
        script = r"""
const assert = require("assert");
const t = (key) => key, finite = Number.isFinite;
let state = "waiting";
const stateOf = () => state;
""" + source + r"""
const row = {status: "open", waiting_from: "2026-11-01T10:00:18+00:00", waiting_why: "stopped", stages: {steps: [{id: "requirement", state: "now", since: "2026-11-01T09:59:58.000Z"}]}};
assert.strictEqual(stages(row, true).steps[0].since, Date.parse(row.waiting_from));
state = "working";
assert.strictEqual(stages(row, true).steps[0].since, Date.parse("2026-11-01T09:59:58.000Z"));
"""
        done = run_node(script)
        self.assertEqual(done.returncode, 0, done.stderr)


@unittest.skipUnless(NODE, "node is not installed")
class PairingLinkTests(unittest.TestCase):
    def test_a_link_pasted_into_a_tab_that_shows_the_board_is_read(self) -> None:
        """Only what follows the # changes then, so the page does not load again; the code stayed in the address bar and the page said "not paired"."""
        source = between((WEB / "serve.js").read_text(encoding="utf-8"), "const pairCode", "// A line that says whether this browser may approve")
        script = r"""
const assert = require("assert");
let hashchange = null, paired = false, reloaded = 0, posted = [], right = "good";
global.location = {hash: "", pathname: "/", reload() { reloaded++; }};
global.history = {replaceState() { location.hash = ""; }};
global.window = {addEventListener(name, fn) { if (name === "hashchange") hashchange = fn; }};
const showPaired = () => {}, note = (data) => data, failed = () => {};
const send = (path, body) => {
  posted.push(path);
  if (path === "/api/pair") { if (body.code !== right) return Promise.reject(new Error("wrong")); paired = true; right = ""; }
  return Promise.resolve({paired});
};
""" + source + r"""
ready.then(() => {
  assert.strictEqual(posted.includes("/api/pair"), false, "no code in the address: nothing to trade");
  location.hash = "#pair=used-up";
  hashchange();
  return new Promise((done) => setTimeout(done, 20));
}).then(() => {
  assert.strictEqual(location.hash, "", "the code leaves the address bar");
  assert.strictEqual(reloaded, 0, "a code that failed keeps the page and what it says");
  location.hash = "#pair=good";
  hashchange();
  return new Promise((done) => setTimeout(done, 20));
}).then(() => {
  assert.strictEqual(paired, true);
  assert.strictEqual(reloaded, 1, "paired: the page loads again, with its buttons");
  location.hash = "#files";
  hashchange();
  return new Promise((done) => setTimeout(done, 20));
}).then(() => assert.strictEqual(reloaded, 1, "any other hash is the page's own"));
"""
        done = run_node(script)
        self.assertEqual(done.returncode, 0, done.stderr)


@unittest.skipUnless(NODE, "node is not installed")
class RefreshRhythmTests(unittest.TestCase):
    def test_polling_waits_while_the_page_is_hidden_and_while_the_last_request_is_not_back(self) -> None:
        source = between((WEB / "common.js").read_text(encoding="utf-8"), "function pollEvery", "// What the task waits for")
        script = r"""
const assert = require("assert");
let timers = [], seen = [];
global.setInterval = (fn, ms) => { timers.push({fn, ms}); return timers.length; };
global.clearInterval = () => {};
global.t = (key) => key;
global.h = (tag, attrs, ...kids) => ({tag, attrs, kids});
global.document = {hidden: false, body: {prepend: () => {}}, handlers: [], addEventListener(name, fn) { this.handlers.push([name, fn]); }};
""" + source + r"""
let calls = 0, release = null;
pollEvery(3, () => { calls++; return new Promise((resolve) => { release = resolve; }); });
assert.strictEqual(timers[0].ms, 3000);
const tick = timers[0].fn;
tick(); assert.strictEqual(calls, 1);
tick(); assert.strictEqual(calls, 1, "the last request is not back: skipped");
release();
setImmediate(() => {
  tick(); assert.strictEqual(calls, 2, "back: asked again");
  release();
  setImmediate(() => {
    document.hidden = true;
    tick(); assert.strictEqual(calls, 2, "hidden: nothing is asked");
    document.hidden = false;
    document.handlers.find((item) => item[0] === "visibilitychange")[1]();
    assert.strictEqual(calls, 3, "shown again: asked at once");
  });
});
"""
        done = run_node(script)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_replace_children_is_never_handed_a_null(self) -> None:
        for path in sorted(WEB.glob("*.js")):
            source = path.read_text(encoding="utf-8")
            for found in re.finditer(r"\.replaceChildren\(", source):
                depth, at, quote, top = 1, found.end(), "", []
                while depth and at < len(source):
                    char = source[at]
                    if quote:
                        at += 1 if char == "\\" else 0
                        quote = "" if char == quote else quote
                    elif char in "\"'`":
                        quote = char
                    elif char in "([{":
                        depth += 1
                    elif char in ")]}":
                        depth -= 1
                    elif depth == 1:
                        top.append(char)
                    at += 1
                # the DOM writes a null argument as the word "null"; h() leaves it out, this call does not
                self.assertNotIn(": null", "".join(top), f"{path.name}: {source[found.start():found.start() + 90]}")

    def test_the_menu_of_a_row_is_not_cut_off_by_the_box_of_the_list(self) -> None:
        source = (WEB / "board.js").read_text(encoding="utf-8")
        self.assertIn('if (more.closest(".scroll")) { openMenu.classList.add("hung"); document.body.append(openMenu); hangMenu(); }', source)
        self.assertIn("else more.after(openMenu);", source)  # the lobby card keeps its menu, or the pointer would leave the card
        self.assertIn(".act-menu.hung{position:fixed", (WEB / "ui.css").read_text(encoding="utf-8"))

    def test_copy_command_opens_beside_the_menu(self) -> None:
        source = (WEB / "board.js").read_text(encoding="utf-8")
        css = (WEB / "ui.css").read_text(encoding="utf-8")
        self.assertIn('h("div", {class: "act-menu menu-copy", role: "menu", hidden: true})', source)
        self.assertIn('toggle.addEventListener("mouseenter", () => show(true));', source)
        self.assertIn("if (placeCopy) placeCopy();", source)  # it follows its menu when the page scrolls
        self.assertIn(".act-menu.menu-copy{position:fixed", css)  # a menu that hangs scrolls, and would cut off a box placed by `absolute`
        self.assertIn("text-overflow:ellipsis", css.split(".menu-copy .act{", 1)[1].split("}", 1)[0])  # a long task name stays on one line

    def test_a_menu_that_is_open_holds_the_poll_and_not_a_click(self) -> None:
        source = (WEB / "board.js").read_text(encoding="utf-8")
        refresh = between(source, "  function refresh(strict)", "  if (typeof SERVE !== \"undefined\") {\n    SERVE.start")
        self.assertRegex(refresh, r"if \(openMenu && strict === true\) \{ later = data; return; \}")
        self.assertIn("closeMenu(false);", refresh)  # a click's own refresh closes the menu
        close = re.search(r"const closeMenu = \(flush\) => \{.*\};", source)
        self.assertIsNotNone(close)
        self.assertIn("apply(data)", close.group(0))  # what waited is drawn when the menu closes


class RefreshSettingTests(HarnessTestCase):
    def test_the_policy_says_3_seconds_and_a_bad_value_falls_back_to_3(self) -> None:
        self.assertEqual(config.policy_or_empty(self.root, "task")["board"]["refresh_seconds"], 3)
        self.assertEqual(boardserve.settings(self.root)["refresh"], 3)
        for value in (None, 0, -2, 601, "5", 2.5, True):
            self.assertEqual(boardserve.refresh_seconds(value), 3, value)
        self.assertEqual(boardserve.refresh_seconds(7), 7)

    def test_the_board_page_carries_the_setting_and_the_task_page_keeps_10(self) -> None:
        board = boardserve.Board(self.root, False, 0, ["pause"], refresh=5)
        text = board.page()
        start = text.index('<script type="application/json" id="data">') + len('<script type="application/json" id="data">')
        self.assertEqual(json.loads(text[start:text.index("</script>", start)])["serve"]["refresh"], 5)
        self.assertEqual(boardserve.Board(self.root, False, 0, ["pause"]).refresh, 3)  # nothing said: 3
        self.assertEqual(boardserve.DESK_REFRESH, 10)

    def test_the_user_name_is_asked_once_while_the_user_files_do_not_change(self) -> None:
        """1.6.109: every page has the name, and git takes seconds to start on a slow computer. Before, a page waited on git once a minute."""
        board = boardserve.Board(self.root, False, 0, ["pause"])
        with mock.patch.object(boardserve.user, "who", return_value={"name": "Ann"}) as asked:
            self.assertEqual([board.user_name() for _ in range(3)], ["Ann"] * 3)
            self.assertEqual(asked.call_count, 1)
            mine = config.override_path(self.root, "user")
            mine.write_text(json.dumps({"name": "Bo"}), encoding="utf-8")  # the person set a name
            os.utime(mine, (1_900_000_000, 1_900_000_000))
            board.user_name()
            self.assertEqual(asked.call_count, 2)


@unittest.skipUnless(NODE, "node is not installed")
class VsButtonTests(unittest.TestCase):
    SCRIPT = r"""
const assert = require("assert");
global.t = (key) => key;
global.h = (tag, attrs, ...kids) => ({tag, attrs: attrs || {}, kids: kids.flat(Infinity).filter((kid) => kid !== null && kid !== undefined), listeners: {}, addEventListener(name, fn) { this.listeners[name] = fn; }});
global.document = {createElementNS: (ns, name) => ({ns, name, attrs: {}, kids: [], setAttribute(key, value) { this.attrs[key] = value; }, append(kid) { this.kids.push(kid); }})};
global.post = () => Promise.resolve({});
global.failed = () => {};
"""

    def run_cases(self, cases: str) -> None:
        source = between((WEB / "serve.js").read_text(encoding="utf-8"), "  const VS_LOGO", "  // Once per page")
        done = run_node(self.SCRIPT + source + cases)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_only_the_logo_is_drawn_and_only_a_missing_code_command_greys_it(self) -> None:
        self.run_cases(r"""
const grey = (chat) => vsButton(chat).attrs.disabled === "disabled";
assert.strictEqual(grey({bound: false, why: "none"}), false, "VS Code not connected: still pressable");
assert.strictEqual(grey({bound: false, why: "starting"}), false);
assert.strictEqual(grey({bound: false, why: "lost"}), false);
assert.strictEqual(grey({bound: false, why: "no-chat"}), false);
assert.strictEqual(vsButton({bound: false, why: "no-chat"}).attrs.class, "vs-btn no-chat", "VS Code is there, this task has no chat");
assert.strictEqual(vsButton({bound: false, why: "none"}).attrs.class, "vs-btn", "the link is down: that is another story");
assert.strictEqual(vsButton({bound: true}).attrs.class, "vs-btn");
assert.strictEqual(grey({bound: true}), false);
assert.strictEqual(grey(undefined), false);
assert.strictEqual(grey({bound: false, why: "no-cli"}), true, "no `code` command found");
assert.strictEqual(grey({bound: false, why: "off"}), true);
const button = vsButton({bound: false, why: "none"});
assert.strictEqual(button.kids.length, 1, "no text beside the logo");
assert.strictEqual(button.kids[0].name, "svg");
assert.ok(button.kids[0].kids[0].attrs.d.startsWith("M23.15"), "the VS Code logo, drawn here");
assert.strictEqual(button.attrs.title, "board.vs.open");
assert.strictEqual(button.attrs["aria-label"], "board.vs.open");
assert.strictEqual(vsButton({bound: false, why: "no-cli"}).attrs.title, "board.vs.why.no-cli");
""")

    def test_the_page_never_loads_the_logo_from_the_network(self) -> None:
        source = (WEB / "serve.js").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"https?://(?!www\.w3\.org/2000/svg)")
        self.assertNotIn("Switch to", source)
        for language in ("en", "zh"):
            table = json.loads((ENGINE / "core" / f"messages.{language}.json").read_text(encoding="utf-8"))
            self.assertNotIn("desk.chat.window", table)  # the words are the title now


@unittest.skipUnless(CHROME, "no Chrome to render the page")
class BoardOnDiskTests(HarnessTestCase):
    """N4 (1.6.11): `replaceChildren` writes a null as the word "null". A board file on disk has no New task button and no VS Code pill (their functions return null), so the top right read `nullnull`."""

    def test_the_top_right_of_a_board_file_has_no_stray_null(self) -> None:
        page = taskhtml.board_page([], "2026-10-31T10:00:00+00:00", 0)
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "board.html"
            file.write_text(page, encoding="utf-8")
            done = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=1500", "--dump-dom", file.as_uri()], capture_output=True, text=True, check=False, timeout=60)
        shift = re.search(r'<div class="shift">(.*?)</div>\s*<div class="lb-seg"', done.stdout, re.S)
        self.assertIsNotNone(shift, done.stdout[:300])
        self.assertNotIn("null", re.sub(r"<[^>]*>", "", shift.group(1)))
        self.assertNotIn("nullnull", done.stdout)

    def test_no_script_draws_a_nullable_part_with_replaceChildren_unfiltered(self) -> None:
        for name in ("board.js", "chat.js", "desk.js", "lobby.js", "serve.js", "task.js"):
            source = (WEB / name).read_text(encoding="utf-8")
            for found in re.finditer(r"\.replaceChildren\(([^\n]*)\)", source):
                call = found.group(1)
                if "filter(Boolean)" in call:
                    continue  # the parts that may be null are dropped first
                self.assertNotRegex(call, r"\b(newTask|vsPill|warnTag|subLine)\(\)", f"{name}: {call[:80]}")


@unittest.skipUnless(NODE, "node is not installed")
class LobbyWarnTests(unittest.TestCase):
    def test_a_robot_gets_the_health_tag_with_the_reasons_in_its_title(self) -> None:
        source = between((WEB / "lobby.js").read_text(encoding="utf-8"), "  function warnMark", "  function create")
        script = r"""
const assert = require("assert");
global.t = (key, values) => key + (values && values.n !== undefined ? ":" + values.n : "");
global.h = (tag, attrs, ...kids) => { const node = {tag, attrs: attrs || {}, kids, removed: false, title: ""}; node.remove = () => { node.removed = true; slot.nodes = slot.nodes.filter((item) => item !== node); }; return node; };
const slot = {nodes: [], querySelector(selector) { return this.nodes.find((node) => "." + node.attrs.class === selector) || null; }, append(node) { this.nodes.push(node); }};
""" + source + r"""
warnMark(slot, {warn: []});
assert.strictEqual(slot.nodes.length, 0, "no warning: no tag");
warnMark(slot, {warn: [{rule: "stuck", n: 12}, {rule: "context", n: 90}]});
assert.strictEqual(slot.nodes.length, 1);
assert.strictEqual(slot.nodes[0].title, "board.warn.stuck:12\nboard.warn.context:90");
assert.strictEqual(slot.nodes[0].kids[0], "⚠");
warnMark(slot, {warn: [{rule: "repeat", n: 4}]});
assert.strictEqual(slot.nodes.length, 1, "drawn again: the same tag, a new reason");
assert.strictEqual(slot.nodes[0].title, "board.warn.repeat:4");
warnMark(slot, {});
assert.strictEqual(slot.nodes.length, 0, "the warning is gone: the tag goes");
"""
        done = run_node(script)
        self.assertEqual(done.returncode, 0, done.stderr)


SESSION = "main-session-1"
AGENT = "5db10132-c1ac-432c-bc20-8f23d92ef108"
CREATED = "2026-10-31T00:00:00+00:00"


class SubagentTraceTests(HarnessTestCase):
    """Q14 (1.6.11): the Trace holds the calls of the subagents of the session, each with its source; the main session's Trace is what it was where there are none."""

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"COPILOT_HOME": self.env["COPILOT_HOME"]})
        patcher.start()
        self.addCleanup(patcher.stop)
        tasktrace._found.clear()
        self.data = {"session_id": SESSION, "surface": "vscode", "created_at": CREATED}

    def write_log(self, session: str, rows: List[Dict[str, Any]]) -> None:
        path = logs.session_log_path(self.root, "vscode", session)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for item in rows:
                handle.write(json.dumps({"surface": "vscode", "session_id": session, **item}) + "\n")

    def write_events(self, rows: List[Dict[str, Any]]) -> None:
        folder = Path(self.env["COPILOT_HOME"]) / "session-state" / SESSION
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "events.jsonl").open("a", encoding="utf-8") as handle:
            for item in rows:
                handle.write(json.dumps(item) + "\n")

    def started(self, agent: str, name: str, minute: int) -> Dict[str, Any]:
        return {"type": "subagent.started", "timestamp": f"2026-10-31T01:{minute:02d}:00.000Z", "agentId": agent, "data": {"agentName": name, "toolCallId": "x"}}

    def call(self, minute: int, tool: str, **more: Any) -> List[Dict[str, Any]]:
        stamp = f"2026-10-31T01:{minute:02d}:00+00:00"
        return [{"at": stamp, "event": "PreToolUse", "tool_name": tool, "tool_kind": "read", "decision": "none", **more},
                {"at": stamp.replace(":00+", ":01+"), "event": "PostToolUse", "tool_name": tool, "tool_kind": "read", "decision": "none"}]

    def test_the_calls_of_the_reviewer_and_the_mapper_are_merged_in_time_order_and_marked(self) -> None:
        mapper = "aaaaaaaa-1111-2222-3333-444444444444"
        self.write_log(SESSION, self.call(1, "Edit") + self.call(10, "Bash"))
        self.write_log(AGENT, self.call(5, "Read") + [{"at": "2026-10-31T01:06:00+00:00", "event": "PreToolUse", "tool_name": "Bash", "decision": "deny", "kind": "reviewer-write", "reason": "read only", "target": {"paths": [], "command": "rm x"}}])
        self.write_log(mapper, self.call(7, "Grep"))
        self.write_events([self.started(AGENT, "reviewer", 4), self.started(mapper, "mapper", 6)])
        found = tasktrace.of_task(self.root, self.data)
        self.assertEqual([(item.get("source", ""), item["tool"], item["kind"]) for item in found["entries"]],
                         [("", "Edit", "tool"), ("reviewer", "Read", "tool"), ("reviewer", "Bash", "gate"), ("mapper", "Grep", "tool"), ("", "Bash", "tool")])
        self.assertEqual(found["sources"], ["reviewer", "mapper"])
        self.assertEqual(found["cut"], 0)

    def test_the_merged_trace_is_bounded_and_counts_what_it_leaves_out(self) -> None:
        self.write_log(SESSION, [row for minute in range(0, 59, 2) for row in self.call(minute, "Read")])
        self.write_log(AGENT, [row for minute in range(1, 59, 2) for row in self.call(minute, "Grep")])
        self.write_events([self.started(AGENT, "reviewer", 0)])
        with mock.patch.object(tasktrace, "SHOWN", 10):
            found = tasktrace.of_task(self.root, self.data)
        self.assertEqual(len(found["entries"]), 10)
        self.assertGreater(found["cut"], 0)
        self.assertEqual([item["at"] for item in found["entries"]], sorted(item["at"] for item in found["entries"]))
        self.assertEqual(found["entries"][-1]["at"], "2026-10-31T01:58:00+00:00")  # the newest are the ones kept

    def test_without_the_record_or_a_subagent_the_trace_is_the_main_session_alone(self) -> None:
        self.write_log(SESSION, self.call(1, "Edit"))
        self.write_log(AGENT, self.call(2, "Read"))  # a log nobody names
        found = tasktrace.of_task(self.root, self.data)
        self.assertEqual(found, {"entries": found["entries"], "cut": 0})
        self.assertEqual([item["tool"] for item in found["entries"]], ["Edit"])
        self.write_events([self.started(AGENT, "reviewer", 1)])
        self.assertEqual(len(tasktrace.of_task(self.root, self.data)["entries"]), 2)

    def test_a_policy_that_turns_the_record_off_leaves_the_main_session_alone(self) -> None:
        self.write_log(SESSION, self.call(1, "Edit"))
        self.write_log(AGENT, self.call(2, "Read"))
        self.write_events([self.started(AGENT, "reviewer", 1)])
        with mock.patch.object(config, "policy_or_empty", return_value={"report": {"copilot_events": False}}):
            self.assertEqual([item["tool"] for item in tasktrace.of_task(self.root, self.data)["entries"]], ["Edit"])

    def test_a_subagent_before_the_task_began_is_left_out_and_a_bad_line_is_skipped(self) -> None:
        self.write_log(AGENT, self.call(2, "Read"))
        folder = Path(self.env["COPILOT_HOME"]) / "session-state" / SESSION
        folder.mkdir(parents=True, exist_ok=True)
        old = dict(self.started(AGENT, "reviewer", 1), timestamp="2026-10-30T01:00:00.000Z")
        (folder / "events.jsonl").write_text(json.dumps(old) + "\n" + '{"type": "subagent.started" broken\n', encoding="utf-8")
        self.assertEqual(tasktrace.of_task(self.root, self.data), {"entries": [], "cut": 0})

    def test_the_subagent_scan_is_cached_until_the_record_changes_and_reads_only_its_tail(self) -> None:
        self.write_events([self.started(AGENT, "reviewer", 1)])
        self.assertEqual(len(tasktrace.subagents(self.root, SESSION, 0.0)), 1)
        with mock.patch("modules.task.tasktrace.json.loads", side_effect=AssertionError("parsed again")):
            self.assertEqual(len(tasktrace.subagents(self.root, SESSION, 0.0)), 1)  # same size, same time: from the cache
        path = Path(self.env["COPILOT_HOME"]) / "session-state" / SESSION / "events.jsonl"
        filler = json.dumps({"type": "tool.execution_start", "timestamp": "2026-10-31T02:00:00.000Z", "data": {"x": "y" * 200}}) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(filler * (tasktrace.EVENTS_TAIL // len(filler) + 10))
        self.assertEqual(tasktrace.subagents(self.root, SESSION, 0.0), [])  # the start line is now past the tail: a long session costs no more than the tail

    def test_the_trace_page_marks_the_source_in_both_languages(self) -> None:
        self.assertIn("item.source", (WEB / "desk.js").read_text(encoding="utf-8"))
        for language in ("en", "zh"):
            table = json.loads((ENGINE / "core" / f"messages.{language}.json").read_text(encoding="utf-8"))
            self.assertIn("{name}", table["desk.trace.source"])


class NoCodeInChatTests(unittest.TestCase):
    def test_no_template_has_a_code_and_the_old_names_are_gone(self) -> None:
        for name in ("NO_CODE", "CODE_OF_ACTION"):
            self.assertFalse(hasattr(chatsend, name), name)
        for why, text in {**chatsend.TEMPLATES, **chatsend.PLAIN}.items():
            self.assertNotIn("{", text, why)
            self.assertNotRegex(text, r"(?i)\bcode\b", why)
        self.assertFalse(hasattr(boardserve.Board, "codes"))
        board = boardserve.Board(Path(tempfile.gettempdir()), False, 0, [])
        self.assertFalse(hasattr(board, "codes"))

    def test_the_approval_still_asks_for_its_code_where_a_person_types_it(self) -> None:
        source = (WEB / "serve.js").read_text(encoding="utf-8")
        self.assertIn('t("board.serve.code")', source)
        self.assertIn("code: input.value.trim()", source)


class PromoteTermTests(unittest.TestCase):
    """Q19 (1.6.11): "write-back" and 回写 / 写回 become `promote (write-back repo)` where the term stands as a noun for the feature; plain `promote` elsewhere."""

    TERM = "promote (write-back repo)"

    def table(self, language: str) -> Dict[str, str]:
        return json.loads((ENGINE / "core" / f"messages.{language}.json").read_text(encoding="utf-8"))

    def test_no_message_keeps_the_old_name_in_either_language(self) -> None:
        for language in ("en", "zh"):
            for key, text in self.table(language).items():
                self.assertNotRegex(text, r"(?i)write-?backs?\b(?! repo)", f"{language} {key}")
                if key != "desk.drafts.hint":  # "never written back": the notes are copied nowhere (not the promote)
                    self.assertNotRegex(text, r"(?i)written back|write back", f"{language} {key}")
                self.assertNotRegex(text, "回写|写回(?!答)", f"{language} {key}")

    def test_the_full_term_stands_once_in_a_message_at_most_and_in_both_languages_at_the_same_places(self) -> None:
        en, zh = self.table("en"), self.table("zh")
        for key, text in en.items():
            self.assertLessEqual(text.lower().count(self.TERM), 1, key)
        for key, text in zh.items():
            self.assertLessEqual(text.lower().count(self.TERM), 1, key)
        both = {key for key in en if self.TERM in en[key].lower()}
        self.assertGreaterEqual(len(both), 15)
        self.assertEqual(sorted(key for key in both if self.TERM not in zh[key].lower()), [])

    def test_the_names_of_the_chat_templates_and_the_button(self) -> None:
        self.assertEqual(chatsend.TEMPLATES["go-promote"], "Promote (write-back repo) approved. Go on with the promote, then stop and report.")
        self.assertIn("promote (write-back repo)", chatsend.PLAIN["go-recover"])
        self.assertEqual(self.table("en")["board.action.approve-promote"], "approve promote")  # a button: plain
        self.assertEqual(self.table("en")["desk.go.recover"], chatsend.PLAIN["go-recover"])


class WalkThroughTests(unittest.TestCase):
    """What a walk through the board with a set of real tasks found (1.6.37)."""

    def test_a_call_the_hook_never_saw_end_is_not_running_when_it_was_denied_or_stopped(self) -> None:
        stamp = lambda second: f"2026-11-01T08:53:{second:02d}+00:00"  # noqa: E731
        node = {"rows": [{"kind": "tool", "at": stamp(1), "tool": "bash", "ok": None, "seconds": None}, {"kind": "tool", "at": stamp(20), "tool": "bash", "ok": None, "seconds": None},
                         {"kind": "tool", "at": stamp(40), "tool": "view", "ok": True, "seconds": 1.0}]}
        refused = [{"at": copilot_events.seconds(stamp(2)), "seconds": 0.5, "error": "The user rejected this tool call."}]
        tasktrace.settle(node, {"until": stamp(50), "refused": refused}, None)
        first, second, third = node["rows"]
        self.assertEqual((first["ok"], first["seconds"], first["error"]), (False, 0.5, "The user rejected this tool call."))
        self.assertTrue(tasktrace.problem(first))
        self.assertEqual((second["ok"], second.get("stopped")), (None, True))  # a newer prompt came: it will not end
        self.assertNotIn("stopped", third)

    def test_the_call_of_the_newest_prompt_runs_until_the_turn_was_stopped(self) -> None:
        at = "2026-11-01T08:55:36+00:00"
        running = {"rows": [{"kind": "tool", "at": at, "tool": "bash", "ok": None, "seconds": None}]}
        tasktrace.settle(running, {"until": "", "refused": []}, None)
        self.assertNotIn("stopped", running["rows"][0])
        tasktrace.settle(running, {"until": "", "refused": []}, copilot_events.seconds("2026-11-01T08:55:57+00:00"))
        self.assertTrue(running["rows"][0]["stopped"])
        self.assertIn('item.stopped ? tag(t("desk.trace.stopped"))', (WEB / "desk.js").read_text(encoding="utf-8"))

    def test_a_long_path_in_the_trace_is_a_path_and_a_key_in_it_is_still_masked(self) -> None:
        path = "/work/company/repositories/sales-repo/src/orders/daily/load.sql"
        row = {"at": "2026-11-01T08:00:00+00:00", "event": "PreToolUse", "tool_name": "Write", "decision": "deny", "target": {"paths": [path, "/a/" + "k" * 60 + "/b.sql"]}}
        self.assertEqual(tasktrace.build([row])["entries"][0]["paths"], [path, "/a/***/b.sql"])

    def test_the_same_words_are_not_shown_twice_on_a_line_of_the_live_tab(self) -> None:
        item = chatlive.tool_item({"toolName": "ask_user", "displayName": "Ask User", "intention": "Waiting for response", "status": "running"}, "i", True, None)
        self.assertEqual((item["say"], "target" in item), ("Waiting for response", False))
        shell = chatlive.tool_item({"toolName": "bash", "intention": "Sleep", "status": "running", "toolInput": json.dumps({"command": "sleep 5"})}, "j", True, None)
        self.assertEqual((shell["say"], shell["target"]), ("Sleep", "sleep 5"))

    def test_a_row_has_one_button_of_its_own_and_the_rest_are_in_the_menu(self) -> None:
        strip = between((WEB / "board.js").read_text(encoding="utf-8"), "function actionStrip(row)", "function actionCell(row)")
        self.assertIn("const first = items.find((item) => isHot(row, item) && !TALK.includes(item.action));", strip)  # steer and stop are drawn once, with the words to the agent (1.6.104)
        self.assertIn('item.action === "archive" || item === first', strip)

    def test_the_words_of_a_stop_and_of_a_dim_button_are_where_they_are_read(self) -> None:
        en = messages.table("en")
        self.assertIn("Stop on this page", en["desk.busy.note"])
        self.assertIn("here or in VS Code", en["desk.wait.cancelled"])
        self.assertIn(".tk-need-h{display:flex;flex-wrap:wrap", (WEB / "desk.css").read_text(encoding="utf-8"))  # on a phone the title wrapped letter by letter

    def test_an_empty_file_says_so_and_a_paused_task_has_its_way_back_on_the_card(self) -> None:
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn('if (!found.blocks.length) return h("div", {class: "empty-state"}, h("b", null, t("desk.doc.empty"))', desk)
        self.assertEqual(desk.count("resumeButton()"), 3)  # the function and the two cards
        self.assertIn('desk.waiting_why === "commit" ? "close"', desk)  # promoted and committed: closing is the next step

    def test_the_review_tab_has_its_own_line_and_the_review_button_its_own(self) -> None:
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn('const parts = [h("p", {class: "hint top"}, t("desk.review.hint"))];', desk[desk.index("function review()"):][:200])  # 1.6.35 renamed the button's words and took this line with them
        self.assertEqual(desk.count('t("desk.rv.hint")'), 2)  # the popover and the title of the button

    def test_a_new_task_has_no_choice_of_permissions(self) -> None:
        chat = (WEB / "chat.js").read_text(encoding="utf-8")
        self.assertNotIn("permChips", chat)
        self.assertNotIn("board.new.perm", chat)
        self.assertIn("allow all", messages.table("en")["board.new.fixed"])

    def test_the_bubble_of_a_wait_shows_the_command_or_the_question_and_outlives_a_redraw(self) -> None:
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn('h("div", {class: "tk-need-t"}, h("h2", null, idle ? idle.title : t("desk.actions.title")), askBubble())', desk)
        self.assertIn("if (!bubbleNode) bubbleNode = Status.card(", desk)  # one node: the 3-second redraw must not close the card
        self.assertIn('h("pre", {class: "send-preview"}, found.command || "-")', between(desk, "function askCard()", "function askBubble()"))
        self.assertIn("found.questions", between(desk, "function askCard()", "function askBubble()"))

    def test_the_same_diff_is_shown_once_and_a_different_plan_still_has_its_block(self) -> None:
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        part = between(desk, "function changes()", "function diffKinds(lines)")
        self.assertIn('found.lines.filter((line) => !line.startsWith("#"))', part)
        self.assertIn('if (!desk.commit) parts.push(h("p", {class: "sub"}, t("desk.changes.promote.same")));', part)  # written back: nothing is left to approve
        self.assertIn('else if (plan.lines.length) parts.push(h("h3", null, t("desk.changes.promote"))', part)

    def test_a_task_with_no_chat_says_so_on_the_icon_and_the_pill(self) -> None:
        serve, shell = (WEB / "serve.js").read_text(encoding="utf-8"), (WEB / "shell.js").read_text(encoding="utf-8")
        self.assertIn('alone ? " no-chat" : ""', serve)
        self.assertIn('alone ? "board.vscode.nochat"', shell)
        self.assertIn("SHELL.vsPill(desk.vscode, chat)", (WEB / "desk.js").read_text(encoding="utf-8"))

    def test_the_line_under_the_name_is_two_short_marks_and_the_cards_say_the_rest(self) -> None:
        self.assertIn("chat.model_name || shortModel(chat.model)", (WEB / "status.js").read_text(encoding="utf-8"))
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn("if (bound && chat.model) nodes.push(modelChip(chat, room));", desk)  # model, thinking and window: one chip
        self.assertIn('h("span", {class: "tk-think", "aria-hidden": "true"}, levels.map((item, index) => h("i", {class: index <= at ? "on" : null})))', desk)  # the level as a gauge
        self.assertIn('fact(t("desk.set.model"), full), level ? fact(t("desk.set.thinking"), level) : null, room ? fact(t("desk.fact.window")', desk)  # the card has the words
        self.assertIn('h("span", {class: "tk-meta"}, h("span", {class: "tk-when"}, icon(CLOCK, 13), changed)), factsCard', desk)  # the tier and the round are in the card only
        self.assertNotIn("infoItem(", desk)
        for key in ("desk.fact.tier.short", "desk.fact.round.short", "desk.info.window.tip", "desk.info.model"):
            self.assertNotIn(key, messages.table("en"), key)
        self.assertIn(".tk-model-name{max-width:16em;overflow:hidden;text-overflow:ellipsis", (WEB / "desk.css").read_text(encoding="utf-8"))  # a long model name does not push the line

    def test_the_task_settings_bar_opens_an_environment_with_one_click_and_the_row_marks_it(self) -> None:
        """1.7.6: the chips post `task allow` with no code; the line under the name has the open mark; both languages have the words."""
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn('SERVE.post("/api/act", {action: "task allow", task: desk.name, env: item.env, runner: chip.getAttribute("aria-pressed") === "true" ? "off" : "on", step: "act"})', desk)
        self.assertIn('disabled: listed && can ? null : "disabled"', desk)  # no system reaches it, or the board cannot act: not clickable
        self.assertIn('class: "chip env never"', desk)  # prod
        self.assertIn('ui.envs = slot("span", "tk-rv tk-env");', desk)  # a pill of the head, beside Independent review, not a field of the message bar
        self.assertIn('ui.envs.set(JSON.stringify([desk.allow, full.status]), () => envButton());', desk)
        status = (WEB / "status.js").read_text(encoding="utf-8")
        self.assertIn('open: (data, key, focus) => openMark(data.open_envs, key, focus)', status)
        self.assertIn(".st-s-open{width:88px", (WEB / "status.css").read_text(encoding="utf-8"))
        en, zh = messages.table("en"), messages.table("zh")
        for key in ("desk.set.open", "desk.set.open.none", "desk.set.open.never", "desk.set.open.note", "desk.set.open.off", "desk.set.open.cannot", "board.status.open", "board.status.open.word"):
            self.assertIn(key, en, key)
            self.assertIn(key, zh, key)

    def test_the_short_words_of_a_stopped_agent(self) -> None:
        en, zh = messages.table("en"), messages.table("zh")
        self.assertEqual((en["task.waiting.stopped"], zh["task.waiting.stopped"]), ("waits for you", "等你"))
        self.assertIn("agent stopped", en["desk.hint.answer"])  # the card on the task page still says what happened

    def test_the_time_waited_alone_does_not_draw_the_page_again(self) -> None:
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn('.replace(/"waited_s":[\\d.]+/g, "")', desk)
        self.assertIn('document.querySelectorAll(".tk-waited:not(.st-run)").forEach', desk)  # the number alone moves on; a live one moves with the clock of the page
        self.assertIn('"data-card-up": "1"', desk)  # the card opens above the bubble: the button is under it
        self.assertIn("!hold.anchor.dataset.cardUp", (WEB / "status.js").read_text(encoding="utf-8"))

    def test_a_task_that_went_away_says_so_and_the_stopped_note_is_over_the_header(self) -> None:
        self.assertIn('"gone": True', (ENGINE / "modules" / "task" / "boardserve.py").read_text(encoding="utf-8"))
        self.assertIn("error.data.gone", (WEB / "desk.js").read_text(encoding="utf-8"))
        self.assertIn(".stopped-note,.unpaired-note{z-index:120;background:var(--pop)", (WEB / "ui.css").read_text(encoding="utf-8"))

    def test_a_paired_browser_is_never_told_it_is_not_paired(self) -> None:
        serve = (WEB / "serve.js").read_text(encoding="utf-8")
        self.assertIn("const post = (path, body) => ready.then(() => send(path, body));", serve)  # a call of the page waits for the pairing
        self.assertIn('const already = send("/api/status", {})', serve)  # the pairing itself cannot wait for itself
        self.assertIn('if (paired) document.querySelector(".unpaired-note")?.remove();', serve)

    def test_a_task_with_no_chat_has_grey_chat_buttons_and_a_new_chat_button(self) -> None:
        common = (WEB / "common.js").read_text(encoding="utf-8")
        self.assertIn('DOCK.start("harness-my-task", t("board.go.words", {task: name}), null, name);', common)
        self.assertIn('chatGone(row) && ["", "no-chat", "no-session"].includes(row.chat.why || "")', common)
        self.assertIn('nodes.push(goOnButton(row.name))', (WEB / "board.js").read_text(encoding="utf-8"))
        self.assertIn('CHAT_ACTIONS.includes(item.action) && item.action !== "send"', common)
        self.assertIn("chat: desk.chat, ask: desk.ask", (WEB / "desk.js").read_text(encoding="utf-8"))
        self.assertIn("link.hidden = !data || !data.bound;", (WEB / "live.js").read_text(encoding="utf-8"))

    def test_close_with_open_steps_goes_to_the_agent_and_results_are_sent(self) -> None:
        serve = (WEB / "serve.js").read_text(encoding="utf-8")
        self.assertIn('DOCK.start("harness-my-task", text, null, row.name)', serve)
        self.assertIn('body: "/harness-my-task " + text', serve)
        self.assertIn('kind: "answer", lang: "", note: "", body: data.result.message', (WEB / "desk.js").read_text(encoding="utf-8"))

    def test_browse_lists_folders_with_no_new_program_and_says_what_it_cannot_read(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            (folder / "b").mkdir()
            (folder / "A").mkdir()
            (folder / ".hidden").mkdir()
            (folder / "kb.ZIP").write_text("x", encoding="utf-8")
            (folder / "note.txt").write_text("x", encoding="utf-8")
            with mock.patch.object(subprocess, "run", side_effect=AssertionError("no program may start")):
                self.assertEqual((setupjob.browse(name)["folders"], setupjob.browse(name)["zips"]), (["A", "b"], []))
                self.assertEqual(setupjob.browse(name, True)["zips"], ["kb.ZIP"])
            with mock.patch.object(setupjob.os, "scandir", side_effect=PermissionError):
                self.assertTrue(setupjob.browse(name)["error"])
            self.assertTrue(setupjob.browse("relative/path")["error"])
            with mock.patch.object(setupjob, "MAX_LISTED", 1):
                self.assertTrue(setupjob.browse(name)["cut"])

    def test_the_system_window_has_a_shown_owner_on_top_of_the_browser(self) -> None:
        for script in (wallpaper.WINDOWS_PICK, wallpaper.WINDOWS_FILE):
            self.assertLess(script.index("TopMost = $true"), script.index("$owner.Show();"))
            self.assertLess(script.index("$owner.Show();"), script.index("$box.ShowDialog($owner)"))

    def test_a_narrow_window_keeps_things_on_the_page(self) -> None:
        desk = (WEB / "desk.css").read_text(encoding="utf-8")
        self.assertIn(".rv-pop{right:auto;left:0}", desk)
        self.assertIn(".tk-head{flex-wrap:wrap;padding-right:96px}", desk)
        self.assertIn("@media (max-width:900px){.kpis{grid-template-columns:repeat(auto-fit,minmax(130px,1fr))}", (WEB / "ui.css").read_text(encoding="utf-8"))
        self.assertIn(".md{overflow-wrap:break-word}", (WEB / "page.css").read_text(encoding="utf-8"))

    def test_every_row_of_numbers_starts_at_the_same_place(self) -> None:
        ui = (WEB / "ui.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns:1.25fr 1fr 1fr 1fr 1fr", ui)  # five to a row, so the sixth number starts the next one
        self.assertIn(".kpi:nth-child(5n+1){border-left:0;padding-left:0}", ui)
        self.assertNotIn(".kpi:first-child", ui + (WEB / "wall.css").read_text(encoding="utf-8"))

    def test_the_review_prompt_is_not_what_a_person_is_told_to_write(self) -> None:
        en = messages.table("en")
        self.assertIn("Independent review on the task page", en["autorun.need.review"])
        for key in ("autorun.need.review", "autorun.screen.limits", "mdreport.review.on"):
            self.assertNotIn("[review]", en[key], key)
        self.assertIn('{name: st.task.split("/").pop()}', (WEB / "live.js").read_text(encoding="utf-8"))

    def test_two_strong_cards_each_say_what_they_are_about(self) -> None:
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn('"confirm-req": "task.waiting.req", "approve-plan": "task.waiting.plan"', desk)

    def test_a_promote_with_files_to_commit_is_not_closed_by_the_agent(self) -> None:
        other = {"repos": [{"name": "sales", "direct": False}], "branch": "feature/x"}
        kb = {"repos": [{"name": "kb", "direct": True, "path": "/nowhere", "base_ref": "main", "commit": "abc"}], "branch": ""}
        text = task_ops.promoted_text(other, {"patch": "x.patch"})
        self.assertIn(messages.text("promote.done.person"), text)
        self.assertNotIn(messages.text("promote.done.close"), text)
        self.assertIn(messages.text("promote.done.close"), task_ops.promoted_text(kb, {"patch": "x.patch"}))  # a knowledge base is committed by the write-back: nothing waits

    def test_a_long_path_in_what_the_agent_says_stays_and_a_key_with_slashes_goes(self) -> None:
        for path in (".workspace/sandbox/tasks/t-e2e-real-agent", "DEV/sales-repo/src/orders_load_daily_final_version_two"):
            self.assertEqual(redact.text("see " + path), "see " + path)
        for key in ("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "x/" + "f" * 40 + "/y", "a2V5a2V5a2V5a2V5a2V5/a2V5a2V5a2V5a2V5a2V5/a2V5", "abcdef0123456789abcdef0123456789abcdef01"):
            self.assertEqual(redact.text(key), redact.MASK, key)

    def test_the_rest_of_the_page_follows_when_the_chat_starts_or_stops_waiting(self) -> None:
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn("LIVE.onChange(() => {", desk)
        self.assertIn("if (changed && !SERVE.busy() && !typing()) pull();", desk)


class GuardrailWordsTests(unittest.TestCase):
    def test_the_gate_why_names_review_set_in_both_languages_and_the_pattern_already_had_it(self) -> None:
        gate = json.loads((ENGINE.parent / "policies" / "gate.json").read_text(encoding="utf-8"))
        found = [item for item in json.dumps(gate, ensure_ascii=False).split("}") if "task review set" in item]
        self.assertTrue(found)
        text = json.dumps(gate, ensure_ascii=False)
        self.assertIn("task review set", text)
        self.assertIn("(?:set|extend|waive|dismiss)", text)
        task = json.loads((ENGINE.parent / "policies" / "task.json").read_text(encoding="utf-8"))
        self.assertEqual(task["board"]["refresh_seconds"], 3)

    def test_the_eval_samples_of_the_gate_are_not_tracked(self) -> None:
        ignore = (ENGINE.parents[1] / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".harness/eval/fixtures/gate/", ignore)


if __name__ == "__main__":
    unittest.main()
