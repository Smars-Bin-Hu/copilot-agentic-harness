// Get ready (1.6.57): one command, then one form. No agent runs. The server does the work (core/setup.py): this page shows and sends. Its own page, and a window over the board (dock.js).
// Needs common.js (h, t, copyCommand), serve.js (SERVE), dock.js (DOCK: the knowledge base tip opens its window).
const SETUP = (function () {
  // Draws the page in `app`. `finished`: what to do when the setup is done; none on the page of its own, which goes to the board. A box taken off the page stops the asking.
  function mount(app, finished) {
    const POLL = 2000, SLOW = 8000;  // slow once the short command is found: only a change from a terminal is left to see
    const leave = finished || (() => location.assign("/"));
    const st = {form: null, timer: 0, probe: 0, refused: [], rules: [], busy: false, saved: false, ready: false, mode: "none", root: "", rootFound: null, singles: [], broken: [], full: false, replace: false, kb: {here: false, domains: 0, prefix: ""}, stamp: "", opened: "", latest: null};
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
    const kbParts = h("div", {class: "su-parts", hidden: ""});
    const kbLearn = h("button", {type: "button", class: "su-link"}, t("setup.kb.learn"));
    kbLearn.addEventListener("click", () => DOCK.allSkills("kb"));
    // The picker on the page: the server reads one folder at a time, and no program starts. The window of the system stays as the second way.
    function chooseOnPage(kind, start, done) {
      const file = kind === "file";
      const here = h("code", {class: "su-pick-path"});
      const list = h("div", {class: "su-pick-list"});
      const note = h("p", {class: "su-note"});
      const drives = h("div", {class: "chips"});
      const up = h("button", {type: "button", class: "act"}, t("setup.pick.up"));
      const use = h("button", {type: "button", class: "act hot"}, t("setup.pick.use"));
      const system = h("button", {type: "button", class: "su-link"}, t("setup.pick.system"));
      const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
      const view = SERVE.dialog([h("h2", null, t(file ? "setup.pick.file" : "setup.pick.folder")), here, drives, list, note, h("div", {class: "row"}, up, file ? "" : use, no, system)]);
      let now = null;
      const pickIt = (path) => { view.close(); done(path); };
      const row = (name, click) => { const node = h("button", {type: "button", class: "su-pick-row"}, name); node.addEventListener("click", click); return node; };
      const join = (name) => now.path.replace(/[\\/]+$/, "") + (now.path.includes("\\") ? "\\" : "/") + name;
      function open(path) {
        note.textContent = t("setup.pick.reading");
        SERVE.call("/api/setup", {step: "folders", path, kind}, 20).then((data) => {
          now = data.result;
          here.textContent = now.path;
          up.disabled = !now.parent;
          drives.replaceChildren(...now.drives.map((drive) => { const chip = h("button", {type: "button", class: "chip"}, drive); chip.addEventListener("click", () => open(drive)); return chip; }));
          list.replaceChildren(...now.folders.map((name) => row(name, () => open(join(name)))), ...now.zips.map((name) => row(name, () => pickIt(join(name)))));
          note.textContent = now.error ? t("setup.pick.bad", {error: now.error}) : now.cut ? t("setup.pick.cut") : list.firstChild ? "" : t("setup.pick.empty");
        }, (error) => { note.textContent = error.message; });
      }
      up.addEventListener("click", () => open(now.parent));
      use.addEventListener("click", () => pickIt(now.path));
      no.addEventListener("click", view.close);
      system.addEventListener("click", () => {
        system.disabled = true;
        note.textContent = t("setup.pick.opening");
        ask("pick", {kind}).then((found) => { system.disabled = false; note.textContent = ""; if (found.path) pickIt(found.path); }, (error) => { system.disabled = false; note.textContent = error.message || String(error); });
      });
      open(start || "");
    }
    const kbPick = h("button", {type: "button", class: "act"}, t("setup.browse"));
    kbPick.addEventListener("click", () => chooseOnPage(kbPick.dataset.kind, kbPath.value.trim(), (path) => { kbPath.value = path; checkKb(); gate(); }));
    const kbReplaceBox = h("input", {type: "checkbox"});
    const kbReplace = h("label", {class: "su-tick", hidden: ""}, kbReplaceBox, h("span", null, t("setup.kb.replace")));
    kbReplaceBox.addEventListener("change", () => { st.replace = kbReplaceBox.checked; gate(); });
    const prefix = h("input", {type: "text", class: "su-in su-short", maxlength: 31, autocomplete: "off", spellcheck: "false"});
    const install = h("input", {type: "text", class: "su-in su-mono", maxlength: 500, autocomplete: "off", spellcheck: "false", placeholder: t("setup.install.ph")});
    const refusedBox = h("input", {type: "text", class: "su-in su-mono", maxlength: 1024, autocomplete: "off", spellcheck: "false"});
    const refusedAdd = h("button", {type: "button", class: "act"}, t("setup.refused.add"));
    const refusedList = h("div", {class: "su-list"});
    const refusedNote = h("p", {class: "su-note bad", hidden: ""});
    const changedLoad = h("button", {type: "button", class: "su-link"}, t("setup.changed.load"));
    const changed = h("p", {class: "su-warn", hidden: ""}, t("setup.changed"), " ", changedLoad);
    changedLoad.addEventListener("click", () => fill(st.latest));
    const broken = h("p", {class: "su-note bad", hidden: ""});
    function paintRules() {
      const chip = (text, off) => {
        const button = h("button", {type: "button", class: "su-x", "aria-label": t("setup.refused.remove")}, "\u00d7");
        button.addEventListener("click", () => { off(); paintRules(); });
        return h("span", {class: "su-item"}, h("code", null, text), button);
      };
      refusedList.replaceChildren(...st.rules.map((rule) => chip(rule.repo + ": " + rule.rule, () => { st.rules = st.rules.filter((held) => held !== rule); })), ...st.refused.map((path) => chip(path, () => { st.refused = st.refused.filter((held) => held !== path); })));
    }
    function paintRepos() {
      const item = (text, ok, why, off) => {
        const button = h("button", {type: "button", class: "su-x", "aria-label": t("setup.repos.remove")}, "\u00d7");
        button.addEventListener("click", () => { off(); paintRepos(); });
        return h("span", {class: "su-item"}, h("span", {class: "su-dot " + (ok ? "ok" : "bad"), title: why}), h("span", {class: "su-repo"}, h("code", null, text), h("span", {class: "su-note" + (ok ? " good" : " bad")}, why)), button);
      };
      const parts = [];
      const folder = (path) => path.split(/[\\/]/).pop();
      const keepRules = (test) => { st.rules = st.rules.filter(test); paintRules(); };  // a rule goes with its repository
      if (st.root) parts.push(item(st.root, st.rootFound.n > 0, st.rootFound.n ? t("setup.repos.found", {n: st.rootFound.n, names: st.rootFound.names.join(", ")}) : st.rootFound.why, () => { st.root = ""; st.rootFound = null; keepRules((rule) => st.singles.some((path) => folder(path) === rule.repo)); }));
      st.singles.forEach((path) => { const ok = !st.broken.includes(path); parts.push(item(path, ok, t(ok ? "setup.repos.valid" : "setup.repos.invalid"), () => { st.singles = st.singles.filter((held) => held !== path); keepRules((rule) => rule.repo !== folder(path)); })); });
      repoList.replaceChildren(...parts);
    }
    function pickRepos(found) {
      const take = h("button", {type: "button", class: "act hot"}, t("setup.repos.take"));
      const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
      const rows = found.repos.map((repo) => {
        const box = h("input", {type: "checkbox", disabled: repo.held || repo.off ? "" : null});
        box.addEventListener("change", sync);
        return {repo, box, node: h("label", {class: "su-tick"}, box, h("code", null, repo.name), repo.held || repo.off ? h("span", {class: "su-note"}, repo.off || t("setup.repos.held")) : null)};
      });
      const free = rows.filter((row) => !row.repo.held && !row.repo.off);
      const all = h("input", {type: "checkbox", disabled: free.length ? null : ""});
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
    repos.addEventListener("keydown", (event) => { if (isEnter(event)) addRepo(); });
    function addRefused() {
      if (!refusedBox.value.trim()) return;
      ask("refuse", {repos_root: st.root, singles: st.singles, path: refusedBox.value}).then((found) => {
        refusedNote.hidden = true;
        refusedBox.value = "";
        refusedAdd.disabled = true;
        if (st.refused.includes(found.path)) return;
        st.refused.push(found.path);
        paintRules();
      }, (error) => { refusedNote.hidden = false; refusedNote.textContent = error.message || String(error); });
    }
    refusedAdd.disabled = true;
    refusedBox.addEventListener("input", () => { refusedAdd.disabled = !refusedBox.value.trim(); });
    refusedAdd.addEventListener("click", addRefused);
    refusedBox.addEventListener("keydown", (event) => { if (isEnter(event)) addRefused(); });
    const browse = (input, kind, after) => {
      const button = h("button", {type: "button", class: "act"}, t("setup.browse"));
      button.addEventListener("click", () => chooseOnPage(kind, input.value.trim(), (path) => { input.value = path; after(); }));
      return button;
    };
    const modes = ["package", "folder", "none"].map((mode) => {
      const chip = h("button", {type: "button", class: "chip", "data-mode": mode}, t("setup.kb." + mode));
      chip.dataset.label = chip.textContent;
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
      paintParts(null);
      kbNote.replaceChildren(...(mode !== "none" ? [] : st.kb.here ? [t("setup.kb.have", {n: st.kb.domains})] : [t("setup.kb.none.hint"), " ", kbLearn]));
      st.full = false;
      paintReplace();
      if (mode !== "none" && kbPath.value.trim()) checkKb();
      gate();
    };
    function paintReplace() {
      kbReplace.hidden = !st.full;
      if (!st.full) { st.replace = false; kbReplaceBox.checked = false; }
    }
    // The check of a chosen folder (`company.layout`): green for what is right, a warning with the place for the rest. It stops nothing, and it says what the states below will say.
    function paintParts(parts) {
      st.parts = parts || null;
      const off = (parts || []).filter((item) => !item.ok);
      kbParts.hidden = !parts;
      kbParts.replaceChildren(...(off.length ? [h("p", {class: "su-note su-warned"}, t("setup.layout.warn"))] : []), ...(parts || []).map((item) => h("p", {class: "su-state"}, h("span", {class: "su-dot " + (item.ok ? "ok" : "need")}), item.text)));
      paintStates();
    }
    function checkKb() {
      ask("probe", {kind: st.mode, path: kbPath.value}).then((found) => {
        kbNote.className = "su-note" + (found.full ? "" : !found.ok ? " bad" : found.why ? "" : " good");  // a knowledge base in place is a choice to make, not a fault
        kbNote.textContent = !found.ok ? found.why : st.mode === "package" ? t("setup.kb.package.ok", {version: found.version, new: found.new, changed: found.changed, removed: found.removed}) + (found.local ? " " + t("setup.kb.package.local", {n: found.local}) : "") : found.why || t("setup.kb.folder.ok");
        st.full = Boolean(found.full);
        paintParts(st.mode === "folder" && kbPath.value.trim() ? found.parts || [] : null);
        paintReplace();
        if (found.prefix && !prefix.value) prefix.value = found.prefix;
        gate();
      }, () => { paintParts(null); });
    }
    const go = h("button", {type: "button", class: "act hot big"}, t(finished ? "setup.save" : "setup.finish"));
    const goNote = h("span", {class: "su-note"});
    function gate() {  // what the server would refuse for being empty, said before the button is pressed
      const lacking = !name.value.trim() ? t("setup.name.need", {limit: 100}) : st.mode !== "none" && !kbPath.value.trim() ? t("setup.kb.path") : st.full && !st.replace ? t("setup.kb.replace.need") : !st.ready ? t("setup.finish.first") : "";
      go.disabled = st.busy || st.saved || Boolean(lacking);
      goNote.textContent = st.busy ? t("setup.finish.working") : st.saved ? "" : lacking || t("setup.finish.note");
    }
    const values = () => ({name: name.value, language: st.lang, repos_root: st.root, singles: st.singles, kb_mode: st.mode, kb_path: kbPath.value, kb_replace: st.replace, skill_prefix: prefix.value, install_command: install.value, refused: st.refused, rules: st.rules});
    const chips = ["en", "zh"].map((lang) => {
      const chip = h("button", {type: "button", class: "chip", "data-lang": lang}, t("desk.send.lang." + lang));
      chip.addEventListener("click", () => setLang(lang));
      return chip;
    });
    const langNote = h("p", {class: "su-note", hidden: ""}, t("setup.language.forced"));
    const setLang = (lang) => { st.lang = lang; chips.forEach((chip) => { const on = chip.dataset.lang === lang; chip.classList.toggle("on", on); chip.setAttribute("aria-pressed", on ? "true" : "false"); }); };
    const star = () => h("b", {class: "su-star", "aria-hidden": "true"}, " *");
    const kbStar = star();
    kbStar.hidden = true;
    const companyState = h("p", {class: "su-state"});
    const standardsState = h("p", {class: "su-state"});
    const needs = (key) => st.guide.missing.includes(key) || (key === "kb" && st.guide.missing.includes("domains"));
    function paintStates() {
      if (!st.guide) return;
      const state = (node, need, text) => node.replaceChildren(h("span", {class: "su-dot " + (need ? "need" : "ok")}), text);
      const has = (key) => st.parts.some((item) => item.key === key && item.ok);  // a folder chosen just now speaks for itself, before it is copied
      const missing = (key) => (st.parts ? !has(key) : needs(key));
      state(companyState, missing("instructions"), t(missing("instructions") ? "setup.company.need" : "setup.company.ok"));
      state(standardsState, missing("standards"), t(missing("standards") ? "setup.standards.need" : st.parts || !st.guide.declared.includes("standards") ? "setup.standards.ok" : "setup.standards.none"));
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
          const lines = found.output.split("\n");
          const size = found.ok ? lines.findIndex((line) => !/[\u2500-\u259f]/.test(line)) : 0;  // the drawn letters come first
          parts.push(h("pre", {class: "su-out" + (found.ok ? "" : " bad")}, size > 0 ? h("span", {class: "su-art"}, lines.slice(0, size).join("\n")) : null, lines.slice(Math.max(size, 0)).join("\n")));
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
        if (!st.tested && !finished) { st.tested = true; testShort(test); }  // the window is for changing a setting: the test is a button there
      }
      shortBox.replaceChildren(...parts);
    }

    function fill(found) {  // what is set now: the form starts from it, and sends all of it back
      st.form = true;
      name.value = found.name;
      st.root = found.repos_root;
      st.rootFound = found.root;
      st.singles = found.singles.slice();
      st.broken = found.broken;
      st.rules = found.rules.slice();
      st.refused = [];
      st.kb = found.kb;
      st.stamp = found.stamp;
      paintRepos();
      paintRules();
      setLang(found.language);
      chips.forEach((chip) => { chip.disabled = found.language_forced; });
      langNote.hidden = !found.language_forced;
      const keep = modes.find((chip) => chip.dataset.mode === "none");
      keep.textContent = found.kb.here ? t("setup.kb.keep") : keep.dataset.label;
      setMode("none");
      refusedBox.placeholder = found.example;
      prefix.value = found.skill_prefix || found.kb.prefix || "";
      install.value = found.install_command;
      more.open = Boolean(found.install_command || found.rules.length);
      changed.hidden = true;
      st.opened = JSON.stringify(values());
    }
    function paint(found) {
      paintShort(found);
      if (!st.form) fill(found);
      app.classList.remove("su-loading");
      st.latest = found;
      changed.hidden = !found.stamp || found.stamp === st.stamp || st.busy || st.saved;
      broken.textContent = found.problem;  // a poll tells it too: the file can break while the form is open
      broken.hidden = !found.problem;
      st.ready = Boolean(found.short.found);
      gate();
    }

    function load() {
      clearTimeout(st.timer);
      if (!app.isConnected) return Promise.resolve();
      return ask("state").then(paint, (error) => { app.classList.remove("su-loading"); said.replaceChildren(...SERVE.reasons(error.message || error)); }).then(() => { if (!document.hidden) st.timer = setTimeout(load, st.ready ? SLOW : POLL); else st.timer = 0; });
    }

    const paintLines = (found) => said.replaceChildren(...found.lines.map((line) => h("p", {class: line.ok ? "su-note good" : "su-note bad"}, (line.ok ? "\u2713 " : "\u2717 ") + t("setup.line." + line.key) + ": " + line.detail)));
    function follow() {
      ask("job").then((found) => {
        paintLines(found);
        if (found.running) { setTimeout(follow, 700); return; }
        st.busy = false;
        st.stamp = found.stamp;  // what was written here is not a change from elsewhere
        st.saved = found.done;
        gate();
        if (!found.done) return;
        said.append(h("p", {class: "su-note good"}, t("setup.saved")));
        leave();
      }, (error) => { st.busy = false; gate(); said.replaceChildren(...SERVE.reasons(error.message || error)); });
    }
    go.addEventListener("click", () => {
      st.busy = true;
      gate();
      said.replaceChildren();
      ask("act", {...values(), stamp: st.stamp}).then(follow,
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
      const count = (list) => Object.entries(list || {}).map(([group, names]) => group + ": " + names.length).join(", ") || "-";
      const told = (key, list) => (list || []).map((item) => h("p", {class: "su-note" + (key === "setup.older.failed" ? " bad" : "")}, t(key, {what: item.what, why: item.why})));
      look.addEventListener("click", () => ask("older", {path: path.value}).then((found) => {
        out.replaceChildren(t("setup.older.plan", {from: found.from, groups: count(found.would_copy)}), ...told("setup.older.skipped", found.skipped));
        apply.hidden = false;
      }, (error) => { out.textContent = error.message || String(error); }));
      apply.addEventListener("click", () => {
        apply.disabled = true;
        ask("older", {path: path.value, apply: true}).then((found) => {
          out.replaceChildren(t("setup.older.done", {groups: count(found.copied)}), ...told("setup.older.failed", found.failed), ...told("setup.older.skipped", found.skipped));
          look.hidden = apply.hidden = true;
          no.textContent = t("board.new.close");
          no.addEventListener("click", finished ? load : leave);  // in the window the note says what changed; what was typed stays
        }, (error) => { apply.disabled = false; out.textContent = error.message || String(error); });
      });
    }
    name.addEventListener("input", gate);
    kbPath.addEventListener("input", () => { st.full = false; paintReplace(); gate(); clearTimeout(st.probe); st.probe = setTimeout(checkKb, 400); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden && !st.timer && app.isConnected) load(); });

    const olderLink = h("button", {type: "button", class: "su-link"}, t("setup.older.title"));
    olderLink.addEventListener("click", older);
    const first = !finished && new URLSearchParams(location.search).has("first");
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
    const more = h("details", {class: "su-more"}, h("summary", {class: "su-note"}, t("setup.more")), row([t("setup.install"), question("python")], install, h("p", {class: "su-note"}, t("setup.install.example"))), row([t("setup.refused"), question("repos")], h("div", {class: "su-line"}, refusedBox, refusedAdd), refusedNote, refusedList, h("p", {class: "su-note"}, t("setup.refused.hint"))));
    app.classList.add("su-loading");  // an empty form that jumps when its data comes is worse than a moment of nothing
    app.replaceChildren(h("div", {class: "su"}, h("h1", null, t(first ? "setup.title" : "setup.guide")), h("p", {class: "su-lead"}, t(finished ? "setup.lead.again" : "setup.lead"), " ", olderLink), shortBox,
      h("section", {class: "su-card"}, h("div", {class: "su-head"}, h("span", {class: "su-mark"}, "2"), h("h2", null, t("setup.form.title"))),
        changed, broken, row([t("setup.name"), star()], name), row([t("setup.language"), star()], h("span", {class: "chips su-modes"}, chips), langNote), row([t("setup.repos"), question("repos")], h("div", {class: "su-line"}, repos, repoAdd, browse(repos, "folder", () => { repoAdd.disabled = false; addRepo(); })), repoNote, repoPick, repoList, h("p", {class: "su-note"}, t("setup.repos.hint"))),
        row([t("setup.kb"), kbStar, question("kb")], h("div", {class: "chips su-modes"}, modes), h("div", {class: "su-line"}, kbPath, kbPick), kbNote, kbParts, kbReplace), row([t("setup.company"), question("instructions")], companyState), row([t("setup.prefix"), question("skills")], prefix, h("p", {class: "su-note"}, t("setup.prefix.hint"))), row([t("setup.standards"), question("standards")], standardsState),
        more, h("div", {class: "su-end"}, go, goNote), said)));
    gate();
    load();
    return {busy: () => st.busy, dirty: () => Boolean(st.form) && !st.saved && JSON.stringify(values()) !== st.opened};
  }
  if (DATA.getReady) {
    document.body.classList.add("su-page");
    mount(document.getElementById("app"));
  }
  return {mount};
})();
