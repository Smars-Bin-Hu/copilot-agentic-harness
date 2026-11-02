// Shared by the task page and the board. No library, no network.
// The page's data is the JSON in the element with id "data": {text: the message table, ...}. Everything is drawn with
// DOM nodes and textContent, never innerHTML, so a task name cannot become markup.
"use strict";

const DATA = JSON.parse(document.getElementById("data").textContent);
const TEXT = DATA.text || {};

// Enter that ends a line. Not the Enter that picks a word in an input method: Chinese is typed with it.
const isEnter = (event) => event.key === "Enter" && !event.isComposing && event.keyCode !== 229;

// A message by name with its {placeholders} filled in. An unknown name shows itself.
function t(key, values) {
  const template = Object.prototype.hasOwnProperty.call(TEXT, key) ? TEXT[key] : key;
  return template.replace(/`/g, "").replace(/\{(\w+)\}/g, (whole, name) => (values && name in values ? String(values[name]) : whole));  // the marks are for a terminal; what a person fills in stays as it is
}

const plainWords = (text) => String(text).replace(/`/g, "");  // words of the engine, written for a terminal

// h("td", {class: "num", title: "x"}, child, "text", [more])
function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name === "style") node.style.cssText = value;
    else node.setAttribute(name, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function clock(seconds) {
  if (seconds === null || seconds === undefined) return "-";
  const total = Math.round(Math.max(0, seconds));
  if (total < 60) return t("unit.seconds", {s: total});
  if (total < 3600) return t("unit.minutes", {m: Math.floor(total / 60), s: total % 60});
  if (total < 86400) return t("unit.hours", {h: Math.floor(total / 3600), m: Math.floor((total % 3600) / 60)});
  return t("unit.days", {d: Math.floor(total / 86400), h: Math.floor((total % 86400) / 3600)});
}

function amount(value) {
  if (value === null || value === undefined) return "-";
  if (Math.abs(value - Math.round(value)) < 0.05) return Math.round(value).toLocaleString("en-US");
  return value.toLocaleString("en-US", {minimumFractionDigits: 1, maximumFractionDigits: 1});
}

const share = (part, whole) => (part && whole ? part / whole : 0);
const percent = (value) => Math.round(value * 100) + "%";
// A UTC stamp as the local time of whoever opens the page: "YYYY-MM-DD HH:MM:SS", then cut like the stamp was (from, to).
function when(stamp, from, to) {
  const date = new Date(stamp || "");
  if (!stamp || isNaN(date.getTime())) return String(stamp || "").slice(from, to).replace("T", " ");
  const two = (value) => String(value).padStart(2, "0");
  const local = date.getFullYear() + "-" + two(date.getMonth() + 1) + "-" + two(date.getDate()) + " " + two(date.getHours()) + ":" + two(date.getMinutes()) + ":" + two(date.getSeconds());
  return local.slice(from, to);
}

function kpi(value, label) {
  // A wide character (Chinese, full-width punctuation) takes the room of two: a long value is set smaller so it stays on one line.
  const room = Array.from(String(value)).reduce((total, char) => total + (char.codePointAt(0) > 0x2e7f ? 2 : 1), 0);
  return h("div", {class: "kpi"}, h("b", {class: room > 12 ? "long" : ""}, value), h("span", null, label));
}

// parts: [css class, value, tooltip]. Each part takes value / whole of the bar.
function bar(parts, whole, thin) {
  return h("div", {class: "bar" + (thin ? " thin" : "")}, parts
    .filter(([, value]) => value && whole)
    .map(([name, value, tip]) => h("i", {class: name, style: `width:${Math.min(100, (value / whole) * 100).toFixed(2)}%`, title: tip})));
}

// items: [css class, label, value text]
function legend(items) {
  return h("div", {class: "legend"}, items.map(([name, label, value]) => h("span", null, h("i", {class: name}), label + " ", h("b", null, value || ""))));
}

function table(head, rows) {
  return h("div", {class: "scroll"}, h("table", null, h("tr", null, head), rows));
}

const th = (text, numeric) => h("th", numeric ? {class: "num"} : null, text || "");
const num = (text) => h("td", {class: "num"}, text);
const thinkingLabel = (level, model) => (model && model.thinking && model.thinking.key === "tier" && model.thinking.labels[level]) || (level === "medium" ? t("desk.set.thinking.recommended", {level}) : level);
const tag = (text, kind) => h("span", {class: "tag" + (kind ? " " + kind : "")}, text);

// The one state of a task is told by the server (tasklife.state_of): new, closed, paused, waiting, working, quiet, unheld.
// A page that is not kept fresh cannot say "working" (the last five minutes it looked at are gone), so it says "quiet".
function stateOf(row, live) { return row.state === "working" && !live ? "quiet" : row.state || "quiet"; }
// What a task waits for, in the language of the page. The server words it too (`row.waiting`), but a board that runs while the language is changed may still send the
// old language for a while; the page's own table is always the one it shows. Waits with a detail in them (a command, a question, an environment) keep the server's words.
const PLAIN_WAITS = ["plan", "promote", "recover", "review", "req", "commit", "stopped", "cancelled", "go-req", "go-plan", "go-promote", "go-recover", "go-review"];
function waitText(row) {
  return PLAIN_WAITS.includes(row.waiting_why) && Object.prototype.hasOwnProperty.call(TEXT, "task.waiting." + row.waiting_why) ? t("task.waiting." + row.waiting_why) : row.waiting;
}
function stateTag(row, live) {
  const state = stateOf(row, live);
  if (state === "waiting") return tag(waitText(row), "hot long");
  if (state === "working") return tag(t("board.state.working"), "good run");
  if (state === "quiet") return tag(t("board.state.quiet"), "idle");
  if (state === "unheld") return tag(t("board.state.unheld") + (row.unheld_s === null || row.unheld_s === undefined ? "" : " \u00b7 " + clock(row.unheld_s)), "lost");
  return tag(t("board.state." + state));
}
const card = (title, ...children) => h("div", {class: "card"}, title ? h("h2", null, title) : null, children);
const reviewsText = (checks, fails) => t("report.kpi.reviews.value", {checks, fails});

// A click copies the command; the person pastes it in a terminal. Nothing runs from a page on disk.
function copyCommand(button, command) {
  const done = () => {
    button.textContent = t("board.copied");
    setTimeout(() => { button.textContent = button.dataset.label; }, 1500);
  };
  const fallback = () => {
    const area = h("textarea", {style: "position:fixed;opacity:0"}, command);
    document.body.append(area);
    area.select();
    try { document.execCommand("copy"); done(); } catch (error) { window.prompt(t("board.copy.manual"), command); }
    area.remove();
  };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(command).then(done, fallback);
  else fallback();
}

// Poll every `seconds`: tick() returns a promise (or null: nothing to do now). After 3 misses in a row (the board server gave no answer: error.offline) polling stops and a notice
// says so, so a stopped server does not fill the console. One miss, or a refusal, changes nothing.
// While the page is hidden nothing is asked, and the first look after it shows again is at once. A round is skipped while the last request has not come back.
function pollEvery(seconds, tick) {
  let misses = 0;
  let waiting = false;
  const timer = setInterval(go, seconds * 1000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) go(); });
  function go() {
    if (document.hidden || waiting) return;
    const run = tick();
    if (!run) return;
    waiting = true;
    run.then(() => { misses = 0; waiting = false; }, (error) => {
      waiting = false;
      if (!error || !error.offline) { misses = 0; return; }
      if (++misses < 3) return;
      clearInterval(timer);
      document.body.prepend(h("div", {class: "stopped-note", role: "alert"}, t("board.stopped")));
    });
  }
}

