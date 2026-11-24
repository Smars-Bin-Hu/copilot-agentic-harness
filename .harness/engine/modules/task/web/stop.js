// The top right of every served page (1.8.17, the person's choice of two prototypes): one row, one height. The search pill stays as it is; next to it a pill with the
// Terminal toggle (moved in from term.js) and the avatar of the account menu (topmenu.js, 1.8.39), whose Stop board opens the card below; a page without the menu has the greeting and the stop button. The stop button is quiet grey, soft red on hover or while its window is open, and shown to a
// The stop is for a paired browser only. It opens a card (Cancel has the focus, so a stray Enter stops nothing); Stop board posts `/api/shutdown`; a card says it is stopping, or that it
// did not stop, with Try again. After the stop every timer, request and redraw ends and the page is one calm screen: the robot asleep, how to start it again.
"use strict";

const STOP = (function () {
  const NS = "http://www.w3.org/2000/svg";
  const PATHS = {power: ["M12 4v7", "M7.2 7.4a7 7 0 1 0 9.6 0"], warn: ["M12 6v7", "M12 17.4v.1"]};
  function icon(name) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    for (const d of PATHS[name]) {
      const part = document.createElementNS(NS, "path");
      part.setAttribute("d", d);
      svg.append(part);
    }
    return svg;
  }
  // The robot asleep (closed eyes, two z). Drawn from the tokens of the theme, so light and dark both hold.
  function robot() {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 96 112");
    svg.setAttribute("class", "sd-robot");
    svg.setAttribute("aria-hidden", "true");
    const add = (tag, attrs) => { const node = document.createElementNS(NS, tag); for (const key of Object.keys(attrs)) node.setAttribute(key, attrs[key]); svg.append(node); return node; };
    add("ellipse", {cx: 48, cy: 104, rx: 26, ry: 4, fill: "var(--robot-shadow)"});
    add("path", {d: "M48 22V12", stroke: "var(--robot-line)", "stroke-width": 2, "stroke-linecap": "round"});
    add("circle", {cx: 48, cy: 9, r: 3.4, fill: "var(--robot-feet)", stroke: "var(--robot-line)", "stroke-width": 1.5});
    add("rect", {x: 29, y: 64, width: 38, height: 30, rx: 12, fill: "var(--robot-body)", stroke: "var(--robot-line)", "stroke-width": 1.5});
    add("rect", {x: 33, y: 94, width: 11, height: 6, rx: 3, fill: "var(--robot-feet)", stroke: "var(--robot-line)", "stroke-width": 1.2});
    add("rect", {x: 52, y: 94, width: 11, height: 6, rx: 3, fill: "var(--robot-feet)", stroke: "var(--robot-line)", "stroke-width": 1.2});
    add("rect", {x: 20, y: 22, width: 56, height: 42, rx: 17, fill: "var(--robot-head)", stroke: "var(--robot-line)", "stroke-width": 1.5});
    add("rect", {x: 27, y: 31, width: 42, height: 24, rx: 12, fill: "var(--robot-visor)"});
    add("path", {d: "M35 44q5 4.4 10 0", fill: "none", stroke: "var(--soft)", "stroke-width": 1.8, "stroke-linecap": "round"});
    add("path", {d: "M51 44q5 4.4 10 0", fill: "none", stroke: "var(--soft)", "stroke-width": 1.8, "stroke-linecap": "round"});
    add("text", {x: 80, y: 22, "font-size": 11, "font-weight": 700, fill: "var(--soft)", opacity: ".8"}).textContent = "z";
    add("text", {x: 87, y: 12, "font-size": 8, "font-weight": 700, fill: "var(--soft)", opacity: ".55"}).textContent = "z";
    return svg;
  }

  // After the stop nothing may ask the server again: the timers and the redraws end, a request that is still made never comes back, and the page is one calm screen.
  function stopped() {
    window.fetch = () => new Promise(() => {});
    window.requestAnimationFrame = () => 0;
    for (let id = window.setTimeout(() => {}, 0); id > 0; id--) { window.clearTimeout(id); window.clearInterval(id); }
    document.querySelectorAll('meta[http-equiv="refresh"]').forEach((node) => node.remove());
    const theme = document.documentElement.getAttribute("data-theme");
    document.documentElement.className = "";  // the Enter screen hides `main` with a class of the page
    if (theme) document.documentElement.setAttribute("data-theme", theme);
    document.body.className = "board-stopped-page";
    const chip = h("span", {class: "sd-chip"}, icon("power"), "Start Harness");
    document.body.replaceChildren(h("div", {class: "board-stopped", role: "status"}, robot(), h("h1", null, t("board.stop.done.title")), h("p", null, t("board.stop.done.sub")),
      h("div", {class: "sd-start"}, h("span", null, t("board.stop.done.lead")), chip), h("p", {class: "sd-fine"}, t("board.stop.done.fine"))));
  }

  // The card: confirm, stopping, failed. One at a time, over a scrim; Esc and a click on the scrim close it except while stopping; Tab stays inside.
  function card(button) {
    const before = document.activeElement;
    const scrim = h("div", {class: "sd-scrim"});
    let state = "";
    const close = () => {
      document.removeEventListener("keydown", onKey, true);
      scrim.remove();
      document.body.classList.remove("has-dialog");
      button.setAttribute("aria-expanded", "false");
      delete button.dataset.busy;
      (before && before.isConnected ? before : button).focus({preventScroll: true});
    };
    const show = (next, error) => {
      state = next;
      button.setAttribute("aria-expanded", "true");
      if (next === "stopping") button.dataset.busy = "1"; else delete button.dataset.busy;
      const title = h("h3", {id: "sd-t"}, t(next === "confirm" ? "board.stop.title" : next === "stopping" ? "board.stop.stopping" : "board.stop.fail.title"));
      const said = h("p", {id: "sd-d"}, t(next === "confirm" ? "board.stop.conseq" : next === "stopping" ? "board.stop.stopping.sub" : "board.stop.fail.sub"));
      const mark = next === "stopping" ? h("span", {class: "sd-spin", "aria-hidden": "true"}) : icon(next === "failed" ? "warn" : "power");
      const body = [title, said];
      if (next === "stopping") body.push(h("div", {class: "sd-bar", "aria-hidden": "true"}, h("i")));
      if (next === "failed") body.push(h("code", {class: "sd-err"}, error || ""));
      let actions = null;
      if (next !== "stopping") {
        const back = h("button", {type: "button", class: "sd-btn"}, t(next === "confirm" ? "board.stop.cancel" : "board.stop.close"));
        const go = h("button", {type: "button", class: "sd-btn danger"}, t(next === "confirm" ? "board.stop.go" : "board.stop.again"));
        back.addEventListener("click", close);
        go.addEventListener("click", run);
        actions = h("div", {class: "sd-act"}, back, go);
      }
      const box = h("div", {class: "sd-dlg" + (next === "failed" ? " fail" : ""), role: "alertdialog", "aria-modal": "true", "aria-labelledby": "sd-t", "aria-describedby": "sd-d", "aria-busy": next === "stopping" ? "true" : null, tabindex: "-1"},
        h("div", {class: "sd-top"}, h("span", {class: "sd-ic"}, mark), h("div", null, body)), actions);
      scrim.replaceChildren(box);
      const first = box.querySelector(".sd-btn");
      (first || box).focus({preventScroll: true});
    };
    const run = () => {
      show("stopping");
      SERVE.call("/api/shutdown", {}, 10).then(() => { close(); stopped(); }, (error) => show("failed", error.message || String(error)));
    };
    const onKey = (event) => {
      if (!scrim.isConnected) return;
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); if (state !== "stopping") close(); return; }
      if (event.key === "Tab") {
        const items = [...scrim.querySelectorAll("button")];
        if (!items.length) { event.preventDefault(); return; }
        const at = items.indexOf(document.activeElement);
        if (event.shiftKey && at <= 0) { event.preventDefault(); items[items.length - 1].focus(); }
        else if (!event.shiftKey && (at === items.length - 1 || at < 0)) { event.preventDefault(); items[0].focus(); }
      }
    };
    scrim.addEventListener("click", (event) => { if (event.target === scrim && state !== "stopping") close(); });
    document.addEventListener("keydown", onKey, true);
    document.body.append(scrim);
    document.body.classList.add("has-dialog");
    show("confirm");
  }

  function mount() {
    if (typeof SERVE === "undefined") return;
    const name = typeof DATA !== "undefined" && DATA && DATA.serve && typeof DATA.serve.user === "string" ? DATA.serve.user.trim() : "";
    const toggle = document.querySelector(".term-toggle");  // term.js made it: it moves into the pill
    // (1.8.39) The pill: the Terminal toggle and the avatar of the account menu (topmenu.js), which holds the greeting, Settings and Stop board. A page without the menu keeps the greeting and the stop button.
    const menu = typeof TOPMENU !== "undefined" && typeof ACCT !== "undefined";
    const button = menu ? TOPMENU.avatar(name) : h("button", {type: "button", class: "hd-ib hd-stop", "aria-label": t("board.stop.tip"), "aria-haspopup": "dialog", "aria-expanded": "false", hidden: ""}, icon("power"), h("span", {class: "hd-tip", role: "tooltip"}, t("board.stop.tip")));
    if (!menu) button.addEventListener("click", () => { if (button.getAttribute("aria-expanded") !== "true") card(button); });
    const parts = [];
    if (name && !menu) parts.push(h("span", {class: "hd-hi", title: t("board.enter.hi") + name}, t("board.enter.hi"), h("b", null, name)));
    if (toggle) parts.push(parts.length ? h("i", {class: "hd-sep"}) : null, toggle);
    const sepStop = h("i", {class: "hd-sep", hidden: ""});
    if (menu) sepStop.hidden = !toggle;
    parts.push(sepStop, button);
    const pill = h("div", {class: "hd-acct" + (name && !menu ? " named" : "") + (menu ? " menu" : "")}, parts);
    if (!name && !toggle && !menu) pill.hidden = true;
    if (menu) TOPMENU.mount(button, {name, stop: (anchor) => { if (!document.querySelector(".sd-scrim")) card(anchor); }});
    document.body.append(pill);
    const root = document.documentElement;
    root.classList.add("has-hd");
    if (name) root.classList.add("hd-named");  // the Enter screen's own greeting steps back: it is in the pill
    // 1.8.25: the gutter of shell.css is wide enough for the search pill alone; with this pill beside it the right end of the page header (the mode tabs, + New task, the task page's
    // tools) ran under both. A header whose top is under the pills gets right padding up to the left edge of the leftmost pill, plus a gap; its own padding (the wall, a narrow
    // window) is read with the inline one taken off, and wins when it is larger. Padding changes the height of a header, never its top: no loop.
    const clear = () => {
      const pills = [document.querySelector(".sh-pill"), pill].filter((node) => node && !node.hidden && node.offsetWidth).map((node) => node.getBoundingClientRect());
      for (const head of document.querySelectorAll(".lb-top,.tk-head")) {
        head.style.paddingRight = "";
        const own = parseFloat(getComputedStyle(head).paddingRight) || 0, box = head.getBoundingClientRect();
        const near = pills.filter((rect) => rect.bottom > box.top);
        const need = near.length ? Math.ceil(box.right - Math.min(...near.map((rect) => rect.left)) + 10) : 0;
        if (need > own) head.style.paddingRight = need + "px";
      }
    };
    let queued = false;
    const later = () => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; clear(); }); } };
    const place = () => { root.style.setProperty("--hd-right", (pill.hidden ? 16 : pill.offsetWidth + 16 + 8) + "px"); later(); };
    place();
    if (window.ResizeObserver) { const watch = new ResizeObserver(place); watch.observe(pill); watch.observe(document.body); }  // the body: a header drawn later, a window of another width
    SERVE.ready.then(() => SERVE.call("/api/status", {}, 8)).then((data) => {
      if (menu) TOPMENU.setPaired(data.paired);
      else {
        button.hidden = !data.paired;
        sepStop.hidden = !data.paired || !(name || toggle);
      }
      if (data.paired) pill.hidden = false;
      place();
    }, () => {});
  }
  return {mount, stopped};
})();
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", STOP.mount); else STOP.mount();
