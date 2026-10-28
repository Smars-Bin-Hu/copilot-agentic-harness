// The code compare of the Changes tab, as in VS Code: old code on the left, new code on the right (or one column), the red and green
// bars as wide as the longest line so they stay when the code is scrolled sideways, both sides scrolled together.
// It reads the unified diff of the task (`desk.changes.diff.lines`) and, for a changed file, the new code (`item.text`):
// the lines between the hunks are the same on both sides, so the whole file is rebuilt from these two. Without the new
// code (a very long file) only the hunks are shown. Everything is drawn with DOM nodes and textContent.
"use strict";

const DiffView = (function () {
  const FOLD_KEEP = 3;  // unchanged lines kept next to a change when a long unchanged run is folded
  const FOLD_MIN = 4;   // fold a run only when it hides at least this many lines
  const MODES = ["split", "unified", "raw"];
  const memory = {};

  function store(name, fallback, value) {
    try {
      if (value !== undefined) { memory[name] = value; localStorage.setItem("harness.diff." + name, value); return value; }
      const kept = localStorage.getItem("harness.diff." + name);
      return kept === null ? (name in memory ? memory[name] : fallback) : kept;
    } catch (error) { return name in memory ? memory[name] : fallback; }
  }

  // --- the diff text -> files with hunks ---------------------------------------------------------------------

  // Inside a hunk the counts of its `@@` line say how many lines follow, as in `diffKinds` of desk.js. A created file has no `@@` line
  // (`--- /dev/null`, then only `+` lines) and a deleted one has none either (`+++ /dev/null`, then only `-` lines).
  function parse(lines) {
    const files = [];
    let file = null, hunk = null, old = 0, added = 0, body = "", skip = false;
    const start = (path) => { file = {path, status: "modify", hunks: [], note: ""}; files.push(file); hunk = null; old = added = 0; body = ""; skip = false; };
    const add = (kind, value) => {
      if (!hunk) { hunk = {oldStart: 1, oldCount: 1, newStart: 1, newCount: 1, lines: []}; file.hunks.push(hunk); }  // no `@@` line: the whole file, from line 1
      hunk.lines.push({k: kind, v: value});
    };
    for (const line of lines) {
      if (old > 0 || added > 0) {
        if (line.startsWith("\\")) continue;
        if (line.startsWith("-")) { old -= 1; add("-", line.slice(1)); } else if (line.startsWith("+")) { added -= 1; add("+", line.slice(1)); } else { old -= 1; added -= 1; add(" ", line.slice(1)); }
        continue;
      }
      const header = /^diff --git a\/(.*) b\/(.*)$/.exec(line);
      if (header) { start(header[2]); continue; }
      if (!file) continue;  // the line at the top of the file
      if (skip) { skip = false; continue; }
      const found = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(line);
      if (found) {
        old = found[2] === undefined ? 1 : Number(found[2]);
        added = found[4] === undefined ? 1 : Number(found[4]);
        hunk = {oldStart: Number(found[1]), oldCount: old, newStart: Number(found[3]), newCount: added, lines: []};
        file.hunks.push(hunk);
        continue;
      }
      if (line === "--- /dev/null") { file.status = "create"; body = "+"; skip = true; continue; }  // the next line is `+++ b/<path>`
      if (line === "+++ /dev/null") { file.status = "delete"; body = "-"; continue; }
      if (body && line.startsWith(body)) { add(body, line.slice(1)); continue; }
      if (line.startsWith("--- ") || line.startsWith("+++ ") || line === "deleted file") continue;
      file.note += (file.note ? "\n" : "") + line;
    }
    return files;
  }

  // --- the rows ----------------------------------------------------------------------------------------------

  // One row per line of the compare: {t: "ctx"|"chg"|"del"|"add"|"sep", o: old line number, n: new line number, a: old text, b: new text}.
  // A run of removed lines next to a run of added ones is laid side by side, line for line (a "chg" row); the longer run goes on alone.
  function rows(file, text) {
    const out = [];
    let o = 1, n = 1;
    const ctx = (value) => { out.push({t: "ctx", o, n, a: value, b: value}); o += 1; n += 1; };
    for (const hunk of file.hunks) {
      const hunkOld = hunk.oldCount === 0 ? hunk.oldStart + 1 : hunk.oldStart;  // `-5,0` is "after line 5"; `-0,0` is an empty file
      const hunkNew = hunk.newCount === 0 ? hunk.newStart + 1 : hunk.newStart;
      if (text) {
        while (n < hunkNew) ctx(n - 1 < text.length ? text[n - 1] : "");
      } else if (hunkNew > n || (out.length === 0 && hunkNew > 1)) {
        out.push({t: "sep"});
      }
      o = hunkOld; n = hunkNew;
      let dels = [], adds = [];
      const flush = () => {
        const most = Math.max(dels.length, adds.length);
        for (let i = 0; i < most; i += 1) {
          const left = i < dels.length, right = i < adds.length;
          out.push({t: left && right ? "chg" : left ? "del" : "add", o: left ? o : null, n: right ? n : null, a: left ? dels[i] : "", b: right ? adds[i] : ""});
          if (left) o += 1;
          if (right) n += 1;
        }
        dels = []; adds = [];
      };
      for (const line of hunk.lines) {
        if (line.k === "-") dels.push(line.v);
        else if (line.k === "+") adds.push(line.v);
        else { flush(); ctx(line.v); }
      }
      flush();
    }
    if (text) { while (n <= text.length) ctx(text[n - 1]); } else if (file.status === "modify") out.push({t: "sep"});
    return out;
  }

  // Long unchanged runs become one "N unchanged lines" row; `open` holds the starts of the runs the person opened.
  function fold(list, open) {
    const out = [];
    let at = 0;
    while (at < list.length) {
      if (list[at].t !== "ctx") { out.push(list[at]); at += 1; continue; }
      let end = at;
      while (end < list.length && list[end].t === "ctx") end += 1;
      const head = at > 0 ? FOLD_KEEP : 0, tail = end < list.length ? FOLD_KEEP : 0, hidden = end - at - head - tail;
      if (hidden >= FOLD_MIN && !open.has(at)) {
        out.push(...list.slice(at, at + head), {t: "fold", id: at, count: hidden}, ...list.slice(end - tail, end));
      } else {
        out.push(...list.slice(at, end));
      }
      at = end;
    }
    return out;
  }

  // The part of two lines that differs: what both begin with and end with is left out.
  function inline(a, b) {
    let head = 0;
    while (head < a.length && head < b.length && a[head] === b[head]) head += 1;
    let tail = 0;
    while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail += 1;
    return {head, tail};
  }

  // --- drawing -----------------------------------------------------------------------------------------------

  function code(value, other, marked) {
    if (!marked || !value || !other) return value || "​";
    const {head, tail} = inline(value, other);
    if (head + tail >= value.length || head + tail >= other.length) return value;
    return [value.slice(0, head), h("mark", null, value.slice(head, value.length - tail)), value.slice(value.length - tail)];
  }

  function cell(number, kind, content) {
    return h("div", {class: "dv-row " + kind}, h("span", {class: "dv-no", "data-n": number === null || number === undefined ? "" : number}), h("span", {class: "dv-code"}, content));
  }

  const FILL = "dv-fill";

  function sideRows(list, side) {
    return list.map((row) => {
      if (row.t === "sep") return h("div", {class: "dv-row dv-sep"}, h("span", {class: "dv-no"}), h("span", {class: "dv-code"}, "⋯"));
      if (row.t === "fold") return h("div", {class: "dv-row dv-fold", title: t("desk.diff.open")}, h("span", {class: "dv-no"}), h("span", {class: "dv-code"}, t("desk.diff.fold", {n: row.count})));
      const left = side === "a";
      const kind = row.t === "ctx" ? "" : row.t === "chg" ? (left ? "del" : "add") : row.t === "del" ? (left ? "del" : FILL) : (left ? FILL : "add");
      if (kind === FILL) return cell(null, FILL, "​");
      return cell(left ? row.o : row.n, kind, code(left ? row.a : row.b, left ? row.b : row.a, row.t === "chg"));
    });
  }

  function bind(node, list, toggle) {  // a fold row opens when clicked
    node.querySelectorAll(".dv-fold").forEach((item, index) => { item.addEventListener("click", () => toggle(list.filter((row) => row.t === "fold")[index].id)); });
  }

  function unifiedRows(list) {
    const out = [];
    for (const row of list) {
      if (row.t === "sep") { out.push(h("div", {class: "dv-row dv-sep"}, h("span", {class: "dv-no"}), h("span", {class: "dv-no"}), h("span", {class: "dv-code"}, "⋯"))); continue; }
      if (row.t === "fold") { out.push(h("div", {class: "dv-row dv-fold", title: t("desk.diff.open")}, h("span", {class: "dv-no"}), h("span", {class: "dv-no"}), h("span", {class: "dv-code"}, t("desk.diff.fold", {n: row.count})))); continue; }
      const line = (kind, o, n, value, other, marked) => h("div", {class: "dv-row " + kind},
        h("span", {class: "dv-no", "data-n": o === null ? "" : o}), h("span", {class: "dv-no", "data-n": n === null ? "" : n}),
        h("span", {class: "dv-code", "data-sign": kind === "add" ? "+" : kind === "del" ? "-" : " "}, code(value, other, marked)));
      if (row.t === "ctx") out.push(line("", row.o, row.n, row.a));
      if (row.t === "chg" || row.t === "del") out.push(line("del", row.o, null, row.a, row.b, row.t === "chg"));
      if (row.t === "chg" || row.t === "add") out.push(line("add", null, row.n, row.b, row.a, row.t === "chg"));
    }
    return out;
  }

  // Two panes that scroll as one. A scroll the other pane caused is not sent back.
  function together(first, second) {
    const follow = (from, to) => from.addEventListener("scroll", () => {
      if (from.dataset.follow) { delete from.dataset.follow; return; }
      if (to.scrollTop !== from.scrollTop || to.scrollLeft !== from.scrollLeft) {
        to.dataset.follow = "1";
        to.scrollTop = from.scrollTop;
        to.scrollLeft = from.scrollLeft;
      }
    });
    follow(first, second);
    follow(second, first);
  }

  function pane(kind, children) {
    return h("div", {class: "dv-pane " + kind}, h("div", {class: "dv-body"}, children, h("div", {class: "dv-end"})));
  }

  // The compare of one file: `text` is its new code (or null), `mode` is "split" or "unified", `key` the view it is in.
  function compare(file, text, mode, key) {
    const open = new Set();
    const box = h("div", {class: "dv " + mode});
    const draw = () => {
      const list = fold(rows(file, text), open);
      const toggle = (id) => { open.add(id); draw(); };
      const was = [...box.querySelectorAll(".dv-pane")].map((node) => [node.scrollTop, node.scrollLeft]);  // opening a fold keeps the place
      box.replaceChildren();
      if (mode === "unified") {
        const only = pane("dv-one", unifiedRows(list));
        box.append(only);
        bind(only, list, toggle);
      } else {
        const left = pane("dv-left", sideRows(list, "a")), right = pane("dv-right", sideRows(list, "b"));
        box.append(left, right);
        bind(left, list, toggle);
        bind(right, list, toggle);
        together(left, right);
      }
      box.querySelectorAll(".dv-pane").forEach((node, index) => {
        node.dataset.keep = "dv." + key + "." + mode + "." + index + "." + file.path;  // desk.js puts the place back after a redraw of the page
        if (was[index]) [node.scrollTop, node.scrollLeft] = was[index];
      });
    };
    draw();
    return box;
  }

  // The +/- counts of a file read from its hunks (the write-back plan has no list of files beside its diff).
  function counts(file) {
    let added = 0, removed = 0;
    for (const hunk of file.hunks) for (const line of hunk.lines) { if (line.k === "+") added += 1; else if (line.k === "-") removed += 1; }
    return {path: file.path, action: file.status, added, removed};
  }

  // The whole view: a list of the files to click, the way to look, and the compare of the file picked. `source` is {lines, cut, files?}: the
  // diff text and, for DEV/, the list of the changed files with their new code. `raw` draws the plain diff text (desk.js). `key` keeps the
  // file picked apart for each view ("dev", "plan"); `small` makes a long file scroll in a lower window.
  function create(source, raw, key, small) {
    const parsed = parse(source.lines);
    const diffs = new Map(parsed.map((item) => [item.path, item]));
    const files = (source.files || parsed.map(counts)).filter((item) => diffs.has(item.path));
    if (!files.length) return raw();
    const chosen = () => (files.find((item) => item.path === store("file." + key, "")) || files[0]);
    const mode = () => (MODES.includes(store("mode", "split")) ? store("mode", "split") : "split");
    const host = h("div", {class: "dv-view" + (small ? " small" : "")});
    // The list is made once and only marked again, so a click does not scroll it back to the top.
    const picks = files.map((item) => {
      const button = h("button", {type: "button", class: "dv-pick", title: item.path},
        h("span", {class: "dv-act " + item.action}, t("desk.changes." + item.action)), h("code", null, item.path),
        h("span", {class: "dv-n add"}, "+" + item.added), h("span", {class: "dv-n del"}, "−" + item.removed));
      button.addEventListener("click", () => { store("file." + key, "", item.path); draw(); });
      return button;
    });
    const list = h("nav", {class: "dv-files", "aria-label": t("desk.diff.file"), "data-keep": "dv-files." + key}, picks);
    const shown = h("div", {class: "dv-shown"});
    const draw = () => {
      const item = chosen(), file = diffs.get(item.path);
      picks.forEach((button, index) => button.classList.toggle("on", files[index] === item));
      const modes = h("span", {class: "dv-modes"}, MODES.map((name) => {
        const button = h("button", {type: "button", class: "dv-mode" + (name === mode() ? " on" : "")}, t("desk.diff." + name));
        button.addEventListener("click", () => { store("mode", "", name); draw(); });
        return button;
      }));
      const notes = [];
      if (file.note) notes.push(h("p", {class: "sub"}, file.note));
      if (source.files && !item.text && item.action === "modify" && mode() !== "raw") notes.push(h("p", {class: "sub"}, t("desk.diff.partial")));
      if (source.cut && mode() !== "raw") notes.push(h("p", {class: "sub"}, t("desk.cut")));
      shown.replaceChildren(
        h("div", {class: "dv-bar"}, h("code", {class: "dv-path"}, item.path), modes),
        ...notes,
        mode() === "raw" ? raw() : compare(file, item.text || null, mode(), key));
    };
    draw();
    if (files.length > 1) host.append(list);
    host.append(shown);
    return host;
  }

  return {parse, rows, fold, inline, counts, create};
})();

if (typeof module !== "undefined" && module.exports) module.exports = DiffView;
