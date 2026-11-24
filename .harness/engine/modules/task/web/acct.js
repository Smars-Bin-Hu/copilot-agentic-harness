// (1.8.38) The Copilot account of the person signed in to gh, as `/api/copilot-account` gives it (core/copilotacct.py): this month's credits, the seat, the organization's switches.
// Shared by Settings > Copilot (wizard.js) and the account menu. Only words and small nodes here: no page of its own. A helper: an answer that cannot be read shows nothing.
// Needs common.js (h, t, amount, clock).
"use strict";

const ACCT = (function () {
  const HARNESS_NEEDS = ["cli_enabled", "is_mcp_enabled", "chat_enabled"];  // an organization that switches one of these off breaks part of the harness: the dot turns amber
  const SWITCHES = HARNESS_NEEDS.concat(["cloud_sessions_enabled"]);  // shown in the hover; cloud sessions are not used by the harness
  const LOW = 0.1;  // under this share left, the credits are low

  const whole = (value) => amount(Math.round(Number(value) || 0));
  const has = (key) => typeof TEXT !== "undefined" && Object.prototype.hasOwnProperty.call(TEXT, key);

  // "Dec 1" (the Chinese table puts the month first): the reset day is a UTC date, read as one (a local clock would say Nov 30 west of London).
  function day(stamp) {
    const found = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(stamp || ""));
    if (!found) return "";
    const month = Number(found[2]), months = t("acct.months").split(" ");
    return t("acct.day", {mon: months[month - 1] || String(month), d: Number(found[3])});
  }

  // "" normal, "low" under 10% left or over the limit where that is allowed, "out" used up with no more allowed. Unlimited or unread: "".
  function level(credits) {
    if (!credits || credits.unlimited || !(credits.total > 0)) return "";
    if (credits.left <= 0 && !credits.over_ok) return "out";
    return credits.over > 0 || credits.left / credits.total < LOW ? "low" : "";
  }

  const leftShare = (credits) => (credits && !credits.unlimited && credits.total > 0 ? Math.max(0, Math.min(1, credits.left / credits.total)) : null);

  // The one line under the bar: "697 / 1,500 used · 53% left · resets Dec 1"; over the limit: "300 / 300 used · 42 over the limit · resets Dec 1".
  function line(account) {
    const credits = account && account.credits;
    if (!credits) return [];
    const resets = day(account.resets);
    if (credits.unlimited) return [t("acct.unlimited")];
    const parts = [t("acct.used", {used: whole(Math.min(credits.used, credits.total)), total: whole(credits.total)})];  // what is over the limit is said on its own
    if (credits.over > 0) parts.push(h("b", {class: "acct-over"}, t("acct.over", {n: whole(credits.over)})));
    else if (credits.left <= 0) parts.push(h("b", {class: "acct-out"}, t("acct.usedup")));
    else parts.push(t("acct.left.pct", {p: Math.round(leftShare(credits) * 100)}));
    if (resets) parts.push(t("acct.resets", {date: resets}));
    return parts.flatMap((part, at) => (at ? [" · ", part] : [part]));
  }

  // The short form for a tooltip: "802 of 1,500 credits left · resets Dec 1".
  function short(account) {
    const credits = account && account.credits;
    if (!credits) return "";
    if (credits.unlimited) return t("acct.unlimited");
    const resets = day(account.resets);
    return t("acct.short", {left: whole(credits.left), total: whole(credits.total)}) + (resets ? " · " + t("acct.resets", {date: resets}) : "");
  }

  function bar(credits) {
    const share = leftShare(credits);
    if (share === null) return null;
    const node = h("div", {class: "acct-bar" + (level(credits) ? " " + level(credits) : ""), role: "meter", "aria-valuemin": "0", "aria-valuemax": String(Math.round(credits.total)), "aria-valuenow": String(Math.round(Math.min(credits.used, credits.total))), "aria-label": t("acct.title")});
    node.append(h("i", {style: "width:" + (credits.left <= 0 ? 100 : Math.round((1 - share) * 1000) / 10) + "%"}));
    return node;
  }

  const plan = (value) => (has("acct.plan." + value) ? t("acct.plan." + value) : value);
  const sinceDay = (stamp) => { const found = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(stamp || "")); return found ? found[1] + "-" + found[2] + "-" + found[3] : ""; };

  // The rows of the hover of the credits line: plan, seat from, enterprise, seat since, over the limit, when it was read; then Refresh.
  function details(found, refresh) {
    const account = found.account || {}, credits = account.credits || {};
    const row = (label, value) => (value ? h("div", {class: "acct-r"}, h("span", null, label), h("span", null, value)) : null);
    const ago = found.read_at ? Math.max(0, Date.now() / 1000 - found.read_at) : null;
    const again = h("button", {type: "button", class: "acct-again"}, t("acct.refresh"));
    again.addEventListener("click", (event) => { event.stopPropagation(); again.disabled = true; again.textContent = t("acct.reading"); refresh(); });
    return h("div", {class: "acct-tip"},
      row(t("acct.tip.plan"), account.plan ? plan(account.plan) : ""),
      row(t("acct.tip.org"), (account.orgs || []).join(", ")),
      row(t("acct.tip.enterprise"), (account.enterprises || []).join(", ")),
      row(t("acct.tip.since"), sinceDay(account.since)),
      credits.unlimited || !account.credits ? null : row(t("acct.tip.over"), credits.over_ok ? t("acct.tip.over.yes") : t("acct.tip.over.no")),
      h("div", {class: "acct-foot"}, h("span", null, ago === null ? "" : ago < 60 ? t("acct.read.now") : t("acct.read.ago", {t: clock(ago)})), found.reading ? h("span", null, t("acct.reading")) : again));
  }

  // The organization's switches: null when none came; else {kind: ok | hot, off: [keys], node: the hover body}.
  function policy(account) {
    const switches = (account && account.switches) || {};
    const keys = SWITCHES.filter((key) => typeof switches[key] === "boolean");
    if (!keys.length) return null;
    const off = keys.filter((key) => !switches[key]);
    const bad = off.filter((key) => HARNESS_NEEDS.includes(key));
    const rows = keys.map((key) => h("div", {class: "acct-r" + (switches[key] ? "" : " off")}, h("span", null, t("acct.sw." + key)),
      h("span", null, switches[key] ? t("acct.sw.on") : h("b", {class: HARNESS_NEEDS.includes(key) ? "acct-warn" : ""}, t("acct.sw.off")), switches[key] ? null : h("em", null, t("acct.sw." + key + ".effect")))));
    return {kind: bad.length ? "hot" : "ok", off, node: h("div", {class: "acct-tip"}, h("div", {class: "acct-head"}, t("acct.sw.title")), rows)};
  }

  // `/api/copilot-account` for a page that has no wizard api (the account menu). Never rejects: an error is `{state: "none"}`.
  function get(fresh) {
    if (typeof SERVE === "undefined") return Promise.resolve({state: "none"});
    return SERVE.call("/api/copilot-account", fresh ? {fresh: true} : {}, 8).then((found) => found || {state: "none"}, () => ({state: "none"}));
  }

  return {day, level, leftShare, line, short, bar, details, policy, get};
})();
