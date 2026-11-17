// The pet of the super agent view (1.8.1): a small robot that walks over the view, turns to face where it goes, looks at what it passes, waves when it carries a letter,
// sleeps, runs out of battery, and answers a click. It is drawn in 3D with the robot of the Enter screen (bot3d.js, WebGL); without WebGL it is the flat robot of the lobby
// (Lobby.robot) with the super agent's cap and clipboard. Needs common.js (h, t) and lobby.js; bot3d.js is optional.
// The pet is placed in the coordinates of its host (a box with position: relative): `place`, `walkTo`. The walk is a CSS transition; a 3D frame is drawn only while the pet moves or
// the picture still settles, and once in a while (every 450 ms) for the blink. Nothing is drawn while the page is hidden or the view is not shown (`run(false)`).
"use strict";

const PET = (function () {
  const NS = "http://www.w3.org/2000/svg";
  const el = (name, attrs) => { const node = document.createElementNS(NS, name); for (const key in attrs) node.setAttribute(key, attrs[key]); return node; };
  const query = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  const reduced = () => Boolean(query && query.matches) || document.documentElement.classList.contains("lite");
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

  // The cap, the headset and the clipboard of the super agent, on the flat robot.
  function dress(root) {
    const head = root.querySelector(".lb-headg"), arm = root.querySelector(".lb-arm.lb-l");
    if (head) head.append(el("path", {class: "sa-cap", d: "M22 22 Q50 2 78 22 L78 26 Q50 12 22 26 Z"}), el("path", {class: "sa-set", d: "M20 34 Q14 34 15 44", fill: "none"}), el("circle", {class: "sa-cap", cx: 16, cy: 46, r: 3}));
    if (arm) {
      const board = el("g", {transform: "translate(6,78) rotate(-8)"});
      board.append(el("rect", {class: "sa-clip", x: -9, y: -4, width: 18, height: 22, rx: 2}), el("path", {class: "sa-clip-l", d: "M-5 3 H5 M-5 7 H5 M-5 11 H2"}), el("rect", {class: "sa-cap", x: -4, y: -6, width: 8, height: 4, rx: 1}));
      arm.append(board);
    }
  }

  // A head of the flat robot for an avatar: `boss` gives the super agent's own (cap, headset).
  function face(pose, kind, delay, boss) {
    if (typeof Lobby === "undefined" || !Lobby.robot) return document.createElement("span");
    const root = Lobby.robot(pose, kind || "", delay || 0);
    if (boss) dress(root);
    root.setAttribute("viewBox", boss ? "10 -4 80 66" : "16 -4 68 66");
    return root;
  }

  function create(host) {
    const body = h("div", {class: "sa-pet-body"});
    const say = h("div", {class: "sa-say", "aria-hidden": "true"});
    const hold = h("span", {class: "sa-hold", "aria-hidden": "true"});  // the letter in its hand
    const zz = h("span", {class: "sa-zz", "aria-hidden": "true"}, "z z");
    const battery = el("svg", {class: "sa-batt", viewBox: "0 0 24 12", "aria-hidden": "true"});
    battery.append(el("rect", {x: 1, y: 1, width: 19, height: 10, rx: 2, fill: "none", "stroke-width": 1.6}), el("rect", {x: 20.5, y: 4, width: 2.5, height: 4, "stroke-width": 0}), el("rect", {x: 3, y: 3, width: 3.5, height: 6, "stroke-width": 0}));
    const node = h("button", {type: "button", class: "sa-pet", "aria-label": t("super.pet.label")}, body, say, hold, zz, battery);
    const flat = (typeof Lobby !== "undefined" && Lobby.robot) ? Lobby.robot("calm", "", 0) : null;
    if (flat) { dress(flat); body.append(flat); }
    host.append(node);
    const solid = typeof BOT3D !== "undefined" ? BOT3D.make(body) : null;  // null: no WebGL (or a slow software renderer): the flat robot stays
    if (solid) new MutationObserver(() => { solid.colours(); kick(); }).observe(document.documentElement, {attributes: true, attributeFilter: ["class", "data-theme"]});

    // what the picture is, and what it moves towards
    const S = {x: 0, y: 0, yaw: 0, yawT: 0, sleep: 0, sleepT: 0, tired: 0, tiredT: 0, arm: 0, nx: 0, ny: 0, nxT: 0, nyT: 0, walking: false, mood: "calm", waveTo: 0, hopTo: 0, think: false, running: false, token: 0, pending: null, clickers: []};
    let raf = 0, timer = 0, sayTimer = 0;

    function settled() {
      return Math.abs(S.yaw - S.yawT) < .01 && Math.abs(S.sleep - S.sleepT) < .01 && Math.abs(S.tired - S.tiredT) < .01 && Math.abs(S.nx - S.nxT) < .01 && Math.abs(S.ny - S.nyT) < .01;
    }
    function draw(now) {
      S.yaw += (S.yawT - S.yaw) * .16;
      S.sleep += (S.sleepT - S.sleep) * .08;
      S.tired += (S.tiredT - S.tired) * .08;
      S.nx += (S.nxT - S.nx) * .2;
      S.ny += (S.nyT - S.ny) * .2;
      const waving = now < S.waveTo, swing = S.walking ? Math.sin(now / 150) * .55 : 0;
      S.arm += ((waving ? 2.6 + Math.sin(now / 130) * .3 : swing) - S.arm) * .18;
      const shut = now % 5000 > 4780 ? .12 : 1, sway = S.walking ? Math.sin(now / 170) * .07 : Math.sin(now / 2100) * .03;
      solid.draw({yaw: S.yaw + sway, pitch: .05, headYaw: S.nx * .22, headPitch: S.ny * .14 + S.sleep * .16 + S.tired * .1, roll: -S.nx * .1 - S.sleep * .07, arm: S.arm,
        eyeX: S.nx * 2.6, eyeY: -S.ny * 2, blink: (1 - S.sleep) * shut + S.sleep * .1, glow: Math.max(0, 1 - S.sleep - S.tired * .55)});
    }
    function frame(now) {
      raf = 0;
      if (!S.running) return;
      if (solid) draw(now);
      const hot = S.walking || now < S.waveTo || now < S.hopTo || !settled();
      if (hot && !reduced()) raf = requestAnimationFrame(frame);
      else if (solid && !reduced()) timer = setTimeout(() => { timer = 0; kick(); }, 450);  // the blink and the slow sway
    }
    function kick() {
      if (!S.running || raf) return;
      clearTimeout(timer); timer = 0;
      raf = requestAnimationFrame(frame);
    }
    function run(on) {
      S.running = on && !document.hidden;
      if (!S.running) { cancelAnimationFrame(raf); raf = 0; clearTimeout(timer); timer = 0; return; }
      if (solid) solid.colours();
      kick();
    }
    document.addEventListener("visibilitychange", () => { if (node.isConnected && !host.hidden) run(!document.hidden); });

    function place(x, y) {
      S.x = x; S.y = y;
      node.style.transitionDuration = "0ms";
      node.style.transform = "translate(" + x.toFixed(1) + "px," + y.toFixed(1) + "px)";
      node.classList.toggle("left", x > host.clientWidth * .55);
    }
    // Walk to (x, y), the top left of the pet. The promise ends when it stands there (or at once when a newer walk replaced this one). `face`: -1 left, 0 front, 1 right, how it stands after.
    function walkTo(x, y, face) {
      const dx = x - S.x, dist = Math.hypot(dx, y - S.y);
      if (S.pending) { clearTimeout(S.pending.timer); S.pending.done(); }
      if (dist < 2 || reduced() || !S.running) { place(x, y); S.yawT = (face || 0) * .35; kick(); return Promise.resolve(); }
      const ms = Math.round(Math.min(2200, 420 + dist * 2.6));
      const goesLeft = dx < 0;
      node.classList.toggle("flip", goesLeft);
      S.yawT = (goesLeft ? -1 : 1) * .9;
      S.walking = true;
      node.classList.add("walk");
      node.style.transitionDuration = ms + "ms";
      node.style.transform = "translate(" + x.toFixed(1) + "px," + y.toFixed(1) + "px)";
      node.classList.toggle("left", x > host.clientWidth * .55);
      S.x = x; S.y = y;
      kick();
      return new Promise((resolve) => {
        const entry = {timer: 0, done: () => { S.pending = null; S.walking = false; node.classList.remove("walk"); S.yawT = (face || 0) * .35; node.classList.toggle("flip", face < 0); kick(); resolve(); }};
        entry.timer = setTimeout(entry.done, ms + 40);
        S.pending = entry;
      });
    }
    function talk(text, ms) {
      clearTimeout(sayTimer);
      say.replaceChildren(text);
      say.classList.add("on");
      if (ms) sayTimer = setTimeout(() => say.classList.remove("on"), ms);
    }
    function quiet() { clearTimeout(sayTimer); say.classList.remove("on"); }
    function think(on) {
      if (on === S.think) return;
      S.think = on;
      node.classList.toggle("thinking", on);
      if (on) { clearTimeout(sayTimer); say.replaceChildren(h("span", {class: "sa-dots", role: "img", "aria-label": t("super.think")}, h("i"), h("i"), h("i"))); say.classList.add("on"); }
      else if (say.querySelector(".sa-dots")) quiet();
    }
    function mood(name) {
      if (name === S.mood) return;
      S.mood = name;
      node.classList.toggle("m-sleep", name === "sleep");
      node.classList.toggle("m-tired", name === "tired");
      S.sleepT = name === "sleep" ? 1 : 0;
      S.tiredT = name === "tired" ? 1 : 0;
      if (solid) solid.colours();
      kick();
    }
    function wave(ms) { S.waveTo = performance.now() + ms; node.classList.add("waving"); setTimeout(() => node.classList.remove("waving"), ms); kick(); }
    function hop() { if (reduced()) return; node.classList.remove("hop"); void node.offsetWidth; node.classList.add("hop"); S.hopTo = performance.now() + 700; kick(); }
    function carry(on) { node.classList.toggle("carry", on); }
    function look(nx, ny) { S.nxT = clamp(nx, -1, 1); S.nyT = clamp(ny, -1, 1); node.style.setProperty("--ex", (S.nxT * 4).toFixed(1) + "px"); node.style.setProperty("--ey", (S.nyT * 3).toFixed(1) + "px"); kick(); }
    node.addEventListener("click", (event) => { event.stopPropagation(); for (const fn of S.clickers) fn(); });

    return {node, solid: Boolean(solid), run, place, walkTo, say: talk, quiet, think, mood, wave, hop, carry, look, at: () => ({x: S.x, y: S.y}), size: () => ({w: node.offsetWidth, h: node.offsetHeight}), onClick: (fn) => S.clickers.push(fn)};
  }

  return {create, face, dress};
})();
