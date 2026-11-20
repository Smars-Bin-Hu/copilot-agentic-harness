// The pop-out of the super agent view (1.8.1, "the companion"): a small window that stays on top of every other window, so the person can work in VS Code and still handle what waits.
// It is a Document Picture-in-Picture window (Chrome, Edge): `documentPictureInPicture.requestWindow`, opened from a click. Its document is empty, so the styles of this page are copied in
// (they are inlined in the page, with companion.css) and `data-theme` / `lite` follow the page. The window shares this page's JavaScript: the buttons in it are the very buttons of the
// super view (`pop.buttonsFor`, from super.js), so every action goes through SERVE.act / CHAT as it does in the view. The window never asks the server: it reads what the super view holds
// (`pop.snapshot`) and is told when that changes (`pop.subscribe`); super.js keeps polling while the window is open, even when the view itself is not shown.
// The windows of an approval (the code field) open in this page, not in the small window: the window tells the person (a line with "Show it") and takes the page's focus.
// It has three sizes: a pill (how many wait, how many work), a card (one item, with the same buttons) and a list. The pet sits on the top edge. Everything stops when the window closes.
// Needs common.js, serve.js, lobby.js (Lobby.robot), pet.js (PET.dress) and super.js, which calls `COMPANION.open`.
"use strict";

