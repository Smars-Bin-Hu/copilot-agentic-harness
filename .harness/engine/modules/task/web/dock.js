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
    const view = SERVE.dialog([h("h2", null, t("dock.title")), h("p", {class: "sub"}, t("dock.hint")), preview, said, h("div", {class: "row"}, go, no)]);
    no.addEventListener("click", view.close);
    if (back) no.before(backButton(view, back));
    ask("preview", body).then((found) => {
      preview.textContent = found.text;
      if (found.blocked) said.replaceChildren(...SERVE.reasons(found.blocked));
      go.disabled = Boolean(found.blocked);
    }, (error) => { preview.textContent = ""; said.replaceChildren(...SERVE.reasons(error.message || error)); });
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
    no.addEventListener("click", view.close);
    if (back) no.before(backButton(view, back));
    let found = [];
    const start = (item, words) => {
      view.close();
      memory.word = search.value;
      memory.top = list.scrollTop;
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
      const go = item.href ? h("a", {class: "act", href: item.href, target: "_blank", rel: "noopener noreferrer"}, t("dock.open")) : item.opens === "reply" ? h("span", {class: "tag", title: t("dock.intask.hint")}, t("dock.intask")) : h("button", {type: "button", class: "act"}, t("dock.start"));
      if (go.tagName === "BUTTON") go.addEventListener("click", () => start(item, words ? words.value : ""));
      return h("div", {class: "dock-skill"}, h("div", {class: "dock-about"}, h("b", null, item.label), item.costly ? h("span", {class: "tag hot"}, t("dock.costly")) : null, h("p", {class: "sub"}, item.about), words), go);
    };
    function paint() {
      const word = search.value.trim().toLowerCase();
      const shown = found.filter((item) => (!only || item.group === only || item.place.includes(only)) && (!word || (item.label + " " + item.name + " " + item.about).toLowerCase().includes(word)));
      const groups = [["own", (item) => item.own], ...["harness", "kb", "task"].map((key) => [key, (item) => !item.own && item.group === key])];
      list.replaceChildren(...groups.flatMap(([key, test]) => {
        const items = shown.filter(test);
        const out = items.length && !only ? [h("h3", null, t("dock.group." + key))] : [];  // a window of one part has its name as its title
        items.forEach((item, index) => {
          if (item.step && (!index || items[index - 1].step !== item.step)) out.push(h("h4", null, t("dock.step." + item.step)));
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
  function kbWindow() {
    const stage = h("div", {class: "dock-list kb-body"});
    const no = h("button", {type: "button", class: "act"}, t("board.new.close"));
    const tabs = ["overview", "atlas", "domains", "lookup", "health"].map((key) => { const tab = h("button", {type: "button", class: "chip", "data-key": key}, t(key === "domains" ? "dock.kb.domains.tab" : "dock.kb." + key)); tab.addEventListener("click", () => show(key)); return tab; });
    const view = SERVE.dialog([h("h2", null, t("dock.kb")), h("div", {class: "chips dock-tabs"}, tabs), stage, h("div", {class: "row"}, no)]);
    view.box.classList.add("dock-window", "kb-window");
    let timer = 0, gone = false;
    no.addEventListener("click", () => { gone = true; clearTimeout(timer); view.close(); });
    const post = (body) => SERVE.post("/api/kb", body).then((data) => data.result);
    function load(op, paint) {
      post({op}).then((found) => {
        if (gone) return;
        if (found.error) stage.replaceChildren(h("p", {class: "bad"}, found.error));
        if (found.result) paint(found.result, found.age);
        else if (!found.error) stage.replaceChildren(h("p", {class: "sub"}, t("dock.kb.working")));
        if (found.running) timer = setTimeout(() => load(op, paint), 1200);
      }, (error) => stage.replaceChildren(h("p", {class: "bad"}, error.message || String(error))));
    }
    const nextButton = () => {
      const go = h("button", {type: "button", class: "act hot"}, t("dock.kb.next"));
      go.addEventListener("click", () => { gone = true; view.close(); start("harness-rookie-new-knowledgebase", "", kbWindow); });
      return go;
    };
    function overview(found) {
      stage.replaceChildren(h("ol", {class: "kb-steps"}, found.steps.map((item) => h("li", {class: item.done ? "done" : item.step === found.stage ? "now" : ""}, (item.done ? "\u2713 " : "") + t("dock.kb.step." + item.step)))),
        h("div", {class: "kb-nums"}, h("span", null, t("dock.kb.domains", {n: found.domains.length})), h("span", null, t("dock.kb.requests", {n: found.requests_open}))), nextButton());
    }
    function domains(found) {
      if (!found.domains.length) { stage.replaceChildren(h("p", {class: "sub"}, t("dock.kb.nodomains")), nextButton()); return; }
      const more = h("button", {type: "button", class: "first-link"}, t("dock.skills.kb"));
      more.addEventListener("click", () => { gone = true; view.close(); allSkills("kb", kbWindow); });
      stage.replaceChildren(h("div", {class: "scroll"}, h("table", {class: "md"}, h("thead", null, h("tr", null, ["domain", "state", "left", "requests"].map((key) => h("th", null, t("dock.kb.col." + key))))),
        h("tbody", null, found.domains.map((item) => h("tr", null, h("td", null, item.domain), h("td", null, t(item.done ? "dock.kb.state.done" : item.task ? "dock.kb.state.task" : "dock.kb.state.open")), h("td", null, item.to_learn === undefined ? "-" : String(item.to_learn)), h("td", null, String(item.requests_open || 0))))))), more);
    }
    function lookup() {
      const box = h("input", {type: "text", class: "code", autocomplete: "off", spellcheck: "false", placeholder: t("dock.kb.lookup.ph")});
      const out = h("pre", {class: "send-preview"});
      out.hidden = true;
      box.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        post({op: "near", query: box.value}).then((found) => { out.hidden = false; out.textContent = JSON.stringify(found, null, 2); }, (error) => { out.hidden = false; out.textContent = error.message || String(error); });
      });
      stage.replaceChildren(box, out);
      box.focus();
    }
    function health(found) {
      const items = found.problems || [];
      stage.replaceChildren(...[h("p", null, found.next), ...items.map((item) => h("section", null, h("b", null, item.domain || item.name || ""), h("ul", null, [...(item.errors || []), ...(item.warnings || [])].slice(0, 200).map((line) => h("li", null, typeof line === "string" ? line : JSON.stringify(line))))))]);
    }
    function show(key) {
      clearTimeout(timer);
      tabs.forEach((tab) => tab.classList.toggle("on", tab.dataset.key === key));
      view.box.classList.toggle("ka-open", key === "atlas");
      stage.classList.remove("ka-stage");
      stage.replaceChildren(h("p", {class: "sub"}, t("dock.kb.working")));
      if (key === "lookup") lookup();
      else if (key === "atlas") load("atlas", (found) => { if (view.box.classList.contains("ka-open")) ATLAS.draw(stage, found); });
      else if (key === "health") load("health", health);
      else load("status", key === "overview" ? overview : domains);
    }
    show("overview");
  }

  // The form of Get ready in a window over the page. When it is done the page reads the new settings.
  function setupWindow() {
    const box = h("div");
    const close = h("button", {type: "button", class: "act"}, t("board.new.close"));
    const view = SERVE.dialog([h("div", {class: "su-winbar"}, close), box]);
    view.box.classList.add("su-window");
    close.addEventListener("click", view.close);
    SETUP.mount(box, () => location.reload());
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
    const askIt = () => { panel.hidden = true; start("harness-rookie-wondering", box.value, showPanel); };
    send.addEventListener("click", askIt);
    box.addEventListener("keydown", (event) => { if (event.key === "Enter") askIt(); });
    deep.addEventListener("click", () => { panel.hidden = true; start("harness-rookie-wondering", "", showPanel); });
    first.addEventListener("click", () => { panel.hidden = true; start("harness-rookie-quick-start", "", showPanel); });
    const every = h("button", {type: "button", class: "first-link"}, t("dock.skills"));
    every.addEventListener("click", () => { panel.hidden = true; allSkills("", showPanel); });
    panel.append(h("h3", null, t("dock.help")), h("div", {class: "dock-line"}, box, send), h("div", {class: "dock-line"}, deep, first), every);
    const button = h("button", {type: "button", class: "dock-btn dock-ask", "aria-label": t("dock.help"), title: t("dock.help")}, "?");
    button.addEventListener("click", () => { if (panel.hidden) showPanel(); else panel.hidden = true; });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") panel.hidden = true; });
    const icon = (name, label, paths, run) => {
      const node = h("button", {type: "button", class: "dock-btn dock-icon " + name, "aria-label": label, title: label}, drawn(paths));
      node.addEventListener("click", run);
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
