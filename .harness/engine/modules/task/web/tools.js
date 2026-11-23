// Tools (1.7.38): Tool packs, Connections & sign-ins and Local. Since O4 they are sections of the Settings window (settings.js), which draws the panels of machine.js (packs, local) and servers.js (connections);
// `open(tab, done, part)` stays for the callers that name a tab, and leads there. The old setup form draws the facts (`facts()`).
// Needs common.js (h, t), serve.js (SERVE), servers.js (SERVERS), machine.js (MACHINE).
const TOOLS = (function () {
  const WINDOWS = ["packs", "connections", "local"];

  // The names before 1.7.38: "company" was the packs and the connections together, "computer" the programs, network, sign-ins, MCP and packs added from a folder. A part that moved goes to its new window.
  function where(tab, part) {
    part = part || "";
    if (tab === "company") return part === "connections" ? ["connections", ""] : ["packs", part === "packs" ? "" : part];
    if (tab === "computer") tab = "local";
    if (tab === "local" && part === "signins") return ["connections", ""];
    if (tab === "local" && part === "added") return ["packs", "added"];
    return [WINDOWS.includes(tab) ? tab : "packs", part];
  }

  // The three windows are sections of Settings now (settings.js): Tool packs, Connections and Network (a part of Local; its programs are in Tool packs, MCP in Advanced).
  function open(tab, done, part) {
    const [at, where_] = where(tab, part);
    const section = at === "local" ? ({network: "network", mcp: "adv"}[where_] || "packs") : at;
    const focus = at === "local" && section === "packs" ? "programs" : where_;
    SETTINGS.open(section, {done, part: focus || undefined});
  }

  // The setup form: the three summaries in one go, each null when it cannot be read. setup.js draws them as facts of its cards.
  function facts() {
    return Promise.all([MACHINE.toolpacksSummary(), SERVERS.summary(), MACHINE.summary()].map((promise) => promise.catch(() => null))).then(([packs, conns, pc]) => ({packs, conns, pc}));
  }

  return {open, facts};
})();
