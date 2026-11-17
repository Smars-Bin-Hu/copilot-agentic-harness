// Autorun on the board (1.8, step 9): the Start dialog (models, spend limit, the typed code) and the run card of the task page (done, parked, left, spend, time, relays, Stop, the steps of the run ledger).
// Only in a served page. The server computes everything (`autorun_board.py`); this file draws it with DOM nodes and textContent, and talks to `/api/autorun`, `/api/autorun/on` and `/api/autorun/stop`.
"use strict";

const AUTORUN = (function () {
  const node = h("section", {class: "ar-card", hidden: ""});
  const watching = {task: "", run: false, on: null, onTrace: null, timer: false, shown: "", card: null, steps: false, asking: false};

  const info = (text) => h("span", {class: "ar-info", title: text, tabindex: "0", role: "img", "aria-label": text}, "i");
  const secondsOf = (from, to) => { const a = Date.parse(from), b = Date.parse(to); return isNaN(a) || isNaN(b) ? null : Math.max(0, (b - a) / 1000); };

  // --- the Start dialog -------------------------------------------------------------------------------------------

  function option(value, label, title, selected) {
    return h("option", {value, title: title || value, selected: selected ? "" : null}, label);
  }

  function form(row, data) {
    const problems = data.problems || [];
    if (problems.length) {
      const close = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
      const view = SERVE.dialog([h("h2", null, t("desk.autorun.start.title", {name: row.name})), h("p", null, t("desk.autorun.start.problems")), h("div", {class: "bad"}, SERVE.reasons(problems.join("\n"))), h("div", {class: "row"}, close)]);
      close.addEventListener("click", view.close);
      return;
    }
    const noClaude = !(data.manager_models || []).length;
    const manager = h("select", {"aria-label": t("desk.autorun.field.manager")}, (data.manager_models || []).map((model) => option(model.id, model.name, model.id, model.id === data.manager_default)));
    const worker = h("select", {"aria-label": t("desk.autorun.field.worker")}, (data.models || []).map((model) => option(model.id, model.name, model.id, model.id === data.worker_default)));
    const percent = h("input", {type: "number", min: 0, max: 95, step: 1, value: data.compact_percent, "aria-label": t("desk.autorun.field.percent")});
    const minutes = h("input", {type: "number", min: 1, step: 1, value: data.minutes, "aria-label": t("desk.autorun.field.minutes")});
    const field = (key, input) => h("label", {title: t("desk.autorun.field." + key + ".tip")}, h("span", null, t("desk.autorun.field." + key)), input);
    const choices = (data.budget && data.budget.choices) || [null];
    const radios = choices.map((add, index) => {
      const recommended = add !== null && add === data.budget.recommended;
      const input = h("input", {type: "radio", name: "ar-budget", value: add === null ? "none" : String(add), checked: recommended ? "" : null});
      return h("label", {class: "ar-opt", title: add === null ? t("desk.autorun.budget.none.tip") : t("desk.autorun.budget.tip")}, input,
        h("span", null, add === null ? t("desk.autorun.budget.none") : t("desk.autorun.budget.add", {n: amount(add)})), recommended ? tag(t("desk.autorun.budget.rec"), "good") : null,
        add === null ? tag(t("desk.autorun.budget.none.mark"), "warn") : null);
    });
    const code = h("input", {class: "code", autocomplete: "off", spellcheck: "false", placeholder: t("board.serve.code")});
    const yes = h("button", {class: "act hot", type: "button", disabled: noClaude ? "" : null}, t("desk.autorun.start.go"));
    const no = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
    const said = h("div", {class: "bad"});
    const steps = data.steps || [];
    const list = h("ul", {class: "ar-list", "data-keep": "ar-list"}, steps.map((step) => h("li", null, h("span", {class: "n"}, step.n), h("span", {class: "t", title: step.text}, step.text), step.model ? tag(step.model, "model") : null)));
    const view = SERVE.dialog([
      h("h2", null, t("desk.autorun.start.title", {name: row.name})),
      h("p", {class: "sub"}, t("desk.autorun.start.steps", {open: steps.length, total: data.total}), (data.screen || []).length ? info(t("desk.autorun.start.screen") + "\n" + data.screen.join("\n")) : null),
      list, noClaude ? h("p", {class: "bad"}, t("desk.autorun.start.noclaude")) : null,
      h("div", {class: "ar-grid"}, field("manager", manager), field("worker", worker), field("percent", percent), field("minutes", minutes)),
      h("fieldset", {class: "ar-budget"}, h("legend", {title: t("desk.autorun.budget.tip")}, t("desk.autorun.budget")), radios),
      data.blocked ? h("p", {class: "bad"}, data.blocked) : null,
      h("p", null, data.ask || ""), code, h("div", {class: "row"}, yes, no), said]);
    view.box.classList.add("ar-dlg");
    no.addEventListener("click", view.close);
    const number = (input) => (input.value.trim() === "" ? null : Number(input.value));
    const send = () => {
      if (yes.disabled) return;
      const chosen = (view.box.querySelector("input[name=ar-budget]:checked") || {}).value;
      yes.disabled = true;
      yes.textContent = t("board.serve.working");
      SERVE.post("/api/autorun/on", {
        task: row.name, step: "act", code: code.value.trim(), manager_model: manager.value, worker: {default: worker.value},
        compact_percent: number(percent), minutes: number(minutes), budget: chosen === "none" || chosen === undefined ? null : {add_credits: Number(chosen)},
      }).then(() => { view.close(); refresh(); SERVE.done(); }, (error) => { said.replaceChildren(...SERVE.reasons(error.message)); yes.disabled = noClaude; yes.textContent = t("desk.autorun.start.go"); });
    };
    yes.addEventListener("click", send);
    code.addEventListener("keydown", (event) => { if (isEnter(event)) send(); });
    code.focus();
  }

  // The Start button of the task page and of the board: the form is made from what the server says now.
  function start(row) {
    return SERVE.post("/api/autorun/on", {task: row.name, step: "preview"}).then((data) => form(row, data), (error) => SERVE.failed(error));
  }

  // --- the run card -----------------------------------------------------------------------------------------------

  const credits = (value) => amount(value);

  function stopButton(card) {
    const button = h("button", {class: "act", type: "button", title: t("desk.autorun.stop.tip"), "data-label": t("desk.autorun.stop")}, t("desk.autorun.stop"));
    button.addEventListener("click", () => {
      button.disabled = true;
      button.textContent = t("board.serve.working");
      SERVE.post("/api/autorun/stop", {task: card.task}).then(() => { refresh(); SERVE.done(); }, (error) => { button.disabled = false; button.textContent = button.dataset.label; SERVE.failed(error); });
    });
    return button;
  }

  function spendNode(card) {
    if (card.spent === null || card.spent === undefined) return h("span", {title: card.cost_readable === false ? t("desk.autorun.spend.unreadable") : t("desk.autorun.spend.tip")}, t("desk.autorun.spend.unknown"));
    if (card.budget_add === null || card.budget_add === undefined) return h("span", {class: "ar-spend", title: t("desk.autorun.spend.tip")}, t("desk.autorun.spend.nolimit", {spent: credits(card.spent)}));
    const share = card.budget_add ? Math.min(1, card.spent / card.budget_add) : 1;
    return h("span", {class: "ar-spend", title: t("desk.autorun.spend.tip")}, t("desk.autorun.spend", {spent: credits(card.spent), limit: credits(card.budget_add)}),
      h("span", {class: "ar-thin" + (share >= 0.8 ? " hot" : "")}, h("i", {style: "width:" + (share * 100).toFixed(1) + "%"})));
  }

  function resultTag(result) {
    return tag(t("desk.autorun.result." + result), result === "done" ? "good" : result === "failed" ? "bad" : result === "parked" ? "hot" : "good run");
  }

  function rowNode(item, asOf) {
    const seconds = secondsOf(item.start, item.end || asOf);
    const tr = h("tr", {tabindex: "0", role: "button", title: t("desk.autorun.row.tip"), "data-call": item.call},
      h("td", {class: "n"}, item.step === null || item.step === undefined ? t("desk.autorun.row.nostep") : item.step),
      h("td", {class: "t", title: item.text}, item.text), h("td", {class: "m opt", title: item.model}, item.model), h("td", null, resultTag(item.result)),
      h("td", {class: "num opt", title: t("desk.autorun.held.tip")}, item.held || ""), h("td", {class: "num opt", title: t("desk.autorun.denied.tip")}, item.denied || ""),
      h("td", {class: "num"}, seconds === null ? "-" : clock(seconds)), h("td", {class: "num opt"}, item.credits === null || item.credits === undefined ? "" : credits(item.credits)));
    const open = () => { if (watching.onTrace) watching.onTrace(item); };
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
    return tr;
  }

  function stepsNode(card) {
    if (!card.rows.length) return null;
    const head = h("tr", null, h("th", null, t("desk.autorun.col.step")), h("th", null, ""), h("th", {class: "opt"}, t("desk.autorun.col.model")), h("th", null, t("desk.autorun.col.result")), h("th", {class: "opt", title: t("desk.autorun.held.tip")}, t("desk.autorun.col.held")),
      h("th", {class: "opt", title: t("desk.autorun.denied.tip")}, t("desk.autorun.col.denied")), h("th", null, t("desk.autorun.col.time")), h("th", {class: "opt"}, t("desk.autorun.col.credits")));
    const box = h("details", {class: "ar-steps", open: watching.steps ? "" : null}, h("summary", {title: t("desk.autorun.steps.tip")}, t("desk.autorun.steps", {n: card.rows.length + card.rows_cut})),
      h("div", {class: "ar-rows", "data-keep": "ar-rows"}, h("table", null, h("thead", null, head), h("tbody", null, card.rows.slice().reverse().map((item) => rowNode(item, card.as_of))))),
      card.rows_cut ? h("p", {class: "sub ar-cut"}, t("desk.autorun.cut", {n: card.rows_cut})) : null);
    box.addEventListener("toggle", () => { watching.steps = box.open; });
    return box;
  }

  function cardNodes(card) {
    const on = card.autorun === "on";
    const total = Math.max(1, card.total);
    const out = [h("div", {class: "ar-head"}, on ? tag(t("desk.autorun.card.on"), "good run") : tag(t("desk.autorun.card.off")), h("span", {class: "ar-sp"}), on ? stopButton(card) : null)];
    out.push(h("div", {class: "ar-counts"}, tag(t("desk.autorun.n.done", {n: card.done}), "good"), card.parked ? tag(t("desk.autorun.n.parked", {n: card.parked}), "hot") : null, tag(t("desk.autorun.n.left", {n: card.left})),
      h("span", {class: "ar-bar", title: t("desk.autorun.n.done.tip") + ": " + card.done + " / " + t("desk.autorun.n.parked.tip") + ": " + card.parked + " / " + t("desk.autorun.n.left.tip") + ": " + card.left},
        h("i", {class: "d", style: "width:" + (card.done / total * 100).toFixed(2) + "%"}), h("i", {class: "p", style: "width:" + (card.parked / total * 100).toFixed(2) + "%"}))));
    if (card.current) out.push(h("p", {class: "ar-now sub", title: card.current.text + (card.current.model ? " (" + card.current.model + ")" : "")}, t("desk.autorun.current", {n: card.current.n, text: card.current.text})));
    const facts = [spendNode(card)];
    if (on && card.left_s !== null && card.left_s !== undefined) facts.push(h("span", null, t("desk.autorun.left", {time: clock(card.left_s)})));
    facts.push(h("span", {title: t("desk.autorun.relay.tip") + "\n" + t("desk.autorun.pushed.tip", {n: card.pushed, max: card.max_steps === null || card.max_steps === undefined ? "-" : card.max_steps})}, t("desk.autorun.relay", {n: card.relay})),
      h("span", {title: t("desk.autorun.pits.tip")}, t("desk.autorun.pits", {n: card.pits})));
    out.push(h("div", {class: "ar-facts"}, facts));
    for (const code of card.warnings) {
      const start = card.start || {};
      const key = "desk.autorun.warn." + code;
      out.push(h("p", {class: "ar-warn"}, tag("⚠", "warn"), " ", Object.prototype.hasOwnProperty.call(TEXT, key) ? t(key, {seen: start.model_seen || "-", wanted: start.model_wanted || "-"}) : code));
    }
    for (const note of card.notes || []) out.push(h("p", {class: "ar-warn"}, plainWords(note)));
    if (card.questions_total) out.push(h("p", {class: "ar-q sub"}, t("desk.autorun.questions", {n: card.questions_open}), " · ", h("a", {href: "#files", title: card.questions_file, class: "ar-qlink"}, t("desk.autorun.questions.file"))));
    if (!on && card.stopped) out.push(h("p", {class: "ar-why"}, h("b", null, t("desk.autorun.why", {why: plainWords(card.stopped.text)})), card.stopped.detail ? h("span", {class: "sub"}, " · " + card.stopped.detail) : null));
    out.push(stepsNode(card));
    return out;
  }

  function paint(card) {
    watching.card = card;
    const sig = JSON.stringify(Object.assign({}, card, {as_of: "", left_s: card.left_s === null ? null : Math.round(card.left_s / 10)}));
    node.hidden = !card.show;
    if (sig === watching.shown) return;
    watching.shown = sig;
    node.className = "ar-card" + (card.autorun === "on" ? " on" : "");
    const keep = new Map([...node.querySelectorAll("[data-keep]")].map((item) => [item.dataset.keep, item.scrollTop]));
    node.replaceChildren(...cardNodes(card).filter(Boolean));
    for (const item of node.querySelectorAll("[data-keep]")) if (keep.has(item.dataset.keep)) item.scrollTop = keep.get(item.dataset.keep);
  }

  function refresh() {
    if (!watching.task || !watching.run) return Promise.resolve();
    const asked = watching.task;
    return SERVE.read("/api/autorun?task=" + encodeURIComponent(asked)).then((data) => { if (asked === watching.task && watching.run && data.card) paint(data.card); }, (error) => { if (error && error.offline) throw error; });
  }

  // desk.js says, at every drawing, which task is open and whether it has a run to show. `onTrace(row)`: what a click on a step of the ledger does.
  function watch(options) {
    const changed = options.task !== watching.task || options.run !== watching.run || options.on !== watching.on;
    Object.assign(watching, {task: options.task, run: options.run, on: options.on, onTrace: options.onTrace});
    if (!options.run) { node.hidden = true; watching.shown = ""; return; }
    if (!watching.timer) {
      watching.timer = true;
      pollEvery(3, () => (watching.run && !SERVE.busy() ? refresh() : null));
    }
    if (changed) refresh();
  }

  return {node, start, watch, refresh};
})();
