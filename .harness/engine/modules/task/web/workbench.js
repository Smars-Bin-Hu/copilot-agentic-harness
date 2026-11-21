// The super agent workbench, the "command deck" (1.8.24): a full-screen layer that takes the place of the narrow super agent view while the board is in its "super" mode.
// It does not draw the chat or the queue. It MOVES the nodes of super.js into its own places (never a clone: their listeners and their data stay) and puts them back when it closes:
//   - the `.sa` section (the chat, the input; its avatar row stays in the DOM, hidden: the bridge clicks it) goes into the middle column, under the bridge;
//   - the `.sa-queue` node (the cards that wait for the person) goes into the left Queue panel (the deck) or into one card at the bottom right (Focus: the first item only);
//   - the history and pop-out buttons of its head go into the top bar.
// The layer has no board chrome: the round buttons, the search and account pill and the dock are hidden under `html.wb-lock` (workbench.css); the board's dialogs stay above it.
// The deck: the chat in the middle, four panels that fold (Queue, Agents on the left; Data, Task on the right), two bars that resize the columns, a battery of today's Credits in the top bar,
// a FOCUS toggle (the chat and a big picture; what waits comes as one card), and a dash that puts the whole mode away (a small pill on the board brings it back).
// A window taller than wide uses the Tall layout: nothing covers anything, everything stacks downward.
// A link to a task page inside the layer opens that task in the Task pane (a tab with an iframe of `/task/<name>?embed=1`; a loaded frame is hidden, never destroyed, so a tab switch is instant).
// The bridge, the tree, the Data blocks, the picture of Focus, the hover card of a task and the task line of a queue item are drawn by wbpanels.js; this file gives them their places, says which are on screen and
// gives the bridge its four calls (pick, menu, closed, target), which act on the avatars of super.js.
// Needs common.js, serve.js, super.js (SUPER.waiting) and wbpanels.js; board.js calls `WORKBENCH.create`.
"use strict";

