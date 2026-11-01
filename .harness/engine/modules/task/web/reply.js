// The reply panel of a task page (1.6.17, B88): one small pill fixed at the bottom centre ("Say something", key R, a badge for the drafts) and, over the page, the panel it opens: the text, the reply
// language, the model and the thinking level, the drafts, and Send, or Steer while the agent works, and Stop. Nothing of it stays on the page. A served page only, and only for an open task that has a chat.
// The text of a message is made by the server (chatsend.py): `/api/send` (kind "answer": the person's own words, the ticked drafts go at the end) when the chat is idle, `/api/steer` while it works.
// The task settings (model, thinking, checks) and the drafts are drawn by desk.js and shown here; the model chosen there goes on every message the board sends. What was typed is kept in the box:
// a poll, a redraw of the page and closing the panel do not touch it. A message that was refused keeps its text and offers it to copy. An approval message (go-req, go-plan, go-promote...) is not made here:
// it has its own button on the card of the wait, which shows the whole message first.
// Needs common.js, serve.js, chat.js (CHAT.stop), live.js (LIVE: the state of the chat, once a second while the panel is open).
"use strict";

const REPLY = (function () {
  const NS = "http://www.w3.org/2000/svg";
  const info = {name: "", show: false, state: "", why: "", count: 0, settings: null, drafts: null, settingsSig: null};
  const mine = {open: false, lang: "en", busy: false, fallback: "", previewing: false, timer: 0};
  const MAC = /Mac|iPhone|iPad/.test(navigator.platform || "");

  const icon = (paths, size) => {
    const node = document.createElementNS(NS, "svg");
    for (const [name, value] of Object.entries({viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", "stroke-width": "1.5", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", width: size, height: size})) node.setAttribute(name, value);
    for (const d of paths) { const part = document.createElementNS(NS, "path"); part.setAttribute("d", d); node.append(part); }
    return node;
  };

  // --- the pill -----------------------------------------------------------------------------------------------------------
  const badge = h("b", {class: "bd", hidden: ""});
  const pill = h("button", {type: "button", class: "rp-pill chat-act", hidden: "", "aria-haspopup": "dialog", "aria-expanded": "false", "aria-keyshortcuts": "R"},
    icon(["M2.5 3h11v7.5H8L5 13v-2.5H2.5z"], 16), h("span", null, t("desk.reply.pill")), h("kbd", null, "R"), badge);

  // --- the panel ----------------------------------------------------------------------------------------------------------
  const close = h("button", {type: "button", class: "rp-x", title: t("board.serve.cancel"), "aria-label": t("desk.reply.close")}, icon(["M4 4l8 8M12 4l-8 8"], 14));
  const box = h("textarea", {rows: 4, class: "rp-text", maxlength: 20000, placeholder: t("desk.reply.ph"), "aria-label": t("desk.reply.title")});
  const chips = ["en", "zh"].map((lang) => {
    const chip = h("button", {type: "button", class: "chip" + (lang === "en" ? " on" : ""), "aria-pressed": lang === "en" ? "true" : "false"}, t("desk.send.lang." + lang));
    chip.addEventListener("click", () => { mine.lang = lang; chips.forEach((item, at) => { const on = ["en", "zh"][at] === lang; item.classList.toggle("on", on); item.setAttribute("aria-pressed", on ? "true" : "false"); }); previewSoon(); });
    return chip;
  });
  const settingsSlot = h("div", {class: "rp-set"});
  const draftsSlot = h("div", {class: "rp-dr"});
  const preview = h("pre", {class: "send-preview rp-pre"}, "");
  const whole = h("details", {class: "rp-pv"}, h("summary", null, t("desk.reply.whole")), preview);
  const said = h("div", {class: "bad rp-said"});
  const hint = h("span", {class: "hint rp-hint"});
  const kbd = h("kbd", null, (MAC ? "⌘" : "Ctrl") + " ↵");
  const stop = h("button", {type: "button", class: "act", hidden: ""}, t("board.action.stop"));
  const go = h("button", {type: "button", class: "act hot live big"}, t("desk.reply.send"));
  const panel = h("div", {class: "rp", role: "dialog", "aria-label": t("desk.reply.title"), hidden: ""},
    h("div", {class: "rp-h"}, h("b", null, t("desk.reply.title")), close), box,
    h("div", {class: "rp-lang"}, h("span", {class: "sub"}, t("desk.send.lang")), h("span", {class: "chips"}, chips)),
    settingsSlot, draftsSlot, whole, said, h("div", {class: "rp-f"}, hint, kbd, stop, go));
  document.body.append(pill, panel);

  const typing = (node) => node instanceof Element && (/^(INPUT|TEXTAREA|SELECT)$/.test(node.tagName) || node.isContentEditable);
  const stateNow = () => {
    const live = typeof LIVE !== "undefined" ? LIVE.data() : null;
    return live && live.bound && live.state ? live.state : info.state;
  };

  // What the button does now: send when idle, steer while it works; nothing while the chat waits for a person's yes or when it cannot be reached.
  function mode() {
    const state = stateNow();
    if (document.documentElement.classList.contains("vs-down")) return {kind: "off", hint: t("desk.reply.off")};
    if (state === "busy") return {kind: "steer", hint: t("desk.reply.steer.hint")};
    if (state === "idle") return {kind: "send", hint: ""};
    if (state === "input") return {kind: "off", hint: t("desk.reply.input")};
    return {kind: "off", hint: t("desk.reply.state", {state: t("desk.chat." + (state || "unknown"))})};
  }

  function sync() {
    const now = mode();
    const text = now.kind === "steer" ? t("desk.reply.steer") : t("desk.reply.send");
    const label = mine.busy ? t("board.serve.working") : text;
    if (go.textContent !== label) go.textContent = label;
    go.disabled = mine.busy || now.kind === "off" || !box.value.trim();
    if (hint.textContent !== now.hint) hint.textContent = now.hint;
    stop.hidden = stateNow() !== "busy";
    kbd.hidden = go.disabled;
    whole.hidden = now.kind !== "send";
    pill.classList.toggle("on", mine.open);
    const count = info.count;
    badge.hidden = !count;
    if (count && badge.textContent !== String(count)) badge.textContent = String(count);
    pill.title = count ? t("desk.reply.pill.drafts", {count}) : "";
  }

  // The whole message as the server makes it (text, language, the ticked drafts at the end): read only when the person opens "the whole message".
  function previewSoon() {
    clearTimeout(mine.timer);
    if (!whole.open) return;
    mine.timer = setTimeout(() => {
      SERVE.post("/api/send", {task: info.name, kind: "answer", lang: mine.lang, note: "", body: box.value, step: "preview"}).then((data) => { preview.textContent = data.result.text; }, (error) => { preview.textContent = (error && error.message) || ""; });
    }, 250);
  }

  function copyFallback(text) {
    const button = h("button", {type: "button", class: "act", "data-label": t("desk.go.copy")}, t("desk.go.copy"));
    button.addEventListener("click", () => copyCommand(button, text));
    return button;
  }

  function send() {
    const text = box.value.trim();
    const now = mode();
    if (!text || mine.busy || now.kind === "off") return;
    mine.busy = true;
    said.replaceChildren();
    sync();
    const call = now.kind === "steer" ? SERVE.post("/api/steer", {task: info.name, text, lang: mine.lang}) : SERVE.post("/api/send", {task: info.name, kind: "answer", lang: mine.lang, note: "", body: text, step: "act"});
    call.then(() => {
      mine.busy = false;
      box.value = "";
      shut(false);
      sync();
      SERVE.done();
    }, (error) => {
      mine.busy = false;
      const fallback = error && error.data && error.data.fallback;
      said.replaceChildren(...SERVE.reasons((error && error.message) || String(error)), fallback ? h("p", {class: "sub"}, t("desk.send.copy.hint")) : null, fallback ? copyFallback(fallback) : null);
      sync();
    });
  }

  function open() {
    if (!info.show || mine.open) return;
    mine.open = true;
    panel.hidden = false;
    pill.setAttribute("aria-expanded", "true");
    fillSlots(true);
    if (typeof LIVE !== "undefined") LIVE.want("reply", true);
    sync();
    box.focus();
    previewSoon();
  }
  function shut(focus) {
    if (!mine.open) return;
    mine.open = false;
    panel.hidden = true;
    pill.setAttribute("aria-expanded", "false");
    if (typeof LIVE !== "undefined") LIVE.want("reply", false);
    sync();
    if (focus) pill.focus();
  }

  // The settings and the drafts are made by desk.js. The drafts node stays the same one; the settings are made again when their data changed, but never while one of their controls has the focus.
  let settingsSig = "";
  function fillSlots(force) {
    if (!mine.open || !info.show) return;
    if (info.drafts && draftsSlot.firstChild !== info.drafts) draftsSlot.replaceChildren(info.drafts);
    if (info.settings && (force || info.settingsSig !== settingsSig) && !settingsSlot.contains(document.activeElement)) {
      settingsSig = info.settingsSig;
      const node = info.settings();
      settingsSlot.replaceChildren(...(node ? [node] : []));
    }
  }

  pill.addEventListener("click", () => (mine.open ? shut(true) : open()));
  close.addEventListener("click", () => shut(true));
  go.addEventListener("click", send);
  stop.addEventListener("click", () => { shut(false); CHAT.stop({name: info.name}); });  // its own confirm dialog; this panel steps aside
  box.addEventListener("input", () => { sync(); previewSoon(); said.replaceChildren(); });
  box.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && !event.isComposing) { event.preventDefault(); send(); }
  });
  whole.addEventListener("toggle", () => { if (whole.open) previewSoon(); });
  if (typeof LIVE !== "undefined") LIVE.onChange(() => { sync(); });

  // R opens it, Esc closes it. R is a letter: it does nothing while the person types in a field, while a dialog or the palette is open, or with Cmd, Ctrl or Alt.
  document.addEventListener("keydown", (event) => {
    if (!info.show || event.isComposing) return;
    if (event.key === "Escape" && mine.open && !(typing(event.target) && event.target !== box) && !SERVE.busy() && !(typeof SHELL !== "undefined" && SHELL.isOpen())) { event.preventDefault(); shut(true); return; }
    if ((event.key !== "r" && event.key !== "R") || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
    if (typing(event.target) || SERVE.busy() || (typeof SHELL !== "undefined" && SHELL.isOpen())) return;
    event.preventDefault();
    open();
  });

  return {
    // desk.js says, with every drawing: is there a chat to talk to (`show`), the state of the chat, how many drafts, and how to make the settings and the drafts.
    update(next) {
      Object.assign(info, next);
      const was = pill.hidden;
      pill.hidden = !info.show;
      document.documentElement.classList.toggle("has-reply", info.show);
      if (!info.show && mine.open) shut(false);
      if (was !== pill.hidden) sync();
      sync();
      fillSlots(false);
    },
    count(value) { info.count = value; sync(); },
    isOpen: () => mine.open,
    open,
  };
})();
