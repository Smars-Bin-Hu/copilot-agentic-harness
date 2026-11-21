// The super agent workbench (1.8.x): a full-screen layer that takes the place of the narrow super agent view while the board is in its "super" mode.
// It does not draw the chat or the queue. It MOVES the nodes of super.js into its own places (never a clone: their listeners and their data stay) and puts them back when it closes:
//   - the `.sa` section (the chat, the avatars, the pet, the input) goes into the middle column;
//   - the `.sa-queue` node (the cards that wait for the person) goes into the left Queue panel (Workbench) or into one card at the bottom right (Focus: the first item only).
// Two views, picked in the top bar: Workbench (the chat in the middle, four panels that open and close: left Queue and Agents, right Data and Task) and Focus (the chat and a picture;
// what waits comes as one card at a time). A window taller than wide uses the Tall layout: nothing covers anything, everything stacks downward.
// A link to a task page inside the layer opens that task in the Task pane (a tab with an iframe of `/task/<name>?embed=1`; a loaded frame is hidden, never destroyed, so a tab switch is instant).
// The tree of running agents, the Data panel, the picture of Focus, the hover card of a task and the task line of a queue item are drawn by wbpanels.js from the rows of the board; this file only gives them their places and says which are on screen.
// Needs common.js, super.js (SUPER.waiting) and wbpanels.js; board.js calls `WORKBENCH.create`.
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
  const taskUrl = (name) => "/task/" + encodeURIComponent(name);
  function taskOf(href) {  // the task a link opens, if it is a link to a task page
    const found = /^\/task\/([^/?#]+)(?:[?#].*)?$/.exec(String(href || ""));
    if (!found) return "";
    try { return decodeURIComponent(found[1]); } catch (error) { return ""; }
  }
  const PANELS = ["q", "t", "d", "p"];  // Queue, Agents (left); Data, Task (right)

  function create(options) {
    const superView = options.superView;
    const sv = superView.node;
    const rowsOf = options.rows || (() => []);
    const panels2 = WBPANELS.create({rows: rowsOf});  // the drawing of the panels
    let mode = store.get("mode", "wb") === "focus" ? "focus" : "wb";
    let panels = {q: true, t: true, d: true, p: true};
    try { const saved = JSON.parse(store.get("panels", "{}")); for (const key of PANELS) if (typeof saved[key] === "boolean") panels[key] = saved[key]; } catch (error) { /* the default */ }
    let sheet = "";  // Tall Workbench: the one of Queue, Agents and Data that is open under the chat
    let taskOn = false;  // the Task layer where the panel is not a fixed one: the window of Focus, the layer of Tall (not kept)
    let cardMin = false;  // Focus: the card is put away (not kept)
    let open = false, tall = false;
    let home = null, queueHome = null, queueNode = null, queueList = null, observer = null;
    let tabs = [], active = "", cardSig = "", cardId = "";
    const later = new Map();  // task item id -> the number of the "Later" that moved it to the end
    let laterNo = 0;

    // ---- the places ----
    const root = h("div", {class: "wb-root", hidden: "", "aria-label": t("super.name")});
    const pn = {};
    const toggles = {}, docks = {};
    const waitEl = h("span", {class: "wb-w", hidden: ""});
    const back = h("button", {type: "button", class: "wb-back", title: t("super.wb.back"), "aria-label": t("super.wb.back")}, "←");
    const modeBtns = {};
    const MODE = {focus: "super.wb.mode.focus", wb: "super.wb.mode.wb"}, MODE_TIP = {focus: "super.wb.mode.focus.tip", wb: "super.wb.mode.wb.tip"};  // written out: a search for a key finds its place
    for (const name of ["focus", "wb"]) modeBtns[name] = h("button", {type: "button", title: t(MODE_TIP[name])}, t(MODE[name]));
    const ICON = {q: "☰", t: "⌥", d: "▤", p: "▭"};
    const LABEL = {q: "super.wb.panel.queue", t: "super.wb.panel.agents", d: "super.wb.panel.data", p: "super.wb.panel.task"};
    const queueCount = h("span", {class: "wb-cnt", hidden: ""});
    const dockCount = h("span", {class: "wb-cnt", hidden: ""});
    for (const key of PANELS) {
      toggles[key] = h("button", {type: "button", class: "wb-tg", title: t(LABEL[key]), "aria-pressed": "false"}, h("span", {class: "wb-ic", "aria-hidden": "true"}, ICON[key]), " ", t(LABEL[key]), key === "q" ? queueCount : null);
      docks[key] = h("button", {type: "button", class: "wb-dk", "aria-pressed": "false"}, h("span", {class: "wb-ic", "aria-hidden": "true"}, ICON[key]), t(LABEL[key]), key === "q" ? dockCount : null);
    }
    const top = h("header", {class: "wb-top"}, h("div", {class: "wb-id"}, back, h("span", {class: "wb-bot", "aria-hidden": "true"}), h("b", {class: "wb-name"}, t("super.name"))), waitEl,
      h("div", {class: "wb-seg", role: "group", "aria-label": t("super.wb.mode")}, modeBtns.focus, modeBtns.wb), h("span", {class: "wb-sp"}),
      h("span", {class: "wb-lbl wb-pt"}, t("super.wb.side.left")), h("div", {class: "wb-seg wb-pt", role: "group"}, toggles.q, toggles.t),
      h("span", {class: "wb-lbl wb-pt"}, t("super.wb.side.right")), h("div", {class: "wb-seg wb-pt", role: "group"}, toggles.d, toggles.p));

    function panel(key, headKey, count) {
      const close = h("button", {type: "button", class: "wb-x", title: t("super.wb.panel.close"), "aria-label": t("super.wb.panel.close")}, "✕");
      close.addEventListener("click", () => closePanel(key));
      const body = h("div", {class: "wb-pb"});
      pn[key] = h("section", {class: "wb-pn wb-pn-" + key, hidden: ""}, h("div", {class: "wb-ph"}, h("b", null, t(headKey)), count || null, close), body);
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
    const framesEl = h("div", {class: "wb-frames"});
    const taskEmpty = h("div", {class: "wb-soon wb-task-empty"}, t("super.wb.task.empty"));
    framesEl.append(taskEmpty);
    pn.p = h("section", {class: "wb-pn wb-pn-p", hidden: ""}, h("div", {class: "wb-tabbar"}, tabsEl, out, closeLayer), framesEl);

    const left = h("aside", {class: "wb-side wb-l"}, pn.q, pn.t);
    const right = h("aside", {class: "wb-side wb-r"}, pn.d, pn.p);
    const center = h("div", {class: "wb-center"});
    const scene = h("section", {class: "wb-scene"}, panels2.scene);
    const dock = h("nav", {class: "wb-dock", "aria-label": t("super.wb.dock")}, PANELS.map((key) => docks[key]));
    const main = h("div", {class: "wb-main"}, left, center, right, scene, dock);

    // The card of Focus: one waiting item, the first of the queue. It holds the queue node itself; the others are hidden by CSS.
    const ofEl = h("span", {class: "wb-of"});
    const laterBtn = h("button", {type: "button", class: "wb-later", title: t("super.wb.card.later.tip")}, t("super.wb.card.later"));
    const minBtn = h("button", {type: "button", class: "wb-min", title: t("super.wb.card.min"), "aria-label": t("super.wb.card.min")}, "—");
    const cardBody = h("div", {class: "wb-cb"});
    const card = h("div", {class: "wb-card", role: "region", "aria-label": t("super.wb.card.label")}, h("div", {class: "wb-ch"}, ofEl, h("span", {class: "wb-sp"}), laterBtn, minBtn), cardBody);
    const bell = h("button", {type: "button", class: "wb-bell"});
    const cardBox = h("div", {class: "wb-cardbox", hidden: ""}, card, bell);
    root.append(top, main, cardBox);

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
      const shown = mode === "focus" && count > 0;
      cardBox.hidden = !shown;
      cardBox.classList.toggle("wb-many", count > 1);
      ofEl.textContent = now ? t("super.wb.card.of", {n: list.indexOf(now) + 1, total: count}) : "";
      laterBtn.disabled = count < 2;
      bell.textContent = "☰ " + t("super.wb.card.bell", {n: count});
      const away = cardMin || (tall && taskOn);
      cardBox.classList.toggle("wb-min", away);
      if (sig === cardSig) return;
      const turned = shown && cardId && nowId !== cardId && !still();  // another item is the current one: the card slides in
      cardSig = sig;
      cardId = shown ? nowId : "";
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
    const visible = (key) => (mode === "wb" && !tall ? panels[key] : mode === "wb" && key !== "p" ? sheet === key : key === "p" && taskOn);
    function keepPanels() { store.set("panels", JSON.stringify(panels)); }
    function layout() {
      tall = isTall();
      const wide = mode === "wb" && !tall;
      const lw = panels.q || panels.t, rw = panels.d || panels.p;
      root.classList.toggle("wb-tall", tall);
      root.classList.toggle("wb-m-wb", mode === "wb");
      root.classList.toggle("wb-m-focus", mode === "focus");
      root.classList.toggle("wb-no-l", wide && !lw);
      root.classList.toggle("wb-no-r", wide && !rw);
      const task = visible("p");
      root.classList.toggle("wb-task-on", task);
      for (const key of PANELS) {
        pn[key].hidden = !visible(key);
        const on = key === "p" ? task : mode === "wb" && visible(key);
        toggles[key].classList.toggle("on", wide && on);
        toggles[key].setAttribute("aria-pressed", wide && on ? "true" : "false");
        docks[key].classList.toggle("on", on);
        docks[key].setAttribute("aria-pressed", on ? "true" : "false");
      }
      pn.d.classList.toggle("wb-sized", visible("d") && task);
      for (const name of Object.keys(modeBtns)) { modeBtns[name].classList.toggle("on", name === mode); modeBtns[name].setAttribute("aria-pressed", name === mode ? "true" : "false"); }
      // the queue node: in its panel (Workbench) or in the card (Focus); the card: at the bottom right, or in the chat above the input (Tall Focus)
      if (queueNode) { const target = mode === "wb" ? queueBody : cardBody; if (queueNode.parentNode !== target) target.append(queueNode); }
      const inChat = mode === "focus" && tall;
      if (inChat) { if (cardBox.parentNode !== sv) sv.insertBefore(cardBox, sv.querySelector(".sa-quick")); } else if (cardBox.parentNode !== root) root.append(cardBox);
      drawQueue();
      syncTask();
      paint();
      requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));  // super.js puts the pet back in its corner
    }
    function setMode(next) { if (mode === next) return; mode = next; store.set("mode", mode); cardSig = ""; layout(); }
    function closePanel(key) {
      if (key === "p") { if (mode === "wb" && !tall) { panels.p = false; keepPanels(); } else taskOn = false; } else if (mode === "wb" && !tall) { panels[key] = false; keepPanels(); } else sheet = "";
      layout();
    }
    function toggle(key) {  // a button of the top bar (wide Workbench) or of the dock (Tall Workbench)
      if (mode === "wb" && !tall) { panels[key] = !panels[key]; keepPanels(); } else if (key === "p") taskOn = !taskOn; else sheet = sheet === key ? "" : key;
      layout();
    }
    for (const key of PANELS) { toggles[key].addEventListener("click", () => toggle(key)); docks[key].addEventListener("click", () => toggle(key)); }
    for (const name of Object.keys(modeBtns)) modeBtns[name].addEventListener("click", () => setMode(name));
    back.addEventListener("click", () => { if (options.back) options.back(); });
    closeLayer.addEventListener("click", () => closePanel("p"));
    addEventListener("resize", () => { if (open && isTall() !== tall) layout(); });
    document.addEventListener("keydown", (event) => { if (open && event.key === "Escape" && !(mode === "wb" && !tall) && taskOn) { event.preventDefault(); closePanel("p"); } });
    right.addEventListener("click", (event) => { if (event.target === right && mode === "focus" && !tall && taskOn) closePanel("p"); });  // a click outside the window of Focus

    // ---- the Task pane ----
    function syncTask() {
      const one = tabs.find((tab) => tab.name === active) || null;
      taskEmpty.hidden = tabs.length > 0;
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
    // A frame that was not shown asked nothing (common.js pollEvery): it looks again at once when it shows (1.8.22).
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
          if (!tabs.length && !(mode === "wb" && !tall)) { closePanel("p"); return; }
          layout();
        });
        tabs.push(tab);
        tabsEl.append(node);
        framesEl.append(frame);
        while (tabs.length > MAX_FRAMES) dropTab(tabs.find((one) => one.name !== name));
      }
      active = name;
      if (mode === "wb" && !tall) { panels.p = true; keepPanels(); } else taskOn = true;
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
      panels2.update({tree: visible("t"), data: visible("d"), scene: mode === "focus", tall});
    }
    function update() {
      const count = SUPER.waiting(rowsOf().filter((row) => row.state !== "error" && row.state !== "broken"));  // as the head of the super view: a task in error is told as an error, not a wait
      waitEl.hidden = !count;
      waitEl.textContent = t("super.wb.waits", {n: count});
      waitEl.title = t("board.mode.super.badge", {n: count});
      if (open) { paint(); panels2.decorate(queueList); }
    }
    let queued = false;
    const changed = () => { if (queued) return; queued = true; Promise.resolve().then(() => { queued = false; if (open) drawQueue(); }); };
    function show() {
      if (open) return;
      open = true;
      home = {parent: sv.parentNode, next: sv.nextSibling};
      queueNode = sv.querySelector(".sa-queue");
      queueList = queueNode ? queueNode.querySelector(".sa-qlist") : null;
      if (queueNode) queueHome = {parent: queueNode.parentNode, next: queueNode.nextSibling};
      if (!root.parentNode) { document.body.append(root); panels2.bind(root); }
      center.append(sv);
      root.hidden = false;
      for (const tab of tabs) if (!tab.frame.hidden) wake(tab.frame);
      document.documentElement.classList.add("wb-lock");
      cardSig = "";
      layout();  // the columns first: the pet of super.js stands in the corner of the place it has
      superView.show();
      panels2.start();
      panels2.intro(root);
      if (queueList) {
        observer = new MutationObserver(changed);
        observer.observe(queueList, {childList: true, attributes: true, attributeFilter: ["hidden"], subtree: true});
      }
      update();
      drawQueue();
    }
    function hide() {
      superView.hide();
      if (!open) return;
      open = false;
      panels2.stop();
      if (observer) { observer.disconnect(); observer = null; }
      cardBox.remove();
      for (const node of queueList ? queueList.children : []) node.classList.remove("wb-cur");
      if (queueNode && queueHome) { if (queueHome.next && queueHome.next.parentNode === queueHome.parent) queueHome.parent.insertBefore(queueNode, queueHome.next); else queueHome.parent.append(queueNode); }
      if (home && home.parent) { if (home.next && home.next.parentNode === home.parent) home.parent.insertBefore(sv, home.next); else home.parent.append(sv); }
      root.hidden = true;
      document.documentElement.classList.remove("wb-lock");
      queueNode = queueList = null;
    }
    return {node: root, show, hide, update, isOpen: () => open};
  }

  return {create, taskOf};
})();
