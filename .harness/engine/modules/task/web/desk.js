// One task in the browser: its documents, TODO progress, history, changes, and what the person can do now.
// DATA.desk is what taskdesk.desk returns; DATA.serve is the board server's (actions, refresh). Markdown comes as a tree
// of blocks (mdtree.py) and is drawn node by node with textContent: nothing an agent wrote can become markup.
// The page asks the server for the task again every few seconds and draws it again only when something changed,
// keeping the open tab and the scroll.
"use strict";

(function () {
  const app = document.getElementById("app");
  let desk = DATA.desk;
  let shown = JSON.stringify(desk);
  const same = (a, b) => a.replace(/"as_of":"[^"]*"/, "") === b.replace(/"as_of":"[^"]*"/, "");  // the time of asking is not a change
  const tabs = ["overview", "test", "plan", "todo", "log", "changes", "review", "history", "docs"];
  const FILES = {overview: "TASK.md", req: "REQ.md", plan: "PLAN.md", todo: "TODO.md", log: "LOG.md"};
  let current = tabs.includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview";
  let other = "";  // the document open in the "docs" tab

  const doc = (name) => desk.docs.find((item) => item.name === name);
  const extra = () => desk.docs.filter((item) => !Object.values(FILES).includes(item.name) && !(desk.test && item.name === "TEST-GUIDE.md"));  // the guide has its own tab on a test task

  // --- markdown -------------------------------------------------------------------------------------------

  function inline(spans) {
    return spans.map((span) => {
      if (span.t === "text") return span.v;
      if (span.t === "br") return h("br");
      if (span.t === "code") return h("code", null, span.v);
      if (span.t === "b") return h("strong", null, inline(span.c));
      if (span.t === "i") return h("em", null, inline(span.c));
      if (span.t === "s") return h("s", null, inline(span.c));
      if (span.t === "a") return link(span.href, inline(span.c));
      return "";
    });
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

  function blocks(list) {
    return list.map((block) => {
      if (block.t === "h") return h("h" + Math.min(block.level + 1, 6), {class: "md-h"}, inline(block.spans));
      if (block.t === "p") return h("p", null, inline(block.spans));
      if (block.t === "hr") return h("hr");
      if (block.t === "code") return h("pre", {class: "code"}, h("code", null, block.text));
      if (block.t === "quote") return h("blockquote", null, blocks(block.blocks));
      if (block.t === "table") {
        const cell = (tag, spans, align) => h(tag, {style: align ? "text-align:" + align : null}, inline(spans));
        return h("div", {class: "scroll"}, h("table", {class: "md"},
          h("thead", null, h("tr", null, block.head.map((spans, i) => cell("th", spans, block.align[i])))),
          h("tbody", null, block.rows.map((row) => h("tr", null, row.map((spans, i) => cell("td", spans, block.align[i])))))));
      }
      if (block.t === "ul" || block.t === "ol") {
        const checks = block.items.some((item) => item.check !== null);
        return h(block.t, {class: checks ? "checks" : null, start: block.t === "ol" && block.start !== 1 ? block.start : null},
          block.items.map((item) => h("li", {class: item.check === null ? null : item.check ? "done" : "open"},
            item.check === null ? null : h("span", {class: "box"}, item.check ? "✓" : ""),
            h("span", null, inline(item.spans)), blocks(item.blocks))));
      }
      return null;
    });
  }

  function markdown(name, empty) {
    const found = doc(name);
    if (!found) return h("div", {class: "empty-state"}, h("b", null, t("desk.missing", {file: name})), h("p", null, empty));
    return h("article", {class: "md"}, blocks(found.blocks), found.cut ? h("p", {class: "sub"}, t("desk.cut")) : null);
  }

  const served = () => typeof SERVE !== "undefined" && Boolean(DATA.serve);

  // --- the parts --------------------------------------------------------------------------------------------

  function header() {
    const kind = t("task.kind." + (desk.kind || "none")) + " · " + t("task.tier." + (desk.tier || "none"));
    const state = stateTag(desk, served());
    return [
      brand(),
      h("div", {class: "crumbs sub"}, h("a", {href: "/"}, "← " + t("desk.back")),
        desk.report ? [" · ", h("a", {href: desk.report.split("/").map(encodeURIComponent).join("/")}, t("desk.report"))] : null),
      h("div", {class: "title-row"}, h("h1", null, desk.name), state),
      h("div", {class: "sub"}, t("desk.subtitle", {kind, round: desk.round, created: when(desk.created_at, 0, 16), updated: when(desk.updated_at, 0, 16)}),
        desk.domains.length ? " · " + t("desk.domains", {names: desk.domains.join(", ")}) : "", desk.autorun ? [" · ", tag(t("desk.autorun"), "good")] : null),
    ];
  }

  // What the card says when no button is the point: put aside, waiting for a word in VS Code, nobody on it, or really nothing.
  function quiet() {
    if (desk.paused_since) return {title: t("desk.actions.paused"), hint: t("desk.actions.paused.hint")};
    const why = desk.waiting_why;
    if (desk.waiting && (["stopped", "cancelled", "autorun", "tests"].includes(why) || why.startsWith("go-"))) {
      return {title: desk.waiting.charAt(0).toUpperCase() + desk.waiting.slice(1), hint: t("desk.wait." + why),
        prompt: why.startsWith("go-") ? t("desk.go." + why.slice(3)) : why === "tests" ? t("desk.tests.prompt") : ""};
    }
    if (desk.state === "unheld") return {title: t("desk.actions.unheld"), hint: t("desk.actions.unheld.hint"), prompt: t("desk.unheld.prompt", {name: desk.name})};
    if (stateOf(desk, served()) === "quiet") return {title: t("desk.actions.quiet"), hint: t("desk.actions.quiet.hint")};
    return {title: t("desk.actions.none"), hint: t("desk.actions.none.hint")};
  }

  // A message the person sends to the agent in VS Code: one click copies it.
  function promptLine(text) {
    const button = h("button", {type: "button", class: "act", "data-label": t("desk.go.copy")}, t("desk.go.copy"));
    button.addEventListener("click", () => copyCommand(button, text));
    return h("div", {class: "prompt-line"}, h("code", null, text), button);
  }

  function actions() {
    if (desk.status !== "open") return h("section", {class: "card actions quiet"}, h("p", {class: "sub"}, t("desk.actions.closed")));
    const optional = ["confirm-req", "pause", "resume", "autorun on", "close"];  // the person may do these any time; the rest is what the task waits for
    const items = desk.actions.filter((item) => !optional.includes(item.action));
    const rest = desk.actions.filter((item) => optional.includes(item.action));
    const row = {name: desk.name, waiting: desk.waiting, state: desk.state};
    const hint = (item) => t("desk.hint." + item.action.replace(" ", "-"));
    const entry = (item) => h("div", {class: "action"}, actionButton(row, item, "big"), h("p", {class: "hint"}, hint(item)));
    const line = (item) => h("div", {class: "action-line"}, actionButton(row, item), h("span", {class: "hint"}, hint(item)));
    const idle = items.length ? null : quiet();
    return h("section", {class: "card actions"},
      h("h2", null, idle ? idle.title : t("desk.actions.title")),
      desk.waited_s !== null && (items.length || desk.waiting) ? h("p", {class: "sub"}, t("desk.waited", {time: clock(desk.waited_s)})) : null,
      desk.req_changed ? h("p", {class: "hint bad"}, t("desk.req.changed")) : null,
      desk.state === "working" && served() ? h("p", {class: "hint"}, t("desk.busy.note")) : null,
      desk.state === "waiting" && !desk.held ? h("p", {class: "hint"}, t("desk.unheld.note")) : null,
      idle ? [h("p", {class: "hint"}, idle.hint), idle.prompt ? promptLine(idle.prompt) : null] : h("div", {class: "action-list"}, items.map(entry)),
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
      if (tab === "todo" && desk.todo.total) return t("desk.tab.todo") + " " + desk.todo.done + "/" + desk.todo.total;
      if (tab === "changes" && desk.changes.files.length) return t("desk.tab.changes") + " " + desk.changes.files.length;
      if (tab === "test") return t("desk.tab.test") + " " + desk.test.passed + "/" + desk.test.total;
      if (tab === "review") return t("desk.tab.review") + (desk.review.n ? " " + desk.review.passes + "/" + desk.review.n : " " + desk.review.rounds.length);
      if (tab === "history") return t("desk.tab.history") + " " + desk.history.length;
      if (tab === "docs") return t("desk.tab.docs") + " " + extra().length;
      return t("desk.tab." + tab);
    };
    return h("nav", {class: "tabs"}, tabs.filter((tab) => (tab !== "docs" || extra().length) && (tab !== "review" || hasReview()) && (tab !== "test" || desk.test)).map((tab) => {
      const button = h("button", {type: "button", class: "tab" + (tab === current ? " on" : "")}, label(tab));
      button.addEventListener("click", () => { current = tab; history.replaceState(null, "", "#" + tab); draw(false); });
      return button;
    }));
  }

  // The tab is there when checks were asked for ([review]=n) or one has run; a task nobody asked to check has none.
  const hasReview = () => desk.review.n > 0 || desk.review.rounds.length > 0;

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
      const answer = item.answer ? blocks(item.answer.blocks) : h("p", {class: "sub"}, item.verdict ? t("desk.review.noanswer") : t("desk.review.pending"));
      parts.push(h("section", {class: "round " + (item.verdict === "FAIL" ? "fail" : item.verdict === "PASS" ? "pass" : "")},
        h("div", {class: "round-head"}, h("strong", null, "round-" + String(item.number).padStart(3, "0")), " ", verdict, " ",
          h("span", {class: "sub"}, when(item.started_at, 5, 16) + " · " + (item.current ? t("desk.review.current") : t("desk.review.earlier")))),
        h("article", {class: "md"}, answer, item.answer && item.answer.cut ? h("p", {class: "sub"}, t("desk.cut")) : null),
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

  // The Test tab of a test task: the guide the agent wrote for the person, then each environment with the results file and the verdict.
  function testing() {
    const x = desk.test;
    const parts = [h("p", {class: "hint top"}, t("desk.test.hint"))];
    parts.push(h("div", {class: "test-envs"}, x.envs.map((env) => tag(env.name + " · " + (env.verdict || (env.waits ? t("desk.test.waits") : t(env.state === "now" ? "desk.test.next" : "desk.test.todo"))),
      env.state === "done" ? "good" : env.state === "failed" ? "bad" : env.waits ? "hot" : ""))));
    parts.push(h("h3", null, t("desk.test.guide")));
    parts.push(x.guide ? h("article", {class: "md"}, blocks(x.guide.blocks), x.guide.cut ? h("p", {class: "sub"}, t("desk.cut")) : null)
      : h("div", {class: "empty-state"}, h("b", null, t("desk.test.noguide"))));
    parts.push(h("h3", null, t("desk.test.results")));
    for (const env of x.envs) {
      const verdict = env.verdict ? tag(env.verdict, env.verdict === "PASS" ? "good" : env.verdict === "FAIL" ? "bad" : "hot") : tag(env.waits ? t("desk.test.waits") : t("desk.test.noresult"), env.waits ? "hot" : "");
      const body = env.results ? h("article", {class: "md"}, blocks(env.results.blocks), env.results.cut ? h("p", {class: "sub"}, t("desk.cut")) : null)
        : h("p", {class: "sub"}, env.waits ? t("desk.test.waiting", {env: env.name}) : t("desk.test.noresult"));
      parts.push(h("section", {class: "round " + (env.state === "failed" ? "fail" : env.state === "done" ? "pass" : "")},
        h("div", {class: "round-head"}, h("strong", null, env.name), " ", verdict, env.file ? [" ", h("span", {class: "sub"}, "TEST/" + env.file)] : null), body));
    }
    if (x.defects) parts.push(...defects(x.defects));
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
    const parts = [];
    if (c.files.length || c.deletes.length) {
      parts.push(h("h3", null, t("desk.changes.files")), table([th(t("desk.changes.file")), th(t("desk.changes.what")), th("+", true), th("−", true)],
        c.files.map((item) => h("tr", null, h("td", null, h("code", null, item.path)), h("td", null, tag(t("desk.changes." + item.action))),
          num(item.added), num(item.removed))).concat(c.deletes.map((path) => h("tr", null, h("td", null, h("code", null, path)), h("td", null, tag(t("desk.changes.delete"), "bad")), num("-"), num("-"))))));
    } else {
      parts.push(h("div", {class: "empty-state"}, h("b", null, t("desk.changes.none")), h("p", null, t("desk.changes.none.hint"))));
    }
    if (c.diff.lines.length) parts.push(h("h3", null, t("desk.changes.diff")), diff(c.diff));
    if (c.promote_plan.lines.length) parts.push(h("h3", null, t("desk.changes.promote")), h("p", {class: "sub"}, t("desk.changes.promote.hint")), diff(c.promote_plan));
    return parts;
  }

  function diff(found) {
    const kind = (line) => (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") ? "file"
      : line.startsWith("@@") ? "hunk" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "");
    return h("div", {class: "scroll"}, h("pre", {class: "diff"}, found.lines.map((line) => h("span", {class: kind(line)}, line + "\n"))),
      found.cut ? h("p", {class: "sub"}, t("desk.cut")) : null);
  }

  function timeline() {
    if (!desk.history.length) return h("div", {class: "empty-state"}, h("b", null, t("desk.history.none")));
    return h("ol", {class: "timeline"}, desk.history.map((event) => h("li", {class: "ev-" + event.what},
      h("span", {class: "when sub"}, when(event.at, 5, 16)), h("b", null, event.label),
      event.detail ? h("span", {class: "sub"}, " · " + event.detail) : null, event.via ? h("span", {class: "tag"}, t("desk.via." + event.via)) : null, event.round > 1 ? h("span", {class: "tag"}, t("desk.round", {round: event.round})) : null)));
  }

  function openDoc(name) {
    const tab = Object.keys(FILES).find((key) => FILES[key] === name);
    if (tab === "req") { current = "overview"; } else if (tab) { current = tab; } else { current = "docs"; other = name; }
    history.replaceState(null, "", "#" + current);
    draw(false);
    if (tab === "req") document.getElementById("req")?.scrollIntoView({behavior: "smooth"});
  }

  function body() {
    if (current === "overview") {
      return [h("p", {class: "hint top"}, t("desk.overview.hint")), markdown("TASK.md", t("desk.missing.task")),
        h("h2", {id: "req", class: "split"}, t("desk.tab.req")), markdown("REQ.md", t("desk.missing.req"))];
    }
    if (current === "plan") return [h("p", {class: "hint top"}, t("desk.plan.hint")), markdown("PLAN.md", t("desk.missing.plan"))];
    if (current === "todo") return [progress(), markdown("TODO.md", t("desk.missing.todo"))];
    if (current === "log") return [h("p", {class: "hint top"}, t("desk.log.hint")), markdown("LOG.md", t("desk.missing.log"))];
    if (current === "changes") return changes();
    if (current === "review") return review();
    if (current === "test" && desk.test) return testing();
    if (current === "history") return [h("p", {class: "hint top"}, t("desk.history.hint")), timeline()];
    const docs = extra();
    const name = docs.some((item) => item.name === other) ? other : (docs[0] || {}).name;
    return [h("div", {class: "doc-list"}, docs.map((item) => {
      const button = h("button", {type: "button", class: "chip" + (item.name === name ? " on" : "")}, item.name);
      button.addEventListener("click", () => { other = item.name; draw(false); });
      return button;
    })), name ? markdown(name, "") : null];
  }

  function draw(keepScroll) {
    const y = window.scrollY;
    app.replaceChildren(...header(), ribbon(), actions(), h("section", {class: "card desk"}, nav(), h("div", {class: "pane"}, body())),
      h("footer", null, t("desk.footer", {as_of: when(desk.as_of, 0, 19)}), copyright()));
    if (keepScroll) window.scrollTo(0, y);
  }

  document.querySelector("main").classList.add("wide");
  draw(false);
  if (typeof SERVE !== "undefined" && DATA.serve.refresh) {
    setInterval(() => {
      if (SERVE.busy()) return;
      SERVE.post("/api/desk", {task: desk.name}).then((data) => {
        const text = JSON.stringify(data.desk);
        if (same(text, shown)) return;
        desk = data.desk;
        shown = text;
        draw(true);
      }, () => {});
    }, DATA.serve.refresh * 1000);
  }
})();
