// The statements of a held call on its card (1.7.38, C13 F3 AP): numbered, each with the system it is on and how its type judges it. `desk.outbox[].stmts` (modules/task/stmtview.py) says what each is:
// `read` (on the pass list: it passes with no approval), `write` (it passes once the connection is open for the task) or `ask` (on no list: it waits for the person, whatever is open), with the reason the type gives.
// The ones that wait for the person are the ones the eye is drawn to; the reads are folded into one line that opens. A script of hundreds is drawn in pieces: nothing is made until it is looked at.
// Colours come from highlight.js (SQL: keywords, strings, comments); the text is put in with textContent, so nothing in a statement can become markup.
"use strict";

const tailName = (name) => (name.length <= 24 ? name : "\u2026" + name.slice(1 - 24));

const STMTS = (function () {
  const PIECE = 40;  // the rows made at a time; "Show more" makes the next piece

  const sql = (text) => (typeof Highlight !== "undefined" ? Highlight.nodes(text, Highlight.language("sql")) : [text]);
  const systemTag = (row) => h("span", {class: "stm-on", title: row.system}, row.system + (row.env && row.env !== "none" ? " · " + row.env.toUpperCase() : ""));

  function row(item, many) {
    const why = item.zone === "ask" ? item.why || "" : "";
    const tip = t("desk.stmt.zone." + item.zone + ".tip") + (why ? "\n" + t("desk.outbox.zone.why", {why}) : "");
    return h("li", {class: "stm-row zone-" + item.zone, value: item.n},
      h("span", {class: "stm-n"}, String(item.n)),
      h("span", {class: "stm-mark", title: tip}, t("desk.stmt.zone." + item.zone)),
      many ? systemTag(item) : null,
      h("code", {class: "stm-code", title: item.cut ? t("desk.stmt.cut") : null}, ...sql(item.text), item.cut ? "…" : ""),
      item.file ? h("span", {class: "stm-file sub", title: item.file}, tailName(item.file.split(/[\\/]/).pop())) : null,  // a long name keeps its end, where two files of one folder differ (1.7.38, C13 FR 15)
      why ? h("div", {class: "stm-why"}, why) : null);
  }

  // `rows` go into `list` PIECE at a time: the first piece now, a button for the next.
  function fill(list, rows, many) {
    let shown = 0;
    const more = h("button", {type: "button", class: "act stm-more"});
    const next = () => {
      const part = rows.slice(shown, shown + PIECE);
      list.append(...part.map((one) => row(one, many)));
      shown += part.length;
      more.hidden = shown >= rows.length;
      more.textContent = t("desk.stmt.more", {n: rows.length - shown});
    };
    more.addEventListener("click", next);
    next();
    return more;
  }

  // The block of one card. `info` is `item.stmts`. Returns a node, or null when there is nothing to list.
  function block(info) {
    if (!info || !info.total || info.total < 2) return null;
    const many = (info.systems || []).length > 1;
    const counts = info.counts || {};
    const heads = [counts.read ? t("desk.stmt.count.read", {n: counts.read}) : null, counts.write ? t("desk.stmt.count.write", {n: counts.write}) : null].filter(Boolean);
    const asks = counts.ask ? h("b", {class: "stm-ask"}, t("desk.stmt.count.ask", {n: counts.ask})) : null;
    const head = h("div", {class: "stm-h"}, h("b", null, t("desk.stmt.title", {n: info.total})), " ", h("span", {class: "sub"}, heads.join(" · ") + (heads.length && asks ? " · " : "")), asks);
    const held = (info.items || []).filter((one) => one.zone !== "read");
    const reads = (info.items || []).filter((one) => one.zone === "read");
    const list = h("ol", {class: "stm-list"});
    const parts = [head];
    if (held.length) { const more = fill(list, held, many); parts.push(list, more); }
    if (reads.length) {
      const inner = h("ol", {class: "stm-list reads"});
      let made = null;
      const fold = h("details", {class: "stm-reads"}, h("summary", null, t("desk.stmt.reads", {n: counts.read || reads.length})), inner);
      fold.addEventListener("toggle", () => { if (fold.open && !made) { made = fill(inner, reads, many); fold.append(made); } });  // made when it is opened: a script with hundreds of reads costs nothing until then
      parts.push(fold);
    }
    if (info.more) parts.push(h("p", {class: "sub stm-left"}, t("desk.stmt.left", {n: info.more})));
    return h("div", {class: "stm"}, ...parts);
  }

  return {block};
})();
