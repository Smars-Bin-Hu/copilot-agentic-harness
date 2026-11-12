// The Agent Performance Review of a task, on its report page (1.7.41). DATA.info.perf is perfreview.page_view: {subject, review}.
// No review yet: on a served page, the button that opens an rca task for it (the skill harness-agent-performance-review). A review: what the code found
// (the numbers, a strip of every call coloured by how it ended, the candidates) and what the review's agent judged (FINDINGS.json): each finding with its
// class, verdict and evidence, and the suggestions. The evidence of a finding opens in place: the command, what the gate or the tool said, the thinking before it.
"use strict";

const PERF = (function () {
  const OUTCOMES = ["ok", "person", "failed", "refused", "held", "running"];
  const PRIORITY = {high: 0, medium: 1, low: 2};

  function startButton(name) {
    const go = h("button", {type: "button", class: "act hot", title: t("report.perf.start.hint")}, t("report.perf.start"));
    go.addEventListener("click", () => CHAT.create({name: ("apr-" + name).slice(0, 80), kind: "rca", text: t("report.perf.start.text", {task: name}), note: t("report.perf.start.note")}));
    return go;
  }

  function strip(review) {
    const calls = review.strip;
    if (!calls.length) return null;
    const flagged = new Set(review.candidates.flatMap((item) => item.calls));
    const end = Math.max(1, ...calls.map(([, at, seconds]) => at + seconds));
    const mark = ([id, at, seconds, outcome, prompt, agent]) => h("i", {
      class: "pf-call pf-" + outcome + (flagged.has(id) ? " pf-flag" : ""),
      style: `left:${((at / end) * 100).toFixed(2)}%;width:max(3px,${((seconds / end) * 100).toFixed(2)}%)`,
      title: (agent ? agent + " · " : "") + t("report.perf.strip.tip", {id, outcome: t("report.perf.outcome." + outcome), seconds: clock(seconds), prompt}),
    });
    const names = ["", ...[...new Set(calls.map((call) => call[5] || ""))].filter(Boolean)];  // the main agent first, then each subagent: a lane each
    const lanes = names.map((agent) => h("div", {class: "pf-lane"}, names.length > 1 ? h("span", {class: "pf-lane-name sub", title: agent || t("report.perf.main")}, agent || t("report.perf.main")) : null,
      h("div", {class: "pf-strip", role: "img", "aria-label": t("report.perf.strip") + (agent ? " · " + agent : "")}, calls.filter((call) => (call[5] || "") === agent).map(mark))));
    const counts = OUTCOMES.map((name) => [name, calls.filter((call) => call[3] === name).length]).filter(([, n]) => n);
    return [
      lanes,
      h("div", {class: "pf-axis sub" + (names.length > 1 ? " pf-axis-lanes" : "")}, h("span", null, "0"), h("span", null, clock(end))),
      h("div", {class: "pf-stack"}, counts.map(([name, n]) => h("i", {class: "pf-" + name, style: `flex:${n}`, title: t("report.perf.outcome." + name) + " " + n}))),
      h("div", {class: "legend"}, counts.map(([name, n]) => h("span", null, h("i", {class: "pf-" + name}), t("report.perf.outcome." + name) + " ", h("b", null, String(n)))),
        h("span", null, h("i", {class: "pf-flag-key"}), t("report.perf.flagged") + " ", h("b", null, String(flagged.size)))),
      review.cut ? h("p", {class: "sub"}, t("report.perf.cut", {n: review.cut})) : null,
    ];
  }

  // One call or thought of the evidence, opened in place.
  function evidence(review, ids) {
    return h("div", {class: "pf-evidence"}, ids.map((id) => {
      const item = review.detail[id];
      if (!item) return h("span", {class: "tag"}, id);
      const box = h("details", {class: "pf-ev"});
      const head = id.startsWith("t") ? t("report.perf.thought", {id}) : id + (item.agent ? " · " + item.agent : "") + " · " + t("report.perf.outcome." + item.outcome) + (item.gate && item.gate.decision !== "passed" ? " · " + (item.gate.system || item.gate.rule) : "");
      box.append(h("summary", null, h("code", null, head)));
      box.addEventListener("toggle", () => {
        if (!box.open || box.childElementCount > 1) return;
        if (id.startsWith("t")) { box.append(h("blockquote", null, item.text)); return; }
        box.append(h("pre", {class: "pf-args"}, item.args));
        if (item.error) box.append(h("p", {class: "sub"}, t("report.perf.said")), h("pre", {class: "pf-said"}, item.error));
        else if (item.result) box.append(h("p", {class: "sub"}, t("report.perf.result")), h("pre", {class: "pf-said"}, item.result));
        const thought = item.thought && review.detail[item.thought];
        if (thought) box.append(h("p", {class: "sub"}, t("report.perf.before")), h("blockquote", null, thought.text));
      });
      return box;
    }));
  }

  function candidateList(review, only) {
    const list = only ? review.candidates.filter((item) => only.includes(item.id)) : review.candidates;
    if (!list.length) return null;
    return h("ol", {class: "pf-list"}, list.map((item) => h("li", null,
      h("div", {class: "pf-line"}, tag(t("report.perf.rule." + item.rule), item.rule === "followed" ? "good" : "hot"), item.agent ? tag(item.agent) : null, h("span", null, item.note)),
      item.calls.length ? evidence(review, item.calls) : null)));
  }

  function findingList(review) {
    const found = (review.findings.findings || []).filter((item) => item && typeof item === "object");
    if (!found.length) return null;
    return h("ol", {class: "pf-list"}, found.map((item) => h("li", null,
      h("div", {class: "pf-line"},
        tag(t("report.perf.class." + item.class), item.class === "guardrail" ? "good" : item.class === "agent" ? "hot" : ""),
        tag(t("report.perf.verdict." + item.verdict), item.verdict === "confirmed" ? "" : "soft"),
        h("b", null, item.title || "")),
      item.why ? h("p", null, item.why) : null,
      item.impact ? h("p", {class: "sub"}, t("report.perf.impact", {text: item.impact})) : null,
      item.change && item.change.what ? h("p", {class: "pf-change"}, t("report.perf.change"), " ", item.change.file ? h("code", null, item.change.file) : null, " ", item.change.what) : null,
      (item.evidence || []).length ? evidence(review, item.evidence) : null)));
  }

  function suggestionList(review) {
    const list = (review.findings.suggestions || []).filter((item) => item && item.what).sort((a, b) => (PRIORITY[a.priority] ?? 3) - (PRIORITY[b.priority] ?? 3));
    if (!list.length) return null;
    return h("ol", {class: "pf-list"}, list.map((item) => h("li", null,
      h("div", {class: "pf-line"}, tag(t("report.perf.priority." + item.priority), item.priority === "high" ? "hot" : ""), h("b", null, item.title || item.what)),
      item.title ? h("p", null, item.what) : null,
      item.file ? h("p", {class: "sub"}, h("code", null, item.file)) : null,
      item.why ? h("p", {class: "sub"}, item.why) : null)));
  }

  function section(perf, served) {
    if (!perf) return null;
    const name = perf.subject.split("/").pop();
    const review = perf.review;
    const title = t("report.perf.title");
    if (!review) {
      if (!served) return null;
      return card(title, h("p", {class: "sub"}, t("report.perf.none")), startButton(name));
    }
    const link = /^https?:$/.test(location.protocol) ? h("a", {href: "/task/" + encodeURIComponent(review.name)}, review.name) : h("code", null, review.name);
    const head = h("p", {class: "sub"}, t("report.perf.by"), " ", link, " · ", t("report.status." + (review.status === "open" ? "open" : "closed")),
      served ? [" · ", (() => { const again = h("button", {type: "button", class: "first-link"}, t("report.perf.again")); again.addEventListener("click", () => CHAT.create({name: ("apr-" + name + "-2").slice(0, 80), kind: "rca", text: t("report.perf.start.text", {task: name}), note: t("report.perf.start.note")})); return again; })()] : null);
    if (!review.numbers) return card(title, head, h("p", {class: "sub"}, t("report.perf.waiting")));
    const n = review.numbers;
    const nodes = [head,
      h("div", {class: "kpis"}, kpi(n.calls, t("report.perf.kpi.calls")), kpi(n.failed || 0, t("report.perf.kpi.failed")), kpi(n.refused || 0, t("report.perf.kpi.refused")),
        kpi(n.held || 0, t("report.perf.kpi.held")), kpi(review.candidates.length, t("report.perf.kpi.candidates")), kpi(clock(n.tool_s || 0), t("report.perf.kpi.tools"))),
      h("h3", null, t("report.perf.calls")), strip(review),
      (review.agents || []).length ? h("p", {class: "sub"}, t("report.perf.subagents"), " ", (review.agents || []).map((item, n) => [n ? ", " : "", h("b", null, item.name), " " + t("report.perf.subagent.line", {n: item.calls, by: item.by || "?"})])) : null];
    if (review.source === "hook-log") nodes.push(h("p", {class: "sub"}, t("report.perf.hooklog")));
    if (review.findings) {
      if (review.findings.summary) nodes.push(h("h3", null, t("report.perf.summary")), h("p", {class: "pf-summary"}, review.findings.summary));
      nodes.push(h("h3", null, t("report.perf.findings")), findingList(review) || h("p", {class: "sub"}, t("report.perf.nofindings")));
      const left = review.checked && review.checked.left && review.checked.left.length ? review.checked.left : null;
      if (left) nodes.push(h("details", {class: "pf-left"}, h("summary", null, t("report.perf.left", {n: left.length})), candidateList(review, left)));
      if (review.checked && !review.checked.ok) nodes.push(h("p", {class: "bad"}, t("report.perf.unchecked", {n: review.checked.problems.length})));
      nodes.push(h("h3", null, t("report.perf.suggestions")), suggestionList(review) || h("p", {class: "sub"}, t("report.perf.nosuggestions")));
    } else {
      nodes.push(h("h3", null, t("report.perf.candidates")), h("p", {class: "sub"}, t("report.perf.judging")), candidateList(review) || h("p", {class: "sub"}, t("report.perf.nocandidates")));
    }
    return card(title, nodes);
  }

  return {section};
})();
