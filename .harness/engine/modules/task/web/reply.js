// The reply panel of a task page (1.6.17, B88): one small pill fixed at the bottom centre ("Say something", key R, a badge for the drafts), a Stop button beside it while the agent works, and, over the
// page, the panel the pill opens: the text and its files, the reply language, the settings of the chat, the drafts, and Send, or Steer while the agent works. Nothing of it stays on the page. A served page
// only, and only for an open task that has a chat. Files come by the Attach button, a paste or a drop, and are read into the page; they go with the message and are not kept anywhere else.
// The text of a message is made by the server (chatsend.py): `/api/send` (kind "answer": the person's own words, the ticked drafts go at the end) when the chat is idle, `/api/steer` while it works.
// The task settings (model, thinking, checks) and the drafts are drawn by desk.js and shown here; the model chosen there goes on every message the board sends. What was typed is kept in the box:
// a poll, a redraw of the page and closing the panel do not touch it. A message that was refused keeps its text and offers it to copy. An approval message (go-req, go-plan, go-promote...) is not made here:
// it has its own button on the card of the wait, which shows the whole message first.
// 1.6.99: beside Stop, Withdraw takes the newest message back (a turn that runs is stopped first) and puts its words in the box, and Try again runs a turn that ended in an error the host can
// retry. While the agent works the panel also offers Queue: the message goes after the turn, as the next one. The queued messages are listed in the panel, each one can be taken back to the box.
// Needs common.js, serve.js, chat.js (CHAT.stop, CHAT.withdraw), live.js (LIVE: the state of the chat, its queued messages and whether Try again fits; once a second while the panel is open).
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
  const back = h("button", {type: "button", class: "rp-stop rp-line chat-act", hidden: "", title: t("desk.reply.back.tip")}, icon(["M6 3.5L2.5 7 6 10.5", "M2.5 7h7a3.5 3.5 0 0 1 0 7H8"], 14), h("span", null, t("desk.reply.back")));
  const again = h("button", {type: "button", class: "rp-stop rp-line chat-act", hidden: "", title: t("desk.reply.retry.tip")}, icon(["M13 8a5 5 0 1 1-1.6-3.7", "M13.2 2.5v2.8h-2.8"], 14), h("span", null, t("desk.reply.retry")));

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
  const later = h("button", {type: "button", class: "act", hidden: "", title: t("desk.reply.queue.tip")}, t("desk.reply.queue"));
  const waiting = h("div", {class: "rp-q", hidden: ""});  // the queued messages of the chat
  // The skills that work on this task (1.6.64): a click puts the slash command in the box, and the person presses Send. Nothing goes by itself.
  const skillRow = h("div", {class: "rp-skills", hidden: ""});
  function fillSkills() {
    if (skillRow.dataset.done) return;
    skillRow.dataset.done = "1";
    SERVE.post("/api/skill", {step: "list"}).then((data) => {
      const items = data.result.skills.filter((item) => item.opens === "reply" && (item.place.includes("task") || item.place.includes("all")));
      skillRow.replaceChildren(...items.map((item) => {
        const chip = h("button", {type: "button", class: "chip", title: item.about}, item.label);
        chip.addEventListener("click", () => { box.value = "/" + item.name + " " + box.value; box.dispatchEvent(new Event("input", {bubbles: true})); box.focus(); });
        return chip;
      }));
      skillRow.hidden = !items.length;
    }, () => { delete skillRow.dataset.done; });
  }
  const head = h("div", {class: "rp-h", title: t("desk.reply.move")}, h("b", null, t("desk.reply.title")), close);
  const edges = ["n", "s", "e", "w", "ne", "nw", "se", "sw"].map((edge) => h("div", {class: "rp-edge rp-" + edge, "data-edge": edge, "aria-hidden": "true"}));
  const panel = h("div", {class: "rp", role: "dialog", "aria-label": t("desk.reply.title"), hidden: ""}, head,
    h("div", {class: "rp-scroll"}, box, files.tray,
      skillRow, h("div", {class: "rp-lang"}, files.attach, files.picker, h("span", {class: "sub"}, t("desk.send.lang")), h("span", {class: "chips"}, chips)),
      settingsSlot, draftBox, whole, waiting, said), h("div", {class: "rp-f"}, hint, kbd, save, later, go), edges);
  document.body.append(h("div", {class: "rp-bar"}, pill, halt, back, again), panel);
  // Where the panel stands (1.6.103): the person moves it by its header and sizes it by any edge or corner, so it does not cover the messages it answers. It floats over the page and moves
  // nothing in it. The place is kept in this browser; a double click on the header puts it back. On a narrow screen it stays where it is made to be.
  const PLACE = "harness.reply.place";
  const MIN_W = 340, MIN_H = 260, GAP = 8;
  let place = null;
  try { place = JSON.parse(localStorage.getItem(PLACE) || "null"); } catch (error) { place = null; }
  const narrow = () => window.matchMedia("(max-width: 600px)").matches;
  function fit(box) {
    const width = Math.min(Math.max(box.width, MIN_W), innerWidth - 2 * GAP), height = Math.min(Math.max(box.height, MIN_H), innerHeight - 2 * GAP);
    return {width, height, left: Math.min(Math.max(box.left, GAP), innerWidth - width - GAP), top: Math.min(Math.max(box.top, GAP), innerHeight - height - GAP)};
  }
  function placeNow() {
    const on = Boolean(place) && !narrow();
    panel.classList.toggle("placed", on);
    const box = on ? fit(place) : null;
    for (const key of ["left", "top", "width", "height"]) panel.style[key] = box ? box[key] + "px" : "";
  }
  function keepPlace() { try { if (place) localStorage.setItem(PLACE, JSON.stringify(place)); else localStorage.removeItem(PLACE); } catch (error) { /* kept while the page is open */ } }
  function follow(event, edge) {  // a drag of the header (`edge` "") or of an edge or a corner
    if (narrow() || event.button !== 0 || (!edge && event.target.closest("button"))) return;
    event.preventDefault();
    const start = panel.getBoundingClientRect(), x0 = event.clientX, y0 = event.clientY, grip = event.currentTarget;
    grip.setPointerCapture(event.pointerId);
    panel.classList.add("moving");
    const move = (next) => {
      const dx = next.clientX - x0, dy = next.clientY - y0;
      const width = Math.max(MIN_W, start.width + (edge.includes("e") ? dx : edge.includes("w") ? -dx : 0));
      const height = Math.max(MIN_H, start.height + (edge.includes("s") ? dy : edge.includes("n") ? -dy : 0));
      const left = !edge ? start.left + dx : edge.includes("w") ? start.right - width : start.left;  // the side not dragged stays where it is
      const top = !edge ? start.top + dy : edge.includes("n") ? start.bottom - height : start.top;
      place = {left, top, width, height};
      placeNow();
    };
    const up = () => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", up);
      grip.removeEventListener("pointercancel", up);
      panel.classList.remove("moving");
      if (place) place = fit(place);
      keepPlace();
    };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", up);
    grip.addEventListener("pointercancel", up);
  }
  head.addEventListener("pointerdown", (event) => follow(event, ""));
  head.addEventListener("dblclick", (event) => { if (event.target.closest("button")) return; place = null; keepPlace(); placeNow(); });
  for (const node of edges) node.addEventListener("pointerdown", (event) => follow(event, node.dataset.edge));
  window.addEventListener("resize", () => { if (!panel.hidden) placeNow(); });
  placeNow();

  const liveNow = () => {
    const live = typeof LIVE !== "undefined" ? LIVE.data() : null;
    return live && live.bound ? live : null;
  };

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
    const state = stateNow(), live = liveNow();
    halt.hidden = state !== "busy" || !info.show;
    back.hidden = !info.show || !live || !["busy", "idle", "input", "error"].includes(state) || !(live.items || []).some((item) => item.k === "me");
    again.hidden = !info.show || !live || !live.retry;
    later.hidden = now.kind !== "steer";
    later.disabled = mine.busy || !box.value.trim() || files.reading();
    paintQueue(live);
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

  // The queued messages (1.6.99): Copilot sends each as the next turn when the one that runs ends. Take back: it leaves the queue and its words come into the box.
  function paintQueue(live) {
    const list = (live && live.queued) || [];
    const sig = JSON.stringify(list);
    if (waiting.dataset.sig === sig) return;
    waiting.dataset.sig = sig;
    waiting.hidden = !list.length;
    waiting.replaceChildren(...(list.length ? [h("div", {class: "sub"}, t("desk.reply.queued", {n: list.length}))] : []), ...list.map((item) => {
      const take = h("button", {type: "button", class: "act", title: t("desk.reply.unqueue.tip")}, t("desk.reply.unqueue"));
      take.addEventListener("click", () => {
        take.disabled = true;
        SERVE.post("/api/unqueue", {task: info.name, id: item.id}).then((data) => { restore(data.result); }, (error) => { take.disabled = false; said.replaceChildren(...SERVE.reasons((error && error.message) || String(error))); });
      });
      return h("div", {class: "rp-qi"}, h("span", {class: "rp-qt", title: item.text}, item.text), take);
    }));
  }

  function send(queue) {
    const text = box.value.trim();
    const now = mode();
    if (!text || mine.busy || now.kind === "off" || files.reading() || (queue && now.kind !== "steer")) return;
    mine.busy = true;
    said.replaceChildren();
    sync();
    const attachments = files.list();
    const call = queue ? SERVE.post("/api/queue", {task: info.name, text, lang: mine.lang, attachments})
      : now.kind === "steer" ? SERVE.post("/api/steer", {task: info.name, text, lang: mine.lang, attachments}) : SERVE.post("/api/send", {task: info.name, kind: "answer", lang: mine.lang, note: "", body: text, step: "act", attachments});
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
    placeNow();  // the window may have changed size while the panel was shut
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
  go.addEventListener("click", () => send(false));
  later.addEventListener("click", () => send(true));
  save.addEventListener("click", saveDraft);
  halt.addEventListener("click", () => { shut(false); CHAT.stop({name: info.name}); });  // its own confirm dialog; this panel steps aside
  back.addEventListener("click", () => { shut(false); CHAT.withdraw({name: info.name}, restore); });
  again.addEventListener("click", () => {
    again.disabled = true;
    SERVE.post("/api/resume", {task: info.name}).then(() => { again.disabled = false; SERVE.done(); }, (error) => { again.disabled = false; SERVE.failed(error, t("desk.reply.retry")); });
  });
  files.zone(panel);
  box.addEventListener("input", () => { sync(); previewSoon(); said.replaceChildren(); });
  box.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && !event.isComposing) { event.preventDefault(); send(false); }
  });
  whole.addEventListener("toggle", () => { if (whole.open) previewSoon(); });
  if (typeof LIVE !== "undefined") LIVE.onChange(() => { sync(); });

  // A message that was withdrawn or taken out of the queue: its words are back in the box to change and send again, after what is typed there. Its files are not kept: the panel names them.
  function restore(found) {
    const typed = box.value.trim();
    box.value = typed ? typed + "\n\n" + found.text : found.text;
    if (found.lang && !typed) language(found.lang);
    open();
    sync();
    if (found.files && found.files.length) said.append(h("p", null, t("desk.reply.files.again", {names: found.files.join(", ")})));
  }

  // R opens it, Esc closes it. R is a letter: it does nothing while the person types in a field, while a dialog or the palette is open, or with Cmd, Ctrl or Alt.
  document.addEventListener("keydown", (event) => {
    if (!info.show || event.isComposing) return;
    if (event.key === "Escape" && mine.open && !(typing(event.target) && event.target !== box) && !SERVE.open() && !(typeof SHELL !== "undefined" && SHELL.isOpen())) { event.preventDefault(); shut(true); return; }
    if ((event.key !== "r" && event.key !== "R") || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
    if (typing(event.target) || SERVE.open() || (typeof SHELL !== "undefined" && SHELL.isOpen())) return;
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
    restore,
  };
})();
