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
  const steady = (text) => text.replace(/"as_of":"[^"]*"/, "").replace(/"waited_s":[\d.]+/g, "");  // the time of asking and the time waited are not a change: a redraw would close a card the pointer is on
  const same = (a, b) => steady(a) === steady(b);
  // The tabs are in five groups (1.6.16): the top row has Live and the groups, the open group has a second row. A group with no tab is not there; a group with one goes straight to it.
  const GROUPS = [
    {id: "live", tabs: ["live"]},
    {id: "overview", tabs: ["overview", "req", "intake", "design", "rca", "plan", "todo"]},
    {id: "deliver", tabs: ["changes", "test", "review"]},
    {id: "records", tabs: ["log", "history", "trace"]},
    {id: "files", tabs: ["docs", "files"]},
  ];
  const tabs = GROUPS.flatMap((group) => group.tabs);  // the commit message is at the top of "changes" once written back (1.5.34)
  const groupOf = (tab) => GROUPS.find((group) => group.tabs.includes(tab));
  const JUMPS = {"approve-plan": "plan", "confirm-req": "req", "approve-promote": "changes"};  // the waits that have a strong card, and the tab where what they ask about is read
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
    const stages = task.stages ? Object.assign({}, task.stages, {round: number, review: found.marks || null, steps: task.stages.steps.map((step) => Object.assign({}, step, {state: "done", flag: ""}))}) : null;  // written back: every step is done
    return Object.assign({}, task, {
      past: found, round: number, status: "closed", state: "", waiting: "", waiting_why: "", waited_s: null, paused_since: "", handoff: null, held: false, autorun: false, active: false,
      branch: found.branch, docs: found.docs, files: found.files, changes: found.changes, review: found.review, history: found.history, stages,
      commit: null, test: null, intake: null, actions: [], todo: {done: 0, total: 0}, todo_left: 0, req_placeholders: 0, req_unconfirmed: false, req_changed: false, report: "",
    });
  }
  const hashOf = (tab) => "#" + (desk.past ? "r" + desk.past.round + "/" : "") + tab;
  // The tab a task opens on: Live for a task of a served page that is open or not started, else Overview.
  const firstTab = () => (ownTab("live") && desk.status !== "closed" ? "live" : tabs.find((tab) => ownTab(tab) && tab !== "docs" && tab !== "live") || "overview");
  const visible = (tab) => (tab === "docs" ? extra().length > 0 : ownTab(tab));
  // The server sent the task again: draw the round that is open from the new data.
  function setDesk(next) {
    full = next;
    drafts.stale = true;  // a send may have used the notes: read them again at the next draw
    shown = JSON.stringify(next);
    desk = desk.past ? pastView(full, desk.past.round) : full;
    if (!visible(current)) current = firstTab();
  }
  function showRound(number, tab) {
    desk = number === full.round ? full : pastView(full, number);
    current = tab && visible(tab) ? tab : firstTab();
    history.replaceState(null, "", hashOf(current));
    draw(false);
  }
  // A tab is there when the kind of the task has it, or when its file is there (M40-1): a test task has no plan and no diff; a question has no log.
  const ownTab = (tab) => {
    if (tab === "live") return served() && !desk.past;  // a saved copy and an earlier round have no live chat
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
  let leavingMode = false;  // "Back to Interactive" was pressed: see otherMode
  if (route && (full.rounds || []).some((item) => item.round === Number(route[1]))) desk = pastView(full, Number(route[1]));
  current = tabs.includes(asked) && visible(asked) ? asked : firstTab();

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
    return h("div", {class: "code-box"}, h("div", {class: "code-bar"}, Highlight.label(kind) ? h("span", {class: "code-lang"}, Highlight.label(kind)) : null, typeof Run !== "undefined" && served() && canAct() ? Run.buttons(desk.name, text, kind, () => goTab("live")) : null, button), h("pre", {class: "code"}, h("code", null, Highlight.nodes(text, kind))));
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

  if (typeof ROUNDS !== "undefined") ROUNDS.drawing(blocks);
  if (typeof LIVE !== "undefined") LIVE.drawing(blocks);  // the items of the agent in the Live tab are drawn as the documents are

  function markdown(name, empty) {
    const found = doc(name);
    if (!found) return h("div", {class: "empty-state"}, h("b", null, t("desk.missing", {file: name})), h("p", null, empty));
    if (!found.blocks.length) return h("div", {class: "empty-state"}, h("b", null, t("desk.doc.empty")), h("p", null, empty));
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

  // --- the header: one slim bar, made once and changed in place ----------------------------------------------------------------
  // The nodes of the shell are made once (`shell()`) and `paintHead()` changes only the places whose data changed (`slot`). So the 3-second poll cannot close a card or the menu, empty a field,
  // or start an animation again: nothing that is on screen is drawn a second time unless its own data changed.
  const ui = {};
  const view = {stages: null, chat: null};  // what the cards read when they open or are filled again

  const useful = (item) => item !== null && item !== undefined && item !== false;
  const fill = (node, kids) => node.replaceChildren(...[kids].flat(Infinity).filter(useful).map((item) => (item instanceof Node ? item : document.createTextNode(String(item)))));

  function slot(tagName, cls) {
    const place = {node: h(tagName, {class: cls}), sig: null, set(sig, make) {
      if (sig === place.sig) return place;
      place.sig = sig;
      const made = [make()].flat(Infinity).filter(useful);
      place.node.replaceChildren(...made);
      place.node.hidden = made.length === 0;
      return place;
    }};
    return place;
  }

  const SVG = "http://www.w3.org/2000/svg";
  function icon(paths, size) {
    const node = document.createElementNS(SVG, "svg");
    for (const [name, value] of Object.entries({viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", "stroke-width": "1.5", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true"})) node.setAttribute(name, value);
    if (size) { node.setAttribute("width", size); node.setAttribute("height", size); }
    for (const d of paths) { const part = document.createElementNS(SVG, "path"); part.setAttribute("d", d); node.append(part); }
    return node;
  }

  // 128000 -> "128k", 1048576 -> "1M"
  const tokensShort = (value) => (value >= 1e6 ? (Math.round(value / 1e5) / 10).toString().replace(/\.0$/, "") + "M" : value >= 1000 ? Math.round(value / 1000) + "k" : String(value));

  // Compact: one confirm, then the server sends /compact to an idle chat. The only place a control mark goes out, and only for this click.
  function askCompact() {
    const said = h("div", {class: "bad"});
    const yes = h("button", {class: "act hot", type: "button"}, t("desk.compact.confirm"));
    const no = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
    const dialog = SERVE.dialog([h("h2", null, t("desk.compact.title", {name: desk.name})), h("p", null, t("desk.compact.warn")), h("div", {class: "row"}, yes, no), said]);
    no.addEventListener("click", dialog.close);
    yes.addEventListener("click", () => {
      yes.disabled = true;
      SERVE.post("/api/compact", {task: desk.name}).then(() => { dialog.close(); SERVE.done(); },
        (error) => { said.replaceChildren(...SERVE.reasons(error.message)); yes.disabled = false; });
    });
  }

  function compactButton(extra) {
    const button = h("button", {type: "button", class: "act chat-act" + (extra ? " " + extra : "")}, t("desk.compact.go"));
    button.addEventListener("click", askCompact);
    return button;
  }
  // Go on in a new chat (1.6.109): the other way out of a long chat. A new chat in VS Code picks the task up from its files (`harness-my-task`); the board binds it at once and the old chat
  // stays in VS Code. Only while the chat is idle: two agents must not work on one task at once. What was said only in the old chat and is in no task file does not come along.
  function newChatButton(chat) {
    const idle = chat && chat.state === "idle";
    const button = h("button", {type: "button", class: "act chat-act", disabled: idle ? null : "disabled", title: t(idle ? "desk.newchat.tip" : "desk.newchat.busy")}, t("desk.newchat.go"));
    button.addEventListener("click", () => chatGoOn(desk.name));
    return button;
  }
  const canCompact = (chat) => Boolean(served() && chat && chat.bound && SERVE.runs("send"));
  function tuneCompact(button, chat) {
    const idle = chat && chat.state === "idle";
    button.disabled = !idle;
    button.title = t(idle ? "desk.compact.tip" : "desk.compact.busy");
  }

  function copyTitleButton(chat) {
    const button = h("button", {type: "button", class: "act", "data-label": t("desk.chat.copy"), title: t("desk.chat.copy.hint")}, t("desk.chat.copy"));
    button.addEventListener("click", () => copyCommand(button, chat.title));
    return button;
  }

  // The row an action button is made for (what `actionButton` and the dialogs read of the task).
  function actionRow() {
    return {name: desk.name, waiting: desk.waiting, state: desk.state, chat: desk.chat, ask: desk.ask, todo_left: desk.todo_left, req_unconfirmed: desk.req_unconfirmed,
      result_missing: FILES[desk.kind] && ["design", "rca"].includes(desk.kind) && !doc(FILES[desk.kind]) ? FILES[desk.kind] : ""};  // a design or an RCA task without its result file: the close dialog warns
  }
  const OPTIONAL = ["pause", "resume", "autorun on", "close"];  // the person may do these any time; the rest is what the task waits for
  const offersChat = (item) => ["send", "answer"].includes(item.action) && chatNew(actionRow());
  const talkButtons = (row, item) => [actionButton(row, item, "big"), offersChat(item) ? goOnButton(row.name, "big") : null];
  const hintOf = (item) => (offersChat(item) ? t("desk.hint.newchat") : item.action === "approve-promote" && desk.promote_direct ? t("desk.hint.approve-promote.kb") : t("desk.hint." + item.action.replace(" ", "-")));
  const canAct = () => desk.status === "open" && !desk.past && !saved;

  // How full the context is: a label, a thin bar, the percent. Unknown is "-" and no bar, never 0.
  // How full the context is: over `notice`, a note; over `limit`, time to compact, and the warning tag on the board (`health`).
  const ctxLevel = (meter) => (meter.percent > (meter.limit || 70) ? "hot" : meter.percent > (meter.notice || 50) ? "warm" : "");
  function ctxBar(percentNow, meter) {
    if (percentNow === null) return [h("span", {class: "tk-cl"}, t("desk.ctx.label")), h("b", {class: "tk-cv"}, "-")];
    const level = ctxLevel(meter);
    return [h("span", {class: "tk-cl"}, t("desk.ctx.label")), h("span", {class: "tk-cb" + (level ? " " + level : "")}, h("i", {style: "width:" + Math.max(0, Math.min(100, percentNow)) + "%"})),
      h("b", {class: "tk-cv" + (level ? " " + level : "")}, Math.round(percentNow * 10) / 10 + "%")];
  }

  // The card over the context bar: the figure, what the context holds when Copilot gave real counts, and the compact action.
  function ctxCard() {
    const chat = view.chat;
    if (!chat || !chat.bound) return null;
    const meter = chat.context && typeof chat.context.percent === "number" ? chat.context : null;
    const parts = Array.isArray(chat.parts) && chat.parts.length ? chat.parts : null;
    const can = canCompact(chat);
    return {sig: JSON.stringify([meter, parts, chat.cost, can, chat.state]), build: () => {
      const box = h("div", {class: "tk-cx"});
      if (typeof chat.cost === "number") box.append(h("div", {class: "st-head"}, t("desk.ctx.session")), h("div", {class: "tk-part"}, h("span", {class: "tk-pn"}, t("desk.ctx.cost")), h("b", null, t("desk.ctx.cost.v", {n: chat.cost}))));
      box.append(h("div", {class: "st-head" + (typeof chat.cost === "number" ? " tk-cx-h" : "")}, t("desk.ctx.label")));
      if (meter) {
        const level = ctxLevel(meter);
        box.append(h("div", {class: "tk-cx-big" + (level ? " " + level : "")}, t("desk.ctx.card.used", {percent: Math.round(meter.percent * 10) / 10, used: amount(meter.used), window: amount(meter.window)})),
          h("span", {class: "tk-cb wide" + (level ? " " + level : "")}, h("i", {style: "width:" + Math.max(0, Math.min(100, meter.percent)) + "%"}), meter.reserved > 0 ? h("b", {class: "tk-cr", style: "width:" + Math.min(Math.max(0, 100 - meter.percent), meter.reserved) + "%"}) : null));
        if (meter.reserved > 0) box.append(h("div", {class: "sub tk-cr-l"}, h("i", {class: "tk-cr"}), t("desk.ctx.reserved")));
        if (level) box.append(h("div", {class: "set-warn"}, t("desk.ctx.level." + level)));
        box.append(h("div", {class: "sub"}, t("desk.ctx.card.note")));
      } else {
        box.append(h("div", {class: "sub"}, t("desk.ctx.unknown")));
      }
      for (const group of ["system", "user", "other"]) {
        const rows = (parts || []).filter((row) => row.group === group);
        if (rows.length) box.append(h("div", {class: "st-head tk-cx-h"}, t("desk.ctx.group." + group)));
        for (const row of rows) box.append(h("div", {class: "tk-part"}, h("span", {class: "tk-pn"}, row.key ? t("desk.ctx.part." + row.key) : row.label), h("span", {class: "tk-pv"}, row.percent.toFixed(1) + "%")));
      }
      if (can) { const go = compactButton(); tuneCompact(go, chat); box.append(h("div", {class: "tk-cx-go"}, go, newChatButton(chat))); }
      return box;
    }};
  }

  // The card over the stage strip.
  function stageCardNow() {
    const found = view.stages;
    if (!found) return null;
    const review = ownTab("review") ? () => goTab("review") : null;
    const again = desk.stages.steps.some((step) => step.id === "plan" && step.state === "now") && desk.history.some((event) => event.what === "approve-plan");  // approved once, asked for again
    return {sig: JSON.stringify([found, Boolean(review), again]), build: () => Status.stageCard(found, review, again)};
  }

  // The menu behind the three dots: what is not needed every minute (the report, a copy to save, the chat's title) and the actions a person may take any time.
  let menuOpen = false, menuSig = "";
  function menuItems() {
    const items = [];
    const chat = view.chat;
    if (!saved && desk.report) items.push(h("a", {class: "tk-mi act", href: desk.report.split("/").map(encodeURIComponent).join("/")}, t("desk.report")));
    if (!saved && served()) items.push(h("a", {class: "tk-mi act", href: "/snapshot/" + encodeURIComponent(desk.name), download: "", title: t("desk.save.hint")}, t("desk.save")));
    if (chat && chat.bound && chat.title) items.push(copyTitleButton(chat));
    if (canAct()) {
      const row = actionRow();
      for (const item of desk.actions.filter((entry) => OPTIONAL.includes(entry.action))) items.push(h("div", {class: "tk-mi-act"}, actionButton(row, item), h("span", {class: "hint"}, hintOf(item))));
    }
    return items;
  }
  function paintMenu(force) {
    const chat = view.chat;
    const sig = JSON.stringify([desk.report, served(), saved, desk.past && desk.past.round, desk.actions, desk.state, desk.waiting, desk.status, chat && [chat.bound, chat.title]]);
    const items = menuItems();
    ui.more.hidden = items.length === 0;
    if (sig === menuSig && !force) return;
    menuSig = sig;
    if (menuOpen) fill(ui.menu, items);
  }
  function openMenu() {
    menuOpen = true;
    fill(ui.menu, menuItems());
    ui.menu.hidden = false;
    ui.moreBtn.setAttribute("aria-expanded", "true");
    const first = ui.menu.querySelector("a,button:not([disabled])");
    if (first) first.focus();
  }
  function closeMenu() {
    menuOpen = false;
    ui.menu.hidden = true;
    ui.moreBtn.setAttribute("aria-expanded", "false");
  }

  function shell() {
    if (ui.root) return;
    ui.back = saved ? null : h("a", {class: "tk-icon tk-back", href: "/", title: t("desk.back"), "aria-label": t("desk.back.label")}, icon(["M10 3L5 8l5 5"], 16));
    ui.name = h("h1", {class: "tk-name"});
    ui.state = slot("span", "tk-state");
    ui.stage = slot("span", "tk-stage");
    Status.card(ui.stage.node, stageCardNow);
    ui.stage.node.setAttribute("role", "group");
    Status.phase(ui.stage.node);
    ui.checks = slot("span", "tk-checks");
    ui.ctx = slot("span", "tk-ctx");
    Status.card(ui.ctx.node, ctxCard);
    ui.vs = slot("span", "tk-vs");
    ui.moreBtn = h("button", {type: "button", class: "tk-icon tk-morebtn", "aria-haspopup": "menu", "aria-expanded": "false", title: t("desk.menu.more"), "aria-label": t("desk.menu.more")}, icon(["M3 8h.01M8 8h.01M13 8h.01"], 16));
    ui.menu = h("div", {class: "tk-menu", role: "menu", hidden: ""});
    ui.more = h("span", {class: "tk-more"}, ui.moreBtn, ui.menu);
    ui.moreBtn.addEventListener("click", () => (menuOpen ? closeMenu() : openMenu()));
    ui.menu.addEventListener("click", (event) => { if (event.target.closest("a,button")) setTimeout(closeMenu, 0); });  // after the click has done its work
    document.addEventListener("click", (event) => { if (menuOpen && !ui.more.contains(event.target)) closeMenu(); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && menuOpen) { closeMenu(); ui.moreBtn.focus(); } });
    ui.head = h("header", {class: "tk-head"}, ui.back, ui.name, ui.state.node, ui.stage.node, ui.checks.node, h("span", {class: "tk-sp"}), ui.ctx.node, h("span", {class: "tk-tools"}, ui.vs.node, ui.more));
    ui.infoL = slot("div", "tk-info-l");
    ui.rounds = slot("span", "tk-rounds");
    ui.pill = slot("span", "tk-pill");
    ui.review = slot("span", "tk-rv");
    ui.envs = slot("span", "tk-rv tk-env");
    ui.info = h("div", {class: "tk-info"}, ui.infoL.node, ui.rounds.node, ui.review.node, ui.envs.node, ui.pill.node);
    ui.forks = slot("div", "tk-forks sub");
    ui.wait = h("div", {class: "tk-wait"});
    ui.tabs = h("div", {class: "tk-tabs"});
    ui.pane = h("div", {class: "pane tk-pane"});
    ui.live = typeof LIVE !== "undefined" ? LIVE.node : h("div", {hidden: ""});  // the stream of the Live tab: made once, outside the part that is drawn again, so its animations go on
    ui.surface = h("section", {class: "tk-surface"}, ui.wait, ui.tabs, ui.live, ui.pane);
    ui.foot = h("div", {class: "tk-foot"});
    ui.root = h("div", {class: "tk"}, ui.head, ui.info, ui.forks.node, SHELL.banner(), ui.surface, ui.foot);
    app.replaceChildren(ui.root);
  }

  // The line under the name says little; the card says it all (the same card on the icon of the kind). An exact time belongs in the card: on the line, how long ago is what counts.
  const CLOCK = ["M8 14.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13z", "M8 4.5V8l2.3 1.4"];
  function agoText(stamp) {
    const minutes = Math.floor((Date.now() - Date.parse(stamp)) / 60000);
    if (!(minutes >= 1)) return t("desk.ago.now");
    if (minutes < 60) return t("desk.ago.min", {n: minutes});
    return minutes < 1440 ? t("desk.ago.hour", {n: Math.floor(minutes / 60)}) : t("desk.ago.day", {n: Math.floor(minutes / 1440)});
  }
  const fact = (label, value) => h("div", {class: "tk-fact"}, h("span", {class: "sub"}, label), h("span", null, value));
  function factsCard() {
    const known = (label, value) => fact(t("desk.fact." + label), value);
    return {sig: JSON.stringify([desk.kind, desk.tier, desk.round, desk.created_at, desk.updated_at, desk.domains, desk.autorun]), build: () => h("div", {class: "tk-facts"},
      known("kind", t("task.kind." + (desk.kind || "none"))), known("tier", t("task.tier." + (desk.tier || "none"))), known("round", String(desk.round)), known("opened", when(desk.created_at, 0, 16)), known("changed", when(desk.updated_at, 0, 16)),
      desk.domains.length ? known("domains", desk.domains.join(", ")) : null, desk.autorun ? known("autorun", t("desk.autorun")) : null)};
  }

  // The chat's model as one chip (1.6.109): a short name and a gauge of the thinking level, one bar for each level the model has. Its card says the full name, the level and the window.
  // The line under the task's name stays two short marks: this chip and the time of the last change.
  function modelChip(chat, room) {
    const model = ((desk.settings && desk.settings.models) || []).find((item) => item.id === chat.model) || null;
    const levels = chat.effort && model && model.thinking ? (model.thinking.levels || []).slice(0, 5) : [];
    const at = levels.indexOf(chat.effort);
    const level = chat.effort ? (model && model.thinking && model.thinking.labels && model.thinking.labels[chat.effort]) || chat.effort : "";
    const full = modelWords(chat, chat.model_name || chat.model);
    const gauge = at >= 0 ? h("span", {class: "tk-think", "aria-hidden": "true"}, levels.map((item, index) => h("i", {class: index <= at ? "on" : null}))) : null;
    const label = [full, level ? t("desk.info.effort", {level}) : "", room ? t("desk.info.window", {size: tokensShort(room)}) : ""].filter(Boolean).join(" \u00b7 ");
    const card = () => ({sig: JSON.stringify([full, level, room, chat.fusion]), build: () => h("div", {class: "tk-facts"},
      fact(t("desk.set.model"), full), level ? fact(t("desk.set.thinking"), level) : null, room ? fact(t("desk.fact.window"), tokensShort(room) + " \u00b7 " + room.toLocaleString("en-US")) : null,
      fusionChat(chat) ? h("p", {class: "set-tip"}, modelTip(chat, "")) : null, level ? h("p", {class: "set-tip"}, t("desk.info.effort.tip")) : null)});
    return Status.card(h("span", {class: "tk-i tk-model"}, h("span", {class: "tk-model-name"}, modelWords(chat, String(chat.model_name || chat.model).replace(/^claude\s+/i, ""))), gauge), card, label);
  }

  function paintHead() {
    const live = served();
    const chat = served() && !desk.past && desk.chat ? desk.chat : null;
    view.chat = chat;
    if (ui.name.textContent !== desk.name) { ui.name.textContent = desk.name; ui.name.title = desk.name; }
    const state = stateTag(desk, live);
    state.title = state.textContent;
    ui.state.set(state.className + "|" + state.textContent, () => state);

    const found = desk.stages && desk.status !== "new" ? Status.stages(desk, live) : null;
    if (saved && found) found.steps.forEach((step) => { if (!isNaN(step.since)) { step.s = Math.max(0, (Date.parse(desk.as_of) - step.since) / 1000); step.since = NaN; } });  // a saved copy does not count on: the time is as of the day it was saved
    view.stages = found;
    ui.stage.set(found ? JSON.stringify(found) : "", () => (found ? Status.ribbon(found, true) : null));
    if (found) ui.stage.node.setAttribute("aria-label", t("board.status.stage.title") + ": " + found.steps.map((step) => step.label + " " + step.text).join(", "));
    ui.checks.set(found && found.review ? JSON.stringify([found.review, ownTab("review")]) : "", () => (found && found.review ? Status.checks(found.review, ownTab("review") ? () => goTab("review") : null) : null));

    const bound = Boolean(chat && chat.bound);
    const meter = bound && chat.context && typeof chat.context.percent === "number" ? chat.context : null;
    ui.ctx.set(bound ? JSON.stringify(meter ? [meter.percent, meter.limit, meter.notice] : null) : "", () => (bound ? ctxBar(meter ? meter.percent : null, meter) : null));
    if (bound) ui.ctx.node.setAttribute("aria-label", meter ? t("board.status.context", {percent: Math.round(meter.percent * 10) / 10, used: amount(meter.used), window: amount(meter.window)}) : t("desk.ctx.unknown"));
    ui.vs.set(chat ? "vs:" + (chat.bound ? "" : chat.why || "") : "", () => (chat ? SERVE.vsButton(chat) : null));
    paintMenu(false);

    const kindName = t("task.kind." + (desk.kind || "none"));
    const room = bound && chat.window ? chat.window : meter ? meter.window : 0;
    const changed = desk.status === "new" ? "" : agoText(desk.updated_at);
    ui.infoL.set(JSON.stringify([desk.kind, desk.tier, desk.status, desk.round, desk.created_at, desk.updated_at, changed, desk.domains, desk.autorun, bound && [chat.model, chat.model_name, chat.effort, chat.fusion, room], desk.settings && desk.settings.models && desk.settings.models.length]), () => {
      const nodes = [];
      if (desk.status !== "new" && desk.kind) nodes.push(Status.card(kindIcon(desk.kind, t("desk.info.kind", {kind: kindName})), factsCard, t("desk.info.kind", {kind: kindName})));
      if (bound && chat.model) nodes.push(modelChip(chat, room));
      if (desk.status !== "new") {  // a task not started has no kind, no round, no dates. The tier and the round are in the card; the round is on the tabs of the rounds too
        nodes.push(Status.card(h("span", {class: "tk-meta"}, h("span", {class: "tk-when"}, icon(CLOCK, 13), changed)), factsCard, t("desk.fact.label")), desk.autorun ? tag(t("desk.autorun"), "good") : null);
      }
      return nodes;
    });
    ui.rounds.set(JSON.stringify([full.rounds, full.round, desk.past && desk.past.round]), () => roundSwitch());
    ui.review.set(JSON.stringify([full.settings && [full.settings.n, full.settings.max_n], full.status, desk.past && full.round]), () => reviewButton());
    ui.envs.set(JSON.stringify([desk.allow, full.status]), () => envButton());
    ui.pill.set(live ? JSON.stringify([desk.vscode, chat && chat.bound]) : "", () => (live ? [SHELL.vsPill(desk.vscode, chat), SERVE.pairMark(true)] : null));
    ui.forks.set(JSON.stringify([desk.forked_from, desk.forked_to]), () => (desk.forked_from || desk.forked_to.length ? [
      desk.forked_from ? [t("desk.forked.from") + " ", taskLink(desk.forked_from)] : null, desk.forked_from && desk.forked_to.length ? " · " : null,
      desk.forked_to.length ? [t("desk.forked.to") + " ", desk.forked_to.map((name, index) => [index ? ", " : "", taskLink(name)])] : null] : null));
    document.documentElement.style.setProperty("--tkh", ui.head.offsetHeight + "px");  // the tab bar sticks under the header
    Status.refresh();
  }

  const defectSync = () => { const go = h("button", {type: "button", class: "act kb-mini"}, t("desk.test.defects.sync")); go.addEventListener("click", () => TERM.run("harness task defects sync --task " + desk.name)); return go; };
  // "Task settings" (1.6, B72): the independent checks (0 to the cap), the model and the thinking level of the messages the board sends. Only the person changes them, from a served page;
  // a change is written in the history and holds from the next message. The model goes on every message the board sends and stays in the chat, also for what is typed in VS Code, until it is changed.
  function settingsRow() {
    const info = desk.settings;
    if (!served() || desk.past || !info || desk.status !== "open") return null;
    const models = info.models || [];
    const running = fusionChat(desk.chat) ? "auto" : desk.chat && desk.chat.model;  // Copilot Fusion stays the choice, whatever one request was routed to
    const now = info.model || running || "";  // the model the chat uses: the board's choice, or what it ran on last
    const chosen = models.find((item) => item.id === now);
    const pick = h("select", {"aria-label": t("desk.set.model"), disabled: info.ready && models.length ? null : "disabled", title: info.ready ? "" : t("desk.set.model.off")},
      chosen ? null : h("option", {value: ""}, t("desk.set.model.chat")), models.map((item) => h("option", {value: item.id, selected: item.id === now ? "" : null}, item.name)));
    const think = h("select", {"aria-label": t("desk.set.thinking")});
    const room = h("select", {"aria-label": t("desk.set.context"), title: t("desk.set.context.tip")});
    // Thinking and Context offer what the model has. They are filled here again when the model changes: this row is not drawn again while one of its controls has the focus.
    function fillFor(id, level, size) {
      const found = models.find((item) => item.id === id);
      const levels = found && found.thinking ? found.thinking.levels : [];
      think.replaceChildren(...[levels.includes(level) ? null : h("option", {value: ""}, t("desk.set.thinking.default")), ...levels.map((item) => h("option", {value: item, selected: item === level ? "" : null}, thinkingLabel(item, found)))].filter(Boolean));
      think.disabled = !levels.length;
      const sizes = found && found.context ? found.context.sizes : [];
      const wanted = sizes.some((item) => item.id === size) ? size : found && found.context ? found.context.default : 0;
      room.replaceChildren(...(sizes.length ? sizes.map((item) => h("option", {value: item.id, selected: item.id === wanted ? "" : null}, item.label)) : [h("option", {value: ""}, t("desk.set.thinking.default"))]));
      room.disabled = !sizes.length;
    }
    fillFor(now, info.thinking || (desk.chat && (desk.chat.fusion || desk.chat.effort)) || "", info.context);
    const save = (id, thinking, context) => SERVE.post("/api/setting", {task: desk.name, id, thinking, context}).then(() => SERVE.done(), (error) => { SERVE.failed(error); SERVE.done(); });
    const switching = h("p", {class: "set-warn", hidden: true});
    const warnSwitch = () => {  // the next message moves the chat to another model: its cache is of no use there
      const from = running, to = pick.value, name = (id) => (models.find((item) => item.id === id) || {}).name || id;
      switching.hidden = !(from && to && from !== to);
      switching.textContent = switching.hidden ? "" : t("desk.set.model.switch", {from: name(from), to: name(to)});
    };
    warnSwitch();
    pick.addEventListener("change", () => { fillFor(pick.value, "", 0); save(pick.value, "", 0); warnSwitch(); });  // a new model starts at its own default level and size
    think.addEventListener("change", () => save(pick.value, think.value, Number(room.value) || 0));
    room.addEventListener("change", () => save(pick.value, think.value, Number(room.value) || 0));
    const hostSetting = (key, label) => {  // offered by the host, told to it at once; it holds from the next turn
      const found = (info.options || {})[key];
      if (!found) return null;
      const select = h("select", {"aria-label": label}, found.choices.map((item) => h("option", {value: item.id, selected: item.id === found.value ? "" : null}, item.label)));
      select.addEventListener("change", () => SERVE.post("/api/chatconfig", {task: desk.name, [key]: select.value}).then(() => SERVE.done(), (error) => { SERVE.failed(error); SERVE.done(); }));
      return h("label", {class: "set-field"}, h("span", {class: "sub"}, label), select);
    };
    const otherMode = () => {  // Plan and Autopilot are not offered here: a task has its own plan and autorun. One set in VS Code is shown, with the way back
      const found = (info.options || {}).mode;
      if (!found || !found.value || found.value === "interactive") { leavingMode = false; return null; }
      if (leavingMode) return null;  // pressed: the host tells the new mode a moment later, and the page must not look as if nothing happened
      const back = h("button", {type: "button", class: "chip"}, t("desk.set.mode.back"));
      const field = h("span", {class: "set-field", title: t("desk.set.mode.tip")}, h("span", {class: "sub"}, t("desk.set.mode")), h("span", null, (found.choices.find((item) => item.id === found.value) || {}).label || found.value), back);
      back.addEventListener("click", () => {
        leavingMode = true;
        field.remove();
        SERVE.post("/api/chatconfig", {task: desk.name, mode: "interactive"}).then(() => SERVE.done(), (error) => { leavingMode = false; SERVE.failed(error); SERVE.done(); });
      });
      return field;
    };
    return h("section", {class: "card chatbar settings", title: t("desk.set.note")}, h("span", {class: "chat-k"}, t("desk.set.label")),
      h("label", {class: "set-field"}, h("span", {class: "sub"}, t("desk.set.model")), pick), h("label", {class: "set-field"}, h("span", {class: "sub"}, t("desk.set.thinking")), think),
      h("label", {class: "set-field"}, h("span", {class: "sub"}, t("desk.set.context")), room), switching, h("p", {class: "set-tip"}, t("desk.set.thinking.hint")), otherMode(), hostSetting("autoApprove", t("desk.set.permission")),
      h("p", {class: "sub set-note", title: t("desk.set.note")}, t("desk.set.note")));
  }

  // "Open to the agent" (1.7.6): a setting of the task at the head of its page, beside Independent review. One chip per environment the protocol knows; clickable only when a
  // system of the company pack reaches it; prod is never a choice. A click is `harness task allow --env <e> --on` (or --off): no code, it can be closed at once. The agent's writes and
  // procedures on that environment's listed systems then run without the outbox. Not drawn when no system is listed.
  const DOOR = ["M3 14V3.5A1.5 1.5 0 0 1 4.5 2h5A1.5 1.5 0 0 1 11 3.5V14", "M11 6h2.5v8H11", "M3 14h10.5", "M8 8.5h.01"];
  let closeEnvs = null;
  document.addEventListener("click", (event) => { if (closeEnvs && !event.target.closest(".tk-env")) closeEnvs(); });
  document.addEventListener("keydown", (event) => { if (closeEnvs && event.key === "Escape") closeEnvs(); });
  function envButton() {
    const found = desk.allow;
    closeEnvs = null;
    if (!found || !found.envs || !found.envs.length) return null;
    const open = found.envs.filter((item) => item.open);
    const can = served() && full.status === "open" && SERVE.runs("task allow");
    const chips = found.envs.map((item) => {
      const listed = item.systems.length > 0;
      const tip = !listed ? t("desk.set.open.none", {env: item.env}) : item.open ? t("desk.set.open.close", {env: item.env, systems: item.systems.join(", ")}) : t("desk.set.open.open", {env: item.env, systems: item.systems.join(", ")});
      const chip = h("button", {type: "button", class: "chip env" + (item.open ? " on" : ""), "aria-pressed": item.open ? "true" : "false", title: tip, disabled: listed && can ? null : "disabled"}, item.env + (item.open ? " ✓" : ""));
      chip.addEventListener("click", () => {
        chips.forEach((node) => { node.disabled = true; });
        SERVE.post("/api/act", {action: "task allow", task: desk.name, env: item.env, runner: item.open ? "off" : "on", step: "act"}).then(() => SERVE.done(), (error) => { SERVE.failed(error); SERVE.done(); });
      });
      return chip;
    });
    const never = (found.never || []).map((env) => h("span", {class: "chip env never", title: t("desk.set.open.never", {env})}, env));
    const note = open.length ? h("p", {class: "set-tip"}, t("desk.set.open.note", {envs: open.map((item) => item.env).join(", "), systems: [...new Set(open.flatMap((item) => item.systems))].join(", ")})) : null;
    const pop = h("div", {class: "rv-pop", hidden: true}, h("b", null, t("desk.set.open")), h("p", {class: "sub"}, t("desk.set.open.tip")), h("div", {class: "chips env-chips"}, chips, never), note,
      can ? null : h("p", {class: "set-warn"}, t("desk.set.open.cannot")));
    const button = h("button", {type: "button", class: "rv-btn" + (open.length ? " on" : ""), "aria-haspopup": "dialog", "aria-expanded": "false", title: t("desk.set.open.tip")},
      icon(DOOR, 14), h("span", {class: "rv-name"}, t("desk.set.open")), h("b", null, open.length ? open.map((item) => item.env).join(", ") : t("desk.set.open.off")));
    const show = (on) => { pop.hidden = !on; button.setAttribute("aria-expanded", String(on)); closeEnvs = on ? () => show(false) : null; if (on) inView(pop); };
    button.addEventListener("click", () => show(pop.hidden));
    return [button, pop];
  }

  // "Independent review" (1.6.33): a setting of the task, at the head of its page, not of a message. A click runs `task review set`, as at a terminal; `[review]=n` in a prompt still does the same, and is not shown.
  // It is the task's, like the VS Code pill: it stays at the head of an earlier round too (1.6.109), says there that it sets the current round, and is gone only when the task is closed.
  const SHIELD = ["M8 1.8l4.8 1.9v3.7c0 3-2 5.5-4.8 6.8-2.8-1.3-4.8-3.8-4.8-6.8V3.7L8 1.8z", "M5.8 8l1.6 1.6 2.9-3"];
  let closeReview = null;
  document.addEventListener("click", (event) => { if (closeReview && !event.target.closest(".tk-rv")) closeReview(); });
  document.addEventListener("keydown", (event) => { if (closeReview && event.key === "Escape") closeReview(); });

  // A pop under a button of the head stays in the window: with the round tabs before it the button can sit in the middle of a narrow window, and the pop would run off the edge.
  function inView(pop) {
    pop.style.transform = "";
    const box = pop.getBoundingClientRect(), edge = 16, width = document.documentElement.clientWidth;
    const shift = box.right > width - edge ? width - edge - box.right : box.left < edge ? edge - box.left : 0;
    if (shift) pop.style.transform = "translateX(" + Math.round(shift) + "px)";
  }
  function reviewButton() {
    const info = full.settings;
    closeReview = null;
    if (!served() || !info || full.status !== "open") return null;
    const can = SERVE.runs("review set");
    const choices = [];
    for (let n = 0; n <= info.max_n; n++) {
      const choice = h("button", {type: "button", class: "chip" + (n === info.n ? " on" : ""), "aria-pressed": n === info.n ? "true" : "false", disabled: can ? null : "disabled"}, n ? String(n) : t("desk.rv.off"));
      choice.addEventListener("click", () => {
        if (n === info.n) return;
        choices.forEach((item) => { item.disabled = true; });
        SERVE.post("/api/act", {action: "review set", task: desk.name, n, step: "act"}).then(() => SERVE.done(), (error) => { SERVE.failed(error); SERVE.done(); });
      });
      choices.push(choice);
    }
    const pop = h("div", {class: "rv-pop", hidden: true}, h("b", null, t("desk.rv.button")), desk.past ? h("p", {class: "set-tip"}, t("desk.rv.current", {round: full.round})) : null, h("p", {class: "sub"}, t("desk.rv.hint")), h("p", {class: "set-warn"}, t("desk.rv.cost")), h("div", {class: "chips"}, choices));
    const button = h("button", {type: "button", class: "rv-btn" + (info.n ? " on" : ""), "aria-haspopup": "dialog", "aria-expanded": "false", title: t("desk.rv.hint")},
      icon(SHIELD, 14), h("span", {class: "rv-name"}, t("desk.rv.button")), h("b", null, info.n ? String(info.n) : t("desk.rv.off")));
    const show = (on) => { pop.hidden = !on; button.setAttribute("aria-expanded", String(on)); closeReview = on ? () => show(false) : null; if (on) inView(pop); };
    button.addEventListener("click", () => show(pop.hidden));
    return [button, pop];
  }

  // "Drafts" (1.6, B77): the person's notes for the next message the board sends. Ticked notes go at the end of it (the send panel shows them); a note is cleared only after a send went.
  // The notes are read and written through the paired POST /api/draft only: they are not in the page data, a saved copy or a digest. One node is kept between redraws, so a half-typed note stays.
  const drafts = {items: null, max: 50, editing: "", text: "", add: "", error: "", busy: false, node: null, loading: false, stale: false};

  function draftCall(body) {
    drafts.busy = true; drafts.error = ""; paintDrafts();
    return SERVE.post("/api/draft", {task: desk.name, ...body}).then((data) => {
      drafts.busy = false;
      drafts.items = data.result.items; drafts.max = data.result.max || drafts.max;
      paintDrafts();
      return true;
    }, (error) => {
      drafts.busy = false; drafts.error = (error && error.message) || String(error);
      if (!error.offline && !(error.data && error.data.unpaired)) draftCall({op: "list"});  // a gone draft: read the list again, so the page shows what is there
      else paintDrafts();
      return false;
    });
  }

  function paintDrafts() {
    if (!drafts.node) return;
    const items = drafts.items || [];
    const used = items.filter((item) => item.use).length;
    const input = h("input", {type: "text", class: "send-body draft-add", placeholder: t("desk.drafts.ph"), maxlength: 2000, value: drafts.add});
    const add = h("button", {type: "button", class: "act", disabled: drafts.busy || !drafts.add.trim() || items.length >= drafts.max ? "disabled" : null}, t("desk.drafts.add"));
    const submit = () => { if (!drafts.add.trim() || drafts.busy) return; const text = drafts.add; draftCall({op: "add", text}).then((ok) => { if (ok) { drafts.add = ""; paintDrafts(); } }); };
    input.addEventListener("input", () => { drafts.add = input.value; add.disabled = drafts.busy || !drafts.add.trim() || items.length >= drafts.max; });
    input.addEventListener("keydown", (event) => { if (isEnter(event)) submit(); });
    add.addEventListener("click", submit);
    const rows = items.map((item) => {
      const tick = h("input", {type: "checkbox", checked: item.use ? "" : null, disabled: drafts.busy ? "disabled" : null, title: t("desk.drafts.use.tip"), "aria-label": t("desk.drafts.use.tip")});
      tick.checked = item.use;
      tick.addEventListener("change", () => draftCall({op: "use", id: item.id, use: tick.checked}));
      if (drafts.editing === item.id) {
        const box = h("input", {type: "text", class: "send-body", maxlength: 2000, value: drafts.text});
        const save = h("button", {type: "button", class: "act", disabled: drafts.text.trim() ? null : "disabled"}, t("desk.drafts.save"));
        const cancel = h("button", {type: "button", class: "act"}, t("desk.drafts.cancel"));
        box.addEventListener("input", () => { drafts.text = box.value; save.disabled = !drafts.text.trim(); });
        const commit = () => { if (!drafts.text.trim()) return; draftCall({op: "edit", id: item.id, text: drafts.text}).then((ok) => { if (ok) { drafts.editing = ""; paintDrafts(); } }); };
        box.addEventListener("keydown", (event) => { if (isEnter(event)) commit(); else if (event.key === "Escape") { drafts.editing = ""; paintDrafts(); } });
        save.addEventListener("click", commit);
        cancel.addEventListener("click", () => { drafts.editing = ""; paintDrafts(); });
        return h("li", {class: "draft-row editing"}, tick, box, save, cancel);
      }
      const edit = h("button", {type: "button", class: "act", disabled: drafts.busy ? "disabled" : null}, t("desk.drafts.edit"));
      const drop = h("button", {type: "button", class: "act", disabled: drafts.busy ? "disabled" : null}, t("desk.drafts.delete"));
      edit.addEventListener("click", () => { drafts.editing = item.id; drafts.text = item.text; paintDrafts(); });
      drop.addEventListener("click", () => draftCall({op: "delete", id: item.id}));
      return h("li", {class: "draft-row" + (item.use ? "" : " off")}, tick, h("span", {class: "draft-text"}, item.text), edit, drop);
    });
    drafts.node.replaceChildren(...[h("span", {class: "chat-k"}, t("desk.drafts.label")), h("p", {class: "sub set-note", title: t("desk.drafts.hint")}, t("desk.drafts.hint")),
      rows.length ? h("ul", {class: "draft-list"}, rows) : h("p", {class: "sub"}, drafts.items ? t("desk.drafts.none") : "..."),
      rows.length ? h("p", {class: "sub"}, t("desk.drafts.count", {count: items.length, used})) : null,
      h("div", {class: "row draft-new"}, input, add), drafts.error ? h("div", {class: "bad"}, ...SERVE.reasons(drafts.error)) : null].filter(Boolean));  // replaceChildren would write a null as the word "null"
    if (typeof REPLY !== "undefined") REPLY.count(items.length);  // the badge of the reply pill
  }

  function draftsBox() {
    if (!served() || desk.past || desk.status !== "open") return null;
    if (!drafts.node) drafts.node = h("section", {class: "card chatbar drafts"});
    paintDrafts();
    if ((drafts.items === null || drafts.stale) && !drafts.loading && !drafts.busy) { drafts.stale = false; drafts.loading = true; SERVE.ready.then(() => draftCall({op: "list"})).then(() => { drafts.loading = false; }); }  // after the pairing is settled: a call before it would be refused
    return drafts.node;
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
        Object.assign(form, {text: "", ran: "", images: []});
        if (!(desk.chat && desk.chat.bound)) return Object.assign(form, {busy: false, gave: data.result, told: false});
        return (form.pick ? form.pick.apply() : Promise.resolve()).then(() => SERVE.post("/api/send", {task: desk.name, kind: "answer", lang: "", note: "", body: data.result.message, step: "act"}))  // not sent: the saved results stay, and the message is there to copy
          .then(() => Object.assign(form, {busy: false, gave: data.result, told: true}), () => Object.assign(form, {busy: false, gave: data.result, told: false}));
      }, (error) => { form.busy = false; form.error = error.message; })
      .then(() => draw(true));
  }

  function resultForm() {
    const handed = desk.handoff || {};
    const env = form.env || handed.env || "";
    const field = (label, node) => h("label", {class: "field"}, h("span", {class: "sub"}, label), node);
    const text = h("textarea", {rows: 6, placeholder: t("desk.inbox.text.ph"), disabled: form.busy ? "" : null, "data-keep": "inbox.text"}, form.text);
    text.addEventListener("input", () => { form.text = text.value; });
    text.addEventListener("paste", (event) => {  // a screenshot pasted into the box becomes a picture; pasted text stays text
      const files = [...(event.clipboardData ? event.clipboardData.files : [])].filter((file) => /^image\//.test(file.type));
      if (files.length) { event.preventDefault(); addImages(files); }
    });
    const ran = h("textarea", {rows: 3, placeholder: t("desk.inbox.ran.ph"), disabled: form.busy ? "" : null, "data-keep": "inbox.ran"}, form.ran);
    ran.addEventListener("input", () => { form.ran = ran.value; });
    const where = h("input", {type: "text", value: env, maxlength: 12, class: "env-input", "data-keep": "inbox.env"});
    where.addEventListener("input", () => { form.env = where.value; });
    const pick = h("input", {type: "file", accept: "image/png,image/jpeg,image/gif,image/webp", multiple: "", style: "display:none"});
    pick.addEventListener("change", () => addImages([...pick.files]));
    const chooser = h("button", {type: "button", class: "act"}, t("desk.inbox.pick"));
    chooser.addEventListener("click", () => pick.click());
    const save = h("button", {type: "button", class: "act hot", disabled: form.busy ? "" : null}, form.busy ? t("desk.inbox.saving") : t(desk.chat && desk.chat.bound ? "desk.inbox.send" : "desk.inbox.save"));
    save.addEventListener("click", () => saveResults(where.value.trim()));
    if (desk.chat && desk.chat.bound && !form.pick && typeof CHAT !== "undefined") form.pick = CHAT.modelPick(desk.name);  // the model the agent reads the results with (1.6.101); made once, kept over redraws
    const thumbs = h("div", {class: "thumbs"}, form.images.map((item, index) => {
      const remove = h("button", {type: "button", class: "act", title: t("desk.inbox.remove")}, "×");
      remove.addEventListener("click", () => { URL.revokeObjectURL(item.url); form.images.splice(index, 1); draw(true); });
      return h("span", {class: "thumb"}, h("img", {src: item.url, alt: ""}), remove);
    }));
    return h("section", {class: "inbox"}, h("h3", null, t("desk.inbox.title")), h("p", {class: "hint"}, t("desk.inbox.hint")),
      form.gave ? h("div", {class: "inbox-done"}, h("p", {class: "hint"}, t(form.told ? "desk.inbox.told" : "desk.inbox.done", {folder: form.gave.folder})), form.told ? null : promptLine(form.gave.message)) : null,
      field(t("desk.inbox.env"), where), field(t("desk.inbox.text"), text), field(t("desk.inbox.ran"), ran),
      h("div", {class: "inbox-pictures"}, chooser, pick, thumbs),
      form.error ? h("p", {class: "hint bad"}, form.error) : null, desk.chat && desk.chat.bound && form.pick ? form.pick.node : null, h("div", {class: "inbox-save"}, save));
  }

  // A message the person sends to the agent in VS Code: one click copies it.
  function promptLine(text) {
    const button = h("button", {type: "button", class: "act", "data-label": t("desk.go.copy")}, t("desk.go.copy"));
    button.addEventListener("click", () => copyCommand(button, text));
    return h("div", {class: "prompt-line"}, h("code", null, text), button);
  }

  // --- what waits for the person --------------------------------------------------------------------------------------------
  // A wait that asks for a decision gets one strong card (approve the plan, confirm the requirement, approve the promote): the wait, what to do, the action, and a link to the tab where the
  // thing is read. Any other wait that has an action (confirm a command, answer a question, send, recover, the checks...) is listed in one quieter card. The card is above the tabs, so it is
  // there on every tab. A task that only runs, or is quiet, has no card: its words are on the Live tab.
  const needItems = () => desk.actions.filter((item) => !OPTIONAL.includes(item.action) && !TALK.includes(item.action));  // steer and stop are not a wait: they are on the Live tab
  const needsCard = () => canAct() && Boolean(needItems().length || desk.waiting || desk.paused_since || desk.state === "unheld");

  function waitNotes() {
    return [
      desk.req_changed ? h("p", {class: "hint bad"}, t("desk.req.changed")) : null,
      desk.req_unconfirmed && desk.req_placeholders ? h("p", {class: "hint bad"}, t("desk.req.placeholders", {n: desk.req_placeholders})) : null,
      desk.test && desk.test.reopen ? h("p", {class: "hint bad"}, t("desk.test.reopen", {dev: desk.test.reopen, envs: desk.test.failed.join(", ")})) : null,
      desk.state === "working" && served() ? h("p", {class: "hint"}, t(desk.chat && desk.chat.bound ? "desk.busy.note" : "desk.busy.note.nochat")) : null,
      desk.state === "waiting" && !desk.held && !chatNew(actionRow()) ? h("p", {class: "hint"}, t("desk.unheld.note")) : null,
    ];
  }

  function jumpButton(tab, label) {
    if (!visible(tab) || tab === current) return null;
    const button = h("button", {type: "button", class: "act tk-jump"}, label + " →");
    button.addEventListener("click", () => goTab(tab));
    return button;
  }

  // "It has waited for you...": on a live page the time moves with the one clock of the page (status.js), so it is the number of the stage card to the second. A saved copy says the time as of then.
  function waitedLine() {
    if (desk.waited_s === null || desk.waited_s === undefined) return null;
    const from = saved ? NaN : Date.parse(desk.waiting_from);
    if (isNaN(from)) return h("span", {class: "sub tk-waited"}, t("desk.waited", {time: clock(desk.waited_s)}));
    const [before, after] = t("desk.waited", {time: "\n"}).split("\n");
    Status.clock();
    return h("span", {class: "sub tk-waited st-run", "data-since": String(from)}, before, h("span", {class: "st-time"}, clock(Math.max(0, Math.floor((Date.now() - from) / 1000)))), after);  // the steady page keeps an old `waited_s`
  }

  const CARD_WORDS = {"confirm-req": "task.waiting.req", "approve-plan": "task.waiting.plan", "approve-promote": "task.waiting.promote"};  // two cards can stand together: each says what it is about

  function strongCard(item, notes) {
    const row = actionRow();
    const tab = JUMPS[item.action];
    return h("section", {class: "tk-need strong", "data-action": item.action},
      h("div", {class: "tk-need-h"}, tag(CARD_WORDS[item.action] ? t(CARD_WORDS[item.action]) : desk.waiting ? waitText(desk) : t("desk.actions.title"), "hot"), waitedLine()),
      h("p", {class: "tk-need-p"}, hintOf(item)), notes,
      h("div", {class: "tk-need-go"}, talkButtons(row, item), jumpButton(tab, t("desk.jump." + tab))));
  }

  // The next step of a card that names it is a button on that card, not only in the menu: resume a task put aside, close one that was committed.
  function resumeButton() {
    const wanted = desk.paused_since ? "resume" : desk.waiting_why === "commit" ? "close" : "";
    const item = wanted ? desk.actions.find((entry) => entry.action === wanted) : null;
    return item ? actionButton(actionRow(), item, "big") : null;
  }

  // What the chat asks, without opening anything: a bubble by the title of the card, and the pointer on it shows the command or the question. The node is kept between drawings, or a redraw would close the card it opened.
  const BUBBLE = ["M2.5 5A2.5 2.5 0 0 1 5 2.5h6A2.5 2.5 0 0 1 13.5 5v3.5A2.5 2.5 0 0 1 11 11H7.5L4.5 13.5V11A2.5 2.5 0 0 1 2.5 8.5z", "M5.5 6.75h.01M8 6.75h.01M10.5 6.75h.01"];
  let bubbleNode = null;
  function askCard() {
    const found = desk.ask;
    if (!found) return {sig: "", build: () => null};
    const asked = (item) => h("div", {class: "tk-peek-q"}, item.title !== found.message ? h("b", null, item.title) : null, item.message && item.message !== item.title ? h("p", {class: "sub"}, item.message) : null,
      item.options.length ? h("ul", null, item.options.map((option) => h("li", null, option.label))) : null, item.free ? h("p", {class: "sub"}, t("desk.ask.peek.free")) : null);
    return {sig: JSON.stringify(found), build: () => h("div", {class: "tk-peek"}, found.kind === "confirm"
      ? [found.title ? h("b", null, found.title) : null, found.intention ? h("p", {class: "sub"}, found.intention) : null, h("pre", {class: "send-preview"}, found.command || "-"), h("p", {class: "sub"}, t("board.ask.call", {tool: found.tool || "-", id: found.tool_call_id}))]
      : [h("b", null, found.message), (found.questions || []).map(asked)],
    found.count > 1 ? h("p", {class: "sub"}, t("board.ask.more", {count: found.count - 1})) : null)};
  }
  function askBubble() {
    if (!desk.ask || !served()) return null;
    if (!bubbleNode) bubbleNode = Status.card(h("span", {class: "tk-bubble", "data-card-up": "1"}, icon(BUBBLE, 15)), askCard, t("desk.ask.peek"));  // above it: the button to answer is below
    return bubbleNode;
  }

  function otherCard(items, notes) {
    const row = actionRow();
    const idle = items.length ? null : quiet();
    const jump = served() && ["tests", "run"].includes(desk.waiting_why) ? jumpButton("live", t("desk.jump.live")) : null;  // the form for the results is on the Live tab
    return h("section", {class: "tk-need"},
      h("div", {class: "tk-need-h"}, h("div", {class: "tk-need-t"}, h("h2", null, idle ? idle.title : t("desk.actions.title")), askBubble()), items.length || desk.waiting ? waitedLine() : null),
      notes,
      idle ? [h("p", {class: "hint"}, idle.hint), resumeButton(), idle.prompt ? promptLine(idle.prompt) : null, jump]
        : h("div", {class: "tk-acts"}, items.map((item) => h("div", {class: "tk-act"}, talkButtons(row, item), h("p", {class: "hint"}, hintOf(item))))));
  }

  function waitBand() {
    if (desk.past) return pastNote();
    if (!needsCard()) return null;
    const items = needItems();
    const strong = items.filter((item) => JUMPS[item.action]);
    const other = items.filter((item) => !JUMPS[item.action]);
    const notes = waitNotes().filter(Boolean);
    const cards = strong.map((item, index) => strongCard(item, index ? [] : notes));
    if (other.length || !strong.length) cards.push(otherCard(other, strong.length ? [] : notes));
    return cards;
  }

  // The words for a task that has nothing waiting on it, on the Live tab: closed, not started, quiet, or at work with nothing to decide.
  function livePlain() {
    if (desk.past || saved) return null;
    if (desk.status !== "open") return h("div", null, h("p", {class: "hint top"}, t(desk.status === "new" ? (desk.state === "broken" ? "desk.actions.broken" : "desk.actions.new") : "desk.actions.closed")), typeof ROUNDS !== "undefined" ? ROUNDS.node : null);  // the stream is hidden here; the rounds can still be read
    if (needsCard()) return null;
    const idle = quiet();
    return h("section", {class: "tk-quiet"}, h("h2", null, idle.title), h("p", {class: "hint"}, idle.hint), resumeButton(), idle.prompt ? promptLine(idle.prompt) : null, waitNotes());
  }

  // --- the Live tab --------------------------------------------------------------------------------------------------------
  // The stream (live.js) is a node of its own above this pane, kept between drawings; what is drawn here is what does not belong in a stream: the words for a task with nothing to follow or nothing
  // waiting, and the form for the results of a run (a test or a run the agent asked for; it is here, under the stream, for as long as that wait lasts). The things said to the agent (the reply, steer,
  // stop, the task settings, the drafts) are in the reply panel (reply.js) on every tab. The cards of what needs the person are in the stream, where the agent stopped.
  const hasStream = () => typeof LIVE !== "undefined" && served() && !desk.past && desk.status === "open";
  function livePane() {
    const parts = [];
    parts.push(hasStream() ? null : h("p", {class: "hint top"}, t("desk.live.hint")));
    parts.push(livePlain());
    if (served() && canAct() && ["tests", "run"].includes(desk.waiting_why)) parts.push(resultForm());
    return parts;
  }

  // What the Live stream and the reply panel need from this drawing.
  function paintLive() {
    const chat = served() && !desk.past ? desk.chat : null;
    const onLive = current === "live" && hasStream();
    if (typeof LIVE !== "undefined" && served()) {
      LIVE.config({task: desk.task, chat, off: desk.status === "open" && !desk.past ? "" : desk.status || "closed"});
      LIVE.want("tab", onLive);
      LIVE.visible(onLive);
    }
    const bound = Boolean(chat && chat.bound);
    const into = onLive && bound;  // the cards of a wait go into the stream where the agent stopped; with no chat to show they stay above the tabs
    const cards = waitBand();
    fill(ui.wait, into ? null : cards);
    ui.wait.hidden = !ui.wait.firstChild;
    if (typeof LIVE !== "undefined" && served()) LIVE.needs(into ? cards : null);
    if (typeof REPLY !== "undefined" && served()) {
      const show = hasStream() && bound;
      if (show) draftsBox();  // loads the drafts (the badge counts them) even while the panel is shut
      REPLY.update({name: desk.name, show, reply: desk.reply_lang, state: chat ? chat.state || "" : "", count: drafts.items ? drafts.items.length : 0, settings: () => settingsRow(), settingsSig: JSON.stringify([desk.settings, desk.status, chat && [chat.model, chat.effort]]), drafts: drafts.node, saveDraft: (text) => draftCall({op: "add", text})});
    }
  }

  // --- the tabs, by function ------------------------------------------------------------------------------------------------
  // The top row: Live and the groups. The group that holds the open tab shows a second row. A group remembers the tab it was left on (for this viewer, in this browser).
  const REMEMBER = "harness.desk.tabs";
  let lastTab = {};
  try { lastTab = JSON.parse(localStorage.getItem(REMEMBER) || "{}") || {}; } catch (error) { lastTab = {}; }  // not allowed here: kept until the page closes
  function remember(tab) {
    if (lastTab[groupOf(tab).id] === tab) return;
    lastTab[groupOf(tab).id] = tab;
    try { localStorage.setItem(REMEMBER, JSON.stringify(lastTab)); } catch (error) { /* kept until the page closes */ }
  }
  function goTab(tab) {
    if (!visible(tab)) return;
    current = tab;
    remember(tab);
    history.replaceState(null, "", hashOf(tab));
    draw(false);
    window.scrollTo(0, 0);
    if (tab === "trace" && typeof SERVE !== "undefined" && DATA.serve.refresh) pull();
  }

  // What a tab shows next to its name: a count, and whether something in it waits for the person.
  function tabInfo(tab) {
    const name = t("desk.tab." + tab);
    const mine = canAct();
    if (tab === "req") return {name, bang: desk.req_unconfirmed};  // waits for the person's confirmation
    if (tab === "plan") return {name, bang: mine && desk.waiting_why === "plan"};
    if (tab === "todo") return {name, count: desk.todo.total ? desk.todo.done + "/" + desk.todo.total : ""};
    if (tab === "changes") return {name, count: desk.changes.files.length ? String(desk.changes.files.length) : "", bang: Boolean(desk.commit && !desk.commit.written) || (mine && desk.waiting_why === "promote")};
    if (tab === "test") return {name, count: desk.test.passed + "/" + desk.test.total};
    if (tab === "review") return {name, count: desk.review.n ? desk.review.passes + "/" + desk.review.n : String(desk.review.rounds.length)};
    if (tab === "history") return {name, count: String(desk.history.length)};
    if (tab === "trace") return {name, count: desk.trace.entries.length + (desk.trace.cut ? "+" : "")};
    if (tab === "docs") return {name, count: String(extra().length)};
    if (tab === "files") return {name, count: String(desk.files.length)};
    if (tab === "intake") { const reads = desk.intake.files.filter((item) => !item.original && !item.report && !item.path.startsWith("media/")).length; return {name, count: reads ? String(reads) : ""}; }  // the same set as "What the agent reads"
    return {name};
  }
  const tabText = (info) => info.name + (info.count ? " " + info.count : "") + (info.bang ? " !" : "");

  // The groups that have a tab to show: {id, tabs (the visible ones), single (a group of one goes straight to its tab)}.
  function shownGroups() {
    return GROUPS.map((group) => ({id: group.id, tabs: group.tabs.filter(visible)})).filter((group) => group.tabs.length);
  }
  const groupName = (id) => t(id === "overview" ? "desk.tab.overview" : "desk.group." + id);

  function nav() {
    const groups = shownGroups();
    const open = groupOf(current);
    const top = h("div", {class: "tk-top", role: "tablist", "aria-label": t("desk.tabs.label")}, groups.map((group) => {
      const single = group.tabs.length === 1;
      const infos = group.tabs.map(tabInfo);
      const info = single ? infos[0] : {name: groupName(group.id), bang: infos.some((item) => item.bang)};
      const on = group.id === open.id;
      const target = single ? group.tabs[0] : (group.tabs.includes(lastTab[group.id]) ? lastTab[group.id] : group.tabs[0]);
      const summary = single ? tabText(infos[0]) : t("desk.tab.group", {group: info.name, tabs: infos.map(tabText).join(", ")});
      const button = h("button", {type: "button", role: "tab", class: "tk-tab" + (on ? " on" : "") + (single ? "" : " has-sub"), "aria-selected": on ? "true" : "false", tabindex: on ? "0" : "-1", "data-key": "g:" + group.id, title: summary, "aria-label": summary},
        info.name, info.count ? h("span", {class: "tk-n"}, info.count) : null, info.bang ? h("i", {class: "tk-bang", title: t("desk.tab.bang")}) : null);
      button.addEventListener("click", () => goTab(on && !single ? current : target));
      return button;
    }));
    const here = groups.find((group) => group.id === open.id);
    const rows = [top];
    if (here && here.tabs.length > 1) {
      rows.push(h("div", {class: "tk-sub", role: "tablist", "aria-label": groupName(here.id)}, here.tabs.map((tab) => {
        const info = tabInfo(tab);
        const on = tab === current;
        const button = h("button", {type: "button", role: "tab", class: "tk-tab" + (on ? " on" : ""), "aria-selected": on ? "true" : "false", tabindex: on ? "0" : "-1", "data-key": "t:" + tab, "aria-label": tabText(info)},
          info.name, info.count ? h("span", {class: "tk-n"}, info.count) : null, info.bang ? h("i", {class: "tk-bang", title: t("desk.tab.bang")}) : null);
        button.addEventListener("click", () => goTab(tab));
        return button;
      })));
    }
    rows.forEach((row) => row.addEventListener("keydown", moveInTabs));
    return rows;
  }

  // Arrow keys move along a row and open the tab; Home and End go to its ends; down from the top row goes into the second, up comes back.
  function moveInTabs(event) {
    const button = event.target instanceof Element ? event.target.closest("[role=tab]") : null;
    if (!button || event.metaKey || event.ctrlKey || event.altKey) return;
    const row = button.parentElement;
    const list = Array.from(row.querySelectorAll("[role=tab]"));
    const at = list.indexOf(button);
    let next = null;
    if (event.key === "ArrowRight") next = list[(at + 1) % list.length];
    else if (event.key === "ArrowLeft") next = list[(at - 1 + list.length) % list.length];
    else if (event.key === "Home") next = list[0];
    else if (event.key === "End") next = list[list.length - 1];
    else if (event.key === "ArrowDown" && row.classList.contains("tk-top")) next = ui.tabs.querySelector(".tk-sub [aria-selected=true]");
    else if (event.key === "ArrowUp" && row.classList.contains("tk-sub")) next = ui.tabs.querySelector(".tk-top [aria-selected=true]");
    if (!next) return;
    event.preventDefault();
    next.focus();
    if (next.parentElement === row) next.click();  // moving along a row opens the tab (the page then puts the focus on the same tab again)
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
        item.stale ? [" ", tag(t("desk.test.defects.stale", {env: item.env}), "hot long"), " ", defectSync()] : null),
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
      const found = block.t === "h" && block.level === 2 ? /^Run (\d+)(?:\s*\(E\d+\))?$/i.exec(plain(block.spans)) : null;  // `Run 2 (E7)`: the evidence number (1.7.3)
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

  // Who runs an environment (1.7.2): the guide may propose the agent; only the person lets it, with one click (no code), and can take it back. Served pages only.
  function runnerLine(env) {
    const who = env.runner || {proposed: "person", granted: false};
    const word = who.granted ? t("desk.test.runner.agent") : who.proposed === "agent" ? t("desk.test.runner.proposed") : t("desk.test.runner.person");
    const line = h("p", {class: "sub runner"}, tag(word, who.granted ? "good" : who.proposed === "agent" ? "hot" : ""));
    if (served() && full.status === "open" && SERVE.runs("test runner")) {
      const button = h("button", {type: "button", class: "chip" + (who.granted ? "" : " on"), title: t("desk.test.runner.hint", {env: env.name})}, who.granted ? t("desk.test.runner.back") : t("desk.test.runner.let", {env: env.name}));
      button.addEventListener("click", () => {
        button.disabled = true;
        SERVE.post("/api/act", {action: "test runner", task: desk.name, env: env.name, runner: who.granted ? "person" : "agent", step: "act"}).then(() => SERVE.done(), (error) => { SERVE.failed(error); SERVE.done(); });
      });
      line.append(" ", button);
    }
    return line;
  }

  function envResults(env) {
    const verdict = env.verdict ? tag(env.verdict, env.verdict === "PASS" ? "good" : env.verdict === "FAIL" ? "bad" : "hot") : tag(env.waits ? t("desk.test.waits") : t("desk.test.noresult"), env.waits ? "hot" : "");
    const body = env.results ? h("article", {class: "md"}, runTabs("env:" + env.name, env.results.blocks, env.runs, false) || blocks(env.results.blocks), env.results.cut ? h("p", {class: "sub"}, t("desk.cut")) : null, evidenceThumbs(env))
      : h("p", {class: "sub"}, env.waits ? t("desk.test.waiting", {env: env.name}) : t("desk.test.noresult"));
    return h("section", {class: "round " + (env.state === "failed" ? "fail" : env.state === "done" ? "pass" : "")},
      h("div", {class: "round-head"}, h("strong", null, env.name), " ", verdict, env.file ? [" ", h("span", {class: "sub"}, "TEST/" + env.file)] : null,
        env.ignored.length ? [" ", tag(t("desk.test.ignored", {files: env.ignored.join(", ")}), "hot")] : null), runnerLine(env), body);
  }

  // The Files tab: what is in REQ/, REF/, DEV/ and RUNS/ (sub-folders too). The list is in the page; a file comes when it is opened (a saved copy has the small ones in it).
  let fileOpen = "";
  const markText = () => ({create: t("desk.files.mark.create"), modify: t("desk.files.mark.modify"), delete: t("desk.files.mark.delete"), unchanged: t("desk.files.mark.unchanged")});  // written out, so each message key is found by a search
  const folded = new Set();  // folders folded in the tree (their full path); kept while the page is open
  const fileCache = {};
  const ROOT_HINT = {REQ: "desk.files.root.req", REF: "desk.files.root.ref", INBOX: "desk.files.root.inbox", DEV: "desk.files.root.dev", RUNS: "desk.files.root.runs"};
  const rootHint = (root) => ROOT_HINT[root.toUpperCase()] || (/^DEV_R\d+$/i.test(root) ? ROOT_HINT.DEV : "desk.files.hint");  // DEV_r<n>: the files an earlier round wrote back
  const size = fileSize;

  // One of a few to choose from over a table: Table or Text, a sheet of a workbook.
  const pickChip = (label, on, call, title) => {
    const button = h("button", {type: "button", class: "chip" + (on ? " on" : ""), "aria-pressed": on ? "true" : "false", title: title || null}, label);
    button.addEventListener("click", call);
    return button;
  };

  const fileLink = (item) => h("a", {href: "/download/" + encodeURIComponent(desk.name) + "/" + item.path.split("/").map(encodeURIComponent).join("/"), download: ""}, t("desk.files.download"));

  // An original kept by Intake: the files made from it (they open here) and the original itself to save.
  function originalExtras(item) {
    if (!item.path.startsWith("REQ/originals/")) return null;
    const made = (item.made || []).map((path) => {
      const a = h("a", {href: "#files", title: path}, path.slice(4));
      a.addEventListener("click", (event) => { event.preventDefault(); fileOpen = path; draw(false); });
      return a;
    });
    return h("p", {class: "sub"}, made.length ? [t("desk.files.made") + " ", made.map((a, index) => [index ? ", " : "", a]), " · "] : null, served() ? fileLink(item) : null);
  }

  // A workbook is opened outside the page: Excel, not VS Code.
  const fileSave = (item) => originalExtras(item) || (served() ? h("p", {class: "sub"}, fileLink(item)) : null);

  // A table of the Files tab: what the person did with it (table or text, the search, how many rows) stays while the page is open. Text cut short ends inside a row: that row is left out.
  const fileTables = {};
  function fileTable(key, text, cut, delimiter) {
    if (!fileTables[key]) {
      const edit = {text, delimiter, cut};
      csvLoad(edit, true);
      if (cut) edit.rows.pop();
      fileTables[key] = edit;
    }
    return fileTables[key];
  }

  function textFile(item, found) {
    if (!found.text.trim()) return h("p", {class: "sub"}, t("desk.doc.empty"));
    const language = Highlight.fileLanguage(item.path);
    const cut = found.cut ? h("p", {class: "sub"}, t("desk.cut")) : null;
    if (language !== "csv" && language !== "tsv") return [codeBlock(found.text, language), cut];
    const edit = fileTable(item.path, found.text, found.cut, language === "tsv" ? "\t" : ",");
    const choice = ([view, label]) => pickChip(label, edit.view === view, () => { edit.view = view; draw(true); });
    const views = edit.rows.length ? h("div", {class: "table-picks"}, [["table", t("desk.intake.view.table")], ["text", t("desk.intake.view.text")]].map(choice)) : null;
    return [views, edit.view === "table" ? csvTable(edit, item.path) : codeBlock(found.text, language), cut];
  }

  // A workbook: its sheets in a row, the open one as a table, and under it what the table leaves out.
  const fileSheet = {};  // a workbook's path -> the number of the sheet open in it
  const LEFT_OUT = {hidden: "desk.files.sheet.skip.hidden", empty: "desk.files.sheet.skip.empty"};  // anything else is a chart sheet or a macro sheet
  function sheetView(item, found) {
    const sheets = found.sheets;
    const number = Math.min(fileSheet[item.path] || 0, sheets.length - 1);
    const open = sheets[number];
    const key = item.path + "#" + number;
    const table = open ? fileTable(key, open.text, open.cut, ",") : null;
    const tab = (sheet, index) => pickChip(sheet.name, index === number, () => { fileSheet[item.path] = index; draw(true); }, sheet.name);
    const left = found.left_out.map((sheet) => t(LEFT_OUT[sheet.why] || "desk.files.sheet.skip.other", {name: sheet.name})).join(", ");
    const notes = [
      open && (open.hidden_rows || open.hidden_columns) ? t("desk.files.sheet.hidden", {rows: open.hidden_rows, columns: open.hidden_columns}) : "",
      open && open.cut ? t("desk.files.sheet.cut", {shown: Math.max(0, table.rows.length - 1), rows: open.rows - 1}) : "",
      left ? t("desk.files.sheet.left", {names: left}) : "",
    ].filter(Boolean);
    return [sheets.length ? h("div", {class: "table-picks"}, sheets.map(tab)) : h("p", {class: "sub"}, t("desk.files.sheet.empty")), open ? csvTable(table, key) : null,
      notes.length ? h("p", {class: "sub"}, notes.join(" ")) : null, fileSave(item)];
  }

  const FILE_KINDS = ["markdown", "text", "sheet"];  // what the page asks the server for
  function fileView(item) {
    if (item.kind === "image") {
      return picture({src: item.path, alt: item.path.split("/").pop(), data: item.data || ""});
    }
    const found = fileCache[item.path] || item.doc;
    if (!found && !FILE_KINDS.includes(item.kind)) return [h("p", {class: "sub"}, t("desk.files.other", {size: size(item.size)})), originalExtras(item)];  // never asked for: it was "Loading…" for good
    if (!found && !served()) return h("p", {class: "sub"}, t("desk.files.saved"));  // a saved copy took in only the small files
    if (!found) return h("p", {class: "sub"}, fileCache[item.path] === null ? t("desk.files.failed") : t("desk.files.loading"));
    if (found.kind === "markdown") return h("article", {class: "md"}, runTabs("file:" + item.path, found.blocks, null, true) || blocks(found.blocks), found.cut ? h("p", {class: "sub"}, t("desk.cut")) : null);
    if (found.kind === "text") return textFile(item, found);
    if (found.kind === "sheet") return sheetView(item, found);
    if (found.note) return [h("p", {class: "sub"}, found.note === "big" ? t("desk.files.sheet.big", {size: size(found.size)}) : t("desk.files.sheet.failed")), fileSave(item)];
    return h("p", {class: "sub"}, t("desk.files.other", {size: size(found.size)}));
  }

  // Asked once: the key stays while the answer is on its way (a workbook takes seconds, and a redraw must not ask again) and after a failure (the page says to reload).
  function fileLoad(item) {
    if (item.doc || item.path in fileCache || !served() || !FILE_KINDS.includes(item.kind)) return;
    fileCache[item.path] = undefined;
    SERVE.post("/api/file", {task: desk.name, path: item.path}).then((data) => { fileCache[item.path] = data.file; draw(true); }, () => { fileCache[item.path] = null; draw(true); });
  }

  // 1.6.100: the person changes the files of the task here (taskfileedit.py): Edit a text file, New file, New folder, Rename (a new path moves it), Delete (to `.task/trash/`). The server refuses while the
  // agent is in the middle of a turn, and a save of a file the agent changed since it was opened. The parts the task is made of are edited, not renamed or deleted; DEV_r<n> is read only.
  const CORE_FILES = ["TASK.MD", "REQ.MD", "PLAN.MD", "TODO.MD", "LOG.MD"];
  const CORE_DIRS = ["REQ", "REF", "INBOX", "DEV", "RUNS"];
  const fileEdit = {path: "", text: "", saved: "", stamp: "", busy: false, error: ""};
  const roundDir = (path) => /^DEV_R\d+(\/|$)/i.test(path);
  const changeable = () => served() && !desk.past && desk.status === "open";
  const fixed = (path, folder) => roundDir(path) || (!path.includes("/") && (folder ? CORE_DIRS : CORE_FILES).includes(path.toUpperCase()));
  const fileOp = (body) => SERVE.post("/api/fileop", {task: desk.name, ...body}).then((data) => data.result);
  const filesAgain = (open) => intakeRefresh().then(() => { if (open !== undefined) fileOpen = open; draw(true); });
  function fileDialog(title, hint, value, run, label) {  // a path to type, or only a yes; the dialog stays with the reason when the server says no
    const input = value === null ? null : h("input", {type: "text", class: "file-path", value, spellcheck: "false", autocomplete: "off", "aria-label": title});
    const ok = h("button", {type: "button", class: "act hot"}, label || t("desk.files.ok"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const said = h("div", {class: "bad"});
    const view = SERVE.dialog([h("h2", null, title), h("p", {class: "sub"}, hint), input, h("div", {class: "row"}, ok, no), said]);
    const go = () => {
      const text = input ? input.value.trim().replace(/^\/+/, "") : "";
      if (input && !text) return;
      ok.disabled = true;
      run(text).then(() => view.close(), (error) => { ok.disabled = false; said.replaceChildren(...SERVE.reasons((error && error.message) || String(error))); });
    };
    ok.addEventListener("click", go);
    no.addEventListener("click", view.close);
    if (input) {
      input.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.isComposing) go(); });
      setTimeout(() => { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }, 0);
    }
  }
  const folderOf = (path) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/") + 1) : "");
  function newFile(folder) {
    fileDialog(t("desk.files.new.file"), t("desk.files.new.file.hint"), folder, (path) => fileOp({op: "file", path}).then((found) => filesAgain(found.path)));
  }
  function newFolder(folder) {
    fileDialog(t("desk.files.new.folder"), t("desk.files.new.folder.hint"), folder, (path) => fileOp({op: "folder", path}).then(() => filesAgain()));
  }
  function renameFile(path) {
    fileDialog(t("desk.files.rename.title", {path}), t("desk.files.rename.hint"), path, (to) => fileOp({op: "rename", path, to}).then((found) => {
      for (const key of Object.keys(fileCache)) if (key === path || key.startsWith(path + "/")) delete fileCache[key];
      if (fileEdit.path === path) fileEdit.path = "";
      return filesAgain(fileOpen === path ? found.path : fileOpen.startsWith(path + "/") ? found.path + fileOpen.slice(path.length) : undefined);
    }), t("desk.files.rename"));
  }
  function deleteFile(path) {
    fileDialog(t("desk.files.delete.title", {path}), t("desk.files.delete.hint"), null, () => fileOp({op: "delete", path}).then(() => {
      for (const key of Object.keys(fileCache)) if (key === path || key.startsWith(path + "/")) delete fileCache[key];
      if (fileEdit.path === path) fileEdit.path = "";
      return filesAgain();
    }), t("desk.files.delete"));
  }
  function editFile(item) {
    fileEdit.error = "";
    fileOp({op: "raw", path: item.path}).then((found) => {
      Object.assign(fileEdit, {path: item.path, text: found.text, saved: found.text, stamp: found.stamp, busy: false, error: ""});
      draw(true);
      const area = document.querySelector("textarea.file-editor");
      if (area) area.focus();
    }, (error) => { fileEdit.error = (error && error.message) || String(error); draw(true); });
  }
  function saveFile() {
    if (fileEdit.busy || fileEdit.text === fileEdit.saved) return;
    fileEdit.busy = true;
    fileEdit.error = "";
    draw(true);
    fileOp({op: "write", path: fileEdit.path, text: fileEdit.text, stamp: fileEdit.stamp}).then((found) => {
      Object.assign(fileEdit, {saved: fileEdit.text, stamp: found.stamp, busy: false});
      delete fileCache[fileEdit.path];
      filesAgain();
    }, (error) => { fileEdit.busy = false; fileEdit.error = (error && error.message) || String(error); draw(true); });
  }
  function fileEditor(item) {
    const area = h("textarea", {rows: 26, class: "editor file-editor", spellcheck: "false", "aria-label": item.path, disabled: fileEdit.busy ? "" : null, "data-keep": "file-edit." + item.path}, fileEdit.text);
    const changed = () => fileEdit.text !== fileEdit.saved;
    const save = h("button", {type: "button", class: "act hot", disabled: fileEdit.busy || !changed() ? "" : null}, fileEdit.busy ? t("board.serve.working") : t("desk.files.save"));
    const close = h("button", {type: "button", class: "act"}, t("desk.files.close"));
    const mark = h("span", {class: "sub"}, changed() ? t("desk.intake.unsaved") : t("desk.intake.saved"));
    area.addEventListener("input", () => {
      fileEdit.text = area.value;
      save.disabled = fileEdit.busy || !changed();
      mark.textContent = changed() ? t("desk.intake.unsaved") : t("desk.intake.saved");
    });
    area.addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveFile(); } });
    save.addEventListener("click", saveFile);
    close.addEventListener("click", () => { if (!changed() || window.confirm(t("desk.intake.discard"))) { fileEdit.path = ""; fileEdit.error = ""; draw(true); } });
    return [item.path.toUpperCase() === "PLAN.MD" ? h("p", {class: "hint"}, t("desk.files.plan.note")) : null, area,
      fileEdit.error ? h("div", {class: "bad"}, SERVE.reasons(fileEdit.error)) : null, h("div", {class: "inbox-save"}, save, close, mark)];
  }
  const smallButton = (label, call, title, cls) => {
    const button = h("button", {type: "button", class: "act " + (cls || ""), title: title || null}, label);
    button.addEventListener("click", (event) => { event.stopPropagation(); call(); });
    return button;
  };

  function filesTab() {
    const items = desk.files;
    const docs = items.filter((item) => item.kind !== "folder");
    if (!docs.some((item) => item.path === fileOpen)) fileOpen = docs.length ? docs[0].path : "";
    const open = docs.find((item) => item.path === fileOpen);
    if (open && fileEdit.path !== open.path) fileLoad(open);
    const may = changeable(), working = desk.state === "working";
    const list = [];
    const marks = new Map();  // DEV/ file -> "create" | "modify" | "delete" | "unchanged", from the Changes tab
    for (const item of desk.changes.files) marks.set("DEV/" + item.path, item.action);
    for (const path of desk.changes.unchanged_files || []) marks.set("DEV/" + path, "unchanged");
    const ghosts = [...marks].filter(([path, action]) => action === "delete" && !items.some((item) => item.path === path)).map(([path]) => ({path, size: 0, ghost: true}));
    const roots = new Map();  // top folder -> {dirs: name -> node, files: [item]}; the files at the top of the task are under ""
    const node0 = () => ({dirs: new Map(), files: []});
    for (const item of [...items, ...ghosts]) {
      const parts = item.path.split("/");
      const folder = item.kind === "folder";
      const top = parts.length > 1 || folder ? parts[0] : "";
      let node = roots.get(top);
      if (!node) roots.set(top, node = node0());
      for (const name of parts.slice(top ? 1 : 0, folder ? parts.length : -1)) {
        if (!node.dirs.has(name)) node.dirs.set(name, node0());
        node = node.dirs.get(name);
      }
      if (!folder) node.files.push(item);
    }
    // What can be done to a folder, at the end of its line: a file in it, a folder in it, rename, delete.
    const folderTools = (path) => (may ? h("span", {class: "files-tools"}, smallButton("+", () => newFile(path + "/"), t("desk.files.new.file.in", {path})),
      fixed(path, true) ? null : [smallButton("✎", () => renameFile(path), t("desk.files.rename")), smallButton("×", () => deleteFile(path), t("desk.files.delete"), "danger")]) : null);
    // Like the VS Code explorer: folders first, a folder that holds only one folder is joined with it (d/e/f/), one file per line.
    const walk = (node, depth, parent) => {
      for (const [name, child] of node.dirs) {
        let label = name, last = child;
        while (!last.files.length && last.dirs.size === 1) { const [next, inner] = last.dirs.entries().next().value; label += "/" + next; last = inner; }
        const id = parent + "/" + label, shut = folded.has(id);
        const row = h("button", {type: "button", class: "files-dir", "aria-expanded": shut ? "false" : "true", style: "padding-left:" + depth * 14 + "px"}, (shut ? "▸ " : "▾ ") + label + "/");
        row.addEventListener("click", () => { if (folded.has(id)) folded.delete(id); else folded.add(id); draw(true); });
        list.push(h("div", {class: "files-line"}, row, roundDir(id.replace(/^\//, "")) ? null : folderTools(id.replace(/^\//, ""))));
        if (!shut) walk(last, depth + 1, id);
      }
      for (const item of node.files) {
        const mark = marks.get(item.path);
        const name = h("span", null, item.path.split("/").pop());
        const tail = mark ? h("span", {class: "tag fmark " + mark}, markText()[mark]) : h("span", {class: "sub"}, " " + size(item.size));
        if (item.ghost) { list.push(h("div", {class: "file ghost", title: item.path, style: "padding-left:" + depth * 14 + "px"}, name, " ", tail)); continue; }
        const button = h("button", {type: "button", class: "file" + (item.path === fileOpen ? " on" : "") + (mark === "unchanged" ? " plain" : ""), title: item.path, style: "padding-left:" + depth * 14 + "px"}, name, " ", tail);
        button.addEventListener("click", () => { fileOpen = item.path; if (!fileEdit.path) fileEdit.error = ""; draw(true); });
        list.push(button);
      }
    };
    for (const [root, node] of [...roots].sort(([a], [b]) => (a === "") - (b === ""))) {  // the files at the top come last
      const hint = root ? rootHint(root) : "desk.files.root.top";
      const known = hint !== "desk.files.hint";
      list.push(h("div", {class: "files-line files-root"}, h("span", null, h("strong", null, root ? root + "/" : t("desk.files.top")), known ? h("span", {class: "sub"}, " " + t(hint)) : null),
        root ? (roundDir(root) ? null : folderTools(root)) : null));
      walk(node, 1, root);
    }
    const tools = may ? h("div", {class: "files-new"}, smallButton(t("desk.files.new.file"), () => newFile(open ? folderOf(open.path) : "")), smallButton(t("desk.files.new.folder"), () => newFolder(open ? folderOf(open.path) : ""))) : null;
    const editing = open && fileEdit.path === open.path;
    const textual = open && ["markdown", "text"].includes(open.kind) && open.size <= 1000000;
    const head = open ? h("div", {class: "round-head files-head"}, h("strong", null, open.path), " ", h("span", {class: "sub"}, size(open.size)),
      may && !editing && !roundDir(open.path) ? h("span", {class: "files-tools on"}, textual ? smallButton(t("desk.files.edit"), () => editFile(open)) : null,
        fixed(open.path, false) ? null : [smallButton(t("desk.files.rename"), () => renameFile(open.path)), smallButton(t("desk.files.delete"), () => deleteFile(open.path), "", "danger")]) : null) : null;
    return [h("p", {class: "hint top"}, t(may ? "desk.files.hint.edit" : "desk.files.hint")), may && working ? h("p", {class: "hint"}, t("desk.files.busy")) : null,
      evidenceList(),
      h("div", {class: "files"}, h("nav", {class: "files-list", "data-keep": "files-list"}, tools, list),
        h("div", {class: "files-view"}, head, !editing && fileEdit.error && fileEdit.path === "" ? h("div", {class: "bad"}, SERVE.reasons(fileEdit.error)) : null,
          open ? (editing ? fileEditor(open) : fileView(open)) : h("p", {class: "sub"}, t("desk.files.none"))))];
  }

  // The evidence of the task (1.7.3): every saved run with its number, who ran it and where it is cited. A row opens its results file in the tree.
  function evidenceList() {
    const items = desk.evidence || [];
    if (!items.length) return null;
    const rows = items.map((item) => {
      const open = h("button", {type: "button", class: "chip", title: item.file}, item.id);
      open.addEventListener("click", () => { fileOpen = item.file; if (!fileEdit.path) fileEdit.error = ""; draw(true); });
      return h("tr", null, h("td", null, open), h("td", null, item.env), h("td", null, tag(item.by === "agent" ? t("desk.evidence.by.agent") : t("desk.evidence.by.person"), item.by === "agent" ? "good" : "")),
        h("td", {class: "sub"}, item.at ? item.at.slice(0, 16).replace("T", " ") : ""), h("td", {class: "sub"}, item.kind === "test" ? t("desk.evidence.kind.test", {n: item.run}) : t("desk.evidence.kind.run", {n: item.run})),
        h("td", {class: "sub"}, item.cited_in.length ? item.cited_in.join(", ") : t("desk.evidence.uncited")));
    });
    return h("details", {class: "evidence", open: ""}, h("summary", null, t("desk.evidence.title", {n: items.length})), h("p", {class: "sub"}, t("desk.evidence.hint")),
      h("div", {class: "scroll"}, h("table", null, h("thead", null, h("tr", null, h("th", null, "E"), h("th", null, t("desk.evidence.env")), h("th", null, t("desk.evidence.by")), h("th", null, t("desk.evidence.at")), h("th", null, t("desk.evidence.run")), h("th", null, t("desk.evidence.cited")))), h("tbody", null, rows))));
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

  // A CSV file as rows of cells, the way the converter writes it: commas (`delimiter`: a tab for a TSV file), a cell in quotes when it holds a comma, a quote ("" inside) or a line break. Blank lines are dropped.
  function parseCsv(text, delimiter = ",") {
    const rows = [];
    let row = [], cell = "", quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted) {
        if (c !== '"') cell += c;
        else if (text[i + 1] === '"') { cell += '"'; i++; }
        else quoted = false;
      } else if (c === '"' && cell === "") quoted = true;
      else if (c === delimiter) { row.push(cell); cell = ""; }
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

  // The table view of a CSV file. In Intake the rows the person picks are taken out, or the only ones kept: the text follows, and is written only by Save. With a `key` (the Files tab) it only reads: nothing to pick.
  const CSV_PAGE = 200;
  function csvLoad(edit, first) {
    edit.rows = parseCsv(edit.text, edit.delimiter);
    edit.picked = new Set(); edit.q = edit.q || ""; edit.shown = CSV_PAGE;
    if (first) edit.view = edit.rows.length > 1 && edit.rows.some((row) => row.length > 1) ? "table" : "text";  // one column or one line: it may not be a comma file; the text is shown
  }

  function csvTable(edit, key) {
    const columns = edit.rows.reduce((most, row) => Math.max(most, row.length), 1), first = edit.rows[0] || [];  // not Math.max(...rows): a file of 200,000 short lines is too many arguments
    const cells = (row) => Array.from({length: columns}, (_, c) => h("td", null, h("div", {class: "csv-cell"}, row[c] || "")));
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
      const rows = Math.max(0, edit.rows.length - 1), drawn = Math.min(hits.length, edit.shown);
      if (!key) info.textContent = t("desk.intake.csv.info", {rows, match: hits.length, drawn, picked: edit.picked.size});
      else info.textContent = edit.q.trim() ? t("desk.files.table.found", {match: hits.length, rows, drawn}) : edit.cut ? t("desk.files.table.part", {rows, columns, drawn}) : t("desk.files.table.info", {rows, columns, drawn});
      del.textContent = t("desk.intake.csv.delete", {n: edit.picked.size});
      keep.textContent = t("desk.intake.csv.keep", {n: edit.picked.size});
      del.disabled = keep.disabled = !edit.picked.size;
      const cut = hits.slice(0, edit.shown);
      body.replaceChildren(...cut.map((i) => {
        if (key) return h("tr", null, h("td", {class: "csv-pick"}, h("span", {class: "sub"}, i)), cells(edit.rows[i]));
        const box = h("input", {type: "checkbox", checked: edit.picked.has(i) ? "" : null});
        box.addEventListener("change", () => { if (box.checked) edit.picked.add(i); else edit.picked.delete(i); refresh(); });
        return h("tr", {class: edit.picked.has(i) ? "picked" : null}, h("td", {class: "csv-pick"}, box, " ", h("span", {class: "sub"}, i)), cells(edit.rows[i]));
      }));
      more.hidden = hits.length <= cut.length;
      more.textContent = t("desk.intake.csv.more", {n: Math.min(CSV_PAGE, hits.length - cut.length)});
    };
    search.addEventListener("input", () => { edit.q = search.value; edit.shown = CSV_PAGE; refresh(); });
    const head = h("thead", null, h("tr", null, h("th", null, "#"), Array.from({length: columns}, (_, c) => h("th", {title: first[c] || null}, first[c] || ""))));
    refresh();
    return h("div", {class: "csv"},
      h("div", {class: "csv-tools"}, search, key ? null : [
        tools(t("desk.intake.csv.pickshown"), () => { for (const i of matching()) edit.picked.add(i); refresh(); }),
        tools(t("desk.intake.csv.clear"), () => { edit.picked.clear(); refresh(); }), del, keep], info),
      h("div", {class: "csv-scroll", "data-keep": "csv." + (key || "intake")}, h("table", {class: "csv-table"}, head, body)),
      h("div", {class: "inbox-save"}, more),
      key ? null : h("p", {class: "hint"}, t("desk.intake.csv.note")));
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
    const area = h("textarea", {rows: 22, class: "editor", spellcheck: "false", disabled: intake.busy ? "" : null, "data-keep": "intake.edit." + edit.path}, edit.text);
    area.addEventListener("input", () => { edit.text = area.value; });
    const views = edit.rows ? h("div", {class: "inbox-save"}, ...[["table", t("desk.intake.view.table")], ["text", t("desk.intake.view.text")]].map(([view, label]) =>
      pickChip(label, edit.view === view, () => { if (edit.view !== view) { edit.view = view; if (view === "table") csvLoad(edit); draw(true); } })), edit.text !== edit.saved ? button(t("desk.intake.csv.undo"), () => { edit.text = edit.saved; csvLoad(edit); draw(true); }) : null) : null;
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
      if (c.files.some((item) => item.by_hand)) parts.push(h("p", {class: "sub"}, t("desk.changes.byhand")));  // DEV/_manual/ is run by hand: promote leaves it
      parts.push(DiffView.create({files: c.files, lines: c.diff.lines, cut: c.diff.cut, same}, () => diff(c.diff), "dev"));  // old and new code side by side (diffview.js); the plain diff text is its third view
    } else {
      parts.push(h("div", {class: "empty-state"}, h("b", null, t("desk.changes.none")), h("p", null, t("desk.changes.none.hint"))));
    }
    const body = (found) => found.lines.filter((line) => !line.startsWith("#")).join("\n");  // the first lines of each file say what it is, not what changes
    const plan = c.promote_plan;
    if (plan.lines.length && !plan.cut && !c.diff.cut && body(plan) === body(c.diff)) {  // the same diff twice says nothing more
      if (!desk.commit) parts.push(h("p", {class: "sub"}, t("desk.changes.promote.same")));  // written back already: nothing is left to approve
    }
    else if (plan.lines.length) parts.push(h("h3", null, t("desk.changes.promote")), h("p", {class: "sub"}, t("desk.changes.promote.hint")),
      DiffView.create(plan, () => diff(plan), "plan", true));  // the same compare, the files read from the plan; a long file scrolls in a lower window
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
    return h("ol", {class: "timeline history"}, desk.history.map((event) => h("li", {class: "ev-" + event.what + (event.mark ? " key " + event.mark : "")},
      h("span", {class: "when sub"}, when(event.at, 5, 16)),
      h("div", {class: "what"}, h("b", null, event.label),  // one block: a long line wraps under its own start, not under the time
        event.detail ? h("span", {class: "sub"}, " · " + event.detail) : null, event.via ? h("span", {class: "tag"}, t("desk.via." + event.via)) : null, event.round > 1 ? h("span", {class: "tag"}, t("desk.round", {round: event.round})) : null))));
  }

  // The Agent actions tab. Open, it asks for the tree (pull): the numbers of the whole task, what was blocked or failed, and one node per prompt with what the agent did for it, in order.
  // Until the tree comes, or where there is none, it is the plain list of the hook log. What the model thought is not in Copilot's record: only how long.
  const traceOpen = new Map();  // prompt number -> open; the newest is open until the person says otherwise
  const spent = (seconds) => (seconds > 0 && seconds < 10 ? seconds.toFixed(1) + " s" : clock(seconds));

  function traceRow(item) {
    const stamp = h("span", {class: "when sub"}, when(item.at, 5, 19));
    if (item.kind === "prompt") return h("li", {class: "tr-prompt"}, stamp, h("div", {class: "what sub"}, t("desk.trace.prompt")));
    if (item.kind === "think") return h("li", {class: "tr-think"}, stamp, h("div", {class: "what sub"}, t("desk.trace.think"), " \u00b7 " + spent(item.seconds)));
    if (item.kind === "subagent") return h("li", {class: "tr-agent"}, stamp, h("div", {class: "what"}, h("b", null, item.agent), " ", tag(t("desk.trace.subagent")), h("span", {class: "sub"}, " \u00b7 " + spent(item.seconds) + " \u00b7 " + t("desk.trace.calls", {n: item.tool_calls || 0}) + (item.model ? " \u00b7 " + item.model : ""))));
    const gate = item.kind === "gate";
    return h("li", {class: (gate ? "tr-gate" : item.ok === false ? "tr-fail" : "") + (item.source ? " tr-in" : "")}, stamp,
      h("div", {class: "what"}, h("b", null, item.tool), item.source ? [" ", h("span", {class: "tag", title: t("desk.trace.source", {name: item.source})}, item.source)] : null,
        gate ? [" ", tag(t("desk.trace." + item.decision), item.decision === "deny" ? "bad" : "hot"), item.rule ? h("span", {class: "sub"}, " \u00b7 " + item.rule) : null] : null,
        !gate && item.ok === false ? [" ", tag(t("desk.trace.failed"), "bad")] : null,
        !gate && item.ok === null ? [" ", item.stopped ? tag(t("desk.trace.stopped")) : tag(t("desk.trace.running"), "good run")] : null,
        item.seconds ? h("span", {class: "sub"}, " \u00b7 " + spent(item.seconds)) : null,
        (item.paths || []).map((path) => [" ", h("span", {class: "path", title: path}, path)]),
        item.command ? [" ", h("code", null, item.command)] : null,
        item.reason ? h("div", {class: "sub"}, item.reason) : null,
        item.error ? h("div", {class: "sub"}, item.error) : null));
  }

  function traceStats(stats) {
    const tile = (value, label, kind) => h("div", {class: "tr-stat" + (kind ? " " + kind : "")}, h("b", null, value), h("span", null, label));
    return h("div", {class: "tr-stats"},
      tile(amount(stats.prompts), t("desk.trace.stat.prompts", {time: clock(stats.active_s)})),
      tile(clock(stats.model_s), t("desk.trace.stat.thinking", {n: amount(stats.turns)})),
      tile(amount(stats.tool_calls), t("desk.trace.stat.tools", {time: clock(stats.tool_s)})),
      tile(amount(stats.subagents), t("desk.trace.stat.subagents", {time: clock(stats.subagent_s)})),
      tile(amount(stats.blocked), t("desk.trace.stat.blocked"), stats.blocked ? "bad" : ""),
      tile(amount(stats.failed), t("desk.trace.stat.failed"), stats.failed ? "bad" : ""));
  }

  function goPrompt(number) {
    traceOpen.set(number, true);
    draw(true);
    const node = document.getElementById("tr-p-" + number);
    if (node) node.scrollIntoView({block: "start", behavior: "smooth"});
  }

  function traceProblems(found) {
    if (!found.problems.length) return null;
    return h("section", {class: "tr-problems"}, h("h3", null, t("desk.trace.problems", {n: found.stats.blocked + found.stats.failed})),
      h("ol", {class: "timeline trace"}, found.problems.map((item) => {
        const row = traceRow(item), jump = h("button", {type: "button", class: "chip tr-jump", title: t("desk.trace.jump", {n: item.prompt})}, "#" + item.prompt);
        jump.addEventListener("click", () => goPrompt(item.prompt));
        row.append(jump);
        return row;
      })), found.problems_cut ? h("p", {class: "sub"}, t("desk.trace.cut", {count: found.problems_cut})) : null);
  }

  function promptNode(node, newest) {
    const chips = [
      node.seconds !== null && node.seconds !== undefined ? tag(clock(node.seconds)) : null, node.tool_calls ? tag(t("desk.trace.chip.tools", {n: node.tool_calls})) : null, node.subagents ? tag(t("desk.trace.chip.subagents", {n: node.subagents})) : null,
      node.asked ? tag(t("desk.trace.chip.asked", {n: node.asked}), "hot") : null, node.blocked ? tag(t("desk.trace.chip.blocked", {n: node.blocked}), "bad") : null, node.failed ? tag(t("desk.trace.chip.failed", {n: node.failed}), "bad") : null];
    const head = h("summary", null, h("span", {class: "tr-n"}, "#" + node.n), h("span", {class: "when sub"}, when(node.at, 5, 19)), h("span", {class: "tr-text", title: node.text}, node.text || t("desk.trace.prompt")), h("span", {class: "tr-chips"}, chips));
    const box = h("details", {class: "tr-node" + (node.blocked || node.failed ? " bad" : ""), id: "tr-p-" + node.n, open: (traceOpen.has(node.n) ? traceOpen.get(node.n) : newest) ? "" : null}, head,
      node.cut ? h("p", {class: "sub"}, t("desk.trace.cut", {count: node.cut})) : null, h("ol", {class: "timeline trace"}, node.rows.map(traceRow)));
    head.addEventListener("click", () => traceOpen.set(node.n, !box.open));  // a click, not the `toggle` event: that one also fires when a node is drawn open
    return box;
  }

  function trace() {
    const found = desk.trace, tree = found.tree;
    const notes = (desk.warn || []).map((item) => h("p", {class: "warn-note"}, tag("\u26a0", "warn"), " ", t("board.warn." + item.rule, {n: item.n})));
    if (tree && tree.prompts && tree.prompts.length) return [h("p", {class: "hint top"}, t("desk.trace.hint.tree")), notes, traceStats(tree.stats), traceProblems(tree), h("div", {class: "tr-tree"}, tree.prompts.map((node, index) => promptNode(node, index === 0)))];
    return [h("p", {class: "hint top"}, t("desk.trace.hint")), notes, h("ol", {class: "timeline trace"}, found.entries.slice().reverse().map(traceRow)), found.cut ? h("p", {class: "sub"}, t("desk.trace.cut", {count: found.cut})) : null];
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
    if (current === "live") return livePane();
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

  // A redraw changes the parts of the page that depend on the data: the header is changed in place (paintHead), the card of waits, the tabs and the open tab are made again. A list or a code window that
  // scrolls by itself (marked `data-keep`) is put back where it was, and so is the focus on a tab. A text box marked `data-keep` that the person is typing in gets its focus and its caret back too
  // (1.6.107: a picture pasted into the results made the box start again at its top, with no focus).
  function draw(keepScroll) {
    shell();
    remember(current);
    const y = window.scrollY;
    const kept = new Map([...app.querySelectorAll("[data-keep]")].map((node) => [node.dataset.keep, [node.scrollTop, node.scrollLeft]]));
    const focused = document.activeElement && document.activeElement.closest ? document.activeElement.closest("[data-key]") : null;
    const focusKey = focused && ui.tabs.contains(focused) ? focused.dataset.key : "";
    const field = document.activeElement;
    const typing = field && app.contains(field) && field.dataset && field.dataset.keep && typeof field.selectionStart === "number"
      ? {key: field.dataset.keep, start: field.selectionStart, end: field.selectionEnd, way: field.selectionDirection || "none"} : null;
    paintHead();
    paintLive();
    fill(ui.tabs, nav());
    fill(ui.pane, body());
    ui.pane.hidden = !ui.pane.firstChild;
    fill(ui.foot, [typeof SERVE === "undefined" && !saved ? h("p", {class: "sub"}, t("board.copy.hint")) : saved ? null : SERVE.banner(true),  // quiet: the mark beside the VS Code pill says it is paired

      h("footer", null, t(saved ? "desk.snapshot.footer" : "desk.footer", {as_of: when(desk.as_of, 0, 19)}), copyright())]);  // a null would be drawn as the word "null"
    if (focusKey) { const again = ui.tabs.querySelector('[data-key="' + focusKey + '"]'); if (again) again.focus({preventScroll: true}); }
    if (typing) {
      const again = [...app.querySelectorAll("[data-keep]")].find((node) => node.dataset.keep === typing.key);
      if (again && again !== field && typeof again.setSelectionRange === "function") {
        again.focus({preventScroll: true});
        try { again.setSelectionRange(typing.start, typing.end, typing.way); } catch (error) { /* a field that takes no range */ }
      }
    }
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
  SHELL.vs(desk.vscode);
  SHELL.visit(desk.name);
  // What Cmd+K can open on a task page: every tab this task has, and (shell.js) the other tasks, the board views and filters.
  SHELL.provide(() => ({here: desk.name, tabs: tabs.filter(visible).map((tab) => ({id: tab, label: t("desk.tab." + tab), group: groupOf(tab).tabs.filter(visible).length > 1 && groupName(groupOf(tab).id) !== t("desk.tab." + tab) ? groupName(groupOf(tab).id) : "", current: tab === current,
    run: () => goTab(tab)}))}));
  draw(false);
  // Ask the server for the task again and draw what changed (keeping the open tab, the scroll, and every node that did not change).
  function pull() {
    return SERVE.post("/api/desk", {task: desk.name, trace: current === "trace"}).then((data) => {
      SHELL.vs(data.desk.vscode);
      if (!data.desk.trace.tree && desk.trace.tree) data.desk.trace.tree = desk.trace.tree;  // asked for only while its tab is open
      const text = JSON.stringify(data.desk);
      if (same(text, shown)) {
        const waited = data.desk.waited_s;
        if (waited !== null && waited !== undefined) document.querySelectorAll(".tk-waited:not(.st-run)").forEach((node) => { node.textContent = t("desk.waited", {time: clock(waited)}); });
        const foot = ui.foot && ui.foot.querySelector("footer");
        if (foot && foot.firstChild) foot.firstChild.textContent = t("desk.footer", {as_of: when(data.desk.as_of, 0, 19)});
        return;
      }
      setDesk(data.desk);
      shown = text;
      draw(true);
    }, (error) => {
      if (error && error.offline) throw error;
      if (error && error.data && error.data.gone && !ui.gone) {  // archived or removed while this page was open: what it shows is no longer there
        ui.gone = true;
        ui.wait.hidden = false;
        ui.wait.replaceChildren(h("section", {class: "tk-need strong"}, h("p", {class: "tk-need-p"}, error.message), h("a", {class: "act", href: "/"}, t("desk.gone.back"))));
      }
    });
  }
  if (typeof SERVE !== "undefined" && DATA.serve.refresh) {
    Run.attach(desk.name);
    SERVE.onChange(() => { pull(); });  // after a click that changed something (a setting, a message sent): in place, so the reply panel and what was typed stay; a reload would drop them
    if (current === "trace") pull();  // opened on this tab: the page came without the tree
    const typing = () => document.activeElement && ["TEXTAREA", "INPUT"].includes(document.activeElement.tagName);  // a redraw would take the focus from what the person is typing
    if (typeof LIVE !== "undefined") {  // the stream is asked every second, the page every few: when the chat starts or stops waiting the rest follows at once, or the two say different things for a moment
      let chat = "";
      LIVE.onChange(() => {
        const now = (LIVE.data() || {}).state || "";
        if (now === chat) return;
        const changed = Boolean(chat);
        chat = now;
        if (changed && !SERVE.busy() && !typing()) pull();
      });
    }
    pollEvery(DATA.serve.refresh, () => {
      if (SERVE.busy() || typing()) return null;
      return pull();
    });
  }
})();
