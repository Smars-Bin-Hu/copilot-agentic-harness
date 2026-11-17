// The pet of the super agent view (1.8.1): a small robot in a headset that hovers over the view, turns to face where it goes, looks at what it passes, waves when it carries a letter,
// sleeps, runs out of battery, and answers a click, a double click and a drag; a right click picks its skin (`SKINS`). One dot circles it for each task (`orbit`), in the colour of the task's state. It is drawn in 3D with the robot of the Enter screen (bot3d.js, WebGL); without WebGL it is the flat robot of the lobby
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
  // The skins, in the order of the shader (bot3d.js `skin`): the gear it wears; the colours are in super.css (`.skin-<name>`). Kept per browser; the flat robots of the super agent (avatars, pop-out) wear it too.
  const SKINS = ["commander", "ninja", "pilot", "mecha", "neon"];
  const SKIN_KEY = "harness.pet.skin";
  const SKIN_LABEL = {commander: "super.pet.skin.commander", ninja: "super.pet.skin.ninja", pilot: "super.pet.skin.pilot", mecha: "super.pet.skin.mecha", neon: "super.pet.skin.neon"};  // written out: a search for a key finds its place
  let current = (() => { try { const name = localStorage.getItem(SKIN_KEY); return SKINS.includes(name) ? name : SKINS[0]; } catch (error) { return SKINS[0]; } })();
  const dressed = new Set();  // the flat robots of the super agent that were dressed: dressed again when the skin changes (those no longer on screen are dropped)
  const GEAR = {
    commander: () => [el("path", {class: "sa-cap", d: "M22 22 Q50 2 78 22 L78 26 Q50 12 22 26 Z"}), el("path", {class: "sa-set", d: "M20 34 Q14 34 15 44", fill: "none"}), el("circle", {class: "sa-cap", cx: 16, cy: 46, r: 3})],
    ninja: () => [el("rect", {class: "sa-cap", x: 23, y: 19, width: 54, height: 7, rx: 3}), el("path", {class: "sa-gs", d: "M25 22 L12 28 M25 23 L15 36"})],
    pilot: () => [el("path", {class: "sa-set", d: "M24 21 H76", fill: "none"}), el("circle", {class: "sa-cap sa-rim", cx: 40, cy: 20, r: 6.5}), el("circle", {class: "sa-cap sa-rim", cx: 60, cy: 20, r: 6.5}), el("circle", {class: "sa-lens", cx: 40, cy: 20, r: 3.6}), el("circle", {class: "sa-lens", cx: 60, cy: 20, r: 3.6})],
    mecha: () => [el("path", {class: "sa-gs", d: "M47 23 L30 5 M53 23 L70 5"}), el("circle", {class: "sa-lens", cx: 50, cy: 23, r: 3.4})],
    neon: () => [el("path", {class: "sa-gs", d: "M35 17 L28 5 M43 15 L41 2 M57 15 L59 2 M65 17 L72 5"}), el("rect", {class: "sa-frame", x: 28.5, y: 23.5, width: 43, height: 27, rx: 11})],
  };

  // The gear of the super agent on the flat robot, in the skin `name` (the current one when not given), and its clipboard.
  function dress(root, name) {
    const skin = SKINS.includes(name) ? name : current;
    if (dressed.size > 300) for (const node of dressed) if (!node.isConnected) dressed.delete(node);
    dressed.add(root);
    for (const old of root.querySelectorAll(".sa-dress")) old.remove();
    root.classList.add("sa-boss");
    for (const each of SKINS) root.classList.toggle("skin-" + each, each === skin);
    const head = root.querySelector(".lb-headg"), arm = root.querySelector(".lb-arm.lb-l");
    if (head) { const gear = el("g", {class: "sa-dress"}); gear.append(...GEAR[skin]()); head.append(gear); }
    if (arm) {
      const board = el("g", {class: "sa-dress", transform: "translate(6,78) rotate(-8)"});
      board.append(el("rect", {class: "sa-clip", x: -9, y: -4, width: 18, height: 22, rx: 2}), el("path", {class: "sa-clip-l", d: "M-5 3 H5 M-5 7 H5 M-5 11 H2"}), el("rect", {class: "sa-cap", x: -4, y: -6, width: 8, height: 4, rx: 1}));
      arm.append(board);
    }
  }
  // Wear `name` from now on: kept in this browser, and every flat robot of the super agent on screen changes with it. The 3D pet changes in its own `wear`.
  function setSkin(name) {
    if (!SKINS.includes(name)) return;
    current = name;
    try { localStorage.setItem(SKIN_KEY, name); } catch (error) { /* kept until the page closes */ }
    for (const node of [...dressed]) { if (node.isConnected) dress(node, name); else dressed.delete(node); }
  }

  // A head of the flat robot for an avatar: `boss` gives the super agent's own, in its skin.
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
    const orbit = h("span", {class: "sa-orbit", "aria-hidden": "true"});  // inside the body, so they hover with it: the dots pass in front of the robot and behind it
    body.append(h("span", {class: "sa-jet", "aria-hidden": "true"}), orbit);
    const node = h("button", {type: "button", class: "sa-pet", "aria-label": t("super.pet.label")}, h("span", {class: "sa-shadow", "aria-hidden": "true"}), body, say, hold, zz, battery);
    const flat = (typeof Lobby !== "undefined" && Lobby.robot) ? Lobby.robot("calm", "", 0) : null;
    if (flat) { dress(flat); body.append(flat); }
    host.append(node);
    const solid = typeof BOT3D !== "undefined" ? BOT3D.make(body, {boss: true}) : null;  // null: no WebGL (or a slow software renderer): the flat robot stays
    if (solid) new MutationObserver(() => { solid.colours(); kick(); }).observe(document.documentElement, {attributes: true, attributeFilter: ["class", "data-theme"]});

    // what the picture is, and what it moves towards
    const S = {skin: SKINS.indexOf(current), x: 0, y: 0, yaw: 0, yawT: 0, sleep: 0, sleepT: 0, tired: 0, tiredT: 0, arm: 0, nx: 0, ny: 0, nxT: 0, nyT: 0, walking: false, mood: "calm", waveTo: 0, hopTo: 0, think: false, running: false, token: 0, pending: null, held: false, clickers: [], doubles: [], drops: []};
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
      S.arm += ((S.held ? 2.2 + Math.sin(now / 90) * .25 : waving ? 2.6 + Math.sin(now / 130) * .3 : swing) - S.arm) * .18;
      const shut = now % 5000 > 4780 ? .12 : 1, sway = S.walking ? Math.sin(now / 170) * .07 : Math.sin(now / 2100) * .03;
      solid.draw({yaw: S.yaw + sway, pitch: .05, headYaw: S.nx * .22, headPitch: S.ny * .14 + S.sleep * .16 + S.tired * .1, roll: -S.nx * .1 - S.sleep * .07, arm: S.arm,
        eyeX: S.nx * 2.6, eyeY: -S.ny * 2, blink: (1 - S.sleep) * shut + S.sleep * .1, glow: Math.max(0, 1 - S.sleep - S.tired * .55), skin: S.skin});
    }
    function frame(now) {
      raf = 0;
      if (!S.running) return;
      if (solid) draw(now);
      const hot = S.walking || S.held || now < S.waveTo || now < S.hopTo || !settled();
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
      node.classList.toggle("off", !S.running);
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
    // One dot per task, circling the waist: `states` in board order, each "block", "you", "work" or "idle". Twelve at most. The circling is CSS (no 3D frame).
    let orbitSig = "";
    function circle(states) {
      const list = (states || []).slice(0, 12), sig = list.join();
      if (sig === orbitSig) return;
      orbitSig = sig;
      orbit.replaceChildren(...list.map((state, at) => { const dot = h("i", {class: "sa-dot " + state}); dot.style.animationDelay = (-(at / list.length) * 9).toFixed(2) + "s"; return dot; }));
    }

    // A click waits a moment for a second one: one click and a double click are different asks. Enter and Space give one click.
    let clickTimer = 0, dragged = false;
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      if (dragged) { dragged = false; return; }
      if (event.detail > 1) return;
      clearTimeout(clickTimer);
      clickTimer = setTimeout(() => { clickTimer = 0; for (const fn of S.clickers) fn(); }, event.detail ? 260 : 0);
    });
    node.addEventListener("dblclick", (event) => { event.stopPropagation(); clearTimeout(clickTimer); clickTimer = 0; for (const fn of S.doubles) fn(); });
    // Drag it: it hangs from the pointer with its arm up; where it is let go is the host's to judge (`onDrop`, with the point in the page).
    node.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || !S.running) return;
      const start = {x: event.clientX, y: event.clientY, px: S.x, py: S.y};
      let moving = false;
      const move = (ev) => {
        const dx = ev.clientX - start.x, dy = ev.clientY - start.y;
        if (!moving && Math.hypot(dx, dy) < 6) return;
        if (!moving) {
          moving = true; S.held = true;
          if (S.pending) { clearTimeout(S.pending.timer); S.pending.done(); }
          node.classList.add("held"); quiet(); kick();
        }
        place(clamp(start.px + dx, -10, host.clientWidth - node.offsetWidth + 10), clamp(start.py + dy, -10, host.clientHeight - node.offsetHeight));
      };
      const up = (ev) => {
        removeEventListener("pointermove", move); removeEventListener("pointerup", up); removeEventListener("pointercancel", up);
        if (!moving) return;
        dragged = true; S.held = false;
        node.classList.remove("held");
        setTimeout(() => { dragged = false; }, 400);
        kick();
        for (const fn of S.drops) fn(ev.clientX, ev.clientY);
      };
      addEventListener("pointermove", move); addEventListener("pointerup", up); addEventListener("pointercancel", up);
    });

    // Right click (or the menu key): pick a skin. The menu is a small list beside the pet; a pick is kept per browser.
    function wear(index) {
      S.skin = index;
      for (const [at, name] of SKINS.entries()) node.classList.toggle("skin-" + name, at === index);
      if (solid) solid.colours();
      kick();
    }
    let menu = null;
    function closeMenu() {
      if (!menu) return;
      menu.remove(); menu = null;
      removeEventListener("pointerdown", outside, true); removeEventListener("keydown", escape, true);
    }
    const outside = (event) => { if (menu && !menu.contains(event.target)) closeMenu(); };
    const escape = (event) => {
      if (event.key === "Escape") { event.stopPropagation(); closeMenu(); node.focus(); return; }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      const items = [...menu.querySelectorAll("button")], at = items.indexOf(document.activeElement);
      event.preventDefault();
      items[(at + (event.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
    };
    function openMenu() {
      closeMenu();
      menu = h("div", {class: "sa-skins", role: "menu", "aria-label": t("super.pet.skins")}, h("div", {class: "sa-skins-head"}, t("super.pet.skins")),
        ...SKINS.map((name, at) => {
          const item = h("button", {type: "button", role: "menuitemradio", "aria-checked": String(at === S.skin), class: "sa-skin skin-" + name}, h("span", {class: "sa-swatch", "aria-hidden": "true"}), t(SKIN_LABEL[name]));
          item.addEventListener("click", (event) => {
            event.stopPropagation();
            wear(at);
            setSkin(name);
            closeMenu(); hop();
            if (!event.detail) node.focus();  // picked with the keyboard: the focus goes back to the pet
          });
          return item;
        }));
      host.append(menu);
      const size = {w: menu.offsetWidth, h: menu.offsetHeight}, left = S.x > host.clientWidth * .55 ? S.x - size.w - 4 : S.x + node.offsetWidth + 4;
      menu.style.left = clamp(left, 0, Math.max(0, host.clientWidth - size.w)) + "px";
      menu.style.top = clamp(S.y + 8, 0, Math.max(0, host.clientHeight - size.h)) + "px";
      (menu.querySelector("[aria-checked=true]") || menu.querySelector("button")).focus();
      addEventListener("pointerdown", outside, true); addEventListener("keydown", escape, true);
    }
    node.addEventListener("contextmenu", (event) => { event.preventDefault(); event.stopPropagation(); quiet(); openMenu(); });
    wear(S.skin);

    return {node, solid: Boolean(solid), run, place, walkTo, say: talk, quiet, think, mood, wave, hop, carry, look, orbit: circle, held: () => S.held, at: () => ({x: S.x, y: S.y}), size: () => ({w: node.offsetWidth, h: node.offsetHeight}),
      onClick: (fn) => S.clickers.push(fn), onDouble: (fn) => S.doubles.push(fn), onDrop: (fn) => S.drops.push(fn)};
  }

  // The battery of the super agent's Credits today (`cost`: left from 0 to 1, full when the limit is reached, the numbers in `tip`). The super view and the pop-out draw it.
  function battery(cost) {
    const level = h("i");
    level.style.width = Math.round(Math.max(0, Math.min(1, cost.left)) * 100) + "%";
    return h("span", {class: "sa-cell" + (cost.full ? " full" : cost.left < .2 ? " low" : cost.left < .5 ? " mid" : ""), role: "img", "aria-label": cost.label, title: cost.tip}, level);
  }

  return {create, face, dress, battery, skin: () => current};
})();
