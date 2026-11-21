"""A slow approval must not block the page (serve.js `act`, `settle`, the registry `running`; common.js `actionButton`).
serve.js runs in node with a small fake page: the buttons, the window and the clock are fakes, the server answers when the test says so."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401 - puts the engine on the path

WEB = Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "web"
NODE = shutil.which("node")

PRELUDE = r"""
const fs = require("fs"), assert = require("assert");
class Node_ {
  constructor(tag, text) { this.tag = tag; this.text = text; this.children = []; this.parent = null; this.attrs = {}; this.listeners = {}; this.set = new Set(); this.value = ""; this.checked = false; this.disabled = false; this.dataset = {}; this.hidden = false; }
  get classList() { const s = this.set; return {add: (c) => s.add(c), remove: (c) => s.delete(c), contains: (c) => s.has(c), toggle: (c) => (s.has(c) ? s.delete(c) : s.add(c))}; }
  get isConnected() { let n = this; while (n) { if (n === BODY) return true; n = n.parent; } return false; }
  get offsetParent() { return this.isConnected ? BODY : null; }
  get textContent() { return this.text !== undefined ? this.text : this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this.text = undefined; this.children = [{textContent: String(v), parent: this}]; }
  setAttribute(k, v) { this.attrs[k] = v; if (k === "data-label") this.dataset.label = v; if (k === "class") String(v).split(" ").filter(Boolean).forEach((c) => this.set.add(c)); if (k === "value") this.value = v; if (k === "type") this.type = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  append(...kids) { for (const k of kids) { if (k.parent) k.parent.children.splice(k.parent.children.indexOf(k), 1); k.parent = this; this.children.push(k); } }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  remove() { if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; }
  addEventListener(n, f) { (this.listeners[n] = this.listeners[n] || []).push(f); }
  removeEventListener() {}
  fire(n, e) { for (const f of this.listeners[n] || []) f(e || {}); }
  focus() {}
  get lastChild() { return this.children[this.children.length - 1] || null; }
  contains(o) { while (o) { if (o === this) return true; o = o.parent; } return false; }
  all(pred, out = []) { for (const c of this.children) { if (c instanceof Node_) { if (pred(c)) out.push(c); c.all(pred, out); } } return out; }
  querySelectorAll(sel) { const tags = sel.split(",").map((s) => s.trim().match(/^[a-z]+/)[0]); const noBox = sel.includes(":not([type=checkbox])"); return this.all((n) => tags.includes(n.tag) && !(noBox && n.type === "checkbox")); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const BODY = new Node_("body");
const document = {body: BODY, activeElement: null, addEventListener() {}, removeEventListener() {}, querySelector: () => null};
function h(tag, attrs, ...kids) {
  const n = new Node_(tag);
  for (const [k, v] of Object.entries(attrs || {})) { if (v === null || v === undefined || v === false) continue; n.setAttribute(k, v); }
  for (const c of kids.flat(Infinity)) { if (c === null || c === undefined || c === false) continue; n.append(c instanceof Node_ ? c : new Node_("#text", String(c))); }
  return n;
}
let now = 0; const timers = [];
const setTimeout_ = (f, ms) => { const t = {f, at: now + ms, on: true}; timers.push(t); return t; };
const clearTimeout_ = (t) => { if (t) t.on = false; };
const advance = (ms) => { const end = now + ms; for (;;) { const next = timers.filter((t) => t.on && t.at <= end).sort((a, b) => a.at - b.at)[0]; if (!next) break; now = next.at; next.on = false; next.f(); } now = end; };
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const acts = [];  // the pending POSTs to /api/act: {body, ok(data), no(message)}
const fetch_ = (path, opts) => {
  const body = JSON.parse(opts.body || "{}");
  if (path !== "/api/act") return Promise.resolve({ok: true, json: () => Promise.resolve({paired: true, started: "", now: ""})});
  return new Promise((resolve) => acts.push({body, ok: (data) => resolve({ok: true, json: () => Promise.resolve(data)}), no: (message) => resolve({ok: false, status: 409, json: () => Promise.resolve({error: message})})}));
};
const code = fs.readFileSync(process.argv[2], "utf8");
const make = new Function("DATA", "document", "window", "location", "history", "fetch", "Node", "h", "t", "plainWords", "isEnter", "copyCommand", "requestAnimationFrame", "setTimeout", "clearTimeout", "CHAT", "AUTORUN", "DOCK", "TERM",
  code + "\nreturn SERVE;");
const SERVE = make({serve: {actions: ["approve-plan", "confirm-req", "accept"]}}, document, {addEventListener() {}}, {hash: "", pathname: "/", reload() {}}, {replaceState() {}}, fetch_, Node_, h, (k) => k, (s) => String(s), () => false, () => {}, (f) => f(), setTimeout_, clearTimeout_, {}, {}, {}, {});
let refreshed = 0; SERVE.onChange(() => { refreshed++; });
const row = {name: "task-one"}, item = {action: "approve-plan"};
const button = () => h("button", {class: "act", "data-label": "Approve plan"}, "Approve plan");
const windows = () => BODY.children.filter((c) => c.set && c.set.has("shade"));
const field = () => windows()[0].all((n) => n.tag === "input" && n.set.has("code"))[0];
const press = (label) => windows()[0].all((n) => n.tag === "button" && n.textContent === label)[0];
const PREVIEW = {result: {screen: ["the plan"], ask: "type ABC"}};
async function open(btn) {  // press the button, answer the preview, the window is there
  SERVE.act(btn, row, item); await flush();
  const p = acts.shift(); assert.strictEqual(p.body.step, "preview"); p.ok(PREVIEW); await flush();
}
"""


class ActBehindTests(unittest.TestCase):
    def run_js(self, body: str) -> None:
        if not NODE:
            self.skipTest("node is not installed")
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "check.js"
            file.write_text(PRELUDE + "\n(async () => {\n" + body + "\n})().then(() => console.log('ok'), (e) => { console.error(e); process.exit(1); });\n", encoding="utf-8")
            done = subprocess.run([NODE, str(file), str(WEB / "serve.js")], capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertIn("ok", done.stdout)

    def test_the_preview_waits_on_its_button_and_never_holds_the_page(self) -> None:
        self.run_js(r"""
const b = button(); BODY.append(b);
SERVE.act(b, row, item); await flush();
assert.strictEqual(b.disabled, true); assert.strictEqual(b.textContent, "board.serve.working");
assert.strictEqual(SERVE.busy(), false);          // the page keeps refreshing
assert.strictEqual(SERVE.running("task-one", "approve-plan"), true);
assert.strictEqual(SERVE.running("task-two", "approve-plan"), false);
const again = button(); BODY.append(again); SERVE.act(again, row, item); await flush();
assert.strictEqual(acts.length, 1);               // a second press of the same task+action does nothing
// the page draws the button again: the new node says "working" too
const redrawn = button(); BODY.append(redrawn); assert.strictEqual(SERVE.running("task-one", "approve-plan", redrawn), true);
assert.strictEqual(redrawn.disabled, true); assert.strictEqual(redrawn.textContent, "board.serve.working");
acts.shift().ok(PREVIEW); await flush();
assert.strictEqual(windows().length, 1); assert.strictEqual(SERVE.running("task-one", "approve-plan"), false);
assert.strictEqual(b.disabled, false); assert.strictEqual(b.textContent, "Approve plan"); assert.strictEqual(redrawn.textContent, "Approve plan");
""")

    def test_a_slow_act_closes_the_window_after_700_ms_and_goes_on_behind_the_page(self) -> None:
        self.run_js(r"""
const b = button(); BODY.append(b); await open(b);
field().value = "ABC"; press("board.serve.confirm").fire("click"); await flush();
const send = acts.shift(); assert.strictEqual(send.body.step, "act"); assert.strictEqual(send.body.code, "ABC");  // the code goes with the act step, as ever
advance(690); assert.strictEqual(windows().length, 1); assert.strictEqual(SERVE.busy(), true);
advance(20);
assert.strictEqual(windows().length, 0); assert.strictEqual(SERVE.busy(), false); assert.strictEqual(BODY.classList.contains("has-dialog"), false);
assert.strictEqual(b.disabled, true); assert.strictEqual(b.textContent, "board.serve.working");
assert.strictEqual(SERVE.running("task-one", "approve-plan"), true);
SERVE.act(b, row, item); await flush(); assert.strictEqual(acts.length, 0);   // no second press while it runs
send.ok({done: true}); await flush();
assert.strictEqual(refreshed, 1); assert.strictEqual(b.disabled, false); assert.strictEqual(b.textContent, "Approve plan");
assert.strictEqual(SERVE.running("task-one", "approve-plan"), false);
""")

    def test_a_late_refusal_opens_the_window_again_with_the_typed_code_and_the_reason(self) -> None:
        self.run_js(r"""
const b = button(); BODY.append(b); await open(b);
field().value = "WRONG"; windows()[0].all((n) => n.tag === "input" && n.type === "checkbox")[0].checked = true;
press("board.serve.confirm").fire("click"); await flush();
const send = acts.shift(); advance(800); assert.strictEqual(windows().length, 0);
send.no("the code is not right"); await flush();
assert.strictEqual(windows().length, 1); assert.strictEqual(refreshed, 0);
assert.strictEqual(field().value, "WRONG");                                            // the typed code is still there
assert.ok(windows()[0].textContent.includes("the code is not right"));              // the reason
assert.ok(windows()[0].textContent.includes("the plan") && windows()[0].textContent.includes("type ABC"));   // the same text
assert.strictEqual(windows()[0].all((n) => n.tag === "input" && n.type === "checkbox")[0].checked, true);   // the tick as it was
assert.strictEqual(b.disabled, false); assert.strictEqual(b.textContent, "Approve plan");
assert.strictEqual(press("board.serve.confirm").disabled, false);
// and it can be sent again: a fast success closes the window and refreshes
field().value = "ABC"; press("board.serve.confirm").fire("click"); await flush();
acts.shift().ok({done: true}); await flush(); assert.strictEqual(windows().length, 0); assert.strictEqual(refreshed, 1);
""")

    def test_a_fast_answer_ends_as_it_always_did(self) -> None:
        self.run_js(r"""
const b = button(); BODY.append(b); await open(b);
field().value = "NOPE"; press("board.serve.confirm").fire("click"); await flush();
advance(300); acts.shift().no("not right"); await flush();
assert.strictEqual(windows().length, 1); assert.ok(windows()[0].textContent.includes("not right"));
assert.strictEqual(field().value, "NOPE"); assert.strictEqual(press("board.serve.confirm").disabled, false);
assert.strictEqual(b.disabled, false);            // the button never turned: the window carried the wait
field().value = "ABC"; press("board.serve.confirm").fire("click"); await flush();
advance(100); acts.shift().ok({done: true}); await flush();
assert.strictEqual(windows().length, 0); assert.strictEqual(refreshed, 1); assert.strictEqual(SERVE.busy(), false);
advance(2000); assert.strictEqual(windows().length, 0);   // the timer of the window is gone: nothing opens late
""")

    def test_accept_with_held_calls_goes_on_behind_after_the_second_yes(self) -> None:
        self.run_js(r"""
const b = button(); b.setAttribute("data-label", "Accept and close"); BODY.append(b);
SERVE.act(b, row, {action: "accept"}); await flush();
const p = acts.shift(); assert.strictEqual(p.body.step, "preview");
p.ok({result: {held: [{system: "ado", env: "dev", title: "a call", code: "C1", detail: ""}]}}); await flush();
assert.strictEqual(windows().length, 1); assert.strictEqual(b.disabled, false);
windows()[0].all((n) => n.tag === "button" && n.set.has("hot"))[0].fire("click"); await flush();
const send = acts.shift(); assert.strictEqual(send.body.void, true); assert.deepStrictEqual(send.body.voids, ["C1"]);
advance(800); assert.strictEqual(windows().length, 0); assert.strictEqual(SERVE.busy(), false); assert.strictEqual(b.disabled, true);
send.no("a call changed"); await flush();
assert.strictEqual(windows().length, 1); assert.ok(windows()[0].textContent.includes("a call changed")); assert.strictEqual(b.disabled, false);
""")

    def test_the_buttons_of_the_page_ask_the_registry(self) -> None:
        common = (WEB / "common.js").read_text(encoding="utf-8")
        self.assertIn("SERVE.running(row.name, item.action, button)", common)
        serve = (WEB / "serve.js").read_text(encoding="utf-8")
        self.assertNotIn("busy = true", serve.split("function act(")[1].split("function codeWindow")[0])  # the preview does not freeze the page
        self.assertIn("SERVE.running(item.task, \"accept\", button)", (WEB / "super.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
