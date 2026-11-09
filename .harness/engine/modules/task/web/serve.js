// Only in the page `task board --serve` sends (never in the files on disk): the buttons that act, and the pairing.
// DATA.serve.actions run from the page; the other buttons stay copy buttons. Pause and resume act at once. An
// approval shows what the terminal would show and asks for its code. The pairing code comes in the address
// (#pair=...), is traded for a cookie and taken out of the address bar. Every request goes to this server only.
"use strict";

const SERVE = (function () {
  const serve = DATA.serve;
  const free = (action) => action === "pause" || action === "resume" || action === "accept";  // no code, no preview: accept closes the task the agent delivered (1.7.38)
  let busy = false;
  const stack = [];  // the windows open now, the top one last
  const quiet = new Set();  // the windows that only tell something: the page under them keeps refreshing (`busy` is false), but keys still wait for them (`open`)
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
  // A page that shows work in progress asks to stay (1.7.38): the Get ready form writes the language first and goes on for a while, and a reload then lost the work it was showing.
  // `keep()` says whether it still asks. The page that changes the language itself (the settings panel) passes `now`: that one reloads.
  const keepers = [];
  const stay = (keep) => { keepers.push(keep); };

  // Every call of the page waits for the pairing of this load: asked before it, a paired browser would be refused and told it is not paired.
  const post = (path, body, now) => ready.then(() => send(path, body, now));

  function send(path, body, now) {
    return fetch(path, {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json", "X-Harness-Board": "1"}, body: JSON.stringify(body)})
      .then((response) => response.json().then((data) => {
        if (response.ok) {
          // The language was changed while the page was open: its texts are the old ones, so the page is loaded again (once: the address is the same, the server now sends the new ones).
          if (data.language && data.language !== document.documentElement.lang && !reloading && (now || !keepers.some((keep) => keep()))) { reloading = true; location.reload(); }
          return data;
        }
        if (data.unpaired) unpairedNote();  // the server says it: a button that does nothing would be worse
        return Promise.reject(Object.assign(new Error(data.error || response.status), {data}));  // `data.fallback`: the text to copy when a send was refused
      }),
        () => Promise.reject(Object.assign(new Error(t("board.serve.stopped")), {offline: true})));  // offline: no answer at all (not a refusal); pollEvery counts these
  }

  // A POST with a deadline and nothing else: no bar for an unpaired browser, no reload. The Enter screen asks with it: a stalled server is an error line there, never a hang.
  function call(path, body, seconds) {
    const control = window.AbortController ? new AbortController() : null;
    const timer = setTimeout(() => control && control.abort(), (seconds || 8) * 1000);
    const failed = (error) => { clearTimeout(timer); throw new Error(error && error.name === "AbortError" ? "no answer in " + (seconds || 8) + " s" : (error && error.message) || "no answer"); };
    return fetch(path, {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json", "X-Harness-Board": "1"}, body: JSON.stringify(body || {}), signal: control ? control.signal : undefined})
      .then((response) => response.json().catch(() => ({})).then((data) => {
        clearTimeout(timer);
        if (!response.ok) throw Object.assign(new Error(data.error || "HTTP " + response.status), {status: response.status, data});
        return data;
      }), failed);
  }

  // One file of this server as a blob (the pictures of wall.js). The network stays in this script, which a page on disk does not have.
  function file(path) {
    return fetch(path, {credentials: "same-origin"}).then((response) => {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.blob();
    });
  }

  // The person's own words have one place: the reply panel of the task page. From the board the task page opens with it.
  function speak(row) {
    if (typeof REPLY !== "undefined" && REPLY.shown()) return REPLY.open();
    try { sessionStorage.setItem("harness.reply", row.name); } catch (error) { /* the page opens, the panel does not */ }
    location.href = "/task/" + encodeURIComponent(row.name);
  }

  // `informs`: the window has no field and no decision, so it does not stop the refresh of the page under it (and a refresh never redraws it).
  function dialog(children, informs) {
    const box = h("div", {class: "dialog card", tabindex: "-1"}, children);
    const shade = h("div", {class: "shade"}, box);
    const before = document.activeElement;
    document.body.append(shade);
    document.body.classList.add("has-dialog");  // the fixed buttons of the page (the terminal toggle) step back while a window is open
    stack.push(box);
    const settle = () => { busy = stack.some((item) => !quiet.has(item)); };
    if (informs) quiet.add(box);
    settle();
    const close = () => {
      if (!stack.includes(box)) return;  // a late answer may close a window the person closed already
      document.removeEventListener("keydown", onKey);
      shade.remove();
      stack.splice(stack.indexOf(box), 1);
      quiet.delete(box);
      settle();
      if (!stack.length) document.body.classList.remove("has-dialog");
      if (before && before.isConnected) before.focus({preventScroll: true});
    };
    const onKey = (event) => {
      if (stack[stack.length - 1] !== box) return;  // a window over a window: the top one answers
      if (event.key === "Tab") {  // the keys stay in the window, not on the page behind it
        const stops = [...box.querySelectorAll("a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary")].filter((node) => node.offsetParent !== null);
        const edge = stops[event.shiftKey ? 0 : stops.length - 1];
        if (!stops.length || !box.contains(document.activeElement) || document.activeElement === box || document.activeElement === edge) { event.preventDefault(); (stops[event.shiftKey ? stops.length - 1 : 0] || box).focus(); }
        return;
      }
      if (event.key !== "Escape") return;  // Esc is Cancel, as long as it would not throw away what the person typed here. A form that starts filled says so itself (`holds`)
      const typed = view.holds ? view.holds() : [...box.querySelectorAll("textarea, input:not([type=file]):not([type=checkbox]):not([type=radio])")].some((node) => node.value.trim());
      if (!typed) close();
    };
    document.addEventListener("keydown", onKey);
    shade.addEventListener("click", (event) => {  // a click beside the window is Cancel, as Esc is, as long as nothing was typed
      if (event.target !== shade) return;
      const typed = view.holds ? view.holds() : [...box.querySelectorAll("textarea, input:not([type=file]):not([type=checkbox]):not([type=radio])")].some((node) => node.value.trim());
      if (!typed) close();
    });
    (box.querySelector("input:not([type=checkbox]):not([type=radio]):not([type=file]), textarea") || box).focus({preventScroll: true});  // never a button: Enter must not act by surprise
    const view = {box, close, holds: null, inform: () => { quiet.add(box); settle(); }};  // inform: a form that turned into a plain notice (New task, once sent)
    return view;
  }

  // A refusal may list reasons, one "- reason" a line: the lines are drawn as lines, not run together.
  function reasons(text) {
    const out = [];
    let list = null;
    for (const line of plainWords(text).split("\n")) {
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
    if (error && error.quiet) return;  // the person already answered a window about it (Open VS Code, 1.7.29)
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

  // Close a task. All steps ticked: one confirm. Steps left: what the person says goes to the agent, which ticks and notes them and closes the task; or the board closes it now and keeps the words in TODO.md.
  function close(row) {
    const said = h("div", {class: "bad"});
    const steps = h("ul", {class: "sub"});
    const go = h("button", {class: "act hot", type: "button"}, t(row.todo_left ? "board.close.direct" : "board.close.go"));
    const no = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
    const words = row.todo_left ? h("textarea", {rows: 3, class: "send-body", maxlength: 500, placeholder: t("board.close.reason.ph")}) : null;
    const canTalk = Boolean(row.chat && row.chat.bound) || chatNew(row);
    const tell = row.todo_left ? h("button", {class: "act hot", type: "button", disabled: "disabled", title: canTalk ? "" : t("board.close.notalk")}, t("board.close.tell")) : null;
    if (tell) go.classList.remove("hot");
    const pick = tell && row.chat && row.chat.bound && typeof CHAT !== "undefined" ? CHAT.modelPick(row.name) : null;  // the model of the message to the agent (1.6.101); a chat still to make has its own dialog
    const view = dialog([h("h2", null, t("board.close.title", {name: row.name})), h("p", null, t("board.close.warn")), row.state === "quiet" ? h("p", {class: "bad"}, t("board.close.quiet")) : null, row.result_missing ? h("p", {class: "bad"}, t("board.close.result", {file: row.result_missing})) : null,
      row.todo_left ? [h("p", {class: "bad"}, t("board.close.todo", {count: row.todo_left})), steps, h("label", {class: "sub"}, t("board.close.reason")), words, pick ? pick.node : null] : null,
      h("div", {class: "row"}, tell, go, no), said]);
    no.addEventListener("click", view.close);
    if (row.todo_left) {
      post("/api/close", {task: row.name, step: "steps"}).then((data) => steps.replaceChildren(...data.result.left.map((text) => h("li", null, text))), () => {});
      words.addEventListener("input", () => { tell.disabled = !canTalk || !words.value.trim(); });
      tell.addEventListener("click", () => {
        const text = t("board.close.words", {task: row.name, words: words.value.trim().replace(/\s+/g, " ")});
        if (!row.chat.bound) { view.close(); return DOCK.start("harness-my-task", text, null, row.name); }
        tell.disabled = true;
        (pick ? pick.apply() : Promise.resolve()).then(() => post("/api/send", {task: row.name, kind: "answer", lang: "", note: "", body: "/harness-my-task " + text, step: "act"})).then(() => { view.close(); done(); },
          (error) => { said.replaceChildren(...reasons(error.message)); tell.disabled = false; });
      });
    }
    go.addEventListener("click", () => {
      go.disabled = true;
      post("/api/close", {task: row.name, reason: words ? words.value.trim() : ""}).then(() => { view.close(); done(); },
        (error) => { said.replaceChildren(...reasons(error.message)); go.disabled = false; });
    });
  }

  // Accept and close (1.7.38, C13 FB-4): when calls of the task still wait for the person, the page lists them first ("N calls still wait for you; closing voids them") and closes on the second yes.
  // The server asks for that yes too: an acceptance that does not carry it is refused while a call waits.
  function accept(button, row, body) {
    const work = () => { button.textContent = t("board.serve.working"); };
    const back = () => { button.textContent = button.dataset.label; };
    const close = (void_) => post("/api/act", {...body, step: "act", ...(void_ ? {void: true} : {})});
    work();
    post("/api/act", {...body, step: "preview"}).then((data) => {
      const calls = (data.result && data.result.held) || [];
      if (!calls.length) return close(false).then(done);
      back();
      const go = h("button", {class: "act hot", type: "button"}, t("board.accept.held.go"));
      const no = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
      const said = h("div", {class: "bad"});
      const view = dialog([h("h2", null, t(calls.length === 1 ? "board.accept.held.title.one" : "board.accept.held.title", {n: calls.length})), h("p", null, t("board.accept.held.warn")),
        h("ul", {class: "held-list"}, calls.map((call) => h("li", null, h("b", null, call.system + (call.env && call.env !== "none" ? " " + call.env.toUpperCase() : "")), " ", h("span", {class: "held-title"}, call.title)))),
        h("div", {class: "row"}, go, no), said]);
      no.addEventListener("click", view.close);
      go.addEventListener("click", () => {
        go.disabled = true;
        work();
        close(true).then(() => { view.close(); done(); }, (error) => { said.replaceChildren(...reasons(error.message)); go.disabled = false; back(); });
      });
    }).catch((error) => { back(); failed(error); });
  }

  function act(button, row, item, withReq) {
    if (item.action === "send") return CHAT.panel(row, item.action);  // chat.js: the panel that shows the message, then sends it
    if (item.action === "answer" || item.action === "steer") return speak(row);
    if (item.action === "confirm") return CHAT.confirm(row);  // the chat waits for a tool to be allowed (B75)
    if (item.action === "question") return CHAT.question(row);
    if (item.action === "stop") return CHAT.stop(row);
    if (item.action === "close") return close(row);
    if (item.action === "archive") return archive([row.name], serve.archive_to);
    // A plan stands on a confirmed requirement: the plan alone is refused, so one code confirms the requirement and approves the plan (1.7.38, C11 T2-11: no window of its own before the code; the window with the code says it).
    const joint = item.action === "approve-plan" && Boolean(row.req_unconfirmed);
    withReq = withReq || joint;
    const body = {action: item.action, task: row.name, ...(withReq ? {with_req: true} : {})};
    if (item.action === "accept") return accept(button, row, body);
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
      const view = dialog([h("h2", null, button.dataset.label + " · " + row.name), joint ? h("p", null, t("board.plan.req")) : null,
        joint && (row.req_sections || []).length ? h("p", {class: "bad"}, t("desk.req.unfinished", {sections: row.req_sections.join(", ")})) : null,  // the card says it; so does the window the code is typed in
        h("div", {class: "screen"}, data.result.screen.map((line) => h("p", {class: "sub"}, line))),
        h("p", null, data.result.ask), input, h("div", {class: "row"}, yes, no), said]);
      no.addEventListener("click", view.close);
      const send = () => {
        yes.disabled = true;
        yes.textContent = t("board.serve.working");
        post("/api/act", {...body, step: "act", code: input.value.trim()}).then(() => { view.close(); done(); },
          (error) => { said.replaceChildren(...reasons(error.message)); yes.disabled = false; yes.textContent = t("board.serve.confirm"); });
      };
      yes.addEventListener("click", send);
      input.addEventListener("keydown", (event) => { if (isEnter(event)) send(); });
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
  // Open VS Code. A VS Code that is already running cannot get this computer's settings (1.7.21): the server says so (409, `running`) and the person
  // may still open it (1.7.29). A window that is closed another way (Esc, a click beside it) is the safe answer: not opened. `sender`: post, or a call with a deadline.
  function openVS(sender) {
    const go = sender || post;
    return go("/api/open", {}).catch((error) => {
      if (!(error && error.data && error.data.running)) throw error;
      return new Promise((resolve, reject) => {
        const quit = h("button", {type: "button", class: "act hot live"}, t("board.vs.quit_first"));
        const anyway = h("button", {type: "button", class: "act", title: t("board.vs.anyway.tip")}, t("board.vs.anyway"));
        const view = dialog([h("h2", null, t("board.vs.running")), h("p", null, t("board.vs.running.why")), h("div", {class: "row win-foot"}, quit, anyway)]);
        let done = false;
        const end = (then) => { if (done) return; done = true; clearInterval(watch); view.close(); then(); };
        const no = () => reject(Object.assign(error, {quiet: true}));  // the person chose: no second window with the same words
        const watch = setInterval(() => { if (!view.box.isConnected) end(no); }, 300);
        quit.addEventListener("click", () => end(no));
        anyway.addEventListener("click", () => end(() => go("/api/open", {anyway: true}).then(resolve, reject)));
      });
    });
  }

  // Restart VS Code (1.7.38): the board asks VS Code to quit the normal way (a file that is not saved is asked about by VS Code itself), waits until it has gone, and opens it again the way `openVS` does. Never a kill.
  // The server says first, with 409 and `busy`, when the agent of a task is at work: the person chooses Restart anyway or Cancel. `open: false` only quits (the identities picker opens it then).
  // `onState(view)`: the state of the restart as it goes (quitting, opening, done, failed). The promise ends with `done`; `failed` is an error whose `why` is a code (`still-open`, `no-command`) or the engine's words.
  // `names`: the chats VS Code lists as running when it did not quit (`still-chat`).
  const restartWhy = (why, names) => (Object.prototype.hasOwnProperty.call(TEXT, "board.vs.restart.why." + why) ? t("board.vs.restart.why." + why, {names: (names || []).join(", ")}) : String(why || ""));
  function restartVS(options) {
    const opts = options || {};
    const go = opts.sender || post;
    const ask = (anyway) => go("/api/restart", {open: opts.open !== false, anyway: anyway || undefined});
    const follow = () => new Promise((resolve, reject) => {
      const look = () => go("/api/restart", {step: "state"}).then((data) => {
        const view = data.result || {};
        if (opts.onState) opts.onState(view);
        if (view.state === "done") resolve(view);
        else if (view.state === "failed") reject(Object.assign(new Error(restartWhy(view.why, view.names)), {why: view.why, quiet: false}));
        else setTimeout(look, 700);
      }, reject);
      look();
    });
    return ask(false).catch((error) => {
      if (!(error && error.data && error.data.busy)) throw error;
      return new Promise((resolve, reject) => {
        const names = error.data.busy || [], chats = error.data.chats || [];  // tasks whose agent is at work; other chats of VS Code that run or wait for the person (VS Code asks about them itself when it quits)
        const yes = h("button", {type: "button", class: "act hot live"}, t("board.vs.restart.anyway"));
        const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
        const says = [names.length ? h("p", null, names.length === 1 ? t("board.vs.restart.busy.one", {name: names[0]}) : t("board.vs.restart.busy", {names: names.join(", ")})) : null,
          chats.length ? h("p", null, chats.length === 1 ? t("board.vs.restart.chat.one", {name: chats[0]}) : t("board.vs.restart.chats", {names: chats.join(", ")})) : null, h("p", {class: "sub"}, t("board.vs.restart.busy.then"))].filter(Boolean);
        const view = dialog([h("h2", null, t(names.length ? "board.vs.restart.busy.title" : "board.vs.restart.chat.title")), ...says, h("div", {class: "row win-foot"}, yes, no)]);
        let done = false;
        const end = (then) => { if (done) return; done = true; clearInterval(watch); view.close(); then(); };
        const cancelled = () => reject(Object.assign(error, {quiet: true}));  // the person chose: nothing is said
        const watch = setInterval(() => { if (!view.box.isConnected) end(cancelled); }, 300);
        no.addEventListener("click", () => end(cancelled));
        yes.addEventListener("click", () => end(() => ask(true).then(resolve, reject)));
      });
    }).then(follow);
  }

  function vsButton(chat) {
    const why = chat && !chat.bound ? chat.why || "" : "";
    const nothing = why === "no-cli" || why === "off", alone = ["no-chat", "no-session", "ambiguous"].includes(why);  // VS Code is there and this task has no chat: the window is all it can bring
    const button = h("button", {type: "button", class: "vs-btn" + (alone ? " no-chat" : ""), disabled: nothing ? "disabled" : null, title: nothing ? t("board.vs.why." + why) : alone ? t("board.vs.nochat") : t("board.vs.open"), "aria-label": t("board.vs.open")}, vsLogo());
    button.addEventListener("click", () => {
      button.disabled = true;
      openVS().then(() => { setTimeout(() => { button.disabled = false; }, 1500); }, (error) => { button.disabled = false; failed(error, chat && chat.title); });
    });
    return button;
  }

  // Once per page: trade the pairing code of the address for a cookie, and ask whether this browser is paired.
  let paired = null;
  let stale = null;  // the board was started on an older release than the files now hold: it still runs the old code
  const banners = [];
  const mark = h("span", {class: "vs-pill", hidden: ""}, h("i"), h("span"));  // the same state in two words, next to the VS Code pill; the tip has the sentence
  let markShort = false;
  function showPaired() {
    if (paired) document.querySelector(".unpaired-note")?.remove();  // paired in the meantime: the bar is no longer true
    for (const node of banners) {
      node.replaceChildren(paired === null || (paired && node.dataset.quiet) ? "" : t(paired ? "board.serve.paired" : "board.serve.unpaired"),
        stale ? h("span", {class: "bad"}, " " + t("board.serve.stale", stale)) : "");
      node.classList.toggle("good", paired === true && !stale);
      node.hidden = !node.textContent;
    }
    mark.hidden = paired === null;
    mark.classList.toggle("on", paired === true);
    mark.title = paired === null ? "" : t(paired ? (markShort ? "desk.paired.short" : "board.serve.paired") : "board.serve.unpaired");
    mark.lastChild.textContent = paired === null ? "" : t(paired ? "board.serve.mark.paired" : "board.serve.mark.unpaired");
  }
  const note = (data) => { stale = data.started && data.now && data.started !== data.now ? {started: data.started, now: data.now} : null; return data; };
  const pairCode = () => (location.hash.startsWith("#pair=") ? decodeURIComponent(location.hash.slice(6)) : "");
  function trade() {
    const code = pairCode();
    if (code) history.replaceState(null, "", location.pathname);  // the code leaves the address bar and the history
    // A browser that has the cookie of an earlier pairing does not need the code again: a second tab, a tab the browser restored
    // or loaded twice would otherwise find the code used up and say so.
    const already = send("/api/status", {}).then((data) => data.paired, () => false);
    return already.then((yes) => (code && !yes ? send("/api/pair", {code}).catch(failed) : null))
      .then(() => send("/api/status", {})).then((data) => { paired = note(data).paired; showPaired(); }, () => { paired = false; showPaired(); });
  }
  const ready = trade();
  // A link pasted into a tab that already shows the board changes only what follows the #: the page does not load again, and without this the code would never be read.
  window.addEventListener("hashchange", () => { if (pairCode()) trade().then(() => { if (paired) location.reload(); }); });

  // A line that says whether this browser may approve; it stays right when the page is drawn again.
  // `quiet`: the page has the mark in its header, so the line is there only for what needs the person (not paired, the board runs old code).
  function banner(quiet) {
    const node = h("div", {class: "sub pairing", "data-quiet": quiet ? "1" : null});
    banners.splice(0, banners.length, ...banners.filter((item) => item.isConnected), node);
    showPaired();
    return node;
  }
  // `short`: the task page says only that the buttons act (it has no word about the code: a command is allowed or denied there, and a plan is approved in its own dialog).
  function pairMark(short) {
    markShort = Boolean(short);
    showPaired();
    return mark;
  }

  // The board: the line under the numbers. The board asks for its rows itself (board.js) and keeps what the person typed.
  function start(app) {
    const kpis = app.querySelector(".kpis");
    if (kpis) kpis.after(banner(true));
  }

  return {call, file, stay, pairMark, runs: (action) => serve.actions.includes(action), act, archive, start, banner, post, openVS, restartVS, restartWhy, vsButton, ready, dialog, reasons, failed, done, busy: () => busy, open: () => stack.length > 0, onChange: (call) => { after = call; }};
})();
