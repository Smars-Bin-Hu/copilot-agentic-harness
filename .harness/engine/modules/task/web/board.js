// The board: every task, what it waits for, its time and usage. DATA.rows is what `task list` gives, each row with
// `brief` (a few numbers of the task, or null) and `report` (the path of its page from the board's folder, or "").
// `actions`: what the person can do about the task, each with the command to paste in a terminal.
// DATA.refresh: the seconds between two boards while `task board --refresh` runs, or 0.
// DATA.serve: set when `task board --serve` sends the page, with serve.js (SERVE) before this script.
"use strict";

(function () {
  const rows = DATA.rows;
  const app = document.getElementById("app");
  const waiting = rows.filter((row) => row.waiting);
  const briefs = rows.filter((row) => row.brief).map((row) => row.brief);
  const usage = briefs.filter((brief) => brief.aiu !== null).map((brief) => brief.aiu);
  const sum = (values) => values.reduce((total, value) => total + value, 0);

  document.querySelector("main").classList.add("wide");
  app.replaceChildren(
    h("h1", null, t("board.brand")),
    h("div", {class: "sub"}, h("b", null, t("board.title")), " · ", DATA.serve ? t("board.subtitle.served", {as_of: when(DATA.as_of, 0, 19), seconds: DATA.serve.refresh})
      : t(DATA.refresh ? "board.subtitle.fresh" : "board.subtitle", {as_of: when(DATA.as_of, 0, 19), seconds: DATA.refresh})),
    h("div", {class: "kpis"},
      kpi(rows.filter((row) => row.status === "open").length, t("board.kpi.open")),
      kpi(waiting.length, t("board.kpi.waiting")),
      kpi(waiting.length ? clock(Math.max(...waiting.map((row) => row.waited_s || 0))) : "-", t("board.kpi.longest")),
      kpi(clock(sum(briefs.map((brief) => brief.active_s))), t("board.kpi.active")),
      kpi(usage.length ? amount(sum(usage)) : "-", t("board.kpi.aiu"))));
  if (!rows.length) {
    app.append(h("div", {class: "card empty"}, t("board.empty")));
    return;
  }

  const longest = Math.max(0, ...briefs.map((brief) => brief.active_s + brief.waiting_s)) || 1;
  const head = [th(t("board.col.task")), th(t("board.col.kind")), th(t("board.col.waiting")), th(t("board.col.waited"), true), th(t("board.col.time")), th("", true),
    th("AIU", true), th(t("board.col.prompts"), true), th(t("board.col.reviews"), true), th(t("board.col.updated")), th(t("board.col.actions"))];

  function actionCell(row) {
    const buttons = (row.actions || []).map((item) => actionButton(row, item));
    return h("td", {class: "acts"}, buttons.length ? buttons : "-");
  }

  function state(row) {
    if (row.status !== "open") return tag(t("board.state." + (row.status === "new" ? "new" : "closed")));
    if (row.paused_since) return tag(t("board.state.paused"));
    return row.waiting ? tag(row.waiting, "hot long") : tag(t("board.state.running"), "good");
  }

  const lines = rows.map((row) => {
    const brief = row.brief;
    const kind = row.status === "new" ? "-" : t("task.kind." + (row.kind || "none")) + " · " + t("task.tier." + (row.tier || "none"));
    return h("tr", null,
      h("td", {class: "name"}, DATA.serve && row.status !== "new" ? h("a", {href: "/task/" + encodeURIComponent(row.name)}, row.name)
        : row.report ? h("a", {href: row.report.split("/").map(encodeURIComponent).join("/")}, row.name) : row.name,
        row.depends_on && row.depends_on.length ? h("div", {class: "sub"}, t("board.depends", {names: row.depends_on.join("、")})) : null),
      h("td", {class: "kind"}, kind), h("td", {class: "state"}, state(row)),
      num(row.waiting && row.waited_s !== null ? clock(row.waited_s) : "-"),
      brief
        ? [h("td", {style: "width:18%"}, bar([
            ["work", brief.active_s, t("report.active") + " " + clock(brief.active_s)],
            ["wait", brief.waiting_s, t("report.waiting") + " " + clock(brief.waiting_s)]], longest, true)),
          num(clock(brief.active_s)), num(amount(brief.aiu)), num(brief.prompts), num(brief.reviews ? reviewsText(brief.reviews, brief.review_fails) : "-")]
        : [h("td"), num("-"), num("-"), num("-"), num("-")],
      h("td", {class: "sub when"}, when(row.updated_at, 5, 16)), actionCell(row));
  });
  app.append(
    h("div", {class: "card"}, table(head, lines), legend([["work", t("report.active"), ""], ["wait", t("report.waiting"), ""]])),
    h("footer", null, t("board.footer"), " ", t(DATA.serve ? "board.copy.hint.served" : "board.copy.hint")), copyright());

  if (typeof SERVE !== "undefined") SERVE.start(app);
})();
