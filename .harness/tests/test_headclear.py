"""1.8.25: the page header keeps clear of the two pills fixed at the top right (the search pill and the greeting pill of stop.js).
stop.js runs in node with a fake page: the pills and the headers have fixed boxes, the test reads the padding the header gets."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401 - puts the engine on the path

WEB = Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "web"
NODE = shutil.which("node")

PAGE = r"""
const fs = require("fs"), assert = require("assert");
let width = 1300;
class Box {
  constructor(tag, attrs) { this.tag = tag; this.attrs = attrs || {}; this.children = []; this.style = {setProperty() {}}; this.hidden = Boolean(this.attrs.hidden); this.rect = {left: 0, right: 0, top: 0, bottom: 0}; this.pad = 20; }
  get offsetWidth() { return this.rect.right - this.rect.left; }
  getBoundingClientRect() { return this.rect; }
  setAttribute(k, v) { this.attrs[k] = v; } append(...kids) { this.children.push(...kids); } addEventListener() {}
  get classList() { return {add() {}, toggle() {}, contains: () => false}; }
}
const svg = () => new Box("svg");
const SEARCH = new Box("button"), BODY = new Box("body"), ROOT = new Box("html");
const heads = [];
const document = {body: BODY, documentElement: ROOT, readyState: "complete", createElementNS: svg, addEventListener() {},
  querySelector: (sel) => (sel === ".sh-pill" ? SEARCH : null),
  querySelectorAll: (sel) => (sel === ".lb-top,.tk-head" ? heads : [])};
const getComputedStyle = (node) => ({paddingRight: node.pad + "px"});
let frames = [];
const requestAnimationFrame = (f) => frames.push(f);
const run = () => { const now = frames; frames = []; now.forEach((f) => f()); };
const observers = [];
class ResizeObserver { constructor(f) { this.f = f; observers.push(this); } observe() {} }
const window = {ResizeObserver, addEventListener() {}};
const SERVE = {ready: new Promise(() => {}), call() {}};
const DATA = {serve: {user: "Ada"}};
const t = (key) => key;
function h(tag, attrs, ...kids) { const n = new Box(tag, attrs); n.children = kids.flat(); return n; }
eval(fs.readFileSync(process.argv[2], "utf8") + "\n;globalThis.STOP_ = STOP;");
const ACCT = BODY.children.find((n) => String(n.attrs.class || "").startsWith("hd-acct"));
function layout(w) {  // the pills sit 16 px from the right edge, the search pill 8 px left of the greeting
  width = w;
  ACCT.rect = {left: w - 16 - 200, right: w - 16, top: 14, bottom: 48};
  SEARCH.rect = {left: w - 16 - 200 - 8 - 120, right: w - 16 - 200 - 8, top: 14, bottom: 48};
}
"""

CASES = r"""
const head = new Box("div"); heads.push(head);
// 1300 wide, the header runs to 1128 (main has a 152 px gutter): the pills start at 956, so the header is padded to 1128 - 956 + 10 = 182
layout(1300); head.rect = {left: 20, right: 1128, top: 30, bottom: 80}; observers.forEach((o) => o.f()); run();
assert.strictEqual(head.style.paddingRight, "182px");
// a wider window, a header far from the pills: its own padding stays
layout(2400); head.rect = {left: 600, right: 1800, top: 30, bottom: 80}; observers.forEach((o) => o.f()); run();
assert.strictEqual(head.style.paddingRight, "");
// a header below the pills (a banner above it) is not touched
layout(1300); head.rect = {left: 20, right: 1128, top: 60, bottom: 120}; observers.forEach((o) => o.f()); run();
assert.strictEqual(head.style.paddingRight, "");
// own padding larger than the need (a narrow window's rule) wins
layout(1300); head.rect = {left: 20, right: 960, top: 30, bottom: 80}; head.pad = 96; observers.forEach((o) => o.f()); run();
assert.strictEqual(head.style.paddingRight, "");
// the greeting pill hidden: only the search pill counts
head.pad = 20; layout(1300); ACCT.hidden = true; SEARCH.rect = {left: 1300 - 16 - 120, right: 1284, top: 14, bottom: 48}; head.rect = {left: 20, right: 1250, top: 30, bottom: 80};
observers.forEach((o) => o.f()); run();
assert.strictEqual(head.style.paddingRight, (1250 - 1164 + 10) + "px");
// many resizes in one frame: one measure
let reads = 0; const real = head.getBoundingClientRect.bind(head); head.getBoundingClientRect = () => { reads++; return real(); };
for (let i = 0; i < 5; i++) observers.forEach((o) => o.f());
run();
assert.strictEqual(reads, 1);
console.log("ok");
"""


@unittest.skipUnless(NODE, "node is not installed")
class HeaderClearTests(unittest.TestCase):
    def test_the_header_is_padded_up_to_the_leftmost_pill_and_only_when_it_would_run_under(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "case.js"
            script.write_text(PAGE + CASES, encoding="utf-8")
            done = subprocess.run([NODE, str(script), str(WEB / "stop.js")], capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr or done.stdout)
            self.assertIn("ok", done.stdout)


if __name__ == "__main__":
    unittest.main()
