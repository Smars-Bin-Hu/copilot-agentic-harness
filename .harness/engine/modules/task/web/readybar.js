// The blocks at the top of the board after Enter (1.7.38, block B): what is still missing, from the same answer as the Enter screen (`/api/ready`, asked again every few seconds).
//
//   red     "The agent cannot work right now": a line of Harness & Local (required) is not ok after Enter, for example VS Code was closed. It has the button that mends it and it cannot be hidden.
//   yellow  "Not fully ready for your company's tasks": the problems of From the company (optional), one line each with one button to the place that mends it. Hide hides it until the set of problems changes
//           (the fingerprint of the set is kept in this browser, in try/catch). With a red block above, it is one line (Show opens it).
//
// Needs common.js (h, t), serve.js (SERVE), readyui.js (READY). The windows its buttons open are those of tools.js, dock.js, term.js, or the setup form. READYBAR.node() is the one node the board puts under its header.
"use strict";

const READYBAR = (function () {
  const KEY = "harness.ready.hidden";
  const EVERY = 6000;
  const root = document.documentElement;
  const wrap = h("div", {class: "rd-wrap", hidden: ""});
  let last = null, at = 0, inflight = false, restart = null, failed = "", openYellow = false, shownKey = "";

  const keep = {
    get() { try { return localStorage.getItem(KEY) || ""; } catch (error) { return ""; } },
    set(value) { try { localStorage.setItem(KEY, value); } catch (error) { /* hidden until the page closes only */ } },
  };
  let memory = keep.get();
  const fingerprint = (list) => JSON.stringify(list.map((problem) => [problem.row, problem.key, problem.text]));
  const dot = (level) => h("i", {class: "rd-dot " + level});

  function line(problem, level, extra) {
    const hooks = {done: () => poll(true), onState: (view) => { restart = view; paint(); }, opened: () => { restart = null; setTimeout(() => poll(true), 1500); }, fail: (error) => { failed = error.message || String(error); paint(); }};
    const said = extra || "";
    return h("div", {class: "rd-li"}, dot(level), h("span", {class: "rd-t"}, h("span", {class: "rd-what"}, problem.text), " ", h("span", {class: "rd-why"}, said || problem.why || "")),
      problem.fix && problem.fix.to ? READY.button(problem.fix, hooks, "act rd-fix" + (level === "red" && problem.fix.to === "vscode" ? " hot live" : "")) : null);
  }

  function red(problems) {
    const going = restart && (restart.state === "quitting" || restart.state === "opening");
    const note = (problem) => (problem.key === "vscode" ? (going ? READY.restartNote(restart) : failed || (restart && restart.state === "failed" ? READY.restartNote(restart) : "")) : "");
    const rows = problems.map((problem) => {
      const row = line(problem, problem.level === "yellow" ? "yellow" : "red", note(problem));
      if (going && problem.key === "vscode") { const button = row.querySelector("button"); if (button) { button.disabled = true; button.textContent = t(restart.state === "opening" ? "board.enter.opening" : "board.enter.vs.quitting"); } }
      return row;
    });
    return h("section", {class: "rd-bar rd-red", role: "alert"}, h("h3", null, dot("red"), t("board.ready.red.title")), h("div", {class: "rd-grp"}, t("board.enter.g.required") + " · " + t("board.enter.tag.required")), ...rows);
  }

  function yellow(problems, kb, withRed) {
    const title = kb ? t("board.ready.yellow.title.n", {n: problems.length}) : t("board.ready.yellow.title");
    const open = !withRed || openYellow;
    const toggle = h("button", {type: "button", class: "rd-x"}, open ? [t("board.ready.hide"), " ✕"] : [t("board.ready.show"), " ▸"]);
    toggle.addEventListener("click", () => {
      if (withRed) { openYellow = !openYellow; paint(); return; }
      memory = fingerprint(problems); keep.set(memory); paint();
    });
    const head = h("h3", null, dot("yellow"), h("span", {class: "rd-title"}, title), toggle);
    if (!open) return h("section", {class: "rd-bar rd-yellow slim"}, head);
    return h("section", {class: "rd-bar rd-yellow"}, head, h("div", {class: "rd-grp"}, t("board.enter.g.optional") + " · " + t("board.enter.tag.optional")), ...problems.map((problem) => line(problem, "yellow")));
  }

  function paint() {
    if (!last) { wrap.hidden = true; return; }
    const required = (last.problems && last.problems.required) || [], optional = (last.problems && last.problems.optional) || [], kb = Boolean(last.optional && last.optional.kb);
    const sig = JSON.stringify([required, optional, kb, restart && restart.state, failed, openYellow, memory === fingerprint(optional), root.lang]);
    if (sig === shownKey) return;
    shownKey = sig;
    const hidden = optional.length && memory === fingerprint(optional);
    const nodes = [];
    if (required.length) nodes.push(red(required));
    if (optional.length && (!hidden || required.length)) nodes.push(yellow(optional, kb, required.length > 0));
    wrap.replaceChildren(...nodes);
    wrap.hidden = !nodes.length;
    document.documentElement.classList.toggle("rd-red", required.some((problem) => problem.key === "vscode" || problem.key === "copilot"));  // the red block says it: the VS Code banner of shell.js would say the same twice
  }

  function poll(now) {
    if (typeof SERVE === "undefined" || inflight || document.hidden || root.classList.contains("en-open")) return;  // the Enter screen asks for itself
    if (!now && Date.now() - at < EVERY) return;
    inflight = true;
    SERVE.call("/api/ready", {}, 8).then((data) => {
      if (!Array.isArray(data.checks)) return;
      last = data; at = Date.now();
      if (data.restart && !(restart && (restart.state === "quitting" || restart.state === "opening"))) restart = data.restart;
      if (!(data.problems.required || []).some((problem) => problem.key === "vscode")) failed = "";  // VS Code is back: what the last try said is over
      paint();
    }, () => {}).then(() => { inflight = false; });
  }
  if (typeof SERVE !== "undefined" && DATA.serve) setInterval(() => poll(false), 1000);

  return {node: () => wrap, poll};
})();
