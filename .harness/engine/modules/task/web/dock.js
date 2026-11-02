// The buttons at the bottom right (1.6.61): the question mark and the one-click chats. The gear is shell.js's. The book opens the knowledge base window, the sliders the setup, the house the Enter screen.
// DOCK.start asks with the whole message in view, sends, and brings VS Code forward. Needs common.js (h, t), serve.js (SERVE).
const DOCK = (function () {
  const BOOK = "https://smarshu.com/book/";
  const ENTERED = "harness.entered";  // enter.js: the Enter screen was seen in this tab
  const ask = (step, body) => SERVE.post("/api/skill", {step, ...body}).then((data) => data.result);

  function done() {
    const close = h("button", {type: "button", class: "act hot"}, t("board.new.close"));
    const view = SERVE.dialog([h("h2", null, t("dock.sent")), h("p", null, t("dock.sent.where")), h("div", {class: "row"}, close)]);
    close.addEventListener("click", view.close);
  }

  // `back`: what to open again when the person steps back; the place they came from.
  const backButton = (view, back) => {
    const button = h("button", {type: "button", class: "act"}, t("dock.back"));
    button.addEventListener("click", () => { view.close(); back(); });
    return button;
  };

  function start(skill, words, back) {
    const lang = document.documentElement.lang === "zh" ? "zh" : "en";
    const body = {skill, words: words || "", lang};
    const preview = h("pre", {class: "send-preview"}, "...");
    const said = h("div", {class: "bad"});
    const go = h("button", {type: "button", class: "act hot", disabled: "disabled"}, t("dock.send"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const copy = h("button", {type: "button", class: "act", "data-label": t("dock.copy"), hidden: ""}, t("dock.copy"));  // with VS Code away, the words can still go into a chat by hand
    const again = h("button", {type: "button", class: "act", hidden: ""}, t("dock.again"));
    const view = SERVE.dialog([h("h2", null, t("dock.title")), h("p", {class: "sub"}, t("dock.hint")), preview, said, h("div", {class: "row"}, go, again, copy, no)]);
    no.addEventListener("click", view.close);
    if (back) no.before(backButton(view, back));
    copy.addEventListener("click", () => copyCommand(copy, preview.textContent));
    const check = () => ask("preview", body).then((found) => {
      preview.textContent = found.text;
      said.replaceChildren(...(found.blocked ? SERVE.reasons(found.blocked) : []));
      go.disabled = Boolean(found.blocked);
      copy.hidden = again.hidden = !found.blocked;
    }, (error) => { preview.textContent = ""; said.replaceChildren(...SERVE.reasons(error.message || error)); });
    again.addEventListener("click", check);
    check();
    go.addEventListener("click", () => {
      go.disabled = true;
      ask("act", body).then(() => { view.close(); done(); }, (error) => { go.disabled = false; said.replaceChildren(...SERVE.reasons(error.message || error)); });
    });
  }

  // The window of all skills: what the skills say of themselves (core/skillboard.py). Words of a skill are shown as text.
  function allSkills(only, back, kept) {  // `kept`: the search, the scroll and the typed words, when the person steps back to this window
    const memory = kept || {word: "", top: 0, typed: {}};
    const search = h("input", {type: "text", class: "code", autocomplete: "off", spellcheck: "false", placeholder: t("dock.skills.search")});
    search.value = memory.word;
    const list = h("div", {class: "dock-list"});
    const no = h("button", {type: "button", class: "act"}, t("board.new.close"));
    const view = SERVE.dialog([h("h2", null, t(only === "kb" ? "dock.skills.kb" : "dock.skills")), search, list, h("div", {class: "row"}, no)]);
    view.box.classList.add("dock-window");
    view.holds = () => Object.values(memory.typed).some((text) => text.trim());  // the words for a skill count; the search does not
    no.addEventListener("click", view.close);
    if (back) no.before(backButton(view, back));
    let found = [];
    const start = (item, words) => {
      memory.word = search.value;
      memory.top = list.scrollTop;
      view.close();
      const again = () => allSkills(only, back, memory);
      if (item.opens === "task") CHAT.create({kind: item.kind, text: "Use the skill " + item.name + "." + (words ? " " + words : ""), note: t("dock.task.note"), back: again});
      else DOCK.start(item.name, words || item.words, again);
    };
    const row = (item) => {
      const words = item.hint ? h("input", {type: "text", class: "code", maxlength: 2000, placeholder: item.hint, "aria-label": item.hint}) : null;
      if (words) {
        words.value = memory.typed[item.label] || "";
        words.addEventListener("input", () => { memory.typed[item.label] = words.value; });
      }
      const go = item.href ? h("a", {class: "act", href: item.href, target: "_blank", rel: "noopener noreferrer"}, t("dock.open")) : item.opens === "reply" ? h("span", {class: "tag"}, t("dock.intask")) : h("button", {type: "button", class: "act"}, t("dock.start"));
      if (go.tagName === "BUTTON") go.addEventListener("click", () => start(item, words ? words.value : ""));
      return h("div", {class: "dock-skill"}, h("div", {class: "dock-about"}, h("b", {title: item.name}, item.label), item.costly ? h("span", {class: "tag hot", title: t("dock.costly.hint")}, t("dock.costly")) : null, item.gone ? h("span", {class: "tag", title: t("dock.gone.hint")}, t("dock.gone")) : null, h("p", {class: "sub"}, item.about), item.opens === "reply" ? h("p", {class: "sub"}, t("dock.intask.hint")) : null, words), go);
    };
    function paint() {
      const wanted = search.value.toLowerCase().split(/\s+/).filter(Boolean);
      const hits = (item) => { const text = [item.label, item.name, item.about, item.hint].join(" ").toLowerCase(); return wanted.every((word) => text.includes(word)); };
      const shown = found.filter((item) => (!only || item.group === only || item.place.includes(only) || item.place.includes("all")) && hits(item));
      const groups = [["own", (item) => item.own], ...["harness", "kb", "task"].map((key) => [key, (item) => !item.own && item.group === key])];
      list.replaceChildren(...groups.flatMap(([key, test]) => {
        const items = shown.filter(test);
        const out = items.length && !only ? [h("h3", null, t("dock.group." + key))] : [];  // a window of one part has its name as its title
        items.forEach((item, index) => {
          if (key !== "own" && item.step && (!index || items[index - 1].step !== item.step)) out.push(h("h4", null, t("dock.step." + item.step)));
          out.push(row(item));
        });
        return out;
      }));
      if (!shown.length) list.append(h("p", {class: "sub"}, t("dock.skills.none")));
    }
    search.addEventListener("input", paint);
    const extra = [  // two that are not a skill of their own
      {name: "book", label: t("dock.book"), about: t("dock.book.about"), href: BOOK, opens: "link", place: ["ask"], group: "harness", order: 2},
      {name: "harness-rookie-wondering", label: t("dock.kbwhy"), about: t("dock.kbwhy.about"), words: "Topic 16: the knowledge base from code", opens: "chat", place: ["kb"], group: "kb", order: 1, step: "start"}];
    ask("list", {}).then((data) => { found = [...data.skills, ...extra].sort((one, two) => one.order - two.order); paint(); list.scrollTop = memory.top; }, (error) => list.replaceChildren(h("p", {class: "bad"}, error.message || String(error))));
  }

  // The knowledge base window: a page over the page, read only; a button with "chat" in it opens a chat (kbview.py, core/kbstatus.py).
  // A view asked for the first time in a window is worked out again, so what changed since shows; the kept one stays on the page until the new one is there.
  function kbWindow(tab) {
    const stage = h("div", {class: "dock-list kb-body"});
    const no = h("button", {type: "button", class: "act"}, t("board.new.close"));
    const age = h("span", {class: "sub kb-age"});
    const again = h("button", {type: "button", class: "act"}, t("dock.kb.refresh"));
    const tabs = ["overview", "atlas", "domains", "lookup", "health"].map((key) => { const tab = h("button", {type: "button", class: "chip", "data-key": key}, t(key === "domains" ? "dock.kb.domains.tab" : "dock.kb." + key)); tab.addEventListener("click", () => show(key)); return tab; });
    const alarm = h("p", {class: "bad kb-alarm", hidden: ""});  // outside the stage: a drawn view stays as it is
    const view = SERVE.dialog([h("h2", null, t("dock.kb")), h("div", {class: "kb-bar"}, h("div", {class: "chips dock-tabs"}, tabs), age, again), alarm, stage, h("div", {class: "row"}, no)]);
    view.box.classList.add("dock-window", "kb-window");
    view.holds = () => false;  // it only reads: nothing here can be lost
    let timer = 0, current = "", drawn = "", word = "", searched = "", ticket = 0;  // word, searched: what was typed in Look up, kept while the tab changes; ticket: the newest search
    const asked = new Set();
    no.addEventListener("click", view.close);
    const post = (body) => SERVE.post("/api/kb", body).then((data) => data.result);
    const leave = (then) => () => { view.close(); then(); };
    const ago = (seconds) => (seconds < 60 ? t("dock.kb.age.now") : t("dock.kb.age", {n: Math.round(seconds / 60)}));
    function load(op, paint, fresh, wait) {
      const key = current;
      post({op, fresh}).then((found) => {
        if (!view.box.isConnected || key !== current) return;  // a late answer belongs to a tab that is gone
        age.textContent = found.running ? t("dock.kb.updating") : found.age === null ? "" : ago(found.age);
        const seen = JSON.stringify(found.result);
        if (found.result && seen !== drawn) { drawn = seen; paint(found.result); }
        alarm.textContent = found.error;
        alarm.hidden = !found.error || found.running;
        if (!found.result) stage.replaceChildren(...(found.running || !found.error ? [h("p", {class: "sub"}, t("dock.kb.working"))] : []));
        if (found.running) timer = setTimeout(() => load(op, paint, false, Math.min((wait || 150) * 2, 1200)), wait || 150);
      }, (error) => { if (view.box.isConnected && key === current) stage.replaceChildren(h("p", {class: "bad"}, error.message || String(error))); });
    }
    const nextButton = (stageName) => {  // the first two steps are done in the setup, not in a chat
      const inSetup = ["targets", "kb_repo"].includes(stageName);
      const go = h("button", {type: "button", class: "act hot"}, t(inSetup ? "dock.setup" : "dock.kb.next"));
      go.addEventListener("click", leave(inSetup ? setupWindow : () => start("harness-rookie-new-knowledgebase", "", () => kbWindow(current))));
      return go;
    };
    // Why a step is not done, when the status knows: a broken toolkit, facts the map does not find, repositories it does not cover.
    const notes = (found) => found.steps.flatMap((item) => [...(item.problems || []), item.problem, item.note, item.no_toolkit ? t("dock.kb.map.notoolkit", {names: item.no_toolkit.join(", ")}) : "", item.step === "map" && item.facts && !item.done ? t("dock.kb.map.facts", {facts: item.facts}) : ""].filter(Boolean)).map((line) => h("p", {class: "su-warn"}, line));
    function overview(found) {
      const built = found.stage === "maintain" && found.steps.every((item) => item.done);
      stage.replaceChildren(...[h("ol", {class: "kb-steps"}, found.steps.map((item) => h("li", {class: item.done ? "done" : item.step === found.stage ? "now" : ""}, (item.done ? "\u2713 " : "") + t("dock.kb.step." + item.step)))),
        h("p", {class: "kb-what"}, t("dock.kb.what." + (built ? "built" : found.stage))), ...notes(found),
        h("div", {class: "kb-nums"}, h("span", null, t("dock.kb.domains", {n: found.domains.length})), h("span", null, t("dock.kb.requests", {n: found.requests_open}))), built ? null : nextButton(found.stage)].filter(Boolean));
    }
    function domains(found) {
      if (!found.domains.length) { stage.replaceChildren(h("p", {class: "sub"}, t("dock.kb.nodomains")), nextButton(found.stage)); return; }
      const more = h("button", {type: "button", class: "first-link"}, t("dock.skills.kb"));
      more.addEventListener("click", leave(() => allSkills("kb", () => kbWindow("domains"))));
      const state = (item) => (item.task ? [t("dock.kb.state.task") + " ", h("a", {href: "/task/" + encodeURIComponent(item.task)}, item.task)] : t(item.done ? "dock.kb.state.done" : item.listed ? "dock.kb.state.listed" : "dock.kb.state.open"));
      stage.replaceChildren(h("div", {class: "scroll"}, h("table", {class: "md"}, h("thead", null, h("tr", null, ["domain", "state", "left", "requests"].map((key) => h("th", null, t("dock.kb.col." + key))))),
        h("tbody", null, found.domains.map((item) => h("tr", null, h("td", {class: "kb-name"}, item.domain), h("td", null, state(item)), h("td", null, item.to_learn === undefined ? "-" : String(item.to_learn)), h("td", null, String(item.requests_open || 0))))))), more);
    }
    function lookup() {
      const box = h("input", {type: "text", class: "code", autocomplete: "off", spellcheck: "false", maxlength: 200, placeholder: t("dock.kb.lookup.ph")});
      const go = h("button", {type: "button", class: "act"}, t("dock.kb.lookup"));
      const out = h("div", {class: "kb-near"});
      const find = (text) => {
        box.value = word = searched = text;
        const mine = ++ticket;
        const shown = () => box.isConnected && mine === ticket;  // only the newest search is drawn
        out.replaceChildren(h("p", {class: "sub"}, t("dock.kb.working")));
        post({op: "near", query: text}).then((found) => { if (shown()) out.replaceChildren(...near(found, find)); }, (error) => { if (shown()) out.replaceChildren(h("p", {class: "bad"}, error.message || String(error))); });
      };
      box.value = word;
      box.addEventListener("input", () => { word = box.value; });
      go.addEventListener("click", () => find(box.value));
      box.addEventListener("keydown", (event) => { if (isEnter(event)) find(box.value); });
      stage.replaceChildren(h("div", {class: "dock-line"}, box, go), out);
      box.focus();
      if (searched) find(searched);
    }
    // One object of the map, or the ones a name fits. An id is a button: it looks that one up.
    function near(found, find) {
      const link = (id) => { const button = h("button", {type: "button", class: "first-link kb-id"}, id); button.addEventListener("click", () => find(id)); return button; };
      if (found.matches) return [h("p", null, found.next), h("ul", {class: "kb-near-list"}, found.matches.map((id) => h("li", null, link(id)))), found.total > found.matches.length ? h("p", {class: "sub"}, t("dock.atlas.more", {n: found.total - found.matches.length})) : null].filter(Boolean);
      const uses = (title, rows) => [h("h3", null, title + " (" + rows.length + ")"), rows.length ? h("ul", {class: "kb-near-list"}, rows.map((row) => h("li", null, link(row.id), " ", h("span", {class: "sub"}, row.how + " \u00b7 " + row.repo + "/" + row.path)))) : h("p", {class: "sub"}, t("dock.kb.lookup.nothing"))];
      const names = (title, list) => (list ? [h("h3", null, title), h("ul", {class: "kb-near-list"}, list.map((name) => h("li", null, h("code", null, name))))] : []);
      return [h("h3", null, found.id), h("p", {class: "sub"}, found.type + " \u00b7 " + found.repo + "/" + found.path + ":" + found.line), found.obsolete ? h("p", {class: "su-warn"}, t("dock.kb.lookup.obsolete")) : null, found.note ? h("p", {class: "su-warn"}, found.note) : null,
        ...uses(t("dock.kb.lookup.usedby"), found.used_by || []), ...uses(t("dock.kb.lookup.uses"), found.uses || []), ...names(t("dock.kb.lookup.missing"), found.uses_missing), ...names(t("dock.kb.lookup.outside"), found.uses_outside)].filter(Boolean);
    }
    function health(found) {
      const SHOWN = 200;
      const items = found.problems || [];
      const lines = (item, key) => (item[key] || []).slice(0, SHOWN).map((line) => h("li", {class: key === "errors" ? "bad" : ""}, typeof line === "string" ? line : JSON.stringify(line)));
      const left = (item) => (item.errors || []).length + (item.warnings || []).length - SHOWN;
      stage.replaceChildren(h("p", null, found.domains ? t("dock.kb.health.sum", {n: found.domains, errors: found.errors, warnings: found.warnings}) + " " + found.next : t("dock.kb.health.none")),
        ...items.map((item) => h("section", {class: "kb-problem"}, h("b", null, item.domain || item.name || ""), h("ul", null, lines(item, "errors"), lines(item, "warnings").slice(0, Math.max(0, SHOWN - (item.errors || []).length))), left(item) > 0 ? h("p", {class: "sub"}, t("dock.kb.health.more", {n: left(item)})) : null)));
    }
    function show(key) {
      clearTimeout(timer);
      current = key;
      drawn = "";
      tabs.forEach((tab) => tab.classList.toggle("on", tab.dataset.key === key));
      view.box.classList.toggle("ka-open", key === "atlas");
      stage.classList.remove("ka-stage");
      age.textContent = "";
      alarm.hidden = true;
      again.hidden = key === "lookup";
      stage.replaceChildren(h("p", {class: "sub"}, t("dock.kb.working")));
      if (key === "lookup") { lookup(); return; }
      const op = key === "health" || key === "atlas" ? key : "status";
      const paint = key === "health" ? health : key === "atlas" ? (found) => ATLAS.draw(stage, found) : key === "overview" ? overview : domains;
      again.onclick = () => { clearTimeout(timer); load(op, paint, true); };
      load(op, paint, !asked.has(op));
      asked.add(op);
    }
    show(tab || "overview");
  }

  // The form of Get ready in a window over the page. When it is done the page reads the new settings.
  // Saved: the page reads the new settings when the person has seen what was done. Changes not saved are not lost by one click.
  function setupWindow() {
    if (document.querySelector(".su-window")) return;
    const box = h("div");
    const note = h("span", {class: "su-note"});
    const close = h("button", {type: "button", class: "act"}, t("board.new.close"));
    const view = SERVE.dialog([h("div", {class: "su-winbar"}, note, close), box]);
    view.box.classList.add("su-window");
    let saved = false, warned = false;
    const form = SETUP.mount(box, () => { saved = true; note.textContent = ""; close.classList.add("hot"); });
    view.holds = () => saved || form.busy() || form.dirty();
    close.addEventListener("click", () => {
      if (saved) location.reload();
      else if (form.busy()) note.textContent = t("setup.close.busy");
      else if (form.dirty() && !warned) { warned = true; note.textContent = t("setup.close.sure"); close.textContent = t("setup.close.discard"); }
      else view.close();
    });
  }
  function enterScreen() {
    try { sessionStorage.removeItem(ENTERED); } catch (error) { /* then nothing was kept, and the screen comes anyway */ }
    location.assign("/");
  }

  const drawn = (paths) => {
    const NS = "http://www.w3.org/2000/svg", node = document.createElementNS(NS, "svg");
    node.setAttribute("viewBox", "0 0 24 24");
    node.setAttribute("aria-hidden", "true");
    for (const d of paths) { const part = document.createElementNS(NS, "path"); part.setAttribute("d", d); node.append(part); }
    return node;
  };

  function build() {
    const panel = h("section", {class: "dock-panel", hidden: ""});
    const box = h("input", {type: "text", class: "su-in", maxlength: 2000, placeholder: t("dock.ask.ph"), "aria-label": t("dock.ask")});
    const send = h("button", {type: "button", class: "act hot"}, t("dock.ask"));
    const deep = h("button", {type: "button", class: "act"}, t("dock.deep"));
    const first = h("button", {type: "button", class: "act"}, t("dock.first"));
    const showPanel = () => { panel.hidden = false; box.focus(); };
    const askIt = () => { if (!box.value.trim()) return; panel.hidden = true; start("harness-rookie-wondering", box.value, showPanel); };
    const fit = () => { send.disabled = !box.value.trim(); };
    fit();
    box.addEventListener("input", fit);
    send.addEventListener("click", askIt);
    box.addEventListener("keydown", (event) => { if (isEnter(event)) askIt(); });
    deep.addEventListener("click", () => { panel.hidden = true; start("harness-rookie-wondering", "", showPanel); });
    first.addEventListener("click", () => { panel.hidden = true; start("harness-rookie-quick-start", "", showPanel); });
    const every = h("button", {type: "button", class: "first-link"}, t("dock.skills"));
    every.addEventListener("click", () => { panel.hidden = true; allSkills("", showPanel); });
    panel.append(h("h3", null, t("dock.help")), h("div", {class: "dock-line"}, box, send), h("div", {class: "dock-line"}, deep, first), every);
    const button = h("button", {type: "button", class: "dock-btn dock-ask", "aria-label": t("dock.help"), title: t("dock.help")}, "?");
    button.addEventListener("click", () => { if (panel.hidden) showPanel(); else panel.hidden = true; });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") panel.hidden = true; });
    document.addEventListener("click", (event) => { if (!panel.contains(event.target) && !button.contains(event.target)) panel.hidden = true; });
    const icon = (name, label, paths, run) => {
      const node = h("button", {type: "button", class: "dock-btn dock-icon " + name, "aria-label": label, title: label}, drawn(paths));
      node.addEventListener("click", () => { panel.hidden = true; run(); });
      return node;
    };
    const kb = icon("dock-book", t("dock.kb"), ["M12 6.5C10.2 5 7.5 4.5 3.5 4.5v14c4 0 6.7.5 8.5 2 1.8-1.5 4.5-2 8.5-2v-14c-4 0-6.7.5-8.5 2z", "M12 6.5v14"], kbWindow);
    const setup = icon("dock-setup", t("dock.setup"), ["M4 7h9M17 7h3M13 4.5h4v5h-4zM4 17h3M11 17h9M7 14.5h4v5H7z"], setupWindow);
    const home = icon("dock-home", t("dock.home"), ["M3.5 11.5 12 4.5l8.5 7M6 9.5V20h12V9.5M10 20v-5.5h4V20"], enterScreen);
    document.body.append(panel, button, kb, setup, home);
  }

  if (typeof DATA !== "undefined" && DATA.serve) build();
  return {start, allSkills, kbWindow, setupWindow, enterScreen};
})();
