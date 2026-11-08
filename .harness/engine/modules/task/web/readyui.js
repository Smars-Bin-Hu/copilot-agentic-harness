// Shared by the Enter screen (enter.js) and the block of the board after Enter (readybar.js) (1.7.38, block B): where a fix of the readiness answer leads, and the VS Code button.
// A fix is what `core/readyitems.py` and `modules/task/ready.py` give each problem: {to, label, ...}.
//   setup   the Get ready form at a card:          /setup?sec=company|computer|you
//   tools   a window of Tools:                     TOOLS.open(tab, done, part), tab packs | connections | local (the three windows of block C; the old window knows packs and connections)
//   kb      the knowledge base window:             DOCK.kbWindow(tab)
//   term    a command the Terminal window runs:    TERM.run(line)
//   vscode  the VS Code button:                    open, restart, or restart with identities (vsAct)
// Needs common.js (h, t), serve.js (SERVE). The other windows are used when the page has them.
"use strict";

const READY = (function () {
  // Restart VS Code, then, with identities, the picker of the saved sign-ins (servers.js) opens it. The picker is held until the board sees VS Code gone: it refuses to open one while a VS Code of this folder is open.
  // hooks: {onState(view), opened()}. The promise ends when the restart has ended (open) or the picker is up (identities); it fails with the reason (`quiet`: the person cancelled).
  function waitGone() {
    const until = Date.now() + 15000;
    return new Promise((resolve) => {
      const look = () => SERVE.call("/api/ready", {}, 8).then((data) => {
        const vs = (data.checks || []).find((line) => line.id === "vscode");
        if (!vs || vs.state !== "ok" || Date.now() > until) resolve(); else setTimeout(look, 700);
      }, () => resolve());
      look();
    });
  }
  function vsAct(kind, hooks) {
    const given = hooks || {};
    const withIdentities = kind === "identities" && typeof SERVERS !== "undefined";
    return SERVE.restartVS({open: !withIdentities, onState: given.onState}).then((view) => {
      if (!withIdentities) { if (given.opened) given.opened(); return view; }
      return waitGone().then(() => SERVERS.choose(() => { if (given.opened) given.opened(); }));
    });
  }

  function go(fix, hooks) {
    if (!fix || !fix.to) return;
    const given = hooks || {};
    if (fix.to === "setup") location.assign("/setup?sec=" + encodeURIComponent(fix.sec || "company"));
    else if (fix.to === "tools" && typeof TOOLS !== "undefined") TOOLS.open(fix.tab, given.done, fix.part || undefined);  // block C rebuilds the window: the tab names are packs, connections and local
    else if (fix.to === "kb" && typeof DOCK !== "undefined") DOCK.kbWindow(fix.tab);
    else if (fix.to === "term" && typeof TERM !== "undefined") TERM.run(fix.run);
    else if (fix.to === "vscode") vsAct(fix.kind, given).catch((error) => { if (given.fail && !error.quiet) given.fail(error); });
  }

  // A fix as a small button (the board's block) or as a link in a note (the Enter screen).
  function button(fix, hooks, cls) {
    const node = h("button", {type: "button", class: cls || "act"}, fix.label || "");
    node.addEventListener("click", () => go(fix, hooks));
    return node;
  }
  function link(fix, hooks, text) {
    const node = h("button", {type: "button", class: "en-link"}, text || fix.label || "");
    node.addEventListener("click", () => go(fix, hooks));
    return node;
  }

  // The words of a restart that is going on or that failed, for a note under the VS Code line. "" when there is nothing to say.
  function restartNote(view) {
    if (!view) return "";
    if (view.state === "quitting") return t("board.vs.restart.quitting");
    if (view.state === "opening") return t("board.vs.restart.opening");
    if (view.state === "failed") return SERVE.restartWhy(view.why);
    return "";
  }

  return {go, button, link, vsAct, restartNote};
})();
