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

  const st = {task: "", rev: "", nodes: new Map(), wants: new Set(), timer: 0, busy: false, fails: 0, skew: 0, data: null, off: "", chat: null, held: [], approved: [], gates: [], marks: new Map(), listeners: [], needs: [], started: "", answer: false,
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
    tool: ["M10.5 2.5a3 3 0 0 0-3.8 3.8L2.5 10.5l3 3 4.2-4.2a3 3 0 0 0 3.8-3.8l-1.9 1.9-1.6-.4-.4-1.6z"], clock: ["M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2zM8 5v3l2 1.5"],
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
  const life = h("div", {class: "lv-life calm"}, robot(), h("span", {class: "eq", "aria-hidden": "true"}, h("i"), h("i"), h("i"), h("i")), h("span", {class: "lt"}, lifeLabel, lifeSep, lifeRun));
  const root = h("section", {class: "lv", hidden: ""}, head, stale, feed, calm, life);
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
      body.append(rec.tag);
    } else if (item.k === "text") {
      rec.tx = h("div", {class: "tx md"});
      rec.cutm = h("span", {class: "cutm", hidden: ""}, t("desk.live.cut"));
      rec.caret = h("span", {class: "caret", hidden: ""});
      rec.pill = h("button", {type: "button", class: "lv-unfold", hidden: "", "aria-expanded": "false"});
      rec.pill.addEventListener("click", () => { rec.open = !rec.open; applyFold(rec); if (!rec.open) keepPill(rec); });
      body.append(rec.tx, rec.pill, rec.cutm);
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
      paintFacts(rec, item, refused);
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
    } else {
      paintThought(rec, item);
    }
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
    const sig = out.map((node) => node.className + node.textContent).join("|");
    if (sig !== rec.fxSig) { rec.fxSig = sig; rec.fx.replaceChildren(...out); }
  }

  function toggle(rec) {
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
    if (run && d.command) out.push(h("div", {class: "tc-cmd"}, h("span", {class: "tc-ps", "aria-hidden": "true"}, "$ "), String(d.command)), d.command_cut ? note("desk.live.call.cut") : null);
    if (input || (run && exit !== null)) {
      const pick = (name, key) => {
        const button = h("button", {type: "button", role: "tab", class: "tc-tab" + (tab === name ? " on" : ""), "aria-selected": String(tab === name), "data-tab": name}, t(key));
        button.addEventListener("click", () => { rec.tab = name; drawBody(rec); const again = rec.tb.querySelector('.tc-tab[data-tab="' + name + '"]'); if (again) again.focus(); });
        return button;
      };
      out.push(h("div", {class: "tc-tabs", role: "tablist"}, pick("out", run ? "desk.live.call.output" : "desk.live.call.result"), input ? pick("in", "desk.live.call.input") : null, h("span", {class: "tc-sp"}),
        run && exit !== null ? h("span", {class: "tc-exit " + (exit === 0 ? "ok" : "bad")}, t("desk.live.call.exit", {code: exit})) : null));
    }
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
    st.head = ""; st.older = []; st.tail = []; st.reach = 0; st.seen = false; st.have = -1; st.loadingOlder = false;
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
      nodes.push(rec.el);
      if (item.id === st.head) nodes.push(earlierLi);
    }
    if (!nodes.includes(earlierLi)) nodes.unshift(earlierLi);
    let expected = feed.firstChild;
    for (const node of nodes) {
      if (node !== expected) feed.insertBefore(node, expected); else expected = expected.nextSibling;
    }
    earlierLi.hidden = !(data && data.bound && ids.length && st.reach > 0);
    paintCalm(data, items);
    paintLife(data);
    if (feed.querySelector(".st-run[data-since]") || life.querySelector(".st-run[data-since]")) { Status.clock(); Status.tick(); }
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
      onData(answer.live);
    }, () => { st.fails += 1; if (st.fails >= 2) stale.hidden = false; }).then(() => {
      st.busy = false;
      const hurry = st.hurry; st.hurry = false;
      if (wanted() && !document.hidden && !st.timer) st.timer = setTimeout(loop, hurry ? 0 : st.fails ? SLOW : EVERY);
    });
  }
  function kick() { if (wanted() && !document.hidden && !st.timer && !st.busy) st.timer = setTimeout(loop, 0); }
  document.addEventListener("visibilitychange", () => { if (document.hidden) { clearTimeout(st.timer); st.timer = 0; } else kick(); });

  // --- what the page gives -------------------------------------------------------------------------------------------------
  return {
    node: root,
    // `task`: the folder name of the task; `off`: why nothing is followed ("" when it is: a closed task or a task not started has no chat to follow); `chat`: desk.chat (its title for the copy button).
    config(info) {
      if (info.task !== st.task) {  // another task: nothing of the first one is kept
        st.task = info.task; st.rev = ""; st.data = null; st.fails = 0; st.turn = "";
        forget();
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
      view(() => { box.replaceChildren(...list); needLi.hidden = list.length === 0; });
      if (st.data) paintLife(st.data);
    },
    drawing(draw) { st.draw = draw; },
    // A static list of finished items (an opened round, rounds.js): drawn as the feed is, and nothing in it acts on the running chat. The person's own message is not in it (the round has its own prompt line).
    draw(items, turn) {
      const list = h("ol", {class: "lv-feed lv-static"});
      const shown = [];
      for (const item of items || []) {
        if (!item || item.k === "me" || !item.id) continue;
        const done = Object.assign({}, item, {live: false, run: false, st: item.st === "run" ? "done" : item.st});
        if (done.sub) done.sub = Object.assign({}, done.sub, {st: done.sub.st === "run" || done.sub.st === "wait" ? "done" : done.sub.st});
        shown.push(done);
        const rec = make(done, true, turn);
        rec.list = () => shown;  // the panel's tabs: the subagents of this round
        paint(rec, done);
        list.append(rec.el);
      }
      return list;
    },
    visible(on) { root.hidden = !on; if (on) kick(); },
  };
})();
