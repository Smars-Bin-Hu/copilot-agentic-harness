// The controls fixed to the browser window of the board and the task page: the search pill (top right) and the Cmd+K / Ctrl+K palette, the gear (bottom right) with the settings panel,
// and the one place that knows whether VS Code is linked (the banner under the header, the pill, the buttons).
// They are built once and appended to <body>, outside #app: the redraw of a page (the 3 s poll) never touches them, so an open panel stays open.
//
// The palette only navigates. It opens a task, a view, a filter, a tab, the settings; it flips the theme or Lite of this browser. It never calls approve, promote, send, steer or any
// call that changes a task. The only calls this file makes are: `/api/board` (a read, to list the tasks on the task page) and `/api/language` (the settings panel).
// A page on disk (no server) has the search, the theme, Lite and the view, filter and tab items; it has no language and no jump to a task page (unless the task has a report file beside it).
// Common helpers (h, t, stateTag) come from common.js; board.js and desk.js hand over what they can open with SHELL.provide().
"use strict";

const SHELL = (function () {
  const served = typeof SERVE !== "undefined";
  const root = document.documentElement;
  const mod = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "") ? "⌘" : "Ctrl";
  const NS = "http://www.w3.org/2000/svg";
  const ICONS = {
    search: ["M7 12.5a5.5 5.5 0 1 0 0-11 5.5 5.5 0 0 0 0 11zM11 11l3.5 3.5"],
    task: ["M3 2.5h10v11H3zM5.5 6h5M5.5 8.5h5M5.5 11h3"],
    list: ["M2.5 4h11M2.5 8h11M2.5 12h11"],
    lobby: ["M2.5 13.5h11M4 13.5V8a4 4 0 0 1 8 0v5.5M6.5 8.2v.1M9.5 8.2v.1"],
    filter: ["M2 3h12L9.5 8.5V13l-3-1.5V8.5z"],
    tab: ["M2 5.5V3.5h5l1 2h6v7H2z"],
    sun: ["M8 5.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6zM8 1v1.6M8 13.4V15M1 8h1.6M13.4 8H15M3 3l1.1 1.1M11.9 11.9L13 13M13 3l-1.1 1.1M4.1 11.9L3 13"],
    bolt: ["M9 1.5L3.5 9h4l-.5 5.5L12.5 7h-4z"],
    gear: ["M8 5.8a2.2 2.2 0 1 0 0 4.4 2.2 2.2 0 0 0 0-4.4z", "M8 1.6l1 1.7 2-.4.6 2 1.9.8-.7 1.9 1.3 1.6-1.6 1.3.1 2-2 .3-1 1.8L8 13.6l-1.6 1-1-1.8-2-.3.1-2L2 8.9l1.3-1.6-.7-1.9 1.9-.8.6-2 2 .4z"],
  };
  function icon(name) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("aria-hidden", "true");
    for (const d of ICONS[name] || ICONS.task) {
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", d);
      svg.append(path);
    }
    return svg;
  }

  // What this browser keeps (the recent tasks, whether the link to VS Code was seen up): a convenience only. Where storage is not allowed it is kept until the page closes.
  const memory = {};
  const keep = {
    get(name) { try { const value = localStorage.getItem(name); return value === null ? (name in memory ? memory[name] : null) : value; } catch (error) { return name in memory ? memory[name] : null; } },
    set(name, value) { memory[name] = value; try { localStorage.setItem(name, value); } catch (error) { /* kept in memory only */ } },
  };
  const tabKeep = {
    get(name) { try { return sessionStorage.getItem(name); } catch (error) { return name in memory ? memory[name] : null; } },
    set(name, value) { memory[name] = value; try { if (value === null) sessionStorage.removeItem(name); else sessionStorage.setItem(name, value); } catch (error) { /* kept in memory only */ } },
  };

  let provider = null;  // () => {tasks: rows, views: [], filters: [], tabs: [], here: name}: what the page itself can open
  const provide = (call) => { provider = call; };
  const given = () => { try { return (provider && provider()) || {}; } catch (error) { return {}; } };

  // ---------- recent tasks ----------
  const recents = () => { try { const list = JSON.parse(keep.get("harness.recent") || "[]"); return Array.isArray(list) ? list.filter((item) => typeof item === "string") : []; } catch (error) { return []; } };
  function visit(name) {
    if (!name) return;
    keep.set("harness.recent", JSON.stringify([name, ...recents().filter((item) => item !== name)].slice(0, 8)));
  }

  // ---------- the tasks the palette can open ----------
  const hrefOf = (row) => (served ? (row.status !== "new" ? "/task/" + encodeURIComponent(row.name) : "") : row.report ? row.report.split("/").map(encodeURIComponent).join("/") : "");
  let fetched = null;  // {rows, at}: the rows the task page asked the server for, kept a few seconds
  let asking = false;
  function tasks() {
    const own = given().tasks;
    if (own) return own;
    return fetched ? fetched.rows : null;
  }
  function loadTasks() {
    if (!served || given().tasks || asking || (fetched && Date.now() - fetched.at < 5000)) return;
    asking = true;
    SERVE.post("/api/board", {}).then((data) => { fetched = {rows: data.rows || [], at: Date.now()}; asking = false; if (open()) render(true); }, () => { asking = false; });
  }

  // ---------- the palette ----------
  let shade = null, input = null, list = null, foot = null, items = [], at = 0, previous = null;
  const open = () => Boolean(shade) && !shade.hidden;
  function buildPalette() {
    input = h("input", {type: "text", spellcheck: "false", autocomplete: "off", role: "combobox", "aria-expanded": "true", "aria-controls": "sh-list", "aria-label": t("board.shell.search"), placeholder: t("board.shell.search.ph")});
    list = h("div", {class: "pal-list", role: "listbox", id: "sh-list"});
    foot = h("div", {class: "pal-ft"});
    const box = h("div", {class: "pal", role: "dialog", "aria-modal": "true", "aria-label": t("board.shell.search")}, h("div", {class: "pal-in"}, icon("search"), input, h("kbd", null, "esc")), list, foot);
    shade = h("div", {class: "pal-shade", hidden: "hidden"}, box);
    document.body.append(shade);
    shade.addEventListener("mousedown", (event) => { if (event.target === shade) closePalette(); });
    input.addEventListener("input", () => { at = 0; render(); });
    list.addEventListener("mousemove", (event) => { const row = event.target.closest(".pal-i"); if (row && Number(row.dataset.i) !== at) { at = Number(row.dataset.i); mark(false); } });
    list.addEventListener("click", (event) => { const row = event.target.closest(".pal-i"); if (row) run(Number(row.dataset.i)); });
    foot.append(h("span", null, h("kbd", null, "↑"), h("kbd", null, "↓"), " " + t("board.shell.move")), h("span", null, h("kbd", null, "↵"), " " + t("board.shell.go")),
      h("span", {class: "grow"}, t("board.shell.more")), h("span", null, h("kbd", null, "esc"), " " + t("board.shell.close")));
  }

  // The board of a served page, asked from a task page: the choice is kept where board.js keeps it, then the board opens.
  function toBoard(mode, filter) {
    if (mode) keep.set("harness.board.mode", mode);
    if (filter) { keep.set("harness.board.filter", filter); keep.set("harness.board.mode", "list"); }
    location.assign("/");
  }

  function allItems() {
    const own = given();
    const out = [];
    const rows = tasks();
    const known = rows ? new Set(rows.map((row) => row.name)) : null;
    const byName = rows ? new Map(rows.map((row) => [row.name, row])) : new Map();
    const task = (name, group) => {
      const row = byName.get(name);
      const href = row ? hrefOf(row) : served ? "/task/" + encodeURIComponent(name) : "";
      if (!href) return null;
      return {g: group, key: "task:" + name, label: name, icon: "task", node: row ? stateTag(row, served) : null, kw: name + " " + (row ? row.kind + " " + row.state : ""),
        run: () => { visit(name); if (name !== own.here) location.assign(href); }};
    };
    const recent = recents().filter((name) => !known || known.has(name)).slice(0, 3);
    for (const name of recent) { const item = task(name, "recent"); if (item) out.push(item); }
    for (const tab of own.tabs || []) out.push({g: "tabs", key: "tab:" + tab.id, label: t("board.shell.tab", {name: tab.label + (tab.group ? " \u00b7 " + tab.group : "")}), icon: "tab", kw: "tab " + tab.label + " " + (tab.group || ""), run: tab.run, current: tab.current});
    if (rows) for (const row of rows) { if (recent.includes(row.name)) continue; const item = task(row.name, "tasks"); if (item) out.push(item); }
    const views = own.views || (served ? [{id: "board", label: t("board.shell.view.board"), kw: "board home all tasks", run: () => toBoard()},
      {id: "list", label: t("board.shell.view.list"), kw: "list table", run: () => toBoard("list")}, {id: "lobby", label: t("board.shell.view.lobby"), kw: "lobby robots floor", run: () => toBoard("lobby")}] : []);
    for (const view of views) out.push({g: "views", key: "view:" + view.id, label: view.label, icon: view.id === "lobby" ? "lobby" : "list", kw: "view " + view.kw, run: view.run});
    const filters = own.filters || (served ? ["all", "waiting", "working", "quiet", "unheld", "paused", "closed"].map((name) => ({id: name, label: t("board.filter." + name), run: () => toBoard("list", name)})) : []);
    filters.forEach((filter, index) => out.push({g: "filters", key: "filter:" + filter.id, top: index < 3, label: t("board.shell.filter", {name: filter.label}), icon: "filter", kw: "filter " + filter.label, run: filter.run}));
    const dark = root.getAttribute("data-theme") === "dark";
    const lite = root.classList.contains("lite");
    out.push({g: "settings", key: "theme", label: t(dark ? "board.shell.theme.light" : "board.shell.theme.dark"), icon: "sun", kw: "theme dark light mode", run: () => harnessTheme.set(dark ? "light" : "dark")});
    out.push({g: "settings", key: "lite", label: t(lite ? "board.shell.lite.off" : "board.shell.lite.on"), icon: "bolt", kw: "lite glass fast blur motion slow", run: () => harnessTheme.setLite(!lite)});
    out.push({g: "settings", key: "settings", label: t("board.shell.open"), icon: "gear", kw: "settings language preferences", run: () => setTimeout(openSettings, 30)});
    return out;
  }

  // A long state text is cut with an ellipsis and told in full on hover.
  function shortTag(node) {
    const full = node.textContent, last = node.lastChild;
    node.title = full;
    if (full.length > 26 && last && last.nodeType === 3) last.textContent = last.textContent.slice(0, Math.max(1, last.textContent.length - (full.length - 25))) + "\u2026";
    return node;
  }

  function lit(label, query) {
    const found = query ? label.toLowerCase().indexOf(query) : -1;
    return found < 0 ? label : [label.slice(0, found), h("mark", null, label.slice(found, found + query.length)), label.slice(found + query.length)];
  }

  function render(keepAt) {
    const query = input.value.trim().toLowerCase();
    const wasKey = keepAt && items[at] ? items[at].key : null;
    const everything = allItems();
    if (!query) items = everything.filter((item) => item.g !== "tasks" && (item.g !== "filters" || item.top));
    else {
      const words = query.split(/\s+/);
      items = everything.filter((item) => words.every((word) => (item.label + " " + (item.kw || "")).toLowerCase().includes(word)))
        .map((item) => ({...item, rank: item.label.toLowerCase().startsWith(query) ? 0 : item.label.toLowerCase().includes(query) ? 1 : 2})).sort((a, b) => a.rank - b.rank);
    }
    if (wasKey !== null) { const again = items.findIndex((item) => item.key === wasKey); if (again >= 0) at = again; }
    if (at >= items.length) at = 0;
    const heads = {recent: "board.shell.recent", tasks: "board.shell.tasks", tabs: "board.shell.tabs", views: "board.shell.views", filters: "board.shell.filters", settings: "board.shell.settings"};
    const nodes = [];
    let last = "";
    items.forEach((item, index) => {
      const group = query && item.g === "recent" ? "tasks" : item.g;
      if (group !== last) { nodes.push(h("div", {class: "pal-h", role: "presentation"}, t(heads[group]))); last = group; }
      nodes.push(h("div", {class: "pal-i", role: "option", id: "sh-o" + index, "data-i": index, "aria-selected": "false"}, icon(item.icon), h("span", {class: "t", title: item.label}, item.g === "tabs" || item.g === "settings" ? item.label : lit(item.label, query)), item.node ? shortTag(item.node) : null));
    });
    list.replaceChildren(...(nodes.length ? nodes : [h("div", {class: "pal-none"}, t("board.shell.none"))]));
    mark(true);
  }
  function mark(scroll) {
    for (const row of list.querySelectorAll(".pal-i")) {
      const on = Number(row.dataset.i) === at;
      row.classList.toggle("on", on);
      row.setAttribute("aria-selected", on ? "true" : "false");
      if (on) { input.setAttribute("aria-activedescendant", row.id); if (scroll !== false) row.scrollIntoView({block: "nearest"}); }
    }
  }
  function run(index) {
    const item = items[index];
    if (!item) return;
    closePalette(true);
    item.run();
  }
  function openPalette() {
    closeSettings();
    if (!shade) buildPalette();
    if (open()) return;
    previous = document.activeElement;
    shade.hidden = false;
    input.value = "";
    input.placeholder = t("board.shell.search.ph");
    at = 0;
    loadTasks();
    render();
    input.focus();
  }
  function closePalette(skipFocus) {
    if (!open()) return;
    shade.hidden = true;
    if (!skipFocus && previous && previous.focus && document.contains(previous)) previous.focus();
  }

  // ---------- settings ----------
  let panel = null, gear = null, said = null;
  const langNow = () => (root.lang === "zh" ? "zh" : "en");
  function segment(key, options) {
    const seg = h("div", {class: "seg2", role: "group", "data-key": key});
    for (const [value, label] of options) seg.append(h("button", {type: "button", "data-v": value, "aria-pressed": "false"}, label));
    return seg;
  }
  function buildSettings() {
    said = h("div", {class: "sp-bad", role: "alert", hidden: "hidden"});
    panel = h("div", {class: "setp", role: "dialog", "aria-label": t("board.shell.gear"), hidden: "hidden"},
      h("h4", null, t("board.shell.gear")),
      h("div", {class: "sp-row"}, h("span", null, t("board.shell.theme")), segment("theme", [["light", t("board.shell.light")], ["dark", t("board.shell.dark")]])),
      h("div", {class: "sp-row"}, h("span", null, t("board.shell.render")), segment("lite", [["false", t("board.shell.glass")], ["true", t("board.shell.lite")]])),
      h("p", {class: "sp-note"}, t("board.shell.lite.hint")),
      typeof WALL !== "undefined" ? WALL.section() : null,  // the Background part (wall.js): the picture, its folder, rotation, motion
      served ? h("div", {class: "sp-row"}, h("span", null, t("board.shell.lang")), segment("lang", [["en", t("desk.send.lang.name.en")], ["zh", t("desk.send.lang.name.zh")]])) : null,
      served ? h("p", {class: "sp-note"}, t("board.shell.lang.hint")) : null, said);
    document.body.append(panel);
    panel.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-v]");
      if (!button) return;
      const key = button.parentNode.dataset.key, value = button.dataset.v;
      if (key === "theme") harnessTheme.set(value);
      else if (key === "lite") { harnessTheme.setLite(value === "true"); if (typeof WALL !== "undefined") WALL.mark(); }
      else if (key === "lang" && value !== langNow()) setLanguage(value, button.parentNode);
      syncSettings();
    });
  }
  // The language is the real `language` setting of the harness: the server writes user.override.json (a paired browser only). The page then loads its texts again (serve.js: post()).
  function setLanguage(value, seg) {
    said.hidden = true;
    for (const button of seg.querySelectorAll("button")) button.disabled = true;
    tabKeep.set("harness.reopen", "settings");
    SERVE.post("/api/language", {language: value}).then(() => {
      for (const button of seg.querySelectorAll("button")) button.disabled = false;  // the page is reloading when the language changed; if not, the buttons come back
    }, (error) => {
      tabKeep.set("harness.reopen", null);
      for (const button of seg.querySelectorAll("button")) button.disabled = false;
      said.textContent = t("board.shell.lang.failed", {error: error && error.message ? error.message : ""});
      said.hidden = false;
    });
  }
  function syncSettings() {
    if (!panel) return;
    const state = {theme: root.getAttribute("data-theme"), lite: String(root.classList.contains("lite")), lang: langNow()};
    for (const button of panel.querySelectorAll("button[data-v]")) {
      const on = state[button.parentNode.dataset.key] === button.dataset.v;
      button.classList.toggle("on", on);
      button.setAttribute("aria-pressed", on ? "true" : "false");
    }
  }
  const settingsOpen = () => Boolean(panel) && !panel.hidden;
  function openSettings() {
    if (open()) closePalette(true);
    if (!panel) buildSettings();
    syncSettings();
    panel.hidden = false;
    gear.setAttribute("aria-expanded", "true");
    if (typeof WALL !== "undefined") WALL.opened();
    const first = panel.querySelector("button.on") || panel.querySelector("button");
    if (first) first.focus({preventScroll: true});
  }
  function closeSettings(focusGear) {
    if (!settingsOpen()) return;
    panel.hidden = true;
    gear.setAttribute("aria-expanded", "false");
    if (focusGear) gear.focus();
  }

  // ---------- the two fixed buttons ----------
  function buildFixed() {
    const pill = h("button", {type: "button", class: "sh-pill", "aria-label": t("board.shell.search") + " " + mod + " K", title: t("board.shell.search") + " (" + mod + " K)"}, icon("search"), h("span", null, t("board.shell.search")), h("kbd", null, mod + " K"));
    pill.addEventListener("click", () => (open() ? closePalette() : openPalette()));
    gear = h("button", {type: "button", class: "sh-gear", "aria-label": t("board.shell.gear"), title: t("board.shell.gear"), "aria-expanded": "false", "aria-haspopup": "dialog"}, icon("gear"));
    gear.addEventListener("click", () => (settingsOpen() ? closeSettings() : openSettings()));
    document.body.append(pill, gear);
  }

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && (event.key === "k" || event.key === "K")) {
      // From anywhere, a box included: the key carries a modifier, so it never collides with typing (the plain keys, like R of the reply pill, stay off in a box).
      event.preventDefault();
      if (open()) closePalette(); else openPalette();
      return;
    }
    if (open()) {
      if (event.key === "Escape") { event.preventDefault(); closePalette(); }
      else if (event.key === "ArrowDown") { event.preventDefault(); at = items.length ? (at + 1) % items.length : 0; mark(); }
      else if (event.key === "ArrowUp") { event.preventDefault(); at = items.length ? (at - 1 + items.length) % items.length : 0; mark(); }
      else if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); run(at); }
      else if (event.key === "Tab") { event.preventDefault(); input.focus(); }
      return;
    }
    if (settingsOpen() && event.key === "Escape") { event.preventDefault(); closeSettings(true); }
  });
  document.addEventListener("mousedown", (event) => {
    if (settingsOpen() && !panel.contains(event.target) && !gear.contains(event.target)) closeSettings();
  });

  // ---------- VS Code: one state ----------
  // The server's thread keeps {ready, bound, unbound, why} (vslink.status) and every poll brings it. vs(status) is the one place that reads it: the class `vs-down` on <html> (the VS Code
  // button and the buttons that talk to the chat are dimmed, the header pill turns amber) and the banner. The banner is in the page flow under the header and covers nothing. It shows only for a
  // link that WAS up (seen on this page, or earlier in this tab) and dropped; a link switched off, or one that never came up, only shows in the pill. It clears itself when the link returns.
  // Nobody is thrown out: nothing here navigates, closes a dialog or empties a field.
  let banner = null, bannerText = null, wasUp = tabKeep.get("harness.vs.up") === "1";
  function vs(status) {
    if (!status) return;
    const down = !status.ready;
    root.classList.toggle("vs-down", down);
    if (status.ready && !wasUp) { wasUp = true; tabKeep.set("harness.vs.up", "1"); }
    const show = down && wasUp && status.why !== "off";
    const text = show ? t("board.shell.vs.down") + (status.why && status.why !== "lost" ? " " + t("board.vs.why." + status.why) : "") : "";
    if (banner) {
      if (bannerText.textContent !== text) bannerText.textContent = text;
      if (banner.hidden === show) banner.hidden = !show;
    }
  }
  // The node a page puts under its header on every drawing (the same node each time, so a redraw does not blink it).
  function bannerNode() {
    if (!banner) {
      bannerText = h("span", null);
      banner = h("div", {class: "vs-banner", role: "status", hidden: "hidden"}, h("i"), bannerText);
    }
    return banner;
  }
  // Is VS Code linked: green when the board reads its chats, amber when not. The title says why.
  // `chat`, on a task page: VS Code being linked says nothing about this task when it has no chat.
  function vsPill(status, chat) {
    if (!served || !status) return null;
    const on = Boolean(status.ready), alone = on && chat && !chat.bound;
    return h("span", {class: "vs-pill" + (on ? " on" : "") + (alone ? " alone" : ""), title: alone ? t("board.vs.nochat") : on ? t("board.vscode.tip.ready", {bound: status.bound, unbound: status.unbound}) : t("board.vs.why." + (status.why || "starting"))},
      h("i"), t(alone ? "board.vscode.nochat" : on ? "board.vscode.ready" : "board.vscode.off"));
  }

  buildFixed();
  if (tabKeep.get("harness.reopen") === "settings") { tabKeep.set("harness.reopen", null); openSettings(); }  // the page loaded again after a language change: the panel comes back

  return {provide, visit, vs, banner: bannerNode, vsPill, openPalette, closePalette, openSettings, closeSettings, isOpen: () => open() || settingsOpen()};
})();
