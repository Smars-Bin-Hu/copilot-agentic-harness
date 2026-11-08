// The Enter screen of a served page (1.6 B86): the wordmark HARNESS, the robot floating over its middle (in 3D, bot3d.js; flat when it cannot be), the pointer light, hold to charge, and the readiness list.
// A page on disk has none (no SERVE). The search and the settings are the global ones of shell.js; this screen adds nothing to the top but the greeting.
//
// Readiness: POST /api/ready every 3 s (a read; the server answers from caches and waits for nothing). Two blocks (1.7.38). Harness & Local is required: this copy is set up, this browser is paired, harness doctor has
// no error, VS Code is open, Copilot is connected. Enter is allowed only when every one is ok: the pill is disabled, the Enter key does nothing, and there is no way past it on this page.
// From the company is optional (knowledge base, instructions, company skills, code standards, tool packs, connections, code repositories): never a gate, but what is missing is said here with a link to the place that
// mends it, and again in the block of the board after Enter (readybar.js). The VS Code button is always beside Enter: Open, Restart, or Restart with identities (vsrestart.py).
// A check that cannot run shows as failed with its reason; a board that does not answer shows a line saying so and the screen goes on asking.
//
// Showing it: once for each tab session (sessionStorage, in try/catch), not on a poll, a reload of the board or a way back from a task. A task page opened from a link skips it only when everything
// is ready (the screen stays hidden for the first answers); when not, it shows the screen and the task is under it. The page below keeps loading its data while the screen is up.
//
// Hold to charge: particles stream into the pointer, a ring tightens, the letters heat up from the pointer outward, the screen trembles, the robot braces; on release a shockwave throws the
// letters outward, they snap back, and the screen flashes. A full charge is bigger than a half one. Canvas and transform only. Off under html.lite and prefers-reduced-motion.
"use strict";

