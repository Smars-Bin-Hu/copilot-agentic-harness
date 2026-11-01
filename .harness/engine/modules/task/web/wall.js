// The wallpaper of a served page (1.6.19, B89): the pictures of the one folder the person chose, shown behind the page in the 3D stage of space.js, and the Background part of the settings panel.
// The pictures stay on this computer. The server (wallpaper.py) lists the files of that folder and hands out one file by its bare name; it cannot resize. The browser does:
//   - a thumbnail (about 192 px wide) for the panel and a downscaled picture (at most 2560 px wide) for the page are made with createImageBitmap and a canvas, then kept in the Cache API
//     (try/catch: a browser that will not keep them makes them again). A picture of 8K and 20 MB is read once; after that only the small copy is used.
//   - nothing is decoded at once: a thumbnail is made only when its tile is on view, two at a time; the picture of the page one at a time. The size in the file header is read first,
//     so a huge picture is decoded already scaled down, and one that is absurdly large is refused.
// In the light theme the picture is turned into its "daylight twin" (inverted, brightened) when it is made, not on every frame (a CSS filter on a moving full-screen layer is paid for each frame).
// The choice (which picture, rotation) is kept in this browser; the folder is the person's setting on the server. The default is no picture.
// A page on disk has no wallpaper (no server to ask): its panel only has the motion switch.
"use strict";

