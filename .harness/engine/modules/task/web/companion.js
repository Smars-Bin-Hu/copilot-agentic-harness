// The pop-out of the super agent view (1.8.1, "the companion"; 1.8.25: a plain chat window): a small window that stays on top of every other window, so the person can work in VS Code and still talk to the super agent and handle what waits.
// It is a Document Picture-in-Picture window (Chrome, Edge): `documentPictureInPicture.requestWindow`, opened from a click. Its document is empty, so the styles of this page are copied in
// (they are inlined in the page, with companion.css) and `data-theme` / `lite` follow the page. The window shares this page's JavaScript and never asks the server: it reads what the super view holds
// (`pop.snapshot`, `pop.chat`) and is told when that changes (`pop.subscribe`); super.js keeps polling while the window is open, even when the view itself is not shown.
// What it shows: one line (four counts with a dot and no words, the card button with the number that waits, and "open in the browser"), the conversation with the super agent, and one input.
// What waits comes as ONE card between the line and the chat; the card button puts it away and back (the choice is kept while the window is open). Its buttons are the very buttons of the
// super view (`pop.buttonsFor`), so every action goes through SERVE.act / CHAT as it does in the view. The words typed go through `pop.send`, the send path of the view's own input ("@task words" included).
// The window never sets its own size: the person drags it where they want and the layout follows. No task page is shown here: "Open" brings this page forward and shows the super agent (the task in its deck) through `pop.front`.
// The windows of an approval (the code field) open in this page, not in the small window: the window tells the person (one line with "Show it") and takes the page's focus.
// Needs common.js, serve.js and super.js, which calls `COMPANION.open`.
"use strict";

