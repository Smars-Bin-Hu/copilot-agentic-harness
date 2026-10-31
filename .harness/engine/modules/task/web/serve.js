// Only in the page `task board --serve` sends (never in the files on disk): the buttons that act, and the pairing.
// DATA.serve.actions run from the page; the other buttons stay copy buttons. Pause and resume act at once. An
// approval shows what the terminal would show and asks for its code. The pairing code comes in the address
// (#pair=...), is traded for a cookie and taken out of the address bar. Every request goes to this server only.
"use strict";

const SERVE = (function () {
  const serve = DATA.serve;
  const free = (action) => action === "pause" || action === "resume";
  let busy = false;
  // After an action the page asks the server again and draws what changed (the board registers how); a page without that reloads. A reload would draw the
  // board from nothing, so no robot would slide or spring: an action is the very moment the person wants to see the change.
  let after = null;
  const done = () => (after ? after() : location.reload());

  // One place for a refusal of an unpaired browser: a bar at the top of the page, on the board and on a task page. A click closes it.
  function unpairedNote() {
    if (document.querySelector(".unpaired-note")) return;
    const bar = h("div", {class: "unpaired-note", role: "alert", title: t("board.serve.cancel")}, t("board.serve.notpaired"));
    bar.addEventListener("click", () => bar.remove());
    document.body.append(bar);
  }

  let reloading = false;

  function post(path, body) {
    return fetch(path, {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json", "X-Harness-Board": "1"}, body: JSON.stringify(body)})
      .then((response) => response.json().then((data) => {
        if (response.ok) {
          // The language was changed while the page was open: its texts are the old ones, so the page is loaded again (once: the address is the same, the server now sends the new ones).
          if (data.language && data.language !== document.documentElement.lang && !reloading) { reloading = true; location.reload(); }
          return data;
        }
        if (data.unpaired) unpairedNote();  // the server says it: a button that does nothing would be worse
        return Promise.reject(Object.assign(new Error(data.error || response.status), {data}));  // `data.fallback`: the text to copy when a send was refused
      }),
        () => Promise.reject(Object.assign(new Error(t("board.serve.stopped")), {offline: true})));  // offline: no answer at all (not a refusal); pollEvery counts these
  }

  function dialog(children) {
    busy = true;
    const box = h("div", {class: "dialog card"}, children);
    const shade = h("div", {class: "shade"}, box);
    document.body.append(shade);
    return {box, close: () => { shade.remove(); busy = false; }};
  }

  // A refusal may list reasons, one "- reason" a line: the lines are drawn as lines, not run together.
  function reasons(text) {
    const out = [];
    let list = null;
    for (const line of String(text).split("\n")) {
      if (!line.trim()) continue;
      const item = line.match(/^\s*[-\u2013\u2022]\s+(.*)$/);
      if (item) {
        if (!list) { list = h("ul", {class: "reasons"}); out.push(list); }
        list.append(h("li", null, item[1]));
      } else {
        list = null;
        out.push(h("p", null, line.trim()));
      }
    }
    return out;
  }

  // `title`: the chat's title, given where the person has to find a chat by hand (the VS button): a button copies it.
  function failed(error, title) {
    const close = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
    const copy = title ? h("button", {class: "act", type: "button", "data-label": t("desk.chat.copy")}, t("desk.chat.copy")) : null;
    if (copy) copy.addEventListener("click", () => copyCommand(copy, title));
    const view = dialog([h("div", {class: "bad"}, reasons(error.message || error)), title ? h("p", {class: "sub"}, t("desk.chat.copy.hint")) : null, h("div", {class: "row"}, copy, close)]);
    close.addEventListener("click", view.close);
  }

  // Archive closed tasks: the folder (the one kept, or a path to type), what would move, then the move. One way: the dialog says so.
  function archive(names, keptFolder) {
    const to = h("input", {class: "code", autocomplete: "off", spellcheck: "false", placeholder: t("board.archive.to"), value: keptFolder || ""});
    const remember = h("input", {type: "checkbox"});
    remember.checked = !keptFolder;
    const said = h("div", {class: "bad"});
    const plan = h("div", {class: "plan"});
    const check = h("button", {class: "act", type: "button"}, t("board.archive.check"));
    const go = h("button", {class: "act hot", type: "button", disabled: "disabled"}, t("board.archive.go", {count: names.length}));
    const no = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
    const view = dialog([h("h2", null, t("board.archive.title", {count: names.length})), h("p", null, t("board.archive.warn")),
      h("p", {class: "sub"}, names.join(", ")), to, h("label", {class: "sub remember"}, remember, " " + t("board.archive.remember")), plan,
      h("div", {class: "row"}, check, go, no), said]);
    const body = (step) => ({tasks: names, to: to.value.trim(), remember: remember.checked, step});
    const sync = () => { check.disabled = !to.value.trim(); };  // nothing to look at before a folder is typed
    sync();
    to.addEventListener("input", () => { sync(); go.disabled = true; plan.replaceChildren(); said.replaceChildren(); });  // a new folder needs a new look
    no.addEventListener("click", view.close);
    check.addEventListener("click", () => {
      said.replaceChildren();
      if (!to.value.trim()) { said.replaceChildren(h("p", null, t("board.archive.need"))); return; }
      post("/api/archive", body("preview")).then((data) => {
        const found = data.result;
        plan.replaceChildren(h("p", null, t("board.archive.folder", {to: found.to}) + (found.folder_exists ? "" : " " + t("board.archive.new"))),
          h("ul", {class: "reasons"}, found.would_move.map((item) => h("li", null, item.name + " \u2192 " + item.to))));
        go.disabled = false;
      }, (error) => { plan.replaceChildren(); go.disabled = true; said.replaceChildren(...reasons(error.message)); });
    });
    go.addEventListener("click", () => {
      go.disabled = true;
      post("/api/archive", body("act")).then(() => { view.close(); done(); },
        (error) => { said.replaceChildren(...reasons(error.message)); go.disabled = false; });
    });
    to.focus();
    if (!to.value.trim()) said.replaceChildren(h("p", {class: "sub"}, t("board.archive.need")));
  }

  // Close a task: one confirm. It writes the report and lets the session go; the folder stays, and `task open` opens it again.
  function close(row) {
    const said = h("div", {class: "bad"});
    const reason = h("input", {type: "text", class: "code", maxlength: 500, autocomplete: "off", placeholder: t("board.close.reason.ph")});
    const go = h("button", {class: "act hot", type: "button"}, t("board.close.go"));
    const no = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
    const view = dialog([h("h2", null, t("board.close.title", {name: row.name})), h("p", null, t("board.close.warn")), row.state === "quiet" ? h("p", {class: "bad"}, t("board.close.quiet")) : null, row.todo_left ? h("p", {class: "bad"}, t("board.close.todo", {count: row.todo_left})) : null, row.result_missing ? h("p", {class: "bad"}, t("board.close.result", {file: row.result_missing})) : null,
      h("label", {class: "sub"}, t("board.close.reason")), reason, h("div", {class: "row"}, go, no), said]);
    no.addEventListener("click", view.close);
    go.addEventListener("click", () => {
      go.disabled = true;
      post("/api/close", {task: row.name, reason: reason.value.trim()}).then(() => { view.close(); done(); },
        (error) => { said.replaceChildren(...reasons(error.message)); go.disabled = false; });
    });
  }

  function act(button, row, item, withReq) {
    if (item.action === "send" || item.action === "answer") return CHAT.panel(row, item.action);  // chat.js: the panel that shows the message, then sends it
    if (item.action === "confirm") return CHAT.confirm(row);  // the chat waits for a tool to be allowed (B75)
    if (item.action === "question") return CHAT.question(row);
    if (item.action === "steer") return CHAT.steer(row);
    if (item.action === "stop") return CHAT.stop(row);
    if (item.action === "close") return close(row);
    if (item.action === "archive") return archive([row.name], serve.archive_to);
    // A plan stands on a confirmed requirement: the plan alone is refused, and one code can confirm the requirement and approve the plan.
    if (item.action === "approve-plan" && row.req_unconfirmed && !withReq) {
      const go = h("button", {class: "act hot", type: "button"}, t("board.plan.req.go"));
      const no = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
      const view = dialog([h("h2", null, t("board.plan.req.title")), h("p", null, t("board.plan.req")), h("div", {class: "row"}, go, no)]);
      no.addEventListener("click", view.close);
      go.addEventListener("click", () => { view.close(); act(button, row, item, true); });
      return;
    }
    const body = {action: item.action, task: row.name, ...(withReq ? {with_req: true} : {})};
    if (free(item.action)) {
      button.textContent = t("board.serve.working");
      post("/api/act", {...body, step: "act"}).then(done, (error) => { button.textContent = button.dataset.label; failed(error); });
      return;
    }
    // The preview works the plan out (git on every repository): it can take long. The button says so, and the page keeps still meanwhile.
    busy = true;
    button.disabled = true;
    button.textContent = t("board.serve.working");
    const back = () => { busy = false; button.disabled = false; button.textContent = button.dataset.label; };
    post("/api/act", {...body, step: "preview"}).then((data) => {
      back();
      const input = h("input", {class: "code", autocomplete: "off", spellcheck: "false", placeholder: t("board.serve.code")});
      const yes = h("button", {class: "act hot", type: "button"}, t("board.serve.confirm"));
      const no = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
      const said = h("div", {class: "bad"});
      // What the terminal would show can be long (a promote lists every file): it scrolls in its own box, so the code and the buttons stay in view.
      const view = dialog([h("h2", null, button.dataset.label + " · " + row.name), h("div", {class: "screen"}, data.result.screen.map((line) => h("p", {class: "sub"}, line))),
        h("p", null, data.result.ask), input, h("div", {class: "row"}, yes, no), said]);
      no.addEventListener("click", view.close);
      const send = () => {
        yes.disabled = true;
        yes.textContent = t("board.serve.working");
        post("/api/act", {...body, step: "act", code: input.value.trim()}).then(() => { view.close(); done(); },
          (error) => { said.replaceChildren(...reasons(error.message)); yes.disabled = false; yes.textContent = t("board.serve.confirm"); });
      };
      yes.addEventListener("click", send);
      input.addEventListener("keydown", (event) => { if (event.key === "Enter") send(); });
      input.focus();
    }).catch((error) => { back(); failed(error); });  // an error while drawing the dialog is told too, not lost
  }

  // The button that brings the VS Code window of this folder forward (the server runs `code <folder>`; no link to one chat exists). It shows only the logo; the words are its title and label.
  // It can be pressed while VS Code is not linked (the command then opens the window). Grey only when no `code` command is found (or the link is switched off). `chat` is row.chat or desk.chat.
  const VS_LOGO = "M23.15 2.587L18.21.21a1.494 1.494 0 0 0-1.705.29l-9.46 8.63-4.12-3.128a.999.999 0 0 0-1.276.057L.327 7.261A1 1 0 0 0 .326 8.74L3.899 12 .326 15.26a1 1 0 0 0 .001 1.479L1.65 17.94a.999.999 0 0 0 1.276.057l4.12-3.128 9.46 8.63a1.492 1.492 0 0 0 1.704.29l4.942-2.377A1.5 1.5 0 0 0 24 20.06V3.939a1.5 1.5 0 0 0-.85-1.352zm-5.146 14.861L10.826 12l7.178-5.448v10.896z";
  function vsLogo() {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", VS_LOGO);
    path.setAttribute("fill", "#2489ca");
    svg.append(path);
    return svg;
  }
  function vsButton(chat) {
    const why = chat && !chat.bound ? chat.why || "" : "";
    const nothing = why === "no-cli" || why === "off";
    const button = h("button", {type: "button", class: "vs-btn", disabled: nothing ? "disabled" : null, title: nothing ? t("board.vs.why." + why) : t("board.vs.open"), "aria-label": t("board.vs.open")}, vsLogo());
    button.addEventListener("click", () => {
      button.disabled = true;
      post("/api/open", {}).then(() => { setTimeout(() => { button.disabled = false; }, 1500); }, (error) => { button.disabled = false; failed(error, chat && chat.title); });
    });
    return button;
  }

  // Once per page: trade the pairing code of the address for a cookie, and ask whether this browser is paired.
  let paired = null;
  let stale = null;  // the board was started on an older release than the files now hold: it still runs the old code
  const banners = [];
  function showPaired() {
    for (const node of banners) {
      node.replaceChildren(paired === null ? "" : t(paired ? "board.serve.paired" : "board.serve.unpaired"),
        stale ? h("span", {class: "bad"}, " " + t("board.serve.stale", stale)) : "");
      node.classList.toggle("good", paired === true && !stale);
    }
  }
  const note = (data) => { stale = data.started && data.now && data.started !== data.now ? {started: data.started, now: data.now} : null; return data; };
  const ready = (function () {
    const code = location.hash.startsWith("#pair=") ? decodeURIComponent(location.hash.slice(6)) : "";
    if (code) history.replaceState(null, "", location.pathname);  // the code leaves the address bar and the history
    // A browser that has the cookie of an earlier pairing does not need the code again: a second tab, a tab the browser restored
    // or loaded twice would otherwise find the code used up and say so.
    const already = post("/api/status", {}).then((data) => data.paired, () => false);
    return already.then((yes) => (code && !yes ? post("/api/pair", {code}).catch(failed) : null))
      .then(() => post("/api/status", {})).then((data) => { paired = note(data).paired; showPaired(); }, () => { paired = false; showPaired(); });
  })();

  // A line that says whether this browser may approve; it stays right when the page is drawn again.
  function banner() {
    const node = h("div", {class: "sub pairing"});
    banners.splice(0, banners.length, ...banners.filter((item) => item.isConnected), node);
    showPaired();
    return node;
  }

  // The board: the line under the numbers. The board asks for its rows itself (board.js) and keeps what the person typed.
  function start(app) {
    const kpis = app.querySelector(".kpis");
    if (kpis) kpis.after(banner());
  }

  return {runs: (action) => serve.actions.includes(action), act, archive, start, banner, post, vsButton, ready, dialog, reasons, failed, done, busy: () => busy, onChange: (call) => { after = call; }};
})();
