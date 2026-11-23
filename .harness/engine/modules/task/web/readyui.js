// Shared by the Enter screen (enter.js) and the block of the board after Enter (readybar.js) (1.7.38, block B): where a fix of the readiness answer leads.
// A fix is what `core/readyitems.py` and `modules/task/ready.py` give each problem: {to, label, ...}.
//   setup   the Settings window at a section:      SETTINGS.open(sec), sec you | programs | copilot | kb (company) | packs | repos | connections | network | adv; `you` on a copy not set up yet is the wizard page (/setup)
//   tools   the Settings window at its section:    TOOLS.open(tab, done, part) -> SETTINGS.open: tab packs | connections | local (part network, mcp or programs)
//   kb      the knowledge base window:             DOCK.kbWindow(tab)
//   term    a command the Terminal window runs:    TERM.run(line)
//   sync    the company's copies: `company sync`, or with op prefix the company's word first (DOCK.syncCompany); the answer is a promise
//   copilot 1.8.x, the board's own agent host:     signin (gh's web sign-in, POST /api/gh), or a download page (`url`)
//   identities the main Windows account of the agent host, when several are saved (H6): the picker of servers.js
// Needs common.js (h, t), serve.js (SERVE). The other windows are used when the page has them.
"use strict";

const READY = (function () {
  function go(fix, hooks) {
    if (!fix || !fix.to) return;
    const given = hooks || {};
    if (fix.to === "setup") { if (typeof SETTINGS !== "undefined" && fix.sec !== "you") SETTINGS.open(fix.sec || "kb", {done: given.done}); else location.assign("/setup"); }  // `you`: a copy that is not set up goes to the wizard
    else if (fix.to === "tools" && typeof TOOLS !== "undefined") TOOLS.open(fix.tab, given.done, fix.part || undefined);  // the tab names are packs, connections and local; tools.js leads to Settings
    else if (fix.to === "kb" && typeof DOCK !== "undefined") DOCK.kbWindow(fix.tab);
    else if (fix.to === "term" && typeof TERM !== "undefined") TERM.run(fix.run);
    else if (fix.to === "sync" && typeof DOCK !== "undefined") return DOCK.syncCompany(fix.op).then(() => { if (given.done) given.done(); });  // an error goes to the caller: the button says it
    else if (fix.to === "copilot" && fix.kind === "signin") return SERVE.post("/api/gh", {do: "login"}).then(() => { if (given.done) given.done(); });  // 1.8.x: gh's web sign-in; the Enter screen shows its code
    else if (fix.to === "copilot" && fix.url) window.open(fix.url, "_blank", "noopener");  // GitHub's or VS Code's own download page: the board downloads nothing
    else if (fix.to === "identities" && typeof SERVERS !== "undefined") SERVERS.choose(() => { if (given.done) given.done(); });
    else if (fix.to === "doctor") return SERVE.post("/api/doctor-again", {}).then(() => { if (given.done) given.done(); });  // 1.7.45: doctor runs now; the line shows its progress at the next look
    return undefined;
  }

  // What a button or a link does with the promise a fix may give: it waits while the work runs, and says the error where it stood.
  function wait(node, fix, hooks) {
    const answer = go(fix, hooks);
    if (!answer || !answer.then) return;
    const label = node.textContent;
    node.disabled = true;
    answer.then(() => { node.disabled = false; }, (error) => { node.disabled = false; node.textContent = (error && error.message ? error.message : String(error)).slice(0, 160); node.title = label; });
  }

  // A fix as a small button (the board's block) or as a link in a note (the Enter screen).
  function button(fix, hooks, cls) {
    const node = h("button", {type: "button", class: cls || "act"}, fix.label || "");
    node.addEventListener("click", () => wait(node, fix, hooks));
    return node;
  }
  function link(fix, hooks, text) {
    const node = h("button", {type: "button", class: "en-link"}, text || fix.label || "");
    node.addEventListener("click", () => wait(node, fix, hooks));
    return node;
  }

  // Accept the guardrail files as they are now (1.7.39): the files are listed first; the person accepts in a window. After a new zip of the same version, or a change the person made on purpose.
  // `done`: called after the accept. The board does it, not the terminal window: there `doctor --accept` is refused, because a pipe cannot tell a person from an agent.
  function acceptFiles(done) {
    const call = (step) => SERVE.post("/api/integrity", {step}).then((data) => data.result);
    return call("preview").then((found) => {
      const files = found.changed || [];
      if (!files.length) { if (done) done(); return; }
      const shown = files.slice(0, 20);
      const go = h("button", {type: "button", class: "act hot"}, t("board.integrity.go"));
      const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
      const said = h("p", {class: "bad", hidden: "hidden"});
      const view = SERVE.dialog([h("h2", null, t("board.integrity.title", {n: files.length})), h("p", {class: "sub"}, t("board.integrity.about")),
        h("ul", {class: "su-chg"}, shown.map((name) => h("li", null, h("code", null, name))), files.length > shown.length ? h("li", {class: "su-soft"}, t("board.integrity.more", {n: files.length - shown.length})) : null),
        said, h("div", {class: "row"}, go, no)]);
      no.addEventListener("click", view.close);
      go.addEventListener("click", () => {
        go.disabled = true;
        call("accept").then(() => { view.close(); if (done) done(); }, (error) => { go.disabled = false; said.hidden = false; said.textContent = error.message; });
      });
      no.focus();
    });
  }
  function acceptButton(done) {
    const b = h("button", {type: "button", class: "en-open", title: t("board.integrity.tip")}, t("board.integrity.button"));
    b.addEventListener("click", () => { acceptFiles(done).catch(() => {}); });
    return b;
  }

  // The skipped setup items of the answer (`notes`: [{key, text, effect}]): the dot on the gear (dock.js) shows them. Whoever reads `/api/ready` (the Enter screen, the board's block, the dock itself) hands them in here;
  // a listener is told only when the list changes.
  let current = [], currentKey = "[]";
  const listeners = [];
  function notes(list) {
    const next = (Array.isArray(list) ? list : []).filter((note) => note && note.text).map((note) => ({key: String(note.key || ""), text: String(note.text), effect: String(note.effect || "")}));
    const key = JSON.stringify(next);
    if (key === currentKey) return;
    currentKey = key; current = next;
    listeners.forEach((fn) => fn(current));
  }
  function onNotes(fn) { listeners.push(fn); fn(current); }

  return {go, button, link, acceptFiles, acceptButton, notes, onNotes, current: () => current};
})();
