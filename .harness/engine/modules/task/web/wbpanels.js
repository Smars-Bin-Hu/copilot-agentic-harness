// The panels of the super agent workbench (1.8.x): the tree of the agents that run, the Data panel, the picture of Focus, the avatar of a task, the card that shows on a hover, the task line of a queue item and the short entrance.
// Everything is drawn from the rows the board already has (`rows()`: status, state, brief.aiu, chat.context, chat.model, stages, checks, autorun, open_conns, agents); nothing is asked of the server.
// A panel is drawn again only when its signature changes; a time that runs (the wait of a task, how long a subagent has run) is a text the one-second timer sets, nothing more.
// A value a row does not have shows "-"; nothing is made up (there is no name of a subagent and no count of the mappers that are done: only what `agents` holds).
// workbench.js owns the places (`.wb-tree`, `.wb-data`, `.wb-scene`) and tells this file which of them are on screen. Needs common.js (h, t, clock, shownName, stateOf) and super.js (SUPER.waiting).
"use strict";

const WBPANELS = (function () {
  const NS = "http://www.w3.org/2000/svg";
  const IDS = 8;  // the colours of a task's own identity (--wbp-id0 .. 7 in wbpanels.css, one set for light and one for dark)
  const FULL = 85;  // the context meter turns red from this percent
  const SUB_CAP = 8;  // the circles of the picture for one task; the rest is a "+N"
  const NONE = "—";
  const KNOWN = {reviewer: "super.wb.sub.reviewer", worker: "super.wb.sub.worker", mapper: "super.wb.sub.mapper"};  // written out: a search for a key finds its place
  const TAGS = {autorun: "super.wb.tag.autorun", review: "super.wb.tag.review", mapper: "super.wb.tag.mapper"};
  const NUMS = {work: "super.wb.num.working", wait: "super.wb.num.wait", err: "super.wb.num.error", aiu: "super.wb.num.aiu", subs: "super.wb.num.subs"};
  const COLS = {wait: "super.wb.col.waited", aiu: "super.wb.col.aiu", ctx: "super.wb.col.ctx", stage: "super.wb.col.stage"};
  const query = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  const still = () => Boolean(query && query.matches) || document.documentElement.classList.contains("lite");
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const finite = (value) => typeof value === "number" && isFinite(value);
  const has = (key) => Object.prototype.hasOwnProperty.call(TEXT, key);
  const taskUrl = (name) => "/task/" + encodeURIComponent(name);
  const two = (value) => String(value).padStart(2, "0");
  const clockOf = (seconds) => {  // 3:28, or 1:03:28
    const total = Math.max(0, Math.floor(seconds));
    return total >= 3600 ? Math.floor(total / 3600) + ":" + two(Math.floor((total % 3600) / 60)) + ":" + two(total % 60) : Math.floor(total / 60) + ":" + two(total % 60);
  };
  const kilo = (value) => (value >= 10000 ? Math.round(value / 1000) + "k" : String(Math.round(value)));
  function el(name, attrs, ...kids) {
    const node = document.createElementNS(NS, name);
    for (const key in attrs || {}) if (attrs[key] !== null && attrs[key] !== undefined && attrs[key] !== false) node.setAttribute(key, String(attrs[key]));
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return node;
  }

  // The identity of a task: a stable number from its name (its colour in the avatar, the picture and the queue), so tasks can be told apart without reading names.
  function idOf(name) {
    let value = 5381;
    for (const ch of String(name)) value = ((value << 5) + value + ch.charCodeAt(0)) >>> 0;
    return value % IDS;
  }
  // The look of a task's state: wait (amber), work (green), err (red), idle (grey).
  function kindOf(row) {
    const state = stateOf(row, true);
    if (state === "error" || state === "broken") return "err";
    if (row.status === "open" && row.waiting_why && !String(row.waiting_why).startsWith("go-") && !row.paused_since) return "wait";
    if (state === "working") return "work";
    return "idle";
  }
  const RANK = {err: 0, wait: 1, work: 2, idle: 3};
  const KC = (kind) => "wbp-k-" + kind;  // the class of a state (a plain "wait" or "work" is styled by the board elsewhere)

  // What a panel needs of a row, once per refresh.
  function subsOf(row) {
    const list = row.agents && Array.isArray(row.agents.subs) ? row.agents.subs : [];
    return list.filter((one) => one && finite(Number(one.n)) && Number(one.n) > 0).map((one) => ({type: String(one.type || ""), n: Math.min(999, Math.floor(Number(one.n))), since: Date.parse(one.since)}));
  }
  function subLabel(one, row) {  // "reviewer x2 · round 1", "worker · step 3 of 5", "mapper x4 · started 6 of 8"
    const agents = row.agents || {};
    const name = KNOWN[one.type] ? t(KNOWN[one.type]) : one.type || t("super.wb.sub.other");
    let text = name + (one.n > 1 ? " ×" + one.n : "");
    if (one.type === "reviewer" && agents.review && finite(Number(agents.review.round))) text += " · " + t("super.wb.sub.round", {n: agents.review.round});
    else if (one.type === "worker" && agents.autorun && finite(Number(agents.autorun.step)) && finite(Number(agents.autorun.total))) text += " · " + t("super.wb.sub.step", {n: agents.autorun.step, total: agents.autorun.total});
    else if (one.type === "mapper" && agents.mapper && finite(Number(agents.mapper.started)) && finite(Number(agents.mapper.limit))) text += " · " + t("super.wb.sub.started", {n: agents.mapper.started, total: agents.mapper.limit});
    return text;
  }
  function infoOf(row) {
    const name = String(row.name || row.task || "");
    const agents = row.agents || {};
    const chat = row.chat || {};
    const meter = chat.context && finite(chat.context.percent) ? chat.context : null;
    const steps = row.stages && Array.isArray(row.stages.steps) ? row.stages.steps : [];
    const now = steps.find((step) => step && step.state === "now");
    const stage = now ? String(now.label || (has("stage." + now.id) ? t("stage." + now.id) : "")) : "";
    const subs = subsOf(row);
    const tags = [];
    if (row.autorun) tags.push("autorun");
    if (agents.review) tags.push("review");
    if (agents.mapper) tags.push("mapper");
    return {
      row, name, shown: shownName(row) || name, id: idOf(name), kind: kindOf(row), tags, stage,
      aiu: row.brief && finite(row.brief.aiu) ? row.brief.aiu : null,
      ctx: meter ? {used: meter.used, window: meter.window, percent: meter.percent} : null,
      subs: subs.map((one) => Object.assign(one, {label: subLabel(one, row)})), subsN: subs.reduce((sum, one) => sum + one.n, 0),
    };
  }
  function wordOf(info) {  // the state as a word (no time: the time is a cell that runs)
    const state = info.row.state;
    if (info.kind === "err") return t("waits.error");
    if (info.kind === "wait") return t("super.wb.st.wait");
    if (info.kind === "work") return t("board.state.working");
    return has("board.state." + state) ? t("board.state." + state) : t("board.state.quiet");
  }

  function create(options) {
    const rowsOf = options.rows || (() => []);
    const cells = [];  // the texts the timer sets: {node, kind: "wait" | "since", name, at}
    const waitBase = new Map();  // task -> {s, at}: the wait the board said, and when this page saw it
    const sigs = {tree: "", data: "", scene: ""};
    let models = [], byName = new Map(), timer = 0, root = null, current = null, rootNode = null;

    // ---- the avatar of a task: a round robot, the ring is its state, the eyes its own colour ----
    function avatar(info, size) {
      return h("span", {class: "wbp-av wbp-i" + info.id + " " + KC(info.kind), style: "--s:" + (size || 20) + "px", "data-wbp-task": info.name, "data-wbp-hv": ""});
    }

    // ---- the cells that run ----
    function runCell(node, kind, name, at) { cells.push({node, kind, name, at}); return node; }
    function waitedNow(name) {
      const base = waitBase.get(name);
      return base ? base.s + (Date.now() - base.at) / 1000 : null;
    }
    function tick() {
      for (let at = cells.length - 1; at >= 0; at--) {
        const cell = cells[at];
        if (!cell.node.isConnected) { cells.splice(at, 1); continue; }
        const seconds = cell.kind === "since" ? (finite(cell.at) ? (Date.now() - cell.at) / 1000 : null) : waitedNow(cell.name);
        const text = seconds === null ? NONE : clockOf(seconds);
        if (cell.node.textContent !== text) cell.node.textContent = text;
      }
    }
    function start() { if (!timer) { timer = setInterval(() => { if (!document.hidden) tick(); }, 1000); tick(); } }
    function stop() { if (timer) { clearInterval(timer); timer = 0; } hideHover(); }

    // ---- the tree of the agents that run ----
    function treeNode(list) {
      const kids = h("div", {class: "wbp-kids"});
      for (const info of list) {
        const tags = info.tags.map((key) => h("span", {class: "wbp-tg", title: t(TAGS[key])}, t(TAGS[key])));
        const word = h("span", {class: "wbp-st " + KC(info.kind)}, wordOf(info));
        const state = info.kind === "wait" ? [word, " ", runCell(h("span", {class: "wbp-tm"}), "wait", info.name)] : [word];
        kids.append(h("div", {class: "wbp-tn " + KC(info.kind), "data-wbp-task": info.name},
          avatar(info, 20), h("a", {class: "wbp-nm", href: taskUrl(info.name), title: info.name}, info.shown), h("span", {class: "wbp-stw"}, state), tags));
        if (info.subs.length) {
          const sub = h("div", {class: "wbp-kids wbp-subs"});
          for (const one of info.subs) {
            const letter = (one.type || "?").charAt(0).toUpperCase();
            sub.append(h("div", {class: "wbp-sub", title: one.label}, h("i", null, letter), h("span", {class: "wbp-sl"}, one.label), runCell(h("span", {class: "wbp-tm"}), "since", info.name, one.since)));
          }
          kids.append(sub);
        }
      }
      const head = h("div", {class: "wbp-root"}, h("span", {class: "wbp-bot", "aria-hidden": "true"}), h("b", null, t("super.name")), h("span", {class: "wbp-w"}, t("super.wb.tree.watches", {n: list.length})));
      return [head, list.length ? kids : h("div", {class: "wb-soon"}, t("super.wb.none"))];
    }

    // ---- the Data panel ----
    function dataNode(list) {
      const waits = SUPER.waiting(list.map((info) => info.row));
      const total = {work: 0, err: 0, aiu: 0, subs: 0};
      let top = 0;
      for (const info of list) {
        if (info.kind === "work") total.work++;
        if (info.kind === "err") total.err++;
        if (info.aiu !== null) { total.aiu += info.aiu; top = Math.max(top, info.aiu); }
        total.subs += info.subsN;
      }
      const num = (kind, value, key) => h("div", {class: "wbp-num " + (kind ? KC(kind) : "")}, h("b", null, String(value)), h("span", {title: t(NUMS[key])}, t(NUMS[key])));
      const nums = h("div", {class: "wbp-nums"}, num("work", total.work, "work"), num("wait", waits, "wait"), num("err", total.err, "err"), num("", Math.round(total.aiu * 10) / 10, "aiu"), num("", total.subs, "subs"));
      const head = h("div", {class: "wbp-dr wbp-dh"}, h("span"), ...["wait", "aiu", "ctx", "stage"].map((key) => h("span", null, t(COLS[key]))));
      const lines = list.map((info) => {
        const wait = info.kind === "wait" ? runCell(h("span"), "wait", info.name) : h("span", null, info.kind === "work" ? "·" : wordOf(info));
        const aiu = h("span", {class: "wbp-m"}, h("span", {class: "wbp-bar"}, h("b", {class: "aiu", style: "width:" + (info.aiu !== null && top > 0 ? clamp(info.aiu / top * 100, 0, 100).toFixed(1) : 0) + "%"})), info.aiu === null ? NONE : info.aiu.toFixed(1));
        const ctx = h("span", {class: "wbp-m"}, h("span", {class: "wbp-bar"}, h("b", {class: info.ctx && info.ctx.percent >= FULL ? "full" : "", style: "width:" + (info.ctx ? clamp(info.ctx.percent, 0, 100).toFixed(1) : 0) + "%"})), info.ctx ? Math.round(info.ctx.percent) + "%" : NONE);
        return h("div", {class: "wbp-dr " + KC(info.kind), "data-wbp-task": info.name, "data-wbp-hv": ""}, avatar(info, 18), h("span", {class: "wbp-wt"}, wait), aiu, ctx, h("span", {class: "wbp-sg", title: info.stage || null}, info.stage || NONE));
      });
      return [nums, h("div", {class: "wbp-table"}, lines.length ? head : null, lines.length ? lines : h("div", {class: "wb-soon"}, t("super.wb.none")))];
    }

    // ---- the picture of Focus ----
    function sceneSVG(list, tall, quiet) {
      const n = list.length;
      const W = tall ? 540 : 700, sx = W / 2, sy = tall ? 30 : 88, sr = tall ? 18 : 38;
      let tr, perRow;
      if (tall) { tr = clamp((W - 40) / Math.max(n, 1) / 2.7, 4, 15); perRow = Math.max(1, n); }
      else { tr = n <= 6 ? 28 : n <= 10 ? 24 : n <= 16 ? 20 : n <= 24 ? 17 : 14; perRow = Math.max(1, Math.min(n, Math.floor((W - 40) / (2 * tr + (n <= 10 ? 34 : 14))))); }
      const cellW = (W - 40) / perRow;
      const sr2 = tall ? 4 : n <= 10 ? 9 : n <= 24 ? 6.5 : 5, pitch = 2 * sr2 + 3;
      const cols = Math.max(1, Math.floor(cellW / pitch));
      const lines = tall ? 0 : n <= 10 ? 1 : 0;  // a word under the avatar only while there is room; later the hover says it
      const firstY = tall ? 104 : sy + sr + 76;
      const room = tall ? Math.floor((200 - firstY - tr - 10) / pitch) : 99;  // rows of circles that fit under a task
      const capFor = tall ? clamp(cols * room, 0, SUB_CAP) : SUB_CAP;
      const shown = list.map((info) => clamp(info.subsN, 0, capFor));
      const slots = list.map((info, at) => shown[at] + (info.subsN > shown[at] ? 1 : 0));  // the circles and, after them, the "+N"
      const subRows = Math.max(0, ...slots.map((count) => Math.ceil(count / Math.min(cols, Math.max(count, 1)))));
      const rowH = 2 * tr + (lines ? 20 : 8) + (subRows ? subRows * pitch + 14 : 0) + 14;
      const rowsN = Math.max(1, Math.ceil(n / perRow));
      const H = tall ? 200 : Math.max(380, Math.round(firstY + rowsN * rowH + 24));
      const out = [];
      const back = [], front = [];
      list.forEach((info, index) => {
        const rowNo = Math.floor(index / perRow), inRow = Math.min(perRow, n - rowNo * perRow);
        const x = 20 + cellW * ((index % perRow) + 0.5) + (perRow - inRow) * cellW / 2, y = firstY + rowNo * rowH + tr;
        const x0 = sx, y0 = sy + sr, y1 = y - tr, bend = tall ? 8 : 34, cx = (x0 + x) / 2, cy = (y0 + y1) / 2 + bend;
        const path = "M" + x0 + "," + y0 + " Q" + cx.toFixed(1) + "," + cy.toFixed(1) + " " + x.toFixed(1) + "," + y1.toFixed(1);
        back.push(el("path", {d: path, class: "wbp-ln " + KC(info.kind)}));
        if ((info.kind === "work" || info.kind === "wait") && (index < 14 || quiet)) {
          const dot = el("circle", {r: tall ? 2.2 : 3.4, class: "wbp-dot " + KC(info.kind)});
          if (quiet) { dot.setAttribute("cx", (0.25 * x0 + 0.5 * cx + 0.25 * x).toFixed(1)); dot.setAttribute("cy", (0.25 * y0 + 0.5 * cy + 0.25 * y1).toFixed(1)); }
          else dot.append(el("animateMotion", Object.assign({dur: info.kind === "work" ? "2.2s" : "3s", begin: "-" + ((index * 0.37) % 2.2).toFixed(2) + "s", repeatCount: "indefinite", path}, info.kind === "wait" ? {keyPoints: "1;0", keyTimes: "0;1", calcMode: "linear"} : {})));
          back.push(dot);
        }
        // the running subagents: one small circle each, in a grid under the task
        const count = shown[index], per = Math.min(cols, Math.max(slots[index], 1));
        for (let at = 0; at < count; at++) {
          const gx = x + ((at % per) - (per - 1) / 2) * pitch, gy = y + tr + (lines ? 22 : 12) + sr2 + Math.floor(at / per) * pitch;
          const letter = (subLetter(info, at) || "?");
          back.push(el("line", {x1: x.toFixed(1), y1: (y + tr).toFixed(1), x2: gx.toFixed(1), y2: (gy - sr2).toFixed(1), class: "wbp-sl2"}));
          front.push(el("g", {class: "wbp-sc"}, el("circle", {cx: gx.toFixed(1), cy: gy.toFixed(1), r: sr2}), sr2 >= 8 ? el("text", {x: gx.toFixed(1), y: (gy + 3.2).toFixed(1), "text-anchor": "middle", "font-size": 9}, letter) : null));
        }
        if (info.subsN > count) {  // "+N" in the slot after the last circle
          const perMore = Math.min(cols, slots[index]), gx = x + ((count % perMore) - (perMore - 1) / 2) * pitch, gy = y + tr + (lines ? 22 : 12) + sr2 + Math.floor(count / perMore) * pitch;
          front.push(el("text", {x: gx.toFixed(1), y: (gy + 3).toFixed(1), "text-anchor": "middle", class: "wbp-more", "font-size": tall ? 8 : 10}, "+" + (info.subsN - count)));
        }
        const ids = el("g", {class: "wbp-t wbp-i" + info.id + " " + KC(info.kind), "data-wbp-task": info.name, "data-wbp-hv": ""},
          el("circle", {cx: x.toFixed(1), cy: y.toFixed(1), r: tr, class: "wbp-body"}),
          el("circle", {cx: (x - tr * .3).toFixed(1), cy: (y - tr * .1).toFixed(1), r: (tr * .14).toFixed(2), class: "wbp-eye"}),
          el("circle", {cx: (x + tr * .3).toFixed(1), cy: (y - tr * .1).toFixed(1), r: (tr * .14).toFixed(2), class: "wbp-eye"}),
          el("circle", {cx: x.toFixed(1), cy: y.toFixed(1), r: tr + 3, class: "wbp-hit"}));
        front.push(ids);
        if (lines) {
          const label = el("text", {x: x.toFixed(1), y: (y + tr + 16).toFixed(1), "text-anchor": "middle", class: "wbp-lb " + KC(info.kind), "font-size": 11.5}, info.kind === "wait" ? "" : wordOf(info));
          if (info.kind === "wait") { label.append(el("tspan", {class: "wbp-lw"}, wordOf(info) + " "), el("tspan", {class: "wbp-lt"})); runCell(label.lastChild, "wait", info.name); }
          front.push(label);
        }
      });
      out.push(...back, ...front);
      if (!quiet) out.push(el("circle", {cx: sx, cy: sy, r: sr + 6, class: "wbp-pulse"}, el("animate", {attributeName: "r", values: (sr + 4) + ";" + (sr + (tall ? 10 : 20)) + ";" + (sr + 4), dur: "3s", repeatCount: "indefinite"})));
      out.push(el("rect", {x: sx - sr, y: sy - sr, width: sr * 2, height: sr * 2, rx: (sr * .34).toFixed(1), class: "wbp-boss"}));
      out.push(el("circle", {cx: (sx - sr * .36).toFixed(1), cy: (sy - sr * .08).toFixed(1), r: (sr * .16).toFixed(1), class: "wbp-bosseye"}), el("circle", {cx: (sx + sr * .36).toFixed(1), cy: (sy - sr * .08).toFixed(1), r: (sr * .16).toFixed(1), class: "wbp-bosseye"}));
      if (!tall) out.push(el("text", {x: sx, y: sy + sr + 20, "text-anchor": "middle", class: "wbp-bossname", "font-size": 12.5}, t("super.name")));
      return el("svg", {viewBox: "0 0 " + W + " " + H, preserveAspectRatio: tall ? "xMidYMid meet" : "xMidYMin meet", role: "img", "aria-label": t("super.wb.scene.label"), class: "wbp-svg"}, out);
    }
    function subLetter(info, at) {  // the letter of the at-th circle of a task: its groups in order, one circle for each running subagent
      let left = at;
      for (const one of info.subs) { if (left < one.n) return (one.type || "?").charAt(0).toUpperCase(); left -= one.n; }
      return "?";
    }
    function sceneNode(list, tall) {
      const subs = list.reduce((sum, info) => sum + info.subsN, 0);
      const cap = h("div", {class: "wbp-cap"}, t("super.wb.scene.cap", {n: list.length, m: subs}));
      return [cap, sceneSVG(list, tall, still())];
    }

    // ---- drawing, only when a signature changed ----
    const infoSig = (info) => [info.name, info.shown, info.kind, info.stage, info.tags.join("+"), info.subs.map((one) => one.label + "@" + one.since).join(","), info.row.state];
    function refresh(vis) {
      const now = Date.now();
      const open = (rowsOf() || []).filter((row) => row && row.status === "open");
      models = open.map(infoOf);
      byName = new Map(models.map((info) => [info.name, info]));
      for (const info of models) {
        const seen = waitBase.get(info.name), s = finite(info.row.waited_s) ? info.row.waited_s : null;
        if (s === null) waitBase.delete(info.name); else if (!seen || seen.s !== s) waitBase.set(info.name, {s, at: now});
      }
      for (const name of [...waitBase.keys()]) if (!byName.has(name)) waitBase.delete(name);
      const sorted = models.slice().sort((a, b) => RANK[a.kind] - RANK[b.kind] || (a.kind === "wait" ? (finite(b.row.waited_s) ? b.row.waited_s : 0) - (finite(a.row.waited_s) ? a.row.waited_s : 0) : 0) || a.name.localeCompare(b.name));
      if (vis.tree) paint("tree", tree, JSON.stringify(sorted.map(infoSig)), () => treeNode(sorted));
      if (vis.data) paint("data", data, JSON.stringify(sorted.map((info) => infoSig(info).concat([info.aiu, info.ctx ? info.ctx.percent : null, info.subsN]))), () => dataNode(sorted));
      if (vis.scene) {
        const byId = models.slice().sort((a, b) => a.name.localeCompare(b.name));
        paint("scene", scene, vis.tall + "|" + still() + "|" + JSON.stringify(byId.map((info) => infoSig(info).slice(0, 3).concat([info.subs.map((one) => one.type + one.n).join(",")]))), () => sceneNode(byId, vis.tall));
      }
      tick();
      if (current && current.isConnected) showHover(current); else if (current) hideHover();
    }
    function paint(key, node, sig, make) {
      if (sigs[key] === sig && node.firstChild) return;
      sigs[key] = sig;
      for (let at = cells.length - 1; at >= 0; at--) if (node.contains(cells[at].node)) cells.splice(at, 1);
      node.replaceChildren(...make());
    }
    // `vis`: {tree, data, scene: which of the three are on screen, tall: the strip of the picture}
    function update(vis) { refresh({tree: Boolean(vis.tree), data: Boolean(vis.data), scene: Boolean(vis.scene), tall: Boolean(vis.tall)}); }

    // ---- the card of a task, on a hover ----
    const hover = h("div", {class: "wbp-hover", role: "tooltip", hidden: ""});
    const SEL = "[data-wbp-hv], .sa-mate[data-task]:not([data-task=\"\"])";
    const nameOfEl = (node) => node.getAttribute("data-wbp-task") || node.getAttribute("data-task") || "";
    function hoverCard(info) {
      const row = info.row;
      let state = wordOf(info);
      if (info.kind === "wait") { const seconds = waitedNow(info.name); state = t("super.wb.hv.waits", {time: seconds === null ? NONE : clock(seconds)}); }
      else if (info.kind === "err") state = t("waits.error") + (row.error && row.error.message ? " · " + String(row.error.message).slice(0, 120) : "");
      const checks = row.checks && row.checks.n ? t("desk.checks.label", {passes: row.checks.passes || 0, n: row.checks.n}) : t("super.wb.hv.off");
      const chat = row.chat || {};
      const model = chat.model_name || chat.model ? String(chat.model_name || chat.model) + (chat.effort ? " · " + chat.effort : "") : NONE;
      const ctx = info.ctx ? (finite(info.ctx.used) && finite(info.ctx.window) ? t("super.wb.hv.ctx", {used: kilo(info.ctx.used), window: kilo(info.ctx.window), percent: Math.round(info.ctx.percent)}) : Math.round(info.ctx.percent) + "%") : NONE;
      const conns = Array.isArray(row.open_conns) && row.open_conns.length ? row.open_conns.map((name) => h("span", {class: "wbp-conn"}, h("i"), String(name))) : t("super.wb.hv.nothing");
      const rowsOfCard = [[t("super.wb.hv.stage"), info.stage || NONE], [t("super.wb.hv.model"), model], [t("super.wb.hv.ctx.label"), ctx],
        [t("super.wb.hv.aiu"), info.aiu === null ? NONE : t("super.wb.hv.aiu.value", {n: info.aiu.toFixed(1)})], [t("super.wb.hv.checks"), checks],
        [t("super.wb.hv.autorun"), row.autorun ? t("super.wb.hv.on") : t("super.wb.hv.off")],
        [t("super.wb.hv.subs"), info.subs.length ? info.subs.map((one) => one.label).join(", ") : t("super.wb.hv.none")], [t("super.wb.hv.conns"), conns]];
      return [h("h4", {title: info.name}, info.shown), h("div", {class: "wbp-hs " + KC(info.kind)}, "● " + state), h("dl", null, rowsOfCard.map((pair) => [h("dt", null, pair[0]), h("dd", null, pair[1])]))];
    }
    function showHover(node) {
      const info = byName.get(nameOfEl(node));
      if (!info || !rootNode) { hideHover(); return; }
      current = node;
      hover.replaceChildren(...hoverCard(info));
      hover.hidden = false;
      const box = node.getBoundingClientRect(), width = hover.offsetWidth || 300, height = hover.offsetHeight || 220;
      const left = box.left > width + 24 ? box.left - width - 10 : box.right + 10;
      hover.style.left = Math.round(clamp(left, 8, innerWidth - width - 8)) + "px";
      hover.style.top = Math.round(clamp(box.top - 6, 8, Math.max(8, innerHeight - height - 8))) + "px";
      for (const mate of rootNode.querySelectorAll(".sa-mate.wbp-hl")) if (nameOfEl(mate) !== info.name) mate.classList.remove("wbp-hl");
      for (const mate of rootNode.querySelectorAll(".sa-mate[data-task]")) if (nameOfEl(mate) === info.name) mate.classList.add("wbp-hl");
    }
    function hideHover() {
      current = null;
      hover.hidden = true;
      if (rootNode) for (const mate of rootNode.querySelectorAll(".sa-mate.wbp-hl")) mate.classList.remove("wbp-hl");
    }
    function bind(node) {  // the layer: a hover on a task's avatar or a line of the Data panel
      rootNode = node;
      node.append(hover);
      node.addEventListener("mouseover", (event) => {
        const target = event.target && event.target.closest ? event.target.closest(SEL) : null;
        if (!target) { if (current) hideHover(); return; }
        if (target !== current) showHover(target);
      });
      node.addEventListener("mouseleave", hideHover);
      node.addEventListener("scroll", () => { if (current) hideHover(); }, true);
      document.addEventListener("keydown", (event) => { if (event.key === "Escape" && current) hideHover(); });
    }

    // ---- the task line of a queue item (super.js marks an item with data-task) ----
    function decorate(list) {
      if (!list) return;
      for (const node of list.children) {
        const name = node.dataset ? node.dataset.task : "";
        if (!name || !node.classList.contains("item")) continue;
        const info = byName.get(name) || (() => { const row = (rowsOf() || []).find((one) => one && (one.name === name || one.task === name)); return row ? infoOf(row) : null; })();
        let chip = [...node.children].find((child) => child.classList.contains("wbp-qt"));
        const kind = info ? info.kind : "idle", id = info ? info.id : idOf(name), shown = info ? info.shown : name;
        const sig = kind + "|" + id + "|" + shown;
        if (chip && chip.dataset.sig === sig) continue;
        const fresh = h("a", {class: "wbp-qt", href: taskUrl(name), title: name, "data-sig": sig, "data-wbp-task": name, "data-wbp-hv": ""},
          h("span", {class: "wbp-av wbp-i" + id + " " + KC(kind), style: "--s:18px", "aria-hidden": "true"}), h("span", {class: "wbp-qn"}, shown));
        if (chip) chip.replaceWith(fresh); else node.insertBefore(fresh, node.firstChild);
      }
    }

    // ---- the entrance: once for each load of the page ----
    function intro(layer) {
      if (introPlayed) return;
      introPlayed = true;
      if (still()) return;
      const veil = h("div", {class: "wbp-intro", "aria-hidden": "true"}, h("span", {class: "wbp-ring"}), h("span", {class: "wbp-ibot"}));
      layer.append(veil);
      layer.classList.add("wbp-in");
      let timer = 0;
      const end = () => {
        clearTimeout(timer);
        veil.remove();
        layer.classList.remove("wbp-in");
        document.removeEventListener("keydown", end, true);
      };
      veil.addEventListener("click", end);
      document.addEventListener("keydown", end, true);
      timer = setTimeout(end, 600);
    }

    const tree = h("div", {class: "wb-tree"}), data = h("div", {class: "wb-data"}), scene = h("div", {class: "wbp-scene"});
    return {tree, data, scene, update, start, stop, bind, decorate, intro};
  }
  let introPlayed = false;

  return {create, idOf};
})();
