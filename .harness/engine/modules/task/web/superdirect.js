// The direct message of the super agent view (1.8.4): the words typed under an avatar (or after "@name") go to that task's own chat with `/api/super/send`. This file holds the three parts both the input and the
// proposal card use, so the two never differ: the send call with the words for its refusals, the small options menu (an icon next to Send), and the receipt words.
// The menu: model, thinking, context, when the task works (queue or steer), the reply language, files and "New chat". Every choice is remembered in this browser (`localStorage`), except the files and New chat: New chat is for one message only (kept on, every later message would make one more chat).
// A choice that is not the default puts a dot on the icon; its hover lists the choices in short form ("Fusion · high · new chat"). The default model is the task's own: nothing is sent for it.
// Needs common.js, serve.js, chat.js (CHAT.fileTray). Loaded before super.js.
"use strict";

const SUPERDIRECT = (function () {
  const KEY = "super.direct", MAX = 10000, MAXN = 5;  // MAXN: the board's default most checks (`review.max_n`); the page has no way to read a changed one for a closed task, and the server refuses a number over its own (why "checks")
  // The reason words of a refusal: written out here and nowhere else, so the list the server gives can be set against it in one place. A word that is not here is shown as it is (super.direct.why.other).
  const SHARED = {unknown: "super.route.why.unknown", paused: "super.route.why.paused", "text.empty": "send.refused.text.empty", "text.long": "send.refused.text.long", request: "serve.refused.request"};
  // The words the server's own refusals have (send.refused.<why>), so the page and the task page say them the same way.
  const SERVER = new Set(["file-count", "file-big", "file-bad", "model", "thinking", "context", "confirm-waits", "not-idle", "off", "not-ready", "unsure", "changed", "timeout", "not-busy", "not-input", "ask-gone", "no-turn", "host", "checks"]);
  // The page's own: the call itself failed (no answer, an unpaired browser).
  const OWN = {error: "super.direct.why.error", unpaired: "super.direct.why.unpaired"};
  const HOW = {sent: ["super.direct.sent", "super.direct.how.sent"], queued: ["super.direct.queued", "super.direct.how.queued"], steered: ["super.direct.steered", "super.direct.how.steered"], said: ["super.direct.said", "super.direct.how.said"], "new-chat": ["super.direct.newchat", "super.direct.how.newchat"], reopened: ["super.direct.reopened", "super.direct.how.reopened"], after: ["super.direct.after", "super.direct.how.after"]};
  // One place for the words of a refusal; a word that is in none of the lists is shown as it is (super.direct.why.other). `error`: the text the server gives with `host`.
  const whyText = (why, error) => (SHARED[why] ? t(SHARED[why]) : SERVER.has(why) ? t("send.refused." + why, {error: String(error || "")}) : OWN[why] ? t(OWN[why]) : t("super.direct.why.other", {why: String(why || "?")}));
  const howOf = (how) => HOW[how] || HOW.sent;

  // ---------- the call ----------
  // One message to one task: {ok: true, how, task} or {ok: false, why}. `options` is what `values()` of a menu gives.
  async function send(task, text, options) {
    if (!String(text || "").trim()) return {ok: false, why: "text.empty"};
    if (String(text).length > MAX) return {ok: false, why: "text.long"};
    try {
      const result = await SERVE.call("/api/super/send", {task, text, ...(options || {})}, 40);
      if (!result || result.ok === false) return {ok: false, why: (result && result.why) || "error", error: result && result.error};
      const spent = (options && options.new_chat && state.newChat) || (options && options.checks !== undefined && String(options.checks) === state.checks);
      if (options && options.new_chat && state.newChat) state.newChat = false;  // New chat and Independent checks are for this message only: off again once it went
      if (options && options.checks !== undefined && String(options.checks) === state.checks) state.checks = "";
      if (spent) menus.forEach((menu) => menu.redraw && menu.redraw());
      return {ok: true, how: result.how || "sent", task: result.task || task, checks: result.checks, checks_pending: result.checks_pending};
    } catch (error) {
      return {ok: false, why: error && error.status === 403 ? "unpaired" : error && error.data && typeof error.data === "object" && error.data.why ? error.data.why : "error", error: error && error.data && error.data.error};
    }
  }
  // The checks the server set: "Checks: 2." now, or "Checks: 2, on once the task is open." when the board holds them until then. `found`: the answer of `send`.
  const checksWord = (found) => (found && Number.isInteger(found.checks) ? " " + t("super.direct.checks", {n: found.checks}) : found && Number.isInteger(found.checks_pending) ? " " + t("super.direct.checks.pending", {n: found.checks_pending}) : "");
  const receipt = (how, task, found) => t(howOf(how)[0], {task}) + checksWord(found);  // "Sent to X." a line of the thread
  const howWord = (how, found) => t(howOf(how)[1]) + (found && Number.isInteger(found.checks) ? " \u00b7 " + t("super.direct.short.checks", {n: found.checks}) : found && Number.isInteger(found.checks_pending) ? " \u00b7 " + t("super.direct.short.checks", {n: found.checks_pending}) : "");  // "Sent": the end of a card's receipt
  const refusal = (task, why, error) => t("super.direct.refused", {task, why: whyText(why, error)});

  // ---------- the options (shared by every menu on the page) ----------
  const DEFAULT = {model: "", thinking: "", context: "", busy: "queue", lang: "", newChat: false, checks: ""};  // checks: "" = no change, "0".."9"
  let state = {...DEFAULT};
  try { const saved = JSON.parse(localStorage.getItem(KEY) || "null"); if (saved && typeof saved === "object") state = {...DEFAULT, ...saved, newChat: false, checks: ""}; } catch (error) { /* no storage: kept for this page only */ }
  const keep = () => { try { localStorage.setItem(KEY, JSON.stringify({...state, newChat: false, checks: ""})); } catch (error) { /* ignore */ } };
  const menus = new Set();
  let models = null;  // the models the host offers; null until asked (and asked again if it failed)
  const own = new Map();  // task -> the task's own {id, thinking, context}
  const asked = new Map();  // task -> the promise of the ask

  function load(task) {
    if (!task) return Promise.resolve();
    if (!asked.has(task)) {
      const call = SERVE.post("/api/skill", {step: "options", task}).then((data) => {
        const found = (data && data.result) || {};
        models = found.models || models || [];
        own.set(task, found.task || {});
      }, () => { asked.delete(task); });  // no list (VS Code away): the message goes with the task's own settings; asked again at the next open
      asked.set(task, call);
    }
    return asked.get(task);
  }
  const modelOf = (id) => (models || []).find((item) => item.id === id) || null;
  const HOST = "-";  // the model "": the host (VS Code) chooses
  const effective = (task) => (state.model === HOST ? "" : state.model || (own.get(task) || {}).id || "");
  const levelsOf = (found) => (found && found.thinking && found.thinking.levels) || [];
  const sizesOf = (found) => (found && found.context && found.context.sizes) || [];
  const different = (checks) => Boolean(state.model || state.thinking || state.context || state.busy === "steer" || state.lang || state.newChat || (checks === undefined ? state.checks : checks) !== "");

  // The options as the server takes them. A choice of thinking or context with no model goes with the task's own model (the call names the model whenever it names one of the others).
  function values(task, checks) {
    const out = {};
    const id = effective(task);
    if (state.model === HOST) out.model = "";
    else if ((state.model || state.thinking || state.context) && id) {
      out.model = id;
      if (state.thinking) out.thinking = state.thinking;
      if (state.context) out.context = state.context;
    }
    if (state.newChat) out.new_chat = true;
    if (state.busy === "steer") out.busy = "steer";
    if (state.lang) out.lang = state.lang;
    const level = checks === undefined ? state.checks : checks;  // a card holds its own checks: the box's are not its
    if (level !== "") out.checks = Number(level);
    return out;
  }
  // The hover: the choices in short form.
  function brief(files, checks) {
    const parts = [];
    const found = modelOf(state.model);
    if (state.model) parts.push(state.model === HOST ? t("board.new.model.chat") : found ? found.name : state.model);
    if (state.thinking) parts.push(thinkingLabel(state.thinking, found || null));
    if (state.context) { const size = sizesOf(found).find((item) => String(item.id) === String(state.context)); parts.push(size ? size.label : state.context); }
    if (state.busy === "steer") parts.push(t("super.direct.short.steer"));
    if (state.lang) parts.push(t("desk.send.lang.name." + state.lang));
    if (state.newChat) parts.push(t("super.direct.short.new"));
    const level = checks === undefined ? state.checks : checks;
    if (level !== "") parts.push(t("super.direct.short.checks", {n: level}));
    if (files) parts.push(t("super.direct.short.files", {n: files}));
    return parts.join(" · ");
  }

  // ---------- the menu ----------
  // `box`: the textarea the words are typed in (a pasted picture becomes a file); `fit`: the node the menu keeps inside of (the view). Gives {button, tray, values, reading, clear, bind, close}.
  function menu(box, fit) {
    let task = "", opened = false, pop = null, mine = null;  // mine: the checks of a card ("" none, "0".."9"); null: the page's
    const said = h("div", {class: "bad sa-dmsg"});
    const redraw = () => { if (!opened && !button.isConnected) { menus.delete(self); return; } paint(); if (opened) fill(); };
    const files = CHAT.fileTray(box, said, redraw);
    const button = h("button", {type: "button", class: "sa-dopt", "aria-haspopup": "true", "aria-expanded": "false"}, h("span", {class: "sa-dico", "aria-hidden": "true"}, "⋯"), h("span", {class: "sa-ddot", hidden: ""}));
    const count = () => files.list().length;
    function paint() {
      const level = mine === null ? undefined : mine;
      const note = brief(count(), level);
      button.querySelector(".sa-ddot").hidden = !different(level) && !count();
      button.title = t("super.direct.opts") + (note ? ": " + note : "");
      button.setAttribute("aria-label", button.title);
    }
    const choose = (label, select) => h("label", {class: "sa-dfield"}, h("span", {class: "sa-dlabel"}, label), select);
    function fill() {
      const model = h("select", {"aria-label": t("board.new.model")});
      model.append(h("option", {value: ""}, t("super.direct.model.own")), h("option", {value: HOST}, t("board.new.model.chat")), ...(models || []).map((item) => h("option", {value: item.id}, item.name)));
      if (state.model !== HOST && !(models || []).some((item) => item.id === state.model)) state.model = models ? "" : state.model;
      model.value = state.model;
      const found = modelOf(effective(task));
      const levels = levelsOf(found);
      const think = h("select", {"aria-label": t("board.new.thinking")});
      think.append(h("option", {value: ""}, t("board.new.thinking.default")), ...levels.map((one) => h("option", {value: one}, thinkingLabel(one, found))));
      if (!levels.includes(state.thinking)) state.thinking = "";
      think.value = state.thinking;
      think.disabled = !levels.length;
      const sizes = sizesOf(found);
      const room = h("select", {"aria-label": t("board.new.context"), title: t("desk.set.context.tip")});
      room.append(h("option", {value: ""}, t("board.new.thinking.default")), ...sizes.map((item) => h("option", {value: String(item.id)}, item.label)));
      if (!sizes.some((item) => String(item.id) === String(state.context))) state.context = "";
      room.value = String(state.context || "");
      const busy = h("select", {"aria-label": t("super.direct.busy"), title: t("super.direct.busy.tip")}, h("option", {value: "queue"}, t("super.direct.busy.queue")), h("option", {value: "steer"}, t("super.direct.busy.steer")));
      busy.value = state.busy;
      const lang = h("select", {"aria-label": t("desk.send.lang")}, h("option", {value: ""}, t("board.new.thinking.default")), h("option", {value: "en"}, t("desk.send.lang.en")), h("option", {value: "zh"}, t("desk.send.lang.zh")));
      lang.value = state.lang;
      const checks = h("select", {"aria-label": t("super.direct.checks.name"), title: t("super.direct.checks.tip")}, h("option", {value: ""}, t("super.direct.checks.none")), ...Array.from({length: MAXN + 1}, (_, n) => n).map((n) => h("option", {value: String(n)}, String(n))));
      checks.value = mine === null ? state.checks : mine;
      const fresh = h("input", {type: "checkbox"});
      fresh.checked = state.newChat;
      const rows = [choose(t("board.new.model"), model), choose(t("board.new.thinking"), think)];
      if (sizes.length > 1) rows.push(choose(t("board.new.context"), room));
      rows.push(choose(t("super.direct.busy"), busy), choose(t("desk.send.lang"), lang), choose(t("super.direct.checks.name"), checks));
      const change = (key, value, again) => () => { state[key] = value(); keep(); for (const other of menus) other.redraw(); if (again) fill(); };
      model.addEventListener("change", () => { state.model = model.value; state.thinking = ""; state.context = ""; keep(); for (const other of menus) other.redraw(); });
      think.addEventListener("change", change("thinking", () => think.value));
      room.addEventListener("change", change("context", () => room.value));
      busy.addEventListener("change", change("busy", () => busy.value));
      lang.addEventListener("change", change("lang", () => lang.value));
      fresh.addEventListener("change", change("newChat", () => fresh.checked));
      checks.addEventListener("change", () => { if (mine === null) { state.checks = checks.value; for (const other of menus) other.redraw(); } else { mine = checks.value; paint(); } });
      const reset = h("button", {type: "button", class: "sa-dreset", title: t("super.direct.reset.tip")}, t("super.direct.reset"));
      reset.addEventListener("click", () => { state = {...DEFAULT}; if (mine !== null) mine = ""; keep(); for (const other of menus) other.redraw(); });
      pop.replaceChildren(...rows,
        h("label", {class: "sa-dcheck", title: t("super.direct.new.tip")}, fresh, h("span", null, t("super.direct.new"))),
        h("div", {class: "sa-dfoot"}, files.attach, reset), files.picker, said);
      place();
    }
    // Inside the view: right edges meet, the menu opens upward when there is more room above, and never leaves the view's box.
    function place() {
      if (!pop) return;
      const wide = (fit || document.body).getBoundingClientRect(), at = button.getBoundingClientRect();
      const width = Math.min(300, Math.max(180, wide.width - 16));
      pop.style.width = width + "px";
      pop.style.left = Math.max(wide.left + 8, Math.min(at.right - width, wide.right - width - 8)) + "px";
      const above = at.top - Math.max(wide.top, 0) - 8, below = innerHeight - at.bottom - 8;
      const up = above >= Math.min(pop.scrollHeight, 320) || above > below;
      pop.style.maxHeight = Math.max(120, Math.min(up ? above : below, 380)) + "px";
      pop.style.top = up ? Math.max(4, at.top - 6 - Math.min(pop.scrollHeight, parseFloat(pop.style.maxHeight))) + "px" : at.bottom + 6 + "px";
    }
    const outside = (event) => { if (pop && !pop.contains(event.target) && !button.contains(event.target)) close(false); };
    const keys = (event) => { if (event.key === "Escape") { event.stopPropagation(); close(true); } };
    function close(back) {
      if (!opened) return;
      opened = false;
      button.setAttribute("aria-expanded", "false");
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("keydown", keys, true);
      removeEventListener("resize", place);
      if (pop) pop.remove();
      pop = null;
      if (back) button.focus();
    }
    function open() {
      opened = true;
      button.setAttribute("aria-expanded", "true");
      pop = h("div", {class: "sa-dmenu", role: "dialog", "aria-label": t("super.direct.opts")});
      document.body.append(pop);
      load(task).then(() => { if (opened) fill(); }, () => { /* the menu is drawn as it is */ });
      fill();
      document.addEventListener("pointerdown", outside, true);
      document.addEventListener("keydown", keys, true);
      addEventListener("resize", place);
      const first = pop.querySelector("select, input, button");
      if (first) first.focus();
    }
    button.addEventListener("click", () => (opened ? close(true) : open()));
    const self = {
      button, tray: files.tray, zone: files.zone, redraw, close, reading: files.reading,
      values: () => ({...values(task, mine === null ? undefined : mine), ...(count() ? {files: files.list()} : {})}),
      presetChecks(level) { mine = level === undefined || level === null ? "" : String(level); paint(); },
      clear: () => files.clear(),
      bind(next) { if (next === task) return; task = next || ""; load(task).then(redraw, redraw); redraw(); },
    };
    menus.add(self);
    paint();
    return self;
  }

  return {menu, send, valuesFor: values, receipt, howWord, refusal, whyText, MAX};
})();