const COMPANION = (function () {
  let win = null;

  // "": it can open; else the reason, for the hover of the button.
  function unsupported() {
    if (!window.isSecureContext) return t("super.pop.insecure");
    return window.documentPictureInPicture ? "" : t("super.pop.nosupport");
  }

  async function open(pop) {
    if (win && !win.closed) return;  // one window at a time
    if (unsupported()) return;
    let made;
    try { made = await window.documentPictureInPicture.requestWindow({width: 340, height: 440}); } catch (error) { SERVE.failed(new Error(t("super.pop.failed"))); return; }  // the size it opens with; it is never set again
    win = made;
    run(made, pop);
  }

  function run(pip, pop) {
    const doc = pip.document;
    const main = document.documentElement;
    let alive = true;
    const state = {snap: pop.snapshot(), cardOn: true, cur: "", curTask: "", sig: "", chatSig: "", dialog: false, note: "", sending: false, replies: new Map(), previews: new Map()};

    // ---------- the document of the window ----------
    for (const node of document.querySelectorAll("style, link[rel=stylesheet]")) doc.head.append(doc.importNode(node, true));
    doc.title = t("super.name");
    const copyLook = () => { for (const name of ["data-theme", "class", "lang"]) { const value = main.getAttribute(name); if (value === null) doc.documentElement.removeAttribute(name); else doc.documentElement.setAttribute(name, value); } };
    copyLook();
    const look = new MutationObserver(copyLook);
    look.observe(main, {attributes: true, attributeFilter: ["data-theme", "class", "lang"]});
    doc.body.className = "cp-doc";

    // ---------- the parts ----------
    const counts = h("div", {class: "cp-counts", role: "group"});
    const badge = h("span", {class: "cp-badge", hidden: ""});
    const listBtn = h("button", {type: "button", class: "cp-cb cp-tog", title: t("super.pop.card"), "aria-label": t("super.pop.card"), "aria-pressed": "true"}, "☰", badge);
    const outBtn = h("button", {type: "button", class: "cp-cb", title: t("super.pop.out"), "aria-label": t("super.pop.out")}, "↗");
    const top = h("div", {class: "cp-top"}, counts, h("span", {class: "cp-sp"}), listBtn, outBtn);
    const dialogLine = h("div", {class: "cp-dialog", hidden: "", role: "status"});
    const cardBox = h("div", {class: "cp-cardbox", hidden: ""});
    const chat = h("div", {class: "cp-chat", role: "log", "aria-live": "polite"});
    const field = h("textarea", {class: "cp-field", rows: 1, maxlength: 2000, placeholder: t("super.pop.ph"), "aria-label": t("super.pop.ph")});
    const go = h("button", {type: "button", class: "cp-send", title: t("super.send"), "aria-label": t("super.send")}, "↑");
    const note = h("div", {class: "cp-note", role: "status", hidden: ""});
    const input = h("div", {class: "cp-in"}, note, h("div", {class: "cp-box"}, field, go));
    doc.body.append(h("div", {class: "cp"}, top, dialogLine, cardBox, chat, input));

    // ---------- the top line ----------
    const COUNTS = [["run", "super.pop.n.run"], ["wait", "super.pop.n.wait"], ["err", "super.pop.n.err"], ["quiet", "super.pop.n.quiet"]];
    function drawTop(snap) {
      const numbers = {run: snap.working, wait: snap.items.length, err: (snap.error || 0) + (snap.stuck || 0), quiet: snap.quiet || 0};
      counts.replaceChildren(...COUNTS.map(([key, name]) => h("span", {class: "cp-n", title: t(name)}, h("i", {class: "cp-dot " + key}), numbers[key])));
      const waiting = snap.items.length;
      badge.hidden = !waiting;
      badge.textContent = waiting;
      listBtn.classList.toggle("on", state.cardOn && waiting > 0);
      listBtn.setAttribute("aria-pressed", String(state.cardOn));
    }

    // ---------- the card: one item that waits ----------
    const items = () => state.snap.items;
    function current() {
      const list = items();
      let at = list.findIndex((item) => item.id === state.cur);
      if (at < 0) at = Math.min(Math.max(0, list.findIndex((item) => item.task === state.curTask)), list.length - 1);
      if (at < 0 && list.length) at = 0;
      if (list[at]) { state.cur = list[at].id; state.curTask = list[at].task; }
      return at;
    }
    function move(step) {
      const list = items();
      if (!list.length) return;
      state.cur = list[(current() + step + list.length) % list.length].id;
      state.curTask = "";
      drawCard(true);
    }
    // Brings this page to the front and shows the super agent there; with a task, that task opens in its deck.
    function toPage(task) {
      try { window.focus(); } catch (error) { /* a browser may keep the focus where it is */ }
      if (pop.front) pop.front(task || "");
    }
    function buttons(item) {
      const nodes = pop.buttonsFor(item);
      nodes.forEach((node, at) => {
        if (item.actions[at] && node.matches("button, a")) node.dataset.action = item.actions[at].action;
        for (const one of node.matches("button, a") ? [node] : node.querySelectorAll("button")) one.classList.add("cp-act");  // a held call, Accept and a stuck chat bring more than one control in a box: the keys find the buttons in it
      });
      return nodes;
    }
    // The reply box and the preview are the super view's own (pop.replyFor, pop.previewFor); one made per item, so a redraw keeps the typed words and the open fold.
    function cached(store, item, make) {
      if (!store.has(item.id)) store.set(item.id, make(item));
      return store.get(item.id);
    }
    function card(item, at, w) {
      const asks = pop.asksPerson(item);
      const what = h("div", {class: "cp-text" + (asks || pop.prose(item) ? " ask" : "") + (pop.prose(item) ? " prose" : ""), title: pop.fullOf(item)}, pop.mainOf(item));
      if (asks || pop.prose(item)) { what.tabIndex = 0; what.addEventListener("click", () => what.classList.toggle("open")); }
      if (pop.hasCalls(item)) what.hidden = true;  // the held calls below show the command with its code
      const joint = pop.jointNote(item);
      const prev = h("button", {type: "button", class: "cp-cb", title: t("super.pop.prev"), "aria-label": t("super.pop.prev")}, "‹"), next = h("button", {type: "button", class: "cp-cb", title: t("super.pop.next"), "aria-label": t("super.pop.next")}, "›");
      prev.addEventListener("click", () => move(-1)); next.addEventListener("click", () => move(1));
      const open = h("button", {type: "button", class: "cp-b", title: t("super.pop.open.tip"), "aria-label": t("super.pop.open.tip")}, t("super.pop.open.go"));
      open.addEventListener("click", () => toPage(item.task));
      const acts = h("div", {class: "cp-acts"}, buttons(item), open, h("span", {class: "cp-nav"}, prev, (at + 1) + "/" + w, next));
      acts.addEventListener("click", (event) => { if (event.target !== open) setTimeout(() => { try { window.focus(); } catch (error) { /* the page may keep its place */ } }, 0); });  // an approval opens its window in the page
      const waited = item.waited_s === null || item.waited_s === undefined ? "" : clock(item.waited_s);
      return h("div", {class: "cp-card"},
        h("div", {class: "cp-head"}, h("b", {class: "cp-task", title: item.task}, item.label || item.task), h("span", {class: "cp-why"}, pop.why(item)), waited ? h("span", {class: "cp-wait", title: t("super.waited", {time: waited})}, waited) : null),
        what, ...pop.extraFor(item), joint ? h("div", {class: "cp-joint"}, joint) : null, cached(state.replies, item, pop.replyFor), cached(state.previews, item, pop.previewFor), acts);
    }
    function drawCard(force) {
      const snap = state.snap, w = snap.items.length, at = current(), item = snap.items[at];
      const show = state.cardOn && w > 0;
      cardBox.hidden = !show;
      if (!show) { state.sig = ""; if (cardBox.firstChild) cardBox.replaceChildren(); return; }
      const sig = JSON.stringify([w, item.id, pop.mainOf(item), pop.sigFor(item), state.dialog]);
      if (!force && sig === state.sig) return;
      state.sig = sig;
      const typing = doc.activeElement;
      cardBox.replaceChildren(card(item, at, w));
      if (typing && typing !== doc.body && typing.isConnected && cardBox.contains(typing)) typing.focus();  // a redraw does not take the focus from a reply box
    }

    // ---------- the chat ----------
    // The agent's words are drawn as the view draws them (pop.rich); a link to a task opens it in the browser page, never here.
    function bubble(one) {
      if (one.role === "you") return h("div", {class: "cp-row me"}, h("div", {class: "cp-bub me" + (one.pending ? " pending" : "")}, one.text));
      if (one.role === "ask") {
        return h("div", {class: "cp-ask"}, h("div", {class: "cp-row me"}, h("div", {class: "cp-bub me"}, h("code", {class: "cp-at"}, "@" + one.task), " " + one.text)),
          one.line ? h("div", {class: "cp-line" + (one.state === "failed" ? " bad" : "")}, one.line) : null,
          one.answer ? h("div", {class: "cp-row"}, h("div", {class: "cp-bub"}, ...pop.rich(one.answer))) : null);
      }
      return h("div", {class: "cp-row"}, h("div", {class: "cp-bub"}, ...pop.rich(one.text)));
    }
    function drawChat(force) {
      const list = pop.chat(), thinking = Boolean(state.snap.thinking);
      const sig = JSON.stringify([list, thinking]);
      if (!force && sig === state.chatSig) return;
      state.chatSig = sig;
      const near = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 60, was = chat.scrollTop;
      chat.replaceChildren(...list.map(bubble), ...(thinking ? [h("div", {class: "cp-row"}, h("div", {class: "cp-bub cp-think", role: "img", "aria-label": t("super.think")}, h("i"), h("i"), h("i")))] : []));
      chat.scrollTop = near || force ? chat.scrollHeight : was;
    }
    chat.addEventListener("click", (event) => {
      const link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
      const task = link ? /^\/task\/([^/?#]+)/.exec(link.getAttribute("href") || "") : null;
      if (!task) return;
      event.preventDefault();
      toPage(decodeURIComponent(task[1]));
    });

    // ---------- the input ----------
    const OFF = {asleep: "super.off.asleep", limit: "super.off.limit", busy: "super.off.busy", off: "super.off.off", none: "super.off.none"};
    function drawInput() {
      const off = state.snap.off;
      field.disabled = Boolean(off);
      go.disabled = Boolean(off) || state.sending;
      field.placeholder = off ? t(OFF[off] || OFF.none) : t("super.pop.ph");
      note.hidden = !state.note;
      note.textContent = state.note;
    }
    function grow() { field.style.height = "auto"; field.style.height = Math.min(field.scrollHeight, 96) + "px"; }
    async function send() {
      const text = field.value.trim();
      if (!text || go.disabled || state.snap.thinking && !text.startsWith("@")) return;
      state.sending = true; state.note = ""; field.value = ""; grow();
      drawInput();
      let result;
      try { result = await pop.send(text); } catch (error) { result = {ok: false, text: String((error && error.message) || error)}; }
      state.sending = false;
      if (!alive) return;
      if (!result.ok && !field.value) { field.value = text; grow(); }  // refused: the words come back
      state.note = result.text || "";
      drawInput();
      drawChat(true);
    }
    go.addEventListener("click", send);
    field.addEventListener("input", () => { grow(); if (state.note) { state.note = ""; drawInput(); } });
    field.addEventListener("keydown", (event) => { if (isEnter(event) && !event.shiftKey) { event.preventDefault(); send(); } });

    // ---------- the buttons of the line ----------
    listBtn.addEventListener("click", () => { state.cardOn = !state.cardOn; drawTop(state.snap); drawCard(true); });
    outBtn.addEventListener("click", () => toPage(""));

    // ---------- what changed in the view ----------
    function onChange() {
      if (!alive) return;
      state.snap = pop.snapshot();
      draw();
    }
    function draw() {
      drawTop(state.snap);
      drawCard(false);
      drawChat(false);
      drawInput();
    }
    draw();
    drawChat(true);
    const unsubscribe = pop.subscribe(onChange);
    pop.watch(true);

    // A window of the page (an approval with its code, the new-task chat) waits there: say so with one button, and bring the page forward.
    const watchDialog = new MutationObserver(() => {
      const open = document.body.classList.contains("has-dialog");
      if (open === state.dialog) return;
      state.dialog = open;
      dialogLine.hidden = !open;
      if (open) {
        const show = h("button", {type: "button", class: "cp-b main"}, t("super.pop.dialog.go"));
        show.addEventListener("click", () => toPage(""));
        dialogLine.replaceChildren(h("span", null, t("super.pop.dialog")), show);
        toPage("");
      } else dialogLine.replaceChildren();
      draw();
    });
    watchDialog.observe(document.body, {attributes: true, attributeFilter: ["class"]});

    // ---------- keys (no hint on screen) ----------
    doc.addEventListener("keydown", (event) => {
      if (event.ctrlKey || event.metaKey || event.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) return;
      const key = event.key.toLowerCase();
      if (!state.cardOn || !items().length) return;
      if (key === "arrowright") move(1);
      else if (key === "arrowleft") move(-1);
      else if (key === "a") {
        const code = cardBox.querySelector(".cp-acts input");
        if (code) code.focus(); else { const first = [...cardBox.querySelectorAll(".cp-acts .cp-act")].find((node) => !node.disabled && node.dataset.action !== "dismiss-action"); if (first) first.click(); }
      } else if (key === "r") { const refuse = cardBox.querySelector('.cp-acts [data-action="dismiss-action"]'); if (refuse && !refuse.disabled) refuse.click(); }
    });

    // ---------- the end ----------
    function close() {
      if (!alive) return;
      alive = false;
      unsubscribe();
      look.disconnect();
      watchDialog.disconnect();
      pop.watch(false);
      removeEventListener("pagehide", close);
      if (win === pip) win = null;
    }
    pip.addEventListener("pagehide", close);
    addEventListener("pagehide", close);  // the page goes: the window goes with it
  }

  return {open, run, unsupported, isOpen: () => Boolean(win && !win.closed)};  // `run` is the window's drawing code: the lab draws it in a frame of a normal page for screenshots
})();