(function () {
  if (typeof SERVE === "undefined" || !DATA.serve) return;
  const root = document.documentElement;
  const app = document.getElementById("app");
  const NS = "http://www.w3.org/2000/svg";
  const SEEN = "harness.entered";
  const POLL = 3000;
  const STEP = 140;  // ms between two lines lighting up
  const FIRST = 380;  // ms before the first one
  const HOLD_FULL = 1.5;  // seconds of holding for a full charge
  let memorySeen = false;
  const seen = () => { try { return sessionStorage.getItem(SEEN) === "1"; } catch (error) { return memorySeen; } };
  const remember = () => { memorySeen = true; try { sessionStorage.setItem(SEEN, "1"); } catch (error) { /* shown again on the next page: nothing can be kept */ } };
  if (seen()) return;

  const reduceQuery = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  const still = () => root.classList.contains("lite") || Boolean(reduceQuery && reduceQuery.matches);  // no motion at all: no loop, no charge
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  function el(name, attrs, parent) { const node = document.createElementNS(NS, name); for (const key in attrs) node.setAttribute(key, attrs[key]); if (parent) parent.append(node); return node; }

  // ---------- the wordmark: letters as strokes (no font to load) ----------
  const LETTERS = [
    ["H", "M12 12V88M138 12V88M12 50H138"],
    ["A", "M12 88L52 12H98L138 88M34 60H116"],
    ["R", "M12 88V12H104Q138 12 138 34V38Q138 58 104 58H12M82 58L138 88"],
    ["N", "M12 88V12L138 88V12"],
    ["E", "M138 12H12V88H138M12 50H116"],
    ["S", "M138 12H46Q12 12 12 31V32Q12 50 46 50H104Q138 50 138 68V69Q138 88 104 88H12"],
    ["S", "M138 12H46Q12 12 12 31V32Q12 50 46 50H104Q138 50 138 68V69Q138 88 104 88H12"],
  ];
  const LW = 150, GAP = 34, VBW = LETTERS.length * LW + (LETTERS.length - 1) * GAP, PATHS = [];
  const wm = {svg: null, gs: [], mgs: [], rimg: [], spot: null, st: [], x: .62, y: .4, raf: 0, last: 0, lastMove: 0, sx: .62, sy: .4, px: 0, py: 0, charge: 0, dirty: false, awake: false};

  // ---------- the screen ----------
  const name = String(DATA.serve.user || "").trim();
  const isTask = Boolean(DATA.desk);
  const hi = h("div", {class: "en-hi", title: name || null}, h("span", null, t("board.enter.hi")), h("b", null, name));
  const svg = el("svg", {id: "en-wm", class: "en-word", role: "img", "aria-label": "HARNESS"});
  const ref = el("svg", {class: "en-ref", "aria-hidden": "true"});
  const canvas = h("canvas", {id: "en-fx", "aria-hidden": "true"});
  const bot = h("div", {class: "en-bot", "aria-hidden": "true"});
  const say = h("div", {class: "en-say", "aria-hidden": "true"});
  const headText = h("span", null, t("board.enter.checking"));
  const getReady = h("button", {type: "button", class: "en-open en-getready", hidden: "hidden", title: t("board.enter.getready.tip")}, t("board.enter.getready"));  // beside "Not ready": the way to /setup (1.7.19)
  getReady.addEventListener("click", () => location.assign("/setup"));
  const head = h("div", {class: "en-chk-h h-check"}, h("i"), headText, getReady);
  const list = h("ul", {class: "en-chk-l"});
  const errLine = h("p", {class: "en-err", role: "status", hidden: "hidden"});
  const legal = h("p", {class: "en-legal"}, t("board.enter.legal", {copyright: t("board.copyright"), version: DATA.serve.version || ""}));
  const body = h("div", {class: "en-chk-body"}, head, list, errLine);  // the lines scroll here; the legal line below it stays in view (1.7.24)
  const chk = h("div", {class: "en-chk", "aria-live": "polite"}, body, legal);
  const go = h("button", {type: "button", class: "en-go", disabled: "disabled"}, h("span", null, t("board.enter.checking")), h("kbd", null, "↵"));
  const vsBtn = h("button", {type: "button", class: "en-vs", hidden: "hidden"}, t("board.enter.open"));  // always beside Enter: Open, Restart, or Restart with identities (1.7.38)
  const vsNote = h("p", {class: "en-vsnote", role: "status", hidden: "hidden"});  // beside the VS Code button: what a restart is doing, or why it did not end (1.7.38, C11 T2-07)
  const cta = h("div", {class: "en-cta"}, vsNote, vsBtn, go);
  const hint = h("div", {class: "en-cap en-hint"}, t("board.enter.hint"));
  const enter = h("div", {id: "enter", class: isTask ? "pending" : "", role: "dialog", tabindex: "-1", "aria-label": t("board.enter.label")},
    h("div", {class: "en-ground"}), h("div", {class: "en-top"}, name ? hi : null), h("div", {class: "en-stage"}, svg, ref), canvas, bot, say, h("div", {class: "en-foot"}, chk, cta, hint));
  document.body.append(enter);
  const stage = enter.querySelector(".en-stage");
  let open = true;
  let shown = !isTask;  // the screen is on view (a task page opened from a link keeps it hidden until it is known that it is needed)

  function buildWord() {
    svg.setAttribute("viewBox", "-30 -44 " + (VBW + 60) + " 188");
    const defs = el("defs", {}, svg);
    const metal = el("linearGradient", {id: "en-metal", gradientUnits: "userSpaceOnUse", x1: 0, y1: 0, x2: 0, y2: 100}, defs);
    el("stop", {offset: 0, "class": "en-m0"}, metal); el("stop", {offset: 1, "class": "en-m1"}, metal);
    wm.spot = el("radialGradient", {id: "en-spotg", gradientUnits: "userSpaceOnUse", cx: VBW / 2, cy: 30, r: 420}, defs);
    el("stop", {offset: 0, "class": "en-sp", "stop-opacity": 1}, wm.spot); el("stop", {offset: .45, "class": "en-sp", "stop-opacity": .38}, wm.spot); el("stop", {offset: 1, "class": "en-sp", "stop-opacity": 0}, wm.spot);
    const mask = el("mask", {id: "en-lm", maskUnits: "userSpaceOnUse", x: -30, y: -44, width: VBW + 60, height: 188}, defs);
    const main = el("g", {id: "en-wmg"}, svg), lt = el("g", {}, main);
    const rim = el("g", {}, lt), mt = el("g", {}, lt), mmask = el("g", {}, mask);
    LETTERS.forEach((letter, i) => {
      const x = i * (LW + GAP);
      PATHS[i] = new Path2D(letter[1]);
      [[rim, "rim", 27], [mt, "metal", 24], [mmask, "mask", 24]].forEach((part, k) => {
        const g = el("g", {"class": "lg", transform: "translate(" + x + ",0)", style: "--i:" + i + ";--x:" + x + "px"}, part[0]);
        const path = el("path", {d: letter[1], fill: "none", "stroke-linejoin": "miter", "stroke-miterlimit": 1.6, "stroke-width": part[2]}, g);
        if (part[1] === "rim") path.setAttribute("class", "en-rim"); else if (part[1] === "metal") path.setAttribute("stroke", "url(#en-metal)"); else path.setAttribute("stroke", "#fff");
        (k === 0 ? wm.rimg : k === 1 ? wm.gs : wm.mgs).push(g);
      });
    });
    el("rect", {x: -30, y: -44, width: VBW + 60, height: 188, fill: "url(#en-spotg)", mask: "url(#en-lm)"}, main);
    ref.setAttribute("viewBox", "-30 -44 " + (VBW + 60) + " 188");
    el("use", {href: "#en-wmg"}, ref);
    wm.st = LETTERS.map((letter, i) => ({cx: i * (LW + GAP) + LW / 2, x: 0, y: 0, r: 0, vx: 0, vy: 0, vr: 0, kick: -1, tx: 0, ty: 0, tr: 0}));
    wm.svg = svg;
  }
  const svgPt = (cx, cy) => { const m = svg.getScreenCTM(); if (!m) return null; const p = svg.createSVGPoint(); p.x = cx; p.y = cy; return p.matrixTransform(m.inverse()); };
  function applyLetters() {
    wm.st.forEach((s, i) => {
      const tr = "translate(" + (i * (LW + GAP) + s.x + s.tx).toFixed(2) + "," + (s.y + s.ty).toFixed(2) + ") rotate(" + (s.r + s.tr).toFixed(2) + " " + (LW / 2) + " 50)";
      wm.gs[i].setAttribute("transform", tr); wm.mgs[i].setAttribute("transform", tr); wm.rimg[i].setAttribute("transform", tr);
    });
  }

  // ---------- the robot: it floats over the N, the middle of the screen. No legs, no shadow ----------
  const MIDDLE = 3, FLOAT = 16;  // the letter, and how far over it
  const pose = {nx: 0, ny: 0, sleep: 1, arm: 0};
  let solid = null;
  function buildBot() {
    const r = el("svg", {viewBox: "0 0 100 106"});
    const armL = el("g", {"class": "r-arm r-l"}, r), armR = el("g", {"class": "r-arm r-r"}, r);
    el("rect", {x: 17, y: 62, width: 10, height: 26, rx: 5}, armL); el("rect", {x: 73, y: 62, width: 10, height: 26, rx: 5}, armR);
    el("rect", {"class": "r-body", x: 30, y: 56, width: 40, height: 42, rx: 13}, r); el("circle", {"class": "r-core", cx: 50, cy: 77, r: 6}, r);
    const headG = el("g", {"class": "r-headg"}, r);
    el("line", {"class": "r-ant", x1: 50, y1: 16, x2: 50, y2: 7}, headG); el("circle", {"class": "r-bulb", cx: 50, cy: 6, r: 3.2}, headG);
    el("rect", {"class": "r-head", x: 24, y: 16, width: 52, height: 42, rx: 15}, headG); el("rect", {"class": "r-visor", x: 31, y: 26, width: 38, height: 22, rx: 9}, headG);
    const eyes = el("g", {"class": "r-eyes"}, headG);
    el("circle", {"class": "r-eye", cx: 42, cy: 37, r: 4.2}, eyes); el("circle", {"class": "r-eye", cx: 58, cy: 37, r: 4.2}, eyes);
    bot.append(r);
    if (still() || typeof BOT3D === "undefined") return;
    solid = BOT3D.make(bot);
    if (solid) new MutationObserver(() => solid.colours()).observe(root, {attributes: true, attributeFilter: ["class", "data-theme"]});
  }
  function placeBot() {
    if (!open || !wm.gs.length) return;
    const r = wm.gs[MIDDLE].getBoundingClientRect();
    if (!r.width) return;
    const was = parseFloat(stage.style.top) || 0;
    const w = Math.max(96, Math.min(250, r.width * 1.55, (r.top - was - FLOAT - 62) / .965));
    // The robot must not run up under the search pill or the greeting: when the window is short, the whole wordmark moves down until the antenna is clear (the list below scrolls instead).
    const drop = Math.max(0, 62 - (r.top - was + 3 - FLOAT - .965 * w));
    if (Math.abs(drop - was) > .5) { stage.style.top = drop.toFixed(1) + "px"; stage.style.bottom = (-drop).toFixed(1) + "px"; }
    const top = r.top - was + drop;
    bot.style.width = w + "px";
    bot.style.left = (r.left + r.width * .5) + "px"; bot.style.top = (top + 3 - FLOAT) + "px";
    say.style.left = Math.min(innerWidth - 90, r.left + r.width * .5 + w * .3) + "px"; say.style.top = (top - FLOAT - w * .95) + "px";
  }
  function lookBot() {
    const b = bot.getBoundingClientRect(), cx = b.left + b.width / 2, cy = b.top + b.height * .35;
    const dx = (wm.px || cx) - cx, dy = (wm.py || cy) - cy, d = Math.max(60, Math.hypot(dx, dy)), nx = dx / d, ny = dy / d;
    bot.style.setProperty("--ex", (nx * 4).toFixed(2) + "px"); bot.style.setProperty("--ey", (ny * 3).toFixed(2) + "px"); bot.style.setProperty("--tilt", (nx * 7).toFixed(1) + "deg");
    pose.nx = nx; pose.ny = ny;
  }
  // The 3D robot turns with the whole picture, more than it (the angles of space.js), and its head and eyes follow the pointer. It wakes as the flat one does.
  function drawBot(now) {
    if (!solid) return;
    const turning = typeof SPACE !== "undefined" && SPACE.on(), angle = (degrees) => degrees * Math.PI / 180;
    pose.sleep += ((bot.classList.contains("awake") ? 0 : 1) - pose.sleep) * .08;
    pose.arm += ((bot.classList.contains("you") ? 2.6 + Math.sin(now / 130) * .3 : 0) - pose.arm) * .14;
    const shut = now % 5000 > 4780 ? .12 : 1;
    solid.draw({yaw: angle((turning ? SPACE.ay * 3.2 : 0) + Math.sin(now / 2100) * 2.5), pitch: angle((turning ? -SPACE.ax * 2 : 0) + 2), headYaw: pose.nx * .22, headPitch: pose.ny * .14 + pose.sleep * .16, roll: -pose.nx * .1 - pose.sleep * .07,
      arm: pose.arm, eyeX: pose.nx * 2.6, eyeY: -pose.ny * 2, blink: (1 - pose.sleep) * shut + pose.sleep * .1, glow: 1 - pose.sleep}, now);
  }
  let sayTimer = 0, clicks = 0;
  const wake = () => { if (bot.classList.contains("awake")) return; bot.classList.add("awake"); if (solid) solid.colours(); };
  function botSay(text) { say.textContent = text; say.classList.add("on"); clearTimeout(sayTimer); sayTimer = setTimeout(() => say.classList.remove("on"), 1900); }
  function hop() { if (still()) return; bot.classList.remove("hop"); void bot.offsetWidth; bot.classList.add("hop"); }
  bot.addEventListener("click", (event) => {
    event.stopPropagation(); wake(); clicks++; hop();
    bot.classList.add("you"); setTimeout(() => bot.classList.remove("you"), 1500);
    if (clicks % 5 === 0) { botSay(t("board.enter.party")); kickAll(0); } else botSay(t("board.enter.say." + (1 + Math.floor(Math.random() * 6))));
  });

  // ---------- hold to charge ----------
  // Everything is drawn from (hold time, release time, power) alone. Canvas + transforms only.
  const FX = {down: false, t0: 0, rel: null, seeds: [], w: 0, h: 0, dpr: 1, light: false, fx: [255, 214, 150], hot: [255, 170, 70], flash: [255, 255, 255]};
  (function () { let s = 11; const r = () => { s = (s * 16807) % 2147483647; return s / 2147483647; }; for (let i = 0; i < 190; i++) FX.seeds.push({a: r() * 6.283, R: 260 + r() * 560, p: r(), s: .6 + r() * .9, w: .7 + r() * 1.6}); })();
  const ctx = canvas.getContext ? canvas.getContext("2d") : null;
  function triple(name, fallback) {
    const parts = getComputedStyle(enter).getPropertyValue(name).split(",").map((x) => parseFloat(x));
    return parts.length === 3 && parts.every((x) => !isNaN(x)) ? parts : fallback;
  }
  function palette() {  // the light theme draws over a light page: normal blending with a warm ink; the dark one adds light
    FX.light = root.getAttribute("data-theme") === "light" && !root.classList.contains("has-wall");  // over a picture the screen is dark in both themes
    FX.fx = triple("--en-fx", FX.fx); FX.hot = triple("--en-hot", FX.hot); FX.flash = triple("--en-flash", FX.flash);
  }
  const fxOn = () => Boolean(ctx) && !still();
  function fxSize() {
    FX.dpr = Math.min(1.5, window.devicePixelRatio || 1); FX.w = innerWidth; FX.h = innerHeight;
    const w = Math.round(FX.w * FX.dpr), hh = Math.round(FX.h * FX.dpr);
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== hh) canvas.height = hh;
  }
  const ease = (x) => 1 - Math.pow(1 - x, 2.2);
  const rgba = (c, a) => "rgba(" + (c[0] | 0) + "," + (c[1] | 0) + "," + (c[2] | 0) + "," + a + ")";
  function letterCenters() { const m = svg.getScreenCTM(); return {m, c: wm.st.map((s) => ({x: m.a * s.cx + m.e, y: m.d * 50 + m.f}))}; }
  function throwLetters(relT, power, px, py) {
    const L = letterCenters();
    wm.st.forEach((s, i) => {
      if (relT < 0) { s.tx = s.ty = s.tr = 0; return; }
      const dx = L.c[i].x - px, dy = L.c[i].y - py, dist = Math.hypot(dx, dy) || 1, spd = 1100 + 700 * power, tau = relT - dist / spd;
      if (tau <= 0) { s.tx = s.ty = s.tr = 0; return; }
      const f = (tau / .15) * Math.exp(1 - tau / .15) * Math.exp(-tau * 1.4), A = 18 + 135 * Math.pow(power, 1.5);
      s.tx = dx / dist * A * f; s.ty = dy / dist * A * f * .6 - 14 * power * f; s.tr = (dx >= 0 ? 1 : -1) * 26 * power * f;
    });
  }
  function fxDraw(holdT, ch, relT, power, px, py) {
    const d = FX.dpr, add = !FX.light;
    ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, FX.w, FX.h);
    const L = letterCenters(), m = L.m;
    let maxD = 1;
    L.c.forEach((c) => { maxD = Math.max(maxD, Math.hypot(c.x - px, c.y - py)); });
    ctx.globalCompositeOperation = add ? "lighter" : "source-over"; ctx.lineCap = "round";
    const heatCh = relT < 0 ? ch : power * Math.max(0, 1 - relT * 1.25), k = add ? 1 : 1.5;
    if (relT < 0 && ch > .004) {
      const gr = ctx.createRadialGradient(px, py, 0, px, py, 70 + 300 * ch);
      gr.addColorStop(0, rgba(FX.fx, (.10 + .42 * ch) * (add ? 1 : .7))); gr.addColorStop(1, rgba(FX.fx, 0));
      ctx.fillStyle = gr; ctx.fillRect(px - 400, py - 400, 800, 800);
      const n = Math.floor(40 + 150 * ch);
      for (let i = 0; i < n; i++) {
        const s = FX.seeds[i], u = (holdT * .85 * s.s + s.p) % 1, r = s.R * Math.pow(1 - u, 1.9);
        if (r < 12) continue;
        const u2 = Math.max(0, u - .06), r2 = s.R * Math.pow(1 - u2, 1.9);
        ctx.strokeStyle = rgba([FX.fx[0], FX.fx[1] - 20 * ch, FX.fx[2] - 60 * ch], (Math.min(1, u * 6) * (.25 + .6 * ch) * (add ? 1 : 1.1)).toFixed(3));
        ctx.lineWidth = s.w * (.7 + ch) * k;
        ctx.beginPath(); ctx.moveTo(px + Math.cos(s.a) * r2, py + Math.sin(s.a) * r2); ctx.lineTo(px + Math.cos(s.a) * r, py + Math.sin(s.a) * r); ctx.stroke();
      }
      const rr = 300 - 268 * ease(ch);
      ctx.strokeStyle = rgba(add ? [255, 255, 255] : FX.hot, .14 + .6 * ch); ctx.lineWidth = 1.2 + 2.8 * ch; ctx.beginPath(); ctx.arc(px, py, rr, 0, 6.283); ctx.stroke();
      ctx.setLineDash([3, 11]); ctx.lineDashOffset = -holdT * 70; ctx.strokeStyle = rgba(FX.fx, .2 + .5 * ch); ctx.beginPath(); ctx.arc(px, py, rr + 16, 0, 6.283); ctx.stroke(); ctx.setLineDash([]);
    }
    if (heatCh > .01 && m) {  // the letters heat up, nearest to the pointer first
      ctx.save(); ctx.setTransform(d * m.a, 0, 0, d * m.d, d * m.e, d * m.f); ctx.lineWidth = 24; ctx.lineJoin = "miter"; ctx.miterLimit = 1.6; ctx.lineCap = "butt";
      for (let i = 0; i < wm.st.length; i++) {
        const thr = Math.hypot(L.c[i].x - px, L.c[i].y - py) / maxD * .62, heat = clamp((heatCh - thr) / .38, 0, 1);
        if (heat <= .01) continue;
        const s2 = wm.st[i];
        ctx.save(); ctx.translate(i * (LW + GAP) + s2.x + s2.tx + LW / 2, s2.y + s2.ty + 50); ctx.rotate((s2.r + s2.tr) * Math.PI / 180); ctx.translate(-LW / 2, -50);
        ctx.globalAlpha = .3 + .65 * heat;
        ctx.strokeStyle = add ? "rgb(255," + ((150 + 100 * heat) | 0) + "," + ((60 + 170 * heat) | 0) + ")" : rgba(FX.hot, 1);
        ctx.shadowColor = rgba(FX.hot, .95); ctx.shadowBlur = 30 * heat * d; ctx.stroke(PATHS[i]); ctx.restore();
      }
      ctx.restore();
    }
    if (relT >= 0) {  // the shockwave and the flash
      const R = (1100 + 700 * power) * relT, fade = Math.max(0, 1 - relT / 1.1);
      if (R > 4 && fade > 0) {
        const g2 = ctx.createRadialGradient(px, py, Math.max(0, R - 160 - 60 * power), px, py, R + 24);
        g2.addColorStop(0, rgba(FX.flash, 0)); g2.addColorStop(.86, rgba(FX.flash, (.2 * power * fade).toFixed(3))); g2.addColorStop(1, rgba(FX.flash, 0));
        ctx.fillStyle = g2; ctx.fillRect(0, 0, FX.w, FX.h);
        ctx.strokeStyle = rgba(add ? FX.flash : FX.hot, (.85 * fade).toFixed(3)); ctx.lineWidth = 3 + 16 * power * fade; ctx.beginPath(); ctx.arc(px, py, R, 0, 6.283); ctx.stroke();
        ctx.strokeStyle = rgba(FX.fx, (.5 * fade).toFixed(3)); ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(px, py, R * .93, 0, 6.283); ctx.stroke();
      }
      const fa = (.1 + .62 * power) * Math.exp(-relT * 9);
      if (fa > .004) { ctx.globalCompositeOperation = "source-over"; ctx.fillStyle = rgba(FX.flash, fa.toFixed(3)); ctx.fillRect(0, 0, FX.w, FX.h); }
    }
  }
  function fxClear() { if (ctx) { ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height); } }
  const trem = {x: 0, y: 0};
  // The wordmark tilts with the 3D space behind it (space.js, a little less than the world) and trembles while it charges.
  function stageApply() {
    let value = "";
    if (typeof SPACE !== "undefined" && SPACE.on() && (Math.abs(SPACE.ax) > .01 || Math.abs(SPACE.ay) > .01)) value = "perspective(1500px) rotateX(" + (SPACE.ax * .8).toFixed(3) + "deg) rotateY(" + (SPACE.ay * .8).toFixed(3) + "deg) ";
    if (trem.x || trem.y) value += "translate3d(" + trem.x.toFixed(2) + "px," + trem.y.toFixed(2) + "px,0)";
    if (stage.style.transform !== value) stage.style.transform = value;
  }
  function tremble(x, y) { trem.x = x; trem.y = y; stageApply(); }
  function botReact(ch, released) {
    bot.classList.toggle("brace", ch > .05 && !released); bot.style.setProperty("--sh", (ch * 2.6).toFixed(2) + "px");
    bot.classList.toggle("you", ch > .55 && !released);
  }
  function kickAll(fromX) { const now = performance.now(); wm.st.forEach((s) => { s.kick = now + Math.abs(s.cx - fromX) * .45; }); loop(); }
  function tick() {
    const now = performance.now();
    wm.raf = 0;
    if (!open || !shown || still()) return;
    const dt = Math.min(32, now - (wm.last || now));
    wm.last = now;
    if (typeof SPACE !== "undefined" && SPACE.on()) SPACE.step(now);  // the 3D space turns on this loop's frame: one frame callback for the whole page
    const idle = now - wm.lastMove > 2400 && !FX.down;
    let tx = wm.x, ty = wm.y;
    if (idle) { tx = .5 + Math.sin(now / 2300) * .28; ty = .38 + Math.cos(now / 3100) * .1; }
    wm.sx += (tx - wm.sx) * .16; wm.sy += (ty - wm.sy) * .16;
    const px = wm.sx * VBW, py = wm.sy * 100 - 20;
    let ch = 0, holdT = 0, relT = -1, power = 0;
    if (FX.down) { holdT = (now - FX.t0) / 1000; ch = clamp(holdT / HOLD_FULL, 0, 1); wm.charge = ch; } else wm.charge = Math.max(0, wm.charge - dt / 300);
    if (FX.rel) { relT = (now - FX.rel.t0) / 1000; power = FX.rel.power; if (relT > 1.5) { FX.rel = null; relT = -1; fxClear(); tremble(0, 0); } }
    wm.spot.setAttribute("cx", px.toFixed(1)); wm.spot.setAttribute("cy", py.toFixed(1)); wm.spot.setAttribute("r", (340 + 420 * wm.charge).toFixed(0));
    wm.st.forEach((s, i) => {  // letters: spring to the pointer push, plus kicks
      const dx = s.cx - px, dy = 50 - py, dist = Math.sqrt(dx * dx + dy * dy * .5), R = 260, f = dist < R && !idle ? Math.pow(1 - dist / R, 2) : 0;
      const tX = (dx >= 0 ? 1 : -1) * f * 22, tY = -f * 12, tR = (dx / R) * f * 7;
      if (s.kick >= 0 && now >= s.kick) { s.vy -= 9.5; s.vr += (i % 2 ? 1 : -1) * 1.6; s.kick = -1; }
      s.vx += (tX - s.x) * .09; s.vy += (tY - s.y) * .09; s.vr += (tR - s.r) * .09; s.vx *= .8; s.vy *= .8; s.vr *= .8; s.x += s.vx; s.y += s.vy; s.r += s.vr;
    });
    if (FX.down || FX.rel) {
      const at = FX.rel ? FX.rel : {x: wm.px || FX.w / 2, y: wm.py || FX.h / 2};
      if (FX.rel) { throwLetters(relT, power, at.x, at.y); const sh = 9 * power * Math.exp(-relT * 8); tremble(Math.sin(now / 23) * sh, Math.cos(now / 29) * sh * .6); }
      else { throwLetters(-1, 0, 0, 0); tremble(Math.sin(now / 17) * 3.2 * ch * ch, Math.cos(now / 23) * 2.2 * ch * ch); }
      fxDraw(holdT, ch, relT, power, at.x, at.y); botReact(ch, Boolean(FX.rel)); wm.dirty = true;
    } else if (wm.dirty) { wm.dirty = false; fxClear(); tremble(0, 0); botReact(0, false); throwLetters(-1, 0, 0, 0); }
    applyLetters(); lookBot(); drawBot(now);
    wm.raf = requestAnimationFrame(tick);
  }
  function loop() { if (!wm.raf && open && shown && !still() && !document.hidden) { wm.last = 0; wm.raf = requestAnimationFrame(tick); } }
  function bindPlay() {
    enter.addEventListener("pointermove", (event) => {
      const p = svgPt(event.clientX, event.clientY);
      if (!p) return;
      wm.x = clamp(p.x / VBW, 0, 1); wm.y = clamp((p.y + 44) / 188 * 1.6 - .2, 0, 1); wm.px = event.clientX; wm.py = event.clientY; wm.lastMove = performance.now();
      wake(); loop();
    });
    enter.addEventListener("pointerdown", (event) => {
      if (event.button || event.target.closest("button,.en-bot,.en-chk")) return;
      wm.px = event.clientX; wm.py = event.clientY;
      if (!fxOn()) return;
      try { enter.setPointerCapture(event.pointerId); } catch (error) { /* the release is then taken from the window */ }
      palette(); fxSize();
      FX.down = true; FX.t0 = performance.now(); FX.rel = null; wm.dirty = true; loop();
    });
    const up = () => {
      if (!FX.down) return;
      const held = (performance.now() - FX.t0) / 1000, power = clamp(held / HOLD_FULL, 0, 1);
      FX.down = false;
      if (held < .22) { fxClear(); tremble(0, 0); const p = svgPt(wm.px, wm.py); kickAll(p ? p.x : 0); return; }  // a quick click: the letters hop
      FX.rel = {t0: performance.now(), power: Math.max(.2, power), x: wm.px, y: wm.py}; hop(); botReact(0, true);
      botSay(power > .9 ? t("board.enter.boom") : t("board.enter.ping")); loop();
    };
    enter.addEventListener("pointerup", up); enter.addEventListener("pointercancel", up);
    window.addEventListener("blur", () => { if (FX.down) { FX.down = false; fxClear(); tremble(0, 0); botReact(0, false); } });
  }

  // ---------- readiness ----------
  // Two blocks (1.7.38). `/api/ready` gives `checks` (Harness & Local, all blocking) and `optional.items` (From the company, never blocking).
  const REQ = ["setup", "paired", "doctor", "vscode", "copilot"];
  const OPT = ["kb", "instructions", "skills", "standards", "packs", "connections", "repos"];
  const GROUPS = [["required", REQ], ["optional", OPT]];
  const ORDER = GROUPS.flatMap((group) => group[1]);
  const chk0 = {t0: 0, last: null, error: "", inflight: false, timer: 0, tick: 0, opened: 0, ready: false, restart: null, restarting: false, fail: ""};
  const OPENED_FOR = 120000;  // ms in which a VS Code that was just opened is waited for, not blamed
  const setText = (node, text) => { if (node.textContent !== text) node.textContent = text; };
  const setClass = (node, cls) => { if (node.className !== cls) node.className = cls; };
  const slot = (i) => chk0.t0 && Date.now() - chk0.t0 >= FIRST + i * STEP;
  function build() {
    for (const [group, ids] of GROUPS) {
      list.append(h("li", {class: "gh", "data-g": group}, h("i", {class: "ck"}), h("span", {class: "gh-t"}, t("board.enter.g." + group)), h("span", {class: "gh-tag"}), h("span", {class: "gh-n"})));
      for (const id of ids) list.append(h("li", {class: "row", "data-id": id, "data-g": group}, h("i", {class: "ck"}), h("span", {class: "t"}), h("em"), h("p", {class: "m", hidden: "hidden"})));
    }
  }
  const rowOf = (id) => list.querySelector('li.row[data-id="' + id + '"]');
  const word = (key, vals, fallback) => (Object.prototype.hasOwnProperty.call(TEXT, key) ? t(key, vals) : fallback || "");
  const langWord = () => { try { return new Intl.DisplayNames([root.lang], {type: "language"}).of(root.lang) || root.lang; } catch (error) { return root.lang; } };  // English, or the name of the language in itself
  const recentlyOpened = () => chk0.opened && Date.now() - chk0.opened < OPENED_FOR;
  const buttonKind = () => (chk0.last && chk0.last.vscode_button ? chk0.last.vscode_button.kind : "open");
  const buttonWords = () => (chk0.last && chk0.last.vscode_button ? chk0.last.vscode_button.label : t("board.enter.open"));
  // A line of the first block -> {state, level, tag, note, soft, tip}: a short word on the line; the long words in the note under it only where the person must do something.
  function reqView(c) {
    const id = c.id, vals = {n: c.n === undefined ? "" : c.n, detail: plainWords(c.detail || "")};
    let state = c.state, level = c.level || "grey", tag = "", note = "", tip = "";
    if (state === "fail" && id === "vscode" && c.why === "none" && recentlyOpened()) { state = "wait"; level = "yellow"; }
    if (state === "check") return {state, level: "grey", tag: "", note: "", soft: false, tip: ""};
    if (state === "ok") {
      tag = id === "setup" ? [String(DATA.serve.user || "").trim(), langWord()].filter(Boolean).join(" · ") : id === "vscode" && c.env_wrong ? t("board.enter.d.vscode.noenv") : t("board.enter.d." + id + ".ok", vals);
      if (id === "vscode" && c.env_wrong) note = t("board.enter.m.vscode.noenv");
      return {state, level, tag, note, soft: true, tip};
    }
    if (state === "wait") tag = id === "copilot" ? t("board.enter.d.copilot.vscode") : t("board.enter.tag.wait");
    else if (id === "paired") tag = t("board.enter.d.paired.unpaired");
    else if (id === "doctor") tag = c.why === "failed" ? t("board.enter.d.doctor.failed") : t(c.n === 1 ? "board.enter.d.doctor.errors.one" : "board.enter.d.doctor.errors", vals);
    else if (id === "vscode") tag = c.why === "none" ? t("board.enter.d.vscode.none") : c.why === "env" ? t("board.enter.d.vscode.noenv") : c.why === "unseen" ? t("board.enter.d.vscode.unseen") : t("board.enter.d.vscode.stuck");
    else if (id === "copilot") tag = c.why === "vscode" ? t("board.enter.d.copilot.vscode") : t("board.enter.d.copilot.fail");
    else tag = t("board.enter.tag.fail");
    if (id === "setup") note = word("board.enter.m.setup." + c.why, vals);
    else if (id === "paired") note = t("board.enter.m.paired.unpaired");
    else if (id === "doctor") note = word("board.enter.m.doctor." + c.why + (c.why === "errors" && c.n === 1 ? ".one" : ""), vals, plainWords(c.detail || ""));
    else if (id === "vscode") note = c.why === "none" && recentlyOpened() ? t("board.enter.m.vscode.opened") : c.why === "none" ? t("board.enter.m.vscode.none", {button: buttonWords()})
      : c.why === "env" || c.why === "unseen" ? t("board.enter.m.vscode." + c.why, {button: buttonWords()}) + (c.detail ? " " + t("board.enter.m.vscode.missing", {detail: plainWords(c.detail)}) : "")  // connected, but not started with this copy's settings (Q2)
      : word("board.enter.m.vscode." + c.why, vals);
    else if (id === "copilot" && c.why !== "vscode") note = word("board.enter.m.copilot." + c.why, vals);
    return {state, level, tag, note, soft: state === "wait", tip};
  }
  // An item of the second block -> {state, level, tag, notes: [{text, fix}], tip}. The note is what the problems of the row say, with a link each to where it is mended.
  function optView(c) {
    const level = c.state === "ok" ? "ok" : c.state === "yellow" ? "yellow" : "grey";
    const notes = (c.problems || []).filter((problem) => problem.short).map((problem) => ({text: problem.short, fix: problem.fix}));
    return {state: c.state === "ok" ? "ok" : "note", level, tag: c.detail || "", notes, tip: c.tip || ""};
  }
  // Names with a dot each (tool packs, connections): one line, "+N" for those that do not fit; the table of environments, states, reasons and times of the connections is a window on hover (1.7.19).
  // A name is never cut: the first one wraps when it alone is wider than the line.
  const pop = h("div", {class: "en-pop", hidden: "hidden", role: "tooltip"});
  let popTimer = 0, popFor = null;
  const ago = (stamp) => {
    const date = new Date(stamp || "");
    if (!stamp || isNaN(date.getTime())) return t("board.enter.sys.never");
    const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000);
    return seconds < 60 ? t("board.enter.sys.now") : seconds < 3600 ? t("board.enter.sys.min", {n: Math.floor(seconds / 60)}) : seconds < 86400 ? t("board.enter.sys.hour", {n: Math.floor(seconds / 3600)}) : t("board.enter.sys.day", {n: Math.floor(seconds / 86400)});
  };
  const itemOf = (key) => (chk0.last && chk0.last.optional ? chk0.last.optional.items.find((x) => x.key === key) : null);
  function popTable(c) {
    const head = ["system", "env", "status", "reason", "checked", "pack"].map((key) => h("th", null, t("board.enter.sys.col." + key)));
    const body = [];
    let last = null;
    for (const row of c.rows || []) {
      const first = row.system !== last;
      last = row.system;
      body.push(h("tr", {class: first ? "first" : ""}, h("td", {class: "sy-n"}, first ? row.system : ""), h("td", {class: "sy-e"}, row.env && row.env !== "none" ? row.env.toUpperCase() : ""),
        h("td", {class: "sy-s " + row.state}, h("i", {class: "sy-d " + row.state}), t("board.enter.sys.state." + row.state)), h("td", {class: "sy-r"}, row.reason || ""),
        h("td", {class: "sy-t"}, row.state === "unknown" ? t("board.enter.sys.never") : ago(row.at)), h("td", {class: "sy-p"}, first ? row.pack || "" : "")));
    }
    return h("div", {class: "en-pop-in"}, h("table", null, h("thead", null, h("tr", null, ...head)), h("tbody", null, ...body)), c.off ? h("p", {class: "sy-off"}, c.off.text) : null);  // the connections whose tool pack is off are not in the table (1.7.38)
  }
  const fillPop = (c) => { pop.replaceChildren(popTable(c)); };
  function markScroll(c) {  // more rows than the window holds: it says so, and how many there are
    const inner = pop.firstChild;
    if (inner && inner.scrollHeight > inner.clientHeight + 2) inner.append(h("p", {class: "sy-scroll"}, t("board.enter.sys.scroll", {n: new Set(c.rows.map((row) => row.system)).size})));
  }
  function popShow(li) {
    const c = itemOf("connections");
    if (!c || !c.rows || !c.rows.length) return;
    clearTimeout(popTimer); popFor = li;
    fillPop(c);
    pop.hidden = false;
    markScroll(c);
    const r = li.getBoundingClientRect(), w = pop.offsetWidth, ph = pop.offsetHeight;
    pop.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + "px";
    pop.style.top = (r.top - ph - 6 > 8 ? r.top - ph - 6 : Math.min(innerHeight - ph - 8, r.bottom + 6)) + "px";
  }
  const popHide = (later) => { clearTimeout(popTimer); popTimer = setTimeout(() => { pop.hidden = true; popFor = null; }, later ? 250 : 0); };
  document.body.append(pop);
  pop.addEventListener("mouseenter", () => clearTimeout(popTimer));
  pop.addEventListener("mouseleave", () => popHide(true));
  function fitNames(sy) {  // show the names that fit on one line, "+N" for the rest
    const items = [...sy.querySelectorAll(".sy-i")], more = sy.querySelector(".sy-more");
    items.forEach((item) => { item.hidden = false; });
    more.hidden = true;
    if (!sy.clientWidth) return;
    const room = sy.clientWidth, size = (item) => Math.min(item.offsetWidth, room) + 10;
    const place = (limit) => {  // one by one, in order: a name that does not fit is skipped and the next, shorter one may still go in; the first stays, whole
      const keep = new Set();
      let used = 0;
      items.forEach((item, index) => { if (!index || used + size(item) <= limit) { keep.add(index); used += size(item); } });
      return keep;
    };
    let keep = place(room + 10);
    if (keep.size < items.length) keep = place(room - 34);  // room kept for "+N"
    if (keep.size === items.length) return;
    items.forEach((item, index) => { item.hidden = !keep.has(index); });
    more.textContent = "+" + (items.length - keep.size); more.hidden = false;
    more.title = items.filter((item, index) => !keep.has(index)).map((item) => item.textContent).join(", ");
  }
  const DOT = {ok: "ok", need: "partly", down: "partly", none: "none", untested: "unknown"};  // the state of a pack or a connection -> the class of its dot
  function names(li, c, hover) {
    let sy = li.querySelector(".sy");
    if (!sy) {
      sy = h("div", {class: "sy", tabindex: "0"});
      li.append(sy);
      if (hover) { li.addEventListener("mouseenter", () => popShow(li)); li.addEventListener("mouseleave", () => popHide(true)); sy.addEventListener("focus", () => popShow(li)); sy.addEventListener("blur", () => popHide(false)); }
    }
    sy.setAttribute("aria-label", t("board.enter.t." + c.key));
    const key = JSON.stringify([c.names, root.lang]);
    if (sy.dataset.k !== key) {
      sy.dataset.k = key;
      const title = (item) => (hover ? "" : c.key === "packs" ? (item.state === "ok" ? "" : t("machine.conn.notusable", {programs: item.missing || ""})) : t("board.enter.cs." + item.state));  // the connections row has its window on hover: a second bubble beside it covered the lines below (C12 N7)
      sy.replaceChildren(...c.names.map((item) => h("span", {class: "sy-i", title: title(item)}, h("i", {class: "sy-d " + (DOT[item.state] || "unknown")}), item.name)), h("span", {class: "sy-more", hidden: ""}));
    }
    fitNames(sy);
    if (hover && popFor === li && !pop.hidden) { fillPop(c); markScroll(c); }  // an open window follows the new answer
  }
  const noNames = (li) => { const sy = li.querySelector(".sy"); if (sy) sy.remove(); };

  // The words of a restart that is going on: the VS Code line says so, and the button waits.
  function showRestart(view, willOpen) { chk0.restart = view; if (view.state === "done" && willOpen !== false) chk0.opened = Date.now(); render(); }
  const optionalCount = () => (chk0.last && chk0.last.optional ? chk0.last.optional.count : 0);
  function render() {  // in place: the lines are made once and only their class and text change, so nothing blinks
    if (!list.children.length) build();
    const data = chk0.last, checks = data ? data.checks : [], optional = data && data.optional ? data.optional : null;
    let all = Boolean(data), pending = false, anyCheck = false, missing = 0;
    ORDER.forEach((id, i) => {
      const li = rowOf(id), req = i < REQ.length;
      const c = req ? checks.find((x) => x.id === id) : optional && optional.items.find((x) => x.key === id);
      const lit = c && slot(i);
      const view = !lit ? {state: "check", level: "", tag: "", note: "", notes: [], soft: false, tip: ""} : req ? reqView(c) : optView(c);
      if (req && view.state !== "ok") { all = false; if (lit && view.state !== "check") missing += 1; }
      if (view.state === "check") { anyCheck = true; if (!c || req || !lit) pending = true; }
      setClass(li, "row s-" + view.state + (view.level ? " l-" + view.level : "") + (req ? " blocks" : " warns") + (!req && c && ((c.home && c.home.to) || (c.fix && c.fix.to)) ? " has-fix" : "") + (!req && c && c.names && c.names.length ? " has-names" : ""));
      setText(li.querySelector(".t"), t("board.enter.t." + id));
      const em = li.querySelector("em");
      li.title = id === "connections" && c && c.rows && c.rows.length ? "" : view.tip || "";  // the hover table has the same sentence at its foot: not a second bubble beside it
      li.dataset.fix = !req && c && ((c.home && c.home.to) || (c.fix && c.fix.to)) ? "1" : "";
      if (!req && c && c.names && c.names.length) { setText(em, ""); names(li, c, id === "connections"); } else { noNames(li); setText(em, view.tag || (view.state === "check" ? "" : "—")); }
      const p = li.querySelector(".m");
      const keyNote = JSON.stringify([view.note, (view.notes || []).map((n) => [n.text, n.fix && n.fix.label]), id === "vscode" ? [chk0.restart && chk0.restart.state, chk0.restart && chk0.restart.why, chk0.fail] : "", c && c.launch, root.lang]);
      let note = view.note, soft = view.soft;
      if (id === "vscode") {
        const live = chk0.restart && (chk0.restart.state === "quitting" || chk0.restart.state === "opening");
        const lost = chk0.restart && chk0.restart.state === "failed" && (view.state !== "ok" || (chk0.restart.since || 0) < 120);  // a VS Code that did not quit is still open: the failure is told for two minutes, and for as long as VS Code is not ok
        const failed = Boolean(chk0.fail) || lost;
        const said = failed ? (chk0.fail || READY.restartNote(chk0.restart)) : live ? READY.restartNote(chk0.restart) : "";
        if (said) { note = said; soft = !failed; }
      }
      const has = Boolean(note) || Boolean((view.notes || []).length) || Boolean(!req && c && c.launch);
      if (has) {
        if (p.dataset.k !== keyNote) {
          p.dataset.k = keyNote;
          const nodes = [];
          if (note) nodes.push(note);
          if ((view.notes || []).length) {
            const gap = root.lang === "zh" ? "" : " ";  // a Chinese sentence ends in a full stop: no space after it (C12 N11)
            nodes.push(view.notes.map((n) => n.text).join(gap));
            const seen = new Set();
            const links = view.notes.map((n) => n.fix).filter((fix) => { if (!fix || !fix.to || seen.has(fix.label)) return false; seen.add(fix.label); return true; });
            links.forEach((fix, index) => nodes.push(index ? " · " : gap, READY.link(fix, {done: () => poll(), onState: showRestart, opened: () => { chk0.opened = Date.now(); }, fail: (error) => { chk0.fail = error.message; render(); }}, fix.short || fix.label)));
          }
          if (!req && c && c.launch) { const b = h("button", {type: "button", class: "en-open", "data-launch": "1"}, t("board.enter.launch")); nodes.push(h("br"), t("board.enter.m.systems.launch"), h("br"), b); }
          p.replaceChildren(...nodes);
        }
        setClass(p, "m" + (soft ? " soft" : "") + (req && view.state === "fail" ? " bad" : "")); if (p.hidden) p.hidden = false;
      } else if (!p.hidden) { p.hidden = true; p.dataset.k = ""; }
    });
    const down = Boolean(chk0.error);
    if (down && all) all = false;
    errLine.hidden = !down; setText(errLine, down ? t("board.enter.noanswer", {error: chk0.error}) : "");
    const ready = all && !pending && !down && slot(ORDER.length - 1);
    chk0.ready = ready;
    root.classList.toggle("en-notready", !ready && !pending);  // the reflection of the wordmark goes when the list has something to say (1.7.29)
    const looks = optionalCount(), noKb = Boolean(optional) && !optional.kb;
    const mood = pending ? "h-check" : !ready ? "h-bad" : looks || noKb ? "h-warn" : "h-ok";
    setClass(head, "en-chk-h " + mood);
    setText(headText, pending ? t("board.enter.checking") : !ready ? t("board.enter.notready") : noKb ? t("board.enter.ready.nokb") : looks ? t("board.enter.ready.look", {n: looks}) : t("board.enter.ready"));
    // the two block heads: the name, a tag (REQUIRED, OPTIONAL) with what is missing or to look at, and, folded, a summary
    const reqMissing = ORDER.slice(0, REQ.length).filter((id) => { const c = checks.find((x) => x.id === id); return c && c.state !== "ok" && c.state !== "check"; }).length;
    const tags = {required: t("board.enter.tag.required") + (reqMissing ? " · " + t("board.enter.tag.missing", {n: reqMissing}) : ""), optional: t("board.enter.tag.optional") + (looks ? " · " + t("board.enter.tag.look", {n: looks}) : "")};
    const dots = {required: !data || pending ? "grey" : reqMissing ? "red" : "ok", optional: !data ? "grey" : looks ? "yellow" : "ok"};
    list.querySelectorAll("li.gh").forEach((gh) => {
      const group = gh.dataset.g;
      setText(gh.querySelector(".gh-tag"), tags[group]);
      setClass(gh, "gh l-" + dots[group]);
      setText(gh.querySelector(".gh-n"), group === "required" ? t("board.enter.fold.required", {n: REQ.length - reqMissing, total: REQ.length}) : foldWords(optional));
    });
    // every line green: the list folds into one line a block; hover or a click unfolds it
    const folded = ready && !looks && !noKb && !anyCheck;
    list.classList.toggle("folded", folded);
    const missingSetup = checks.find((x) => x.id === "setup");
    chk0.setup = Boolean(missingSetup && missingSetup.state !== "ok" && missingSetup.state !== "wait");  // a new copy: the button goes to Get ready, whatever the other lines say
    chk0.sec = chk0.setup ? "you" : "";
    go.disabled = !(ready || chk0.setup);
    const offer = !ready && !pending && !chk0.setup && checks.some((x) => x.id === "paired" && x.state !== "ok");  // not paired: Get ready is still one click away
    if (getReady.hidden === offer) getReady.hidden = !offer;
    const first = (REQ.map((id) => checks.find((x) => x.id === id)).find((x) => x && x.state !== "ok" && x.state !== "check") || {}).id;
    const tip = ready ? "" : (first ? t("board.enter.t." + first) + ": " + (rowOf(first).querySelector("em").textContent || "") : down ? errLine.textContent : t("board.enter.checking"));
    if (go.title !== tip) go.title = tip.length > 400 ? tip.slice(0, 399) + "…" : tip;
    setText(go.firstChild, chk0.setup ? t("board.enter.getready") : ready ? t("board.enter.go") : pending ? t("board.enter.checking") : t("board.enter.notready"));
    const k = go.querySelector("kbd").style, kd = ready ? "" : "none"; if (k.display !== kd) k.display = kd;
    go.classList.toggle("plain", !ready);  // no key beside the word: it stands in the middle
    paintButton(ready, checks);
    fitList();
    return ready;
  }
  // The folded summary of the second block: the knowledge base, the packs and the sign-ins, as far as there are any.
  function foldWords(optional) {
    if (!optional) return "";
    const by = (key) => optional.items.find((x) => x.key === key) || {};
    const kb = (by("kb").detail || "").split(" · ")[0];
    const packs = (by("packs").names || []).length, signed = (by("connections").names || []).filter((x) => x.state === "ok").length;
    return [kb, packs ? t(packs === 1 ? "board.enter.fold.pack" : "board.enter.fold.packs", {n: packs}) : "", signed ? t("board.enter.fold.signed", {n: signed}) : ""].filter(Boolean).join(" · ");
  }
  // The VS Code button: its words come from the server (Open, Restart, Restart with identities); it is the main button of the screen while VS Code is the line that is not ok.
  function paintButton(ready, checks) {
    const live = Boolean(chk0.restart && (chk0.restart.state === "quitting" || chk0.restart.state === "opening"));
    const going = chk0.restarting || live;
    if (!chk0.last) { vsBtn.hidden = true; vsNote.hidden = true; return; }
    const vs = checks.find((x) => x.id === "vscode");
    const up = chk0.last.vscode_button && chk0.last.vscode_button.up;
    const lost = Boolean(chk0.restart && chk0.restart.state === "failed" && ((vs && vs.state !== "ok") || (chk0.restart.since || 0) < 120));  // the same two minutes as the VS Code line
    const failed = !live && (Boolean(chk0.fail) || lost);
    const said = live ? READY.restartNote(chk0.restart) : failed ? (chk0.fail || READY.restartNote(chk0.restart)) : "";  // the label says Quitting only once the board is quitting: a question about a working agent comes first
    setText(vsBtn, live ? t(chk0.restart.state === "opening" ? "board.enter.opening" : "board.enter.vs.quitting") : failed && !chk0.restarting ? t("board.enter.vs.again") : buttonWords());
    setText(vsNote, said);
    vsNote.hidden = !said;
    vsNote.classList.toggle("bad", failed);
    vsBtn.hidden = Boolean(up && vs && vs.state === "ok" && !going && !failed && !said);  // VS Code runs with this copy's settings and nothing is going on: nothing to press, and a button that need not be pressed made people stop and wonder (C12 N15)
    vsBtn.disabled = going;
    vsBtn.classList.toggle("hot", !ready && !chk0.setup && Boolean(vs) && vs.state !== "ok");
    vsBtn.title = going ? "" : t(up ? "board.enter.vs.restart.tip" : "board.enter.vs.open.tip");
  }
  function fitList() {  // a short window: the list scrolls inside the room under the wordmark instead of running into it
    const wr = svg.getBoundingClientRect();
    if (!wr.height) return;
    const stacked = matchMedia("(max-width:1100px)").matches;  // the pill is above the list then (enter.css)
    const room = Math.max(150, innerHeight - (wr.bottom + 16) - 44 - (stacked ? go.offsetHeight + 14 : 0));
    const value = Math.round(room) + "px";
    if (chk.style.getPropertyValue("--chk-max") !== value) chk.style.setProperty("--chk-max", value);
    markMore();
  }
  function markMore() {  // lines below the box edge: a fade at the foot says "scroll" (the buttons and the systems row can be down there)
    const more = body.scrollHeight - body.scrollTop - body.clientHeight > 2;
    if (chk.classList.contains("more") !== more) chk.classList.toggle("more", more);
  }
  body.addEventListener("scroll", markMore, {passive: true});

  const ask = (path, body) => SERVE.call(path, body, 8);  // a POST with a deadline (serve.js): the same headers and cookie as every other call
  function poll() {
    if (!open || chk0.inflight || document.hidden) return;
    chk0.inflight = true;
    ask("/api/ready", {}).then((data) => { if (Array.isArray(data.checks)) { chk0.last = data; chk0.error = ""; if (data.restart && !chk0.restarting) chk0.restart = data.restart; } else chk0.error = "bad answer"; },
      (error) => { chk0.error = String(error.message || error).slice(0, 200); })
      .then(() => {
        chk0.inflight = false; settle();
        // A line the server does not know yet (the one doctor run) is asked again after a second, not at the next 3 s poll. Still one cheap read.
        if (open && chk0.last && chk0.last.checks.some((c) => c.state === "check")) { clearTimeout(chk0.soon); chk0.soon = setTimeout(poll, 1000); }
      });
  }
  let pendingUntil = isTask ? Date.now() + 2500 : 0;
  function settle() {  // after each answer
    if (!open) return;
    const ready = render();
    if (!shown) {  // a task page opened from a link: skip when ready, show when something needs the person, wait a moment while it is only checking
      if (ready) { finish(true); return; }
      const needs = chk0.last && chk0.last.checks.some((c) => c.blocking && (c.state === "fail" || c.state === "wait"));
      if (needs || chk0.error || Date.now() >= pendingUntil) reveal();
    }
  }
  function reveal() {
    if (shown || !open) return;
    shown = true; enter.classList.remove("pending");
    chk0.t0 = Date.now(); render();
    present(true);
  }
  // The greeting sits in the corner and the search pill to its left: how far left depends on the name.
  function roomForHi() { if (name && hi.isConnected) root.style.setProperty("--en-hi", (hi.offsetWidth + 40) + "px"); }
  function present(play) {
    palette(); fxSize(); app.inert = true; root.classList.add("en-open");
    roomForHi();
    if (typeof SPACE !== "undefined") { SPACE.hosted = () => Boolean(wm.raf); SPACE.onTilt = stageApply; }
    if (play && !still()) { void enter.offsetWidth; enter.classList.add("intro"); }
    placeBot(); render(); loop();
    setTimeout(placeBot, 60); setTimeout(() => { if (open && shown) wake(); }, 1500);
    try { enter.focus({preventScroll: true}); } catch (error) { /* no focus */ }
  }
  function finish(quick) {  // the screen goes; the page under it was never held back
    if (!open) return;
    open = false; remember(); pop.remove();
    clearInterval(chk0.timer); clearInterval(chk0.tick); clearTimeout(chk0.soon); cancelAnimationFrame(wm.raf); wm.raf = 0; FX.down = false; FX.rel = null; fxClear(); tremble(0, 0);
    app.inert = false; root.classList.remove("en-open");
    if (typeof SPACE !== "undefined") { SPACE.hosted = null; SPACE.onTilt = null; SPACE.set(SPACE.tx / 2, SPACE.ty / 2); }
    stage.style.transform = "";
    if (quick || still()) { enter.remove(); return; }
    enter.classList.add("out"); setTimeout(() => enter.remove(), 450);
  }
  function tryEnter() {
    if (open && shown && chk0.setup) { location.assign("/setup?first=1&sec=" + (chk0.sec || "you")); return true; }
    if (open && shown && chk0.ready) { finish(false); return true; }
    return false;
  }

  list.addEventListener("click", (event) => { if (list.classList.contains("folded") && !event.target.closest("button, .row.has-fix .t")) list.classList.toggle("unfold"); });  // a folded list opens on a click as well as on hover
  list.addEventListener("click", (event) => {  // the name of an optional row opens the place that mends it (a window of Tools, the setup form, the knowledge base)
    const name = event.target.closest(".row.has-fix .t");
    if (!name) return;  // 1.7.38: a folded list shows no row, so a name that was clicked is one of an unfolded list (hover or a click): it opens its window
    const item = itemOf(name.closest("li").dataset.id);
    const to = item && ((item.home && item.home.to) ? item.home : item.fix);  // the row's own window; a note's link leads to the fix (1.7.38)
    if (to) READY.go(to, {done: () => poll()});
  });
  list.addEventListener("click", (event) => {  // Windows: the company's launch script asks for the identity in a window of its own and starts VS Code with it (1.7.9)
    const button = event.target.closest("[data-launch]");
    if (!button || button.disabled) return;
    button.disabled = true;
    ask("/api/launch", {}).then(() => { button.textContent = t("board.enter.launched"); }, (error) => { button.disabled = false; button.textContent = error.message; });
  });
  // The VS Code button (1.7.38): Open when none runs, Restart when one does, Restart with identities when a sign-in is saved and its test passed. The board asks VS Code to quit the normal way and waits; it never kills it.
  vsBtn.addEventListener("click", () => {
    if (vsBtn.disabled) return;
    chk0.fail = ""; chk0.restarting = true; render();
    READY.vsAct(buttonKind(), {onState: showRestart, opened: () => { chk0.opened = Date.now(); setTimeout(poll, 1500); }})
      .catch((error) => { if (!error.quiet) chk0.fail = error.message || String(error); })
      .then(() => { chk0.restarting = false; poll(); render(); });
  });
  go.addEventListener("click", () => { tryEnter(); });
  document.addEventListener("keydown", (event) => {
    if (!open || !shown || event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || event.isComposing) return;
    if (typeof SHELL !== "undefined" && SHELL.isOpen()) return;  // the palette or the settings own the keys
    if (document.body.classList.contains("has-dialog")) return;  // a window opened from the dock over this screen owns the keys (1.7.32)
    if (["Shift", "Control", "Alt", "Meta", "Tab", "Escape", "CapsLock", "Dead", "Process"].includes(event.key) || /^F\d+$/.test(event.key)) return;
    const target = event.target;
    if (target && target.closest && target.closest("input,textarea,select,[contenteditable='true'],.en-vs,.en-link,[data-launch]")) return;
    if (document.querySelector(".dock-panel:not([hidden])")) return;  // the ? panel is open: its words are read, its text is typed in (1.7.34)
    if (target && target.closest && target.closest(".dock-btn") && (event.key === "Enter" || event.key === " ")) return;  // a dock button keeps its own Enter and Space; after its window closed, any other key goes in
    if (tryEnter()) event.preventDefault();  // any key goes in, but only when everything is ready
  });

  // ---------- start ----------
  buildWord(); buildBot(); bindPlay(); wm.spot.setAttribute("cx", (VBW * .62).toFixed(1));
  window.addEventListener("resize", () => { placeBot(); fxSize(); fitList(); roomForHi(); list.querySelectorAll(".sy").forEach(fitNames); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) return; poll(); loop(); });
  chk0.t0 = Date.now();
  if (shown) present(true); else render();
  if (!shown) setTimeout(() => { if (!shown && open) settle(); }, 2600);  // a board that does not answer must not hide the screen for ever
  // The pairing code of the address is traded by serve.js first (SERVE.ready); a poll before it would say "not paired". A slow pairing is not waited for longer than 4 s.
  Promise.race([SERVE.ready, new Promise((done) => setTimeout(done, 4000))]).then(() => {
    if (!open) return;
    poll();
    chk0.timer = setInterval(poll, POLL);
    chk0.tick = setInterval(() => { if (open && shown) render(); }, 120);  // the lines light up in order
  });
})();
