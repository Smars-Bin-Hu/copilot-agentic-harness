// Get ready (1.6.57): one command, then one form. No agent runs. The server does the work (core/setup.py): this page shows and sends.
// Needs common.js (h, t, copyCommand), serve.js (SERVE).
(function () {
  const app = document.getElementById("app");
  const POLL = 2000;
  const st = {form: null, timer: 0, probe: 0, refused: [], busy: false, ready: false, mode: "none", root: "", rootFound: null, singles: []};
  const ask = (step, body) => SERVE.post("/api/setup", {step, ...(body || {})}).then((data) => data.result);

  const shortBox = h("section", {class: "su-card"});
  const said = h("div", {class: "su-said"});
  const repoNote = h("p", {class: "su-note bad", hidden: ""});
  const repoList = h("div", {class: "su-list"});
  const repoAdd = h("button", {type: "button", class: "act"}, t("setup.refused.add"));
  const name = h("input", {type: "text", class: "su-in", maxlength: 100, autocomplete: "name", spellcheck: "false", required: ""});
  const repos = h("input", {type: "text", class: "su-in su-mono", maxlength: 1024, autocomplete: "off", spellcheck: "false", placeholder: t("setup.repos.ph")});
  const kbPath = h("input", {type: "text", class: "su-in su-mono", maxlength: 1024, autocomplete: "off", spellcheck: "false", hidden: ""});
  const kbNote = h("p", {class: "su-note"});
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
    const item = (text, off) => {
      const button = h("button", {type: "button", class: "su-x", "aria-label": t("setup.repos.remove")}, "\u00d7");
      button.addEventListener("click", () => { off(); paintRepos(); });
      return h("span", {class: "su-item"}, h("code", null, text), button);
    };
    const parts = [];
    if (st.root) parts.push(item(st.root + "  \u00b7  " + t("setup.repos.found", {n: st.rootFound.n, names: st.rootFound.names.join(", ")}), () => { st.root = ""; st.rootFound = null; }));
    st.singles.forEach((path) => parts.push(item(path, () => { st.singles = st.singles.filter((held) => held !== path); })));
    repoList.replaceChildren(...parts);
  }
  function addRepo() {
    if (!repos.value.trim()) return;
    ask("repo", {path: repos.value, repos_root: st.root, singles: st.singles}).then((found) => {
      repoNote.hidden = true;
      repos.value = "";
      repoAdd.disabled = true;
      if (found.kind === "repo") st.singles.push(found.path);
      else { st.root = found.path; st.rootFound = found; }
      paintRepos();
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
    kbNote.textContent = mode === "none" ? t("setup.kb.none.hint") : "";
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
      row([t("setup.name"), star()], name), row([t("setup.language"), star()], h("span", {class: "chips su-modes"}, chips)), row(t("setup.repos"), h("div", {class: "su-line"}, repos, repoAdd, browse(repos, "folder", () => { repoAdd.disabled = false; addRepo(); })), repoNote, repoList, h("p", {class: "su-note"}, t("setup.repos.hint"))),
      row([t("setup.kb"), kbStar], h("div", {class: "chips su-modes"}, modes), h("div", {class: "su-line"}, kbPath, kbPick), kbNote), row(t("setup.prefix"), prefix, h("p", {class: "su-note"}, t("setup.prefix.hint"))),
      h("details", {class: "su-more"}, h("summary", {class: "su-note"}, t("setup.more")), row(t("setup.install"), install, h("p", {class: "su-note"}, t("setup.install.example"))), row(t("setup.refused"), h("div", {class: "su-line"}, refusedBox, refusedAdd), refusedNote, refusedList, h("p", {class: "su-note"}, t("setup.refused.hint")))),
      h("div", {class: "su-end"}, go, goNote), said), first ? null : guideBox));
  gate();
  load();
})();
