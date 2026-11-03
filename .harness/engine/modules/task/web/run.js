// The two buttons of a shell code block on the task page (1.6.50), and the panel of a running command.
// "Ask agent" sends the command to the task's chat: the gate and the confirmations hold, and the agent sees the output. "Run" is the person's own run: the board starts it, the gate does not see it (taskrun.py).
// Needs common.js (h, t), serve.js (SERVE). Drawn with DOM nodes and textContent only.
const Run = (function () {
  const POLL_MS = 600;
  const MAX_SHOWN = 200000;  // characters kept in the panel; the whole output is in the task folder
  let panel = null;

  const offered = (kind) => Boolean(DATA.serve && (DATA.serve.run_kinds || []).includes(kind));

  function askRun(task, text) {
    const go = h("button", {type: "button", class: "act hot"}, t("desk.run.go"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const said = h("div", {class: "bad"});
    const view = SERVE.dialog([h("h2", null, t("desk.run.title")), h("pre", {class: "send-preview"}, text), h("p", {class: "sub"}, t("desk.run.where", {task})), h("p", {class: "bad"}, t("desk.run.warn")), said, h("div", {class: "row"}, go, no)]);
    no.addEventListener("click", view.close);
    go.addEventListener("click", () => {
      go.disabled = true;
      SERVE.post("/api/run", {op: "start", task, command: text}).then((data) => { view.close(); open(task, data.result); },
        (error) => { go.disabled = false; said.replaceChildren(...SERVE.reasons(error.message || error)); });
    });
  }

  // `done`: what the page does once the message went (it opens Live).
  function askAgent(task, text, done) {
    const go = h("button", {type: "button", class: "act hot", disabled: "disabled"}, t("desk.run.ask.go"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const preview = h("pre", {class: "send-preview"}, "...");
    const said = h("div", {class: "bad"});
    const pick = typeof CHAT !== "undefined" ? CHAT.modelPick(task) : null;  // 1.6.101
    const view = SERVE.dialog([h("h2", null, t("desk.run.ask.title")), preview, h("p", {class: "sub"}, t("desk.run.ask.note")), pick ? pick.node : null, said, h("div", {class: "row"}, go, no)]);
    const body = (step) => ({task, kind: "command", body: text, lang: "", note: "", step});
    no.addEventListener("click", view.close);
    SERVE.post("/api/send", body("preview")).then((data) => {
      preview.textContent = data.result.text;
      if (data.result.blocked) said.replaceChildren(...SERVE.reasons(data.result.blocked));
      go.disabled = Boolean(data.result.blocked);
    }, (error) => { preview.textContent = ""; said.replaceChildren(...SERVE.reasons(error.message || error)); });
    go.addEventListener("click", () => {
      go.disabled = true;
      (pick ? pick.apply() : Promise.resolve()).then(() => SERVE.post("/api/send", body("act"))).then(() => { view.close(); SERVE.done(); if (done) done(); },
        (error) => { said.replaceChildren(...SERVE.reasons(error.message || error)); });
    });
  }

  function buttons(task, text, kind, done) {
    if (!offered(kind)) return [];
    const ask = h("button", {type: "button", class: "act copy-code run-ask", title: t("desk.run.ask.hint")}, t("desk.run.ask"));
    const run = h("button", {type: "button", class: "act copy-code run-go", title: t("desk.run.hint")}, "▶ " + t("desk.run"));
    ask.addEventListener("click", () => askAgent(task, text, done));
    run.addEventListener("click", () => askRun(task, text));
    return [ask, run];
  }

  function open(task, found) {
    if (panel) panel.remove();
    const state = h("span", {class: "run-state"});
    const out = h("pre", {class: "run-out"});
    const foot = h("div", {class: "run-foot sub"});
    const stop = h("button", {type: "button", class: "act"}, t("desk.run.stop"));
    const close = h("button", {type: "button", class: "act", hidden: "hidden"}, t("desk.run.close"));
    const box = h("section", {class: "run-panel card", "aria-label": t("desk.run")}, h("div", {class: "run-head"}, h("code", {class: "run-cmd", title: found.command}, found.command), state, stop, close), out, foot);
    document.body.append(box);
    panel = box;
    let since = 0, gone = false;
    const paint = (data) => {
      if (data.skipped) out.append(t("desk.run.skipped") + "\n");
      if (data.text) {
        const near = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
        out.append(data.text);
        if (out.textContent.length > MAX_SHOWN) out.textContent = out.textContent.slice(-MAX_SHOWN);
        if (near) out.scrollTop = out.scrollHeight;
      }
      since = data.next;
      const running = data.state === "running";
      state.textContent = running ? t("desk.run.running") : data.state === "stopped" ? t("desk.run.stopped") : t("desk.run.ended", {code: data.code === null ? "-" : data.code});
      state.className = "run-state " + (running ? "good" : data.code === 0 ? "" : "bad");
      stop.hidden = !running;
      close.hidden = running;
      if (!running && !data.more) foot.textContent = t("desk.run.saved", {folder: data.folder}) + (data.cut ? " " + t("desk.run.cut") : "") + (data.error ? " " + data.error : "");
      return running || data.more;
    };
    const tick = () => {
      if (gone) return;
      SERVE.post("/api/run", {op: "read", id: found.id, since}).then((data) => { if (paint(data.result)) setTimeout(tick, data.result.more ? 50 : POLL_MS); },
        (error) => { foot.textContent = error.message || String(error); if (error.offline) setTimeout(tick, POLL_MS * 5); });
    };
    stop.addEventListener("click", () => { stop.disabled = true; SERVE.post("/api/run", {op: "stop", id: found.id}).catch((error) => { stop.disabled = false; foot.textContent = error.message || String(error); }); });
    close.addEventListener("click", () => { gone = true; box.remove(); if (panel === box) panel = null; });
    paint({...found, text: "", more: false});
    tick();
  }

  // A page opened or loaded again while a command runs: it takes the panel back.
  function attach(task) {
    SERVE.post("/api/run", {op: "latest", task}).then((data) => { if (data.result.run && !panel) open(task, data.result.run); }, () => {});
  }

  return {buttons, attach};
})();
