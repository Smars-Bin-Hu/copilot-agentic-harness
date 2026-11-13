// The Agent Performance Review page of a task (`/tasks/<task>/performance`, 1.7.41). DATA.perf is perfreview.page_data. Read only.
// Top: the conclusion, the accounts and the waste by owner. Then a row per prompt (its AIU or agent time, its origin, where the person stepped in, the waste in it; a click
// opens its notes, the same as `harness task performance --prompt`), the findings by owner as chains with their evidence, the prompt critiques, the suggestions by owner,
// the call timeline with a lane per subagent, and the facts. With no review the page shows the accounts the code made (layer 1) and says so.
"use strict";

(function () {
  const OWNERS = ["person", "harness", "model", "environment", "platform", "knowledge", "unknown"];
  const OUTCOMES = ["ok", "person", "failed", "refused", "held", "running"];
  const PRIORITY = {high: 0, medium: 1, low: 2};
  const CHAIN = ["said", "context", "thought", "action", "result"];
  const perf = DATA.perf;
  const app = document.getElementById("app");
  const ev = perf.evidence;
  const review = perf.review;
  const found = (review && review.findings) || null;
  const waste = review && review.waste;
  let metric = "aiu";

  const owner = (name) => h("span", {class: "tag pf-own pf-o-" + name, title: t("report.perf.owner.tip." + name)}, t("report.perf.owner." + name));
  const ownerOf = (name) => (OWNERS.includes(name) ? name : "unknown");

  function head() {
    const back = h("a", {class: "act", href: "/tasks/" + encodeURIComponent(perf.name) + "/report.html"}, "← " + t("report.perf.back"));
    const facts = [];
    if (review) facts.push(t("report.perf.by") + " ", h("a", {href: "/task/" + encodeURIComponent(review.name)}, review.name));
    if (ev && ev.made_at) facts.push((facts.length ? " · " : "") + when(ev.made_at, 0, 16));
    return h("header", {class: "pf-head"}, h("div", {class: "row"}, back, h("h1", null, t("report.perf.page.title", {name: perf.name}))), facts.length ? h("p", {class: "sub"}, facts) : null);
  }

  function ownerBar() {
    if (!waste || !waste.by_owner) return null;
    const parts = Object.entries(waste.by_owner).map(([name, cost]) => [ownerOf(name), cost]).sort((a, b) => OWNERS.indexOf(a[0]) - OWNERS.indexOf(b[0]));
    const whole = parts.reduce((sum, [, cost]) => sum + (cost.aiu || 0), 0);
    if (!whole) return null;
    return [h("h3", null, t("report.perf.owners")),
      h("div", {class: "pf-ownbar"}, parts.map(([name, cost]) => h("i", {class: "pf-o-" + name, style: `flex:${cost.aiu}`, title: t("report.perf.owner." + name) + " · " + amount(cost.aiu) + " Credits · " + clock(cost.work_s)}))),
      h("div", {class: "legend"}, parts.map(([name, cost]) => h("span", {title: t("report.perf.owner.tip." + name)}, h("i", {class: "pf-o-" + name}), t("report.perf.owner." + name) + " ", h("b", null, amount(cost.aiu) + " Credits"))))];
  }

  function short() {
    const total = ev.totals;
    const facts = total.facts || {};
    const nodes = [];
    if (found && found.summary) nodes.push(h("p", {class: "pf-summary"}, found.summary));
    else if (review && !found) nodes.push(h("p", {class: "sub"}, t("report.perf.waiting")));
    else if (!review) nodes.push(h("p", {class: "sub"}, t("report.perf.live")));
    if (!found && total.quiet) nodes.push(h("p", {class: "sub"}, t("report.perf.quiet")));
    if (ev.source === "hook-log") nodes.push(h("p", {class: "sub"}, t("report.perf.hooklog")));
    if (review && found && review.ok === false) nodes.push(h("p", {class: "bad"}, t("report.perf.unchecked", {n: review.problems})));
    nodes.push(h("div", {class: "kpis pf-kpis"},
      kpi(amount(total.aiu), t("report.perf.kpi.aiu")), kpi(clock(total.work_s), t("report.perf.kpi.work")), total.person_s ? kpi(clock(total.person_s), t("report.perf.kpi.person")) : null,
      kpi((facts.failed || 0) + (facts.refused || 0) + (facts.held || 0), t("report.perf.kpi.trouble")), kpi((facts.retry || 0) + (facts.repeat || 0), t("report.perf.kpi.again")),
      kpi(total.interventions || 0, t("report.perf.kpi.interventions")), waste ? kpi(percent(waste.share_aiu || 0), t("report.perf.kpi.waste")) : null));
    if (waste && waste.aiu) nodes.push(h("p", null, t("report.perf.waste", {aiu: amount(waste.aiu), share: percent(waste.share_aiu || 0), time: clock(waste.work_s), tshare: percent(waste.share_time || 0)})));
    nodes.push(ownerBar());
    return card(t("report.perf.summary"), nodes);
  }

  // A row per prompt. The bar is the prompt's AIU or agent time against the dearest; the red part is the waste the review found in it.
  function prompts() {
    const rows = ev.prompts;
    if (!rows.length) return null;
    const wasted = {};
    for (const item of Object.values(ev.segments || {})) {
      if (item.verdict === "waste" && item.prompt) {
        const mine = wasted[item.prompt] || (wasted[item.prompt] = {aiu: 0, work_s: 0, ids: []});
        mine.aiu += item.aiu || 0; mine.work_s += item.work_s || 0;
      }
    }
    for (const [id, item] of Object.entries(ev.segments || {})) if (item.verdict === "waste" && item.prompt) wasted[item.prompt].ids.push(id);
    const value = (row) => (metric === "aiu" ? row.aiu || 0 : row.work_s || 0);
    const box = h("div", {class: "pf-prompts"});
    const draw = () => {
      const most = Math.max(0.0001, ...rows.map(value));
      box.replaceChildren(...rows.map((row) => {
        const lost = wasted[row.n];
        const lostValue = lost ? (metric === "aiu" ? lost.aiu : lost.work_s) : 0;
        const facts = Object.entries(row.facts || {}).filter(([name]) => !["intervention", "person"].includes(name));
        const line = h("button", {type: "button", class: "pf-prow" + (row.intervention ? " pf-int" : ""), "aria-expanded": "false"},
          h("span", {class: "pf-pn"}, "P" + row.n),
          h("span", {class: "tag pf-src pf-src-" + row.origin, title: t("report.perf.origin.tip." + row.origin)}, t("report.perf.origin." + row.origin)),
          h("span", {class: "pf-flag-int", title: row.intervention ? t("report.perf.intervention.tip") : ""}, row.intervention ? "⚑" : ""),
          h("span", {class: "pf-track"}, h("i", {class: "pf-fill", style: `width:${((value(row) / most) * 100).toFixed(2)}%`}),
            lostValue ? h("i", {class: "pf-lost", style: `width:${((Math.min(lostValue, value(row)) / most) * 100).toFixed(2)}%`, title: lost.ids.join(", ")}) : null),
          h("span", {class: "pf-val"}, metric === "aiu" ? amount(row.aiu) : clock(row.work_s)),
          h("span", {class: "pf-mini"}, facts.map(([name, n]) => h("span", {class: "pf-fact pf-f-" + name, title: t("report.perf.fact." + name)}, n + " " + t("report.perf.fact." + name)))),
          h("span", {class: "pf-star", title: row.worth.length ? t("report.perf.worth", {why: row.worth.map((why) => t("report.perf.why." + why)).join(", ")}) : ""}, row.worth.length ? "★" : ""));
        const words = row.words ? h("p", {class: "sub pf-words"}, row.words) : null;
        const more = h("div", {class: "pf-notes", hidden: ""});
        line.addEventListener("click", () => {
          const open = more.hidden;
          more.hidden = !open;
          line.setAttribute("aria-expanded", open ? "true" : "false");
          if (open && !more.childElementCount) more.append(row.notes ? h("pre", null, row.notes.join("\n")) : h("p", {class: "sub"}, t("report.perf.notes.cut", {n: row.n})));
        });
        return h("div", {class: "pf-prompt"}, line, words, more);
      }));
    };
    const chips = ["aiu", "time"].map((name) => {
      const chip = h("button", {type: "button", class: "chip" + (name === "aiu" ? " on" : ""), "aria-pressed": name === "aiu" ? "true" : "false"}, t("report.perf.metric." + name));
      chip.addEventListener("click", () => { metric = name === "aiu" ? "aiu" : "time"; chips.forEach((item, at) => { const on = ["aiu", "time"][at] === name; item.classList.toggle("on", on); item.setAttribute("aria-pressed", on ? "true" : "false"); }); draw(); });
      return chip;
    });
    draw();
    return card(t("report.perf.prompts"), h("div", {class: "row pf-tools"}, h("div", {class: "chips"}, chips), h("span", {class: "sub pf-hint", title: t("report.perf.prompts.hint")}, "ⓘ")), box);
  }

  // One call, thought, piece of context or prompt the evidence names, opened in place.
  function evidence(ids) {
    return h("div", {class: "pf-evidence"}, ids.map((id) => {
      const item = ev.detail[id];
      if (!item) return h("span", {class: "tag"}, id);
      const box = h("details", {class: "pf-ev"});
      const label = item.kind === "call" ? id + (item.agent ? " · " + item.agent : "") + " · " + item.tool + " · " + t("report.perf.outcome." + item.outcome) + (item.gate && item.gate.decision !== "passed" ? " · " + (item.gate.system || item.gate.rule) : "")
        : id + " · " + (item.what || item.kind) + (item.ref ? " · " + item.ref : "") + (item.prompt ? " · P" + item.prompt : "");
      box.append(h("summary", null, h("code", null, label)));
      box.addEventListener("toggle", () => {
        if (!box.open || box.childElementCount > 1) return;
        if (item.kind !== "call") { box.append(h("pre", {class: "pf-said"}, item.text)); return; }
        if (item.thought) box.append(h("blockquote", null, item.thought));
        box.append(h("pre", {class: "pf-args"}, item.args));
        if (item.error || item.result) box.append(h("pre", {class: "pf-said"}, item.error || item.result));
      });
      return box;
    }));
  }

  function chainOf(chain) {
    if (!chain || typeof chain !== "object") return null;
    const steps = CHAIN.filter((key) => chain[key]);
    if (!steps.length) return null;
    return h("ol", {class: "pf-chain"}, steps.map((key) => {
      const text = String(chain[key]);
      return h("li", null, h("span", {class: "sub"}, t("report.perf.chain." + key)), ev.detail[text.trim()] ? evidence([text.trim()]) : h("span", null, text));
    }));
  }

  function findings() {
    if (!found) return null;
    const list = (found.findings || []).filter((item) => item && typeof item === "object");
    if (!list.length) return card(t("report.perf.findings"), h("p", {class: "sub"}, t("report.perf.nofindings")));
    const groups = OWNERS.map((name) => [name, list.filter((item) => ownerOf(item.owner) === name)]).filter(([, items]) => items.length);
    return card(t("report.perf.findings"), groups.map(([name, items]) => h("section", {class: "pf-group"}, h("h3", null, owner(name)),
      items.map((item) => {
        const segs = (item.segments || []).map((id) => [id, (ev.segments || {})[id]]).filter(([, seg]) => seg);
        return h("details", {class: "pf-finding"},
          h("summary", null, tag(t("report.perf.confidence." + item.confidence), item.confidence === "certain" ? "" : "soft"), " ", h("b", null, item.title || ""),
            segs.map(([id, seg]) => h("span", {class: "sub pf-seg", title: seg.what}, " · " + (seg.verdict === "waste" ? t("report.perf.segment", {span: seg.span || id, aiu: amount(seg.aiu), time: clock(seg.work_s)}) : seg.span || id)))),
          item.why ? h("p", null, item.why) : null,
          chainOf(item.chain),
          (item.evidence || []).length ? [h("p", {class: "sub"}, t("report.perf.evidence")), evidence(item.evidence)] : null);
      }))));
  }

  function critiques() {
    const list = ((found && found.prompts) || []).filter((item) => item && item.original);
    if (!list.length) return null;
    return card(t("report.perf.critiques"), list.map((item) => h("div", {class: "pf-crit"},
      h("div", {class: "pf-crit-head"}, h("b", null, "P" + item.prompt)),
      h("div", {class: "pf-crit-grid"},
        h("span", {class: "sub"}, t("report.perf.critique.original")), h("blockquote", null, item.original),
        h("span", {class: "sub"}, t("report.perf.critique.problem")), h("p", null, item.problem || ""),
        h("span", {class: "sub"}, t("report.perf.critique.better")), h("blockquote", {class: "pf-better"}, item.better || "")))));
  }

  function suggestions() {
    if (!found) return null;
    const list = (found.suggestions || []).filter((item) => item && item.what).sort((a, b) => (PRIORITY[a.priority] ?? 3) - (PRIORITY[b.priority] ?? 3));
    if (!list.length) return card(t("report.perf.suggestions"), h("p", {class: "sub"}, t("report.perf.nosuggestions")));
    const groups = OWNERS.map((name) => [name, list.filter((item) => ownerOf(item.for) === name)]).filter(([, items]) => items.length);
    return card(t("report.perf.suggestions"), groups.map(([name, items]) => h("section", {class: "pf-group"}, h("h3", null, owner(name)),
      h("ol", {class: "pf-list"}, items.map((item) => h("li", null,
        h("div", {class: "pf-line"}, tag(t("report.perf.priority." + item.priority), item.priority === "high" ? "hot" : ""), h("span", null, item.what)),
        item.file ? h("p", {class: "sub"}, h("code", null, item.file)) : null,
        item.why ? h("p", {class: "sub"}, item.why) : null))))));
  }

  function timeline() {
    const calls = ev.strip;
    if (!calls.length) return null;
    const end = Math.max(1, ...calls.map(([, at, seconds]) => at + seconds));
    const mark = ([id, at, seconds, outcome, prompt, agent]) => h("i", {
      class: "pf-call pf-" + outcome,
      style: `left:${((at / end) * 100).toFixed(2)}%;width:max(3px,${((seconds / end) * 100).toFixed(2)}%)`,
      title: (agent ? agent + " · " : "") + t("report.perf.strip.tip", {id, outcome: t("report.perf.outcome." + outcome), seconds: clock(seconds), prompt}),
    });
    const names = ["", ...[...new Set(calls.map((call) => call[5] || ""))].filter(Boolean)];  // the main agent first, then each subagent: a lane each
    const lanes = names.map((agent) => h("div", {class: "pf-lane"}, h("span", {class: "pf-lane-name sub", title: agent || t("report.perf.main")}, agent || t("report.perf.main")),
      h("div", {class: "pf-strip", role: "img", "aria-label": t("report.perf.strip") + (agent ? " · " + agent : "")}, calls.filter((call) => (call[5] || "") === agent).map(mark))));
    const counts = OUTCOMES.map((name) => [name, calls.filter((call) => call[3] === name).length]).filter(([, n]) => n);
    return card(t("report.perf.timeline"), lanes, h("div", {class: "pf-axis sub"}, h("span", null, "0"), h("span", null, clock(end))),
      h("div", {class: "legend"}, counts.map(([name, n]) => h("span", null, h("i", {class: "pf-" + name}), t("report.perf.outcome." + name) + " ", h("b", null, String(n))))),
      ev.cut ? h("p", {class: "sub"}, t("report.perf.cut", {n: ev.cut})) : null);
  }

  function facts() {
    const list = ev.facts.filter((item) => item.fact !== "person");
    if (!list.length) return null;
    const box = h("details", {class: "pf-facts"}, h("summary", null, t("report.perf.facts") + " · " + list.length, " ", h("span", {class: "sub", title: t("report.perf.facts.hint")}, "ⓘ")),
      h("ol", {class: "pf-list"}, list.map((item) => h("li", null,
        h("div", {class: "pf-line"}, tag(t("report.perf.fact." + item.fact), ["failed", "refused", "retry", "repeat"].includes(item.fact) ? "hot" : ""), h("code", null, item.id),
          h("span", {class: "sub"}, "P" + item.prompt), item.agent ? tag(item.agent) : null, h("span", null, item.note)),
        item.calls.length ? evidence(item.calls) : null))));
    return card("", box);
  }

  function draw() {
    app.replaceChildren(head());
    if (!ev) { app.append(card("", h("p", {class: "sub"}, t("report.perf.none")))); return; }
    for (const node of [short(), prompts(), findings(), critiques(), suggestions(), timeline(), facts()]) if (node) app.append(node);
  }

  draw();
})();
