// A box over the cards when two held calls or more of a task wait at once (1.7.38, C13 F3 AP): one row for each call (its system, what it does, a short summary), a tick to leave one out,
// ONE code for the ticked ones, and "Do not approve any" with the reason. The code is made by the board from exactly the calls ticked and shown here only (`/api/batch`): a call that changes, one that is left out
// or added gives another code. A call that names a script cannot be ticked before View was pressed on it, and the board checks that again. Each call is approved alone: its own wait returns approved.
// The calls the agent went on without are not in it (they have cards of their own), and nothing refused ever had a card.
"use strict";

const BATCH = (function () {
  const states = new Map();  // task -> what the person did in this box; the page is drawn again every few seconds, the box keeps it
  const flat = (text) => String(text || "").replace(/\s+/g, " ").trim();
  const cut = (text, size) => (text.length > size ? text.slice(0, size - 1).trimEnd() + "…" : text);

  function stateOf(task) {
    if (!states.has(task)) states.set(task, {known: new Set(), checked: new Set(), autoed: new Set(), code: "", shown: {key: "", code: ""}, asking: null, line: "", said: ""});
    return states.get(task);
  }

  // ctx: {task, items, can, viewed(code) -> the files as View had them or undefined, needsView(item), view(item), unview(code), approved(calls, result), done(), reasons, lineReasons}
  function box(ctx) {
    const items = ctx.items || [];
    if (items.length < 2) { states.delete(ctx.task); return null; }
    const st = stateOf(ctx.task);
    const codes = new Set(items.map((item) => item.code));
    for (const code of [...st.known]) if (!codes.has(code)) { st.known.delete(code); st.checked.delete(code); st.autoed.delete(code); }
    for (const item of items) st.known.add(item.code);
    // The tick: a call is ticked for the person only when it is an ordinary write of a write list (`item.batch` is `plain`) and View was pressed on it, once; the person may untick it, and it stays unticked. Any other call
    // is ticked by the person, after View. A call that comes later is not ticked: the list under the person's hand does not change (1.7.38, C13 FR 1).
    for (const item of items) if (item.batch === "plain" && ctx.viewed(item.code) && !st.autoed.has(item.code)) { st.autoed.add(item.code); st.checked.add(item.code); }
    for (const code of [...st.checked]) if (ctx.needsView(items.find((item) => item.code === code) || {}) && !ctx.viewed(code)) st.checked.delete(code);  // a View that was lost (the file changed) takes the tick away

    const said = h("div", {class: "bad"}, st.said || null);
    const code = h("input", {class: "code", autocomplete: "off", spellcheck: "false", placeholder: t("desk.batch.code"), "aria-label": t("desk.batch.code"), value: st.code, "data-keep": "batch.code"});
    const chip = h("button", {type: "button", class: "ev code-chip bt-chip", title: t("desk.batch.chip.tip"), hidden: ""});
    const yes = h("button", {type: "button", class: "act hot big", disabled: "disabled"}, t("desk.batch.approve", {n: st.checked.size}));
    const no = h("button", {type: "button", class: "act", disabled: ctx.can ? null : "disabled", "aria-expanded": st.asking ? "true" : "false"}, t("desk.batch.dismiss"));
    const count = h("span", {class: "sub bt-count"});
    const reasonBox = h("div", {class: "tk-reasons", role: "group", "aria-label": t("desk.outbox.reason.title"), hidden: st.asking ? null : ""});

    const arm = () => {
      const n = st.checked.size;
      yes.textContent = t("desk.batch.approve", {n});
      yes.disabled = !(ctx.can && n && code.value.trim() && st.shown.code);
      yes.title = !ctx.can ? "" : !n ? t("desk.batch.none") : !st.shown.code ? t("desk.batch.wait") : !code.value.trim() ? t("desk.batch.type") : "";
      count.textContent = t("desk.batch.count", {n, total: items.length});
      code.classList.toggle("pulse", ctx.can && n > 0 && !code.value.trim());
    };
    let timer = 0;
    const preview = () => {  // the code of the list as ticked now: asked of the board, shown here
      const list = items.map((item) => item.code).filter((one) => st.checked.has(one));
      const key = list.join(",");
      clearTimeout(timer);
      if (!list.length) { st.shown = {key: "", code: ""}; chip.hidden = true; arm(); return; }
      if (st.shown.key === key && st.shown.code) { chip.textContent = st.shown.code; chip.hidden = false; arm(); return; }
      st.shown = {key, code: ""}; chip.hidden = true; arm();
      timer = setTimeout(() => {
        SERVE.post("/api/batch", {step: "preview", task: ctx.task, codes: list}).then((data) => {
          if (st.shown.key !== key) return;
          st.shown.code = data.result.code; chip.textContent = data.result.code; chip.hidden = false; arm();
        }, (error) => { if (st.shown.key === key) { st.said = error.message; said.replaceChildren(...SERVE.reasons(error.message)); } });
      }, 120);
    };

    const rows = items.map((item) => {
      const needs = ctx.needsView(item), viewed = Boolean(ctx.viewed(item.code));
      const blocked = needs && !viewed;
      const tick = h("input", {type: "checkbox", class: "bt-tick", "aria-label": t("desk.batch.tick"), disabled: ctx.can && !blocked ? null : "disabled"});
      tick.checked = st.checked.has(item.code);
      tick.addEventListener("change", () => { if (tick.checked) st.checked.add(item.code); else st.checked.delete(item.code); st.said = ""; said.replaceChildren(); preview(); });
      const view = h("button", {type: "button", class: "act bt-view" + (blocked ? " pulse" : "")}, t("desk.outbox.view"));
      view.addEventListener("click", () => ctx.view(item));
      const statement = item.body && item.body.text ? flat(item.body.text) : "";  // the statement says more than `sqlcmd -S server ...`
      const summary = item.says && item.says.length ? item.says.join(" \u00b7 ") : cut(statement || flat(item.command), 160);
      return h("li", {class: "bt-row" + (blocked ? " blocked" : ""), "data-code": item.code},
        tick,
        h("span", {class: "bt-sys"}, h("b", null, item.system), item.env && item.env !== "none" ? [" ", tag(item.env, "hot")] : null),
        h("span", {class: "bt-what tag"}, (() => { const key = "desk.outbox.verb." + item.verb; const word = t(key); return word === key ? item.verb : word; })()),
        h("span", {class: "bt-sum", title: flat(item.command).slice(0, 400)}, summary),
        item.stmts ? h("span", {class: "bt-stm sub", title: t("desk.stmt.count.ask", {n: item.stmts.counts.ask || 0})}, t("desk.stmt.title", {n: item.stmts.total})) : null,
        blocked ? h("span", {class: "bt-why", title: t("desk.batch.view_first.tip")}, t("desk.batch.view_first")) : null,
        view);
    });

    code.addEventListener("input", () => { st.code = code.value; arm(); });
    chip.addEventListener("click", () => { navigator.clipboard.writeText(st.shown.code).then(() => {}, () => {}); code.value = st.shown.code; st.code = code.value; arm(); yes.focus(); });
    const send = () => {
      if (yes.disabled) return;
      const list = items.map((item) => item.code).filter((one) => st.checked.has(one));
      const seen = {};
      for (const one of list) if (ctx.viewed(one)) seen[one] = {files: ctx.viewed(one)};
      yes.disabled = true; yes.textContent = t("board.serve.working");
      SERVE.post("/api/batch", {step: "act", task: ctx.task, codes: list, code: code.value.trim(), seen}).then((data) => {
        st.checked.clear(); st.code = ""; st.said = ""; st.shown = {key: "", code: ""};
        ctx.approved(list, data.result);
        SERVE.done();
      }, (error) => {
        for (const one of (error.data && error.data.changed) || []) ctx.unview(one);  // a file changed since View, or was never viewed: View pulses again
        st.said = error.message; said.replaceChildren(...SERVE.reasons(error.message)); arm(); if ((error.data && error.data.changed || []).length) ctx.redraw();
      });
    };
    yes.addEventListener("click", send);
    code.addEventListener("keydown", (event) => { if (event.key === "Enter" && !yes.disabled) send(); });

    const dismissAll = (reason, note) => {  // each call is dismissed on its own, with the same reason: the agent of each is told as for one
      reasonBox.querySelectorAll("button").forEach((one) => { one.disabled = true; });
      no.disabled = true;
      let chain = Promise.resolve();
      for (const item of items) chain = chain.then(() => SERVE.post("/api/act", {action: "dismiss action", task: ctx.task, step: "act", code: item.code, reason, note: note || ""}));
      chain.then(() => { st.asking = null; st.line = ""; st.checked.clear(); SERVE.done(); }, (error) => { st.said = error.message; said.replaceChildren(...SERVE.reasons(error.message)); no.disabled = false; reasonBox.querySelectorAll("button").forEach((one) => { one.disabled = false; }); SERVE.done(); });
    };
    const paintReasons = () => {
      reasonBox.hidden = !st.asking;
      no.setAttribute("aria-expanded", st.asking ? "true" : "false");
      if (!st.asking || reasonBox.firstChild) return;
      const line = h("input", {class: "tk-reason-line", type: "text", maxlength: 500, autocomplete: "off", placeholder: t("desk.outbox.reason.line.ph"), "aria-label": t("desk.outbox.reason.line.ph"), value: st.line, "data-keep": "batch.reason"});
      line.addEventListener("input", () => { st.line = line.value; });
      const go = h("button", {type: "button", class: "act hot"}, t("desk.outbox.reason.go"));
      const lineRow = h("span", {class: "tk-reason-line-row"}, line, go);
      lineRow.hidden = !ctx.lineReasons.includes(st.asking.kind);
      const chips = ctx.reasons.map((kind) => {
        const chipOne = h("button", {type: "button", class: "act tk-reason" + (st.asking.kind === kind ? " on" : ""), "data-reason": kind}, t("desk.outbox.reason." + kind));
        chipOne.addEventListener("click", () => {
          if (!ctx.lineReasons.includes(kind)) return dismissAll(kind, "");
          st.asking = {kind}; chips.forEach((one) => one.classList.toggle("on", one === chipOne)); lineRow.hidden = false; line.focus();
        });
        return chipOne;
      });
      const none = h("button", {type: "button", class: "act tk-reason", "data-reason": "none"}, t("desk.outbox.reason.none"));
      none.addEventListener("click", () => dismissAll("", ""));
      go.addEventListener("click", () => { if (ctx.lineReasons.includes(st.asking.kind)) dismissAll(st.asking.kind, line.value); });
      line.addEventListener("keydown", (event) => { if (event.key === "Enter" && ctx.lineReasons.includes(st.asking.kind)) dismissAll(st.asking.kind, line.value); });
      reasonBox.replaceChildren(h("span", {class: "sub"}, t("desk.batch.reason.title")), ...chips, none, lineRow);
    };
    no.addEventListener("click", () => { st.asking = st.asking ? null : {kind: ""}; reasonBox.replaceChildren(); paintReasons(); });
    paintReasons();
    preview();
    arm();
    return h("section", {class: "tk-need tk-call strong tk-batch", "data-action": "approve-batch"},
      h("div", {class: "tk-need-h"}, tag(t("desk.batch.title", {n: items.length}), "hot"), count),
      h("p", {class: "hint"}, t("desk.batch.hint")),
      h("ul", {class: "bt-list"}, ...rows),
      h("div", {class: "tk-need-go tk-call-go"}, h("span", {class: "tk-code-in"}, h("span", {class: "sub"}, t("desk.batch.code.label")), chip, code, yes), no, h("span", {class: "sub"}, t("desk.batch.same_as"))),
      reasonBox, said);
  }

  return {box};
})();
