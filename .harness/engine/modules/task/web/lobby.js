// The lobby: the first screen of the board. Every task that is not closed is a small robot on a floor, in the zone of what it
// is doing: at work, waiting for the person, left alone (no session holds it), resting. The robot's pose says the state, the thing in its hand says the kind of
// task. A mouse near it makes its eyes follow; over it, it hops and a card shows the task and its stages; a click opens the page.
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
  const ZONES = [["work", "board.lobby.zone.work"], ["you", "board.lobby.zone.you"], ["left", "board.lobby.zone.left"], ["rest", "board.lobby.zone.rest"]];
  const STATE_TEXT = {work: "board.lobby.state.work", idle: "board.lobby.state.idle", pause: "board.state.paused", lost: "board.lobby.state.unheld"};

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

  function create(options) {
    const slots = new Map();  // task name -> {slot, bot, row, pose, zone, label}
    const rowsOf = {};
    const zoneBox = {};
    const count = h("div", {class: "lb-sub"});
    const card = h("div", {class: "lb-card"});
    const empty = h("div", {class: "lb-empty"});
    const scene = h("div", {class: "lb-scene"});
    for (let index = 0; index < 34; index++) {  // the stars are drawn once and stay where they are
      const star = h("i", {class: "lb-star"});
      star.style.left = Math.random() * 100 + "%";
      star.style.top = Math.random() * 60 + "%";
      star.style.animationDelay = Math.random() * 3 + "s";
      scene.append(star);
    }
    scene.append(h("h3", null, t("board.title")), count);
    for (const [id, label] of ZONES) {
      const row = h("div", {class: "lb-row"});
      const name = h("span", null);
      const dot = h("i", {class: "lb-dot lb-dot-" + id});
      rowsOf[id] = row;
      zoneBox[id] = {box: h("div", {class: "lb-zone"}, h("div", {class: "lb-label"}, dot, name), row), name, label};
      scene.append(zoneBox[id].box);
    }
    scene.append(empty, card);

    function show(entry) {
      const {row, pose} = entry;
      const state = pose === "you" || pose === "tests" ? row.waiting : t(STATE_TEXT[pose]);  // a task at work that already has a plan to approve is at work
      const lines = [h("b", null, row.name), h("div", {class: "lb-k"}, t("task.kind." + (row.kind || "none")) + " · " + t("task.tier." + (row.tier || "none")) + " · " + state + (state === row.waiting && row.waited_s ? " · " + clock(row.waited_s) : ""))];
      const s = row.stages;
      if (s && s.steps && s.steps.length) {
        const dots = [];
        s.steps.forEach((step, index) => {
          dots.push(h("i", {class: "lb-d " + (step.state === "done" ? "is-done" : step.state === "now" ? "is-now is-" + (pose === "you" || pose === "tests" ? "you" : pose === "lost" ? "left" : "ok") : "")}));
          if (index < s.steps.length - 1) dots.push(h("i", {class: "lb-l" + (step.state === "done" ? " is-done" : "")}));
        });
        const here = s.steps.find((step) => step.state === "now") || s.steps[s.steps.length - 1];
        const reviewed = s.review && s.review.n ? t("board.lobby.reviewed", {passes: s.review.states.filter((mark) => mark === "pass").length, n: s.review.n}) : "";
        lines.push(h("div", {class: "lb-mini"}, dots), h("div", {class: "lb-mini-names"}, h("span", null, here.label || t("stage." + here.id)),
          h("span", null, [s.round > 1 ? t("stage.round", {round: s.round}) : "", reviewed].filter(Boolean).join(" · "))));
      }
      // The buttons of the list, on the card: the same ones, grey while the agent is at work. The card stays while the mouse is on it.
      if (row.actions && row.actions.length) lines.push(h("div", {class: "lb-acts"}, row.actions.map((item) => actionButton(row, item))));
      card.replaceChildren(...lines);
      clearTimeout(leaveTimer);
      current = entry;
      const sceneBox = scene.getBoundingClientRect(), at = entry.slot.getBoundingClientRect();
      let x = at.left - sceneBox.left + at.width / 2 - 125, y = at.top - sceneBox.top - card.offsetHeight - 6;
      const below = y < 6;
      if (below) y = at.bottom - sceneBox.top + 4;
      card.classList.toggle("below", below);
      card.style.left = Math.max(8, Math.min(sceneBox.width - 258, x)) + "px";
      card.style.top = y + "px";
      card.classList.add("on");
    }
    let leaveTimer = 0, current = null;
    const hide = () => { clearTimeout(leaveTimer); card.classList.remove("on"); current = null; };
    const later = () => { clearTimeout(leaveTimer); leaveTimer = setTimeout(hide, 220); };  // time to cross from the robot to its card
    card.addEventListener("mouseenter", () => clearTimeout(leaveTimer));
    card.addEventListener("mouseleave", later);
    card.addEventListener("focusin", () => clearTimeout(leaveTimer));
    card.addEventListener("focusout", later);

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
    }

    // A robot that comes drops in from above and springs; one that goes lifts, shrinks and fades, and then the others close the gap.
    function enter(entry) {
      if (!entry.slot.animate) return;
      entry.slot.animate([{opacity: 0, transform: "translateY(-38px) scale(.5)"}, {opacity: 1, transform: "translateY(4px) scale(1.06)", offset: 0.7}, {opacity: 1, transform: "none"}], {duration: 650, easing: "cubic-bezier(.2,.8,.3,1)"});
      pulse(entry);
    }

    function leave(entry) {
      hide();
      const slot = entry.slot;
      if (still || !slot.animate) { flip(() => { slot.remove(); zones(); }); return; }
      slot.style.pointerEvents = "none";
      slot.animate([{opacity: 1, transform: "none"}, {opacity: 0, transform: "translateY(-30px) scale(.6)"}], {duration: 500, easing: "ease-in", fill: "forwards"}).onfinish = () => flip(() => { slot.remove(); zones(); });
    }

    let ready = false;  // the first draw shows the robots where they are; it does not bring them in

    function update(rows, live) {
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
            const label = h("div", {class: "lb-nm"}, row.name);
            const slot = h("div", {class: "lb-slot", tabindex: "0", role: "link", "aria-label": row.name}, bot, label);
            entry = {slot, bot, row, pose, zone: "", label};
            slot.addEventListener("mouseenter", () => show(entry));
            slot.addEventListener("focus", () => show(entry));
            slot.addEventListener("mouseleave", later);
            slot.addEventListener("blur", later);
            const open = () => { const href = options.href(entry.row); if (href) window.location.href = href; };
            slot.addEventListener("click", open);
            slot.addEventListener("keydown", (event) => { if (event.key === "Enter") open(); });
            slots.set(row.name, entry);
            if (ready) came.push(entry);
          }
          entry.actionsChanged = JSON.stringify(entry.row.actions) !== JSON.stringify(row.actions);
          entry.row = row;
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
      // The card shows what the task is now: draw it again unless the mouse is on it (that would take a click away; an action just done is the exception),
      // and take it away when its robot is gone or changed state.
      if (current && card.classList.contains("on")) {
        const same = slots.get(current.row.name);
        if (!same || changed.includes(same)) hide();
        else if (!card.matches(":hover") || same.actionsChanged) show(same);
      }
      ready = true;
      count.textContent = agents.length ? t("board.lobby.count", {count: agents.length}) : t("board.lobby.none");
      if (!agents.length && !empty.firstChild) {
        const idle = robot("idle", "other", 0);
        idle.setAttribute("class", "lb-bot lb-pose-idle lb-lone");
        empty.append(idle, h("p", null, t("board.lobby.quiet")));
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
    return {node: scene, update};
  }

  return {create};
})();
