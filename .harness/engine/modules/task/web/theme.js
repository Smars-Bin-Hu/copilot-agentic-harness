// Sets data-theme on <html> before the page is drawn: the person's choice (localStorage "harness.theme": light or dark), else the system's, and follows the
// system while no choice is made. Where the browser keeps nothing (a file page in a private window), the system's theme is used. The settings panel of a later block calls
// harnessTheme.set("light" | "dark" | "") ("" = follow the system).
(function () {
  "use strict";
  const root = document.documentElement;
  const media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  let memory = "";
  function chosen() {
    try { const value = localStorage.getItem("harness.theme"); return value === "light" || value === "dark" ? value : ""; } catch (error) { return memory; }
  }
  function apply() {
    const theme = chosen() || (media && media.matches ? "dark" : "light");
    if (root.getAttribute("data-theme") !== theme) root.setAttribute("data-theme", theme);
  }
  apply();
  if (media && media.addEventListener) media.addEventListener("change", apply);
  window.addEventListener("storage", apply);
  window.harnessTheme = {
    get: chosen,
    set(value) {
      memory = value === "light" || value === "dark" ? value : "";
      try { if (memory) localStorage.setItem("harness.theme", memory); else localStorage.removeItem("harness.theme"); } catch (error) { /* kept in memory only */ }
      apply();
    },
  };
})();
