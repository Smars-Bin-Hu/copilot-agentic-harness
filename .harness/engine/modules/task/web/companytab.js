// The Company tab of the knowledge base window (1.7.32): what this company's agent can do, from the files in place (companyview.py gives the data, this file draws it).
// COMPANYTAB.draw(stage, found, {goMap}). Rows show names and a status dot; the details come on hover (a small laid-out window), and in the title for a touch screen.
// Needs common.js (h, t).
const COMPANYTAB = (function () {
  const STATE = {ok: "ok", denied: "down", failed: "down", unknown: "unknown", none: "none"};
  const ago = (stamp) => {
    const date = new Date(stamp || "");
    if (!stamp || isNaN(date.getTime())) return t("board.enter.sys.never");
    const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000);
    return seconds < 60 ? t("board.enter.sys.now") : seconds < 3600 ? t("board.enter.sys.min", {n: Math.floor(seconds / 60)}) : seconds < 86400 ? t("board.enter.sys.hour", {n: Math.floor(seconds / 3600)}) : t("board.enter.sys.day", {n: Math.floor(seconds / 86400)});
  };
  const dot = (state) => h("i", {class: "co-d " + (STATE[state] || "unknown")});

  // One small window for the whole tab: it follows the pointer's row, stays inside the screen, and goes when the pointer leaves.
  let pop = null, popTimer = 0;
  function popup() {
    if (pop && pop.isConnected) return pop;
    pop = h("div", {class: "co-pop", hidden: "", role: "tooltip"});
    pop.addEventListener("mouseenter", () => clearTimeout(popTimer));
    pop.addEventListener("mouseleave", () => hide(true));
    document.body.append(pop);
    return pop;
  }
  function hide(later) { clearTimeout(popTimer); popTimer = setTimeout(() => { if (pop) pop.hidden = true; }, later ? 200 : 0); }
  function hover(node, build) {  // `build()`: the nodes of the small window
    const show = () => {
      clearTimeout(popTimer);
      const box = popup();
      box.replaceChildren(...[].concat(build()).flat().filter(Boolean));
      box.hidden = false;
      const r = node.getBoundingClientRect(), w = box.offsetWidth, ph = box.offsetHeight;
      box.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + "px";
      box.style.top = (r.bottom + 6 + ph < innerHeight - 8 ? r.bottom + 6 : Math.max(8, r.top - ph - 6)) + "px";
    };
    node.setAttribute("tabindex", "0");
    node.classList.add("co-tip");
    node.addEventListener("mouseenter", show);
    node.addEventListener("mouseleave", () => hide(true));
    node.addEventListener("focus", show);
    node.addEventListener("blur", () => hide(false));
    return node;
  }
  const fact = (name, value) => value ? h("div", {class: "co-fact"}, h("span", null, name), h("b", null, value)) : null;

  const head = (key, count, ...more) => h("h3", {class: "co-h"}, t("dock.co." + key), count === undefined ? null : h("span", {class: "co-n"}, count), ...more);

  function company(found) {
    if (!found.found) return h("section", {class: "co-sec"}, head("company"), h("p", {class: "sub"}, t("dock.co.company.none")));
    const parts = [found.name ? h("b", {class: "co-name"}, found.name) : h("span", {class: "sub", title: t("dock.co.name.none.tip")}, t("dock.co.name.none"))];
    if (found.prefix) parts.push(h("span", {class: "co-chip", title: t("dock.co.prefix.tip")}, t("dock.co.prefix", {prefix: found.prefix})));
    if (found.version) parts.push(hover(h("span", {class: "co-chip"}, t("dock.co.version", {version: found.version})), () => fact(t("dock.co.made"), found.made) || h("span", null, t("dock.co.version.tip"))));
    if (found.stale) parts.push(h("span", {class: "co-chip warn", title: t("dock.co.stale.tip")}, t("dock.co.stale", {n: found.stale})));
    return h("section", {class: "co-sec"}, head("company"), h("div", {class: "co-line"}, parts));
  }

  // A line with words is shown as it is. A rule the pack did not put in words is not shown as a pattern (1.7.38): "N rules", and the patterns in the small window on hover.
  function lines(rows) {
    const said = rows.filter((row) => row.text), bare = rows.filter((row) => !row.text && row.pattern);
    return h("ul", {class: "co-lines"}, said.map((row) => h("li", null, row.text)),
      bare.length ? hover(h("li", {class: "co-bare"}, t(bare.length === 1 ? "dock.co.rules.one" : "dock.co.rules", {n: bare.length})), () => bare.map((row) => h("code", {class: "co-pat"}, row.pattern))) : null);
  }

  function pack(item) {
    const programs = item.programs.map((program) => hover(h("span", {class: "co-prog"}, dot(program.found ? "ok" : "denied"), program.name), () => h("span", null, t(program.found ? "dock.co.program.found" : "dock.co.program.missing", {name: program.name}))));
    const kinds = (rows, key) => rows.length ? h("details", {class: "co-verb"}, h("summary", null, t("dock.co." + key), h("span", {class: "co-n"}, rows.length)), lines(rows)) : null;
    const links = item.connections.map((link) => hover(h("span", {class: "co-conn"}, link.state === "none" ? null : dot(link.state), link.name), () => [
      h("b", null, link.name), fact(t("board.enter.sys.col.env"), link.env && link.env !== "none" ? link.env.toUpperCase() : ""), fact(t("board.enter.sys.col.status"), link.state === "none" ? t("dock.co.conn.mcp") : t("board.enter.sys.state." + (STATE[link.state] || "unknown"))),
      fact(t("dock.co.conn.who"), link.who), fact(t("board.enter.sys.col.reason"), link.why), fact(t("board.enter.sys.col.checked"), link.state === "unknown" || !link.at ? t("board.enter.sys.never") : ago(link.at)),
      fact(t("dock.co.conn.type"), link.type), link.own ? h("span", {class: "sub"}, t("dock.co.conn.own")) : null]));
    const missing = item.missing.map((code) => {
      const program = code.startsWith("program:") ? code.slice(8) : "";
      return h("span", {class: "co-miss", title: t("dock.co.miss." + (program ? "program" : code) + ".tip", {name: program})}, t("dock.co.miss." + (program ? "program" : code), {name: program}));
    });
    return h("div", {class: "co-pack"},
      h("div", {class: "co-line"}, hover(h("b", {class: "co-name"}, item.name), () => [h("b", null, item.name), item.about ? h("span", null, item.about) : null, ...item.types.map((kind) => h("span", {class: "sub"}, kind.label + " (" + kind.type + (kind.via === "mcp" ? ", MCP" : "") + ")"))]),
        item.version ? h("span", {class: "co-chip"}, item.version) : null, programs, missing),
      kinds((item.read_names || []).map((name) => ({text: name})), "reads"), kinds(item.writes, "writes"), kinds(item.execs, "execs"), kinds(item.destroys, "destroys"),
      item.connections.length ? h("div", {class: "co-line co-conns"}, h("span", {class: "sub"}, t("dock.co.conns")), links) : null);
  }

  function unknownPack(name) {  // a name in the company's `use` that no factory pack has (1.7.34)
    return h("div", {class: "co-pack"}, h("div", {class: "co-line"}, hover(h("b", {class: "co-name"}, name), () => [h("b", null, name), h("span", null, t("dock.co.unknown.tip", {name}))]),
      h("span", {class: "co-miss", title: t("dock.co.unknown.tip", {name})}, t("dock.co.unknown"))));
  }

  // The tools the company selected (1.7.38): grouped as the skills are, the company's own packs first, then the factory packs it turns on, then a folder tried on this computer.
  // Change opens the Tool packs window, where a factory pack is turned on or off.
  function toolsSection(found, options) {
    const unknown = found.unknown_use || [];
    const change = h("button", {type: "button", class: "act kb-mini co-change", title: t("dock.co.tools.change.tip")}, t("dock.co.tools.change"));
    change.addEventListener("click", () => { if (options.goTools) options.goTools(); });
    const groups = [["company", found.tools.filter((item) => item.source === "company")], ["harness", found.tools.filter((item) => item.source === "harness")], ["added", found.tools.filter((item) => item.source !== "company" && item.source !== "harness")]];
    return h("section", {class: "co-sec"}, head("tools", found.tools.length, change),
      groups.map(([key, rows]) => rows.length ? h("details", {class: "co-group", open: ""}, h("summary", null, t("dock.co.tools." + key), h("span", {class: "co-n"}, rows.length)), rows.map((item) => pack(item))) : null),
      unknown.map(unknownPack), found.tools.length || unknown.length ? null : h("p", {class: "sub"}, t("dock.co.tools.none")));
  }

  function skill(item) {
    return hover(h("div", {class: "co-skill"}, h("b", {class: "co-sname"}, item.name), item.synced ? null : h("span", {class: "co-miss", title: t("dock.co.unsynced.tip")}, t("dock.co.unsynced")), h("span", {class: "co-about"}, item.about)),
      () => [h("b", null, item.name), item.about ? h("span", null, item.about) : null, item.pack ? h("span", {class: "sub"}, t("dock.co.skill.pack", {pack: item.pack})) : null, item.synced ? null : h("span", {class: "sub"}, t("dock.co.unsynced.tip"))]);
  }

  function skillsSection(found, options) {
    const groups = [["company", found.skills.company], ["pack", found.skills.pack], ["harness", found.skills.harness]];
    const total = groups.reduce((sum, [, rows]) => sum + rows.length, 0);
    return h("section", {class: "co-sec"}, head("skills", total), groups.map(([key, rows]) => rows.length ? h("details", {class: "co-group", open: key !== "harness" ? "" : null},
      h("summary", null, t("dock.co.skills." + key), h("span", {class: "co-n"}, rows.length)), rows.map((row, index) => [row.pack && (!index || rows[index - 1].pack !== row.pack) ? h("h4", {class: "co-sub"}, row.pack) : null, skill(row)])) : null),
      domainLink(options));
  }

  function domainLink(options) {  // the domain skills have their own tab: a way there, not a copy (1.7.38)
    if (!options.goDomains) return null;
    const go = h("button", {type: "button", class: "co-link"}, t("dock.co.skills.domains"));
    go.addEventListener("click", options.goDomains);
    return h("p", {class: "sub co-domains"}, go);
  }

  function filesSection(found) {
    const rows = [...found.standards.map((row) => ({...row, kind: "standards"})), ...found.instructions.map((row) => ({...row, kind: "instructions"}))];
    const good = (state) => state === "copied" || state === "inplace";
    return h("section", {class: "co-sec"}, head("standards", rows.length), rows.length ? rows.map((row) => hover(h("div", {class: "co-file"}, h("code", null, row.file), row.state ? h("span", {class: good(row.state) ? "co-chip" : "co-miss"}, t("dock.co.file." + row.state)) : null, h("span", {class: "co-about"}, row.first)),
      () => [h("b", null, row.file), h("span", null, row.first), h("span", {class: "sub"}, t("dock.co." + row.kind + ".one")), row.state ? h("span", {class: "sub"}, t("dock.co.file." + row.state + ".tip")) : null])) : h("p", {class: "sub"}, t("dock.co.standards.none")));
  }

  function draw(stage, found, options) {
    stage.classList.add("co-stage");
    const given = options || {};
    stage.replaceChildren(company(found), toolsSection(found, given), skillsSection(found, given), filesSection(found));  // the domains have their own tab: not repeated here (1.7.35)
  }
  const clear = () => { if (pop) pop.hidden = true; };
  return {draw, clear};
})();
