// Talking to the chat of a task from a served page (1.6, B72): the send panel, "steer" and "stop"; the "New task" dialog (B73). Loaded after serve.js; only a page the board server sent has it.
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

  // "New task" (B73): a chat is made in VS Code and told to open the task. The server checks every field again and makes the first message (a fixed English text, then what the person wrote);
  // this dialog only collects the fields and shows that message. The mode (interactive) and the folder (no worktree) are fixed and not on the form.
  function create() {
    const state = {lang: "en", perm: "allow-all", busy: false, ready: false, timer: null, models: [], options: null};
    const field = (label, control, extra) => h("label", {class: "new-field" + (extra ? " " + extra : "")}, h("span", {class: "sub label"}, label), control);
    const name = h("input", {type: "text", class: "send-body", maxlength: 80, autocomplete: "off", spellcheck: "false", placeholder: t("board.new.name.ph")});
    const kind = h("select", {class: "send-body"});
    const source = h("select", {class: "send-body"});
    const text = h("textarea", {rows: 5, class: "send-body", placeholder: t("board.new.text.ph"), maxlength: 5000});
    const model = h("select", {class: "send-body"});
    const thinking = h("select", {class: "send-body"});
    const preview = h("pre", {class: "send-preview"}, "...");
    const problem = h("div", {class: "sub"});  // what is not right yet: shown quietly while the person types
    const blocked = h("div", {class: "bad"});
    const said = h("div", {class: "bad"});
    const permHint = h("p", {class: "sub"});
    const go = h("button", {type: "button", class: "act hot", disabled: "disabled"}, t("board.new.go"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const langChips = ["en", "zh"].map((lang) => {
      const chip = h("button", {type: "button", class: "chip" + (lang === "en" ? " on" : ""), "aria-pressed": lang === "en" ? "true" : "false"}, t("desk.send.lang." + lang));
      chip.addEventListener("click", () => { state.lang = lang; langChips.forEach((item, at) => { const on = ["en", "zh"][at] === lang; item.classList.toggle("on", on); item.setAttribute("aria-pressed", on ? "true" : "false"); }); refresh(); });
      return chip;
    });
    const permChips = ["allow-all", "default", "assisted"].map((perm) => {
      const chip = h("button", {type: "button", class: "chip" + (perm === state.perm ? " on" : ""), "aria-pressed": perm === state.perm ? "true" : "false"}, t("board.new.perm." + perm));
      chip.addEventListener("click", () => { state.perm = perm; showPerm(); refresh(); });
      return chip;
    });
    function showPerm() {
      permChips.forEach((item, at) => { const on = ["allow-all", "default", "assisted"][at] === state.perm; item.classList.toggle("on", on); item.setAttribute("aria-pressed", on ? "true" : "false"); });
      permHint.textContent = t("board.new.perm." + state.perm + ".hint");
    }
    const view = SERVE.dialog([h("h2", null, t("board.new.title")), blocked,
      h("div", {class: "new-grid"}, field(t("board.new.name"), name), field(t("board.new.kind"), kind)),
      field(t("board.new.source"), source), h("p", {class: "sub"}, t("board.new.source.hint")),
      field(t("board.new.text"), text),
      h("div", {class: "new-grid three"}, field(t("board.new.model"), model), field(t("board.new.thinking"), thinking), field(t("board.new.lang"), h("div", {class: "chips"}, langChips))),
      h("div", {class: "send-lang"}, h("span", {class: "sub"}, t("board.new.perm")), h("div", {class: "chips"}, permChips)), permHint, h("p", {class: "sub"}, t("board.new.fixed")),
      h("div", {class: "sub label"}, t("board.new.first")), preview, problem, h("div", {class: "row send-actions"}, go, no), said]);
    const body = (step) => ({step, name: name.value.trim(), kind: kind.value, source: source.value, text: text.value, model: model.value, thinking: thinking.value, lang: state.lang, permission: state.perm});
    const sync = () => { go.disabled = state.busy || !state.ready; };
    function levels() {
      const found = state.models.find((item) => item.id === model.value);
      const list = (found && found.thinking && found.thinking.levels) || [];
      thinking.replaceChildren(h("option", {value: ""}, t("board.new.thinking.default")), ...list.map((level) => h("option", {value: level}, level)));
      thinking.disabled = !list.length;
    }
    function refresh() {
      clearTimeout(state.timer);
      state.timer = setTimeout(() => {
        ask("/api/create", body("preview")).then((found) => {
          preview.textContent = found.text;
          problem.textContent = "";
          state.ready = !found.blocked;
          blocked.replaceChildren(...(found.blocked ? SERVE.reasons(found.blocked) : []));
          sync();
        }, (error) => {
          state.ready = false;
          preview.textContent = "...";
          problem.replaceChildren(...SERVE.reasons(shown(error)));  // quiet: it is what is missing now, not a failure
          sync();
        });
      }, 250);
    }
    const close = () => { clearTimeout(state.timer); view.close(); };
    no.addEventListener("click", close);
    for (const control of [name, text]) control.addEventListener("input", refresh);
    for (const control of [kind, source, thinking]) control.addEventListener("change", refresh);
    model.addEventListener("change", () => { levels(); refresh(); });
    go.addEventListener("click", () => {
      state.busy = true; go.textContent = t("board.new.working"); sync(); said.replaceChildren();
      ask("/api/create", body("act")).then((found) => {
        clearTimeout(state.timer);
        const done = h("button", {type: "button", class: "act hot"}, t("board.new.close"));
        done.addEventListener("click", () => { close(); SERVE.done(); });
        view.box.replaceChildren(h("h2", null, t("board.new.title") + " \u00b7 " + found.name), h("p", null, t("board.new.done")),
          found.warn ? h("p", {class: "bad"}, found.warn) : found.unchecked ? h("p", {class: "sub"}, t("board.new.done.unchecked")) : null, h("div", {class: "row send-actions"}, done));
        done.focus();
      }, (error) => { state.busy = false; go.textContent = t("board.new.go"); sync(); said.replaceChildren(...SERVE.reasons(shown(error))); });
    });
    ask("/api/create", {step: "options"}).then((found) => {
      state.options = found; state.models = found.models || [];
      kind.replaceChildren(...found.kinds.map((item) => h("option", {value: item, selected: item === "dev" ? "" : null}, t("task.kind." + item))));
      source.replaceChildren(h("option", {value: ""}, t("board.new.source.none")), ...found.sources.map((item) => h("option", {value: item.name}, item.name + (item.kind ? " \u00b7 " + t("task.kind." + item.kind) : "") + (item.status === "closed" ? " \u00b7 " + t("board.filter.closed") : ""))));
      model.replaceChildren(h("option", {value: ""}, t("board.new.model.chat")), ...state.models.map((item) => h("option", {value: item.id}, item.name)));
      state.perm = found.permission || "allow-all";
      showPerm(); levels();
      if (!found.ready) blocked.replaceChildren(h("p", null, t("board.new.off")), h("p", {class: "sub"}, t("board.vs.why." + (found.why || "starting"))));
      refresh();
    }, (error) => { blocked.replaceChildren(h("p", null, t("board.new.options", {error: shown(error)}))); });
    showPerm(); levels();
    name.focus();
  }

  return {panel, steer, stop, create};
})();
