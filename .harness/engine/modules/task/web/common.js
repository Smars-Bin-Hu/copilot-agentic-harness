// Shared by the task page and the board. No library, no network.
// The page's data is the JSON in the element with id "data": {text: the message table, ...}. Everything is drawn with
// DOM nodes and textContent, never innerHTML, so a task name cannot become markup.
"use strict";

const DATA = JSON.parse(document.getElementById("data").textContent);
const TEXT = DATA.text || {};

// A message by name with its {placeholders} filled in. An unknown name shows itself.
function t(key, values) {
  const template = Object.prototype.hasOwnProperty.call(TEXT, key) ? TEXT[key] : key;
  return template.replace(/\{(\w+)\}/g, (whole, name) => (values && name in values ? String(values[name]) : whole));
}

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
const tag = (text, kind) => h("span", {class: "tag" + (kind ? " " + kind : "")}, text);

// The one state of a task is told by the server (tasklife.state_of): new, closed, paused, waiting, working, quiet, unheld.
// A page that is not kept fresh cannot say "working" (the last five minutes it looked at are gone), so it says "quiet".
function stateOf(row, live) { return row.state === "working" && !live ? "quiet" : row.state || "quiet"; }
function stateTag(row, live) {
  const state = stateOf(row, live);
  if (state === "waiting") return tag(row.waiting, "hot long");
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

// The button of one action ({action, command}) of a task row: it acts when the board server runs that action, else it copies the command.
const CONTROLS = ["pause", "resume", "close", "autorun on"];
function actionButton(row, item, extra) {
  const label = t("board.action." + item.action.replace(" ", "-"));
  const live = typeof SERVE !== "undefined" && SERVE.runs(item.action);  // serve.js is there only when the server sent the page
  const hot = row.waiting && !CONTROLS.includes(item.action);  // what the task waits for, not what the person may do any time
  // While the agent is in the middle of a turn nothing is pressed on the page: a question about the result is a doubt, and the person decides when the answer is in
  // (stop the agent in VS Code first, or wait for it to stop)
  const locked = typeof SERVE !== "undefined" && row.state === "working" && item.action !== "archive";
  const button = h("button", {class: "act" + (hot ? " hot" : "") + (live ? " live" : "") + (locked ? " locked" : "") + (extra ? " " + extra : ""), type: "button", title: locked ? t("board.action.busy") : live ? "" : item.command, "data-label": label}, label);
  if (locked) button.disabled = true;
  button.addEventListener("click", () => (locked ? null : live ? SERVE.act(button, row, item) : copyCommand(button, item.command)));
  return button;
}

// The name of the workspace above a page, and the notice at its foot (the NOTICE file asks for it to be kept).
function brand() {
  const served = /^https?:$/.test(location.protocol);
  return h("div", {class: "brand"}, served ? h("a", {href: "/"}, t("board.brand")) : t("board.brand"));
}

function copyright() {
  return h("p", {class: "copyright"}, t("board.copyright"));
}