const COMPANION = (function () {
  const OFF = {asleep: "super.off.asleep", limit: "super.off.limit", busy: "super.off.busy", off: "super.off.off", none: "super.off.none"};
  const SIZE = {pill: [300, 150], card: [360, 470], list: [380, 420]};
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
    try { made = await window.documentPictureInPicture.requestWindow({width: SIZE.card[0], height: SIZE.card[1] - 70}); } catch (error) { SERVE.failed(new Error(t("super.pop.failed"))); return; }
    win = made;
    run(made, pop);
  }

  function run(pip, pop) {
    const doc = pip.document;
    const main = document.documentElement;
    const timers = new Set();
    const later = (fn, ms) => { const id = setTimeout(() => { timers.delete(id); if (alive) fn(); }, ms); timers.add(id); return id; };
    let alive = true;
    const state = {view: "card", cur: "", snap: pop.snapshot(), known: new Set(), seenMsg: new Set(), sig: "", quiet: 0, pose: "", replies: new Map(), previews: new Map(), qaOpen: new Set(), menu: null, doneN: 0, askRow: false, dialog: false, bubTimer: 0, lastAsk: ""};
    const cap = (text) => String(text || "").replace(/\s*(\.{3}|…)$/, "");

    // ---------- the document of the window ----------
    for (const node of document.querySelectorAll("style, link[rel=stylesheet]")) doc.head.append(doc.importNode(node, true));
    doc.title = t("super.name");
    const copyLook = () => { for (const name of ["data-theme", "class", "lang"]) { const value = main.getAttribute(name); if (value === null) doc.documentElement.removeAttribute(name); else doc.documentElement.setAttribute(name, value); } };
    copyLook();
    const look = new MutationObserver(copyLook);
    look.observe(main, {attributes: true, attributeFilter: ["data-theme", "class", "lang"]});
    doc.body.className = "cp-doc";

    // ---------- the parts ----------
    const perch = h("div", {class: "cp-perch", "aria-hidden": "true"}), think = h("span", {class: "cp-think"}, h("span", {class: "cp-dots"}, h("i"), h("i"), h("i")));
    const bat = h("span", {class: "cp-bat"}, "▯");
    const listBtn = h("button", {type: "button", class: "cp-cb", title: t("super.pop.list"), "aria-label": t("super.pop.list")}, "☰");
    const minBtn = h("button", {type: "button", class: "cp-cb", title: t("super.pop.small"), "aria-label": t("super.pop.small")}, "–");
    const chrome = h("div", {class: "cp-chrome"}, h("span", {class: "cp-pin", title: t("super.pop.pin")}, "⇱"), h("b", null, t("super.name")), h("span", {class: "cp-sp"}), listBtn, minBtn);
    const dialogLine = h("div", {class: "cp-dialog", hidden: "", role: "status"});
    const body = h("div", {class: "cp-main"});
    const ask = h("button", {type: "button", class: "cp-b ghost", title: t("super.pop.ask.tip")}, t("super.pop.ask"));
    const make = SERVE.runs("create") && typeof CHAT !== "undefined" ? h("button", {type: "button", class: "cp-b ghost", title: t("super.new.tip")}, t("super.new.go")) : null;
    const board = h("button", {type: "button", class: "cp-b ghost", title: t("super.pop.board.tip")}, t("super.pop.board"));
    const field = h("input", {class: "cp-field", maxlength: 2000, placeholder: t("super.input.ph"), "aria-label": t("super.input.ph")});
    const go = h("button", {type: "button", class: "cp-b main"}, t("super.pop.ask.go"));
    const askRow = h("div", {class: "cp-askrow", hidden: ""}, field, go);
    const askWhy = h("div", {class: "cp-askwhy", role: "status", hidden: ""});  // why a question was refused: stays until the person types again
    const foot = h("div", {class: "cp-foot"}, h("div", {class: "cp-btns"}, ask, make, h("span", {class: "cp-sp"}), board), askRow, askWhy);
    const bub = h("div", {class: "cp-bub", role: "status"});
    const win0 = h("div", {class: "cp-win"}, chrome, dialogLine, body, foot);
    const root = h("div", {class: "cp"}, perch, think, bat, win0, bub);
    doc.body.append(root);

    // ---------- the pet: the flat robot of the pet, on the top edge ----------
    function setPose(name) {
      if (state.pose === name) return;
      state.pose = name;
      const robot = Lobby.robot(name, "", 0);
      PET.dress(robot);
      perch.replaceChildren(robot);
    }
    const moodOf = () => state.snap.mood;
    function drawPet() {
      const mood = moodOf(), asleep = mood === "sleep" || (mood === "calm" && state.quiet >= 60);
      root.classList.toggle("m-sleep", asleep);
      root.classList.toggle("m-tired", mood === "tired");
      root.classList.toggle("thinking", state.snap.thinking && mood === "calm");
      if (state.pose !== "you") setPose(asleep ? "idle" : "sit");
    }
    function wake() { state.quiet = 0; if (state.pose === "idle" && moodOf() === "calm") { state.pose = ""; drawPet(); } }
    function hop() { perch.classList.remove("hop"); void perch.offsetWidth; perch.classList.add("hop"); }
    function toast(text) {
      const node = h("div", {class: "cp-toast"}, text);
      root.append(node);
      later(() => node.remove(), 1500);
    }
    // A new item: it stands and waves, the window shakes once, the new card is on top.
    function noticed(item) {
      state.quiet = 0;
      state.pose = "";
      setPose("you");
      root.classList.remove("shake"); void root.offsetWidth; root.classList.add("shake");
      state.cur = item.id;
      if (state.view === "pill") setView("card");
      state.fresh = item.id;
      later(() => { root.classList.remove("shake"); state.pose = ""; drawPet(); }, 1500);
    }

    // ---------- the answer pops up above the card, and goes ----------
    function say(question, answer) {
      clearTimeout(state.bubTimer);
      const close = h("button", {type: "button", class: "cp-x", title: t("super.pop.close"), "aria-label": t("super.pop.close")}, "×");
      close.addEventListener("click", () => bub.classList.remove("on"));
      bub.replaceChildren(...[close, question ? h("span", {class: "cp-you"}, t("super.pop.you", {text: question})) : null, h("span", {class: "cp-ans"}, answer), h("span", {class: "cp-judg", title: t("super.judgment.tip")}, "◇")].filter(Boolean));
      bub.classList.add("on");
      state.bubTimer = later(() => bub.classList.remove("on"), 14000);
    }

    // ---------- what is drawn ----------
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
      const at = current();
      state.cur = list[(at + step + list.length) % list.length].id;
      state.curTask = "";
      draw(true);
    }
    function setView(view) {
      state.view = view;
      draw(true);
      try { pip.resizeTo(...SIZE[view]); } catch (error) { /* the browser may refuse a size: the layout follows the real one */ }
    }
    const dot = (cls) => h("span", {class: "cp-dot " + cls});
    function stat(snap) {
      const w = snap.items.length, mood = snap.mood;
      return h("div", {class: "cp-stat"}, h("span", null, dot("run"), t("super.pop.run", {n: snap.working})), h("span", null, dot("wait"), t("super.pop.wait", {n: w})), ...pop.alertMarks(),
        mood === "sleep" ? h("span", null, "· " + cap(t("super.line.asleep"))) : mood === "tired" ? h("span", null, "· " + cap(t("super.line.tired"))) : null,
        snap.cost ? h("span", {class: "cp-cost"}, PET.battery(snap.cost)) : null);
    }
    // 1.8.5: what is starting, not seen to start, or being made: no card yet, so a short line of marks (a spinner or a yellow mark, the name; the details in the hover).
    function waits(snap) {
      const marks = [];
      for (const mate of snap.mates || []) {
        if (mate.state !== "start" && !(mate.starting && mate.starting.late)) continue;
        const late = Boolean(mate.starting && mate.starting.late);
        marks.push(h("span", {class: "cp-wt" + (late ? " late" : ""), title: shownName(mate) + "\n" + (nameTip(mate) ? nameTip(mate) + "\n" : "") + startingTip(mate.starting)}, late ? h("span", {class: "cp-late", "aria-hidden": "true"}) : spinner("cp-spin"), shownName(mate)));
      }
      for (const one of snap.making || []) marks.push(h("span", {class: "cp-wt cp-mk", title: makingTip(one)}, h("b", {class: "cp-mk-name"}, one.name), makingMarks(one, false)));
      return marks.length ? h("div", {class: "cp-waits"}, ...marks) : null;
    }
    function buttons(item) {
      const nodes = pop.buttonsFor(item);
      nodes.forEach((node, at) => {
        if (item.actions[at] && node.matches("button, a")) node.dataset.action = item.actions[at].action;
        for (const one of node.matches("button, a") ? [node] : node.querySelectorAll("button")) one.classList.add("cp-act");  // a held call, Accept and a stuck chat bring more than one control in a box: the keys find the buttons in it
      });
      return nodes;
    }
    function avatar(item) {
      const mate = (state.snap.mates || []).find((one) => one.task === item.task);
      return h("span", {class: "cp-av"}, PET.face("you", mate ? mate.kind : "", 0));
    }
    // The reply box and the preview are the super view's own (pop.replyFor, pop.previewFor); one made per item, so a redraw keeps the typed words and the open fold.
    function cached(store, item, make) {
      if (!store.has(item.id)) store.set(item.id, make(item));
      return store.get(item.id);
    }
    // The last ask of this card's task and its answer: a few lines, the rest on a click.
    function asked(item) {
      const list = pop.asksOf(item.task), last = list[list.length - 1];
      if (!last) return null;
      const open = state.qaOpen.has(last.id), answer = last.answer ? String(last.answer) : "";
      const ans = answer ? h("div", {class: "cp-qans" + (open ? " open" : ""), title: open ? "" : t("super.more")}, answer) : null;
      if (ans) ans.addEventListener("click", () => { ans.classList.toggle("open"); if (ans.classList.contains("open")) state.qaOpen.add(last.id); else state.qaOpen.delete(last.id); });
      return h("div", {class: "cp-qa"}, h("div", {class: "cp-qq"}, t("super.pop.you", {text: last.text})), last.line ? h("div", {class: "cp-qline" + (last.state === "failed" ? " bad" : "")}, last.line) : null, ans);
    }
    function card(item, at, w) {
      const main = pop.mainOf(item), asks = pop.asksPerson(item);
      const what = h("div", {class: "cp-text" + (asks || pop.prose(item) ? " ask" : "") + (pop.prose(item) ? " prose" : ""), title: pop.fullOf(item)}, main);
      if (asks || pop.prose(item)) { what.tabIndex = 0; what.addEventListener("click", () => what.classList.toggle("open")); }
      if (pop.hasCalls(item)) what.hidden = true;  // the held calls below show the command with its code (1.8.4)
      const note = pop.jointNote(item);
      const more = !asks && !pop.prose(item) && item.detail && item.detail !== item.title ? h("details", {class: "cp-more"}, h("summary", null, t("super.details")), h("pre", null, item.detail)) : null;
      const prev = h("button", {type: "button", class: "cp-cb", title: t("super.pop.prev"), "aria-label": t("super.pop.prev")}, "‹"), next = h("button", {type: "button", class: "cp-cb", title: t("super.pop.next"), "aria-label": t("super.pop.next")}, "›");
      prev.addEventListener("click", () => move(-1)); next.addEventListener("click", () => move(1));
      const acts = h("div", {class: "cp-acts"}, buttons(item));
      acts.addEventListener("click", () => { wake(); setTimeout(() => { try { window.focus(); } catch (error) { /* the page may keep its place */ } }, 0); });  // an approval opens its window in the page
      const reply = cached(state.replies, item, pop.replyFor), preview = cached(state.previews, item, pop.previewFor), qa = asked(item);
      const node = h("div", {class: "cp-card" + (state.fresh === item.id ? " fresh" : "")},
        h("div", {class: "cp-head"}, avatar(item), pop.taskLink(item.task, undefined, "cp-task", item), h("span", {class: "cp-why"}, "· " + pop.why(item)), h("span", {class: "cp-nav"}, prev, (at + 1) + "/" + w, next)),
        what, ...pop.extraFor(item), note ? h("div", {class: "cp-note"}, h("span", {class: "cp-judg", title: t("super.judgment.tip")}, "◇"), " " + note) : null, more, qa, reply, preview, acts, h("div", {class: "cp-keys"}, t("super.pop.keys")));
      state.fresh = "";
      return node;
    }
    function row(item, at) {
      const mate = (state.snap.mates || []).find((one) => one.task === item.task);
      const node = h("button", {type: "button", class: "cp-row"}, h("span", {class: "cp-av"}, PET.face("you", mate ? mate.kind : "", 0)),
        h("span", {class: "cp-et"}, h("b", {title: item.task + (nameTip(item) ? "\n" + nameTip(item) : "")}, shownName(item)), h("span", null, pop.why(item) + " · " + cap(item.title))), h("span", {class: "cp-go"}, "›"));
      node.title = t("super.pop.row.tip");
      node.addEventListener("click", () => { state.cur = item.id; state.curTask = item.task; state.view = "card"; setView("card"); });
      node.addEventListener("contextmenu", (event) => { event.preventDefault(); menuOpen(item.task, node); });  // a right click, or the menu key on the focused row
      return node;
    }
    function draw(force) {
      const snap = state.snap, w = snap.items.length, at = current(), item = snap.items[at];
      const sig = JSON.stringify([state.view, w, snap.items.map((one) => one.id + "|" + pop.mainOf(one)), item ? pop.sigFor(item) : "", item ? item.id : "", item && state.view === "card" ? pop.asksOf(item.task).slice(-1).map((one) => [one.id, one.state, one.answer, one.line]) : "", snap.done.length, snap.working, JSON.stringify([(snap.mates || []).map((mate) => [mate.task, mate.state, mate.label, mate.starting && mate.starting.late]), snap.making]), snap.stuck, snap.error, snap.mood, snap.cost, snap.failed, snap.off, snap.loaded, state.dialog]);
      drawPet();
      listBtn.classList.toggle("on", state.view === "list");
      root.className = root.className.replace(/\bv-\w+\b/g, "").trim() + " v-" + state.view;
      foot.hidden = state.view === "pill";
      if (!force && sig === state.sig) return;
      state.sig = sig;
      let content;
      if (state.view === "pill") {
        const pill = h("button", {type: "button", class: "cp-pill", title: t("super.pop.open.tip")}, w ? h("b", null, w) : null, w ? " " + t("super.pop.pill.wait") : t("super.pop.pill.none"), h("span", {class: "cp-meta"}, " · " + t("super.pop.run", {n: snap.working})));
        pill.addEventListener("click", () => setView(w ? "card" : "list"));
        content = [pill];
      } else if (state.view === "list") {
        content = [stat(snap), waits(snap), h("div", {class: "cp-list"}, ...(w ? snap.items.map(row) : [h("div", {class: "cp-meta cp-none"}, t("super.empty.title"))]),
          snap.done.length ? h("div", {class: "cp-today"}, h("span", {class: "cp-meta"}, t("super.pop.today")), ...snap.done.slice().reverse().map((one) => h("span", {class: "cp-ok"}, one.task + " · " + one.text))) : null)];
      } else if (!w) {
        content = [stat(snap), waits(snap), h("div", {class: "cp-clear"}, t("super.pop.clear"), h("br"), h("span", {class: "cp-meta"}, t("super.pop.clear.sub"))),
          snap.done.length ? h("div", {class: "cp-today"}, h("span", {class: "cp-meta"}, t("super.pop.today")), ...snap.done.slice(-3).reverse().map((one) => h("span", {class: "cp-ok"}, one.task + " · " + one.text))) : null];
      } else content = [stat(snap), waits(snap), card(item, at, w)];
      const typing = doc.activeElement;
      body.replaceChildren(...content.filter(Boolean));
      if (typing && typing !== doc.body && typing.isConnected && body.contains(typing)) typing.focus();  // a redraw does not take the focus from a reply box
      drawFoot();
    }
    // ---------- list view: right click on a row, Steer and Stop (pop.steer, pop.stop), while the task works ----------
    function menuClose() {
      if (!state.menu) return;
      state.menu.remove();
      state.menu = null;
    }
    function menuOpen(task, anchor) {
      menuClose();
      const works = pop.mateWorks(task);
      const said = h("div", {class: "bad cp-menubad"});
      const line = h("input", {type: "text", class: "cp-menuline", maxlength: 2000, placeholder: t("super.mate.steer.ph", {task}), "aria-label": t("super.mate.steer.ph", {task})});
      const lineRow = h("div", {class: "cp-menurow", hidden: ""}, line);
      const item = (key, onClick) => {
        const node = h("button", {type: "button", role: "menuitem", class: "cp-menuitem"}, t(key));
        node.disabled = !works;
        node.title = works ? "" : t("super.pop.menu.none");
        node.addEventListener("click", onClick);
        return node;
      };
      let busy = false;
      const run = (call, toasted) => {
        if (busy) return;
        busy = true;
        said.replaceChildren();
        call().then(() => { menuClose(); toast(toasted); }, (error) => { busy = false; said.replaceChildren(...SERVE.reasons((error && error.message) || String(error))); });
      };
      const steer = item("super.mate.steer", () => { lineRow.hidden = false; line.focus(); });
      const stop = item("super.mate.stop", () => run(() => pop.stop(task), t("super.mate.stopped", {task})));
      line.addEventListener("keydown", (event) => {
        if (!isEnter(event) || event.shiftKey || !line.value.trim()) return;
        event.preventDefault();
        run(() => pop.steer(task, line.value.trim()), t("super.mate.steered", {task}));
      });
      const menu = h("div", {class: "cp-menu", role: "menu", "aria-label": t("super.mate.menu", {task})}, h("div", {class: "cp-menuhead", title: task}, task), steer, lineRow, stop, said);
      state.menu = menu;
      root.append(menu);
      const box = root.getBoundingClientRect(), at = anchor.getBoundingClientRect();
      menu.style.left = Math.max(6, Math.min(at.left - box.left + 8, box.width - menu.offsetWidth - 6)) + "px";
      menu.style.top = Math.max(6, Math.min(at.bottom - box.top - 2, box.height - menu.offsetHeight - 6)) + "px";
      (works ? steer : menu).focus();
    }
    // The task of the card on show: a typed question goes to it; "" without a card (the super chat answers).
    function cardTask() {
      const list = items();
      return state.view === "card" && list.length ? list[Math.min(Math.max(current(), 0), list.length - 1)].task : "";
    }
    // "@name words": the name is one of the open or recently closed tasks and ends at a space, the end or , : ; (longest name first, as the super view reads it).
    function nameIn(text) {
      if (!text.startsWith("@")) return null;
      for (const name of [...(state.snap.mates || []).map((mate) => mate.task), ...(state.snap.closed || []).map((one) => one.task)].sort((a, b) => b.length - a.length)) {  // a closed task too: the message reopens it
        if (text.startsWith("@" + name) && /^($|[\s,:;])/.test(text.slice(name.length + 1))) return {task: name, text: text.slice(name.length + 1).replace(/^[\s,:;]+/, "").trim()};
      }
      return null;
    }
    function drawFoot() {
      const snap = state.snap, off = snap.off;
      ask.disabled = Boolean(off);
      ask.title = off ? t(OFF[off] || OFF.none) : t("super.pop.ask.tip");
      go.disabled = Boolean(off); field.disabled = Boolean(off);
      const target = cardTask();
      field.placeholder = off ? t(OFF[off] || OFF.none) : target ? t("super.route.ph", {task: target}) : t("super.input.ph");
      askRow.hidden = !state.askRow || Boolean(off);
      if (askRow.hidden) askWhy.hidden = true;
      if (make) make.disabled = false;
    }

    // ---------- what changed in the view ----------
    function onChange() {
      if (!alive) return;
      const before = state.snap, snap = pop.snapshot();
      state.snap = snap;
      const fresh = snap.loaded ? snap.items.filter((item) => !state.known.has(item.id)) : [];
      const first = !state.loadedOnce && snap.loaded;
      if (snap.loaded) { state.loadedOnce = true; for (const item of snap.items) state.known.add(item.id); }
      for (const message of snap.messages) {
        if (state.seenMsg.has(message.id)) continue;
        state.seenMsg.add(message.id);
        if (!first && state.opened) { say(state.lastAsk, message.text); state.lastAsk = ""; }
      }
      if (snap.done.length > state.doneN) {
        const last = snap.done[snap.done.length - 1];
        if (state.doneN || state.opened) { toast(last.text); hop(); }
        state.doneN = snap.done.length;
      }
      if (!first && fresh.length && snap.mood === "calm") noticed(fresh[0]);
      if (first && !snap.items.length && state.view === "card") state.view = "pill";
      draw(false);
      drawFoot();
      if (before.items.length !== snap.items.length && !snap.items.length && state.view === "card") later(() => { if (!state.snap.items.length && state.view === "card") setView("pill"); }, 2600);
    }
    state.opened = false;
    for (const message of state.snap.messages) state.seenMsg.add(message.id);
    for (const item of state.snap.items) state.known.add(item.id);
    state.loadedOnce = state.snap.loaded;
    state.doneN = state.snap.done.length;
    if (!state.snap.items.length) state.view = "pill";
    setPose("sit");
    draw(true); drawFoot();
    state.opened = true;
    const unsubscribe = pop.subscribe(onChange);
    pop.watch(true);

    // ---------- the footer ----------
    ask.addEventListener("click", () => { wake(); state.askRow = !state.askRow; drawFoot(); if (state.askRow) field.focus(); });
    function send() {
      const text = field.value.trim();
      if (!text || go.disabled) return;
      const named = nameIn(text), task = named ? named.task : cardTask();
      if (task) {  // one task is asked: its answer shows in its card
        field.value = "";
        go.disabled = true;
        askWhy.hidden = true;
        pop.askTask(task, named ? named.text : text).then((result) => {
          go.disabled = false;
          if (!alive) return;
          if (!result.ok) { if (!field.value) field.value = text; askWhy.textContent = result.text; askWhy.hidden = false; }
          draw(true);
        });
        return;
      }
      if (state.snap.thinking) return;
      state.lastAsk = text; field.value = ""; state.askRow = false;
      pop.ask(text);
      drawFoot();
    }
    go.addEventListener("click", send);
    field.addEventListener("input", () => { askWhy.hidden = true; });
    field.addEventListener("keydown", (event) => { if (isEnter(event)) { event.preventDefault(); send(); } });
    const toPage = () => { try { window.focus(); } catch (error) { /* a browser may keep the focus where it is */ } };
    if (make) make.addEventListener("click", () => { CHAT.create(); toPage(); });  // the new-task window is the board's: it opens in the page
    board.addEventListener("click", toPage);
    listBtn.addEventListener("click", () => setView(state.view === "list" ? "card" : "list"));
    minBtn.addEventListener("click", () => setView(state.view === "pill" ? "card" : "pill"));

    // A window of the page (an approval with its code, the new-task chat) waits there: say so, and bring the page forward.
    const watchDialog = new MutationObserver(() => {
      const open = document.body.classList.contains("has-dialog");
      if (open === state.dialog) return;
      state.dialog = open;
      dialogLine.hidden = !open;
      if (open) {
        const show = h("button", {type: "button", class: "cp-b main"}, t("super.pop.dialog.go"));
        show.addEventListener("click", toPage);
        dialogLine.replaceChildren(h("span", null, t("super.pop.dialog")), show);
        toPage();
      } else dialogLine.replaceChildren();
      draw(false);
    });
    watchDialog.observe(document.body, {attributes: true, attributeFilter: ["class"]});

    // ---------- keys ----------
    doc.addEventListener("keydown", (event) => {
      wake();
      if (event.key === "Escape" && state.menu) { menuClose(); return; }
      if (event.ctrlKey || event.metaKey || event.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) { if (event.key === "Escape" && event.target === field) { state.askRow = false; drawFoot(); } return; }
      const key = event.key.toLowerCase();
      if (key === "arrowright") { if (items().length) { if (state.view !== "card") setView("card"); move(1); } }
      else if (key === "arrowleft") { if (items().length) { if (state.view !== "card") setView("card"); move(-1); } }
      else if (key === "escape") setView("pill");
      else if (key === "a") {
        const code = body.querySelector(".cp-acts input");
        if (code) code.focus(); else { const first = [...body.querySelectorAll(".cp-acts .cp-act")].find((node) => !node.disabled && node.dataset.action !== "dismiss-action"); if (first) first.click(); }
      } else if (key === "r") { const refuse = body.querySelector('.cp-acts [data-action="dismiss-action"]'); if (refuse && !refuse.disabled) refuse.click(); }
    });
    for (const name of ["pointermove", "pointerdown"]) doc.addEventListener(name, wake);
    doc.addEventListener("pointerdown", (event) => { if (state.menu && !state.menu.contains(event.target)) menuClose(); }, true);

    // ---------- the quiet minute, and the end ----------
    const tick = setInterval(() => { if (!alive) return; if (moodOf() === "calm" && state.quiet < 60 && ++state.quiet === 60) drawPet(); }, 1000);
    function close() {
      if (!alive) return;
      alive = false;
      clearInterval(tick);
      for (const id of timers) clearTimeout(id);
      timers.clear();
      unsubscribe();
      look.disconnect();
      menuClose();
      watchDialog.disconnect();
      pop.watch(false);
      removeEventListener("pagehide", close);
      if (win === pip) win = null;
    }
    pip.addEventListener("pagehide", close);
    addEventListener("pagehide", close);  // the page goes: the window goes with it
  }

  return {open, unsupported, isOpen: () => Boolean(win && !win.closed)};
})();
