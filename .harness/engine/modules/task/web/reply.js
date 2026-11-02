// The reply panel of a task page (1.6.17, B88): one small pill fixed at the bottom centre ("Say something", key R, a badge for the drafts), a Stop button beside it while the agent works, and, over the
// page, the panel the pill opens: the text and its files, the reply language, the settings of the chat, the drafts, and Send, or Steer while the agent works. Nothing of it stays on the page. A served page
// only, and only for an open task that has a chat. Files come by the Attach button, a paste or a drop, and are read into the page; they go with the message and are not kept anywhere else.
// The text of a message is made by the server (chatsend.py): `/api/send` (kind "answer": the person's own words, the ticked drafts go at the end) when the chat is idle, `/api/steer` while it works.
// The task settings (model, thinking, checks) and the drafts are drawn by desk.js and shown here; the model chosen there goes on every message the board sends. What was typed is kept in the box:
// a poll, a redraw of the page and closing the panel do not touch it. A message that was refused keeps its text and offers it to copy. An approval message (go-req, go-plan, go-promote...) is not made here:
// it has its own button on the card of the wait, which shows the whole message first.
// Needs common.js, serve.js, chat.js (CHAT.stop), live.js (LIVE: the state of the chat, once a second while the panel is open).
"use strict";

const REPLY = (function () {
  const NS = "http://www.w3.org/2000/svg";
  const info = {name: "", show: false, state: "", why: "", count: 0, settings: null, drafts: null, settingsSig: null};
  const mine = {open: false, lang: "", busy: false, fallback: "", previewing: false, timer: 0};
  const MAC = /Mac|iPhone|iPad/.test(navigator.platform || "");

  const icon = (paths, size) => {  // the style gives each its size too: a page style sets the width of an svg
    const node = document.createElementNS(NS, "svg");
    for (const [name, value] of Object.entries({viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", "stroke-width": "1.5", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", width: size, height: size})) node.setAttribute(name, value);
    for (const d of paths) { const part = document.createElementNS(NS, "path"); part.setAttribute("d", d); node.append(part); }
    return node;
  };

  // --- the pill -----------------------------------------------------------------------------------------------------------
  const badge = h("b", {class: "bd", hidden: ""});
  const pill = h("button", {type: "button", class: "rp-pill chat-act", hidden: "", "aria-haspopup": "dialog", "aria-expanded": "false", "aria-keyshortcuts": "R"},
    icon(["M2.5 3h11v7.5H8L5 13v-2.5H2.5z"], 16), h("span", null, t("desk.reply.pill")), h("kbd", null, "R"), badge);

  const halt = h("button", {type: "button", class: "rp-stop chat-act", hidden: "", title: t("desk.reply.stop.tip")}, icon(["M4 4h8v8H4z"], 14), h("span", null, t("board.action.stop")));

  // --- the panel ----------------------------------------------------------------------------------------------------------
  const close = h("button", {type: "button", class: "rp-x", title: t("board.serve.cancel"), "aria-label": t("desk.reply.close")}, icon(["M4 4l8 8M12 4l-8 8"], 14));
  const box = h("textarea", {rows: 4, class: "rp-text", maxlength: 20000, placeholder: t("desk.reply.ph"), "aria-label": t("desk.reply.title")});
  // `mine.lang` stays empty until the person picks one: the chip shows the language the chat replies in, and nothing is added to the message.
  const paintLanguage = (lang) => chips.forEach((item, at) => { const on = ["en", "zh"][at] === lang; item.classList.toggle("on", on); item.setAttribute("aria-pressed", on ? "true" : "false"); });
  const language = (lang) => { mine.lang = lang; paintLanguage(lang); previewSoon(); };
  const chips = ["en", "zh"].map((lang) => {
    const chip = h("button", {type: "button", class: "chip" + (lang === "en" ? " on" : ""), "aria-pressed": lang === "en" ? "true" : "false"}, t("desk.send.lang." + lang));
    chip.addEventListener("click", () => language(lang));
    return chip;
  });
  const settingsSlot = h("div", {class: "rp-set"});
  const draftsSlot = h("div", {class: "rp-dr"});
  const draftHead = h("summary", {title: t("desk.drafts.hint")}, t("desk.drafts.label"));
  const draftBox = h("details", {class: "rp-pv"}, draftHead, draftsSlot);
  const preview = h("pre", {class: "send-preview rp-pre"}, "");
  const whole = h("details", {class: "rp-pv"}, h("summary", null, t("desk.reply.whole")), preview);
  const said = h("div", {class: "bad rp-said"});
  const files = CHAT.fileTray(box, said, () => sync());
  const hint = h("span", {class: "hint rp-hint"});
  const kbd = h("kbd", null, (MAC ? "⌘" : "Ctrl") + " ↵");
  const save = h("button", {type: "button", class: "act", title: t("desk.reply.draft.tip")}, t("desk.reply.draft"));
  const go = h("button", {type: "button", class: "act hot live big"}, t("desk.reply.send"));
  // The skills that work on this task (1.6.64): a click puts the slash command in the box, and the person presses Send. Nothing goes by itself.
  const skillRow = h("div", {class: "rp-skills", hidden: ""});
  function fillSkills() {
    if (skillRow.dataset.done) return;
    skillRow.dataset.done = "1";
    SERVE.post("/api/skill", {step: "list"}).then((data) => {
      const items = data.result.skills.filter((item) => item.opens === "reply" && item.place.includes("task"));
      skillRow.replaceChildren(...items.map((item) => {
        const chip = h("button", {type: "button", class: "chip", title: item.about}, item.label);
        chip.addEventListener("click", () => { box.value = "/" + item.name + " " + box.value; box.dispatchEvent(new Event("input", {bubbles: true})); box.focus(); });
        return chip;
      }));
      skillRow.hidden = !items.length;
    }, () => { delete skillRow.dataset.done; });
  }
  const panel = h("div", {class: "rp", role: "dialog", "aria-label": t("desk.reply.title"), hidden: ""},
    h("div", {class: "rp-h"}, h("b", null, t("desk.reply.title")), close), box, files.tray,
    skillRow, h("div", {class: "rp-lang"}, files.attach, files.picker, h("span", {class: "sub"}, t("desk.send.lang")), h("span", {class: "chips"}, chips)),
    settingsSlot, draftBox, whole, said, h("div", {class: "rp-f"}, hint, kbd, save, go));
  document.body.append(h("div", {class: "rp-bar"}, pill, halt), panel);

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
    go.disabled = mine.busy || now.kind === "off" || !box.value.trim() || files.reading();
    save.disabled = mine.busy || !box.value.trim() || !info.saveDraft;
    if (hint.textContent !== now.hint) hint.textContent = now.hint;
    halt.hidden = stateNow() !== "busy" || !info.show;
    kbd.hidden = go.disabled;
    whole.hidden = now.kind !== "send";
    pill.classList.toggle("on", mine.open);
    const count = info.count;
    badge.hidden = !count;
    if (count && badge.textContent !== String(count)) badge.textContent = String(count);
    pill.title = count ? t("desk.reply.pill.drafts", {count}) : "";
    const heading = t("desk.drafts.label") + (count ? " \u00b7 " + count : "");
    if (draftHead.textContent !== heading) draftHead.textContent = heading;
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

  function saveDraft() {
    const text = box.value.trim();
    if (!text || mine.busy || !info.saveDraft) return;
    mine.busy = true;
    sync();
    info.saveDraft(text).then((kept) => {
      mine.busy = false;
      if (kept) box.value = "";
      sync();
      box.focus();
    });
  }

  function send() {
    const text = box.value.trim();
    const now = mode();
    if (!text || mine.busy || now.kind === "off" || files.reading()) return;
    mine.busy = true;
    said.replaceChildren();
    sync();
    const attachments = files.list();
    const call = now.kind === "steer" ? SERVE.post("/api/steer", {task: info.name, text, lang: mine.lang, attachments}) : SERVE.post("/api/send", {task: info.name, kind: "answer", lang: mine.lang, note: "", body: text, step: "act", attachments});
    call.then(() => {
      mine.busy = false;
      box.value = "";
      files.clear();
      shut(false);
      sync();
      SERVE.done();
    }, (error) => {
      mine.busy = false;
      const fallback = error && error.data && error.data.fallback;
      said.replaceChildren(...SERVE.reasons((error && error.message) || String(error)), ...(fallback ? [h("p", {class: "sub"}, t("desk.send.copy.hint")), copyFallback(fallback)] : []));
      sync();
    });
  }

  function open() {
    fillSkills();
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
  save.addEventListener("click", saveDraft);
  halt.addEventListener("click", () => { shut(false); CHAT.stop({name: info.name}); });  // its own confirm dialog; this panel steps aside
  files.zone(panel);
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
      if (!mine.lang) paintLanguage(next.reply || "en");
      Object.assign(info, next);
      const was = pill.hidden;
      pill.hidden = !info.show;
      document.documentElement.classList.toggle("has-reply", info.show);
      if (!info.show && mine.open) shut(false);
      if (was !== pill.hidden) sync();
      sync();
      fillSlots(false);
      if (!info.show) return;
      try {  // the board sent the person here to answer
        if (sessionStorage.getItem("harness.reply") === info.name) { sessionStorage.removeItem("harness.reply"); open(); }
      } catch (error) { /* no storage: the pill is there */ }
    },
    count(value) { info.count = value; sync(); },
    isOpen: () => mine.open,
    shown: () => info.show,
    open,
    // A message that was withdrawn: its words are back in the box to change and send again. Its files are not kept: the panel names them.
    restore(found) {
      box.value = found.text;
      if (found.lang) language(found.lang);
      open();
      sync();
      if (found.files && found.files.length) said.append(h("p", null, t("desk.reply.files.again", {names: found.files.join(", ")})));
    },
  };
})();
