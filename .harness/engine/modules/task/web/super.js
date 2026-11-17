// The super agent view of the board (1.8.1): one window like a messenger. Everything that waits for the person comes as a short message with its buttons (from `/api/super`, built by
// superview.py out of the rows of the board); a strip of round avatars shows the state of every open task (green dashed ring: at work, amber with a count: waits for you, grey: idle) and
// a click shows only that task's messages; a robot (pet.js) rests in the top right corner and flies out to an avatar to fetch a letter when a new message arrives. A message that is answered folds
// into one "✓" line. Under the stream: two quick asks and an input to ask the agent or start a new task.
//
// The buttons of a message are the buttons of the board (`actionButton`, common.js): the same code, the same endpoints, the same code field for an approval; this file makes no action of its own.
// The agent's brain is another part (`/api/super/ask`, `/api/super/talk`): when they do not answer, the view still works and the input says the agent is not there.
// Not the default: board.js shows it when the person picks "Super agent" in the bar (the choice is not kept; the board opens as before).
// Needs common.js, serve.js, chat.js, lobby.js (Lobby.robot) and pet.js; board.js calls `SUPER.create`.
"use strict";

const SUPER = (function () {
  // The names of the messages are written out, so a search for a key finds its place.
  const WHY = {confirm: "super.why.confirm", question: "super.why.question", asking: "super.why.asking", outbox: "super.why.outbox", autorun: "super.why.autorun", req: "super.why.req", plan: "super.why.plan",
    promote: "super.why.promote", review: "super.why.review", recover: "super.why.recover", accept: "super.why.accept", commit: "super.why.commit", stopped: "super.why.stopped", cancelled: "super.why.cancelled"};
  const MATE = {you: "super.mate.you", work: "super.mate.work", idle: "super.mate.idle"};
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
    // The pop-out (companion.js): a small window that stays on top of every other window. Only where the browser can open one (Document Picture-in-Picture: Chrome, Edge).
    const popUp = typeof COMPANION !== "undefined" ? h("button", {type: "button", class: "sa-pop"}, "⇱") : null;
    const streamWrap = h("div", {class: "sa-streamwrap"}, stream, pill);
    const hist = typeof SUPERHIST !== "undefined" ? SUPERHIST.create(streamWrap, (text) => linked(text)) : null;  // the earlier days (superhist.js)
    sv.append(h("div", {class: "sa-head"}, h("div", {class: "sa-who"}, h("div", {class: "sa-name"}, t("super.name")), lineEl), costEl, hist ? hist.button : null, popUp), team, filterEl, banner,
      streamWrap, quick, h("div", {class: "sa-input"}, box));

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
        const ring = h("span", {class: "sa-ring"}, PET.face(state === "you" ? "you" : state === "work" ? "work" : "idle", mate.kind, ((at * .37) % 3).toFixed(2)));
        return h("button", {type: "button", class: "sa-mate " + state + (filter === mate.task ? " on" : ""), "data-task": mate.task, "data-state": state, title: t("super.mate.tip", {task: mate.task, state: t(MATE[state])})},
          ring, mate.count ? h("span", {class: "sa-cnt"}, mate.count) : null, h("span", {class: "sa-nm"}, mate.task));
      });
      team.replaceChildren(all, ...nodes);
    }
    team.addEventListener("click", (event) => {
      const mate = event.target.closest(".sa-mate");
      if (mate) setFilter(mate.dataset.task === filter ? "" : mate.dataset.task);
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
    }
    function applyFilter() {
      let visible = 0;
      for (const node of stream.children) {
        if (node === empty || node === earlier) continue;
        node.hidden = Boolean(filter) && node.dataset.task !== filter;
        if (!node.hidden) visible++;
      }
      empty.hidden = visible > 0;
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
        h("div", {class: "sa-bub agent"}, h("div", {class: "sa-fw"}, h("b", null, t("super.name")), judgment, message.at ? h("span", {class: "sa-when"}, when(message.at, 11, 16)) : null), h("div", {class: "sa-text"}, linked(message.text))));
      chatRows.push(row);
      add(row);
      foldChat();
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
        if (!message || seenTalk.has(message.id)) continue;
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
    const mainOf = (item) => (asksPerson(item) ? item.detail : item.title);
    const fullOf = (item) => (asksPerson(item) ? item.detail : "");

    // One item of the board: who it comes from, what it is, its buttons. Its buttons are drawn again only when the row of the task changed what they would be.
    function sigFor(item) {
      const row = rowFor(item.task);
      return JSON.stringify([item.actions.map((one) => one.action), row.state, row.chat ? [row.chat.bound, row.chat.why] : null, row.req_unconfirmed || false, row.todo_left || 0]);
    }
    const sigOf = (entry) => sigFor(entry.item);
    // The buttons of one item (also the pop-out window's): the board's own, so every action goes through SERVE.act / CHAT as in the board.
    function buttonsFor(item) {
      const row = rowFor(item.task);
      return item.actions.map((one) => (one.action === "answer"
        ? h("a", {class: "act hot live", href: taskUrl(item.task), target: "_blank", rel: "noopener", "data-label": t("board.action.answer")}, t("board.action.answer"))  // the reply panel is on the task page: a new tab, not this one
        : actionButton(row, one)));
    }
    function drawActs(entry) {
      const row = rowFor(entry.item.task);
      const buttons = buttonsFor(entry.item);
      const joint = entry.item.why === "plan" && Boolean(row.req_unconfirmed);  // one code confirms the requirement and approves the plan (the approve-plan window does it)
      entry.note.hidden = !joint;
      entry.note.textContent = joint ? t("super.plan.joint") : "";
      entry.acts.replaceChildren(...buttons, taskLink(entry.item.task, t("super.open") + " ↗", "act sa-open"));
      entry.sig = sigOf(entry);
    }
    function drawWaited(entry) {
      const seconds = entry.item.waited_s;
      entry.waited.textContent = seconds === null || seconds === undefined ? "" : t("super.waited", {time: clock(seconds)});
      entry.waited.title = entry.item.since ? when(entry.item.since, 0, 19) : "";
    }
    function build(item) {
      const why = h("span", {class: "sa-why"}, t(WHY[item.why] || "super.why.other"));
      const waited = h("span", {class: "sa-when"});
      const what = h("div", {class: "sa-what"}, mainOf(item));
      what.title = fullOf(item);
      if (asksPerson(item)) {  // the question or command itself is the message: a few lines, the rest on a click
        what.classList.add("ask");
        what.tabIndex = 0;
        const flip = () => what.classList.toggle("open");
        what.addEventListener("click", flip);
        what.addEventListener("keydown", (event) => { if (isEnter(event)) { event.preventDefault(); flip(); } });
      }
      const note = h("div", {class: "sa-note", hidden: ""});
      const acts = h("div", {class: "sa-acts"});
      const more = !asksPerson(item) && item.detail && item.detail !== item.title ? h("details", {class: "sa-more"}, h("summary", null, t("super.details")), h("pre", null, item.detail)) : null;
      const node = h("div", {class: "sa-row item", "data-task": item.task, "data-id": item.id},
        h("span", {class: "sa-mini hot"}, PET.face("you", (mates.find((mate) => mate.task === item.task) || {}).kind, 0)),
        h("div", {class: "sa-bub fwd"}, h("div", {class: "sa-fw"}, taskLink(item.task), why, waited), what, note, more, acts));
      const entry = {item, node, acts, waited, what, note, sig: "", clicked: ""};
      acts.addEventListener("click", (event) => { const button = event.target.closest("button, a.act"); if (button && button.dataset.label) entry.clicked = plain(button.dataset.label); });
      drawActs(entry);
      drawWaited(entry);
      return entry;
    }
    function addItem(item, down) {
      if (known.has(item.id)) return;
      const entry = build(item);
      known.set(item.id, entry);
      queued.delete(item.id);
      add(entry.node, down);
    }
    function fold(entry, next) {
      entry.done = true;
      entry.node.classList.add("done");
      entry.waited.textContent = "";
      entry.note.hidden = true;
      // The task has another wait now (a row has one): it is not settled, it moved on. The person's own click is still the better thing to say.
      const line = entry.clicked ? "✓ " + t("super.done.you", {action: entry.clicked}) : next ? "→ " + t("super.done.next", {kind: t(WHY[next.why] || "super.why.other")}) : "✓ " + t("super.done.elsewhere");
      entry.acts.replaceChildren(h("span", {class: next && !entry.clicked ? "sa-next" : "sa-ok"}, line + " · " + stamp()));
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
        if (entry.what.textContent !== mainOf(item)) { entry.what.textContent = mainOf(item); entry.what.title = fullOf(item); }
        drawWaited(entry);
        if (entry.sig !== sigOf(entry)) drawActs(entry);
      }
      const fresh = items.filter((item) => !known.has(item.id) && !queued.has(item.id));
      const animate = !first && fresh.length <= 3 && petFree();
      for (const item of fresh) {
        if (animate) { queued.add(item.id); chain = chain.then(() => notice(item)).catch(() => addItem(item, true)); } else addItem(item, false);
      }
      if (first) { stream.scrollTop = 0; pill.hidden = true; }  // the most urgent message is the first one
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
      if (!petFree() || !mate) { addItem(item, true); return; }
      noticeBusy = true;
      try {
        mate.scrollIntoView({inline: "nearest", block: "nearest"});
        await wait(200);
        pet.look(0, .5);
        pet.say(t("super.pet.way"), 1000);
        const stand = standAt(mate);
        await pet.walkTo(stand.x, stand.y, stand.face);
        if (!petFree()) { addItem(item, true); return; }
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
        const end = hostBox(), list = stream.getBoundingClientRect(), now = pet.at();
        letter({x: now.x + size.w - 6, y: now.y + size.h * .45}, {x: list.left - end.left + 50, y: list.top - end.top + 30}, true);
        await wait(650);
        addItem(item, true);
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
      for (const node of stream.querySelectorAll(".sa-spot")) node.classList.remove("sa-spot");
      if (!entry) {
        pointing = null;
        const mood = moodNow();
        if (mood === "sleep") pet.say(t("super.pet.zz"), 1500);
        else if (mood === "tired") pet.say(t("super.pet.tired"), 1700);
        else { pet.hop(); pet.wave(1100); pet.say(t("super.pet.clear"), 2200); }
        return;
      }
      if (entry.node.hidden) setFilter("");
      pointing = {id: entry.item.id, until: Date.now() + 8000};
      holdUntil = pointing.until;
      entry.node.classList.add("sa-spot");
      setTimeout(() => entry.node.classList.remove("sa-spot"), 8000);
      entry.node.scrollIntoView({block: "nearest", behavior: still() ? "auto" : "smooth"});
      pet.say(t("super.pet.next", {task: entry.item.task, why: t(WHY[entry.item.why] || "super.why.other")}), 3200);
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
      pet.orbit(mates.map((mate) => (blocked.has(mate.task) ? "block" : MATE[mate.state] ? mate.state : "idle")));
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
    function drawStatus() {
      const status = (data && data.status) || {};
      const mood = moodNow();
      lineEl.replaceChildren();
      if (failed) { lineEl.append(failed); } else if (mood === "sleep") lineEl.append(t("super.line.asleep"));
      else if (mood === "tired") lineEl.append(t("super.line.tired"));
      else {
        const n = status.watching || 0;
        lineEl.append(t(n === 1 ? "super.line.watching.one" : "super.line.watching", {n}), " · ", h("span", {class: status.waiting ? "sa-w" : ""}, status.waiting ? t("super.line.waiting", {n: status.waiting}) : t("super.line.none")));
        if (status.as_of) lineEl.append(" · " + t("super.line.updated", {time: when(status.as_of, 11, 16)}));
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
      const off = talkOff(), blocked = Boolean(off) || thinkingNow();
      field.disabled = Boolean(off);
      field.placeholder = off ? t(OFF[off]) : t("super.input.ph");
      field.title = field.placeholder;
      send.disabled = blocked;
      box.classList.toggle("off", Boolean(off));
      quick.hidden = Boolean(off);
      if (!quick.children.length) {
        for (const [key, body] of [["super.quick.next", () => ({text: t("super.quick.next")})], ["super.quick.summary", () => ({kind: "summary"})]]) {
          const button = h("button", {type: "button"}, t(key));
          button.addEventListener("click", () => ask(body(), t(key)));
          quick.append(button);
        }
      }
      for (const button of quick.children) button.disabled = blocked;
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
    send.addEventListener("click", () => ask(null));
    field.addEventListener("keydown", (event) => { if (isEnter(event) && !event.shiftKey) { event.preventDefault(); ask(null); } });
    field.addEventListener("input", () => { field.style.height = "auto"; field.style.height = Math.min(120, field.scrollHeight) + "px"; });
    if (newTask) newTask.addEventListener("click", () => { const text = field.value.trim(); CHAT.create(text ? {text} : undefined); field.value = ""; });  // the text moved into the new-task dialog

    // ---------- asking the server ----------
    function apply(result, spoken) {
      failed = "";
      data = result;
      talk = spoken && typeof spoken === "object" && spoken.state ? spoken : null;
      drawTeam(result.mates || []);
      if (talk && talk.state !== "thinking" && localThink && Date.now() - localThink > 4000) localThink = 0;  // the server is done (a message, or nothing to say)
      mergeTalk(talk ? talk.messages : []);
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
      sv.hidden = true;
      if (!watchers) clearTimeout(pollTimer);
      patrolToken++;
      if (pet) pet.run(false);
    }
    // What the pop-out window reads (companion.js): the data this view already holds, and a call when it changes. It never asks the server itself.
    function snapshot() {
      const status = (data && data.status) || {};
      return {items: (data && data.items) || [], done: doneLog.slice(), working: mates.filter((mate) => mate.state === "work").length, watching: status.watching || 0, failed,
        mood: moodNow(), thinking: thinkingNow(), off: talkOff(), cost: costNow(),
        messages: talk ? (talk.messages || []).filter((message) => message && message.role !== "you") : [], mates, loaded: data !== null};
    }
    function watch(on) {
      watchers = Math.max(0, watchers + (on ? 1 : -1));
      if (on && watchers === 1 && !shown) poll().then(schedule, schedule);
      if (!watchers && !shown) clearTimeout(pollTimer);
    }
    const pop = {snapshot, buttonsFor, sigFor, mainOf, fullOf, asksPerson, why: (item) => t(WHY[item.why] || "super.why.other"), jointNote: (item) => (item.why === "plan" && Boolean(rowFor(item.task).req_unconfirmed) ? t("super.plan.joint") : ""),
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
