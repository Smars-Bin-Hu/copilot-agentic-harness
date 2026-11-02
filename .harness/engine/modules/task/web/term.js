// The Terminal window (1.6.92): a small window at the top right of a served page, with tabs. A person types a `harness` command and reads the output (`boardterm.py`). It is no real terminal.
// TERM.run(line) opens a tab and runs a command: what a button on the page uses. The tabs of this browser tab live in sessionStorage, so they survive going from page to page.
const TERM = (() => {
  const KEY = "harness.term";
  const KEEP = 20000;  // characters of a tab kept when the page changes
  const POLL = 400;
  const memory = {open: false, tabs: [], at: 0};
  let ui = null;
  const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify({...memory, tabs: memory.tabs.map((tab) => ({...tab, text: tab.text.slice(-KEEP)}))})); } catch (error) { /* a convenience only */ } };
  const load = () => { try { Object.assign(memory, JSON.parse(sessionStorage.getItem(KEY) || "{}")); } catch (error) { /* start empty */ } };
  const post = (body) => SERVE.post("/api/term", body).then((data) => data.result);
  const current = () => memory.tabs[memory.at] || null;
  const newTab = () => { memory.tabs.push({label: "", text: "", job: "", since: 0}); memory.at = memory.tabs.length - 1; return current(); };
  const labelOf = (line) => line.replace(/^harness\s+/, "").split(/\s+/).slice(0, 2).join(" ").slice(0, 22);

  function paint() {
    if (!ui) return;
    ui.box.hidden = !memory.open;
    ui.toggle.classList.toggle("on", memory.open);
    ui.tabs.replaceChildren(...memory.tabs.map((tab, index) => {
      const shut = h("button", {type: "button", class: "term-x", "aria-label": t("term.close"), title: t("term.close")}, "×");
      shut.addEventListener("click", (event) => { event.stopPropagation(); close(index); });
      const name = h("button", {type: "button", class: "term-tab" + (index === memory.at ? " on" : "") + (tab.job ? " busy" : "")}, tab.label || t("term.title"));
      name.addEventListener("click", () => { memory.at = index; paint(); });
      return h("span", {class: "term-tabwrap"}, name, shut);
    }), ui.add);
    const tab = current();
    ui.out.textContent = tab ? tab.text : "";
    ui.out.scrollTop = ui.out.scrollHeight;
    ui.stop.hidden = !(tab && tab.job);
    ui.input.disabled = Boolean(tab && tab.job);
    save();
  }
  function close(index) {
    const tab = memory.tabs[index];
    if (tab.job) post({op: "stop", id: tab.job}).catch(() => {});
    memory.tabs.splice(index, 1);
    memory.at = Math.max(0, Math.min(memory.at, memory.tabs.length - 1));
    if (!memory.tabs.length) newTab();
    paint();
  }
  function follow(tab) {
    if (!tab.job) return;
    post({op: "read", id: tab.job, since: tab.since}).then((found) => {
      tab.text += found.text; tab.since = found.next;
      if (found.done) {
        tab.job = "";
        tab.text += found.gone ? t("term.gone") + "\n" : found.code ? t("term.failed", {code: found.code}) + "\n" : "";
      } else setTimeout(() => follow(tab), POLL);
      paint();
    }, (error) => { tab.job = ""; tab.text += (error.message || String(error)) + "\n"; paint(); });
  }
  function submit(tab, line) {
    tab.label = labelOf(line); tab.text += (tab.text ? "\n" : "") + "$ " + line + "\n"; tab.since = 0;
    paint();
    post({op: "start", line}).then((found) => { tab.job = found.id; paint(); follow(tab); }, (error) => { tab.text += (error.message || String(error)) + "\n"; paint(); });
  }
  function run(line) {
    memory.open = true;
    const tab = current();
    submit(tab && !tab.text && !tab.job ? tab : newTab(), line);
  }
  function mount() {
    if (typeof SERVE === "undefined") return;
    load();
    if (!memory.tabs.length) newTab();
    const toggle = h("button", {type: "button", class: "term-toggle", title: t("term.open"), "aria-label": t("term.open")}, ">_");
    const tabs = h("div", {class: "term-tabs"});
    const add = h("button", {type: "button", class: "term-add", title: t("term.new"), "aria-label": t("term.new")}, "+");
    const out = h("pre", {class: "term-out", tabindex: "0"});
    const input = h("input", {type: "text", class: "term-in", spellcheck: "false", autocomplete: "off", placeholder: t("term.ph"), "aria-label": t("term.title")});
    const stop = h("button", {type: "button", class: "act term-stop", hidden: ""}, t("term.stop"));
    const hide = h("button", {type: "button", class: "term-x", "aria-label": t("term.hide"), title: t("term.hide")}, "−");
    const box = h("section", {class: "term", hidden: "", "aria-label": t("term.title")}, h("div", {class: "term-bar"}, tabs, hide), out, h("div", {class: "term-line"}, h("span", {class: "term-mark"}, "$"), input, stop));
    ui = {box, toggle, tabs, add, out, input, stop};
    const said = [];
    let back = 0;
    toggle.addEventListener("click", () => { memory.open = !memory.open; paint(); if (memory.open) input.focus(); });
    hide.addEventListener("click", () => { memory.open = false; paint(); });
    add.addEventListener("click", () => { newTab(); paint(); input.focus(); });
    stop.addEventListener("click", () => { const tab = current(); if (tab && tab.job) post({op: "stop", id: tab.job}).catch(() => {}); });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && input.value.trim()) {
        said.push(input.value.trim()); back = 0;
        submit(current(), input.value.trim());
        input.value = "";
      } else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
        event.preventDefault();
        back = Math.max(0, Math.min(said.length, back + (event.key === "ArrowUp" ? 1 : -1)));
        input.value = back ? said[said.length - back] : "";
      }
    });
    document.body.append(toggle, box);
    paint();
    memory.tabs.forEach(follow);
  }
  return {mount, run};
})();
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", TERM.mount); else TERM.mount();
