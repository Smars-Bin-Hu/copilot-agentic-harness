// Reopen a closed task, said before the person presses (1.8.21): one card for the task page and the list of the board.
// The engine says what a reopen will be (`taskreopen.plan_of`: same round, a new round that moves the old one aside, or refused); the card writes it out, then two ways go on:
// "Reopen only" (`/api/act` reopen: the task is open, no chat, no credits) and "Reopen and hand to the agent" (`/api/super/send` with the message: a new chat that opens the task first).
// Also the small icon the list draws on a closed row, with its hover. Needs common.js and serve.js; used by desk.js and board.js, on a served page only.
"use strict";

const REOPEN = (function () {
  const SVG = "http://www.w3.org/2000/svg";
  const ICONS = {again: ["M13 8a5 5 0 1 1-1.7-3.8", "M13.2 2.4v2.9h-2.9"], forward: ["M3 8h9", "M9 4.8L12.2 8 9 11.2"], stop: ["M8 2.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11z", "M4.2 11.8l7.6-7.6"]};
  function icon(name, size) {
    const node = document.createElementNS(SVG, "svg");
    for (const [key, value] of Object.entries({viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", "stroke-width": "1.5", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true"})) node.setAttribute(key, value);
    if (size) { node.setAttribute("width", size); node.setAttribute("height", size); }
    for (const d of ICONS[name]) { const part = document.createElementNS(SVG, "path"); part.setAttribute("d", d); node.append(part); }
    return node;
  }

  // The three cases as the card names them: new (amber), same (green), no (red: refused).
  const kindOf = (mode) => (mode === "new" ? "new" : mode === "same" ? "same" : "no");
  const modeIcon = {new: "again", same: "forward", no: "stop"};
  const MODE = {new: "desk.reopen.mode.new", same: "desk.reopen.mode.same", refused: "desk.reopen.mode.no"};  // the words of each case, named here whole (a test finds a message that nothing uses)
  const TIP = {new: "desk.reopen.tip.new", same: "desk.reopen.tip.same", partial: "desk.reopen.tip.partial", checks: "desk.reopen.tip.checks"};
  const code = (text) => h("code", null, text);

  function whoLine(plan) {
    const at = when(plan.closed_at, 5, 16);
    if (plan.mode === "new") return t(plan.branch ? "desk.reopen.who.new.branch" : "desk.reopen.who.new", {at, round: plan.round, branch: plan.branch});
    return t(plan.mode === "same" ? "desk.reopen.who.same" : "desk.reopen.who", {at});
  }

  // The numbered list of what happens. A new round: what moves aside (only what is there), then the two decisions of the person; the same round: nothing moves.
  function whatList(plan) {
    const rows = [];
    if (plan.mode === "new") {
      const parts = [];
      (plan.moves || []).forEach((move, index) => {
        if (index) parts.push(", ");
        parts.push(move.from ? [code(move.from), " → ", code(move.to)] : [t("desk.reopen.changes") + " → ", code(move.to)]);
      });
      rows.push([t("desk.reopen.kept", {round: plan.round}) + " ", parts, "."]);
      if ((plan.again || []).includes("req")) rows.push([t("desk.reopen.req.pre"), h("b", null, t("desk.reopen.req.bold")), t("desk.reopen.req.post")]);
      if ((plan.again || []).includes("plan")) rows.push([t("desk.reopen.plan.pre"), h("b", null, t("desk.reopen.plan.bold")), t("desk.reopen.plan.post")]);
      rows.push([t("desk.reopen.branch")]);
    } else if (plan.mode === "same") {
      rows.push([t("desk.reopen.same.moves")], [t("desk.reopen.same.holds")]);
    } else if (plan.mode === "refused") {
      rows.push([t(plan.why === "checks" ? "desk.reopen.no.checks" : "desk.reopen.no.partial")]);
    }
    return h("ul", {class: "ro-what"}, rows.map((row, index) => h("li", {"data-i": plan.mode === "refused" ? "!" : String(index + 1)}, row)));
  }

  // The words of a refusal of `/api/super/send`: the server's own (`send.refused.<why>`), else the code shown as it is.
  const whyText = (why, error) => (Object.prototype.hasOwnProperty.call(TEXT, "send.refused." + why) ? t("send.refused." + why, {error: String(error || "")}) : t("desk.reopen.why.other", {why: String(why || "?")}));

  // The card. `plan`: what `taskreopen.plan_of` gave. Both ways close it and let the page draw again (`SERVE.done`); a refusal is shown in the card, which stays.
  function card(name, plan) {
    const kind = kindOf(plan.mode), refused = plan.mode === "refused";
    const number = plan.mode === "new" ? plan.next_round : plan.round;  // the round the task will be in
    const said = h("div", {class: "bad", role: "alert"});
    const message = refused ? null : h("textarea", {class: "ro-msg", rows: 3, maxlength: 10000, placeholder: t(plan.mode === "new" ? "desk.reopen.msg.new" : "desk.reopen.msg.same", {round: number}), "aria-label": t("desk.reopen.msg")});
    const no = h("button", {type: "button", class: "act ro-btn"}, t("board.serve.cancel"));
    const only = h("button", {type: "button", class: "act ro-btn", disabled: refused ? "disabled" : null}, t("desk.reopen.only"));
    const recover = refused && plan.why !== "checks" && SERVE.runs("recover");
    const hand = h("button", {type: "button", class: "act ro-btn primary", disabled: refused && !recover ? "disabled" : null}, t(recover ? "desk.reopen.recover" : "desk.reopen.hand"));
    const view = SERVE.dialog([
      h("h2", {class: "ro-title"}, t("desk.reopen.title", {name})), h("p", {class: "sub ro-who"}, whoLine(plan)),
      h("span", {class: "ro-mode " + kind}, icon(modeIcon[kind], 13), h("span", null, t(MODE[plan.mode], {round: number}))),
      whatList(plan),
      refused ? null : h("label", {class: "ro-lbl"}, t("desk.reopen.msg"), message),
      said, h("div", {class: "ro-btns"}, no, only, hand), refused ? null : h("p", {class: "ro-foot"}, t("desk.reopen.foot"))]);
    view.box.classList.add("ro-card");
    no.addEventListener("click", view.close);
    const labels = new Map([[only, only.textContent], [hand, hand.textContent]]);
    const busy = (on, button) => { only.disabled = on || refused; hand.disabled = on; no.disabled = on; button.textContent = on ? t("board.serve.working") : labels.get(button); };
    const fail = (error, button) => { busy(false, button); said.replaceChildren(...SERVE.reasons(error && error.message ? error.message : String(error))); };
    only.addEventListener("click", () => {
      said.replaceChildren(); busy(true, only);
      SERVE.post("/api/act", {action: "reopen", task: name, step: "act"}).then(() => { view.close(); SERVE.done(); }, (error) => fail(error, only));
    });
    hand.addEventListener("click", () => {
      said.replaceChildren();
      if (recover) {  // partial: the way out is Recover, in its own window
        view.close();
        const button = h("button", {type: "button", class: "act", "data-label": t("board.action.recover")}, t("board.action.recover"));
        SERVE.act(button, {name}, {action: "recover"});
        return;
      }
      busy(true, hand);
      SERVE.post("/api/super/send", {task: name, text: message.value.trim()}).then((answer) => {
        if (answer && answer.ok === false) { fail({message: whyText(answer.why, answer.error)}, hand); return; }
        view.close(); SERVE.done();
      }, (error) => fail(error, hand));
    });
    return view;
  }

  // Opens the card. `plan` is given when the page has it (the task page); else it is asked for (the list): `/api/act` reopen with `step: preview`.
  function open(name, plan) {
    if (plan && plan.mode && plan.mode !== "open") return Promise.resolve(card(name, plan));
    return SERVE.post("/api/act", {action: "reopen", task: name, step: "preview"}).then((data) => card(name, data.result), (error) => { SERVE.failed(error); });
  }

  // The pill of the task page's head, left of "Checks after the close" (the same look: `rv-btn`).
  function pill(name, plan) {
    const button = h("button", {type: "button", class: "rv-btn ro-pill", "aria-haspopup": "dialog", title: t("desk.reopen.tip")}, icon("again", 14), h("span", {class: "rv-name"}, t("desk.reopen.button")));
    button.addEventListener("click", () => { open(name, plan); });
    return button;
  }

  // The hover of the list's icon, drawn on the page itself (the list's box cuts off what leaves it): the mode, one sentence, and what a click does.
  let pop = null;
  const hide = () => { if (pop) { pop.remove(); pop = null; } };
  document.addEventListener("scroll", hide, {capture: true, passive: true});
  window.addEventListener("resize", hide);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") hide(); });
  function tipOf(row) {
    const info = row.reopen || {};
    const kind = kindOf(info.mode);
    const word = info.mode === "refused" ? (info.why === "checks" ? TIP.checks : TIP.partial) : info.mode === "new" ? TIP.new : TIP.same;
    const head = t(MODE[info.mode] || MODE.refused, {round: info.mode === "new" ? info.next_round : info.round});
    return {kind, head, sentence: t(word, {round: info.round}), click: t("desk.reopen.tip.click")};
  }
  function show(button, row) {
    hide();
    if (!button.isConnected) return;
    const found = tipOf(row);
    pop = h("div", {class: "ro-tip", role: "tooltip"}, h("span", {class: "m " + found.kind}, found.head), h("br"), found.sentence, h("br"), h("span", {class: "k"}, found.click));
    document.body.append(pop);
    const at = button.getBoundingClientRect(), width = pop.offsetWidth, height = pop.offsetHeight, edge = 8;
    pop.style.left = Math.max(edge, Math.min(at.right - width, document.documentElement.clientWidth - width - edge)) + "px";
    pop.style.top = (at.bottom + 6 + height <= window.innerHeight - edge ? at.bottom + 6 : Math.max(edge, at.top - 6 - height)) + "px";
  }

  // The icon of a closed row in the list, next to Archive: no words in the row, the hover says which reopen it will be, a click opens the card.
  function rowButton(row) {
    const info = row.reopen || {};
    const button = h("button", {type: "button", class: "act ro-ic " + kindOf(info.mode), "aria-label": t("desk.reopen.button") + " " + row.name, "aria-haspopup": "dialog"}, icon("again", 14));
    button.addEventListener("mouseenter", () => show(button, row));
    button.addEventListener("focus", () => show(button, row));
    button.addEventListener("mouseleave", hide);
    button.addEventListener("blur", hide);
    button.addEventListener("click", () => { hide(); open(row.name); });
    return button;
  }

  return {open, pill, rowButton, card, icon};
})();
