// The task window of the served board (1.8.36): a click on a task in Lobby or List opens its page in a window over the board, not in place of it.
// One window, a tab per task (taskframes.js: a hidden tab keeps its page and asks nothing; past six loaded pages the one seen longest ago unloads).
// The bar: the tabs, Open in its own browser tab, Minimize (a strip at the bottom centre, one chip per tab), Maximize or Restore (a double click on the bar too), Close (every tab).
// It opens as a split (one side of the screen, the board on the other; see `layout`); ⧉ makes it a floating window: the bar drags it, the bottom right corner sizes it; a sheet over the page while dragging keeps the frames from taking the pointer. Narrower than 700 px it always fills the screen.
// Kept in localStorage: the tabs, the active one, split or float, the share of the split, the place and size, maximized. After a reload the window comes back minimized and loads nothing until it is shown.
// Filling the screen, it hides the board's fixed controls (the account pill, the gear, the dock) as the workbench does; they come back when it is smaller or minimized.
// Nothing is built before the first open or a restored strip: the board opens as fast as before. Under the super workbench (`html.wb-lock`) both stay hidden.
// Needs common.js (h, t) and taskframes.js; board.js calls TASKWIN.open(name) and TASKWIN.warm(name), and sets window.EMBED_HOST (desk.js asks it for a link inside a frame).
"use strict";

