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
  const MATE = {you: "super.mate.you", work: "super.mate.work", idle: "super.mate.idle", stuck: "super.mate.stuck", error: "super.mate.error"};
  const BLOCKS = new Set(["confirm", "question", "asking", "outbox", "autorun"]);  // superview.py: these stop running work; their dot on the pet is red
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
  const taskLink = (task, text, cls) => h("a", {class: cls || "sa-task", href: taskUrl(task), target: "_blank", rel: "noopener", title: cls ? t("super.open.tip") : task}, text === undefined ? task : text);

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
    const box = h("div", {class: "sa-box"}, field, newTask, send);
    const complete = h("div", {class: "sa-comp", role: "listbox", hidden: "", "aria-label": t("super.route.pick")});
    // The pop-out (companion.js): a small window that stays on top of every other window. Only where the browser can open one (Document Picture-in-Picture: Chrome, Edge).
    const popUp = typeof COMPANION !== "undefined" ? h("button", {type: "button", class: "sa-pop"}, "⇱") : null;
    const streamWrap = h("div", {class: "sa-streamwrap"}, stream, pill);
    // The queue (1.8.4): the open items, pinned above the chat; the receipts of the settled ones fold into "Done (n)" at its foot.
    const queueList = h("div", {class: "sa-qlist", role: "list", "aria-label": t("super.queue")});
    const doneList = h("div", {class: "sa-qdlist"});
    const doneHead = h("summary", {title: t("super.done.tip")});
    const doneBox = h("details", {class: "sa-qdone", hidden: ""}, doneHead, doneList);
    const queue = h("div", {class: "sa-queue", hidden: ""}, queueList, doneBox);
    const hist = typeof SUPERHIST !== "undefined" ? SUPERHIST.create(streamWrap, (text) => linked(text)) : null;  // the earlier days (superhist.js)
    sv.append(h("div", {class: "sa-head"}, h("div", {class: "sa-who"}, h("div", {class: "sa-name"}, t("super.name")), lineEl), costEl, hist ? hist.button : null, popUp), team, filterEl, banner,
      h("div", {class: "sa-body"}, queue, streamWrap), quick, h("div", {class: "sa-input"}, complete, box));

    let shown = false, pet = null, data = null, talk = null, talkGone = 0, first = true, vsDown = false, filter = "";
    let teamSig = "", bannerSig = "", mates = [], localThink = 0, failed = "";
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
    function drawTeam(list) {
      mates = list;
      const sig = JSON.stringify(list) + "|" + filter;
      if (sig === teamSig) return;
      teamSig = sig;
      if (filter && !list.some((mate) => mate.task === filter)) filter = "";
      const all = h("button", {type: "button", class: "sa-mate all" + (filter ? "" : " on"), "data-task": "", title: t("super.team.all.tip")}, h("span", {class: "sa-ring"}, t("super.team.all")), h("span", {class: "sa-nm"}, t("super.team.all")));
      const nodes = list.map((mate, at) => {
        const state = MATE[mate.state] ? mate.state : "idle";
        const ring = h("span", {class: "sa-ring"}, PET.face(state === "you" || state === "error" ? "you" : state === "work" || state === "stuck" ? "work" : "idle", mate.kind, ((at * .37) % 3).toFixed(2)));
        return h("button", {type: "button", class: "sa-mate " + state + (filter === mate.task ? " on" : ""), "data-task": mate.task, "data-state": state, title: t("super.mate.tip", {task: mate.task, state: t(MATE[state])})},
          ring, mate.count ? h("span", {class: "sa-cnt"}, mate.count) : null, h("span", {class: "sa-nm"}, mate.task));
      });
      team.replaceChildren(all, ...nodes);
    }
    team.addEventListener("click", (event) => {
      const mate = event.target.closest(".sa-mate");
      if (mate) setFilter(mate.dataset.task === filter ? "" : mate.dataset.task);
    });
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
      const line = h("input", {type: "text", class: "sa-mateline", maxlength: 2000, placeholder: t("super.mate.steer.ph", {task}), "aria-label": t("super.mate.steer.ph", {task})});
      const lineRow = h("div", {class: "sa-materow", hidden: ""}, line);
      let busy = false;
      const send = (call, line) => {
        if (busy) return;
        busy = true;
        said.replaceChildren();
        call.then(() => { mateMenuClose(true); addSys(line); }, (error) => { busy = false; said.replaceChildren(...SERVE.reasons((error && error.message) || String(error))); });
      };
      const steer = item("super.mate.steer", () => { lineRow.hidden = false; line.focus(); });
      const stop = item("super.mate.stop", () => send(mateStop(task), t("super.mate.stopped", {task})));
      line.addEventListener("keydown", (event) => {
        if (!isEnter(event) || event.shiftKey || !line.value.trim()) return;
        event.preventDefault();
        send(mateSteer(task, line.value.trim()), t("super.mate.steered", {task}));
      });
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
      drawTeam(mates);
      filterEl.hidden = !task;
      filterEl.replaceChildren(...(task ? [t("super.filter.only") + " ", taskLink(task), " ", h("button", {type: "button", class: "sa-x", title: t("super.filter.clear"), "aria-label": t("super.filter.clear")}, "×")] : []));
      const clear = filterEl.querySelector(".sa-x");
      if (clear) clear.addEventListener("click", () => setFilter(""));
      applyFilter();
      drawInput();
    }
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
      sv.classList.toggle("sa-nochat", !chat);  // no chat yet: the queue takes the room
      empty.hidden = chat + open > 0;
      empty.replaceChildren(...[h("b", null, filter ? t("super.empty.filter") : mates.length ? t("super.empty.title") : t("super.empty.notasks")), filter || !mates.length ? null : h("div", null, t("super.empty.text"))].filter(Boolean));
    }

    // ---------- the messages ----------
    function addSys(text) { add(h("div", {class: "sa-sys"}, text)); }
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
    function addYou(text, at) {
      const row = h("div", {class: "sa-row me"}, h("div", {class: "sa-bub", title: at ? when(at, 11, 16) : null}, text));
      chatRows.push(row);
      add(row, true);
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
    const ACT_WHY = {unknown: "super.act.why.unknown", state: "super.act.why.state", kind: "super.act.why.kind", n: "super.act.why.n", text: "super.act.why.text", paused: "super.act.why.paused", closed: "super.act.why.closed", empty: "super.act.why.empty", long: "super.act.why.long", name: "super.act.why.name", taken: "super.act.why.taken", bad: "super.act.why.bad"};
    const actSig = (list) => JSON.stringify(list || []);
    const actWhat = (one) => (one.kind === "send" ? t("super.act.send.to", {task: one.task})
      : one.kind === "new" ? t("super.act.new", {name: one.name})
      : one.action === "review set" ? t("super.act.set.what", {task: one.task, n: one.n})
      : one.action === "steer" ? t("super.act.steer.what", {task: one.task})
      : one.action === "stop" ? t("super.act.stop.what", {task: one.task})
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
      if (one.kind === "send") {
        const box = h("textarea", {class: "sa-reply-box sa-acttextbox", rows: "3", maxlength: 2000, "aria-label": t("super.act.send.tip")});
        box.value = state.drafts.has(at) ? state.drafts.get(at) : (one.text || "");
        box.addEventListener("input", () => state.drafts.set(at, box.value));
        const go = h("button", {type: "button", class: "act hot live"}, t("super.act.send.go"));
        go.addEventListener("click", () => {
          const text = box.value.trim();
          if (!text) return;
          post(go, () => (mateMenuWorks(one.task) ? SERVE.post("/api/queue", {task: one.task, text, lang: ""}) : SERVE.post("/api/send", {task: one.task, kind: "answer", body: text, note: "", lang: "", step: "act"})));
        });
        return h("div", {class: "sa-actrow"}, h("div", {class: "sa-acthead"}, h("span", {class: "sa-actwhat"}, actWhat(one)), taskLink(one.task)), h("div", {class: "sa-reply"}, box, go), said);
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
    function actDraw(state) {
      const rows = (state.list || []).map((one, at) => actRow(state, one, at));
      const all = actAll(state);
      state.box.replaceChildren(h("div", {class: "sa-acthd"}, t("super.act.head")), ...rows, ...(all ? [all] : []));
      state.sig = actSig(state.list);
    }
    function actCard(message) {
      if (!message || !Array.isArray(message.proposals) || !message.proposals.length) return null;
      const state = {box: h("div", {class: "sa-act"}), sig: "", list: message.proposals, drafts: new Map(), pressed: new Map(), done: new Map()};
      ACT.set(message.id, state);
      actDraw(state);
      return state.box;
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
    const saidLong = (item) => String(said(item)).split("\n").reduce((sum, line) => sum + Math.max(1, Math.ceil(line.length / 60)), 0) > 8;

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
    // The window View opens: the call as the server shows it (what the task page's View shows, without its layout): the words of its type, the system, the text it writes, the files it reads, the command as written.
    function callWindow(call, onCode) {
      const copy = h("button", {type: "button", class: "act"}, t("desk.outbox.copy"));
      copy.addEventListener("click", () => { navigator.clipboard.writeText(call.command || "").then(() => { copy.textContent = t("desk.outbox.copied"); }, () => {}); });
      const close = h("button", {type: "button", class: "act"}, t("desk.window.close"));
      const chip = h("button", {type: "button", class: "ev code-chip", title: t("desk.outbox.code_tip")}, call.code);  // a click copies the code, puts it in the card's box and closes this window
      const scripts = (call.layout && (call.layout.scripts || (call.layout.script ? [call.layout.script] : []))) || [];
      const says = (call.says || []).filter(Boolean);
      const body = call.body && call.body.text ? call.body : null;
      const view = SERVE.dialog([h("h2", null, t("desk.outbox.window")), says.length ? h("p", null, says.join(" · ")) : null,
        h("p", {class: "sub"}, h("b", null, call.system || "-"), call.env && call.env !== "none" ? " (" + call.env + ")" : "", call.target ? " · " + call.target : ""),
        h("p", {class: "sub"}, t("desk.outbox.asked", {at: when(call.created_at, 0, 16)}), " ", chip),
        h("div", {class: "win-body"},
          body ? [h("p", {class: "sub"}, h("b", null, body.label || t("desk.outbox.body")), body.path ? " · " + body.path : ""), h("pre", {class: "cmd-script", tabindex: "0"}, body.text), body.cut ? h("p", {class: "sub"}, t("desk.outbox.body.cut")) : null] : null,
          scripts.filter((script) => script && script.text).map((script) => [h("p", null, h("b", null, script.path)), h("pre", {class: "cmd-script", tabindex: "0"}, script.text), script.cut ? h("p", {class: "sub"}, t("desk.cut")) : null]),
          h("p", {class: "sub"}, t("desk.outbox.as_written")), h("pre", {class: "cmd-script", tabindex: "0"}, call.command || "")),
        call.draft ? h("p", {class: "sub"}, t("super.call.draft", {file: call.draft})) : null, h("div", {class: "row win-foot"}, copy, close)]);
      view.box.classList.add("wide");
      close.addEventListener("click", view.close);
      chip.addEventListener("click", () => { navigator.clipboard.writeText(call.code).then(() => {}, () => {}); view.close(); if (onCode) onCode(call.code); });
    }
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
          VIEWED.set(code, result.call.seen || {});
          CHANGED.delete(code);
          armAll(code);
          callWindow(result.call, (typed) => { TYPED.set(code, typed); input.value = typed; armAll(code); yes.focus(); });
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
      const line = h("input", {type: "text", class: "sa-mateline sa-steerline", maxlength: 2000, placeholder: t("super.mate.steer.ph", {task: item.task}), "aria-label": t("super.mate.steer.ph", {task: item.task}), hidden: ""});
      const steer = h("button", {type: "button", class: "act hot live", "data-act": "steer"}, t("super.mate.steer"));
      const stop = h("button", {type: "button", class: "act live", "data-act": "stop"}, t("super.mate.stop"));
      let busy = false;
      const send = (call, receipt, said_) => {  // the mate menu's own calls (mateSteer, mateStop)
        if (busy) return;
        busy = true; said.replaceChildren();
        call.then(() => { busy = false; const entry = known.get(item.id); if (entry) entry.clicked = t(receipt); addSys(said_); poll(); emit(); }, (error) => { busy = false; said.replaceChildren(...actBad(error)); });
      };
      steer.addEventListener("click", () => { line.hidden = !line.hidden; if (!line.hidden) line.focus(); });
      line.addEventListener("keydown", (event) => { if (isEnter(event) && !event.shiftKey && line.value.trim()) { event.preventDefault(); send(mateSteer(item.task, line.value.trim()), "super.done.steered", t("super.mate.steered", {task: item.task})); } });
      stop.addEventListener("click", () => send(mateStop(item.task), "super.done.stopped", t("super.mate.stopped", {task: item.task})));
      return [steer, stop, line, said];
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
      const row = rowFor(entry.item.task);
      const buttons = buttonsFor(entry.item);
      const joint = entry.item.why === "plan" && Boolean(row.req_unconfirmed);  // one code confirms the requirement and approves the plan (the approve-plan window does it)
      entry.note.hidden = !joint;
      entry.note.textContent = joint ? t("super.plan.joint") : "";
      const open = taskLink(entry.item.task, t("super.open") + " ↗", "act sa-open");
      const goes = buttons.filter((node) => node.classList && node.classList.contains("sa-call")).map((node) => node.querySelector(".sa-callgo")).filter(Boolean);
      entry.acts.classList.toggle("sa-calls", goes.length > 0);
      if (goes.length) goes[goes.length - 1].append(open);  // a held call: "Open task" sits in the row of its buttons, not on a line of its own
      entry.acts.replaceChildren(...buttons, ...(goes.length ? [] : [open]));
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
      if (!PREVIEW_ASKED.has(item.id)) PREVIEW_ASKED.set(item.id, SERVE.call("/api/super/preview", {task: item.task, kind}, 8).then((result) => result || {}, () => ({})));
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
      if (said(item)) what.replaceChildren(...linked(said(item)));
      let saidMore = null;
      if (said(item)) what.classList.add("said");
      if (said(item) && saidLong(item)) { saidMore = h("button", {type: "button", class: "sa-askmore"}, t("super.more")); saidMore.addEventListener("click", () => { what.classList.add("open"); saidMore.hidden = true; }); }
      if (clampable(item) || saidLong(item)) {  // the question or command itself is the message: a few lines, the rest on a click
        what.classList.add("ask");
        what.tabIndex = 0;
        const flip = () => { what.classList.toggle("open"); if (saidMore) saidMore.hidden = what.classList.contains("open"); };
        what.addEventListener("click", flip);
        what.addEventListener("keydown", (event) => { if (isEnter(event)) { event.preventDefault(); flip(); } });
      }
      const note = h("div", {class: "sa-note", hidden: ""});
      const acts = h("div", {class: "sa-acts"});
      const xtra = h("div", {class: "sa-xtra"});
      const more = !asksPerson(item) && !["error", "stuck", "accept"].includes(item.why) && item.detail && item.detail !== item.title ? h("details", {class: "sa-more"}, h("summary", null, t("super.details")), h("pre", null, item.detail)) : null;
      const node = h("div", {class: "sa-row item" + (item.why === "error" ? " err" : ""), "data-task": item.task, "data-id": item.id},
        h("span", {class: "sa-mini hot"}, PET.face("you", (mates.find((mate) => mate.task === item.task) || {}).kind, 0)),
        h("div", {class: "sa-bub fwd"}, h("div", {class: "sa-fw"}, taskLink(item.task), why, waited), what, xtra, saidMore, note, more, acts));
      const entry = {item, node, acts, waited, what, note, why, xtra, xsig: "", sig: "", clicked: ""};
      if (item.why === "stopped" || SAYS(item)) node.querySelector(".sa-bub").insertBefore(replyBox(entry), acts);
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
      entry.note.hidden = true;
      // The task has another wait now (a row has one): it is not settled, it moved on. The person's own click is still the better thing to say.
      const said_ = decidedIn(entry) || entry.clicked;
      const line = said_ ? "\u2713 " + said_ : next ? "\u2192 " + t("super.done.next", {kind: whyText(next)}) : "\u2713 " + t("super.done.elsewhere");
      entry.node.remove();  // the card leaves the queue; its receipt goes to the "Done" row
      doneList.prepend(h("div", {class: "sa-rc", "data-task": entry.item.task}, taskLink(entry.item.task), h("span", {class: next && !said_ ? "sa-next" : "sa-ok"}, line + " \u00b7 " + stamp())));
      while (doneList.children.length > RECEIPTS) doneList.lastElementChild.remove();
      doneBox.classList.remove("sa-flash"); void doneBox.offsetWidth; doneBox.classList.add("sa-flash");
      applyFilter();
      doneLog.push({task: entry.item.task, text: line, at: stamp()});
      if (doneLog.length > 30) doneLog.shift();
    }
    function reconcile(items) {
      const ids = new Set(items.map((item) => item.id));
      for (const [id, entry] of known) if (!entry.done && !ids.has(id)) fold(entry, items.find((item) => item.task === entry.item.task));
      for (const item of items) {
        const entry = known.get(item.id);
        if (!entry || entry.done) continue;
        entry.item = item;
        entry.why.textContent = whyText(item);
        drawExtra(entry);
        if (entry.what.textContent !== mainOf(item)) { if (said(item)) entry.what.replaceChildren(...linked(said(item))); else entry.what.textContent = mainOf(item); entry.what.title = fullOf(item); }
        drawWaited(entry);
        if (entry.sig !== sigOf(entry)) drawActs(entry);
      }
      const fresh = items.filter((item) => !known.has(item.id) && !queued.has(item.id));
      const animate = !first && fresh.length <= 3 && petFree();
      for (const item of fresh) {
        if (animate) { queued.add(item.id); chain = chain.then(() => notice(item)).catch(() => addItem(item)); } else addItem(item);
      }
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
      pet.orbit(mates.map((mate) => (blocked.has(mate.task) || mate.state === "stuck" || mate.state === "error" ? "block" : MATE[mate.state] ? mate.state : "idle")));
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
      const open = kind === "sleep" ? h("button", {type: "button", class: "act"}, t("super.banner.open")) : null;
      if (open) open.addEventListener("click", () => { open.disabled = true; SERVE.openVS().then(() => { setTimeout(() => { open.disabled = false; }, 1500); }, (error) => { open.disabled = false; SERVE.failed(error); }); });
      banner.replaceChildren(...[h("span", null, text), open].filter(Boolean));
    }
    // Today's Credits of the super agent, for its battery: what is left, and the numbers for the tooltip. Null when it has no limit.
    function costNow() {
      if (!talk || !talk.limit) return null;
      const spent = talk.spent || 0, left = Math.max(0, talk.limit - spent), numbers = {spent: amount(spent), limit: amount(talk.limit), left: amount(left)};
      return {left: left / talk.limit, full: moodNow() === "tired", tip: t("super.cost.tip", numbers), label: t("super.cost.label", numbers)};
    }
    const talkOff = () => (!talk ? "none" : moodNow() === "sleep" ? "asleep" : moodNow() === "tired" ? "limit" : "");
    function drawInput() {
      const routing = Boolean(filter);  // one task's avatar is on: the input asks that task, whatever the super chat's state
      const off = routing ? "" : talkOff(), blocked = routing ? false : Boolean(off) || thinkingNow(), quickOff = Boolean(talkOff()) || thinkingNow();
      field.disabled = Boolean(off);
      field.placeholder = off ? t(OFF[off]) : routing ? t("super.route.ph", {task: filter}) : t("super.input.ph");
      field.title = field.placeholder;
      send.disabled = blocked;
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
      try { result = await SERVE.call("/api/super/ask", body || {text: typed}, 10); } catch (error) { result = (error && error.data && typeof error.data === "object" && error.data.why) ? error.data : {ok: false, why: "none"}; }
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
    // Where the typed words go: the task of the filter, or the task named after "@" (the name ends at a space or a mark, not inside a longer name), else the super chat (null).
    function routeTarget(typed) {
      if (filter) return {task: filter, text: typed};
      if (!typed.startsWith("@")) return null;
      for (const name of mates.map((mate) => mate.task).sort((a, b) => b.length - a.length)) {
        if (!typed.startsWith("@" + name) || !/^($|[\s,:;])/.test(typed.slice(name.length + 1))) continue;  // the name ends at a space, the end or , : ; (not inside a longer name such as job.v2)
        return {task: name, text: typed.slice(name.length + 1).replace(/^[\s,:;]+/, "").trim()};
      }
      return null;
    }
    // One ask to one task (the view's and the pop-out's): "" when it went, else the reason code.
    async function routeAsk(task, text) {
      if (!text) return "empty";
      try {
        const result = await SERVE.call("/api/super/route", {task, text, lang: ""}, 10);
        return !result || result.ok === false ? (result && result.why) || "other" : "";
      } catch (error) {
        return error && error.status === 403 ? "unpaired" : error && error.data && typeof error.data === "object" && error.data.why ? error.data.why : "other";
      }
    }
    async function routeSend(target, typed) {
      routeBusy = true;
      field.value = "";
      field.style.height = "auto";
      routeComplete();
      const why = await routeAsk(target.task, target.text);
      routeBusy = false;
      if (why) {  // refused: say why in the stream, the words go back into the input
        if (!field.value) field.value = typed;
        field.dispatchEvent(new Event("input"));
        addSys(t(routeKey(why)));
        return;
      }
      poll().then(schedule, schedule);
    }
    function submit() {
      const typed = field.value.trim();
      if (!typed || routeBusy) return;
      const target = routeTarget(typed);
      if (target) routeSend(target, typed); else ask(null);
    }
    // The ask rows: one per ask, drawn again in place when its state changes (never added twice).
    function routeBuild(item) {
      const kind = (mates.find((mate) => mate.task === item.task) || {}).kind;
      const line = h("div", {class: "sa-askline"}), answer = h("div", {class: "sa-text sa-ans"}), more = h("button", {type: "button", class: "sa-askmore", hidden: ""}, t("super.more"));
      const entry = {ask: item, sig: "", open: false, line, answer, more};
      more.addEventListener("click", () => { entry.open = true; routeDraw(entry, entry.ask); });
      entry.node = h("div", {class: "sa-row askrow", "data-task": item.task, "data-ask": item.id},
        h("span", {class: "sa-mini hot"}, PET.face("you", kind, 0)),
        h("div", {class: "sa-bub fwd"}, h("div", {class: "sa-fw"}, taskLink(item.task), item.at ? h("span", {class: "sa-when"}, when(item.at, 11, 16)) : null),
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
    function routeMerge(messages, asks) {
      const fresh = (asks || []).filter((item) => item && item.id && !ROUTE_ASKS.has(item.id)).sort((a, b) => String(a.at).localeCompare(String(b.at)));
      for (const item of fresh) {
        mergeTalk((messages || []).filter((message) => message && !seenTalk.has(message.id) && String(message.at || "") <= String(item.at || "")));
        const entry = routeBuild(item);
        ROUTE_ASKS.set(item.id, entry);
        chatRows.push(entry.node);
        add(entry.node, true);
        foldChat();
      }
      mergeTalk(messages || []);
      for (const item of asks || []) { const entry = item && ROUTE_ASKS.get(item.id); if (entry) routeDraw(entry, item); }
    }
    // "@" completion: the open task names, filtered as the person types; ArrowUp/ArrowDown move, Enter or Tab pick, Esc closes, a click picks.
    function routeComplete() {
      const word = /^@([^\s]*)$/.exec(field.value);
      routeNames = !filter && word ? mates.map((mate) => mate.task).filter((name) => name.toLowerCase().includes(word[1].toLowerCase())).slice(0, 8) : [];
      if (routePick >= routeNames.length) routePick = routeNames.length - 1;
      if (routePick < 0 && routeNames.length) routePick = 0;
      complete.hidden = !routeNames.length;
      complete.replaceChildren(...routeNames.map((name, at) => h("div", {class: "sa-opt" + (at === routePick ? " on" : ""), role: "option", "aria-selected": String(at === routePick), "data-task": name}, name)));
    }
    function routeChoose(name) {
      field.value = "@" + name + " ";
      routePick = -1;
      routeComplete();
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
    field.addEventListener("input", () => { routePick = -1; routeComplete(); });
    send.addEventListener("click", submit);
    field.addEventListener("keydown", (event) => { if (isEnter(event) && !event.shiftKey) { event.preventDefault(); submit(); } });
    field.addEventListener("input", () => { field.style.height = "auto"; field.style.height = Math.min(120, field.scrollHeight) + "px"; });
    if (newTask) newTask.addEventListener("click", () => { const text = field.value.trim(); CHAT.create(text ? {text} : undefined); field.value = ""; });  // the text moved into the new-task dialog

    // ---------- asking the server ----------
    function apply(result, spoken) {
      failed = "";
      data = result;
      talk = spoken && typeof spoken === "object" && spoken.state ? spoken : null;
      drawTeam(result.mates || []);
      if (talk && talk.state !== "thinking" && localThink && Date.now() - localThink > 4000) localThink = 0;  // the server is done (a message, or nothing to say)
      routeMerge(talk ? talk.messages : [], talk ? talk.asks : []);
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
        : SERVE.ready.then(() => SERVE.call("/api/super/talk", {}, 6)).then((answer) => { talkGone = 0; return answer; }, () => { talkGone = Date.now(); return null; });
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
      const delay = document.hidden && !watchers ? 30000 : thinkingNow() ? 1500 : Math.max(3, Number(DATA.serve && DATA.serve.refresh) || 5) * 1000;
      pollTimer = setTimeout(() => poll().then(schedule, schedule), delay);
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
        pet = PET.create(sv);
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
      if (!watchers) clearTimeout(pollTimer);
      patrolToken++;
      if (pet) pet.run(false);
    }
    // What the pop-out window reads (companion.js): the data this view already holds, and a call when it changes. It never asks the server itself.
    function snapshot() {
      const status = (data && data.status) || {};
      return {items: (data && data.items) || [], done: doneLog.slice(), working: mates.filter((mate) => mate.state === "work").length, watching: status.watching || 0, stuck: count(status.stuck), error: count(status.error), failed,
        mood: moodNow(), thinking: thinkingNow(), off: talkOff(), cost: costNow(),
        messages: talk ? (talk.messages || []).filter((message) => message && message.role !== "you") : [], mates, loaded: data !== null};
    }
    function watch(on) {
      watchers = Math.max(0, watchers + (on ? 1 : -1));
      if (on && watchers === 1 && !shown) poll().then(schedule, schedule);
      if (!watchers && !shown) clearTimeout(pollTimer);
    }
    // The pop-out's calls (companion.js): the same pieces as the view, never a copy of them.
    const replyFor = (item) => { const entry = item && (item.why === "stopped" || SAYS(item)) ? known.get(item.id) : null; return entry && !entry.done ? replyBox(entry) : null; };
    const previewFor = (item) => previewBox(item);
    const asksOf = (task) => ((talk && talk.asks) || []).filter((one) => one && one.task === task).map((one) => ({...one, line: one.state === "sent" ? t("super.route.waiting") : one.state === "queued" ? t("super.route.queued") : one.state === "failed" ? t(routeKey(one.why || one.end)) : ""}));
    async function askTask(task, text) {
      const why = await routeAsk(task, String(text || "").trim());
      if (!why) poll().then(schedule, schedule);
      return {ok: !why, why, text: why ? t(routeKey(why)) : ""};
    }
    const pop = {alertMarks: () => alertMarks((data && data.status) || {}), replyFor, previewFor, askTask, asksOf, mateWorks: mateMenuWorks, steer: mateSteer, stop: mateStop, snapshot, buttonsFor, sigFor, mainOf, fullOf, asksPerson, why: whyText, extraFor: extraNodes, hasCalls: (item) => callsOf(item).length > 0, prose, jointNote: (item) => (item.why === "plan" && Boolean(rowFor(item.task).req_unconfirmed) ? t("super.plan.joint") : ""),
      taskLink, ask: (text) => ask(null, text), watch, subscribe: (fn) => { listeners.add(fn); return () => listeners.delete(fn); }, openVS: () => SERVE.openVS()};
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
