// Get ready (1.6.57): one command, then one form. No agent runs. The server does the work (core/setup.py): this page shows and sends. Its own page, and a window over the board (dock.js).
// Needs common.js (h, t, copyCommand), serve.js (SERVE), dock.js (DOCK: the knowledge base tip opens its window).
const SETUP = (function () {
  // Draws the page in `app`. `finished`: what to do when the setup is done; none on the page of its own, which goes to the board. A box taken off the page stops the asking.
  function mount(app, finished, onbusy) {  // `onbusy(true|false)`: the window around the form hides its Close while the work runs
    const POLL = 2000, SLOW = 8000;  // slow once the short command is found: only a change from a terminal is left to see
    const leave = finished || (() => location.assign("/"));
    const st = {form: null, timer: 0, probe: 0, refused: [], rules: [], busy: false, saved: false, ready: false, mode: "none", root: "", rootFound: null, singles: [], broken: [], full: false, replace: false, kb: {here: false, domains: 0, prefix: ""}, stamp: "", opened: "", latest: null, tools: null, probePrefix: ""};
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
    const kbDot = h("span", {class: "su-dot need"});  // the dot of the knowledge base row: in place, or the folder chosen just now reads well (1.7.38)
    const kbInfo = h("div", {class: "su-kbinfo"});  // path, domains, domain skills, version of the knowledge base that is in place
    const repoDot = h("span", {class: "su-dot need"});
    const kbParts = h("div", {class: "su-parts", hidden: ""});
    const kbChanges = h("div", {class: "su-changes", hidden: ""});  // what an update from the folder would change, listed before the person ticks (Q5)
    const kbLearn = h("button", {type: "button", class: "su-link"}, t("setup.kb.learn"));
    kbLearn.addEventListener("click", () => DOCK.allSkills("kb"));
    const kbPick = h("button", {type: "button", class: "act"}, t("setup.browse"));
    kbPick.hidden = true;
    kbPick.addEventListener("click", () => DOCK.chooseOnPage(kbPick.dataset.kind, kbPath.value.trim(), (path) => { kbPath.value = path; checkKb(); gate(); }));
    const kbReplaceBox = h("input", {type: "checkbox"});
    const kbReplaceText = h("span", null, t("setup.kb.replace"));
    const kbReplace = h("label", {class: "su-tick", hidden: ""}, kbReplaceBox, kbReplaceText);
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
      repoDot.className = "su-dot " + (parts.length && parts.every((node) => !node.querySelector(".su-dot.bad")) ? "ok" : parts.length ? "bad" : "need");
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
      button.addEventListener("click", () => DOCK.chooseOnPage(kind, input.value.trim(), (path) => { input.value = path; after(); }));
      return button;
    };
    const modes = ["package", "folder", "none"].map((mode) => {
      const chip = h("button", {type: "button", class: "chip", "data-mode": mode}, t("setup.kb." + mode));
      chip.dataset.label = chip.textContent;
      chip.addEventListener("click", () => setMode(mode));
      return chip;
    });
    const modeBox = h("div", {class: "chips su-modes"}, modes);
    function paintKbInfo() {
      kbInfo.hidden = st.mode !== "none";
      modeBox.title = st.kb.here ? t("setup.kb.have.tip") : "";
      if (st.mode !== "none") return;
      const k = st.kb;
      kbInfo.replaceChildren(...(k.here ? [h("code", {class: "su-kbpath", title: k.path}, k.path), h("span", null, t("setup.kb.info.domains", {n: k.domains})), h("span", null, t("setup.kb.info.dskills", {n: k.domain_skills || 0})), k.version ? h("span", {class: "su-soft"}, t("setup.kb.info.version", {version: k.version})) : null].filter(Boolean) : [h("span", {class: "su-off"}, t("setup.fact.notfound"))]));
    }
    function kbDotPaint() {
      const ok = st.mode === "none" ? st.kb.here : Boolean(kbPath.value.trim()) && st.kbOk !== false;
      kbDot.className = "su-dot " + (ok ? "ok" : "need");
    }
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
      st.probePrefix = "";
      paintParts(null);
      kbNote.replaceChildren(...(mode !== "none" || st.kb.here ? [] : [t("setup.kb.none.line"), " ", kbLearn]));
      paintKbInfo();
      st.full = false;
      st.update = null;
      paintReplace();
      paintChanges();
      if (mode !== "none" && kbPath.value.trim()) checkKb();
      kbDotPaint();
      gate();
    };
    function paintReplace() {
      kbReplace.hidden = !st.full;
      kbReplaceText.textContent = t(st.update && st.update.state === "behind" ? "setup.kb.update.tick" : "setup.kb.replace");  // a git update, or the old replace
      if (!st.full) { st.replace = false; kbReplaceBox.checked = false; }
    }
    // The list of an update from a folder (Q5): the files it would add, change or remove, the first ones by name; for a copy that is ahead, the commits that stay.
    const MARK = {add: "+", change: "~", remove: "\u2212"};
    function paintChanges() {
      const u = st.update, rows = u && u.state === "behind" ? u.changes || [] : [];
      const subjects = u && u.state === "ahead" ? u.subjects || [] : [];
      // The commits of this copy that the folder lacks (they stay): each title once, and a button that sends them to the folder in the Terminal window (the command is the engine's, never shown here).
      const send = u && u.state === "ahead" && u.pull && typeof TERM !== "undefined" ? h("button", {type: "button", class: "act su-send", title: t("setup.kb.update.pull.tip")}, t("setup.kb.update.pull")) : null;
      if (send) send.addEventListener("click", () => { send.disabled = true; TERM.run(u.pull, checkKb); });
      kbChanges.hidden = !rows.length && !subjects.length && !send;
      kbChanges.replaceChildren(...(rows.length ? [h("ul", {class: "su-chg"}, rows.map((row) => h("li", {class: row.change}, h("b", null, MARK[row.change] || "~"), " ", h("code", null, row.path))), u.total > rows.length ? h("li", {class: "su-soft"}, t("setup.kb.update.more", {n: u.total - rows.length})) : null)] : []),
        ...(subjects.length ? [h("ul", {class: "su-chg"}, subjects.map((line) => h("li", null, line)), u.ahead > subjects.length ? h("li", {class: "su-soft"}, t("setup.kb.update.more", {n: u.ahead - subjects.length})) : null)] : []), send);
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
        kbNote.textContent = !found.ok ? plainWords(found.why) : st.mode === "package" ? t("setup.kb.package.ok", {version: found.version, new: found.new, changed: found.changed, removed: found.removed}) + (found.local ? " " + t("setup.kb.package.local", {n: found.local}) : "") : plainWords(found.why || t("setup.kb.folder.ok"));
        st.full = Boolean(found.full);
        st.update = st.mode === "folder" ? found.update || null : null;
        st.kbOk = Boolean(found.ok);
        paintParts(st.mode === "folder" && kbPath.value.trim() ? found.parts || [] : null);
        paintReplace();
        paintChanges();
        if (found.prefix && !prefix.value) prefix.value = found.prefix;
        st.probePrefix = found.prefix || "";
        gate();
      }, () => { paintParts(null); });
    }
    const go = h("button", {type: "button", class: "act hot big"}, t(finished ? "setup.save" : "setup.finish"));
    const goNote = h("span", {class: "su-note"});
    function gate() {  // what the server would refuse for being empty, said before the button is pressed
      const lacking = !name.value.trim() ? t("setup.name.need", {limit: 100}) : st.mode !== "none" && !kbPath.value.trim() ? t("setup.kb.path") : st.update && ["ahead", "unrelated", "dirty", "error"].includes(st.update.state) ? t("setup.kb.update.stop") : st.full && !st.replace ? t(st.update && st.update.state === "behind" ? "setup.kb.update.need" : "setup.kb.replace.need") : !st.ready ? t("setup.finish.first") : "";
      go.disabled = st.busy || st.saved || Boolean(lacking);
      goNote.textContent = st.busy ? t("setup.finish.working") : st.saved ? "" : lacking;
      if (onbusy) onbusy(st.busy);
    }
    const values = () => ({name: name.value, language: st.lang, repos_root: st.root, singles: st.singles, kb_mode: st.mode, kb_path: kbPath.value, kb_replace: st.replace, skill_prefix: prefix.value, install_command: install.value, refused: st.refused, rules: st.rules});
    const chips = ["en", "zh"].map((lang) => {
      const chip = h("button", {type: "button", class: "chip", "data-lang": lang}, t("desk.send.lang." + lang));
      chip.addEventListener("click", () => setLang(lang));
      return chip;
    });
    const langNote = h("span", {class: "sv-info", tabindex: "0", hidden: "", title: t("setup.language.forced")}, "\u24d8");  // only when HARNESS_LANGUAGE is set in the environment the board runs in
    const setLang = (lang) => { st.lang = lang; chips.forEach((chip) => { const on = chip.dataset.lang === lang; chip.classList.toggle("on", on); chip.setAttribute("aria-pressed", on ? "true" : "false"); }); };
    const star = () => h("b", {class: "su-star", "aria-hidden": "true"}, " *");
    const kbStar = star();
    kbStar.hidden = true;
    const needs = (key) => st.guide.missing.includes(key) || (key === "kb" && st.guide.missing.includes("domains"));
    // The facts (1.7.36): one row each, a dot, a name, one short fact; the details are on hover. `text` is a string, a node (words with parts coloured), or a list of names with a dot each.
    // `go` = [window, part]: the name opens that window of Tools there; `open` = the same as a button at the end of the row (1.7.38: the packs and the connections).
    const NAMES = 6;  // names shown on a row; the rest is "+N", all of them on hover
    const dotOf = (kind) => h("span", {class: "su-dot " + kind});
    const fact = (label, kind, text, tip, help, go, open) => {
      let key = label;
      if (go) { key = h("button", {type: "button", class: "su-fk-btn", title: t("setup.fact.open", {where: label})}, label); key.addEventListener("click", () => TOOLS.open(go[0], loadTools, go[1])); }
      let end = null;
      if (open) { end = h("button", {type: "button", class: "act su-open su-fact-open"}, t("tools.open")); end.addEventListener("click", () => TOOLS.open(open[0], loadTools, open[1])); }
      const shape = Array.isArray(text) ? " su-names" : typeof text === "string" ? " su-text" : " su-rich";
      return h("div", {class: "su-fact", "data-kind": kind, title: tip || ""}, dotOf(kind), h("b", {class: "su-fk"}, key, help ? " " : null, help ? question(help) : null), h("span", {class: "su-fv" + shape}, text), end);
    };
    const names = (items) => {  // [{name, kind, tip}] -> a name with a dot each; long lists are cut with "+N"
      const shown = items.slice(0, NAMES).map((item) => h("span", {class: "su-nm", title: item.tip || ""}, dotOf(item.kind), item.name));
      return items.length > NAMES ? [...shown, h("span", {class: "su-more-n", title: items.slice(NAMES).map((item) => item.name).join(", ")}, "+" + (items.length - NAMES))] : shown;
    };
    const part = (text, kind) => h("span", {class: kind ? "su-" + kind : null}, text);  // a piece of a row's words: "off" yellow, "soft" grey
    const openTab = (tab) => {  // the one Open of a card, in its title row
      const button = h("button", {type: "button", class: "act su-open"}, t("tools.open"));
      button.addEventListener("click", () => TOOLS.open(tab, loadTools));
      return button;
    };
    const files = (n) => t(n === 1 ? "setup.fact.file.one" : "setup.fact.files", {n});
    const factsBox = h("div", {class: "su-facts"});
    const computerBox = h("div", {class: "su-facts"});
    const lookNote = h("span", {class: "su-note"});
    function paintFacts() {
      if (!st.guide || !st.latest) return;
      const c = st.latest.company || {};
      const has = (key) => st.parts && st.parts.some((item) => item.key === key && item.ok);  // a folder chosen just now speaks for itself, before it is copied
      const missing = (key) => (st.parts ? !has(key) : needs(key));
      const rows = [], mine = [];
      let look = 0;  // rows to look at for company tasks: yellow ones, with a knowledge base in place
      const add = (list, node, kind) => { list.push(node); if (kind === "need") look++; };
      const inCopy = st.guide.company && !st.parts;  // counts are of the company folder that is here, not of one just chosen
      const lacking = missing("instructions");
      const partial = lacking && !st.parts && st.guide.company;  // the folder is there but lacks the one file: say that, not "not found" (1.7.34)
      // Only the file the engine uses counts (1.7.38), as on the Enter screen: the others are told as "not used", their names on hover.
      const counted = (n, unused) => (!inCopy || !n ? t("setup.fact.found") : h("span", null, files(n), (unused || []).length ? part(" \u00b7 " + t("setup.fact.skipped", {n: unused.length}), "soft") : null));
      const unusedTip = (unused, key, used) => ((unused || []).length ? " " + t(key, {names: unused.join(", "), used}) : "");
      add(rows, fact(t("setup.fact.company"), lacking ? "need" : "ok", lacking ? t(partial ? "setup.fact.noinstr" : "setup.fact.notfound") : counted(c.instructions_n, c.instructions_unused), t(lacking ? (partial ? "setup.company.partial" : "setup.company.need") : "setup.company.ok") + (lacking || !inCopy ? "" : unusedTip(c.instructions_unused, "setup.fact.skipped.instr", "knowledgebase.instructions.md")), "instructions"), lacking ? "need" : "ok");
      const skills = c.skills || {n: 0, off: []};
      const noSkills = st.parts ? !has("skills") : !inCopy || !skills.n;
      const off = inCopy ? skills.off || [] : [];
      const skillKind = noSkills || off.length ? "need" : "ok";
      add(rows, fact(t("setup.skills"), skillKind, noSkills ? t("setup.fact.notfound") : st.parts ? t("setup.fact.found") : h("span", null, String(skills.n), off.length ? part(" \u00b7 " + t("setup.fact.skills.off", {n: off.length, names: off.slice(0, 3).join(", ") + (off.length > 3 ? ", \u2026" : "")}), "off") : null),
        off.length ? off.join("\n") : t(noSkills ? "setup.fact.skills.none.tip" : "setup.fact.skills.ok.tip"), "skills"), skillKind);
      const own = st.probePrefix || (c.prefix && c.prefix.kb) || "";  // the knowledge base names it: a fact, no box. It names none: the box (the override keeps working)
      const conflict = !st.probePrefix && c.prefix && c.prefix.conflict;
      const showBox = !own && (st.kb.here || st.mode !== "none");  // no knowledge base at all: a yellow "not found" (1.7.38)
      prefixRow.hidden = !showBox;
      if (own) add(rows, fact(t("setup.prefix"), conflict ? "need" : "ok", own, conflict || t("setup.fact.prefix.tip"), "skills"), conflict ? "need" : "ok");
      else if (showBox) rows.push(prefixRow);
      else if (c.prefix && c.prefix.effective) add(rows, fact(t("setup.prefix"), "ok", c.prefix.effective, t("setup.fact.prefix.tip"), "skills"), "ok");  // no knowledge base, but this copy names one (user.override.json): say it, as the Enter screen does
      else add(rows, fact(t("setup.prefix"), "need", t("setup.fact.notfound"), t("setup.fact.prefix.none.tip"), "skills"), "need");
      const standard = missing("standards");
      const said = !st.parts && st.guide.declared.includes("standards");
      add(rows, fact(t("setup.standards"), standard ? "need" : said ? "none" : "ok", standard ? t("setup.fact.notfound") : said ? t("setup.fact.nonesaid") : counted(c.standards_n, c.standards_unused), t(standard ? "setup.standards.need" : said ? "setup.standards.none" : "setup.standards.ok") + (standard || said || !inCopy ? "" : unusedTip(c.standards_unused, "setup.fact.skipped.stds", "code-standards.md")), "standards"), standard ? "need" : "ok");
      const tools = st.tools || {};
      const packs = [...(c.packs || []).map((name) => ({name, from: "harness"})), ...(c.own_packs || []).map((name) => ({name, from: "company"}))];
      const ready = new Map(((tools.packs || {}).names || []).map((item) => [item.name, item.ok]));
      const packKinds = packs.map((item) => !ready.has(item.name) ? "none" : ready.get(item.name) ? "ok" : "need");
      const packKind = !packs.length || packKinds.includes("need") ? "need" : "ok";
      add(rows, fact(t("setup.toolpacks"), packKind, packs.length ? [...names(packs.map((item, index) => ({name: item.name, kind: packKinds[index], tip: ready.has(item.name) ? t(ready.get(item.name) ? "setup.fact.pack.ready" : "setup.fact.pack.not") : ""}))), packs.some((item) => item.from === "harness") ? part(packs.every((item) => item.from === "harness") ? t("setup.fact.packs.harness") : t("setup.fact.packs.mixed", {harness: packs.filter((item) => item.from === "harness").length, own: packs.filter((item) => item.from !== "harness").length}), "soft") : null].filter(Boolean)
        : h("span", null, part(t("setup.fact.packs.none"), "off"), part(" \u00b7 " + t("setup.fact.packs.picks"), "soft")), packs.map((item) => item.name).join(", ") || t("setup.fact.packs.tip"), "", ["packs", ""], ["packs", ""]), packKind);
      const conns = tools.conns ? tools.conns.rows : (c.connections || []).map((name) => ({alias: name, saved: false, account: ""}));
      const offConns = tools.conns ? tools.conns.off || [] : [];  // their tool pack is off: not counted
      const todo = conns.filter((row) => !row.saved).length, failed = conns.filter((row) => row.failed).length;  // failed: kept, and the last check or Test did not pass
      const connKind = !conns.length || todo || failed ? "need" : "ok";
      add(rows, fact(t("connections.title"), connKind, conns.length ? [...names(conns.map((row) => ({name: row.alias, kind: row.failed ? "need" : row.saved ? "ok" : "ring", tip: row.failed ? t("setup.fact.signin.failed", {account: row.account || "-"}) : row.saved ? t("setup.fact.signin.saved", {account: row.account || "-"}) : t("setup.fact.signin.not")}))),
        part([todo ? t("setup.fact.conns.todo", {n: todo}) : failed ? "" : t("setup.fact.conns.all"), failed ? t("setup.fact.conns.failed", {n: failed}) : ""].filter(Boolean).join(" \u00b7 "), todo || failed ? "off" : "soft")]
        : part(t("setup.fact.conns.none"), "off"), [conns.map((row) => row.alias).join(", ") || t("setup.fact.conns.tip"), offConns.length ? t(offConns.length === 1 ? "setup.fact.conns.off.one" : "setup.fact.conns.off", {n: offConns.length, names: offConns.slice(0, 4).join(", ") + (offConns.length > 4 ? " +" + (offConns.length - 4) : "")}) : ""].filter(Boolean).join("\n"), "", ["connections", ""], ["connections", ""]), connKind);
      factsBox.replaceChildren(...rows);
      // Local
      const pc = tools.pc;
      if (pc) {
        const lackingProg = pc.programs.filter((row) => !row.found).map((row) => row.program);
        const progKind = lackingProg.length ? "need" : "ok";
        add(mine, fact(t("machine.prog.title"), progKind, [...names(pc.programs.map((row) => ({name: row.found ? row.program : row.program + " \u00b7 " + t("machine.prog.missing"), kind: row.found ? "ok" : "need", tip: row.found ? row.path : t("machine.prog.missing.tip", {program: row.program})}))), pc.programs.length === 1 ? part(t("setup.fact.programs.hint"), "soft") : null].filter(Boolean),
          lackingProg.length ? t("machine.prog.lacking", {programs: lackingProg.join(", ")}) : t("machine.prog.tip"), "", ["local", "programs"]), progKind);
        const netKind = pc.certs ? "ok" : pc.company_proxy ? "need" : "ring";
        add(mine, fact(t("machine.net.title"), netKind, pc.certs ? [t(pc.certs === 1 ? "setup.fact.ca.n.one" : "setup.fact.ca.n", {n: pc.certs}), pc.proxy ? t("setup.fact.net.proxy", {proxy: pc.proxy}) : ""].filter(Boolean).join(" \u00b7 ") : h("span", null, part(t("machine.ca.none.long"), pc.company_proxy ? "off" : null), part(" \u00b7 " + t(pc.company_proxy ? "setup.fact.ca.need.company" : "setup.fact.ca.need.maybe"), "soft")),
          pc.certs ? t("setup.fact.ca.tip", {host: pc.host || "-"}) : t("machine.ca.none.tip"), "", ["local", "network"]), netKind);
        mine.push(fact("MCP", pc.mcp ? "ok" : "ring", t(pc.mcp ? "setup.fact.mcp.on" : "setup.fact.mcp.off"), t("machine.mcp.tip"), "", ["local", "mcp"]));
      }
      computerBox.replaceChildren(...mine);
      lookNote.textContent = st.kb.here && look ? t("setup.look.n", {n: look}) : "";
      kbDotPaint();
    }
    const paintStates = paintFacts;
    function loadTools() { if (typeof TOOLS === "undefined") return Promise.resolve(); return TOOLS.facts().then((found) => { st.tools = found; paintFacts(); }); }
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
          const size = found.ok ? lines.findIndex((line) => !/[\u2500-\u259f]/.test(line)) : 0;  // the drawn letters come first; they are left out (1.7.38): they never drew well in a box, and the proof is the words under them
          parts.push(h("pre", {class: "su-out" + (found.ok ? "" : " bad")}, lines.slice(Math.max(size, 0)).join("\n").replace(/^\n+/, "")));
        }
        if (found.python) parts.push(h("p", {class: "su-warn"}, found.python));
        testOut.replaceChildren(...parts);
      }, (error) => { button.disabled = false; testOut.replaceChildren(h("p", {class: "su-note bad"}, error.message || String(error))); });
    }

    // This browser is not paired (or the board did not answer): the first card says so, instead of staying an empty box (1.7.38). The poll goes on: pairing in another tab shows the real card at once.
    function paintUnpaired(error) {
      st.shortKey = "";
      const unpaired = Boolean(error && error.data && error.data.unpaired);
      shortBox.replaceChildren(h("div", {class: "su-head"}, h("span", {class: "su-mark"}, "1"), h("h2", null, t("setup.short.title"))), h("p", {class: "su-note bad"}, t(unpaired ? "setup.short.unpaired" : "setup.short.nolink")), h("p", {class: "su-note"}, (error && error.message) || ""));
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
        parts.push(h("p", {class: "su-note"}, t("setup.short.where")));  // the path above may be another copy's: it runs the copy of the folder you are in (1.7.38)
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
      if (!st.scrolled) {  // the Enter screen sent the person to the section that is missing (1.7.36): ?sec=you|company|computer
        st.scrolled = true;
        const want = new URLSearchParams(location.search).get("sec"), target = want && app.querySelector('[data-sec="' + want.replace(/[^a-z]/g, "") + '"]');
        if (target) setTimeout(() => target.scrollIntoView({block: "start"}), 0);
      }
      st.latest = found;
      paintFacts();
      changed.hidden = !found.stamp || found.stamp === st.stamp || st.busy || st.saved;
      broken.textContent = found.problem;  // a poll tells it too: the file can break while the form is open
      broken.hidden = !found.problem;
      st.ready = Boolean(found.short.found);
      gate();
    }

    function load() {
      clearTimeout(st.timer);
      if (!app.isConnected) return Promise.resolve();
      return ask("state").then(paint, (error) => { app.classList.remove("su-loading"); if (!st.shortKey) paintUnpaired(error); said.replaceChildren(...SERVE.reasons(error.message || error)); }).then(() => { if (!document.hidden) st.timer = setTimeout(load, st.ready ? SLOW : POLL); else st.timer = 0; });
    }

    // While the work runs: a spinner, a line that says do not close, and the steps done. At the end: the result, or the reason it stopped (1.7.19).
    function paintLines(found) {
      const lines = found.lines.map((line) => h("p", {class: line.ok ? "su-note good" : "su-note bad"}, (line.ok ? "\u2713 " : "\u2717 ") + t("setup.line." + line.key) + ": " + line.detail));
      const failed = found.lines.find((line) => !line.ok);
      const head = found.running ? [h("p", {class: "su-busy su-run-head", role: "status"}, t("setup.run.working")), h("p", {class: "su-note"}, t("setup.run.steps", {done: found.lines.length, total: found.total || found.lines.length}))]
        : failed ? [h("p", {class: "bad su-run-head", role: "status"}, t("setup.run.failed", {step: t("setup.line." + failed.key)})), h("p", {class: "su-note"}, t("setup.run.retry"))]
        : found.done ? [h("p", {class: "su-note good su-run-head", role: "status"}, "\u2713 " + t("setup.run.done"))] : [];
      said.replaceChildren(h("div", {class: "su-run"}, ...head, ...lines));
      if (found.running || failed) said.scrollIntoView({block: "nearest", behavior: "smooth"});  // the form is long: the progress stays in sight
    }
    function follow() {
      ask("job").then((found) => {
        paintLines(found);
        if (found.lines.length !== st.seenLines) { st.seenLines = found.lines.length; loadTools(); }  // a step ended: the packs and connections it brought show now, not at the end (1.7.38)
        if (found.running) { setTimeout(follow, 700); return; }
        st.busy = false;
        go.textContent = t(found.done ? (finished ? "setup.save" : "setup.finish") : "setup.run.again");  // after a stop, the same button runs it again
        st.stamp = found.stamp;  // what was written here is not a change from elsewhere
        st.saved = found.done;
        gate();
        if (!found.done) return;
        loadTools();
        st.parts = null;  // what the folder had is now copied: the states below follow the copy itself, read again (1.7.22; "Not found yet" stayed after the copy)
        loadGuide();
        leave();
      }, (error) => { st.busy = false; gate(); said.replaceChildren(...SERVE.reasons(error.message || error)); });
    }
    go.addEventListener("click", () => {
      st.busy = st.touched = true;
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
      // What would move, what moved, what failed and what was left alone (1.6.109): a count per group, and the lists folded in a box that scrolls. Before, every failed file was a red line of the window.
      // A number or a group is a button: it opens its list and shows the part (1.6.109).
      const reveal = (list, part) => {
        if (!list) return;
        list.open = true;
        (part || list).scrollIntoView({block: "nearest", behavior: "smooth"});
        if (part) { part.classList.remove("su-flash"); void part.offsetWidth; part.classList.add("su-flash"); }
      };
      const groupList = (key, list) => {
        const entries = Object.entries(list || {});
        const total = entries.reduce((sum, [, names]) => sum + names.length, 0);
        return total ? h("details", {class: "su-older-list"}, h("summary", null, t(key, {n: total})),
          h("div", {class: "su-older-box"}, ...entries.map(([group, names]) => h("div", {class: "su-older-row", "data-group": group}, h("b", {class: "su-older-group"}, group + " \u00b7 " + names.length), ...names.map((name) => h("code", null, name)))))) : null;
      };
      const groups = (list, box) => h("div", {class: "chips su-older-groups"}, ...Object.entries(list || {}).map(([group, names]) => {
        const chip = h("button", {type: "button", class: "chip"}, group + " \u00b7 " + names.length);
        chip.addEventListener("click", () => reveal(box, box && [...box.querySelectorAll("[data-group]")].find((node) => node.dataset.group === group)));
        return chip;
      }));
      const folded = (key, items, open, bad) => (items || []).length ? h("details", {class: "su-older-list" + (bad ? " bad" : ""), open: open ? "" : null}, h("summary", null, t(key, {n: items.length})),
        h("div", {class: "su-older-box"}, ...items.map((item) => h("div", {class: "su-older-row"}, h("code", null, item.what), h("span", {class: "su-note"}, item.why),
          ...(item.files || []).map((file) => h("div", {class: "su-older-file"}, h("code", null, file.path), h("span", {class: "su-note"}, file.why))),
          item.more ? h("span", {class: "su-note"}, t("setup.older.more", {n: item.more})) : null)))) : null;
      function result(found) {
        const copied = Object.values(found.copied || {}).reduce((sum, names) => sum + names.length, 0);
        const failed = found.failed || [], skipped = found.skipped || [];
        const carried = groupList("setup.older.copied.n", found.copied);
        const failedList = folded("setup.older.failed.n", failed, true, true);
        const skippedList = folded("setup.older.skipped.n", skipped, false, false);
        const stat = (key, n, kind, list) => {
          const node = h("button", {type: "button", class: "su-older-stat" + (kind ? " " + kind : ""), disabled: list ? null : ""}, h("b", null, String(n)), h("span", null, t(key)));
          node.addEventListener("click", () => reveal(list));
          return node;
        };
        const close = h("button", {type: "button", class: "act hot"}, t("board.new.close"));
        const win = SERVE.dialog([h("h2", null, t("setup.older.result")), h("p", {class: "sub su-older-from"}, t("setup.older.from", {from: found.from})),
          h("div", {class: "su-older-stats"}, stat("setup.older.count.copied", copied, copied ? "good" : "", carried), stat("setup.older.count.failed", failed.length, failed.length ? "bad" : "", failedList), stat("setup.older.count.skipped", skipped.length, "", skippedList)),
          groups(found.copied, carried), failedList, carried, skippedList, h("div", {class: "row"}, close)]);
        win.box.classList.add("su-older-win");
        close.addEventListener("click", () => { win.close(); (finished ? load : leave)(); });  // in the window the note says what changed; what was typed stays
      }
      // An old copy of many files takes a while, longer on a computer that checks each file: the buttons wait and a line counts the time (1.6.109). Before, a click showed nothing.
      const waiting = (key) => {
        const began = Date.now();
        const line = h("p", {class: "su-note su-busy", role: "status"});
        const tick = () => { line.textContent = t(key, {time: clock((Date.now() - began) / 1000)}); };
        tick();
        const timer = setInterval(tick, 1000);
        out.replaceChildren(line);
        path.disabled = look.disabled = apply.disabled = true;
        return () => { clearInterval(timer); path.disabled = look.disabled = apply.disabled = false; };
      };
      look.addEventListener("click", () => {
        const done = waiting("setup.older.looking");
        ask("older", {path: path.value}).then((found) => {
          done();
          const moves = groupList("setup.older.moves.n", found.would_copy);
          out.replaceChildren(h("p", {class: "su-note su-older-from"}, t("setup.older.from", {from: found.from})), groups(found.would_copy, moves), moves, folded("setup.older.skipped.n", found.skipped, false, false));
          apply.hidden = false;
        }, (error) => { done(); out.textContent = error.message || String(error); });
      });
      apply.addEventListener("click", () => {
        const done = waiting("setup.older.carrying");
        ask("older", {path: path.value, apply: true}).then((found) => {
          done();
          view.close();
          result(found);
        }, (error) => { done(); out.textContent = error.message || String(error); });
      });
    }
    name.addEventListener("input", gate);
    kbPath.addEventListener("input", () => { st.full = false; st.update = null; paintReplace(); paintChanges(); gate(); clearTimeout(st.probe); st.probe = setTimeout(checkKb, 400); });
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
    loadTools();
    const prefixRow = row([t("setup.prefix"), question("skills")], prefix, h("p", {class: "su-note"}, t("setup.prefix.hint")));  // only when the knowledge base names none (1.7.36)
    // The knowledge base is the first fact of card 3 and shaped like the others: a dot, its name, and what it says (1.7.38); the chips choose where a new one comes from.
    const kbRow = h("div", {class: "su-fact su-kbrow"}, kbDot, h("b", {class: "su-fk"}, t("setup.kb"), kbStar, " ", question("kb")), h("div", {class: "su-fv su-kbv"}, modeBox, h("div", {class: "su-line"}, kbPath, kbPick), kbInfo, kbNote, kbChanges, kbParts, kbReplace));
    const repoRow = h("div", {class: "su-fact su-repos"}, repoDot, h("b", {class: "su-fk"}, t("setup.repos"), " ", question("repos")), h("div", {class: "su-fv su-repov"}, h("div", {class: "su-line"}, repos, repoAdd, browse(repos, "folder", () => { repoAdd.disabled = false; addRepo(); })), repoNote, repoPick, repoList, h("p", {class: "su-note"}, t("setup.repos.hint"))));
    const card = (key, num, head, ...nodes) => h("section", {class: "su-card", "data-sec": key}, h("div", {class: "su-head"}, h("span", {class: "su-mark"}, num), h("h2", null, t("setup.sec." + key), " ", h("span", {class: "sv-info", tabindex: "0", title: t("setup.sec." + key + ".tip")}, "\u24d8")), head), ...nodes);  // four cards of one rank (1.7.38)
    const more = h("details", {class: "su-more"}, h("summary", {class: "su-note"}, t("setup.more")), row([t("setup.install"), question("python")], install, h("p", {class: "su-note"}, t("setup.install.example"))), row([t("setup.refused"), question("repos")], h("div", {class: "su-line"}, refusedBox, refusedAdd), refusedNote, refusedList, h("p", {class: "su-note"}, t("setup.refused.hint"))));
    app.classList.add("su-loading");  // an empty form that jumps when its data comes is worse than a moment of nothing
    const finishTip = h("span", {class: "sv-info", tabindex: "0", title: t("setup.finish.note")}, "\u24d8");
    app.replaceChildren(h("div", {class: "su"}, h("h1", null, t(first ? "setup.title" : "setup.guide")), h("p", {class: "su-lead"}, t(finished ? "setup.lead.again" : "setup.lead"), " ", olderLink), shortBox, changed, broken,
      card("you", "2", null, row([t("setup.name"), star()], name), row([t("setup.language"), star()], h("span", {class: "su-line"}, h("span", {class: "chips su-modes"}, chips), langNote))),
      card("company", "3", h("span", {class: "su-tag"}, t("setup.optional")), kbRow, factsBox, repoRow),
      card("computer", "4", openTab("local"), computerBox, more),
      h("div", {class: "su-end"}, go, finishTip, goNote, lookNote), said));
    gate();
    load();
    // Finish writes the language first and goes on for a while. A reload in the middle (the page asks to stay, but a reload by hand or a second tab happens) would lose the work it shows: the page that finds it running goes on showing it (1.7.38).
    SERVE.stay(() => st.touched && app.isConnected);
    ask("job").then((found) => { if (found.running && !st.busy) { st.busy = st.touched = true; gate(); follow(); } }, () => {});
    return {busy: () => st.busy, dirty: () => Boolean(st.form) && !st.saved && JSON.stringify(values()) !== st.opened};
  }
  if (DATA.getReady) {
    document.body.classList.add("su-page");
    mount(document.getElementById("app"));
  }
  return {mount};
})();
