// The panels of the super agent workbench (1.8.25, the command deck): the bridge (the super agent over its tasks), the tree of the agents that run, the Data panel, the picture of Focus, the avatar of a task, the card that shows on a hover, the task line of a queue item and the short entrance.
// Everything is drawn from the rows the board already has (`rows()`: status, state, brief, chat.context, chat.model, stages, checks, autorun, open_conns, warn, sub, agents); nothing is asked of the server.
// A panel is drawn again only when its signature changes; a time that runs (the wait of a task, how long a subagent has run) is a text the one-second timer sets, nothing more. The line "now" of a working task is the `row.sub` the board already has: it changes when the rows change, never by a timer.
// A value a row does not have shows "-"; nothing is made up (there is no name of a subagent and no count of the mappers that are done: only what `agents` holds; `agents.gate` and `brief.time` may be absent).
// workbench.js owns the places (`.wb-tree`, `.wb-data`, `.wb-scene`, the bridge) and tells this file which of them are on screen. Needs common.js (h, t, clock, shownName, stateOf) and super.js (SUPER.waiting).
"use strict";

const WBPANELS = (function () {
  const NS = "http://www.w3.org/2000/svg";
  const IDS = 8;  // the colours of a task's own identity (--wbp-id0 .. 7 in wbpanels.css, one set for light and one for dark)
  const FULL = 85;  // the context meter turns red from this percent
  const LOOK_CTX = 70;  // a context this full is a thing to look at
  const SUB_CAP = 8;  // the circles under a task; the rest is a "+N"
  const TREE_FLAT = 12;  // up to this many open tasks the tree is one flat list; more are grouped by state
  const DOTS = 12;  // the moving dots on a bridge, all together
  const GATE_MIN = 10;  // the window of `agents.gate`, when the row does not say
  const PIPE_CAP = 10;  // the dots in a column of the pipeline
  const NONE = "—";
  const KNOWN = {reviewer: "super.wb.sub.reviewer", worker: "super.wb.sub.worker", mapper: "super.wb.sub.mapper"};  // written out: a search for a key finds its place
  const TAGS = {autorun: "super.wb.tag.autorun", review: "super.wb.tag.review", mapper: "super.wb.tag.mapper"};
  const GRP = {err: "super.wb.grp.err", wait: "super.wb.grp.wait", work: "super.wb.grp.work", idle: "super.wb.grp.idle"};
  const PIPE_ENVS = 4;  // the environments of the test lane shown; more go into the last one shown
  const TIME = [["model_s", "super.wb.time.model", "wbp-s-model"], ["tool_s", "super.wb.time.tool", "wbp-s-tool"], ["subagent_s", "super.wb.time.sub", "wbp-s-sub"], ["approval_s", "super.wb.time.appr", "wbp-s-appr"], ["waiting_s", "super.wb.time.you", "wbp-s-you"]];
  const BRIDGE_ORDER = ["err", "wait", "work", "idle"];  // the order of the groups on the bridge and in the Focus picture
  const TREE_ORDER = ["work", "err", "wait", "idle"];  // the order of the groups in the tree
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
  const clip = (text, limit) => (text.length > limit ? text.slice(0, limit - 1).trimEnd() + "…" : text);
  function durOf(seconds) {  // 2 h 05, 34 min, 45 s
    const total = Math.max(0, Math.round(seconds));
    if (total >= 3600) return t("super.wb.dur.h", {h: Math.floor(total / 3600), m: two(Math.floor((total % 3600) / 60))});
    return total >= 60 ? t("super.wb.dur.min", {m: Math.round(total / 60)}) : t("super.wb.dur.s", {s: total});
  }
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
    if (handedOff(row)) return "work";  // 1.8.50: a closed task just handed to an agent: it is on its way
    const state = stateOf(row, true);
    if (state === "error" || state === "broken") return "err";
    if (row.status === "open" && row.waiting_why && !String(row.waiting_why).startsWith("go-") && !row.paused_since) return "wait";
    if (state === "working") return "work";
    return "idle";
  }
  const RANK = {err: 0, wait: 1, work: 2, idle: 3};
  const KC = (kind) => "wbp-k-" + kind;  // the class of a state (a plain "wait" or "work" is styled by the board elsewhere)

  // The pipeline has one lane per kind of task, each with the steps that kind really has (taskstages.py): dev and kb: requirement, plan, developing, write-back
  // (or apply by hand), done; test: the guide, one step per environment, done; rca, design and other: doing, done; qa (no ribbon): open, done. A lane is drawn
  // only for a kind the board has. The last step of a lane holds no open task: it counts the closed tasks of that kind (an open task whose ribbon is at done
  // waits to be closed, so it stays in the step before).
  const LANES = {dev: ["requirement", "plan", "developing", "writeback", "done"], simple: ["doing", "done"], qa: ["open", "done"]};
  const LANE_OF = {dev: "dev", kb: "dev", test: "test", rca: "simple", design: "simple", other: "simple", qa: "qa"};
  function laneOf(kind) { return LANE_OF[kind] || "qa"; }
  // {lane, step}: where an open task is. `step` is the id of a step of its lane (for test: "guide" or the environment's name).
  function placeOf(kind, now) {
    const lane = laneOf(kind), id = now ? String(now.id || "") : "";
    if (lane === "dev") return {lane, step: id === "byhand" || id === "done" ? "writeback" : (LANES.dev.indexOf(id) >= 0 ? id : "developing")};
    if (lane === "test") return {lane, step: id === "env" ? String(now.label || "?").toUpperCase() : "guide"};
    return {lane, step: lane === "qa" ? "open" : "doing"};
  }
  // What the person is asked to do, by the reason a task waits (tasklife.waiting): the second view of the pipeline, the same for every kind.
  const DECISIONS = [["answer", ["asking"]], ["call", ["outbox"]], ["req", ["req"]], ["plan", ["plan"]], ["promote", ["promote", "commit", "recover"]], ["accept", ["accept"]], ["other", []]];
  function decisionOf(why) { const found = DECISIONS.find((one) => one[1].indexOf(String(why || "")) >= 0); return found ? found[0] : "other"; }

  // How many avatars a bridge of this width holds: `few` with a name under each, `many` (smaller, grouped, two rows in the big picture).
  function fitOf(width, big) {
    const room = Math.max(0, width - 60), rows = big ? 2 : 1;
    return {few: Math.floor(room / (big ? 62 : 46)) * rows, many: Math.floor(room / (big ? 50 : 38)) * rows};
  }
  // The groups of the bridge. Items: {name, kind, subsN, waited}. All fit: one avatar each, in the order error, wait, work, paused.
  // More than fit: by state; error shows up to 3, working up to 4 (a task with subagents first), paused 1, waiting all the rest of the room (the longest wait first);
  // each state shows at least one task; a room that waiting does not use goes to working, paused, error; every group with a rest has one "+N" bubble (it takes a place).
  function bridgeGroups(items, fit) {
    const sorters = {
      err: (a, b) => String(a.name).localeCompare(String(b.name)),
      wait: (a, b) => (b.waited || 0) - (a.waited || 0) || String(a.name).localeCompare(String(b.name)),
      work: (a, b) => (b.subsN || 0) - (a.subsN || 0) || String(a.name).localeCompare(String(b.name)),
      idle: (a, b) => String(a.name).localeCompare(String(b.name)),
    };
    const groups = BRIDGE_ORDER.map((kind) => ({kind, list: items.filter((item) => item.kind === kind).sort(sorters[kind])})).filter((group) => group.list.length);
    if (items.length <= fit.few) return {grouped: false, groups: groups.map((group) => Object.assign(group, {show: group.list, more: 0}))};
    const caps = {err: 3, work: 4, idle: 1};
    const waitAt = groups.findIndex((group) => group.kind === "wait");
    let room = Math.max(groups.length, fit.many - groups.length);  // a place for each "+N" is kept; each state shows at least one task
    const take = groups.map(() => 1);
    room -= groups.length;
    const reserve = waitAt >= 0 ? Math.min(1, groups[waitAt].list.length - 1) : 0;
    groups.forEach((group, at) => {
      if (group.kind === "wait") return;
      const extra = clamp(Math.min(caps[group.kind] - 1, group.list.length - 1, room - reserve), 0, 99);
      take[at] += extra;
      room -= extra;
    });
    if (waitAt >= 0) { const extra = clamp(Math.min(groups[waitAt].list.length - 1, room), 0, 9999); take[waitAt] += extra; room -= extra; }
    for (const kind of ["work", "idle", "err"]) {  // what is left of the room
      const at = groups.findIndex((group) => group.kind === kind);
      if (at >= 0 && room > 0) { const more = Math.min(room, groups[at].list.length - take[at]); take[at] += more; room -= more; }
    }
    return {grouped: true, groups: groups.map((group, at) => Object.assign(group, {show: group.list.slice(0, take[at]), more: group.list.length - take[at]}))};
  }

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
  const startingOf = (row) => (row && row.starting && !row.starting.late ? row.starting : null);  // 1.8.50: the board sent something and has not seen the agent start (`Board.settle`)
  function nowOf(row) {  // what a working task does now: its last tool call (the line the board already has), else "thinking"; never asked for again
    const sub = row.sub && typeof row.sub === "object" ? row.sub : null;
    if (sub && sub.kind !== "reply") {
      const what = String(sub.what || "").trim(), text = String(sub.text || "").trim();
      const line = what && text ? what + " · " + text : what || text;
      if (line) return clip(line, 140);
    }
    return t("super.wb.now.thinking");
  }
  function gateOf(row) {  // {n, m}: the calls the gate refused in the last m minutes; null when the board does not say
    const gate = row.agents && row.agents.gate && typeof row.agents.gate === "object" ? row.agents.gate : null;
    return gate && finite(Number(gate.n)) ? {n: Math.max(0, Math.floor(Number(gate.n))), m: finite(Number(gate.minutes)) ? Number(gate.minutes) : GATE_MIN} : null;
  }
  function timeOf(row) {  // the split of a task's time; null unless Copilot's record is known
    const time = row.brief && row.brief.time && typeof row.brief.time === "object" ? row.brief.time : null;
    if (!time || time.known !== true) return null;
    const out = {};
    for (const part of TIME) out[part[0]] = finite(Number(time[part[0]])) ? Math.max(0, Number(time[part[0]])) : 0;
    return out;
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
    const kind = kindOf(row), gate = gateOf(row);
    return {
      row, name, shown: shownName(row) || name, id: idOf(name), kind, tags, stage, place: placeOf(String(row.kind || ""), now), decision: decisionOf(row.waiting_why),
      aiu: row.brief && finite(row.brief.aiu) ? row.brief.aiu : null,
      prem: row.brief && finite(row.brief.premium_requests) ? row.brief.premium_requests : null,
      ctx: meter ? {used: meter.used, window: meter.window, percent: meter.percent} : null,
      subs: subs.map((one) => Object.assign(one, {label: subLabel(one, row)})), subsN: subs.reduce((sum, one) => sum + one.n, 0),
      gate, now: kind === "work" ? (startingOf(row) ? (startingOf(row).stage && has("waits.stage." + startingOf(row).stage) ? t("waits.stage." + startingOf(row).stage) : "") : nowOf(row)) : "", time: timeOf(row), waited: finite(row.waited_s) ? row.waited_s : 0,
    };
  }
  function wordOf(info) {  // the state as a word (no time: the time is a cell that runs)
    const state = info.row.state;
    if (info.kind === "err") return t("waits.error");
    if (info.kind === "wait") return t("super.wb.st.wait");
    if (info.kind === "work") return t(startingOf(info.row) ? "waits.starting" : "board.state.working");  // 1.8.50: sent, the agent not seen to start yet
    return has("board.state." + state) ? t("board.state." + state) : t("board.state.quiet");
  }
  // The reasons to look at a task, the worst first: [{sev, text}]. Error 0, stuck 1, a full context 1.5, the gate 2, a context from 70% 3, repeat 4, cost 5, idle 6.
  function looksOf(info) {
    const row = info.row, out = [];
    const warn = Array.isArray(row.warn) ? row.warn.filter((item) => item && item.rule) : [];
    const rule = (name) => warn.find((item) => item.rule === name);
    if (info.kind === "err") out.push({sev: 0, text: t("super.wb.look.error")});
    const stuck = rule("stuck");
    if (stuck) out.push({sev: 1, text: t("super.wb.look.stuck", {n: stuck.n})});
    if (info.gate && info.gate.n > 0) out.push({sev: 2, text: t("super.wb.look.gate", {n: info.gate.n, m: info.gate.m})});
    const warned = rule("context"), percent = Math.max(info.ctx ? info.ctx.percent : 0, warned && finite(Number(warned.n)) ? Number(warned.n) : 0);
    if (warned || percent >= LOOK_CTX) out.push({sev: percent >= FULL ? 1.5 : 3, text: t("super.wb.look.context", {n: Math.round(percent)})});
    const repeat = rule("repeat"); if (repeat) out.push({sev: 4, text: t("super.wb.look.repeat", {n: repeat.n})});
    const cost = rule("cost"); if (cost) out.push({sev: 5, text: t("super.wb.look.cost", {n: cost.n})});
    const idle = rule("idle"); if (idle) out.push({sev: 6, text: t("super.wb.look.idle", {n: idle.n})});
    return out.sort((a, b) => a.sev - b.sev);
  }

  function create(options) {
    const rowsOf = options.rows || (() => []);
    const moreOf = typeof options.more === "function" ? options.more : () => 0;  // the older closed tasks the board does not list: the chip says "N+"
    const pickTask = typeof options.pick === "function" ? options.pick : null;  // a click on an avatar: target that task for a direct message
    const menuTask = typeof options.menu === "function" ? options.menu : null;  // a right click or a long press on an avatar of the bridge
    const closedChip = typeof options.closed === "function" ? options.closed : null;  // a click on "Closed N"
    const targetOf = typeof options.target === "function" ? options.target : () => "";  // the task now targeted ("" for none)
    const cells = [];  // the texts the timer sets: {node, kind: "wait" | "since", name, at}
    const waitBase = new Map();  // task -> {s, at}: the wait the board said, and when this page saw it
    const sigs = {tree: "", data: "", scene: "", bridge: ""};
    const fold = {work: true, err: true, wait: false, idle: false};  // the groups of the tree that are open
    const opened = {look: false, pipe: false, time: false, spend: false};  // the blocks of Data that show their whole list
    let closedMoreN = 0, models = [], byName = new Map(), closedN = 0, closedBy = {}, timer = 0, root = null, current = null, rootNode = null, lastVis = null, pop = null, popSpec = null, frame = 0;

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
    function stop() { if (timer) { clearInterval(timer); timer = 0; } hideHover(); closeList(); }

    // ---- the tree of the agents that run ----
    function taskRow(info) {
      const tags = info.tags.map((key) => h("span", {class: "wbp-tg", title: t(TAGS[key])}, t(TAGS[key])));
      const word = h("span", {class: "wbp-st " + KC(info.kind)}, wordOf(info));
      const state = info.kind === "wait" ? [word, " ", runCell(h("span", {class: "wbp-tm"}), "wait", info.name)] : [word];
      const out = [h("div", {class: "wbp-tn " + KC(info.kind), "data-wbp-task": info.name},
        avatar(info, 20), h("a", {class: "wbp-nm", href: taskUrl(info.name), title: info.name}, info.shown), h("span", {class: "wbp-stw"}, state), tags)];
      const kids = [];
      if (info.kind === "work") {
        const gate = info.gate && info.gate.n > 0 ? h("span", {class: "wbp-gate", title: t("super.wb.gate.tip", {n: info.gate.n, m: info.gate.m})}, "⛔ " + info.gate.n) : null;
        kids.push(h("div", {class: "wbp-sub wbp-now"}, h("i", null, "›"), h("span", {class: "wbp-nw", title: info.now}, info.now), gate));
      }
      for (const one of info.subs) {
        const letter = (one.type || "?").charAt(0).toUpperCase();
        kids.push(h("div", {class: "wbp-sub", title: one.label}, h("i", null, letter), h("span", {class: "wbp-sl"}, one.label), runCell(h("span", {class: "wbp-tm"}), "since", info.name, one.since)));
      }
      if (kids.length) out.push(h("div", {class: "wbp-kids wbp-subs"}, kids));
      return out;
    }
    function byKind(list, kind) {
      return list.filter((info) => info.kind === kind).sort((a, b) => (kind === "wait" ? b.waited - a.waited : 0) || a.name.localeCompare(b.name));
    }
    function treeNode(list) {
      const kids = h("div", {class: "wbp-kids"});
      if (list.length <= TREE_FLAT) for (const info of list) kids.append(...taskRow(info));
      else for (const kind of TREE_ORDER) {
        const group = byKind(list, kind);
        if (!group.length) continue;
        const open = fold[kind];
        kids.append(h("button", {type: "button", class: "wbp-grp " + KC(kind), "data-wbp-fold": kind, "aria-expanded": open ? "true" : "false"}, h("span", null, (open ? "▾ " : "▸ ") + t(GRP[kind])), h("b", null, String(group.length))));
        if (open) for (const info of group) kids.append(...taskRow(info));  // a folded group is not drawn
      }
      const head = h("div", {class: "wbp-root"}, h("span", {class: "wbp-bot", "aria-hidden": "true"}), h("b", null, t("super.name")), h("span", {class: "wbp-w"}, t("super.wb.tree.watches", {n: list.length})));
      return [head, list.length ? kids : h("div", {class: "wb-soon"}, t("super.wb.none"))];
    }

    // ---- the Data panel: four blocks, each a summary that opens ----
    function block(key, title, extra, body, toggle) {
      return h("section", {class: "wbp-blk"}, h("div", {class: "wbp-bt"}, h("span", null, title), extra ? h("em", null, extra) : null, toggle || null), body);
    }
    function toggleBtn(key, text) { return h("button", {type: "button", class: "wbp-morebtn", "data-wbp-open": key}, text); }
    function lookBlock(list) {
      const found = list.map((info) => ({info, looks: looksOf(info)})).filter((one) => one.looks.length).sort((a, b) => a.looks[0].sev - b.looks[0].sev || a.info.name.localeCompare(b.info.name));
      const shown = opened.look ? found : found.slice(0, 3);
      const lines = shown.map((one) => h("div", {class: "wbp-look " + (one.looks[0].sev <= 1.5 ? "wbp-k-err" : "wbp-k-wait"), "data-wbp-task": one.info.name, "data-wbp-hv": "", title: one.looks.map((item) => item.text).join("\n")},
        avatar(one.info, 18), h("span", {class: "wbp-why"}, one.looks[0].text + (one.looks.length > 1 ? " +" + (one.looks.length - 1) : "")), h("span", {class: "wbp-ln1"}, one.info.shown)));
      const more = found.length > 3 ? toggleBtn("look", opened.look ? t("super.wb.data.look.less") : t("super.wb.data.look.more", {n: found.length - 3})) : null;
      const body = found.length ? h("div", {class: opened.look ? "wbp-list" : ""}, lines, more) : h("div", {class: "wbp-ok"}, t("super.wb.data.look.ok"));
      return block("look", t("super.wb.data.look") + " · " + found.length, "", [body]);
    }
    const STEP_TEXT = {requirement: "super.wb.pipe.step.requirement", plan: "super.wb.pipe.step.plan", developing: "super.wb.pipe.step.developing", writeback: "super.wb.pipe.step.writeback",
      done: "super.wb.pipe.step.done", guide: "super.wb.pipe.step.guide", doing: "super.wb.pipe.step.doing", open: "super.wb.pipe.step.open"};
    const LANE_TEXT = {dev: "super.wb.pipe.lane.dev", test: "super.wb.pipe.lane.test", simple: "super.wb.pipe.lane.simple", qa: "super.wb.pipe.lane.qa"};
    const ASK_TEXT = {answer: "super.wb.ask.answer", call: "super.wb.ask.call", req: "super.wb.ask.req", plan: "super.wb.ask.plan", promote: "super.wb.ask.promote", accept: "super.wb.ask.accept", other: "super.wb.ask.other"};
    const stepName = (lane, step) => (STEP_TEXT[step] ? t(STEP_TEXT[step]) : step);  // an environment of the test lane is its own name
    const laneName = (lane) => t(LANE_TEXT[lane] || LANE_TEXT.qa);
    const LANE_TIP = {dev: "super.wb.pipe.tip.dev", test: "super.wb.pipe.tip.test", simple: "super.wb.pipe.tip.simple", qa: "super.wb.pipe.tip.qa"};
    function lanesOf(list) {  // [{lane, steps: [id]}] for the kinds the board has, open or closed
      const kinds = new Set(list.map((info) => info.place.lane));
      for (const lane of Object.keys(closedBy)) if (closedBy[lane]) kinds.add(lane);
      return ["dev", "test", "simple", "qa"].filter((lane) => kinds.has(lane)).map((lane) => {
        if (lane !== "test") return {lane, steps: LANES[lane]};
        const envs = [];
        for (const info of list) if (info.place.lane === "test" && info.place.step !== "guide" && envs.indexOf(info.place.step) < 0) envs.push(info.place.step);
        const shown = envs.slice(0, PIPE_ENVS);  // only the environments the open test tasks are in: none is made up (review 1)
        return {lane, steps: ["guide", ...shown, "done"], cut: envs.slice(PIPE_ENVS)};
      });
    }
    // The pipeline: per kind of task, its steps as arrows from left to right; the open tasks under the step they are in; the step where most tasks wait for the
    // person is lit; the last step (Done) is the count of closed tasks of that kind. Few words: the kind is one word (the hover names the kinds), no lines of help.
    function pipeBlock(list) {
      const lanes = lanesOf(list);
      let worst = null;
      for (const one of lanes) for (const step of one.steps) {
        const n = list.filter((info) => info.place.lane === one.lane && info.place.step === step && info.kind === "wait").length;
        if (n && (!worst || n > worst.n)) worst = {lane: one.lane, step, n};
      }
      const rows = lanes.map((one) => {
        const wide = one.steps.length === 2 ? "3.3" : "1";
        const flow = [], track = [];
        one.steps.forEach((step, at) => {
          const last = at === one.steps.length - 1;
          const here = last ? [] : list.filter((info) => info.place.lane === one.lane && (info.place.step === step || (one.cut && one.cut.length && at === one.steps.length - 2 && one.cut.indexOf(info.place.step) >= 0)));
          const count = last ? (closedBy[one.lane] || 0) : here.length, grow = last ? ".7" : wide;
          const lit = worst && worst.lane === one.lane && worst.step === step;
          flow.push(h("div", {class: "wbp-chev" + (last ? " wbp-cdone" : "") + (lit ? " wbp-jam" : "") + (!count ? " wbp-cnone" : ""), style: "flex:" + grow + " 1 0"}, h("span", null, stepName(one.lane, step)), h("b", null, String(count))));
          const extra = here.length - PIPE_CAP;
          track.push(h("div", {class: "wbp-cell", style: "flex:" + grow + " 1 0"}, here.slice(0, PIPE_CAP).map((info) => avatar(info, 11)), extra > 0 ? h("button", {type: "button", class: "wbp-plus", "data-wbp-col": one.lane + ":" + step}, "+" + extra) : null));
        });
        return h("div", {class: "wbp-lane"}, h("div", {class: "wbp-lk", title: t(LANE_TIP[one.lane] || LANE_TIP.qa)}, laneName(one.lane)), h("div", null, h("div", {class: "wbp-flow"}, flow), h("div", {class: "wbp-track"}, track)));
      });
      const wide = opened.pipe ? h("div", {class: "wbp-list"}, list.slice().sort((a, b) => a.place.lane.localeCompare(b.place.lane) || RANK[a.kind] - RANK[b.kind] || a.name.localeCompare(b.name)).map((info) => h("div", {class: "wbp-look " + KC(info.kind), "data-wbp-task": info.name, "data-wbp-hv": ""}, avatar(info, 16), h("span", {class: "wbp-ln1"}, info.shown), h("span", {class: "wbp-r"}, laneName(info.place.lane) + " · " + stepName(info.place.lane, info.place.step))))) : null;
      return block("pipe", t("super.wb.data.pipe"), "", [rows.length ? h("div", {class: "wbp-lanes"}, rows) : h("div", {class: "wbp-ok wbp-soft"}, t("super.wb.pipe.none")), wide], list.length ? toggleBtn("pipe", opened.pipe ? t("super.wb.data.less") : t("super.wb.pipe.list")) : null);
    }
    // What waits for the person, by the decision asked (the same for every kind): ranked bars, the most first; a decision nobody waits on is not shown.
    function askBlock(list) {
      const waiting = list.filter((info) => info.kind === "wait");
      if (!waiting.length) return null;
      const groups = DECISIONS.map((one) => ({key: one[0], here: waiting.filter((info) => info.decision === one[0])})).filter((one) => one.here.length).sort((a, b) => b.here.length - a.here.length);
      const most = groups[0].here.length;
      const bars = groups.map((one) => h("div", {class: "wbp-rk"}, h("span", {class: "wbp-rkl"}, t(ASK_TEXT[one.key])),
        h("span", {class: "wbp-rkbar"}, h("b", {style: "width:" + Math.max(8, one.here.length / most * 100).toFixed(1) + "%"}), h("span", {class: "wbp-rkav"}, one.here.slice(0, 8).map((info) => avatar(info, 11)), one.here.length > 8 ? h("button", {type: "button", class: "wbp-plus", "data-wbp-col": "ask:" + one.key}, "+" + (one.here.length - 8)) : null)),
        h("span", {class: "wbp-rkn"}, String(one.here.length))));
      return h("section", {class: "wbp-blk"}, h("div", {class: "wbp-bt"}, h("span", null, t("super.wb.data.ask")), h("b", {class: "wbp-btn"}, String(waiting.length))), h("div", {class: "wbp-rks"}, bars));
    }
    function timeBlock(list) {
      const known = list.filter((info) => info.time);
      const sum = TIME.map((part) => known.reduce((total, info) => total + info.time[part[0]], 0)), all = sum.reduce((a, b) => a + b, 0);
      const extra = t("super.wb.time.known", {k: known.length, n: list.length});
      if (!known.length) return block("time", t("super.wb.data.time"), "", [h("div", {class: "wbp-ok wbp-soft"}, t("super.wb.time.none"))]);
      const bar = h("div", {class: "wbp-two"}, TIME.map((part, at) => (sum[at] > 0 ? h("b", {class: part[2], style: "width:" + (sum[at] / all * 100).toFixed(2) + "%", title: t(part[1]) + " " + durOf(sum[at])}) : null)));
      const leg = h("div", {class: "wbp-leg"}, TIME.map((part, at) => h("span", null, h("i", {class: part[2]}), t(part[1]) + " ", h("b", null, durOf(sum[at])))));
      const wide = opened.time ? h("div", {class: "wbp-list"}, known.map((info) => [info, TIME.reduce((total, part) => total + info.time[part[0]], 0)]).sort((a, b) => b[1] - a[1] || a[0].name.localeCompare(b[0].name)).map((pair) => h("div", {class: "wbp-look " + KC(pair[0].kind), "data-wbp-task": pair[0].name, "data-wbp-hv": ""}, avatar(pair[0], 16), h("span", {class: "wbp-ln1"}, pair[0].shown), h("span", {class: "wbp-r"}, durOf(pair[1]))))) : null;
      return block("time", t("super.wb.data.time"), extra, [bar, leg, wide], toggleBtn("time", opened.time ? t("super.wb.data.less") : t("super.wb.time.per")));
    }
    function spendBlock(list) {
      const withAiu = list.filter((info) => info.aiu !== null), withPrem = list.filter((info) => info.prem !== null);
      const aiu = withAiu.reduce((sum, info) => sum + info.aiu, 0), prem = withPrem.reduce((sum, info) => sum + info.prem, 0);
      const top = withAiu.slice().sort((a, b) => b.aiu - a.aiu || a.name.localeCompare(b.name));
      if (!withAiu.length && !withPrem.length) return block("spend", t("super.wb.data.spend"), t("super.wb.spend.scope"), [h("div", {class: "wbp-ok wbp-soft"}, t("super.wb.spend.none"))]);  // nothing recorded: one plain line, no dashes
      const tops = top.slice(0, 3).map((info) => h("span", {class: "wbp-topx", "data-wbp-task": info.name, "data-wbp-hv": ""}, avatar(info, 17), info.aiu.toFixed(1)));
      const head = h("div", {class: "wbp-spend"}, h("div", {class: "wbp-big"}, withAiu.length ? t("super.wb.hv.aiu.value", {n: (Math.round(aiu * 10) / 10).toFixed(1)}) : NONE),
        h("div", {class: "wbp-big wbp-sm"}, withPrem.length ? Math.round(prem * 10) / 10 + " " + t("super.wb.spend.premium") : NONE), h("div", {class: "wbp-tops"}, tops));
      const wide = opened.spend ? h("div", {class: "wbp-list"}, top.map((info) => h("div", {class: "wbp-look " + KC(info.kind), "data-wbp-task": info.name, "data-wbp-hv": ""}, avatar(info, 16), h("span", {class: "wbp-ln1"}, info.shown), h("span", {class: "wbp-r"}, info.aiu.toFixed(1))))) : null;
      return block("spend", t("super.wb.data.spend"), t("super.wb.spend.scope"), [head, wide], top.length > 3 ? toggleBtn("spend", opened.spend ? t("super.wb.data.less") : t("super.wb.spend.all")) : null);
    }
    function dataNode(list) { return [lookBlock(list), askBlock(list), pipeBlock(list), timeBlock(list), spendBlock(list)].filter(Boolean); }

    // ---- the bridge and the picture of Focus: one drawing, two sizes ----
    function subLetter(info, at) {  // the letter of the at-th circle of a task: its groups in order, one circle for each running subagent
      let left = at;
      for (const one of info.subs) { if (left < one.n) return (one.type || "?").charAt(0).toUpperCase(); left -= one.n; }
      return "?";
    }
    const shortName = (text, chars) => (text.length > chars ? text.slice(0, Math.max(1, chars - 1)) + "…" : text);
    // The plan of a drawing: which tasks show, in which order. The signature is made of it, so a change of the order of waits that no one sees draws nothing.
    function planOf(width, big) {
      const items = models.map((info) => ({name: info.name, kind: info.kind, subsN: info.subsN, waited: info.waited, info}));
      return bridgeGroups(items, fitOf(width, big));
    }
    function planSig(plan, W, H, big, quiet, down) {
      const one = (item) => { const info = item.info; return [info.name, info.shown, info.kind, info.subsN, info.subs.map((sub) => sub.type + sub.n).join(","), info.gate ? info.gate.n : 0, startingOf(info.row) ? 1 : 0].join("~"); };  // 1.8.50: Starting… becomes working
      return [W, H, big, quiet, down, targetOf(), plan.grouped, closedN, closedMoreN, plan.groups.map((group) => group.kind + group.more + ":" + group.list.length + ":" + group.show.map(one).join("|")).join("/")].join("#");
    }
    function sceneSVG(plan, W, H, big, quiet, down) {
      const nodes = [];
      plan.groups.forEach((group, gi) => {
        group.show.forEach((item) => nodes.push({info: item.info, kind: group.kind, g: gi}));
        if (group.more) nodes.push({more: group.more, kind: group.kind, g: gi, group});
      });
      const dense = plan.grouped, rows = big && nodes.length > 14 ? 2 : 1, perRow = Math.max(1, Math.ceil(nodes.length / rows));
      const sx = W / 2, sy = big ? 50 : 28, sr = big ? 34 : 17, tr = big ? (dense ? 20 : 25) : (dense ? 14 : 16);
      const y0 = big ? clamp(H * 0.4, 170, 240) : (H <= 170 ? 80 : 92), rowGap = 185, gapG = dense ? (big ? 22 : 14) : 0, margin = big ? 60 : 45;
      const sr2 = big ? 8 : dense ? 4.5 : 5.5, pitch = 2 * sr2 + 3;
      const back = [], front = [], marks = [], target = targetOf();
      const wq = [], kq = [];
      let bottom = 0;
      for (let r = 0; r < rows; r++) {
        const row = nodes.slice(r * perRow, (r + 1) * perRow);
        if (!row.length) continue;
        let breaks = 0;
        row.forEach((node, at) => { if (at > 0 && node.g !== row[at - 1].g) breaks++; });
        const itemW = Math.min((W - 2 * margin - gapG * breaks) / row.length, dense ? (big ? 64 : 46) : (big ? 130 : 104)), startX = (W - (itemW * row.length + gapG * breaks)) / 2;
        let before = 0, rowBottom = 0;
        const segs = [];
        row.forEach((node, at) => {
          if (at > 0 && node.g !== row[at - 1].g) before++;
          const x = startX + itemW * (at + 0.5) + gapG * before;
          const frac = row.length > 1 ? at / (row.length - 1) : 0.5;
          const y = y0 + r * rowGap + (dense || rows > 1 ? 0 : (big ? 40 : 12) * Math.sin(frac * Math.PI));
          const col = "wbp-k-" + node.kind;
          const d = "M" + sx + "," + (sy + sr) + " Q" + ((sx + x) / 2).toFixed(1) + "," + ((sy + sr + y - tr) / 2 + (big ? 40 : 18)).toFixed(1) + " " + x.toFixed(1) + "," + (y - tr).toFixed(1);
          const seg = segs.length && segs[segs.length - 1].g === node.g ? segs[segs.length - 1] : segs[segs.push({g: node.g, kind: node.kind, x0: x, x1: x, group: plan.groups[node.g]}) - 1];
          seg.x1 = x;
          if (node.more) {  // the "+N" of a state: a dashed bubble; a click lists the tasks of the state
            back.push(el("path", {d, class: "wbp-ln wbp-more-ln " + col}));
            front.push(el("g", {class: "wbp-bub " + col, "data-wbp-more": node.kind, role: "button", tabindex: "0", "aria-label": t(GRP[node.kind]) + " +" + node.more},
              el("title", null, t("super.wb.bridge.more.tip")), el("circle", {cx: x.toFixed(1), cy: y.toFixed(1), r: tr}), el("text", {x: x.toFixed(1), y: (y + 4).toFixed(1), "text-anchor": "middle", "font-size": big ? 12 : 10.5}, "+" + node.more)));
            rowBottom = Math.max(rowBottom, y + tr);
            return;
          }
          const info = node.info;
          back.push(el("path", {d, class: "wbp-ln " + col}), el("path", {d, class: "wbp-lnhit", "data-wbp-task": info.name, "data-wbp-hv": ""}));
          if (info.kind === "work") kq.push({d, info, at: r * 100 + at}); else if (info.kind === "wait") wq.push({d, info, at: r * 100 + at});
          const lines = dense ? (info.kind === "wait" ? 1 : 0) : 2, textH = dense ? (lines ? 14 : 0) : (big ? 34 : 27);
          const slots = Math.min(SUB_CAP, info.subsN) + (info.subsN > SUB_CAP ? 1 : 0), cols = clamp(Math.floor(itemW / pitch), 1, 8), per = Math.min(cols, Math.max(slots, 1));
          const firstCy = y + tr + textH + 6 + sr2;
          for (let k = 0; k < slots; k++) {
            const gx = x + ((k % per) - (per - 1) / 2) * pitch, gy = firstCy + Math.floor(k / per) * pitch;
            if (k >= SUB_CAP) { front.push(el("text", {x: gx.toFixed(1), y: (gy + 3).toFixed(1), "text-anchor": "middle", class: "wbp-more", "font-size": big ? 10 : 9, "data-wbp-task": info.name, "data-wbp-hv": ""}, "+" + (info.subsN - SUB_CAP))); continue; }
            back.push(el("line", {x1: x.toFixed(1), y1: (y + tr + textH).toFixed(1), x2: gx.toFixed(1), y2: (gy - sr2).toFixed(1), class: "wbp-sl2"}));
            front.push(el("g", {class: "wbp-sc", "data-wbp-task": info.name, "data-wbp-hv": ""}, el("circle", {cx: gx.toFixed(1), cy: gy.toFixed(1), r: sr2}), sr2 >= 5.5 ? el("text", {x: gx.toFixed(1), y: (gy + 2.6).toFixed(1), "text-anchor": "middle", "font-size": 7}, subLetter(info, k)) : null));
          }
          const subsBottom = slots ? firstCy + (Math.ceil(slots / per) - 1) * pitch + sr2 : 0;
          rowBottom = Math.max(rowBottom, y + tr + textH, subsBottom);
          const group = el("g", {class: "wbp-t wbp-i" + info.id + " " + col, "data-wbp-task": info.name, "data-wbp-hv": "", role: "button", tabindex: "0", "aria-label": info.shown},
            el("circle", {cx: x.toFixed(1), cy: y.toFixed(1), r: tr, class: "wbp-body"}),
            el("circle", {cx: (x - tr * .3).toFixed(1), cy: (y - tr * .1).toFixed(1), r: (tr * .15).toFixed(2), class: "wbp-eye"}),
            el("circle", {cx: (x + tr * .3).toFixed(1), cy: (y - tr * .1).toFixed(1), r: (tr * .15).toFixed(2), class: "wbp-eye"}),
            el("circle", {cx: x.toFixed(1), cy: y.toFixed(1), r: tr + 3, class: "wbp-hit"}));
          front.push(group);
          if (info.name === target) front.push(el("circle", {cx: x.toFixed(1), cy: y.toFixed(1), r: tr + 5, class: "wbp-ring"}));
          if (info.gate && info.gate.n > 0) front.push(el("g", {class: "wbp-gatebadge"}, el("circle", {cx: (x - tr * .78).toFixed(1), cy: (y - tr * .78).toFixed(1), r: big ? 7 : 5.5}), el("text", {x: (x - tr * .78).toFixed(1), y: (y - tr * .78 + 2.8).toFixed(1), "text-anchor": "middle", "font-size": 8}, info.gate.n > 99 ? "99" : info.gate.n)));
          const fs = big ? 11 : dense ? 8.5 : 9.5;
          if (!dense || info.kind === "wait") {  // the word of the state, or the time a task has waited
            const label = el("text", {x: x.toFixed(1), y: (y + tr + (big ? 16 : 12)).toFixed(1), "text-anchor": "middle", class: "wbp-lb " + col, "font-size": fs});
            if (info.kind === "wait") { const cell = el("tspan", null); label.append(cell); runCell(cell, "wait", info.name); } else label.append(wordOf(info));
            front.push(label);
          }
          if (!dense) front.push(el("text", {x: x.toFixed(1), y: (y + tr + (big ? 30 : 23)).toFixed(1), "text-anchor": "middle", class: "wbp-nmlb", "font-size": big ? 10.5 : 9}, shortName(info.shown, Math.floor((itemW - 2) / (big ? 6.4 : 5.6)))));
        });
        bottom = Math.max(bottom, rowBottom);
        if (dense) {
          const by = rowBottom + 8;
          for (const seg of segs) {
            const x0 = seg.x0 - tr, x1 = seg.x1 + tr;
            marks.push(el("path", {d: "M" + x0.toFixed(1) + "," + (by - 5) + " v5 h" + (x1 - x0).toFixed(1) + " v-5", class: "wbp-br wbp-k-" + seg.kind}),
              el("text", {x: ((x0 + x1) / 2).toFixed(1), y: (by + 12).toFixed(1), "text-anchor": "middle", class: "wbp-brl wbp-k-" + seg.kind, "font-size": 9.5}, t(GRP[seg.kind]).toUpperCase() + " " + seg.group.list.length));
          }
          bottom = Math.max(bottom, by + 16);
        }
      }
      // the moving dots: down a working task's line, up a waiting one's; at most DOTS, a working and a waiting task in turn
      const dots = [];
      while (dots.length < DOTS && (wq.length || kq.length)) { if (kq.length) dots.push(kq.shift()); if (dots.length < DOTS && wq.length) dots.push(wq.shift()); }
      const moving = [];
      if (!down) for (const dot of dots) {
        const col = "wbp-k-" + dot.info.kind, c = el("circle", {r: big ? 3.6 : 2.8, class: "wbp-dot " + col, "data-wbp-task": dot.info.name, "data-wbp-hv": ""});
        if (quiet) { const m = /^M([\d.-]+),([\d.-]+) Q([\d.-]+),([\d.-]+) ([\d.-]+),([\d.-]+)$/.exec(dot.d); if (m) { c.setAttribute("cx", (0.25 * m[1] + 0.5 * m[3] + 0.25 * m[5]).toFixed(1)); c.setAttribute("cy", (0.25 * m[2] + 0.5 * m[4] + 0.25 * m[6]).toFixed(1)); } }
        else c.append(el("animateMotion", Object.assign({dur: dot.info.kind === "work" ? "2.2s" : "3s", begin: "-" + ((dot.at * 0.37) % 2.2).toFixed(2) + "s", repeatCount: "indefinite", path: dot.d}, dot.info.kind === "wait" ? {keyPoints: "1;0", keyTimes: "0;1", calcMode: "linear"} : {})));
        moving.push(c);
      }
      const out = [...back, ...moving, ...front, ...marks];
      if (!quiet && !down) out.push(el("circle", {cx: sx, cy: sy, r: sr + 6, class: "wbp-pulse"}, el("animate", {attributeName: "r", values: (sr + 3) + ";" + (sr + (big ? 20 : 10)) + ";" + (sr + 3), dur: "3s", repeatCount: "indefinite"})));
      out.push(el("g", {class: "wbp-bossg", "data-wbp-boss": "", role: "button", tabindex: "0", "aria-label": t("super.wb.bridge.boss.tip")},  // a click on the super agent itself: the target goes back to All (1.8.25)
        el("title", null, t("super.wb.bridge.boss.tip")),
        el("rect", {x: sx - sr, y: sy - sr, width: sr * 2, height: sr * 2, rx: (sr * .34).toFixed(1), class: "wbp-boss"}),
          el("circle", {cx: (sx - sr * .36).toFixed(1), cy: (sy - sr * .08).toFixed(1), r: (sr * .16).toFixed(1), class: "wbp-bosseye"}), el("circle", {cx: (sx + sr * .36).toFixed(1), cy: (sy - sr * .08).toFixed(1), r: (sr * .16).toFixed(1), class: "wbp-bosseye"})));
      if (big) out.push(el("text", {x: sx, y: sy + sr + 18, "text-anchor": "middle", class: "wbp-bossname", "font-size": 12.5}, t("super.name")));
      if (!nodes.length) out.push(el("text", {x: sx, y: (big ? sy + sr + 46 : sy + sr + 30), "text-anchor": "middle", class: "wbp-lb wbp-k-idle", "font-size": 12}, t("super.wb.none")));
      const content = Math.max(H, Math.ceil(bottom + 10));  // a picture that needs more height than the place has is drawn smaller, never cut
      return el("svg", {viewBox: "0 0 " + W + " " + content, preserveAspectRatio: "xMidYMin meet", role: "group", "aria-label": t("super.wb.bridge.label"), class: "wbp-svg" + (down ? " wbp-dim" : "")}, out);
    }
    const bridgeChip = () => (closedN > 0 && closedChip ? h("button", {type: "button", class: "wbp-closed", "data-wbp-closed": "", title: t("super.wb.bridge.closed.tip")}, "▤ " + t("super.wb.bridge.closed", {n: closedN + (closedMoreN ? "+" : "")})) : null);
    function paintBridge(node, key, big, vis) {
      const W = node.clientWidth, H = node.clientHeight || (vis.tall ? 160 : 190);
      if (W < 120) return;  // not laid out (hidden): drawn when it is
      const quiet = still(), plan = planOf(W, big);
      const sig = planSig(plan, W, H, big, quiet, vis.down) + (big ? "" : "|" + (closedChip ? 1 : 0));
      if (sigs[key] === sig && node.firstChild) return;
      sigs[key] = sig;
      for (let at = cells.length - 1; at >= 0; at--) if (node.contains(cells[at].node)) cells.splice(at, 1);
      const svg = sceneSVG(plan, W, H, big, quiet, vis.down);
      if (big) node.replaceChildren(h("div", {class: "wbp-cap"}, t("super.wb.scene.cap", {n: models.length, m: models.reduce((sum, info) => sum + info.subsN, 0)})), svg);
      else node.replaceChildren(...[svg, bridgeChip()].filter(Boolean));
    }

    // ---- a list that opens on a "+N" (a state of the bridge, a column of the pipeline) ----
    function closeList() { popSpec = null; if (pop) { for (let at = cells.length - 1; at >= 0; at--) if (pop.contains(cells[at].node)) cells.splice(at, 1); pop.remove(); pop = null; } }
    function fillList() {
      const list = popSpec.list();
      if (!list.length) { closeList(); return; }
      for (let at = cells.length - 1; at >= 0; at--) if (pop.contains(cells[at].node)) cells.splice(at, 1);
      const rows = list.map((info) => h("button", {type: "button", class: "wbp-pi " + KC(info.kind), "data-wbp-pick": info.name, "data-wbp-task": info.name, "data-wbp-hv": ""},
        avatar(info, 18), h("span", {class: "wbp-pn"}, info.shown), h("span", {class: "wbp-pt"}, info.kind === "wait" ? runCell(h("span"), "wait", info.name) : wordOf(info))));
      pop.replaceChildren(h("h5", null, popSpec.title + " · " + list.length), h("div", {class: "wbp-pl"}, rows));
      tick();
    }
    function openList(title, list, rect) {
      closeList();
      popSpec = {title, list};
      pop = h("div", {class: "wbp-pop", role: "dialog"});
      (rootNode || document.body).append(pop);
      fillList();
      if (!pop) return;
      const width = Math.min(340, innerWidth - 16);
      pop.style.width = width + "px";
      pop.style.left = Math.round(clamp(rect.left, 8, innerWidth - width - 8)) + "px";
      pop.style.top = Math.round(clamp(rect.bottom + 8, 8, Math.max(8, innerHeight - 300))) + "px";
    }
    const sortedOf = (kind) => models.filter((info) => info.kind === kind).sort((a, b) => (kind === "wait" ? b.waited - a.waited : 0) || a.name.localeCompare(b.name));
    function pickIt(name) { closeList(); if (pickTask) pickTask(name); }  // "" is the super agent itself: back to All
    function wire(node) {  // the clicks of a picture (the bridge, the Focus picture)
      let press = null, held = false;
      node.addEventListener("click", (event) => {
        if (held) { held = false; return; }
        const target = event.target && event.target.closest ? event.target : null;
        if (!target) return;
        const more = target.closest("[data-wbp-more]");
        if (more) { const kind = more.getAttribute("data-wbp-more"); openList(t(GRP[kind]), () => sortedOf(kind), more.getBoundingClientRect()); return; }
        const chip = target.closest("[data-wbp-closed]");
        if (chip) { const box = chip.getBoundingClientRect(); if (closedChip) closedChip(box.left, box.bottom); return; }
        if (target.closest("[data-wbp-boss]")) { pickIt(""); return; }
        const one = target.closest(".wbp-t[data-wbp-task]");
        if (one) pickIt(one.getAttribute("data-wbp-task"));
      });
      node.addEventListener("contextmenu", (event) => {
        const one = event.target && event.target.closest ? event.target.closest(".wbp-t[data-wbp-task]") : null;
        if (!one || !menuTask) return;
        event.preventDefault();
        menuTask(one.getAttribute("data-wbp-task"), event.clientX, event.clientY);
      });
      node.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const target = event.target && event.target.closest ? event.target : null;
        const more = target && target.closest("[data-wbp-more]"), one = target && target.closest(".wbp-t[data-wbp-task]"), boss = target && target.closest("[data-wbp-boss]");
        if (boss) { event.preventDefault(); pickIt(""); } else if (more) { event.preventDefault(); more.dispatchEvent(new MouseEvent("click", {bubbles: true})); } else if (one) { event.preventDefault(); pickIt(one.getAttribute("data-wbp-task")); }
      });
      node.addEventListener("pointerdown", (event) => {  // a long press (a finger) is the right click
        if (event.pointerType === "mouse" || !menuTask) return;
        const one = event.target && event.target.closest ? event.target.closest(".wbp-t[data-wbp-task]") : null;
        if (!one) return;
        const x = event.clientX, y = event.clientY, name = one.getAttribute("data-wbp-task");
        press = {x, y, timer: setTimeout(() => { held = true; press = null; menuTask(name, x, y); }, 550)};
      });
      const cancel = (event) => { if (press && (!event || event.type !== "pointermove" || Math.abs(event.clientX - press.x) + Math.abs(event.clientY - press.y) > 8)) { clearTimeout(press.timer); press = null; } };
      node.addEventListener("pointerup", cancel);
      node.addEventListener("pointercancel", cancel);
      node.addEventListener("pointermove", cancel);
    }

    // ---- drawing, only when a signature changed ----
    const treeSig = (info) => [info.name, info.shown, info.kind, info.tags.join("+"), info.subs.map((one) => one.label + "@" + one.since).join(","), info.row.state, info.now, info.gate ? info.gate.n : -1];
    const dataSig = (info) => [info.name, info.shown, info.kind, info.place.lane + ":" + info.place.step, info.decision, info.aiu, info.prem, info.ctx ? info.ctx.percent : null, info.gate ? info.gate.n + "/" + info.gate.m : null, info.time ? TIME.map((part) => Math.round(info.time[part[0]])).join(",") : null,
      (Array.isArray(info.row.warn) ? info.row.warn : []).map((item) => item && item.rule + ":" + item.n).join(",")];
    function refresh(vis) {
      lastVis = vis;
      const now = Date.now();
      const all = rowsOf() || [];
      const open = all.filter((row) => row && (row.status === "open" || handedOff(row)));  // 1.8.50: with the closed tasks just handed to an agent, until it opens them
      closedN = all.reduce((sum, row) => sum + (row && row.status === "closed" && !handedOff(row) ? 1 : 0), 0);
      closedMoreN = Number(moreOf()) > 0 ? 1 : 0;
      closedBy = {};
      for (const row of all) if (row && row.status === "closed") { const lane = laneOf(String(row.kind || "")); closedBy[lane] = (closedBy[lane] || 0) + 1; }
      models = open.map(infoOf);
      byName = new Map(models.map((info) => [info.name, info]));
      for (const info of models) {
        const seen = waitBase.get(info.name), s = finite(info.row.waited_s) ? info.row.waited_s : null;
        if (s === null) waitBase.delete(info.name); else if (!seen || seen.s !== s) waitBase.set(info.name, {s, at: now});
      }
      for (const name of [...waitBase.keys()]) if (!byName.has(name)) waitBase.delete(name);
      const sorted = models.slice().sort((a, b) => RANK[a.kind] - RANK[b.kind] || (a.kind === "wait" ? b.waited - a.waited : 0) || a.name.localeCompare(b.name));
      for (const node of [tree, data, scene, bridge]) node.classList.toggle("wbp-down", vis.down);
      if (vis.tree) paint("tree", tree, JSON.stringify([vis.down, sorted.length > TREE_FLAT ? TREE_ORDER.map((kind) => fold[kind]) : 0, sorted.map(treeSig)]), () => treeNode(sorted));
      if (vis.data) paint("data", data, JSON.stringify([vis.down, closedBy, opened, sorted.map(dataSig)]), () => dataNode(sorted));
      if (vis.scene) paintBridge(scene, "scene", true, vis);
      if (vis.bridge) paintBridge(bridge, "bridge", false, vis);
      if (popSpec && pop) fillList();
      tick();
      if (current && current.isConnected) showHover(current); else if (current) hideHover();
    }
    function paint(key, node, sig, make) {
      if (sigs[key] === sig && node.firstChild) return;
      sigs[key] = sig;
      for (let at = cells.length - 1; at >= 0; at--) if (node.contains(cells[at].node)) cells.splice(at, 1);
      node.replaceChildren(...make());
    }
    // `vis`: {tree, data, scene: which of them are on screen, bridge: draw the bridge, tall: the strip of the picture, down: VS Code is not linked}
    function update(vis) { refresh({tree: Boolean(vis.tree), data: Boolean(vis.data), scene: Boolean(vis.scene), bridge: Boolean(vis.bridge), tall: Boolean(vis.tall), down: Boolean(vis.down)}); }
    function again() { frame = 0; if (lastVis) refresh(lastVis); }  // a place got another size
    function resized() { if (!frame) frame = requestAnimationFrame(again); }

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
      const gate = info.gate ? (info.gate.n > 0 ? t("super.wb.hv.gate.n", {n: info.gate.n, m: info.gate.m}) : t("super.wb.hv.gate.none")) : NONE;
      const split = info.time ? t("super.wb.hv.time.value", {model: durOf(info.time.model_s), tool: durOf(info.time.tool_s), sub: durOf(info.time.subagent_s), appr: durOf(info.time.approval_s), you: durOf(info.time.waiting_s)}) : null;
      const rowsOfCard = [[t("super.wb.hv.stage"), info.stage || NONE], [t("super.wb.hv.model"), model], [t("super.wb.hv.ctx.label"), ctx],
        [t("super.wb.hv.aiu"), info.aiu === null ? NONE : t("super.wb.hv.aiu.value", {n: info.aiu.toFixed(1)})], [t("super.wb.hv.checks"), checks],
        [t("super.wb.hv.autorun"), row.autorun ? t("super.wb.hv.on") : t("super.wb.hv.off")],
        [t("super.wb.hv.now"), info.now || NONE], [t("super.wb.hv.gate"), gate],
        [t("super.wb.hv.subs"), info.subs.length ? info.subs.map((one) => one.label).join(", ") : t("super.wb.hv.none")], [t("super.wb.hv.conns"), conns]];
      if (split) rowsOfCard.push([t("super.wb.hv.time"), split]);
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
    function bind(node) {  // the layer: a hover on a task's avatar or a line of the Data panel; the clicks of the pictures, of the groups of the tree and of the blocks of Data
      rootNode = node;
      node.append(hover);
      node.addEventListener("mouseover", (event) => {
        const target = event.target && event.target.closest ? event.target.closest(SEL) : null;
        if (!target) { if (current) hideHover(); return; }
        if (target !== current) showHover(target);
      });
      node.addEventListener("mouseleave", hideHover);
      node.addEventListener("scroll", () => { if (current) hideHover(); }, true);
      document.addEventListener("keydown", (event) => { if (event.key === "Escape") { if (current) hideHover(); if (pop) closeList(); } });
      node.addEventListener("click", (event) => {
        const target = event.target && event.target.closest ? event.target : null;
        if (!target) return;
        const pick = target.closest("[data-wbp-pick]");
        if (pick) { pickIt(pick.getAttribute("data-wbp-pick")); return; }
        if (pop && !target.closest(".wbp-pop") && !target.closest("[data-wbp-more], [data-wbp-col]")) closeList();
        const group = target.closest("[data-wbp-fold]");
        if (group) { const kind = group.getAttribute("data-wbp-fold"); fold[kind] = !fold[kind]; if (lastVis) refresh(lastVis); return; }
        const toggle = target.closest("[data-wbp-open]");
        if (toggle) { const key = toggle.getAttribute("data-wbp-open"); opened[key] = !opened[key]; if (lastVis) refresh(lastVis); return; }
        const col = target.closest("[data-wbp-col]");
        if (col) {
          const [lane, step] = String(col.getAttribute("data-wbp-col")).split(":");
          const ask = lane === "ask";
          openList(ask ? t(ASK_TEXT[step] || ASK_TEXT.other) : laneName(lane) + " · " + stepName(lane, step),
            () => models.filter((info) => (ask ? info.kind === "wait" && info.decision === step : info.place.lane === lane && info.place.step === step)).sort((a, b) => RANK[a.kind] - RANK[b.kind] || a.name.localeCompare(b.name)), col.getBoundingClientRect());
        }
      });
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
      const veil = h("div", {class: "wbp-intro", "aria-hidden": "true"}, h("span", {class: "wbp-ring0"}), h("span", {class: "wbp-ibot"}));
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

    const tree = h("div", {class: "wb-tree"}), data = h("div", {class: "wb-data"}), scene = h("div", {class: "wbp-scene"}), bridge = h("div", {class: "wbp-bridge"});
    wire(bridge);
    wire(scene);
    if (typeof ResizeObserver === "function") { const watch = new ResizeObserver(resized); watch.observe(bridge); watch.observe(scene); }
    return {tree, data, scene, bridge, update, start, stop, bind, decorate, intro};
  }
  let introPlayed = false;

  return {create, idOf, fitOf, bridgeGroups, placeOf, decisionOf};
})();
