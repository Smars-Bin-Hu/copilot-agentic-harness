// Tools (1.7.38): three windows, each opened on its own: Tool packs, Connections & sign-ins, and Local. They have no tabs; a link inside one (a missing program, a step that broke) opens another in the same
// dialog at the part that helps. Each window is a panel of machine.js (packs, local) or servers.js (connections): `panel(ctx)` gives {title, tip, sub, body, foot}; ctx.go(window, part, focus) switches and
// scrolls to a part (or a row: `data-focus`). The setup form opens them with Open and draws their facts (`facts()`).
// Needs common.js (h, t), serve.js (SERVE), servers.js (SERVERS), machine.js (MACHINE).
const TOOLS = (function () {
  const WINDOWS = ["packs", "connections", "local"];

  // The names before 1.7.38: "company" was the packs and the connections together, "computer" the programs, network, sign-ins, MCP and packs added from a folder. A part that moved goes to its new window.
  function where(tab, part) {
    part = part || "";
    if (tab === "company") return part === "connections" ? ["connections", ""] : ["packs", part === "packs" ? "" : part];
    if (tab === "computer") tab = "local";
    if (tab === "local" && part === "signins") return ["connections", ""];
    if (tab === "local" && part === "added") return ["packs", "added"];
    return [WINDOWS.includes(tab) ? tab : "packs", part];
  }

  function open(tab, done, part) {
    let at;
    [at, part] = where(tab, part);
    const title = h("h2");
    const sub = h("p", {class: "sub tl-sub"});
    const body = h("div", {class: "win-body tl-body"});
    const foot = h("div", {class: "row win-foot"});
    const close = h("button", {type: "button", class: "act"}, t("connections.close"));
    const view = SERVE.dialog([title, sub, body, foot]);
    view.box.classList.add("wide", "sv-win", "tl-win");
    let want = null, until = 0;  // the part or row to scroll to: asked again as the panels fill in, for a few seconds
    const reveal = () => {
      if (!want || Date.now() > until) { want = null; return; }
      const row = want.focus ? [...body.querySelectorAll("[data-focus]")].find((node) => node.dataset.focus === want.focus) : null;
      const node = row || (want.part ? body.querySelector('[data-part="' + want.part + '"]') : null);
      if (!node) return;
      body.scrollTop = Math.max(0, node.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop - 4);
      if (row) { row.classList.remove("tl-flash"); void row.offsetWidth; row.classList.add("tl-flash"); want = null; }
    };
    const ctx = {go: (name, part, focus) => show(name, part, focus), close: view.close, arrived: reveal};
    function show(name, part, focus) {
      [name, part] = where(name, part);
      at = name;
      want = part || focus ? {part, focus} : null; until = Date.now() + 4000;
      const made = name === "local" ? MACHINE.localPanel(ctx) : name === "connections" ? SERVERS.connectionsPanel(ctx) : MACHINE.packsPanel(ctx);
      view.box.dataset.window = name;
      title.replaceChildren(made.title, " ", h("span", {class: "sv-info", tabindex: "0", title: made.tip}, "ⓘ"));
      sub.textContent = made.sub;
      body.replaceChildren(...made.body);
      foot.replaceChildren(...made.foot, h("span", {class: "tl-grow"}), close);
      body.scrollTop = 0;
      reveal();
    }
    close.addEventListener("click", view.close);
    show(at, part);
    if (done) { const watch = setInterval(() => { if (!view.box.isConnected) { clearInterval(watch); done(); } }, 400); }
  }

  // The setup form: the three summaries in one go, each null when it cannot be read. setup.js draws them as facts of its cards.
  function facts() {
    return Promise.all([MACHINE.toolpacksSummary(), SERVERS.summary(), MACHINE.summary()].map((promise) => promise.catch(() => null))).then(([packs, conns, pc]) => ({packs, conns, pc}));
  }

  return {open, facts};
})();
