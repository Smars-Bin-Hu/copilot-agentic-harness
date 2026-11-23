// The block at the top of the board after Enter (1.7.38, block B): what is still missing, from the same answer as the Enter screen (`/api/ready`, asked again every few seconds).
//
//   red     "The agent cannot work right now": a line of Harness & Local (required) is not ok after Enter, for example gh signed out. It has the button that mends it and it cannot be hidden.
//   The company's things that are not set up (optional) are not drawn here: they are the dot on the gear (READY.notes, dock.js).
//
// Needs common.js (h, t), serve.js (SERVE), readyui.js (READY). The windows its buttons open are those of tools.js, dock.js, term.js, or the wizard. READYBAR.node() is the one node the board puts under its header.
"use strict";

const READYBAR = (function () {
  const EVERY = 6000;
  const root = document.documentElement;
  const wrap = h("div", {class: "rd-wrap", hidden: ""});
  let last = null, at = 0, inflight = false, shownKey = "";

  const dot = (level) => h("i", {class: "rd-dot " + level});

  function line(problem, level) {
    const hooks = {done: () => poll(true)};  // an error is said on the button itself (READY.button)
    const said = "";
    return h("div", {class: "rd-li"}, dot(level), h("span", {class: "rd-t"}, h("span", {class: "rd-what"}, problem.text), document.documentElement.lang === "zh" ? "" : " ", h("span", {class: "rd-why"}, said || problem.why || "")),
      problem.fix && problem.fix.to ? READY.button(problem.fix, hooks, "act rd-fix") : null);
  }

  function red(problems) {
    const rows = problems.map((problem) => line(problem, problem.level === "yellow" ? "yellow" : "red"));
    return h("section", {class: "rd-bar rd-red", role: "alert"}, h("h3", null, dot("red"), t("board.ready.red.title")), h("div", {class: "rd-grp"}, t("board.enter.g.required") + " · " + t("board.enter.tag.required")), ...rows);
  }

  function paint() {
    if (!last) { wrap.hidden = true; return; }
    const required = (last.problems && last.problems.required) || [];
    const sig = JSON.stringify([required, root.lang]);
    if (sig === shownKey) return;
    shownKey = sig;
    wrap.replaceChildren(...(required.length ? [red(required)] : []));
    wrap.hidden = !required.length;
    document.documentElement.classList.toggle("rd-red", required.some((problem) => problem.key === "vscode" || problem.key === "copilot"));  // the red block says it: the VS Code banner of shell.js would say the same twice
  }

  function poll(now) {
    if (typeof SERVE === "undefined" || inflight || document.hidden || root.classList.contains("en-open")) return;  // the Enter screen asks for itself
    if (!now && Date.now() - at < EVERY) return;
    inflight = true;
    SERVE.call("/api/ready", {}, 8).then((data) => {
      if (!Array.isArray(data.checks)) return;
      last = data; at = Date.now();
      READY.notes(data.notes);  // the dot on the gear
      paint();
    }, () => {}).then(() => { inflight = false; });
  }
  if (typeof SERVE !== "undefined" && DATA.serve) setInterval(() => poll(false), 1000);

  return {node: () => wrap, poll};
})();
