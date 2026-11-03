// The earlier rounds of a task's chat, at the top of the Live tab (1.6.55): one line for each prompt of the person, opened to read the prompt and all the agent wrote for it.
// Scrolling up shows older rounds. The server reads them from Copilot's own record, or from the task's saved transcript (chatrounds.py), so this works with VS Code closed.
// Each line ends with what the round took (1.6.98): its time, its credits and its tools, as icons with the words in their tip. The round that still runs counts its time on the page.
// Needs common.js (h, t, when, clock, amount, lineSvg), serve.js (SERVE), live.js (LIVE), status.js (Status: the one clock of the page). Drawn with DOM nodes and textContent only.
const ROUNDS = (function () {
  const STEP = 20;
  const ICONS = {
    time: [["circle", {cx: 8, cy: 8, r: 6}], ["path", {d: "M8 4.8V8l2.2 1.4"}]],  // clock
    credits: [["ellipse", {cx: 8, cy: 4.6, rx: 5, ry: 2}], ["path", {d: "M3 4.6v6.8c0 1.1 2.2 2 5 2s5-.9 5-2V4.6M3 8c0 1.1 2.2 2 5 2s5-.9 5-2"}]],  // a stack of coins
    tools: [["path", {d: "M9.8 2.4a3.3 3.3 0 0 0-3.9 4.3L2.4 10.2a1.3 1.3 0 0 0 1.8 1.8l3.5-3.5a3.3 3.3 0 0 0 4.3-3.9l-2 2-1.6-.4-.4-1.6z"}]],  // wrench
  };
  const stat = (kind, tip, value) => h("span", {class: "rd-stat", title: tip, "aria-label": tip}, lineSvg(ICONS[kind]), value);
  function stats(item, running) {
    const parts = [];
    if (running) parts.push(stat("time", t("desk.rounds.time.now"), h("span", {class: "st-run", "data-since": String(Date.parse(item.at))}, h("span", {class: "st-time"}, clock(item.seconds)))));
    else if (item.seconds !== null && item.seconds !== undefined) parts.push(stat("time", t("desk.rounds.time", {time: clock(item.seconds)}), clock(item.seconds)));
    if (item.aiu !== null && item.aiu !== undefined) parts.push(stat("credits", t("desk.rounds.credits", {n: amount(item.aiu)}), amount(item.aiu)));
    if (item.tools) parts.push(stat("tools", t("desk.rounds.count", {n: item.tools}), String(item.tools)));
    return parts;
  }
  const st = {task: "", list: [], shown: STEP, nodes: new Map(), state: "", draw: null};
  const more = h("button", {type: "button", class: "rd-more", hidden: ""});
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
    const node = h("details", {class: "rd-row"}, h("summary", null, h("span", {class: "sub rd-at"}, when(item.at)), h("span", {class: "rd-head"}, item.head || t("desk.rounds.empty")), count), body);
    node.addEventListener("toggle", () => { if (node.open) fill(body, item.n); });
    return {node, count};
  }

  // Older rounds go in above what is being read: the page is moved by the same height, so the reading place stays.
  function paint() {
    const list = st.list.slice(-st.shown);
    const before = document.documentElement.scrollHeight;
    const above = rows.firstChild ? rows.firstChild.getBoundingClientRect().top < 0 : false;
    let next = rows.firstChild;
    const newest = st.list.length ? st.list[st.list.length - 1] : null;
    const began = Date.parse((LIVE.data() || {}).started || "");
    // the newest round still runs: its time is counted here, its credits come with the next list. Only the round of the running turn (Copilot may not have written its prompt yet)
    const busy = ["busy", "input"].includes(st.state) && newest && !(Date.parse(newest.at) < began - 60000);
    const last = newest ? newest.n : -1;
    for (const item of list) {
      let rec = st.nodes.get(item.n);
      if (!rec) { rec = make(item); st.nodes.set(item.n, rec); }
      const sig = [item.seconds, item.aiu, item.tools, busy && item.n === last].join();
      if (rec.count.dataset.sig !== sig) { rec.count.dataset.sig = sig; rec.count.replaceChildren(...stats(item, busy && item.n === last)); }
      if (rec.node === next) next = next.nextSibling;
      else rows.insertBefore(rec.node, next);
    }
    const left = st.list.length - list.length;
    more.hidden = !left;
    more.textContent = t("desk.rounds.more", {n: left});
    box.hidden = !st.list.length;
    if (busy && typeof Status !== "undefined") Status.clock();
    if (above) window.scrollBy({top: document.documentElement.scrollHeight - before, behavior: "instant"});
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

  more.addEventListener("click", () => { st.shown += STEP; paint(); });
  if (typeof IntersectionObserver !== "undefined") new IntersectionObserver((seen) => { if (seen.some((item) => item.isIntersecting) && !more.hidden) { st.shown += STEP; paint(); } }).observe(more);
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
      st.task = task; st.list = []; st.shown = STEP; st.state = "";
      st.nodes.clear();
      rows.replaceChildren();
      box.hidden = true;
      load();
    },
  };
})();
