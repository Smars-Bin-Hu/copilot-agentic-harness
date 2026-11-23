// The Enter screen of a served page (1.6 B86): the wordmark HARNESS, the robot floating over its middle (in 3D, bot3d.js; flat when it cannot be), the pointer light, hold to charge, and one button.
// A page on disk has none (no SERVE). The search and the settings are the global ones of shell.js; this screen adds nothing to the top but the greeting.
//
// The button (1.8.x, O3): `POST /api/ready` every 3 s (a read; the server answers from caches and waits for nothing) gives `button`: its kind (enter, setup, program, doctor, signin, signing, preparing, restart-host, wait, check, pair), its label in the
// person's language and what the kind needs (the code of the sign-in, the percent of the host's download, the reason a host stopped). The screen has no list: what is missing is said in the setup page (/setup), the gear's dot (`notes`) and the block of the board
// after Enter (readybar.js). A board that does not answer shows a line saying so and the screen goes on asking.
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
  const KEEP_READY = 120 * Math.max(1, Number(DATA.pace) || 1);  // 1.8.13: seconds a ready answer still counts while the board answers late
  const legal = h("p", {class: "en-legal"}, t("board.enter.legal", {copyright: t("board.copyright"), version: DATA.serve.version || ""}));
  const label = h("span", {class: "en-lab"}, t("board.enter.checking"));
  const fill = h("i", {class: "en-fill", "aria-hidden": "true"});  // the progress of `preparing`, drawn inside the button
  const goSpin = h("i", {class: "en-spin", "aria-hidden": "true", hidden: "hidden"});
  const kbd = h("kbd", null, "\u21b5");
  const go = h("button", {type: "button", class: "en-go k-check plain off", disabled: "disabled"}, fill, goSpin, label, kbd);  // the one button; its kind comes from /api/ready (`button`)
  const card = h("div", {class: "en-card", role: "status", hidden: "hidden"});  // above the button: the one-time code of the sign-in, or the problems of doctor
  const subDot = h("i", {class: "en-dot", hidden: "hidden"}), subText = h("span");
  const sub = h("div", {class: "en-sub", hidden: "hidden"}, subDot, subText);  // under the button: one short line
  const errLine = h("p", {class: "en-err", role: "status", hidden: "hidden"});
  const cta = h("div", {class: "en-cta", "aria-live": "polite"}, card, go, sub, errLine);
  const hint = h("div", {class: "en-cap en-hint"}, t("board.enter.hint"));
  const enter = h("div", {id: "enter", class: isTask ? "pending" : "", role: "dialog", tabindex: "-1", "aria-label": t("board.enter.label")},
    h("div", {class: "en-ground"}), h("div", {class: "en-top"}, name ? hi : null), h("div", {class: "en-stage"}, svg, ref), canvas, bot, say, h("div", {class: "en-foot"}, legal, cta, hint));
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
      arm: pose.arm, eyeX: pose.nx * 2.6, eyeY: -pose.ny * 2, blink: (1 - pose.sleep) * shut + pose.sleep * .1, glow: 1 - pose.sleep});
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
    FX.light = root.getAttribute("data-theme") === "light";
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
      if (event.button || event.target.closest("button,.en-bot,.en-card")) return;
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

  // ---------- readiness: one button ----------
  // `/api/ready` gives `button` (O1): {kind, label, off, code, url, left, percent, program, download, detail, n}. The label is already in the person's language. The screen is the wordmark, the robot and this button;
  // the lists of what is set up live in the setup page (/setup) and the gear (dock.js), not here. An older server that has no `button` yet: `enter` when `ready`, else `check`.
  const chk0 = {t0: 0, last: null, at: 0, error: "", inflight: false, timer: 0, tick: 0, ready: false, kind: "", fail: "", docOpen: false, acting: false, said: ""};
  const setText = (node, text) => { if (node.textContent !== text) node.textContent = text; };
  const setClass = (node, cls) => { if (node.className !== cls) node.className = cls; };
  const mmss = (s) => { const n = Math.max(0, Math.round(Number(s) || 0)); return Math.floor(n / 60) + ":" + String(n % 60).padStart(2, "0"); };
  function view() {
    const data = chk0.last;
    if (!data) return {kind: "check", label: t("board.enter.checking"), off: true};
    if (data.button && data.button.kind) return data.button;
    return data.ready ? {kind: "enter", label: t("board.enter.go"), off: false} : {kind: "check", label: t("board.enter.checking"), off: true};
  }
  const checkOf = (id) => ((chk0.last && chk0.last.checks) || []).find((x) => x.id === id) || {};
  const CAPTION = {signin: ["board.enter.cap.signin", ""], preparing: ["board.enter.cap.preparing", ""], doctor: ["board.enter.cap.doctor", "bad"], program: ["board.enter.cap.program", "hot"], "restart-host": ["", "bad"]};
  function paintSub(b) {  // the short line under the button: what it is about, with the reason in its hover
    const cap = CAPTION[b.kind];
    const text = chk0.said || (b.kind === "restart-host" || !cap ? plainWords(b.detail || "") : t(cap[0], {program: b.program || ""}));
    const level = chk0.said ? "bad" : cap ? cap[1] : "";
    sub.hidden = !text;
    setText(subText, text);
    setClass(subDot, "en-dot" + (level ? " " + level : ""));
    subDot.hidden = !level;
    sub.title = b.kind === "restart-host" ? plainWords(b.detail || "") : "";
  }
  function paintCode(b) {  // the code card of the sign-in: made again only when the code changes; the time left changes in place
    const key = "code|" + (b.code || "") + "|" + root.lang;
    if (card.dataset.k !== key) {
      card.dataset.k = key;
      const copy = h("button", {type: "button", class: "en-mini"}, t("board.enter.gh.copy"));
      copy.addEventListener("click", () => { try { navigator.clipboard.writeText(b.code).then(() => { copy.textContent = t("board.enter.gh.copied"); }); } catch (error) { /* the code stays on view */ } });
      const openGh = h("button", {type: "button", class: "en-mini en-mini-go"}, t("board.enter.gh.open"));
      openGh.addEventListener("click", () => window.open(chk0.last && chk0.last.button && chk0.last.button.url || b.url || "https://github.com/login/device", "_blank", "noopener"));
      const cancel = h("button", {type: "button", class: "en-mini en-mini-end"}, t("board.enter.gh.cancel"));
      cancel.addEventListener("click", () => { cancel.disabled = true; ask("/api/gh", {do: "cancel"}).then(poll, poll); });
      card.replaceChildren(h("div", {class: "en-card-t"}, t("board.enter.gh.title")), h("div", {class: "en-code-row"}, h("div", {class: "en-code"}, b.code || ""), copy), h("div", {class: "en-card-acts"}, openGh, cancel), h("p", {class: "en-card-w", "data-w": "1"}, h("i", {class: "en-spin"}), h("span")));
    }
    const left = Math.max(0, (Number(b.left) || 0) - Math.floor((Date.now() - chk0.at) / 1000));
    setText(card.querySelector("[data-w] span"), t("board.enter.card.left", {left: mmss(left)}));
  }
  function paintDoctor() {  // the problems of `harness doctor`: the line it found first, and the ways on from it
    const c = checkOf("doctor"), b = view();
    const key = ["doctor", c.why, c.detail, c.n, c.integrity, c.started, c.now, b.n, root.lang].join("|");
    if (card.dataset.k !== key) {
      card.dataset.k = key;
      const said = c.why === "stale" ? t("board.enter.m.doctor.stale", {started: c.started, now: c.now}) : plainWords(c.detail || "");
      const rows = [h("div", {class: "en-prob"}, h("i", {class: "en-dot bad"}), h("span", null, said))];
      const more = (Number(c.n) || b.n || 0) - 1;
      if (c.why === "errors" && more > 0) rows.push(h("div", {class: "en-prob soft"}, h("i", {class: "en-dot"}), h("span", null, t("board.enter.doc.more", {n: more}))));
      const acts = h("div", {class: "en-card-acts end"});
      if (c.why === "stale" && typeof SHELL !== "undefined") {
        const restart = h("button", {type: "button", class: "en-mini en-mini-go"}, t("board.enter.restart"));
        restart.addEventListener("click", () => SHELL.restartBoard(restart, (words) => { chk0.said = words; render(); }));
        acts.append(restart);
      } else {
        if (c.integrity) acts.append(READY.acceptButton(() => poll()));
        acts.append(READY.link({to: "doctor"}, {done: () => poll()}, t("board.enter.doctor.again")));
      }
      card.replaceChildren(h("div", {class: "en-card-t"}, t("board.enter.doc.title")), h("div", {class: "en-probs"}, ...rows), acts);
      for (const node of acts.querySelectorAll(".en-link,.en-open")) node.className = "en-mini" + (node === acts.lastChild ? " en-mini-go" : "");
    }
  }
  function paintCard(b) {
    const kind = b.kind === "signing" && b.code ? "code" : b.kind === "doctor" && chk0.docOpen ? "doctor" : "";
    if (!kind) { if (!card.hidden) { card.hidden = true; card.dataset.k = ""; } return; }
    if (kind === "code") paintCode(b); else paintDoctor();
    card.hidden = false;
  }
  function render() {  // in place: the nodes are made once; only their class and text change, so nothing blinks
    const data = chk0.last, b = view();
    const down = Boolean(chk0.error) && (chk0.misses || 0) >= 2;  // 1.8.13: one late answer is not a board that is down
    // 1.8.13: a slow computer is not a broken one. While the last answer that came was ready (KEEP_READY s ago at most), Enter stays on and the line says the board is slow, in amber; only after that is it red and Enter off.
    const lastOk = chk0.readyAt ? Math.round((Date.now() - chk0.readyAt) / 1000) : -1;
    const slowOnly = down && lastOk >= 0 && lastOk <= KEEP_READY;
    const ready = Boolean(data) && b.kind === "enter" && (!down || slowOnly);
    if (ready && !down) chk0.readyAt = Date.now();
    chk0.ready = ready; chk0.kind = b.kind;
    errLine.hidden = !down; setText(errLine, slowOnly ? t("board.enter.slow", {s: lastOk}) : down ? t("board.enter.noanswer", {error: chk0.error}) : "");
    errLine.classList.toggle("soft", slowOnly);
    root.classList.toggle("en-notready", b.kind !== "enter" && b.kind !== "check");  // the reflection of the wordmark goes when the button has something to say (1.7.29)
    const off = Boolean(b.off) || chk0.acting || (down && !slowOnly && b.kind === "enter");
    go.disabled = off;
    setClass(go, "en-go k-" + b.kind + (b.kind === "enter" ? "" : " plain") + (off ? " off" : ""));
    setText(label, b.label || "");
    const percent = b.kind === "preparing" ? clamp(Number(b.percent) || 0, 0, 100) : 0;
    const width = b.kind === "preparing" ? Math.max(3, percent) + "%" : "0";
    if (fill.style.width !== width) fill.style.width = width;
    goSpin.hidden = !(b.kind === "signing" || b.kind === "wait" || b.kind === "check");
    kbd.hidden = b.kind !== "enter";
    go.title = b.kind === "check" || b.kind === "wait" ? "" : go.title;
    paintCard(b); paintSub(b);
    roomForCard();
    return ready;
  }
  function roomForCard() {  // a short window: the card is never taller than the room between the wordmark and the button
    const wr = svg.getBoundingClientRect();
    if (!wr.height || card.hidden) return;
    const room = Math.max(120, go.getBoundingClientRect().top - (wr.bottom + 16));
    const value = Math.round(room) + "px";
    if (card.style.getPropertyValue("--card-max") !== value) card.style.setProperty("--card-max", value);
  }

  const ask = (path, body) => SERVE.call(path, body, 8);  // a POST with a deadline (serve.js): the same headers and cookie as every other call
  function poll() {
    if (!open || chk0.inflight || document.hidden) return;
    chk0.inflight = true;
    ask("/api/ready", {}).then((data) => { if (Array.isArray(data.checks) && data.button && data.button.kind === "setup") { open = false; location.replace("/setup"); return; }  // a copy that is not set up (the browser is paired: kind `pair` comes first) goes to the wizard by itself, no click; /setup never sends back to / before Confirm
      if (Array.isArray(data.checks)) { chk0.last = data; chk0.at = Date.now(); chk0.error = ""; chk0.misses = 0; READY.notes(data.notes); } else { chk0.error = "bad answer"; chk0.misses = (chk0.misses || 0) + 1; } },
      (error) => { chk0.error = String(error.message || error).slice(0, 200); chk0.misses = (chk0.misses || 0) + 1; })
      .then(() => {
        chk0.inflight = false; settle();
        // A doctor that is still running is asked again after a second, not at the next 3 s poll. Still one cheap read.
        if (open && chk0.last && (view().kind === "check" || checkOf("doctor").state === "check")) { clearTimeout(chk0.soon); chk0.soon = setTimeout(poll, 1000); }
      });
  }
  let pendingUntil = isTask ? Date.now() + 2500 : 0;
  function settle() {  // after each answer
    if (!open) return;
    const ready = render();
    if (!shown) {  // a task page opened from a link: skip when ready, show when something needs the person, wait a moment while it is only checking
      if (ready) { finish(true); return; }
      const needs = chk0.last && !["enter", "wait", "check"].includes(view().kind);
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
    open = false; remember();
    clearInterval(chk0.timer); clearInterval(chk0.tick); clearTimeout(chk0.soon); cancelAnimationFrame(wm.raf); wm.raf = 0; FX.down = false; FX.rel = null; fxClear(); tremble(0, 0);
    app.inert = false; root.classList.remove("en-open");
    if (typeof SPACE !== "undefined") { SPACE.hosted = null; SPACE.onTilt = null; SPACE.set(SPACE.tx / 2, SPACE.ty / 2); }
    stage.style.transform = "";
    if (quick || still()) { enter.remove(); return; }
    enter.classList.add("out"); setTimeout(() => enter.remove(), 450);
  }
  // What the button does, by the kind the server gave it. A kind that is `off` does nothing.
  function press() {
    if (!open || !shown || go.disabled) return false;
    const b = view();
    if (b.kind === "enter") { if (!chk0.ready) return false; finish(false); return true; }
    if (b.kind === "setup") { location.assign("/setup"); return true; }
    if (b.kind === "program") { location.assign("/setup?only=programs"); return true; }
    if (b.kind === "doctor") { chk0.docOpen = !chk0.docOpen; render(); return true; }
    if (b.kind === "signin") { act(() => ask("/api/gh", {do: "login"})); return true; }
    if (b.kind === "restart-host") { act(() => ask("/api/host", {do: "restart"}).then((data) => { const found = data && data.result; if (found && found.state === "waiting") chk0.said = t("board.enter.host.waiting"); })); return true; }  // chats still work: the host restarts once they finish
    if (b.kind === "pair") { act(() => ask("/api/reopen", {}).then((data) => { chk0.said = data && data.opened ? "" : t("board.serve.pair.notopened"); })); return true; }
    return false;
  }
  function act(call) {  // one press at a time: the button waits for the answer, the next look at the board shows what came of it
    chk0.acting = true; chk0.said = ""; render();
    call().then(() => {}, (error) => { chk0.said = plainWords(error && error.message ? error.message : String(error)).slice(0, 200); }).then(() => { chk0.acting = false; render(); poll(); });
  }
  const tryEnter = () => (view().kind === "enter" ? press() : false);  // a key only enters; every other kind of the button (a fix, a program to get, the setup) needs a click

  go.addEventListener("click", () => { press(); });

  document.addEventListener("keydown", (event) => {
    if (!open || !shown || event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || event.isComposing) return;
    if (typeof SHELL !== "undefined" && SHELL.isOpen()) return;  // the palette or the settings own the keys
    if (document.body.classList.contains("has-dialog")) return;  // a window opened from the dock over this screen owns the keys (1.7.32)
    if (["Shift", "Control", "Alt", "Meta", "Tab", "Escape", "CapsLock", "Dead", "Process"].includes(event.key) || /^F\d+$/.test(event.key)) return;
    const target = event.target;
    if (target && target.closest && target.closest("input,textarea,select,[contenteditable='true'],.en-card,.en-link")) return;
    if (document.querySelector(".dock-panel:not([hidden])")) return;  // the ? panel is open: its words are read, its text is typed in (1.7.34)
    if (target && target.closest && target.closest(".dock-btn") && (event.key === "Enter" || event.key === " ")) return;  // a dock button keeps its own Enter and Space; after its window closed, any other key goes in
    if (tryEnter()) event.preventDefault();  // any key goes in, but only when everything is ready (the kind `enter`)
  });

  // ---------- start ----------
  buildWord(); buildBot(); bindPlay(); wm.spot.setAttribute("cx", (VBW * .62).toFixed(1));
  window.addEventListener("resize", () => { placeBot(); fxSize(); roomForHi(); roomForCard(); });
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
