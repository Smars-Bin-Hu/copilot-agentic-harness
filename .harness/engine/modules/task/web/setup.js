// Get ready (1.6.57): one command, then one form. No agent runs. The server does the work (core/setup.py): this page shows and sends.
// Needs common.js (h, t, copyCommand), serve.js (SERVE), dock.js (DOCK: the knowledge base tip opens its window).
(function () {
  const app = document.getElementById("app");
  const POLL = 2000;
  const st = {form: null, timer: 0, probe: 0, refused: [], busy: false, ready: false, mode: "none", root: "", rootFound: null, singles: [], broken: []};
  const ask = (step, body) => SERVE.post("/api/setup", {step, ...(body || {})}).then((data) => data.result);

  const shortBox = h("section", {class: "su-card"});
  const said = h("div", {class: "su-said"});
  const repoNote = h("p", {class: "su-note bad", hidden: ""});
  const repoList = h("div", {class: "su-list"});
  const repoPick = h("div");
  const repoAdd = h("button", {type: "button", class: "act"}, t("setup.refused.add"));
  const name = h("input", {type: "text", class: "su-in", maxlength: 100, autocomplete: "name", spellcheck: "false", required: ""});
  const repos = h("input", {type: "text", class: "su-in su-mono", maxlength: 1024, autocomplete: "off", spellcheck: "false", placeholder: t("setup.repos.ph")});
  const kbPath = h("input", {type: "text", class: "su-in su-mono", maxlength: 1024, autocomplete: "off", spellcheck: "false", hidden: ""});
  const kbNote = h("p", {class: "su-note"});
  const kbLearn = h("button", {type: "button", class: "su-link"}, t("setup.kb.learn"));
  kbLearn.addEventListener("click", () => DOCK.allSkills("kb"));
  const kbPick = h("button", {type: "button", class: "act"}, t("setup.browse"));
  kbPick.addEventListener("click", () => {
    kbPick.disabled = true;
    ask("pick", {kind: kbPick.dataset.kind}).then((found) => { kbPick.disabled = false; if (found.path) { kbPath.value = found.path; checkKb(); gate(); } }, () => { kbPick.disabled = false; });
  });
  const prefix = h("input", {type: "text", class: "su-in su-short", maxlength: 31, autocomplete: "off", spellcheck: "false"});
  const install = h("input", {type: "text", class: "su-in su-mono", maxlength: 500, autocomplete: "off", spellcheck: "false", placeholder: t("setup.install.ph")});
  const refusedBox = h("input", {type: "text", class: "su-in su-mono", maxlength: 1024, autocomplete: "off", spellcheck: "false"});
  const refusedAdd = h("button", {type: "button", class: "act"}, t("setup.refused.add"));
  const refusedList = h("div", {class: "su-list"});
  const refusedNote = h("p", {class: "su-note bad", hidden: ""});
  function paintRepos() {
    const item = (text, ok, why, off) => {
      const button = h("button", {type: "button", class: "su-x", "aria-label": t("setup.repos.remove")}, "\u00d7");
      button.addEventListener("click", () => { off(); paintRepos(); });
      return h("span", {class: "su-item"}, h("span", {class: "su-dot " + (ok ? "ok" : "bad"), title: why}), h("span", {class: "su-repo"}, h("code", null, text), h("span", {class: "su-note" + (ok ? " good" : " bad")}, why)), button);
    };
    const parts = [];
    if (st.root) parts.push(item(st.root, st.rootFound.n > 0, st.rootFound.n ? t("setup.repos.found", {n: st.rootFound.n, names: st.rootFound.names.join(", ")}) : st.rootFound.why, () => { st.root = ""; st.rootFound = null; }));
    st.singles.forEach((path) => { const ok = !st.broken.includes(path); parts.push(item(path, ok, t(ok ? "setup.repos.valid" : "setup.repos.invalid"), () => { st.singles = st.singles.filter((held) => held !== path); })); });
    repoList.replaceChildren(...parts);
  }
  function pickRepos(found) {
    const take = h("button", {type: "button", class: "act hot"}, t("setup.repos.take"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const rows = found.repos.map((repo) => {
      const box = h("input", {type: "checkbox", disabled: repo.held ? "" : null});
      box.addEventListener("change", sync);
      return {repo, box, node: h("label", {class: "su-tick"}, box, h("code", null, repo.name), repo.held ? h("span", {class: "su-note"}, t("setup.repos.held")) : null)};
    });
    const free = rows.filter((row) => !row.repo.held);
    const all = h("input", {type: "checkbox"});
    all.addEventListener("change", () => { free.forEach((row) => { row.box.checked = all.checked; }); sync(); });
    function sync() {
      const chosen = free.filter((row) => row.box.checked).length;
      all.checked = chosen > 0 && chosen === free.length;
      take.disabled = !chosen;
    }
    take.addEventListener("click", () => {
      const chosen = free.filter((row) => row.box.checked);
      if (chosen.length === rows.length && !st.root) { st.root = found.path; st.rootFound = found; }  // the whole folder: repositories added to it later count too
      else chosen.forEach((row) => st.singles.push(row.repo.path));
      repoPick.replaceChildren();
      paintRepos();
    });
    no.addEventListener("click", () => repoPick.replaceChildren());
    sync();
    repoPick.replaceChildren(h("div", {class: "su-pick"}, h("p", {class: "su-note good"}, h("span", {class: "su-dot ok"}), " ", t("setup.repos.pick", {n: found.n})), h("code", {class: "su-note"}, found.path),
      h("label", {class: "su-tick su-all"}, all, h("span", null, t("setup.repos.all"))), h("div", {class: "su-ticks"}, rows.map((row) => row.node)), h("div", {class: "su-end"}, take, no)));
  }
  function addRepo() {
    if (!repos.value.trim()) return;
    ask("repo", {path: repos.value, repos_root: st.root, singles: st.singles}).then((found) => {
      repoNote.hidden = true;
      repos.value = "";
      repoAdd.disabled = true;
      if (found.kind === "repo") { st.singles.push(found.path); repoPick.replaceChildren(); paintRepos(); }
      else pickRepos(found);
    }, (error) => { repoNote.hidden = false; repoNote.textContent = error.message || String(error); });
  }
  repoAdd.disabled = true;
  repos.addEventListener("input", () => { repoAdd.disabled = !repos.value.trim(); repoNote.hidden = true; });
  repoAdd.addEventListener("click", addRepo);
  repos.addEventListener("keydown", (event) => { if (event.key === "Enter") addRepo(); });
  function addRefused() {
    if (!refusedBox.value.trim()) return;
    ask("refuse", {repos_root: st.root, singles: st.singles, path: refusedBox.value}).then((found) => {
      refusedNote.hidden = true;
      refusedBox.value = "";
      refusedAdd.disabled = true;
      if (st.refused.includes(found.path)) return;
      st.refused.push(found.path);
      const chip = h("span", {class: "su-item"}, h("code", null, found.path));
      const off = h("button", {type: "button", class: "su-x", "aria-label": t("setup.refused.remove")}, "\u00d7");
      off.addEventListener("click", () => { st.refused = st.refused.filter((item) => item !== found.path); chip.remove(); });
      chip.append(off);
      refusedList.append(chip);
    }, (error) => { refusedNote.hidden = false; refusedNote.textContent = error.message || String(error); });
  }
  refusedAdd.disabled = true;
  refusedBox.addEventListener("input", () => { refusedAdd.disabled = !refusedBox.value.trim(); });
  refusedAdd.addEventListener("click", addRefused);
  refusedBox.addEventListener("keydown", (event) => { if (event.key === "Enter") addRefused(); });
  const browse = (input, kind, after) => {
    const button = h("button", {type: "button", class: "act"}, t("setup.browse"));
    button.addEventListener("click", () => {
      button.disabled = true;
      ask("pick", {kind}).then((found) => { button.disabled = false; if (found.path) { input.value = found.path; after(); } }, (error) => { button.disabled = false; said.replaceChildren(...SERVE.reasons(error.message || error)); });
    });
    return button;
  };
  const modes = ["package", "folder", "none"].map((mode) => {
    const chip = h("button", {type: "button", class: "chip", "data-mode": mode}, t("setup.kb." + mode));
    chip.addEventListener("click", () => setMode(mode));
    return chip;
  });
  const setMode = (mode) => {
    st.mode = mode;
    modes.forEach((chip) => { const on = chip.dataset.mode === mode; chip.classList.toggle("on", on); chip.setAttribute("aria-pressed", on ? "true" : "false"); });
    kbPath.hidden = mode === "none";
    kbPath.required = mode !== "none";
    kbStar.hidden = mode === "none";
    kbPick.hidden = mode === "none";
    kbPick.dataset.kind = mode === "package" ? "file" : "folder";
    kbPath.placeholder = mode === "package" ? t("setup.kb.package.ph") : t("setup.kb.folder.ph");
    kbNote.className = "su-note";
    kbNote.replaceChildren(...(mode === "none" ? [t("setup.kb.none.hint"), " ", kbLearn] : []));
    if (mode !== "none" && kbPath.value.trim()) checkKb();
    gate();
  };
  function checkKb() {
    ask("probe", {kind: st.mode, path: kbPath.value}).then((found) => {
      kbNote.className = "su-note" + (found.ok ? " good" : " bad");
      kbNote.textContent = !found.ok ? found.why : st.mode === "package" ? t("setup.kb.package.ok", {version: found.version, n: found.new}) : found.why || t("setup.kb.folder.ok");
      if (found.prefix && !prefix.value) prefix.value = found.prefix;
    }, () => {});
  }
  const go = h("button", {type: "button", class: "act hot big"}, t("setup.finish"));
  const goNote = h("span", {class: "su-note"});
  function gate() {  // what the server would refuse for being empty, said before the button is pressed
    const lacking = !name.value.trim() ? t("setup.name.need", {limit: 100}) : st.mode !== "none" && !kbPath.value.trim() ? t("setup.kb.path") : !st.ready ? t("setup.finish.first") : "";
    go.disabled = st.busy || Boolean(lacking);
    goNote.textContent = lacking || t("setup.finish.note");
  }
  const chips = ["en", "zh"].map((lang) => {
    const chip = h("button", {type: "button", class: "chip", "data-lang": lang}, t("desk.send.lang." + lang));
    chip.addEventListener("click", () => setLang(lang));
    return chip;
  });
  const setLang = (lang) => { st.lang = lang; chips.forEach((chip) => { const on = chip.dataset.lang === lang; chip.classList.toggle("on", on); chip.setAttribute("aria-pressed", on ? "true" : "false"); }); };
  const star = () => h("b", {class: "su-star", "aria-hidden": "true"}, " *");
  const kbStar = star();
  kbStar.hidden = true;
  const companyState = h("p", {class: "su-state"});
  const standardsState = h("p", {class: "su-state"});
  const needs = (key) => st.guide.missing.includes(key) || (key === "kb" && st.guide.missing.includes("domains"));
  function paintStates() {
    const state = (node, need, text) => node.replaceChildren(h("span", {class: "su-dot " + (need ? "need" : "ok")}), text);
    state(companyState, needs("instructions"), t(needs("instructions") ? "setup.company.need" : "setup.company.ok"));
    state(standardsState, needs("standards"), t(needs("standards") ? "setup.standards.need" : st.guide.declared.includes("standards") ? "setup.standards.none" : "setup.standards.ok"));
  }
  function loadGuide() {
    return ask("guide").then((found) => { st.guide = found; paintStates(); }, (error) => { said.replaceChildren(...SERVE.reasons(error.message || error)); });
  }
  const question = (key) => {
    const button = h("button", {type: "button", class: "su-q", "aria-label": t("setup.help"), title: t("setup.help")}, "?");
    button.addEventListener("click", () => help(key));
    return button;
  };
  const row = (label, ...nodes) => h("div", {class: "su-row"}, h("span", {class: "su-k"}, label), h("div", {class: "su-v"}, nodes));

  const testOut = h("div");
  function testShort(button) {
    button.disabled = true;
    ask("test").then((found) => {
      button.disabled = false;
      const parts = [];
      if (found.why) parts.push(h("p", {class: "su-note bad"}, found.why));
      if (found.output) {
        const art = found.ok && found.output.includes("\u2588");
        const line = (text) => {  // the robot fills the first 20 columns
          const robot = text.slice(0, 20).split("\u25cf").flatMap((part, at) => (at ? [h("b", {class: "su-eye"}, "\u25cf"), part] : [part]));
          const right = text.slice(20);
          return [...robot, /[\u2500-\u259f]/.test(right) ? h("span", {class: "su-art"}, right) : right, "\n"];
        };
        parts.push(h("pre", {class: "su-out" + (found.ok ? "" : " bad") + (art ? " art" : "")}, art ? found.output.split("\n").map(line) : found.output));
      }
      if (found.python) parts.push(h("p", {class: "su-warn"}, found.python));
      testOut.replaceChildren(...parts);
    }, (error) => { button.disabled = false; testOut.replaceChildren(h("p", {class: "su-note bad"}, error.message || String(error))); });
  }

  function paintShort(found) {
    const key = JSON.stringify([found.short, found.reopen]);
    if (key === st.shortKey) return;  // the poll must not take away the button the person is about to press
    st.shortKey = key;
    const done = Boolean(found.short.found);
    const parts = [h("div", {class: "su-head"}, h("span", {class: "su-mark" + (done ? " ok" : "")}, done ? "\u2713" : "1"), h("h2", null, t("setup.short.title")), done ? h("code", {class: "su-found"}, found.short.found) : null)];
    if (!done) {
      const copy = h("button", {type: "button", class: "act", "data-label": t("desk.code.copy")}, t("desk.code.copy"));
      copy.addEventListener("click", () => copyCommand(copy, found.short.command));
      const run = h("button", {type: "button", class: "act hot"}, t("setup.short.run"));
      const out = h("p", {class: "su-note bad", hidden: ""});
      run.addEventListener("click", () => {
        run.disabled = true;
        ask("short").then(load, (error) => { run.disabled = false; out.hidden = false; out.textContent = error.message || String(error); });
      });
      parts.push(h("p", {class: "su-note"}, t("setup.short.do")), h("div", {class: "su-cmd"}, h("code", null, found.short.command), copy), h("div", {class: "su-end"}, run), out);
    } else {
      if (found.reopen) parts.push(h("p", {class: "su-warn"}, t("setup.short.reopen")));
      const test = h("button", {type: "button", class: "act"}, t("setup.short.test"));
      test.addEventListener("click", () => testShort(test));
      parts.push(h("div", {class: "su-end"}, test, h("code", {class: "su-note"}, "harness --version")), testOut);
      if (!st.tested) { st.tested = true; testShort(test); }
    }
    shortBox.replaceChildren(...parts);
  }

  function paint(found) {
    paintShort(found);
    if (!st.form) {
      st.form = true;
      name.value = found.name;
      st.root = found.repos_root;
      st.rootFound = found.root;
      st.singles = found.singles.slice();
      st.broken = found.broken;
      paintRepos();
      setLang(found.language);
      setMode("none");
      refusedBox.placeholder = found.example;
      prefix.value = found.skill_prefix || "";
      if (found.problem) said.replaceChildren(...SERVE.reasons(found.problem));
    }
    st.ready = Boolean(found.short.found);
    gate();
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
      else { st.busy = false; gate(); }
    }, (error) => { st.busy = false; gate(); said.replaceChildren(...SERVE.reasons(error.message || error)); });
  }
  go.addEventListener("click", () => {
    st.busy = true;
    gate();
    said.replaceChildren();
    ask("act", {name: name.value, language: st.lang, repos_root: st.root, singles: st.singles, kb_mode: st.mode, kb_path: kbPath.value, skill_prefix: prefix.value, install_command: install.value, refused: st.refused}).then(follow,
      (error) => { st.busy = false; gate(); said.replaceChildren(...SERVE.reasons(error.message || error)); });
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
  name.addEventListener("input", gate);
  kbPath.addEventListener("input", () => { gate(); clearTimeout(st.probe); st.probe = setTimeout(checkKb, 400); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !st.timer) load(); });

  const olderLink = h("button", {type: "button", class: "su-link"}, t("setup.older.title"));
  olderLink.addEventListener("click", older);
  const first = new URLSearchParams(location.search).has("first");
  const words = (spans) => (spans || []).map((span) => {  // the page builds every node: nothing of the file is markup
    if (span.t === "code") return h("code", null, span.v);
    if (span.t === "b") return h("b", null, words(span.c));
    if (span.t === "i") return h("i", null, words(span.c));
    if (span.t === "br") return h("br");
    if (span.t === "a" && /^https?:/i.test(span.href)) return h("a", {href: span.href, target: "_blank", rel: "noopener noreferrer"}, words(span.c));
    return span.v !== undefined ? span.v : words(span.c);
  });
  function doc(list) {  // the words of docs/03-configure.md
    return list.map((block) => {
      if (block.t === "h") return h("h4", null, words(block.spans));
      if (block.t === "p") return h("p", {class: "su-doc"}, words(block.spans));
      if (block.t === "code") return h("pre", {class: "su-cmd"}, block.text);
      if (block.t === "ul" || block.t === "ol") return h(block.t, {class: "su-doc"}, block.items.map((item) => h("li", null, words(item.spans))));
      if (block.t === "table") return h("div", {class: "scroll"}, h("table", {class: "md"}, h("thead", null, h("tr", null, block.head.map((cell) => h("th", null, words(cell))))), h("tbody", null, block.rows.map((cells) => h("tr", null, cells.map((cell) => h("td", null, words(cell))))))));
      return null;
    });
  }
  // One window for every question mark, with a tab for each part: the words link to each other.
  function help(key) {
    if (!st.guide) { loadGuide().then(() => { if (st.guide) help(key); }); return; }
    const stage = h("div", {class: "dock-list su-help"});
    const close = h("button", {type: "button", class: "act"}, t("board.new.close"));
    const dot = (part) => h("span", {class: "su-dot " + (needs(part.key) ? "need" : "ok")});
    const tabs = st.guide.sections.map((part) => {
      const tab = h("button", {type: "button", class: "chip", "data-key": part.key}, dot(part), part.title);
      tab.addEventListener("click", () => show(part));
      return tab;
    });
    const view = SERVE.dialog([h("h2", null, t("setup.help.title")), h("div", {class: "chips dock-tabs"}, tabs), stage, h("div", {class: "row"}, close)]);
    view.box.classList.add("dock-window");
    close.addEventListener("click", view.close);
    function show(part) {
      tabs.forEach((tab) => tab.classList.toggle("on", tab.dataset.key === part.key));
      let none = null;
      if (part.can_declare) {
        const box = h("input", {type: "checkbox", checked: st.guide.declared.includes(part.key) ? "" : null});
        box.addEventListener("change", () => ask("none", {key: part.key, on: box.checked}).then(loadGuide).then(() => tabs.forEach((tab, index) => tab.firstChild.replaceWith(dot(st.guide.sections[index])))));
        none = h("label", {class: "su-none"}, box, h("span", null, t("setup.none")));
      }
      stage.replaceChildren(...[none, ...doc(part.blocks)].filter(Boolean));
      stage.scrollTop = 0;
    }
    show(st.guide.sections.find((part) => part.key === key) || st.guide.sections[0]);
  }
  loadGuide();
  app.replaceChildren(h("div", {class: "su"}, h("h1", null, t(first ? "setup.title" : "setup.guide")), h("p", {class: "su-lead"}, t("setup.lead"), " ", olderLink), shortBox,
    h("section", {class: "su-card"}, h("div", {class: "su-head"}, h("span", {class: "su-mark"}, "2"), h("h2", null, t("setup.form.title"))),
      row([t("setup.name"), star()], name), row([t("setup.language"), star()], h("span", {class: "chips su-modes"}, chips)), row([t("setup.repos"), question("repos")], h("div", {class: "su-line"}, repos, repoAdd, browse(repos, "folder", () => { repoAdd.disabled = false; addRepo(); })), repoNote, repoPick, repoList, h("p", {class: "su-note"}, t("setup.repos.hint"))),
      row([t("setup.kb"), kbStar, question("kb")], h("div", {class: "chips su-modes"}, modes), h("div", {class: "su-line"}, kbPath, kbPick), kbNote), row([t("setup.company"), question("instructions")], companyState), row([t("setup.prefix"), question("skills")], prefix, h("p", {class: "su-note"}, t("setup.prefix.hint"))), row([t("setup.standards"), question("standards")], standardsState),
      h("details", {class: "su-more"}, h("summary", {class: "su-note"}, t("setup.more")), row([t("setup.install"), question("python")], install, h("p", {class: "su-note"}, t("setup.install.example"))), row([t("setup.refused"), question("repos")], h("div", {class: "su-line"}, refusedBox, refusedAdd), refusedNote, refusedList, h("p", {class: "su-note"}, t("setup.refused.hint")))),
      h("div", {class: "su-end"}, go, goNote), said)));
  gate();
  load();
})();
