// The Terminal window (1.6.92): a small window at the top right of a served page, with tabs. A person types a command and reads the output (`boardterm.py`). It is no real terminal.
// A tab starts in the harness folder; a plain `cd` moves that tab, a bare `cd` brings it back. `cd x && y` goes to the shell: it holds for that line only.
// TERM.run(line) opens a tab and runs a command: what a button on the page uses. The tabs of this browser tab live in sessionStorage, so they survive going from page to page.
const TERM = (() => {
  const KEY = "harness.term";
  const KEEP = 20000;  // characters of a tab kept when the page changes
  const POLL = 400;
  const MIN_WIDTH = 320, MIN_HEIGHT = 180;
  const WATCH = 4000;  // ms between asks for what runs, for the count on the button
  const QUIET = 300;  // seconds with no output before the tab says so; nothing is stopped
  const memory = {open: false, tabs: [], at: 0};
  let ui = null;
  const after = new Map();
  const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify({...memory, tabs: memory.tabs.map((tab) => ({...tab, text: tab.text.slice(-KEEP)}))})); } catch (error) { /* a convenience only */ } };
  const load = () => { try { Object.assign(memory, JSON.parse(sessionStorage.getItem(KEY) || "{}")); } catch (error) { /* start empty */ } };
  const post = (body) => SERVE.post("/api/term", body).then((data) => data.result);
  const current = () => memory.tabs[memory.at] || null;
  const newTab = () => { memory.tabs.push({label: "", text: "", job: "", since: 0}); memory.at = memory.tabs.length - 1; return current(); };
  const folderOf = (path) => path.split(/[\\/]/).filter(Boolean).pop() || path;  // the whole path is the tip: the line is for typing
  const labelOf = (line) => line.replace(/^harness\s+/, "").split(/[|;&<>]/)[0].trim().split(/\s+/).slice(0, 2).join(" ").slice(0, 22);

  const clock = (seconds) => (seconds < 60 ? seconds + "s" : Math.floor(seconds / 60) + "m" + String(seconds % 60).padStart(2, "0") + "s");
  function paintStatus(tab) {  // the line of a run: the bar when the command counts its steps, always the time, and a word when it has gone quiet
    const now = tab && tab.job ? tab.status : null;
    ui.status.hidden = !(tab && tab.job);
    if (!now) { ui.bar.style.width = "0"; ui.barBox.hidden = true; ui.said.textContent = tab && tab.job ? t("term.running") : ""; return; }
    const step = now.progress && now.progress.total ? now.progress : null;
    ui.barBox.hidden = !step;
    ui.bar.style.width = step ? Math.round(100 * step.done / step.total) + "%" : "0";
    ui.said.textContent = [step ? step.done + "/" + step.total + " " + step.word : t("term.running"), clock(now.seconds || 0), now.idle >= QUIET ? t("term.quiet", {minutes: Math.floor(now.idle / 60)}) : ""].filter(Boolean).join(" \u00b7 ");
  }
  function paintCount() {  // the button says it with the window shut: how many run, and how the last one ended
    if (!ui) return;
    ui.count.hidden = !memory.running;
    ui.count.textContent = memory.running || "";
    ui.toggle.classList.toggle("busy", Boolean(memory.running));
    ui.toggle.classList.toggle("ended", memory.ended === "ok" && !memory.open);
    ui.toggle.classList.toggle("broke", memory.ended === "bad" && !memory.open);
    ui.toggle.title = memory.running ? t("term.count", {n: memory.running}) : t("term.open");
  }
  function watch() {
    post({op: "running"}).then((found) => { memory.running = found.running.length; paintCount(); setTimeout(watch, WATCH); }, () => setTimeout(watch, WATCH * 4));
  }
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
    paintStatus(tab);
    if (memory.open) memory.ended = "";
    paintCount();
    ui.mark.textContent = (tab && tab.cwd ? folderOf(tab.cwd) + " " : "") + "$";
    ui.mark.title = (tab && tab.cwd) || "";
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
      tab.text += found.text; tab.since = found.next; tab.status = found;
      if (found.done) {
        const then = after.get(tab.job);
        after.delete(tab.job);
        tab.job = "";
        memory.ended = found.code ? "bad" : "ok";
        memory.running = Math.max(0, (memory.running || 0) - 1);
        if (then && !found.code) then();
        tab.text += found.gone ? t("term.gone") + "\n" : found.code ? t("term.failed", {code: found.code}) + "\n" : "";
      } else setTimeout(() => follow(tab), POLL);
      paint();
      if (found.done && tab === current() && memory.open && document.activeElement === document.body) ui.input.focus();  // Stop took the focus; the next line goes here
    }, (error) => { tab.job = ""; tab.text += (error.message || String(error)) + "\n"; paint(); });
  }
  function move(tab, to) {
    post({op: "cd", cwd: tab.cwd || "", to}).then((found) => { tab.cwd = found.cwd; paint(); }, (error) => { tab.text += (error.message || String(error)) + "\n"; paint(); });
  }
  function submit(tab, line, done) {
    const place = line.match(/^cd(?:\s+([^;&|<>]*))?$/);
    if (place) { tab.text += (tab.text ? "\n" : "") + "$ " + line + "\n"; move(tab, (place[1] || "").trim()); return; }
    tab.label = labelOf(line); tab.text += (tab.text ? "\n" : "") + "$ " + line + "\n"; tab.since = 0;
    paint();
    post({op: "start", line, cwd: tab.cwd || ""}).then((found) => {
      if (done) after.set(found.id, done);
      const going = memory.tabs.findIndex((item) => item.job === found.id);
      if (found.again && going >= 0) {  // the run has its tab already: go there, and this new one has nothing to show
        const holder = memory.tabs[going];
        if (tab !== holder) memory.tabs.splice(memory.tabs.indexOf(tab), 1);
        memory.at = memory.tabs.indexOf(holder);
        paint();
        return;
      }
      tab.job = found.id;
      memory.running = (memory.running || 0) + (found.again ? 0 : 1);
      paint();
      follow(tab);
    }, (error) => { tab.text += (error.message || String(error)) + "\n"; paint(); });
  }
  function run(line, done) {  // `done`: what the page does when the command ends well; it holds for this page only
    memory.open = true;
    const tab = current();
    submit(tab && !tab.text && !tab.job ? tab : newTab(), line, done);
  }
  function mount() {
    if (typeof SERVE === "undefined") return;
    load();
    if (!memory.tabs.length) newTab();
    const count = h("span", {class: "term-count", hidden: ""});
    const toggle = h("button", {type: "button", class: "term-toggle", title: t("term.open"), "aria-label": t("term.open")}, ">_", count);
    const bar = h("i");
    const barBox = h("span", {class: "term-bar-box", hidden: ""}, bar);
    const statusWords = h("span", {class: "term-said"});
    const status = h("div", {class: "term-status", hidden: ""}, barBox, statusWords);
    const tabs = h("div", {class: "term-tabs"});
    const add = h("button", {type: "button", class: "term-add", title: t("term.new"), "aria-label": t("term.new")}, "+");
    const out = h("pre", {class: "term-out", tabindex: "0"});
    const input = h("input", {type: "text", class: "term-in", spellcheck: "false", autocomplete: "off", placeholder: t("term.ph"), "aria-label": t("term.title")});
    const stop = h("button", {type: "button", class: "act term-stop", hidden: ""}, t("term.stop"));
    const mark = h("span", {class: "term-mark"}, "$");
    const hide = h("button", {type: "button", class: "term-x", "aria-label": t("term.hide"), title: t("term.hide")}, "−");
    const box = h("section", {class: "term", hidden: "", "aria-label": t("term.title")}, h("div", {class: "term-bar"}, tabs, hide), out, status, h("div", {class: "term-line"}, mark, input, stop));
    ui = {box, toggle, tabs, add, out, input, stop, mark, count, bar, barBox, status, said: statusWords};
    const grip = h("span", {class: "term-grip", title: t("term.resize")});
    const sized = () => { box.style.width = memory.size ? memory.size[0] + "px" : ""; box.style.height = memory.size ? memory.size[1] + "px" : ""; };
    // The window hangs from the top right, so it grows from its bottom left corner.
    grip.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      grip.setPointerCapture(event.pointerId);
      const from = {x: event.clientX, y: event.clientY, width: box.offsetWidth, height: box.offsetHeight};
      const move = (step) => {
        memory.size = [Math.round(Math.max(MIN_WIDTH, from.width + from.x - step.clientX)), Math.round(Math.max(MIN_HEIGHT, from.height + step.clientY - from.y))];
        sized();
      };
      const stop = () => { grip.removeEventListener("pointermove", move); grip.removeEventListener("pointerup", stop); grip.removeEventListener("pointercancel", stop); save(); };
      grip.addEventListener("pointermove", move);
      grip.addEventListener("pointerup", stop);
      grip.addEventListener("pointercancel", stop);
    });
    grip.addEventListener("dblclick", () => { memory.size = null; sized(); save(); });
    const said = [];
    let back = 0;
    toggle.addEventListener("click", () => { memory.open = !memory.open; paint(); if (memory.open) input.focus(); });
    hide.addEventListener("click", () => { memory.open = false; paint(); });
    add.addEventListener("click", () => { move(newTab(), ""); input.value = ""; paint(); input.focus(); });
    stop.addEventListener("click", () => { const tab = current(); if (tab && tab.job) post({op: "stop", id: tab.job}).catch(() => {}); });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && input.value.trim() && !(current() && current().job)) {
        said.push(input.value.trim()); back = 0;
        submit(current(), input.value.trim());
        input.value = "";
      } else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
        event.preventDefault();
        back = Math.max(0, Math.min(said.length, back + (event.key === "ArrowUp" ? 1 : -1)));
        input.value = back ? said[said.length - back] : "";
      }
    });
    box.append(grip);
    document.body.append(toggle, box);
    sized();
    paint();
    memory.tabs.forEach((tab) => { follow(tab); if (!tab.cwd) move(tab, ""); });
    watch();
  }
  return {mount, run};
})();
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", TERM.mount); else TERM.mount();