// What the task waits for, not what the person may do any time (nor a check they may say judged wrong): such an action is "hot".
const CONTROLS = ["pause", "resume", "close", "autorun on"];
const CHAT_ACTIONS = ["send", "answer", "steer", "stop", "confirm", "question"];  // the buttons that go through the link to VS Code: dimmed while it is down (shell.js)
const TALK = ["steer", "stop"];  // said to the agent while it works: the one thing a page may do then
const isHot = (row, item) => Boolean(row.waiting) && !CONTROLS.includes(item.action) && item.action !== "review dismiss";

// The button of one action ({action, command}) of a task row: it acts when the board server runs that action, else it copies the command.
// A served task with no chat to talk to: the chat buttons are grey with the reason, and with VS Code up a button beside them makes a new chat that picks the task up.
const chatGone = (row) => typeof SERVE !== "undefined" && Boolean(row.chat) && !row.chat.bound;
const chatNew = (row) => chatGone(row) && ["", "no-chat", "no-session"].includes(row.chat.why || "");
function chatGoOn(name) {
  DOCK.start("harness-my-task", t("board.go.words", {task: name}), null, name);
}
function goOnButton(name, extra) {
  const button = h("button", {class: "act hot live chat-act" + (extra ? " " + extra : ""), type: "button"}, t("board.go.new"));
  button.addEventListener("click", () => chatGoOn(name));
  return button;
}
function actionButton(row, item, extra) {
  const label = t("board.action." + item.action.replace(" ", "-"));
  const live = typeof SERVE !== "undefined" && SERVE.runs(item.action);  // serve.js is there only when the server sent the page
  const hot = isHot(row, item);
  // While the agent is in the middle of a turn nothing is pressed on the page: a question about the result is a doubt, and the person decides when the answer is in
  // (stop the agent in VS Code first, or wait for it to stop)
  const locked = typeof SERVE !== "undefined" && row.state === "working" && item.action !== "archive" && !TALK.includes(item.action);
  const button = h("button", {class: "act" + (CHAT_ACTIONS.includes(item.action) ? " chat-act" : "") + (hot ? " hot" : "") + (live ? " live" : "") + (locked ? " locked" : "") + (extra ? " " + extra : ""), type: "button", title: locked ? t("board.action.busy") : live ? "" : item.command, "data-label": label}, label);
  if (locked) button.disabled = true;
  if (chatGone(row) && CHAT_ACTIONS.includes(item.action) && item.action !== "send") {  // Send stays: its panel lets the person copy the message
    button.disabled = true;
    button.classList.remove("hot");  // it asks for nothing now, and the button beside it is the one to press
    button.title = t("board.vs.why." + (row.chat.why || "no-chat"));
  }
  button.addEventListener("click", () => (locked ? null : live ? SERVE.act(button, row, item) : typeof TERM !== "undefined" ? TERM.run(item.command) : copyCommand(button, item.command)));  // a served page runs it in the Terminal window; a saved page can only copy
  return button;
}

