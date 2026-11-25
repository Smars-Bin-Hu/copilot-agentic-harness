// The super agent view of the board (1.8.1): one window like a messenger. Everything that waits for the person comes as a short message with its buttons (from `/api/super`, built by
// superview.py out of the rows of the board); a strip of round avatars shows the state of every open task (green dashed ring: at work, amber with a count: waits for you, grey: idle) and
// a click shows only that task's messages; a robot (pet.js) rests in the top right corner and flies out to an avatar to fetch a letter when a new message arrives. A message that is answered folds
// into one "✓" line. Under the stream: two quick asks and an input to ask the agent or start a new task.
//
// Layout (1.8.4): two parts. The queue of items is pinned above the chat (its own scroll, at most half the height, the most urgent item on top); the chat (the agent's talk, your words, the asks) is below it
// and a long chat never pushes the queue away. An item that is settled leaves the queue: its receipt goes to a collapsed "Done (n)" row at the foot of the queue. The header line shows
// `N wait · oldest X · K stuck · M errors` (a part that is zero or missing is left out; the words are in the hover).
//
// The cards (1.8.4): a held call shows its command and its code, View opens the whole command (and counts as seen, as on the task page) before Approve works, and the typed code stays; an error has "Try again";
// a stuck chat has Steer and Stop; a question shows its text and options and says it is answered in VS Code; a delivery shows its summary, and "Accept and close" counts 10 s down in the page (the accept is sent only when it ends;
// Undo, or closing the page, sends nothing). Requirements and deliveries have a folded preview. A receipt says what was done (Allowed, Denied, Answered: ..., Approved).
//
// The buttons of a message are the buttons of the board (`actionButton`, common.js): the same code, the same endpoints, the same code field for an approval; this file makes no action of its own.
// The agent's brain is another part (`/api/super/ask`, `/api/super/talk`): when they do not answer, the view still works and the input says the agent is not there.
// Not the default: board.js shows it when the person picks "Super agent" in the bar (the choice is not kept; the board opens as before).
// Needs common.js, serve.js, chat.js, lobby.js (Lobby.robot) and pet.js; board.js calls `SUPER.create`.
"use strict";

