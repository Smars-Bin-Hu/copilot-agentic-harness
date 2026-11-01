// Sets data-theme on <html> before the page is drawn: the person's choice (localStorage "harness.theme": light or dark), else the system's, and follows the
// system while no choice is made. Where the browser keeps nothing (a file page in a private window), the system's theme is used. The settings panel (shell.js) calls
// harnessTheme.set("light" | "dark" | "") ("" = follow the system).
// Lite is the one switch for "no blur and no motion": the class `lite` on <html> (harness.lite = "1"). Every style that blurs or moves hangs on it; harnessTheme.setLite(true | false).
(function () {
  "use strict";
  const root = document.documentElement;
  const media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  let memory = "";
  let lite = false;
  function chosen() {
    try { const value = localStorage.getItem("harness.theme"); return value === "light" || value === "dark" ? value : ""; } catch (error) { return memory; }
  }
  function apply() {
    const theme = chosen() || (media && media.matches ? "dark" : "light");
    if (root.getAttribute("data-theme") !== theme) root.setAttribute("data-theme", theme);
  }
  function liteChosen() {
    try { return localStorage.getItem("harness.lite") === "1"; } catch (error) { return lite; }
  }
  function applyLite() { root.classList.toggle("lite", liteChosen()); }
  apply();
  applyLite();
  if (media && media.addEventListener) media.addEventListener("change", apply);
  window.addEventListener("storage", () => { apply(); applyLite(); });
  window.harnessTheme = {
    get: chosen,
    set(value) {
      memory = value === "light" || value === "dark" ? value : "";
      try { if (memory) localStorage.setItem("harness.theme", memory); else localStorage.removeItem("harness.theme"); } catch (error) { /* kept in memory only */ }
      apply();
    },
    getLite: liteChosen,
    setLite(value) {
      lite = Boolean(value);
      try { if (lite) localStorage.setItem("harness.lite", "1"); else localStorage.removeItem("harness.lite"); } catch (error) { /* kept in memory only */ }
      applyLite();
    },
  };
})();
