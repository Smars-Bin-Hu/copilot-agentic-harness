// The stop button (1.8.11): a small icon at the top right of every served page, next to the Terminal toggle, shown only to a paired browser. A click asks once, then the board
// stops (`POST /api/shutdown`) and the page says so and asks for nothing more: every timer, every request and every redraw of the page ends.
"use strict";

const STOP = (function () {
  function icon() {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("width", "14");
    svg.setAttribute("height", "14");
    svg.setAttribute("aria-hidden", "true");
    for (const [tag, attrs] of [["path", {d: "M4.6 3.6a6 6 0 1 0 6.8 0"}], ["path", {d: "M8 1.5v6"}]]) {
      const part = document.createElementNS(ns, tag);
      part.setAttribute("fill", "none");
      part.setAttribute("stroke", "currentColor");
      part.setAttribute("stroke-width", "1.7");
      part.setAttribute("stroke-linecap", "round");
      for (const name of Object.keys(attrs)) part.setAttribute(name, attrs[name]);
      svg.append(part);
    }
    return svg;
  }
  // After the stop nothing may ask the server again: the timers and the redraws end, a request that is still made never comes back, and the page is replaced by one sentence.
  function stopped() {
    window.fetch = () => new Promise(() => {});
    window.requestAnimationFrame = () => 0;
    for (let id = window.setTimeout(() => {}, 0); id > 0; id--) { window.clearTimeout(id); window.clearInterval(id); }
    document.querySelectorAll('meta[http-equiv="refresh"]').forEach((node) => node.remove());
    document.documentElement.className = "";  // the Enter screen hides `main` with a class of the page
    document.body.className = "board-stopped-page";
    document.body.replaceChildren(h("div", {class: "board-stopped", role: "status"}, h("p", null, t("board.stop.done"))));
  }
  function mount() {
    if (typeof SERVE === "undefined") return;
    const button = h("button", {type: "button", class: "board-stop", title: t("board.stop.tip"), "aria-label": t("board.stop.tip"), hidden: ""});
    button.append(icon());
    button.addEventListener("click", () => {
      if (!window.confirm(t("board.stop.confirm"))) return;
      button.disabled = true;
      SERVE.call("/api/shutdown", {}, 10).then(stopped, (error) => { button.disabled = false; window.alert(t("board.stop.failed", {error: error.message})); });
    });
    document.body.append(button);
    SERVE.ready.then(() => SERVE.call("/api/status", {}, 8)).then((data) => { button.hidden = !data.paired; }, () => {});
  }
  return {mount, stopped};
})();
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", STOP.mount); else STOP.mount();
