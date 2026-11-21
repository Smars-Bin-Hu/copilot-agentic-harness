// The window "The command the agent wants to run" (1.8.24): one dialog for a held call, drawn by the task page (desk.js) and by the super view's queue (super.js). The call is what
// `taskdesk.outbox_view` gives (words, facts, layout, statements, files seen): this file only draws it. The page says what opening it means (`onOpen`: the call counts as seen), what the code chip does
// (`onCode`) and what follows a close (`onClose`).
"use strict";

const CALLVIEW = (function () {
  const SQL_WORDS = /\b(select|from|where|insert|into|update|set|delete|merge|exec|execute|create|alter|drop|truncate|table|values|join|on|group by|order by|having|union|with|begin|commit|rollback|tran|declare|if|else|while|top|as|and|or|not|null|is|in|exists|case|when|then|end|nocount)\b/gi;
  function sqlNodes(text) {
    const out = [];
    let last = 0;
    for (const found of text.matchAll(SQL_WORDS)) {
      if (found.index > last) out.push(text.slice(last, found.index));
      out.push(h("b", {class: "kw"}, found[0]));
      last = found.index + found[0].length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }
  function commandNodes(layout) {
    const rows = [];
    for (const line of layout.lines) {
      if (line.kind === "program") rows.push(h("div", {class: "cmd-line"}, h("span", {class: "cmd-prog"}, line.text)));
      else if (line.kind === "option") rows.push(h("div", {class: "cmd-line in"}, h("span", {class: "cmd-opt"}, line.text), line.value ? [" ", h("span", {class: "cmd-val"}, line.value)] : null));
      else if (line.kind === "flag") rows.push(h("div", {class: "cmd-line in"}, h("span", {class: "cmd-opt"}, line.text)));
      else if (line.kind === "sep") rows.push(h("div", {class: "cmd-sep"}, h("span", null, line.text)));  // the next command of the line (1.7.38)
      else if (line.kind === "block") rows.push(h("div", {class: "cmd-block"}, sqlNodes(line.text)));
      else rows.push(h("div", {class: "cmd-line in"}, h("span", {class: "cmd-val"}, line.text)));
    }
    return h("div", {class: "cmd-fmt"}, rows);
  }
  const known = (key, plain) => (Object.prototype.hasOwnProperty.call(TEXT, key) ? t(key) : plain);  // a word of the harness in the language of the page; a name a tool pack gives stays as it is
  const factSpan = (label, value, hot, title) => (value ? h("span", {class: "tk-fact"}, h("span", {class: "k"}, label), hot ? tag(value, "hot") : h("code", title ? {title} : null, value)) : null);
  const factList = (facts) => Object.entries(facts || {}).map(([name, value]) => factSpan(known("desk.outbox.fact." + name, name), value));
  const manyWrites = (item) => Array.isArray(item.parts) && item.parts.length > 1;  // a held line of several writes: each has its own words, facts and text (1.7.38)
  const ZONE_WORDS = {ask: ["desk.outbox.zone.ask", "desk.outbox.zone.ask.tip"], write: ["desk.outbox.zone.write", "desk.outbox.zone.write.tip"], broken: ["desk.outbox.zone.broken", "desk.outbox.zone.broken.tip"]};  // why a held call waits: word and hover
  const tailPath = (path, max) => (path.length <= max ? path : "\u2026" + path.slice(1 - max));  // a long path keeps its end, where the file name is; the whole path is on hover
  const scriptsOf = (item) => (item.layout ? item.layout.scripts || (item.layout.script ? [item.layout.script] : []) : []);  // every file the line names and the task holds (1.7.38: two `-i` files show both)
  const zoneFact = (zone, note, system, env, why) => (ZONE_WORDS[zone] ? h("span", {class: "tk-fact"}, h("span", {class: "k"}, t("desk.outbox.zone")), system ? [h("b", null, system), env && env !== "none" ? [" ", tag(env, "hot")] : null, " "] : null,
    h("span", {class: "unnamed", title: t(ZONE_WORDS[zone][1], {what: note || "-"}) + (why && zone === "ask" ? "\n" + t("desk.outbox.zone.why", {why}) : "")}, t(ZONE_WORDS[zone][0]), " ", h("span", {class: "why"}, "?"))) : null);  // the statement as it was written, and, when the type says it, what is wrong with it (F3 U2)
  const systemFact = (system, env) => h("span", {class: "tk-fact"}, h("span", {class: "k"}, t("desk.outbox.system")), h("b", null, system), env && env !== "none" ? [" ", tag(env, "hot")] : null);
  function callFacts(item) {
    const verb = known("desk.outbox.verb." + item.verb, item.verb);
    const many = manyWrites(item);
    const reaches = item.reaches && item.reaches.length > 1 ? item.reaches : null;  // a line on more than one system names each of them (1.7.38)
    const holds = item.holds && item.holds.length > 1 ? item.holds : null;  // and why each part is held
    return h("div", {class: "tk-call-facts"},
      factSpan(t("desk.outbox.what"), item.named === false ? h("span", {class: "unnamed", title: t("desk.outbox.unnamed")}, item.verb, " ", h("span", {class: "why"}, "?")) : verb, false, item.named === false ? null : item.verb === "unknown" ? t("desk.outbox.verb.unknown.tip") : item.verb),  // a call of a pack with a faulty file has no kind: the gate could not judge it (1.7.38, M5)
      reaches ? h("span", {class: "tk-fact tk-systems"}, h("span", {class: "k"}, t("desk.outbox.systems")), reaches.map((one, index) => [index ? " " : "", h("b", null, one.system), one.env && one.env !== "none" ? [" ", tag(one.env, "hot")] : null])) : systemFact(item.system, item.env),
      ...(many ? [] : factList(item.facts)),
      many ? null : factSpan(t("desk.outbox.target"), item.target),
      ...(holds ? holds.map((hold) => zoneFact(hold.zone, hold.note, hold.system, hold.env)) : [zoneFact(item.zone, item.zone_note, "", "", item.why)]),  // 1.7.38: why a call of a type with lists waits; a line on more than one system says why for each part (F1 M6)
      ...scriptsOf(item).map((script) => h("span", {class: "tk-fact"}, h("span", {class: "k"}, t("desk.outbox.script")), h("code", {class: "tk-path", title: script.path}, tailPath(script.path, window.innerWidth < 560 ? 24 : 44)), " ", h("span", {class: "sub"}, t(script.lines === 1 ? "desk.outbox.lines.one" : "desk.outbox.lines", {n: script.lines})))));  // the end of the path: two scripts of one folder differ there (F1 M3)
  }
  // The card of a call whose type says what it does in words (1.7.20): the title is that sentence, and the text it writes stands in a block of its own (a file of the task, or the text as written).
  // The raw command is folded: ids, headers and long addresses are not on the face of the card. A line of several writes (1.7.38) says each on a line of its own, with its own facts and text.
  const sayLine = (item) => {
    if (manyWrites(item)) {
      return h("div", {class: "tk-parts"}, h("span", {class: "tk-writes"}, t(item.parts.every((part) => part.say) ? "desk.outbox.writes" : "desk.outbox.statements", {n: item.parts.length})),  // statements: the type gave no title to each, and one may be a read
        h("ol", null, item.parts.map((part) => h("li", null, part.say ? h("div", {class: "tk-call-say"}, part.say) : null, part.system || Object.keys(part.facts || {}).length ? h("div", {class: "tk-call-facts"}, part.system ? systemFact(part.system, part.env) : null, ...factList(part.facts)) : null, bodyBlock(part)))));
    }
    return item.say ? h("div", {class: "tk-call-say"}, item.say) : null;
  };
  function bodyBlock(item) {
    const body = item.body;
    if (!body) return null;
    if (body.missing) return h("div", {class: "tk-call-body missing"}, h("p", {class: "bad"}, t("desk.outbox.body.missing", {path: body.path, dismiss: t("desk.outbox.dismiss")})));
    return h("div", {class: "tk-call-body"},
      h("div", {class: "tk-body-h"}, h("b", null, body.system ? t("desk.outbox.body.on", {label: body.label || t("desk.outbox.body"), where: body.system + (body.env && body.env !== "none" ? " (" + body.env + ")" : "")}) : body.label || t("desk.outbox.body")), " ", h("span", {class: "sub"}, [body.path ? t("desk.outbox.body.file", {path: body.path}) : "", body.lines > 1 ? t("desk.outbox.body.lines", {n: body.lines}) : ""].filter(Boolean).join(" \u00b7 "))),  // "The statement that will run on acmedw-dev (dev)" when the line reaches more than one system (F1 M4)
      h("pre", {class: "tk-body-text", tabindex: "0"}, body.text), body.cut ? h("p", {class: "sub"}, t("desk.outbox.body.cut")) : null);
  }
  const rawFold = (item) => h("details", {class: "tk-raw"}, h("summary", null, t("desk.outbox.raw")), h("pre", {class: "cmd-script one"}, item.command));
  // What a person wants to copy out of a call is the body: the query in the quoted block, or the script the command reads; the command line itself only when there is neither.
  function callBody(item) {
    if (item.body) return item.command;  // the text it writes is on the card; what Copy gives is the command itself
    const files = scriptsOf(item).filter((script) => script.text);
    if (files.length) return files.map((script) => script.text).join("\n");  // two files: both, one after the other
    const lines = item.layout ? item.layout.lines : [];
    const block = lines.find((line) => line.kind === "block") || lines.find((line) => line.quoted && (line.kind === "arg" || line.value));  // a long quoted value, or a short one (`-Q "SELECT 1"`)
    return block ? (block.kind === "option" ? block.value : block.text) : item.command;
  }
  function open(item, options) {
    const {onCode, onOpen, onClose} = options || {};
    if (onOpen) onOpen(item);  // the page takes the call as seen: its files as they are now
    const copy = h("button", {type: "button", class: "act"}, t("desk.outbox.copy"));
    copy.addEventListener("click", () => { navigator.clipboard.writeText(callBody(item)).then(() => { copy.textContent = t("desk.outbox.copied"); }, () => {}); });
    const close = h("button", {type: "button", class: "act"}, t("desk.window.close"));  // View only shows: nothing to cancel (F1 L5)
    const scripts = scriptsOf(item);
    // The code, as a chip: a click copies it, puts it in the card's box and closes the window, so Approve is the next press.
    const codeChip = h("button", {type: "button", class: "ev code-chip", title: t("desk.outbox.code_tip")}, item.code);
    const view = SERVE.dialog([h("h2", null, t("desk.outbox.window")), sayLine(item), callFacts(item), h("p", {class: "sub"}, t("desk.outbox.asked", {at: when(item.created_at, 0, 16)}), " ", codeChip),
      h("div", {class: "win-body"},  // one scrolling body (both ways); the blocks in it scroll sideways only; the buttons stay in view
        manyWrites(item) ? null : bodyBlock(item),
        typeof STMTS !== "undefined" ? STMTS.block(item.stmts) : null,
        item.layout ? h("div", {class: "cmd-scroll flat"}, commandNodes(item.layout)) : null,
        scripts.map((script) => [h("p", null, h("b", null, script.path), " ", h("span", {class: "sub"}, t(script.lines === 1 ? "desk.outbox.script.note.one" : "desk.outbox.script.note", {n: script.lines}))), h("div", {class: "cmd-scroll flat"}, h("pre", {class: "cmd-script"}, sqlNodes(script.text)), script.cut ? h("p", {class: "sub"}, t("desk.cut")) : null)]),
        h("p", {class: "sub"}, t("desk.outbox.as_written")), h("div", {class: "cmd-scroll one"}, h("pre", {class: "cmd-script"}, item.command))),
      h("div", {class: "row win-foot"}, copy, close)]);
    view.box.classList.add("wide");
    close.addEventListener("click", () => { view.close(); if (onClose) onClose(item); });
    codeChip.addEventListener("click", () => { navigator.clipboard.writeText(item.code).then(() => {}, () => {}); view.close(); if (onCode) onCode(item.code); });
  }
  return {open, callBody, commandNodes, sqlNodes, callFacts, sayLine, bodyBlock, rawFold, manyWrites, scriptsOf};
})();