const TASKWIN = (function () {
  const KEY = "harness.board.taskwin";
  const MIN_W = 420, MIN_H = 260;
  let ui = null, frames = null;
  const state = {tabs: [], at: "", rect: null, max: false, min: false};
  const load = () => { try { Object.assign(state, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (error) { /* start empty */ } };
  const save = () => {
    if (frames) { state.tabs = frames.names(); state.at = frames.active(); }
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (error) { /* a convenience only */ }
  };
  const narrow = () => innerWidth < 700;
  // A window that fills the screen (maximized, or a narrow screen) hides the board's fixed controls, as the workbench does (taskwin.css `html.tw-full`): the account pill would cover its buttons.
  // Split (1.8.36, the default): the window takes one side of the screen and the board keeps the other (taskwin.css `html.tw-split`): the right half of a wide window,
  // the bottom half of a tall one. The divider sets the share (state.ratio, kept); the board keeps BOARD_MIN at least. ⧉ makes it a floating window, ◫ a split again (state.mode, kept).
  // `layout` sets the classes and the size after every change: the window shown, split or float, maximized, minimized, a resize of the browser window.
  const BOARD_MIN = 560, SPLIT_MIN = 360;  // narrower, the board's own blocks (laid out for the window, not for their side) fall apart
  function layout() {
    const root = document.documentElement;
    const shown = Boolean(ui && !ui.win.hidden);
    const tall = innerWidth < innerHeight;
    const room = tall ? innerHeight : innerWidth;
    const on = shown && state.mode !== "float" && !state.max && !narrow() && room >= BOARD_MIN + SPLIT_MIN;  // too little room for both: it floats this time (the choice stays split)
    const ratio = typeof state.ratio === "number" && state.ratio > 0 && state.ratio < 1 ? state.ratio : 0.5;
    root.style.setProperty("--tw-sp", Math.round(Math.max(SPLIT_MIN, Math.min(room - BOARD_MIN, room * ratio))) + "px");
    root.classList.toggle("tw-split", on);
    root.classList.toggle("tw-tall", tall);
    root.classList.toggle("tw-full", shown && (state.max || narrow()));
    if (!ui) return;
    ui.win.classList.toggle("split", on);
    ui.divider.hidden = !on;
    const float = state.mode === "float";
    ui.mode.textContent = float ? "\u25eb" : "\u29c9";
    ui.mode.title = t(float ? "board.win.split" : "board.win.float");
    ui.mode.setAttribute("aria-label", ui.mode.title);
  }
  const full = layout;
  const button = (cls, title, text) => h("button", {type: "button", class: "tw-b " + cls, title, "aria-label": title}, text);

  function defaultRect() {
    const w = Math.max(MIN_W, Math.min(1100, Math.round(innerWidth * 0.68)));
    return {x: Math.max(0, innerWidth - w - 76), y: 70, w, h: Math.max(MIN_H, innerHeight - 140)};  // clear of the dock's column at the right edge
  }
  function place() {  // the whole window stays on the screen: its buttons and its corner can always be reached
    const r = state.rect || defaultRect();
    r.w = Math.max(Math.min(MIN_W, innerWidth), Math.min(r.w, innerWidth));
    r.h = Math.max(Math.min(MIN_H, innerHeight), Math.min(r.h, innerHeight));
    r.x = Math.max(0, Math.min(innerWidth - r.w, r.x));
    r.y = Math.max(0, Math.min(innerHeight - r.h, r.y));
    state.rect = r;
    Object.assign(ui.win.style, {left: r.x + "px", top: r.y + "px", width: r.w + "px", height: r.h + "px"});
  }

  function build() {
    if (ui) return;
    const tabs = h("div", {class: "tw-tabs", role: "tablist"});
    const out = h("a", {class: "tw-b tw-out", href: "#", target: "_blank", rel: "noopener", title: t("board.win.out"), "aria-label": t("board.win.out")}, "\u2197");
    const min = button("tw-min-b", t("board.win.min"), "—");
    const max = button("tw-max-b", t("board.win.max"), "▢");
    const mode = button("tw-mode", t("board.win.float"), "\u29c9");
    const close = button("tw-close", t("board.win.close"), "✕");
    const bar = h("div", {class: "tw-bar"}, tabs, h("div", {class: "tw-btns"}, out, mode, min, max, close));
    const body = h("div", {class: "tw-body"});
    const grip = h("span", {class: "tw-grip", title: t("board.win.size")});
    const win = h("div", {class: "tw", role: "dialog", "aria-label": t("board.win.label"), hidden: ""}, bar, body, grip);
    const chips = h("div", {class: "tw-chips"});
    const up = button("tw-up", t("board.win.up"), "▴");
    const stripX = button("tw-close", t("board.win.close"), "✕");
    const strip = h("div", {class: "tw-strip", hidden: ""}, up, chips, stripX);
    const divider = h("div", {class: "tw-div", role: "separator", title: t("board.win.divider"), "aria-label": t("board.win.divider"), hidden: ""});
    ui = {win, bar, tabs, body, out, max, mode, divider, strip, chips};
    frames = TASKFRAMES.create({tabs, frames: body, prefix: "tw", title: (name) => t("super.wb.task.frame", {name}), changed, closed: () => { if (!frames.count()) closeAll(); else save(); }});
    min.addEventListener("click", minimize);
    mode.addEventListener("click", () => { state.mode = state.mode === "float" ? "split" : "float"; if (state.mode === "float") place(); layout(); save(); });
    divider.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      const tall = innerWidth < innerHeight, room = tall ? innerHeight : innerWidth;
      const start = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--tw-sp")) || room / 2;
      drag(event, (dx, dy) => { state.ratio = Math.max(0.05, Math.min(0.95, (start - (tall ? dy : dx)) / room)); layout(); }, true);
    });
    max.addEventListener("click", () => setMax(!state.max));
    up.addEventListener("click", () => show());
    close.addEventListener("click", closeAll);
    stripX.addEventListener("click", closeAll);
    bar.addEventListener("dblclick", (event) => { if (event.target === bar || event.target === tabs) setMax(!state.max); });
    bar.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || state.max || narrow() || ui.win.classList.contains("split") || event.target.closest(".tw-btns,.tw-tab-x")) return;  // a tab drags too: with many tabs the bar has no empty room
      const r = {...state.rect};
      drag(event, (dx, dy) => { state.rect = {...r, x: r.x + dx, y: r.y + dy}; place(); });
    });
    grip.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      const r = {...state.rect};
      drag(event, (dx, dy) => { state.rect = {...r, w: Math.min(r.w + dx, innerWidth - r.x), h: Math.min(r.h + dy, innerHeight - r.y)}; place(); }, true);  // the corner grows to the edge, it does not push the window
    });
    addEventListener("resize", () => { if (!ui.win.hidden) place(); full(); });
    document.body.append(win, divider, strip);
  }
  // A move of the pointer, from where it went down. The pointer is captured (a fast move over a frame still reaches this page) and a sheet covers the frames.
  // `now`: the corner grip starts at once; the bar waits for a few pixels, so a click on a tab stays a click (a capture at the press would take the click from the tab).
  function drag(event, move, now) {
    const sx = event.clientX, sy = event.clientY, id = event.pointerId, holder = event.target;
    let sheet = null;
    const start = () => {
      sheet = h("div", {class: "tw-sheet"});
      document.body.append(sheet);
      try { holder.setPointerCapture(id); } catch (error) { /* the sheet alone then */ }
    };
    const step = (ev) => {
      if (ev.pointerId !== id) return;
      const dx = ev.clientX - sx, dy = ev.clientY - sy;
      if (!sheet) { if (Math.abs(dx) + Math.abs(dy) < 4) return; start(); }
      move(dx, dy);
    };
    const end = (ev) => {
      if (ev && ev.pointerId !== undefined && ev.pointerId !== id) return;
      removeEventListener("pointermove", step);
      removeEventListener("pointerup", end);
      removeEventListener("pointercancel", end);
      holder.removeEventListener("lostpointercapture", end);
      if (sheet) { sheet.remove(); sheet = null; save(); }
    };
    addEventListener("pointermove", step);
    addEventListener("pointerup", end);
    addEventListener("pointercancel", end);
    holder.addEventListener("lostpointercapture", end);
    if (now) start();
  }

  function changed() {  // the tabs moved: the link out, the chips of the strip
    const at = frames.active();
    ui.out.href = at ? TASKFRAMES.url(at) : "#";
    ui.out.hidden = !at;
    ui.chips.textContent = "";
    for (const name of frames.names()) {
      const chip = h("button", {type: "button", class: "tw-chip" + (name === at ? " on" : ""), title: name}, h("span", null, name));
      chip.addEventListener("click", () => { frames.select(name); show(); });
      ui.chips.append(chip);
    }
    save();
  }
  function setMax(value) {
    state.max = Boolean(value);
    ui.win.classList.toggle("max", state.max);
    ui.max.textContent = state.max ? "❐" : "▢";
    ui.max.title = t(state.max ? "board.win.restore" : "board.win.max");
    ui.max.setAttribute("aria-label", ui.max.title);
    full();
    save();
  }
  function show() {
    build();
    state.min = false;
    place();
    setMax(state.max);
    ui.strip.hidden = true;
    ui.win.hidden = false;
    full();
    frames.setShown(true);
    save();
  }
  function minimize() {
    if (!ui || !frames.count()) return;
    state.min = true;
    ui.win.hidden = true;
    ui.strip.hidden = false;
    full();
    frames.setShown(false);
    save();
  }
  function closeAll() {
    if (!ui) return;
    frames.closeAll();
    ui.win.hidden = true;
    ui.strip.hidden = true;
    state.min = false;
    state.max = false;
    ui.win.classList.remove("max");
    full();
    save();
  }
  function open(name) {
    if (!name) return;
    build();
    frames.open(name);
    show();
  }
  // After a reload: the tabs come back on the strip; nothing loads until the window shows.
  function restore() {
    load();
    const names = Array.isArray(state.tabs) ? state.tabs.filter((name) => typeof name === "string" && name) : [];
    if (!names.length) return;
    build();
    frames.setShown(false);
    frames.restore(names, state.at);
    changed();
    state.min = true;
    ui.strip.hidden = false;
    save();
  }
  // A frame of this window asks (desk.js, embed): another task opens as a tab, the board minimizes the window. A frame of anything else is not ours.
  const owns = (frame) => Boolean(ui && frame && ui.body.contains(frame));
  const host = {
    task(name, frame) { if (!owns(frame)) return false; open(name); return true; },
    board(frame) { if (!owns(frame)) return false; minimize(); return true; },
  };

  return {open, warm: (name) => { if (name) { build(); frames.warm(name); } }, restore, minimize, host, isOpen: () => Boolean(ui && !ui.win.hidden)};
})();
