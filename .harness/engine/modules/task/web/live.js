// The Live tab of a task page (1.6.17, B88): the latest items of the agent's chat, as they come. A served page only.
// The server keeps the chat in memory and gives the latest few items (`/api/live`: agent text, tool calls, thinking; every text redacted and cut there). This file asks once a second while the
// tab (or the reply panel) is open and the page is visible, and draws only what changed: an item that is already there is changed in place (its text, its state, its time), never made again, so
// no animation starts over and nothing jumps. A new item is added at the bottom; one that left the latest few is removed from the top. The page follows the bottom only if the person is there; a
// person who scrolled up to read is kept where they are (what is above the reading place changes height: the place is put back).
// The run times tick on the one timer of status.js (`.st-run[data-since]`); this file has no timer of its own for them. The text only grows or is replaced: new letters are added as a small piece that fades in.
// Needs common.js (h, t, clock), serve.js (SERVE), status.js (Status). Drawn with DOM nodes and textContent only.
"use strict";

const LIVE = (function () {
  const NS = "http://www.w3.org/2000/svg";
  const EVERY = 1000;  // ms between two answers and the next question
  const SLOW = 3000;  // after a failed one
  const LINK_DOWN = ["starting", "none", "no-cli", "cli-failed", "cli-slow", "many", "error", "lost", "off"];  // why the link to VS Code itself is not there (the other reasons are about this task's chat)

  const st = {task: "", rev: "", nodes: new Map(), groups: new Map(), wants: new Set(), timer: 0, busy: false, fails: 0, skew: 0, data: null, off: "", chat: null, held: [], approved: [], gates: [], marks: new Map(), listeners: [], needs: [], started: "", answer: false,
    // What the page has seen of the turn it shows (2026-11): `full` holds the last FULL version of every item by id; the order on the page is `head` (the person's message), then `older` (loaded with the button), then `tail` (from the answers).
    turn: "", have: -1, full: new Map(), head: "", older: [], tail: [], reach: 0, seen: false, epoch: 0, loadingOlder: false, hurry: false};
  const FOLD_AT = 320;  // a finished reply drawn higher than this (px) is folded to FOLD_TO


  const svg = (paths, size, cls) => {
    const node = document.createElementNS(NS, "svg");
    for (const [name, value] of Object.entries({viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", "stroke-width": "1.5", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", class: cls || ""})) node.setAttribute(name, value);
    if (size) { node.setAttribute("width", size); node.setAttribute("height", size); }
    for (const d of paths) { const part = document.createElementNS(NS, "path"); part.setAttribute("d", d); node.append(part); }
    return node;
  };
  const ICONS = {
    read: ["M4 2h5l3 3v9H4zM9 2v3h3"], edit: ["M3 13l1-3 7-7 2 2-7 7zM9.5 4.5l2 2"], run: ["M3 4l4 4-4 4M8 12h5"], search: ["M7 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM10 10l3 3"],
    web: ["M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2zM2 8h12M8 2c2 2 2 10 0 12M8 2c-2 2-2 10 0 12"],
    create: ["M4 2h5l3 3v9H4zM9 2v3h3M8 8v4M6 10h4"], agent: ["M2 2h5v5H2zM9 9h5v5H9zM4.5 7v3.5A1.5 1.5 0 0 0 6 12h3"], ring: ["M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2zM5.5 8h5"], other: ["M3 8h.01M8 8h.01M13 8h.01"], think: ["M8 2a4 4 0 0 0-2 7.5V11h4V9.5A4 4 0 0 0 8 2zM6.5 13.5h3"],
    tool: ["M10.5 2.5a3 3 0 0 0-3.8 3.8L2.5 10.5l3 3 4.2-4.2a3 3 0 0 0 3.8-3.8l-1.9 1.9-1.6-.4-.4-1.6z"], shield: ["M8 1.8l5.3 2v4.1c0 3-2.3 5.4-5.3 6.3-3-.9-5.3-3.3-5.3-6.3V3.8z"],
    ask: ["M3 3h10v7H8l-3 3v-3H3zM7 5.3a1.2 1.2 0 1 1 1.6 1.1c-.4.2-.6.5-.6.9M8 8.6h.01"], reader: ["M2.5 3.5h11v9h-11zM9.5 3.5v9"], bell: ["M4 11V7a4 4 0 1 1 8 0v4l1 1.5H3zM6.5 13.5a1.6 1.6 0 0 0 3 0"], compact: ["M3 4h10M5 8h6M7 12h2M8 1.5v1.5M8 13v1.5"], clock: ["M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2zM8 5v3l2 1.5"],
  };
  // The word of a kind (the server's `kind` of a tool item), written out so each message key is found by a search. `other` has none: it keeps the tool's own name.
  const KIND_WORD = {read: "desk.live.kind.read", search: "desk.live.kind.search", edit: "desk.live.kind.edit", create: "desk.live.kind.create", agent: "desk.live.kind.agent", web: "desk.live.kind.web", run: "desk.live.kind.run"};
  // The kind of a tool, from its name: only for the icon, and for an old item that has no `kind`. A name this does not know gets the three dots.
  function kindOf(tool, name) {
    const text = (tool + " " + name).toLowerCase();
    if (/(bash|shell|terminal|command|powershell|\brun\b|exec)/.test(text)) return "run";
    if (/(edit|write|patch|replace|create|apply|insert|delete|rename|move)/.test(text)) return "edit";
    if (/(grep|glob|search|find|list|\bls\b)/.test(text)) return "search";
    if (/(fetch|web|http|browse|url)/.test(text)) return "web";
    if (/(read|view|open|cat|get_file|file)/.test(text)) return "read";
    return "other";
  }
  const robot = () => {
    const node = document.createElementNS(NS, "svg");
    for (const [name, value] of Object.entries({viewBox: "0 0 32 32", class: "lv-rb", "aria-hidden": "true", fill: "none", stroke: "currentColor", "stroke-width": "1.4", "stroke-linecap": "round"})) node.setAttribute(name, value);
    const add = (tag, attrs) => { const part = document.createElementNS(NS, tag); for (const [name, value] of Object.entries(attrs)) part.setAttribute(name, String(value)); node.append(part); return part; };
    add("rect", {x: 6, y: 10, width: 20, height: 15, rx: 5});
    add("path", {d: "M16 10V6M12 28h8"});
    add("circle", {cx: 16, cy: 5, r: 1.6, class: "bulb", stroke: "none"});
    add("circle", {cx: 12, cy: 17, r: 1.7, class: "ey", stroke: "none"});
    add("circle", {cx: 20, cy: 17, r: 1.7, class: "ey", stroke: "none"});
    return node;
  };

  // --- the nodes made once ----------------------------------------------------------------------------------------------
  const link = h("button", {type: "button", class: "lv-link"}, t("desk.live.whole"));
  const head = h("div", {class: "lv-h"}, h("span", {class: "lv-t"}, t("desk.live.title")), h("span", {class: "sub lv-sub"}, t("desk.live.sub")), link);
  const earlier = h("button", {type: "button", class: "lv-earlier-btn"}, t("desk.live.earlier"));
  const earlierBad = h("span", {class: "bad lv-earlier-bad", role: "alert", hidden: ""});
  const earlierLi = h("li", {class: "lv-earlier", "data-id": "~earlier", hidden: ""}, earlier, earlierBad);  // right under the person's message: the older steps appear exactly there
  const needLi = h("li", {class: "fi fi-need", hidden: ""}, h("i", {class: "dot hot"}), h("div", {class: "lv-need"}));
  const feed = h("ol", {class: "lv-feed"}, needLi);
  const calm = h("div", {class: "lv-empty", hidden: ""});
  const stale = h("p", {class: "sub lv-stale", hidden: ""}, t("desk.live.stale"));
  const lifeLabel = h("span", {class: "lt-l"}), lifeSep = h("span", {class: "lt-s"}, " \u00b7 "), lifeRun = h("b", {class: "lt-r"}, h("span", {class: "st-time"}));
  const lifeDoing = h("span", {class: "lt-doing", hidden: ""});  // B15: what it does now, in a few words
  const lifeBack = h("button", {type: "button", class: "lt-back", hidden: "", "aria-expanded": "false"});  // B16: what runs on in the background; it opens to the list, a shell with Stop
  const backList = h("ul", {class: "lt-blist", hidden: ""});
  lifeBack.addEventListener("click", () => { backList.hidden = !backList.hidden; lifeBack.setAttribute("aria-expanded", String(!backList.hidden)); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !backList.hidden) { backList.hidden = true; lifeBack.setAttribute("aria-expanded", "false"); lifeBack.focus({preventScroll: true}); } });
  const life = h("div", {class: "lv-life calm"}, robot(), h("span", {class: "eq", "aria-hidden": "true"}, h("i"), h("i"), h("i"), h("i")), h("span", {class: "lt"}, lifeLabel, lifeSep, lifeRun), lifeDoing, lifeBack, backList);
  // B9: the title of the round stays at the top once its start is scrolled away: the first sentence of the person's words, the time, credits and calls as they go. A click goes back to the start.
  const barText = h("span", {class: "rb-t"});
  const barStats = h("span", {class: "rb-s"});
  const bar = h("button", {type: "button", class: "lv-roundbar", hidden: "", title: t("desk.live.bar.top")}, h("span", {class: "rb-n"}, t("desk.live.receipt.title")), barText, barStats);
  const barWrap = h("div", {class: "lv-rbwrap"}, bar);  // sticky and of no height: the title floats over the feed and moves nothing when it shows
  // B10: at the bottom, while what waits for the person is out of sight: how many wait and what, one click to their card; and Latest, back to the newest step
  const waitGo = h("button", {type: "button", class: "wb-go"});
  const waitList = h("span", {class: "wb-l"});
  const latestBtn = h("button", {type: "button", class: "wb-latest"}, h("span", {"aria-hidden": "true"}, "\u2193 "), t("desk.live.latest"));
  const waitBar = h("div", {class: "lv-waitbar", hidden: ""}, waitGo, waitList, latestBtn);
  const waitWrap = h("div", {class: "lv-wbwrap"}, waitBar);
  // B19, B20: one row over the round: show only the failed steps, the changes, the commands or what waits; and a search of the whole round, opened with / (Ctrl+F while the Live tab is shown)
  const FILTERS = ["all", "fail", "change", "run", "wait"];
  // written out so each message key is found by a search
  const FILTER_WORD = {all: "desk.live.filter.all", fail: "desk.live.filter.fail", change: "desk.live.filter.change", run: "desk.live.filter.run", wait: "desk.live.filter.wait"};
  const WHERE_WORD = {me: "desk.live.find.where.me", text: "desk.live.find.where.text", think: "desk.live.find.where.think", ask: "desk.live.find.where.ask", note: "desk.live.find.where.note",
    command: "desk.live.find.where.command", input: "desk.live.find.where.input", diff: "desk.live.find.where.diff", line: "desk.live.find.where.line"};
  const chipNodes = new Map(FILTERS.map((name) => [name, h("button", {type: "button", class: "lv-chip" + (name === "all" ? " on" : ""), "aria-pressed": String(name === "all"), "data-filter": name}, h("span", null, t(FILTER_WORD[name])), h("b", {class: "lv-chip-n"}))]));
  const findBtn = h("button", {type: "button", class: "lv-findbtn", title: t("desk.live.find.open"), "aria-label": t("desk.live.find.open"), "aria-keyshortcuts": "/"});
  const filterSaid = h("span", {class: "sub lv-filter-said", hidden: ""});
  const tools = h("div", {class: "lv-tools", hidden: "", role: "toolbar", "aria-label": t("desk.live.filter.label")}, ...chipNodes.values(), filterSaid, h("span", {class: "lv-tools-sp"}), findBtn);
  const findInput = h("input", {type: "search", class: "lv-find-in", placeholder: t("desk.live.find.ph"), "aria-label": t("desk.live.find.ph"), maxlength: "200", autocomplete: "off", spellcheck: "false"});
  const findN = h("span", {class: "lv-find-n", "aria-live": "polite"});
  const findUp = h("button", {type: "button", class: "lv-find-b", title: t("desk.live.find.prev"), "aria-label": t("desk.live.find.prev")}, "\u2191");
  const findDown = h("button", {type: "button", class: "lv-find-b", title: t("desk.live.find.next"), "aria-label": t("desk.live.find.next")}, "\u2193");
  const findShut = h("button", {type: "button", class: "lv-find-b", title: t("desk.live.find.close"), "aria-label": t("desk.live.find.close")}, "\u00d7");
  const findWhere = h("div", {class: "lv-find-where", hidden: ""});
  const findRow = h("div", {class: "lv-find", hidden: "", role: "search"}, h("div", {class: "lv-find-bar"}, findInput, findN, findUp, findDown, findShut), findWhere);
  const toolsWrap = h("div", {class: "lv-toolswrap"}, tools, findRow);
  // B18: where the person last looked, when they come back: a dashed line after that step, and what happened since
  const sinceText = h("span", {class: "lv-since-t"});
  const sinceSum = h("span", {class: "lv-since-s"});
  const sinceSeen = h("button", {type: "button", class: "lv-since-ok"}, t("desk.live.since.seen"));
  const sinceLi = h("li", {class: "lv-since", "data-id": "~since"}, h("div", {class: "lv-since-line"}, sinceText), h("div", {class: "lv-since-box"}, sinceSum, sinceSeen));
  const root = h("section", {class: "lv", hidden: ""}, head, stale, barWrap, toolsWrap, feed, waitWrap, calm, life);
  const roundsHere = (box) => { if (box.parentNode !== root) root.insertBefore(box, stale); };

  link.addEventListener("click", () => {
    link.disabled = true;
    SERVE.openVS().then(() => { setTimeout(() => { link.disabled = false; }, 1500); }, (error) => { link.disabled = false; SERVE.failed(error, st.chat && st.chat.title); });
  });

  // --- time -------------------------------------------------------------------------------------------------------------
  const seconds = (ms) => (ms < 10000 ? t("unit.seconds", {s: (Math.max(0, ms) / 1000).toFixed(1)}) : clock(ms / 1000));
  const since = (ms) => ms - st.skew;  // the server's clock to this page's

  // A running time: a node the one timer of status.js moves (`.st-run[data-since]` with a `.st-time` child). Set it, and write the first value now.
  function running(node, ms) {
    const value = String(Math.round(since(ms)));
    if (node.getAttribute("data-since") !== value) node.setAttribute("data-since", value);
    if (!node.classList.contains("st-run")) node.classList.add("st-run");
    const label = node.querySelector(".st-time");
    const text = clock(Math.max(0, (Date.now() - since(ms)) / 1000));
    if (label && label.textContent !== text) label.textContent = text;
  }
  function stopped(node) {
    if (node.hasAttribute("data-since")) node.removeAttribute("data-since");
    node.classList.remove("st-run");
  }
  const setText = (node, value) => { if (node.textContent !== value) node.textContent = value; };
  const setClass = (node, value) => { if (node.className !== value) node.className = value; };

  // --- a long reply folds -----------------------------------------------------------------------------------------------
  // A finished text drawn higher than FOLD_AT is folded (`lv-fold`: a fixed height with a fade) and has a pill under it. The height is the natural one (`scrollHeight`: the same folded or not), measured when the node is drawn;
  // one that is drawn while the tab is hidden has no height yet: the one ResizeObserver measures it when it gets one. The person's choice (`rec.open`) stays with the item.
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver((entries) => { for (const entry of entries) { const rec = st.folds.get(entry.target); if (rec) measure(rec); } }) : null;
  st.folds = new WeakMap();
  function applyFold(rec) {
    const on = rec.foldable && !rec.item.live;
    rec.tx.classList.toggle("lv-fold", on && !rec.open);
    rec.pill.hidden = !on;
    if (rec.read) rec.read.hidden = !on;  // a reply long enough to fold can be read in the side panel
    setText(rec.pill, t(rec.open ? "desk.live.fold.less" : "desk.live.fold.all"));
    rec.pill.setAttribute("aria-expanded", String(rec.open));
  }
  function measure(rec) {
    const item = rec.item;
    if (!item || (item.k !== "text" && item.k !== "think")) return;  // a reply, or an opened thought (its fold record: `rec.fold`)
    const natural = rec.tx.scrollHeight;
    if (!natural && !item.live) return;  // not shown (yet): the observer comes back when it is
    rec.foldable = Boolean(!item.live && !item.run && natural > FOLD_AT);
    applyFold(rec);
  }
  function watch(rec) {  // after each paint of a text
    if (ro) { if (!st.folds.has(rec.tx)) { st.folds.set(rec.tx, rec); ro.observe(rec.tx); } measure(rec); }
    else requestAnimationFrame(() => measure(rec));
  }
  function unwatch(rec) { if (ro && rec.tx) { ro.unobserve(rec.tx); st.folds.delete(rec.tx); } }
  function keepPill(rec) {  // folded again from far below: the pill is where the reader was, do not leave it above the window
    const box = rec.pill.getBoundingClientRect();
    if (!rec.pill.hidden && (box.bottom < 0 || box.top > window.innerHeight)) rec.pill.scrollIntoView({block: "center"});
  }

  // --- one item ---------------------------------------------------------------------------------------------------------
  function make(item, fixed, turn, subCall) {  // `subCall`: drawn in the panel of the subagent that call started  // `fixed`: a round that is over (LIVE.draw): no entry animation, nothing that acts on the running chat. `turn`: the id of the turn the item is of (an opened call is asked for by it)
    const li = h("li", {class: "fi fi-" + item.k + (fixed ? "" : " enter"), "data-id": item.id}, h("i", {class: "dot"}));
    const body = h("div", {class: "fb"});
    li.append(body);
    const rec = {el: li, body, kind: item.k, sig: "", text: "", pieces: 0, fixed: Boolean(fixed), open: false, turn: String(turn || ""), subCall: String(subCall || ""), detail: null, dsig: "", loading: false, again: false, err: "", tab: "out", all: false, fetched: ""};
    if (item.k === "me") {  // what the person said: a small mark; the words are in its card
      rec.tag = h("span", {class: "me-tag", role: "button"}, t("desk.live.you"));
      Status.card(rec.tag, () => saidCard(rec), t("desk.live.you"));
      // B9: the words themselves, three lines at most until the person asks for all of them
      rec.mtx = h("div", {class: "me-tx"});
      rec.mfiles = h("div", {class: "sub me-files", hidden: ""});
      rec.mall = h("button", {type: "button", class: "lv-unfold me-all", hidden: "", "aria-expanded": "false"}, t("desk.live.fold.all"));
      rec.mall.addEventListener("click", () => { rec.mopen = !rec.mopen; paintMe(rec); });
      body.append(rec.tag, h("div", {class: "me-box"}, rec.mtx, rec.mfiles, rec.mall));
    } else if (item.k === "text") {
      rec.tx = h("div", {class: "tx md"});
      rec.cutm = h("span", {class: "cutm", hidden: ""}, t("desk.live.cut"));
      rec.caret = h("span", {class: "caret", hidden: ""});
      rec.pill = h("button", {type: "button", class: "lv-unfold", hidden: "", "aria-expanded": "false"});
      rec.pill.addEventListener("click", () => { rec.open = !rec.open; applyFold(rec); if (!rec.open) keepPill(rec); });
      rec.read = h("button", {type: "button", class: "lv-unfold lv-read", hidden: ""}, svg(ICONS.reader, 13), t("desk.live.read"));  // B11: the whole reply in the side panel; the feed stays where it is
      rec.read.addEventListener("click", () => { if (rec.item) READER.open(rec.item, rec.read); });
      body.append(rec.tx, h("div", {class: "lv-folds"}, rec.pill, rec.read), rec.cutm);
    } else if (item.k === "tool") {
      rec.ico = h("span", {class: "ti"});
      rec.say = h("span", {class: "in"});
      rec.tg = h("code", {class: "tg"});
      rec.fx = h("span", {class: "fx"});
      rec.el2 = h("span", {class: "el"}, h("span", {class: "st-time"}));
      rec.chev = h("span", {class: "tc-chev", "aria-hidden": "true"}, "\u203a");
      rec.line = h("button", {type: "button", class: "tc-line", "aria-expanded": "false"}, rec.chev, rec.ico, rec.say, rec.tg, rec.fx, rec.el2);  // the whole line opens the call
      rec.line.addEventListener("click", () => toggle(rec));
      body.append(rec.line);
    } else if (item.k === "ask") {  // B8: a question of the agent. Waiting: one amber line that points at its card; answered: one record line that opens to every question and its answer
      rec.ico = h("span", {class: "ti"}, svg(ICONS.ask, 15));
      rec.say = h("span", {class: "in"});
      rec.tg = h("span", {class: "tg ask-q"});
      rec.fx = h("span", {class: "fx"});
      rec.el2 = h("span", {class: "el"});
      rec.chev = h("span", {class: "tc-chev", "aria-hidden": "true"}, "\u203a");
      rec.line = h("button", {type: "button", class: "tc-line ask-line", "aria-expanded": "false"}, rec.chev, rec.ico, rec.say, rec.tg, rec.fx, rec.el2);
      rec.qa = h("div", {class: "ask-qa", hidden: ""});
      rec.line.addEventListener("click", () => {
        if (rec.item && rec.item.st === "wait") { const card = needLi.hidden ? null : (needLi.querySelector("section.wc[data-action='question']") || needLi); if (card) { flash(card); card.scrollIntoView({block: "center", behavior: "smooth"}); const first = card.querySelector("button, textarea"); if (first) first.focus({preventScroll: true}); } return; }
        rec.open = !rec.open; paintAsk(rec, rec.item);
      });
      body.append(rec.line, rec.qa);
    } else if (item.k === "note") {  // B13, B14: what Copilot itself tells the chat, and a compaction of the context: one grey line
      rec.ico = h("span", {class: "ti"}, svg(item.kind === "compact" ? ICONS.compact : ICONS.bell, 14));
      rec.tx = h("span", {class: "note-tx"});
      body.append(h("div", {class: "note-line"}, rec.ico, rec.tx));
    } else if (item.k === "err") {  // 1.8.5: a turn that ended in an error: its words, in red
      rec.tx = h("div", {class: "tx err-tx"});
      body.append(h("b", {class: "err-h"}, t("waits.error")), rec.tx);
    } else {
      // 1.8.x board chat: a finished thought is one line (chevron, icon, "Thought", how long) that opens to its words, drawn as Markdown; one with no words says so and does not open.
      // While it runs, its newest words show under the line, a few lines at most.
      rec.ico = h("span", {class: "ti"}, svg(ICONS.think, 15));
      rec.say = h("span", {class: "in"});
      rec.wave = h("b", {class: "wv", "aria-hidden": "true"}, h("i"), h("i"), h("i"));
      rec.none = h("span", {class: "thk-none", hidden: "", title: t("desk.live.think.none.tip")}, t("desk.live.think.none"));
      rec.el2 = h("span", {class: "el"}, h("span", {class: "st-time"}));
      rec.chev = h("span", {class: "tc-chev", "aria-hidden": "true"}, "\u203a");
      rec.line = h("button", {type: "button", class: "thk-row", "aria-expanded": "false"}, rec.chev, rec.ico, rec.say, rec.wave, rec.none, rec.el2);
      rec.line.addEventListener("click", () => { if (rec.line.classList.contains("tc-static")) return; rec.open = !rec.open; paintThought(rec, rec.item); });
      rec.tx = h("div", {class: "tx thk", hidden: ""});
      rec.fold = {tx: rec.tx, item: null, open: false, foldable: false, pill: h("button", {type: "button", class: "lv-unfold thk-unfold", hidden: "", "aria-expanded": "false"})};  // a long thought folds as a long reply does
      rec.fold.pill.addEventListener("click", () => { rec.fold.open = !rec.fold.open; applyFold(rec.fold); if (!rec.fold.open) keepPill(rec.fold); });
      body.append(rec.line, rec.tx, rec.fold.pill);
    }
    li.addEventListener("animationend", (event) => { if (event.target === li) li.classList.remove("enter"); });
    return rec;
  }

  // An agent item is Markdown, drawn the way the documents of the task are (desk.js gives the drawing: `drawing`, with a Copy button on each code block). It is drawn only when its text changed,
  // so a finished item keeps the person's selection.
  function growText(rec, item) {
    if (item.text === rec.text) return;
    rec.text = item.text;
    rec.tx.replaceChildren(...[st.draw && item.blocks ? st.draw(item.blocks) : item.text].flat(Infinity).filter(Boolean));
  }

  // The card of a message of the person. The newest can be taken back; a turn that runs is stopped first (1.6.99).
  function saidCard(rec) {
    const item = rec.item;
    if (!item) return null;
    const last = st.lastSaid === item.id && Boolean(st.data) && ["idle", "busy", "input", "error"].includes(st.data.state);
    return {sig: JSON.stringify([item, last]), build: () => {
      const undo = last ? h("button", {type: "button", class: "act"}, t("desk.undo.title")) : null;
      if (undo) undo.addEventListener("click", () => { CHAT.withdraw({name: st.task.split("/").pop()}, (found) => { REPLY.restore(found); kick(); }); });
      return h("div", {class: "tk-said"}, h("div", {class: "st-head"}, t("desk.live.you")), h("div", {class: "tk-said-t"}, item.text + (item.cut ? " …" : "")),
        item.files ? h("div", {class: "sub"}, t("desk.live.files", {names: item.files.join(", ")})) : null, undo);
    }};
  }

  // --- a subagent (1.8.x board chat, B4) ------------------------------------------------------------------------------------
  // The call that started a subagent is drawn as its row: a status dot, its name, what it does now (the icon, word and target of its newest call) or how it ended (a line of its last
  // reply), its tool calls and its time. Rows of subagents side by side join into one card. The row opens the side panel: the subagent's whole chat, drawn as the main chat is.
  const SA_WAIT = 1000;  // ms between two questions of the panel while the subagent works
  function paintSub(rec, item) {
    const sub = item.sub;
    rec.el.classList.toggle("fi-sa", Boolean(sub));
    if (!sub) { if (rec.saNow) { rec.saNow.remove(); rec.saNow = null; } return; }
    if (!rec.saNow) { rec.saNow = h("span", {class: "sa-now"}); rec.tg.after(rec.saNow); }
    setText(rec.say, sub.title || t("desk.live.subagent.untitled"));
    rec.say.classList.add("sa-name");
    rec.say.title = item.say || sub.title || "";
    rec.tg.hidden = true;
    const now = sub.now || {};
    const parts = [];
    if (sub.st === "wait") parts.push(h("span", {class: "sa-wait"}, t("desk.live.sa.wait")), now.word || now.target ? h("span", {class: "sa-wait"}, "\u00b7 " + [now.word, now.target].filter(Boolean).join(" ")) : null);
    else if (sub.st === "run" && (now.kind || now.word || now.name)) parts.push(svg(ICONS[now.kind] || ICONS.other, 13, "sa-ico"), h("span", {class: "sa-word"}, now.kind && now.kind !== "run" && KIND_WORD[now.kind] ? t(KIND_WORD[now.kind]) : now.word || now.name || ""), now.target ? h("code", {class: "tg"}, now.target) : null);
    else if (sub.st === "fail") parts.push(h("span", {class: "sa-fail"}, t("desk.live.sa.fail") + (sub.said ? " \u00b7 " + sub.said : "")));
    else if (sub.st === "done") parts.push(h("span", {class: "sa-ok", "aria-hidden": "true"}, "\u2713"), h("span", {class: "sa-said"}, sub.said || t("desk.live.subagent.done")));
    rec.saNow.replaceChildren(...parts.filter(Boolean));
    rec.saNow.title = sub.said || "";
    const calls = typeof sub.calls === "number" ? h("span", {class: "fx-n sa-calls", title: t("desk.live.sa.calls", {n: sub.calls})}, svg(ICONS.tool, 12), String(sub.calls)) : null;
    rec.fx.replaceChildren(...[calls].filter(Boolean));
    rec.fxSig = "sa";
    for (const name of ["run", "wait", "fail", "done"]) rec.el.classList.toggle("sa-" + name, sub.st === name);
    if (sub.st === "wait") { for (const name of ["run", "fail", "done", "held", "refused"]) rec.el.classList.remove("is-" + name); rec.el.classList.add("is-wait"); }
    rec.line.setAttribute("aria-haspopup", "dialog");
    if (PANEL.call === item.id) PANEL.tab(rec);  // the open panel follows the row
  }

  // The side panel. One for the page; it shows one subagent at a time, with a tab for each subagent of the list it was opened from.
  const PANEL = (function () {
    const p = {call: "", task: "", turn: "", list: [], nodes: new Map(), full: new Map(), have: -1, timer: 0, busy: false, epoch: 0, st: "", data: null, back: null};
    const title = h("b", {class: "sa-title"});
    const what = h("span", {class: "sa-what"});
    const dot = h("i", {class: "sa-dot"});
    const close = h("button", {type: "button", class: "sa-close", "aria-label": t("desk.live.sa.close"), title: t("desk.live.sa.close")}, "\u00d7");
    const tabs = h("div", {class: "sa-tabs", role: "tablist"});
    const feed = h("ol", {class: "lv-feed sa-feed"});
    const empty = h("p", {class: "sa-empty", hidden: ""});
    const foot = h("div", {class: "sa-foot"});
    const box = h("aside", {class: "sa-panel lv", role: "dialog", "aria-modal": "false", hidden: ""}, h("div", {class: "sa-head"}, dot, title, what, close), tabs, h("div", {class: "sa-scroll"}, feed, empty), foot);
    close.addEventListener("click", () => p.shut());
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !box.hidden) p.shut(); });
    p.open = function (item, list, turn) {
      if (!box.isConnected) document.body.append(box);
      READER.reset();
      p.list = (list || []).filter((one) => one && one.sub);
      if (!p.list.some((one) => one.id === item.id)) p.list.unshift(item);
      p.mainTurn = turn || "";
      p.back = document.activeElement;
      p.show(item.id);
      box.hidden = false;
      document.body.classList.add("sa-on");
      close.focus({preventScroll: true});
    };
    p.show = function (call) {
      p.epoch += 1;
      clearTimeout(p.timer); p.timer = 0; p.busy = false;
      p.call = call; p.task = st.task; p.have = -1; p.data = null; p.st = "";
      for (const rec of p.nodes.values()) unwatch(rec);
      p.nodes.clear(); p.full.clear(); feed.replaceChildren();
      empty.hidden = false; setText(empty, t("desk.live.reading"));
      p.head(); p.drawTabs(); p.ask();
    };
    p.head = function () {
      const item = p.list.find((one) => one.id === p.call) || {};
      const sub = item.sub || {};
      setText(title, sub.title || t("desk.live.subagent.untitled"));
      setText(what, item.say && item.say !== sub.title ? item.say : "");
      what.title = what.textContent;
      dot.className = "sa-dot sa-" + (sub.st || "done");
      const calls = typeof sub.calls === "number" ? sub.calls : p.data && p.data.usage && typeof p.data.usage.calls === "number" ? p.data.usage.calls : null;
      const time = h("span", {class: "sa-f"}, svg(ICONS.clock, 13), h("span", {class: "st-time"}));
      const parts = [time, calls === null ? null : h("span", {class: "sa-f", title: t("desk.live.sa.calls", {n: calls})}, svg(ICONS.tool, 13), String(calls))];
      foot.replaceChildren(...parts.filter(Boolean));
      if (sub.st === "run" || sub.st === "wait") { if (item.t0) running(time, item.t0); }
      else setText(time.lastChild, item.t0 && item.t1 ? seconds(item.t1 - item.t0) : p.data && p.data.usage && p.data.usage.ms ? seconds(p.data.usage.ms) : "\u2013");
      if (feed.querySelector(".st-run[data-since]") || foot.querySelector(".st-run[data-since]")) { Status.clock(); Status.tick(); }
    };
    p.drawTabs = function () {
      tabs.hidden = p.list.length < 2;
      tabs.replaceChildren(...p.list.map((one) => {
        const sub = one.sub || {};
        const tab = h("button", {type: "button", role: "tab", class: "sa-tab" + (one.id === p.call ? " is-on" : ""), "aria-selected": String(one.id === p.call)}, h("i", {class: "sa-dot sa-" + (sub.st || "done")}), h("span", null, sub.title || t("desk.live.subagent.untitled")));
        tab.addEventListener("click", () => { if (one.id !== p.call) p.show(one.id); });
        return tab;
      }));
    };
    p.tab = function (rec) {  // a row of the main feed changed: its item is the newest word on the subagent's state
      const at = p.list.findIndex((one) => one.id === rec.item.id);
      if (at >= 0) p.list[at] = rec.item; else p.list.push(rec.item);
      if (!box.hidden) { p.head(); p.drawTabs(); if ((rec.item.sub || {}).st !== p.st && !p.timer && !p.busy) p.ask(); }
    };
    p.ask = function () {
      if (box.hidden && p.data) return;
      if (p.busy) return;
      p.busy = true;
      const epoch = p.epoch, call = p.call;
      SERVE.post("/api/live", {task: p.task, sub: {call, have: p.have}}).then((answer) => {
        if (epoch !== p.epoch) return;
        p.take(answer && answer.sub);
      }, (error) => {
        if (epoch !== p.epoch) return;
        if (!p.nodes.size) { empty.hidden = false; setText(empty, (error && error.message) || String(error)); }
      }).then(() => {
        if (epoch !== p.epoch) return;
        p.busy = false;
        const item = p.list.find((one) => one.id === p.call) || {};
        const going = ["run", "wait"].includes((item.sub || {}).st) || ["run", "wait"].includes(p.st);
        if (!box.hidden && going) p.timer = setTimeout(() => { p.timer = 0; p.ask(); }, SA_WAIT);
      });
    };
    p.take = function (data) {
      if (!data || typeof data !== "object" || !Array.isArray(data.items)) {
        if (!p.nodes.size) { empty.hidden = false; setText(empty, t("desk.live.sa.gone")); }
        return;
      }
      p.data = data; p.st = data.st || "";
      p.turn = data.turn || "";
      if (data.items.some((item) => item.same && !p.full.has(item.id))) { p.have = -1; return; }  // a stub of an item the panel does not have: ask for all next time
      for (const item of data.items) if (!item.same) p.full.set(item.id, item);
      p.have = typeof data.n === "number" ? data.n : -1;
      const ids = data.items.map((item) => item.id).filter((id) => p.full.has(id));
      const keep = new Set(ids);
      for (const [id, rec] of p.nodes) if (!keep.has(id)) { unwatch(rec); rec.el.remove(); p.nodes.delete(id); }
      let expected = feed.firstChild;
      for (const id of ids) {
        const item = p.full.get(id);
        if (item.k === "me") { if (!p.nodes.has(id)) { const rec = {el: h("li", {class: "fi fi-text sa-task", "data-id": id}, h("i", {class: "dot"}), h("div", {class: "fb"}, h("div", {class: "tx"}, item.text || ""))), item}; p.nodes.set(id, rec); } }
        let rec = p.nodes.get(id);
        if (!rec || rec.kind !== item.k && item.k !== "me") {
          if (rec) { unwatch(rec); rec.el.remove(); }
          rec = make(item, true, p.turn, p.call);
          p.nodes.set(id, rec);
          paint(rec, item);
        } else if (item.k !== "me" && rec.item !== item) { rec.turn = p.turn; paint(rec, item); }
        if (rec.el !== expected) feed.insertBefore(rec.el, expected); else expected = expected.nextSibling;
      }
      empty.hidden = ids.length > 0;
      if (!ids.length) setText(empty, t("desk.live.sa.none"));
      p.head();
    };
    p.shut = function () {
      p.epoch += 1;
      clearTimeout(p.timer); p.timer = 0; p.busy = false; p.call = "";
      box.hidden = true;
      document.body.classList.remove("sa-on");
      if (p.back && p.back.isConnected) p.back.focus({preventScroll: true});
    };
    p.reset = function () { if (!box.hidden) p.shut(); };
    return p;
  })();

  // A call the gate stopped fails in the chat ("Run Shell Command failed"), and none of the three things it can be is a failure of the call itself (1.7.22, 1.7.24; F3 U7):
  // held, and its card waits in the outbox ("held": amber); approved, and the agent has not run it again ("approved"); or stopped by the gate before: held and not approved (`past`), or refused (`refused`: a call the gate never lets through).
  // The last two are read from the gate's own record (`st.gates`, the task's hook log) and matched to the failed call by its command and, when the board saw the call begin, by the time. A call that really failed stays red.
  const flat = (text) => String(text || "").replace(/\s+/g, " ").trim();
  const sameCommand = (command, target) => command.includes(target) || target.includes(command.slice(0, 60));
  function isHeld(item) {  // "held" (waits for the person), "approved" (waits for the agent to run it again), "past" or "refused" (the gate's record), or "" (a call like any other)
    if (item.k !== "tool" || item.st !== "fail" || !item.target) return "";
    const target = flat(item.target).slice(0, 60);
    if (target.length <= 3) return "";
    if (st.held.some((command) => sameCommand(command, target))) return "held";
    if (st.approved.some((command) => sameCommand(command, target))) return "approved";  // an approved call that has not run is not a failure (1.7.24)
    const mark = st.marks.get(item.id);
    return mark ? (mark.how === "held" ? "past" : "refused") : "";
  }
  function markGates(items) {  // which failed calls the gate's record explains: each row of the record explains one call
    const marks = new Map(), used = new Set();
    for (const item of items) {  // oldest first
      if (item.k !== "tool" || item.st !== "fail" || !item.target) continue;
      const target = flat(item.target).slice(0, 60);
      if (target.length <= 3) continue;
      const index = st.gates.findIndex((row, at) => !used.has(at) && (!item.t0 || !row.ms || Math.abs(item.t0 - row.ms) <= 20000) && sameCommand(row.command, target));
      if (index >= 0) { used.add(index); marks.set(item.id, st.gates[index]); }
    }
    return marks;
  }
  function paint(rec, item) {
    const held = rec.fixed ? "" : isHeld(item);
    const why = held === "past" || held === "refused" ? (st.marks.get(item.id) || {}).reason || "" : "";
    const sig = JSON.stringify(item) + (held ? "|" + held + "|" + why : "");
    if (sig === rec.sig) return;
    rec.sig = sig;
    rec.item = item;
    if (item.k === "me") {
      rec.tag.setAttribute("aria-label", t("desk.live.you") + ": " + item.text.slice(0, 200));
      setText(rec.mtx, item.text + (item.cut ? " \u2026" : ""));
      rec.mfiles.hidden = !item.files;
      setText(rec.mfiles, item.files ? t("desk.live.files", {names: item.files.join(", ")}) : "");
      paintMe(rec);
    } else if (item.k === "text") {
      growText(rec, item);
      rec.cutm.hidden = !item.cut;
      rec.caret.hidden = !item.live;
      if (item.live) (rec.tx.lastElementChild || rec.tx).append(rec.caret);  // the caret stays at the end of the growing text
      rec.el.classList.toggle("is-live", Boolean(item.live));
      watch(rec);
    } else if (item.k === "tool") {
      const kind = item.kind && ICONS[item.kind] ? item.kind : kindOf(item.tool || "", item.name || "");  // an old item (and an old round) has no `kind`: the name tells
      if (rec.kind2 !== kind) { rec.kind2 = kind; rec.ico.replaceChildren(svg(ICONS[kind], 15)); }
      const named = item.kind ? wordOf(item) : "";  // with a kind the line says the word, and the agent's sentence moves to the tip and the opened call
      const label = named || (held === "approved" ? t("desk.live.approved") : held === "past" ? t("desk.live.held.past") : held === "refused" ? t("desk.live.refused") : held ? t("desk.live.held") : item.say || item.name || item.tool || "");
      setText(rec.say, label);
      rec.say.classList.toggle("mono", item.kind === "run" && Boolean(item.word));
      const gate = held === "approved" ? t("desk.live.approved") : held === "past" ? t("desk.live.held.past") : held === "refused" ? t("desk.live.refused") : held ? t("desk.live.held") : "";
      rec.say.title = why ? label + ": " + why : label;  // what the gate said, in the words it gave
      if (named) rec.say.title = [gate && why ? gate + ": " + why : gate, item.say || ""].filter(Boolean).join(" \u00b7 ") || label;  // a word with a kind: the gate's words and the agent's sentence
      setText(rec.tg, item.target || "");
      rec.tg.hidden = !item.target;
      rec.tg.title = (item.target || "") + (item.cut ? " …" : "");
      const refused = item.st === "fail" && !held && REFUSED.test(reasonOf(rec, item));  // a call the person refused is not a failure: grey, "stopped"
      const shown = held === "past" ? "held" : held === "refused" || refused ? "refused" : held ? "wait" : item.st === "stop" ? "done" : item.st || "done";
      for (const name of ["run", "wait", "fail", "done", "held", "refused"]) rec.el.classList.toggle("is-" + name, shown === name);  // classList: the `enter` class is not lost
      paintFacts(rec, item, refused || held === "refused" || held === "past");  // a call the gate stopped has no exit of its own to show
      paintSub(rec, item);
      const time = rec.el2;
      if (item.st === "run" && item.t0) { running(time, item.t0); }
      else {
        stopped(time);
        const label2 = time.querySelector(".st-time");
        const took = item.t0 && item.t1 ? seconds(item.t1 - item.t0) : "";
        const marked = item.kind === "run" && typeof item.exit === "number";  // the exit mark of a command is among its facts
        const end = item.st === "run" ? "" : item.st === "stop" || refused ? t("desk.trace.stopped") : item.kind ? ((item.st === "fail" && !marked ? "\u2717 " : "") + took).trim() : (item.st === "fail" ? "\u2717" : "\u2713") + (took ? " " + took : "");
        setText(label2, held === "approved" ? t("desk.live.wait.agent") : held === "past" ? t("desk.live.held.tag") : held === "refused" ? t("desk.live.refused.tag") : held || item.st === "wait" ? t("desk.live.wait") : end);
      }
      const can = canOpen(rec);
      rec.line.classList.toggle("tc-static", !can);
      rec.line.tabIndex = can ? 0 : -1;
      if (rec.open && can && rec.fetched !== JSON.stringify(item)) fetchCall(rec);  // the call changed while it is open (it ended, it failed): ask again; the page keeps what it shows meanwhile
    } else if (item.k === "err") {
      setText(rec.tx, item.text || t("waits.error.none"));
    } else if (item.k === "ask") {
      paintAsk(rec, item);
    } else if (item.k === "note") {
      const k = (n) => (n >= 1000 ? Math.round(n / 1000) + "k" : String(n));
      setText(rec.tx, item.kind === "compact" ? (typeof item.before === "number" && typeof item.after === "number" ? t("desk.live.compact.sizes", {before: k(item.before), after: k(item.after)}) : t("desk.live.compact")) : item.text || "");
    } else {
      paintThought(rec, item);
    }
  }

  function paintMe(rec) {  // three lines, or all of them; the button only when there is more than three lines
    rec.mtx.classList.toggle("me-clamp", !rec.mopen);
    requestAnimationFrame(() => {
      const more = rec.mopen || rec.mtx.scrollHeight > rec.mtx.clientHeight + 2;
      rec.mall.hidden = !more;
      setText(rec.mall, rec.mopen ? t("desk.live.fold.less") : t("desk.live.fold.all"));
      rec.mall.setAttribute("aria-expanded", String(Boolean(rec.mopen)));
    });
  }

  function paintAsk(rec, item) {
    const qs = Array.isArray(item.qs) ? item.qs : [];
    const wait = item.st === "wait";
    for (const name of ["wait", "done", "skip"]) rec.el.classList.toggle("is-" + name, item.st === name);
    setText(rec.say, wait ? t("desk.live.ask.wait") : item.st === "skip" ? t("desk.live.ask.skip") : t("desk.live.ask.done"));
    setText(rec.tg, item.text || (qs[0] && qs[0].title) || "");
    rec.tg.title = item.text || "";
    const answers = qs.map((one) => one.answer).filter(Boolean);
    const line = wait ? [h("span", {class: "ask-go"}, t("desk.live.ask.go"))] : answers.length ? [h("span", {class: "ask-a"}, "\u2192 " + answers.join(" \u00b7 "))] : [];
    rec.fx.replaceChildren(...line);
    const at = item.t1 ? new Date(item.t1).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) : "";
    setText(rec.el2, wait ? "" : at);
    const can = !wait && qs.length > 0;
    rec.line.classList.toggle("tc-static", !can && !wait);
    const open = can && Boolean(rec.open);
    rec.line.setAttribute("aria-expanded", String(open));
    rec.el.classList.toggle("is-open", open);
    rec.qa.hidden = !open;
    if (open) rec.qa.replaceChildren(h("dl", {class: "ask-dl"}, ...qs.flatMap((one) => [h("dt", null, one.title || "-"), h("dd", null, one.answer || t("desk.live.ask.none"))])));
  }

  function paintThought(rec, item) {
    const done = !item.run;
    const words = Boolean(item.text);
    rec.el.classList.toggle("is-done", done);
    rec.el.classList.toggle("is-run", !done);
    setText(rec.say, done ? t("desk.live.thought") : t("desk.live.thinking"));
    rec.wave.hidden = done;
    rec.none.hidden = !done || words;  // the host sent no words: a mark, not an empty line
    const can = done && words;
    rec.line.classList.toggle("tc-static", !can);
    rec.line.tabIndex = can ? 0 : -1;
    const open = can && Boolean(rec.open);
    rec.line.setAttribute("aria-expanded", open ? "true" : "false");
    rec.el.classList.toggle("is-open", open);
    if (!done && item.t0) running(rec.el2, item.t0);
    else {
      stopped(rec.el2);
      const took = typeof item.ms === "number" && item.ms > 0 ? item.ms : item.t0 && item.t1 ? item.t1 - item.t0 : 0;  // the host's own duration first, else until the next step began
      setText(rec.el2.querySelector(".st-time"), done && took ? seconds(took) : "");
    }
    rec.tx.classList.toggle("thk-live", !done);
    rec.tx.hidden = !(words && (!done || open));
    rec.fold.item = item;
    if (rec.tx.hidden || !done) { rec.fold.foldable = false; applyFold(rec.fold); }
    if (rec.tx.hidden) return;
    const key = (done ? "md:" : "tx:") + item.text.length + (item.cut ? "+" : "");
    if (rec.drawn !== key) {  // drawn only when it changed: an open thought keeps the person's selection
      rec.drawn = key;
      if (done && st.draw && item.blocks) rec.tx.replaceChildren(...[st.draw(item.blocks), item.cut ? h("p", {class: "thk-cut"}, t("desk.live.cut")) : null].flat(Infinity).filter(Boolean));
      else setText(rec.tx, item.text + (item.cut ? " \u2026" : ""));
    }
    if (done) watch(rec.fold);  // measured again each time it is shown: closed, it has no height
  }

  // --- an opened tool call (1.8.x board chat) -------------------------------------------------------------------------------
  // The closed line is a button: its chevron, icon, word, target, small facts and time. Opening asks the server for the call (`/api/live {task, call: {turn, id}}`: the whole command, its output, the diff of an edit)
  // and draws it under the line; the call is asked for again each time the line is opened and when the item changes while it is open (a running call grows). The opened state stays on the item's record: a repaint of the line
  // does not close it. Only the item's turn is needed: items of the live feed and of `older` have it; an item of an opened round has it only when the round's answer gave it (`LIVE.draw(items, turn)`).
  const OUT_TAIL = 40;  // lines of an output shown first
  const TAIL_CHARS = 8000;  // and never more characters than this before the person asks for all
  const REFUSED = /refus|denied|declin|cancel/i;  // the words of a call the person (or the gate) did not let through: not a failure
  const canOpen = (rec) => Boolean(rec.turn && rec.item && rec.item.k === "tool" && rec.item.id);
  const reasonOf = (rec, item) => String(item.reason || (rec.detail && rec.detail.reason) || "");
  function wordOf(item) {  // the word on the line of a tool with a kind: a command's program, else the kind's word; a kind with no word (other) keeps the tool's own name
    if (item.kind === "run") return item.word || t(KIND_WORD.run);
    return KIND_WORD[item.kind] ? t(KIND_WORD[item.kind]) : item.name || item.tool || "";
  }
  // The small facts after the target: +added −removed and the number of files, the hits of a search, the exit mark of a command. Only numbers, never a colour of a kind: green and red are the diff's own.
  function paintFacts(rec, item, refused) {
    const out = [];
    if ((item.kind === "edit" || item.kind === "create") && (typeof item.add === "number" || typeof item.del === "number")) {
      out.push(h("span", {class: "fx-add"}, "+" + (item.add || 0)), h("span", {class: "fx-del"}, "−" + (item.del || 0)));
      if (typeof item.files === "number" && item.files > 1) out.push(h("span", {class: "fx-n"}, "· " + t("desk.live.call.files", {n: item.files})));
    }
    if (item.kind === "search" && typeof item.hits === "number") out.push(h("span", {class: "fx-n"}, t("desk.live.call.hits", {n: item.hits})));
    if (item.kind === "run" && typeof item.exit === "number" && !refused) {
      const words = t("desk.live.call.exit", {code: item.exit});
      out.push(h("span", {class: item.exit === 0 ? "fx-ok" : "fx-bad", title: words, "aria-label": words}, item.exit === 0 ? "✓" : "✗"));
    }
    if (item.ok === "you") {  // B8: it waited for the person, who let it go: a record of the decision on its line
      const at = item.okAt ? new Date(item.okAt).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) : "";
      const words = at ? t("desk.live.ok.at", {time: at}) : t("desk.live.ok");
      out.push(h("span", {class: "fx-okby", title: words}, svg(ICONS.shield, 12), "\u2713 " + words));
    }
    const sig = out.map((node) => node.className + node.textContent).join("|");
    if (sig !== rec.fxSig) { rec.fxSig = sig; rec.fx.replaceChildren(...out); }
  }

  function flash(node) {  // the card a line or the bar took the person to: a short glow, so it is plain which one
    node.classList.remove("lv-flash");
    void node.offsetWidth;
    node.classList.add("lv-flash");
    setTimeout(() => node.classList.remove("lv-flash"), 1600);
  }
  function toggle(rec) {
    if (!rec.fixed && rec.item && rec.item.k === "tool" && rec.el.classList.contains("is-wait") && !needLi.hidden) {  // a call that waits for the person: its card has the buttons and the whole command
      const card = [...needLi.querySelectorAll("section.wc")].find((node) => node.textContent.includes(rec.item.target || "\u0000")) || needLi;
      flash(card);
      card.scrollIntoView({block: "center", behavior: "smooth"});
      const first = card.querySelector("button:not([disabled]), textarea");
      if (first) setTimeout(() => first.focus({preventScroll: true}), 350);
      return;
    }
    if (rec.item && rec.item.sub && rec.item.id) { PANEL.open(rec.item, rec.list ? rec.list() : [...st.nodes.values()].map((one) => one.item), rec.turn); return; }  // a subagent opens its panel
    if (!canOpen(rec)) return;
    rec.open = !rec.open;
    syncOpen(rec);
    if (rec.open) fetchCall(rec);
  }
  function syncOpen(rec) {
    rec.line.setAttribute("aria-expanded", String(rec.open));
    rec.el.classList.toggle("tc-open", rec.open);
    if (rec.open && !rec.tb) { rec.tb = h("div", {class: "tc-body"}); rec.line.after(rec.tb); }
    if (rec.tb) rec.tb.hidden = !rec.open;
    if (rec.open) drawBody(rec);
  }
  function fetchCall(rec) {
    if (rec.loading) { rec.again = true; return; }  // one question at a time; the next goes when this one is back
    const task = st.task, turn = rec.turn, id = rec.item.id;
    rec.loading = true;
    rec.fetched = JSON.stringify(rec.item);
    rec.err = "";
    if (!rec.detail) drawBody(rec);
    SERVE.post("/api/live", {task, call: rec.subCall ? {turn, id, sub: rec.subCall} : {turn, id}}).then((answer) => {  // a call in a subagent's panel is looked for in its chat
      const found = answer && answer.call && typeof answer.call === "object" && !Array.isArray(answer.call) ? answer.call : {};
      const sig = JSON.stringify(found);
      return () => { const was = rec.detail; const redraw = sig !== rec.dsig || Boolean(rec.err) || !was; rec.err = ""; rec.detail = found; rec.dsig = sig; return {redraw, reason: (was && was.reason) !== found.reason}; };
    }, (error) => () => { rec.err = (error && error.message) || String(error); return {redraw: true, reason: false}; }).then((apply) => {
      rec.loading = false;
      if (!rec.el.isConnected || task !== st.task) return;  // the task or the turn changed meanwhile: this node is gone
      const done = apply();
      if (rec.open && done.redraw) drawBody(rec);
      if (done.reason && rec.item) { rec.sig = ""; paint(rec, rec.item); }  // a refused call says so only in its detail: the line is drawn again
      if (rec.again) { rec.again = false; if (rec.open) fetchCall(rec); }
    }).catch(() => { rec.loading = false; });
  }

  const note = (key) => h("p", {class: "sub tc-note"}, t(key));
  const box = (text, cls) => h("pre", {class: "tc-box" + (cls ? " " + cls : ""), tabindex: "0"}, text);  // its own vertical scroll (about 60vh); a text goes in as one text node
  function termNodes(rec, part) {
    const text = String(part.text || "");
    const tail = part.cut || part.truncated ? note("desk.live.call.cut") : null;
    if (!text.trim()) return [h("p", {class: "sub tc-note"}, t("desk.live.call.noout")), tail];
    const lines = text.split("\n");
    let shown = rec.all ? text : lines.slice(-OUT_TAIL).join("\n");
    let clipped = false;
    if (!rec.all && shown.length > TAIL_CHARS) { shown = shown.slice(-TAIL_CHARS); clipped = true; }
    const more = !rec.all && (lines.length > OUT_TAIL || clipped);
    const all = more ? h("button", {type: "button", class: "tc-more"}, t("desk.live.call.all", {n: Math.max(Number(part.lines) || 0, lines.length)})) : null;
    if (all) all.addEventListener("click", () => { rec.all = true; drawBody(rec); const out = rec.tb.querySelector(".tc-out"); if (out) out.focus(); });
    return [box(shown, "tc-out"), all, tail];
  }
  // A file may be cut in the middle of a hunk (the server's cap on lines): the counts of its `@@` line are then not met, and the compare would take the next file's header for code. Pad it with blank context lines.
  function balanced(lines) {
    let old = 0, added = 0;
    for (const line of lines) {
      if (old > 0 || added > 0) { if (line.startsWith("\\")) continue; if (line.startsWith("-")) old -= 1; else if (line.startsWith("+")) added -= 1; else { old -= 1; added -= 1; } continue; }
      const found = /^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@/.exec(line);
      if (found) { old = found[1] === undefined ? 1 : Number(found[1]); added = found[2] === undefined ? 1 : Number(found[2]); }
    }
    const out = lines.slice();
    while (old > 0 && added > 0) { out.push(" …"); old -= 1; added -= 1; }
    while (old > 0) { out.push("-…"); old -= 1; }
    while (added > 0) { out.push("+…"); added -= 1; }
    return out;
  }
  function diffNodes(part) {
    const files = Array.isArray(part.files) ? part.files.filter((file) => file && typeof file === "object") : [];
    const lines = [];
    for (const file of files) {
      const path = String(file.path || "");
      lines.push("diff --git a/" + path + " b/" + path, file.new ? "--- /dev/null" : "--- a/" + path, file.gone ? "+++ /dev/null" : "+++ b/" + path);
      for (const line of balanced((Array.isArray(file.lines) ? file.lines : []).map(String))) lines.push(line);
    }
    if (!lines.length) return [];
    const raw = () => box(lines.join("\n"), "tc-raw");
    if (typeof DiffView === "undefined") return [raw(), part.cut ? note("desk.live.call.cut") : null];
    try { return [DiffView.create({lines, cut: Boolean(part.cut)}, raw, "live", true)]; } catch (error) { return [raw(), part.cut ? note("desk.live.call.cut") : null]; }
  }
  function partNodes(rec, part) {
    if (!part || typeof part !== "object") return [];
    const tail = part.cut ? note("desk.live.call.cut") : null;
    if (part.k === "term") return termNodes(rec, part);
    if (part.k === "diff") return diffNodes(part);
    if (part.k === "file") return [part.path ? h("div", {class: "tc-path"}, h("code", null, String(part.path))) : null, box(String(part.text || "")), tail];
    if (part.k === "text") return [box(String(part.text || "")), tail];
    if (part.k === "other") return [h("p", {class: "sub tc-note"}, t("desk.live.call.other", {type: String(part.type || "")}))];
    return [];
  }
  function detailNodes(rec, d) {
    const run = (d.kind || (rec.item && rec.item.kind)) === "run";
    const parts = Array.isArray(d.parts) ? d.parts : [];
    const exitPart = parts.find((part) => part && part.k === "term" && typeof part.exit === "number");
    const exit = exitPart ? exitPart.exit : rec.item && typeof rec.item.exit === "number" ? rec.item.exit : null;
    const input = typeof d.input === "string" && d.input ? d.input : "";
    const tab = input && rec.tab === "in" ? "in" : "out";
    const out = [];
    if (d.why) out.push(h("p", {class: "tc-why"}, String(d.why)));
    const gate = rec.fixed || !rec.item ? "" : isHeld(rec.item);
    if (gate === "refused" || gate === "past") {  // the gate stopped it: who and why first, in the gate's own words (its record in the hook log)
      const why = (st.marks.get(rec.item.id) || {}).reason || "";
      out.push(h("p", {class: "tc-gate"}, svg(ICONS.shield, 13), h("b", null, gate === "refused" ? t("desk.live.gate.refused") : t("desk.live.held.past")), why ? " \u00b7 " + why : ""));
    }
    if (run && d.command) out.push(h("div", {class: "tc-cmd"}, h("span", {class: "tc-ps", "aria-hidden": "true"}, "$ "), String(d.command)), d.command_cut ? note("desk.live.call.cut") : null);
    if (input || (run && exit !== null)) {
      const pick = (name, key) => {
        const button = h("button", {type: "button", role: "tab", class: "tc-tab" + (tab === name ? " on" : ""), "aria-selected": String(tab === name), "data-tab": name}, t(key));
        button.addEventListener("click", () => { rec.tab = name; drawBody(rec); const again = rec.tb.querySelector('.tc-tab[data-tab="' + name + '"]'); if (again) again.focus(); });
        return button;
      };
      out.push(h("div", {class: "tc-tabs", role: "tablist"}, pick("out", run ? "desk.live.call.output" : "desk.live.call.result"), input ? pick("in", "desk.live.call.input") : null, h("span", {class: "tc-sp"}),
        run && exit !== null ? h("span", {class: "tc-exit " + (exit === 0 ? "ok" : "bad")}, t("desk.live.call.exit", {code: exit})) : null, askButton(rec, exit)));
    } else { const ask = askButton(rec, exit); if (ask) out.push(h("div", {class: "tc-askrow"}, ask)); }
    if (tab === "in") out.push(box(input, "tc-in"), d.input_cut ? note("desk.live.call.cut") : null);
    else for (const part of parts) out.push(...partNodes(rec, part));
    if (d.error) out.push(h("p", {class: "tc-error bad", role: "alert"}, String(d.error)));
    if (d.reason) out.push(h("p", {class: "tc-reason"}, svg(ICONS.ring, 13, "tc-ring"), String(d.reason)));  // a refused call: soft, with a ring
    if (d.cut && !out.some((node) => node && node.nodeType === 1 && (node.classList.contains("tc-note") || node.querySelector(".tc-note")))) out.push(note("desk.live.call.cut"));  // once: a part that says it is cut already told
    return out.filter(Boolean);
  }
  function drawBody(rec) {
    const tb = rec.tb;
    if (!tb) return;
    const was = [...tb.querySelectorAll(".tc-box")].map((node) => node.scrollTop);
    const d = rec.detail && typeof rec.detail === "object" ? rec.detail : null;
    const kids = [];
    if (rec.err) {
      const again = h("button", {type: "button", class: "tc-more"}, t("desk.live.call.retry"));
      again.addEventListener("click", () => fetchCall(rec));
      kids.push(h("div", {class: "tc-err"}, h("span", {class: "bad", role: "alert"}, rec.err), again));
    }
    if (!d) { if (rec.loading) kids.push(h("p", {class: "sub tc-load"}, spinner(), " ", t("desk.live.call.loading"))); }
    else {
      const found = Object.keys(d).length ? detailNodes(rec, d) : [];
      if (found.length) kids.push(...found); else if (!rec.err) kids.push(note("desk.live.call.none"));
    }
    tb.replaceChildren(...kids);
    const now = [...tb.querySelectorAll(".tc-box")];
    if (now.length === was.length) now.forEach((node, at) => { node.scrollTop = was[at]; });  // the same boxes: the reader's place in them stays
    if (rec.onDrawn && d) { const call = rec.onDrawn; rec.onDrawn = null; requestAnimationFrame(() => call(rec)); }  // B20: a search waits for the call's detail to mark the hit in it
  }

  // --- scroll: follow the bottom only when the person is there; never move what they are reading --------------------------
  const TOP_EDGE = 130;  // below the sticky header and tabs
  // `survives(node)`: will this item still be there after `change`? The place is kept by an item that stays.
  function view(change, survives) {
    if (root.hidden) { change(); return; }
    const gap = life.getBoundingClientRect().bottom - window.innerHeight;
    const follow = gap <= 70;
    let anchor = null, top = 0;
    if (!follow) {
      anchor = Array.from(feed.children).find((node) => !node.hidden && node.getBoundingClientRect().bottom > TOP_EDGE && (!survives || !node.dataset.id || survives(node))) || null;
      if (anchor) top = anchor.getBoundingClientRect().top;
    }
    change();
    if (follow) {
      const more = life.getBoundingClientRect().bottom - window.innerHeight + 24;
      if (more > 0) window.scrollBy({top: more, behavior: "instant"});
    } else if (anchor && anchor.isConnected) {
      const moved = anchor.getBoundingClientRect().top - top;
      if (Math.abs(moved) > 1) window.scrollBy({top: moved, behavior: "instant"});
    }
  }

  // --- what the page has of the turn -----------------------------------------------------------------------------------
  // The server sends all the items its memory holds of the last turn; one that did not change since `have` comes as a stub (`same: true`): it is kept as it is and not drawn again. An item that fell out of the server's
  // memory (a long turn loses its oldest parts) stays here: it is finished. Only the turn changing, or the task, starts anew.
  const order = () => [st.head, ...st.older, ...st.tail].filter((id) => id && st.full.has(id));
  function forget() {  // nothing of the turn is kept; the next question asks for everything
    st.epoch += 1;
    for (const rec of st.nodes.values()) { unwatch(rec); rec.el.remove(); }
    st.nodes.clear(); st.full.clear();
    for (const group of st.groups.values()) group.li.remove();
    st.groups.clear();
    st.head = ""; st.older = []; st.tail = []; st.reach = 0; st.seen = false; st.have = -1; st.loadingOlder = false;
    st.filter = "all"; st.counts = null; st.since = null; st.loadingAll = null;  // B18, B19: a new round shows all of itself; the line of the last look belongs to the round it was put in
    for (const node of st.hidPool || []) node.remove();
    sinceLi.remove();
    earlier.disabled = false; earlierBad.hidden = true;
  }
  // The ids of the answer in the server's order, with the ones the page holds that the answer no longer has put back where they were (after the id that came before them).
  function merge(held, now) {
    const inNow = new Set(now), after = new Map(), lead = [];
    let last = null;
    for (const id of held) {
      if (inNow.has(id)) { last = id; continue; }
      if (last === null) lead.push(id); else { if (!after.has(last)) after.set(last, []); after.get(last).push(id); }
    }
    const out = [...lead];
    for (const id of now) { out.push(id); if (after.has(id)) out.push(...after.get(id)); }
    return out;
  }
  // Takes an answer into the record. Returns the ids to draw again, or null when the answer cannot be used (a stub of an item the page does not hold: it asks again for everything).
  function absorb(data) {
    if (!data.bound) { forget(); st.turn = ""; return new Set(); }
    const turn = data.turn || "";
    if (turn !== st.turn) { forget(); st.turn = turn; }
    const answer = data.items || [];
    if (answer.some((item) => item.same && !st.full.has(item.id))) { st.have = -1; st.rev = ""; st.hurry = true; return null; }
    const mine = answer.filter((item) => item.k !== "me").map((item) => item.id);
    if (st.tail.length && mine.length && !mine.some((id) => st.tail.includes(id))) {  // a gap: the steps between were lost from the server's memory before the page saw them
      forget(); st.turn = turn;
      if (answer.some((item) => item.same)) { st.rev = ""; st.hurry = true; return null; }  // a stub of what was just dropped: ask for everything again
    }
    const changed = new Set();
    for (const item of answer) {
      if (item.k === "me") st.head = item.id;
      if (!item.same) { st.full.set(item.id, item); changed.add(item.id); }
    }
    st.tail = merge(st.tail, mine);
    if (st.older.length) st.older = st.older.filter((id) => !mine.includes(id));
    if (!st.seen) { st.seen = true; st.reach = data.before ? data.before.i || 0 : 0; }
    st.have = typeof data.n === "number" ? data.n : -1;
    return changed;
  }

  // --- what the answer says ---------------------------------------------------------------------------------------------
  function show(data, changed, all) {
    const ids = data && data.bound ? order() : [];
    const keep = new Set(ids);
    for (const [id, rec] of st.nodes) if (!keep.has(id)) { unwatch(rec); rec.el.remove(); st.nodes.delete(id); }
    const items = ids.map((id) => st.full.get(id));
    st.lastSaid = st.head && keep.has(st.head) ? st.head : "";
    st.marks = markGates(items);
    const nodes = [];
    for (const item of items) {
      let rec = st.nodes.get(item.id);
      if (!rec || rec.kind !== item.k) {
        if (rec) { unwatch(rec); rec.el.remove(); }
        rec = make(item, false, st.turn);
        st.nodes.set(item.id, rec);
        paint(rec, item);
      } else if (all || (changed && changed.has(item.id))) paint(rec, item);  // a stub is never drawn again
      nodes.push(rec);
      if (item.id === st.head) nodes.push(earlierLi);
    }
    if (!nodes.includes(earlierLi)) nodes.unshift(earlierLi);
    const running = Boolean(data && data.bound && (data.started || data.state === "busy"));
    if (st.arriveDue && !root.hidden && !document.hidden && data && data.bound && !data.loading && ids.length) arrive();
    const folded = st.filter && st.filter !== "all" ? filtered(nodes) : fold(nodes, running, st.groups);
    if (!st.filter || st.filter === "all") for (const node of st.hidPool || []) node.remove();
    for (const rec of nodes) if (rec && rec.el) rec.el.classList.toggle("lv-dim", Boolean(st.filter && st.filter !== "all" && THREAD.includes(rec.kind)));
    for (const node of [...feed.children]) if (node.classList.contains("fi-group") && !folded.includes(node)) node.remove();
    nodes.length = 0; nodes.push(...folded);
    const lineAt = sinceAt(nodes);
    if (lineAt >= 0) nodes.splice(lineAt, 0, sinceLi); else sinceLi.remove();
    let expected = feed.firstChild;
    for (const node of nodes) {
      if (node !== expected) feed.insertBefore(node, expected); else expected = expected.nextSibling;
    }
    earlierLi.hidden = !(data && data.bound && ids.length && st.reach > 0) || Boolean(st.filter && st.filter !== "all");
    paintSince();
    if (!findRow.hidden && fd.q && ids.length !== fd.size) refreshFind();
    if (st.since && st.since.jump && sinceLi.isConnected && !root.hidden) { st.since.jump = false; toSince(); }
    paintTools(data);
    paintCalm(data, items);
    paintLife(data);
    rcFollow(data);
    paintBar(data);
    queueWaits();
    seenSoon();
    if (feed.querySelector(".st-run[data-since]") || life.querySelector(".st-run[data-since]")) { Status.clock(); Status.tick(); }
  }

  // --- the reading view of a long reply (B11): the side panel of the subagents, with the reply drawn whole; the feed does not move -------------------------------------
  const READER = (function () {
    const title = h("b", {class: "sa-title"}, t("desk.live.read.title"));
    const close = h("button", {type: "button", class: "sa-close", "aria-label": t("desk.live.sa.close"), title: t("desk.live.sa.close")}, "×");
    const body = h("div", {class: "tx md rd-body"});
    const scroll = h("div", {class: "sa-scroll rd-scroll"}, body);
    const box = h("aside", {class: "sa-panel lv rd-panel", role: "dialog", "aria-modal": "false", "aria-label": t("desk.live.read.title"), hidden: ""}, h("div", {class: "sa-head"}, title, h("span", {class: "sa-what"}), close), scroll);
    let back = null;
    const shut = () => { if (box.hidden) return; box.hidden = true; document.body.classList.remove("sa-on"); if (back && back.isConnected) back.focus({preventScroll: true}); };
    close.addEventListener("click", shut);
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !box.hidden) shut(); });
    return {
      open(item, from) {
        if (!box.isConnected) document.body.append(box);
        PANEL.reset();
        body.replaceChildren(...[st.draw && item.blocks ? st.draw(item.blocks) : item.text, item.cut ? h("p", {class: "thk-cut"}, t("desk.live.cut")) : null].flat(Infinity).filter(Boolean));
        back = from || document.activeElement;
        box.hidden = false;
        document.body.classList.add("sa-on");
        scroll.scrollTop = 0;
        close.focus({preventScroll: true});
      },
      reset: shut,
    };
  })();

  // --- the steps between two things said, folded to one line (B7, prototype 5 pin 3) ---------------------------------------------------------------------------------------------
  // What the person and the agent say is the thread; the finished steps between two of them (tool calls, thoughts) are one line: how many, how many of each kind, the lines an edit added and
  // removed, how long. It opens to the steps themselves, all of them. Never folded: a call that failed, waits for the person, was held or refused by the gate, a subagent's row, and the
  // steps after the last thing said while the round runs. One step alone is not folded. A group is known by its first step: it stays open or closed across the polls.
  const GROUP_MIN = 2;
  const KEEP_OUT = ["is-fail", "is-wait", "is-held", "is-refused", "is-run"];
  const GROUP_ORDER = ["think", "read", "search", "edit", "create", "run", "web", "agent", "other"];
  const stepOf = (rec) => (rec && rec.el ? (rec.kind === "tool" ? rec.kind2 || "other" : ["me", "text", "err", "ask", "note"].includes(rec.kind) ? "" : "think") : "");
  const keptOut = (rec) => rec.kind === "tool" && (KEEP_OUT.some((name) => rec.el.classList.contains(name)) || Boolean(rec.item && (rec.item.sub || rec.item.ok)));  // B8: a call the person let go is a record of their decision
  function groupLine(group) {
    const counts = new Map();
    let add = 0, del = 0, first = Infinity, last = 0, took = 0;
    for (const rec of group.members) {
      const kind = stepOf(rec);
      counts.set(kind, (counts.get(kind) || 0) + 1);
      const item = rec.item || {};
      add += Number(item.add) || 0; del += Number(item.del) || 0;
      if (item.t0) first = Math.min(first, item.t0);
      const end = item.t1 || (item.t0 && typeof item.ms === "number" ? item.t0 + item.ms : 0);
      if (end) last = Math.max(last, end);
      if (!item.t0 && typeof item.ms === "number") took += item.ms;
    }
    const span = (last && first !== Infinity ? last - first : 0) + took;
    const kinds = GROUP_ORDER.filter((kind) => counts.has(kind)).map((kind) => {
      const word = kind === "think" ? t("desk.live.thought") : KIND_WORD[kind] ? t(KIND_WORD[kind]) : kind;
      return h("span", {class: "gp-k", title: word + " × " + counts.get(kind)}, svg(ICONS[kind] || ICONS.other, 13), String(counts.get(kind)));
    });
    return [h("span", {class: "tc-chev", "aria-hidden": "true"}, "›"), h("span", {class: "gp-n"}, t("desk.live.group.steps", {n: group.members.length})), ...kinds,
      add || del ? h("span", {class: "fx gp-pm"}, h("span", {class: "fx-add"}, "+" + add), h("span", {class: "fx-del"}, "−" + del)) : null,
      h("span", {class: "el"}, span ? seconds(span) : "")].filter(Boolean);
  }
  function groupLi(store, key) {
    let found = store.get(key);
    if (!found) {
      const line = h("button", {type: "button", class: "tc-line gp-line", "aria-expanded": "false"});
      const li = h("li", {class: "fi fi-group", "data-id": "~g:" + key}, h("i", {class: "dot"}), h("div", {class: "fb"}, line));
      found = {li, line, open: false, sig: "", members: []};
      line.addEventListener("click", () => {  // the line stays where the pointer is: the page moves by what changed above it, if anything
        const before = line.getBoundingClientRect().top;
        found.open = !found.open; paintGroup(found);
        const moved = line.getBoundingClientRect().top - before;
        if (Math.abs(moved) > 1) window.scrollBy(0, moved);
      });
      store.set(key, found);
    }
    return found;
  }
  function paintGroup(group) {
    group.line.setAttribute("aria-expanded", String(group.open));
    group.li.classList.toggle("is-open", group.open);
    for (const rec of group.members) rec.el.hidden = !group.open;
    const sig = group.members.map((rec) => { const item = rec.item || {}; return [item.id, item.st, item.kind, item.t0, item.t1, item.ms, item.add, item.del].join("|"); }).join("\u0001");
    if (sig !== group.sig) { group.sig = sig; group.line.replaceChildren(...groupLine(group)); group.line.setAttribute("aria-label", t("desk.live.group.steps", {n: group.members.length})); }
  }
  // `nodes`: records and plain nodes (the "earlier steps" control) in order; `store`: the groups of this list. The answer: the nodes in order, with a group's line before its steps.
  function fold(nodes, running, store) {
    let lastSaid = -1;
    nodes.forEach((node, at) => { if (node && node.el && ["me", "text", "err"].includes(node.kind)) lastSaid = at; });
    const out = [], used = new Set();
    let run = [];
    const close = () => {
      if (run.length >= GROUP_MIN) {
        const group = groupLi(store, run[0].item ? run[0].item.id : run[0].el.dataset.id);
        group.members = run;
        used.add(group);
        out.push(group.li, ...run.map((rec) => rec.el));
        paintGroup(group);
      } else for (const rec of run) { rec.el.hidden = false; out.push(rec.el); }
      run = [];
    };
    nodes.forEach((node, at) => {
      const rec = node && node.el ? node : null;
      if (rec && stepOf(rec) && !keptOut(rec) && !(running && at > lastSaid)) { run.push(rec); return; }
      close();
      if (rec) rec.el.hidden = false;
      out.push(rec ? rec.el : node);
    });
    close();
    for (const [key, group] of store) if (!used.has(group)) store.delete(key);
    return out;
  }

  // --- what waits, at the bottom (B10) -------------------------------------------------------------------------------------------
  // Counted: each line of the round that waits for the person (a call to allow, a question) and each other card of the task (a plan to approve, a requirement to confirm). The chat's own
  // waits share one card (it says "+N"), so a click goes to the cards, where the buttons are, and puts the focus on the first of them.
  function waitsNow() {
    const lines = [...feed.querySelectorAll(":scope > li.fi-tool.is-wait, :scope > li.fi-ask.is-wait")];  // never folded, so never hidden
    const words = lines.map((node) => { const rec = st.nodes.get(node.dataset.id); const item = rec && rec.item ? rec.item : {}; return item.k === "ask" ? t("desk.live.ask.wait") + " · " + (item.text || "") : [item.word || item.name || "", item.target || ""].filter(Boolean).join(" "); });
    const chatCard = st.needs.some((node) => node.classList && node.classList.contains("wc"));
    const others = st.needs.filter((node) => !(node.classList && node.classList.contains("wc")));
    for (const node of others) {  // a card's own words: its head without how long it has waited
      const head = node.querySelector(".tk-need-h") || node;
      const title = [...head.childNodes].filter((one) => !(one.classList && one.classList.contains("tk-waited"))).map((one) => one.textContent).join(" ").replace(/\s+/g, " ").trim();
      words.push(title.slice(0, 80));
    }
    const count = Math.max(lines.length, chatCard ? 1 : 0) + others.length;
    return {count, words};
  }
  let waitFrame = 0;
  function placeWaits() {
    waitFrame = 0;
    if (root.hidden || !st.data || !st.data.bound) { waitBar.hidden = true; return; }
    const view = window.innerHeight;
    const {count, words} = waitsNow();
    const card = needLi.hidden ? null : needLi.getBoundingClientRect();
    const cardSeen = Boolean(card && card.top < view - 90 && card.bottom > 120);
    const end = life.getBoundingClientRect();
    const far = end.top > view + 160;  // the newest step is well below the window
    const showWaits = count > 0 && !cardSeen && Boolean(card);
    waitGo.hidden = waitList.hidden = !showWaits;
    latestBtn.hidden = !far;
    waitBar.hidden = !(showWaits || far);
    if (showWaits) {
      const label = t("desk.live.waits", {n: count});
      setText(waitGo, (card.top > view ? "↓ " : "↑ ") + label);
      setText(waitList, words.filter(Boolean).join(" · "));
      waitList.title = words.filter(Boolean).join("\n");
    }
  }
  const queueWaits = () => { if (!waitFrame) waitFrame = requestAnimationFrame(placeWaits); };
  window.addEventListener("scroll", queueWaits, {passive: true});
  window.addEventListener("resize", queueWaits, {passive: true});
  waitGo.addEventListener("click", () => {
    if (needLi.hidden) return;
    needLi.scrollIntoView({block: "center", behavior: "smooth"});
    flash(needLi.querySelector("section.wc, section.tk-need") || needLi);
    const first = needLi.querySelector("button:not([disabled]), textarea");
    if (first) setTimeout(() => first.focus({preventScroll: true}), 350);
  });
  latestBtn.addEventListener("click", () => { life.scrollIntoView({block: "end", behavior: "smooth"}); });

  // --- the title of the round at the top (B9) ---------------------------------------------------------------------------------
  const RB_ICONS = {time: [["circle", {cx: 8, cy: 8, r: 6}], ["path", {d: "M8 4.8V8l2.2 1.4"}]], credits: [["ellipse", {cx: 8, cy: 4.6, rx: 5, ry: 2}], ["path", {d: "M3 4.6v6.8c0 1.1 2.2 2 5 2s5-.9 5-2V4.6M3 8c0 1.1 2.2 2 5 2s5-.9 5-2"}]],
    tools: [["path", {d: "M9.8 2.4a3.3 3.3 0 0 0-3.9 4.3L2.4 10.2a1.3 1.3 0 0 0 1.8 1.8l3.5-3.5a3.3 3.3 0 0 0 4.3-3.9l-2 2-1.6-.4-.4-1.6z"}]]};
  const firstSentence = (text) => { const one = String(text || "").replace(/\s+/g, " ").trim(); const end = one.search(/[.!?。！？](\s|$)/); return (end > 0 && end < 160 ? one.slice(0, end + 1) : one.slice(0, 160)) + (one.length > 160 && (end < 0 || end >= 160) ? "…" : ""); };
  let barSig = "";
  function paintBar(data) {
    const me = st.head ? st.full.get(st.head) : null;
    const facts = data && data.round ? data.round : null;
    const runningSince = data && data.started ? Date.parse(data.started) : NaN;
    const took = rc.data && typeof rc.data.ms === "number" ? rc.data.ms : null;
    const sig = JSON.stringify([me && me.text, facts, data && data.started, took, st.filter]);
    if (sig !== barSig) {
      barSig = sig;
      setText(barText, me ? firstSentence(me.text) : "");
      const parts = [];
      if (!isNaN(runningSince)) { const clockNode = h("b", null, h("span", {class: "st-time"})); parts.push(h("span", {class: "rb-st", title: t("desk.rounds.time.now")}, lineSvg(RB_ICONS.time), clockNode)); running(clockNode, runningSince); }
      else if (took !== null) parts.push(h("span", {class: "rb-st", title: t("desk.live.receipt.time", {time: clock(took / 1000)})}, lineSvg(RB_ICONS.time), h("b", null, clock(took / 1000))));
      if (facts) {
        parts.push(h("span", {class: "rb-st", title: typeof facts.credits === "number" ? t("desk.live.receipt.credits", {n: rcCredits(facts.credits)}) : t("desk.live.receipt.credits.none")}, lineSvg(RB_ICONS.credits), h("b", null, typeof facts.credits === "number" ? rcCredits(facts.credits) : "-")));
        parts.push(h("span", {class: "rb-st", title: t("desk.live.receipt.calls", {n: facts.calls || 0})}, lineSvg(RB_ICONS.tools), h("b", null, String(facts.calls || 0))));
      }
      if (st.filter && st.filter !== "all") parts.push(h("span", {class: "rb-filter"}, t(FILTER_WORD[st.filter] || FILTER_WORD.all)));  // B19: the page shows only some steps: said where the person looks
      barStats.replaceChildren(...parts);
      if (!isNaN(runningSince)) { Status.clock(); Status.tick(); }
    }
    placeBar();
  }
  function barTop() {  // under the page's own sticky header and tabs
    let top = 0;
    for (const node of document.querySelectorAll(".tk-head, .tk-tabs")) { const style = getComputedStyle(node); if (style.position === "sticky" && node.offsetParent !== null) top = Math.max(top, node.getBoundingClientRect().bottom); }
    return Math.max(0, Math.round(top));
  }
  function placeBar() {
    const me = st.head ? st.nodes.get(st.head) : null;
    const show = Boolean(!root.hidden && st.data && st.data.bound && me && me.el.isConnected && barText.textContent);
    if (!show) { bar.hidden = true; if (toolsWrap.classList.contains("is-finding")) toolsWrap.style.top = barTop() + "px"; return; }
    const top = barTop();
    barWrap.style.top = top + "px";
    const past = me.el.getBoundingClientRect().bottom < top + 8;
    const feedEnd = feed.getBoundingClientRect().bottom > top + 60;
    bar.hidden = !(past && feedEnd);
    if (toolsWrap.classList.contains("is-finding")) toolsWrap.style.top = (top + (bar.hidden ? 0 : bar.offsetHeight + 10)) + "px";  // B20: the search row stays in sight, under the title of the round
  }
  let barFrame = 0;
  window.addEventListener("scroll", () => { if (!barFrame) barFrame = requestAnimationFrame(() => { barFrame = 0; placeBar(); }); }, {passive: true});
  window.addEventListener("resize", () => placeBar(), {passive: true});
  bar.addEventListener("click", () => { const me = st.head ? st.nodes.get(st.head) : null; if (me) window.scrollBy({top: me.el.getBoundingClientRect().top - barTop() - 8, behavior: "smooth"}); });

  // --- the receipt of a round that ended (B6): what it took and what it changed, as icons with numbers; each file opens to its diff ------------------------------------------------
  // The server counts the calls and the files the edit calls changed (`/api/live {receipt: turn}`); the gate's holds and refusals are the rows of its record (`st.gates`) inside the round's time.
  // A number nobody knows is "-", with a tip that says why: never left out.
  const RC_ICONS = {
    time: [["circle", {cx: 8, cy: 8, r: 6}], ["path", {d: "M8 4.8V8l2.2 1.4"}]],  // clock
    credits: [["ellipse", {cx: 8, cy: 4.6, rx: 5, ry: 2}], ["path", {d: "M3 4.6v6.8c0 1.1 2.2 2 5 2s5-.9 5-2V4.6M3 8c0 1.1 2.2 2 5 2s5-.9 5-2"}]],  // coins
    tools: [["path", {d: "M9.8 2.4a3.3 3.3 0 0 0-3.9 4.3L2.4 10.2a1.3 1.3 0 0 0 1.8 1.8l3.5-3.5a3.3 3.3 0 0 0 4.3-3.9l-2 2-1.6-.4-.4-1.6z"}]],  // wrench
    ctx: [["path", {d: "M2.5 11a5.5 5.5 0 1 1 11 0"}], ["path", {d: "M8 11l2.6-3.4"}]],  // a gauge
    files: [["path", {d: "M10 2H5.3A1.3 1.3 0 0 0 4 3.3v7.4A1.3 1.3 0 0 0 5.3 12h6.4a1.3 1.3 0 0 0 1.3-1.3V5z"}], ["path", {d: "M10 2v3h3M2 5v8.7A1.3 1.3 0 0 0 3.3 15H10"}]],  // two sheets
    gate: [["path", {d: "M8 1.8l5.3 2v4.1c0 3-2.3 5.4-5.3 6.3-3-.9-5.3-3.3-5.3-6.3V3.8z"}], ["path", {d: "M6.6 6v4M9.4 6v4"}]],  // a shield, paused
  };
  const rcLi = h("li", {class: "rcpt", hidden: "", "aria-label": t("desk.live.receipt.title")});
  const rc = {turn: "", data: null, busy: false, failedAt: 0, tries: 0, sig: ""};  // tries: questions that found nothing (3 at most, 5 s apart)
  const rcTip = (node, key, tip) => { node._tip = () => tip; node.setAttribute("data-tip", "rc-" + key); node.setAttribute("tabindex", "0"); node.setAttribute("aria-label", tip); return node; };
  const rcStat = (kind, value, tip, cls) => rcTip(h("span", {class: "rc-st" + (cls ? " " + cls : "")}, lineSvg(RC_ICONS[kind]), h("b", null, value)), kind, tip);
  const rcCredits = (value) => (value < 1 ? value.toFixed(2) : amount(value));
  const rcPercent = (value) => (typeof value === "number" ? (value >= 10 ? Math.round(value) : value.toFixed(1).replace(/\.0$/, "")) + "%" : "?");
  function rcGates(data) {  // the gate's record inside the round: from its start to its end, and a few seconds after (the hook writes after the call)
    const start = Date.parse(data.at || ""), length = typeof data.ms === "number" ? data.ms : NaN;
    if (isNaN(start) || isNaN(length)) return null;
    const rows = st.gates.filter((row) => row.ms && row.ms >= start - 2000 && row.ms <= start + length + 5000);
    return {held: rows.filter((row) => row.how === "held").length, refused: rows.filter((row) => row.how !== "held").length};
  }
  function rcFile(file) {
    const row = h("button", {type: "button", class: "rc-row", "aria-expanded": "false"}, h("span", {class: "rc-chev", "aria-hidden": "true"}, "›"), h("code", {title: file.path}, file.path),
      file.new ? h("span", {class: "rc-new"}, t("desk.live.receipt.new")) : null, h("span", {class: "add"}, "+" + file.add), h("span", {class: "del"}, "−" + file.del));
    const body = h("div", {class: "rc-diff", hidden: ""});
    let loaded = false;
    row.addEventListener("click", () => {
      const open = body.hidden;
      body.hidden = !open;
      row.setAttribute("aria-expanded", String(open));
      if (!open || loaded) return;
      loaded = true;
      body.replaceChildren(h("p", {class: "sub"}, spinner()));
      const task = st.task, turn = rc.turn;
      Promise.all((file.calls || []).map((id) => SERVE.post("/api/live", {task, call: {turn, id}}).then((answer) => (answer && answer.call) || {}, () => ({}))))
        .then((details) => {
          if (task !== st.task || turn !== rc.turn) return;
          const files = [];
          let cut = false;
          for (const d of details) for (const part of Array.isArray(d.parts) ? d.parts : []) {
            if (!part || part.k !== "diff") continue;
            cut = cut || Boolean(part.cut);
            for (const one of Array.isArray(part.files) ? part.files : []) if (one && one.path === file.path) files.push(one);
          }
          const nodes = files.length ? diffNodes({files, cut}) : [];
          body.replaceChildren(...(nodes.length ? nodes : [h("p", {class: "sub tc-note"}, t("desk.live.receipt.nodiff"))]));
        });
    });
    return [row, body];
  }
  function rcPaint() {
    const data = rc.data;
    const gates = data ? rcGates(data) : null;
    const sig = JSON.stringify([data, gates]);
    if (sig === rc.sig) return;
    rc.sig = sig;
    if (!data) { rcLi.hidden = true; rcLi.replaceChildren(); return; }
    const seconds = typeof data.ms === "number" ? data.ms / 1000 : null;
    const ctx = data.ctx;
    const files = Array.isArray(data.files) ? data.files : [];
    const changed = files.length + (data.more || 0);
    const stops = gates ? gates.held + gates.refused : null;
    const line = h("div", {class: "rc1"},
      h("span", {class: "rc-n"}, t("desk.live.receipt.title")),
      rcStat("time", seconds === null ? "-" : clock(seconds), seconds === null ? t("desk.live.receipt.time.none") : t("desk.live.receipt.time", {time: clock(seconds)})),
      rcStat("credits", typeof data.credits === "number" ? rcCredits(data.credits) : "-", typeof data.credits === "number" ? t("desk.live.receipt.credits", {n: rcCredits(data.credits)}) : t("desk.live.receipt.credits.none")),
      rcStat("tools", String(data.calls || 0), t("desk.live.receipt.calls", {n: data.calls || 0})),
      rcStat("ctx", ctx ? rcPercent(ctx.from) + " → " + rcPercent(ctx.to) : "-", ctx ? t("desk.live.receipt.ctx", {from: rcPercent(ctx.from), to: rcPercent(ctx.to)}) : t("desk.live.receipt.ctx.none")),
      h("span", {class: "rc-sp"}),
      rcStat("files", String(changed), t("desk.live.receipt.files", {n: changed, add: data.add || 0, del: data.del || 0})),
      h("span", {class: "rc-pm"}, h("span", {class: "add"}, "+" + (data.add || 0)), h("span", {class: "del"}, "−" + (data.del || 0))),
      rcStat("gate", stops === null ? "-" : String(stops), stops === null ? t("desk.live.receipt.gate.none") : t("desk.live.receipt.gate", {held: gates.held, refused: gates.refused}), stops ? "hold" : ""));
    const list = files.length ? h("div", {class: "rc-f"}, ...files.flatMap(rcFile), data.more ? h("p", {class: "sub rc-more"}, t("desk.live.receipt.more", {n: data.more})) : null) : null;
    rcLi.replaceChildren(h("div", {class: "rc-card"}, line, list));
    rcLi.hidden = false;
  }
  function rcFollow(data) {  // after each drawing: a round that ended gets its receipt once; a new round takes it away
    if (rc.turn !== st.turn) { rc.turn = st.turn; rc.data = null; rc.failedAt = 0; rc.tries = 0; rcPaint(); }
    const ended = Boolean(data && data.bound && !data.loading && st.turn && !data.started && data.state !== "busy" && st.nodes.size);
    if (!ended) { rcLi.hidden = true; return; }
    const after = needLi.parentNode === feed ? needLi : null;  // the receipt closes the round: right after its last step, above a card of what waits for you
    if (rcLi.nextSibling !== after || rcLi.parentNode !== feed) feed.insertBefore(rcLi, after);
    if (rc.data || rc.busy || rc.tries >= 3 || Date.now() - rc.failedAt < 5000) { rcPaint(); return; }
    rc.busy = true;
    const task = st.task, turn = st.turn;
    SERVE.post("/api/live", {task, receipt: turn}).then((answer) => {
      rc.busy = false;
      if (task !== st.task || turn !== st.turn) return;
      const found = answer && answer.receipt && typeof answer.receipt === "object" && answer.receipt.turn === turn ? answer.receipt : null;
      rc.turn = turn; rc.data = found;
      if (!found) again();
      rcPaint();
      paintBar(st.data);
    }, () => { rc.busy = false; again(); });
    function again() { rc.failedAt = Date.now(); rc.tries += 1; if (rc.tries < 3) setTimeout(() => { if (turn === st.turn) rcFollow(st.data); }, 5200); }
  }

  // "Earlier steps of this round": up to 60 older steps of the turn, read from the file, go in after the person's message; the place of the reader stays.
  function loadOlder() {
    if (st.loadingOlder || !st.turn || st.reach <= 0) return;
    const task = st.task, turn = st.turn, at = st.reach, epoch = st.epoch;
    st.loadingOlder = true;
    earlier.disabled = true;
    earlierBad.hidden = true;
    SERVE.post("/api/live", {task, before: {turn, i: at}}).then((answer) => {
      if (epoch !== st.epoch || task !== st.task) return;  // another turn or task was opened meanwhile
      const found = (answer && answer.older) || {items: [], before: null};
      const fresh = (found.items || []).filter((item) => item.k !== "me" && !st.full.has(item.id));
      for (const item of fresh) st.full.set(item.id, item);
      st.older = [...new Set([...fresh.map((item) => item.id), ...st.older])];
      st.reach = found.before ? found.before.i || 0 : 0;
      st.loadingOlder = false;
      earlier.disabled = false;
      const keep = new Set(order());
      view(() => show(st.data, null, true), (node) => node !== earlierLi && keep.has(node.dataset.id));
    }, (error) => {
      if (epoch !== st.epoch) return;
      st.loadingOlder = false;
      earlier.disabled = false;
      earlierBad.textContent = (error && error.message) || String(error);
      earlierBad.hidden = false;
    });
  }
  earlier.addEventListener("click", loadOlder);

  function paintLife(data) {
    const bound = Boolean(data && data.bound);
    const state = bound ? (st.starting ? "starting" : data.state) : "";
    life.hidden = !bound;
    root.classList.toggle("is-busy", state === "busy" && !st.answer);  // the robot of the footer works only when the agent does
    const asked = state === "busy" && st.answer;  // busy in the chat, but the agent waits for the person's answer on a held call: not "Working"
    const waits = asked || state === "input" || (state === "idle" && st.needs.length > 0);  // the chat is idle, the task is not: a card above says what it waits for
    setClass(life, "lv-life " + (state === "starting" ? "paused" : state === "error" ? "err" : state === "busy" && !asked ? "run" : waits ? "paused" : "calm"));
    const when = state === "busy" && !asked && data.started ? Date.parse(data.started) : NaN;
    setText(lifeLabel, asked ? t("desk.live.approval") : state === "starting" ? t("waits.starting") : state === "busy" ? t("desk.live.working") : waits ? t("desk.live.input") : state === "error" ? t("waits.error") : t("desk.live.idle"));
    lifeSep.hidden = lifeRun.hidden = isNaN(when);
    if (!isNaN(when)) running(lifeRun, when); else stopped(lifeRun);
    // B15: while it works, what it does now: the host's own words when it gives some (loading plugins, settings), else the step that runs, else that it waits for the model
    const doing = state === "busy" && !asked ? (data.activity || doingNow()) : "";
    lifeDoing.hidden = !doing;
    setText(lifeDoing, doing ? "\u00b7 " + doing : "");
    // B16: shells and subagents that run on after their call, after the round too
    const back = bound && Array.isArray(data.background) ? data.background : [];
    lifeBack.hidden = !back.length;
    setText(lifeBack, back.length ? t("desk.live.background", {n: back.length}) : "");
    if (!back.length) backList.hidden = true;
    const sig = JSON.stringify(back);
    if (backList.dataset.sig !== sig) {
      backList.dataset.sig = sig;
      backList.replaceChildren(...back.map((work) => {
        const shell = work.kind === "shell";
        const stop = shell ? h("button", {type: "button", class: "act lt-bstop"}, t("desk.live.background.stop")) : null;
        const said = h("span", {class: "bad lt-bsaid"});
        if (stop) stop.addEventListener("click", () => {
          stop.disabled = true;
          SERVE.post("/api/bgstop", {task: st.task.split("/").pop(), id: work.id}).then(() => { setText(said, ""); kick(); }, (error) => { stop.disabled = false; setText(said, (error && error.message) || String(error)); });
        });
        return h("li", null, h("span", {class: shell ? "lt-bcmd" : "lt-bname"}, shell ? "$ " + (work.command || work.label || "") : (work.label || work.kind || "")), stop, said);
      }));
    }
  }
  function doingNow() {  // the newest item of the round that runs: a call (its word and target), a thought; nothing running: the model has the turn
    const items = order().map((id) => st.full.get(id)).filter(Boolean);
    const last = items[items.length - 1];
    if (last && last.k === "tool" && (last.st === "run")) return t("desk.live.doing.run", {what: [wordOf(last), last.target || ""].filter(Boolean).join(" ").slice(0, 80)});
    if (last && last.k === "think" && last.run) return t("desk.live.doing.think");
    if (last && last.k === "text" && last.live) return t("desk.live.doing.write");
    return t("desk.live.doing.model");
  }

  // The calm states: no chat, a chat that has not said anything, a link that dropped. One line says what and why.
  function paintCalm(data, items) {
    let title = "", why = "", button = false;
    link.hidden = !data || !data.bound;  // no chat: the window alone is the button of the calm state
    if (!data) { title = t("desk.live.reading"); }
    else if (!data.bound) {
      title = LINK_DOWN.includes(data.why) ? t("desk.live.down") : t("desk.live.none");
      why = t("board.vs.why." + (data.why || "no-chat"));
      button = data.why !== "off" && data.why !== "no-cli";
    } else if (data.loading) title = t("desk.live.reading");
    else if (!items.length) { title = t("desk.live.quiet"); why = t("desk.live.quiet.why"); }
    calm.hidden = !title;
    if (!title) { calm.replaceChildren(); calm.dataset.sig = ""; return; }
    const fresh = Boolean(data && !data.bound && st.task && st.off === "" && ["", "no-chat", "no-session"].includes(data.why || ""));
    const sig = title + "|" + why + "|" + button + "|" + fresh;
    if (calm.dataset.sig === sig) return;
    calm.dataset.sig = sig;
    const open = button ? h("button", {type: "button", class: "act hot live big"}, t(fresh ? "board.go.new" : "desk.live.open")) : null;
    if (open && fresh) open.addEventListener("click", () => chatGoOn(st.task.split("/").pop()));
    else if (open) open.addEventListener("click", () => { open.disabled = true; SERVE.openVS().then(() => { setTimeout(() => { open.disabled = false; }, 1500); }, (error) => { open.disabled = false; SERVE.failed(error, st.chat && st.chat.title); }); });
    calm.replaceChildren(...[robot(), h("h3", null, title), why ? h("p", null, why) : null, open].filter(Boolean));
  }

  function onData(data) {
    if (!data) return;
    if (typeof data.now === "number") st.skew = data.now - Date.now();
    if (data.same) { st.fails = 0; stale.hidden = true; return; }
    const changed = absorb(data);
    if (changed === null) return;  // a stub of an item the page does not have: the next question is for everything, at once
    st.rev = data.rev || "";
    st.data = data;
    stale.hidden = true;
    const keep = new Set(order());
    const same = !changed.size && st.nodes.size === keep.size && [...keep].every((id) => st.nodes.has(id));
    if (same) show(data, changed); else view(() => show(data, changed), (node) => node !== earlierLi && keep.has(node.dataset.id));
    for (const call of st.listeners) { try { call(data); } catch (error) { /* a listener must not stop the stream */ } }
  }

  // --- the poll: once a second while something wants it and the page is seen; never two at a time ---------------------
  const wanted = () => st.wants.size > 0 && Boolean(st.task) && !st.off;
  function loop() {
    st.timer = 0;
    if (!wanted() || document.hidden || st.busy || unseen()) return;  // unseen (common.js): a frame of the workbench that is not shown; the workbench wakes it when it shows
    st.busy = true;
    const task = st.task;
    SERVE.post("/api/live", {task, rev: st.rev, have: st.have}).then((answer) => {
      if (task !== st.task) return;  // another task was opened meanwhile
      st.fails = 0;
      try { onData(answer.live); } catch (error) { console.error("live:", error); throw error; }  // a fault of the drawing is said, not taken for a lost answer
    }, () => { st.fails += 1; if (st.fails >= 2) stale.hidden = false; }).then(() => {
      st.busy = false;
      const hurry = st.hurry; st.hurry = false;
      if (wanted() && !document.hidden && !st.timer) st.timer = setTimeout(loop, hurry ? 0 : st.fails ? SLOW : EVERY);
    });
  }
  function kick() { if (wanted() && !document.hidden && !st.timer && !st.busy) st.timer = setTimeout(loop, 0); }
  document.addEventListener("visibilitychange", () => { if (document.hidden) { clearTimeout(st.timer); st.timer = 0; } else { st.arriveDue = true; kick(); } });

  // --- B19: show only some steps of the round (prototype 6 pin 3) ------------------------------------------------------------------------------------------
  // The chips count the steps of the whole round: those on the page, and those the page has not loaded yet (the server counts them once per place: they are over and do not change). A chip
  // shows only its steps, one row each, no groups; what the person and the agent said stays as a grey line to know where one is; the steps between are one line "N steps hidden". A filter
  // first loads the whole round. A new round shows all of itself again.
  const TOOLS_AT = 6;  // steps in the round before the row shows (a search or a filter on keeps it)
  const THREAD = ["me", "text", "err"];
  const isStep = (rec) => Boolean(rec && rec.el) && !THREAD.includes(rec.kind) && !(rec.kind === "note" && rec.item && rec.item.starts);
  function facetsOf(rec) {
    const item = rec.item || {}, out = [];
    if (rec.kind === "tool") {
      if (rec.el.classList.contains("is-fail")) out.push("fail");
      if (item.kind === "edit" || item.kind === "create") out.push("change");
      if (item.kind === "run") out.push("run");
      if (rec.el.classList.contains("is-wait")) out.push("wait");
    } else if (rec.kind === "ask" && item.st === "wait") out.push("wait");
    return out;
  }
  st.hidPool = [];
  function filtered(nodes) {
    const out = [];
    let hidden = 0, used = 0;
    const flush = () => {
      if (!hidden) return;
      let li = st.hidPool[used];
      if (!li) { li = h("li", {class: "fi lv-hid", "data-id": "~h" + used}); st.hidPool.push(li); }
      setText(li, hidden === 1 ? t("desk.live.filter.hidden.one") : t("desk.live.filter.hidden", {n: hidden}));
      used += 1; out.push(li); hidden = 0;
    };
    for (const node of nodes) {
      const rec = node && node.el ? node : null;
      if (!rec) { out.push(node); continue; }
      if (!isStep(rec) || facetsOf(rec).includes(st.filter)) { flush(); rec.el.hidden = false; out.push(rec.el); continue; }
      rec.el.hidden = true; out.push(rec.el); hidden += 1;
    }
    flush();
    for (const li of st.hidPool.slice(used)) li.remove();
    return out;
  }
  function paintTools(data) {
    const recs = order().map((id) => st.nodes.get(id)).filter(Boolean);
    const counts = {all: 0, fail: 0, change: 0, run: 0, wait: 0};
    for (const rec of recs) { if (!isStep(rec)) continue; counts.all += 1; for (const name of facetsOf(rec)) counts[name] += 1; }
    const extra = st.counts && st.counts.turn === st.turn && st.counts.before === st.reach ? st.counts : null;
    if (st.reach > 0 && !extra) askCounts();
    if (extra) for (const name of FILTERS) if (name !== "wait") counts[name] += Number(extra[name]) || 0;  // a step that was let go of waits no more
    const on = st.filter && st.filter !== "all";
    tools.hidden = !(data && data.bound && (counts.all >= TOOLS_AT || on || !findRow.hidden));
    for (const [name, chip] of chipNodes) {
      const mine = st.filter === name || (!on && name === "all");
      chip.classList.toggle("on", mine);
      chip.setAttribute("aria-pressed", String(mine));
      setText(chip.lastChild, String(counts[name]) + (st.reach > 0 && !extra && name !== "wait" ? "+" : ""));
      chip.disabled = !mine && name !== "all" && counts[name] === 0;
    }
  }
  function askCounts() {
    const key = st.turn + "|" + st.reach;
    if (st.countsAsked === key || Date.now() - (st.countsFailed || 0) < 10000) return;
    st.countsAsked = key;
    const task = st.task, turn = st.turn, before = st.reach;
    SERVE.post("/api/live", {task, counts: {turn, before}}).then((answer) => {
      const found = answer && answer.counts;
      if (task !== st.task || turn !== st.turn || !found || found.turn !== turn) return;
      st.counts = found;
      paintTools(st.data);
    }, () => { st.countsAsked = ""; st.countsFailed = Date.now(); });
  }
  // The whole round on the page: every step the page has not loaded, from the file, at once (a filter, a search). One question at a time; the place of the reader stays.
  function loadAll() {
    if (!st.turn || st.reach <= 0) return Promise.resolve(true);
    if (st.loadingAll) return st.loadingAll;
    const task = st.task, turn = st.turn, epoch = st.epoch;
    st.loadingAll = SERVE.post("/api/live", {task, before: {turn, i: st.reach}, all: true}).then((answer) => {
      st.loadingAll = null;
      if (epoch !== st.epoch || task !== st.task) return false;
      const found = (answer && answer.older) || {items: [], before: null};
      const fresh = (found.items || []).filter((item) => item.k !== "me" && !st.full.has(item.id));
      for (const item of fresh) st.full.set(item.id, item);
      st.older = [...new Set([...fresh.map((item) => item.id), ...st.older])];
      st.reach = found.before ? found.before.i || 0 : 0;
      const keep = new Set(order());
      if (st.data) view(() => show(st.data, null, true), (node) => node !== earlierLi && keep.has(node.dataset.id));
      return true;
    }, (error) => { st.loadingAll = null; throw error; });
    return st.loadingAll;
  }
  function toolsInView() {  // after a change of filter the row stays where the person looks: brought under the title bar when it went above
    const box = toolsWrap.getBoundingClientRect(), top = barTop();
    if (box.top < top || box.top > window.innerHeight - 80) window.scrollBy({top: box.top - top - 8, behavior: "instant"});
  }
  function setFilter(name) {
    st.filter = name === st.filter || !FILTERS.includes(name) ? "all" : name;  // the chip that is on, again: back to All
    filterSaid.hidden = true;
    const draw = () => { if (st.data) { show(st.data, null, false); toolsInView(); } };
    if (st.filter !== "all" && st.reach > 0) {
      setText(filterSaid, t("desk.live.filter.loading")); filterSaid.hidden = false;
      loadAll().then(() => { filterSaid.hidden = true; draw(); }, (error) => { setText(filterSaid, (error && error.message) || String(error)); });
    }
    draw();
  }
  for (const [name, chip] of chipNodes) chip.addEventListener("click", () => setFilter(name));

  // --- B20: search the whole round (prototype 6 pin 4) ---------------------------------------------------------------------------------------------------
  // The server looks in every part of the round (`/api/live {find: {turn, q}}`): the words, the thoughts, every call's command, input, output and diff, also those folded and those not loaded.
  // ↑ ↓ (Enter, Shift+Enter) go from hit to hit: the round is loaded whole when needed, the group opens, the step opens on the tab of the hit, and every place of the words in it is marked
  // (the CSS highlight of the browser: nothing in the page is changed). Only this round.
  const MARK = typeof window.Highlight === "function" ? window.Highlight : null;  // the browser's own: the page's syntax colouring (highlight.js) has the name `Highlight` too
  const HL = Boolean(typeof CSS !== "undefined" && CSS.highlights && MARK);
  const fd = {q: "", hits: [], at: -1, more: false, timer: 0, seq: 0};
  const REGION = {command: ".tc-cmd", input: ".tc-in", output: ".tc-body .tc-box:not(.tc-in)", diff: ".tc-body", text: ".tx", think: ".tx", me: ".me-tx", ask: ".fb", line: ".tc-line", note: ".note-tx"};
  function openFind() {
    findRow.hidden = false;
    toolsWrap.classList.add("is-finding");
    placeBar();
    paintTools(st.data);
    findInput.focus();
    findInput.select();
  }
  function shutFind() {
    clearTimeout(fd.timer);
    fd.seq += 1; fd.q = ""; fd.hits = []; fd.at = -1; fd.more = false;
    findInput.value = "";
    findRow.hidden = true;
    toolsWrap.classList.remove("is-finding");
    toolsWrap.style.top = "";
    findWhere.hidden = true;
    setText(findN, "");
    clearMarks();
    if (st.data) paintTools(st.data);
  }
  function clearMarks() { if (HL) { CSS.highlights.delete("lv-find"); CSS.highlights.delete("lv-find-now"); } }
  function runFind(now) {
    clearTimeout(fd.timer);
    const q = findInput.value.trim();
    if (!q) { fd.seq += 1; fd.q = ""; fd.hits = []; fd.at = -1; paintFind(); clearMarks(); return; }
    fd.timer = setTimeout(() => {
      const seq = ++fd.seq, task = st.task, turn = st.turn;
      setText(findN, t("desk.live.find.busy"));
      SERVE.post("/api/live", {task, find: {turn, q}}).then((answer) => {
        if (seq !== fd.seq || task !== st.task) return;
        const found = (answer && answer.find) || {};
        fd.q = q; fd.hits = Array.isArray(found.hits) ? found.hits : []; fd.more = Boolean(found.more); fd.at = -1; fd.size = order().length;
        if (fd.hits.length) goHit(0); else { paintFind(); clearMarks(); }
      }, (error) => { if (seq === fd.seq) setText(findN, (error && error.message) || String(error)); });
    }, now ? 0 : 250);
  }
  // The round grew while the search is open: asked again (at most every 3 s), the count changes, the place the person is at stays
  function refreshFind() {
    fd.size = order().length;
    if (fd.refreshing || Date.now() - (fd.refreshed || 0) < 3000) return;
    fd.refreshing = true;
    const seq = fd.seq, task = st.task, q = fd.q, was = fd.hits[fd.at];
    SERVE.post("/api/live", {task, find: {turn: st.turn, q}}).then((answer) => {
      fd.refreshing = false; fd.refreshed = Date.now();
      if (seq !== fd.seq || task !== st.task || q !== fd.q) return;
      const found = (answer && answer.find) || {};
      fd.hits = Array.isArray(found.hits) ? found.hits : []; fd.more = Boolean(found.more);
      const again = was ? fd.hits.findIndex((one) => one.id === was.id && one.where === was.where && one.line === was.line) : -1;
      fd.at = again >= 0 ? again : Math.min(fd.at, fd.hits.length - 1);
      paintFind();
    }, () => { fd.refreshing = false; fd.refreshed = Date.now(); });
  }
  function whereWords(hit) {
    const item = st.full.get(hit.id);
    const base = hit.where === "line" ? "" : hit.where === "output" ? t("desk.live.find.where.output", {line: hit.line}) : (WHERE_WORD[hit.where] ? t(WHERE_WORD[hit.where]) : "");
    const what = item && item.k === "tool" ? [wordOf(item), item.target || ""].filter(Boolean).join(" ").replace(/\s+/g, " ").slice(0, 90) : "";
    return [base, what].filter(Boolean).join(" · ") || t("desk.live.find.where.line");
  }
  function paintFind() {
    const count = fd.hits.length;
    setText(findN, !fd.q ? "" : !count ? t("desk.live.find.none") : t(fd.more ? "desk.live.find.n.more" : "desk.live.find.n", {at: Math.max(1, fd.at + 1), n: count}));
    findN.classList.toggle("bad", Boolean(fd.q) && !count);
    findUp.disabled = findDown.disabled = count < 2;
    const hit = fd.hits[fd.at];
    findWhere.hidden = !hit;
    if (hit) findWhere.replaceChildren(h("span", {class: "lv-find-w"}, whereWords(hit)), h("span", {class: "lv-find-snip"}, hit.snip[0], h("mark", null, hit.snip[1]), hit.snip[2]));
  }
  function goHit(at) {
    if (!fd.hits.length) return;
    fd.at = (at + fd.hits.length) % fd.hits.length;
    const hit = fd.hits[fd.at], seq = fd.seq;
    paintFind();
    const step = () => {
      if (seq !== fd.seq || hit !== fd.hits[fd.at]) return;
      const rec = st.nodes.get(hit.id);
      if (!rec) { setText(findN, t("desk.live.find.gone")); return; }
      if (st.filter !== "all" && rec.el.hidden) { st.filter = "all"; show(st.data, null, false); }
      for (const group of st.groups.values()) if (group.members.includes(rec) && !group.open) { group.open = true; paintGroup(group); }
      paintFind();
      const nth = fd.hits.slice(0, fd.at).filter((one) => one.id === hit.id && one.where === hit.where).length;
      const mark = () => markHit(rec, hit, nth, false);
      if (rec.kind === "tool" && ["command", "input", "output", "diff"].includes(hit.where) && canOpen(rec)) {
        const tab = hit.where === "input" ? "in" : "out";
        if (hit.where === "output" && hit.line <= hit.lines - OUT_TAIL) rec.all = true;  // above the last lines shown first
        const redraw = rec.tab !== tab || (hit.where === "output" && rec.all);
        rec.tab = tab;
        if (!rec.open) { rec.open = true; syncOpen(rec); rec.onDrawn = mark; fetchCall(rec); }
        else if (!rec.detail || rec.loading) rec.onDrawn = mark;
        else { if (redraw) drawBody(rec); mark(); }
        rec.el.scrollIntoView({block: "center"});
        return;
      }
      if (rec.kind === "think" && !rec.open && rec.item && rec.item.text) { rec.open = true; paintThought(rec, rec.item); }
      if (rec.kind === "text" && rec.foldable && !rec.open) { rec.open = true; applyFold(rec); }
      if (rec.kind === "me" && !rec.mopen) { rec.mopen = true; paintMe(rec); }
      if (rec.kind === "ask" && !rec.open && rec.item && rec.item.st !== "wait") { rec.open = true; paintAsk(rec, rec.item); }
      mark();
    };
    if (!st.full.has(hit.id) && st.reach > 0) loadAll().then(step, (error) => { setText(findN, (error && error.message) || String(error)); });
    else step();
  }
  function rangesIn(node, needle) {
    const out = [];
    if (!node || !needle) return out;
    const walk = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    for (let text = walk.nextNode(); text && out.length < 400; text = walk.nextNode()) {
      const low = text.nodeValue.toLowerCase();
      for (let at = low.indexOf(needle); at >= 0 && out.length < 400; at = low.indexOf(needle, at + needle.length)) {
        const range = document.createRange();
        range.setStart(text, at); range.setEnd(text, at + needle.length);
        out.push(range);
      }
    }
    return out;
  }
  function markHit(rec, hit, nth, again) {
    if (!rec.el.isConnected) return;
    const needle = fd.q.toLowerCase();
    const region = rec.el.querySelector(REGION[hit.where] || ".fb") || rec.el;
    let ranges = rangesIn(region, needle);
    if (!ranges.length && rec.kind === "tool" && hit.where === "output" && !rec.all && !again) { rec.all = true; drawBody(rec); markHit(rec, hit, nth, true); return; }  // cut from the tail shown first
    if (!ranges.length) ranges = rangesIn(rec.el, needle);
    const now = ranges.length ? ranges[Math.min(nth, ranges.length - 1)] : null;
    if (HL) {
      if (ranges.length) CSS.highlights.set("lv-find", new MARK(...ranges)); else CSS.highlights.delete("lv-find");
      if (now) CSS.highlights.set("lv-find-now", new MARK(now)); else CSS.highlights.delete("lv-find-now");
    }
    const holder = now ? (now.startContainer.parentElement || rec.el).closest(".tc-box, .tx, .dv-body, .tc-body") : null;  // a box with its own scroll: its place first
    if (holder && holder.scrollHeight > holder.clientHeight + 2) { const inner = now.getBoundingClientRect(), outer = holder.getBoundingClientRect(); holder.scrollTop += inner.top - outer.top - holder.clientHeight / 2; }
    const box = now ? now.getBoundingClientRect() : rec.el.getBoundingClientRect();
    const top = Math.max(barTop() + 70, toolsWrap.classList.contains("is-finding") ? toolsWrap.getBoundingClientRect().bottom + 24 : 0), bottom = window.innerHeight - 110;  // below the search row that stays on top
    if (box.top < top || box.bottom > bottom) window.scrollBy({top: box.top - (top + bottom) / 2, behavior: "instant"});
    flash(rec.el);
  }
  findBtn.append(svg(ICONS.search, 15));
  findBtn.addEventListener("click", () => (findRow.hidden ? openFind() : shutFind()));
  findInput.addEventListener("input", () => runFind(false));
  findInput.addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    if (event.key === "Enter") {
      event.preventDefault();
      if (findInput.value.trim() !== fd.q) runFind(true); else goHit(fd.at + (event.shiftKey ? -1 : 1));
    } else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); shutFind(); findBtn.focus({preventScroll: true}); }
    else if (event.key === "ArrowDown") { event.preventDefault(); goHit(fd.at + 1); }
    else if (event.key === "ArrowUp") { event.preventDefault(); goHit(fd.at - 1); }
  });
  findUp.addEventListener("click", () => goHit(fd.at - 1));
  findDown.addEventListener("click", () => goHit(fd.at + 1));
  findShut.addEventListener("click", () => { shutFind(); findBtn.focus({preventScroll: true}); });
  document.addEventListener("keydown", (event) => {  // / opens the search; so does Ctrl+F (Cmd+F) while the Live tab is shown, and once more inside the box gives the browser's own
    if (root.hidden || !st.data || !st.data.bound || event.isComposing || event.defaultPrevented) return;
    if (typeof SERVE !== "undefined" && SERVE.open && SERVE.open()) return;
    const inField = event.target instanceof Element && (/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName) || event.target.isContentEditable);
    if (event.key === "/" && !inField && !event.metaKey && !event.ctrlKey && !event.altKey) { event.preventDefault(); openFind(); return; }
    if ((event.key === "f" || event.key === "F") && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && document.activeElement !== findInput && !inField) { event.preventDefault(); openFind(); }
  });

  // --- B18: back after you left (prototype 6 pin 2) -----------------------------------------------------------------------------------------------------
  // While the Live tab is seen, the last step in the window is kept in this browser, per task (it only moves down in a round). When the person comes back (the page opened again, the tab or the
  // window shown again) after a minute or more, and the round has steps after that one, a dashed line goes after it with what happened since: steps done, failed, what waits; the page goes to it.
  // Mark as seen takes it away. The line stays while the person reads on; the next return puts a new one.
  const SEEN_KEY = "harness.live.seen", AWAY_MS = 60000, SEEN_TASKS = 60;
  function seenAll() { try { const all = JSON.parse(localStorage.getItem(SEEN_KEY) || "{}"); return all && typeof all === "object" ? all : {}; } catch (error) { return {}; } }
  function seenOf(task) { const one = seenAll()[task]; return one && typeof one === "object" && typeof one.ms === "number" && typeof one.id === "string" ? one : null; }
  function keepSeen(mark) {
    try {
      const all = seenAll();
      all[st.task] = mark;
      const names = Object.keys(all);
      if (names.length > SEEN_TASKS) { names.sort((a, b) => ((all[a] || {}).ms || 0) - ((all[b] || {}).ms || 0)); for (const name of names.slice(0, names.length - SEEN_TASKS)) delete all[name]; }
      localStorage.setItem(SEEN_KEY, JSON.stringify(all));
    } catch (error) { /* no storage: no line */ }
  }
  let seenFrame = 0, seenSig = "";
  const seenSoon = () => { if (!seenFrame) seenFrame = requestAnimationFrame(noteSeen); };
  window.addEventListener("scroll", seenSoon, {passive: true});
  function lastSeenId() {
    let found = "";
    const end = window.innerHeight - 60;
    for (const node of feed.children) {
      if (node.hidden || !node.dataset || !node.dataset.id) continue;
      const box = node.getBoundingClientRect();
      if (!box.height) continue;
      if (box.top >= end) break;
      const id = node.dataset.id;
      if (id.startsWith("~g:")) { const group = [...st.groups.values()].find((one) => one.li === node); const last = group && group.members[group.members.length - 1]; if (last && last.item) found = last.item.id; }
      else if (!id.startsWith("~")) found = id;
    }
    return found;
  }
  function noteSeen() {
    seenFrame = 0;
    if (document.hidden || root.hidden || st.arriveDue || !st.task || !st.turn || !st.data || !st.data.bound) return;
    const id = lastSeenId();
    if (!id) return;
    const ids = order(), old = seenOf(st.task);
    const keepId = old && old.turn === st.turn && ids.indexOf(old.id) > ids.indexOf(id) ? old.id : id;  // reading up does not move it back
    const sig = st.turn + "|" + keepId, now = Date.now();
    if (sig === seenSig && old && now - old.ms < 5000) return;
    seenSig = sig;
    keepSeen({turn: st.turn, id: keepId, ms: now});
  }
  function arrive() {
    st.arriveDue = false;
    const mark = seenOf(st.task);
    if (!mark || Date.now() - mark.ms < AWAY_MS) return;
    const ids = order();
    let at = -1;
    const fresh = mark.turn !== st.turn;
    if (!fresh) { at = ids.indexOf(mark.id); if (at < 0 && !(st.reach > 0)) return; }
    else at = ids.indexOf(st.head);
    const after = ids.slice(at + 1).map((id) => st.full.get(id)).filter(Boolean);
    if (!after.some((item) => item.k !== "me")) return;
    st.since = {id: at >= 0 ? ids[at] : "", ms: mark.ms, fresh, jump: true, away: Date.now() - mark.ms, sig: ""};
  }
  function sinceAt(nodes) {  // where the line goes among the nodes of the feed: after the step last seen, else at the top of what is loaded
    const since = st.since;
    if (!since || !st.data || !st.data.bound) return -1;
    if (since.id) {
      const rec = st.nodes.get(since.id);
      const at = rec ? nodes.indexOf(rec.el) : -1;
      if (at < 0) { st.since = null; return -1; }
      let end = at + 1;
      while (end < nodes.length && nodes[end] === earlierLi) end += 1;
      return end;
    }
    const top = nodes.indexOf(earlierLi);
    return top >= 0 ? top + 1 : 0;
  }
  function paintSince() {
    const since = st.since;
    if (!since) return;
    const ids = order();
    const at = since.id ? ids.indexOf(since.id) : -1;
    let done = 0, failed = 0;
    for (const id of ids.slice(at + 1)) {
      const rec = st.nodes.get(id);
      if (!rec || !isStep(rec)) continue;
      if (!rec.el.classList.contains("is-run") && !rec.el.classList.contains("is-wait") && !(rec.kind === "think" && rec.item && rec.item.run)) done += 1;
      if (rec.el.classList.contains("is-fail")) failed += 1;
    }
    const waits = waitsNow().count;
    const time = new Date(since.ms).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
    const plus = !since.id && st.reach > 0 ? "+" : "";
    const sig = [since.fresh, time, done, failed, waits, plus].join("|");
    if (sig === since.sig) return;
    since.sig = sig;
    setText(sinceText, t(since.fresh ? "desk.live.since.new" : "desk.live.since.line", {time}));
    const num = (value, key, cls) => h("span", {class: "lv-since-n" + (cls ? " " + cls : "")}, t(key, {n: String(value) + (key === "desk.live.since.done" ? plus : "")}));
    sinceSum.replaceChildren(...[h("span", null, t("desk.live.since.away", {time: clock(since.away / 1000)})), num(done, "desk.live.since.done"),
      failed ? num(failed, "desk.live.since.fail", "bad") : null, waits ? num(waits, "desk.live.since.wait", "hot") : null].filter(Boolean));
  }
  // The page goes to the line once it is drawn; and again a moment later if what loads above it (the receipt, the cards) pushed it away and the person has not moved the page themself.
  let moved = false;
  for (const name of ["wheel", "touchstart", "keydown", "mousedown"]) window.addEventListener(name, () => { moved = true; }, {passive: true, capture: true});
  function toSince() {
    moved = false;
    const go = () => { if (!sinceLi.isConnected || root.hidden) return; const box = sinceLi.getBoundingClientRect(), top = barTop() + 70; if (Math.abs(box.top - top) > 40) window.scrollBy({top: box.top - top, behavior: "instant"}); };
    requestAnimationFrame(go);
    for (const wait of [400, 1200]) setTimeout(() => { if (!moved) go(); }, wait);
  }
  sinceSeen.addEventListener("click", () => {
    const next = sinceLi.nextElementSibling;
    st.since = null;
    sinceLi.remove();
    const target = next && next.querySelector("button:not([disabled])");  // the keyboard stays where the line was
    if (target) target.focus({preventScroll: true});
    const ids = order();
    if (ids.length) { keepSeen({turn: st.turn, id: ids[ids.length - 1], ms: Date.now()}); seenSig = ""; }
  });

  // --- B17: ask about this (prototype 6 pin 1) ----------------------------------------------------------------------------------------------------------
  // An opened call has Ask: the reply box gets a quote of it (which step, the command, its exit) and the lines the person selected in it, else the last lines of its output or the start of its
  // diff; the person adds a sentence. The agent gets the quote and the words as one message.
  const QUOTE_LINES = 30, QUOTE_CHARS = 3000, QUOTE_TAIL = 5;
  function pickedIn(node) {
    const sel = window.getSelection();
    if (!node || !sel || sel.isCollapsed || !sel.rangeCount) return "";
    return node.contains(sel.getRangeAt(0).commonAncestorContainer) ? sel.toString() : "";
  }
  function quoteOf(rec, picked, exit) {
    const item = rec.item || {}, d = rec.detail || {};
    const calls = order().filter((id) => (st.full.get(id) || {}).k === "tool");
    const n = !rec.fixed && !rec.subCall && st.reach === 0 ? calls.indexOf(item.id) + 1 : 0;
    const what = (d.command ? String(d.command) : [wordOf(item), item.target || ""].filter(Boolean).join(" ")).replace(/\s+/g, " ").trim().slice(0, 200);  // a command says its program itself
    const title = [n > 0 ? t("desk.live.ask.step", {n}) : "", what, typeof exit === "number" ? t("desk.live.call.exit", {code: exit}) : ""].filter(Boolean).join(" · ");
    let lines = [];
    if (picked.trim()) lines = picked.replace(/\s+$/, "").split("\n");
    else {
      const parts = Array.isArray(d.parts) ? d.parts : [];
      const diff = parts.find((part) => part && part.k === "diff" && Array.isArray(part.files) && part.files.length);
      const said = parts.find((part) => part && ["term", "text", "file"].includes(part.k) && String(part.text || "").trim());
      if (diff) { const file = diff.files[0]; lines = [String(file.path || "")].concat((Array.isArray(file.lines) ? file.lines : []).slice(0, 12).map(String)); }
      else if (said) lines = String(said.text).replace(/\s+$/, "").split("\n").slice(-QUOTE_TAIL);
      else if (d.error || d.reason) lines = [String(d.error || d.reason)];
    }
    if (lines.length > QUOTE_LINES) lines = lines.slice(0, QUOTE_LINES).concat("…");
    let text = lines.join("\n");
    if (text.length > QUOTE_CHARS) text = text.slice(0, QUOTE_CHARS) + "…";
    return {title, lines: text ? text.split("\n") : []};
  }
  function askButton(rec, exit) {
    if (typeof REPLY === "undefined" || !REPLY.quote || !REPLY.shown()) return null;
    const button = h("button", {type: "button", class: "tc-ask", title: t("desk.live.ask.about.tip")}, svg(ICONS.ask, 13), h("span", null, t("desk.live.ask.about")));
    let picked = "";
    button.addEventListener("mousedown", () => { picked = pickedIn(rec.tb); });  // before the click takes the selection away
    button.addEventListener("click", () => { const chosen = picked || pickedIn(rec.tb); picked = ""; REPLY.quote(quoteOf(rec, chosen, exit)); });
    return button;
  }

  // --- what the page gives -------------------------------------------------------------------------------------------------
  return {
    node: root,
    // `task`: the folder name of the task; `off`: why nothing is followed ("" when it is: a closed task or a task not started has no chat to follow); `chat`: desk.chat (its title for the copy button).
    config(info) {
      if (info.task !== st.task) {  // another task: nothing of the first one is kept
        st.task = info.task; st.rev = ""; st.data = null; st.fails = 0; st.turn = "";
        forget();
        st.arriveDue = true; shutFind();
        PANEL.reset();
        show(null);
      }
      if (typeof ROUNDS !== "undefined") { if (!info.off) roundsHere(ROUNDS.node); ROUNDS.follow(info.task); }
      st.chat = info.chat || null;
      const heldNow = (info.held || []).map(flat);
      const approvedNow = (info.approved || []).map(flat);
      const gatesNow = (info.gates || []).map((row) => ({command: flat(row.command), how: row.how === "held" ? "held" : "refused", reason: flat(row.reason).slice(0, 240), ms: Date.parse(row.at || "") || 0})).filter((row) => row.command);
      const gatesKey = JSON.stringify(gatesNow);
      if (heldNow.join("\n") !== st.held.join("\n") || approvedNow.join("\n") !== st.approved.join("\n") || gatesKey !== st.gatesKey) {
        st.held = heldNow; st.approved = approvedNow; st.gates = gatesNow; st.gatesKey = gatesKey;
        st.marks = markGates([...st.nodes.values()].map((rec) => rec.item).filter(Boolean));
        for (const rec of st.nodes.values()) if (rec.item) paint(rec, rec.item);  // a card that arrives later changes how its call reads
        if (rc.data) rcPaint();  // the receipt counts the gate's record too
      }
      st.off = info.off || "";
      const answer = Boolean(info.answer);  // the agent sits in `harness wait --approval`: the chat is busy, but the agent waits for the person (1.7.38, C12 TB-15)
      const starting = Boolean(info.starting);  // 1.8.5: the board sent something and the agent has not started: the footer does not say what the chat said before
      if (answer !== st.answer || starting !== st.starting) { st.answer = answer; st.starting = starting; if (st.data) paintLife(st.data); }
      const nothing = st.chat && !st.chat.bound ? st.chat.why || "" : "";
      link.title = nothing === "no-cli" || nothing === "off" ? t("board.vs.why." + nothing) : t("board.vs.open");
      link.disabled = nothing === "no-cli" || nothing === "off";
      if (st.off) { clearTimeout(st.timer); st.timer = 0; }
      else if (!st.data && st.chat && !st.chat.bound) show({bound: false, why: st.chat.why || "no-chat"});  // the page already knows: no wait for the first answer
      kick();
    },
    // `key` wants the poll (the open tab, the open reply panel) or lets go of it.
    want(key, on) {
      if (on) st.wants.add(key); else st.wants.delete(key);
      if (!wanted()) { clearTimeout(st.timer); st.timer = 0; } else kick();
    },
    onChange(call) { st.listeners.push(call); },
    data: () => st.data,
    // The cards of what needs the person, drawn by desk.js (the same ones as above the tabs), go at the end of the stream, where the agent stopped.
    needs(nodes) {
      const list = nodes ? [nodes].flat(Infinity).filter((node) => node instanceof Node) : [];
      const box = needLi.lastChild;
      const same = list.length === st.needs.length && list.every((node, at) => node === st.needs[at]);
      if (same) return;
      st.needs = list;
      queueWaits();
      view(() => { box.replaceChildren(...list); needLi.hidden = list.length === 0; });
      if (st.data) paintLife(st.data);
    },
    drawing(draw) { st.draw = draw; },
    // A static list of finished items (an opened round, rounds.js): drawn as the feed is, and nothing in it acts on the running chat. The person's own message is not in it (the round has its own prompt line).
    draw(items, turn) {
      const list = h("ol", {class: "lv-feed lv-static"});
      const shown = [], recs = [];
      for (const item of items || []) {
        if (!item || item.k === "me" || !item.id) continue;
        const done = Object.assign({}, item, {live: false, run: false, st: item.st === "run" ? "done" : item.st});
        if (done.sub) done.sub = Object.assign({}, done.sub, {st: done.sub.st === "run" || done.sub.st === "wait" ? "done" : done.sub.st});
        shown.push(done);
        const rec = make(done, true, turn);
        rec.list = () => shown;  // the panel's tabs: the subagents of this round
        paint(rec, done);
        recs.push(rec);
      }
      list.append(...fold(recs, false, new Map()));
      return list;
    },
    visible(on) { const was = root.hidden; root.hidden = !on; if (on && was) st.arriveDue = true; if (on) kick(); },
  };
})();
