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

from core import config, logs, messages
from modules.task import boardserve, chatsend, taskhtml, tasktrace

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
