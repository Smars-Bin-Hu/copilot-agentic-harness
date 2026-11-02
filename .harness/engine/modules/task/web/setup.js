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
  const kbPath = h("input", {type: "text", class: "su-in su-mono", maxlength: 1024, autocomplete: "off", spellcheck: "false", hidden: ""});
  const kbNote = h("p", {class: "su-note"});
  const prefix = h("input", {type: "text", class: "su-in su-short", maxlength: 31, autocomplete: "off", spellcheck: "false"});
  const install = h("input", {type: "text", class: "su-in su-mono", maxlength: 500, autocomplete: "off", spellcheck: "false", placeholder: t("setup.install.ph")});
  const refused = h("textarea", {class: "su-in su-mono", rows: 3, spellcheck: "false", placeholder: t("setup.refused.ph")});
  const modes = ["package", "folder", "none"].map((mode) => {
    const chip = h("button", {type: "button", class: "chip", "data-mode": mode}, t("setup.kb." + mode));
    chip.addEventListener("click", () => setMode(mode));
    return chip;
  });
  const setMode = (mode) => {
    st.mode = mode;
    modes.forEach((chip) => { const on = chip.dataset.mode === mode; chip.classList.toggle("on", on); chip.setAttribute("aria-pressed", on ? "true" : "false"); });
    kbPath.hidden = mode === "none";
    kbPath.placeholder = mode === "package" ? t("setup.kb.package.ph") : t("setup.kb.folder.ph");
    kbNote.className = "su-note";
    kbNote.textContent = mode === "none" ? t("setup.kb.none.hint") : "";
    if (mode !== "none" && kbPath.value.trim()) checkKb();
  };
  function checkKb() {
    ask("probe", {kind: st.mode, path: kbPath.value}).then((found) => {
      kbNote.className = "su-note" + (found.ok ? " good" : " bad");
      kbNote.textContent = !found.ok ? found.why : st.mode === "package" ? t("setup.kb.package.ok", {version: found.version, n: found.new}) : found.why || t("setup.kb.folder.ok");
      if (found.prefix && !prefix.value) prefix.value = found.prefix;
    }, () => {});
  }
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
      setMode("none");
      prefix.value = found.skill_prefix || "";
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

  const paintLines = (found) => said.replaceChildren(...found.lines.map((line) => h("p", {class: line.ok ? "su-note good" : "su-note bad"}, (line.ok ? "\u2713 " : "\u2717 ") + t("setup.line." + line.key) + ": " + line.detail)));
  function follow() {
    ask("job").then((found) => {
      paintLines(found);
      if (found.running) { setTimeout(follow, 700); return; }
      if (found.done) location.assign("/");
      else go.disabled = false;
    }, (error) => { go.disabled = false; said.replaceChildren(...SERVE.reasons(error.message || error)); });
  }
  go.addEventListener("click", () => {
    go.disabled = true;
    said.replaceChildren();
    ask("act", {name: name.value, language: st.lang, repos_root: repos.value, kb_mode: st.mode, kb_path: kbPath.value, skill_prefix: prefix.value, install_command: install.value, refused_paths: refused.value}).then(follow,
      (error) => { go.disabled = false; said.replaceChildren(...SERVE.reasons(error.message || error)); });
  });
  function older() {
    const path = h("input", {class: "code", autocomplete: "off", spellcheck: "false", placeholder: t("setup.older.ph")});
    const look = h("button", {type: "button", class: "act"}, t("setup.older.look"));
    const apply = h("button", {type: "button", class: "act hot", hidden: ""}, t("setup.older.apply"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const out = h("div", {class: "su-note"});
    const view = SERVE.dialog([h("h2", null, t("setup.older.title")), h("p", {class: "sub"}, t("setup.older.hint")), path, out, h("div", {class: "row"}, look, apply, no)]);
    no.addEventListener("click", view.close);
    look.addEventListener("click", () => ask("older", {path: path.value}).then((found) => {
      const groups = Object.entries(found.would_copy || {}).map(([group, names]) => group + ": " + names.length);
      out.textContent = t("setup.older.plan", {from: found.from, groups: groups.join(", ") || "-"});
      apply.hidden = false;
    }, (error) => { out.textContent = error.message || String(error); }));
    apply.addEventListener("click", () => { apply.disabled = true; ask("older", {path: path.value, apply: true}).then(() => { location.assign("/"); }, (error) => { apply.disabled = false; out.textContent = error.message || String(error); }); });
  }
  repos.addEventListener("input", () => { clearTimeout(st.probe); st.probe = setTimeout(checkRepos, 400); });
  kbPath.addEventListener("input", () => { clearTimeout(st.probe); st.probe = setTimeout(checkKb, 400); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !st.timer) load(); });

  const olderLink = h("button", {type: "button", class: "su-link"}, t("setup.older.title"));
  olderLink.addEventListener("click", older);
  const first = new URLSearchParams(location.search).has("first");
  const plain = (spans) => (spans || []).map((span) => (span.v !== undefined ? span.v : plain(span.c))).join("");
  function doc(list) {  // the words of docs/03-configure.md, as text
    return list.map((block) => {
      if (block.t === "h") return h("h4", null, plain(block.spans));
      if (block.t === "p") return h("p", {class: "su-doc"}, plain(block.spans));
      if (block.t === "code") return h("pre", {class: "su-cmd"}, block.text);
      if (block.t === "ul" || block.t === "ol") return h(block.t, {class: "su-doc"}, block.items.map((item) => h("li", null, plain(item.spans))));
      if (block.t === "table") return h("div", {class: "scroll"}, h("table", {class: "md"}, h("thead", null, h("tr", null, block.head.map((cell) => h("th", null, plain(cell))))), h("tbody", null, block.rows.map((cells) => h("tr", null, cells.map((cell) => h("td", null, plain(cell))))))));
      return null;
    });
  }
  const guideBox = h("div", {class: "su-guide"});
  function guide() {
    ask("guide").then((found) => {
      guideBox.replaceChildren(...found.sections.map((part) => {
        const open = found.missing.includes(part.key) || (part.key === "kb" && found.missing.includes("domains"));
        const none = part.can_declare ? h("label", {class: "su-none"}, h("input", {type: "checkbox"}), h("span", null, t("setup.none"))) : null;
        if (none) none.firstChild.addEventListener("change", () => ask("none", {key: part.key, on: none.firstChild.checked}).then(guide));
        return h("details", {class: "su-part", open: open ? "" : null}, h("summary", null, h("span", {class: "su-dot" + (open ? " need" : " ok")}), part.title), none, doc(part.blocks));
      }));
    }, () => {});
  }
  if (!first) guide();
  app.replaceChildren(h("div", {class: "su"}, h("h1", null, t(first ? "setup.title" : "setup.guide")), h("p", {class: "su-lead"}, t("setup.lead"), " ", olderLink), shortBox,
    h("section", {class: "su-card"}, h("div", {class: "su-head"}, h("span", {class: "su-mark"}, "2"), h("h2", null, t("setup.form.title"))),
      row(t("setup.name"), h("div", {class: "su-line"}, name, h("span", {class: "chips"}, chips))), row(t("setup.repos"), repos, repoNote),
      row(t("setup.kb"), h("div", {class: "chips su-modes"}, modes), kbPath, kbNote), row(t("setup.prefix"), prefix, h("p", {class: "su-note"}, t("setup.prefix.hint"))),
      h("details", {class: "su-more"}, h("summary", {class: "su-note"}, t("setup.more")), row(t("setup.install"), install), row(t("setup.refused"), refused)),
      h("div", {class: "su-end"}, go, h("span", {class: "su-note"}, t("setup.finish.note"))), said), first ? null : guideBox));
  load();
})();
