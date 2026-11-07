// The Live tab of a task page (1.6.17, B88): the latest items of the agent's chat, as they come. A served page only.
// The server keeps the chat in memory and gives the latest few items (`/api/live`: agent text, tool calls, thinking; every text redacted and cut there). This file asks once a second while the
// tab (or the reply panel) is open and the page is visible, and draws only what changed: an item that is already there is changed in place (its text, its state, its time), never made again, so
// no animation starts over and nothing jumps. A new item is added at the bottom; one that left the latest few is removed from the top. The page follows the bottom only if the person is there; a
// person who scrolled up to read is kept where they are (what is above the reading place changes height: the place is put back).
// The run times tick on the one timer of status.js (`.st-run[data-since]`); this file has no timer of its own for them. The text only grows or is replaced: new letters are added as a small piece that fades in.
// Needs common.js (h, t, clock), serve.js (SERVE), status.js (Status). Drawn with DOM nodes and textContent only.
"use strict";

const LIVE = (function () {
  const NS = "http://www.w3.org/2000/svg";
  const EVERY = 1000;  // ms between two answers and the next question
  const SLOW = 3000;  // after a failed one
  const LINK_DOWN = ["starting", "none", "no-cli", "cli-failed", "many", "error", "lost", "off"];  // why the link to VS Code itself is not there (the other reasons are about this task's chat)

  const st = {task: "", rev: "", nodes: new Map(), wants: new Set(), timer: 0, busy: false, fails: 0, skew: 0, data: null, off: "", chat: null, held: [], approved: [], listeners: [], needs: [], started: ""};

  const svg = (paths, size, cls) => {
    const node = document.createElementNS(NS, "svg");
    for (const [name, value] of Object.entries({viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", "stroke-width": "1.5", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", class: cls || ""})) node.setAttribute(name, value);
    if (size) { node.setAttribute("width", size); node.setAttribute("height", size); }
    for (const d of paths) { const part = document.createElementNS(NS, "path"); part.setAttribute("d", d); node.append(part); }
    return node;
  };
  const ICONS = {
    read: ["M4 2h5l3 3v9H4zM9 2v3h3"], edit: ["M3 13l1-3 7-7 2 2-7 7zM9.5 4.5l2 2"], run: ["M3 4l4 4-4 4M8 12h5"], search: ["M7 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM10 10l3 3"],
    web: ["M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2zM2 8h12M8 2c2 2 2 10 0 12M8 2c-2 2-2 10 0 12"], other: ["M3 8h.01M8 8h.01M13 8h.01"], think: ["M8 2a4 4 0 0 0-2 7.5V11h4V9.5A4 4 0 0 0 8 2zM6.5 13.5h3"],
  };
  // The kind of a tool, from its name: only for the icon. A name this does not know gets the three dots.
  function kindOf(tool, name) {
    const text = (tool + " " + name).toLowerCase();
    if (/(bash|shell|terminal|command|powershell|\brun\b|exec)/.test(text)) return "run";
    if (/(edit|write|patch|replace|create|apply|insert|delete|rename|move)/.test(text)) return "edit";
    if (/(grep|glob|search|find|list|\bls\b)/.test(text)) return "search";
    if (/(fetch|web|http|browse|url)/.test(text)) return "web";
    if (/(read|view|open|cat|get_file|file)/.test(text)) return "read";
    return "other";
  }
  const robot = () => {
    const node = document.createElementNS(NS, "svg");
    for (const [name, value] of Object.entries({viewBox: "0 0 32 32", class: "lv-rb", "aria-hidden": "true", fill: "none", stroke: "currentColor", "stroke-width": "1.4", "stroke-linecap": "round"})) node.setAttribute(name, value);
    const add = (tag, attrs) => { const part = document.createElementNS(NS, tag); for (const [name, value] of Object.entries(attrs)) part.setAttribute(name, String(value)); node.append(part); return part; };
    add("rect", {x: 6, y: 10, width: 20, height: 15, rx: 5});
    add("path", {d: "M16 10V6M12 28h8"});
    add("circle", {cx: 16, cy: 5, r: 1.6, class: "bulb", stroke: "none"});
    add("circle", {cx: 12, cy: 17, r: 1.7, class: "ey", stroke: "none"});
    add("circle", {cx: 20, cy: 17, r: 1.7, class: "ey", stroke: "none"});
    return node;
  };

  // --- the nodes made once ----------------------------------------------------------------------------------------------
  const link = h("button", {type: "button", class: "lv-link"}, t("desk.live.whole"));
  const head = h("div", {class: "lv-h"}, h("span", {class: "lv-t"}, t("desk.live.title")), h("span", {class: "sub lv-sub"}, t("desk.live.sub")), link);
  const earlier = h("div", {class: "lv-earlier", hidden: ""}, h("span", null, t("desk.live.earlier")));
  const needLi = h("li", {class: "fi fi-need", hidden: ""}, h("i", {class: "dot hot"}), h("div", {class: "lv-need"}));
  const feed = h("ol", {class: "lv-feed"}, needLi);
  const calm = h("div", {class: "lv-empty", hidden: ""});
  const stale = h("p", {class: "sub lv-stale", hidden: ""}, t("desk.live.stale"));
  const lifeLabel = h("span", {class: "lt-l"}), lifeSep = h("span", {class: "lt-s"}, " \u00b7 "), lifeRun = h("b", {class: "lt-r"}, h("span", {class: "st-time"}));
  const life = h("div", {class: "lv-life calm"}, robot(), h("span", {class: "eq", "aria-hidden": "true"}, h("i"), h("i"), h("i"), h("i")), h("span", {class: "lt"}, lifeLabel, lifeSep, lifeRun));
  const root = h("section", {class: "lv", hidden: ""}, head, stale, earlier, feed, calm, life);
  const roundsHere = (box) => { if (box.parentNode !== root) root.insertBefore(box, stale); };

  link.addEventListener("click", () => {
    link.disabled = true;
    SERVE.openVS().then(() => { setTimeout(() => { link.disabled = false; }, 1500); }, (error) => { link.disabled = false; SERVE.failed(error, st.chat && st.chat.title); });
  });

  // --- time -------------------------------------------------------------------------------------------------------------
  const seconds = (ms) => (ms < 10000 ? t("unit.seconds", {s: (Math.max(0, ms) / 1000).toFixed(1)}) : clock(ms / 1000));
  const since = (ms) => ms - st.skew;  // the server's clock to this page's

  // A running time: a node the one timer of status.js moves (`.st-run[data-since]` with a `.st-time` child). Set it, and write the first value now.
  function running(node, ms) {
    const value = String(Math.round(since(ms)));
    if (node.getAttribute("data-since") !== value) node.setAttribute("data-since", value);
    if (!node.classList.contains("st-run")) node.classList.add("st-run");
    const label = node.querySelector(".st-time");
    const text = clock(Math.max(0, (Date.now() - since(ms)) / 1000));
    if (label && label.textContent !== text) label.textContent = text;
  }
  function stopped(node) {
    if (node.hasAttribute("data-since")) node.removeAttribute("data-since");
    node.classList.remove("st-run");
  }
  const setText = (node, value) => { if (node.textContent !== value) node.textContent = value; };
  const setClass = (node, value) => { if (node.className !== value) node.className = value; };

  // --- one item ---------------------------------------------------------------------------------------------------------
  function make(item) {
    const li = h("li", {class: "fi fi-" + item.k + " enter", "data-id": item.id}, h("i", {class: "dot"}));
    const body = h("div", {class: "fb"});
    li.append(body);
    const rec = {el: li, body, kind: item.k, sig: "", text: "", pieces: 0};
    if (item.k === "me") {  // what the person said: a small mark; the words are in its card
      rec.tag = h("span", {class: "me-tag", role: "button"}, t("desk.live.you"));
      Status.card(rec.tag, () => saidCard(rec), t("desk.live.you"));
      body.append(rec.tag);
    } else if (item.k === "text") {
      rec.tx = h("div", {class: "tx md"});
      rec.cutm = h("span", {class: "cutm", hidden: ""}, t("desk.live.cut"));
      rec.caret = h("span", {class: "caret", hidden: ""});
      body.append(rec.tx, rec.cutm);
    } else if (item.k === "tool") {
      rec.ico = h("span", {class: "ti"});
      rec.say = h("span", {class: "in"});
      rec.tg = h("code", {class: "tg"});
      rec.el2 = h("span", {class: "el"}, h("span", {class: "st-time"}));
      body.append(rec.ico, rec.say, rec.tg, rec.el2);
    } else {
      rec.ico = h("span", {class: "ti"}, svg(ICONS.think, 15));
      rec.say = h("span", {class: "in"});
      rec.wave = h("b", {class: "wv", "aria-hidden": "true"}, h("i"), h("i"), h("i"));
      rec.el2 = h("span", {class: "el"}, h("span", {class: "st-time"}));
      rec.tx = h("p", {class: "tx thk", hidden: ""});
      body.append(h("div", {class: "thk-row"}, rec.ico, rec.say, rec.wave, rec.el2), rec.tx);
    }
    li.addEventListener("animationend", (event) => { if (event.target === li) li.classList.remove("enter"); });
    return rec;
  }

  // An agent item is Markdown, drawn the way the documents of the task are (desk.js gives the drawing: `drawing`, with a Copy button on each code block). It is drawn only when its text changed,
  // so a finished item keeps the person's selection.
  function growText(rec, item) {
    if (item.text === rec.text) return;
    rec.text = item.text;
    rec.tx.replaceChildren(...[st.draw && item.blocks ? st.draw(item.blocks) : item.text].flat(Infinity).filter(Boolean));
  }

  // The card of a message of the person. The newest can be taken back; a turn that runs is stopped first (1.6.99).
  function saidCard(rec) {
    const item = rec.item;
    if (!item) return null;
    const last = st.lastSaid === item.id && Boolean(st.data) && ["idle", "busy", "input", "error"].includes(st.data.state);
    return {sig: JSON.stringify([item, last]), build: () => {
      const undo = last ? h("button", {type: "button", class: "act"}, t("desk.undo.title")) : null;
      if (undo) undo.addEventListener("click", () => { CHAT.withdraw({name: st.task.split("/").pop()}, (found) => { REPLY.restore(found); kick(); }); });
      return h("div", {class: "tk-said"}, h("div", {class: "st-head"}, t("desk.live.you")), h("div", {class: "tk-said-t"}, item.text + (item.cut ? " …" : "")),
        item.files ? h("div", {class: "sub"}, t("desk.live.files", {names: item.files.join(", ")})) : null, undo);
    }};
  }

  // A subagent the tool call started (1.6.105): its latest steps under the call, open while it works and folded when it is done. Once the person opens or folds it, that stays.
  function subLine(step) {
    if (step.k === "tool") {
      const mark = step.st === "run" ? "\u2026" : step.st === "fail" ? "\u2717" : step.st === "wait" ? "?" : "\u2713";
      return h("li", {class: "sub-tool is-" + (step.st || "done")}, h("span", {class: "sub-mark", "aria-hidden": "true"}, mark), h("span", {class: "sub-say"}, step.say || step.name || step.tool || ""),
        step.target ? h("code", {class: "tg", title: step.target}, step.target) : null);
    }
    if (step.k === "text") return h("li", {class: "sub-text"}, step.text);
    if (step.k === "think") return h("li", {class: "sub-think"}, step.run ? t("desk.live.thinking") : t("desk.live.thought"));
    return null;
  }
  function paintSub(rec, sub) {
    if (!sub) { if (rec.sub) { rec.sub.remove(); rec.sub = null; } return; }
    if (!rec.sub) {
      rec.subHead = h("summary", {class: "sub-h"});
      rec.subList = h("ol", {class: "sub-list"});
      rec.sub = h("details", {class: "fi-subagent"}, rec.subHead, rec.subList);
      rec.subHead.addEventListener("click", () => { rec.subChosen = true; });
      rec.body.append(rec.sub);
    }
    if (!rec.subChosen) rec.sub.open = sub.st === "run";
    setText(rec.subHead, t("desk.live.subagent", {title: sub.title || t("desk.live.subagent.untitled")}) + " \u00b7 " + t(sub.st === "run" ? "desk.live.subagent.run" : "desk.live.subagent.done"));
    rec.subList.replaceChildren(...[...sub.items.map(subLine), sub.more ? h("li", {class: "sub-think"}, t("desk.live.subagent.more")) : null, !sub.items.length ? h("li", {class: "sub-think"}, t("desk.live.subagent.none")) : null].filter(Boolean));
  }

  // A call the gate held for the person fails in the chat ("Run Shell Command failed"): when its command is one waiting in the outbox, it is shown as held, not as failed (1.7.22).
  const flat = (text) => String(text || "").replace(/\s+/g, " ").trim();
  function isHeld(item) {  // "held" (waits for the person), "approved" (waits for the agent to run it again), or "" (a call like any other)
    if (item.k !== "tool" || item.st !== "fail" || !item.target) return "";
    const target = flat(item.target).slice(0, 60);
    if (target.length <= 3) return "";
    const same = (command) => command.includes(target) || target.includes(command.slice(0, 60));
    return st.held.some(same) ? "held" : st.approved.some(same) ? "approved" : "";  // an approved call that has not run is not a failure (1.7.24)
  }
  function paint(rec, item) {
    const held = isHeld(item);
    const sig = JSON.stringify(item) + (held ? "|" + held : "");
    if (sig === rec.sig) return;
    rec.sig = sig;
    rec.item = item;
    if (item.k === "me") {
      rec.tag.setAttribute("aria-label", t("desk.live.you") + ": " + item.text.slice(0, 200));
    } else if (item.k === "text") {
      growText(rec, item);
      rec.cutm.hidden = !item.cut;
      rec.caret.hidden = !item.live;
      if (item.live) (rec.tx.lastElementChild || rec.tx).append(rec.caret);  // the caret stays at the end of the growing text
      rec.el.classList.toggle("is-live", Boolean(item.live));
    } else if (item.k === "tool") {
      const kind = kindOf(item.tool || "", item.name || "");
      if (rec.kind2 !== kind) { rec.kind2 = kind; rec.ico.replaceChildren(svg(ICONS[kind], 15)); }
      const label = held === "approved" ? t("desk.live.approved") : held ? t("desk.live.held") : item.say || item.name || item.tool || "";
      setText(rec.say, label);
      rec.say.title = label;
      setText(rec.tg, item.target || "");
      rec.tg.hidden = !item.target;
      rec.tg.title = (item.target || "") + (item.cut ? " …" : "");
      for (const name of ["run", "wait", "fail", "done"]) rec.el.classList.toggle("is-" + name, (held ? "wait" : item.st === "stop" ? "done" : item.st || "done") === name);  // classList: the `enter` class is not lost
      paintSub(rec, item.sub);
      const time = rec.el2;
      if (item.st === "run" && item.t0) { running(time, item.t0); }
      else {
        stopped(time);
        const label2 = time.querySelector(".st-time");
        setText(label2, held === "approved" ? t("desk.live.wait.agent") : held || item.st === "wait" ? t("desk.live.wait") : item.st === "run" ? "" : item.st === "stop" ? t("desk.trace.stopped") : (item.st === "fail" ? "✗" : "✓") + (item.t0 && item.t1 ? " " + seconds(item.t1 - item.t0) : ""));
      }
    } else {
      const done = !item.run;
      rec.el.classList.toggle("is-done", done);
      rec.el.classList.toggle("is-run", !done);
      const gone = done && item.t0 && item.t1 ? " " + seconds(item.t1 - item.t0) : "";
      setText(rec.say, done ? t("desk.live.thought") + gone : t("desk.live.thinking"));
      rec.wave.hidden = done;
      if (!done && item.t0) running(rec.el2, item.t0); else { stopped(rec.el2); setText(rec.el2.querySelector(".st-time"), ""); }
      rec.tx.hidden = !item.text;
      setText(rec.tx, item.text ? item.text + (item.cut ? " …" : "") : "");
    }
  }

  // --- scroll: follow the bottom only when the person is there; never move what they are reading --------------------------
  const TOP_EDGE = 130;  // below the sticky header and tabs
  // `survives(node)`: will this item still be there after `change`? The place is kept by an item that stays.
  function view(change, survives) {
    if (root.hidden) { change(); return; }
    const gap = life.getBoundingClientRect().bottom - window.innerHeight;
    const follow = gap <= 70;
    let anchor = null, top = 0;
    if (!follow) {
      anchor = Array.from(feed.children).find((node) => !node.hidden && node.getBoundingClientRect().bottom > TOP_EDGE && (!survives || !node.dataset.id || survives(node))) || null;
      if (anchor) top = anchor.getBoundingClientRect().top;
    }
    change();
    if (follow) {
      const more = life.getBoundingClientRect().bottom - window.innerHeight + 24;
      if (more > 0) window.scrollBy({top: more, behavior: "instant"});
    } else if (anchor && anchor.isConnected) {
      const moved = anchor.getBoundingClientRect().top - top;
      if (Math.abs(moved) > 1) window.scrollBy({top: moved, behavior: "instant"});
    }
  }

  // --- what the answer says ---------------------------------------------------------------------------------------------
  function show(data) {
    const items = data && data.bound ? data.items || [] : [];
    const ids = new Set(items.map((item) => item.id));
    for (const [id, rec] of st.nodes) if (!ids.has(id)) { rec.el.remove(); st.nodes.delete(id); }
    st.lastSaid = (items.filter((item) => item.k === "me").pop() || {}).id || "";
    let previous = null;
    for (const item of items) {
      let rec = st.nodes.get(item.id);
      if (!rec || rec.kind !== item.k) {
        if (rec) rec.el.remove();
        rec = make(item);
        st.nodes.set(item.id, rec);
      }
      paint(rec, item);
      const expected = previous ? previous.el.nextSibling : feed.firstChild;
      if (rec.el !== expected) feed.insertBefore(rec.el, expected);
      previous = rec;
    }
    earlier.hidden = !(data && data.bound && data.more && items.length);
    paintCalm(data, items);
    paintLife(data);
    root.classList.toggle("is-busy", Boolean(data && data.bound && data.state === "busy"));
    if (feed.querySelector(".st-run[data-since]") || life.querySelector(".st-run[data-since]")) { Status.clock(); Status.tick(); }
  }

  function paintLife(data) {
    const bound = Boolean(data && data.bound);
    const state = bound ? data.state : "";
    life.hidden = !bound;
    const waits = state === "input" || (state === "idle" && st.needs.length > 0);  // the chat is idle, the task is not: a card above says what it waits for
    setClass(life, "lv-life " + (state === "busy" ? "run" : waits ? "paused" : "calm"));
    const when = state === "busy" && data.started ? Date.parse(data.started) : NaN;
    setText(lifeLabel, state === "busy" ? t("desk.live.working") : waits ? t("desk.live.input") : state === "error" ? t("desk.chat.error") : t("desk.live.idle"));
    lifeSep.hidden = lifeRun.hidden = isNaN(when);
    if (!isNaN(when)) running(lifeRun, when); else stopped(lifeRun);
  }

  // The calm states: no chat, a chat that has not said anything, a link that dropped. One line says what and why.
  function paintCalm(data, items) {
    let title = "", why = "", button = false;
    link.hidden = !data || !data.bound;  // no chat: the window alone is the button of the calm state
    if (!data) { title = t("desk.live.reading"); }
    else if (!data.bound) {
      title = LINK_DOWN.includes(data.why) ? t("desk.live.down") : t("desk.live.none");
      why = t("board.vs.why." + (data.why || "no-chat"));
      button = data.why !== "off" && data.why !== "no-cli";
    } else if (data.loading) title = t("desk.live.reading");
    else if (!items.length) { title = t("desk.live.quiet"); why = t("desk.live.quiet.why"); }
    calm.hidden = !title;
    if (!title) { calm.replaceChildren(); calm.dataset.sig = ""; return; }
    const fresh = Boolean(data && !data.bound && st.task && st.off === "" && ["", "no-chat", "no-session"].includes(data.why || ""));
    const sig = title + "|" + why + "|" + button + "|" + fresh;
    if (calm.dataset.sig === sig) return;
    calm.dataset.sig = sig;
    const open = button ? h("button", {type: "button", class: "act hot live big"}, t(fresh ? "board.go.new" : "desk.live.open")) : null;
    if (open && fresh) open.addEventListener("click", () => chatGoOn(st.task.split("/").pop()));
    else if (open) open.addEventListener("click", () => { open.disabled = true; SERVE.openVS().then(() => { setTimeout(() => { open.disabled = false; }, 1500); }, (error) => { open.disabled = false; SERVE.failed(error, st.chat && st.chat.title); }); });
    calm.replaceChildren(...[robot(), h("h3", null, title), why ? h("p", null, why) : null, open].filter(Boolean));
  }

  function onData(data) {
    if (!data) return;
    if (typeof data.now === "number") st.skew = data.now - Date.now();
    if (data.same) { st.fails = 0; stale.hidden = true; return; }
    st.rev = data.rev || "";
    st.data = data;
    stale.hidden = true;
    const keep = new Set(data.bound ? (data.items || []).map((item) => item.id) : []);
    view(() => show(data), (node) => keep.has(node.dataset.id));
    for (const call of st.listeners) { try { call(data); } catch (error) { /* a listener must not stop the stream */ } }
  }

  // --- the poll: once a second while something wants it and the page is seen; never two at a time ---------------------
  const wanted = () => st.wants.size > 0 && Boolean(st.task) && !st.off;
  function loop() {
    st.timer = 0;
    if (!wanted() || document.hidden || st.busy) return;
    st.busy = true;
    const task = st.task;
    SERVE.post("/api/live", {task, rev: st.rev}).then((answer) => {
      if (task !== st.task) return;  // another task was opened meanwhile
      st.fails = 0;
      onData(answer.live);
    }, () => { st.fails += 1; if (st.fails >= 2) stale.hidden = false; }).then(() => {
      st.busy = false;
      if (wanted() && !document.hidden && !st.timer) st.timer = setTimeout(loop, st.fails ? SLOW : EVERY);
    });
  }
  function kick() { if (wanted() && !document.hidden && !st.timer && !st.busy) st.timer = setTimeout(loop, 0); }
  document.addEventListener("visibilitychange", () => { if (document.hidden) { clearTimeout(st.timer); st.timer = 0; } else kick(); });

  // --- what the page gives -------------------------------------------------------------------------------------------------
  return {
    node: root,
    // `task`: the folder name of the task; `off`: why nothing is followed ("" when it is: a closed task or a task not started has no chat to follow); `chat`: desk.chat (its title for the copy button).
    config(info) {
      if (info.task !== st.task) {  // another task: nothing of the first one is kept
        st.task = info.task; st.rev = ""; st.data = null; st.fails = 0;
        for (const rec of st.nodes.values()) rec.el.remove();
        st.nodes.clear();
        show(null);
      }
      if (typeof ROUNDS !== "undefined") { if (!info.off) roundsHere(ROUNDS.node); ROUNDS.follow(info.task); }
      st.chat = info.chat || null;
      const heldNow = (info.held || []).map(flat);
      const approvedNow = (info.approved || []).map(flat);
      if (heldNow.join("\n") !== st.held.join("\n") || approvedNow.join("\n") !== st.approved.join("\n")) { st.held = heldNow; st.approved = approvedNow; for (const rec of st.nodes.values()) if (rec.item) paint(rec, rec.item); }  // a card that arrives later changes how its call reads
      st.off = info.off || "";
      const nothing = st.chat && !st.chat.bound ? st.chat.why || "" : "";
      link.title = nothing === "no-cli" || nothing === "off" ? t("board.vs.why." + nothing) : t("board.vs.open");
      link.disabled = nothing === "no-cli" || nothing === "off";
      if (st.off) { clearTimeout(st.timer); st.timer = 0; }
      else if (!st.data && st.chat && !st.chat.bound) show({bound: false, why: st.chat.why || "no-chat"});  // the page already knows: no wait for the first answer
      kick();
    },
    // `key` wants the poll (the open tab, the open reply panel) or lets go of it.
    want(key, on) {
      if (on) st.wants.add(key); else st.wants.delete(key);
      if (!wanted()) { clearTimeout(st.timer); st.timer = 0; } else kick();
    },
    onChange(call) { st.listeners.push(call); },
    data: () => st.data,
    // The cards of what needs the person, drawn by desk.js (the same ones as above the tabs), go at the end of the stream, where the agent stopped.
    needs(nodes) {
      const list = nodes ? [nodes].flat(Infinity).filter((node) => node instanceof Node) : [];
      const box = needLi.lastChild;
      const same = list.length === st.needs.length && list.every((node, at) => node === st.needs[at]);
      if (same) return;
      st.needs = list;
      view(() => { box.replaceChildren(...list); needLi.hidden = list.length === 0; });
      if (st.data) paintLife(st.data);
    },
    drawing(draw) { st.draw = draw; },
    visible(on) { root.hidden = !on; if (on) kick(); },
  };
})();
