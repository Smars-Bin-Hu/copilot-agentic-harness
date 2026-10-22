// One task: where its time and usage went. DATA.info is what taskinsight.build returns.
// DATA.now: what the task waits for at this moment ({text, why, since, seconds}), or null. That wait is counted in the numbers of info.
"use strict";

(function () {
  const info = DATA.info;
  const totals = info.totals;
  const app = document.getElementById("app");
  const PARTS = ["model", "tool", "subagent", "approval", "other"];
  const active = totals.active_s, waiting = totals.waiting_s;
  const hasSplit = totals.model_s !== null, hasUsage = totals.aiu !== null;
  const partLabel = (name) => t("insight.part." + name);

  function timeParts(entry) {
    if (entry.model_s === null) return [["work", entry.active_s, t("report.active") + " " + clock(entry.active_s)]];
    return PARTS.map((name) => [name, entry[name + "_s"] || 0, partLabel(name) + " " + clock(entry[name + "_s"])]);
  }

  // Served by the board: the way back to the task page and to the board. A file on disk has no server to go back to.
  function crumbs() {
    if (!/^https?:$/.test(location.protocol)) return null;
    return h("div", {class: "crumbs sub"}, h("a", {href: "/"}, "\u2190 " + t("desk.back")), " \u00b7 ",
      h("a", {href: "/task/" + encodeURIComponent(info.name)}, t("report.back")));
  }

  function header() {
    return [
      brand(),
      crumbs(),
      h("h1", null, t("report.title", {name: info.name})),
      h("div", {class: "sub"}, t("report.subtitle", {
        kind: t("task.kind." + (info.kind || "none")), tier: t("task.tier." + (info.tier || "none")),
        status: t("report.status." + (info.status === "open" ? "open" : "closed")),
        start: when(info.span.from, 0, 16), end: when(info.span.to, 0, 16), as_of: when(info.as_of, 0, 19),
      })),
      DATA.now ? h("div", {class: "now"}, tag(t("report.now", {text: DATA.now.text, time: clock(DATA.now.seconds)}), "hot long")) : null,
      h("div", {class: "kpis"},
        kpi(clock(active), t("report.kpi.active")),
        kpi(clock(waiting), t("report.kpi.waiting")),
        kpi(totals.prompts, t("report.kpi.prompts")),
        kpi(amount(totals.aiu), t("report.kpi.aiu")),
        kpi(amount(totals.premium_requests), t("report.kpi.premium")),
        kpi(reviewsText(totals.reviews, totals.review_fails), t("report.kpi.reviews"))),
    ];
  }

  function footer(note) {
    const line = t("report.footer", {source: t("report.source." + info.source.replace("-", "_"))});
    return h("footer", null, line, note ? [h("br"), t("report.footer.note")] : null, copyright());
  }

  function findings() {
    return card(t("report.findings"), h("ol", {class: "findings"}, info.findings.map((item) => h("li", null, item.text))));
  }

  function timeCard() {
    const whole = active + waiting;
    const nodes = [
      bar([["work", active, t("report.active") + " " + clock(active)], ["wait", waiting, t("report.waiting") + " " + clock(waiting)]], whole),
      legend([
        ["work", t("report.active"), clock(active) + " · " + percent(share(active, whole))],
        ["wait", t("report.waiting"), clock(waiting) + " · " + percent(share(waiting, whole))],
      ]),
    ];
    if (hasSplit) {
      nodes.push(h("div", {style: "height:16px"}), bar(timeParts(totals), active),
        legend(PARTS.map((name) => [name, partLabel(name), clock(totals[name + "_s"]) + " · " + percent(share(totals[name + "_s"], active))])));
    }
    return card(t("report.time"), nodes);
  }

  function promptsCard() {
    const longest = Math.max(...info.prompts.map((entry) => entry.active_s)) || 1;
    const dearest = Math.max(...info.prompts.map((entry) => entry.aiu || 0)) || 1;
    const head = [th("#"), th(t("report.col.at")), th(t("report.col.stage")), th(t("report.col.time")), th("", true),
      hasUsage ? [th("AIU"), th("", true)] : null, th(t("report.col.turns"), true), th(t("report.col.calls"), true)];
    const columns = hasUsage ? 9 : 7;
    const rows = [];
    for (const entry of info.prompts) {
      const notes = [["report.tag.denied", "denied"], ["report.tag.blocks", "stop_blocks"], ["report.tag.failed", "failed_tool_calls"]]
        .filter(([, field]) => entry[field]).map(([key, field]) => [" ", tag(t(key, {n: entry[field]}), "bad")]);
      rows.push(h("tr", null,
        h("td", null, entry.n), h("td", {class: "when"}, when(entry.at, 5, 16)),
        h("td", null, tag(entry.stage_label || entry.stage), notes, entry.text ? h("div", {class: "sub said", title: entry.text}, entry.text) : null),
        h("td", {class: "grow"}, bar(timeParts(entry), longest)), num(clock(entry.active_s)),
        hasUsage ? [h("td", {style: "width:14%"}, bar([["usage", entry.aiu || 0, "AIU " + amount(entry.aiu)]], dearest, true)), num(amount(entry.aiu))] : null,
        num(entry.turns || "-"), num(entry.tool_calls)));
      if (entry.waited_after_s && entry.waited_after_s >= 60) {
        const wait = info.waits.find((item) => item.after_prompt === entry.n);
        rows.push(h("tr", {class: "gap"}, h("td"), h("td", {colspan: columns - 1},
          "⏸ " + t(wait && wait.open ? "report.gap.open" : "report.gap", {time: clock(entry.waited_after_s), reason: t("insight.wait." + (wait ? wait.reason : "reply"))}))));
      }
    }
    return card(t("report.prompts"), table(head, rows), hasSplit ? legend(PARTS.map((name) => [name, partLabel(name), ""])) : null);
  }

  function stagesCard() {
    if (!(info.stages.length > 1 || (info.stages.length && info.stages[0].stage !== "doing"))) return null;
    const has = (key) => info.stages.some((stage) => stage[key] !== null && stage[key] !== undefined);
    const thinking = has("model_s"), tokens = has("input_tokens");
    const head = [th(t("report.col.stage")), th(t("report.col.prompts"), true), th(t("report.col.time")), th("", true), hasUsage ? [th("AIU"), th("", true)] : null,
      thinking ? th(t("report.col.thinking"), true) : null, th(t("report.col.calls"), true), th(t("report.col.subagents"), true), tokens ? th(t("report.col.tokens_io"), true) : null];
    const rows = info.stages.map((stage) => h("tr", null,
      h("td", null, stage.label), num(stage.prompts),
      h("td", {style: "width:20%"}, bar([["work", stage.share_time, percent(stage.share_time)]], 1, true)),
      num(clock(stage.active_s) + " · " + percent(stage.share_time)),
      hasUsage ? [h("td", {style: "width:20%"}, bar([["usage", stage.share_aiu, percent(stage.share_aiu)]], 1, true)), num(amount(stage.aiu) + " · " + percent(stage.share_aiu))] : null,
      thinking ? num(clock(stage.model_s)) : null,
      num(stage.failed_tool_calls ? t("report.stage.calls_failed", {calls: stage.tool_calls, failed: stage.failed_tool_calls}) : String(stage.tool_calls)),
      num(stage.subagents ? stage.subagents + " · " + clock(stage.subagent_s) : "-"),
      tokens ? num(amount(stage.input_tokens) + " / " + amount(stage.output_tokens)) : null));
    return card(t("report.stages"), table(head, rows));
  }

  // One line over the prompts; a prompt with no number is skipped.
  function contextCard() {
    const points = info.prompts.map((entry, index) => [index, entry.context_tokens]).filter(([, value]) => value !== null);
    if (points.length < 2) return null;
    const NS = "http://www.w3.org/2000/svg";
    const width = 1000, height = 120, pad = 10;
    const top = Math.max(...points.map(([, value]) => value)) || 1;
    const last = Math.max(1, info.prompts.length - 1);
    const spots = points.map(([index, value]) => [pad + (index / last) * (width - 2 * pad), height - pad - (value / top) * (height - 2 * pad)]);
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("preserveAspectRatio", "none");
    const line = document.createElementNS(NS, "polyline");
    line.setAttribute("points", spots.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" "));
    line.setAttribute("class", "line");
    svg.append(line);
    const tip = h("div", {class: "tip", role: "tooltip", hidden: ""});
    const words = (order) => {
      const [index, value] = points[order];
      const before = order ? points[order - 1][1] : null;
      const change = before === null ? "" : t("report.context.change", {delta: (value >= before ? "+" : "-") + amount(Math.abs(value - before))});
      return t("report.context.point", {n: index + 1, at: when(info.prompts[index].at, 5, 16), tokens: amount(value)}) + change;
    };
    const dots = h("div", {class: "dots"}, spots.map(([x, y], order) => {
      const dot = h("i", {style: `left:${(x / width) * 100}%;top:${(y / height) * 100}%`, tabindex: "0", "aria-label": words(order)});
      const show = () => {
        tip.textContent = words(order);
        tip.style.left = `${(x / width) * 100}%`;
        tip.style.top = `${(y / height) * 100}%`;
        tip.classList.toggle("left", x > width * 0.7);
        tip.hidden = false;
      };
      const hide = () => { tip.hidden = true; };
      dot.addEventListener("mouseenter", show);
      dot.addEventListener("focus", show);
      dot.addEventListener("mouseleave", hide);
      dot.addEventListener("blur", hide);
      return dot;
    }));
    return card(t("report.context"), h("div", {class: "chart"}, svg, dots, tip),
      h("div", {class: "sub"}, t("report.context.note", {first: amount(totals.context_tokens_first), largest: amount(totals.context_tokens_max)})));
  }

  function toolsCard() {
    if (!info.tools.length) return null;
    const slowest = Math.max(...info.tools.map((tool) => tool.total_s)) || 1;
    const head = [th(t("report.col.tool")), th(t("report.col.calls"), true), th(t("report.col.total")), th("", true), th(t("report.col.longest"), true),
      th(t("report.col.failed"), true), th(t("report.col.result_tokens"), true)];
    const rows = info.tools.slice(0, 15).map((tool) => h("tr", null,
      h("td", null, tool.name), num(tool.calls),
      h("td", {style: "width:30%"}, bar([["tool", tool.total_s, clock(tool.total_s)]], slowest, true)),
      num(clock(tool.total_s)), num(clock(tool.max_s)), num(tool.failed || "-"), num(amount(tool.result_tokens))));
    return card(t("report.tools"), table(head, rows));
  }

  function reviewsCard() {
    if (!info.reviews.length) return null;
    const head = [th(t("report.col.check")), th(t("report.col.at")), th(t("report.col.verdict")), th(t("report.col.time"), true), th(t("report.col.tokens"), true), th(t("report.col.model"))];
    const rows = info.reviews.map((item) => h("tr", null,
      h("td", null, "round-" + String(item.number || 0).padStart(3, "0")), h("td", {class: "when"}, when(item.started_at, 5, 16)),
      h("td", null, item.verdict ? tag(item.verdict, item.verdict === "PASS" ? "good" : "bad") : tag(t("report.review.none"))),
      num(clock(item.seconds)), num(amount(item.tokens)), h("td", null, item.model || "-")));
    return card(t("report.reviews"), table(head, rows));
  }

  app.replaceChildren(...header().filter(Boolean));  // a part with nothing to show is left out, not drawn as "null"
  if (!info.prompts.length) {
    app.append(h("div", {class: "card empty"}, t("report.empty")), footer(false));
    return;
  }
  for (const node of [findings(), timeCard(), promptsCard(), stagesCard(), contextCard(), toolsCard(), reviewsCard(), footer(true)]) {
    if (node) app.append(node);
  }
})();
