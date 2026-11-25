// The rows of the calls to outside systems (callrecord.py): the list on the Runs tab and the runs of a script on the Scripts tab. One row is one call the gate let through: how it ended
// (a dot), what it did (an icon), the system and the environment, the first line of the command, what let it through, the saved run it belongs to, how long it took and when.
// A row opens to the whole command and the output: on a served page it asks the board once (`/api/callrecord`); a saved copy carries it (`call.detail`).
// The page draws again every few seconds: which rows are open, what was asked and which filter is on are kept here, so a new drawing shows the same.
// Needs common.js (h, t, when, tag). The page gives what it already has: `{task, served, command(text, layout), output(item), evChip(id), redraw()}`.
"use strict";

const CALLROWS = (function () {
  const ICONS = {  // write and exec are the Live tab's edit and run (live.js); read and destroy are this file's own
    write: ["M3 13l1-3 7-7 2 2-7 7zM9.5 4.5l2 2"], exec: ["M3 4l4 4-4 4M8 12h5"], read: ["M1.5 8s2.4-4.5 6.5-4.5S14.5 8 14.5 8s-2.4 4.5-6.5 4.5S1.5 8 1.5 8z", "M8 6.2a1.8 1.8 0 1 0 0 3.6 1.8 1.8 0 0 0 0-3.6z"],
    destroy: ["M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5M6.8 7v3.5M9.2 7v3.5"]};
  const SHIELD = ["M8 1.8l4.8 1.9v3.7c0 3-2 5.5-4.8 6.8-2.8-1.3-4.8-3.8-4.8-6.8V3.7L8 1.8z", "M5.8 8l1.6 1.6 2.9-3"];  // desk.js: the mark of something the person approved
  const NS = "http://www.w3.org/2000/svg";
  const PAGE = 50;
  const FILTERS = ["all", "approved", "write", "exec", "failed", "unknown"];
  const HOWS = ["allow", "plan", "runner", "opened", "approved"];
  const VERBS = ["write", "exec", "destroy", "read"];
  const WHYS = ["board", "cut", "stopped", "noresult", "unmatched"];

  const open = new Set();  // the ids of the rows that are open
  const details = {};  // id + outcome -> the answer of the board (undefined while asked, null when refused)
  let filter = "all";
  let shown = PAGE;

  function icon(paths, size) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 16 16"); svg.setAttribute("width", size); svg.setAttribute("height", size); svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.5"); svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round"); svg.setAttribute("aria-hidden", "true");
    paths.forEach((d) => { const path = document.createElementNS(NS, "path"); path.setAttribute("d", d); svg.append(path); });
    return svg;
  }

  // How long a call took: "0.8 s", "41 s", "2:05", "1:02:10".
  function took(seconds) {
    if (typeof seconds !== "number" || !isFinite(seconds) || seconds < 0) return "";
    if (seconds < 10) return (Math.round(seconds * 10) / 10).toFixed(1) + " s";
    if (seconds < 60) return Math.round(seconds) + " s";
    const whole = Math.round(seconds), two = (value) => String(value).padStart(2, "0");
    return whole < 3600 ? Math.floor(whole / 60) + ":" + two(whole % 60) : Math.floor(whole / 3600) + ":" + two(Math.floor(whole / 60) % 60) + ":" + two(whole % 60);
  }

  const outcomeOf = (call) => (["ok", "failed", "running"].includes(call.outcome) ? call.outcome : "unknown");
  const whyOf = (call) => t("desk.calls.why." + (WHYS.includes(call.why) ? call.why : "unmatched"));
  function outcomeTip(call) {
    const outcome = outcomeOf(call);
    if (outcome === "unknown") return t("desk.calls.none") + ": " + whyOf(call);
    return t("desk.calls.outcome." + outcome) + (typeof call.exit === "number" ? " · " + t("desk.calls.exit", {n: call.exit}) : "");
  }
  // The day is left out for a call of today: the list is newest first, and most of it is of one day.
  function stamp(at) {
    const whole = when(at, 0, 16), today = when(new Date().toISOString(), 0, 10);
    return whole.slice(0, 10) === today ? whole.slice(11, 16) : whole.slice(5, 16);
  }

  function matches(call, name) {
    if (name === "approved") return call.how === "approved";
    if (name === "write") return call.verb === "write" || call.verb === "destroy";
    if (name === "exec") return call.verb === "exec";
    if (name === "failed") return call.outcome === "failed";
    if (name === "unknown") return outcomeOf(call) === "unknown";
    return true;
  }

  function fill(body, call, ctx) {
    const outcome = outcomeOf(call), key = call.id + "|" + outcome;
    const found = call.detail || details[key];
    if (found === undefined && ctx.served) {
      if (!(key in details)) {
        details[key] = undefined;
        SERVE.post("/api/callrecord", {task: ctx.task, id: call.id}).then((data) => { details[key] = data.call || null; }, () => { details[key] = null; }).then(() => { if (body.isConnected && open.has(call.id)) fill(body, call, ctx); });
      }
      body.replaceChildren(ctx.command(call.command, null), h("p", {class: "sub"}, t("desk.calls.loading")));
      return;
    }
    if (found === null && ctx.served) {  // the board did not answer: say so and offer to ask again; "no output was kept" would be untrue
      const again = h("button", {type: "button", class: "act"}, t("desk.calls.retry"));
      again.addEventListener("click", () => { delete details[key]; fill(body, call, ctx); });
      body.replaceChildren(ctx.command(call.command, null), h("p", {class: "cr-none"}, h("span", {class: "bad"}, t("desk.calls.noload")), " ", again));
      return;
    }
    const parts = [ctx.command(call.command, found ? found.layout : null)];
    if (outcome === "running") parts.push(h("p", {class: "sub"}, t("desk.calls.running")));
    else if (!found || !found.has_output) parts.push(h("p", {class: "cr-none"}, h("b", null, t("desk.calls.none")), " ", h("span", {class: "sub"}, "· " + whyOf(call))));
    else if (!found.output) parts.push(h("p", {class: "cr-none"}, h("b", null, t("desk.calls.empty")), typeof call.exit === "number" ? [" ", h("span", {class: "tag cr-exit" + (call.exit === 0 ? " good" : " bad")}, t("desk.calls.exit", {n: call.exit}))] : null));
    else {
      const pane = [].concat(ctx.output({id: "call:" + call.id, output: found.output, output_cut: found.output_cut, output_view: found.output_view}));
      if (typeof call.exit === "number" && pane[0]) pane[0].append(" ", h("span", {class: "tag cr-exit" + (call.exit === 0 ? " good" : " bad")}, t("desk.calls.exit", {n: call.exit})));
      parts.push(...pane);
    }
    body.replaceChildren(...parts.filter(Boolean));
  }

  // One row. `ctx.evChip(id)` draws the chip of a saved run; a click on it must not open the row.
  function row(call, ctx) {
    const outcome = outcomeOf(call), verb = VERBS.includes(call.verb) ? call.verb : "write", how = HOWS.includes(call.how) ? call.how : "unknown";
    const mark = h("span", {class: "cr-verb " + verb + (call.floor === true ? " floor" : ""), title: t("desk.calls.verb." + verb) + (call.floor === true ? "\n" + t("desk.calls.floor") : "")}, icon(ICONS[verb], 14), call.floor === true ? h("b", null, "?") : null);
    const leave = h("span", {class: "tag cr-how" + (how === "approved" ? " you" : ""), title: t("desk.evidence.leave." + how + ".tip")}, how === "approved" ? icon(SHIELD, 12) : null, t("desk.evidence.leave." + how) + (call.code ? " " + call.code : ""));
    const length = outcome === "running" ? "" : took(call.seconds);
    const tail = h("span", {class: "cr-tail"}, leave, (call.evidence || []).map((id) => ctx.evChip(id)), h("span", {class: "cr-dur", title: length ? t("desk.calls.took", {time: length}) : ""}, length || (outcome === "running" ? "…" : "—")));
    const line = h("summary", {class: "cr-line"}, h("i", {class: "cr-dot " + outcome, title: outcomeTip(call), role: "img", "aria-label": outcomeTip(call)}), mark, h("span", {class: "cr-sys", title: call.system}, call.system || "?"),
      call.env ? h("span", {class: "cr-env", title: call.env}, call.env) : null, h("code", {class: "cr-cmd", title: call.command.slice(0, 600)}, call.command.split("\n")[0].slice(0, 400)), tail,
      h("time", {class: "cr-at", datetime: call.at, title: when(call.at, 0, 19)}, stamp(call.at)));
    const body = h("div", {class: "cr-body"});
    const node = h("details", {class: "cr-row cr-" + outcome + (verb === "destroy" ? " cr-destroy" : ""), "data-call": call.id}, line, body);
    if (open.has(call.id)) { node.open = true; fill(body, call, ctx); }
    node.addEventListener("toggle", () => {
      if (node.open) { open.add(call.id); fill(body, call, ctx); } else { open.delete(call.id); body.replaceChildren(); }
    });
    return h("li", null, node);
  }

  // A list of rows, newest first. `calls` is oldest first, as the server gives it.
  function list(calls, ctx) {
    return h("ul", {class: "cr-list"}, calls.slice().reverse().map((call) => row(call, ctx)));
  }

  // The section of the Runs tab: the title, the filters with their counts, the rows of the filter that is on (PAGE at a time), or the line that says there are none.
  function section(calls, ctx) {
    const head = h("h3", {class: "cr-h", title: t("desk.calls.title.tip")}, t("desk.calls.title"), " ", h("span", {class: "tk-n"}, String(calls.length)));
    if (!calls.length) return h("section", {class: "cr-sec"}, head, h("p", {class: "sub cr-zero"}, t("desk.calls.zero")));
    const counts = {};
    FILTERS.forEach((name) => { counts[name] = calls.filter((call) => matches(call, name)).length; });
    if (!counts[filter]) filter = "all";
    const chips = h("div", {class: "cr-filters", role: "group", "aria-label": t("desk.calls.filter")}, FILTERS.filter((name) => name === "all" || counts[name] || name === filter).map((name) => {
      const chip = h("button", {type: "button", class: "chip" + (filter === name ? " on" : ""), "aria-pressed": filter === name ? "true" : "false", title: t("desk.calls.filter." + name + ".tip")}, t("desk.calls.filter." + name), " ", h("span", {class: "tk-n"}, String(counts[name])));
      chip.addEventListener("click", () => { filter = name; shown = PAGE; ctx.redraw(); });
      return chip;
    }));
    const picked = calls.filter((call) => matches(call, filter));
    const rest = Math.max(0, picked.length - shown);
    const more = h("button", {type: "button", class: "cr-older-btn"}, t("desk.calls.older", {n: Math.min(PAGE, rest)}));
    more.addEventListener("click", () => { shown += PAGE; ctx.redraw(); });
    return h("section", {class: "cr-sec"}, head, chips, list(picked.slice(rest), ctx), rest ? h("div", {class: "cr-older"}, more, h("span", null, t("desk.calls.more", {n: rest}))) : null);
  }

  // The mark on a script's row: how its last run ended. Nothing for a script that never ran (`norun` says that).
  function last(runs) {
    if (!runs || !runs.length) return h("span", {class: "cr-norun", title: t("desk.scripts.norun.tip")}, t("desk.scripts.norun"));
    const call = runs[runs.length - 1], outcome = outcomeOf(call);
    return h("span", {class: "cr-last " + outcome, title: t("desk.scripts.last.tip") + "\n" + outcomeTip(call)}, h("i", {class: "cr-dot " + outcome}), t("desk.scripts.last." + outcome));
  }

  return {section, list, last, took};
})();
