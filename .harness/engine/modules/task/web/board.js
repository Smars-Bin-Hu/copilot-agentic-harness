// The board: every task, what it waits for, its time and usage. DATA.rows is what `task list` gives, each row with
// `brief` (a few numbers of the task, or null) and `report` (the path of its page from the board's folder, or "").
// `actions`: what the person can do about the task, each with the command to paste in a terminal.
// DATA.hidden: how many older closed tasks are not in the rows.
// The person filters by state and kind, searches by name, and sorts by a column; the choice is kept in this browser.
// DATA.refresh: the seconds between two boards while `task board --refresh` runs, or 0.
// DATA.serve: set when `task board` serves the page, with serve.js (SERVE) before this script. The page then asks the server
// for the rows every few seconds and draws them again, keeping what the person typed.
"use strict";

(function () {
  let rows = DATA.rows;
  let hidden = DATA.hidden || 0;
  let archiveTo = DATA.serve ? DATA.serve.archive_to || "" : "";
  let vscode = DATA.serve ? DATA.serve.vscode || null : null;  // {ready, bound, unbound, why}: the link to VS Code (the server's thread keeps it)
  let asOf = DATA.as_of;
  const canArchive = typeof SERVE !== "undefined" && SERVE.runs("archive");
  const selected = new Set();  // closed tasks the person ticked, to archive together
  let shown = JSON.stringify([rows, hidden, vscode]);
  let hovering = false;  // the pointer is over the list: a refresh updates the cells but keeps the row order, so no row jumps under a click
  let held = null;  // the order of the rows (their names) at the last drawing
  const app = document.getElementById("app");
  const sum = (values) => values.reduce((total, value) => total + value, 0);

  // What the person chose stays in this browser; where that is not allowed, it stays until the page closes.
  const memory = {};
  const keep = {
    get(name, fallback) { try { const value = localStorage.getItem("harness.board." + name); return value === null ? fallback : value; } catch (error) { return name in memory ? memory[name] : fallback; } },
    set(name, value) { memory[name] = value; try { localStorage.setItem("harness.board." + name, value); } catch (error) { /* kept in memory only */ } },
  };
  const FILTERS = ["all", "waiting", "working", "quiet", "unheld", "paused", "closed"];
  const view = {filter: keep.get("filter", "all"), kind: keep.get("kind", ""), query: keep.get("query", ""), key: keep.get("sort", ""), dir: Number(keep.get("dir", "1")) || 1};
  if (!FILTERS.includes(view.filter)) view.filter = "all";
  // Time, Credits, prompts and checks of a task that went through several rounds: all of them, or only the current one (brief.current).
  let current = keep.get("rounds", "all") === "current";
  const figures = (row) => (row.brief && current && row.brief.current ? row.brief.current : row.brief);

  const matches = Object.fromEntries(FILTERS.map((name) => [name, name === "all" ? () => true : (row) => stateOf(row, live) === name]));
  const ORDER = ["broken", "waiting", "working", "quiet", "unheld", "paused", "closed", "new"];
  const rank = (row) => ORDER.indexOf(stateOf(row, live));
  const kindText = (row) => (row.status === "new" ? "-" : t("task.kind." + (row.kind || "none")));
  // The columns that sort: the value of a row, and whether a bigger number comes first on the first click.
  const COLUMNS = {
    task: {label: () => t("board.col.task"), value: (row) => row.name.toLowerCase()},
    waiting: {label: () => t("board.col.waiting"), value: rank},
    waited: {label: () => t("board.col.waited"), value: (row) => (row.waiting ? row.waited_s : null), numeric: true},
    time: {label: () => t("board.col.time"), value: (row) => (figures(row) ? figures(row).active_s + figures(row).waiting_s : null), numeric: true},
    aiu: {label: () => t("board.col.credits"), value: (row) => (figures(row) ? figures(row).aiu : null), numeric: true},
    prompts: {label: () => t("board.col.prompts"), value: (row) => (figures(row) ? figures(row).prompts : null), numeric: true},
    reviews: {label: () => t("board.col.reviews"), value: (row) => (row.checks && row.checks.n ? row.checks.n : null), numeric: true},
  };

  function listed() {
    const query = view.query.trim().toLowerCase();
    let found = rows.filter((row) => matches[view.filter](row) && (!view.kind || row.kind === view.kind)
      && (!query || (row.name + " " + kindText(row)).toLowerCase().includes(query)));
    const column = COLUMNS[view.key];
    if (column) {
      found = found.map((row, index) => ({row, index, value: column.value(row)}));
      found.sort((a, b) => {
        if (a.value === null || a.value === undefined) return b.value === null || b.value === undefined ? a.index - b.index : 1;  // no value: last, either way
        if (b.value === null || b.value === undefined) return -1;
        const order = a.value < b.value ? -1 : a.value > b.value ? 1 : 0;
        return order * view.dir || a.index - b.index;
      });
      found = found.map((item) => item.row);
    }
    if (hovering && held) {  // rows seen before keep their place; a new one goes last
      const place = (row) => { const at = held.indexOf(row.name); return at < 0 ? held.length : at; };
      found = found.map((row, index) => ({row, index})).sort((a, b) => place(a.row) - place(b.row) || a.index - b.index).map((item) => item.row);
    }
    held = found.map((row) => row.name);
    return found;
  }

  function sortBy(key) {
    const column = COLUMNS[key];
    if (view.key !== key) { view.key = key; view.dir = column.numeric ? -1 : 1; }  // numbers: the biggest first
    else if (view.dir === (column.numeric ? -1 : 1)) view.dir = -view.dir;
    else view.key = "";  // a third click goes back to the order the server gave
    keep.set("sort", view.key);
    keep.set("dir", String(view.dir));
    held = null;  // a click on a head sorts at once, pointer over the list or not
    drawTable();
  }

  function header(key, numeric) {
    const column = COLUMNS[key];
    const on = view.key === key;
    const mark = on ? (view.dir === 1 ? " \u25b2" : " \u25bc") : "";
    const cell = h("th", {class: "sortable" + (numeric ? " num" : "") + (on ? " on" : ""), title: t("board.sort.hint"), "aria-sort": on ? (view.dir === 1 ? "ascending" : "descending") : "none"}, column.label() + mark);
    cell.addEventListener("click", () => sortBy(key));
    return cell;
  }

  // The box in the head ticks every closed task that is listed now, or none.
  function headerTick(shownRows) {
    const closed = shownRows.filter((row) => row.status === "closed").map((row) => row.name);
    if (!closed.length) return h("th", {class: "tick"});
    const box = h("input", {type: "checkbox", "aria-label": t("board.select.all")});
    box.checked = closed.every((name) => selected.has(name));
    box.addEventListener("change", () => { for (const name of closed) { box.checked ? selected.add(name) : selected.delete(name); } drawSelection(); drawTable(); });
    return h("th", {class: "tick"}, box);
  }

  // The actions of a row, in three classes (the first two are in the row, the last in the menu behind the three dots):
  // 1. what the task waits for now (orange: confirm, approve, recover...), 2. speaking to the agent at work (room is kept: a later block fills `.act-talk`),
  // 3. the rest (pause or resume, autorun, close, the checks, copy a command). A closed task has only "archive": shown at once.
  let openMenu = null, menuButton = null, placeCopy = null;
  // A refresh that comes while a menu is open waits (`later`): drawing the rows again would close the menu under the person's hand. It is drawn when the menu closes.
  let later = null;
  const closeMenu = (flush) => { if (openMenu) { openMenu.remove(); openMenu = null; menuButton = null; placeCopy = null; } if (flush !== false && later) { const data = later; later = null; apply(data); } };
  document.addEventListener("click", (event) => { if (openMenu && !openMenu.contains(event.target) && !event.target.closest(".act-more")) closeMenu(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeMenu(); });
  // The list scrolls sideways inside its own box, and that box cuts off whatever leaves it: the menu of a row hangs from the page, beside its button. The lobby card has no such box, and its
  // menu stays in the card, because the pointer must not leave the card to reach it.
  function hangMenu() {
    if (openMenu && openMenu.classList.contains("hung")) {
      const at = menuButton.getBoundingClientRect(), width = openMenu.offsetWidth, height = openMenu.offsetHeight, gap = 4, edge = 8;
      openMenu.style.left = Math.max(edge, Math.min(at.right - width, window.innerWidth - width - edge)) + "px";
      openMenu.style.top = Math.max(edge, at.bottom + gap + height <= window.innerHeight - edge ? at.bottom + gap : at.top - gap - height) + "px";
    }
    if (placeCopy) placeCopy();
  }
  // "Copy command" opens beside the menu, on the side that has room. It stays a child of the menu, so a click in it is a click in the menu and the pointer stays in the lobby card;
  // `fixed` takes it out of a menu that scrolls. A card can be the frame of a fixed box, so 0,0 is measured first.
  function hangCopy(menu, toggle, copy) {
    copy.style.left = copy.style.top = "0px";
    const zero = copy.getBoundingClientRect(), box = menu.getBoundingClientRect(), item = toggle.getBoundingClientRect(), gap = 4, edge = 8;
    const left = box.right + gap + zero.width <= window.innerWidth - edge ? box.right + gap : Math.max(edge, box.left - gap - zero.width);
    const top = Math.max(edge, Math.min(item.top - 7, window.innerHeight - edge - zero.height));  // 7: its padding and border, so the first line is level with the item
    copy.style.left = left - zero.left + "px";
    copy.style.top = top - zero.top + "px";
  }
  document.addEventListener("scroll", hangMenu, {capture: true, passive: true});  // capture: the sideways scroll of the list's box does not bubble
  window.addEventListener("resize", hangMenu);

  function menuFor(row, items, more) {
    const menu = h("div", {class: "act-menu", role: "menu"});
    const groups = [["board.menu.task", items.filter((item) => CONTROLS.includes(item.action))], ["board.menu.checks", items.filter((item) => !CONTROLS.includes(item.action))]];
    for (const [title, list] of groups) {
      if (!list.length) continue;
      menu.append(h("div", {class: "menu-title"}, t(title)), ...list.map((item) => actionButton(row, item, "item")));
    }
    const copy = h("div", {class: "act-menu menu-copy", role: "menu", hidden: true});
    for (const item of items) {
      const label = t("board.action." + item.action.replace(" ", "-"));
      const line = h("button", {type: "button", class: "act item", title: item.command, "data-label": label}, label + " \u2192 " + item.command);
      line.dataset.label = label + " \u2192 " + item.command;
      line.addEventListener("click", () => copyCommand(line, item.command));
      copy.append(line);
    }
    const toggle = h("button", {type: "button", class: "act item menu-more", "aria-haspopup": "menu", "aria-expanded": "false"}, t("board.menu.copy"), h("span", {class: "menu-arrow", "aria-hidden": "true"}, "\u203a"));
    const show = (on) => {
      copy.hidden = !on;
      toggle.classList.toggle("open", on);
      toggle.setAttribute("aria-expanded", String(on));
      placeCopy = on ? () => hangCopy(menu, toggle, copy) : null;
      if (on) placeCopy();
    };
    toggle.addEventListener("mouseenter", () => show(true));
    toggle.addEventListener("click", (event) => { show(true); if (!event.detail) copy.querySelector("button").focus(); });  // detail 0: the keyboard
    menu.addEventListener("mouseover", (event) => { const item = event.target.closest(".act"); if (item && item !== toggle && !copy.contains(item)) show(false); });
    menu.append(h("div", {class: "menu-title"}), toggle, copy);
    return menu;
  }

  // The buttons of a row as one strip (also the lobby card's): what the task waits for, what is said to the agent, and the menu behind the three dots. Null: no action.
  function actionStrip(row) {
    const items = row.actions || [];
    if (!items.length) return null;
    const first = items.find((item) => isHot(row, item));  // the others go behind the three dots: a second button takes its width from the State column of every row
    const direct = items.filter((item) => item.action === "archive" || item === first);
    const talk = items.filter((item) => TALK.includes(item.action));
    const rest = items.filter((item) => !direct.includes(item) && !talk.includes(item));
    const nodes = direct.map((item) => actionButton(row, item));
    nodes.push(h("span", {class: "act-talk"}, talk.map((item) => actionButton(row, item))));
    if (rest.length) {
      const more = h("button", {type: "button", class: "act act-more", title: t("board.menu.more"), "aria-haspopup": "menu", "aria-label": t("board.menu.more")}, "\u22ef");
      more.addEventListener("click", () => {
        const again = menuButton === more;
        closeMenu(again);
        if (again) return;
        openMenu = menuFor(row, rest, more);
        menuButton = more;
        if (more.closest(".scroll")) { openMenu.classList.add("hung"); document.body.append(openMenu); hangMenu(); }
        else more.after(openMenu);
      });
      nodes.push(more);
    }
    return h("div", {class: "act-strip"}, nodes);
  }
  function actionCell(row) {
    const strip = actionStrip(row);
    return strip ? h("td", {class: "acts"}, strip) : h("td", {class: "acts"}, "-");
  }

  function state(row) {
    const node = stateTag(row, live);
    return /\b(run|hot)\b/.test(node.className) ? inPhase(node) : node;  // a tag that moves starts where the clock says it is
  }
  const live = Boolean(DATA.serve || DATA.refresh);

  // The motion of the state tags (page.css) has one period. A tag that is drawn again starts where the clock says it is,
  // not from the beginning, so a redraw does not make every tag flinch.
  const PERIOD_MS = 2400;
  const still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function inPhase(node) { node.style.setProperty("--t", (Date.now() % PERIOD_MS) + "ms"); return node; }

  function tickCell(row) {
    if (row.status !== "closed") return h("td", {class: "tick"});
    const box = h("input", {type: "checkbox", "aria-label": row.name});
    box.checked = selected.has(row.name);
    box.addEventListener("change", () => { box.checked ? selected.add(row.name) : selected.delete(row.name); drawSelection(); });
    return h("td", {class: "tick"}, box);
  }

  // The line under a task name (1.6.14): small status marks (status.js): model, context, run time of the latest turn, stage, TODO. A mark with no data is left empty; the line is as high
  // for every row. `row.sub` (the last tool or reply) is still in the data, for the task page; the list no longer draws it.
  function statusLine(row) {
    return Status.row(row, {live});
  }

  // The warning tag after the state (B74): only when a health rule fired; the mouse over it says which and why.
  function warnTag(row) {
    if (!row.warn || !row.warn.length) return null;
    return h("span", {class: "tag warn", title: row.warn.map((item) => t("board.warn." + item.rule, {n: item.n})).join("\n"), "aria-label": t("board.warn.label")}, "\u26a0");
  }

  function line(row, longest) {
    const brief = figures(row);
    return h("tr", {class: [row.status === "closed" ? "closed" : "", touched.has(row.name) ? "touched" : ""].join(" ").trim() || null, "data-name": row.name},
      canArchive ? tickCell(row) : null,
      h("td", {class: "name"},
        h("div", {class: "name-line"}, kindIcon(row.kind || "other", row.status === "new" ? t("task.kind.none") : t("task.kind." + (row.kind || "none"))),
          DATA.serve ? h("a", {href: "/task/" + encodeURIComponent(row.name), title: row.name}, row.name)
            : row.report ? h("a", {href: row.report.split("/").map(encodeURIComponent).join("/"), title: row.name}, row.name) : h("span", {title: row.name}, row.name),
          DATA.serve && row.status === "open" ? SERVE.vsButton(row.chat) : null),
        statusLine(row)),
      h("td", {class: "state"}, state(row), warnTag(row) ? [" ", warnTag(row)] : null),
      h("td", {class: "checks"}, row.status === "new" ? "-" : checkDots(row)),
      num(row.waiting && row.waited_s !== null ? clock(row.waited_s) : "-"),
      actionCell(row),
      brief
        ? [h("td", {style: "width:6%"}, bar([
            ["work", brief.active_s, t("report.active") + " " + clock(brief.active_s)],
            ["wait", brief.waiting_s, t("report.waiting") + " " + clock(brief.waiting_s)]], longest, true)),
          num(clock(brief.active_s)), num(amount(brief.aiu)), num(brief.prompts)]
        : [h("td"), num("-"), num("-"), num("-")]);
  }

  // --- the page: drawn once, then its parts are drawn again when the rows change ----------------------------------
  const kpis = h("div", {class: "kpis"});
  const chips = h("div", {class: "chips"});
  const kinds = h("select", {class: "kinds", title: t("board.filter.kind")});
  const search = h("input", {type: "search", class: "search", placeholder: t("board.search"), autocomplete: "off", spellcheck: "false", value: view.query});
  const pick = h("div", {class: "pick"});
  const roundBox = h("div", {class: "chips", role: "group", title: t("board.rounds.hint")});
  const tableBox = h("div", {class: "card board-list"});
  tableBox.addEventListener("mouseenter", () => { hovering = true; });
  tableBox.addEventListener("mouseleave", () => { hovering = false; });
  const more = h("p", {class: "sub"});
  const stamp = h("span");
  const boardName = h("b", null, t("board.title"));
  const newSlot = h("span", {class: "new-slot"});  // the main act of the board: the far end of the header, filled
  const statusBox = h("span", {class: "lb-status"});  // a served board: VS Code and the pairing. The time of the numbers is a tip on the name: the page keeps itself fresh
  const stampNote = h("span");  // a page on disk says in the footer how to get fresher numbers; the header has room for the time only
  document.querySelector("main").classList.add("wide");

  const paintStamp = () => { stamp.textContent = t("board.stamp", {as_of: when(asOf, 0, 19)}); stamp.title = subtitle(); stampNote.textContent = subtitle(); if (DATA.serve) boardName.title = t("board.stamp", {as_of: when(asOf, 0, 19)}) + ". " + subtitle(); };
  const subtitle = () => (DATA.serve ? t("board.subtitle.served", {as_of: when(asOf, 0, 19), seconds: DATA.serve.refresh})
    : t(DATA.refresh ? "board.subtitle.fresh" : "board.subtitle", {as_of: when(asOf, 0, 19), seconds: DATA.refresh}));

  function drawNumbers() {
    const waiting = rows.filter((row) => stateOf(row, live) === "waiting");  // what the chip "Waiting for you" counts too
    const briefs = rows.filter((row) => row.brief).map(figures);
    const usage = briefs.filter((brief) => brief.aiu !== null).map((brief) => brief.aiu);
    kpis.replaceChildren(
      kpi(rows.filter((row) => row.status === "open").length, t("board.kpi.open")),
      kpi(waiting.length, t("board.kpi.waiting")),
      kpi(waiting.length ? clock(Math.max(...waiting.map((row) => row.waited_s || 0))) : "-", t("board.kpi.longest")),
      kpi(clock(sum(briefs.map((brief) => brief.active_s))), t("board.kpi.active")),
      kpi(usage.length ? amount(sum(usage)) : "-", t("board.kpi.aiu")));
  }

  function drawControls() {
    chips.replaceChildren(...FILTERS.map((name) => {
      const count = rows.filter(matches[name]).length;
      const chip = h("button", {type: "button", class: "chip" + (view.filter === name ? " on" : "")}, t("board.filter." + name) + " " + count);
      chip.addEventListener("click", () => { view.filter = name; keep.set("filter", name); drawControls(); drawTable(); });
      return chip;
    }));
    const several = rows.some((row) => row.brief && row.brief.current);  // the toggle is there only when some task has more than one round
    roundBox.hidden = !several;
    roundBox.replaceChildren(...(several ? [false, true] : []).map((only) => {
      const chip = h("button", {type: "button", class: "chip" + (current === only ? " on" : "")}, t(only ? "board.rounds.current" : "board.rounds.all"));
      chip.addEventListener("click", () => { current = only; keep.set("rounds", only ? "current" : "all"); drawNumbers(); drawControls(); drawTable(); });
      return chip;
    }));
    const found = [...new Set(rows.filter((row) => row.status !== "new" && row.kind).map((row) => row.kind))].sort();
    if (view.kind && !found.includes(view.kind)) view.kind = "";
    const options = ["", ...found];
    if (Array.from(kinds.options).map((option) => option.value).join("|") !== options.join("|")) {  // not while the person has it open
      kinds.replaceChildren(...options.map((kind) => h("option", {value: kind}, kind ? t("task.kind." + kind) : t("board.filter.kind"))));
    }
    kinds.value = view.kind;
  }

  function drawTable() {
    if (canArchive) DATA.serve.archive_to = archiveTo;  // the single-row button reads it
    paintStamp();
    more.textContent = hidden ? t("board.closed.more", {count: hidden}) : "";
    if (!rows.length) { tableBox.replaceChildren(firstTask()); return; }
    const shownRows = listed();
    const before = rowTops();
    touched = new Set(rows.filter((row) => row.status === "open" && seen.has(row.name) && seen.get(row.name) !== row.updated_at).map((row) => row.name));
    seen = new Map(rows.map((row) => [row.name, row.updated_at]));
    const briefs = rows.filter((row) => row.brief).map(figures);
    const longest = Math.max(0, ...briefs.map((brief) => brief.active_s + brief.waiting_s)) || 1;
    if (!shownRows.length) { tableBox.replaceChildren(h("div", {class: "empty"}, t("board.filter.none"))); return; }
    tableBox.replaceChildren(
      table([canArchive ? headerTick(shownRows) : null, header("task"), header("waiting"), header("reviews"), header("waited", true), th(t("board.col.actions")), header("time"), th("", true), header("aiu", true), header("prompts", true)],
        shownRows.map((row) => line(row, longest))),
      legend([["work", t("report.active"), ""], ["wait", t("report.waiting"), ""]]));
    slide(before);
  }

  // A task whose file was just written lights up once, and a row that moves slides to its new place instead of jumping.
  // `seen`: the updated_at of each task at the last draw (the first draw lights nothing).
  let seen = new Map(), touched = new Set();
  function rowTops() {
    const tops = new Map();
    for (const node of tableBox.querySelectorAll("tr[data-name]")) tops.set(node.getAttribute("data-name"), node.getBoundingClientRect().top);
    return tops;
  }
  function slide(before) {
    if (still || !before.size) return;
    for (const node of tableBox.querySelectorAll("tr[data-name]")) {
      const was = before.get(node.getAttribute("data-name"));
      const moved = was === undefined ? 0 : was - node.getBoundingClientRect().top;
      if (Math.abs(moved) > 1 && node.animate) node.animate([{transform: "translateY(" + moved + "px)"}, {transform: "none"}], {duration: 450, easing: "cubic-bezier(.2,.8,.2,1)"});
    }
  }

  // "N ticked": archive them together, or let go of them.
  function drawSelection() {
    for (const name of Array.from(selected)) { if (!rows.some((row) => row.name === name && row.status === "closed")) selected.delete(name); }
    if (!selected.size) { pick.replaceChildren(); return; }
    const go = h("button", {type: "button", class: "act hot"}, t("board.select.archive", {count: selected.size}));
    go.addEventListener("click", () => SERVE.archive(Array.from(selected), archiveTo));
    const none = h("button", {type: "button", class: "act"}, t("board.select.clear"));
    none.addEventListener("click", () => { selected.clear(); drawSelection(); drawTable(); });
    pick.replaceChildren(h("span", {class: "sub"}, t("board.select.count", {count: selected.size}) + " "), go, none);
  }

  // Off work and back to work (M38-2): every open task that is not at work is paused at once, and later only those are taken back.
  // Served, the buttons act (no pairing, as for pause); a page on disk copies the command instead.
  const shift = h("div", {class: "shift"});
  const said = h("div", {class: "sub shift-said"});
  const canShift = typeof SERVE !== "undefined" && SERVE.runs("pause");
  function drawShift() {
    const off = rows.filter((row) => row.status === "open" && !row.paused_since && !row.autorun && stateOf(row, live) !== "working").length;
    const on = rows.filter((row) => row.status === "open" && row.paused_by === "offwork").length;
    const button = (action, count, label, hint) => {
      const node = h("button", {type: "button", class: "act" + (count ? "" : " locked"), title: t(hint), "data-label": t(label, {count})}, t(label, {count}));
      if (!count) node.disabled = true;
      node.addEventListener("click", () => {
        if (!canShift) { copyCommand(node, cli + " task " + action); return; }
        node.disabled = true;
        SERVE.post("/api/act", {action, task: "", step: "act"}).then((data) => { said.textContent = data.result.next || ""; return refresh(); },
          (error) => { said.textContent = error.message || String(error); node.disabled = false; });
      });
      return node;
    };
    // replaceChildren writes a null as the word "null": on a page on disk, with no server, "New task" and the VS Code pill are not there (N4, 1.6.11).
    shift.replaceChildren(...[button("offwork", off, "board.offwork", "board.offwork.hint"), button("onwork", on, "board.onwork", "board.onwork.hint")]);
    newSlot.replaceChildren(...[rows.length ? newTask() : null].filter(Boolean));
    paintSetup(DATA.serve && DATA.serve.setup);
    statusBox.replaceChildren(...[SHELL.vsPill(vscode), typeof SERVE !== "undefined" ? SERVE.pairMark() : null].filter(Boolean));
  }
  // The big warning (1.6.59): what this copy lacks before it can do real work. It stays until that is set; a click opens the setup guide.
  const setupBar = h("a", {class: "setup-bar", href: "/setup", hidden: ""});
  function paintSetup(list) {
    const items = list || [];
    if (!setupBar.isConnected) { const top = document.querySelector(".lb-top"); if (top) top.after(setupBar); }
    setupBar.hidden = !items.length;
    const sig = items.join();
    if (setupBar.dataset.sig === sig) return;
    setupBar.dataset.sig = sig;
    setupBar.replaceChildren(h("i"), h("span", null, t("board.setup.warn", {n: items.length})), h("span", {class: "setup-more"}, items.map((key) => h("span", null, t("board.setup." + key)))));
  }
  // "New task" (1.6, B73): a served board only (it makes a chat in VS Code). The dialog is in chat.js.
  function newTask() {
    if (typeof SERVE === "undefined" || !SERVE.runs("create")) return null;
    const node = h("button", {type: "button", class: "act hot big new-task", title: t("board.new.hint")}, h("span", {class: "new-plus", "aria-hidden": "true"}, "+"), t("board.new"));
    node.addEventListener("click", () => CHAT.create());
    return node;
  }
  // No task at all (1.6.18): in the list and in the lobby a block with a large New task button (served), in place of a sentence. The dialog tells the reason when VS Code is not linked, so the button
  // stays. A page on disk cannot start a task: no button, and how to run the served board. With tasks, the small button of the header is the one; with none, only this one.
  function bigNewTask() {
    if (typeof SERVE === "undefined" || !SERVE.runs("create")) return null;
    const go = h("button", {type: "button", class: "act hot live first-go new-task", title: t("board.new.hint")}, t("board.new"));
    go.addEventListener("click", () => CHAT.create());
    return go;
  }
  function lessonLink() {
    const link = h("button", {type: "button", class: "first-link"}, t("board.empty.lesson"));
    link.addEventListener("click", () => DOCK.start("harness-rookie-quick-start", ""));
    return link;
  }
  function firstTask() {
    const go = bigNewTask(), served = Boolean(go);
    if (go) go.textContent = t("board.empty.own");
    const sample = served ? h("button", {type: "button", class: "act hot live first-go new-task"}, t("board.empty.sample")) : null;
    if (sample) { sample.addEventListener("click", () => CHAT.create(true)); go.classList.remove("hot"); }
    return h("div", {class: "first-task"}, h("h2", null, t(served ? "board.empty.title" : "board.empty.title.disk")),
      h("p", null, served ? t("board.empty.text") : t("board.empty.disk", {command: cli + " task board"})), served ? h("div", {class: "first-row"}, sample, go) : null, served ? lessonLink() : null);
  }
  // The pill that says whether VS Code is linked is SHELL.vsPill (shell.js): the same state as the banner and the dimmed buttons.
  const cli = DATA.cli || "harness";

  function draw() { drawNumbers(); drawControls(); drawTable(); drawSelection(); drawShift(); lobby.update(rows, live); }

  search.addEventListener("input", () => { view.query = search.value; keep.set("query", search.value); drawTable(); });
  kinds.addEventListener("change", () => { view.kind = kinds.value; keep.set("kind", view.kind); drawTable(); });
  const clear = h("button", {type: "button", class: "chip"}, t("board.filter.clear"));
  clear.addEventListener("click", () => {
    Object.assign(view, {filter: "all", kind: "", query: "", key: "", dir: 1});
    for (const name of ["filter", "kind", "query", "sort", "dir"]) keep.set(name, "");
    search.value = "";
    drawControls();
    drawTable();
  });

  // Two ways to look at the same rows: the lobby (the first screen) and the list. The choice stays in this browser.
  // The card of a robot (lobby.js) is the row of the list again: the same marks (status.js), the same numbers (`figures`), the same buttons (`actionStrip`).
  const lobby = Lobby.create({href: (row) => (DATA.serve && row.status !== "new" ? "/task/" + encodeURIComponent(row.name)
    : row.report ? row.report.split("/").map(encodeURIComponent).join("/") : ""), figures, actions: actionStrip, live, first: firstTask, go: bigNewTask});
  let mode = keep.get("mode", "lobby") === "list" ? "list" : "lobby";
  const controls = h("div", {class: "controls"}, chips, roundBox, kinds, search, clear);
  const modeButtons = {};
  const seg = h("div", {class: "lb-seg", role: "group"}, ["lobby", "list"].map((name) => {
    const button = h("button", {type: "button"}, t(name === "lobby" ? "board.mode.lobby" : "board.mode.list"));
    button.addEventListener("click", () => setMode(name));
    modeButtons[name] = button;
    return button;
  }));
  function setMode(name) { mode = name; keep.set("mode", name); drawMode(); }
  function drawMode() {
    for (const name of Object.keys(modeButtons)) modeButtons[name].classList.toggle("on", name === mode);
    const asList = mode === "list";
    for (const part of [kpis, controls, pick, tableBox, more]) part.hidden = !asList;
    lobby.node.hidden = asList;
    if (asList) lobby.hide();
  }

  app.replaceChildren(
    h("div", {class: "lb-top"}, h("div", null, h("h1", null, t("board.brand")), h("div", {class: "sub"}, boardName, DATA.serve ? [" \u00b7 ", statusBox] : [" \u00b7 ", stamp])), h("div", {class: "lb-right"}, shift, seg, newSlot)), SHELL.banner(), said,
    kpis, controls, lobby.node,
    pick, tableBox, more,
    h("footer", null, t("board.footer"), " ", t(DATA.serve ? "board.copy.hint.served" : "board.copy.hint"), DATA.serve ? null : " ", DATA.serve ? null : stampNote), copyright());
  draw();
  drawMode();
  SHELL.vs(vscode);
  // What Cmd+K can open on the board: its tasks, the two views and the filters (it only changes what is shown; it never acts on a task).
  SHELL.provide(() => ({tasks: rows,
    views: [{id: "list", label: t("board.shell.view.list"), kw: "list table", run: () => setMode("list")}, {id: "lobby", label: t("board.shell.view.lobby"), kw: "lobby robots floor", run: () => setMode("lobby")}],
    filters: FILTERS.map((name) => ({id: name, label: t("board.filter." + name), run: () => { view.filter = name; keep.set("filter", name); setMode("list"); drawControls(); drawTable(); }}))}));

  function refresh(strict) {  // strict: an unanswered request is thrown (the poll counts it); a click's refresh ignores it
    if (typeof SERVE === "undefined") return Promise.resolve();
    return SERVE.post("/api/board", {}).then((data) => {
      if (openMenu && strict === true) { later = data; return; }  // the poll waits; a click's refresh is the person's own act, the menu goes
      closeMenu(false);
      later = null;
      apply(data);
    }, (error) => { if (strict === true) throw error; });
  }
  function apply(data) {
    asOf = data.as_of;
    archiveTo = data.archive_to || "";
    SHELL.vs(data.vscode);
    if (DATA.serve) { DATA.serve.setup = data.setup; paintSetup(data.setup); }
    const text = JSON.stringify([data.rows, data.hidden, data.vscode || null]);
    if (text !== shown) { rows = data.rows; hidden = data.hidden; vscode = data.vscode || null; shown = text; draw(); } else paintStamp();
  }
  if (typeof SERVE !== "undefined") {
    SERVE.start(app);
    SERVE.onChange(refresh);  // after a click the board is asked again in place, and the robots slide (a reload draws them from nothing)
    if (DATA.serve.refresh) pollEvery(DATA.serve.refresh, () => (SERVE.busy() ? null : refresh(true)));
  }
})();
