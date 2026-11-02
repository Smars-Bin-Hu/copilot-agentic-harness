// Get ready (1.6.57): one command, then one form. No agent runs. The server does the work (core/setup.py): this page shows and sends.
// Needs common.js (h, t, copyCommand), serve.js (SERVE).
(function () {
  const app = document.getElementById("app");
  const POLL = 2000;
  const st = {form: null, timer: 0, probe: 0};
  const ask = (step, body) => SERVE.post("/api/setup", {step, ...(body || {})}).then((data) => data.result);

  const shortBox = h("section", {class: "su-card"});
  const said = h("div", {class: "su-said"});
  const repoNote = h("p", {class: "su-note"});
  const name = h("input", {type: "text", class: "su-in", maxlength: 100, autocomplete: "name", spellcheck: "false"});
  const repos = h("input", {type: "text", class: "su-in su-mono", maxlength: 1024, autocomplete: "off", spellcheck: "false", placeholder: t("setup.repos.ph")});
  const go = h("button", {type: "button", class: "act hot big"}, t("setup.finish"));
  const chips = ["en", "zh"].map((lang) => {
    const chip = h("button", {type: "button", class: "chip", "data-lang": lang}, t("desk.send.lang." + lang));
    chip.addEventListener("click", () => setLang(lang));
    return chip;
  });
  const setLang = (lang) => { st.lang = lang; chips.forEach((chip) => { const on = chip.dataset.lang === lang; chip.classList.toggle("on", on); chip.setAttribute("aria-pressed", on ? "true" : "false"); }); };
  const row = (label, ...nodes) => h("div", {class: "su-row"}, h("span", {class: "su-k"}, label), h("div", {class: "su-v"}, nodes));

  function paintShort(found) {
    const done = Boolean(found.short.found);
    const parts = [h("div", {class: "su-head"}, h("span", {class: "su-mark" + (done ? " ok" : "")}, done ? "\u2713" : "1"), h("h2", null, t("setup.short.title")), done ? h("code", {class: "su-found"}, found.short.found) : null)];
    if (!done) {
      const copy = h("button", {type: "button", class: "act", "data-label": t("desk.code.copy")}, t("desk.code.copy"));
      copy.addEventListener("click", () => copyCommand(copy, found.short.command));
      parts.push(h("p", {class: "su-note"}, t("setup.short.do")), h("div", {class: "su-cmd"}, h("code", null, found.short.command), copy), h("p", {class: "su-note"}, t("setup.short.wait")));
    } else if (found.reopen) parts.push(h("p", {class: "su-warn"}, t("setup.short.reopen")));
    shortBox.replaceChildren(...parts);
  }

  function paint(found) {
    paintShort(found);
    if (!st.form) {
      st.form = true;
      name.value = found.name;
      repos.value = found.repos_root;
      setLang(found.language);
      if (found.problem) said.replaceChildren(...SERVE.reasons(found.problem));
      checkRepos();
    }
    go.disabled = !found.short.found;
    go.title = found.short.found ? "" : t("setup.finish.first");
  }

  function checkRepos() {
    ask("probe", {repos_root: repos.value}).then((found) => {
      repoNote.className = "su-note" + (found.ok && found.n ? " good" : found.ok ? "" : " bad");
      repoNote.textContent = found.why || (found.n ? t("setup.repos.found", {n: found.n, names: found.names.join(", ")}) : t("setup.repos.hint"));
    }, () => {});
  }

  function load() {
    clearTimeout(st.timer);
    return ask("state").then(paint, (error) => { said.replaceChildren(...SERVE.reasons(error.message || error)); }).then(() => { if (!document.hidden) st.timer = setTimeout(load, POLL); else st.timer = 0; });
  }

  go.addEventListener("click", () => {
    go.disabled = true;
    said.replaceChildren();
    ask("act", {name: name.value, language: st.lang, repos_root: repos.value}).then((found) => {
      said.replaceChildren(...found.lines.map((line) => h("p", {class: line.ok ? "su-note good" : "su-note bad"}, (line.ok ? "\u2713 " : "\u2717 ") + t("setup.line." + line.key) + ": " + line.detail)));
      if (found.done) location.assign("/");
      else go.disabled = false;
    }, (error) => { go.disabled = false; said.replaceChildren(...SERVE.reasons(error.message || error)); });
  });
  repos.addEventListener("input", () => { clearTimeout(st.probe); st.probe = setTimeout(checkRepos, 400); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !st.timer) load(); });

  app.replaceChildren(h("div", {class: "su"}, h("h1", null, t("setup.title")), h("p", {class: "su-lead"}, t("setup.lead")), shortBox,
    h("section", {class: "su-card"}, h("div", {class: "su-head"}, h("span", {class: "su-mark"}, "2"), h("h2", null, t("setup.form.title"))),
      row(t("setup.name"), h("div", {class: "su-line"}, name, h("span", {class: "chips"}, chips))), row(t("setup.repos"), repos, repoNote),
      h("div", {class: "su-end"}, go, h("span", {class: "su-note"}, t("setup.finish.note"))), said)));
  load();
})();
