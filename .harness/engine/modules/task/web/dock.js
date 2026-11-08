// The buttons at the bottom right (1.6.61): the question mark and the one-click chats. The gear is shell.js's. The book opens the knowledge base window, the sliders the setup, the house the Enter screen.
// DOCK.start asks with the whole message in view and the model it goes with (CHAT.modelPick, 1.6.101), sends, and brings VS Code forward. Needs common.js (h, t), serve.js (SERVE), chat.js (CHAT).
const DOCK = (function () {
  const BOOK = "https://smarshu.com/book/";
  const ENTERED = "harness.entered";  // enter.js: the Enter screen was seen in this tab
  const ask = (step, body) => SERVE.post("/api/skill", {step, ...body}).then((data) => data.result);

  function done() {
    const close = h("button", {type: "button", class: "act hot"}, t("board.new.close"));
    const view = SERVE.dialog([h("h2", null, t("dock.sent")), h("p", null, t("dock.sent.where")), h("div", {class: "row"}, close)], true);
    close.addEventListener("click", view.close);
  }

  // `back`: what to open again when the person steps back; the place they came from.
  const backButton = (view, back) => {
    const button = h("button", {type: "button", class: "act"}, t("dock.back"));
    button.addEventListener("click", () => { view.close(); back(); });
    return button;
  };

  function start(skill, words, back, task) {  // `task`: the chat goes on with this task, and no new one is made
    const lang = document.documentElement.lang === "zh" ? "zh" : "en";
    const body = {skill, words: words || "", lang, ...(task ? {task} : {})};
    const preview = h("pre", {class: "send-preview"}, "...");
    const said = h("div", {class: "bad"});
    const runs = h("p", {class: "sub", hidden: ""});
    const go = h("button", {type: "button", class: "act hot", disabled: "disabled"}, t("dock.send"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const copy = h("button", {type: "button", class: "act", "data-label": t("dock.copy"), hidden: ""}, t("dock.copy"));  // with VS Code away, the words can still go into a chat by hand
    const again = h("button", {type: "button", class: "act", hidden: ""}, t("dock.again"));
    const pick = typeof CHAT !== "undefined" ? CHAT.modelPick(task || "") : null;  // 1.6.101: the person picks the model; a task's chat has no Copilot Fusion by default
    const view = SERVE.dialog([h("h2", null, t(task ? "dock.title.task" : "dock.title")), h("p", {class: "sub"}, task ? t("dock.hint.task", {task}) : t("dock.hint")), preview, pick ? pick.node : runs, said, h("div", {class: "row"}, go, again, copy, no)]);
    no.addEventListener("click", () => { view.close(); if (back) back(); });  // Cancel goes back to where the person came from
    copy.addEventListener("click", () => copyCommand(copy, preview.textContent));
    const check = () => ask("preview", body).then((found) => {
      preview.textContent = found.text;
      runs.hidden = !found.model;
      runs.textContent = found.model ? t("dock.model", {model: found.model}) : "";
      said.replaceChildren(...(found.blocked ? SERVE.reasons(found.blocked) : []));
      go.disabled = Boolean(found.blocked);
      copy.hidden = again.hidden = !found.blocked;
    }, (error) => { preview.textContent = ""; said.replaceChildren(...SERVE.reasons(error.message || error)); });
    again.addEventListener("click", check);
    check();
    go.addEventListener("click", () => {
      go.disabled = true;
      (pick ? pick.apply() : Promise.resolve({})).then((chosen) => ask("act", {...body, ...chosen})).then(() => { view.close(); done(); }, (error) => { go.disabled = false; said.replaceChildren(...SERVE.reasons(error.message || error)); });
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
      const go = item.href ? h("a", {class: "act", href: item.href, target: "_blank", rel: "noopener noreferrer"}, t("dock.open")) : item.opens === "reply" ? h("span", {class: "tag"}, t("dock.intask")) : !item.opens ? null : h("button", {type: "button", class: "act"}, t("dock.start"));  // no `board-opens`: a tool pack's skill that is only listed (1.7.34)
      if (go && go.tagName === "BUTTON") go.addEventListener("click", () => start(item, words ? words.value : ""));
      return h("div", {class: "dock-skill"}, h("div", {class: "dock-about"}, h("b", {title: item.name}, item.label), item.costly ? h("span", {class: "tag hot", title: t("dock.costly.hint")}, t("dock.costly")) : null, item.gone ? h("span", {class: "tag", title: t("dock.gone.hint")}, t("dock.gone")) : null, h("p", {class: "sub"}, item.about), item.opens === "reply" ? h("p", {class: "sub"}, t("dock.intask.hint")) : null, words), go);
    };
    function paint() {
      const wanted = search.value.toLowerCase().split(/\s+/).filter(Boolean);
      const hits = (item) => { const text = [item.label, item.name, item.about, item.hint].join(" ").toLowerCase(); return wanted.every((word) => text.includes(word)); };
      const shown = found.filter((item) => (!only || item.group === only || item.place.includes(only) || item.place.includes("all")) && hits(item));
      const groups = [["company", (item) => item.own && item.naming !== "pack"], ["pack", (item) => item.own && item.naming === "pack"], ...["harness", "kb", "task"].map((key) => [key, (item) => !item.own && item.group === key])];  // by the naming rule (core/skillgroups.py)
      list.replaceChildren(...groups.flatMap(([key, test]) => {
        const items = shown.filter(test);
        if (key === "pack") items.sort((one, two) => one.pack.localeCompare(two.pack));  // a small heading for each pack
        const out = items.length && !only ? [h("h3", null, t("dock.group." + key))] : [];  // a window of one part has its name as its title
        items.forEach((item, index) => {
          if (!["company", "pack"].includes(key) && item.step && (!index || items[index - 1].step !== item.step)) out.push(h("h4", null, t("dock.step." + item.step)));
          if (key === "pack" && item.pack && (!index || items[index - 1].pack !== item.pack)) out.push(h("h4", {class: "dock-pack"}, item.pack));
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
  const STALE_EVERY = 600000;  // ms; the view is kept as long (kbview.py)
  const UNPAIRED_EVERY = 30000;  // a page opened before its browser is paired asks again soon
  let staleCount = 0;
  function badge(n) {
    const mark = document.querySelector(".dock-count");
    if (!mark) return;
    staleCount = n || 0;
    mark.hidden = !n;
    mark.textContent = n > 99 ? "99+" : String(n);
    mark.title = staleWords();  // what the number counts, on hover of the number and, below the other words, of the button (retest N12)
    paintBook();
  }
  const staleWords = () => (staleCount ? t(staleCount === 1 ? "dock.kb.badge.one" : "dock.kb.badge.n", {n: staleCount}) : "");
  function watchStale() {
    SERVE.post("/api/kb", {op: "detail", fresh: false}).then((data) => {
      if (data.result.result) badge(data.result.result.stale);
      setTimeout(watchStale, data.result.running ? 5000 : STALE_EVERY);
    }, () => setTimeout(watchStale, UNPAIRED_EVERY));
  }
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
      SERVE.post("/api/setup", {step: "pick", kind}).then((data) => { const found = data.result; system.disabled = false; note.textContent = ""; if (found.path) pickIt(found.path); }, (error) => { system.disabled = false; note.textContent = error.message || String(error); });
    });
    open(start || "");
  }
  // The company content against its copies in `.github/`: the book button turns yellow and moves, and the window says what a sync would change (core/company.py).
  const COMPANY_EVERY = 120000;  // ms
  const COMPANY_LINES = 6;  // lines of the tip
  let drift = null, hasCompany = false;
  const CHANGES = {add: "dock.company.add", change: "dock.company.change", remove: "dock.company.remove"};
  const CHAT_WORDS = 1800;  // under `skillsend.MAX_WORDS`, the limit of a one-click message
  const stuckWord = (item) => plainWords(item.skill + ": " + item.why);
  const changeWord = (row) => t(CHANGES[row.change]) + " " + row.path;
  function showDrift(found) {
    drift = found && found.found && !found.in_sync ? found : null;
    hasCompany = Boolean(found && found.found);
    const book = document.querySelector(".dock-book");
    if (!book) return;
    book.classList.toggle("dock-warn", Boolean(drift));
    paintBook();
  }
  // The hover of the book: the company's copies that differ (when they do), then what the number on it counts.
  function paintBook() {
    const book = document.querySelector(".dock-book");
    if (!book) return;
    const base = !drift ? t("dock.kb") : [drift.total ? t(drift.total === 1 ? "dock.company.tip.one" : "dock.company.tip", {count: drift.total}) : t("dock.company.title.stuck"), ...drift.changes.slice(0, COMPANY_LINES).map(changeWord), ...drift.refused.slice(0, COMPANY_LINES).map(stuckWord), plainWords(drift.problem || "")].filter(Boolean).join("\n");
    book.title = [base, staleWords()].filter(Boolean).join("\n");
  }
  function watchCompany() {
    SERVE.post("/api/company", {}).then((data) => { showDrift(data.result); setTimeout(watchCompany, COMPANY_EVERY); }, () => setTimeout(watchCompany, UNPAIRED_EVERY));
  }
  // The Sync button of the Enter screen and of the block at the top of the board (1.7.38): `sync`, or `prefix` (the company's word goes in the person's file first). The book follows the answer.
  function syncCompany(op) {
    return SERVE.post("/api/company", {op: op === "prefix" ? "prefix" : "sync"}).then((data) => { showDrift(data.result); return data.result; });
  }
  function driftCard(node) {
    const said = h("p", {class: "bad"});
    const go = h("button", {type: "button", class: "act hot"}, t("dock.company.go"));
    const fix = h("button", {type: "button", class: "act hot"}, t("dock.company.fix", {word: drift ? drift.fix || "" : ""}));
    fix.addEventListener("click", () => { fix.disabled = true; SERVE.post("/api/company", {op: "prefix"}).then((data) => { showDrift(data.result); driftCard(node); }, (error) => { fix.disabled = false; said.textContent = error.message; }); });
    go.addEventListener("click", () => {
      go.disabled = true;
      SERVE.post("/api/company", {op: "sync"}).then((data) => { showDrift(data.result); driftCard(node); }, (error) => { go.disabled = false; said.textContent = error.message; });
    });
    // What a sync cannot do needs a change in the knowledge base: a person or an agent writes it, so the way on is a chat.
    const stuck = drift ? [...drift.refused.map(stuckWord), ...(drift.problem && !drift.fix ? [plainWords(drift.problem)] : [])] : [];
    const chat = h("button", {type: "button", class: "act" + (drift && (drift.total || drift.fix) ? "" : " hot")}, t("dock.company.chat"));
    chat.addEventListener("click", () => start("harness-my-task", t("dock.company.chat.words", {items: stuck.join(" ")}).slice(0, CHAT_WORDS)));
    node.hidden = !drift;
    node.replaceChildren(...(!drift ? [] : [h("h3", null, t(drift.total || drift.fix ? "dock.company.title" : "dock.company.title.stuck")), drift.fix ? "" : h("p", {class: "sub"}, t(drift.total ? "dock.company.hint" : "dock.company.hint.stuck")),
      drift.total || drift.refused.length ? h("ul", null, drift.changes.map((row) => h("li", null, h("code", null, changeWord(row)))), drift.total > drift.changes.length ? h("li", null, t("dock.company.more", {count: drift.total - drift.changes.length})) : null,
        drift.refused.map((item) => h("li", {class: "bad"}, stuckWord(item)))) : "",
      drift.problem ? h("p", {class: "bad"}, plainWords(drift.problem)) : "", h("div", {class: "row kb-sync-go"}, drift.fix ? fix : "", drift.total ? go : "", stuck.length ? chat : ""), said]));
  }
  function kbWindow(tab) {
    const stage = h("div", {class: "dock-list kb-body"});
    const no = h("button", {type: "button", class: "act"}, t("board.new.close"));
    const age = h("span", {class: "sub kb-age"});
    const again = h("button", {type: "button", class: "act"}, t("dock.kb.refresh"));
    const tabs = ["overview", "atlas", "company", "domains", "lookup", "health"].map((key) => { const tab = h("button", {type: "button", class: "chip", "data-key": key}, t(key === "domains" ? "dock.kb.domains.tab" : "dock.kb." + key)); tab.addEventListener("click", () => show(key)); return tab; });
    const rebuild = h("span", {class: "kb-rebuild", hidden: ""});
    const alarm = h("p", {class: "bad kb-alarm", hidden: ""});  // outside the stage: a drawn view stays as it is
    const synced = h("section", {class: "kb-sync", hidden: ""});
    driftCard(synced);
    // The copies are looked at again when the window opens and with Refresh (1.7.38): a person who just changed the knowledge base should not wait for the 2 minutes of the book
    const recheck = () => SERVE.post("/api/company", {}).then((data) => { showDrift(data.result); driftCard(synced); }, () => {});
    recheck();
    const packed = h("p", {class: "su-note kb-packed", hidden: ""});
    const pack = h("button", {type: "button", class: "act", title: t("dock.pack.hint"), hidden: hasCompany ? null : ""}, t("dock.pack"));
    // The order of Pack for colleagues (1.7.38): check first (nothing uncommitted, the skills, the form of the knowledge base), and only then ask where to put the file.
    function packNow(out) {
      pack.disabled = true;
      packed.hidden = false;
      packed.classList.remove("bad");
      packed.textContent = t("dock.pack.working");
      SERVE.post("/api/company", {op: "pack", out}).then((data) => { packed.textContent = t("dock.pack.done", {file: data.result.package, files: data.result.files}); }, (error) => { packed.classList.add("bad"); paintPackError(error); }).then(() => { pack.disabled = false; });
    }
    function packStart() {
      pack.disabled = true;
      packed.hidden = false;
      packed.classList.remove("bad");
      packed.textContent = t("dock.pack.checking");
      SERVE.post("/api/company", {op: "packcheck"}).then(() => { packed.hidden = true; packed.textContent = ""; chooseOnPage("folder", "", packNow); }, (error) => { packed.classList.add("bad"); paintPackError(error); }).then(() => { pack.disabled = false; });
    }
    function paintPackError(error) {  // changes git does not hold: they are listed here, and one button commits them (no command to read)
      const skills = error.data && error.data.skills;
      if (skills) {  // what a skill lacks is written in the skill: that is a change in the knowledge base, so an agent makes it
        const items = skills.map(plainWords).map((item) => (/[.!?\u3002]$/.test(item.trim()) ? item.trim() : item.trim() + "."));  // the package was not made; which skill and why; the rest is fine (1.7.38, as `harness company pack` says it)
        const fix = h("button", {type: "button", class: "act kb-mini"}, chatGlyph(), t("dock.company.chat"));
        fix.addEventListener("click", () => start("harness-my-task", t("dock.company.chat.words", {items: items.join(" ")}).slice(0, CHAT_WORDS)));
        packed.replaceChildren(t("dock.pack.skills"), h("ul", null, items.map((item) => h("li", null, item))), h("p", {class: "su-note"}, t("dock.pack.skills.rest")), fix);
        return;
      }
      const folder = error.data && error.data.dirty;
      if (!folder) { packed.textContent = plainWords(error.message); return; }
      const files = (error.data.files || []).map((line) => String(line).replace(/^\s*\S+\s+/, ""));  // `git status --porcelain`: the mark, then the path
      const commit = h("button", {type: "button", class: "act kb-mini"}, t("dock.pack.commit"));
      commit.addEventListener("click", () => {
        commit.disabled = true;
        SERVE.post("/api/company", {op: "commit"}).then(() => packStart(), (problem) => { commit.disabled = false; packed.classList.add("bad"); packed.replaceChildren(plainWords(problem.message)); });
      });
      packed.replaceChildren(...[t("dock.pack.dirty"), files.length ? h("ul", {class: "kb-dirty"}, files.map((name) => h("li", null, h("code", null, name))), error.data.more ? h("li", null, t("dock.pack.more", {n: error.data.more})) : null) : null, commit].filter(Boolean));  // replaceChildren writes a null as the word "null"
    }
    pack.addEventListener("click", packStart);
    const view = SERVE.dialog([h("h2", null, t("dock.kb")), h("div", {class: "kb-bar"}, h("div", {class: "chips dock-tabs"}, tabs), age, rebuild, again), alarm, synced, stage, packed, h("div", {class: "row"}, pack, no)]);
    view.box.classList.add("dock-window", "kb-window");
    view.holds = () => false;  // it only reads: nothing here can be lost
    let timer = 0, current = "", seenView = "", word = "", searched = "", ticket = 0, extra = null, painted = null, detailTimer = 0;  // word, searched: what was typed in Look up, kept while the tab changes; ticket: the newest search
    const asked = new Set();
    no.addEventListener("click", view.close);
    const post = (body) => SERVE.post("/api/kb", body).then((data) => data.result);
    const leave = (then) => () => { view.close(); then(); };
    const ago = (seconds) => (seconds < 60 ? t("dock.kb.age.now") : t("dock.kb.age", {n: Math.round(seconds / 60)}));
    // No knowledge base in this copy (1.7.38): every tab says so once, and leads to the setup where one is imported. The steps of a build, the map and the company tab have nothing to show yet.
    function emptyState() {
      const go = h("button", {type: "button", class: "act hot"}, t("dock.kb.empty.go"));
      go.addEventListener("click", () => { if (typeof READY !== "undefined") READY.go({to: "setup", sec: "company"}); else location.assign("/setup?sec=company"); });
      stage.classList.remove("ka-stage", "co-stage");
      view.box.classList.remove("ka-open");
      stage.replaceChildren(h("div", {class: "kb-empty"}, h("p", null, t("dock.kb.empty")), go));
      alarm.hidden = true;
      rebuild.hidden = true;
      age.textContent = "";
    }
    function load(op, paint, fresh, wait) {
      const key = current;
      post({op, fresh}).then((found) => {
        if (!view.box.isConnected || key !== current) return;  // a late answer belongs to a tab that is gone
        if (found.has_kb === false) { emptyState(); return; }
        age.textContent = found.running ? t("dock.kb.updating") : found.age === null ? "" : ago(found.age);
        const seen = JSON.stringify(found.result);
        if (found.result && seen !== seenView) { seenView = seen; painted = () => paint(found.result); painted(); }
        alarm.replaceChildren(h("span", null, found.error || ""), ...(found.nomap ? [found.canmap ? mapButton(true) : nextButton("map")] : []));
        if (op === "atlas") { rebuild.replaceChildren(mapButton(false)); rebuild.hidden = Boolean(found.error); }
        alarm.hidden = !found.error || found.running;
        if (!found.result) stage.replaceChildren(...(found.running || !found.error ? [h("p", {class: "sub"}, t("dock.kb.working"))] : []));
        if (found.running) timer = setTimeout(() => load(op, paint, false, Math.min((wait || 150) * 2, 1200)), wait || 150);
      }, (error) => { if (view.box.isConnected && key === current) stage.replaceChildren(h("p", {class: "bad"}, error.message || String(error))); });
    }
    const mapButton = (hot) => {  // the map is a script, in the background: it costs no request, and the view comes back when it is done
      const go = h("button", {type: "button", class: "act" + (hot ? " hot" : "")}, t("dock.kb.rebuild"));
      go.addEventListener("click", () => TERM.run("harness kb map", () => { if (view.box.isConnected) again.click(); }));  // Refresh forgets every view: Domains and Overview change with the map (1.7.38)
      return go;
    };
    const nextButton = (stageName) => {  // the first two steps are done in the setup, not in a chat
      const inSetup = ["targets", "kb_repo"].includes(stageName);
      const go = h("button", {type: "button", class: "act hot"}, t(inSetup ? "dock.setup" : "dock.kb.next"));
      go.addEventListener("click", leave(inSetup ? setupWindow : () => start("harness-rookie-new-knowledgebase", t("dock.kb.next.words", {step: stageName}), () => kbWindow(current))));
      return go;
    };
    // Why a step is not done, when the status knows: a broken toolkit, facts the map does not find, repositories it does not cover.
    const notes = (found) => found.steps.flatMap((item) => [...(item.problems || []), item.problem, item.note, item.no_toolkit ? t("dock.kb.map.notoolkit", {names: item.no_toolkit.join(", ")}) : "", item.step === "map" && item.facts && !item.done ? t("dock.kb.map.facts", {facts: item.facts}) : ""].filter(Boolean)).map((line) => h("p", {class: "su-warn"}, plainWords(line)));
    const chatGlyph = () => { const node = drawn(["M4 5h16v11h-8l-4 3.5V16H4z"]); node.classList.add("kb-chat"); return node; };
    const chatButton = (label, run, hot) => { const go = h("button", {type: "button", class: "act" + (hot ? " hot" : "")}, chatGlyph(), label); go.addEventListener("click", leave(run)); return go; };
    const backHere = () => kbWindow(current);
    const taskChat = (skill, domain, word) => CHAT.create({kind: "kb", name: word + "-" + domain.toLowerCase().replace(/[^a-z0-9_-]+/g, "-"), domains: [domain], text: "Use the skill " + skill + ". Domain: " + domain + ".", note: t("dock.task.note"), back: backHere});
    const goOn = (item) => start("generic-kb-learn-batch", item.task, backHere, item.task);
    const learn = (item) => taskChat("generic-kb-learn-plan", item.domain, "learn");
    const refresh = (item) => taskChat("generic-kb-refresh", item.domain, "refresh");
    // What a domain asks for, by what is known of it: learning first, then its stale cards. A task that waits for its plan to be approved is the person's, on its own page.
    function action(item) {
      if (item.task) return item.plan && item.to_learn ? [t("dock.kb.go"), goOn] : null;
      if (!item.done) return [t("dock.kb.learn"), learn];
      const known = extra && extra.domains[item.domain];
      return known && known.stale ? [t("dock.kb.refresh.cards"), refresh] : null;
    }
    const staleOf = (item) => { if (!extra) return undefined; const known = extra.domains[item.domain]; return known ? known.stale : 0; };  // a domain only listed has no folder yet, so no card
    const percent = (item) => { const left = item.to_learn || 0, cards = item.cards || 0; return item.done ? 100 : item.problem ? 0 : cards + left ? Math.round(100 * cards / (cards + left)) : 0; };  // a domain whose objects are not known (no map) has no bar, not a full one
    function readText(item) {
      if (!extra) return "\u2026";
      const known = extra.domains[item.domain];
      if (!known || !known.read) return t("dock.kb.read.never");
      const days = Math.floor((Date.now() - Date.parse(known.read)) / 86400000);
      return !(days > 0) ? t("dock.kb.read.today") : t("dock.kb.read.days", {n: days});
    }
    const state = (item) => (item.task ? [t("dock.kb.state.task") + " ", h("a", {href: "/task/" + encodeURIComponent(item.task)}, item.task)] : t(item.done ? "dock.kb.state.done" : item.listed ? "dock.kb.state.listed" : "dock.kb.state.open"));
    function domainTable(list, full) {
      const heads = ["domain", ...(full ? ["state"] : []), "cards", "learned", "stale", "requests", "read", ""];
      const row = (item) => {
        const stale = staleOf(item), todo = action(item);
        const bar = h("span", {class: "kb-bar-line", title: percent(item) + "%"}, h("i", {style: "width:" + percent(item) + "%"}));
        const button = todo ? h("button", {type: "button", class: "act kb-mini"}, chatGlyph(), todo[0]) : null;
        if (button) button.addEventListener("click", leave(() => todo[1](item)));
        return h("tr", null, h("td", {class: "kb-name"}, h("b", null, item.domain)), full ? h("td", null, state(item)) : null, h("td", {class: "kb-num"}, String(item.cards || 0)), h("td", null, bar, item.to_learn ? h("span", {class: "sub kb-left"}, t("dock.kb.left", {n: item.to_learn})) : null),
          h("td", {class: "kb-num" + (stale ? " kb-hot" : "")}, stale === undefined ? "…" : stale === null ? "?" : stale ? String(stale) : "-"), h("td", {class: "kb-num"}, String(item.requests_open || 0)), h("td", {class: "kb-num"}, readText(item)), h("td", {class: "kb-do"}, button));
      };
      return h("div", {class: "scroll"}, h("table", {class: "md kb-table"}, h("thead", null, h("tr", null, heads.map((key) => h("th", null, key ? t("dock.kb.col." + key) : "")))), h("tbody", null, list.map(row))));
    }
    // The next step in words for a person, with the button that does it; `kb status` writes its own `next` for the agent.
    function nextCard(found) {
      const built = found.stage === "maintain" && found.steps.every((item) => item.done);
      if (found.stage === "learn") {
        const item = found.domains.find((one) => !one.done);
        if (item) {
          const words = !item.task ? [t("dock.kb.next.plan", {domain: item.domain}), chatButton(t("dock.kb.learn"), () => learn(item), true)]
            : !item.plan ? [t("dock.kb.next.approve", {domain: item.domain, task: item.task}), null]
            : item.to_learn ? [t("dock.kb.next.batch", {domain: item.domain, left: item.to_learn, batches: item.batches_left || 0, task: item.task}), chatButton(t("dock.kb.go.chat"), () => goOn(item), true)]
            : [t("dock.kb.next.finish", {domain: item.domain, task: item.task}), null];
          return h("div", {class: "kb-next"}, h("p", null, words[0]), words[1]);
        }
      }
      return h("div", {class: "kb-next"}, h("p", null, t("dock.kb.what." + (built ? "built" : found.stage))), built ? null : nextButton(found.stage));
    }
    function tiles(found) {
      const tile = (value, label, mark) => h("div", {class: "kb-tile" + (mark ? " " + mark : "")}, h("b", null, value), h("span", null, label));
      const waiting = "…";
      return h("div", {class: "kb-tiles"}, tile(String(found.domains.length), t("dock.kb.tile.domains")), tile(String(found.domains.reduce((sum, item) => sum + (item.cards || 0), 0)), t("dock.kb.tile.cards")),
        tile(extra ? String(extra.stale) : waiting, t("dock.kb.tile.stale"), extra && extra.stale ? "hot" : ""), tile(String(found.requests_open), t("dock.kb.tile.requests")), tile(extra ? String(extra.form_errors) : waiting, t("dock.kb.tile.errors"), extra && extra.form_errors ? "bad" : ""));
    }
    const legend = () => h("p", {class: "sub kb-legend"}, chatGlyph(), t("dock.kb.legend"));
    const FIRST = 6;  // the rows of Overview; the rest are in Domains. What asks for something comes first
    function overview(found) {
      const list = [...found.domains].sort((one, two) => Number(Boolean(action(two))) - Number(Boolean(action(one))));
      const more = h("button", {type: "button", class: "first-link"}, t("dock.kb.all", {n: list.length}));
      more.addEventListener("click", () => show("domains"));
      stage.replaceChildren(...[h("ol", {class: "kb-steps"}, found.steps.map((item) => h("li", {class: item.done ? "done" : item.step === found.stage ? "here" : ""}, t("dock.kb.step." + item.step)))),
        nextCard(found), ...notes(found), found.domains.length ? tiles(found) : null, found.domains.length ? domainTable(list.slice(0, FIRST), false) : null, list.length > FIRST ? more : null, found.domains.length ? legend() : null].filter(Boolean));
    }
    function domains(found) {
      if (!found.domains.length) { stage.replaceChildren(h("p", {class: "sub"}, t("dock.kb.nodomains")), nextButton(found.stage)); return; }
      const more = h("button", {type: "button", class: "first-link"}, t("dock.skills.kb"));
      more.addEventListener("click", leave(() => allSkills("kb", () => kbWindow("domains"))));
      stage.replaceChildren(domainTable(found.domains, true), more, legend());
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
        post({op: "near", query: text}).then((found) => { if (shown()) out.replaceChildren(...near(found, find)); }, (error) => { if (shown()) out.replaceChildren(h("p", {class: "bad kb-alarm"}, h("span", null, error.message || String(error)), ...(error.message === t("dock.kb.nomap") ? [nextButton("map")] : []))); });
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
      const ids = (rows, label) => (rows.length ? [h("p", {class: "sub"}, label), h("ul", null, rows.map((id) => h("li", null, h("code", null, id))))] : []);
      const staleRows = found.stale || [], gaps = found.gaps || {};
      const audit = found.audit || {};
      const auditGo = h("button", {type: "button", class: "act kb-mini"}, chatGlyph(), t(audit.done ? "dock.kb.audit.again" : "dock.kb.audit.go"));
      auditGo.addEventListener("click", leave(() => start("generic-kb-toolkit-audit", "", backHere)));
      const auditBlock = [h("h3", null, t("dock.kb.audit")), h("section", {class: "kb-problem"}, h("div", {class: "kb-head"}, h("span", null, !audit.ready ? t("dock.kb.audit.nomap") : audit.done ? t("dock.kb.audit.done") : audit.note ? plainWords(audit.note) : t("dock.kb.audit.none")), audit.ready ? auditGo : null))];
      const staleButton = (item) => { const go = h("button", {type: "button", class: "act kb-mini"}, chatGlyph(), t("dock.kb.refresh.cards")); go.addEventListener("click", leave(() => refresh(item))); return go; };
      const showAll = (n, line, key) => { const go = h("button", {type: "button", class: "act kb-mini"}, t("dock.kb.health.all")); go.addEventListener("click", () => TERM.run(line)); return h("p", {class: "sub"}, t(key, {n}), " ", go); };
      const cut = (shown, total, line) => (total > shown ? showAll(total - shown, line, "dock.kb.health.cut") : null);
      stage.replaceChildren(...[...auditBlock, h("h3", null, t("dock.kb.health.form")), h("p", null, found.domains ? t("dock.kb.health.sum", {n: found.domains, errors: found.errors, warnings: found.warnings}) : t("dock.kb.health.none")),
        ...items.map((item) => h("section", {class: "kb-problem"}, h("b", null, item.domain || item.name || ""), h("ul", null, lines(item, "errors"), lines(item, "warnings").slice(0, Math.max(0, SHOWN - (item.errors || []).length))), left(item) > 0 ? showAll(left(item), "harness kb check", "dock.kb.health.more") : null)),
        found.domains ? h("h3", null, t("dock.kb.health.stale")) : null, found.domains && !staleRows.length ? h("p", {class: "sub"}, t("dock.kb.health.fresh")) : null,
        ...staleRows.map((item) => h("section", {class: "kb-problem"}, h("div", {class: "kb-head"}, h("b", null, item.domain + (item.total ? " \u00b7 " + item.total : "")), item.total ? staleButton(item) : null), item.error ? h("p", {class: "bad"}, item.error) : null, ...item.unreadable.map((one) => h("p", {class: "bad"}, one.repo + ": " + one.error)), ...ids(item.changed, t("dock.kb.health.changed")), ...ids(item.gone, t("dock.kb.health.gone")), cut(item.changed.length + item.gone.length, item.total, "harness kb stale"))),
        gaps.names ? h("h3", null, t("dock.kb.health.gaps")) : null, gaps.names && !gaps.missing && !gaps.obsolete_used ? h("p", {class: "sub"}, t("dock.kb.health.nogaps")) : null,
        ...(gaps.names ? [h("section", {class: "kb-problem"}, ...ids(gaps.names, t("dock.kb.health.missing", {n: gaps.missing})), cut(gaps.names.length, gaps.missing, "harness kb gaps"), ...ids(gaps.obsolete, t("dock.kb.health.obsolete", {n: gaps.obsolete_used})), cut(gaps.obsolete.length, gaps.obsolete_used, "harness kb gaps"))] : [])].filter(Boolean));
    }
    function show(key) {
      clearTimeout(timer);
      current = key;
      synced.classList.toggle("off", key !== "overview");  // the card asks for one thing: on the first tab, not over every view
      seenView = "";
      painted = null;
      tabs.forEach((tab) => tab.classList.toggle("on", tab.dataset.key === key));
      view.box.classList.toggle("ka-open", key === "atlas");
      stage.classList.remove("ka-stage", "co-stage");
      COMPANYTAB.clear();
      age.textContent = "";
      alarm.hidden = true;
      again.hidden = key === "lookup";
      rebuild.hidden = true;
      stage.replaceChildren(h("p", {class: "sub"}, t("dock.kb.working")));
      if (key === "lookup") { lookup(); return; }
      const op = ["health", "atlas", "company"].includes(key) ? key : "status";
      const paint = key === "health" ? health : key === "atlas" ? (found) => ATLAS.draw(stage, found) : key === "company" ? (found) => COMPANYTAB.draw(stage, found, {goMap: () => show("atlas"), goDomains: () => show("domains"), goTools: typeof TOOLS !== "undefined" ? () => TOOLS.open("packs", () => show("company")) : null}) : key === "overview" ? overview : domains;
      again.onclick = () => {  // every kept view is old, not only this one: a map rebuilt here changes Overview and Domains too
        clearTimeout(timer);
        post({op: "forget"}).catch(() => {}).then(() => { asked.clear(); asked.add(op); asked.add("detail"); load(op, paint, true); loadDetail(true); });
        recheck();
      };
      load(op, paint, !asked.has(op));
      asked.add(op);
      if (op === "status" && !asked.has("detail")) { asked.add("detail"); loadDetail(true); }
    }
    // The stale cards, the form errors and the reads ask git and the logs: they come after the page is drawn, and the rows fill in.
    function loadDetail(fresh) {
      clearTimeout(detailTimer);
      post({op: "detail", fresh}).then((found) => {
        if (!view.box.isConnected) return;
        if (found.result) { extra = found.result; badge(extra.stale); if (painted && ["overview", "domains"].includes(current)) painted(); }
        if (found.running) detailTimer = setTimeout(() => loadDetail(false), 800);
      }, () => {});
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
    const form = SETUP.mount(box, () => { saved = true; note.textContent = ""; close.classList.add("hot"); }, (busy) => {  // no Close while the work runs (1.7.19)
      close.hidden = busy;
      note.textContent = busy ? t("setup.run.working") : note.textContent === t("setup.run.working") ? "" : note.textContent;
    });
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
    const setup = icon("dock-setup", t("dock.setup"), ["M12 8.7a3.3 3.3 0 1 0 0 6.6 3.3 3.3 0 0 0 0-6.6z", "M12 2.4l1.5 2.55 3-0.6 0.9 3 2.85 1.2-1.05 2.85 1.95 2.4-2.4 1.95 0.15 3-3 0.45-1.5 2.7L12 20.4l-2.4 1.5-1.5-2.7-3-0.45 0.15-3L3 13.35l1.95-2.4-1.05-2.85 2.85-1.2 0.9-3 3 0.6z"], setupWindow);  // the gear: Get ready / Change the setup (1.7.35; the board's own panel below it has the sliders)
    const home = icon("dock-home", t("dock.home"), ["M3.5 11.5 12 4.5l8.5 7M6 9.5V20h12V9.5M10 20v-5.5h4V20"], enterScreen);
    kb.append(h("span", {class: "dock-count", title: t("dock.kb.badge"), hidden: ""}));
    document.body.append(panel, button, kb, setup, home);
    watchStale();
    watchCompany();
  }

  if (typeof DATA !== "undefined" && DATA.serve) build();
  return {start, allSkills, kbWindow, setupWindow, enterScreen, chooseOnPage, syncCompany};
})();