const WALL = (function () {
  const served = typeof SERVE !== "undefined" && Boolean(DATA.serve);
  const root = document.documentElement;
  const PICK = "harness.wall", ROT = "harness.wall.rot";
  const CACHE = "harness-wall-v1";
  const FULL_W = 2560, THUMB_W = 192, MAX_SIDE = 20000, MAX_PIXELS = 120e6;
  const TWIN = "invert(1) hue-rotate(180deg) contrast(.55) brightness(1.42) saturate(1.25)";
  const memory = {};
  const keep = {
    get(name) { try { const value = localStorage.getItem(name); return value === null ? (name in memory ? memory[name] : null) : value; } catch (error) { return name in memory ? memory[name] : null; } },
    set(name, value) { memory[name] = value; try { if (value === null) localStorage.removeItem(name); else localStorage.setItem(name, value); } catch (error) { /* kept in memory only */ } },
  };
  const config = {every: 10 * 60 * 1000};  // the rotation; a test shortens it
  const W = {info: null, current: "", broken: new Set(), config, error: ""};
  const light = () => root.getAttribute("data-theme") === "light";
  const lite = () => root.classList.contains("lite");
  const twinByCanvas = typeof CanvasRenderingContext2D !== "undefined" && "filter" in CanvasRenderingContext2D.prototype;
  if (!twinByCanvas) root.classList.add("twin-css");  // the filter is then on the layer (space.css)

  // ---------- the small copies, kept in the Cache API ----------
  const key = (kind, entry) => location.origin + "/__wall/" + kind + "/" + W.info.id + "/" + entry.m + "-" + entry.s + "/" + encodeURIComponent(entry.n);
  async function cacheGet(address) {
    try { const cache = await caches.open(CACHE); const found = await cache.match(address); return found ? await found.blob() : null; } catch (error) { return null; }
  }
  async function cachePut(address, blob) {
    try { const cache = await caches.open(CACHE); await cache.put(address, new Response(blob, {headers: {"Content-Type": blob.type || "image/jpeg"}})); } catch (error) { /* made again next time */ }
  }
  async function cachePrune() {  // what the folder no longer has (or another folder) is forgotten
    try {
      const cache = await caches.open(CACHE);
      const valid = new Set();
      if (W.info && W.info.state === "ok") for (const entry of W.info.names) for (const kind of ["t", "d", "l"]) valid.add(key(kind, entry));
      for (const request of await cache.keys()) if (!valid.has(request.url)) await cache.delete(request);
    } catch (error) { /* nothing kept, nothing to forget */ }
  }

  // ---------- reading a picture ----------
  // The size from the first bytes of the file: JPEG (the start-of-frame marker), PNG (IHDR), WebP (VP8, VP8L, VP8X). null when it cannot be told.
  function size(u8) {
    const view = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
    if (u8.length > 24 && u8[0] === 0x89 && u8[1] === 0x50) return {w: view.getUint32(16), h: view.getUint32(20)};
    if (u8.length > 4 && u8[0] === 0xff && u8[1] === 0xd8) {
      let i = 2;
      while (i + 9 < u8.length) {
        if (u8[i] !== 0xff) { i++; continue; }
        const marker = u8[i + 1];
        if (marker === 0xff) { i++; continue; }
        if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) return {h: (u8[i + 5] << 8) | u8[i + 6], w: (u8[i + 7] << 8) | u8[i + 8]};
        if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) { i += 2; continue; }
        i += 2 + ((u8[i + 2] << 8) | u8[i + 3]);
      }
      return null;
    }
    if (u8.length > 30 && u8[0] === 0x52 && u8[8] === 0x57) {
      const chunk = String.fromCharCode(u8[12], u8[13], u8[14], u8[15]);
      if (chunk === "VP8 ") return {w: (u8[26] | (u8[27] << 8)) & 0x3fff, h: (u8[28] | (u8[29] << 8)) & 0x3fff};
      if (chunk === "VP8L") return {w: 1 + (((u8[22] & 0x3f) << 8) | u8[21]), h: 1 + (((u8[24] & 0x0f) << 10) | (u8[23] << 2) | ((u8[22] & 0xc0) >> 6))};
      if (chunk === "VP8X") return {w: 1 + (u8[24] | (u8[25] << 8) | (u8[26] << 16)), h: 1 + (u8[27] | (u8[28] << 8) | (u8[29] << 16))};
    }
    return null;
  }
  async function bitmap(blob, width) {  // already scaled down when the picture is wider than `width`
    const head = new Uint8Array(await blob.slice(0, 262144).arrayBuffer());
    const found = size(head);
    if (found && (found.w < 1 || found.h < 1 || found.w > MAX_SIDE || found.h > MAX_SIDE || found.w * found.h > MAX_PIXELS)) throw new Error("too large");
    try {
      return await createImageBitmap(blob, found && found.w > width ? {resizeWidth: width, resizeQuality: "high"} : {});
    } catch (error) {
      if (!found) throw error;
      return await createImageBitmap(blob);  // an older browser without the resize options
    }
  }
  function canvasOf(w, h) { return typeof OffscreenCanvas !== "undefined" ? new OffscreenCanvas(w, h) : Object.assign(document.createElement("canvas"), {width: w, height: h}); }
  function encode(canvas, quality) {
    return canvas.convertToBlob ? canvas.convertToBlob({type: "image/jpeg", quality}) : new Promise((done, fail) => canvas.toBlob((blob) => (blob ? done(blob) : fail(new Error("encode"))), "image/jpeg", quality));
  }
  async function drawn(source, width, filter) {  // source: an ImageBitmap; the picture at `width` (or its own width when smaller), filtered when asked
    const scale = Math.min(1, width / source.width);
    const w = Math.max(1, Math.round(source.width * scale)), h = Math.max(1, Math.round(source.height * scale));
    const canvas = canvasOf(w, h), ctx = canvas.getContext("2d");
    ctx.fillStyle = "#202226"; ctx.fillRect(0, 0, w, h);
    if (filter) ctx.filter = filter;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(source, 0, 0, w, h);
    return encode(canvas, filter ? .88 : .86);
  }
  const original = (entry) => SERVE.file("/wall/" + encodeURIComponent(entry.n));

  // Work is done a few at a time: the thumbnails two at a time (only the tiles on view), the picture of the page one at a time.
  function lane(limit) {
    let busy = 0;
    const waiting = [];
    const pump = () => {
      while (busy < limit && waiting.length) {
        const job = waiting.shift();
        if (job.dropped && job.dropped()) { job.done(null); continue; }
        busy++;
        job.run().then(job.done, job.fail).then(() => { busy--; pump(); });
      }
    };
    return (run, dropped) => new Promise((done, fail) => { waiting.push({run, dropped, done, fail}); pump(); });
  }
  const thumbLane = lane(2), fullLane = lane(1);

  const urls = {t: new Map(), f: new Map()};  // object URLs: thumbnails of tiles, and the pictures of the page (only two are kept)
  async function thumb(entry, dropped) {
    const address = key("t", entry);
    return thumbLane(async () => {
      let blob = await cacheGet(address);
      if (!blob) {
        const source = await bitmap(await original(entry), THUMB_W * 2);
        try { blob = await drawn(source, THUMB_W, ""); } finally { if (source.close) source.close(); }
        await cachePut(address, blob);
      }
      return blob;
    }, dropped);
  }
  async function full(entry) {  // the blob of the picture for the page, in the theme's variant
    const dark = key("d", entry), twin = key("l", entry);
    return fullLane(async () => {
      if (light() && twinByCanvas) {
        const found = await cacheGet(twin);
        if (found) return found;
      }
      let blob = await cacheGet(dark);
      if (!blob) {
        const source = await bitmap(await original(entry), FULL_W);
        try { blob = await drawn(source, FULL_W, ""); } finally { if (source.close) source.close(); }
        await cachePut(dark, blob);
      }
      if (light() && twinByCanvas) {
        const source = await createImageBitmap(blob);
        try { blob = await drawn(source, FULL_W, TWIN); } finally { if (source.close) source.close(); }
        await cachePut(twin, blob);
      }
      return blob;
    });
  }

  // ---------- the picture behind the page: two layers, a 1.5 s crossfade inside the 3D stage ----------
  let layer = -1, token = 0;
  const layers = () => SPACE.layers;
  function paint(blob, instant) {
    const url = URL.createObjectURL(blob);
    const next = layer === 0 ? 1 : 0, now = layers()[next], previous = layer >= 0 ? layers()[layer] : null;
    const finish = () => {
      now.classList.toggle("inst", instant || lite());
      now.style.zIndex = 2; if (previous) previous.style.zIndex = 1;
      void now.offsetWidth;
      now.classList.add("on"); layer = next;
      root.classList.add("has-wall");
      if (previous) setTimeout(() => { if (layers()[layer] !== previous) { previous.classList.remove("on"); previous.style.backgroundImage = ""; } }, instant ? 30 : 1700);
      const old = urls.f.get(previous);
      if (old) setTimeout(() => URL.revokeObjectURL(old), 1800);
      urls.f.set(now, url);
    };
    now.style.backgroundImage = 'url("' + url + '")';
    const probe = new Image();
    probe.onload = finish; probe.onerror = () => { URL.revokeObjectURL(url); };
    probe.src = url;
  }
  function clear() {
    token++;
    layers().forEach((node) => { node.classList.remove("on"); node.style.backgroundImage = ""; });
    layer = -1; W.current = "";
    for (const url of urls.f.values()) URL.revokeObjectURL(url);
    urls.f.clear();
    root.classList.remove("has-wall");
  }
  async function show(name, instant) {
    const mine = ++token;
    const entry = W.info && W.info.state === "ok" ? W.info.names.find((item) => item.n === name) : null;
    if (!entry || W.broken.has(name)) { if (!name || !entry) clear(); return false; }
    try {
      const blob = await full(entry);
      if (mine !== token) return false;
      W.current = name;
      paint(blob, Boolean(instant));
      return true;
    } catch (error) {
      if (mine === token) { W.broken.add(name); clear(); mark(); }
      return false;
    }
  }
  function choose(name) {
    keep.set(PICK, name || null);
    if (!name) clear(); else show(name, false);
    mark(); arm();
  }

  // ---------- rotation: every 10 minutes, in random order, paused while the page is hidden, off in Lite ----------
  let timer = 0, deck = [];
  const rotating = () => keep.get(ROT) === "1";
  function arm() {
    clearTimeout(timer);
    if (!rotating() || lite() || document.hidden || !W.current || !W.info || W.info.names.length < 2) return;
    timer = setTimeout(next, config.every);
  }
  async function next() {
    if (document.hidden || lite() || !rotating() || !W.info) return;
    for (let tries = 0; tries < 6; tries++) {
      if (!deck.length) {
        deck = W.info.names.map((item) => item.n).filter((name) => name !== W.current && !W.broken.has(name));
        for (let i = deck.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [deck[i], deck[j]] = [deck[j], deck[i]]; }
      }
      const name = deck.pop();
      if (!name) break;
      keep.set(PICK, name);
      if (await show(name, false)) break;
    }
    mark(); arm();
  }
  document.addEventListener("visibilitychange", arm);

  // ---------- asking the server ----------
  async function refresh() {
    if (!served) return null;
    try {
      const data = await SERVE.call("/api/wall", {}, 8);
      W.error = "";
      take(data.wall);
    } catch (error) {
      W.error = "off";
      if (!W.info) W.info = {state: "off", folder: "", names: [], skipped: 0, more: false, id: ""};
    }
    render();
    return W.info;
  }
  function take(info) {
    const before = W.info;
    W.info = info;
    if (!before || before.id !== info.id) W.broken.clear();
    const wanted = keep.get(PICK) || "";
    if (info.state === "ok" && wanted && info.names.some((item) => item.n === wanted)) {
      if (W.current !== wanted) show(wanted, !before);
    } else if (W.current || root.classList.contains("has-wall")) clear();
    cachePrune();
    arm();
  }

  // ---------- the settings panel: the Background part ----------
  let box = null, grid = null, say = null, bad = null, input = null, change = null, rot = null, rotNote = null, motion = null, observer = null;
  const tiles = new Map();
  const wantedTiles = [];
  function tile(entry) {
    const node = h("button", {type: "button", class: "th", "data-n": entry.n, "aria-pressed": "false", "aria-label": t("board.wall.pick", {name: entry.n}), title: entry.n, tabindex: "-1"});
    tiles.set(entry.n, node);
    return node;
  }
  function look(node) {  // a tile came into view: its thumbnail is made, unless it left again before its turn
    const entry = W.info && W.info.names.find((item) => item.n === node.dataset.n);
    if (!entry || node.dataset.loaded) return;
    node.dataset.loaded = "1";
    thumb(entry, () => !node.isConnected || node.dataset.vis !== "1").then((blob) => {
      if (!blob) { delete node.dataset.loaded; return; }  // it went out of view: asked again when it comes back
      const url = URL.createObjectURL(blob);
      urls.t.set(entry.n, url);
      node.style.backgroundImage = 'url("' + url + '")';
      node.classList.add("ready");
    }, () => { node.classList.add("bad"); node.disabled = true; node.title = entry.n + " — " + t("board.wall.broken"); W.broken.add(entry.n); });
  }
  function watch() {
    if (observer) observer.disconnect();
    if (!window.IntersectionObserver) { for (const node of tiles.values()) { node.dataset.vis = "1"; look(node); } return; }
    observer = new IntersectionObserver((list) => {
      for (const item of list) { item.target.dataset.vis = item.isIntersecting ? "1" : "0"; if (item.isIntersecting) look(item.target); }
    }, {root: grid, rootMargin: "60px"});
    for (const node of tiles.values()) observer.observe(node);
  }
  function build() {
    if (box) return box;
    const none = h("button", {type: "button", class: "th none", "data-n": "", "aria-pressed": "false", tabindex: "0"}, t("board.wall.none"));
    tiles.set("", none);
    grid = h("div", {class: "wgrid", role: "group", "aria-label": t("board.wall.title")}, none);
    say = h("p", {class: "sp-note", role: "status"});
    bad = h("p", {class: "sp-bad", role: "alert", hidden: "hidden"});
    input = h("input", {type: "text", class: "wpath", spellcheck: "false", autocomplete: "off", maxlength: "1000", placeholder: t("board.wall.folder.ph"), "aria-label": t("board.wall.folder")});
    change = h("button", {type: "button", class: "wchange"}, t("board.wall.change"));
    rot = h("input", {type: "checkbox"});
    rotNote = h("span", {class: "sp-note", hidden: "hidden"}, t("board.wall.rot.off"));
    motion = h("input", {type: "checkbox"});
    const wall = served ? [grid, say, bad, h("div", {class: "wfolder"}, h("label", {class: "sp-note"}, t("board.wall.folder")), h("div", {class: "wline"}, input, change)),
      h("label", {class: "sp-check"}, rot, h("span", null, t("board.wall.rot"))), rotNote] : [h("p", {class: "sp-note"}, t("board.wall.disk"))];
    box = h("div", {class: "sp-bg"}, h("h5", null, t("board.wall.title")), ...wall,
      h("label", {class: "sp-check"}, motion, h("span", null, t("board.wall.motion"))), h("p", {class: "sp-note"}, t("board.wall.motion.hint")));
    grid.addEventListener("click", (event) => {
      const node = event.target.closest("button.th");
      if (node && !node.disabled) choose(node.dataset.n);
    });
    grid.addEventListener("keydown", (event) => {
      const keys = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -2, ArrowDown: 2, Home: -9, End: 9};
      if (!(event.key in keys)) return;
      const all = [...grid.querySelectorAll("button.th:not([disabled])")], at = all.indexOf(document.activeElement);
      if (at < 0) return;
      event.preventDefault();
      let to = at + keys[event.key];
      if (Math.abs(keys[event.key]) === 2) {  // up and down: the tile above or below, by where it is on the screen
        const here = all[at].getBoundingClientRect();
        const row = all.filter((node) => Math.abs(node.getBoundingClientRect().left - here.left) < 4 && (keys[event.key] > 0 ? node.getBoundingClientRect().top > here.top + 4 : node.getBoundingClientRect().top < here.top - 4));
        to = row.length ? all.indexOf(keys[event.key] > 0 ? row[0] : row[row.length - 1]) : at;
      } else if (event.key === "Home") to = 0;
      else if (event.key === "End") to = all.length - 1;
      to = Math.max(0, Math.min(all.length - 1, to));
      all.forEach((node) => { node.tabIndex = -1; });
      all[to].tabIndex = 0; all[to].focus();
    });
    input.addEventListener("input", () => { input.dataset.typed = "1"; });
    const submit = () => setFolder(input.value);
    change.addEventListener("click", submit);
    input.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); submit(); } });
    rot.addEventListener("change", () => { keep.set(ROT, rot.checked ? "1" : "0"); arm(); });
    motion.addEventListener("change", () => SPACE.setMotion(motion.checked));
    return box;
  }
  function state() {
    const info = W.info;
    if (!info) return "";
    if (info.state === "ok") return (info.skipped ? t("board.wall.skipped", {n: info.skipped}) + " " : "") + (info.more ? t("board.wall.more", {n: info.names.length}) : "");
    return t("board.wall.state." + info.state, {folder: info.folder});
  }
  function render() {  // in place: the tiles are made again only when the list of names changed
    if (!box) return;
    const info = W.info || {state: "none", names: [], folder: ""};
    const names = info.state === "ok" ? info.names.map((item) => item.n) : [];
    const now = [...grid.querySelectorAll("button.th:not(.none)")].map((node) => node.dataset.n);
    if (now.join("\n") !== names.join("\n")) {
      for (const [name, node] of tiles) if (name) { tiles.delete(name); node.remove(); }
      for (const url of urls.t.values()) URL.revokeObjectURL(url);
      urls.t.clear();
      grid.append(...info.names.slice(0, names.length).map(tile));
      watch();
    }
    grid.hidden = false;
    grid.classList.toggle("only-none", !names.length);
    const text = state();
    if (say.textContent !== text) say.textContent = text;
    say.hidden = !text;
    if (document.activeElement !== input && input.value !== info.folder && !input.dataset.typed) input.value = info.folder || "";
    mark();
  }
  function mark() {
    if (!box) return;
    const shown = W.current && W.info && W.info.state === "ok" ? W.current : "";
    for (const [name, node] of tiles) {
      const on = name === shown;
      node.classList.toggle("on", on); node.setAttribute("aria-pressed", on ? "true" : "false");
    }
    rot.checked = rotating();
    const off = lite();
    rot.disabled = off; rotNote.hidden = !off;
    motion.checked = SPACE.motion(); motion.disabled = off || SPACE.reduced();
  }
  async function setFolder(text) {
    bad.hidden = true; change.disabled = true;
    try {
      const data = await SERVE.call("/api/wallfolder", {folder: text}, 8);
      delete input.dataset.typed;
      take(data.wall);
      if (data.wall.state === "ok") say.textContent = t("board.wall.saved", {n: data.wall.names.length});
      render();
      if (data.wall.state === "ok") say.textContent = t("board.wall.saved", {n: data.wall.names.length}) + " " + state();
    } catch (error) {
      bad.textContent = error && error.message ? error.message : t("board.wall.state.off");
      bad.hidden = false;
    }
    change.disabled = false;
  }
  function section() {  // the nodes of the Background part (made once; shell.js puts them in the panel)
    build();
    render();
    return box;
  }
  function opened() { mark(); if (served) refresh(); if (grid) { const on = grid.querySelector("button.on"); if (on) on.tabIndex = 0; } }

  // ---------- start ----------
  if (served) {
    if (keep.get(PICK)) root.classList.add("has-wall");  // the panels are glass from the first frame; the picture comes a moment later
    refresh();
    new MutationObserver(() => { if (W.current) show(W.current, false); mark(); }).observe(root, {attributes: true, attributeFilter: ["data-theme"]});
    new MutationObserver(() => { arm(); mark(); }).observe(root, {attributes: true, attributeFilter: ["class"]});
  }

  return Object.assign(W, {served, section, opened, refresh, choose, next, show, mark, listing: () => W.info});
})();