const WORKBENCH = (function () {
  const PREFIX = "harness.board.wb.";
  const MAX_FRAMES = 6;  // task pages kept loaded; the oldest one is dropped
  const memory = {};
  const store = {
    get(name, fallback) { try { const value = localStorage.getItem(PREFIX + name); return value === null ? fallback : value; } catch (error) { return name in memory ? memory[name] : fallback; } },
    set(name, value) { memory[name] = value; try { localStorage.setItem(PREFIX + name, value); } catch (error) { /* kept in memory only */ } },
  };
  const query = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  const still = () => Boolean(query && query.matches) || document.documentElement.classList.contains("lite");
  const isTall = () => innerWidth < innerHeight;
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const taskUrl = (name) => "/task/" + encodeURIComponent(name);
  function taskOf(href) {  // the task a link opens, if it is a link to a task page
    const found = /^\/task\/([^/?#]+)(?:[?#].*)?$/.exec(String(href || ""));
    if (!found) return "";
    try { return decodeURIComponent(found[1]); } catch (error) { return ""; }
  }
  const PANELS = ["q", "t", "d", "p"];  // Queue, Agents (left); Data, Task (right)
  const SIDES = {l: ["q", "t"], r: ["d", "p"]};
  const sideOf = (key) => (key === "q" || key === "t" ? "l" : "r");
  const LIMITS = {l: [220, 560], r: [300, 1400]};  // the narrowest and widest a side can be dragged to (the right one is also kept 700 px short of the window)
  const RECHARGE = [25, 50];
  const RECHARGE_MAX = 200;  // what the server allows a day (superbrain.EXTRA_MAX): a button that would pass it is off

  // The pet of super.js is not wanted in the deck (the bridge takes its place). board.js gives this stand-in to SUPER.create (`makePet`): the same calls, doing nothing:
  // no 3D robot, no timer, no frame, and nothing is put in the page. It is always "held": super.js then never sends it to carry an item or to patrol, so a new item shows at once (review 1 of the deck).
  function stillPet() {
    const idle = () => undefined;
    const own = {node: h("button", {type: "button", class: "sa-pet", hidden: ""}), solid: false, held: () => true, at: () => ({x: 0, y: 0}), size: () => ({w: 0, h: 0}), walkTo: () => Promise.resolve(), orbit: idle};
    return new Proxy(own, {get: (target, key) => (key in target ? target[key] : idle)});
  }

  function create(options) {
    const superView = options.superView;
    const sv = superView.node;
    const rowsOf = options.rows || (() => []);
    const mateOf = (task) => (task ? [...sv.querySelectorAll(".sa-team .sa-mate[data-task]")].find((node) => node.dataset.task === task) || null : null);
    const placeAt = (menu, x, y) => {  // super.js puts its menus under the avatar it knows; the avatar of the bridge is elsewhere, so the menu goes to the point asked
      if (!menu) return;
      const box = sv.getBoundingClientRect();
      menu.style.left = clamp(x - box.left, 0, Math.max(0, box.width - menu.offsetWidth)) + "px";
      menu.style.top = clamp(y - box.top, 0, Math.max(0, box.height - menu.offsetHeight)) + "px";
    };
    // The four calls of the bridge: what a click on a bridge avatar does is what a click on the avatar of super.js does (the avatar row stays in the DOM, hidden).
    const bridgeCalls = {
      pick(task) { const mate = mateOf(task); if (mate) mate.click(); setTimeout(() => update(), 0); },  // the ring of the target moves at once, not at the next refresh
      menu(task, x, y) {
        const mate = mateOf(task);
        if (!mate) return;
        mate.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, button: 2, clientX: x, clientY: y}));
        placeAt(sv.querySelector(".sa-matemenu"), x, y);
      },
      closed(x, y) {
        const shut = sv.querySelector(".sa-team .sa-closed");
        if (!shut) return;
        shut.click();
        placeAt(sv.querySelector(".sa-closedmenu"), x, y);
      },
      target() { const on = sv.querySelector(".sa-team .sa-mate.on[data-task]"); return on ? on.dataset.task || "" : ""; },
    };
    const panels2 = WBPANELS.create(Object.assign({rows: rowsOf}, bridgeCalls));  // the drawing of the panels
    let mode = store.get("mode", "wb") === "focus" ? "focus" : "wb";
    let fold = {q: false, t: false, d: false, p: false};  // a folded panel is only its head line; a side with both folded is a rail
    try { const saved = JSON.parse(store.get("fold", "{}")); for (const key of PANELS) if (typeof saved[key] === "boolean") fold[key] = saved[key]; } catch (error) { /* the default */ }
    let widths = {l: null, r: null};  // pixels the person dragged the sides to; null: the default
    try { const saved = JSON.parse(store.get("widths", "{}")); for (const side of ["l", "r"]) if (typeof saved[side] === "number" && isFinite(saved[side])) widths[side] = saved[side]; } catch (error) { /* the default */ }
    let sheet = "";  // Tall Workbench: the one of Queue, Agents and Data that is open under the chat
    let taskOn = false;  // the Task layer where the panel is not a fixed one: the window of Focus, the layer of Tall (not kept)
    let cardMin = false;  // Focus: the card is put away (not kept)
    let open = false, tall = false, down = false, minimized = false;
    let home = null, queueHome = null, queueNode = null, queueList = null, observer = null, costObserver = null, moved = [], headHome = null;
    let tabs = [], active = "", cardSig = "", cardId = "";
    const later = new Map();  // task item id -> the number of the "Later" that moved it to the end
    let laterNo = 0;

    // ---- the places ----
    const root = h("div", {class: "wb-root", hidden: "", "aria-label": t("super.name")});
    const pn = {};
    const docks = {}, rails = {};
    const back = h("button", {type: "button", class: "wb-back", title: t("super.wb.min"), "aria-label": t("super.wb.min")}, "—");
    const ICON = {q: "☰", t: "⌥", d: "▤", p: "▭"};
    const LABEL = {q: "super.wb.panel.queue", t: "super.wb.panel.agents", d: "super.wb.panel.data", p: "super.wb.panel.task"};
    const queueCount = h("span", {class: "wb-cnt", hidden: ""});
    const dockCount = h("span", {class: "wb-cnt", hidden: ""});
    for (const key of PANELS) {
      docks[key] = h("button", {type: "button", class: "wb-dk", title: t(LABEL[key]), "aria-label": t(LABEL[key]), "aria-pressed": "false"}, h("span", {class: "wb-ic", "aria-hidden": "true"}, ICON[key]), h("span", {class: "wb-dkn"}, t(LABEL[key])), key === "q" ? dockCount : null);
      rails[key] = h("button", {type: "button", class: "wb-rb", title: t(LABEL[key]), "aria-label": t(LABEL[key])}, ICON[key], key === "q" ? queueCount : null);
    }
    // the battery of the super agent's Credits today; the numbers are read from the one super.js draws (see `readCost`)
    const cellBar = h("i");
    const cell = h("span", {class: "wb-cell", "aria-hidden": "true"}, cellBar);
    const pct = h("span", {class: "wb-pct"});
    const batt = h("button", {type: "button", class: "wb-batt", hidden: "", "aria-haspopup": "dialog", "aria-expanded": "false"}, cell, pct);
    const tools = h("span", {class: "wb-tools"});  // the history and pop-out buttons of super.js move here
    const focusBtn = h("button", {type: "button", class: "wb-focus", title: t("super.wb.mode.focus.tip"), "aria-pressed": "false"}, t("super.wb.mode.focus"));
    const top = h("header", {class: "wb-top"}, back, h("span", {class: "wb-bot", "aria-hidden": "true"}), h("b", {class: "wb-name"}, t("super.name")), batt, tools, h("span", {class: "wb-sp"}), focusBtn);

    function panel(key, headKey, count) {
      const fb = h("button", {type: "button", class: "wb-fold-btn", "aria-expanded": "true"}, "—");
      fb.addEventListener("click", () => foldPanel(key, !fold[key]));
      const head = h("div", {class: "wb-ph"}, h("b", null, t(headKey)), count || null, fb);
      head.addEventListener("click", (event) => { if (fold[key] && !event.target.closest(".wb-fold-btn")) foldPanel(key, false); });  // a click on the line of a folded panel opens it
      const body = h("div", {class: "wb-pb"});
      pn[key] = h("section", {class: "wb-pn wb-pn-" + key, hidden: ""}, head, body);
      return body;
    }
    const queueTotal = h("span", {class: "wb-pc"});
    const queueBody = panel("q", "super.queue", queueTotal);
    queueBody.classList.add("wb-qb");
    const queueEmpty = h("div", {class: "wb-soon wb-qempty"}, t("super.wb.queue.empty"));
    queueBody.append(queueEmpty);
    const treeBody = panel("t", "super.wb.head.agents");
    treeBody.append(panels2.tree);
    const dataBody = panel("d", "super.wb.head.data");
    dataBody.append(panels2.data);

    // The Task pane: tabs, one iframe each. Made once and never moved (a moved iframe reloads); CSS puts it in the right column, in the window of Focus, or under the chat.
    const tabsEl = h("div", {class: "wb-tabs", role: "tablist"});
    const out = h("a", {class: "wb-out", "data-wb-out": "", href: "#", target: "_blank", rel: "noopener", title: t("super.wb.task.out"), "aria-label": t("super.wb.task.out"), hidden: ""}, "↗");
    const closeLayer = h("button", {type: "button", class: "wb-x wb-closelayer", title: t("super.wb.task.close"), "aria-label": t("super.wb.task.close")}, "✕");
    const taskFold = h("button", {type: "button", class: "wb-fold-btn", "aria-expanded": "true"}, "—");
    taskFold.addEventListener("click", () => foldPanel("p", !fold.p));
    const framesEl = h("div", {class: "wb-frames"});
    const taskEmpty = h("div", {class: "wb-soon wb-task-empty"}, t("super.wb.task.empty"));
    framesEl.append(taskEmpty);
    const taskLbl = h("b", {class: "wb-tlbl"}, t(LABEL.p));  // the name of the panel while no tab is open or the panel is folded
    const tabbar = h("div", {class: "wb-tabbar"}, taskLbl, tabsEl, out, closeLayer, taskFold);
    tabbar.addEventListener("click", (event) => { if (fold.p && (event.target === tabbar || event.target === tabsEl || event.target === taskLbl)) foldPanel("p", false); });
    pn.p = h("section", {class: "wb-pn wb-pn-p", hidden: ""}, tabbar, framesEl);

    const railL = h("div", {class: "wb-rail"}, rails.q, rails.t);
    const railR = h("div", {class: "wb-rail"}, rails.d, rails.p);
    const left = h("aside", {class: "wb-side wb-l"}, pn.q, pn.t, railL);
    const right = h("aside", {class: "wb-side wb-r"}, pn.d, pn.p, railR);
    const barL = h("div", {class: "wb-bar wb-bar-l", role: "separator", "aria-orientation": "vertical", title: t("super.wb.bar")});
    const barR = h("div", {class: "wb-bar wb-bar-r", role: "separator", "aria-orientation": "vertical", title: t("super.wb.bar")});
    const bridge = h("div", {class: "wb-bridge", "aria-label": t("super.wb.bridge")});
    if (panels2.bridge) bridge.append(panels2.bridge);
    const center = h("div", {class: "wb-center"}, bridge);
    const scene = h("section", {class: "wb-scene", "aria-label": t("super.wb.scene.label")}, panels2.scene);
    const dock = h("nav", {class: "wb-dock", "aria-label": t("super.wb.dock")}, PANELS.map((key) => docks[key]));
    const main = h("div", {class: "wb-main"}, left, barL, center, barR, right, scene, dock);

    // The card of Focus: one waiting item, the first of the queue. It holds the queue node itself; the others are hidden by CSS.
    const ofEl = h("span", {class: "wb-of"});
    const laterBtn = h("button", {type: "button", class: "wb-later", title: t("super.wb.card.later.tip")}, t("super.wb.card.later"));
    const minBtn = h("button", {type: "button", class: "wb-min", title: t("super.wb.card.min"), "aria-label": t("super.wb.card.min")}, "—");
    const cardBody = h("div", {class: "wb-cb"});
    const card = h("div", {class: "wb-card", role: "region", "aria-label": t("super.wb.card.label")}, h("div", {class: "wb-ch"}, ofEl, h("span", {class: "wb-sp"}), laterBtn, minBtn), cardBody);
    const bell = h("button", {type: "button", class: "wb-bell"});
    const cardBox = h("div", {class: "wb-cardbox", hidden: ""}, card, bell);
    const pop = h("div", {class: "wb-pop", role: "dialog", "aria-label": t("super.wb.batt.head"), hidden: ""});
    root.append(top, main, cardBox, pop);

    // The small lit pill on the normal board that brings the deck back after a minimize (only after one in this page load).
    const orbWait = h("span", {class: "wb-orb-w", hidden: ""});
    const orb = h("button", {type: "button", class: "wb-orb", hidden: "", title: t("super.wb.orb")}, h("span", {class: "wb-bot", "aria-hidden": "true"}), h("b", null, t("super.name")), orbWait);
    orb.addEventListener("click", () => { if (options.open) options.open(); });

    // ---- the battery ----
    let cost = null, fresh = null;  // cost: what super.js draws; fresh: the talk answer asked for the popover (replaces it until super.js draws again)
    function readCost() {
      const mark = sv.querySelector(".sa-cost .sa-cell");
      if (!mark || !mark.firstElementChild) return null;
      const left = parseFloat(mark.firstElementChild.style.width);
      return {left: isFinite(left) ? clamp(left / 100, 0, 1) : 0, full: mark.classList.contains("full"), tip: mark.getAttribute("title") || "", label: mark.getAttribute("aria-label") || ""};
    }
    function drawBatt() {
      const now = fresh || cost;
      batt.hidden = !now;
      if (!now) return;
      cell.className = "wb-cell" + (now.full ? " full" : now.left < .2 ? " low" : now.left < .5 ? " mid" : "");
      cellBar.style.width = Math.round(now.left * 100) + "%";
      pct.textContent = Math.round(now.left * 100) + "%";
      batt.title = now.tip || now.label || "";
      batt.setAttribute("aria-label", now.label || now.tip || "");
    }
    function costChanged() { cost = readCost(); fresh = null; drawBatt(); if (!pop.hidden) drawPop(); }
    let talk = null;  // the last talk answer (spent, limit, base, extra)
    const credits = (answer) => {
      const limit = Number(answer.limit) || 0, spent = Number(answer.spent) || 0;
      if (!limit) return null;
      const left = Math.max(0, limit - spent), numbers = {spent: amount(spent), limit: amount(limit), left: amount(left)};
      return {left: left / limit, full: left <= 0, tip: t("super.cost.tip", numbers), label: t("super.cost.label", numbers), numbers};
    };
    function readTalk() {  // one request, only when the popover opens or after a recharge (never on a timer)
      return SERVE.call("/api/super/talk", {}, 30).then((answer) => {
        if (!answer || typeof answer !== "object") return;
        talk = answer;
        fresh = credits(answer);
        drawBatt();
        drawPop();
      }, () => { /* the numbers of super.js stay */ });
    }
    let popError = "", popBusy = false;
    function drawPop() {
      if (pop.hidden) return;
      const now = fresh || cost;
      const info = talk && credits(talk);
      const extra = talk ? Math.floor(Number(talk.extra) || 0) : 0;
      const line = info ? t("super.wb.batt.left", {left: info.numbers.left, limit: info.numbers.limit}) : now ? now.label : "";
      const buttons = RECHARGE.map((n, at) => {
        const one = h("button", {type: "button", class: "wb-rc" + (at === 0 ? " pri" : ""), disabled: popBusy || extra + n > RECHARGE_MAX ? "" : null}, t(at === 0 ? "super.wb.batt.recharge" : "super.wb.batt.plus", {n}));
        one.addEventListener("click", () => recharge(n));
        return one;
      });
      pop.replaceChildren(...[h("h5", null, t("super.wb.batt.head")), h("div", {class: "wb-pl"}, line), extra > 0 ? h("div", {class: "wb-pa"}, t("super.wb.batt.added", {n: extra})) : null,
        h("div", {class: "wb-prow"}, ...buttons), h("div", {class: "wb-pnote"}, t("super.wb.batt.today")), popError ? h("div", {class: "wb-perr", role: "alert"}, popError) : null].filter(Boolean));
    }
    function recharge(amountNow) {
      popError = "";
      popBusy = true;
      drawPop();
      SERVE.post("/api/super/recharge", {amount: amountNow}).then((answer) => { popBusy = false; if (answer && answer.ok === false) popError = String(answer.reason || ""); return readTalk(); }, (error) => { popBusy = false; popError = String((error && error.message) || error || ""); drawPop(); });
    }
    function placePop() {
      const at = batt.getBoundingClientRect();
      pop.style.left = clamp(at.left, 8, Math.max(8, innerWidth - 320)) + "px";
      pop.style.top = at.bottom + 8 + "px";
    }
    const popOutside = (event) => { if (!pop.hidden && !pop.contains(event.target) && !batt.contains(event.target)) closePop(); };
    const popKey = (event) => { if (event.key === "Escape" && !pop.hidden) { event.preventDefault(); event.stopPropagation(); closePop(); batt.focus(); } };
    function closePop() {
      pop.hidden = true;
      batt.setAttribute("aria-expanded", "false");
      removeEventListener("pointerdown", popOutside, true);
      removeEventListener("keydown", popKey, true);
    }
    function openPop() {
      popError = "";
      pop.hidden = false;
      batt.setAttribute("aria-expanded", "true");
      drawPop();
      placePop();
      addEventListener("pointerdown", popOutside, true);
      addEventListener("keydown", popKey, true);
      readTalk();
    }
    batt.addEventListener("click", () => { if (pop.hidden) openPop(); else closePop(); });

    // ---- the queue: items, the current one ----
    const items = () => (queueList ? [...queueList.children].filter((node) => node.classList.contains("item") && !node.hidden) : []);
    function ordered() {  // the card's order: what was not put "Later" first (the order of the queue), then the later ones in the order they were put
      const list = items(), ids = new Set(list.map((node) => node.dataset.id));
      for (const id of [...later.keys()]) if (!ids.has(id)) later.delete(id);
      return list.map((node, index) => ({node, index, no: later.get(node.dataset.id) || 0})).sort((a, b) => a.no - b.no || a.index - b.index).map((one) => one.node);
    }
    function drawQueue() {
      if (!queueList) return;
      const list = items(), line = ordered(), count = list.length, now = line[0] || null;
      const nowId = now ? now.dataset.id : "";
      panels2.decorate(queueList);  // the task of each item: its avatar and name at the top
      const sig = mode + "|" + count + "|" + line.map((node) => node.dataset.id).join(",");
      for (const node of queueList.children) node.classList.toggle("wb-cur", mode === "focus" && node === now);
      queueEmpty.hidden = count > 0;
      queueTotal.textContent = count ? String(count) : "";
      for (const badge of [queueCount, dockCount]) { badge.hidden = !count; badge.textContent = count; }
      const shownCard = mode === "focus" && count > 0;
      cardBox.hidden = !shownCard;
      cardBox.classList.toggle("wb-many", count > 1);
      ofEl.textContent = now ? t("super.wb.card.of", {n: list.indexOf(now) + 1, total: count}) : "";
      laterBtn.disabled = count < 2;
      bell.textContent = "☰ " + t("super.wb.card.bell", {n: count});
      const away = cardMin || (tall && taskOn);
      cardBox.classList.toggle("wb-min", away);
      if (sig === cardSig) return;
      const turned = shownCard && cardId && nowId !== cardId && !still();  // another item is the current one: the card slides in
      cardSig = sig;
      cardId = shownCard ? nowId : "";
      if (turned) { card.classList.remove("wb-in"); void card.offsetWidth; card.classList.add("wb-in"); }
    }
    laterBtn.addEventListener("click", () => {
      const now = ordered()[0];
      if (now && items().length > 1) { later.set(now.dataset.id, ++laterNo); drawQueue(); }
    });
    minBtn.addEventListener("click", () => { cardMin = true; drawQueue(); });
    bell.addEventListener("click", () => { cardMin = false; if (tall) { taskOn = false; layout(); } else drawQueue(); });
    card.addEventListener("animationend", () => card.classList.remove("wb-in"));

    // ---- the layout ----
    const wideNow = () => mode === "wb" && !tall;
    const railOf = (side) => wideNow() && SIDES[side].every((key) => fold[key]);
    // is the body of a panel on screen (the panel is drawn only then)
    const shown = (key) => (wideNow() ? !fold[key] && !railOf(sideOf(key)) : mode === "wb" && key !== "p" ? sheet === key : key === "p" && taskOn);
    function keep() { store.set("fold", JSON.stringify(fold)); }
    function sizes() {  // the dragged widths as CSS values on the layer; no value: the default of the style sheet
      for (const side of ["l", "r"]) {
        const bound = side === "r" ? Math.max(LIMITS.r[0], Math.min(LIMITS.r[1], innerWidth - 700)) : LIMITS.l[1];
        if (widths[side] === null) root.style.removeProperty("--wb-" + side + "wu");
        else root.style.setProperty("--wb-" + side + "wu", clamp(widths[side], LIMITS[side][0], bound) + "px");
      }
    }
    function layout() {
      tall = isTall();
      const wide = wideNow();
      root.classList.toggle("wb-tall", tall);
      root.classList.toggle("wb-m-wb", mode === "wb");
      root.classList.toggle("wb-m-focus", mode === "focus");
      root.classList.toggle("wb-rail-l", railOf("l"));
      root.classList.toggle("wb-rail-r", railOf("r"));
      const task = shown("p");
      root.classList.toggle("wb-task-on", task);
      for (const key of PANELS) {
        const on = shown(key);
        pn[key].hidden = wide ? railOf(sideOf(key)) : !on;
        const folded = wide && fold[key];
        pn[key].classList.toggle("wb-fold", folded);
        for (const button of pn[key].querySelectorAll(".wb-fold-btn")) {
          button.textContent = folded ? "▸" : "—";
          button.setAttribute("aria-expanded", folded ? "false" : "true");
          button.title = t(folded ? "super.wb.unfold" : "super.wb.fold");
          button.setAttribute("aria-label", button.title);
        }
        docks[key].classList.toggle("on", on);
        docks[key].setAttribute("aria-pressed", on ? "true" : "false");
      }
      pn.d.classList.toggle("wb-sized", shown("d") && task);
      focusBtn.classList.toggle("on", mode === "focus");
      focusBtn.setAttribute("aria-pressed", mode === "focus" ? "true" : "false");
      bridge.hidden = !panels2.bridge || mode === "focus";
      sizes();
      // the queue node: in its panel (the deck) or in the card (Focus); the card: at the bottom right, or in the chat above the input (Tall Focus)
      if (queueNode) { const target = mode === "wb" ? queueBody : cardBody; if (queueNode.parentNode !== target) target.append(queueNode); }
      const inChat = mode === "focus" && tall;
      if (inChat) { if (cardBox.parentNode !== sv) sv.insertBefore(cardBox, sv.querySelector(".sa-quick")); } else if (cardBox.parentNode !== root) root.append(cardBox);
      drawQueue();
      syncTask();
      paint();
    }
    function setMode(next) { if (mode === next) return; mode = next; store.set("mode", mode); cardSig = ""; layout(); }
    function foldPanel(key, value) {
      fold[key] = value;
      keep();
      layout();
      if (!value && key === "p") { const one = tabs.find((tab) => tab.name === active); if (one) wake(one.frame); }
    }
    function closePanel(key) {  // the Task layer of Focus and Tall, and the open panel of Tall
      if (key === "p") taskOn = false; else sheet = "";
      layout();
    }
    function toggle(key) {  // a button of the dock (Tall Workbench)
      if (key === "p") taskOn = !taskOn; else sheet = sheet === key ? "" : key;
      layout();
    }
    for (const key of PANELS) {
      docks[key].addEventListener("click", () => toggle(key));
      rails[key].addEventListener("click", () => foldPanel(key, false));  // a click on the rail opens the panel it stands for
    }
    focusBtn.addEventListener("click", () => setMode(mode === "focus" ? "wb" : "focus"));
    back.addEventListener("click", () => { minimized = true; closePop(); if (options.back) options.back(); });
    closeLayer.addEventListener("click", () => closePanel("p"));
    addEventListener("resize", () => { if (open && isTall() !== tall) layout(); else if (open) sizes(); });
    document.addEventListener("keydown", (event) => { if (open && event.key === "Escape" && !wideNow() && taskOn) { event.preventDefault(); closePanel("p"); } });
    right.addEventListener("click", (event) => { if (event.target === right && mode === "focus" && !tall && taskOn) closePanel("p"); });  // a click outside the window of Focus

    // The two bars that resize the sides: drag (pointer events, so a frame under the pointer does not take it), double click for the default; the widths are kept.
    function bar(node, side) {
      let at = false;
      node.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || railOf(side)) return;
        event.preventDefault();
        at = true;
        node.classList.add("drag");
        try { node.setPointerCapture(event.pointerId); } catch (error) { /* the move events still come */ }
      });
      node.addEventListener("pointermove", (event) => {
        if (!at) return;
        const box = main.getBoundingClientRect();
        widths[side] = Math.round(side === "l" ? event.clientX - box.left - 3 : box.right - event.clientX - 3);
        sizes();
      });
      const end = () => {
        if (!at) return;
        at = false;
        node.classList.remove("drag");
        store.set("widths", JSON.stringify(widths));
      };
      node.addEventListener("pointerup", end);
      node.addEventListener("pointercancel", end);
      node.addEventListener("dblclick", () => { widths[side] = null; store.set("widths", JSON.stringify(widths)); sizes(); });
    }
    bar(barL, "l");
    bar(barR, "r");

    // ---- the Task pane ----
    function syncTask() {
      const one = tabs.find((tab) => tab.name === active) || null;
      taskEmpty.hidden = tabs.length > 0;
      taskLbl.hidden = tabs.length > 0 && !(wideNow() && fold.p);
      out.hidden = !one;
      if (one) out.href = taskUrl(one.name);
      for (const tab of tabs) {
        const on = tab === one;
        const was = tab.frame.hidden;
        tab.frame.hidden = !on;
        if (on && was) wake(tab.frame);
        tab.tab.classList.toggle("on", on);
        tab.tab.firstChild.setAttribute("aria-selected", on ? "true" : "false");
      }
    }
    // A frame that was not shown asked nothing (common.js pollEvery): it looks again at once when it shows (1.8.24).
    function wake(frame) { setTimeout(() => { try { frame.contentDocument.dispatchEvent(new Event("visibilitychange")); } catch (error) { /* not loaded yet: it asks on its next round */ } }, 0); }
    function select(name) { active = name; syncTask(); }
    function dropTab(tab) {
      tab.frame.remove();
      tab.tab.remove();
      tabs = tabs.filter((one) => one !== tab);
      if (active === tab.name) active = tabs.length ? tabs[tabs.length - 1].name : "";
    }
    function openTask(name) {
      let tab = tabs.find((one) => one.name === name);
      if (!tab) {
        const frame = h("iframe", {class: "wb-frame", src: taskUrl(name) + "?embed=1", title: t("super.wb.task.frame", {name}), hidden: ""});
        const label = h("button", {type: "button", class: "wb-tab-n", role: "tab", title: name}, name);
        const x = h("button", {type: "button", class: "wb-tab-x", title: t("super.wb.task.tab.close"), "aria-label": t("super.wb.task.tab.close")}, "✕");
        const node = h("div", {class: "wb-tab"}, label, x);
        tab = {name, frame, tab: node};
        label.addEventListener("click", () => select(name));
        x.addEventListener("click", () => {
          dropTab(tab);
          if (!tabs.length && !wideNow()) { closePanel("p"); return; }
          layout();
        });
        tabs.push(tab);
        tabsEl.append(node);
        framesEl.append(frame);
        while (tabs.length > MAX_FRAMES) dropTab(tabs.find((one) => one.name !== name));
      }
      active = name;
      if (wideNow()) { fold.p = false; keep(); } else taskOn = true;
      layout();
    }
    root.addEventListener("click", (event) => {  // a link to a task page opens in the pane; a click with a modifier key and a middle click keep their way (a new browser tab)
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
      if (!link || link.hasAttribute("data-wb-out")) return;
      const name = taskOf(link.getAttribute("href"));
      if (!name) return;
      event.preventDefault();
      openTask(name);
    });

    // ---- open and close ----
    function paint() {  // the panels that are on screen are drawn (again only when what they show changed)
      if (!open) return;
      panels2.update({tree: shown("t"), data: shown("d"), scene: mode === "focus", bridge: mode === "wb", tall, down});
    }
    function update() {
      const count = SUPER.waiting(rowsOf());  // as the badge of the board's own header
      orbWait.hidden = !count;
      orbWait.textContent = t("super.wb.waits", {n: count});
      orb.title = t("board.mode.super.badge", {n: count});
      if (open) { paint(); panels2.decorate(queueList); }
    }
    let queued = false;
    const changed = () => { if (queued) return; queued = true; Promise.resolve().then(() => { queued = false; if (open) drawQueue(); }); };
    function show() {
      if (open) return;
      open = true;
      minimized = false;
      orb.hidden = true;
      home = {parent: sv.parentNode, next: sv.nextSibling};
      queueNode = sv.querySelector(".sa-queue");
      queueList = queueNode ? queueNode.querySelector(".sa-qlist") : null;
      if (queueNode) queueHome = {parent: queueNode.parentNode, next: queueNode.nextSibling};
      headHome = sv.querySelector(".sa-head");
      moved = headHome ? [...headHome.children].filter((node) => node.classList.contains("sa-pop")) : [];  // the history and the pop-out buttons
      tools.append(...moved);
      if (!root.parentNode) { document.body.append(root); panels2.bind(root); }
      center.append(sv);
      root.hidden = false;
      for (const tab of tabs) if (!tab.frame.hidden) wake(tab.frame);
      document.documentElement.classList.add("wb-lock");
      cardSig = "";
      layout();
      superView.show();
      panels2.start();
      panels2.intro(root);
      if (queueList) {
        observer = new MutationObserver(changed);
        observer.observe(queueList, {childList: true, attributes: true, attributeFilter: ["hidden"], subtree: true});
      }
      const costNode = sv.querySelector(".sa-cost");
      if (costNode) { costObserver = new MutationObserver(costChanged); costObserver.observe(costNode, {childList: true, subtree: true, attributes: true}); }
      costChanged();
      update();
      drawQueue();
    }
    function hide() {
      superView.hide();
      orb.hidden = !minimized;
      if (minimized && !orb.parentNode) document.body.append(orb);
      if (!open) return;
      open = false;
      closePop();
      panels2.stop();
      if (observer) { observer.disconnect(); observer = null; }
      if (costObserver) { costObserver.disconnect(); costObserver = null; }
      cardBox.remove();
      for (const node of queueList ? queueList.children : []) node.classList.remove("wb-cur");
      if (queueNode && queueHome) { if (queueHome.next && queueHome.next.parentNode === queueHome.parent) queueHome.parent.insertBefore(queueNode, queueHome.next); else queueHome.parent.append(queueNode); }
      if (headHome) headHome.append(...moved);
      moved = [];
      if (home && home.parent) { if (home.next && home.next.parentNode === home.parent) home.parent.insertBefore(sv, home.next); else home.parent.append(sv); }
      root.hidden = true;
      document.documentElement.classList.remove("wb-lock");
      queueNode = queueList = null;
    }
    // The link of VS Code: when it is down the edge of the deck turns red (the banner above the input is the one of super.js).
    function setVscode(status) {
      down = Boolean(status) && !status.ready;
      root.classList.toggle("wb-down", down);
      superView.setVscode(status);
      paint();
    }
    return {node: root, show, hide, update, setVscode, isOpen: () => open, openTask: (name) => { if (open) openTask(name); }};  // openTask: the pop-out's Open (the board shows the deck first)
  }

  return {create, taskOf, stillPet};
})();
