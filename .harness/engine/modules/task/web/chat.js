// Talking to the chat of a task from a served page (1.6, B72): the send panel, "steer" and "stop"; the "New task" dialog (B73). Loaded after serve.js; only a page the board server sent has it.
// The text of a message is made by the server (chatsend.py): this file shows it and asks for it to be sent. Every call is a POST of the paired browser.
"use strict";

const CHAT = (function () {
  const ask = (path, body) => SERVE.post(path, body).then((data) => data.result);
  const shown = (error) => (error && error.message) || String(error);

  // The model a message goes with (1.6.101): on every dialog that sends to an agent. A chat that works on a task (`task`): the task's own model (Task settings), else the last one picked for a task in
  // this browser, never Copilot Fusion by default: a task may have much to read, and a cheap model picked for a short first message would read it all again after a switch. A short one-off chat (no
  // `task`): Copilot Fusion by default (`board.one_click_fusion`). A pick for a task is kept on the task (`/api/setting`), so its next messages and Say something use it too.
  const LAST = "harness.model.last";
  const remembered = () => { try { return JSON.parse(localStorage.getItem(LAST) || "null"); } catch (error) { return null; } };
  function remember(choice) { try { localStorage.setItem(LAST, JSON.stringify(choice)); } catch (error) { /* kept for this dialog only */ } }
  // The context sizes a model offers (1.6.109), for every dialog that picks a model: a select that shows only when the model has more than one size, at its default unless `keep` names
  // another. `chosen()`: the size picked, as text, or "" when the model has none to pick. `fill(found, keep)` fills it for a model of the host's list.
  function sizePick(select, holder) {
    const sizes = (found) => (found && found.context && found.context.sizes) || [];
    return {
      fill(found, keep) {
        const list = sizes(found);
        holder.hidden = list.length < 2;
        const wanted = list.some((item) => String(item.id) === String(keep)) ? keep : found && found.context ? found.context.default : "";
        select.replaceChildren(...list.map((item) => h("option", {value: String(item.id), selected: String(item.id) === String(wanted) ? "" : null}, item.label)));
      },
      chosen: () => (holder.hidden ? "" : select.value),
      same: (found, size) => String(size || (found && found.context ? found.context.default : "") || "") === String(holder.hidden ? (found && found.context ? found.context.default : "") || "" : select.value),
    };
  }

  function modelPick(task) {
    const state = {models: [], current: {}, ready: false};
    const model = h("select", {class: "send-body", "aria-label": t("board.new.model")});
    const level = h("select", {class: "send-body", "aria-label": t("board.new.thinking")});
    const room = h("select", {class: "send-body", "aria-label": t("board.new.context"), title: t("desk.set.context.tip")});
    const sizes = sizePick(room, room);
    const node = h("div", {class: "model-pick"}, h("span", {class: "sub"}, t("desk.model.runs")), model, level, room);
    const of = (id) => state.models.find((item) => item.id === id);
    const levels = (keep) => {
      const found = of(model.value);
      const list = (found && found.thinking && found.thinking.levels) || [];
      level.replaceChildren(h("option", {value: ""}, t("board.new.thinking.default")), ...list.map((one) => h("option", {value: one}, thinkingLabel(one, found))));
      level.value = list.includes(keep) ? keep : "";
      level.disabled = !list.length;
    };
    const loaded = SERVE.post("/api/skill", {step: "options", ...(task ? {task} : {})}).then((data) => {
      const found = data.result;
      state.models = found.models || [];
      state.current = found.task || {};
      const pick = (task ? (state.current.id ? state.current : remembered()) : found.small) || {};
      model.replaceChildren(h("option", {value: ""}, t("board.new.model.chat")), ...state.models.map((item) => h("option", {value: item.id}, item.name)));
      model.value = state.models.some((item) => item.id === pick.id) ? pick.id : "";
      levels(pick.thinking || "");
      sizes.fill(of(model.value), pick.context);
      state.ready = true;
    }, () => { node.hidden = true; });  // no list (VS Code away): the message goes as it did before
    const picked = () => { if (task) remember({id: model.value, thinking: level.value, context: sizes.chosen()}); };
    model.addEventListener("change", () => { levels(""); sizes.fill(of(model.value), ""); picked(); });
    level.addEventListener("change", picked);
    room.addEventListener("change", picked);
    return {
      node,
      // Before the message goes: a task keeps the pick when it changed; a one-off chat names it in its own request (the fields to add to it).
      apply() {
        return loaded.then(() => {
          if (!state.ready) return {};
          const context = sizes.chosen();
          if (!task) return {model: model.value, thinking: level.value, ...(context ? {context} : {})};
          if ((state.current.id || "") === model.value && (state.current.thinking || "") === level.value && sizes.same(of(model.value), state.current.context)) return {};
          return ask("/api/setting", {task, id: model.value, thinking: level.value, context}).then(() => { state.current = {id: model.value, thinking: level.value, context}; return {}; });
        });
      },
    };
  }

  // A message the person may copy to VS Code by hand: the way out when the board cannot send.
  function copyButton(getText) {
    const button = h("button", {type: "button", class: "act", "data-label": t("desk.go.copy")}, t("desk.go.copy"));
    button.addEventListener("click", () => copyCommand(button, getText()));
    return button;
  }

  // The files of a message, for the reply panel and New task: by the Attach button, a paste in `box` (a paste with words stays words: a screenshot has none) or a drop on `zone`. Each file is read into
  // the page; it goes with the message and is not kept anywhere else. `said`: where a refusal is written. `changed`: called when the list changed. chatsend.py holds the same three limits.
  const MAX_FILES = 10, MAX_FILE = 10 * 1024 * 1024, MAX_TOTAL = 20 * 1024 * 1024;
  const fileIcon = (paths) => {
    const NS = "http://www.w3.org/2000/svg", node = document.createElementNS(NS, "svg");
    for (const [key, value] of Object.entries({viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", "stroke-width": "1.5", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true"})) node.setAttribute(key, value);
    for (const d of paths) { const part = document.createElementNS(NS, "path"); part.setAttribute("d", d); node.append(part); }
    return node;
  };
  const sizeOf = (bytes) => (bytes < 1024 ? bytes + " B" : bytes < 1048576 ? Math.round(bytes / 1024) + " KB" : (bytes / 1048576).toFixed(1) + " MB");

  function fileTray(box, said, changed) {
    let files = [];
    const tray = h("div", {class: "rp-files", hidden: ""});
    const picker = h("input", {type: "file", multiple: "multiple", hidden: ""});
    const attach = h("button", {type: "button", class: "act rp-attach", title: t("desk.reply.attach.tip")}, fileIcon(["M13 7.5l-5.2 5.2a3 3 0 0 1-4.3-4.3l5.6-5.5a2 2 0 0 1 2.8 2.8L6.4 11.2a1 1 0 0 1-1.4-1.4l4.8-4.7"]), h("span", null, t("desk.reply.attach")));
    const refuse = (text) => said.append(h("p", null, text));
    function paint() {
      tray.hidden = !files.length;
      tray.replaceChildren(...files.map((item) => {
        const off = h("button", {type: "button", class: "rp-file-x", title: t("desk.reply.files.remove", {name: item.name}), "aria-label": t("desk.reply.files.remove", {name: item.name})}, fileIcon(["M4 4l8 8M12 4l-8 8"]));
        off.addEventListener("click", () => drop(item));
        return h("span", {class: "rp-file", title: item.name}, item.url ? h("img", {src: item.url, alt: ""}) : fileIcon(["M4 2h5l3 3v9H4zM9 2v3h3"]), h("span", {class: "rp-file-n"}, item.name), h("span", {class: "sub"}, sizeOf(item.size)), off);
      }));
      changed();
    }
    function drop(item) {
      if (item.url) URL.revokeObjectURL(item.url);
      files = files.filter((other) => other !== item);
      paint();
    }
    function add(list) {
      said.replaceChildren();
      for (const file of list) {
        const total = files.reduce((sum, item) => sum + item.size, 0);
        if (files.length >= MAX_FILES) { refuse(t("desk.reply.files.many", {n: MAX_FILES})); break; }
        if (file.size > MAX_FILE || total + file.size > MAX_TOTAL) { refuse(t("desk.reply.files.big", {name: file.name})); continue; }
        const item = {name: file.name || "file", type: file.type, size: file.size, data: "", url: file.type.startsWith("image/") ? URL.createObjectURL(file) : ""};
        files.push(item);
        const reader = new FileReader();
        reader.addEventListener("load", () => { item.data = String(reader.result).split(",")[1] || ""; if (item.data) changed(); else { refuse(t("desk.reply.files.read", {name: item.name})); drop(item); } });
        reader.addEventListener("error", () => { refuse(t("desk.reply.files.read", {name: item.name})); drop(item); });
        reader.readAsDataURL(file);
      }
      paint();
    }
    attach.addEventListener("click", () => picker.click());
    picker.addEventListener("change", () => { add([...picker.files]); picker.value = ""; });
    box.addEventListener("paste", (event) => {
      const data = event.clipboardData;
      if (!data || !data.files.length || data.getData("text/plain")) return;
      event.preventDefault();
      add([...data.files]);
    });
    return {
      tray, attach, picker,
      zone(node) {
        node.addEventListener("dragover", (event) => { event.preventDefault(); node.classList.add("drag-on"); });
        node.addEventListener("dragleave", (event) => { if (!node.contains(event.relatedTarget)) node.classList.remove("drag-on"); });
        node.addEventListener("drop", (event) => { event.preventDefault(); node.classList.remove("drag-on"); add([...event.dataTransfer.files]); });
      },
      reading: () => files.some((item) => !item.data),
      list: () => files.map((item) => ({name: item.name, type: item.type, data: item.data})),
      clear() { for (const item of files) if (item.url) URL.revokeObjectURL(item.url); files = []; paint(); },
    };
  }

  // The panel: the message in full, the reply language, an optional note, then send / save as draft / copy. `action` is "send" (a template after an approval) or "answer" (the person's own words).
  function panel(row, action) {
    const state = {lang: "", note: "", text: "", blocked: "", busy: false, timer: null};  // lang: empty until the person picks one; the chips show what the chat replies in
    const preview = h("pre", {class: "send-preview"}, "...");
    const blocked = h("div", {class: "bad"});
    const said = h("div", {class: "bad"});
    const note = h("textarea", {rows: 2, class: "send-body", placeholder: t("desk.send.note.ph"), maxlength: 2000});
    const chips = ["en", "zh"].map((lang) => {
      const chip = h("button", {type: "button", class: "chip" + (lang === "en" ? " on" : ""), "aria-pressed": lang === "en" ? "true" : "false"}, t("desk.send.lang." + lang));
      chip.addEventListener("click", () => { state.lang = lang; paintChips(lang); refresh(); });
      return chip;
    });
    const paintChips = (lang) => chips.forEach((item, at) => { const on = ["en", "zh"][at] === lang; item.classList.toggle("on", on); item.setAttribute("aria-pressed", on ? "true" : "false"); });
    const send = h("button", {type: "button", class: "act hot"}, t("desk.send.go"));
    const pick = modelPick(row.name);
    const save = h("button", {type: "button", class: "act", title: t("desk.send.draft.tip")}, t("desk.send.draft"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const copy = copyButton(() => state.text);
    const drafts = h("p", {class: "sub"});
    const view = SERVE.dialog([h("h2", null, actionTitle(action) + " · " + row.name),
      h("p", {class: "sub"}, t("desk.send.hint")),
      h("div", {class: "sub label"}, t("desk.send.preview")), preview, drafts,
      h("div", {class: "send-lang"}, h("span", {class: "sub"}, t("desk.send.lang")), chips), pick.node,
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
          if (!state.lang && found.reply) paintChips(found.reply);
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
      pick.apply().then(() => ask("/api/send", {task: row.name, kind: "go", lang: state.lang, note: state.note, body: "", step: "act"})).then(() => { close(); SERVE.done(); }, (error) => {
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
  let waiting = null;  // the New task notice while it is open: {name, line, row}; board.js hands it every board read (CHAT.seen)
  function seen(rows) {
    if (!waiting || !waiting.line.isConnected || !rows.some((row) => row.name === waiting.name)) return;
    const name = waiting.name;  // `waiting` is let go below, before the click
    const open = h("button", {type: "button", class: "act hot"}, t("board.new.open"));
    open.addEventListener("click", () => { location.href = "/task/" + encodeURIComponent(name); });
    waiting.line.replaceWith(h("p", null, t("board.new.here")));
    waiting.row.prepend(open);
    waiting = null;
  }

  function create(preset) {  // preset: `true` for the sample of the lesson, or {name, kind, domains, text, note, back} for a skill; `back` opens the place the person came from
    const state = {lang: "en", busy: false, ready: false, timer: null, models: [], options: null, domainList: null, domains: new Set(), linkTypes: []};
    const field = (label, control, extra) => h("label", {class: "new-field" + (extra ? " " + extra : "")}, h("span", {class: "sub label"}, label), control);
    const name = h("input", {type: "text", class: "send-body", maxlength: 80, autocomplete: "off", spellcheck: "false", placeholder: t("board.new.name.ph")});
    const kind = h("select", {class: "send-body"});
    const source = h("select", {class: "send-body"});
    const links = h("input", {type: "text", class: "send-body new-links", maxlength: 400, autocomplete: "off", spellcheck: "false", placeholder: t("board.new.links.ph")});  // tickets to link (1.7.20): `ado:300100`, several split by space or comma
    const linkKinds = h("div", {class: "chips new-link-types"});
    const smallNote = h("p", {class: "sub new-small", hidden: "", role: "note"}, t("board.new.small"));  // tickets named, a short text, Kind Dev: a small errand is lighter as Q&A (1.7.26). Kind is not changed for the person.
    const small = () => { const on = kind.value === "dev" && links.value.trim().length > 0 && text.value.trim().length < 140; if (smallNote.hidden === on) smallNote.hidden = !on; };
    const text = h("textarea", {rows: 5, class: "send-body", placeholder: t("board.new.text.ph"), maxlength: 5000});
    const said = h("div", {class: "bad"});
    const files = fileTray(text, said, () => sync());
    const model = h("select", {class: "send-body"});
    const thinking = h("select", {class: "send-body"});
    const room = h("select", {class: "send-body", title: t("desk.set.context.tip")});
    const roomField = field(t("board.new.context"), room, "new-context");
    const sizes = sizePick(room, roomField);
    const preview = h("pre", {class: "send-preview"}, "...");
    const grill = h("input", {type: "checkbox"});  // Ask me first: the opening of the task, not a thing of its own
    grill.addEventListener("change", () => refresh());
    const problem = h("div", {class: "sub"});  // what is not right yet: shown quietly while the person types
    const blocked = h("div", {class: "bad"});
    const kbBox = h("div", {class: "new-kb"});  // the knowledge base domains a task may be about: ticks, and "None" (a choice of its own). Drawn when the options come.
    const go = h("button", {type: "button", class: "act hot primary", disabled: "disabled"}, t("board.new.go"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const langChips = ["en", "zh"].map((lang) => {
      const chip = h("button", {type: "button", class: "chip" + (lang === "en" ? " on" : ""), "aria-pressed": lang === "en" ? "true" : "false"}, t("desk.send.lang." + lang));
      chip.addEventListener("click", () => { state.lang = lang; langChips.forEach((item, at) => { const on = ["en", "zh"][at] === lang; item.classList.toggle("on", on); item.setAttribute("aria-pressed", on ? "true" : "false"); }); refresh(); });
      return chip;
    });
    const view = SERVE.dialog([h("h2", null, t("board.new.title")), blocked, typeof READYBAR !== "undefined" ? READYBAR.vsNote() : null,
      h("div", {class: "new-split"},
        h("div", {class: "new-form"},
          h("div", {class: "new-grid"}, field(t("board.new.name"), name), field(t("board.new.kind"), kind)),
          field(t("board.new.source"), source), h("p", {class: "sub"}, t("board.new.source.hint")),
          h("div", {class: "new-field"}, h("span", {class: "sub label"}, t("board.new.kb")), kbBox),
          h("div", {class: "new-field"}, h("span", {class: "sub label"}, t("board.new.links")), links, linkKinds, h("p", {class: "sub"}, t("board.new.links.hint")), smallNote),
          field(t("board.new.text"), text), h("div", {class: "new-files"}, files.attach, files.picker, files.tray),
          h("div", {class: "new-grid models"}, field(t("board.new.model"), model, "new-model"), field(t("board.new.thinking"), thinking), roomField, field(t("board.new.lang"), h("div", {class: "chips"}, langChips), "new-lang")),
          h("label", {class: "new-grill"}, grill, h("span", null, t("board.new.grill"))), h("p", {class: "sub"}, t("board.new.fixed"))),
        h("div", {class: "new-side"}, h("div", {class: "sub label"}, t("board.new.first")), h("p", {class: "sub"}, t("board.new.first.hint")), preview)),  // beside the fields, so a low window need not scroll to read it
      h("div", {class: "new-actions"}, problem, said, h("div", {class: "row send-actions"}, go, no))]);  // the bar stays in view: the reason the button is dim is read there, not below the long message
    view.box.classList.add("new-wide");
    files.zone(view.box);
    const body = (step) => ({step, name: name.value.trim(), kind: kind.value, source: source.value, text: grill.checked ? text.value.trimEnd() + "\n\nFirst use the skill generic-grill-me: ask me what is unclear." : text.value, model: model.value, thinking: thinking.value, context: sizes.chosen(), lang: state.lang, domains: Array.from(state.domains), links: links.value});
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
    const sync = () => { go.disabled = state.busy || !state.ready || files.reading(); };
    function levels() {
      const found = state.models.find((item) => item.id === model.value);
      const list = (found && found.thinking && found.thinking.levels) || [];
      thinking.replaceChildren(h("option", {value: ""}, t("board.new.thinking.default")), ...list.map((level) => h("option", {value: level}, thinkingLabel(level, found))));
      thinking.disabled = !list.length;
    }
    const keepPick = () => remember({id: model.value, thinking: thinking.value, context: sizes.chosen()});
    function refresh() {
      small();
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
    const close = () => { clearTimeout(state.timer); waiting = null; view.close(); };
    no.addEventListener("click", close);
    if (preset && preset.back) {
      const back = h("button", {type: "button", class: "act"}, t("dock.back"));
      back.addEventListener("click", () => { close(); preset.back(); });
      no.before(back);
    }
    for (const control of [name, text, links]) control.addEventListener("input", refresh);
    for (const control of [kind, source, thinking]) control.addEventListener("change", refresh);
    model.addEventListener("change", () => { levels(); sizes.fill(state.models.find((item) => item.id === model.value), ""); keepPick(); refresh(); });
    thinking.addEventListener("change", keepPick);
    room.addEventListener("change", keepPick);
    go.addEventListener("click", () => {
      state.busy = true; go.textContent = t("board.new.working"); sync(); said.replaceChildren();
      ask("/api/create", {...body("act"), attachments: files.list()}).then((found) => {
        clearTimeout(state.timer);
        const done = h("button", {type: "button", class: "act hot"}, t("board.new.close"));
        done.addEventListener("click", () => { close(); SERVE.done(); });
        const line = h("p", null, t("board.new.done"));
        const buttons = h("div", {class: "row send-actions"}, done);
        view.box.replaceChildren(...[h("h2", null, t("board.new.title") + " \u00b7 " + found.name), line,
          found.warn ? h("p", {class: "bad"}, found.warn) : found.unchecked ? h("p", {class: "sub"}, t("board.new.done.unchecked")) : null, buttons].filter(Boolean));
        view.inform();  // only a notice now: the board behind it keeps refreshing and brings the task in
        waiting = {name: found.name, line, row: buttons};
        done.focus();
      }, (error) => { state.busy = false; go.textContent = t("board.new.go"); sync(); said.replaceChildren(...SERVE.reasons(shown(error))); });
    });
    ask("/api/create", {step: "options"}).then((found) => {
      state.options = found; state.models = found.models || [];
      kind.replaceChildren(...found.kinds.map((item) => h("option", {value: item, selected: item === "dev" ? "" : null}, t("task.kind." + item))));
      source.replaceChildren(h("option", {value: ""}, t("board.new.source.none")), ...found.sources.map((item) => h("option", {value: item.name}, item.name + (item.kind ? " \u00b7 " + t("task.kind." + item.kind) : "") + (item.status === "closed" ? " \u00b7 " + t("board.filter.closed") : ""))));
      model.replaceChildren(h("option", {value: ""}, t("board.new.model.chat")), ...state.models.map((item) => h("option", {value: item.id}, item.name)));
      const last = remembered();  // a task's chat starts on the model last picked for a task, not on Copilot Fusion (1.6.101)
      if (last && state.models.some((item) => item.id === last.id)) model.value = last.id;
      state.domainList = Array.isArray(found.domains) ? found.domains : [];
      state.linkTypes = Array.isArray(found.link_types) ? found.link_types : [];
      if (state.linkTypes.length) links.placeholder = state.linkTypes.slice(0, 2).map((one) => one.type + ":" + (one.example || "id")).join(" ");  // a sample of a type that is really there (F1 L6)
      for (const one of state.linkTypes) {  // a click puts the type in, ready for the number
        const chip = h("button", {type: "button", class: "chip", title: (one.label || one.type) + " \u00b7 " + one.toolpack}, one.type + ":");
        chip.addEventListener("click", () => { links.value = (links.value.trim() ? links.value.trim() + " " : "") + one.type + ":"; links.focus(); refresh(); });
        linkKinds.append(chip);
      }
      drawKb();
      levels();
      if (last && model.value === last.id && [...thinking.options].some((option) => option.value === last.thinking)) thinking.value = last.thinking;
      sizes.fill(state.models.find((item) => item.id === model.value), last && model.value === last.id ? last.context : "");
      const filled = preset === true ? (found.sample && found.sample.name ? {...found.sample, note: t("board.new.sample")} : null) : preset;
      if (filled) {
        if (filled.name) name.value = filled.name;
        if (filled.kind) kind.value = filled.kind;
        for (const domain of filled.domains || []) {  // a domain that has no folder yet is offered here too: a `kb` task may learn it
          const same = state.domainList.find((item) => item.toLowerCase() === domain.toLowerCase());
          if (!same) state.domainList.push(domain);
          state.domains.add(same || domain);
        }
        drawKb();
        text.value = filled.text || "";
        if (filled.note) blocked.after(h("p", {class: "sub"}, filled.note));
      }
      if (!found.ready) blocked.replaceChildren(h("p", null, t("board.new.off")), h("p", {class: "sub"}, t("board.vs.why." + (found.why || "starting"))));
      refresh();
    }, (error) => { blocked.replaceChildren(h("p", null, t("board.new.options", {error: shown(error)}))); });
    levels();
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
    const typed = {};  // what the person wrote under a list of options
    const ready = () => { send.disabled = found.questions.some((item) => item.required && !(typed[item.id] || "").trim() && (values[item.id] === undefined || values[item.id] === "" || (Array.isArray(values[item.id]) && !values[item.id].length))); };
    const freeBox = (item) => {
      if (!item.free) return null;
      const input = h("input", {type: "text", class: "send-body ask-free", maxlength: 2000, placeholder: t("board.ask.free"), "aria-label": t("board.ask.free")});
      input.addEventListener("input", () => { typed[item.id] = input.value; ready(); });
      return input;
    };
    const control = (item) => {
      const name = "q-" + item.id;
      if (item.kind === "single-select" || item.kind === "boolean") {
        const list = item.kind === "boolean" ? [{id: "yes", label: t("board.ask.yes")}, {id: "no", label: t("board.ask.no")}] : item.options;
        return h("div", {class: "ask-options"}, list.map((option) => {
          const box = h("input", {type: "radio", name});
          box.addEventListener("change", () => { values[item.id] = item.kind === "boolean" ? option.id === "yes" : option.id; ready(); });
          return h("label", {class: "ask-option"}, box, " " + option.label);
        }), freeBox(item));
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
        }), freeBox(item));
      }
      const number = item.kind === "number" || item.kind === "integer";
      const input = number ? h("input", {type: "number", class: "send-body", step: item.kind === "integer" ? "1" : "any"}) : h("textarea", {rows: 3, class: "send-body", maxlength: 2000});
      input.addEventListener("input", () => { values[item.id] = number ? (input.value === "" ? undefined : Number(input.value)) : input.value; ready(); });
      return input;
    };
    const fields = found.questions.map((item) => h("div", {class: "ask-field"}, h("div", {class: "sub label"}, item.title + (item.required ? " *" : "")),
      item.message && item.message !== item.title ? h("div", {class: "sub ask-text"}, item.message) : null, control(item)));
    const words = found.text || found.message;  // all the agent said, with its line breaks (1.6.102); `message` is the one line of a card
    const view = SERVE.dialog([h("h2", null, actionTitle("question") + " \u00b7 " + row.name), words ? h("div", {class: "ask-text ask-lead"}, words) : null, ...fields,
      found.count > 1 ? h("p", {class: "sub"}, t("board.ask.more", {count: found.count - 1})) : null, h("div", {class: "row send-actions"}, send, no), said]);
    ready();
    send.addEventListener("click", () => {
      send.disabled = true; send.textContent = t("board.serve.working");
      const answers = {};
      for (const [key, value] of Object.entries(values)) if (value !== undefined) answers[key] = value;
      for (const [key, text] of Object.entries(typed)) if (text.trim()) answers[key] = {value: values[key], free: text};
      ask("/api/answer", {task: row.name, id: found.id, request_id: found.request_id, digest: found.digest, answers}).then(() => { view.close(); SERVE.done(); },
        (error) => { send.textContent = t("board.ask.send"); ready(); said.replaceChildren(...SERVE.reasons(shown(error))); });
    });
    no.addEventListener("click", view.close);
  }

  return {panel, stop, withdraw, create, seen, confirm, question, fileTray, modelPick};
})();
