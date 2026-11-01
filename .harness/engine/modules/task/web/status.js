// The small status marks of a task (1.6.14, B85b): one row of up to five marks, in this order: model, context, run time of the latest turn, stage, TODO.
// The list shows the row under the task name; the lobby card shows the same row. A mark with no data is not drawn (its place stays, so rows are as high and as aligned as the others).
// The mini stage ribbon (`Status.stages`, `Status.ribbon`) is a shared part: it does not know the list. The task page (B87) draws its stage strip from the same states and colours.
//   done: green, a check    running: blue, turning    waits for the person: yellow, blinking    not started: black (dark theme: dark fill, grey ring)
// One timer for the whole page ticks every run time; nothing here keeps a timer per row. Animations are in step with the clock (a negative delay from `--t`),
// so a row that is drawn again by the 3-second poll goes on from where its animation was, and does not start over.
// Needs common.js (h, t, clock, amount, stateOf, waitText). Drawn with DOM nodes and textContent only.
"use strict";

const Status = (function () {
  const NS = "http://www.w3.org/2000/svg";
  const PERIOD_MS = 2400;  // every animation of this file has a period that divides this (1.2 s, 2.4 s)
  const SLOTS = ["model", "context", "run", "stage", "todo"];
  const COMPACT_FROM = 11;  // more steps than this: segments, not dots, so the ribbon always fits its place

  const phase = (node) => { node.style.setProperty("--t", (Date.now() % PERIOD_MS) + "ms"); return node; };
  const svg = (name, attrs) => {
    const node = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    return node;
  };
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

  // --- the tip: one small panel for the whole page, opened by the pointer or the keyboard on any [data-tip] mark -------
  // The mark holds `_tip`, a function that gives a string or a node. The panel is moved to stay inside the window.
  const pop = {node: null, anchor: null, key: ""};
  let timer = 0;

  function popNode() {
    if (!pop.node) { pop.node = h("div", {class: "st-pop", role: "tooltip"}); document.body.append(pop.node); }
    return pop.node;
  }

  // Put `node` next to the `anchor` element: above it if there is room (`below`: first try under), else the other side; then pushed inside the window.
  function place(node, anchor, below) {
    const at = anchor.getBoundingClientRect(), width = node.offsetWidth, height = node.offsetHeight, gap = 6, edge = 8;
    const fitsAbove = at.top - gap - height >= edge, fitsBelow = at.bottom + gap + height <= window.innerHeight - edge;
    const under = below ? (fitsBelow || !fitsAbove) : !(fitsAbove || !fitsBelow);
    const top = under ? at.bottom + gap : at.top - gap - height;
    node.classList.toggle("below", under);
    node.style.left = clamp(at.left + at.width / 2 - width / 2, edge, Math.max(edge, window.innerWidth - width - edge)) + "px";
    node.style.top = clamp(top, edge, Math.max(edge, window.innerHeight - height - edge)) + "px";
  }

  function fillPop() {
    const content = pop.anchor && pop.anchor._tip ? pop.anchor._tip() : null;
    if (content === null || content === undefined || content === "") { hideTip(); return; }
    const node = popNode();
    if (typeof content === "string") node.replaceChildren(h("div", {class: "st-tx"}, content));
    else node.replaceChildren(content);
    place(node, pop.anchor, true);
  }

  function showTip(anchor) {
    if (pop.anchor === anchor) return;
    pop.anchor = anchor;
    pop.key = anchor.getAttribute("data-tip") || "";
    fillPop();
    if (pop.anchor) { popNode().classList.add("on"); ensureTimer(); }
  }

  function hideTip() {
    pop.anchor = null;
    pop.key = "";
    if (pop.node) pop.node.classList.remove("on");
  }

  // Delegated, once: a page of 100 rows has no listener on a row.
  document.addEventListener("mouseover", (event) => {
    const hit = event.target instanceof Element ? event.target.closest("[data-tip]") : null;
    if (hit && hit !== pop.anchor) showTip(hit);
    else if (!hit && pop.anchor) hideTip();
  });
  document.addEventListener("focusin", (event) => { const hit = event.target instanceof Element ? event.target.closest("[data-tip]") : null; if (hit) showTip(hit); });
  document.addEventListener("focusout", () => hideTip());
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") hideTip(); });
  document.addEventListener("scroll", () => { if (pop.anchor) hideTip(); }, true);
  window.addEventListener("resize", () => hideTip());
  document.documentElement.addEventListener("mouseleave", () => hideTip());

  // --- the clock: one interval for every run time on the page, and the housekeeping of the tip ---------------------
  function paintRun(node) {
    const since = Number(node.getAttribute("data-since"));
    const text = clock(Math.max(0, (Date.now() - since) / 1000));
    const label = node.querySelector(".st-time");
    if (label && label.textContent !== text) label.textContent = text;
    return text;
  }

  function tick() {
    if (document.hidden) return;
    const runs = document.querySelectorAll(".st-run[data-since]");
    for (const node of runs) paintRun(node);
    if (pop.anchor) {
      if (!pop.anchor.isConnected) {  // the page drew its rows again (the poll): find the same mark in the new rows, or let go
        const again = pop.key ? Array.from(document.querySelectorAll("[data-tip]")).find((node) => node.getAttribute("data-tip") === pop.key) : null;
        if (again) { pop.anchor = again; fillPop(); } else hideTip();
      } else if (pop.anchor.classList.contains("st-run") || pop.anchor.querySelector(".st-run")) fillPop();  // the time in the tip moves too
    }
    if (!runs.length && !pop.anchor) { clearInterval(timer); timer = 0; }
  }
  function ensureTimer() { if (!timer) timer = setInterval(tick, 1000); }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });

  // --- model, context, run time, TODO ---------------------------------------------------------------------------------
  // `claude-sonnet-5-5` -> `sonnet 5.5`; a date at the end and a provider in front are dropped. The whole name is in the tip.
  function shortModel(id) {
    const raw = String(id || "").trim();
    const name = raw.replace(/^.*\//, "").replace(/-\d{8}$/, "").replace(/^claude-/i, "").replace(/(\d)-(\d)/g, "$1.$2").replace(/[-_]+/g, " ").trim().toLowerCase();
    return name || raw;
  }

  // A mark with a tip. `focusable`: the keyboard can reach it (the lobby card; in a list of 100 rows only the ribbon is a tab stop, the others have a label for a screen reader).
  function marked(node, key, build, label, focusable) {
    node._tip = build;
    node.setAttribute("data-tip", key);
    if (focusable) node.setAttribute("tabindex", "0");
    if (label) node.setAttribute("aria-label", label);
    return node;
  }

  function modelMark(chat, key, focusable) {
    if (!chat || !chat.model) return null;
    const full = t("board.status.model", {model: chat.model});
    return marked(h("span", {class: "st-chip"}, shortModel(chat.model)), key, () => full, full, focusable);
  }

  const finite = (value) => typeof value === "number" && isFinite(value);

  function contextMark(chat, key, focusable) {
    const meter = chat && chat.context;
    if (!meter || !finite(meter.percent)) return null;
    const radius = 6.2, length = 2 * Math.PI * radius, shown = clamp(meter.percent, 0, 100);
    const over = finite(meter.limit) && meter.percent > meter.limit;
    const ring = svg("svg", {viewBox: "0 0 16 16", class: "st-ring" + (over ? (meter.percent >= 100 ? " bad" : " warn") : ""), "aria-hidden": "true"});
    ring.append(svg("circle", {cx: 8, cy: 8, r: radius, class: "st-track"}));
    if (shown > 0) ring.append(svg("circle", {cx: 8, cy: 8, r: radius, class: "st-arc", "stroke-dasharray": (length * shown / 100).toFixed(2) + " " + length.toFixed(2), transform: "rotate(-90 8 8)"}));
    const text = t("board.status.context", {percent: Math.round(meter.percent * 10) / 10, used: amount(meter.used), window: amount(meter.window)})
      + (over ? "\n" + t("board.status.context.warn", {limit: meter.limit}) : "");
    return marked(h("span", {class: "st-ctx"}, ring), key, () => text, text.replace("\n", ". "), focusable);
  }

  function runMark(chat, key, focusable) {
    if (!chat || chat.state !== "busy" || !chat.started_at) return null;
    const since = Date.parse(chat.started_at);
    if (isNaN(since)) return null;
    const node = h("span", {class: "st-run", "data-since": String(since)}, h("i", {class: "st-live"}), h("span", {class: "st-time"}, ""));
    paintRun(node);
    marked(node, key, () => t("board.status.run", {time: paintRun(node)}), "", focusable);
    node.setAttribute("aria-label", t("board.status.run", {time: clock(Math.max(0, (Date.now() - since) / 1000))}));
    ensureTimer();
    return node;
  }

  function todoMark(info, key, focusable) {
    if (!info || !finite(info.total) || info.total <= 0) return null;
    const done = clamp(finite(info.done) ? info.done : 0, 0, info.total);
    const text = t("board.status.todo", {done, total: info.total});
    const fill = h("i", {style: "width:" + (done / info.total * 100).toFixed(1) + "%"});
    return marked(h("span", {class: "st-todo" + (done >= info.total ? " full" : "")}, h("span", {class: "st-bar"}, fill), h("span", {class: "st-n"}, done + "/" + info.total)), key, () => text, text, focusable);
  }

  // --- the stages -----------------------------------------------------------------------------------------------------
  // The states of the steps of a row (`row.stages`, from taskstages.py) with the colours of the state of the task. The step that is now is:
  //   `bad`  the server flagged it (stopped halfway, failed)       `wait`  the task waits for the person       `run`  the agent is at work (a live page only)       `now`  none of these
  // `live`: the page is kept fresh (a page on disk cannot say "working").
  function stages(row, live) {
    const s = row && row.stages;
    if (!s || !Array.isArray(s.steps) || !s.steps.length) return null;
    const state = stateOf(row, live);
    const waits = state === "waiting" && row.status === "open";
    const works = state === "working" && row.status === "open";
    const steps = s.steps.map((step) => {
      const label = step.label || t("stage." + step.id);
      let kind = "todo", text = t("board.status.stage.todo");
      if (step.state === "done") { kind = "done"; text = t("board.status.stage.done"); }
      else if (step.state === "now") {
        if (step.flag) { kind = "bad"; text = t("stage." + step.flag); }
        else if (waits) { kind = "wait"; text = row.waiting_why === "tests" && s.handoff && s.handoff === step.label ? t("stage.tests") : t("board.status.stage.wait"); }
        else if (works) { kind = "run"; text = t("board.status.stage.run"); }
        else { kind = "now"; text = t("board.status.stage.now"); }
      }
      return {label, kind, text};
    });
    const review = s.review && (s.review.n || (s.review.states || []).length) ? {n: s.review.n, states: (s.review.states || []).map((mark) => ({pass: "done", run: "run", fail: "bad"}[mark] || "todo")), waived: Boolean(s.review.waived)} : null;
    return {steps, round: s.round || 1, review};
  }

  const dot = (kind, extra) => h("span", {class: "st-d k-" + kind + (extra ? " " + extra : "")});

  // The ribbon: a dot for each step and a line between two dots (a line is green once the step before it is done). Many steps: one segment each.
  function ribbon(found) {
    const compact = found.steps.length >= COMPACT_FROM;
    const parts = [];
    found.steps.forEach((step, index) => {
      parts.push(dot(step.kind, compact ? "seg" : ""));
      if (!compact && index < found.steps.length - 1) parts.push(h("i", {class: "st-l" + (step.kind === "done" ? " k-done" : "")}));
    });
    return h("span", {class: "st-ribbon" + (compact ? " compact" : "")}, parts);
  }

  // What the tip of the ribbon lists: every stage with its state, the one that is now in bold, the round, the reviewer's checks.
  function stageList(found) {
    const lines = [h("div", {class: "st-head"}, t("board.status.stage.title") + (found.round > 1 ? " · " + t("board.status.stage.round", {round: found.round}) : ""))];
    for (const step of found.steps) {
      lines.push(h("div", {class: "st-ln" + (["run", "wait", "now", "bad"].includes(step.kind) ? " cur" : "")}, dot(step.kind), h("span", {class: "st-nm"}, step.label), h("span", {class: "st-st k-" + step.kind}, step.text)));
    }
    if (found.review) {
      lines.push(h("div", {class: "st-ln st-rv"}, h("span", {class: "st-nm"}, found.review.n ? t("stage.reviewer", {n: found.review.n}) : t("stage.reviewer.off")), h("span", {class: "st-marks"}, found.review.states.map((kind) => dot(kind)))));
    }
    return h("div", {class: "st-list"}, lines);
  }

  function stageMark(row, live, key, focusable) {
    const found = stages(row, live);
    if (!found) return null;
    const label = t("board.status.stage.title") + ": " + found.steps.map((step) => step.label + " " + step.text).join(", ");
    return marked(ribbon(found), key, () => stageList(found), label, true);
  }

  // --- the row ----------------------------------------------------------------------------------------------------------
  // row(row, {live, wrap}) -> the element; element.update(row, live) changes only the marks whose data changed. `wrap`: the lobby card (the marks may go to a second line,
  // and a mark with no data takes no room); in the list every place keeps its width, so the marks of two rows are in line.
  function build(row, options) {
    const box = h("div", {class: "st-row" + (options && options.wrap ? " st-wrap" : "")});
    const places = {};
    for (const name of SLOTS) { places[name] = {node: h("span", {class: "st-slot st-s-" + name}), sig: null}; box.append(places[name].node); }
    phase(box);
    let live = Boolean(options && options.live);
    const make = {
      model: (data, key, focus) => modelMark(data.chat, key, focus),
      context: (data, key, focus) => contextMark(data.chat, key, focus),
      run: (data, key, focus) => runMark(data.chat, key, focus),
      stage: (data, key) => stageMark(data, live, key),
      todo: (data, key, focus) => todoMark(data.todo, key, focus),
    };
    const sigs = {
      model: (data) => data.chat && data.chat.model || "",
      context: (data) => JSON.stringify(data.chat && data.chat.context || null),
      run: (data) => data.chat && data.chat.state === "busy" ? data.chat.started_at || "" : "",
      stage: (data) => JSON.stringify([data.stages, data.status, stateOf(data, live), data.waiting_why, live]),
      todo: (data) => JSON.stringify(data.todo || null),
    };
    function update(data, nextLive) {
      if (nextLive !== undefined) live = Boolean(nextLive);
      for (const name of SLOTS) {
        const sig = sigs[name](data);
        if (sig === places[name].sig) continue;
        places[name].sig = sig;
        const node = make[name](data, (data.task || data.name || "") + "\n" + name, Boolean(options && options.wrap));
        places[name].node.replaceChildren(...(node ? [node] : []));
      }
    }
    update(row);
    box.update = update;
    return box;
  }

  return {row: build, stages, ribbon, stageList, dot, place, phase, shortModel, tick};
})();
