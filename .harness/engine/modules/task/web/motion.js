// How the first-run screens move (1.8.34): the wizard, the Enter screen, Settings and the Appearance panel use these and nothing else. The durations and
// curves are the tokens of tokens.css (--m-*); every move is transform and opacity only, played with the Web Animations API, so a slow computer keeps it
// smooth. still() (Lite, or the system's reduced motion): no move at all, at most a fade of 120 ms. The convention: the caller puts the page in its new
// state and MOTION plays the way into it (the frames end where the page already is), so a move cut short or skipped leaves the page right.
"use strict";

const MOTION = (function () {
  const root = document.documentElement;
  const query = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  const still = () => root.classList.contains("lite") || Boolean(query && query.matches);
  const IN = "cubic-bezier(.2,.8,.2,1)", OUT = "cubic-bezier(.4,0,1,1)";  // in: quick start, soft landing; out: a clean leave
  const MS = {micro: 120, show: 200, page: 260, window: 280};  // a press, something appearing, a page turn, a window; no move of the screens is longer than 300 ms
  const can = (el) => Boolean(el && typeof el.animate === "function");

  // play(el, frames, {ms, ease, delay, fill}) -> a promise that settles when the move ends or is cut. Under still() only the opacity of the frames is
  // played, in 120 ms at most, and a move with no opacity is not played.
  function play(el, frames, opts) {
    const o = opts || {};
    if (!can(el) || !frames || !frames.length) return Promise.resolve();
    let use = frames, ms = o.ms || MS.show, delay = o.delay || 0;
    if (still()) {
      if (!frames.every((frame) => "opacity" in frame)) return Promise.resolve();
      use = frames.map((frame) => ("offset" in frame ? {opacity: frame.opacity, offset: frame.offset} : {opacity: frame.opacity}));
      ms = Math.min(ms, MS.micro);
      delay = 0;
    }
    try {
      const move = el.animate(use, {duration: ms, delay, easing: o.ease || IN, fill: o.fill || "backwards"});
      return move.finished.then(() => undefined, () => undefined);
    } catch (error) {
      return Promise.resolve();  // an old browser: no move, the page is already right
    }
  }

  // appear(el, {y, ms, delay}): it was not there and now is (a fade, and `y` px of rise)
  const appear = (el, opts) => play(el, [{opacity: 0, transform: "translateY(" + ((opts && opts.y) || 0) + "px)"}, {opacity: 1, transform: "none"}], opts);

  // ghost(el): a copy of what is on screen now, fixed where it is, for a move out after the real one has changed (the old page of a turn). The caller removes it.
  function ghost(el) {
    if (!el || !el.isConnected) return null;
    const box = el.getBoundingClientRect();
    const copy = el.cloneNode(true);
    copy.setAttribute("aria-hidden", "true");
    copy.inert = true;
    copy.removeAttribute("id");
    for (const named of copy.querySelectorAll("[id]")) named.removeAttribute("id");
    Object.assign(copy.style, {position: "fixed", left: box.left + "px", top: box.top + "px", width: box.width + "px", height: box.height + "px", margin: "0", pointerEvents: "none", zIndex: "5"});
    document.body.append(copy);
    return copy;
  }

  // turn(old, now, dir): a page turn (W4). The old page is gone in 100 ms while it slides 24 px away (160 ms); the new one starts 60 ms later and comes
  // in over 200 ms, so the two never show their words over each other. dir 1 forward (to the left), -1 back. `old` is usually a ghost: it is removed here.
  function turn(old, now, dir) {
    const d = (dir < 0 ? -1 : 1) * 24;
    const leaving = old ? Promise.all([
      play(old, [{opacity: 1}, {opacity: 0}], {ms: 100, ease: OUT, fill: "forwards"}),
      play(old, [{transform: "none"}, {transform: "translateX(" + (-d) + "px)"}], {ms: 160, ease: OUT, fill: "forwards"}),
    ]).then(() => { if (old.parentNode && old.getAttribute("aria-hidden") === "true") old.remove(); }) : Promise.resolve();
    if (old && still()) old.remove();
    const coming = now ? play(now, [{opacity: 0, transform: "translateX(" + d + "px)"}, {opacity: 1, transform: "none"}], {ms: 200, delay: 60}) : Promise.resolve();
    return Promise.all([leaving, coming]).then(() => undefined);
  }

  // swap(el, change): a label or a small part changes (E4): the old fades out in 100 ms, `change()` runs, the new fades in over 160 ms; never both at once.
  // A second swap while one runs takes over (the last change wins).
  // 1.8.44: a browser that does not play the frames (a busy or covered window) could leave the label at opacity 0 (the fade-out holds its end, the fade-in waits
  // at its start): the change is written after SWAP_LATE ms whatever the frames do, and every move of the swap is taken off once it should be over.
  const SWAP_LATE = 400;
  const clear = (el) => { for (const running of el.getAnimations ? el.getAnimations() : []) running.cancel(); };
  const late = (wait) => new Promise((resolve) => setTimeout(resolve, wait));
  function swap(el, change) {
    if (!el) { change(); return Promise.resolve(); }
    if (still()) { change(); return Promise.resolve(); }
    const turnNo = (el._motionSwap = (el._motionSwap || 0) + 1);
    const out = play(el, [{opacity: 1}, {opacity: 0}], {ms: 100, ease: OUT, fill: "forwards"});
    return Promise.race([out, late(SWAP_LATE)]).then(() => {
      if (el._motionSwap !== turnNo) return undefined;
      clear(el);
      change();
      return Promise.race([play(el, [{opacity: 0}, {opacity: 1}], {ms: 160}), late(SWAP_LATE)]).then(() => { if (el._motionSwap === turnNo) clear(el); });
    });
  }

  // glide(els, change, ms): measure, run `change()`, then move each element from where it was to where it is now (FLIP, 200 ms): the footer of the wizard
  // when the page above changes height (W4), the selection of Settings (S2). Under still() the change only.
  function glide(els, change, ms) {
    const list = (Array.isArray(els) ? els : [els]).filter(Boolean);
    const before = list.map((el) => el.getBoundingClientRect());
    change();
    if (still()) return Promise.resolve();
    return Promise.all(list.map((el, index) => {
      if (!el.isConnected) return null;
      const now = el.getBoundingClientRect(), dx = before[index].left - now.left, dy = before[index].top - now.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return null;
      return play(el, [{transform: "translate(" + dx + "px," + dy + "px)"}, {transform: "none"}], {ms: ms || MS.show});
    })).then(() => undefined);
  }

  // guard(fn, ms): a press while a move runs is dropped (a burst of clicks on Continue moves one page, GOAL 10); a press after `ms` works again
  function guard(fn, ms) {
    let until = 0;
    return function (...args) {
      const now = performance.now();
      if (now < until) return undefined;
      until = now + (ms == null ? 300 : ms);
      return fn.apply(this, args);
    };
  }

  // leave(then, {content, cls}): the page fades to its own background (160 ms) before it goes away (a reload after a language change E6, the wizard to the Enter
  // screen W10), so the next page comes out of the same colour instead of a flash. `content` (a node) sits in the middle meanwhile.
  function leave(then, opts) {
    const veil = document.createElement("div");
    veil.className = "m-veil" + (opts && opts.cls ? " " + opts.cls : "");  // cls "enter-bg": the Enter screen's backdrop, light or dark
    veil.setAttribute("aria-hidden", "true");
    if (opts && opts.content) veil.append(opts.content);
    document.body.append(veil);
    return play(veil, [{opacity: 0}, {opacity: 1}], {ms: 160, fill: "forwards"}).then(() => (then ? then() : undefined));
  }

  // mark(key) / taken(key, within): a hand-over between two pages of one tab (sessionStorage): the wizard marks "from-wizard" before it goes, and the Enter
  // screen plays its entrance from the wizard once (W10). A mark older than `within` ms (10 s) is not taken.
  const KEY = "harness.motion.";
  const mark = (key) => { try { sessionStorage.setItem(KEY + key, String(Date.now())); } catch (error) { /* no hand-over: the next page opens as usual */ } };
  const taken = (key, within) => {
    try {
      const at = Number(sessionStorage.getItem(KEY + key) || 0);
      sessionStorage.removeItem(KEY + key);
      return at > 0 && Date.now() - at < (within || 10000);
    } catch (error) {
      return false;
    }
  };

  return {still, play, appear, ghost, turn, swap, glide, guard, leave, mark, taken, MS, IN, OUT};
})();
