// The super agent view of the board (1.8.1): one window like a messenger. Everything that waits for the person comes as a short message with its buttons (from `/api/super`, built by
// superview.py out of the rows of the board); a strip of round avatars shows the state of every open task (green dashed ring: at work, amber with a count: waits for you, grey: idle) and
// a click shows only that task's messages; a robot (pet.js) walks over the view, looks at the avatars, and fetches a letter when a new message arrives. A message that is answered folds
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
  const SAYS = ["super.pet.say.1", "super.pet.say.2", "super.pet.say.3", "super.pet.say.4"];
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
    const slot = h("div", {class: "sa-slot"});
    const lineEl = h("div", {class: "sa-line"});
    const costEl = h("span", {class: "sa-cost", hidden: ""});
    const lane = h("div", {class: "sa-lane", "aria-hidden": "true"});
    const team = h("div", {class: "sa-team", role: "group", "aria-label": t("super.team")});
    const filterEl = h("div", {class: "sa-filter", hidden: ""});
    const banner = h("div", {class: "sa-banner", hidden: "", role: "status"});
    const empty = h("div", {class: "sa-empty"});
    const stream = h("div", {class: "sa-stream", role: "log", "aria-live": "polite"}, empty);
    const pill = h("button", {type: "button", class: "sa-newpill", hidden: ""}, "↓ " + t("super.new"));
    const quick = h("div", {class: "sa-quick"});
    const field = h("textarea", {class: "sa-field", rows: 1, maxlength: 2000, placeholder: t("super.input.ph"), "aria-label": t("super.input.ph")});
    const newTask = SERVE.runs("create") ? h("button", {type: "button", class: "sa-new", title: t("super.new.tip")}, t("super.new.go")) : null;
    const send = h("button", {type: "button", class: "sa-send", title: t("super.send"), "aria-label": t("super.send")}, "↑");
    const box = h("div", {class: "sa-box"}, field, newTask, send);
    sv.append(h("div", {class: "sa-head"}, slot, h("div", {class: "sa-who"}, h("div", {class: "sa-name"}, t("super.name")), lineEl), costEl), lane, team, filterEl, banner,
      h("div", {class: "sa-streamwrap"}, stream, pill), quick, h("div", {class: "sa-input"}, box));

    let shown = false, pet = null, data = null, talk = null, talkGone = 0, first = true, vsDown = false, filter = "";
    let teamSig = "", bannerSig = "", mates = [], localThink = 0, failed = "";
    let pollTimer = 0, patrolToken = 0, noticeBusy = false, chain = Promise.resolve(), lastMate = "";
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
        if (node === empty) continue;
        node.hidden = Boolean(filter) && node.dataset.task !== filter;
        if (!node.hidden) visible++;
      }
      empty.hidden = visible > 0;
      empty.replaceChildren(...[h("b", null, filter ? t("super.empty.filter") : mates.length ? t("super.empty.title") : t("super.empty.notasks")), filter || !mates.length ? null : h("div", null, t("super.empty.text"))].filter(Boolean));
    }

    // ---------- the messages ----------
    function addSys(text) { add(h("div", {class: "sa-sys"}, text)); }
    function addYou(text, at) {
      add(h("div", {class: "sa-row me"}, h("div", {class: "sa-bub", title: at ? when(at, 11, 16) : null}, text)), true);
    }
    function addAgent(message) {
      const judgment = h("span", {class: "sa-judg", title: t("super.judgment.tip"), "aria-label": t("super.judgment.tip")}, "◇");
      add(h("div", {class: "sa-row"}, h("span", {class: "sa-mini boss"}, PET.face("calm", "", 0, true)),
        h("div", {class: "sa-bub agent"}, h("div", {class: "sa-fw"}, h("b", null, t("super.name")), judgment, message.at ? h("span", {class: "sa-when"}, when(message.at, 11, 16)) : null), h("div", {class: "sa-text"}, linked(message.text)))));
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

    // One item of the board: who it comes from, what it is, its buttons. Its buttons are drawn again only when the row of the task changed what they would be.
    function sigOf(entry) {
      const row = rowFor(entry.item.task);
      return JSON.stringify([entry.item.actions.map((item) => item.action), row.state, row.chat ? [row.chat.bound, row.chat.why] : null, row.req_unconfirmed || false, row.todo_left || 0]);
    }
    function drawActs(entry) {
      const row = rowFor(entry.item.task);
      const buttons = entry.item.actions.map((item) => (item.action === "answer"
        ? h("a", {class: "act hot live", href: taskUrl(entry.item.task), target: "_blank", rel: "noopener", "data-label": t("board.action.answer")}, t("board.action.answer"))  // the reply panel is on the task page: a new tab, not this one
        : actionButton(row, item)));
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
      const what = h("div", {class: "sa-what"}, item.title);
      const acts = h("div", {class: "sa-acts"});
      const more = item.detail && item.detail !== item.title ? h("details", {class: "sa-more"}, h("summary", null, t("super.details")), h("pre", null, item.detail)) : null;
      const node = h("div", {class: "sa-row item", "data-task": item.task, "data-id": item.id},
        h("span", {class: "sa-mini hot"}, PET.face("you", (mates.find((mate) => mate.task === item.task) || {}).kind, 0)),
        h("div", {class: "sa-bub fwd"}, h("div", {class: "sa-fw"}, taskLink(item.task), why, waited), what, more, acts));
      const entry = {item, node, acts, waited, what, sig: "", clicked: ""};
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
    function fold(entry) {
      entry.done = true;
      entry.node.classList.add("done");
      entry.waited.textContent = "";
      entry.acts.replaceChildren(h("span", {class: "sa-ok"}, "✓ " + (entry.clicked ? t("super.done.you", {action: entry.clicked}) : t("super.done.elsewhere")) + " · " + stamp()));
    }
    function reconcile(items) {
      const ids = new Set(items.map((item) => item.id));
      for (const [id, entry] of known) if (!entry.done && !ids.has(id)) fold(entry);
      for (const item of items) {
        const entry = known.get(item.id);
        if (!entry || entry.done) continue;
        entry.item = item;
        if (entry.what.textContent !== item.title) entry.what.textContent = item.title;
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
    const petFree = () => Boolean(pet) && shown && !still() && !document.hidden && moodNow() === "calm";
    function home() {
      const box = hostBox(), at = slot.getBoundingClientRect(), size = pet.size();
      return {x: at.left - box.left, y: at.bottom - box.top - size.h};
    }
    function standAt(target) {
      const box = hostBox(), at = target.getBoundingClientRect(), floor = lane.getBoundingClientRect(), size = pet.size();
      return {x: clamp(at.left + at.width / 2 - box.left - size.w / 2, 0, Math.max(0, box.width - size.w)), y: floor.bottom - box.top - size.h + 3};
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
        await pet.walkTo(standAt(mate).x, standAt(mate).y, 0);
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
    function canPatrol() { return petFree() && !noticeBusy && !thinkingNow() && !SERVE.open(); }
    async function patrol(token) {
      while (token === patrolToken) {
        await wait(2400 + Math.random() * 2600);
        if (token !== patrolToken) return;
        if (!canPatrol()) continue;
        const list = visibleMates().filter((node) => node.dataset.task !== lastMate);
        if (!list.length || Math.random() < .2) { const back = home(); pet.look(0, 0); await pet.walkTo(back.x, back.y, 0); lastMate = ""; continue; }
        const mate = list[Math.floor(Math.random() * list.length)];
        lastMate = mate.dataset.task;
        const spot = standAt(mate);
        pet.look(0, .6);
        await pet.walkTo(spot.x, spot.y, 0);
        if (token !== patrolToken || !canPatrol()) continue;
        if (mate.dataset.state === "you" && Math.random() < .6) pet.say(t("super.pet.waits"), 1300);
        else if (mate.dataset.state === "work" && Math.random() < .3) pet.say(t("super.pet.busy"), 1000);
        await wait(1200 + Math.random() * 1400);
      }
    }
    function petClick() {
      const mood = moodNow();
      if (mood === "sleep") { pet.say(t("super.pet.zz"), 1500); return; }
      if (mood === "tired") { pet.say(t("super.pet.tired"), 1700); return; }
      pet.hop(); pet.wave(1100);
      pet.say(t(SAYS[Math.floor(Math.random() * SAYS.length)]), 2000);
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
      if (talk && talk.limit) {
        costEl.hidden = false;
        costEl.textContent = t("super.cost", {spent: amount(talk.spent || 0), limit: amount(talk.limit)});
        costEl.title = t("super.cost.tip");
        costEl.classList.toggle("full", mood === "tired");
      } else costEl.hidden = true;
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
      applyMood(); drawInput(); schedule();
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
      applyFilter();
      drawStatus(); drawBanner(); drawInput(); applyMood();
      first = false;
    }
    function poll() {
      if (!shown || SERVE.busy()) return Promise.resolve();
      const spoken = talkGone && Date.now() - talkGone < 60000 ? Promise.resolve(null)
        : SERVE.ready.then(() => SERVE.call("/api/super/talk", {}, 6)).then((answer) => { talkGone = 0; return answer; }, () => { talkGone = Date.now(); return null; });
      return Promise.all([SERVE.post("/api/super", {}), spoken]).then(([result, answer]) => { if (shown) apply(result, answer); }, (error) => {
        if (!shown) return;
        failed = error && error.offline ? t("board.serve.stopped") : t("super.unavailable");
        drawStatus();
      });
    }
    function schedule() {
      clearTimeout(pollTimer);
      if (!shown) return;
      const delay = document.hidden ? 30000 : thinkingNow() ? 1500 : Math.max(3, Number(DATA.serve && DATA.serve.refresh) || 5) * 1000;
      pollTimer = setTimeout(() => poll().then(schedule, schedule), delay);
    }
    document.addEventListener("visibilitychange", () => { if (shown && !document.hidden) poll().then(schedule, schedule); });
    addEventListener("resize", () => {
      if (!shown) return;
      fit();
      if (pet && !noticeBusy) { const back = home(); pet.place(back.x, back.y); }
    });

    function show() {
      shown = true;
      sv.hidden = false;
      fit();
      if (!pet) { pet = PET.create(sv); pet.onClick(petClick); }
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
      clearTimeout(pollTimer);
      patrolToken++;
      if (pet) pet.run(false);
    }
    return {node: sv, show, hide, setVscode: (status) => { vsDown = Boolean(status) && !status.ready; if (shown) { drawStatus(); drawBanner(); drawInput(); applyMood(); } }};
  }

  return {create, waiting};
})();
