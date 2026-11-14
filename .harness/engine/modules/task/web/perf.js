// The small part of the Agent Performance Review on a task's report page (1.7.41). DATA.info.perf is perfreview.summary_view: the facts of the task (layer 1) and the
// newest review's one line. The credits, the time and the dearest prompt are not repeated here: the report above has them, counted the same way. The rest is on the review page (`/tasks/<task>/performance`, perfpage.js).
// A served page has the link to that page and the button that starts a review (an rca task, high thinking, the person's model).
"use strict";

const PERF = (function () {
  function start(name, tokens, again) {
    const go = h("button", {type: "button", class: again ? "first-link" : "act hot", title: t("report.perf.start.hint")}, t(again ? "report.perf.again" : "report.perf.start"));
    go.addEventListener("click", () => CHAT.create({name: ("apr-" + name + (again ? "-2" : "")).slice(0, 80), kind: "rca", text: t("report.perf.start.text", {task: name}),
      note: t("report.perf.start.note", {tokens: amount(tokens || 0)}), thinking: "high"}));
    return go;
  }

  function section(perf, served) {
    if (!perf) return null;
    const title = t("report.perf.title");
    const total = perf.totals;
    const review = perf.review;
    const web = /^https?:$/.test(location.protocol);
    const nodes = [];
    if (!total) {
      if (!served) return null;
      return card(title, h("p", {class: "sub"}, t("report.perf.norecord")));
    }
    const facts = total.facts || {};
    const trouble = (facts.failed || 0) + (facts.refused || 0) + (facts.held || 0);
    const again = (facts.retry || 0) + (facts.repeat || 0);
    const waste = review && review.waste;
    nodes.push(h("div", {class: "kpis pf-kpis"},
      kpi(trouble, t("report.perf.kpi.trouble")), kpi(again, t("report.perf.kpi.again")), kpi(total.interventions || 0, t("report.perf.kpi.interventions")),
      waste ? kpi(percent(waste.share_aiu || 0), t("report.perf.kpi.waste")) : null));
    const lines = [];
    if (review && review.findings && review.findings.summary) lines.push(h("p", {class: "pf-summary"}, review.findings.summary));
    else if (total.quiet) lines.push(h("p", {class: "sub"}, t("report.perf.quiet")));
    if (review && !review.findings) lines.push(h("p", {class: "sub"}, t("report.perf.waiting")));
    if (review && review.findings && review.ok === false) lines.push(h("p", {class: "bad"}, t("report.perf.unchecked", {n: review.problems})));
    nodes.push(...lines);
    const row = h("div", {class: "row pf-actions"});
    if (web) row.append(h("a", {class: "act", href: "/tasks/" + encodeURIComponent(perf.name) + "/performance", title: t("report.perf.open.hint")}, t("report.perf.open")));
    if (review) row.append(h("span", {class: "sub"}, t("report.perf.by") + " ", web ? h("a", {href: "/task/" + encodeURIComponent(review.name)}, review.name) : h("code", null, review.name)));
    if (served && typeof CHAT !== "undefined") row.append(start(perf.name, perf.read_tokens, Boolean(review)));
    if (row.childElementCount) nodes.push(row);
    return card(title, nodes);
  }

  return {section};
})();
