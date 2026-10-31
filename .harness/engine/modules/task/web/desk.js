// One task in the browser: its documents, TODO progress, history, changes, and what the person can do now.
// DATA.desk is what taskdesk.desk returns; DATA.serve is the board server's (actions, refresh). Markdown comes as a tree
// of blocks (mdtree.py) and is drawn node by node with textContent: nothing an agent wrote can become markup.
// The page asks the server for the task again every few seconds and draws it again only when something changed,
// keeping the open tab and the scroll.
"use strict";

(function () {
  const app = document.getElementById("app");
  let full = DATA.desk;  // the task as the server gave it; `desk` is what the page draws: this, or an earlier round of it (pastView)
  let desk = full;
  let shown = JSON.stringify(full);
  const same = (a, b) => a.replace(/"as_of":"[^"]*"/, "") === b.replace(/"as_of":"[^"]*"/, "");  // the time of asking is not a change
  const tabs = ["overview", "req", "intake", "design", "rca", "test", "plan", "todo", "log", "changes", "review", "history", "trace", "docs", "files"];  // the commit message is at the top of "changes" once written back (1.5.34)
  const FILES = {overview: "TASK.md", req: "REQ.md", plan: "PLAN.md", todo: "TODO.md", log: "LOG.md", design: "DESIGN.md", rca: "RCA.md"};
  const WRITES_BACK = ["dev", "kb"];  // the kinds that have a plan, a diff and a commit
  const PAST_TABS = ["req", "plan", "changes", "review", "history", "files"];  // an earlier round keeps these; the others (overview, TODO, log, intake) are the task's, not one round's
  const route = /^r(\d+)(?:\/(.*))?$/.exec(location.hash.slice(1));  // #r1/plan: a link to an earlier round
  const wanted = route ? route[2] || "" : location.hash.slice(1);
  const asked = wanted === "commit" ? "changes" : wanted;  // a link to the old Commit tab
  let other = "";  // the document open in the "docs" tab

  const served = () => typeof SERVE !== "undefined" && Boolean(DATA.serve);
  const saved = Boolean(DATA.snapshot);  // a saved copy: no buttons, no way back to a board, no calls to a server

  const doc = (name) => desk.docs.find((item) => item.name === name);

  // An earlier round (a written back task that was opened again) as a page of its own: the same tabs, filled from what the server kept of that round. Nothing in it can be changed.
  function pastView(task, number) {
    const found = (task.rounds || []).find((item) => item.round === number);
    if (!found) return task;
    const stages = task.stages ? Object.assign({}, task.stages, {round: number, review: null, steps: task.stages.steps.map((step) => Object.assign({}, step, {state: "done", flag: ""}))}) : null;  // written back: every step is done
    return Object.assign({}, task, {
      past: found, round: number, status: "closed", state: "", waiting: "", waiting_why: "", waited_s: null, paused_since: "", handoff: null, held: false, autorun: false, active: false,
      branch: found.branch, docs: found.docs, files: found.files, changes: found.changes, review: found.review, history: found.history, stages,
      commit: null, test: null, intake: null, actions: [], todo: {done: 0, total: 0}, todo_left: 0, req_placeholders: 0, req_unconfirmed: false, req_changed: false, report: "",
    });
  }
  const hashOf = (tab) => "#" + (desk.past ? "r" + desk.past.round + "/" : "") + tab;
  const firstTab = () => tabs.find((tab) => ownTab(tab) && tab !== "docs") || "overview";
  // The server sent the task again: draw the round that is open from the new data.
  function setDesk(next) {
    full = next;
    shown = JSON.stringify(next);
    desk = desk.past ? pastView(full, desk.past.round) : full;
    if (!ownTab(current)) current = firstTab();
  }
  function showRound(number, tab) {
    desk = number === full.round ? full : pastView(full, number);
    current = tab && ownTab(tab) ? tab : firstTab();
    history.replaceState(null, "", hashOf(current));
    draw(false);
  }
  // A tab is there when the kind of the task has it, or when its file is there (M40-1): a test task has no plan and no diff; a question has no log.
  const ownTab = (tab) => {
    if (desk.past && !PAST_TABS.includes(tab)) return false;
    if (desk.past && tab === "plan") return Boolean(doc(FILES.plan));
    if (tab === "design" || tab === "rca") return Boolean(doc(FILES[tab])) || (desk.kind === tab && desk.status === "open");  // a closed task that never wrote it has nothing to show
    if (tab === "plan") return WRITES_BACK.includes(desk.kind) || (desk.kind !== "test" && Boolean(doc(FILES.plan)));
    if (tab === "changes") return WRITES_BACK.includes(desk.kind) || (desk.kind !== "test" && desk.changes.files.length > 0);
    if (tab === "todo" || tab === "log" || tab === "req") return Boolean(doc(FILES[tab]));
    if (tab === "test") return Boolean(desk.test);
    if (tab === "review") return desk.review.n > 0 || desk.review.rounds.length > 0;
    if (tab === "files") return desk.files.length > 0;
    if (tab === "trace") return Boolean(desk.trace && desk.trace.entries.length);
    if (tab === "intake") return Boolean(desk.intake) && served();  // a saved copy has no server to write to
    return true;
  };
  const extra = () => desk.docs.filter((item) => !Object.keys(FILES).some((tab) => FILES[tab] === item.name && ownTab(tab)) && item.name !== "REQ.md" && !(desk.test && item.name === "TEST-GUIDE.md") && !(desk.commit && item.name === "COMMIT-MESSAGE.md"));  // these have a tab of their own
  let current = "overview";
  if (route && (full.rounds || []).some((item) => item.round === Number(route[1]))) desk = pastView(full, Number(route[1]));
  current = tabs.includes(asked) && ownTab(asked) ? asked : firstTab();

  // --- markdown -------------------------------------------------------------------------------------------

  // Review answers: a place in the task folder ("DEV/dir/file.sql:3", "REQ/paper.md:40") is a link to the file: its diff on the Changes tab when it is in the diff, else the Files tab.
  // In a code span the whole text is the place (spaces and Chinese are fine); in plain text it runs to the next space.
  let placeLinks = false;
  const PLACE = /^((?:DEV|REQ|REF|RUNS|INBOX)\/.+?)(?::(\d+)(?:-\d+)?)?$/;
  const PLACE_IN_TEXT = /(?:DEV|REQ|REF|RUNS|INBOX)\/[^\s,;，；。`'"()（）]+/g;
  function placeLink(text, label) {
    const found = PLACE.exec(text.trim());
    if (!found) return null;
    const path = found[1];
    const dev = path.startsWith("DEV/") ? path.slice(4) : "";
    const inDiff = dev && (desk.changes.files.some((item) => item.path === dev) || desk.changes.deletes.includes(dev)) && ownTab("changes");
    if (!inDiff && !(ownTab("files") && desk.files.some((item) => item.path === path))) return null;
    const a = h("a", {href: "#" + (inDiff ? "changes" : "files"), title: t("desk.path.open", {path})}, label);
    a.addEventListener("click", (event) => {
      event.preventDefault();
      current = inDiff ? "changes" : "files";
      if (inDiff) DiffView.select("dev", dev, found[2] ? Number(found[2]) : 0);  // the file in the Changes picker, and its line
      else fileOpen = path;
      history.replaceState(null, "", "#" + current);
      draw(false);
    });
    return a;
  }

  function inline(spans) {
    return spans.map((span) => {
      if (placeLinks && span.t === "code") return placeLink(span.v, h("code", null, span.v)) || h("code", null, span.v);
      if (placeLinks && span.t === "text" && /(?:DEV|REQ|REF|RUNS|INBOX)\//.test(span.v)) {
        const out = [];
        let from = 0;
        for (const found of span.v.matchAll(PLACE_IN_TEXT)) {
          const link = placeLink(found[0], found[0]);
          if (!link) continue;
          out.push(span.v.slice(from, found.index), link);
          from = found.index + found[0].length;
        }
        return [...out, span.v.slice(from)];
      }
      if (span.t === "text") return span.v;
      if (span.t === "br") return h("br");
      if (span.t === "code") return h("code", null, span.v);
      if (span.t === "b") return h("strong", null, inline(span.c));
      if (span.t === "i") return h("em", null, inline(span.c));
      if (span.t === "s") return h("s", null, inline(span.c));
      if (span.t === "a") return link(span.href, inline(span.c));
      if (span.t === "img") return picture(span);
      return "";
    });
  }

  // A picture of the task (the evidence a person gave): from the board server by its path in the task folder, from a saved copy by its own bytes.
  // Click to see it whole. A saved copy that was too large to take it in shows its description.
  function picture(span) {
    const src = span.data || (served() ? "/file/" + encodeURIComponent(desk.name) + "/" + span.src.split("/").map(encodeURIComponent).join("/") : "");
    if (!src) return h("span", {class: "path", title: span.src}, span.alt || span.src);
    // Not `loading: "lazy"`: a picture above the screen that loads late pushes the page down by its height while the person scrolls up (a drift of a few pixels). They are local files.
    const image = h("img", {src, alt: span.alt, title: span.alt, class: "md-img"});
    return span.data ? image : h("a", {href: src, target: "_blank", rel: "noopener noreferrer", class: "md-img-link"}, image);  // a browser does not open a data: address in a new tab
  }

  // A link to another document of the task opens its tab; http(s) and mailto open outside; a path of the repository
  // is shown as a path: it opens in VS Code, not here.
  function link(href, label) {
    const name = href.split("#")[0].split("/").pop();
    if (desk.docs.some((item) => item.name === name) && !/^[a-z]+:/i.test(href)) {
      const a = h("a", {href: "#"}, label);
      a.addEventListener("click", (event) => { event.preventDefault(); openDoc(name); });
      return a;
    }
    if (/^(https?:|mailto:)/i.test(href)) return h("a", {href, target: "_blank", rel: "noopener noreferrer"}, label);
    if (href.startsWith("#")) return h("span", null, label);
    return h("span", {class: "path", title: t("desk.path.hint", {path: href})}, label);
  }

  // A code block of any document has a button that copies it whole: a command or a query is pasted into a terminal or a client, not retyped.
  // `kind`: the language from highlight.js (of the file's type or of the word after the three backticks); "" is plain text.
  function codeBlock(text, kind) {
    const button = h("button", {type: "button", class: "act copy-code", "data-label": t("desk.code.copy")}, t("desk.code.copy"));
    button.addEventListener("click", () => copyCommand(button, text));
    return h("div", {class: "code-box"}, h("div", {class: "code-bar"}, Highlight.label(kind) ? h("span", {class: "code-lang"}, Highlight.label(kind)) : null, button), h("pre", {class: "code"}, h("code", null, Highlight.nodes(text, kind))));
  }

  function blocks(list) {
    return list.map((block) => {
      if (block.t === "h") return h("h" + Math.min(block.level + 1, 6), {class: "md-h"}, inline(block.spans));
      if (block.t === "p") return h("p", null, inline(block.spans));
      if (block.t === "hr") return h("hr");
      if (block.t === "code") return codeBlock(block.text, Highlight.language(block.lang));
      if (block.t === "quote") return h("blockquote", null, blocks(block.blocks));
      if (block.t === "table") {
        const plain = (spans) => spans.map((span) => (span.v !== undefined ? span.v : span.c ? plain(span.c) : "")).join("");
        const VERDICT_CLASS = {"PASS": "v-good", "FAIL": "v-bad", "NEEDS MORE": "v-warn"};  // a test verdict cell is coloured
        const cell = (tag, spans, align) => {
          const mark = tag === "td" ? VERDICT_CLASS[plain(spans).trim().toUpperCase()] : null;
          return h(tag, {style: align ? "text-align:" + align : null, class: mark || null}, inline(spans));
        };
        return h("div", {class: "scroll"}, h("table", {class: "md"},
          h("thead", null, h("tr", null, block.head.map((spans, i) => cell("th", spans, block.align[i])))),
          h("tbody", null, block.rows.map((row) => h("tr", null, row.map((spans, i) => cell("td", spans, block.align[i])))))));
      }
      if (block.t === "ul" || block.t === "ol") {
        const checks = block.items.some((item) => item.check !== null);
        return h(block.t, {class: checks ? "checks" : null, start: block.t === "ol" && block.start !== 1 ? block.start : null},
          block.items.map((item) => h("li", {class: item.check === null ? null : item.check ? "done" : "open"},
            item.check === null ? null : h("span", {class: "box"}, item.check ? "✓" : ""),
            h("span", {class: "txt"}, inline(item.spans)), blocks(item.blocks))));
      }
      return null;
    });
  }

  function markdown(name, empty) {
    const found = doc(name);
    if (!found) return h("div", {class: "empty-state"}, h("b", null, t("desk.missing", {file: name})), h("p", null, empty));
    // The template's own words under the title ("> The handover file. A new session reads this file first...") are for the agent: folded, so the page starts with the task.
    const note = (name === "TASK.md" || name === "REQ.md") && found.blocks.length > 1 && found.blocks[0].t === "h" && found.blocks[1].t === "quote";
    const parts = note ? [blocks(found.blocks.slice(0, 1)), h("details", {class: "tpl-note"}, h("summary", null, t("desk.template.note")), blocks(found.blocks.slice(1, 2))), blocks(found.blocks.slice(2))] : blocks(found.blocks);
    return h("article", {class: "md"}, parts, found.cut ? h("p", {class: "sub"}, t("desk.cut")) : null);
  }


  // --- the parts --------------------------------------------------------------------------------------------

  // After the requirement is confirmed, only a task that is written back needs a plan; a test task writes its guide; the others go on (B65).
  const REQ_NEXT = (kind) => (kind === "dev" || kind === "kb" ? "" : kind === "test" ? ".test" : ".work");
  const taskLink = (name) => (saved ? h("b", null, name) : h("a", {href: "/task/" + encodeURIComponent(name)}, name));  // a saved page links to no board

  // "Round 1 · Round 2 (current)": only a task that was written back and opened again has more than one.
  function roundSwitch() {
    if (!(full.rounds || []).length) return null;
    const numbers = [...full.rounds.map((item) => item.round), full.round];
    const shownRound = desk.past ? desk.past.round : full.round;
    return h("nav", {class: "subtabs small round-switch"}, numbers.map((number) => {
      const button = h("button", {type: "button", class: "subtab" + (number === shownRound ? " on" : "")}, t(number === full.round ? "desk.round.pick.current" : "desk.round.pick", {round: number}));
      button.addEventListener("click", () => { if (number !== shownRound) showRound(number, current); });
      return button;
    }));
  }

  // On an earlier round: no button and no "what waits for you"; one line says what this is.
  function pastNote() {
    const back = h("button", {type: "button", class: "act"}, t("desk.round.back"));
    back.addEventListener("click", () => showRound(full.round, current));
    return h("section", {class: "card actions quiet"}, h("p", {class: "sub"}, t("desk.round.past", {round: desk.past.round})), back);
  }

  function header() {
    const kind = t("task.kind." + (desk.kind || "none")) + " · " + t("task.tier." + (desk.tier || "none"));
    const state = stateTag(desk, served());
    return [
      brand(),
      saved ? null : h("div", {class: "crumbs sub"}, h("a", {href: "/"}, "← " + t("desk.back")),
        desk.report ? [" · ", h("a", {href: desk.report.split("/").map(encodeURIComponent).join("/")}, t("desk.report"))] : null,
        served() ? [" · ", h("a", {href: "/snapshot/" + encodeURIComponent(desk.name), download: "", title: t("desk.save.hint")}, t("desk.save"))] : null),
      h("div", {class: "title-row"}, h("h1", null, desk.name), roundSwitch(), state),
      h("div", {class: "sub"}, t("desk.subtitle", {kind, round: desk.round, created: when(desk.created_at, 0, 16), updated: when(desk.updated_at, 0, 16)}),
        desk.domains.length ? " · " + t("desk.domains", {names: desk.domains.join(", ")}) : "", desk.autorun ? [" · ", tag(t("desk.autorun"), "good")] : null),
      desk.forked_from || desk.forked_to.length ? h("div", {class: "sub"},  // the tasks this one came from and went on to (`task fork`)
        desk.forked_from ? [t("desk.forked.from") + " ", taskLink(desk.forked_from)] : null,
        desk.forked_from && desk.forked_to.length ? " · " : null,
        desk.forked_to.length ? [t("desk.forked.to") + " ", desk.forked_to.map((name, index) => [index ? ", " : "", taskLink(name)])] : null) : null,
    ];
  }

  // The chat of VS Code behind this task (1.6): its state now, the model of its last turn, a button to its window; under it the last thing the agent did, with the first lines of its last reply to open.
  // The whole conversation is not drawn: it is in VS Code. Only a served page, and not an earlier round.
  let recentOpen = false;
  function chatBars() {
    if (!served() || desk.past || !desk.chat) return null;
    const chat = desk.chat;
    const row = [h("span", {class: "chat-k"}, t("desk.chat.label"))];
    if (chat.bound) {
      row.push(h("span", {class: "chat-title", title: chat.title}, chat.title || "-"), tag(t("desk.chat." + (chat.state || "unknown")), chat.state === "busy" ? "good run" : chat.state === "input" || chat.state === "error" ? "hot" : ""));
      if (chat.model) row.push(h("span", {class: "sub"}, t("desk.chat.model", {model: chat.model})));
    } else {
      row.push(h("span", {class: "sub"}, t("desk.chat.unbound", {why: t("board.vs.why." + (chat.why || "no-chat"))})));
    }
    row.push(h("span", {class: "chat-grow"}), SERVE.vsButton(chat), h("span", {class: "sub"}, t("desk.chat.window")));
    const bars = [h("section", {class: "card chatbar"}, row)];
    if (desk.sub && (desk.sub.what || desk.sub.text)) {
      const more = desk.recent && desk.recent !== desk.sub.text ? h("details", {class: "recent-more", open: recentOpen ? "" : null}, h("summary", null, t("desk.recent.more")), h("pre", {class: "recent-text"}, desk.recent)) : null;
      if (more) more.addEventListener("toggle", () => { recentOpen = more.open; });
      bars.push(h("section", {class: "card chatbar recent"}, h("span", {class: "chat-k"}, t("desk.recent.label")), h("div", {class: "recent-body"}, h("div", {class: "recent-line"}, subNodes(desk.sub)), more)));
    }
    return bars;
  }

  // "Task settings" (1.6, B72): the independent checks (0 to the cap), the model and the thinking level of the messages the board sends. Only the person changes them, from a served page;
  // a change is written in the history and holds from the next message. The model goes on every message the board sends and stays in the chat, also for what is typed in VS Code, until it is changed.
  function settingsRow() {
    const info = desk.settings;
    if (!served() || desk.past || !info || desk.status !== "open") return null;
    const can = SERVE.runs("review set");
    const chips = [];
    for (let n = 0; n <= info.max_n; n++) {
      const chip = h("button", {type: "button", class: "chip" + (n === info.n ? " on" : ""), "aria-pressed": n === info.n ? "true" : "false", disabled: can ? null : "disabled", title: t("desk.set.checks.tip", {n})}, String(n));
      chip.addEventListener("click", () => {
        if (n === info.n) return;
        chips.forEach((item) => { item.disabled = true; });
        SERVE.post("/api/act", {action: "review set", task: desk.name, n, step: "act"}).then(() => SERVE.done(), (error) => { SERVE.failed(error); SERVE.done(); });
      });
      chips.push(chip);
    }
    const models = info.models || [];
    const pick = h("select", {"aria-label": t("desk.set.model"), disabled: info.ready && models.length ? null : "disabled", title: info.ready ? "" : t("desk.set.model.off")},
      h("option", {value: ""}, t("desk.set.model.chat")), models.map((item) => h("option", {value: item.id, selected: item.id === info.model ? "" : null}, item.name)));
    const chosen = models.find((item) => item.id === info.model);
    const levels = chosen && chosen.thinking ? chosen.thinking.levels : [];
    const think = h("select", {"aria-label": t("desk.set.thinking"), disabled: levels.length ? null : "disabled"},
      h("option", {value: ""}, t("desk.set.thinking.default")), levels.map((level) => h("option", {value: level, selected: level === info.thinking ? "" : null}, level)));
    const save = (id, level) => SERVE.post("/api/setting", {task: desk.name, id, thinking: level}).then(() => SERVE.done(), (error) => { SERVE.failed(error); SERVE.done(); });
    pick.addEventListener("change", () => save(pick.value, ""));  // a new model starts at its own default level
    think.addEventListener("change", () => save(pick.value, think.value));
    return h("section", {class: "card chatbar settings"}, h("span", {class: "chat-k"}, t("desk.set.label")),
      h("label", {class: "set-field"}, h("span", {class: "sub"}, t("desk.set.model")), pick), h("label", {class: "set-field"}, h("span", {class: "sub"}, t("desk.set.thinking")), think),
      h("span", {class: "set-field"}, h("span", {class: "sub"}, t("desk.set.checks")), h("span", {class: "chips"}, chips)),
      h("p", {class: "sub set-note"}, t("desk.set.note", {n: Math.max(1, info.n || 3)})));
  }

  // What the card says when no button is the point: put aside, waiting for a word in VS Code, nobody on it, or really nothing.
  function quiet() {
    if (desk.paused_since) return {title: t("desk.actions.paused"), hint: t("desk.actions.paused.hint")};
    const why = desk.waiting_why;
    if (desk.waiting && (["stopped", "cancelled", "autorun", "tests", "run", "commit"].includes(why) || why.startsWith("go-"))) {
      const handed = desk.handoff || {};
      const form = served() && (why === "tests" || why === "run");  // the page has the form for the results: no message to teach (the form says it)
      return {title: desk.waiting.charAt(0).toUpperCase() + desk.waiting.slice(1), hint: t("desk.wait." + why + (form ? ".form" : ""), {env: handed.env || "", what: handed.detail || "", branch: desk.branch || ""}),
        prompt: why.startsWith("go-") ? t("desk.go." + why.slice(3) + (why === "go-req" ? REQ_NEXT(desk.kind) : "")) : form ? "" : why === "tests" ? t("desk.tests.prompt") : why === "run" ? t("desk.run.prompt", {env: handed.env || ""}) : ""};
    }
    if (desk.state === "unheld") return {title: t("desk.actions.unheld"), hint: t("desk.actions.unheld.hint"), prompt: t("desk.unheld.prompt", {name: desk.name})};
    if (stateOf(desk, served()) === "quiet") return {title: t("desk.actions.quiet"), hint: t("desk.actions.quiet.hint")};
    if (desk.waiting) return {title: desk.waiting.charAt(0).toUpperCase() + desk.waiting.slice(1), hint: ""};  // a reason with no card of its own: never "nothing waits" (B62)
    return {title: t("desk.actions.none"), hint: t("desk.actions.none.hint")};
  }

  // Give the results of a run here (1.5.42): the output and the commands as text, screenshots as pictures. The server saves them under INBOX/ in the task; the person
  // then tells the agent. What is typed is kept in `form` so a redraw of the page does not lose it.
  const form = {env: "", text: "", ran: "", images: [], busy: false, error: "", gave: null};
  const MAX_IMAGES = 10, MAX_IMAGE_BYTES = 8 * 1024 * 1024;

  function addImages(files) {
    for (const file of files) {
      if (!/^image\//.test(file.type)) continue;
      if (form.images.length >= MAX_IMAGES) { form.error = t("desk.inbox.too_many", {limit: MAX_IMAGES}); break; }
      if (file.size > MAX_IMAGE_BYTES) { form.error = t("desk.inbox.too_big", {mb: MAX_IMAGE_BYTES / 1048576}); continue; }
      form.images.push({file, url: URL.createObjectURL(file)});
    }
    draw(true);
  }

  function encode(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
      reader.onerror = () => reject(new Error(t("desk.inbox.unreadable")));
      reader.readAsDataURL(file);
    });
  }

  function saveResults(env) {
    form.busy = true; form.error = "";
    draw(true);
    Promise.all(form.images.map((item) => encode(item.file).then((data) => ({data}))))
      .then((images) => SERVE.post("/api/inbox", {task: desk.name, env, text: form.text, ran: form.ran, images}))
      .then((data) => {
        form.images.forEach((item) => URL.revokeObjectURL(item.url));
        Object.assign(form, {text: "", ran: "", images: [], busy: false, gave: data.result});
      }, (error) => { form.busy = false; form.error = error.message; })
      .then(() => draw(true));
  }

  function resultForm() {
    const handed = desk.handoff || {};
    const env = form.env || handed.env || "";
    const field = (label, node) => h("label", {class: "field"}, h("span", {class: "sub"}, label), node);
    const text = h("textarea", {rows: 6, placeholder: t("desk.inbox.text.ph"), disabled: form.busy ? "" : null}, form.text);
    text.addEventListener("input", () => { form.text = text.value; });
    text.addEventListener("paste", (event) => {  // a screenshot pasted into the box becomes a picture; pasted text stays text
      const files = [...(event.clipboardData ? event.clipboardData.files : [])].filter((file) => /^image\//.test(file.type));
      if (files.length) { event.preventDefault(); addImages(files); }
    });
    const ran = h("textarea", {rows: 3, placeholder: t("desk.inbox.ran.ph"), disabled: form.busy ? "" : null}, form.ran);
    ran.addEventListener("input", () => { form.ran = ran.value; });
    const where = h("input", {type: "text", value: env, maxlength: 12, class: "env-input"});
    where.addEventListener("input", () => { form.env = where.value; });
    const pick = h("input", {type: "file", accept: "image/png,image/jpeg,image/gif,image/webp", multiple: "", style: "display:none"});
    pick.addEventListener("change", () => addImages([...pick.files]));
    const chooser = h("button", {type: "button", class: "act"}, t("desk.inbox.pick"));
    chooser.addEventListener("click", () => pick.click());
    const save = h("button", {type: "button", class: "act hot", disabled: form.busy ? "" : null}, form.busy ? t("desk.inbox.saving") : t("desk.inbox.save"));
    save.addEventListener("click", () => saveResults(where.value.trim()));
    const thumbs = h("div", {class: "thumbs"}, form.images.map((item, index) => {
      const remove = h("button", {type: "button", class: "act", title: t("desk.inbox.remove")}, "×");
      remove.addEventListener("click", () => { URL.revokeObjectURL(item.url); form.images.splice(index, 1); draw(true); });
      return h("span", {class: "thumb"}, h("img", {src: item.url, alt: ""}), remove);
    }));
    return h("section", {class: "inbox"}, h("h3", null, t("desk.inbox.title")), h("p", {class: "hint"}, t("desk.inbox.hint")),
      form.gave ? h("div", {class: "inbox-done"}, h("p", {class: "hint"}, t("desk.inbox.done", {folder: form.gave.folder})), promptLine(form.gave.message)) : null,
      field(t("desk.inbox.env"), where), field(t("desk.inbox.text"), text), field(t("desk.inbox.ran"), ran),
      h("div", {class: "inbox-pictures"}, chooser, pick, thumbs),
      form.error ? h("p", {class: "hint bad"}, form.error) : null, h("div", {class: "inbox-save"}, save));
  }

  // A message the person sends to the agent in VS Code: one click copies it.
  function promptLine(text) {
    const button = h("button", {type: "button", class: "act", "data-label": t("desk.go.copy")}, t("desk.go.copy"));
    button.addEventListener("click", () => copyCommand(button, text));
    return h("div", {class: "prompt-line"}, h("code", null, text), button);
  }

  function actions() {
    if (desk.status !== "open") return h("section", {class: "card actions quiet"}, h("p", {class: "sub"}, t("desk.actions.closed")));
    const optional = ["pause", "resume", "autorun on", "close"];  // the person may do these any time; the rest is what the task waits for
    const items = desk.actions.filter((item) => !optional.includes(item.action));
    const rest = desk.actions.filter((item) => optional.includes(item.action));
    const row = {name: desk.name, waiting: desk.waiting, state: desk.state, todo_left: desk.todo_left, req_unconfirmed: desk.req_unconfirmed,
      result_missing: FILES[desk.kind] && ["design", "rca"].includes(desk.kind) && !doc(FILES[desk.kind]) ? FILES[desk.kind] : ""};  // a design or an RCA task without its result file: the close dialog warns
    const hint = (item) => t("desk.hint." + item.action.replace(" ", "-"));
    const entry = (item) => h("div", {class: "action"}, actionButton(row, item, "big"), h("p", {class: "hint"}, hint(item)));
    const line = (item) => h("div", {class: "action-line"}, actionButton(row, item), h("span", {class: "hint"}, hint(item)));
    const idle = items.length ? null : quiet();
    return h("section", {class: "card actions"},
      h("h2", null, idle ? idle.title : t("desk.actions.title")),
      desk.waited_s !== null && (items.length || desk.waiting) ? h("p", {class: "sub"}, t("desk.waited", {time: clock(desk.waited_s)})) : null,
      desk.req_changed ? h("p", {class: "hint bad"}, t("desk.req.changed")) : null,
      desk.req_unconfirmed && desk.req_placeholders ? h("p", {class: "hint bad"}, t("desk.req.placeholders", {n: desk.req_placeholders})) : null,
      desk.test && desk.test.reopen ? h("p", {class: "hint bad"}, t("desk.test.reopen", {dev: desk.test.reopen, envs: desk.test.failed.join(", ")})) : null,
      desk.state === "working" && served() ? h("p", {class: "hint"}, t("desk.busy.note")) : null,
      desk.state === "waiting" && !desk.held ? h("p", {class: "hint"}, t("desk.unheld.note")) : null,
      idle ? [h("p", {class: "hint"}, idle.hint), idle.prompt ? promptLine(idle.prompt) : null] : h("div", {class: "action-list"}, items.map(entry)),
      served() && ["tests", "run"].includes(desk.waiting_why) ? resultForm() : null,
      rest.length ? h("div", {class: "action-more"}, h("div", {class: "sub label"}, t("desk.actions.more")), rest.map(line)) : null,
      typeof SERVE === "undefined" ? h("p", {class: "sub"}, t("board.copy.hint")) : SERVE.banner());
  }

  // The stages of the task by its kind (taskstages.py) and the reviewer's checks. The step that is now moves: orange when the
  // task waits for the person, blue while the agent is at work (and the page is live), still otherwise.
  function ribbon() {
    const s = desk.stages;
    if (!s || desk.status === "new") return null;
    const live = served();
    const waits = Boolean(desk.waiting) && desk.status === "open" && !desk.paused_since;
    const works = Boolean(live) && desk.active && !waits && desk.status === "open";
    const again = s.steps.some((step) => step.id === "plan" && step.state === "now") && desk.history.some((event) => event.what === "approve-plan");
    const parts = [];
    s.steps.forEach((step, index) => {
      const label = step.label || t("stage." + step.id);
      const mark = step.state === "done" ? "\u2713" : step.flag ? "!" : String(index + 1);
      const here = step.state === "now";
      const note = here ? (step.flag === "partial" ? t("stage.partial") : step.flag === "failed" ? t("stage.failed")
        : waits ? (desk.waiting_why === "tests" && s.handoff && s.handoff === step.label ? t("stage.tests") : t("stage.you")) : works ? t("stage.work") : "") : "";
      parts.push(h("div", {class: "rb-step" + (step.state === "done" ? " is-done" : here ? " is-now" + (step.flag ? " is-bad" : waits ? " is-you" : works ? " is-work" : "") : "")},
        h("div", {class: "rb-node"}, mark), h("div", {class: "rb-name"}, label), h("div", {class: "rb-note"}, note)));
      if (index < s.steps.length - 1) parts.push(h("div", {class: "rb-link" + (step.state === "done" ? " is-done" : "") + (here && works && !waits ? " is-flow" : "")}));
    });
    return h("section", {class: "card"},
      s.round > 1 || again ? h("div", {class: "rb-round sub"}, s.round > 1 ? tag(t("stage.round", {round: s.round})) : null, again ? " " + t("stage.again") : null) : null,
      h("div", {class: "rb-ribbon"}, parts), s.review ? lane(s.review, works) : null);
  }

  // Under the ribbon: the reviewer and one mark for each check asked for: not yet, running, passed, failed.
  function lane(r, works) {
    const marks = r.states.map((state) => h("span", {class: "rb-check " + state}, state === "pass" ? "\u2713" : state === "fail" ? "\u00d7" : ""));
    return h("div", {class: "rb-lane"}, h("span", {class: "rb-who"}, h("span", {class: "rb-orb"}, "R"), r.n ? t("stage.reviewer", {n: r.n}) : t("stage.reviewer.off")),
      marks, r.waived ? tag(t("desk.review.waived"), "hot") : null, r.stamp ? h("span", {class: "rb-stamp"}, t("stage.reviewed", {n: r.n})) : null);
  }

  function nav() {
    const label = (tab) => {
      if (tab === "req" && desk.req_unconfirmed) return t("desk.tab.req") + " !";  // waits for the person's confirmation
      if (tab === "todo" && desk.todo.total) return t("desk.tab.todo") + " " + desk.todo.done + "/" + desk.todo.total;
      if (tab === "changes" && desk.changes.files.length) return t("desk.tab.changes") + " " + desk.changes.files.length + (desk.commit && !desk.commit.written ? " !" : "");
      if (tab === "test") return t("desk.tab.test") + " " + desk.test.passed + "/" + desk.test.total;
      if (tab === "review") return t("desk.tab.review") + (desk.review.n ? " " + desk.review.passes + "/" + desk.review.n : " " + desk.review.rounds.length);
      if (tab === "history") return t("desk.tab.history") + " " + desk.history.length;
      if (tab === "trace") return t("desk.tab.trace") + " " + desk.trace.entries.length + (desk.trace.cut ? "+" : "");
      if (tab === "docs") return t("desk.tab.docs") + " " + extra().length;
      if (tab === "files") return t("desk.tab.files") + " " + desk.files.length;
      if (tab === "intake") { const reads = desk.intake.files.filter((item) => !item.original && !item.report && !item.path.startsWith("media/")).length; return t("desk.tab.intake") + (reads ? " " + reads : ""); }  // the same set as "What the agent reads"
      return t("desk.tab." + tab);
    };
    return h("nav", {class: "tabs"}, tabs.filter((tab) => tab === "docs" ? extra().length > 0 : ownTab(tab)).map((tab) => {
      const button = h("button", {type: "button", class: "tab" + (tab === current ? " on" : "")}, label(tab));
      button.addEventListener("click", () => { current = tab; history.replaceState(null, "", hashOf(tab)); draw(false); });
      return button;
    }));
  }

  function review() {
    const r = desk.review;
    const parts = [h("p", {class: "hint top"}, t("desk.review.hint"))];
    parts.push(h("div", {class: "review-sum"},
      r.n ? t("desk.review.sum", {n: r.n, passes: r.passes, used: r.used, limit: r.limit}) : t("desk.review.off"),
      r.waived ? [" ", tag(t("desk.review.waived"), "hot")] : null,
      r.pending ? [" ", tag(t("desk.review.running", {number: r.pending}), "good run")] : null));
    if (!r.rounds.length) parts.push(h("div", {class: "empty-state"}, h("b", null, t("desk.review.none"))));
    for (const item of r.rounds) {
      const verdict = item.verdict ? tag(item.verdict, item.verdict === "PASS" ? "good" : item.verdict === "FAIL" ? "bad" : "") : tag(t("desk.review.waiting"));
      placeLinks = true;
      const answer = item.answer ? blocks(item.answer.blocks) : h("p", {class: "sub"}, item.verdict ? t("desk.review.noanswer") : t("desk.review.pending"));
      placeLinks = false;
      parts.push(h("section", {class: "round " + (item.verdict === "FAIL" ? "fail" : item.verdict === "PASS" ? "pass" : "")},
        h("div", {class: "round-head"}, h("strong", null, "round-" + String(item.number).padStart(3, "0")), " ", verdict, " ",
          item.dismissed ? [tag(t("desk.review.dismissed"), "hot"), " "] : item.invalid ? [tag(t(item.refunded ? "desk.review.given_back" : "desk.review.invalid"), "hot"), " "] : null,
          h("span", {class: "sub"}, when(item.started_at, 5, 16) + " · " + (item.current ? t("desk.review.current") : t("desk.review.earlier")))),
        (h("article", {class: "md"}, answer, item.answer && item.answer.cut ? h("p", {class: "sub"}, t("desk.cut")) : null)),
        (item.dropped || []).length ? h("div", {class: "dropped"}, h("p", {class: "sub"}, t("desk.review.dropped")),
          h("ul", null, item.dropped.map((found) => h("li", null, h("b", null, found.why), " ", found.text)))) : null,
        item.package ? h("details", null, h("summary", {class: "sub"}, t("desk.review.given")), h("article", {class: "md"}, blocks(item.package.blocks))) : null));
    }
    return parts;
  }

  // TEST/defects.md: the open defects first, each with its text; the fixed ones folded. The status is what `task defects sync` wrote.
  function defects(d) {
    const one = (item, cls) => h("section", {class: "round " + cls},
      h("div", {class: "round-head"}, h("strong", null, item.id), " ", tag(item.env, item.status === "fixed" ? "good" : "bad"), " ", item.title,
        item.stale ? [" ", tag(t("desk.test.defects.stale", {env: item.env}), "hot long")] : null),
      item.doc ? h("article", {class: "md"}, blocks(item.doc.blocks), item.doc.cut ? h("p", {class: "sub"}, t("desk.cut")) : null) : null);
    const parts = d.intro ? [h("article", {class: "md"}, blocks(d.intro.blocks))] : [];
    parts.push(h("h3", null, t("desk.test.defects.open") + " " + d.open.length));
    if (!d.open.length) parts.push(h("p", {class: "sub"}, t("desk.test.defects.none")));
    parts.push(...d.open.map((item) => one(item, "fail")));
    if (d.fixed.length) parts.push(h("details", null, h("summary", {class: "sub"}, t("desk.test.defects.fixed") + " " + d.fixed.length), ...d.fixed.map((item) => one(item, "pass"))));
    for (const part of d.other) parts.push(h("h4", null, part.title), part.doc ? h("article", {class: "md"}, blocks(part.doc.blocks)) : null);
    if (d.odd.length) parts.push(h("p", {class: "hint bad"}, t("desk.test.defects.odd") + " " + d.odd.join(" · ")));
    return parts;
  }

  // The commit message of the write-back: what the agent wrote, with the contributor line the harness adds, to copy into the commit.
  const COMMIT_WARNINGS = {empty: "desk.commit.warn.empty", subject_long: "desk.commit.warn.subject_long", no_blank: "desk.commit.warn.no_blank"};
  function commit() {
    const x = desk.commit;
    const parts = [h("p", {class: "hint top"}, t("desk.commit.hint"))];
    if (!x.messages.length) return [...parts, h("div", {class: "empty-state"}, h("b", null, t("desk.commit.none")), h("p", {class: "sub"}, x.file))];
    const copier = (label, text) => {
      const button = h("button", {type: "button", class: "act", "data-label": label}, label);
      button.addEventListener("click", () => copyCommand(button, text));
      return button;
    };
    for (const item of x.messages) {
      // The whole commit as commands to paste (M37-10): the message is never pasted into `git commit -m "..."`, where a backtick is run by the shell.
      const shells = item.commands ? [["posix", "desk.commit.shell.posix"], ["powershell", "desk.commit.shell.powershell"]].map(([key, label]) =>
        h("div", {class: "shell"}, h("div", {class: "round-head"}, h("strong", null, t(label)), " ", copier(t("desk.commit.copy_commands"), item.commands[key])),
          h("pre", {class: "commit"}, item.commands[key]))) : null;
      parts.push(h("section", {class: "round"},
        h("div", {class: "round-head"}, h("strong", null, t("desk.commit.repo", {repo: item.repo})), " ", copier(t("desk.commit.copy"), item.text),
          item.warnings.map((code) => [" ", tag(t(COMMIT_WARNINGS[code]), "hot")])),
        h("pre", {class: "commit"}, item.text),
        shells ? [h("p", {class: "sub"}, t("desk.commit.commands", {branch: item.branch})), shells] : null));
    }
    parts.push(h("p", {class: "sub"}, x.coauthor ? t("desk.commit.author", {author: x.coauthor}) : t("desk.commit.noauthor")));
    return parts;
  }

  // The Test tab of a test task: the guide the agent wrote for the person, one small tab for each environment (its part of the guide, then its results and
  // verdict), an overview before them and the defects after them. The tab that is open is kept while the page redraws.
  let testSub = "";
  const plain = (spans) => spans.map((span) => span.v || (span.c ? plain(span.c) : "")).join("").trim();

  // The guide cut at the headings that name an environment: what comes before the first one, and each environment's part (its heading left out: the tab says it).
  function guideParts(guide, envs) {
    const names = envs.map((env) => env.name.toUpperCase());
    const parts = {intro: [], by: {}};
    let at = null;
    for (const block of guide.blocks) {
      const name = block.t === "h" && block.level === 2 ? plain(block.spans).toUpperCase() : "";
      if (names.includes(name)) { at = name; parts.by[at] = []; continue; }
      (at ? parts.by[at] : parts.intro).push(block);
    }
    return parts;
  }

  function testing() {
    const x = desk.test;
    const parts = [h("p", {class: "hint top"}, t("desk.test.hint"))];
    const split = x.guide ? guideParts(x.guide, x.envs) : null;
    const cut = x.guide && x.guide.cut ? h("p", {class: "sub"}, t("desk.cut")) : null;
    const mark = (env) => env.state === "done" ? "✓" : env.state === "failed" ? "✗" : env.waits ? "●" : "○";
    const open = x.envs.find((env) => env.state === "now" || env.state === "failed") || x.envs[0];
    const ids = ["intro", ...x.envs.map((env) => env.name), ...(x.defects ? ["defects"] : [])];
    if (!ids.includes(testSub)) testSub = open ? open.name : "intro";
    const label = (id) => id === "intro" ? t("desk.test.sub.intro") : id === "defects" ? t("desk.test.sub.defects", {n: x.defects.open.length}) : (() => {
      const env = x.envs.find((item) => item.name === id);
      return mark(env) + " " + env.name;
    })();
    const klass = (id) => {
      const env = x.envs.find((item) => item.name === id);
      return "subtab" + (id === testSub ? " on" : "") + (env ? " " + (env.state === "done" ? "good" : env.state === "failed" ? "bad" : env.waits ? "hot" : "") : "");
    };
    parts.push(h("nav", {class: "subtabs"}, ids.map((id) => {
      const button = h("button", {type: "button", class: klass(id)}, label(id));
      button.addEventListener("click", () => { testSub = id; draw(true); });
      return button;
    })));
    const guideOf = (blocksList) => blocksList && blocksList.length ? h("article", {class: "md"}, blocks(blocksList), cut) : null;
    if (testSub === "intro") {
      parts.push(x.guide ? guideOf(split.by && Object.keys(split.by).length ? split.intro : x.guide.blocks)
        : h("div", {class: "empty-state"}, h("b", null, t("desk.test.noguide"))));
      if (x.guide && !Object.keys(split.by).length) {  // a guide with no heading that names an environment: it is shown whole, and every environment's results follow
        parts.push(h("h3", null, t("desk.test.results")));
        x.envs.forEach((env) => parts.push(envResults(env)));
      }
    } else if (testSub === "defects") {
      parts.push(...defects(x.defects));
    } else {
      const env = x.envs.find((item) => item.name === testSub);
      const own = split && split.by[env.name.toUpperCase()];
      parts.push(own ? guideOf(own) : null, h("h3", null, t("desk.test.results")), envResults(env));
    }
    return parts;
  }

  // A results file holds one `## Run N` after another. With two or more, each run is a small tab of its own and the newest is open (the verdict of each run is
  // its last `Verdict for` line; `verdicts` has them in order, "" when not known).
  const runPick = {};
  function runTabs(key, list, verdicts, intro) {
    const parts = {intro: [], runs: []};
    for (const block of list) {
      const found = block.t === "h" && block.level === 2 ? /^Run (\d+)$/i.exec(plain(block.spans)) : null;
      if (found) parts.runs.push({n: Number(found[1]), blocks: []});
      else (parts.runs.length ? parts.runs[parts.runs.length - 1].blocks : parts.intro).push(block);
    }
    if (parts.runs.length < 2) return null;
    if (!parts.runs.some((run) => run.n === runPick[key])) runPick[key] = parts.runs[parts.runs.length - 1].n;
    const shown = parts.runs.find((run) => run.n === runPick[key]);
    const nav = h("nav", {class: "subtabs small"}, parts.runs.map((run, index) => {
      const verdict = verdicts && verdicts.length === parts.runs.length ? verdicts[index] : "";
      const button = h("button", {type: "button", class: "subtab" + (run.n === runPick[key] ? " on" : "") + (verdict === "PASS" ? " good" : verdict === "FAIL" ? " bad" : verdict ? " hot" : "")},
        t("desk.test.run", {n: run.n}) + (verdict ? " · " + verdict : ""));
      button.addEventListener("click", () => { runPick[key] = run.n; draw(true); });
      return button;
    }));
    return [intro && parts.intro.length ? blocks(parts.intro) : null, nav, blocks(shown.blocks)];
  }

  // The evidence pictures of an environment that the results text does not show itself: small, each linking to the full picture. A saved copy has no server: nothing to show.
  function evidenceThumbs(env) {
    if (!served() || !(env.pictures || []).length) return null;
    const shown = new Set();
    const walk = (node) => {
      if (Array.isArray(node)) node.forEach(walk);
      else if (node && typeof node === "object") { if (node.t === "img") shown.add(node.src); Object.values(node).forEach(walk); }
    };
    walk(env.results ? env.results.blocks : []);
    const rest = env.pictures.filter((path) => !shown.has(path));
    if (!rest.length) return null;
    return h("div", {class: "evidence"}, rest.map((path) => {
      const src = "/file/" + encodeURIComponent(desk.name) + "/" + path.split("/").map(encodeURIComponent).join("/");
      return h("a", {href: src, target: "_blank", rel: "noopener noreferrer", title: path.split("/").pop()}, h("img", {src, alt: path.split("/").pop(), class: "md-thumb"}));
    }));
  }

  function envResults(env) {
    const verdict = env.verdict ? tag(env.verdict, env.verdict === "PASS" ? "good" : env.verdict === "FAIL" ? "bad" : "hot") : tag(env.waits ? t("desk.test.waits") : t("desk.test.noresult"), env.waits ? "hot" : "");
    const body = env.results ? h("article", {class: "md"}, runTabs("env:" + env.name, env.results.blocks, env.runs, false) || blocks(env.results.blocks), env.results.cut ? h("p", {class: "sub"}, t("desk.cut")) : null, evidenceThumbs(env))
      : h("p", {class: "sub"}, env.waits ? t("desk.test.waiting", {env: env.name}) : t("desk.test.noresult"));
    return h("section", {class: "round " + (env.state === "failed" ? "fail" : env.state === "done" ? "pass" : "")},
      h("div", {class: "round-head"}, h("strong", null, env.name), " ", verdict, env.file ? [" ", h("span", {class: "sub"}, "TEST/" + env.file)] : null,
        env.ignored.length ? [" ", tag(t("desk.test.ignored", {files: env.ignored.join(", ")}), "hot")] : null), body);
  }

  // The Files tab: what is in REQ/, REF/, DEV/ and RUNS/ (sub-folders too). The list is in the page; a file comes when it is opened (a saved copy has the small ones in it).
  let fileOpen = "";
  const markText = () => ({create: t("desk.files.mark.create"), modify: t("desk.files.mark.modify"), delete: t("desk.files.mark.delete"), unchanged: t("desk.files.mark.unchanged")});  // written out, so each message key is found by a search
  const folded = new Set();  // folders folded in the tree (their full path); kept while the page is open
  const fileCache = {};
  const ROOT_HINT = {REQ: "desk.files.root.req", REF: "desk.files.root.ref", INBOX: "desk.files.root.inbox", DEV: "desk.files.root.dev", RUNS: "desk.files.root.runs"};
  const rootHint = (root) => ROOT_HINT[root.toUpperCase()] || (/^DEV_R\d+$/i.test(root) ? ROOT_HINT.DEV : "desk.files.hint");  // DEV_r<n>: the files an earlier round wrote back
  const size = (bytes) => bytes < 1024 ? bytes + " B" : bytes < 1048576 ? Math.round(bytes / 1024) + " KB" : (bytes / 1048576).toFixed(1) + " MB";

  // An original kept by Intake: the files made from it (they open here) and the original itself to save.
  function originalExtras(item) {
    if (!item.path.startsWith("REQ/originals/")) return null;
    const made = (item.made || []).map((path) => {
      const a = h("a", {href: "#files", title: path}, path.slice(4));
      a.addEventListener("click", (event) => { event.preventDefault(); fileOpen = path; draw(false); });
      return a;
    });
    const href = "/download/" + encodeURIComponent(desk.name) + "/" + item.path.split("/").map(encodeURIComponent).join("/");
    return h("p", {class: "sub"}, made.length ? [t("desk.files.made") + " ", made.map((a, index) => [index ? ", " : "", a]), " · "] : null,
      served() ? h("a", {href, download: ""}, t("desk.files.download")) : null);
  }

  function fileView(item) {
    if (item.kind === "image") {
      return picture({src: item.path, alt: item.path.split("/").pop(), data: item.data || ""});
    }
    const found = fileCache[item.path] || item.doc;
    if (!found && !["markdown", "text"].includes(item.kind)) return [h("p", {class: "sub"}, t("desk.files.other", {size: size(item.size)})), originalExtras(item)];  // never asked for: it was "Loading…" for good
    if (!found && !served()) return h("p", {class: "sub"}, t("desk.files.saved"));  // a saved copy took in only the small files
    if (!found) return h("p", {class: "sub"}, fileCache[item.path] === null ? t("desk.files.failed") : t("desk.files.loading"));
    if (found.kind === "markdown") return h("article", {class: "md"}, runTabs("file:" + item.path, found.blocks, null, true) || blocks(found.blocks), found.cut ? h("p", {class: "sub"}, t("desk.cut")) : null);
    if (found.kind === "text") return [codeBlock(found.text, Highlight.fileLanguage(item.path)), found.cut ? h("p", {class: "sub"}, t("desk.cut")) : null];
    return h("p", {class: "sub"}, t("desk.files.other", {size: size(found.size)}));
  }

  function fileLoad(item) {
    if (item.doc || fileCache[item.path] || !served() || !["markdown", "text"].includes(item.kind)) return;
    fileCache[item.path] = undefined;
    SERVE.post("/api/file", {task: desk.name, path: item.path}).then((data) => { fileCache[item.path] = data.file; draw(true); }, () => { fileCache[item.path] = null; draw(true); });
  }

  function filesTab() {
    const items = desk.files;
    if (!items.some((item) => item.path === fileOpen)) fileOpen = items[0].path;
    const open = items.find((item) => item.path === fileOpen);
    fileLoad(open);
    const list = [];
    const marks = new Map();  // DEV/ file -> "create" | "modify" | "delete" | "unchanged", from the Changes tab
    for (const item of desk.changes.files) marks.set("DEV/" + item.path, item.action);
    for (const path of desk.changes.unchanged_files || []) marks.set("DEV/" + path, "unchanged");
    const ghosts = [...marks].filter(([path, action]) => action === "delete" && !items.some((item) => item.path === path)).map(([path]) => ({path, size: 0, ghost: true}));
    const roots = new Map();  // root folder -> {dirs: name -> node, files: [item]}
    for (const item of [...items, ...ghosts]) {
      const parts = item.path.split("/");
      let node = roots.get(parts[0]);
      if (!node) roots.set(parts[0], node = {dirs: new Map(), files: []});
      for (const name of parts.slice(1, -1)) {
        if (!node.dirs.has(name)) node.dirs.set(name, {dirs: new Map(), files: []});
        node = node.dirs.get(name);
      }
      node.files.push(item);
    }
    // Like the VS Code explorer: folders first, a folder that holds only one folder is joined with it (d/e/f/), one file per line.
    const walk = (node, depth, parent) => {
      for (const [name, child] of node.dirs) {
        let label = name, last = child;
        while (!last.files.length && last.dirs.size === 1) { const [next, inner] = last.dirs.entries().next().value; label += "/" + next; last = inner; }
        const id = parent + "/" + label, shut = folded.has(id);
        const row = h("button", {type: "button", class: "files-dir", "aria-expanded": shut ? "false" : "true", style: "padding-left:" + depth * 14 + "px"}, (shut ? "▸ " : "▾ ") + label + "/");
        row.addEventListener("click", () => { if (folded.has(id)) folded.delete(id); else folded.add(id); draw(true); });
        list.push(row);
        if (!shut) walk(last, depth + 1, id);
      }
      for (const item of node.files) {
        const mark = marks.get(item.path);
        const name = h("span", null, item.path.split("/").pop());
        const tail = mark ? h("span", {class: "tag fmark " + mark}, markText()[mark]) : h("span", {class: "sub"}, " " + size(item.size));
        if (item.ghost) { list.push(h("div", {class: "file ghost", title: item.path, style: "padding-left:" + depth * 14 + "px"}, name, " ", tail)); continue; }
        const button = h("button", {type: "button", class: "file" + (item.path === fileOpen ? " on" : "") + (mark === "unchanged" ? " plain" : ""), title: item.path, style: "padding-left:" + depth * 14 + "px"}, name, " ", tail);
        button.addEventListener("click", () => { fileOpen = item.path; draw(true); });
        list.push(button);
      }
    };
    for (const [root, node] of roots) {
      list.push(h("div", {class: "files-root"}, h("strong", null, root + "/"), h("span", {class: "sub"}, " " + t(rootHint(root)))));
      walk(node, 1, root);
    }
    return [h("p", {class: "hint top"}, t("desk.files.hint")),
      h("div", {class: "files"}, h("nav", {class: "files-list", "data-keep": "files-list"}, list),
        h("div", {class: "files-view"}, h("div", {class: "round-head"}, h("strong", null, open.path), " ", h("span", {class: "sub"}, size(open.size))), fileView(open)))];
  }

  // The Intake tab (1.5.45): the documents of a requirement go into REQ/ here (a program turns Word and Excel into Markdown and CSV: no AI), are trimmed in a text box, and
  // can be put back as converted. What is typed is kept in `intake`, so a redraw of the page does not lose it.
  // A heading, a list, a fence or a quote at the start of a line, and no tab (cells copied out of a sheet are tab-separated).
  const looksLikeMarkdown = (text) => !text.includes("\t") && /^(#{1,6} |[-*+] |\d+\. |```|> )/m.test(text);
  // A table has tabs (from Excel), or two lines or more with the same number of commas. Anything else is text, not a table of one column.
  const looksLikeTable = (text) => {
    if (text.includes("\t")) return true;
    const lines = text.split(/\r?\n/).filter((line) => line.trim());
    const commas = (line) => (line.match(/,/g) || []).length;
    return lines.length > 1 && commas(lines[0]) > 0 && lines.every((line) => commas(line) === commas(lines[0]));
  };
  const guessKind = (text) => (looksLikeMarkdown(text) ? "doc" : looksLikeTable(text) ? "csv" : "txt");
  const intake = {busy: false, error: "", done: [], editing: null, name: "", kind: "csv", kindChosen: false, text: "", hidden: false, domains: null, open: new Set(), picked: new Set()};
  const UPLOAD_TYPES = ".docx,.docm,.xlsx,.xlsm,.xls,.pdf,.csv,.tsv,.txt,.md,.json,.sql,.png,.jpg,.jpeg,.gif,.webp";

  function intakeCall(action, body) {
    return SERVE.post("/api/intake", {task: desk.name, action, ...(body || {})}).then((data) => data.result);
  }

  function intakeRefresh() {
    return SERVE.post("/api/desk", {task: desk.name}).then((data) => setDesk(data.desk), () => {});
  }

  function fileBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
      reader.onerror = () => reject(new Error(t("desk.inbox.unreadable")));
      reader.readAsDataURL(file);
    });
  }

  function intakeAdd(list) {
    const files = [...list];
    if (!files.length || intake.busy) return;
    const limit = desk.intake.limit_mb * 1048576;
    intake.busy = true; intake.error = "";
    draw(true);
    files.reduce((chain, file) => chain.then(() => {
      if (file.size > limit) { intake.error = t("desk.intake.big", {name: file.name, mb: desk.intake.limit_mb}); return null; }
      return fileBase64(file).then((data) => intakeCall("upload", {name: file.name, data, include_hidden: intake.hidden}))
        .then((result) => { intake.done.unshift({name: file.name, result}); }, (error) => { intake.error = file.name + ": " + error.message; });
    }), Promise.resolve()).then(() => intakeRefresh()).then(() => { intake.busy = false; draw(true); });
  }

  // the editor sits below the whole list: bring it into view
  function intakeShow() {
    const editor = document.querySelector("section.editing");
    if (editor && editor.scrollIntoView) editor.scrollIntoView({block: "start", behavior: "smooth"});
    // the redraws that follow (the refreshed list, the end of "busy") put the old scroll back: draw() brings the editor into view again until this ends
    intake.reveal = true;
    clearTimeout(intakeShow.timer);
    intakeShow.timer = setTimeout(() => { intake.reveal = false; }, 1500);
  }

  function intakeOpen(path, item) {
    intake.error = "";
    if (item && !item.editable) {  // an original, a picture, a file that is not text: a card to look at it (a picture is shown) and to delete it
      intake.editing = {path, readonly: true, size: item.size, picture: /\.(png|jpe?g|gif|webp)$/i.test(path)};
      draw(true); intakeShow();
      return;
    }
    intakeCall("read", {path}).then((found) => {
      const edit = {path, text: found.text, saved: found.text, pristine: found.pristine, size: found.size, view: "text"};
      if (/\.csv$/i.test(path)) csvLoad(edit, true);
      intake.editing = edit; draw(true); intakeShow();
    },
      (error) => { intake.error = error.message; draw(true); });
  }

  function intakeSave() {
    const edit = intake.editing;
    intake.busy = true; draw(true);
    intakeCall("save", {path: edit.path, text: edit.text}).then(() => { edit.saved = edit.text; intake.error = ""; }, (error) => { intake.error = error.message; })
      .then(() => intakeRefresh()).then(() => { intake.busy = false; draw(true); });
  }

  function intakeAct(action, path, after, more) {
    intake.busy = true; intake.error = ""; draw(true);
    intakeCall(action, {path, ...(more || {})}).then((found) => { if (after) after(found); }, (error) => { intake.error = error.message; })
      .then(() => intakeRefresh()).then(() => { intake.busy = false; draw(true); });
  }

  // A CSV file as rows of cells, the way the converter writes it: commas, a cell in quotes when it holds a comma, a quote ("" inside) or a line break. Blank lines are dropped.
  function parseCsv(text) {
    const rows = [];
    let row = [], cell = "", quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted) {
        if (c !== '"') cell += c;
        else if (text[i + 1] === '"') { cell += '"'; i++; }
        else quoted = false;
      } else if (c === '"' && cell === "") quoted = true;
      else if (c === ",") { row.push(cell); cell = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(cell);
        if (row.length > 1 || row[0] !== "") rows.push(row);
        row = []; cell = "";
      } else cell += c;
    }
    if (cell !== "" || row.length) { row.push(cell); if (row.length > 1 || row[0] !== "") rows.push(row); }
    return rows;
  }

  function toCsv(rows) {
    return rows.map((row) => row.map((cell) => (/[",\n\r]/.test(cell) ? '"' + cell.replace(/"/g, '""') + '"' : cell)).join(",")).join("\n") + "\n";
  }

  // The table view of a CSV file: the rows the person picks are taken out, or the only ones kept. The text follows, and is written only by Save.
  const CSV_PAGE = 200;
  function csvLoad(edit, first) {
    edit.rows = parseCsv(edit.text);
    edit.picked = new Set(); edit.q = edit.q || ""; edit.shown = CSV_PAGE;
    if (first) edit.view = edit.rows.length > 1 && edit.rows.some((row) => row.length > 1) ? "table" : "text";  // one column or one line: it may not be a comma file; the text is shown
  }

  function csvTable(edit) {
    const matching = () => {
      const q = edit.q.trim().toLowerCase(), out = [];
      for (let i = 1; i < edit.rows.length; i++) if (!q || edit.rows[i].some((cell) => cell.toLowerCase().includes(q))) out.push(i);
      return out;
    };
    const tools = (label, call, cls) => {
      const b = h("button", {type: "button", class: "act " + (cls || "")}, label);
      b.addEventListener("click", call);
      return b;
    };
    const apply = (keep) => {
      edit.rows = edit.rows.filter((row, i) => i === 0 || edit.picked.has(i) === keep);
      edit.text = toCsv(edit.rows);
      edit.picked = new Set(); edit.q = ""; edit.shown = CSV_PAGE;  // the search ends too: what is left is what the person looks at next
      draw(true);
    };
    const search = h("input", {type: "text", class: "env-input", value: edit.q, placeholder: t("desk.intake.csv.search")});
    const info = h("span", {class: "sub"});
    const del = tools("", () => apply(false), "danger");
    const keep = tools("", () => apply(true));
    const body = h("tbody");
    const more = tools("", () => { edit.shown += CSV_PAGE; refresh(); });
    const refresh = () => {
      const hits = matching();
      info.textContent = t("desk.intake.csv.info", {rows: edit.rows.length - 1, match: hits.length, drawn: Math.min(hits.length, edit.shown), picked: edit.picked.size});
      del.textContent = t("desk.intake.csv.delete", {n: edit.picked.size});
      keep.textContent = t("desk.intake.csv.keep", {n: edit.picked.size});
      del.disabled = keep.disabled = !edit.picked.size;
      const cut = hits.slice(0, edit.shown);
      body.replaceChildren(...cut.map((i) => {
        const box = h("input", {type: "checkbox", checked: edit.picked.has(i) ? "" : null});
        box.addEventListener("change", () => { if (box.checked) edit.picked.add(i); else edit.picked.delete(i); refresh(); });
        return h("tr", {class: edit.picked.has(i) ? "picked" : null}, h("td", {class: "csv-pick"}, box, " ", h("span", {class: "sub"}, i)),
          edit.rows[i].map((cell) => h("td", null, h("div", {class: "csv-cell"}, cell))));
      }));
      more.hidden = hits.length <= cut.length;
      more.textContent = t("desk.intake.csv.more", {n: Math.min(CSV_PAGE, hits.length - cut.length)});
    };
    search.addEventListener("input", () => { edit.q = search.value; edit.shown = CSV_PAGE; refresh(); });
    const columns = Math.max(1, ...edit.rows.map((row) => row.length)), first = edit.rows[0] || [];
    const head = h("thead", null, h("tr", null, h("th", null, "#"), Array.from({length: columns}, (_, c) => h("th", null, first[c] || ""))));
    refresh();
    return h("div", {class: "csv"},
      h("div", {class: "csv-tools"}, search,
        tools(t("desk.intake.csv.pickshown"), () => { for (const i of matching()) edit.picked.add(i); refresh(); }),
        tools(t("desk.intake.csv.clear"), () => { edit.picked.clear(); refresh(); }), del, keep, info),
      h("div", {class: "csv-scroll"}, h("table", {class: "csv-table"}, head, body)),
      h("div", {class: "inbox-save"}, more),
      h("p", {class: "hint"}, t("desk.intake.csv.note")));
  }

  function intakeEditor() {
    const edit = intake.editing;
    const button = (label, call, cls) => {
      const b = h("button", {type: "button", class: "act " + (cls || ""), disabled: intake.busy ? "" : null}, label);
      b.addEventListener("click", call);
      return b;
    };
    const close = () => { if (edit.readonly || edit.text === edit.saved || window.confirm(t("desk.intake.discard"))) { intake.editing = null; draw(true); } };
    const remove = () => {
      if (window.confirm(t("desk.intake.delete.confirm", {path: edit.path}))) intakeAct("delete", edit.path, () => { intake.editing = null; });
    };
    const rename = () => {
      const now = edit.path.split("/").pop();
      const name = window.prompt(t("desk.intake.rename.ask", {path: edit.path}), now);
      if (name === null || !name.trim() || name.trim() === now) return;
      if (!edit.readonly && edit.text !== edit.saved && !window.confirm(t("desk.intake.discard"))) return;
      intakeAct("rename", edit.path, (found) => {
        for (const card of intake.done) {  // the "recently saved" cards name the file as it was
          const again = (text) => (text === found.from ? found.file : text);
          card.name = again(card.name); card.result.files = card.result.files.map(again); card.result.report = again(card.result.report);
        }
        intake.editing = null; intakeOpen(found.file.replace(/^REQ\//, ""));
      }, {name: name.trim()});
    };
    const head = h("div", {class: "card-head"},
      h("div", {class: "card-title"}, h("strong", null, "REQ/" + edit.path), " ", edit.readonly ? null : edit.text !== edit.saved ? tag(t("desk.intake.unsaved"), "hot") : h("span", {class: "sub"}, t("desk.intake.saved"))),
      h("div", {class: "card-tools"}, h("span", {class: "sub"}, size(edit.size || 0)), edit.path.startsWith("originals/") ? null : button(t("desk.intake.rename"), rename), button(t("desk.intake.delete"), remove, "danger"), button("×", close, "close")));
    if (edit.readonly) {
      const src = edit.picture ? "/file/" + encodeURIComponent(desk.name) + "/REQ/" + edit.path.split("/").map(encodeURIComponent).join("/") : "";
      return h("section", {class: "round editing"}, head, edit.picture ? h("img", {src, alt: edit.path, class: "md-img"}) : h("p", {class: "sub"}, t("desk.intake.noview")));
    }
    const area = h("textarea", {rows: 22, class: "editor", spellcheck: "false", disabled: intake.busy ? "" : null}, edit.text);
    area.addEventListener("input", () => { edit.text = area.value; });
    const views = edit.rows ? h("div", {class: "inbox-save"}, ...[["table", t("desk.intake.view.table")], ["text", t("desk.intake.view.text")]].map(([view, label]) =>
      button(label, () => { if (edit.view !== view) { edit.view = view; if (view === "table") csvLoad(edit); draw(true); } }, edit.view === view ? "hot" : "")), edit.text !== edit.saved ? button(t("desk.intake.csv.undo"), () => { edit.text = edit.saved; csvLoad(edit); draw(true); }) : null) : null;
    const reset = () => { if (window.confirm(t("desk.intake.reset.confirm"))) intakeAct("reset", edit.path, () => { intake.editing = null; intakeOpen(edit.path); }); };
    return h("section", {class: "round editing"}, head, views, edit.view === "table" ? csvTable(edit) : area,
      h("div", {class: "inbox-save"}, button(t("desk.intake.save"), intakeSave, "hot"), " ", edit.pristine ? button(t("desk.intake.reset"), reset) : null));
  }

  function intakeTab() {
    const x = desk.intake;
    const parts = [h("p", {class: "hint top"}, t("desk.intake.hint"))];
    const pick = h("input", {type: "file", accept: UPLOAD_TYPES, multiple: "", style: "display:none"});
    pick.addEventListener("change", () => intakeAdd(pick.files));
    const chooser = h("button", {type: "button", class: "act", disabled: intake.busy ? "" : null}, intake.busy ? t("desk.intake.working") : t("desk.intake.add"));
    chooser.addEventListener("click", () => pick.click());
    const hidden = h("input", {type: "checkbox", checked: intake.hidden ? "" : null});
    hidden.addEventListener("change", () => { intake.hidden = hidden.checked; });
    const zone = h("div", {class: "intake-drop"}, h("p", null, t("desk.intake.drop")), chooser, pick, h("label", {class: "sub"}, hidden, " " + t("desk.intake.hidden")));
    zone.addEventListener("dragover", (event) => { event.preventDefault(); zone.classList.add("over"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("over"));
    zone.addEventListener("drop", (event) => { event.preventDefault(); zone.classList.remove("over"); intakeAdd(event.dataTransfer.files); });
    parts.push(h("h3", null, t("desk.intake.add.title")), zone);
    const name = h("input", {type: "text", value: intake.name, placeholder: t("desk.intake.paste.name"), class: "env-input", maxlength: 60});
    name.addEventListener("input", () => { intake.name = name.value; });
    const kind = h("select", null, [["csv", t("desk.intake.kind.csv")], ["md", t("desk.intake.kind.md")], ["doc", t("desk.intake.kind.doc")], ["txt", t("desk.intake.kind.txt")]].map(([value, label]) => h("option", {value, selected: intake.kind === value ? "" : null}, label)));
    kind.addEventListener("change", () => { intake.kind = kind.value; intake.kindChosen = true; });
    const text = h("textarea", {rows: 7, placeholder: t("desk.intake.paste.ph"), class: "editor"}, intake.text);
    text.addEventListener("input", () => {
      intake.text = text.value;
      // Markdown pasted as a table would be cut into cells: until the person picks a kind, the text picks it. A choice the person made stays.
      if (!intake.kindChosen) intake.kind = kind.value = guessKind(intake.text);
    });
    const savePaste = h("button", {type: "button", class: "act hot", disabled: intake.busy ? "" : null}, t("desk.intake.paste.save"));
    savePaste.addEventListener("click", () => {
      intake.busy = true; intake.error = ""; draw(true);
      intakeCall("paste", {name: intake.name || "pasted", kind: intake.kind, text: intake.text})
        .then((found) => { intake.text = ""; intake.name = ""; intake.kindChosen = false; intake.done.unshift({name: found.file, result: {files: [found.file], notes: [], report: found.file}}); }, (error) => { intake.error = error.message; })
        .then(() => intakeRefresh()).then(() => { intake.busy = false; draw(true); });
    });
    parts.push(h("h4", {class: "intake-sub"}, t("desk.intake.paste.title")), h("p", {class: "hint"}, t("desk.intake.paste.hint")), h("div", {class: "inbox-pictures"}, name, kind), text, h("div", {class: "inbox-save"}, savePaste));
    if (intake.error) parts.push(h("p", {class: "hint bad"}, intake.error));
    if (x.unread.length) parts.unshift(h("div", {class: "hint bad intake-unread", role: "alert"}, x.unread.map((file) => h("p", null, t("desk.intake.unread", {file})))));  // at the top of the tab
    for (const item of intake.done.slice(0, 5)) {
      parts.push(h("section", {class: "round pass"},
        h("div", {class: "round-head"}, h("strong", null, item.name), " ", h("span", {class: "sub"}, t("desk.intake.made", {n: item.result.files.length}))),
        item.result.files.length ? h("ul", null, item.result.files.map((path) => h("li", null, h("code", null, path)))) : null,
        item.result.notes.length ? [h("div", {class: "sub"}, t("desk.intake.notes")), h("ul", null, item.result.notes.map((note) => h("li", {class: "sub"}, note)))] : null,
        item.result.report ? h("p", {class: "sub"}, t("desk.intake.report", {report: item.result.report})) : null));
    }
    parts.push(h("h3", null, t("desk.intake.files")));
    if (!x.has_intake) {
      // which knowledge base domain is it about? The choices are the domains of the knowledge base; none is a choice. The task's own domains are ticked at first.
      if (intake.domains === null) intake.domains = [...x.task_domains];
      const make = h("button", {type: "button", class: "act hot", disabled: intake.busy ? "" : null}, t("desk.intake.init"));
      make.addEventListener("click", () => {
        intake.busy = true; intake.error = ""; draw(true);
        intakeCall("init", {domains: intake.domains.length ? intake.domains : ["none"]}).then(() => intakeOpen("INTAKE.md"), (error) => { intake.error = error.message; })
          .then(() => intakeRefresh()).then(() => { intake.busy = false; draw(true); });
      });
      const row = (label, ticked, cls, change) => {
        const box = h("input", {type: "checkbox", checked: ticked ? "" : null});
        box.addEventListener("change", () => { change(box.checked); draw(true); });
        return h("label", {class: "domain-choice " + cls + (ticked ? " on" : "")}, box, h("span", null, label));
      };
      const choices = x.domains.map((name) => row(name, intake.domains.includes(name), "name",
        (on) => { intake.domains = on ? [...new Set([...intake.domains, name])] : intake.domains.filter((item) => item !== name); }));
      const none = row(t("desk.intake.domain.none"), !intake.domains.length, "none", (on) => { if (on) intake.domains = []; });
      parts.push(h("p", {class: "hint"}, t("desk.intake.init.hint")),
        x.domains.length ? h("div", {class: "domain-panel"}, h("div", {class: "domain-title"}, t("desk.intake.domain.title")), h("div", {class: "sub"}, t("desk.intake.domain.hint")), h("div", {class: "domain-list"}, choices, none))
          : h("p", {class: "hint"}, t("desk.intake.domain.empty")), make);
    }
    if (!x.files.length) parts.push(h("div", {class: "empty-state"}, h("b", null, t("desk.intake.none"))));
    const row = (item) => {
      const open = h("button", {type: "button", class: "linkish"}, item.path);
      open.addEventListener("click", () => intakeOpen(item.path, item));
      const tick = h("input", {type: "checkbox", checked: intake.picked.has(item.path) ? "" : null, disabled: intake.busy ? "" : null});
      tick.addEventListener("change", () => { if (tick.checked) intake.picked.add(item.path); else intake.picked.delete(item.path); draw(true); });
      return h("tr", null, h("td", null, tick, " ", open, " ", h("span", {class: "sub"}, size(item.size))));
    };
    const table = (list) => h("div", {class: "scroll"}, h("table", {class: "md intake-files"}, h("tbody", null, list.map(row))));
    // what the agent reads comes first; the reports, and the originals and pictures, are folded: they are there to look at, not to trim
    const reads = x.files.filter((item) => !item.original && !item.report && !item.path.startsWith("media/"));
    const reports = x.files.filter((item) => item.report);
    const rest = x.files.filter((item) => item.original || item.path.startsWith("media/"));
    if (x.files.length) {  // pick files (the folded groups too) and delete them together
      for (const path of [...intake.picked]) if (!x.files.some((item) => item.path === path)) intake.picked.delete(path);
      const all = h("input", {type: "checkbox", checked: intake.picked.size === x.files.length ? "" : null, disabled: intake.busy ? "" : null});
      all.addEventListener("change", () => { intake.picked = new Set(all.checked ? x.files.map((item) => item.path) : []); draw(true); });
      const many = h("button", {type: "button", class: "act danger", disabled: intake.busy || !intake.picked.size ? "" : null}, t("desk.intake.pick.delete", {n: intake.picked.size}));
      many.addEventListener("click", () => {
        const list = [...intake.picked];
        const shown = list.slice(0, 12).map((path) => "REQ/" + path).join("\n") + (list.length > 12 ? "\n…" : "");
        if (window.confirm(t("desk.intake.pick.confirm", {n: list.length, list: shown}))) {
          intake.busy = true; intake.error = ""; draw(true);
          intakeCall("delete_many", {paths: list}).then(() => { intake.picked = new Set(); if (intake.editing && list.includes(intake.editing.path)) intake.editing = null; }, (error) => { intake.error = error.message; })
            .then(() => intakeRefresh()).then(() => { intake.busy = false; draw(true); });
        }
      });
      parts.push(h("div", {class: "intake-pick"}, h("label", null, all, " " + t("desk.intake.pick.all")), many));
    }
    if (reads.length) parts.push(h("p", {class: "sub"}, t("desk.intake.group.reads", {n: reads.length})), table(reads));
    const group = (key, label, list) => {  // folded, and kept open or shut across a redraw
      const box = h("details", {class: "intake-group", open: intake.open.has(key) ? "" : null}, h("summary", null, label), table(list));
      box.addEventListener("toggle", () => { if (box.open) intake.open.add(key); else intake.open.delete(key); });
      return box;
    };
    if (reports.length) parts.push(group("reports", t("desk.intake.group.reports", {n: reports.length}), reports));
    if (rest.length) parts.push(group("rest", t("desk.intake.group.rest", {n: rest.length}), rest));
    if (intake.editing) parts.push(intakeEditor());
    parts.push(h("h3", null, t("desk.intake.tell")), promptLine(t("desk.intake.message")));
    return parts;
  }

  function progress() {
    const {done, total} = desk.todo;
    if (!total) return null;
    return h("div", {class: "progress"}, bar([["work", done, ""], ["other", total - done, ""]], total, true),
      h("span", {class: "sub"}, t("desk.todo.progress", {done, total})));
  }

  function changes() {
    const c = desk.changes;
    const parts = desk.commit ? [h("h3", null, t("desk.changes.commit")), ...commit()] : [];  // written back: the commit is what comes next
    if (desk.past && desk.past.branch) parts.push(h("p", {class: "hint top"}, t("desk.round.written", {branch: desk.past.branch, state: desk.past.promote.state, at: when(desk.past.promote.at, 0, 16)})));
    if (desk.past && !c.kept) parts.push(h("p", {class: "hint"}, t("desk.round.nodiff")));
    if (desk.past && !c.kept && c.files.length) {  // no counts to show: only the names are known
      parts.push(h("h3", null, t("desk.changes.files")), table([th(t("desk.changes.file"))], c.files.map((item) => h("tr", null, h("td", null, h("code", null, item.path))))));
    }
    const same = c.unchanged_files || [];
    if ((c.files.length && !(desk.past && !c.kept)) || c.deletes.length || same.length) {  // one list: the changed files, the deleted ones and the fetched ones left as they were
      const fetched = c.files.filter((item) => item.action !== "create").length + same.length;
      parts.push(h("h3", null, t("desk.changes.files")));
      if (same.length) parts.push(h("p", {class: "sub"}, t("desk.changes.summary", {fetched, changed: fetched - same.length, same: same.length})));
      parts.push(DiffView.create({files: c.files, lines: c.diff.lines, cut: c.diff.cut, same}, () => diff(c.diff), "dev"));  // old and new code side by side (diffview.js); the plain diff text is its third view
    } else {
      parts.push(h("div", {class: "empty-state"}, h("b", null, t("desk.changes.none")), h("p", null, t("desk.changes.none.hint"))));
    }
    if (c.promote_plan.lines.length) parts.push(h("h3", null, t("desk.changes.promote")), h("p", {class: "sub"}, t("desk.changes.promote.hint")),
      DiffView.create(c.promote_plan, () => diff(c.promote_plan), "plan", true));  // the same compare, the files read from the plan; a long file scrolls in a lower window
    return parts;
  }

  // Inside a hunk the counts of its `@@` line say how many lines follow: a removed line that starts with `--` (an SQL comment) is not a file header.
  function diffKinds(lines) {
    let old = 0, added = 0;
    return lines.map((line) => {
      if (old > 0 || added > 0) {
        if (line.startsWith("\\")) return "";
        if (line.startsWith("-")) { old -= 1; return "del"; }
        if (line.startsWith("+")) { added -= 1; return "add"; }
        old -= 1; added -= 1;
        return "";
      }
      const hunk = /^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@/.exec(line);
      if (hunk) {
        old = hunk[1] === undefined ? 1 : Number(hunk[1]);
        added = hunk[2] === undefined ? 1 : Number(hunk[2]);
        return "hunk";
      }
      return line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") ? "file" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "";
    });
  }

  function diff(found) {
    const kinds = diffKinds(found.lines);
    return h("div", {class: "scroll"}, h("pre", {class: "diff"}, found.lines.map((line, index) => h("span", {class: kinds[index]}, line + "\n"))),
      found.cut ? h("p", {class: "sub"}, t("desk.cut")) : null);
  }

  function timeline() {
    if (!desk.history.length) return h("div", {class: "empty-state"}, h("b", null, t("desk.history.none")));
    return h("ol", {class: "timeline"}, desk.history.map((event) => h("li", {class: "ev-" + event.what},
      h("span", {class: "when sub"}, when(event.at, 5, 16)),
      h("div", {class: "what"}, h("b", null, event.label),  // one block: a long line wraps under its own start, not under the time
        event.detail ? h("span", {class: "sub"}, " · " + event.detail) : null, event.via ? h("span", {class: "tag"}, t("desk.via." + event.via)) : null, event.round > 1 ? h("span", {class: "tag"}, t("desk.round", {round: event.round})) : null))));
  }

  // The Trace tab: the tool calls and the gate decisions of the session, newest first. The server sends tool names, paths, times and the gate's reasons; no thinking, no reply, no prompt text.
  function trace() {
    const found = desk.trace;
    const notes = (desk.warn || []).map((item) => h("p", {class: "warn-note"}, tag("\u26a0", "warn"), " ", t("board.warn." + item.rule, {n: item.n})));
    const rows = found.entries.slice().reverse().map((item) => {
      if (item.kind === "prompt") return h("li", {class: "tr-prompt"}, h("span", {class: "when sub"}, when(item.at, 5, 19)), h("div", {class: "what sub"}, t("desk.trace.prompt")));
      const gate = item.kind === "gate";
      return h("li", {class: gate ? "tr-gate" : item.ok === false ? "tr-fail" : ""},
        h("span", {class: "when sub"}, when(item.at, 5, 19)),
        h("div", {class: "what"}, h("b", null, item.tool),
          gate ? [" ", tag(t("desk.trace." + item.decision), item.decision === "deny" ? "bad" : "hot"), item.rule ? h("span", {class: "sub"}, " \u00b7 " + item.rule) : null] : null,
          !gate && item.ok === false ? [" ", tag(t("desk.trace.failed"), "bad")] : null,
          !gate && item.ok === null ? [" ", tag(t("desk.trace.running"), "good run")] : null,
          item.seconds ? h("span", {class: "sub"}, " \u00b7 " + clock(item.seconds)) : null,
          (item.paths || []).map((path) => [" ", h("span", {class: "path", title: path}, path)]),
          item.command ? [" ", h("code", null, item.command)] : null,
          item.reason ? h("div", {class: "sub"}, item.reason) : null,
          item.error ? h("div", {class: "sub"}, item.error) : null));
    });
    return [h("p", {class: "hint top"}, t("desk.trace.hint")), notes, h("ol", {class: "timeline trace"}, rows), found.cut ? h("p", {class: "sub"}, t("desk.trace.cut", {count: found.cut})) : null];
  }

  function openDoc(name) {
    const tab = Object.keys(FILES).find((key) => FILES[key] === name);
    if (tab) { current = tab; } else { current = "docs"; other = name; }
    history.replaceState(null, "", hashOf(current));
    draw(false);
  }

  // One line over the plan: when it was approved, with which code, and whether it changed since (what approve-plan stored; nothing new is kept).
  function planApproval() {
    const a = desk.plan_approval;
    if (!a) return null;
    if (!a.approved) return h("p", {class: "plan-approval"}, tag(t("desk.plan.approval.none"), "hot long"));
    return h("p", {class: "plan-approval"}, tag(t(a.changed ? "desk.plan.approval.changed" : "desk.plan.approval.yes", {at: when(a.at, 0, 16), code: a.code}), (a.changed ? "hot" : "good") + " long"));
  }

  function body() {
    if (current === "overview") {
      return [h("p", {class: "hint top"}, t("desk.overview.hint") + (doc("REQ.md") ? " " + t("desk.overview.req") : "")), markdown("TASK.md", t("desk.missing.task"))];
    }
    if (current === "req") return [h("p", {class: "hint top"}, t("desk.req.hint")), markdown("REQ.md", t("desk.missing.req"))];
    if (current === "design") return [h("p", {class: "hint top"}, t("desk.design.hint")), markdown(FILES.design, t("desk.missing.design"))];
    if (current === "rca") return [h("p", {class: "hint top"}, t("desk.rca.hint")), markdown(FILES.rca, t("desk.missing.rca"))];
    if (current === "plan") return [h("p", {class: "hint top"}, t("desk.plan.hint")), planApproval(), markdown("PLAN.md", t("desk.missing.plan"))];
    if (current === "todo") return [progress(), markdown("TODO.md", t("desk.missing.todo"))];
    if (current === "log") return [h("p", {class: "hint top"}, t("desk.log.hint")), markdown("LOG.md", t("desk.missing.log"))];
    if (current === "changes") return changes();
    if (current === "review") return review();
    if (current === "test" && desk.test) return testing();
    if (current === "files") return filesTab();
    if (current === "intake") return intakeTab();
    if (current === "trace") return trace();
    if (current === "history") return [h("p", {class: "hint top"}, t("desk.history.hint")), timeline()];
    const docs = extra();
    const name = docs.some((item) => item.name === other) ? other : (docs[0] || {}).name;
    return [h("div", {class: "doc-list"}, docs.map((item) => {
      const button = h("button", {type: "button", class: "chip" + (item.name === name ? " on" : "")}, item.name);
      button.addEventListener("click", () => { other = item.name; draw(false); });
      return button;
    })), name ? markdown(name, "") : null];
  }

  // A redraw makes every node again: a list or a code window that scrolls by itself (marked `data-keep`) is put back where it was.
  function draw(keepScroll) {
    const y = window.scrollY;
    const kept = new Map([...app.querySelectorAll("[data-keep]")].map((node) => [node.dataset.keep, [node.scrollTop, node.scrollLeft]]));
    app.replaceChildren(...[...header(), ...(chatBars() || []), settingsRow(), ribbon(), desk.past ? pastNote() : saved ? null : actions(), h("section", {class: "card desk"}, nav(), h("div", {class: "pane"}, body())),
      h("footer", null, t(saved ? "desk.snapshot.footer" : "desk.footer", {as_of: when(desk.as_of, 0, 19)}), copyright())].filter(Boolean));  // a null would be drawn as the word "null"
    if (keepScroll) {
      for (const node of app.querySelectorAll("[data-keep]")) if (kept.has(node.dataset.keep)) [node.scrollTop, node.scrollLeft] = kept.get(node.dataset.keep);
      window.scrollTo(0, y);
      if (intake && intake.reveal) { const editor = document.querySelector("section.editing"); if (editor) editor.scrollIntoView({block: "start"}); }
    }
  }

  // A hash changed by hand, or the browser's back and forward: follow it. Our own writes use replaceState, which fires no event, so there is no loop.
  window.addEventListener("hashchange", () => {
    const at = /^r(\d+)(?:\/(.*))?$/.exec(location.hash.slice(1));
    const number = at && (full.rounds || []).some((item) => item.round === Number(at[1])) ? Number(at[1]) : full.round;
    const tab = at ? at[2] || "" : location.hash.slice(1);
    showRound(number, tab === "commit" ? "changes" : tab);
  });

  document.querySelector("main").classList.add("wide");
  draw(false);
  if (typeof SERVE !== "undefined" && DATA.serve.refresh) {
    pollEvery(DATA.serve.refresh, () => {
      if (SERVE.busy()) return null;
      if (document.activeElement && ["TEXTAREA", "INPUT"].includes(document.activeElement.tagName)) return null;  // a redraw would take the focus from what the person is typing
      return SERVE.post("/api/desk", {task: desk.name}).then((data) => {
        const text = JSON.stringify(data.desk);
        if (same(text, shown)) return;
        setDesk(data.desk);
        shown = text;
        draw(true);
      }, (error) => { if (error && error.offline) throw error; });
    });
  }
})();