// The kind of a task as a 16px line icon (no library). The name of the kind is the tooltip. Each icon: [tag, {attributes}] parts.
const KIND_ICONS = {
  dev: [["path", {d: "M2.8 13.2L8.4 7.6", "stroke-width": 2.4}], ["path", {d: "M7.6 1.8L14 8.2l-2.6 2.4L5 4.2z", fill: "currentColor", "stroke-width": 0.8}]],  // hammer: a filled head across a thick handle
  test: [["path", {d: "M6 2h4M7 2v4L3 13a1 1 0 0 0 1 1.5h8A1 1 0 0 0 13 13L9 6V2M5 10h6"}]],  // flask
  rca: [["circle", {cx: 7, cy: 7, r: 4.5}], ["path", {d: "M10.5 10.5L14 14"}]],  // magnifier
  qa: [["circle", {cx: 8, cy: 8, r: 6}], ["path", {d: "M6 6.3a2 2 0 1 1 3 1.7c-.7.4-1 .8-1 1.5M8 11.5v.5"}]],  // question
  kb: [["path", {d: "M3 2.5h8a2 2 0 0 1 2 2v9H5a2 2 0 0 1-2-2zM3 11.5a2 2 0 0 1 2-2h8"}]],  // book
  design: [["path", {d: "M2 3h12v10H2zM2 6.5h12M6 6.5V13"}]],  // blueprint
  other: [["circle", {cx: 3.5, cy: 8, r: 1}], ["circle", {cx: 8, cy: 8, r: 1}], ["circle", {cx: 12.5, cy: 8, r: 1}]],  // three dots
};
function kindIcon(kind, text) {
  const wrap = h("span", {class: "kind-icon", title: text, role: "img", "aria-label": text});
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  for (const [name, value] of Object.entries({viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", "stroke-width": "1.4", "stroke-linecap": "round", "stroke-linejoin": "round"})) svg.setAttribute(name, value);
  for (const [tagName, attrs] of KIND_ICONS[kind] || KIND_ICONS.other) {
    const part = document.createElementNS(ns, tagName);
    for (const [name, value] of Object.entries(attrs)) part.setAttribute(name, String(value));
    svg.append(part);
  }
  wrap.append(svg);
  return wrap;
}

// The independent checks of a row (row.checks, from taskreview.dots) as one dot per wanted check: green for each pass in a row, red where the last one did not pass,
// turning while a check runs, hollow for the rest. No checks wanted: a dash.
function checkDots(row) {
  const info = row.checks;
  if (!info || !info.n) return h("span", {class: "dots-none"}, "-");
  const title = t("board.checks.tip", {n: info.n, passes: info.passes, total: info.total, fails: info.fails});
  const dots = [];
  for (let at = 0; at < info.n; at++) {
    let kind = "";
    if (info.waived || at < info.passes) kind = "pass";
    else if (at === info.passes && info.pending) kind = "run";
    else if (at === info.passes && info.last && info.last !== "PASS") kind = "fail";
    dots.push(h("i", {class: "cdot" + (kind ? " " + kind : "")}));
  }
  return h("span", {class: "cdots", title, role: "img", "aria-label": title}, dots);
}

// What the agent did last (`sub`: {at, what, text, kind}, from tasksub.py): "13:51 Edit DEV/a.sql", or "13:51 Reply <first line>". The time is the viewer's own.
function subNodes(sub) {
  const label = sub.what || (sub.kind === "reply" ? t("board.sub.reply") : "");
  return [sub.at ? h("span", {class: "sub-at"}, when(sub.at, 11, 16) + " ") : null, label ? h("b", null, label + " ") : null, sub.text || ""];
}

// The name of the workspace above a page, and the notice at its foot (the NOTICE file asks for it to be kept).
function brand() {
  const served = /^https?:$/.test(location.protocol);
  return h("div", {class: "brand"}, served ? h("a", {href: "/"}, t("board.brand")) : t("board.brand"));
}

function copyright() {
  return h("p", {class: "copyright"}, t("board.copyright"));
}
