// The buttons at the bottom right (1.6.61): the question mark and the one-click chats. The gear is shell.js's. The brain comes with the knowledge base window.
// DOCK.start asks with the whole message in view, sends, and brings VS Code forward. Needs common.js (h, t), serve.js (SERVE).
const DOCK = (function () {
  const ask = (step, body) => SERVE.post("/api/skill", {step, ...body}).then((data) => data.result);

  function done() {
    const close = h("button", {type: "button", class: "act hot"}, t("board.new.close"));
    const view = SERVE.dialog([h("h2", null, t("dock.sent")), h("p", null, t("dock.sent.where")), h("div", {class: "row"}, close)]);
    close.addEventListener("click", view.close);
  }

  function start(skill, words) {
    const lang = document.documentElement.lang === "zh" ? "zh" : "en";
    const body = {skill, words: words || "", lang};
    const preview = h("pre", {class: "send-preview"}, "...");
    const said = h("div", {class: "bad"});
    const go = h("button", {type: "button", class: "act hot", disabled: "disabled"}, t("dock.send"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const view = SERVE.dialog([h("h2", null, t("dock.title")), h("p", {class: "sub"}, t("dock.hint")), preview, said, h("div", {class: "row"}, go, no)]);
    no.addEventListener("click", view.close);
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
  function allSkills(only) {
    const search = h("input", {type: "text", class: "code", autocomplete: "off", spellcheck: "false", placeholder: t("dock.skills.search")});
    const list = h("div", {class: "dock-list"});
    const no = h("button", {type: "button", class: "act"}, t("board.new.close"));
    const view = SERVE.dialog([h("h2", null, t(only === "kb" ? "dock.skills.kb" : "dock.skills")), search, list, h("div", {class: "row"}, no)]);
    view.box.classList.add("dock-window");
    no.addEventListener("click", view.close);
    let found = [];
    const start = (item, words) => {
      view.close();
      if (item.opens === "task") CHAT.create({kind: item.kind, text: "Use the skill " + item.name + "." + (words ? " " + words : ""), note: t("dock.task.note")});
      else DOCK.start(item.name, words);
    };
    const row = (item) => {
      const words = item.hint ? h("input", {type: "text", class: "code", maxlength: 2000, placeholder: item.hint, "aria-label": item.hint}) : null;
      const go = h("button", {type: "button", class: "act"}, t("dock.start"));
      go.addEventListener("click", () => start(item, words ? words.value : ""));
      return h("div", {class: "dock-skill"}, h("div", {class: "dock-about"}, h("b", null, item.label), item.costly ? h("span", {class: "tag hot"}, t("dock.costly")) : null, h("p", {class: "sub"}, item.about), words), go);
    };
    function paint() {
      const word = search.value.trim().toLowerCase();
      const shown = found.filter((item) => item.opens !== "reply" && (!only || item.place.includes(only)) && (!word || (item.label + " " + item.name + " " + item.about).toLowerCase().includes(word)));
      const groups = [["own", (item) => item.own], ["work", (item) => !item.own && !item.place.includes("kb")], ["kb", (item) => !item.own && item.place.includes("kb")]];
      list.replaceChildren(...groups.flatMap(([key, test]) => {
        const items = shown.filter(test);
        return items.length ? [h("h3", null, t("dock.group." + key)), ...items.map(row)] : [];
      }));
      if (!shown.length) list.append(h("p", {class: "sub"}, t("dock.skills.none")));
    }
    search.addEventListener("input", paint);
    ask("list", {}).then((data) => { found = data.skills; paint(); }, (error) => list.replaceChildren(h("p", {class: "bad"}, error.message || String(error))));
  }

  // The knowledge base window: a page over the page, read only; a button with "chat" in it opens a chat (kbview.py, core/kbstatus.py).
  function kbWindow() {
    const stage = h("div", {class: "dock-list kb-body"});
    const no = h("button", {type: "button", class: "act"}, t("board.new.close"));
    const tabs = ["overview", "domains", "lookup", "health"].map((key) => { const tab = h("button", {type: "button", class: "chip", "data-key": key}, t(key === "domains" ? "dock.kb.domains.tab" : "dock.kb." + key)); tab.addEventListener("click", () => show(key)); return tab; });
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
      go.addEventListener("click", () => { gone = true; view.close(); start("harness-rookie-new-knowledgebase", ""); });
      return go;
    };
    function overview(found) {
      stage.replaceChildren(h("ol", {class: "kb-steps"}, found.steps.map((item) => h("li", {class: item.done ? "done" : item.step === found.stage ? "now" : ""}, (item.done ? "\u2713 " : "") + t("dock.kb.step." + item.step)))),
        h("div", {class: "kb-nums"}, h("span", null, t("dock.kb.domains", {n: found.domains.length})), h("span", null, t("dock.kb.requests", {n: found.requests_open}))), nextButton());
    }
    function domains(found) {
      if (!found.domains.length) { stage.replaceChildren(h("p", {class: "sub"}, t("dock.kb.nodomains")), nextButton()); return; }
      const more = h("button", {type: "button", class: "first-link"}, t("dock.skills.kb"));
      more.addEventListener("click", () => { gone = true; view.close(); allSkills("kb"); });
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
      stage.replaceChildren(h("p", {class: "sub"}, t("dock.kb.working")));
      if (key === "lookup") lookup();
      else if (key === "health") load("health", health);
      else load("status", key === "overview" ? overview : domains);
    }
    show("overview");
  }

  function build() {
    const panel = h("section", {class: "dock-panel", hidden: ""});
    const box = h("input", {type: "text", class: "su-in", maxlength: 2000, placeholder: t("dock.ask.ph"), "aria-label": t("dock.ask")});
    const send = h("button", {type: "button", class: "act hot"}, t("dock.ask"));
    const deep = h("button", {type: "button", class: "act"}, t("dock.deep"));
    const first = h("button", {type: "button", class: "act"}, t("dock.first"));
    const askIt = () => { panel.hidden = true; start("harness-rookie-wondering", box.value); };
    send.addEventListener("click", askIt);
    box.addEventListener("keydown", (event) => { if (event.key === "Enter") askIt(); });
    deep.addEventListener("click", () => { panel.hidden = true; start("harness-rookie-wondering", ""); });
    first.addEventListener("click", () => { panel.hidden = true; start("harness-rookie-quick-start", ""); });
    const every = h("button", {type: "button", class: "first-link"}, t("dock.skills"));
    every.addEventListener("click", () => { panel.hidden = true; allSkills(""); });
    panel.append(h("h3", null, t("dock.help")), h("div", {class: "dock-line"}, box, send), h("div", {class: "dock-line"}, deep, first), every);
    const button = h("button", {type: "button", class: "dock-btn dock-ask", "aria-label": t("dock.help"), title: t("dock.help")}, "?");
    button.addEventListener("click", () => { panel.hidden = !panel.hidden; if (!panel.hidden) box.focus(); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") panel.hidden = true; });
    const brain = h("button", {type: "button", class: "dock-btn dock-brain", "aria-label": t("dock.kb"), title: t("dock.kb")}, "\u25c9");
    brain.addEventListener("click", kbWindow);
    document.body.append(panel, button, brain);
  }

  if (typeof DATA !== "undefined" && DATA.serve) build();
  return {start, allSkills, kbWindow};
})();
