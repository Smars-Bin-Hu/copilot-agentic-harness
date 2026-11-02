// The earlier rounds of a task's chat, at the top of the Live tab (1.6.55): one line for each prompt of the person, opened to read the prompt and all the agent wrote for it.
// Scrolling up shows older rounds. The server reads them from Copilot's own record, or from the task's saved transcript (chatrounds.py), so this works with VS Code closed.
// Needs common.js (h, t, when), serve.js (SERVE), live.js (LIVE). Drawn with DOM nodes and textContent only.
const ROUNDS = (function () {
  const STEP = 20;
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
    const count = h("span", {class: "sub rd-count"});
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
    for (const item of list) {
      let rec = st.nodes.get(item.n);
      if (!rec) { rec = make(item); st.nodes.set(item.n, rec); }
      rec.count.textContent = item.tools ? t("desk.rounds.count", {n: item.tools}) : "";
      if (rec.node === next) next = next.nextSibling;
      else rows.insertBefore(rec.node, next);
    }
    const left = st.list.length - list.length;
    more.hidden = !left;
    more.textContent = t("desk.rounds.more", {n: left});
    box.hidden = !st.list.length;
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
  LIVE.onChange(() => {
    const now = (LIVE.data() || {}).state || "";
    if (now !== st.state) { st.state = now; load(); }
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
