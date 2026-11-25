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
    const bar = h("div", {class: "unpaired-note", role: "alert", title: t("board.serve.cancel")}, refusal || t("board.serve.notpaired"), " ", pairControl());
    bar.addEventListener("click", () => bar.remove());
    document.body.append(bar);
  }

  let reloading = false;
  // A page that shows work in progress asks to stay (1.7.38): the wizard writes the language first and goes on for a while, and a reload then lost the work it was showing.
  // `keep()` says whether it still asks. The page that changes the language itself (the settings panel) passes `now`: that one reloads.
  const keepers = [];
  const stay = (keep) => { keepers.push(keep); };

  // 1.8.5: the button a request came from turns while the request has not come back (`is-waiting`, after WAIT_SHOW ms) and cannot be pressed again. A request belongs to the button
  // pressed at most PRESS_WINDOW ms before it started, or to the button whose last request came back that recently (a dialog's Send makes two calls, one after the other).
  // A poll of the page (POLLS) belongs to no button. A button drawn again while it waits is a new node: the old one goes with the page, the new one does not turn.
  const WAIT_SHOW = 300, PRESS_WINDOW = 400;
  let pressed = null, pressedAt = 0;
  const pending = new Map();
  document.addEventListener("click", (event) => {
    const button = event.target && event.target.closest ? event.target.closest("button") : null;
    if (button && !button.disabled) { pressed = button; pressedAt = Date.now(); }
  }, true);
  const POLLS = ["board", "super", "live", "desk", "status", "ready"];  // what the pages ask every few seconds (`/api/<name>`), and after an action to draw it
  function waitOn(promise, path) {
    const button = !POLLS.includes(String(path || "").split("/").pop()) && pressed && Date.now() - pressedAt <= PRESS_WINDOW && pressed.isConnected ? pressed : null;
    if (!button) return promise;
    pending.set(button, (pending.get(button) || 0) + 1);
    const timer = setTimeout(() => { if (button.isConnected && pending.get(button)) { button.classList.add("is-waiting"); button.setAttribute("aria-busy", "true"); } }, WAIT_SHOW);
    const back = () => {
      clearTimeout(timer);
      const left = (pending.get(button) || 1) - 1;
      if (left > 0) { pending.set(button, left); return; }
      pending.delete(button);
      button.classList.remove("is-waiting");
      button.removeAttribute("aria-busy");
      if (pressed === button) pressedAt = Date.now();  // a call made right after this one came back is still the same press
    };
    return promise.then((value) => { back(); return value; }, (error) => { back(); throw error; });
  }

  // Every call of the page waits for the pairing of this load: asked before it, a paired browser would be refused and told it is not paired.
  const post = (path, body, now) => waitOn(ready.then(() => send(path, body, now)), path);

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

  // A read of this server (GET) once the pairing of this load is done: the run card of autorun (`/api/autorun?task=`). A refusal shows the note for an unpaired browser; no answer at all is `offline`, as for `post`.
  const read = (path) => ready.then(() => fetch(path, {credentials: "same-origin"}).then((response) => response.json().then((data) => {
    if (response.ok) return data;
    if (data.unpaired) unpairedNote();
    return Promise.reject(Object.assign(new Error(data.error || response.status), {data}));
  }), () => Promise.reject(Object.assign(new Error(t("board.serve.stopped")), {offline: true}))));

  // A POST with a deadline and nothing else: no bar for an unpaired browser, no reload. The Enter screen asks with it: a stalled server is an error line there, never a hang.
  function call(path, body, seconds) {
    return waitOn(callNow(path, body, seconds), path);
  }
  // The seconds are for a computer as fast as the limits were written for; DATA.pace (1 to 10) says how much slower this one is. `seconds` grow with it here, in one place, for every caller.
  const PACE = Math.max(1, Number(typeof DATA !== "undefined" && DATA ? DATA.pace : 1) || 1);
  function callNow(path, body, base) {
    const seconds = (base || 8) * PACE;
    const control = window.AbortController ? new AbortController() : null;
    const timer = setTimeout(() => control && control.abort(), seconds * 1000);
    const failed = (error) => { clearTimeout(timer); throw new Error(error && error.name === "AbortError" ? "no answer in " + seconds + " s" : (error && error.message) || "no answer"); };
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
    if (error && error.quiet) return;  // the person already answered a window about it
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
    const held = h("div", {class: "held-block", hidden: ""});  // the calls of the task that still wait, listed in this window when the board has said so (1.7.38, F3 M2): the one yes closes the task and voids them
    const view = dialog([h("h2", null, t("board.close.title", {name: row.name})), h("p", null, t("board.close.warn")), row.state === "quiet" ? h("p", {class: "bad"}, t("board.close.quiet")) : null, row.result_missing ? h("p", {class: "bad"}, t("board.close.result", {file: row.result_missing})) : null,
      held, row.todo_left ? [h("p", {class: "bad"}, t("board.close.todo", {count: row.todo_left})), steps, h("label", {class: "sub"}, t("board.close.reason")), words, pick ? pick.node : null] : null,
      h("div", {class: "row"}, tell, go, no), said]);
    let listed = [];  // the codes the person was shown
    go.disabled = true;  // until the board has said whether calls wait: the yes is for the list the person sees
    post("/api/close", {task: row.name, step: "preview"}).then((data) => {
      go.disabled = false;
      listed = ((data.result && data.result.held) || []).map((call) => call.code);
      if (!listed.length) return;
      const found = heldBlock(data.result.held);
      held.replaceChildren(h("p", {class: "bad"}, found.title), ...found.nodes);
      held.hidden = false;
      if (!row.todo_left) go.textContent = t(listed.length === 1 ? "board.accept.held.go.one" : "board.accept.held.go");  // one call: "Void it and close" (1.7.38, C13 FR 12)
      requestAnimationFrame(found.mark);
    }, () => { go.disabled = false; });  // when the list cannot be had, the server still refuses to close while a call waits, and the button says so
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
      post("/api/close", {task: row.name, reason: words ? words.value.trim() : "", ...(listed.length ? {void: true, voids: listed} : {})}).then(() => { view.close(); done(); },
        (error) => { said.replaceChildren(...reasons(error.message)); go.disabled = false; });
    });
  }

  // A slow approval must not block the page (1.8.25). The task+action that waits for the server is kept here, not on a button: the board, the task page and the super queue draw their buttons again every few seconds,
  // and each new button asks `running` for its state. The page itself is never held (`busy` stays false); only the button of that task+action says "working" and cannot be pressed again.
  const LATE = 700;  // a window with a Confirm button stays at most this long (ms) while the server has not answered; then it closes and the action goes on behind the page
  const RUNNING = new Map();  // "task\0action" -> the buttons drawn for it
  const keyOf = (task, action) => task + "\u0000" + action;
  const paint = (node) => { node.disabled = true; node.textContent = t("board.serve.working"); node.setAttribute("aria-busy", "true"); };
  function hold(task, action, node) {
    const key = keyOf(task, action);
    if (!RUNNING.has(key)) RUNNING.set(key, new Set());
    if (node) RUNNING.get(key).add(node);
    for (const other of RUNNING.get(key)) if (other.isConnected || other === node) paint(other);
  }
  function release(task, action) {
    const nodes = RUNNING.get(keyOf(task, action));
    RUNNING.delete(keyOf(task, action));
    for (const node of nodes || []) {
      if (!node.isConnected) continue;
      node.removeAttribute("aria-busy");
      if (node.dataset.label) node.textContent = node.dataset.label;
      if (!node.classList.contains("locked")) node.disabled = false;  // a locked button (the agent is at work) gets its words back and stays off
    }
  }
  // A button the page draws now asks: does its task+action run? If so it says "working" (and is told when it ends).
  function running(task, action, node) {
    const nodes = RUNNING.get(keyOf(task, action));
    if (!nodes) return false;
    if (node) { nodes.add(node); paint(node); }
    return true;
  }
  // The request behind a window's Confirm. It answers within LATE ms: the window ends as it always did (`stay`: the reason shows in it). Later: the window closes and the button of the task+action shows "working";
  // when the answer comes, success refreshes the page and a refusal opens the window again (`again(error)`: same text, same typed code, the reason).
  function settle(view, request, task, action, node, hooks) {
    let late = false;
    const timer = setTimeout(() => { late = true; view.close(); hold(task, action, node); }, LATE);
    request.then(() => {
      clearTimeout(timer);
      if (late) release(task, action); else view.close();
      done();
    }, (error) => {
      clearTimeout(timer);
      if (!late && view.box.isConnected) return hooks.stay(error);  // the window is still there: the reason shows in it
      release(task, action);
      hooks.again(error);  // the window is gone (late, or the person closed it meanwhile): it comes back with the reason, never a refusal nobody sees
    });
  }

  // The part of the question Close and Accept and close share when calls of the task still wait for the person (C13 FB-4, F1 M2, F3 M2): what to say, the calls listed (each with the part of its command that tells it apart
  // from a twin, F3 U3), and a mark that tells a list that scrolls. `title` and `nodes` go in a window; call `mark` once it is on the page.
  function heldBlock(calls) {
    const one = calls.length === 1;
    const list = h("ul", {class: "held-list"}, calls.map((call) => h("li", null, h("b", null, call.system + (call.env && call.env !== "none" ? " " + call.env.toUpperCase() : "")), " ", h("span", {class: "held-title"}, call.title),
      call.detail ? h("span", {class: "held-detail", title: call.detail}, call.detail) : null)));
    const more = h("p", {class: "sub held-more", hidden: ""}, t("board.accept.held.more"));
    const mark = () => { more.hidden = !(list.scrollHeight > list.clientHeight + 1 && list.scrollTop + list.clientHeight < list.scrollHeight - 1); };
    list.addEventListener("scroll", mark);
    return {title: t(one ? "board.accept.held.title.one" : "board.accept.held.title", {n: calls.length}), nodes: [h("p", null, t(one ? "board.accept.held.warn.one" : "board.accept.held.warn")), list, more], mark};
  }

  // The window Accept and close asks when calls of the task still wait: the calls are listed, closing voids them, and the task closes on the second yes.
  // `run(true, codes)` closes with the person's yes and the codes it was shown (the server asks for both); it gives a promise.
  function askVoid(calls, run, ctx, why) {
    const found = heldBlock(calls);
    const go = h("button", {class: "act hot", type: "button"}, t(calls.length === 1 ? "board.accept.held.go.one" : "board.accept.held.go"));
    const no = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
    const said = h("div", {class: "bad"}, ...(why ? reasons(why) : []));
    const view = dialog([h("h2", null, found.title), ...found.nodes, h("div", {class: "row"}, go, no), said]);
    requestAnimationFrame(found.mark);
    no.addEventListener("click", view.close);
    go.addEventListener("click", () => {
      go.disabled = true;
      no.disabled = true;  // the request is out: Cancel would not take it back
      settle(view, run(true, calls.map((call) => call.code)), ctx.task, "accept", ctx.button, {
        stay: (error) => { said.replaceChildren(...reasons(error.message)); go.disabled = false; no.disabled = false; },
        again: (error) => askVoid(calls, run, ctx, error.message)});
    });
    return view;
  }

  // Accept and close (1.7.38, C13 FB-4): when calls of the task still wait for the person, the page lists them first and closes on the second yes.
  // The server asks for that yes too: an acceptance that does not carry it is refused while a call waits.
  function accept(button, row, body) {
    if (running(row.name, "accept")) return;
    hold(row.name, "accept", button);
    const close = (void_, codes) => post("/api/act", {...body, step: "act", ...(void_ ? {void: true, voids: codes || []} : {})});
    post("/api/act", {...body, step: "preview"}).then((data) => {
      const calls = (data.result && data.result.held) || [];
      if (!calls.length) return close(false).then(() => { release(row.name, "accept"); done(); });
      release(row.name, "accept");
      askVoid(calls, (void_, codes) => close(void_, codes), {task: row.name, button});
    }).catch((error) => { release(row.name, "accept"); failed(error); });
  }

  function act(button, row, item) {
    if (item.action === "send") return CHAT.panel(row, item.action);  // chat.js: the panel that shows the message, then sends it
    if (item.action === "answer" || item.action === "steer") return speak(row);
    if (item.action === "confirm") return CHAT.confirm(row);  // the chat waits for a tool to be allowed (B75)
    if (item.action === "question") return CHAT.question(row);
    if (item.action === "stop") return CHAT.stop(row);
    if (item.action === "autorun on") return AUTORUN.start(row);  // autorun.js: the Start form (models, spend limit, the code), not the code window of an approval
    if (item.action === "close") return close(row);
    if (item.action === "archive") return archive([row.name], serve.archive_to);
    const body = {action: item.action, task: row.name};  // 1.8.49: a plan is approved only on a confirmed requirement; there is no code for both
    if (item.action === "accept") return accept(button, row, body);
    if (free(item.action)) {
      button.textContent = t("board.serve.working");
      post("/api/act", {...body, step: "act"}).then(done, (error) => { button.textContent = button.dataset.label; failed(error); });
      return;
    }
    // The preview works the plan out (git on every repository): it can take long. The button says so and cannot be pressed again; the page keeps working meanwhile (1.8.25).
    if (running(row.name, item.action)) return;
    hold(row.name, item.action, button);
    post("/api/act", {...body, step: "preview"}).then((data) => {
      release(row.name, item.action);
      codeWindow(button, row, item, body, data, "", false, "");
    }).catch((error) => { release(row.name, item.action); failed(error); });  // an error while drawing the dialog is told too, not lost
  }

  // The window with what the terminal would show and the code field. `typed`, `nowake` and `why` are what a window that comes back after a late refusal starts with.
  function codeWindow(button, row, item, body, data, typed, nowake, why) {
    const input = h("input", {class: "code", autocomplete: "off", spellcheck: "false", placeholder: t("board.serve.code"), value: typed});
    const yes = h("button", {class: "act hot", type: "button"}, t("board.serve.confirm"));
    const no = h("button", {class: "act", type: "button"}, t("board.serve.cancel"));
    const said = h("div", {class: "bad"}, ...(why ? reasons(why) : []));
    const quiet = item.action === "approve-plan" ? h("input", {type: "checkbox"}) : null;  // 1.8: approve, but do not wake the agent: autorun comes next
    if (quiet && nowake) quiet.checked = true;
    const quietRow = quiet ? h("label", {class: "sub", title: t("board.plan.nowake.tip")}, quiet, " " + t("board.plan.nowake")) : null;
    // What the terminal would show can be long (a promote lists every file): it scrolls in its own box, so the code and the buttons stay in view.
    const view = dialog([h("h2", null, button.dataset.label + " · " + row.name),
      h("div", {class: "screen"}, data.result.screen.map((line) => h("p", {class: "sub"}, line))),
      h("p", null, data.result.ask), input, quietRow, h("div", {class: "row"}, yes, no), said]);
    no.addEventListener("click", view.close);
    const send = () => {
      if (yes.disabled) return;
      yes.disabled = true;
      no.disabled = true;  // the request is out: Cancel would not take it back
      yes.textContent = t("board.serve.working");
      const code = input.value.trim(), asleep = Boolean(quiet && quiet.checked);
      // The server may be slow (git): the window stays 700 ms, then the action goes on behind the page. The code goes with the act step as ever.
      settle(view, post("/api/act", {...body, step: "act", code, ...(asleep ? {no_wake: true} : {})}), row.name, item.action, button, {
        stay: (error) => { said.replaceChildren(...reasons(error.message)); yes.disabled = false; no.disabled = false; yes.textContent = t("board.serve.confirm"); },
        again: (error) => codeWindow(button, row, item, body, data, code, asleep, error.message)});
    };
    yes.addEventListener("click", send);
    input.addEventListener("keydown", (event) => { if (isEnter(event)) send(); });
    input.focus();
  }

  // Once per page: trade the pairing code of the address for a cookie, and ask whether this browser is paired.
  let paired = null;
  let refusal = "";  // why the code of the address was refused (used, old, wrong), until this browser is paired
  let pairSaid = "";  // what the last press of the pair button found
  // One click to pair (1.8.11): the board opens itself in the default browser of this computer, with a new code. A small button; the long words are in its tip.
  function pairControl() {
    const said = h("span", {class: "sub pair-said"}, pairSaid);
    const button = h("button", {type: "button", class: "act pair-btn", title: t("board.serve.pair.tip")}, t("board.serve.pair.button"));
    button.addEventListener("click", (event) => {
      event.stopPropagation();  // the bar closes on a click; this is not a click to close it
      button.disabled = true;
      send("/api/reopen", {}).then((data) => data.opened ? t("board.serve.pair.opened") : t("board.serve.pair.notopened"), (error) => t("board.serve.pair.notopened") + " " + (error && error.message || ""))
        .then((text) => { pairSaid = text; said.textContent = text; button.disabled = false; });
    });
    return h("span", {class: "pair-control"}, button, " ", said);
  }
  let stale = null;  // the board was started on an older release than the files now hold: it still runs the old code
  const banners = [];
  const mark = h("span", {class: "vs-pill", hidden: ""}, h("i"), h("span"));  // the same state in two words, next to the VS Code pill; the tip has the sentence
  let markShort = false;
  function showPaired() {
    if (paired) document.querySelector(".unpaired-note")?.remove();  // paired in the meantime: the bar is no longer true
    for (const node of banners) {
      node.replaceChildren(paired === null || (paired && node.dataset.quiet) ? "" : refusal && !paired ? refusal : t(paired ? "board.serve.paired" : "board.serve.unpaired"),
        paired === false ? h("span", null, " ", pairControl()) : "",
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
    return already.then((yes) => (code && !yes ? send("/api/pair", {code}).catch((error) => { if (error && error.data && error.data.reason) { refusal = error.message; } else failed(error); }) : null))
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

  return {call, read, file, stay, pairMark, pairControl, runs: (action) => serve.actions.includes(action), running, act, archive, start, banner, post, ready, dialog, reasons, failed, done, busy: () => busy, open: () => stack.length > 0, onChange: (call) => { after = call; }};
})();
