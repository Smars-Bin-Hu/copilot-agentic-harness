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
    const state = {lang: "en", note: "", text: "", blocked: "", busy: false, timer: null};
    const preview = h("pre", {class: "send-preview"}, "...");
    const blocked = h("div", {class: "bad"});
    const said = h("div", {class: "bad"});
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
      h("p", {class: "sub"}, t("desk.send.hint")),
      h("div", {class: "sub label"}, t("desk.send.preview")), preview, drafts,
      h("div", {class: "send-lang"}, h("span", {class: "sub"}, t("desk.send.lang")), chips),
      h("div", null, h("div", {class: "sub label"}, t("desk.send.note")), note),
      blocked, h("div", {class: "row send-actions"}, send, save, copy, no), said]);
    const sync = () => {
      send.disabled = state.busy || !state.text || Boolean(state.blocked);
      save.disabled = state.busy || !state.note.trim();
    };
    function refresh() {
      clearTimeout(state.timer);
      state.timer = setTimeout(() => {
        ask("/api/send", {task: row.name, kind: "go", lang: state.lang, note: state.note, body: "", step: "preview"}).then((found) => {
          state.text = found.text;
          state.blocked = found.blocked || "";
          preview.textContent = found.text;
          drafts.textContent = found.drafts ? t("desk.send.drafts", {count: found.drafts}) : "";
          blocked.replaceChildren(...(state.blocked ? [h("p", null, state.blocked), h("p", {class: "sub"}, t("desk.send.copy.hint"))] : []));
          said.replaceChildren();
          sync();
        }, (error) => {
          state.text = "";
          preview.textContent = "...";
          said.replaceChildren(...SERVE.reasons(shown(error)));
          sync();
        });
      }, 250);
    }
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
      ask("/api/send", {task: row.name, kind: "go", lang: state.lang, note: state.note, body: "", step: "act"}).then(() => { close(); SERVE.done(); }, (error) => {
        state.busy = false; send.textContent = t("desk.send.go"); sync();
        if (error.data && error.data.fallback) state.text = error.data.fallback;  // the text that was refused stays in the copy button
        said.replaceChildren(...SERVE.reasons(shown(error)), h("p", {class: "sub"}, t("desk.send.copy.hint")));
      });
    });
    sync();
    refresh();
    send.focus();
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

  // "Withdraw": the last message of the person leaves the chat with all that answered it, and its words come back to the reply box. It cannot be undone, so it asks first.
  function withdraw(row, done) {
    const go = h("button", {type: "button", class: "act hot"}, t("desk.undo.go"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const said = h("div", {class: "bad"});
    const view = SERVE.dialog([h("h2", null, t("desk.undo.title") + " · " + row.name), h("p", null, t("desk.undo.hint")), h("div", {class: "row"}, go, no), said]);
    no.addEventListener("click", view.close);
    go.addEventListener("click", () => {
      go.disabled = true;
      ask("/api/undo", {task: row.name}).then((found) => { view.close(); done(found); SERVE.done(); }, (error) => { go.disabled = false; said.replaceChildren(...SERVE.reasons(shown(error))); });
    });
  }

  // "New task" (B73): a chat is made in VS Code and told to open the task. The server checks every field again and makes the first message (a fixed English text, then what the person wrote);
  // this dialog only collects the fields and shows that message. The mode (interactive) and the folder (no worktree) are fixed and not on the form.
  function create() {
    const state = {lang: "en", perm: "allow-all", busy: false, ready: false, timer: null, models: [], options: null, domainList: null, domains: new Set()};
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
    const kbBox = h("div", {class: "new-kb"});  // the knowledge base domains a task may be about: ticks, and "None" (a choice of its own). Drawn when the options come.
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
      h("div", {class: "new-field"}, h("span", {class: "sub label"}, t("board.new.kb")), kbBox),
      field(t("board.new.text"), text),
      h("div", {class: "new-grid three"}, field(t("board.new.model"), model), field(t("board.new.thinking"), thinking), field(t("board.new.lang"), h("div", {class: "chips"}, langChips))),
      h("div", {class: "send-lang"}, h("span", {class: "sub"}, t("board.new.perm")), h("div", {class: "chips"}, permChips)), permHint, h("p", {class: "sub"}, t("board.new.fixed")),
      h("div", {class: "sub label"}, t("board.new.first")), h("p", {class: "sub"}, t("board.new.first.hint")), preview, problem, said, h("div", {class: "row send-actions new-actions"}, go, no)]);
    const body = (step) => ({step, name: name.value.trim(), kind: kind.value, source: source.value, text: text.value, model: model.value, thinking: thinking.value, lang: state.lang, permission: state.perm, domains: Array.from(state.domains)});
    // The knowledge base: the domains this repository's knowledge bases have. None ticked is a valid choice. When there are no domains the box says so and the dialog goes on.
    function drawKb() {
      const list = state.domainList;
      if (list === null) { kbBox.replaceChildren(); return; }
      if (!list.length) { kbBox.replaceChildren(h("p", {class: "sub new-kb-empty"}, t("board.new.kb.empty"))); return; }
      const chip = (label, on, click, full) => {
        const node = h("button", {type: "button", class: "chip kb-chip" + (on ? " on" : ""), "aria-pressed": on ? "true" : "false", title: full || label}, h("span", {class: "kb-name"}, label));
        node.addEventListener("click", click);
        return node;
      };
      const none = chip(t("board.new.kb.none"), !state.domains.size, () => { state.domains.clear(); drawKb(); refresh(); });
      const ticks = list.map((item) => chip(item, state.domains.has(item), () => { state.domains.has(item) ? state.domains.delete(item) : state.domains.add(item); drawKb(); refresh(); }));
      kbBox.replaceChildren(h("div", {class: "chips kb-list"}, none, ...ticks), h("p", {class: "sub"}, t("board.new.kb.hint")));
    }
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
          preview.textContent = found.text;  // the server's own message, grown from the fields as they are now (a field not right yet is a <placeholder>); read only
          problem.replaceChildren(...(found.problem ? SERVE.reasons(found.problem) : []));  // quiet: it is what is missing now, not a failure
          state.ready = !found.blocked && !found.problem;
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
        view.box.replaceChildren(...[h("h2", null, t("board.new.title") + " \u00b7 " + found.name), h("p", null, t("board.new.done")),
          found.warn ? h("p", {class: "bad"}, found.warn) : found.unchecked ? h("p", {class: "sub"}, t("board.new.done.unchecked")) : null, h("div", {class: "row send-actions"}, done)].filter(Boolean));
        done.focus();
      }, (error) => { state.busy = false; go.textContent = t("board.new.go"); sync(); said.replaceChildren(...SERVE.reasons(shown(error))); });
    });
    ask("/api/create", {step: "options"}).then((found) => {
      state.options = found; state.models = found.models || [];
      kind.replaceChildren(...found.kinds.map((item) => h("option", {value: item, selected: item === "dev" ? "" : null}, t("task.kind." + item))));
      source.replaceChildren(h("option", {value: ""}, t("board.new.source.none")), ...found.sources.map((item) => h("option", {value: item.name}, item.name + (item.kind ? " \u00b7 " + t("task.kind." + item.kind) : "") + (item.status === "closed" ? " \u00b7 " + t("board.filter.closed") : ""))));
      model.replaceChildren(h("option", {value: ""}, t("board.new.model.chat")), ...state.models.map((item) => h("option", {value: item.id}, item.name)));
      state.perm = found.permission || "allow-all";
      state.domainList = Array.isArray(found.domains) ? found.domains : [];
      drawKb();
      showPerm(); levels();
      if (!found.ready) blocked.replaceChildren(h("p", null, t("board.new.off")), h("p", {class: "sub"}, t("board.vs.why." + (found.why || "starting"))));
      refresh();
    }, (error) => { blocked.replaceChildren(h("p", null, t("board.new.options", {error: shown(error)}))); });
    showPerm(); levels();
    name.focus();
  }

  // "Allow . deny" (B75): the chat waits for a person to let a tool run. The dialog shows the one call (the command, redacted and cut, and its id) and sends the decision for that call only.
  // The server reads the host again and refuses when the call is gone or is not what this dialog showed.
  function confirm(row) {
    const found = row.ask;
    if (!found || found.kind !== "confirm") return;
    const allow = h("button", {type: "button", class: "act hot"}, t("board.ask.allow"));
    const deny = h("button", {type: "button", class: "act"}, t("board.ask.deny"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const said = h("div", {class: "bad"});
    const view = SERVE.dialog([h("h2", null, t("board.action.confirm") + " \u00b7 " + row.name), h("p", null, t("board.ask.confirm.hint")),
      found.title ? h("p", {class: "sub"}, found.title) : null, found.intention ? h("p", null, found.intention) : null,
      h("pre", {class: "send-preview"}, found.command || "-"),
      h("p", {class: "sub"}, t("board.ask.call", {tool: found.tool || "-", id: found.tool_call_id})), found.count > 1 ? h("p", {class: "sub"}, t("board.ask.more", {count: found.count - 1})) : null,
      h("div", {class: "row send-actions"}, allow, deny, no), said]);
    const decide = (decision) => {
      allow.disabled = deny.disabled = true;
      ask("/api/confirm", {task: row.name, id: found.id, tool_call_id: found.tool_call_id, digest: found.digest, decision}).then(() => { view.close(); SERVE.done(); },
        (error) => { allow.disabled = deny.disabled = false; said.replaceChildren(...SERVE.reasons(shown(error))); });
    };
    allow.addEventListener("click", () => decide("allow"));
    deny.addEventListener("click", () => decide("deny"));
    no.addEventListener("click", view.close);
    no.focus();  // Enter does not allow anything by accident
  }

  // "Answer..." (B75): the agent asked a question. One control for each question (options, a box, yes or no, a number); the answers go for the one request this dialog showed.
  function question(row) {
    const found = row.ask;
    if (!found || found.kind !== "question" || !found.supported) return;
    const values = {};
    const said = h("div", {class: "bad"});
    const send = h("button", {type: "button", class: "act hot", disabled: "disabled"}, t("board.ask.send"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const ready = () => { send.disabled = found.questions.some((item) => item.required && (values[item.id] === undefined || values[item.id] === "" || (Array.isArray(values[item.id]) && !values[item.id].length))); };
    const control = (item) => {
      const name = "q-" + item.id;
      if (item.kind === "single-select" || item.kind === "boolean") {
        const list = item.kind === "boolean" ? [{id: "yes", label: t("board.ask.yes")}, {id: "no", label: t("board.ask.no")}] : item.options;
        return h("div", {class: "ask-options"}, list.map((option) => {
          const box = h("input", {type: "radio", name});
          box.addEventListener("change", () => { values[item.id] = item.kind === "boolean" ? option.id === "yes" : option.id; ready(); });
          return h("label", {class: "ask-option"}, box, " " + option.label);
        }));
      }
      if (item.kind === "multi-select") {
        return h("div", {class: "ask-options"}, item.options.map((option) => {
          const box = h("input", {type: "checkbox", name});
          box.addEventListener("change", () => {
            const now = new Set(values[item.id] || []);
            box.checked ? now.add(option.id) : now.delete(option.id);
            values[item.id] = Array.from(now);
            ready();
          });
          return h("label", {class: "ask-option"}, box, " " + option.label);
        }));
      }
      const number = item.kind === "number" || item.kind === "integer";
      const input = number ? h("input", {type: "number", class: "send-body", step: item.kind === "integer" ? "1" : "any"}) : h("textarea", {rows: 3, class: "send-body", maxlength: 2000});
      input.addEventListener("input", () => { values[item.id] = number ? (input.value === "" ? undefined : Number(input.value)) : input.value; ready(); });
      return input;
    };
    const fields = found.questions.map((item) => h("div", {class: "ask-field"}, h("div", {class: "sub label"}, item.title + (item.required ? " *" : "")),
      item.message && item.message !== item.title ? h("div", {class: "sub"}, item.message) : null, control(item)));
    const view = SERVE.dialog([h("h2", null, t("board.action.question") + " \u00b7 " + row.name), found.message ? h("p", null, found.message) : null, ...fields,
      found.count > 1 ? h("p", {class: "sub"}, t("board.ask.more", {count: found.count - 1})) : null, h("div", {class: "row send-actions"}, send, no), said]);
    ready();
    send.addEventListener("click", () => {
      send.disabled = true; send.textContent = t("board.serve.working");
      const answers = {};
      for (const [key, value] of Object.entries(values)) if (value !== undefined) answers[key] = value;
      ask("/api/answer", {task: row.name, id: found.id, request_id: found.request_id, digest: found.digest, answers}).then(() => { view.close(); SERVE.done(); },
        (error) => { send.textContent = t("board.ask.send"); ready(); said.replaceChildren(...SERVE.reasons(shown(error))); });
    });
    no.addEventListener("click", view.close);
  }

  return {panel, stop, withdraw, create, confirm, question};
})();
