// The lobby: the first screen of the board. Every task that is not closed is a small robot on a floor, in the zone of what it
// is doing: at work, waiting for the person, left alone (no session holds it), resting. The robot's pose says the state, the thing in its hand says the kind of
// task. A mouse near it makes its eyes follow; over it, it hops and a card opens (1.6.14): the task, the status marks of the list (status.js), its numbers and its buttons. A click opens the page.
// Closed tasks that are not archived sit apart, on the dock under the floor (M38-1): a shelf they rest on in a row, eyes shut, cores
// glowing slowly as if charging; one comes in sliding along the shelf, and the mouse lifts one off it. Their eyes do not follow the mouse.
// Pure SVG and CSS (lobby.css), drawn with DOM nodes. Robots are kept between two draws, so a board that asks again every few
// seconds does not make them start over; only a robot whose state changed changes its pose.
"use strict";

const Lobby = (function () {
  const NS = "http://www.w3.org/2000/svg";
  const still = Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const svg = (name, attrs, ...kids) => {
    const node = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    for (const kid of kids.flat()) node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return node;
  };

  // pose -> zone. `tests`: waiting for the results of a test the person is to run.
  // `lost`: no session holds the task (a plug hangs loose).
  const ZONE_OF = {work: "work", you: "you", tests: "you", lost: "left", idle: "rest", pause: "rest"};
  const ZONES = [["you", "board.lobby.zone.you"], ["work", "board.lobby.zone.work"], ["left", "board.lobby.zone.left"], ["rest", "board.lobby.zone.rest"]];  // what waits for the person is on top

  // The state is the server's (`row.state`); the pose only draws it.
  function poseOf(row, live) {
    const state = stateOf(row, live);
    if (state === "paused") return "pause";
    if (state === "waiting") return row.waiting_why === "tests" ? "tests" : "you";
    if (state === "unheld") return "lost";
    return state === "working" ? "work" : "idle";
  }

  // What the robot holds, by the kind of task. Small drawings, drawn at the hand.
  function accessory(kind) {
    const group = svg("g", {class: "lb-acc"});
    const path = (d, cls) => group.append(svg("path", {d, class: cls || ""}));
    if (kind === "dev") { path("M-1 -4 L-1 -13 M-1 -13 a4 4 0 1 0 4 0 L3 -9"); path("M-1 -4 L3 -4"); }
    else if (kind === "rca") { group.append(svg("circle", {cx: 0, cy: -10, r: 4.5})); path("M3.4 -6.8 L7 -3"); }
    else if (kind === "design") { path("M-2 -2 L6 -10 L8 -8 L0 0 Z"); path("M-2 -2 L-3 1 L0 0"); }
    else if (kind === "test") { path("M-3 -14 L-3 -9 L-7 -2 L7 -2 L3 -9 L3 -14 Z"); path("M-5 -4 L5 -4 L7 -2 L-7 -2 Z", "lb-fill"); }
    else if (kind === "kb") { path("M-6 -13 L6 -13 L6 -2 L-6 -2 Z"); path("M0 -13 L0 -2"); }
    else if (kind === "qa") { path("M-7 -14 L7 -14 L7 -6 L1 -6 L-3 -2 L-3 -6 L-7 -6 Z"); }
    else { group.append(svg("circle", {cx: 0, cy: -8, r: 4})); path("M0 -14 L0 -12 M0 -4 L0 -2 M-6 -8 L-4 -8 M4 -8 L6 -8"); }
    return group;
  }

  function robot(pose, kind, delay) {
    const root = svg("svg", {viewBox: "0 0 100 130", class: "lb-bot lb-pose-" + pose, style: "--d:" + delay + "s", "aria-hidden": "true"});
    root.append(svg("g", {class: "lb-shadow"}, svg("ellipse", {cx: 50, cy: 123, rx: 22, ry: 4})));
    const body = svg("g", {class: "lb-floaty"});
    body.append(svg("rect", {class: "lb-feet", x: 36, y: 96, width: 10, height: 10, rx: 3}), svg("rect", {class: "lb-feet", x: 54, y: 96, width: 10, height: 10, rx: 3}));
    const left = svg("g", {class: "lb-arm lb-l"}, svg("rect", {x: 17, y: 62, width: 10, height: 26, rx: 5}));
    const right = svg("g", {class: "lb-arm lb-r"}, svg("rect", {x: 73, y: 62, width: 10, height: 26, rx: 5}));
    const held = accessory(kind);
    held.setAttribute("transform", "translate(78,92)");
    right.append(held);
    body.append(left, right, svg("rect", {class: "lb-body", x: 30, y: 56, width: 40, height: 42, rx: 13}), svg("circle", {class: "lb-core", cx: 50, cy: 77, r: 6}));
    const head = svg("g", {class: "lb-headg"});
    head.append(svg("line", {class: "lb-ant", x1: 50, y1: 16, x2: 50, y2: 7}), svg("circle", {class: "lb-bulb", cx: 50, cy: 6, r: 3.2}),
      svg("rect", {class: "lb-head", x: 24, y: 16, width: 52, height: 42, rx: 15}), svg("rect", {class: "lb-visor", x: 31, y: 26, width: 38, height: 22, rx: 9}),
      svg("g", {class: "lb-eyes"}, svg("circle", {class: "lb-eye", cx: 42, cy: 37, r: 4.2}), svg("circle", {class: "lb-eye", cx: 58, cy: 37, r: 4.2})));
    const mark = svg("text", {x: 80, y: 19, "text-anchor": "middle", "font-size": 15, "font-weight": 800, fill: "#1a1202"}, pose === "tests" ? "?" : "!");
    body.append(head, svg("g", {class: "lb-bubble"}, svg("circle", {cx: 80, cy: 14, r: 11, fill: "#f0a02e"}), svg("path", {d: "M72 21 L68 28 L77 24 Z", fill: "#f0a02e"}), mark),
      svg("text", {class: "lb-zz", x: 70, y: 22}, "z"), svg("text", {class: "lb-zz lb-b", x: 78, y: 12}, "Z"));
    body.append(svg("g", {class: "lb-cable"}, svg("path", {d: "M70 84 C84 86 88 98 80 110"}), svg("circle", {class: "lb-spark", cx: 80, cy: 112, r: 2.6})));
    root.append(body);
    root._mark = mark;
    return root;
  }

  // The health warning of a task (row.warn, from health.py; the list view shows the same): a small tag by the robot, the reason in its title.
  function warnMark(slot, row) {
    let node = slot.querySelector(".lb-warn");
    if (!row.warn || !row.warn.length) { if (node) node.remove(); return; }
    if (!node) { node = h("span", {class: "lb-warn", role: "img", "aria-label": t("board.warn.label")}, "\u26a0"); slot.append(node); }
    node.title = row.warn.map((item) => t("board.warn." + item.rule, {n: item.n})).join("\n");
  }

  // options: href(row) the page of a task; figures(row) its Time, Credits and prompts (the brief); actions(row) the strip of buttons of the list row, or null; live: the page is kept fresh.
  function create(options) {
    const slots = new Map();  // task name -> {slot, bot, row, pose, zone, label}
    const rowsOf = {};
    const zoneBox = {};
    const count = h("div", {class: "lb-sub"});
    const card = h("div", {class: "lb-card", role: "group"});
    document.body.append(card);  // outside the scene: the scene clips what leaves it, and the card must be able to go to any edge of the window
    let liveNow = Boolean(options.live);
    const empty = h("div", {class: "lb-empty"});
    const scene = h("div", {class: "lb-scene"});
    scene.append(h("h3", null, t("board.title")), count);
    for (const [id, label] of ZONES) {
      const row = h("div", {class: "lb-row"});
      const name = h("span", null);
      const dot = h("i", {class: "lb-dot lb-dot-" + id});
      rowsOf[id] = row;
      zoneBox[id] = {box: h("div", {class: "lb-zone"}, h("div", {class: "lb-label"}, dot, name), row), name, label};
      scene.append(zoneBox[id].box);
    }
    const docked = new Map();  // task name -> entry, for the closed tasks
    const shelf = h("div", {class: "lb-shelf"});
    const dockName = h("span", null);
    const dock = h("div", {class: "lb-dock"}, h("div", {class: "lb-label"}, h("i", {class: "lb-dot lb-dot-closed"}), dockName), shelf);
    scene.append(empty, dock);

    function dockUpdate(rows) {
      const closed = rows.filter((row) => row.status === "closed");
      const names = new Set(closed.map((row) => row.name));
      for (const [name, entry] of docked) if (!names.has(name)) { entry.slot.remove(); docked.delete(name); }
      closed.forEach((row, index) => {
        let entry = docked.get(row.name);
        if (!entry) {
          const bot = robot("closed", row.kind, ((index * 0.61) % 4).toFixed(2));
          const slot = h("div", {class: "lb-slot lb-docked", tabindex: "0", role: "link", "aria-label": row.name}, bot, h("div", {class: "lb-nm", title: row.name}, row.name));
          entry = {slot, bot, row, pose: "closed", zone: "dock"};
          wire(entry);
          docked.set(row.name, entry);
          if (ready && !still && slot.animate) slot.animate([{opacity: 0, transform: "translateX(60px)"}, {opacity: 1, transform: "none"}], {duration: 900, easing: "cubic-bezier(.2,.8,.2,1)"});
        }
        entry.row = row;
        shelf.append(entry.slot);  // in the order of the rows: the newest closed first
      });
      dock.hidden = !closed.length;
      dockName.textContent = t("board.lobby.zone.closed") + " \u00b7 " + closed.length;
    }

    // --- the card of a robot (1.6.14) ------------------------------------------------------------------------------------
    // Built once, filled in place: the parts below are drawn again only when what they show changed, so the poll (3 s) neither closes the card nor restarts a clock or an
    // animation in it, nor takes a button from under the pointer. It is in the body and placed with `Status.place` (above the robot if there is room, else below, always inside the window).
    const parts = {};
    for (const name of ["head", "state", "marks", "stats", "acts"]) { parts[name] = {node: h("div", {class: "lb-" + name}), sig: null}; card.append(parts[name].node); }
    let marks = null, current = null, hideTimer = 0, frame = 0;
    const touchy = () => Boolean(window.matchMedia && window.matchMedia("(hover: none), (max-width: 700px)").matches);  // no hover: the card opens on a click

    function put(name, sig, make) {
      const part = parts[name];
      if (part.sig === sig) return;
      part.sig = sig;
      const kids = make();
      part.node.replaceChildren(...(kids ? [kids].flat().filter(Boolean) : []));
      part.node.hidden = !part.node.firstChild;
    }

    function fill(entry) {
      const row = entry.row, href = options.href(row);
      const served = typeof SERVE !== "undefined" && DATA.serve;
      card.setAttribute("aria-label", t("board.status.card.label", {name: row.name}));
      put("head", JSON.stringify([row.name, row.kind, row.status, href, served && row.status === "open" ? row.chat || null : null]), () => [
        kindIcon(row.kind || "other", row.status === "new" ? t("task.kind.none") : t("task.kind." + (row.kind || "none"))),
        href ? h("a", {class: "lb-name", href, title: row.name}, row.name) : h("span", {class: "lb-name", title: row.name}, row.name),
        served && row.status === "open" ? SERVE.vsButton(row.chat) : null]);
      put("state", JSON.stringify([stateOf(row, liveNow), row.waiting, row.waiting_why, row.unheld_s, row.warn || []]), () => {
        const tag = stateTag(row, liveNow);
        const warn = row.warn && row.warn.length ? h("span", {class: "tag warn", title: row.warn.map((item) => t("board.warn." + item.rule, {n: item.n})).join("\n"), "aria-label": t("board.warn.label")}, "⚠") : null;
        return [/\b(run|hot)\b/.test(tag.className) ? Status.phase(tag) : tag, warn];
      });
      if (!marks) { marks = Status.row(row, {live: liveNow, wrap: true}); parts.marks.node.append(marks); } else marks.update(row, liveNow);
      const figures = options.figures(row);
      put("stats", JSON.stringify(figures ? [figures.active_s, figures.aiu, figures.prompts] : null), () => {
        if (!figures) return null;
        const stat = (label, value) => (value === null || value === undefined ? null : h("div", {class: "lb-stat"}, h("span", null, label), h("b", {title: String(value)}, value)));
        return [stat(t("board.col.time"), figures.active_s === null || figures.active_s === undefined ? null : clock(figures.active_s)), stat(t("board.col.credits"), figures.aiu === null || figures.aiu === undefined ? null : amount(figures.aiu)),
          stat(t("board.col.prompts"), figures.prompts)];
      });
      put("acts", JSON.stringify([row.actions || [], row.state, row.waiting_why, row.waiting, row.paused_since || ""]), () => options.actions(row));
    }

    function position() {
      frame = 0;
      if (!current || !card.classList.contains("on")) return;
      if (!current.slot.isConnected || scene.offsetParent === null) { hide(); return; }
      Status.place(card, current.slot, false);
    }
    const again = () => { if (!frame && current) frame = requestAnimationFrame(position); };
    window.addEventListener("scroll", again, {passive: true});
    window.addEventListener("resize", again);

    function show(entry) {
      clearTimeout(hideTimer);
      current = entry;
      fill(entry);
      card.classList.add("on");
      position();
    }
    function hide() { clearTimeout(hideTimer); card.classList.remove("on"); current = null; }
    // A little time to cross from the robot to its card. Not while the pointer is on the card, nor while the keyboard is in it.
    const later = () => {
      clearTimeout(hideTimer);
      hideTimer = setTimeout(() => { if (!card.matches(":hover") && !card.querySelector(":focus-visible")) hide(); }, 220);
    };
    card.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    card.addEventListener("mouseleave", later);
    card.addEventListener("focusin", () => clearTimeout(hideTimer));
    card.addEventListener("focusout", later);

    const slotsInOrder = () => Array.from(scene.querySelectorAll(".lb-slot"));
    const focusable = () => Array.from(card.querySelectorAll("a[href],button:not([disabled]),[tabindex='0']")).filter((node) => node.offsetParent !== null);
    // The keyboard: Esc closes the card and goes back to the robot; Tab on a robot with its card open goes into the card, and Tab at the end of the card goes on to the next robot.
    card.addEventListener("keydown", (event) => {
      if (event.key !== "Tab" || !current) return;
      const items = focusable(), at = items.indexOf(document.activeElement);
      if (event.shiftKey && at <= 0) { event.preventDefault(); current.slot.focus(); }
      else if (!event.shiftKey && at === items.length - 1) {
        event.preventDefault();
        const order = slotsInOrder(), next = order[order.indexOf(current.slot) + 1];
        hide();
        (next || current.slot).focus();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !card.classList.contains("on")) return;
      const inside = card.contains(document.activeElement), slot = current && current.slot;
      hide();
      if (inside && slot) slot.focus();
    });
    document.addEventListener("click", (event) => {  // a tap outside (touch, narrow window) closes it
      if (card.classList.contains("on") && !card.contains(event.target) && !(current && current.slot.contains(event.target))) hide();
    });

    function wire(entry) {
      const slot = entry.slot;
      const go = () => { const href = options.href(entry.row); if (href) window.location.href = href; };
      slot.addEventListener("mouseenter", () => { if (!touchy()) show(entry); });
      slot.addEventListener("focus", () => { if (slot.matches(":focus-visible")) show(entry); });  // the keyboard opens it; a tap on a touch screen focuses too, but its click decides
      slot.addEventListener("mouseleave", later);
      slot.addEventListener("blur", later);
      slot.addEventListener("click", () => {
        if (touchy()) { if (current === entry && card.classList.contains("on")) hide(); else show(entry); } else go();
      });
      slot.addEventListener("keydown", (event) => {
        if (event.key === "Enter") go();
        else if (event.key === "Tab" && !event.shiftKey && current === entry && card.classList.contains("on")) {
          const items = focusable();
          if (items.length) { event.preventDefault(); items[0].focus(); }
        }
      });
    }

    function place(entry, zone) {
      if (entry.zone !== zone) { rowsOf[zone].append(entry.slot); entry.zone = zone; }
    }

    // A robot whose task changed state slides to its new place (it does not jump), and a ring in the colour of the new state spreads from it once.
    function pulse(entry) {
      const ring = h("i", {class: "lb-ring"});
      ring.style.borderColor = getComputedStyle(entry.bot).getPropertyValue("--c") || "#fff";
      entry.slot.append(ring);
      const gone = () => ring.remove();
      if (!ring.animate) { gone(); return; }
      ring.animate([{transform: "translate(-50%,-50%) scale(.3)", opacity: 0.9}, {transform: "translate(-50%,-50%) scale(1.5)", opacity: 0}], {duration: 900, easing: "ease-out"}).onfinish = gone;
      entry.bot.animate([{transform: "scale(.86,1.1)"}, {transform: "scale(1.08,.94)", offset: 0.4}, {transform: "none"}], {duration: 600, easing: "cubic-bezier(.3,1.5,.5,1)"});
    }

    // The robots slide to where they now are, whatever changed the layout (a robot that came, went or changed zone).
    function flip(change) {
      const was = new Map();
      if (!still) for (const [name, entry] of slots) was.set(name, entry.slot.getBoundingClientRect());
      change();
      if (still) return;
      for (const [name, entry] of slots) {
        const before = was.get(name);
        if (!before || !entry.slot.animate) continue;
        const now = entry.slot.getBoundingClientRect(), dx = before.left - now.left, dy = before.top - now.top;
        if (Math.abs(dx) > 2 || Math.abs(dy) > 2) entry.slot.animate([{transform: "translate(" + dx + "px," + dy + "px)"}, {transform: "none"}], {duration: 700, easing: "cubic-bezier(.2,.8,.2,1)"});
      }
    }

    function zones() {
      for (const [id] of ZONES) {
        const here = [...slots.values()].filter((entry) => entry.zone === id).length;
        zoneBox[id].box.hidden = !rowsOf[id].childElementCount;  // a robot on its way out still holds its zone open
        zoneBox[id].name.textContent = t(zoneBox[id].label) + " \u00b7 " + here;
      }
      size();
    }

    // One robot size for the whole page: the block with the most robots decides, so a robot is as big in a quiet block as in a crowded one.
    // 8 or fewer: large; up to 16: medium; more: small (the sizes are in lobby.css). The dock has the same size and does not count.
    function size() {
      const most = Math.max(0, ...ZONES.map(([id]) => rowsOf[id].childElementCount));
      const wanted = most >= 17 ? "s" : most >= 9 ? "m" : "l";
      if (scene.dataset.size !== wanted) scene.dataset.size = wanted;
    }

    // A robot that comes drops in from above and springs; one that goes lifts, shrinks and fades, and then the others close the gap.
    function enter(entry) {
      if (!entry.slot.animate) return;
      entry.slot.animate([{opacity: 0, transform: "translateY(-38px) scale(.5)"}, {opacity: 1, transform: "translateY(4px) scale(1.06)", offset: 0.7}, {opacity: 1, transform: "none"}], {duration: 650, easing: "cubic-bezier(.2,.8,.3,1)"});
      pulse(entry);
    }

    function leave(entry) {
      if (current === entry) hide();
      const slot = entry.slot;
      if (still || !slot.animate) { flip(() => { slot.remove(); zones(); }); return; }
      slot.style.pointerEvents = "none";
      slot.animate([{opacity: 1, transform: "none"}, {opacity: 0, transform: "translateY(-30px) scale(.6)"}], {duration: 500, easing: "ease-in", fill: "forwards"}).onfinish = () => flip(() => { slot.remove(); zones(); });
    }

    let ready = false;  // the first draw shows the robots where they are; it does not bring them in

    function update(rows, live) {
      liveNow = Boolean(live);
      const changed = [], came = [], gone = [];
      const agents = rows.filter((row) => row.status === "open");
      const names = new Set(agents.map((row) => row.name));
      flip(() => {
        for (const [name, entry] of slots) if (!names.has(name)) { gone.push(entry); slots.delete(name); }
        agents.forEach((row, index) => {
          const pose = poseOf(row, live);
          let entry = slots.get(row.name);
          if (!entry) {
            const bot = robot(pose, row.kind, ((index * 0.37) % 3).toFixed(2));
            const label = h("div", {class: "lb-nm", title: row.name}, row.name);
            const slot = h("div", {class: "lb-slot", tabindex: "0", role: "link", "aria-label": row.name}, bot, label);
            entry = {slot, bot, row, pose, zone: "", label};
            wire(entry);
            slots.set(row.name, entry);
            if (ready) came.push(entry);
          }
          entry.row = row;
          warnMark(entry.slot, row);
          if (entry.pose !== pose) {
            changed.push(entry);
            entry.bot.setAttribute("class", "lb-bot lb-pose-" + pose);
            entry.bot._mark.textContent = pose === "tests" ? "?" : "!";
            entry.pose = pose;
          }
          place(entry, ZONE_OF[pose]);
        });
        zones();
      });
      if (!still) { changed.forEach(pulse); came.forEach(enter); }
      gone.forEach(leave);
      dockUpdate(rows);
      // The card shows what the task is now: it is filled in place (never closed by a poll). It goes only when its robot is gone. A robot that moved to another zone is followed.
      if (current && card.classList.contains("on")) {
        const same = slots.get(current.row.name) || docked.get(current.row.name);
        if (!same) hide();
        else { current = same; fill(same); position(); if (changed.length || came.length || gone.length) setTimeout(position, 760); }
      }
      ready = true;
      count.textContent = agents.length ? t("board.lobby.count", {count: agents.length}) : t("board.lobby.none");
      if (!agents.length) {
        // No task at all: the first-task block (options.first, board.js: the big New task button, or how to run the served board). Tasks that are all closed: the quiet sentence and the same button;
        // a page on disk cannot start a task, so it says where to.
        const none = !rows.length && typeof options.first === "function";
        const key = none ? "first" : "quiet";
        if (empty.getAttribute("data-kind") !== key) {  // built once for each kind: a poll does not redraw the button under the pointer
          const idle = robot("idle", "other", 0);
          idle.setAttribute("class", "lb-bot lb-pose-idle lb-lone");
          const go = none || typeof options.go !== "function" ? null : options.go();
          empty.replaceChildren(idle, ...(none ? [options.first()] : [h("p", null, t(go ? "board.lobby.quiet" : "board.lobby.quiet.disk")), go].filter(Boolean)));
          empty.setAttribute("data-kind", key);
        }
      }
      empty.hidden = agents.length > 0;
    }

    if (!still) {  // the eyes follow the mouse; one frame at a time
      let frame = 0, x = 0, y = 0;
      window.addEventListener("mousemove", (event) => {
        x = event.clientX; y = event.clientY;
        if (frame || scene.offsetParent === null) return;
        frame = requestAnimationFrame(() => {
          frame = 0;
          for (const entry of slots.values()) {
            const box = entry.slot.getBoundingClientRect();
            const dx = x - (box.left + box.width / 2), dy = y - (box.top + box.height * 0.3), far = Math.hypot(dx, dy) || 1;
            const reach = Math.min(1, far / 220) * 3.2;
            entry.bot.style.setProperty("--ex", (dx / far * reach).toFixed(2) + "px");
            entry.bot.style.setProperty("--ey", (dy / far * reach * 0.7).toFixed(2) + "px");
          }
        });
      });
    }
    return {node: scene, update, hide};
  }

  return {create};
})();
