// The 3D space behind the page (1.6.19, B89): the stage (#sp) with the picture far back, two layers of dust nearer, and a floor grid with a horizon when there is no picture. The look is in space.css.
// The world turns with the pointer: +-4 deg on the board and the task page, +-8 deg on the Enter screen. Two smoothing steps make it glide, never overshoot, never jitter (about 1.4 s to follow, about 4 s
// to come back to the centre once the pointer has left). One requestAnimationFrame, and only the transform of #sp-world changes. The loop stops when the angles have settled, when the page is hidden, in Lite,
// under reduced motion and when the "Background motion" switch is off. Panels, rows and text are not in the stage: they never move.
// While it moves the frame time is measured. When it stays poor for a few seconds, a small note offers Lite once. It never switches by itself.
// The Enter screen (enter.js) has its own loop while it is open: it calls SPACE.step() each frame instead, so there is still one frame callback, and tilts its wordmark with SPACE.ax / SPACE.ay.
"use strict";

const SPACE = (function () {
  const root = document.documentElement;
  const reduceQuery = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  const memory = {};
  const keep = {
    get(name) { try { const value = localStorage.getItem(name); return value === null ? (name in memory ? memory[name] : null) : value; } catch (error) { return name in memory ? memory[name] : null; } },
    set(name, value) { memory[name] = value; try { localStorage.setItem(name, value); } catch (error) { /* kept in memory only */ } },
  };
  const MOTION = "harness.motion";  // "0": off. Anything else: on (the default).
  const ASKED = "harness.slow.asked";  // "1": the note about a slow page was shown once and is not shown again

  // ---------- the stage ----------
  const div = (id, cls) => { const node = document.createElement("div"); if (id) node.id = id; if (cls) node.className = cls; return node; };
  const stage = div("sp"), world = div("sp-world");
  stage.setAttribute("aria-hidden", "true");
  const layers = [document.createElement("i"), document.createElement("i")];
  layers.forEach((node) => { node.className = "wl"; });
  const wp = div("wp");
  wp.append(...layers);
  const dust = [div("sp-d1", "sp-dust"), div("sp-d2", "sp-dust")];
  world.append(div("sp-studio"), div("sp-grid"), div("sp-horizon"), wp, ...dust);
  stage.append(world);
  document.body.prepend(stage);

  // Fine dust: many tiny soft dots in one background each, made once with a fixed seed (the same every time, so a still of the page can be compared).
  (function () {
    let seed = 7;
    const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    function paint(node, count, size, alpha) {
      const parts = [];
      for (let i = 0; i < count; i++) {
        const s = (size * (.6 + rnd() * .9)).toFixed(1);
        parts.push("radial-gradient(" + s + "px " + s + "px at " + (rnd() * 100).toFixed(1) + "% " + (rnd() * 100).toFixed(1) + "%,rgba(var(--sp-rgb)," + (alpha * (.5 + rnd() * .5)).toFixed(2) + ") 0,rgba(var(--sp-rgb),0) 100%)");
      }
      node.style.backgroundImage = parts.join(",");
    }
    paint(dust[0], 84, 3.4, .75);
    paint(dust[1], 34, 5.2, .8);
  })();

  // ---------- the angles ----------
  const S = {ax: 0, ay: 0, sx: 0, sy: 0, tx: 0, ty: 0, raf: 0, leaving: false, hosted: null, onTilt: null, layers, frame: 0};
  const reduced = () => Boolean(reduceQuery && reduceQuery.matches);
  const motionChosen = () => keep.get(MOTION) !== "0";
  const lite = () => root.classList.contains("lite");
  const on = () => motionChosen() && !lite() && !reduced();
  const max = () => (root.classList.contains("en-open") ? 8 : 4);
  function sync() { root.classList.toggle("sp-still", !on()); }

  function apply() {
    world.style.transform = "rotateX(" + S.ax.toFixed(3) + "deg) rotateY(" + S.ay.toFixed(3) + "deg)";
    if (S.onTilt) S.onTilt();
  }
  // One step towards the target. Returns whether it still moves. `now` (a frame time) feeds the frame-rate check.
  function step(now) {
    const rate = S.leaving ? .03 : .06;
    S.sx += (S.tx - S.sx) * rate; S.sy += (S.ty - S.sy) * rate; S.ax += (S.sx - S.ax) * rate; S.ay += (S.sy - S.ay) * rate;
    const moving = Math.abs(S.tx - S.ax) > .01 || Math.abs(S.ty - S.ay) > .01 || Math.abs(S.sx - S.ax) > .004 || Math.abs(S.sy - S.ay) > .004;
    if (!moving) { S.ax = S.sx = S.tx; S.ay = S.sy = S.ty; }
    apply();
    measure(moving ? now : 0);
    return moving;
  }
  function tick(now) {
    S.raf = 0;
    if (!on() || document.hidden) { measure(0); return; }
    if (step(now)) S.raf = requestAnimationFrame(tick);
  }
  function kick() {
    if (!on() || document.hidden || S.raf) return;
    if (S.hosted && S.hosted()) return;  // the Enter screen's loop is running a frame: it calls step() itself
    S.raf = requestAnimationFrame(tick);
  }
  function stop() {
    cancelAnimationFrame(S.raf); S.raf = 0; measure(0);
  }
  function reset() {
    stop();
    S.ax = S.ay = S.sx = S.sy = S.tx = S.ty = 0;
    world.style.transform = "";
    if (S.onTilt) S.onTilt();
  }
  function set(ax, ay, immediately) {  // for a still of the page (tests and screenshots) and for a script: the target angles
    S.tx = ax; S.ty = ay;
    if (immediately) { S.ax = S.sx = ax; S.ay = S.sy = ay; apply(); } else kick();
  }

  document.addEventListener("pointermove", (event) => {
    if (!on() || event.pointerType === "touch") return;
    const m = max();
    S.leaving = false;
    S.tx = -(event.clientY / innerHeight - .5) * 2 * m; S.ty = (event.clientX / innerWidth - .5) * 2 * m;
    kick();
  });
  root.addEventListener("mouseleave", () => { S.leaving = true; S.tx = S.ty = 0; kick(); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); else kick(); });

  // ---------- the frame rate ----------
  // Only frames of the moving background count, and only the time between two frames in a row (a gap over 250 ms is a pause, not a slow frame). After 4 s of moving, when more than
  // 60 in 100 of those frames took longer than 34 ms (below 30 per second), the page offers Lite once. The check starts again every 4 s of moving.
  const F = {last: 0, n: 0, slow: 0, time: 0};
  function measure(now) {
    if (!now) { F.last = 0; return; }
    if (F.last && now > F.last && now - F.last < 250) {
      const dt = now - F.last;
      F.n++; F.time += dt; if (dt > 34) F.slow++;
      if (F.time >= 4000) {
        const poor = F.n > 20 && F.slow / F.n > .6;
        F.n = F.slow = F.time = 0;
        if (poor) offer();
      }
    }
    F.last = now;
  }
  let note = null, asked = keep.get(ASKED) === "1";
  function offer() {
    if (asked || note || lite() || !on() || typeof harnessTheme === "undefined" || typeof t !== "function") return;
    asked = true; keep.set(ASKED, "1");
    const go = h("button", {type: "button", class: "go"}, t("board.space.slow.lite"));
    const no = h("button", {type: "button"}, t("board.space.slow.keep"));
    note = h("div", {class: "sp-slow", role: "status"}, h("p", null, t("board.space.slow")), h("div", {class: "row"}, no, go));
    document.body.append(note);
    const close = () => { note.remove(); };
    go.addEventListener("click", () => { harnessTheme.setLite(true); close(); });
    no.addEventListener("click", close);
  }

  // ---------- the switch ----------
  function setMotion(value) {
    keep.set(MOTION, value ? "1" : "0");
    sync();
    if (!on()) reset(); else kick();
  }
  // Lite is the class `lite` on <html> (theme.js): the stage follows it, whoever switched it.
  if (window.MutationObserver) new MutationObserver(() => { sync(); if (!on()) reset(); }).observe(root, {attributes: true, attributeFilter: ["class"]});
  if (reduceQuery && reduceQuery.addEventListener) reduceQuery.addEventListener("change", () => { sync(); if (!on()) reset(); });
  sync();

  // A still for a test or a screenshot: #tilt=4,-4 puts the world at those angles (it stays: no pointer, no motion).
  (function () {
    const found = /[#&]tilt=(-?[\d.]+),(-?[\d.]+)/.exec(location.hash || "");
    if (found) set(parseFloat(found[1]) || 0, parseFloat(found[2]) || 0, true);
  })();

  Object.assign(S, {step, kick, stop, reset, set, setMotion, on, motion: motionChosen, still: () => !on(), reduced, offer, frames: F});
  return S;
})();
