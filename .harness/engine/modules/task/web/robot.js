// The robot's one drawing (1.8.31): ROBOT.svg() returns its <svg>. enter.js draws the Enter screen's flat robot with it and the setup wizard's welcome page shows it; robot.css has the base colours.
// The class names (r-arm, r-body, r-core, r-headg, r-ant, r-bulb, r-head, r-visor, r-eyes, r-eye) are what enter.css and enter.js animate. bot3d.js draws the same robot from distances.
"use strict";

const ROBOT = (function () {
  const NS = "http://www.w3.org/2000/svg";
  function el(name, attrs, parent) { const node = document.createElementNS(NS, name); for (const key in attrs) node.setAttribute(key, attrs[key]); if (parent) parent.append(node); return node; }
  // svg({head: true}) draws the head only (viewBox "21 1 58 59"); `glow` adds the soft light of the eyes (class "glow" of robot.css). The whole robot is "0 0 100 106".
  function svg(options) {
    const opts = options || {}, headOnly = Boolean(opts.head);
    const r = el("svg", {viewBox: headOnly ? "21 1 58 59" : "0 0 100 106", "class": "robot" + (headOnly ? " head" : "") + (opts.glow ? " glow" : ""), "aria-hidden": "true", focusable: "false"});
    if (!headOnly) {
      const armL = el("g", {"class": "r-arm r-l"}, r), armR = el("g", {"class": "r-arm r-r"}, r);
      el("rect", {x: 17, y: 62, width: 10, height: 26, rx: 5}, armL); el("rect", {x: 73, y: 62, width: 10, height: 26, rx: 5}, armR);
      el("rect", {"class": "r-body", x: 30, y: 56, width: 40, height: 42, rx: 13}, r); el("circle", {"class": "r-core", cx: 50, cy: 77, r: 6}, r);
    }
    const headG = el("g", {"class": "r-headg"}, r);
    el("line", {"class": "r-ant", x1: 50, y1: 16, x2: 50, y2: 7}, headG); el("circle", {"class": "r-bulb", cx: 50, cy: 6, r: 3.2}, headG);
    el("rect", {"class": "r-head", x: 24, y: 16, width: 52, height: 42, rx: 15}, headG); el("rect", {"class": "r-visor", x: 31, y: 26, width: 38, height: 22, rx: 9}, headG);
    const eyes = el("g", {"class": "r-eyes"}, headG);
    el("circle", {"class": "r-eye", cx: 42, cy: 37, r: 4.2}, eyes); el("circle", {"class": "r-eye", cx: 58, cy: 37, r: 4.2}, eyes);
    return r;
  }
  return {svg};
})();
