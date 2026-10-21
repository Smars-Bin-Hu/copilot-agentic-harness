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

  function post(path, body) {
    return fetch(path, {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json", "X-Harness-Board": "1"}, body: JSON.stringify(body)})
      .then((response) => response.json().then((data) => (response.ok ? data : Promise.reject(new Error(data.error || response.status)))),
        () => Promise.reject(new Error(t("board.serve.stopped"))));
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

  function failed(error) {
    const close = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
    const view = dialog([h("div", {class: "bad"}, reasons(error.message || error)), close]);
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
    const go = h("button", {class: "act hot", type: "button"}, t("board.close.go"));
    const no = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
    const view = dialog([h("h2", null, t("board.close.title", {name: row.name})), h("p", null, t("board.close.warn")), row.state === "quiet" ? h("p", {class: "bad"}, t("board.close.quiet")) : null, row.todo_left ? h("p", {class: "bad"}, t("board.close.todo", {count: row.todo_left})) : null, h("div", {class: "row"}, go, no), said]);
    no.addEventListener("click", view.close);
    go.addEventListener("click", () => {
      go.disabled = true;
      post("/api/close", {task: row.name}).then(() => { view.close(); done(); },
        (error) => { said.replaceChildren(...reasons(error.message)); go.disabled = false; });
    });
  }

  function act(button, row, item) {
    if (item.action === "close") return close(row);
    if (item.action === "archive") return archive([row.name], serve.archive_to);
    const body = {action: item.action, task: row.name};
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
      const view = dialog([h("h2", null, button.dataset.label + " · " + row.name), ...data.result.screen.map((line) => h("p", {class: "sub"}, line)),
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

  // Once per page: trade the pairing code of the address for a cookie, and ask whether this browser is paired.
  let paired = null;
  const banners = [];
  function showPaired() {
    for (const node of banners) {
      node.textContent = paired === null ? "" : t(paired ? "board.serve.paired" : "board.serve.unpaired");
      node.classList.toggle("good", paired === true);
    }
  }
  const ready = (function () {
    const code = location.hash.startsWith("#pair=") ? decodeURIComponent(location.hash.slice(6)) : "";
    if (code) history.replaceState(null, "", location.pathname);  // the code leaves the address bar and the history
    // A browser that has the cookie of an earlier pairing does not need the code again: a second tab, a tab the browser restored
    // or loaded twice would otherwise find the code used up and say so.
    const already = post("/api/status", {}).then((data) => data.paired, () => false);
    return already.then((yes) => (code && !yes ? post("/api/pair", {code}).catch(failed) : null))
      .then(() => post("/api/status", {})).then((data) => { paired = data.paired; showPaired(); }, () => { paired = false; showPaired(); });
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

  return {runs: (action) => serve.actions.includes(action), act, archive, start, banner, post, ready, busy: () => busy, onChange: (call) => { after = call; }};
})();
