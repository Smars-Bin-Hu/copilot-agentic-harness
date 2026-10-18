// Only in the page `task board --serve` sends (never in the files on disk): the buttons that act, and the pairing.
// DATA.serve.actions run from the page; the other buttons stay copy buttons. Pause and resume act at once. An
// approval shows what the terminal would show and asks for its code. The pairing code comes in the address
// (#pair=...), is traded for a cookie and taken out of the address bar. Every request goes to this server only.
"use strict";

const SERVE = (function () {
  const serve = DATA.serve;
  const free = (action) => action === "pause" || action === "resume";
  let busy = false;

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

  function act(button, row, item) {
    const body = {action: item.action, task: row.name};
    if (free(item.action)) {
      button.textContent = t("board.serve.working");
      post("/api/act", {...body, step: "act"}).then(() => location.reload(), (error) => { button.textContent = button.dataset.label; failed(error); });
      return;
    }
    post("/api/act", {...body, step: "preview"}).then((data) => {
      const input = h("input", {class: "code", autocomplete: "off", spellcheck: "false", placeholder: t("board.serve.code")});
      const yes = h("button", {class: "act hot", type: "button"}, t("board.serve.confirm"));
      const no = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
      const said = h("div", {class: "bad"});
      const view = dialog([h("h2", null, button.dataset.label + " · " + row.name), ...data.result.screen.map((line) => h("p", {class: "sub"}, line)),
        h("p", null, data.result.ask), input, h("div", {class: "row"}, yes, no), said]);
      no.addEventListener("click", view.close);
      const send = () => {
        yes.disabled = true;
        post("/api/act", {...body, step: "act", code: input.value.trim()}).then(() => { view.close(); location.reload(); },
          (error) => { said.replaceChildren(...reasons(error.message)); yes.disabled = false; });
      };
      yes.addEventListener("click", send);
      input.addEventListener("keydown", (event) => { if (event.key === "Enter") send(); });
      input.focus();
    }, failed);
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
    return (code ? post("/api/pair", {code}).catch(failed) : Promise.resolve())
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

  return {runs: (action) => serve.actions.includes(action), act, start, banner, post, ready, busy: () => busy};
})();
