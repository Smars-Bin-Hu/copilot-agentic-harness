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
  return h("div", {class: "kpi"}, h("b", null, value), h("span", null, label));
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
  return h("table", null, h("tr", null, head), rows);
}

const th = (text, numeric) => h("th", numeric ? {class: "num"} : null, text || "");
const num = (text) => h("td", {class: "num"}, text);
const tag = (text, kind) => h("span", {class: "tag" + (kind ? " " + kind : "")}, text);
const card = (title, ...children) => h("div", {class: "card"}, title ? h("h2", null, title) : null, children);
const reviewsText = (checks, fails) => t("report.kpi.reviews.value", {checks, fails});
