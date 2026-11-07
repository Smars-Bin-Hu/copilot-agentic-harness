// Tools (1.7.17): one window, three tabs: Tool packs (what is installed), Connections (where the agent goes, with your sign-in), This computer (programs,
// the CA bundle, MCP). Each tab is a panel of servers.js or machine.js: `panel(ctx)` gives {body, foot}; ctx.go(tab) switches, ctx.changed() repaints the dots.
// Get ready shows one group "Tools" with a line per tab (`line(tab)`). Needs common.js (h, t), serve.js (SERVE), servers.js (SERVERS), machine.js (MACHINE).
const TOOLS = (function () {
  const TABS = ["packs", "connections", "computer"];
  const LABEL = {packs: "setup.toolpacks", connections: "connections.title", computer: "machine.title"};

  // The dot of a tab and the words of its line in Get ready: ok (green), warn (something is missing here), none (nothing set, grey).
  function states() {
    return Promise.all([MACHINE.toolpacksSummary(), SERVERS.summary(), MACHINE.summary()].map((promise) => promise.catch(() => null))).then(([packs, conns, pc]) => ({
      packs: packs ? {dot: !packs.n ? "none" : packs.ready === packs.n ? "ok" : "warn", words: packs.n ? t("tools.packs.state", packs) : t("tools.packs.none")} : {dot: "none", words: ""},
      connections: conns ? {dot: !conns.n ? "none" : conns.saved === conns.n ? "ok" : "warn", words: conns.n ? t("setup.connections.state", conns) : t("setup.connections.none")} : {dot: "none", words: ""},
      computer: pc ? {dot: pc.paths || pc.certs ? "ok" : "none", words: [pc.paths || pc.certs ? t("setup.machine.state", pc) : t("setup.machine.none"), t(pc.mcp ? "tools.mcp.on" : "tools.mcp.off")].join(" · ")} : {dot: "none", words: ""},
    }));
  }

  function open(tab, done) {
    let at = TABS.includes(tab) ? tab : "packs";
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
    const ctx = {go: (name) => show(name), close: view.close, changed: repaint};
    function show(name) {
      at = name;
      tabs.forEach((button) => { const on = button.dataset.tab === name; button.classList.toggle("on", on); button.setAttribute("aria-selected", String(on)); });
      const made = name === "connections" ? SERVERS.panel(ctx) : name === "computer" ? MACHINE.panel(ctx) : MACHINE.packsPanel(ctx);
      body.replaceChildren(...made.body);
      foot.replaceChildren(...made.foot, close);
      body.scrollTop = 0;
    }
    close.addEventListener("click", view.close);
    let tallest = 0;  // the window is centred: a tab shorter or taller than the one before made it jump. The body keeps the tallest height seen in this window (1.7.26).
    if (typeof ResizeObserver === "function") new ResizeObserver(() => { if (body.offsetHeight > tallest) { tallest = body.offsetHeight; body.style.minHeight = Math.max(0, Math.min(tallest, innerHeight - 232)) + "px"; } }).observe(body);
    show(at);
    repaint();
    if (done) { const watch = setInterval(() => { if (!view.box.isConnected) { clearInterval(watch); done(); } }, 400); }
  }

  // Get ready: one group, a line per tab: its dot, a few words, and Open on that tab.
  function group(refresh) {
    const lines = {};
    const rows = TABS.map((name) => {
      lines[name] = {dot: h("span", {class: "mc-dot"}), words: h("span", {class: "su-note"})};
      const go = h("button", {type: "button", class: "act"}, t("tools.open"));
      go.addEventListener("click", () => open(name, paint));
      return h("div", {class: "su-row tl-row"}, h("span", {class: "su-k"}, t(LABEL[name])), h("div", {class: "su-v"}, h("div", {class: "su-line"}, lines[name].dot, lines[name].words, go)));
    });
    function paint() {
      states().then((found) => TABS.forEach((name) => { lines[name].dot.className = "mc-dot " + found[name].dot; lines[name].words.textContent = found[name].words; }));
      if (refresh) refresh();
    }
    paint();
    return h("div", {class: "tl-group"}, h("div", {class: "tl-head"}, h("b", null, t("tools.title")), " ", h("span", {class: "su-note"}, t("tools.lead")), " ", h("span", {class: "sv-info", tabindex: "0", title: t("tools.model.tip")}, "ⓘ")), ...rows);
  }

  return {open, group};
})();