const SUPER = (function () {
  // The names of the messages are written out, so a search for a key finds its place.
  const WHY = {confirm: "super.why.confirm", question: "super.why.question", asking: "super.why.asking", outbox: "super.why.outbox", autorun: "super.why.autorun", req: "super.why.req", plan: "super.why.plan",
    promote: "super.why.promote", review: "super.why.review", recover: "super.why.recover", accept: "super.why.accept", commit: "super.why.commit", stopped: "super.why.stopped", cancelled: "super.why.cancelled", error: "super.why.error"};
  // What the person did, as a receipt says it (the action of the button that was pressed); an action not here is said with the name of its button.
  const RECEIPT = {"approve-action": "super.done.approved", "approve-plan": "super.done.approved", "approve-promote": "super.done.approved", "confirm-req": "super.done.confirmed", accept: "super.done.accepted", send: "super.done.sent",
    recover: "super.done.recovered", "review extend": "super.done.extended", "review waive": "super.done.waived", "review dismiss": "super.done.dismissed", "autorun on": "super.done.autorun", steer: "super.done.steered", stop: "super.done.stopped"};
  const receiptFor = (action) => (RECEIPT[action] ? t(RECEIPT[action]) : plain(t("board.action." + String(action).replace(" ", "-"))));
  const idleMin = (item) => Math.max(1, Math.floor((Number(item.idle_s) || 0) / 60));
  const whyText = (item) => (item.why === "stuck" ? t("super.why.stuck", {n: idleMin(item)}) : t(WHY[item.why] || "super.why.other"));  // "Stuck · N min" says how long
  const MATE = {you: "super.mate.you", work: "super.mate.work", idle: "super.mate.idle", stuck: "super.mate.stuck", error: "super.mate.error", start: "super.waits.start"};
  const BLOCKS = new Set(["confirm", "question", "auth", "asking", "outbox", "autorun"]);  // superview.py: these stop running work; their dot on the pet is red
  const OFF = {asleep: "super.off.asleep", limit: "super.off.limit", busy: "super.off.busy", off: "super.off.off", none: "super.off.none"};
  const query = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  const still = () => Boolean(query && query.matches) || document.documentElement.classList.contains("lite");
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const two = (value) => String(value).padStart(2, "0");
  const stamp = () => { const now = new Date(); return two(now.getHours()) + ":" + two(now.getMinutes()); };
  const taskUrl = (task) => "/task/" + encodeURIComponent(task);
  const plain = (text) => String(text || "").replace(/\s*(\.{3}|…)$/, "");

  // The tasks that wait for the person, as the bar's badge counts them (the rows of the board; the same rule as superview.py).
  function waiting(rows) {
    return (rows || []).filter((row) => row.status === "open" && row.waiting_why && !String(row.waiting_why).startsWith("go-") && !row.paused_since).length;
  }

  // A link to the task page, in a new tab: the person's place in the messages stays.
  // `row` (1.8.5) is the item or mate: its display name is the text, the task name is in the hover.
const taskLink = (task, text, cls, row) => h("a", {class: cls || "sa-task", href: taskUrl(task), target: "_blank", rel: "noopener", title: (cls ? t("super.open.tip") : task) + (row && nameTip(row) ? "\n" + nameTip(row) : "")}, text === undefined ? (row ? shownName(row) : task) : text);

  function create(options) {
    const rowsOf = options.rows;
    const sv = h("section", {class: "sa", hidden: "", "aria-label": t("super.name")});
    const lineEl = h("div", {class: "sa-line"});
    const costEl = h("span", {class: "sa-cost", hidden: ""});
    const team = h("div", {class: "sa-team", role: "group", "aria-label": t("super.team")});
    const filterEl = h("div", {class: "sa-filter", hidden: ""});
    const banner = h("div", {class: "sa-banner", hidden: "", role: "status"});
    const empty = h("div", {class: "sa-empty"});
    const earlier = h("button", {type: "button", class: "sa-earlier", hidden: ""});  // a long day: the older exchanges are folded behind it (FOLD)
    const stream = h("div", {class: "sa-stream", role: "log", "aria-live": "polite"}, earlier, empty);
    const pill = h("button", {type: "button", class: "sa-newpill", hidden: ""}, "↓ " + t("super.new"));
    const quick = h("div", {class: "sa-quick"});
    const field = h("textarea", {class: "sa-field", rows: 1, maxlength: 2000, placeholder: t("super.input.ph"), "aria-label": t("super.input.ph")});
    const newTask = SERVE.runs("create") ? h("button", {type: "button", class: "sa-new", title: t("super.new.tip")}, t("super.new.go")) : null;
    const send = h("button", {type: "button", class: "sa-send", title: t("super.send"), "aria-label": t("super.send")}, "↑");
    // The direct message (superdirect.js): under an avatar (or after "@name") the words go to that task. The counter, the options menu (an icon next to Send) and the files it holds show only then.
    const counter = h("span", {class: "sa-dcount", hidden: "", title: t("super.direct.count.tip")});
    const direct = SUPERDIRECT.menu(field, sv, (task) => isClosed(task));  // the task is closed: its checks are "Checks after the close"
    direct.button.hidden = true;
    direct.onchange = () => { drawHolder(); drawDirect(); };  // the checks were changed in the menu: the placeholder and the mark above the input follow (a closed task: checks after the close)
    const box = h("div", {class: "sa-box"}, field, newTask, counter, direct.button, send);
    const to = h("div", {class: "sa-to", hidden: "", title: t("super.direct.to.tip")});  // "To: <task>": where the words go while a task is targeted
    const complete = h("div", {class: "sa-comp", role: "listbox", hidden: "", "aria-label": t("super.route.pick")});
    // The pop-out (companion.js): a small window that stays on top of every other window. Only where the browser can open one (Document Picture-in-Picture: Chrome, Edge).
    const popUp = typeof COMPANION !== "undefined" ? h("button", {type: "button", class: "sa-pop"}, "⇱") : null;
    // The fold (1.8.4): one small control that folds the chat to one line so the queue takes the whole room. Remembered in localStorage; typing or a new agent message unfolds it (not remembered).
    const FOLD_KEY = "super.chatfold";
    const foldBtn = h("button", {type: "button", class: "sa-fold"});
    const foldLine = h("span", {class: "sa-foldline"}, t("super.chat.folded"));
    let chatFolded = false;
    try { chatFolded = localStorage.getItem(FOLD_KEY) === "1"; } catch (error) { /* no storage: the fold is not remembered */ }
    function drawFold() {
      sv.classList.toggle("sa-fold-on", chatFolded);
      foldBtn.textContent = chatFolded ? "\u2303" : "\u2304";
      foldBtn.title = t(chatFolded ? "super.chat.unfold" : "super.chat.fold");
      foldBtn.setAttribute("aria-label", foldBtn.title);
      foldBtn.setAttribute("aria-expanded", chatFolded ? "false" : "true");
      if (!chatFolded) { toBottom(); }
    }
    function setFold(on, remember) {
      if (chatFolded === on) return;
      chatFolded = on;
      if (remember) { try { localStorage.setItem(FOLD_KEY, on ? "1" : "0"); } catch (error) { /* ignore */ } }
      drawFold();
    }
    const streamWrap = h("div", {class: "sa-streamwrap"}, stream, pill, foldLine, foldBtn);
    // The queue (1.8.4): the open items, pinned above the chat; the receipts of the settled ones fold into "Done (n)" at its foot.
    const queueList = h("div", {class: "sa-qlist", role: "list", "aria-label": t("super.queue")});
    const doneList = h("div", {class: "sa-qdlist"});
    const doneHead = h("summary", {title: t("super.done.tip")});
    const doneBox = h("details", {class: "sa-qdone", hidden: ""}, doneHead, doneList);
    const queue = h("div", {class: "sa-queue", hidden: ""}, queueList, doneBox);
    const hist = typeof SUPERHIST !== "undefined" ? SUPERHIST.create(streamWrap, (text) => rich(text)) : null;  // the earlier days (superhist.js)
    sv.append(h("div", {class: "sa-head"}, h("div", {class: "sa-who"}, h("div", {class: "sa-name"}, t("super.name")), lineEl), costEl, hist ? hist.button : null, popUp), team, filterEl, banner,
      h("div", {class: "sa-body"}, queue, streamWrap), quick, h("div", {class: "sa-input"}, complete, direct.tray, to, box));

    foldBtn.addEventListener("click", () => setFold(!chatFolded, true));
    foldLine.addEventListener("click", () => setFold(false, true));
    drawFold();
    let shown = false, pet = null, data = null, talk = null, talkGone = 0, first = true, vsDown = false, filter = "";
    let teamSig = "", bannerSig = "", mates = [], making = [], closedList = [], closedMore = 0, localThink = 0, failed = "";
    const PULSE_MS = 1500, PULSE_POLL_MS = 2500, PULSE_QUICK_MS = 15000;
    let pulseTimer = 0, pulseLast = "", pulseQuick = 0, pulseOff = 0;
    let pollTimer = 0, patrolToken = 0, noticeBusy = false, chain = Promise.resolve(), lastMate = "";
    let pointing = null, holdUntil = 0;  // the item the pet showed on a click (a second click soon after opens its task); the pet stays put until holdUntil
    let watchers = 0;  // the pop-out window is one: while it is open the data keeps coming, shown or not
    const live = () => shown || watchers > 0;
    const doneLog = [];  // what was settled while this page is open: {task, text, at}
    const listeners = new Set();
    const emit = () => { for (const fn of [...listeners]) { try { fn(); } catch (error) { /* a window that is gone must not stop the view */ } } };
    const known = new Map();  // item id -> {item, node, acts, waited, sig, clicked}
    const queued = new Set();
    const seenTalk = new Set();
    const SUMMARY_ASKED = "\u0000summary";  // stands for a summary request in pendingYou: the server writes its own words for it
    const pendingYou = [];  // what the person typed, until the agent's list has it too

    // ---------- small helpers ----------
    const rowFor = (task) => (rowsOf() || []).find((row) => row.name === task || row.task === task) || {name: task, task, state: "waiting", actions: []};
    const mateOf = (task) => [...team.children].find((node) => node.dataset.task === task) || null;
    const hostBox = () => sv.getBoundingClientRect();
    function fit() { sv.style.height = Math.max(460, Math.round(innerHeight - (sv.getBoundingClientRect().top + scrollY) - 14)) + "px"; }
    function atBottom() { return stream.scrollHeight - stream.scrollTop - stream.clientHeight < 90; }
    function toBottom() { stream.scrollTop = stream.scrollHeight; pill.hidden = true; }
    function add(node, forceDown) {
      const near = atBottom();
      stream.append(node);
      applyFilter();
      if (forceDown || near) toBottom(); else if (!node.hidden) pill.hidden = false;
    }
    pill.addEventListener("click", toBottom);
    stream.addEventListener("scroll", () => { if (atBottom()) pill.hidden = true; });

    // Task names in the agent's words become links to the task page.
    function linked(text) {
      const names = mates.map((mate) => mate.task).sort((a, b) => b.length - a.length);
      if (!names.length) return [String(text)];
      const found = new RegExp("(" + names.map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "g");
      return String(text).split(found).map((part, at) => (at % 2 ? taskLink(part, part) : part));
    }

    // The agent's words (F12): `**bold**` (also around `code`, with or without inner spaces), `code`, and [text](url) as a link when the url is http(s) or a board path; any other url is shown as text. A code fence left empty at the end
    // (what is left when the proposals block was cut out of it) goes. One pass with one pattern: no nesting but bold around the rest, so a long text costs a long text.
    const RICH = /\*\*([\s\S]+?)\*\*|`([^`\n]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)/g;
    const safeUrl = (url) => /^https?:\/\//i.test(url) || /^\/task\//.test(url);
    function rich(text, plainOnly) {
      const out = [];
      const source = String(text || "").replace(/(^|\n)[ \t]*(```|~~~)[\w-]*\s*\2[ \t]*(?=\s*$)/, "$1").replace(/\s+$/, "");
      let at = 0;
      for (const found of source.matchAll(RICH)) {
        if (found.index > at) out.push(...linked(source.slice(at, found.index)));
        if (found[1] !== undefined) out.push(h("b", null, ...(plainOnly ? [found[1].trim()] : rich(found[1].trim(), true))));
        else if (found[2] !== undefined) out.push(h("code", {class: "sa-ic"}, found[2]));
        else if (safeUrl(found[4])) out.push(h("a", {href: found[4], target: "_blank", rel: "noopener", class: "sa-link"}, found[3]));
        else out.push(found[3] + " (" + found[4] + ")");
        at = found.index + found[0].length;
      }
      if (at < source.length) out.push(...linked(source.slice(at)));
      return out;
    }

    // ---------- the avatars ----------
    // The recently closed tasks (1.8.17): not on the strip as avatars but behind one control at its end. A task is "closed" here only while it has no avatar: once it is open again its avatar takes over.
    const closedOnly = () => closedList.filter((one) => one && one.task && !mates.some((mate) => mate.task === one.task) && !making.some((item) => item && item.name === one.task));  // 1.8.50: one just handed to an agent turns on the strip instead
    const isClosed = (task) => Boolean(task) && closedOnly().some((one) => one.task === task);
    const closedTitle = (one) => String((one && one.title) || "");
    // 1.8.21: what a reopen of a closed task will be, said before the person presses. From the Closed list (`reopen` of the row: {mode: same | new | refused, round, next_round, why}); null when the server gave none (an older one).
    const reopenOf = (task) => { const one = closedList.find((item) => item && item.task === task); return one && one.reopen && typeof one.reopen === "object" && one.reopen.mode ? one.reopen : null; };
    const MODES = {new: ["new", "super.closed.mode.new"], same: ["same", "super.closed.mode.same"], partial: ["no", "super.closed.mode.partial"], checks: ["no", "super.closed.mode.checks"]};  // key -> [look, short word]
    const MODE_WHY = {partial: "super.reopen.why.partial", checks: "super.reopen.why.checks"};
    const modeKey = (info) => (!info ? "" : info.mode === "refused" ? (info.why === "checks" ? "checks" : "partial") : info.mode === "new" || info.mode === "same" ? info.mode : "");
    const modeLine = (info) => { const key = modeKey(info); return key === "new" ? t("super.reopen.line.new", {n: Number(info.next_round) || (Number(info.round) || 1) + 1}) : key === "same" ? t("super.reopen.line.same") : MODE_WHY[key] ? t(MODE_WHY[key]) : ""; };
    const modeTag = (info) => { const key = modeKey(info); return key ? h("span", {class: "sa-mtag " + MODES[key][0], title: modeLine(info)}, t(MODES[key][1])) : null; };
    function drawTeam(list, creating, shut, more) {
      mates = list; making = creating || [];
      if (shut) closedList = shut;
      closedMore = Number(more) > 0 ? Number(more) : 0;
      const sig = JSON.stringify([list, making, closedList, closedMore]) + "|" + filter;
      if (sig === teamSig) return;
      teamSig = sig;
      if (filter && !list.some((mate) => mate.task === filter) && !isClosed(filter)) filter = "";
      const all = h("button", {type: "button", class: "sa-mate all" + (filter ? "" : " on"), "data-task": "", title: t("super.team.all.tip")}, h("span", {class: "sa-ring"}, t("super.team.all")), h("span", {class: "sa-nm"}, t("super.team.all")));
      const nodes = list.map((mate, at) => {
        const state = MATE[mate.state] ? mate.state : "idle";
        const ring = h("span", {class: "sa-ring"}, state === "start" ? spinner("sa-spin") : PET.face(state === "you" || state === "error" ? "you" : state === "work" || state === "stuck" ? "work" : "idle", mate.kind, ((at * .37) % 3).toFixed(2)));
        const late = Boolean(mate.starting && mate.starting.late);  // 1.8.5: the board sent something and has not seen the agent start
        const tip = t("super.mate.tip", {task: mate.task, state: t(MATE[state])}) + (nameTip(mate) ? "\n" + nameTip(mate) : "") + (mate.starting ? "\n" + startingTip(mate.starting) : "");
        return h("button", {type: "button", class: "sa-mate " + state + (late ? " late" : "") + (filter === mate.task ? " on" : ""), "data-task": mate.task, "data-state": state, title: tip},
          ring, mate.count ? h("span", {class: "sa-cnt"}, mate.count) : null, late ? h("span", {class: "sa-late", "aria-hidden": "true"}) : null, h("span", {class: "sa-nm"}, shownName(mate)));
      });
      // One avatar for each task the board is still making: a spinner and its name; not a filter, no menu.
      const makes = making.map((one) => h("span", {class: "sa-mk", "data-making": one.name, title: makingTip(one)},
        h("span", {class: "sa-ring"}, makingInfo(one).stage === "refused" || makingInfo(one).stage === "lost" ? h("span", {class: "mk-dot", "aria-hidden": "true"}) : spinner("sa-spin")), h("span", {class: "sa-nm"}, one.name), h("span", {class: "sa-mkst"}, makingMarks(one, true))));
      const shutList = closedOnly(), shutN = shutList.length + (closedMore ? "+" : "");
      const closedBtn = shutList.length ? h("button", {type: "button", class: "sa-closed" + (isClosed(filter) ? " on" : ""), "aria-haspopup": "true", "aria-expanded": closedMenuNode ? "true" : "false", title: t("super.closed.tip", {n: shutN}), "aria-label": t("super.closed.tip", {n: shutN})},
        h("span", {class: "sa-ring", "aria-hidden": "true"}, h("span", {class: "sa-clico"}, "\u25A4")), h("span", {class: "sa-nm"}, t("super.closed", {n: shutN}))) : null;
      team.replaceChildren(all, ...nodes, ...makes, ...(closedBtn ? [closedBtn] : []));
      actModes();
    }
    team.addEventListener("click", (event) => {
      const shut = event.target.closest(".sa-closed");
      if (shut) { if (closedMenuNode) closedMenuClose(true); else closedMenuOpen(shut); return; }
      const mate = event.target.closest(".sa-mate");
      if (mate) setFilter(mate.dataset.task === filter ? "" : mate.dataset.task);
    });
    // ---------- the list of the closed tasks: a small menu under the control; picking one sets the filter to it (the input then reopens it) ----------
    let closedMenuNode = null, closedMenuFrom = null;
    function closedMenuClose(back) {
      if (!closedMenuNode) return;
      closedMenuNode.remove();
      closedMenuNode = null;
      removeEventListener("pointerdown", closedMenuOutside, true);
      removeEventListener("keydown", closedMenuKey, true);
      const from = closedMenuFrom;
      closedMenuFrom = null;
      if (from && from.isConnected) { from.setAttribute("aria-expanded", "false"); if (back) from.focus(); }
    }
    function closedMenuOutside(event) { if (closedMenuNode && !closedMenuNode.contains(event.target) && !(closedMenuFrom && closedMenuFrom.contains(event.target))) closedMenuClose(false); }
    function closedMenuKey(event) {
      if (!closedMenuNode) return;
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closedMenuClose(true); return; }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      const list = [...closedMenuNode.querySelectorAll("button.sa-cl-item")];
      if (!list.length) return;
      event.preventDefault();
      list[(list.indexOf(document.activeElement) + (event.key === "ArrowDown" ? 1 : -1) + list.length) % list.length].focus();
    }
    function closedMenuOpen(from) {
      closedMenuClose(false);
      const items = closedOnly().map((one) => {
        const node = h("button", {type: "button", role: "menuitem", class: "sa-skin sa-cl-item", "data-closed": one.task, title: one.task + (closedTitle(one) ? "\n" + closedTitle(one) : "") + (one.closed_at ? "\n" + t("super.closed.at", {when: when(one.closed_at, 5, 16)}) : "") + (modeLine(one.reopen) ? "\n" + modeLine(one.reopen) : "")},
          h("span", {class: "sa-cl-top"}, h("span", {class: "sa-cl-name"}, one.task), modeTag(one.reopen)), closedTitle(one) && closedTitle(one) !== one.task ? h("span", {class: "sa-cl-title"}, closedTitle(one)) : null);
        node.addEventListener("click", () => { closedMenuClose(false); setFilter(one.task); field.focus(); });
        return node;
      });
      closedMenuNode = h("div", {class: "sa-skins sa-closedmenu", role: "menu", "aria-label": t("super.closed.menu")}, h("div", {class: "sa-skins-head"}, t("super.closed.head")), ...items);
      closedMenuFrom = from;
      from.setAttribute("aria-expanded", "true");
      sv.append(closedMenuNode);
      const box = hostBox(), at = from.getBoundingClientRect(), size = {w: closedMenuNode.offsetWidth, h: closedMenuNode.offsetHeight};
      closedMenuNode.style.left = clamp(at.right - box.left - size.w, 0, Math.max(0, box.width - size.w)) + "px";
      closedMenuNode.style.top = clamp(at.bottom - box.top + 4, 0, Math.max(0, box.height - size.h)) + "px";
      const first = closedMenuNode.querySelector("button.sa-cl-item");
      if (first) first.focus();
      addEventListener("pointerdown", closedMenuOutside, true);
      addEventListener("keydown", closedMenuKey, true);
    }
    // ---------- the menu of an avatar (1.8.2): right click or the menu key. Steer and Stop, only while the task works ----------
    let mateMenuNode = null, mateMenuFrom = null;
    const mateMenuWorks = (task) => Boolean(["work", "stuck"].includes((mates.find((mate) => mate.task === task) || {}).state) || rowFor(task).state === "working");
    const mateSteer = (task, text) => SERVE.post("/api/steer", {task, text, lang: ""});  // the menu's and the pop-out's
    const mateStop = (task) => SERVE.post("/api/stop", {task});
    function mateMenuClose(back) {
      if (!mateMenuNode) return;
      mateMenuNode.remove();
      mateMenuNode = null;
      removeEventListener("pointerdown", mateMenuOutside, true);
      removeEventListener("keydown", mateMenuKey, true);
      if (back && mateMenuFrom && mateMenuFrom.isConnected) mateMenuFrom.focus();
    }
    function mateMenuOutside(event) { if (mateMenuNode && !mateMenuNode.contains(event.target)) mateMenuClose(false); }
    function mateMenuKey(event) {
      if (!mateMenuNode) return;
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); mateMenuClose(true); return; }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      const list = [...mateMenuNode.querySelectorAll("button.sa-skin, input.sa-mateline")].filter((node) => !node.disabled && !node.closest("[hidden]"));
      if (!list.length) return;
      event.preventDefault();
      const at = list.indexOf(document.activeElement);
      list[(at + (event.key === "ArrowDown" ? 1 : -1) + list.length) % list.length].focus();
    }
    function mateMenuOpen(mate) {
      mateMenuClose(false);
      const task = mate.dataset.task, works = mateMenuWorks(task);
      const item = (key, onClick) => {
        const node = h("button", {type: "button", role: "menuitem", class: "sa-skin sa-mateitem"}, t(key));
        node.disabled = !works;
        node.title = works ? "" : t(MATE.idle);
        node.addEventListener("click", onClick);
        return node;
      };
      const said = h("div", {class: "bad sa-matebad"});
      let busy = false;
      const send = (call, line) => {
        if (busy) return;
        busy = true;
        said.replaceChildren();
        call.then(() => { mateMenuClose(true); addSys(line); }, (error) => { busy = false; said.replaceChildren(...SERVE.reasons((error && error.message) || String(error))); });
      };
      const steerIn = steerBox(task, (words) => send(mateSteer(task, words), t("super.mate.steered", {task})), "sa-materow");
      const lineRow = steerIn.row;
      const steer = item("super.mate.steer", () => steerIn.open());
      const stop = item("super.mate.stop", () => send(mateStop(task), t("super.mate.stopped", {task})));
      mateMenuNode = h("div", {class: "sa-skins sa-matemenu", role: "menu", "aria-label": t("super.mate.menu", {task})}, h("div", {class: "sa-skins-head"}, task), steer, lineRow, stop, said);
      mateMenuFrom = mate;
      sv.append(mateMenuNode);
      const box = hostBox(), at = mate.getBoundingClientRect(), size = {w: mateMenuNode.offsetWidth, h: mateMenuNode.offsetHeight};
      mateMenuNode.style.left = clamp(at.left - box.left, 0, Math.max(0, box.width - size.w)) + "px";
      mateMenuNode.style.top = clamp(at.bottom - box.top + 4, 0, Math.max(0, box.height - size.h)) + "px";
      (works ? steer : mateMenuNode).focus();
      addEventListener("pointerdown", mateMenuOutside, true);
      addEventListener("keydown", mateMenuKey, true);
    }
    team.addEventListener("contextmenu", (event) => {
      const mate = event.target.closest(".sa-mate");
      if (!mate || !mate.dataset.task) return;
      event.preventDefault();
      mateMenuOpen(mate);
    });
    function setFilter(task) {
      filter = task;
      teamSig = "";
      drawTeam(mates, making);
      filterEl.hidden = !task;
      filterEl.replaceChildren(...(task ? [t("super.filter.only") + " ", taskLink(task, undefined, undefined, mates.find((mate) => mate.task === task)), " ", h("button", {type: "button", class: "sa-x", title: t("super.filter.clear"), "aria-label": t("super.filter.clear")}, "×")] : []));
      const clear = filterEl.querySelector(".sa-x");
      if (clear) clear.addEventListener("click", () => setFilter(""));
      applyFilter();
      drawInput();
    }
    const MANY = 3;
    function applyFilter() {
      let chat = 0, open = 0;
      for (const node of stream.children) {
        if (node === empty || node === earlier) continue;
        node.hidden = Boolean(filter) && node.dataset.task !== filter;
        if (!node.hidden) chat++;
      }
      for (const node of queueList.children) {
        node.hidden = Boolean(filter) && node.dataset.task !== filter;
        if (!node.hidden) open++;
      }
      let settled = 0;
      for (const node of doneList.children) {
        node.hidden = Boolean(filter) && node.dataset.task !== filter;
        if (!node.hidden) settled++;
      }
      doneBox.hidden = !settled;
      doneHead.replaceChildren(h("span", {class: "sa-qcheck", "aria-hidden": "true"}, "\u2713"), " " + t("super.done.head", {n: settled}));
      queue.hidden = !open && !settled;
      sv.classList.toggle("sa-many", queueList.children.length >= MANY);  // 3 or more waiting: the queue may take more room (changes only when the count crosses the line)
      sv.classList.toggle("sa-nochat", !chat);  // no chat yet: the queue takes the room
      empty.hidden = chat + open > 0;
      empty.replaceChildren(...[h("b", null, filter ? t("super.empty.filter") : mates.length ? t("super.empty.title") : t("super.empty.notasks")), filter || !mates.length ? null : h("div", null, t("super.empty.text"))].filter(Boolean));
    }

    // ---------- the messages ----------
    // A line of the chat. With a task it belongs to that task's thread (the filter of another task hides it, the filter of this one and All show it); `title`: the words it is about.
    function addSys(text, task, bad, title) { const node = h("div", {class: "sa-sys" + (bad ? " bad" : ""), "data-task": task || null, title: title || null}, text); add(node, true); return node; }
    // A long day: the chat shows its last FOLD messages; the older ones are behind "Show earlier" (the task items are never folded).
    const FOLD = 40, chatRows = [];
    let unfolded = false;
    function foldChat() {
      const hide = unfolded ? 0 : Math.max(0, chatRows.length - FOLD);
      chatRows.forEach((node, at) => node.classList.toggle("sa-folded", at < hide));
      earlier.hidden = !hide;
      earlier.textContent = hide ? t("super.earlier", {n: hide}) : "";
    }
    earlier.addEventListener("click", () => { unfolded = true; foldChat(); });
    // The person's words. With a `task` they are a message to that task (a direct one): the row belongs to its thread, and long words fold after FOLD_LINES lines behind "Show more".
    const FOLD_LINES = 8;
    function addYou(text, at, task) {
      const body = h("div", {class: "sa-ytext"}, text), bub = h("div", {class: "sa-bub", title: at ? when(at, 11, 16) : null}, body);
      if (task && routeEstimate(text) > FOLD_LINES) {
        const more = h("button", {type: "button", class: "sa-askmore sa-ymore"}, t("super.more"));
        body.classList.add("sa-clip");
        more.addEventListener("click", () => { body.classList.remove("sa-clip"); more.remove(); });
        bub.append(more);
      }
      const row = h("div", {class: "sa-row me", "data-task": task || null}, bub);
      chatRows.push(row);
      add(row, true);
      foldChat();
      return row;
    }
    function dropYou(row) {
      const at = chatRows.indexOf(row);
      if (at >= 0) chatRows.splice(at, 1);
      row.remove();
      foldChat();
    }
    function addAgent(message) {
      const judgment = h("span", {class: "sa-judg", title: t("super.judgment.tip"), "aria-label": t("super.judgment.tip")}, "◇");
      const row = h("div", {class: "sa-row"}, h("span", {class: "sa-mini boss"}, PET.face("calm", "", 0, true)),
        h("div", {class: "sa-bub agent"}, h("div", {class: "sa-fw"}, h("b", null, t("super.name")), judgment, message.at ? h("span", {class: "sa-when"}, when(message.at, 11, 16)) : null), h("div", {class: "sa-text"}, rich(message.text)), actCard(message)));
      chatRows.push(row);
      add(row);
      foldChat();
    }
    // The proposal card (1.8.3) under an agent message: one row per proposal the server checked (`proposals`, superact.py). The card presses nothing by itself.
    // Each button is the board's own (`actionButton`) or posts the one endpoint the board posts; a refused proposal shows its reason and no button.
    // The card is drawn again in place when its proposals change (the server checks them at every poll); words typed in a Send box stay.
    const ACT = new Map();  // message id -> {box, sig, list, drafts, pressed, done}
    const ACT_ALL = ["archive", "pause", "resume", "close", "review set"];  // "Do all" only for what needs no code and no dialog of its own
    const ACT_WHY = {open: "super.act.why.open", checks: "super.act.why.checks", unknown: "super.act.why.unknown", state: "super.act.why.state", kind: "super.act.why.kind", n: "super.act.why.n", text: "super.act.why.text", paused: "super.act.why.paused", closed: "super.act.why.closed", empty: "super.act.why.empty", long: "super.act.why.long", name: "super.act.why.name", taken: "super.act.why.taken", bad: "super.act.why.bad", ref: "super.act.why.ref", title: "super.act.why.title"};
    // The actions of 1.8.37 the page runs with the endpoint of the task page's own button: label, and the call (`call(one)` gives a promise).
    const NEW_ACT = {compact: "super.act.compact", retry: "super.act.retry", rename: "super.act.rename", "autorun off": "super.act.autorun.off", "task link": "super.act.link", "dismiss action": "super.act.dismiss"};
    const actLabel = (one) => (one.action === "dismiss action" && heldCodes(one.task).length > 1 ? t("super.act.dismiss.many", {n: heldCodes(one.task).length}) : t(NEW_ACT[one.action], {title: one.title || "", ref: one.ref || ""}));
    const STEP_WORD = {resume: "super.act.step.resume", "new-chat": "super.act.step.new-chat", send: "super.act.step.send"};  // written out: a search for a key finds its place
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    // The held calls of a task as the super view lists them (each has a code): "dismiss action" dismisses each, as the task page's Dismiss does with no reason.
    const heldCodes = (task) => ((data && data.items) || []).filter((item) => item.task === task && item.why === "outbox").flatMap((item) => callsOf(item).map((one) => one.code));
    function actCall(one) {
      const task = one.task;
      if (one.action === "compact") return SERVE.post("/api/compact", {task});
      if (one.action === "retry") return SERVE.post("/api/resume", {task});
      if (one.action === "rename") return SERVE.post("/api/title", {task, title: one.title});
      if (one.action === "autorun off") return SERVE.post("/api/autorun/stop", {task});
      if (one.action === "task link") return SERVE.post("/api/act", {action: "task link", task, env: one.ref, runner: "on", step: "act"});
      const codes = heldCodes(task);
      if (!codes.length) return Promise.reject(new Error(t("super.act.dismiss.none")));
      return codes.reduce((chain, code) => chain.then(() => SERVE.post("/api/act", {action: "dismiss action", task, step: "act", code, reason: "", note: ""})), Promise.resolve());
    }
    // The resume of a send chain: the board's own call, then wait (15 s at most) until the row is not paused any more.
    async function resumeStep(task) {
      try { await SERVE.post("/api/act", {action: "resume", task, step: "act"}); } catch (error) { return {ok: false, text: (error && error.message) || String(error)}; }
      SERVE.done(); poll();
      for (let tries = 0; tries < 30; tries++) {
        const row = (rowsOf() || []).find((one) => one.name === task || one.task === task);
        if (row && !row.paused_since) return {ok: true};
        await sleep(500);
      }
      return {ok: false, text: t("super.act.why.resume.timeout")};
    }
    const actSig = (list) => JSON.stringify(list || []);
    const actWhat = (one) => (one.kind === "send" ? t("super.act.send.to", {task: one.task})
      : one.kind === "reopen" ? t("super.act.reopen.to", {task: one.task})
      : one.kind === "new" ? t("super.act.new", {name: one.name})
      : one.action === "review set" ? t("super.act.set.what", {task: one.task, n: one.n})
      : one.action === "steer" ? t("super.act.steer.what", {task: one.task})
      : one.action === "stop" ? t("super.act.stop.what", {task: one.task})
      : NEW_ACT[one.action] ? actLabel(one) + " \u00b7 " + one.task
      : t("board.action." + String(one.action).replace(" ", "-")) + " · " + one.task);
    const actBad = (error) => SERVE.reasons((error && error.message) || String(error));
    function actRow(state, one, at) {
      const mark = () => { state.done.set(at, stamp()); actDraw(state); emit(); };
      const said = h("div", {class: "bad sa-actbad"});
      if (state.done.has(at)) return h("div", {class: "sa-actrow done"}, "✓ " + actWhat(one) + " · " + state.done.get(at));
      if (one.ok === false) {
        if (state.pressed.has(at) && one.kind === "action") return h("div", {class: "sa-actrow done"}, "✓ " + actWhat(one) + " · " + state.pressed.get(at));  // pressed on the board's button; the state it needed is gone now
        return h("div", {class: "sa-actrow no"}, one.task ? taskLink(one.task) : null, h("span", {class: "sa-actwhy"}, t(ACT_WHY[one.why] || ACT_WHY.bad)));
      }
      const post = (button, call) => {
        button.disabled = true; said.replaceChildren();
        call().then(mark, (error) => { button.disabled = false; said.replaceChildren(...actBad(error)); });
      };
      if (one.kind === "new") {
        const go = h("button", {type: "button", class: "act hot live"}, t("super.act.new.go"));
        go.addEventListener("click", () => { state.pressed.set(at, stamp()); CHAT.create({name: one.name, kind: one.task_kind, text: one.text}); });
        return h("div", {class: "sa-actrow"}, h("div", {class: "sa-acthead"}, h("span", {class: "sa-actwhat"}, actWhat(one)), h("span", {class: "sa-actkind"}, one.task_kind || "dev"), go), h("div", {class: "sa-acttext"}, one.text));
      }
      if (one.kind === "send" || one.kind === "reopen") {  // a reopen card is a send card for a closed task: the same editable message and menu, its checks from the proposal, and the button says Reopen; the same options menu as the input; the receipt says how it went (sent, queued, said, new chat)
        const shut = one.kind === "reopen";
        const box = h("textarea", {class: "sa-reply-box sa-acttextbox", rows: "3", maxlength: SUPERDIRECT.MAX, "aria-label": t("super.act.send.tip")});
        box.value = state.drafts.has(at) ? state.drafts.get(at) : (one.text || "");
        box.addEventListener("input", () => state.drafts.set(at, box.value));
        const options = SUPERDIRECT.menu(box, sv, (task) => shut || isClosed(task));
        options.bind(one.task);
        options.presetChecks(state.picked.has(at) ? state.picked.get(at) : shut && Number.isInteger(one.checks) ? one.checks : "");  // the card holds its own checks: the box's are not its
        state.chain = state.chain || new Map();  // chain of a send card: {steps, mark: {step: run|done|fail}, fail, text}; it lives in the state so a redraw in the middle (the check gives other steps once it resumed) keeps it
        const chain = shut ? null : state.chain.get(at);
        const plan = chain ? chain.steps : !shut && Array.isArray(one.steps) && one.steps.length > 1 ? one.steps : null;
        const running = Boolean(chain && !chain.fail);
        const go = h("button", {type: "button", class: "act hot live"}, t(shut ? "super.act.reopen.go" : chain && chain.fail ? "super.act.again" : running ? "super.act.running" : plan && plan.includes("resume") ? "super.act.resume.send" : "super.act.send.go"));
        const alt = plan && !chain && plan.includes("resume") && !plan.includes("new-chat") ? h("button", {type: "button", class: "act live", title: t("super.act.newchat.instead.tip")}, t("super.act.newchat.instead")) : null;  // a chat is bound: the same chain, with a new chat
        const stepsLine = plan ? h("div", {class: "sa-steps"}, t("super.act.steps"), ...plan.flatMap((step, i) => { const m = chain && chain.mark[step]; return [i ? " \u2192 " : " ", h("span", {class: "sa-step" + (m ? " " + m : "")}, (m === "done" ? "\u2713 " : m === "fail" ? "\u2715 " : m === "run" ? "\u2026 " : "") + t(STEP_WORD[step]))]; })) : null;
        if (running) { go.disabled = true; box.disabled = true; }
        const only = shut ? h("button", {type: "button", class: "act live", title: t("super.reopen.only.tip")}, t("super.reopen.only")) : null;  // 1.8.21: only the person's click opens the task with no chat
        const modeBox = shut ? h("div", {class: "sa-rmbox"}) : null;
        // 1.8.21: the mode of the reopen, above the message: what it will be before the person presses (or, with checks above 0, that it is checks after the close and not a reopen)
        const drawMode = () => {
          if (!shut) return;
          const info = reopenOf(one.task), key = modeKey(info), n = options.checks(), after = n !== null && n > 0, cant = !after && key !== "" && info.mode === "refused";
          state.picked.set(at, n === null ? "" : n);
          go.textContent = t(after ? "super.act.reopen.after.go" : "super.act.reopen.go");
          go.disabled = cant;
          only.hidden = after;
          only.disabled = cant;
          const badge = after ? [h("span", {class: "sa-mode new"}, t("super.act.reopen.mode.after")), t(n === 1 ? "super.reopen.after.one" : "super.reopen.after.many", {n})]
            : cant ? [h("span", {class: "sa-mode no"}, t("super.act.reopen.mode.no")), modeLine(info)]
            : key === "new" ? [h("span", {class: "sa-mode new"}, t("super.act.reopen.mode.new", {n: Number(info.next_round) || (Number(info.round) || 1) + 1})), t("super.act.reopen.moves", {r: Number(info.round) || 1})]
            : key === "same" ? [h("span", {class: "sa-mode same"}, t("super.act.reopen.mode.same")), t("super.act.reopen.same")] : null;
          modeBox.hidden = !badge;
          modeBox.replaceChildren(...(badge ? [badge[0], h("div", {class: "sa-rmline"}, badge[1], ...(cant && key === "partial" ? [" ", taskLink(one.task, t("super.reopen.recover"), "sa-to-link")] : []))] : []));
          const link = modeBox.querySelector(".sa-to-link");
          if (link) link.title = t("super.reopen.recover.tip");
        };
        options.onchange = drawMode;
        drawMode();
        // Press: the steps in order. Resume (then wait until the task is not paused), then the send, which makes the chat too when New chat is a step (`/api/super/send` with `new_chat`). The first failure stops the chain; Try again goes on from there.
        const runChain = async (steps, again) => {
          const text = box.value.trim();
          if (!text || options.reading()) return;
          const values = options.values();
          const now = again || {steps, mark: {}, fail: null, text: ""};
          now.fail = null; now.text = ""; state.chain.set(at, now);
          const failed = (step, why) => { now.mark[step] = "fail"; now.fail = step; now.text = why; actDraw(state); emit(); };
          for (const step of now.steps) {
            if (now.mark[step] === "done" || step === "new-chat") continue;  // new-chat is made by the send
            const fresh = step === "send" && now.steps.includes("new-chat");
            now.mark[step] = "run"; if (fresh) now.mark["new-chat"] = "run";
            actDraw(state); emit();
            if (step === "resume") {
              const result = await resumeStep(one.task);
              if (!result.ok) return failed(step, result.text);
              now.mark[step] = "done";
            } else {
              const result = await directSend(one.task, text, {...values, ...(fresh ? {new_chat: true} : {})}, true, false);
              if (!result.ok && result.why === "paused" && now.steps.includes("resume")) delete now.mark.resume;  // paused again since the resume: Try again resumes again
              if (!result.ok) { const bad = SUPERDIRECT.whyText(result.why, result.error); return fresh && !String(result.why).startsWith("text") ? (delete now.mark.send, failed("new-chat", bad)) : failed(step, bad); }
              state.chain.delete(at);
              state.done.set(at, SUPERDIRECT.howWord(result.how, result) + " \u00b7 " + stamp()); actDraw(state); emit(); return;
            }
          }
        };
        if (plan) {
          go.addEventListener("click", () => runChain(plan, chain && chain.fail ? chain : null));
          if (alt) alt.addEventListener("click", () => runChain(["resume", "new-chat", "send"], null));
        }
        else go.addEventListener("click", async () => {
          const text = box.value.trim();
          if ((!text && !shut) || options.reading()) return;
          go.disabled = true; said.replaceChildren();
          if (only) only.disabled = true;
          const result = await directSend(one.task, text, options.values(), true, shut);
          if (result.ok) { options.clear(); state.done.set(at, SUPERDIRECT.howWord(result.how, result) + " \u00b7 " + stamp()); actDraw(state); emit(); return; }
          drawMode();
          said.replaceChildren(...refusalNodes(one.task, result.why, result.error, (words) => said.replaceChildren(words)));
        });
        if (only) only.addEventListener("click", async () => {
          go.disabled = true; only.disabled = true; said.replaceChildren();
          const result = await reopenCall(one.task);
          if (result.ok) { state.done.set(at, t("super.reopen.how") + " \u00b7 " + stamp()); actDraw(state); emit(); return; }
          drawMode();
          said.replaceChildren(...actBad(result.error));
        });
        if (chain && chain.fail) said.replaceChildren(...(chain.fail === "resume" ? SERVE.reasons(chain.text) : [chain.text]));
        return h("div", {class: "sa-actrow"}, h("div", {class: "sa-acthead"}, h("span", {class: "sa-actwhat", title: actWhat(one)}, actWhat(one)), taskLink(one.task)), stepsLine, modeBox, h("div", {class: "sa-reply"}, box, options.button, go, alt, only), options.tray, said);
      }
      let button;
      if (one.action === "review set") {
        button = h("button", {type: "button", class: "act hot live"}, t("super.act.set", {n: one.n}));
        button.addEventListener("click", () => post(button, () => SERVE.post("/api/act", {action: "review set", task: one.task, n: one.n, step: "act"})));
      } else if (one.action === "steer") {
        button = h("button", {type: "button", class: "act hot live"}, t("super.act.steer"));
        button.addEventListener("click", () => post(button, () => mateSteer(one.task, one.text || "")));
      } else if (one.action === "stop") {
        button = h("button", {type: "button", class: "act hot live"}, t("super.act.stop"));
        button.addEventListener("click", () => post(button, () => mateStop(one.task)));
      } else if (NEW_ACT[one.action]) {
        button = h("button", {type: "button", class: "act hot live", title: actLabel(one)}, actLabel(one));
        button.addEventListener("click", () => post(button, () => actCall(one).then((result) => { SERVE.done(); poll(); return result; })));
      } else {
        button = actionButton(rowFor(one.task), {action: one.action});
        button.addEventListener("click", () => state.pressed.set(at, stamp()));  // the board's button does the work (and asks its code or dialog); the next check shows the result
      }
      return h("div", {class: "sa-actrow"}, h("div", {class: "sa-acthead"}, taskLink(one.task), button), one.action === "steer" && one.text ? h("div", {class: "sa-acttext"}, one.text) : null, said);
    }
    function actAll(state) {
      const groups = new Map();
      (state.list || []).forEach((one, at) => { if (one.kind === "action" && one.ok && ACT_ALL.includes(one.action) && !state.done.has(at)) { const key = one.action === "review set" ? "review set:" + one.n : one.action; groups.set(key, [...(groups.get(key) || []), [one, at]]); } });
      const found = [...groups.values()].find((group) => group.length > 1);
      if (!found) return null;
      const said = h("div", {class: "bad sa-actbad"});
      const go = h("button", {type: "button", class: "act hot live"}, t("super.act.all", {n: found.length}));
      go.addEventListener("click", async () => {
        go.disabled = true; said.replaceChildren();
        if (found[0][0].action === "archive") { SERVE.archive(found.map(([one]) => one.task), ""); go.disabled = false; return; }  // one dialog for all names, as the board's
        for (const [one, at] of found) {
          try { await SERVE.post("/api/act", {action: one.action, task: one.task, ...(one.action === "review set" ? {n: one.n} : {}), step: "act"}); state.done.set(at, stamp()); }
          catch (error) { said.replaceChildren(h("b", null, one.task + ": "), ...actBad(error)); go.disabled = false; actDraw(state); emit(); return; }
        }
        actDraw(state); emit();
      });
      return h("div", {class: "sa-actrow sa-actall"}, go, said);
    }
    const modeSigOf = (list) => JSON.stringify((list || []).filter((one) => one && one.kind === "reopen").map((one) => reopenOf(one.task)));
    function actDraw(state) {
      state.modes = modeSigOf(state.list);
      const rows = (state.list || []).map((one, at) => actRow(state, one, at));
      const all = actAll(state);
      state.box.replaceChildren(h("div", {class: "sa-acthd"}, t("super.act.head")), ...rows, ...(all ? [all] : []));
      state.sig = actSig(state.list);
    }
    function actCard(message) {
      if (!message || !Array.isArray(message.proposals) || !message.proposals.length) return null;
      const state = {box: h("div", {class: "sa-act"}), sig: "", modes: "", list: message.proposals, drafts: new Map(), pressed: new Map(), done: new Map(), picked: new Map()};
      ACT.set(message.id, state);
      actDraw(state);
      return state.box;
    }
    // The Closed list changed (a check began, a promote was put right): a reopen card that says what the reopen will be is drawn again with the new mode.
    function actModes() {
      for (const state of ACT.values()) if (state.box.isConnected && state.modes !== modeSigOf(state.list)) actDraw(state);
    }
    function actRefresh(message) {
      const state = ACT.get(message.id);
      if (!state || !Array.isArray(message.proposals) || actSig(message.proposals) === state.sig) return;
      state.list = message.proposals;
      actDraw(state);
    }
    let typing = null;
    function typingBubble(on) {
      if (on && !typing) {
        typing = h("div", {class: "sa-row"}, h("span", {class: "sa-mini boss"}, PET.face("calm", "", 0, true)), h("div", {class: "sa-bub agent"}, h("span", {class: "sa-dots", role: "img", "aria-label": t("super.think")}, h("i"), h("i"), h("i"))));
        add(typing);
      } else if (!on && typing) { typing.remove(); typing = null; }
    }
    function mergeTalk(list) {
      for (const message of list || []) {
        if (message && seenTalk.has(message.id)) { actRefresh(message); continue; }
        if (!message) continue;
        seenTalk.add(message.id);
        if (message.role === "you") {
          const at = pendingYou.indexOf(message.kind === "summary" ? SUMMARY_ASKED : message.text);  // a summary request is shown with the button's own label
          if (at >= 0) { pendingYou.splice(at, 1); continue; }
          typingBubble(false); addYou(message.kind === "summary" ? t("super.quick.summary") : message.text, message.at);
        } else {
          typingBubble(false);
          if (localThink && Date.parse(message.at || "") >= localThink - 5000) localThink = 0;
          if (!first) setFold(false, false);  // a new agent message unfolds the chat
          addAgent(message);
        }
      }
    }

    // A chat that asks the person, or a held outside call: the real question or command is in `detail`, the `title` is a generic line. Show the detail as the message when there is one.
    const asksPerson = (item) => ["confirm", "question", "asking", "outbox"].includes(item.why) && Boolean(item.detail);
    const said = (item) => (item.said && !asksPerson(item) && !summaryOf(item) ? String(item.said) : "");  // the agent's last words of a stopped, accepted or cancelled task
    // 1.8.4: an asking item shows the question itself (`question.message`, from the mark; an older mark has none), an error its message, a delivery its summary.
    const questionOf = (item) => (item.why === "asking" && item.question && item.question.message ? item.question : null);
    const summaryOf = (item) => (item.why === "accept" && item.deliver && item.deliver.summary ? String(item.deliver.summary) : "");
    const callsOf = (item) => (item.why === "outbox" && Array.isArray(item.calls) ? item.calls.filter((one) => one && one.code) : []);  // a held call with its command: the card draws it (callRow), not the one line of the board
    const prose = (item) => Boolean(questionOf(item) || summaryOf(item) || item.why === "error");  // words, not a command: the card's text is not in the code font
    const mainOf = (item) => (questionOf(item) ? questionOf(item).message : summaryOf(item) || (item.why === "error" ? item.detail || item.title : asksPerson(item) ? item.detail : said(item) || item.title));
    const fullOf = (item) => (questionOf(item) ? questionOf(item).message : asksPerson(item) ? item.detail : "");
    const clampable = (item) => asksPerson(item) || prose(item);
    // 1.8.43: the card shows two lines of the task's last words, as plain text; the whole words are the task's line in the chat (`says`, drawn by sayBuild). `sumOf`: the words without Markdown marks, on one line.
    const sumOf = (text) => String(text || "").replace(/```[\s\S]*?```/g, " ").replace(/\*\*|__|`/g, "").replace(/\[([^\]\n]+)\]\([^)\s]+\)/g, "$1").replace(/^[ \t]*(#+|[-*+]|\d+\.)[ \t]+/gm, "").split(/\s+/).join(" ").trim();
    const hasSay = (item) => Boolean(item && item.said) && ["stopped", "accept", "cancelled"].includes(item.why);

    // One item of the board: who it comes from, what it is, its buttons. Its buttons are drawn again only when the row of the task changed what they would be.
    function sigFor(item) {
      const row = rowFor(item.task);
      return JSON.stringify([item.why, item.actions.map((one) => one.action), row.state, row.chat ? [row.chat.bound, row.chat.why] : null, row.req_unconfirmed || false, row.todo_left || 0, callsOf(item).map((one) => one.code), item.resumable]);
    }
    const sigOf = (entry) => sigFor(entry.item);
    // ---------- the held call (1.8.4): its command and code on the card, View, the typed code, Approve ----------
    // The same three guards as the task page: Approve works only after View (the call is drawn from the server's copy and its `seen` is what Approve sends), the person types the code, and a command that
    // changed since View is refused by the server (`changed`): "viewed" is taken back and View is asked for again. What was viewed and typed is kept by the call's code, so a card drawn again (here or in the pop-out) keeps it.
    const VIEWED = new Map(), TYPED = new Map(), CHANGED = new Map();  // call code -> the files pinned at View / the code typed / why the last Approve was refused
    const CTL = new Set();  // the controls of the cards on show: {code, node, arm}
    function armAll(code) {
      for (const ctl of [...CTL]) {
        if (!ctl.node.isConnected && Date.now() - ctl.born > 3000) { CTL.delete(ctl); continue; }
        if (ctl.code === code) ctl.arm();
      }
    }
    // The window View opens is the task page's, whole (callview.js): the call as the server shows it (`/api/super/preview`, taskdesk.outbox_view). View marks it as seen; the code chip fills the card's box.
    function callRow(item, one) {
      const can = SERVE.runs("approve-action");
      const code = one.code;
      const input = h("input", {class: "code sa-code", autocomplete: "off", spellcheck: "false", placeholder: t("desk.outbox.code"), "aria-label": t("board.serve.code")});
      input.value = TYPED.get(code) || "";
      const view = h("button", {type: "button", class: "act sa-view"}, t("desk.outbox.view"));
      const seen = h("span", {class: "sa-seen", title: t("super.call.viewed"), hidden: ""}, "✓");
      const yes = h("button", {type: "button", class: "act hot sa-approve", disabled: "disabled", "data-act": "approve-action", "data-label": t("desk.outbox.approve")}, t("desk.outbox.approve"));
      const said = h("div", {class: "bad sa-actbad"});
      const ready = () => can && VIEWED.has(code) && input.value.trim().length > 0;
      const arm = () => {
        const viewed = VIEWED.has(code);
        yes.disabled = !ready();
        yes.title = ready() || !can ? "" : viewed ? t("desk.outbox.type_code") : t("desk.outbox.view_first");
        seen.hidden = !viewed;
        view.classList.toggle("pulse", can && !viewed);  // the order is View, then the code: View pulses until it was opened, then the box until a code is typed
        input.classList.toggle("pulse", can && viewed && !input.value.trim());
        if (!viewed && CHANGED.has(code) && !said.textContent) said.textContent = CHANGED.get(code);
      };
      const lead = !one.title || String(one.command || "").startsWith(plain(one.title));  // a title that is only the start of the command says nothing more
      const node = h("div", {class: "sa-call", "data-code": code},
        h("div", {class: "sa-callh"}, h("span", {class: "sa-chip", title: t("desk.outbox.code")}, code), one.system ? h("span", {class: "sa-sys", title: one.verb || ""}, one.system + (one.env && one.env !== "none" ? " · " + one.env : "")) : null, lead ? null : h("span", {class: "sa-ctitle", title: one.title || ""}, one.title || ""),
          h("code", {class: "sa-cmd", title: t("super.call.cmd.tip")}, one.command || "")),
        h("div", {class: "sa-callgo"}, view, seen, input, yes), said);
      CTL.add({code, node, arm, born: Date.now()});
      input.addEventListener("input", () => { TYPED.set(code, input.value); arm(); });
      view.addEventListener("click", () => {
        view.disabled = true;
        said.replaceChildren();
        SERVE.post("/api/super/preview", {task: item.task, kind: "call", code}).then((result) => {
          view.disabled = false;
          if (!result || result.ok !== true || !result.call) { said.textContent = t("super.call.gone"); return; }
          CALLVIEW.open(result.call, {
            onOpen: (call) => { VIEWED.set(code, call.seen || {}); CHANGED.delete(code); armAll(code); },  // seen: Approve is held to the files as they are now
            onCode: (typed) => { TYPED.set(code, typed); input.value = typed; armAll(code); yes.focus(); }});
        }, (error) => { view.disabled = false; said.replaceChildren(...actBad(error)); });
      });
      const send = () => {
        if (!ready()) return;
        yes.disabled = true; yes.textContent = t("board.serve.working"); said.replaceChildren();
        SERVE.post("/api/act", {action: "approve-action", task: item.task, step: "act", code: input.value.trim(), seen: {code, files: VIEWED.get(code) || {}}}).then(() => {
          const entry = known.get(item.id);
          if (entry) entry.clicked = receiptFor("approve-action");
          TYPED.delete(code); VIEWED.delete(code);
          SERVE.done(); poll(); emit();
        }, (error) => {
          if (error && error.data && error.data.changed) { VIEWED.delete(code); CHANGED.set(code, error.message); }  // a file changed since View: View is asked for again
          said.replaceChildren(...actBad(error));
          yes.textContent = t("desk.outbox.approve");
          armAll(code);
        });
      };
      yes.addEventListener("click", send);
      input.addEventListener("keydown", (event) => { if (isEnter(event) && !yes.disabled) send(); });
      arm();
      return node;
    }

    // The one-line steer box (1.8.25), for the Stuck card and the avatar's menu: the input, a Send button (as the reply box has) and a small x. Enter or Send sends; Escape or x closes; the steer button
    // opens it, and while it holds words a second press only focuses it, so typed words are not lost. After a send the caller closes it (the words go).
    function steerBox(task, send, extra) {
      const line = h("input", {type: "text", class: "sa-mateline sa-steerline", maxlength: 2000, placeholder: t("super.mate.steer.ph", {task}), "aria-label": t("super.mate.steer.ph", {task})});
      const go = h("button", {type: "button", class: "act hot sa-reply-go sa-steergo"}, t("super.reply.send"));
      const shut = h("button", {type: "button", class: "act sa-steershut", title: t("super.steer.close"), "aria-label": t("super.steer.close")}, "\u2715");
      const row = h("div", {class: "sa-steerrow" + (extra ? " " + extra : ""), hidden: ""}, line, go, shut);
      const text = () => line.value.trim();
      const open = () => { row.hidden = false; line.focus(); };
      const close = () => { row.hidden = true; line.value = ""; };
      const push = () => { if (text()) send(text()); };
      go.addEventListener("click", push);
      shut.addEventListener("click", close);
      line.addEventListener("keydown", (event) => {
        if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); return; }
        if (isEnter(event) && !event.shiftKey) { event.preventDefault(); push(); }
      });
      return {row, line, open, close, toggle: () => { if (row.hidden) open(); else if (text()) line.focus(); else close(); }};  // a second press hides the box only when it is empty
    }
    // ---------- an error and a stuck chat (1.8.4) ----------
    function errorButtons(item) {
      const retry = h("button", {type: "button", class: "act hot live", "data-act": "retry", title: t(item.resumable === false ? "super.retry.no" : "super.retry.tip")}, t("super.retry"));
      const said = h("div", {class: "bad sa-actbad"});
      retry.addEventListener("click", () => {
        retry.disabled = true; said.replaceChildren();
        SERVE.post("/api/resume", {task: item.task}).then(() => { const entry = known.get(item.id); if (entry) entry.clicked = t("super.done.retried"); retry.disabled = false; SERVE.done(); poll(); emit(); },
          (error) => { retry.disabled = false; said.replaceChildren(...actBad(error)); });  // a refusal says why, here
      });
      return [retry, said];
    }
    function stuckButtons(item) {
      const said = h("div", {class: "bad sa-actbad"});
      const steer = h("button", {type: "button", class: "act hot live", "data-act": "steer"}, t("super.mate.steer"));
      const stop = h("button", {type: "button", class: "act live", "data-act": "stop"}, t("super.mate.stop"));
      let busy = false;
      const send = (call, receipt, said_) => {  // the mate menu's own calls (mateSteer, mateStop)
        if (busy) return;
        busy = true; said.replaceChildren();
        call.then(() => { busy = false; box.close(); const entry = known.get(item.id); if (entry) entry.clicked = t(receipt); addSys(said_); poll(); emit(); }, (error) => { busy = false; said.replaceChildren(...actBad(error)); });
      };
      const box = steerBox(item.task, (words) => send(mateSteer(item.task, words), "super.done.steered", t("super.mate.steered", {task: item.task})));
      steer.addEventListener("click", box.toggle);
      stop.addEventListener("click", () => send(mateStop(item.task), "super.done.stopped", t("super.mate.stopped", {task: item.task})));
      return [steer, stop, box.row, said];
    }

    // ---------- Accept and close (1.8.4): 10 s in the page, then the accept is sent ----------
    // The person presses Accept; nothing goes to the server until the countdown ends, so Undo (or a page that is closed) leaves the task open. A task whose held calls still wait asks its second yes at once (the board's window,
    // which closes at once: that yes is the deliberate one). The state is kept by the item, so the view and the pop-out show the same countdown.
    const ACCEPT_SECONDS = 10;
    const COUNT = new Map();  // item id -> {end, timer} while counting down; "sending" once it went
    const COUNT_BAD = new Map();  // item id -> why the accept was refused
    function acceptEnd(item) {
      const state = COUNT.get(item.id);
      if (!state) return;
      state.sending = true;
      SERVE.post("/api/act", {action: "accept", task: item.task, step: "act"}).then(() => {
        COUNT.delete(item.id);
        const entry = known.get(item.id);
        if (entry) entry.clicked = receiptFor("accept");
        SERVE.done(); poll(); emit();
      }, (error) => { COUNT.delete(item.id); COUNT_BAD.set(item.id, (error && error.message) || String(error)); emit(); });
    }
    function acceptNode(item) {
      const row = rowFor(item.task);
      const wrap = h("span", {class: "sa-accept"});
      const button = h("button", {type: "button", class: "act hot live", "data-act": "accept", "data-label": t("board.action.accept")}, t("board.action.accept"));
      SERVE.running(item.task, "accept", button);  // an accept that goes on behind the page (serve.js) shows "working" here too
      button.addEventListener("click", () => {
        button.disabled = true;
        COUNT_BAD.delete(item.id);
        SERVE.post("/api/act", {action: "accept", task: item.task, step: "preview"}).then((data) => {
          button.disabled = false;
          if ((((data && data.result) || {}).held || []).length) { SERVE.act(button, row, {action: "accept"}); return; }  // calls still wait: the board's window asks first
          COUNT.set(item.id, {end: Date.now() + ACCEPT_SECONDS * 1000, timer: setTimeout(() => acceptEnd(item), ACCEPT_SECONDS * 1000)});
          draw(); emit();
        }, (error) => { button.disabled = false; COUNT_BAD.set(item.id, (error && error.message) || String(error)); draw(); });
      });
      const undo = h("button", {type: "button", class: "act", title: t("super.accept.tip")}, t("super.accept.undo"));
      undo.addEventListener("click", () => {
        const state = COUNT.get(item.id);
        if (!state || state.sending) return;
        clearTimeout(state.timer);
        COUNT.delete(item.id);
        draw(); emit();
      });
      function draw() {
        const state = COUNT.get(item.id), bad = COUNT_BAD.get(item.id);
        if (state) {
          const left = Math.max(0, Math.ceil((state.end - Date.now()) / 1000));
          undo.disabled = Boolean(state.sending);
          wrap.replaceChildren(h("span", {class: "sa-count", role: "timer", title: t("super.accept.tip")}, t("super.accept.count", {n: left})), " · ", undo);
        } else wrap.replaceChildren(button, ...(bad ? [h("div", {class: "bad sa-actbad"}, ...SERVE.reasons(bad))] : []));
      }
      draw();
      let ticks = 0;
      const tick = setInterval(() => { if (!wrap.isConnected && ++ticks > 8) { clearInterval(tick); return; } if (wrap.isConnected) ticks = 0; draw(); }, 250);
      return wrap;
    }
    // The buttons of one item (also the pop-out window's): the board's own, so every action goes through SERVE.act / CHAT as in the board; the held call, an error, a stuck chat and Accept have their own (above).
    function buttonsFor(item) {
      if (item.why === "error") return errorButtons(item);
      if (item.why === "stuck") return stuckButtons(item);
      const row = rowFor(item.task), calls = callsOf(item), nodes = [];
      for (const one of item.actions) {
        if (one.action === "answer") continue;  // 1.8.4: the reply box of a stopped item is on the card; a link to the task page beside "Open task" said the same
        if (one.action === "approve-action" && calls.length) { nodes.push(...calls.map((call) => callRow(item, call))); continue; }
        if (one.action === "accept") { nodes.push(acceptNode(item)); continue; }
        const button = actionButton(row, one);
        button.dataset.act = one.action;
        button.addEventListener("click", () => { const entry = known.get(item.id); if (entry) entry.clicked = receiptFor(one.action); });  // what the receipt says if this settles it (a window the person closes settles nothing: the next poll says so)
        nodes.push(button);
      }
      return nodes;
    }
    function drawActs(entry) {
      const buttons = buttonsFor(entry.item);
      const open = taskLink(entry.item.task, t("super.open") + " ↗", "act sa-open");
      const goes = buttons.filter((node) => node.classList && node.classList.contains("sa-call")).map((node) => node.querySelector(".sa-callgo")).filter(Boolean);
      entry.acts.classList.toggle("sa-calls", goes.length > 0);
      if (goes.length) goes[goes.length - 1].append(open);  // a held call: "Open task" sits in the row of its buttons, not on a line of its own
      const toChat = hasSay(entry.item) ? h("button", {type: "button", class: "act" + (entry.item.why === "stopped" ? " hot" : ""), title: t("super.say.tip")}, t(entry.item.why === "stopped" ? "super.say.reply" : "super.say.show")) : null;
      if (toChat) toChat.addEventListener("click", () => showSay(entry.item));
      entry.acts.replaceChildren(...(toChat ? [toChat] : []), ...buttons, ...(goes.length ? [] : [open]));
      entry.sig = sigOf(entry);
    }
    function drawWaited(entry) {
      const seconds = entry.item.waited_s;
      entry.waited.textContent = seconds === null || seconds === undefined ? "" : t("super.waited", {time: clock(seconds)});
      entry.waited.title = entry.item.since ? when(entry.item.since, 0, 19) : "";
    }
    // The reply box of a "stopped" item (the agent ended its turn with a question in text): the answer goes to the task's chat through /api/send, the item folds as answered.
    // On a refusal (409 and the like) the reasons show under the box and the words stay.
    // The same box for an item that waits on the agent's own question (why "question"): the words skip the question (the server turns the send into "say"); never for "confirm".
    const SAYS = (item) => Boolean(item) && item.why === "question";  // 1.8.4: not for "asking": the chat waits for its answer in VS Code, and the server refuses words sent to a chat that is not idle
    function replyBox(entry) {
      const box = h("textarea", {class: "sa-reply-box", rows: "2", placeholder: t(SAYS(entry.item) ? "super.reply.say.ph" : "super.reply.ph"), title: t("super.reply.tip")});
      const send = h("button", {type: "button", class: "act hot sa-reply-go"}, t("super.reply.send"));
      const said = h("div", {class: "bad sa-reply-bad"});
      let busy = false;
      const go = () => {
        const text = box.value.trim();
        if (!text || busy) return;
        busy = true;
        send.disabled = true;
        said.replaceChildren();
        SERVE.post("/api/send", {task: entry.item.task, kind: "answer", lang: "", note: "", body: text, step: "act"}).then(() => {
          busy = false;
          entry.clicked = t("super.done.sent");
          reply.classList.add("sent");  // the same box in the pop-out goes too
          fold(entry, null);
          emit();
        }, (error) => {
          busy = false;
          send.disabled = false;
          said.replaceChildren(...SERVE.reasons((error && error.message) || String(error)));
        });
      };
      send.addEventListener("click", go);
      box.addEventListener("keydown", (event) => { if (isEnter(event) && !event.shiftKey) { event.preventDefault(); go(); } });
      const reply = h("div", {class: "sa-reply"}, box, send, said);
      return reply;
    }
    // The preview under a "plan", "promote", "req" or "accept" message (1.8.2, 1.8.4): asked once per item id, shown folded as one line; a refusal or nothing to show draws nothing.
    const PREVIEW_ASKED = new Map();  // item id -> the answer (a promise): the view and the pop-out both draw from it
    const previewKind = (item) => (item.why === "plan" ? "plan" : item.why === "promote" ? "changes" : item.why === "req" ? "req" : item.why === "accept" ? "deliver" : "");
    const fileRows = (files) => (files || []).map((one) => h("li", null, h("span", {class: "sa-pvpath"}, one.path), " ", h("span", {class: "sa-pvadd"}, "+" + one.added), " ", h("span", {class: "sa-pvdel"}, "−" + one.removed), one.action === "delete" ? h("em", {class: "sa-pvgone"}, " " + t("super.preview.deleted")) : null));
    // `[the one line, the rows, the link text]` of a preview, or null when there is nothing to show.
    function previewParts(kind, result) {
      if (!result || result.ok !== true) return null;
      if (kind === "plan") {
        const lines = result.lines || [];
        return lines.length ? [t("super.preview.plan.sum", {n: result.total || lines.length + (result.more ? "+" : "")}), lines.map((one) => h("li", null, String(one))), "super.preview.plan.open"] : null;
      }
      if (kind === "changes") {
        const files = result.files || [];
        return files.length ? [t(files.length === 1 && !result.more ? "super.preview.changes.one" : "super.preview.changes.sum", {n: files.length + (result.more ? "+" : "")}), fileRows(files), "super.preview.changes.open"] : null;
      }
      if (kind === "req") {
        const sections = (result.sections || []).filter((one) => one && (one.lines || []).length);
        return sections.length ? [t("super.preview.req.sum", {n: result.total || sections.reduce((sum, one) => sum + one.lines.length, 0)}), sections.flatMap((one) => [h("li", {class: "sa-pvh"}, h("b", null, one.title)), ...one.lines.map((line) => h("li", null, String(line)))]), "super.preview.req.open"] : null;
      }
      const files = result.files || [];  // deliver: the whole summary, then the files a promote would change
      if (!files.length && String(result.summary || "").length < 140 && !/\n/.test(String(result.summary || ""))) return null;  // the card shows a short summary whole: nothing to unfold
      return [files.length ? t(files.length === 1 && !result.more ? "super.preview.deliver.one" : "super.preview.deliver.sum", {n: files.length + (result.more ? "+" : "")}) : t("super.preview.deliver.text"),
        [...(result.summary ? [h("li", {class: "sa-pvsum"}, String(result.summary))] : []), ...fileRows(files)], "super.preview.deliver.open"];
    }
    function previewFill(box, item, kind, result) {
      const parts = previewParts(kind, result);
      if (!parts) return;
      const rows = parts[1];
      if (result.more) rows.push(h("li", {class: "sa-pvmore"}, t("super.preview.more")));
      box.replaceChildren(h("summary", null, parts[0]), h("ul", {class: "sa-pvlist"}, ...rows), taskLink(item.task, t(parts[2]) + " ↗", "sa-pvopen"));
      box.hidden = false;
    }
    function previewBox(item) {
      const kind = previewKind(item);
      if (!kind) return null;
      const box = h("details", {class: "sa-pv", hidden: ""});
      if (!PREVIEW_ASKED.has(item.id)) PREVIEW_ASKED.set(item.id, SERVE.call("/api/super/preview", {task: item.task, kind}, 30).then((result) => result || {}, () => ({})));
      PREVIEW_ASKED.get(item.id).then((result) => previewFill(box, item, kind, result));
      return box;
    }
    // What a card says beyond its text (also the pop-out's): the options of a question and where it is answered, the steps a delivery left open.
    function extraNodes(item) {
      const out = [];
      if (item.why === "asking") {
        const options = (questionOf(item) || {}).options || [];
        if (options.length) out.push(h("div", {class: "sa-opts"}, h("span", {class: "sa-optk"}, t("super.ask.opts") + ":"), ...options.map((option) => h("span", {class: "sa-optc"}, String(option)))));
        out.push(h("div", {class: "sa-vs"}, h("i", {"aria-hidden": "true"}, "⇢"), t("super.ask.vs")));
      }
      if (item.why === "accept" && item.deliver && item.deliver.todo_open) out.push(h("div", {class: "sa-todo"}, h("i", {"aria-hidden": "true"}, "⚠"), t("super.accept.todo", {why: String(item.deliver.todo_open)})));
      return out;
    }
    function drawExtra(entry) {
      const sig = JSON.stringify([entry.item.why, entry.item.question, entry.item.deliver && entry.item.deliver.todo_open]);
      if (sig === entry.xsig) return;
      entry.xsig = sig;
      entry.xtra.replaceChildren(...extraNodes(entry.item));
      entry.xtra.hidden = !entry.xtra.children.length;
    }
    function build(item) {
      const why = h("span", {class: "sa-why " + (item.why === "error" ? "err" : item.why === "stuck" ? "stuck" : "")}, whyText(item));
      const waited = h("span", {class: "sa-when"});
      const what = h("div", {class: "sa-what"}, mainOf(item));
      what.title = fullOf(item) || (item.why === "accept" && item.deliver && item.deliver.at ? t("super.accept.at", {at: when(item.deliver.at, 0, 16)}) : "");
      if (callsOf(item).length) what.hidden = true;  // the held calls under it show the command, with its code
      if (prose(item)) what.classList.add("prose");
      if (said(item)) {  // two lines; a click shows the whole words in the task's thread
        what.textContent = sumOf(said(item));
        what.classList.add("sa-sum");
        what.tabIndex = 0;
        what.title = t("super.say.tip");
        what.addEventListener("click", () => showSay(entry.item));
        what.addEventListener("keydown", (event) => { if (isEnter(event)) { event.preventDefault(); showSay(entry.item); } });
      } else if (clampable(item)) {  // the question or command itself is the message: a few lines, the rest on a click
        what.classList.add("ask");
        what.tabIndex = 0;
        const flip = () => what.classList.toggle("open");
        what.addEventListener("click", flip);
        what.addEventListener("keydown", (event) => { if (isEnter(event)) { event.preventDefault(); flip(); } });
      }
      const acts = h("div", {class: "sa-acts"});
      const xtra = h("div", {class: "sa-xtra"});
      const more = !asksPerson(item) && !["error", "stuck", "accept"].includes(item.why) && item.detail && item.detail !== item.title ? h("details", {class: "sa-more"}, h("summary", null, t("super.details")), h("pre", null, item.detail)) : null;
      const node = h("div", {class: "sa-row item" + (item.why === "error" ? " err" : ""), "data-task": item.task, "data-id": item.id},
        h("span", {class: "sa-mini hot"}, PET.face("you", (mates.find((mate) => mate.task === item.task) || {}).kind, 0)),
        h("div", {class: "sa-bub fwd"}, h("div", {class: "sa-fw"}, taskLink(item.task, undefined, undefined, item), why, waited), what, xtra, more, acts));
      const entry = {item, node, acts, waited, what, why, xtra, xsig: "", sig: "", clicked: ""};
      if (SAYS(item)) node.querySelector(".sa-bub").insertBefore(replyBox(entry), acts);
      const preview = previewBox(item);
      if (preview) node.querySelector(".sa-bub").insertBefore(preview, acts);
      drawExtra(entry);
      drawActs(entry);
      drawWaited(entry);
      return entry;
    }
    // A new item goes where the server's order puts it (the most urgent on top), not at the end.
    function queueInsert(node, id) {
      const order = ((data && data.items) || []).map((item) => item.id), mine = order.indexOf(id);
      let before = null;
      if (mine >= 0) for (const one of queueList.children) { if (order.indexOf(one.dataset.id) > mine) { before = one; break; } }
      queueList.insertBefore(node, before);
    }
    function addItem(item) {
      if (known.has(item.id)) return;
      const entry = build(item);
      known.set(item.id, entry);
      queued.delete(item.id);
      queueInsert(entry.node, item.id);
      applyFilter();
    }
    const RECEIPTS = 30;
    // The window of an allow or an answer (chat.js) says what was decided: "Allowed", "Denied", "Answered: DEV only". Only for the item of that kind, and only a minute after.
    function decidedIn(entry) {
      const found = typeof CHAT !== "undefined" && CHAT.decided ? CHAT.decided() : null;
      if (!found || found.task !== entry.item.task || Date.now() - found.at > 60000) return "";
      if (entry.item.why === "confirm" && (found.kind === "allow" || found.kind === "deny")) return t(found.kind === "allow" ? "super.done.allowed" : "super.done.denied");
      if (["question", "asking"].includes(entry.item.why) && found.kind === "answer") return found.text ? t("super.done.answered", {text: found.text}) : t("super.done.answered.none");
      return "";
    }
    function fold(entry, next) {
      const counting = COUNT.get(entry.item.id);
      if (counting) { clearTimeout(counting.timer); COUNT.delete(entry.item.id); }  // a card that left takes its countdown with it
      entry.done = true;
      entry.waited.textContent = "";
      // The task has another wait now (a row has one): it is not settled, it moved on. The person's own click is still the better thing to say.
      const said_ = decidedIn(entry) || entry.clicked;
      const line = said_ ? "\u2713 " + said_ : next ? "\u2192 " + t("super.done.next", {kind: whyText(next)}) : "\u2713 " + t("super.done.elsewhere");
      entry.node.remove();  // the card leaves the queue; its receipt goes to the "Done" row
      doneList.prepend(h("div", {class: "sa-rc", "data-task": entry.item.task}, taskLink(entry.item.task, undefined, undefined, entry.item), h("span", {class: next && !said_ ? "sa-next" : "sa-ok"}, line + " \u00b7 " + stamp())));
      while (doneList.children.length > RECEIPTS) doneList.lastElementChild.remove();
      doneBox.classList.remove("sa-flash"); void doneBox.offsetWidth; doneBox.classList.add("sa-flash");
      applyFilter();
      doneLog.push({task: entry.item.task, text: line, at: stamp()});
      if (doneLog.length > 30) doneLog.shift();
    }
    function reconcile(items) {
      const top0 = queueList.firstElementChild ? queueList.firstElementChild.dataset.id : "";
      const ids = new Set(items.map((item) => item.id));
      for (const [id, entry] of known) if (!entry.done && !ids.has(id)) fold(entry, items.find((item) => item.task === entry.item.task));
      for (const item of items) {
        const entry = known.get(item.id);
        if (!entry || entry.done) continue;
        entry.item = item;
        entry.why.textContent = whyText(item);
        drawExtra(entry);
        const text = said(item) ? sumOf(said(item)) : mainOf(item);
        if (entry.what.textContent !== text) { entry.what.textContent = text; if (!said(item)) entry.what.title = fullOf(item); }
        drawWaited(entry);
        if (entry.sig !== sigOf(entry)) drawActs(entry);
      }
      const fresh = items.filter((item) => !known.has(item.id) && !queued.has(item.id));
      const animate = !first && fresh.length <= 3 && petFree();
      for (const item of fresh) {
        if (animate) { queued.add(item.id); chain = chain.then(() => notice(item)).catch(() => addItem(item)); } else addItem(item);
      }
      const top1 = queueList.firstElementChild ? queueList.firstElementChild.dataset.id : "";
      if (!first && top1 !== top0) queueList.scrollTop = 0;  // a more urgent item came: it is the one in view
      if (first) { queueList.scrollTop = 0; stream.scrollTop = stream.scrollHeight; pill.hidden = true; }  // the most urgent item is the first one of the queue, in view; the chat shows its newest
    }

    // ---------- the pet ----------
    const moodNow = () => (talk ? (talk.state === "asleep" ? "sleep" : talk.state === "tired" ? "tired" : "calm") : vsDown ? "sleep" : "calm");
    const thinkingNow = () => Boolean((talk && talk.state === "thinking") || (localThink && Date.now() - localThink < 90000));
    const petFree = () => Boolean(pet) && shown && !still() && !document.hidden && moodNow() === "calm" && !pet.held();
    function home() {
      const box = hostBox(), size = pet.size();  // its corner: top right, beside the header and the avatars, which leave room for it (super.css)
      return {x: Math.max(0, box.width - size.w - 6), y: 2};
    }
    function standAt(target) {
      // beside the avatar, low in the avatar strip, so the avatar itself stays in sight: to its right, or to its left near the end of the strip
      const box = hostBox(), at = target.getBoundingClientRect(), size = pet.size(), right = at.right - box.left - 6;
      const x = right + size.w <= box.width ? right : at.left - box.left - size.w + 6;
      return {x: clamp(x, 0, Math.max(0, box.width - size.w)), y: Math.max(2, team.getBoundingClientRect().bottom - box.top - size.h), face: x === right ? -1 : 1};
    }
    function visibleMates() {
      const area = team.getBoundingClientRect();
      return [...team.children].filter((node) => node.dataset.task && node.getBoundingClientRect().left >= area.left - 2 && node.getBoundingClientRect().right <= area.right + 2);
    }
    function letter(from, to, fade) {
      const node = h("span", {class: "sa-letter", "aria-hidden": "true"});
      node.style.left = from.x + "px"; node.style.top = from.y + "px";
      sv.append(node);
      requestAnimationFrame(() => requestAnimationFrame(() => { node.style.left = to.x + "px"; node.style.top = to.y + "px"; if (fade) node.style.opacity = ".15"; }));
      setTimeout(() => node.remove(), 800);
    }
    const centre = (node) => { const box = hostBox(), at = node.getBoundingClientRect(); return {x: at.left + at.width / 2 - box.left - 8, y: at.top + at.height / 2 - box.top - 6}; };
    // A new item: the pet walks to the avatar of the task, takes the letter, brings it down to the stream, and the message comes.
    async function notice(item) {
      const mate = mateOf(item.task);
      if (!petFree() || !mate) { addItem(item); return; }
      noticeBusy = true;
      try {
        mate.scrollIntoView({inline: "nearest", block: "nearest"});
        await wait(200);
        pet.look(0, .5);
        pet.say(t("super.pet.way"), 1000);
        const stand = standAt(mate);
        await pet.walkTo(stand.x, stand.y, stand.face);
        if (!petFree()) { addItem(item); return; }
        mate.classList.add("ping");
        const a = centre(mate), p = pet.at(), size = pet.size();
        letter(a, {x: p.x + size.w - 6, y: p.y + size.h * .45}, false);
        pet.wave(900);
        await wait(700);
        mate.classList.remove("ping");
        pet.carry(true);
        pet.say(t("super.pet.for"), 1300);
        const target = home();
        await pet.walkTo(target.x, target.y, 0);
        pet.carry(false);
        const end = hostBox(), list = (queue.hidden ? stream : queueList).getBoundingClientRect(), now = pet.at();
        letter({x: now.x + size.w - 6, y: now.y + size.h * .45}, {x: list.left - end.left + 50, y: list.top - end.top + 30}, true);
        await wait(650);
        addItem(item);
        pet.hop();
      } finally { noticeBusy = false; pet.look(0, 0); }
    }
    function canPatrol() { return petFree() && !noticeBusy && !thinkingNow() && !SERVE.open() && Date.now() > holdUntil; }
    async function patrol(token) {
      while (token === patrolToken) {
        await wait(15000 + Math.random() * 15000);  // it rests in its corner; now and then it flies to a task that waits for you and back
        if (token !== patrolToken) return;
        if (!canPatrol()) continue;
        const list = visibleMates().filter((node) => node.dataset.state === "you" && node.dataset.task !== lastMate);
        if (!list.length) { lastMate = ""; continue; }
        const mate = list[Math.floor(Math.random() * list.length)];
        lastMate = mate.dataset.task;
        const spot = standAt(mate);
        pet.look(spot.face * .6, .3);
        await pet.walkTo(spot.x, spot.y, spot.face);
        if (token !== patrolToken || !canPatrol()) continue;
        pet.say(t("super.pet.waits"), 1300);
        await wait(1600);
        if (token !== patrolToken || noticeBusy || Date.now() <= holdUntil || pet.held()) continue;
        const back = home(); pet.look(0, 0); await pet.walkTo(back.x, back.y, 0);
      }
    }
    // One click: the pet shows the next thing that waits (the first open item, in the order of superview.py) and flies beside its task. A second click soon after opens the task.
    // It is code only: no model, no Credits, in any mood.
    function nextEntry() {
      const open = ((data && data.items) || []).map((item) => known.get(item.id)).filter((entry) => entry && !entry.done);
      return open.find((entry) => !entry.node.hidden) || open[0] || null;
    }
    function petClick() {
      if (noticeBusy) return;
      const shownBefore = pointing && Date.now() < pointing.until ? known.get(pointing.id) : null;
      if (shownBefore && !shownBefore.done) {
        pointing = null;
        pet.wave(900);
        pet.say(t("super.pet.open", {task: shownBefore.item.task}), 1500);
        window.open(taskUrl(shownBefore.item.task), "_blank", "noopener");
        return;
      }
      const entry = nextEntry();
      for (const node of sv.querySelectorAll(".sa-spot")) node.classList.remove("sa-spot");
      if (!entry) {
        pointing = null;
        const mood = moodNow();
        if (mood === "sleep") pet.say(t("super.pet.zz"), 1500);
        else if (mood === "tired") pet.say(t("super.pet.tired"), 1700);
        else { pet.hop(); pet.wave(1100); pet.say(t("super.pet.clear"), 2200); }
        return;
      }
      if (entry.node.hidden) setFilter("");
      queueList.scrollTop = Math.min(queueList.scrollTop, entry.node.offsetTop);  // the queue's own scroll shows it (scrollIntoView below does the rest)
      pointing = {id: entry.item.id, until: Date.now() + 8000};
      holdUntil = pointing.until;
      entry.node.classList.add("sa-spot");
      setTimeout(() => entry.node.classList.remove("sa-spot"), 8000);
      entry.node.scrollIntoView({block: "nearest", behavior: still() ? "auto" : "smooth"});
      pet.say(t("super.pet.next", {task: entry.item.task, why: whyText(entry.item)}), 3200);
      // it flies beside the task's avatar, looks at it, and goes back to its corner when it has said its line
      const mate = mateOf(entry.item.task), token = pointing;
      if (mate && !still()) {
        const spot = standAt(mate);
        pet.walkTo(spot.x, spot.y, spot.face).then(() => { pet.look(spot.face * .7, .4); return wait(3000); }).then(() => {
          if (pointing !== token || noticeBusy || pet.held()) return;
          const back = home(); pet.look(0, 0); pet.walkTo(back.x, back.y, 0);
        });
      }
    }
    // A double click: the agent sums up today, as the button does (about 0.2 Credits).
    function petDouble() {
      pointing = null;
      if (thinkingNow()) { pet.say(t("super.pet.thinking"), 1600); return; }
      if (talkOff()) { pet.say(t("super.pet.cant"), 1800); return; }
      pet.hop();
      pet.say(t("super.pet.summing"), 1500);
      ask({kind: "summary"}, t("super.quick.summary"));
    }
    // Let go over an avatar: only that task's messages ("All" shows all again). Then it flies back to its corner.
    function petDrop(x, y) {
      pet.node.style.pointerEvents = "none";
      const under = document.elementFromPoint(x, y);
      pet.node.style.pointerEvents = "";
      const mate = under && under.closest ? under.closest(".sa-mate") : null;
      if (mate && team.contains(mate)) {
        const task = mate.dataset.task || "";
        setFilter(task);
        pet.hop();
        pet.say(task ? t("super.pet.only", {task}) : t("super.pet.all"), 1800);
      }
      holdUntil = Date.now() + 2500;
      const back = home();
      pet.walkTo(back.x, back.y, 0);
    }
    // Its eyes follow the pointer over the view (one 3D frame per animation frame at most).
    let eyeFrame = 0, eyeAt = null;
    sv.addEventListener("pointermove", (event) => {
      eyeAt = event;
      if (eyeFrame || !pet) return;
      eyeFrame = requestAnimationFrame(() => {
        eyeFrame = 0;
        if (!pet || !shown || noticeBusy || pet.held()) return;
        const at = pet.node.getBoundingClientRect();
        pet.look(clamp((eyeAt.clientX - at.left - at.width / 2) / 260, -1, 1), clamp((eyeAt.clientY - at.top - at.height * .35) / 200, -1, 1));
      });
    });
    sv.addEventListener("pointerleave", () => { if (pet && !noticeBusy && !pet.held()) pet.look(0, 0); });
    function drawOrbit() {
      if (!pet) return;
      const blocked = new Set(((data && data.items) || []).filter((item) => BLOCKS.has(item.why)).map((item) => item.task));
      pet.orbit(mates.map((mate) => (blocked.has(mate.task) || mate.state === "stuck" || mate.state === "error" ? "block" : mate.state === "start" ? "work" : MATE[mate.state] ? mate.state : "idle")));
    }
    function applyMood() {
      if (!pet) return;
      const mood = moodNow(), thinking = thinkingNow() && mood === "calm";
      pet.mood(mood);
      pet.think(thinking);
      if (thinking && !typing) typingBubble(true);
      if (!thinking && typing) typingBubble(false);
      if (mood !== "calm" || thinking) { const back = home(); pet.look(0, 0); pet.walkTo(back.x, back.y, 0); }
    }

    // ---------- the header, the banner, the input ----------
    // `N wait · oldest X · K stuck · M errors`: icons and short marks, the words in the hover. A part that is zero or missing (the server of 1.8.3 has no oldest, stuck or error) is left out.
    const count = (value) => (Number.isFinite(Number(value)) && Number(value) > 0 ? Math.floor(Number(value)) : 0);
    const mark = (cls, icon, text, tip) => h("span", {class: "sa-st " + cls, title: tip}, icon ? h("i", {"aria-hidden": "true"}, icon) : null, text);
    function alertMarks(status) {  // the stuck and error marks (also the pop-out's header)
      const stuck = count(status.stuck), error = count(status.error), list = [];
      if (stuck) list.push(mark("sa-st-stuck", "\u26a0", t("super.head.stuck", {n: stuck}), t("super.head.stuck.tip", {n: stuck})));
      if (error) list.push(mark("sa-st-error", "\u2715", t(error === 1 ? "super.head.error.one" : "super.head.error", {n: error}), t("super.head.error.tip", {n: error})));
      return list;
    }
    function headMarks(status) {
      const waiting = count(status.waiting), oldest = Number(status.oldest_s);
      const list = [waiting ? mark("sa-w", "", t("super.head.wait", {n: waiting}), t("super.line.waiting", {n: waiting})) : mark("sa-st-none", "", t("super.line.none"), t("super.line.none"))];
      if (Number.isFinite(oldest) && oldest > 0 && status.oldest_s !== null) list.push(mark("sa-st-old", "\u25f7", clock(oldest), t("super.head.oldest.tip", {time: clock(oldest)})));
      list.push(...alertMarks(status));
      return list.flatMap((node, at) => (at ? [h("span", {class: "sa-sep", "aria-hidden": "true"}, "\u00b7"), node] : [node]));
    }
    function drawStatus() {
      const status = (data && data.status) || {};
      const mood = moodNow();
      lineEl.replaceChildren();
      if (failed) { lineEl.append(failed); } else if (mood === "sleep") lineEl.append(t("super.line.asleep"));
      else if (mood === "tired") lineEl.append(t("super.line.tired"));
      else {
        lineEl.append(...headMarks(status));
        const n = status.watching || 0;
        lineEl.append(h("span", {class: "sa-tail"}, h("span", {class: "sa-sep", "aria-hidden": "true"}, "\u00b7"), t(n === 1 ? "super.line.watching.one" : "super.line.watching", {n}) + (status.as_of ? " \u00b7 " + t("super.line.updated", {time: when(status.as_of, 11, 16)}) : "")));
      }
      lineEl.title = lineEl.textContent;
      const cost = costNow();
      costEl.hidden = !cost;
      costEl.replaceChildren(...(cost ? [PET.battery(cost)] : []));
    }
    function drawBanner() {
      const mood = moodNow();
      const kind = mood === "sleep" ? "sleep" : mood === "tired" ? "tired" : !talk ? "none" : "";
      const sig = kind + (talk ? "|" + talk.spent + "|" + talk.limit : "");
      if (sig === bannerSig) return;
      bannerSig = sig;
      banner.hidden = !kind;
      if (!kind) { banner.replaceChildren(); return; }
      const text = kind === "sleep" ? t("super.banner.asleep") : kind === "tired" ? t("super.banner.tired", {spent: amount(talk.spent || 0), limit: amount(talk.limit || 0)}) : t("super.banner.none");
      banner.replaceChildren(h("span", null, text));
    }
    // Today's Credits of the super agent, for its battery: what is left, and the numbers for the tooltip. Null when it has no limit.
    function costNow() {
      if (!talk || !talk.limit) return null;
      const spent = talk.spent || 0, left = Math.max(0, talk.limit - spent), numbers = {spent: amount(spent), limit: amount(talk.limit), left: amount(left)};
      return {left: left / talk.limit, full: moodNow() === "tired", tip: t("super.cost.tip", numbers), label: t("super.cost.label", numbers)};
    }
    const talkOff = () => (!talk ? "none" : moodNow() === "sleep" ? "asleep" : moodNow() === "tired" ? "limit" : "");
    // The placeholder of the box; a closed task with checks above 0 gets the words of a note for the checks (1.8.21).
    function drawHolder(off, routing) {
      if (off === undefined) { routing = Boolean(filter); off = routing ? "" : talkOff(); }
      const after = routing && isClosed(filter) && direct.checks() > 0;
      field.placeholder = off ? t(OFF[off]) : routing ? t(isClosed(filter) ? (after ? "super.direct.after.ph" : "super.direct.reopen.ph") : "super.direct.ph", {task: filter}) : t("super.input.ph");
      field.title = field.placeholder;
    }
    let sendOff = false, sendCant = false, toSig = "", reopening = "";  // sendCant: the target is a closed task that cannot be reopened (and no checks after the close are asked): Send waits
    function drawInput() {
      const routing = Boolean(filter);  // one task's avatar is on: the input asks that task, whatever the super chat's state
      const off = routing ? "" : talkOff(), blocked = routing ? false : Boolean(off) || thinkingNow(), quickOff = Boolean(talkOff()) || thinkingNow();
      field.disabled = Boolean(off);
      sendOff = blocked;
      send.disabled = blocked || sendCant;
      drawHolder(off, routing);
      box.classList.toggle("off", Boolean(off));
      quick.hidden = Boolean(talkOff());
      if (!quick.children.length) {
        for (const [key, body] of [["super.quick.next", () => ({text: t("super.quick.next")})], ["super.quick.summary", () => ({kind: "summary"})]]) {
          const button = h("button", {type: "button"}, t(key));
          button.addEventListener("click", () => ask(body(), t(key)));
          quick.append(button);
        }
      }
      for (const button of quick.children) button.disabled = quickOff;
      routeComplete();
      drawDirect();
    }
    // The direct message: the counter, the options menu and the length limit follow the target of the words (the avatar, or "@name" in All).
    function drawDirect() {
      const typed = field.value.trim(), target = routeTarget(typed), on = Boolean(target) && !talkOff() || Boolean(filter);
      direct.button.hidden = !on;
      if (newTask) newTask.hidden = on;  // the room is for the words and the options
      counter.hidden = !on;
      to.hidden = !on;
      direct.tray.classList.toggle("sa-off", !on);
      if (!on) { field.maxLength = 2000; sendCant = false; send.disabled = sendOff; return; }
      const name = target ? target.task : filter;
      const shut = isClosed(name), info = shut ? reopenOf(name) : null, n = shut ? direct.checks() : null;
      const after = shut && n !== null && n > 0;  // checks after the close: the task stays closed (1.8.20)
      sendCant = shut && !after && Boolean(info) && info.mode === "refused";
      send.disabled = sendOff || sendCant;
      drawMark(name, shut, info, after, n);
      direct.bind(name);
      const used = target ? target.text.length : 0;
      field.maxLength = SUPERDIRECT.MAX + (target ? typed.length - target.text.length : 0);
      counter.textContent = t("super.direct.count", {n: used, max: SUPERDIRECT.MAX});
      counter.classList.toggle("over", used >= SUPERDIRECT.MAX);
    }
    // The mark above the input (1.8.21): "To: task"; for a closed task "Reopen: task · what the reopen will be" with a Reopen only link (no chat, no message), a red "Cannot reopen" with the reason (and Open Recover when a promote wrote part), or "Checks after the close".
    function drawMark(name, shut, info, after, n) {
      const cant = shut && !after && Boolean(info) && info.mode === "refused", key = modeKey(info);
      const sig = JSON.stringify([name, shut, after, n, info, reopening === name]);
      if (sig === toSig) return;
      toSig = sig;
      to.className = "sa-to" + (shut ? " sa-reopen " + (after ? "new" : key === "same" ? "same" : cant ? "no" : "new") : "");
      if (!shut) { to.textContent = t("super.direct.to", {task: name}); to.title = t("super.direct.to.tip"); return; }
      const rest = after ? t(n === 1 ? "super.reopen.after.one" : "super.reopen.after.many", {n}) : modeLine(info);
      const nodes = [h("b", {class: "sa-to-main"}, t(after ? "super.reopen.after.mark" : cant ? "super.reopen.cannot" : "super.direct.reopen", {task: name})), ...(rest ? [h("span", {class: "sa-to-rest"}, " \u00b7 " + rest)] : [])];
      if (cant && key === "partial") { const link = taskLink(name, t("super.reopen.recover"), "sa-to-link"); link.title = t("super.reopen.recover.tip"); nodes.push(" ", link); }
      else if (!after && !cant) {
        const only = h("button", {type: "button", class: "sa-to-link", title: t("super.reopen.only.tip")}, t("super.reopen.only"));
        only.disabled = reopening === name;
        only.addEventListener("click", () => reopenOnly(name));
        nodes.push(" ", only);
      }
      to.title = after ? t("super.direct.checks.after.hint") : cant ? rest : t("super.direct.reopen.tip");
      to.replaceChildren(...nodes);
    }
    // The person opens a closed task again with no chat (the board's `reopen` action, paired page only): the same call for the mark and the card. {ok, text, new_round} or {ok: false, error}.
    async function reopenCall(task) {
      try {
        const info = reopenOf(task);  // what the mark and the card said: a task in another state now is refused, and the person looks again
        const answer = await SERVE.post("/api/act", {action: "reopen", task, step: "act", ...(info ? {seen: {mode: info.mode, round: info.round}} : {})});
        const found = (answer && (answer.result || answer)) || {};
        poll().then(schedule, schedule);
        return {ok: true, new_round: Boolean(found.new_round), text: found.new_round ? t("super.reopen.done.new", {task, n: found.round}) : t("super.reopen.done.same", {task})};
      } catch (error) { return {ok: false, error}; }
    }
    async function reopenOnly(task) {
      if (reopening) return;
      reopening = task;
      drawDirect();
      const result = await reopenCall(task);
      reopening = "";
      if (result.ok) addSys(result.text, task).classList.add("sa-dl");
      else addSys(actBad(result.error), task, true).classList.add("sa-dl");
      toSig = "";
      drawDirect();
      toBottom();
    }
    async function ask(body, text) {
      if (talkOff() || thinkingNow()) return;
      const typed = text || field.value.trim();
      if (!typed) return;
      if (!text) field.value = "";
      if (filter) setFilter("");
      const mine = body && body.kind === "summary" ? SUMMARY_ASKED : typed;
      pendingYou.push(mine);
      addYou(typed, new Date().toISOString());
      localThink = Date.now();
      applyMood(); drawInput(); schedule(); emit();
      let result;
      try { result = await SERVE.call("/api/super/ask", body || {text: typed}, 30); } catch (error) { result = (error && error.data && typeof error.data === "object" && error.data.why) ? error.data : {ok: false, why: "none"}; }
      if (result && result.ok === false) {
        localThink = 0;
        const at = pendingYou.indexOf(mine); if (at >= 0) pendingYou.splice(at, 1);
        addSys(t(OFF[result.why] || OFF.none));
        applyMood(); drawInput();
      }
      poll();
    }
    // ---------- asking one task (1.8.2): the filter, or "@name" in the first words ----------
    const ROUTE_ASKS = new Map();  // ask id -> the row of an ask: {ask, sig, open, node, line, answer, more}
    const ROUTE_WHY = {unknown: "super.route.why.unknown", paused: "super.route.why.paused", nochat: "super.route.why.nochat", asleep: "super.route.why.asleep", asking: "super.route.why.asking", empty: "super.route.why.empty",
      long: "super.route.why.long", error: "super.route.why.error", lost: "super.route.why.lost", cancelled: "super.route.why.cancelled", unpaired: "super.route.why.unpaired"};  // written out: a search for a key finds its place
    const routeKey = (why) => ROUTE_WHY[why] || "super.route.why.other";
    const routeEstimate = (text) => String(text).split("\n").reduce((sum, line) => sum + Math.max(1, Math.ceil(line.length / 60)), 0);  // the lines an answer takes, about
    let routeBusy = false, routePick = -1, routeNames = [];
    const routeNamesAll = () => [...mates.map((mate) => mate.task), ...closedOnly().map((one) => one.task)];  // the open tasks, then the closed ones (a message to one of those reopens it)
    // Where the typed words go: the task of the filter, or the task named after "@" (the name ends at a space or a mark, not inside a longer name), else the super chat (null).
    function routeTarget(typed) {
      if (filter) return {task: filter, text: typed};
      if (!typed.startsWith("@")) return null;
      for (const name of routeNamesAll().sort((a, b) => b.length - a.length)) {
        if (!typed.startsWith("@" + name) || !/^($|[\s,:;])/.test(typed.slice(name.length + 1))) continue;  // the name ends at a space, the end or , : ; (not inside a longer name such as job.v2)
        return {task: name, text: typed.slice(name.length + 1).replace(/^[\s,:;]+/, "").trim()};
      }
      return null;
    }
    // The refusal of a direct message as the nodes of one line: the words and, when the task is paused, a Resume button for that one task (the board's own `resume`, as its card or row has). `after` says what to do once it ran.
    function refusalNodes(task, why, error, after) {
      const out = [SUPERDIRECT.refusal(task, why, error)];
      if (why === "paused") {
        const button = actionButton(rowFor(task), {action: "resume"}, "sa-resume");
        button.addEventListener("click", () => {
          let tries = 0;
          const look = setInterval(() => {  // the board draws the new state after its own call: the line tells when the task is back
            if (++tries > 14 || !button.isConnected) { clearInterval(look); return; }
            const row = (rowsOf() || []).find((one) => one.name === task || one.task === task);
            if (row && !row.paused_since) { clearInterval(look); if (after) after(t("super.direct.resumed", {task})); }
          }, 500);
        });
        out.push(button);
      }
      return out;
    }
    // One direct message to one task (the input's, the card's and the pop-out's): {ok, how, text} with the line to show, or {ok: false, why, text}. Said in the task's thread, so the filter never hides it.
    // Not quiet: the person's words show as their own bubble (after the send, or at once when it may make a new chat: that takes long), then one line under it with the result. A refusal shows no bubble.
    async function directSend(task, text, options, quiet, empty) {  // `empty`: a closed task may be reopened, or checked, with no words (1.8.21)
      const slow = !quiet && (Boolean(options && options.new_chat) || chatGone(rowFor(task)) || isClosed(task));
      let bubble = null, line = null;
      if (slow) {
        bubble = text ? addYou(text, new Date().toISOString(), task) : null;
        line = addSys(t(isClosed(task) ? "super.direct.reopening" : "super.direct.making", {task}), task, false, String(text).slice(0, 300));
        line.classList.add("sa-dl", "sa-pend");
      }
      const info = isClosed(task) ? reopenOf(task) : null;  // what the mark said (1.8.21 review 1): another state now is refused before a chat is made
      const result = await SUPERDIRECT.send(task, text, info ? {...(options || {}), seen: {mode: info.mode, round: info.round}} : options, empty || isClosed(task));
      if (!quiet) {
        const ok = result.ok;
        const nodes = ok ? [SUPERDIRECT.receipt(result.how, task, result) + (result.how === "said" ? " " + t("super.direct.skipped") : "")] : refusalNodes(task, result.why, result.error, (words) => { if (line && line.isConnected) { line.classList.remove("bad"); line.replaceChildren(words); } });
        if (ok && !bubble && text) bubble = addYou(text, new Date().toISOString(), task);
        if (!ok && bubble) { dropYou(bubble); bubble = null; }
        if (line) { line.className = "sa-sys sa-dl" + (ok ? "" : " bad"); line.replaceChildren(...nodes); line.title = String(text).slice(0, 300); }
        else line = addSys(nodes, task, !ok, String(text).slice(0, 300));
        line.classList.add("sa-dl");
        if (bubble || !ok) toBottom();
      }
      if (result.ok) { SERVE.done(); poll().then(schedule, schedule); }  // 1.8.50: the board's rows too (the bridge draws from them): a task just handed shows at once
      return result;
    }
    async function submit_direct(target, typed) {
      routeBusy = true;
      const options = direct.values();
      field.value = "";
      field.style.height = "auto";
      routeComplete();
      drawDirect();
      const result = await directSend(target.task, target.text, options);
      routeBusy = false;
      if (result.ok) { direct.clear(); drawInput(); return; }
      if (!field.value) field.value = typed;  // refused: the words come back into the input
      field.dispatchEvent(new Event("input"));
    }
    function submit(button) {
      const typed = field.value.trim();
      if (routeBusy) return;
      const bare = Boolean(button) && !typed && Boolean(filter) && isClosed(filter);  // the Send button with an empty box on a closed task: reopen it and hand it to the agent (1.8.21; Enter never does)
      if (!typed && !bare) return;
      const target = bare ? {task: filter, text: ""} : routeTarget(typed);
      if (target && sendCant) return;  // a closed task that cannot be reopened
      if (target && direct.reading()) return;  // a file is still being read
      if (target) { submit_direct(target, typed); return; }
      const named = filter ? null : /^@([^\s,:;]+)/.exec(typed);  // "@name" that is no open task: never a question to the super agent (it costs Credits); the words stay in the box
      if (named) { addSys(t("super.route.noname", {name: named[1]}), "", true, typed.slice(0, 300)).classList.add("sa-dl"); return; }
      ask(null);
    }
    // The ask rows: one per ask, drawn again in place when its state changes (never added twice).
    function routeBuild(item) {
      const kind = (mates.find((mate) => mate.task === item.task) || {}).kind;
      const line = h("div", {class: "sa-askline"}), answer = h("div", {class: "sa-text sa-ans"}), more = h("button", {type: "button", class: "sa-askmore", hidden: ""}, t("super.more"));
      const entry = {ask: item, sig: "", open: false, line, answer, more};
      more.addEventListener("click", () => { entry.open = true; routeDraw(entry, entry.ask); });
      entry.node = h("div", {class: "sa-row askrow", "data-task": item.task, "data-ask": item.id},
        h("span", {class: "sa-mini hot"}, PET.face("you", kind, 0)),
        h("div", {class: "sa-bub fwd"}, h("div", {class: "sa-fw"}, taskLink(item.task, undefined, undefined, mates.find((mate) => mate.task === item.task)), item.at ? h("span", {class: "sa-when"}, when(item.at, 11, 16)) : null),
          h("div", {class: "sa-text sa-q"}, item.text), line, answer, more));
      return entry;
    }
    function routeDraw(entry, item) {
      entry.ask = item;
      const sig = JSON.stringify([item.state, item.answer, item.why, item.end, entry.open]);
      if (sig === entry.sig) return;
      entry.sig = sig;
      const failedAsk = item.state === "failed", partial = item.state === "answered" || failedAsk ? String(item.answer || "") : "";
      entry.node.classList.toggle("fail", failedAsk);
      entry.line.className = "sa-askline" + (failedAsk ? " bad" : "");
      entry.line.textContent = item.state === "sent" ? t("super.route.waiting") : item.state === "queued" ? t("super.route.queued") : failedAsk ? t(routeKey(item.why || item.end)) : "";
      entry.line.hidden = !entry.line.textContent;
      entry.answer.hidden = !partial;
      entry.answer.replaceChildren(...(partial ? rich(partial) : []));
      const long = routeEstimate(partial) > 12;
      entry.answer.classList.toggle("sa-ansclip", long && !entry.open);
      entry.more.hidden = !(long && !entry.open);
    }
    // The messages and the asks in one time order: an ask lands among the messages by its time.
    // 1.8.43: what the tasks said when they stopped (`says`) lands the same way, as a line of the task's thread (sayBuild).
    function routeMerge(messages, asks, says) {
      const freshAsks = (asks || []).filter((item) => item && item.id && !ROUTE_ASKS.has(item.id)).map((item) => ({item, say: false}));
      const freshSays = (says || []).filter((item) => item && item.id && !SAYS_SHOWN.has(item.id)).map((item) => ({item, say: true}));
      const fresh = [...freshAsks, ...freshSays].sort((a, b) => String(a.item.at).localeCompare(String(b.item.at)));
      for (const {item, say} of fresh) {
        mergeTalk((messages || []).filter((message) => message && !seenTalk.has(message.id) && String(message.at || "") <= String(item.at || "")));
        let node;
        if (say) { const entry = sayBuild(item); SAYS_SHOWN.set(item.id, entry); node = entry.node; }
        else { const entry = routeBuild(item); ROUTE_ASKS.set(item.id, entry); node = entry.node; }
        chatRows.push(node);
        add(node, !say);  // a task's words do not pull the chat down while the person reads higher up (the pill says there is more)
        foldChat();
      }
      mergeTalk(messages || []);
      for (const item of asks || []) { const entry = item && ROUTE_ASKS.get(item.id); if (entry) routeDraw(entry, item); }
      for (const item of says || []) { const entry = item && SAYS_SHOWN.get(item.id); if (entry && entry.say.text !== item.text) sayText(entry, item); }  // 1.8.47: the words of a wait can be caught up later
      for (const entry of SAYS_SHOWN.values()) sayDraw(entry);
    }
    // A task's last words in its thread: its avatar, its name, what it waited for and when, and the words (rich). While its wait is open the line says it waits for you;
    // once the wait is gone it turns grey and says how it ended ("answered" for a stop, "done" for the rest).
    const SAYS_SHOWN = new Map();  // wait id -> {say, node, tag, waiting}
    const SAY_FOLD = 20;
    function sayBuild(item) {
      const kind = (mates.find((mate) => mate.task === item.task) || {}).kind;
      const tag = h("span", {class: "sa-ttag"});
      const node = h("div", {class: "sa-row sayrow", "data-task": item.task, "data-say": item.id},
        h("span", {class: "sa-mini hot"}, PET.face("you", kind, 0)),
        h("div", {class: "sa-bub fwd"}, h("div", {class: "sa-fw"}, taskLink(item.task, undefined, undefined, mates.find((mate) => mate.task === item.task)), tag, item.at ? h("span", {class: "sa-when", title: when(item.at, 0, 19)}, when(item.at, 11, 16)) : null),
          h("div", {class: "sa-text"}, ...rich(item.text))));
      const entry = {say: item, node, tag, waiting: null};
      sayFold(entry);
      return entry;
    }
    function sayFold(entry) {
      const old = entry.node.querySelector(".sa-askmore"), body = entry.node.querySelector(".sa-text");
      if (old) old.remove();
      body.classList.remove("sa-sayclip");
      if (routeEstimate(entry.say.text) > SAY_FOLD) {  // a long message folds after SAY_FOLD lines; "Show more" opens it in place
        const more = h("button", {type: "button", class: "sa-askmore"}, t("super.more"));
        body.classList.add("sa-sayclip");
        more.addEventListener("click", () => { body.classList.remove("sa-sayclip"); more.remove(); });
        entry.node.querySelector(".sa-bub").append(more);
      }
    }
    function sayText(entry, item) {
      entry.say = item;
      entry.node.querySelector(".sa-text").replaceChildren(...rich(item.text));
      sayFold(entry);
    }
    function sayDraw(entry) {
      const waiting = Boolean(data && (data.items || []).some((item) => item.id === entry.say.id));
      if (waiting === entry.waiting) return;
      entry.waiting = waiting;
      entry.node.classList.toggle("settled", !waiting);
      const what = whyText({why: entry.say.why});
      entry.tag.textContent = waiting ? t("super.say.waits", {what}) : t(entry.say.why === "stopped" ? "super.say.answered" : "super.say.done", {what});
    }
    // "Reply in chat" (or a click on the card's two lines): the task's thread, its line in view for a moment, and the input ready for the task.
    function showSay(item) {
      setFold(false, false);
      stream.dispatchEvent(new CustomEvent("sa-showchat", {bubbles: true}));  // the Workbench closes a panel that covers the chat (Tall: the Queue sheet)
      if (filter !== item.task) setFilter(item.task);
      const entry = SAYS_SHOWN.get(item.id);
      if (entry) {
        entry.node.classList.remove("sa-flash"); void entry.node.offsetWidth; entry.node.classList.add("sa-flash");
        entry.node.scrollIntoView({block: "nearest"});
        const bub = entry.node.querySelector(".sa-bub");
        if (bub && bub.offsetHeight > stream.clientHeight) entry.node.scrollIntoView({block: "start"});
      }
      if (item.why === "stopped") field.focus();
    }
    // "@" completion: the open task names, filtered as the person types; ArrowUp/ArrowDown move, Enter or Tab pick, Esc closes, a click picks.
    const label = (task) => String((mates.find((mate) => mate.task === task) || closedOnly().find((one) => one.task === task) || {}).label || (closedOnly().find((one) => one.task === task) || {}).title || "");
    function routeComplete() {
      const word = /^@([^\s]*)$/.exec(field.value);
      const fits = (name, extra) => (name + " " + (extra || "")).toLowerCase().includes(word[1].toLowerCase());
      routeNames = !filter && word ? [...mates.filter((mate) => fits(mate.task, mate.label)).map((mate) => mate.task), ...closedOnly().filter((one) => fits(one.task, closedTitle(one))).map((one) => one.task)].slice(0, 8) : [];  // open tasks first, then the closed ones
      if (routePick >= routeNames.length) routePick = routeNames.length - 1;
      if (routePick < 0 && routeNames.length) routePick = 0;
      complete.hidden = !routeNames.length;
      complete.replaceChildren(...routeNames.map((name, at) => h("div", {class: "sa-opt" + (at === routePick ? " on" : ""), role: "option", "aria-selected": String(at === routePick), "data-task": name}, ...[name, ...(label(name) ? [h("span", {class: "sa-optl"}, " \u00b7 " + label(name))] : []), ...(isClosed(name) ? [h("span", {class: "sa-optx", title: t("super.direct.reopen.tip")}, t("super.closed.mark"))] : [])])));
    }
    function routeChoose(name) {
      field.value = "@" + name + " ";
      routePick = -1;
      routeComplete();
      drawDirect();
      field.focus();
    }
    complete.addEventListener("mousedown", (event) => event.preventDefault());
    complete.addEventListener("click", (event) => { const opt = event.target.closest(".sa-opt"); if (opt) routeChoose(opt.dataset.task); });
    field.addEventListener("keydown", (event) => {  // before the Enter-sends handler below: it stops that one while the list is open
      if (complete.hidden) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); routePick = (routePick + (event.key === "ArrowDown" ? 1 : -1) + routeNames.length) % routeNames.length; routeComplete(); }
      else if (isEnter(event) || event.key === "Tab") { event.preventDefault(); event.stopImmediatePropagation(); routeChoose(routeNames[Math.max(0, routePick)]); }
      else if (event.key === "Escape") { event.preventDefault(); routePick = -1; routeNames = []; complete.hidden = true; }
    });
    field.addEventListener("input", () => { routePick = -1; routeComplete(); drawDirect(); });
    send.addEventListener("click", () => submit(true));
    field.addEventListener("keydown", (event) => { if (isEnter(event) && !event.shiftKey) { event.preventDefault(); submit(); } });
    field.addEventListener("input", () => { setFold(false, false); field.style.height = "auto"; field.style.height = Math.min(120, field.scrollHeight) + "px"; });
    if (newTask) newTask.addEventListener("click", () => { const text = field.value.trim(); CHAT.create(text ? {text} : undefined); field.value = ""; });  // the text moved into the new-task dialog

    // ---------- asking the server ----------
    function apply(result, spoken) {
      failed = "";
      if (shown) fit();  // the board's banner above the view may have gone (hidden by the person): the view takes the room it left
      data = result;
      talk = spoken && typeof spoken === "object" && spoken.state ? spoken : null;
      drawTeam(result.mates || [], result.making, Array.isArray(result.closed) ? result.closed : [], result.closed_more);
      if (talk && talk.state !== "thinking" && localThink && Date.now() - localThink > 4000) localThink = 0;  // the server is done (a message, or nothing to say)
      routeMerge(talk ? talk.messages : [], talk ? talk.asks : [], talk ? talk.says : []);
      reconcile(result.items || []);
      drawOrbit();
      applyFilter();
      drawStatus(); drawBanner(); drawInput(); applyMood();
      first = false;
      emit();
      morning();
    }
    // The first open of the day: the agent sums up what waits, once a day in this browser, when it is free and nobody talked to it yet today (about 0.2 Credits).
    function morning() {
      if (!shown || !talk || talk.state !== "idle" || (talk.messages || []).length || !((data && data.items) || []).length) return;
      const today = new Date().toISOString().slice(0, 10);
      try { if (localStorage.getItem("super.morning") === today) return; localStorage.setItem("super.morning", today); } catch (error) { return; }  // no storage: no automatic call, the button stays
      ask({kind: "summary"}, t("super.quick.summary"));
    }
    function poll() {
      if (!live() || SERVE.busy()) return Promise.resolve();
      const spoken = talkGone && Date.now() - talkGone < 60000 ? Promise.resolve(null)
        : SERVE.ready.then(() => SERVE.call("/api/super/talk", {}, 30)).then((answer) => { talkGone = 0; return answer; }, () => { talkGone = Date.now(); return null; });
      return Promise.all([SERVE.post("/api/super", {}), spoken]).then(([result, answer]) => { if (live()) apply(result, answer); }, (error) => {
        if (!live()) return;
        failed = error && error.offline ? t("board.serve.stopped") : t("super.unavailable");
        drawStatus();
        emit();
      });
    }
    function schedule() {
      clearTimeout(pollTimer);
      if (!live()) return;
      const quick = thinkingNow() || Date.now() < pulseQuick;
      const delay = document.hidden && !watchers ? 30000 : quick ? (thinkingNow() ? 1500 : PULSE_POLL_MS) : Math.max(3, Number(DATA.serve && DATA.serve.refresh) || 5) * 1000;
      pollTimer = setTimeout(() => poll().then(schedule, schedule), delay);
      pulseSchedule();
    }
    // 1.8.47: a light look at the chats between the full polls (`/api/super/pulse`: from the server's memory, no file read). When a chat starts or ends a turn, the full poll runs at once,
    // then every PULSE_POLL_MS for PULSE_QUICK_MS: the Stop hook marks the wait only after its own checks (3-13 s on a slow computer). The 5 s poll stays as it was.
    function pulseSchedule() {
      clearTimeout(pulseTimer);
      if (!live() || document.hidden || Date.now() < pulseOff) return;
      pulseTimer = setTimeout(pulseLook, PULSE_MS);
    }
    function pulseLook() {
      if (!live() || document.hidden || SERVE.busy()) { pulseSchedule(); return; }
      SERVE.post("/api/super/pulse", {}).then((answer) => {
        const mark = String((answer && answer.pulse) || "");
        const moved = Boolean(pulseLast) && mark !== pulseLast;
        pulseLast = mark;
        if (moved) { pulseQuick = Date.now() + PULSE_QUICK_MS; poll().then(schedule, schedule); }
        else pulseSchedule();
      }, () => { pulseOff = Date.now() + 60000; });  // an older board has no pulse: the 5 s poll alone, look again in a minute
    }
    document.addEventListener("visibilitychange", () => { if (live() && !document.hidden) poll().then(schedule, schedule); });
    addEventListener("resize", () => {
      if (!shown) return;
      fit();
      if (pet && !noticeBusy) { const back = home(); pet.place(back.x, back.y); }
    });

    function show() {
      shown = true;
      sv.hidden = false;
      fit();
      if (!pet) {
        pet = (options.makePet || PET.create)(sv);  // 1.8.25: the workbench gives a stand-in that does nothing (the bridge takes the pet's place)
        pet.node.title = t("super.pet.tip");
        pet.onClick(petClick); pet.onDouble(petDouble); pet.onDrop(petDrop);
        drawOrbit();
      }
      pet.run(true);
      const back = home();
      pet.place(back.x, back.y);
      applyFilter();
      applyMood();
      patrolToken++;
      patrol(patrolToken);
      poll().then(() => { const spot = home(); if (!noticeBusy) pet.place(spot.x, spot.y); schedule(); }, schedule);
    }
    function hide() {
      shown = false;
      mateMenuClose(false);
      sv.hidden = true;
      if (!watchers) { clearTimeout(pollTimer); clearTimeout(pulseTimer); }
      patrolToken++;
      if (pet) pet.run(false);
    }
    // What the pop-out window reads (companion.js): the data this view already holds, and a call when it changes. It never asks the server itself.
    function snapshot() {
      const status = (data && data.status) || {};
      return {items: (data && data.items) || [], done: doneLog.slice(), working: mates.filter((mate) => mate.state === "work" || mate.state === "start").length, making: making.slice(), closed: closedOnly(), watching: status.watching || 0, stuck: count(status.stuck), error: count(status.error), failed,
        mood: moodNow(), thinking: thinkingNow(), off: talkOff(), cost: costNow(),
        quiet: quietCount(), mates, loaded: data !== null};
    }
    // The tasks that are neither at work nor waiting nor in error: the idle ones and the paused ones, each once (the grey count of the pop-out).
    function quietCount() {
      const names = new Set(mates.filter((mate) => mate.state === "idle").map((mate) => mate.task));
      for (const row of rowsOf() || []) if (row.status === "open" && row.paused_since) names.add(row.name || row.task);
      return names.size;
    }
    // The chat as the pop-out draws it: the messages of the talk (the person's and the agent's), what was typed and the server has not listed yet, and the asks to one task, in time order.
    function chatOf() {
      const out = [];
      for (const message of (talk && talk.messages) || []) {
        if (!message || !message.id) continue;
        out.push({id: "m" + message.id, role: message.role === "you" ? "you" : "agent", text: message.role === "you" && message.kind === "summary" ? t("super.quick.summary") : String(message.text || ""), at: String(message.at || "")});
      }
      for (const one of (talk && talk.asks) || []) {
        if (!one || !one.id) continue;
        out.push({id: "a" + one.id, role: "ask", task: one.task, text: String(one.text || ""), answer: String(one.answer || ""), state: one.state, at: String(one.at || ""),
          line: one.state === "sent" ? t("super.route.waiting") : one.state === "queued" ? t("super.route.queued") : one.state === "failed" ? t(routeKey(one.why || one.end)) : ""});
      }
      out.sort((a, b) => a.at.localeCompare(b.at));
      pendingYou.forEach((text, at) => out.push({id: "p" + at + text, role: "you", text: text === SUMMARY_ASKED ? t("super.quick.summary") : text, at: "", pending: true}));
      return out;
    }
    // What the person types in the pop-out goes the way the view's own input sends it: "@task words" is a direct message (directSend), any other words ask the super agent (ask). {ok, text}: the line to show.
    async function popSend(text) {
      const typed = String(text || "").trim();
      if (!typed) return {ok: false, text: ""};
      if (typed.startsWith("@")) {
        const saved = filter;
        filter = "";  // the words name their task: the avatar the view has picked is not the target here
        const target = routeTarget(typed);
        filter = saved;
        if (!target) { const named = /^@([^\s,:;]+)/.exec(typed); return {ok: false, text: t("super.route.noname", {name: named ? named[1] : ""})}; }
        const result = await directSend(target.task, target.text, SUPERDIRECT.valuesFor(target.task), false);
        return {ok: result.ok, text: result.ok ? SUPERDIRECT.receipt(result.how, target.task, result) : SUPERDIRECT.refusal(target.task, result.why, result.error)};
      }
      ask(null, typed);
      return {ok: true, text: ""};
    }
    function watch(on) {
      watchers = Math.max(0, watchers + (on ? 1 : -1));
      if (on && watchers === 1 && !shown) poll().then(schedule, schedule);
      if (!watchers && !shown) { clearTimeout(pollTimer); clearTimeout(pulseTimer); }
    }
    // The pop-out's calls (companion.js): the same pieces as the view, never a copy of them.
    const replyFor = (item) => { const entry = item && (item.why === "stopped" || SAYS(item)) ? known.get(item.id) : null; return entry && !entry.done ? replyBox(entry) : null; };
    const previewFor = (item) => previewBox(item);
    const pop = {replyFor, previewFor, snapshot, buttonsFor, sigFor, mainOf, fullOf, asksPerson, why: whyText, extraFor: extraNodes, hasCalls: (item) => callsOf(item).length > 0, prose,
      taskLink, chat: chatOf, rich: (text) => rich(text), send: popSend, front: (task) => { if (options.front) options.front(task || ""); }, watch, subscribe: (fn) => { listeners.add(fn); return () => listeners.delete(fn); }};
    if (popUp) {
      const reason = COMPANION.unsupported();
      popUp.disabled = Boolean(reason);
      popUp.title = reason || t("super.pop.open");
      popUp.setAttribute("aria-label", popUp.title);
      popUp.addEventListener("click", () => COMPANION.open(pop));
    }
    return {node: sv, show, hide, setVscode: (status) => { vsDown = Boolean(status) && !status.ready; if (shown) { drawStatus(); drawBanner(); drawInput(); applyMood(); } emit(); }};
  }

  return {create, waiting};
})();
