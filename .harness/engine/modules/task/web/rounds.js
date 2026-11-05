// The earlier rounds of a task's chat, at the top of the Live tab (1.6.55): one line for each prompt of the person, opened to read the prompt and all the agent wrote for it.
// Only the last 5 are shown (1.6.108): the older ones are folded under one button, so the tab does not grow with the chat. The server reads them from Copilot's own record, or from the task's saved transcript (chatrounds.py), so this works with VS Code closed.
// Each line ends with what the round took (1.6.98): its time, its credits and its tools, as icons with the words in their tip. The round that still runs counts its time on the page.
// Each line also has the rewind icon (1.6.109): back to before that message, the chat and the task's files; its tip says what it does or why it cannot. A click shows what changes first.
// The icons' words are in the page's tip card (status.js: `data-tip`), on hover and on keyboard focus, not in a `title` the keyboard never shows.
// Needs common.js (h, t, when, clock, amount, lineSvg), serve.js (SERVE), live.js (LIVE), status.js (Status: the one clock of the page), reply.js (REPLY). Drawn with DOM nodes and textContent only.
const ROUNDS = (function () {
  const SHOWN = 5;
  const ICONS = {
    time: [["circle", {cx: 8, cy: 8, r: 6}], ["path", {d: "M8 4.8V8l2.2 1.4"}]],  // clock
    credits: [["ellipse", {cx: 8, cy: 4.6, rx: 5, ry: 2}], ["path", {d: "M3 4.6v6.8c0 1.1 2.2 2 5 2s5-.9 5-2V4.6M3 8c0 1.1 2.2 2 5 2s5-.9 5-2"}]],  // a stack of coins
    tools: [["path", {d: "M9.8 2.4a3.3 3.3 0 0 0-3.9 4.3L2.4 10.2a1.3 1.3 0 0 0 1.8 1.8l3.5-3.5a3.3 3.3 0 0 0 4.3-3.9l-2 2-1.6-.4-.4-1.6z"}]],  // wrench
    rewind: [["path", {d: "M3.6 7.2A4.8 4.8 0 1 1 4.4 11"}], ["path", {d: "M3.4 3.4v3.9h3.9"}]],  // an arrow that turns back
  };
  const tipped = (node, key, tip) => { node._tip = tip; node.setAttribute("data-tip", key); return node; };
  const stat = (kind, n, tip, value) => tipped(h("span", {class: "rd-stat", "aria-label": tip}, lineSvg(ICONS[kind]), value), "rd-" + n + "-" + kind, () => tip);
  function stats(item, running) {
    const parts = [];
    if (running) parts.push(stat("time", item.n, t("desk.rounds.time.now"), h("span", {class: "st-run", "data-since": String(Date.parse(item.at))}, h("span", {class: "st-time"}, clock(item.seconds)))));
    else if (item.seconds !== null && item.seconds !== undefined) parts.push(stat("time", item.n, t("desk.rounds.time", {time: clock(item.seconds)}), clock(item.seconds)));
    if (item.aiu !== null && item.aiu !== undefined) parts.push(stat("credits", item.n, t("desk.rounds.credits", {n: amount(item.aiu)}), amount(item.aiu)));
    if (item.tools) parts.push(stat("tools", item.n, t("desk.rounds.count", {n: item.tools}), String(item.tools)));
    return parts;
  }
  const st = {task: "", list: [], open: false, nodes: new Map(), state: "", draw: null};
  const more = h("button", {type: "button", class: "rd-more", hidden: "", "aria-expanded": "false"});
  const rows = h("div", {class: "rd-rows"});
  const box = h("section", {class: "rd", hidden: "", "aria-label": t("desk.rounds.title")}, h("h3", {class: "rd-title"}, t("desk.rounds.title")), more, rows);

  async function fill(body, n) {
    body.replaceChildren(h("p", {class: "sub"}, "..."));
    try {
      const found = (await SERVE.post("/api/rounds", {op: "one", task: st.task, n})).result;
      const tools = Object.entries(found.tools).map(([name, count]) => (count > 1 ? name + " × " + count : name)).join(", ");
      body.replaceChildren(...[h("div", {class: "rd-who sub"}, t("desk.rounds.you")), h("div", {class: "rd-prompt"}, found.prompt),
        h("div", {class: "rd-who sub"}, t("desk.rounds.agent")),
        found.texts.length ? h("div", {class: "rd-text"}, found.texts.map((blocks) => h("div", {class: "rd-part"}, st.draw ? st.draw(blocks) : null))) : h("p", {class: "sub"}, t("desk.rounds.none")),
        tools ? h("p", {class: "sub rd-tools"}, t("desk.rounds.tools", {tools})) : null, found.cut ? h("p", {class: "sub"}, t("desk.rounds.cut")) : null].filter(Boolean));
    } catch (error) {
      body.replaceChildren(h("p", {class: "bad"}, (error && error.message) || String(error)));
    }
  }

  function make(item) {
    const count = h("span", {class: "sub rd-stats"});
    const body = h("div", {class: "rd-body"});
    const back = tipped(h("button", {type: "button", class: "rd-rw"}, lineSvg(ICONS.rewind)), "rd-" + item.n + "-rewind", null);
    const rec = {count, back, item};
    back.addEventListener("click", (event) => {  // inside the summary: the click must not open or fold the round
      event.preventDefault();
      event.stopPropagation();
      if (!back.classList.contains("off")) rewindAsk(rec.item);
    });
    const node = h("details", {class: "rd-row", "data-n": String(item.n)}, h("summary", null, h("span", {class: "sub rd-at"}, when(item.at)), h("span", {class: "rd-head"}, item.head || t("desk.rounds.empty")), count, back), body);
    node.addEventListener("toggle", () => { if (node.open) fill(body, item.n); });
    rec.node = node;
    return rec;
  }

  // Why the chat cannot go back now, whatever the round: VS Code not linked, the agent at work, a question waiting. Empty: the chat is idle.
  function chatWhy() {
    if (!(LIVE.data() || {}).bound) return t("desk.rewind.away");
    return st.state === "idle" ? "" : t(st.state === "busy" ? "desk.rewind.busy" : st.state === "input" ? "desk.rewind.input" : "desk.rewind.wait");
  }

  // The rewind icon of a round: on when the server found its restore point and nothing stands in the way, and the chat is idle. Not `disabled`: a disabled button shows no tip.
  // Its tip: what goes back and how many messages leave the chat (`after`: this round and the ones after it; the preview counts the chat's own turns), or why it cannot.
  function paintBack(rec, item, after) {
    const mark = item.rewind || {seq: null, why: "none"};
    const why = mark.why ? t("desk.rewind.why." + mark.why) : chatWhy();
    const head = t(why ? "desk.rewind.off" : "desk.rewind.icon");
    const body = why || t("desk.rewind.tip", {n: after});
    rec.back.classList.toggle("off", Boolean(why));
    rec.back.setAttribute("aria-disabled", why ? "true" : "false");
    rec.back.setAttribute("aria-label", head + ". " + body);
    rec.back._tip = () => h("div", null, h("div", {class: "st-head"}, head), h("div", {class: "st-tx"}, body));
  }

  // What going back changes, then the act: the files and the chat go back, the words of the message come back to the reply box.
  function rewindAsk(item) {
    const task = st.task;
    const said = h("div", {class: "bad"});
    const view = SERVE.dialog([h("h2", null, t("desk.rewind.title")), h("p", {class: "sub"}, "..."), said]);
    SERVE.post("/api/rewind", {task, seq: item.rewind.seq, step: "preview"}).then((data) => {
      const found = data.result;
      const words = {back: "desk.rewind.back", removed: "desk.rewind.removed", lost: "desk.rewind.lost"};
      const list = (key) => (found.counts[key] ? h("details", {class: "rw-list"}, h("summary", null, t(words[key], {n: found.counts[key]})),
        h("ul", null, found[key].map((name) => h("li", null, h("code", null, name))), found.counts[key] > found[key].length ? h("li", {class: "sub"}, "…") : null)) : null);
      const go = h("button", {type: "button", class: "act hot"}, t("desk.rewind.go"));
      const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
      const files = found.counts.back + found.counts.removed + found.counts.lost;
      view.box.replaceChildren(...[h("h2", null, t("desk.rewind.title")), h("p", {class: "rw-said"}, h("span", {class: "sub"}, when(item.at)), " ", item.head || ""),
        h("p", null, t("desk.rewind.turns", {n: found.turns})), files ? h("div", {class: "rw-files"}, list("back"), list("removed"), list("lost")) : h("p", {class: "sub"}, t("desk.rewind.same")),
        found.req === "lost" ? h("p", {class: "rw-plan"}, t("desk.rewind.req")) : null,  // only when it is so: the confirmation of the requirement is lost
        found.plan === "lost" ? h("p", {class: "rw-plan"}, t("desk.rewind.plan")) : null,  // and the approval of the plan
        h("p", {class: "sub"}, t("desk.rewind.outside")), said, h("div", {class: "row send-actions"}, go, no)].filter(Boolean));
      no.addEventListener("click", view.close);
      go.addEventListener("click", () => {
        go.disabled = true;
        SERVE.post("/api/rewind", {task, seq: item.rewind.seq, step: "act"}).then((done) => {
          view.close();
          if (typeof REPLY !== "undefined") REPLY.restore(done.result);
          SERVE.done();
          load();
          setTimeout(load, 2500);  // Copilot rewrites its record a moment later
        }, (error) => { go.disabled = false; said.replaceChildren(...SERVE.reasons((error && error.message) || String(error))); });
      });
      go.focus();
    }, (error) => { said.replaceChildren(...SERVE.reasons((error && error.message) || String(error))); });
  }

  // Rounds go in or out above what is being read, and the reading place stays: the browser keeps it itself (scroll anchoring, 1.6.108: moving the page too sent it twice as far);
  // one that cannot is moved here by the same height. A folded round keeps its node, open or not, for when it is shown again.
  const ANCHORS = typeof CSS !== "undefined" && typeof CSS.supports === "function" && CSS.supports("overflow-anchor", "auto");
  function paint() {
    const list = st.open ? st.list : st.list.slice(-SHOWN);
    const before = document.documentElement.scrollHeight;
    const above = rows.firstChild ? rows.firstChild.getBoundingClientRect().top < 0 : false;
    const keep = new Set(list.map((item) => String(item.n)));
    for (const node of [...rows.children]) if (!keep.has(node.dataset.n)) node.remove();
    let next = rows.firstChild;
    const newest = st.list.length ? st.list[st.list.length - 1] : null;
    const began = Date.parse((LIVE.data() || {}).started || "");
    // the newest round still runs: its time is counted here, its credits come with the next list. Only the round of the running turn (Copilot may not have written its prompt yet)
    const busy = ["busy", "input"].includes(st.state) && newest && !(Date.parse(newest.at) < began - 60000);
    const last = newest ? newest.n : -1;
    // how many messages leave the chat with each round: the person's own. The harness's message at the end of a round is part of that round in the chat (hand test 2026-11-04)
    const leave = new Map();
    let count = 0;
    for (let i = st.list.length - 1; i >= 0; i--) {
      if (!(st.list[i].rewind && st.list[i].rewind.why === "harness")) count++;
      leave.set(st.list[i].n, count);
    }
    for (const item of list) {
      let rec = st.nodes.get(item.n);
      if (rec && rec.item.at !== item.at) {  // the chat was cut back (rewind, withdraw) and another message has this place now: a line of its own, not the old one's words
        if (rec.node === next) next = next.nextSibling;
        rec.node.remove();
        rec = null;
      }
      if (!rec) { rec = make(item); st.nodes.set(item.n, rec); }
      const sig = [item.seconds, item.aiu, item.tools, busy && item.n === last].join();
      if (rec.count.dataset.sig !== sig) { rec.count.dataset.sig = sig; rec.count.replaceChildren(...stats(item, busy && item.n === last)); }
      rec.item = item;
      paintBack(rec, item, leave.get(item.n));
      if (rec.node === next) next = next.nextSibling;
      else rows.insertBefore(rec.node, next);
    }
    const older = Math.max(0, st.list.length - SHOWN);
    more.hidden = !older;
    more.textContent = t(st.open ? "desk.rounds.fold" : "desk.rounds.more", {n: older});
    more.setAttribute("aria-expanded", String(st.open));
    more.classList.toggle("is-open", st.open);
    box.hidden = !st.list.length;
    if (busy && typeof Status !== "undefined") Status.clock();
    if (above && !ANCHORS) window.scrollBy({top: document.documentElement.scrollHeight - before, behavior: "instant"});
  }

  function load() {
    if (!st.task) return;
    const task = st.task;
    SERVE.post("/api/rounds", {op: "list", task}).then((data) => {
      if (task !== st.task) return;
      st.list = data.result.rounds;
      paint();
    }, () => {});
  }

  more.addEventListener("click", () => { st.open = !st.open; paint(); });
  let again = 0;
  LIVE.onChange(() => {
    const now = (LIVE.data() || {}).state || "";
    if (now === st.state) return;
    st.state = now; load();
    clearTimeout(again);
    if (now === "busy") again = setTimeout(load, 4000);  // Copilot writes the prompt of a new turn a moment after the turn starts: its line comes then, with its running time
  });

  return {
    node: box,
    drawing(draw) { st.draw = draw; },
    follow(task) {
      if (task === st.task) return;
      st.task = task; st.list = []; st.open = false; st.state = "";
      st.nodes.clear();
      rows.replaceChildren();
      box.hidden = true;
      load();
    },
  };
})();
