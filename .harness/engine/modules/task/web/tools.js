// Tools (1.7.38): one window, two tabs named like the setup form's sections and the Enter groups. From the company: what the knowledge base brings, read only (the tool packs, the connections with a dot for your sign-in).
// This computer: what you do here (programs, network, sign-ins, MCP, packs added from a folder). Each tab is a panel of servers.js or machine.js: `panel(ctx)` gives {body, foot}; ctx.go(tab, part, focus) switches and
// scrolls to a part (or a row: `data-focus`), ctx.changed() repaints the dots. Get ready draws their facts in its sections (`facts()`) and opens a tab with Open.
// Needs common.js (h, t), serve.js (SERVE), servers.js (SERVERS), machine.js (MACHINE).
const TOOLS = (function () {
  const TABS = ["company", "computer"];
  const LABEL = {company: "setup.sec.company", computer: "setup.sec.computer"};
  const OLD = {packs: ["company", "packs"], connections: ["company", "connections"]};  // the names of the three tabs before 1.7.38

  // The dot of a tab and the words of its line in Get ready: ok (green), warn (something is missing here), none (nothing set, grey).
  function states() {
    return Promise.all([MACHINE.toolpacksSummary(), SERVERS.summary(), MACHINE.summary()].map((promise) => promise.catch(() => null))).then(([packs, conns, pc]) => ({
      company: packs || conns ? {dot: !packs || !packs.n ? "none" : packs.ready === packs.n ? "ok" : "warn", words: [packs ? (packs.n ? t("tools.packs.state", packs) : t("tools.packs.none")) : "", conns ? (conns.n ? t("setup.connections.state", conns) : t("setup.connections.none")) : ""].filter(Boolean).join(" \u00b7 ")} : {dot: "none", words: ""},
      computer: pc ? {dot: pc.paths || pc.certs ? "ok" : "none", words: [pc.paths || pc.certs ? t("setup.machine.state", pc) : t("setup.machine.none"), t(pc.mcp ? "tools.mcp.on" : "tools.mcp.off")].join(" \u00b7 ")} : {dot: "none", words: ""},
    }));
  }

  // From the company: two parts, the tool packs and the connections (both read only; a link on a row opens the row of This computer that fixes it).
  function companyPanel(ctx) {
    const packs = MACHINE.packsPanel(ctx), conns = SERVERS.listPanel(ctx);
    const part = (key, title, tip, nodes) => h("section", {class: "tl-part", "data-part": key}, h("h3", {class: "mc-h"}, title, tip ? " " : null, tip ? h("span", {class: "sv-info", tabindex: "0", title: t(tip)}, "\u24d8") : null), ...nodes);
    return {body: [h("p", {class: "sub"}, t("tools.company.lead"), " ", h("span", {class: "sv-info", tabindex: "0", title: t("tools.company.tip")}, "\u24d8")),
      part("packs", t("setup.toolpacks"), "machine.conn.add", packs.body), part("connections", t("connections.title"), "", conns.body)], foot: []};
  }

  function open(tab, done, part) {
    const old = OLD[tab];
    if (old) { part = part || old[1]; tab = old[0]; }
    let at = TABS.includes(tab) ? tab : "company";
    const dots = {};
    const tabs = TABS.map((name) => {
      dots[name] = h("span", {class: "mc-dot"});
      const button = h("button", {type: "button", class: "tl-tab", role: "tab", "data-tab": name}, dots[name], t(LABEL[name]));
      button.addEventListener("click", () => show(name));
      return button;
    });
    const body = h("div", {class: "win-body tl-body"});
    const foot = h("div", {class: "row win-foot"});
    const close = h("button", {type: "button", class: "act"}, t("connections.close"));
    const view = SERVE.dialog([h("h2", null, t("tools.title"), " ", h("span", {class: "sv-info", tabindex: "0", title: t("tools.model.tip")}, "ⓘ")), h("div", {class: "tl-tabs", role: "tablist"}, ...tabs), body, foot]);
    view.box.classList.add("wide", "sv-win", "tl-win");
    const repaint = () => states().then((found) => TABS.forEach((name) => { dots[name].className = "mc-dot " + found[name].dot; dots[name].title = found[name].words; }));
    let want = null, until = 0;  // the part or row to scroll to: asked again as the panels fill in, for a few seconds
    const reveal = () => {
      if (!want || Date.now() > until) { want = null; return; }
      const row = want.focus ? [...body.querySelectorAll("[data-focus]")].find((node) => node.dataset.focus === want.focus) : null;
      const node = row || (want.part ? body.querySelector('[data-part="' + want.part + '"]') : null);
      if (!node) return;
      body.scrollTop = Math.max(0, node.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop - 4);
      if (row) { row.classList.remove("tl-flash"); void row.offsetWidth; row.classList.add("tl-flash"); want = null; }
    };
    const ctx = {go: (name, part, focus) => show(name, part, focus), close: view.close, changed: repaint, arrived: reveal};
    function show(name, part, focus) {
      at = name;
      want = part || focus ? {part, focus} : null; until = Date.now() + 4000;
      tabs.forEach((button) => { const on = button.dataset.tab === name; button.classList.toggle("on", on); button.setAttribute("aria-selected", String(on)); });
      const made = name === "computer" ? MACHINE.panel(ctx) : companyPanel(ctx);
      body.replaceChildren(...made.body);
      foot.replaceChildren(...made.foot, close);
      body.scrollTop = 0;
      reveal();
    }
    close.addEventListener("click", view.close);
    let tallest = 0;  // the window is centred: a tab shorter or taller than the one before made it jump. The body keeps the tallest height seen in this window (1.7.26).
    if (typeof ResizeObserver === "function") new ResizeObserver(() => { if (body.offsetHeight > tallest) { tallest = body.offsetHeight; body.style.minHeight = Math.max(0, Math.min(tallest, innerHeight - 232)) + "px"; } }).observe(body);
    show(at, part);
    repaint();
    if (done) { const watch = setInterval(() => { if (!view.box.isConnected) { clearInterval(watch); done(); } }, 400); }
  }

  // Get ready (1.7.36): the three summaries in one go, each null when it cannot be read. setup.js draws them as facts of its sections.
  function facts() {
    return Promise.all([MACHINE.toolpacksSummary(), SERVERS.summary(), MACHINE.summary()].map((promise) => promise.catch(() => null))).then(([packs, conns, pc]) => ({packs, conns, pc}));
  }

  return {open, facts};
})();
