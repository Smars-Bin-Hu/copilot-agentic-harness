// Talking to the chat of a task from a served page (1.6, B72): the send panel, "steer" and "stop". Loaded after serve.js; only a page the board server sent has it.
// The text of a message is made by the server (chatsend.py): this file shows it and asks for it to be sent. Every call is a POST of the paired browser.
"use strict";

const CHAT = (function () {
  const ask = (path, body) => SERVE.post(path, body).then((data) => data.result);
  const shown = (error) => (error && error.message) || String(error);

  // A message the person may copy to VS Code by hand: the way out when the board cannot send.
  function copyButton(getText) {
    const button = h("button", {type: "button", class: "act", "data-label": t("desk.go.copy")}, t("desk.go.copy"));
    button.addEventListener("click", () => copyCommand(button, getText()));
    return button;
  }

  // The panel: the message in full, the reply language, an optional note, then send / save as draft / copy. `action` is "send" (a template after an approval) or "answer" (the person's own words).
  function panel(row, action) {
    const answer = action === "answer";
    const state = {lang: "en", note: "", body: "", text: "", blocked: "", busy: false, timer: null};
    const preview = h("pre", {class: "send-preview"}, "...");
    const blocked = h("div", {class: "bad"});
    const said = h("div", {class: "bad"});
    const body = h("textarea", {rows: 6, class: "send-body", placeholder: t("desk.send.body.ph"), maxlength: 20000});
    const note = h("textarea", {rows: 2, class: "send-body", placeholder: t("desk.send.note.ph"), maxlength: 2000});
    const chips = ["en", "zh"].map((lang) => {
      const chip = h("button", {type: "button", class: "chip" + (lang === "en" ? " on" : ""), "aria-pressed": lang === "en" ? "true" : "false"}, t("desk.send.lang." + lang));
      chip.addEventListener("click", () => { state.lang = lang; chips.forEach((item, at) => { const on = ["en", "zh"][at] === lang; item.classList.toggle("on", on); item.setAttribute("aria-pressed", on ? "true" : "false"); }); refresh(); });
      return chip;
    });
    const send = h("button", {type: "button", class: "act hot"}, t("desk.send.go"));
    const save = h("button", {type: "button", class: "act", title: t("desk.send.draft.tip")}, t("desk.send.draft"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const copy = copyButton(() => state.text);
    const drafts = h("p", {class: "sub"});
    const view = SERVE.dialog([h("h2", null, t("board.action." + action) + " · " + row.name),
      h("p", {class: "sub"}, t(answer ? "desk.send.answer.hint" : "desk.send.hint")),
      answer ? body : null, h("div", {class: "sub label"}, t("desk.send.preview")), preview, drafts,
      h("div", {class: "send-lang"}, h("span", {class: "sub"}, t("desk.send.lang")), chips),
      answer ? null : h("div", null, h("div", {class: "sub label"}, t("desk.send.note")), note),
      blocked, h("div", {class: "row send-actions"}, send, answer ? null : save, copy, no), said]);
    const sync = () => {
      send.disabled = state.busy || !state.text || Boolean(state.blocked) || (answer && !state.body.trim());
      save.disabled = state.busy || !state.note.trim();
    };
    function refresh() {
      clearTimeout(state.timer);
      state.timer = setTimeout(() => {
        ask("/api/send", {task: row.name, kind: answer ? "answer" : "go", lang: state.lang, note: state.note, body: state.body, step: "preview"}).then((found) => {
          state.text = found.text;
          state.blocked = found.blocked || "";
          preview.textContent = found.text;
          drafts.textContent = found.drafts ? t("desk.send.drafts", {count: found.drafts}) : "";
          blocked.replaceChildren(...(state.blocked ? [h("p", null, state.blocked), h("p", {class: "sub"}, t("desk.send.copy.hint"))] : []));
          said.replaceChildren();
          sync();
        }, (error) => {
          state.text = "";
          preview.textContent = answer ? "" : "...";
          said.replaceChildren(...SERVE.reasons(shown(error)));
          sync();
        });
      }, 250);
    }
    body.addEventListener("input", () => { state.body = body.value; sync(); refresh(); });
    note.addEventListener("input", () => { state.note = note.value; sync(); refresh(); });
    const poll = setInterval(() => { if (!state.busy) refresh(); }, 5000);  // the chat may become idle (or busy) while the panel is open
    const close = () => { clearInterval(poll); clearTimeout(state.timer); view.close(); };
    no.addEventListener("click", close);
    save.addEventListener("click", () => {
      state.busy = true; sync();
      ask("/api/draft", {task: row.name, text: state.note}).then(() => { note.value = ""; state.note = ""; state.busy = false; refresh(); sync(); },
        (error) => { state.busy = false; said.replaceChildren(...SERVE.reasons(shown(error))); sync(); });
    });
    send.addEventListener("click", () => {
      state.busy = true; send.textContent = t("board.serve.working"); sync();
      ask("/api/send", {task: row.name, kind: answer ? "answer" : "go", lang: state.lang, note: state.note, body: state.body, step: "act"}).then(() => { close(); SERVE.done(); }, (error) => {
        state.busy = false; send.textContent = t("desk.send.go"); sync();
        if (error.data && error.data.fallback) state.text = error.data.fallback;  // the text that was refused stays in the copy button
        said.replaceChildren(...SERVE.reasons(shown(error)), h("p", {class: "sub"}, t("desk.send.copy.hint")));
      });
    });
    sync();
    refresh();
    (answer ? body : send).focus();
  }

  // "Steer": one more line to the agent while it works. It reads it at its next step, in the same turn.
  function steer(row) {
    const text = h("textarea", {rows: 4, class: "send-body", placeholder: t("desk.steer.ph"), maxlength: 20000});
    const go = h("button", {type: "button", class: "act hot", disabled: "disabled"}, t("desk.steer.go"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const said = h("div", {class: "bad"});
    const view = SERVE.dialog([h("h2", null, t("board.action.steer") + " · " + row.name), h("p", {class: "sub"}, t("desk.steer.hint")), text, h("div", {class: "row"}, go, copyButton(() => text.value.trim()), no), said]);
    text.addEventListener("input", () => { go.disabled = !text.value.trim(); });
    no.addEventListener("click", view.close);
    go.addEventListener("click", () => {
      go.disabled = true;
      ask("/api/steer", {task: row.name, text: text.value}).then(() => { view.close(); SERVE.done(); }, (error) => { go.disabled = false; said.replaceChildren(...SERVE.reasons(shown(error))); });
    });
    text.focus();
  }

  // "Stop": cancel the turn that runs. What the agent already wrote stays; the chat is idle at once.
  function stop(row) {
    const go = h("button", {type: "button", class: "act hot"}, t("desk.stop.go"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const said = h("div", {class: "bad"});
    const view = SERVE.dialog([h("h2", null, t("board.action.stop") + " · " + row.name), h("p", null, t("desk.stop.hint")), h("div", {class: "row"}, go, no), said]);
    no.addEventListener("click", view.close);
    go.addEventListener("click", () => {
      go.disabled = true;
      ask("/api/stop", {task: row.name}).then(() => { view.close(); SERVE.done(); }, (error) => { go.disabled = false; said.replaceChildren(...SERVE.reasons(shown(error))); });
    });
  }

  return {panel, steer, stop};
})();
