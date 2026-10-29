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
  let asOf = DATA.as_of;
  const canArchive = typeof SERVE !== "undefined" && SERVE.runs("archive");
  const selected = new Set();  // closed tasks the person ticked, to archive together
  let shown = JSON.stringify([rows, hidden]);
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
  // Time, AIU, prompts and checks of a task that went through several rounds: all of them, or only the current one (brief.current).
  let current = keep.get("rounds", "all") === "current";
  const figures = (row) => (row.brief && current && row.brief.current ? row.brief.current : row.brief);

  const matches = Object.fromEntries(FILTERS.map((name) => [name, name === "all" ? () => true : (row) => stateOf(row, live) === name]));
  const ORDER = ["waiting", "working", "quiet", "unheld", "paused", "closed", "new"];
  const rank = (row) => ORDER.indexOf(stateOf(row, live));
  const kindText = (row) => (row.status === "new" ? "-" : t("task.kind." + (row.kind || "none")));
  // The columns that sort: the value of a row, and whether a bigger number comes first on the first click.
  const COLUMNS = {
    task: {label: () => t("board.col.task"), value: (row) => row.name.toLowerCase()},
    kind: {label: () => t("board.col.kind"), value: (row) => kindText(row).toLowerCase()},
    waiting: {label: () => t("board.col.waiting"), value: rank},
    waited: {label: () => t("board.col.waited"), value: (row) => (row.waiting ? row.waited_s : null), numeric: true},
    time: {label: () => t("board.col.time"), value: (row) => (figures(row) ? figures(row).active_s + figures(row).waiting_s : null), numeric: true},
    aiu: {label: () => "AIU", value: (row) => (figures(row) ? figures(row).aiu : null), numeric: true},
    prompts: {label: () => t("board.col.prompts"), value: (row) => (figures(row) ? figures(row).prompts : null), numeric: true},
    reviews: {label: () => t("board.col.reviews"), value: (row) => (figures(row) ? figures(row).reviews : null), numeric: true},
    updated: {label: () => t("board.col.updated"), value: (row) => row.updated_at || null},
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
    return found;
  }

  function sortBy(key) {
    const column = COLUMNS[key];
    if (view.key !== key) { view.key = key; view.dir = column.numeric ? -1 : 1; }  // numbers: the biggest first
    else if (view.dir === (column.numeric ? -1 : 1)) view.dir = -view.dir;
    else view.key = "";  // a third click goes back to the order the server gave
    keep.set("sort", view.key);
    keep.set("dir", String(view.dir));
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

  function actionCell(row) {
    const buttons = (row.actions || []).map((item) => actionButton(row, item));
    return h("td", {class: "acts"}, buttons.length ? h("div", {class: "act-strip"}, buttons) : "-");  // one line that scrolls sideways, so a row stays as low as the others
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

  function line(row, longest) {
    const brief = figures(row);
    const kind = row.status === "new" ? "-" : t("task.kind." + (row.kind || "none")) + " \u00b7 " + t("task.tier." + (row.tier || "none"));
    return h("tr", {class: [row.status === "closed" ? "closed" : "", touched.has(row.name) ? "touched" : ""].join(" ").trim() || null, "data-name": row.name},
      canArchive ? tickCell(row) : null,
      h("td", {class: "name"}, DATA.serve && row.status !== "new" ? h("a", {href: "/task/" + encodeURIComponent(row.name)}, row.name)
        : row.report ? h("a", {href: row.report.split("/").map(encodeURIComponent).join("/")}, row.name) : row.name,
        row.depends_on && row.depends_on.length ? h("div", {class: "sub"}, t("board.depends", {names: row.depends_on.join("\u3001")})) : null),
      h("td", {class: "kind"}, kind), h("td", {class: "state"}, state(row)),
      num(row.waiting && row.waited_s !== null ? clock(row.waited_s) : "-"),
      brief
        ? [h("td", {style: "width:18%"}, bar([
            ["work", brief.active_s, t("report.active") + " " + clock(brief.active_s)],
            ["wait", brief.waiting_s, t("report.waiting") + " " + clock(brief.waiting_s)]], longest, true)),
          num(clock(brief.active_s)), num(amount(brief.aiu)), num(brief.prompts), num(brief.reviews ? reviewsText(brief.reviews, brief.review_fails) : "-")]
        : [h("td"), num("-"), num("-"), num("-"), num("-")],
      h("td", {class: "sub when"}, when(row.updated_at, 5, 16)), actionCell(row));
  }

  // --- the page: drawn once, then its parts are drawn again when the rows change ----------------------------------
  const kpis = h("div", {class: "kpis"});
  const chips = h("div", {class: "chips"});
  const kinds = h("select", {class: "kinds", title: t("board.filter.kind")});
  const search = h("input", {type: "search", class: "search", placeholder: t("board.search"), autocomplete: "off", spellcheck: "false", value: view.query});
  const pick = h("div", {class: "pick"});
  const roundBox = h("div", {class: "chips", role: "group", title: t("board.rounds.hint")});
  const tableBox = h("div", {class: "card"});
  const more = h("p", {class: "sub"});
  const stamp = h("span");
  document.querySelector("main").classList.add("wide");

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
    stamp.textContent = subtitle();
    more.textContent = hidden ? t("board.closed.more", {count: hidden}) : "";
    if (!rows.length) { tableBox.replaceChildren(h("div", {class: "empty"}, t("board.empty"))); return; }
    const shownRows = listed();
    const before = rowTops();
    touched = new Set(rows.filter((row) => row.status === "open" && seen.has(row.name) && seen.get(row.name) !== row.updated_at).map((row) => row.name));
    seen = new Map(rows.map((row) => [row.name, row.updated_at]));
    const briefs = rows.filter((row) => row.brief).map(figures);
    const longest = Math.max(0, ...briefs.map((brief) => brief.active_s + brief.waiting_s)) || 1;
    if (!shownRows.length) { tableBox.replaceChildren(h("div", {class: "empty"}, t("board.filter.none"))); return; }
    tableBox.replaceChildren(
      table([canArchive ? headerTick(shownRows) : null, header("task"), header("kind"), header("waiting"), header("waited", true), header("time"), th("", true), header("aiu", true), header("prompts", true), header("reviews", true), header("updated"), th(t("board.col.actions"))],
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
    shift.replaceChildren(button("offwork", off, "board.offwork", "board.offwork.hint"), button("onwork", on, "board.onwork", "board.onwork.hint"));
  }
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
  const lobby = Lobby.create({href: (row) => (DATA.serve && row.status !== "new" ? "/task/" + encodeURIComponent(row.name)
    : row.report ? row.report.split("/").map(encodeURIComponent).join("/") : "")});
  let mode = keep.get("mode", "lobby") === "list" ? "list" : "lobby";
  const controls = h("div", {class: "controls"}, chips, roundBox, kinds, search, clear);
  const modeButtons = {};
  const seg = h("div", {class: "lb-seg", role: "group"}, ["lobby", "list"].map((name) => {
    const button = h("button", {type: "button"}, t(name === "lobby" ? "board.mode.lobby" : "board.mode.list"));
    button.addEventListener("click", () => { mode = name; keep.set("mode", name); drawMode(); });
    modeButtons[name] = button;
    return button;
  }));
  function drawMode() {
    for (const name of Object.keys(modeButtons)) modeButtons[name].classList.toggle("on", name === mode);
    const asList = mode === "list";
    for (const part of [kpis, controls, pick, tableBox, more]) part.hidden = !asList;
    lobby.node.hidden = asList;
  }

  app.replaceChildren(
    h("div", {class: "lb-top"}, h("div", null, h("h1", null, t("board.brand")), h("div", {class: "sub"}, h("b", null, t("board.title")), " \u00b7 ", stamp)), h("div", {class: "lb-right"}, shift, seg)), said,
    kpis, controls, lobby.node,
    pick, tableBox, more,
    h("footer", null, t("board.footer"), " ", t(DATA.serve ? "board.copy.hint.served" : "board.copy.hint")), copyright());
  draw();
  drawMode();

  function refresh() {
    if (typeof SERVE === "undefined") return Promise.resolve();
    return SERVE.post("/api/board", {}).then((data) => {
      asOf = data.as_of;
      archiveTo = data.archive_to || "";
      const text = JSON.stringify([data.rows, data.hidden]);
      if (text !== shown) { rows = data.rows; hidden = data.hidden; shown = text; draw(); } else stamp.textContent = subtitle();
    }, () => {});
  }
  if (typeof SERVE !== "undefined") {
    SERVE.start(app);
    SERVE.onChange(refresh);  // after a click the board is asked again in place, and the robots slide (a reload draws them from nothing)
    if (DATA.serve.refresh) setInterval(() => { if (!SERVE.busy()) refresh(); }, DATA.serve.refresh * 1000);
  }
})();
