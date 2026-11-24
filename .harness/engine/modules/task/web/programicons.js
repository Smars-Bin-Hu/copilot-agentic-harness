// The programs' own logos for the badge of a program row (1.8.34): PROGRAM_ICONS.svg(id) returns an <svg> for python, git, vscode, gh (the GitHub CLI shows the GitHub
// mark) and harness (the robot's head, drawn by robot.js), or null for any other id (the row keeps its text badge). The shapes are drawn here by hand, small and flat:
// the GitHub mark is GitHub's own path, the others are close likenesses (Python, Git, Visual Studio Code), not copies. The mark follows the text colour, so it is dark
// on light and light on dark, as GitHub shows it. The logos are trademarks of their owners and only name the programs the harness looks for (NOTICE).
"use strict";

const PROGRAM_ICONS = (function () {
  const NS = "http://www.w3.org/2000/svg";
  function node(name, attrs, parent) { const n = document.createElementNS(NS, name); for (const key in attrs) n.setAttribute(key, attrs[key]); if (parent) parent.append(n); return n; }
  function canvas(id, box) { return node("svg", {viewBox: box, "class": "pi pi-" + id, "aria-hidden": "true", focusable: "false"}); }
  const draw = {
    python() {  // two interlocked snakes, blue over yellow, an eye each
      const s = canvas("python", "0 0 32 32");
      node("path", {d: "M15.9 3C10.5 3 10.8 5.4 10.8 5.4V8h5.2v.9H8.6S5 8.4 5 14s3.1 5.4 3.1 5.4H10v-2.6s-.1-3.1 3.1-3.1h5.2s3 .05 3-2.9V6S21.8 3 15.9 3z", fill: "#3776AB"}, s);
      node("path", {d: "M16.1 29c5.4 0 5.1-2.4 5.1-2.4V24h-5.2v-.9h7.4S27 23.6 27 18s-3.1-5.4-3.1-5.4H22v2.6s.1 3.1-3.1 3.1h-5.2s-3-.05-3 2.9V26S10.2 29 16.1 29z", fill: "#FFD43B"}, s);
      node("circle", {cx: 13.2, cy: 5.9, r: 1, fill: "#fff"}, s); node("circle", {cx: 18.8, cy: 26.1, r: 1, fill: "#fff"}, s);
      return s;
    },
    git() {  // the orange diamond with the branch and its three nodes
      const s = canvas("git", "0 0 32 32");
      node("rect", {x: 6.2, y: 6.2, width: 19.6, height: 19.6, rx: 3, fill: "#F05033", transform: "rotate(45 16 16)"}, s);
      const g = node("g", {stroke: "#fff", "stroke-width": 1.9, "stroke-linecap": "round", fill: "none"}, s);
      node("path", {d: "M13.6 10.4v11.2M13.6 13.8l6.4 4.2"}, g);
      for (const [x, y] of [[13.6, 10.4], [13.6, 21.6], [20.2, 18.1]]) node("circle", {cx: x, cy: y, r: 2.1, fill: "#F05033"}, g);
      return s;
    },
    vscode() {  // the folded blue ribbon with its open notch
      const s = canvas("vscode", "0 0 32 32");
      node("path", {d: "M23 3.2l4 2v21.6l-4 2L11.4 18.4 6.9 21.8 5 20.8V11.2l1.9-1 4.5 3.4z", fill: "#0065A9"}, s);
      node("path", {d: "M23 3.2l4 2v21.6l-4 2z", fill: "#007ACC"}, s);
      node("path", {d: "M23 8.6v14.8L14.6 16z", fill: "#1F9CF0"}, s);
      node("path", {d: "M6.9 10.2l4.5 3.4L14.6 16l-3.2 2.4-4.5 3.4L5 20.8V11.2z", fill: "#2489CA"}, s);
      return s;
    },
    gh() {  // the GitHub mark (GitHub's octicon path), in the text colour
      const s = canvas("gh", "0 0 16 16");
      node("path", {fill: "currentColor", d: "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"}, s);
      return s;
    },
    harness() {  // the robot's head, from the project's own drawing
      if (typeof ROBOT === "undefined") return null;
      const s = ROBOT.svg({head: true}); s.classList.add("pi", "pi-harness");
      return s;
    },
  };
  function svg(id) { return Object.prototype.hasOwnProperty.call(draw, id) ? draw[id]() : null; }
  return {svg, ids: Object.keys(draw)};
})();
