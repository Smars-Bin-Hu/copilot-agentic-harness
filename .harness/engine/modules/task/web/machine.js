// Local (1.7.11) and Tool packs (1.7.13), two of the three windows of tools.js (the third is Connections & sign-ins, servers.js). Local: what VS Code is started with when the board opens it, so that the agent's
// commands reach the tools here: the programs, tool folders put before PATH, a CA bundle made for a proxy that inspects TLS, and the MCP switch. Tool packs: the packs the harness ships and which the company
// uses, the company's own, and those added on this computer from a folder. Needs common.js (h, t), serve.js (SERVE).
const MACHINE = (function () {
  const ask = (step, body) => SERVE.post("/api/machine", {step, ...(body || {})}).then((data) => data.result);
  const field = (caption, input, mark) => h("label", {class: "sv-field"}, h("span", {class: "sv-cap"}, caption, mark ? " " : null, mark || null), input);
  const dot = (kind, title) => h("span", {class: "su-dot " + kind, title: title || ""});  // ok (green), need (yellow), bad (red), none (grey), ring (nothing set)
  const chip = (text, kind, title) => h("span", {class: "tl-chip" + (kind ? " " + kind : ""), title: title || ""}, text);
  const link = (text, tip, go) => { const b = h("button", {type: "button", class: "tl-textlink", title: tip || ""}, text); b.addEventListener("click", go); return b; };
  const info = (key) => h("span", {class: "sv-info", tabindex: "0", title: t(key)}, "ⓘ");
  const button = (text, go) => { const b = h("button", {type: "button", class: "act kb-mini"}, text); b.addEventListener("click", go); return b; };

  // --- Local -------------------------------------------------------------------------------------------------------------------------------------------

  function bundleState(state) {  // the title line of Network: a dot, and what the bundle is
    const b = state.bundle, rec = state.recipe || {};
    if (!b.path) {
      const proxied = Boolean(rec.proxy || rec.host || state.proxy);  // a company or this computer says there is a proxy: a missing bundle is worth a look
      return [dot(proxied ? "need" : "ring"), h("span", {class: "tl-sum" + (proxied ? " need" : ""), title: t("machine.ca.none.tip")}, t("machine.ca.none.long"))];
    }
    return [dot("ok"), h("span", {class: "tl-sum ok", title: t("machine.ca.tip", {path: b.path, host: b.host || "-", proxy: b.proxy || t("machine.proxy.none"), made: b.made || "-", vars: b.vars.join(", ")})}, t(b.n === 1 ? "machine.ca.state.long.one" : "machine.ca.state.long", {n: b.n, made: (b.made || "-").slice(0, 10)}))];
  }

  function made(result) {  // the answer of Make: whether a tool trusting only this bundle reached the address
    const tip = t("machine.ca.made.tip", {roots: result.roots || "-", n_roots: result.n_roots, added: result.added, system: result.system || 0, trust: result.trust, proxy: result.proxy || t("machine.proxy.none")});
    return result.ok ? h("span", {class: "sv-result ok", title: tip}, h("b", null, "✓"), " ", t("machine.ca.made.ok", {host: result.host, added: result.added}))
      : h("span", {class: "sv-result bad", title: tip}, h("b", null, "✗"), " ", t("machine.ca.made.bad", {why: result.why}));
  }

  // Programs (1.7.37): one row per program the tool packs that are on need (and python), who needs it, where it is, or "not found" and a field for the folder it is in. Folders added are kept small below.
  function programsBlock(state, repaint, said) {
    const rec = state.recipe || {tool_folders: [], error: ""};
    const who = (row) => row.needed_by.map((item) => item.pack === "harness" ? t("machine.prog.harness") : item.why === "signin" ? t("machine.prog.signin", {pack: item.pack, program: row.program}) : item.pack).filter((x, i, all) => all.indexOf(x) === i).join(", ");
    const rows = state.programs.map((row) => {
      const parts = [dot(row.found ? "ok" : "need"), h("b", {class: "tl-pname"}, row.program), h("span", {class: "tl-pwho", title: row.needed_by.map((item) => item.pack + (item.conn ? " \u2190 " + item.conn : "")).join("\n")}, "\u2190 ", who(row)),
        h("code", {class: "tl-ppath" + (row.found ? "" : " need"), title: row.found ? row.path : t("machine.prog.missing.tip", {program: row.program})}, row.found ? row.path : t("machine.prog.missing"))];
      if (!row.found) {  // not found: the folder it is in, on the same line (it wraps on a narrow window)
        const input = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", "aria-label": t("machine.prog.here", {program: row.program}), placeholder: t("machine.prog.ph.of", {program: row.program}), value: row.hint || ""});
        const use = h("button", {type: "button", class: "act"}, t("machine.prog.use"));
        const go = () => {
          use.disabled = true; said.replaceChildren();
          ask("folder-add", {program: row.program, path: input.value.trim()}).then((next) => { repaint(next); }, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); }).then(() => { use.disabled = false; });
        };
        use.addEventListener("click", go);
        input.addEventListener("keydown", (event) => { if (isEnter(event)) go(); });
        parts.push(row.hint ? h("span", {class: "sv-own", title: t("machine.recipe.from", {value: row.hint})}, t("machine.recipe.mark")) : null, input, use);
      }
      return h("div", {class: "tl-prog", "data-focus": "prog:" + row.program}, h("div", {class: "tl-prow"}, ...parts));
    });
    const general = rec.tool_folders.filter((item) => !item.program);  // an older recipe hint names no program: shown as a hint
    const added = state.paths.map((item) => {
      const x = h("button", {type: "button", class: "mc-x", title: t("machine.paths.remove"), "aria-label": t("machine.paths.remove")}, "×");
      x.addEventListener("click", () => { ask("paths", {paths: state.paths.filter((one) => one.path !== item.path).map((one) => one.path)}).then(repaint, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); }); });
      return h("span", {class: "mc-dir " + (item.found ? "ok" : "bad"), title: item.found ? (item.programs.join("\n") || "-") : t("machine.paths.gone")}, (item.found ? "" : "✗ ") + item.path, " ", x);
    });
    return [...rows, ...(rec.error ? [h("span", {class: "bad", title: rec.error}, t("machine.recipe.bad", {error: rec.error}))] : []),
      ...general.map((item) => h("span", {class: "mc-dir hint", tabindex: "0", title: t("machine.recipe.folder.tip", {label: item.label, hint: item.hint || "-"})}, h("b", null, item.label), item.hint ? " — " + item.hint : "")),
      added.length ? h("div", {class: "mc-added"}, h("span", {class: "sub"}, t("machine.paths.added"), " "), ...added) : null].filter(Boolean);
  }

  function localPanel(ctx) {
    const said = h("span", {class: "sv-said"});
    const progs = h("div", {class: "tl-progs"});
    const host = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false"});
    const proxy = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: t("machine.proxy.none")});
    const make = h("button", {type: "button", class: "act hot"}, t("machine.ca.make"));
    const drop = h("button", {type: "button", class: "act danger"}, t("machine.ca.drop"));
    const caState = h("span", {class: "tl-sumline"});
    const caSaid = h("span", {class: "sv-said"});
    const mcp = h("span", {class: "mc-mcp"});
    const hostMark = h("span", {class: "sv-own", hidden: ""}, t("machine.recipe.mark"));
    const proxyMark = h("span", {class: "sv-own", hidden: ""}, t("machine.recipe.mark"));
    const part = (key, title, ...nodes) => h("section", {class: "tl-part", "data-part": key}, h("h3", {class: "mc-h"}, title), ...nodes);
    const body = [part("programs", [t("machine.prog.title"), " ", info("machine.prog.tip")], progs, said),
      part("network", [t("machine.net.title"), " ", info("machine.ca.lead.short"), " ", caState], h("p", {class: "tl-gsub"}, t("machine.net.lead")), h("div", {class: "sv-fields"}, field(t("machine.ca.host"), host, hostMark), field(t("machine.ca.proxy"), proxy, proxyMark)), h("div", {class: "sv-acts"}, make, drop, caSaid)),
      part("mcp", ["MCP ", info("machine.mcp.tip")], mcp, h("p", {class: "tl-gsub"}, t("machine.mcp.when")))];
    const paint = (state) => {
      progs.replaceChildren(...programsBlock(state, (next) => { paint(next); }, said));
      if (ctx.arrived) ctx.arrived();
      host.placeholder = state.default_host;
      const rec = state.recipe || {host: "", proxy: "", tool_folders: [], error: ""};  // the company's recipe fills only what the person has not set: a made bundle's own values come first
      if (!host.value) host.value = state.bundle.host || rec.host || "";
      if (!proxy.value) proxy.value = state.bundle.proxy || rec.proxy || state.proxy || "";
      for (const [input, mark, value] of [[host, hostMark, rec.host], [proxy, proxyMark, rec.proxy]]) {  // a value that is still the company's gets the mark; typing over it takes the mark away
        const sync = () => { const same = !!value && input.value.trim() === value && !(input === host ? state.bundle.host : state.bundle.proxy); mark.hidden = !same; mark.title = same ? t("machine.recipe.from", {value}) : ""; };
        sync(); input.oninput = sync;
      }
      caState.replaceChildren(...bundleState(state));
      make.textContent = t(state.bundle.path ? "machine.ca.again" : "machine.ca.make");
      make.className = "act" + (state.bundle.path ? "" : " hot");
      drop.hidden = !state.bundle.path;
      const on = state.mcp.allowed;
      const chips = [["allowed", true], ["blocked", false]].map(([word, value]) => {
        const toggle = h("button", {type: "button", class: "chip" + (on === value ? " on" : ""), "aria-pressed": String(on === value)}, t(value ? "machine.mcp.allowed" : "machine.mcp.blocked"));
        toggle.addEventListener("click", () => { if (on !== value) ask("mcp", {allowed: value}).then((next) => { paint(next); }, (error) => { caSaid.replaceChildren(h("span", {class: "bad"}, error.message)); }); });
        return toggle;
      });
      mcp.replaceChildren(...[h("span", {class: "chips"}, ...chips), state.mcp.detected === "blocked" ? h("span", {class: "sub"}, " " + t("machine.mcp.detected")) : null].filter(Boolean));
    };
    ask("state").then(paint, (error) => { caSaid.replaceChildren(h("span", {class: "bad"}, error.message)); });
    make.addEventListener("click", () => {
      make.disabled = true; caSaid.replaceChildren(h("span", {class: "sub"}, t("machine.ca.making")));
      ask("bundle", {host: host.value.trim(), proxy: proxy.value.trim()}).then((state) => { paint(state); caSaid.replaceChildren(made(state.made)); },
        (error) => { caSaid.replaceChildren(h("span", {class: "bad"}, error.message)); }).then(() => { make.disabled = false; });
    });
    drop.addEventListener("click", () => { drop.disabled = true; ask("drop").then((state) => { host.value = ""; proxy.value = ""; paint(state); caSaid.replaceChildren(); }, (error) => { caSaid.replaceChildren(h("span", {class: "bad"}, error.message)); }).then(() => { drop.disabled = false; }); });
    return {title: t("tools.local.title"), tip: t("tools.local.tip"), sub: t("tools.local.lead"), body, foot: []};
  }

  // --- Tool packs --------------------------------------------------------------------------------------------------------------------------------------

  // One pack: a dot, its name, version, whether the company uses it, one line of what it is, and a button; under it chips for what it brings (connection types, skills, links) and what it needs
  // (the programs, found or not once it is on). `ctx.go` opens Local at the program that is missing.
  function packRow(row, ctx, change) {
    const state = !row.active ? "ring" : row.errors.length ? "bad" : row.ok ? "ok" : "need";
    const badge = row.from === "harness" ? chip(t(row.used ? "machine.pack.used" : "machine.pack.notused"), row.used ? "used" : "", t(row.used ? "machine.pack.used.tip" : "machine.pack.notused.tip"))
      : row.from === "company" ? chip(t("machine.pack.company"), "", t("machine.conn.src.company.tip")) : chip(t("machine.pack.folder"), "", t("machine.conn.src.folder.tip", {path: row.from}));
    const acts = [];
    if (row.removable) {  // only a folder added here is forgotten here; a factory or company pack is turned on and off in the knowledge base (1.7.30)
      if (row.newer) acts.push(button(t("machine.conn.update"), () => change("toolpack-update", row.name)));
      const drop = button(t("machine.ca.drop"), () => { if (window.confirm(t("machine.conn.remove.ask", {name: row.name}))) change("toolpack-remove", row.name); });
      drop.classList.add("danger");
      acts.push(drop);
    } else if (row.toggle) {  // a factory pack: on or off is the knowledge base's `use` list (1.7.34)
      const flip = button(t(row.used ? "machine.conn.toggle.off" : "machine.conn.toggle.on"), () => change("toolpack-use", row.name, {on: !row.used}));
      flip.title = row.toggle === "nocompany" ? t("machine.conn.toggle.nocompany") : t(row.used ? "machine.conn.toggle.off.tip" : "machine.conn.toggle.on.tip");
      if (row.toggle === "nocompany") flip.disabled = true;
      acts.push(flip);
    }
    const needs = row.needs_all.map((item) => {
      const words = t(item.why === "signin" ? "machine.pack.needs.signin" : "machine.pack.needs", {program: item.program});
      if (!row.active) return chip(words, "", t("machine.pack.needs.off"));
      const out = chip([dot(item.found ? "ok" : "need"), words + " · " + t(item.found ? "machine.prog.found" : "machine.prog.missing")], item.found ? "" : "warn", item.found ? item.path : t("machine.prog.missing.tip", {program: item.program}));
      if (item.found) return out;
      out.append(" ", link(t("tools.local.title"), t("tools.link.tip"), () => ctx.go("local", "programs", "prog:" + item.program)));
      return out;
    });
    const brings = [...row.types.map((item) => chip(t("machine.conn.type", {label: item.label}), "", item.via === "mcp" ? t("machine.conn.type.mcp") : "")),
      row.skills ? chip(t("machine.conn.skills", {n: row.skills}) + (row.skill_label ? " · " + row.skill_label : ""), "", row.skill_names.join("\n")) : null, ...row.links.map((name) => chip(t("machine.conn.link", {name}))),
      row.mcp_rules ? chip(t("machine.conn.mcp", {n: row.mcp_rules}), "", t("machine.conn.mcp.tip")) : null, ...needs,
      row.errors.length ? chip(t("machine.pack.errors", {n: row.errors.length}), "warn", row.errors.join("\n")) : null].filter(Boolean);
    return h("div", {class: "tl-item" + (row.active ? "" : " off"), "data-focus": "pack:" + row.name},
      h("div", {class: "tl-l1"}, dot(state, t(row.active ? "machine.conn.on" : "machine.conn.off")), h("b", {class: "tl-name"}, row.name), h("span", {class: "tl-ver"}, row.version), badge,
        row.updated && row.updated.to ? chip(t("machine.conn.updated", row.updated), "", t("machine.conn.updated.tip", row.updated)) : null,
        h("span", {class: "tl-desc", title: row.description}, row.description), h("span", {class: "tl-acts"}, ...acts)),
      brings.length ? h("div", {class: "tl-l2"}, ...brings) : null);
  }

  // The window (1.7.41): three groups. Shipped with the harness: the factory packs, marked used or not by the company's knowledge base (Turn on / Turn off write its `use` list). From the company's knowledge base:
  // the packs the company wrote. Added on this computer: a folder tried here only, with its path field.
  function packsPanel(ctx) {
    const shipped = h("div", {class: "tl-items"}), company = h("div", {class: "tl-items"}), added = h("div", {class: "tl-items"});
    const heads = {shipped: h("span", {class: "mute"}), company: h("span", {class: "mute"})};
    const nokb = h("p", {class: "tl-note", hidden: ""}, t("machine.pack.nokb"));
    const group = (key, title, ...nodes) => h("section", {class: "tl-part", "data-part": key}, h("h3", {class: "mc-h"}, title), ...nodes);
    const change = (step, name, more) => ask(step, {name, ...(more || {})}).then(() => paint(), (error) => { shipped.prepend(h("p", {class: "bad"}, error.message)); });
    const none = (key) => h("p", {class: "tl-empty"}, t(key));
    const list = addedBlock(ctx, added, change);
    const paint = () => ask("toolpacks").then((found) => {
      const rows = found.toolpacks;
      const fact = rows.filter((row) => row.from === "harness"), own = rows.filter((row) => row.from === "company");
      heads.shipped.textContent = " · " + t("machine.pack.shipped.n", {n: fact.length, used: fact.filter((row) => row.used).length});
      heads.company.textContent = own.length ? " · " + own.length : "";
      nokb.hidden = Boolean(found.company);
      shipped.replaceChildren(...(fact.length ? fact.map((row) => packRow(row, ctx, change)) : [none("machine.conn.none")]));
      company.replaceChildren(...(own.length ? own.map((row) => packRow(row, ctx, change)) : [none(found.company ? "machine.pack.company.none" : "machine.pack.company.nokb")]));
      list.paint(rows.filter((row) => row.removable));
      if (ctx.arrived) ctx.arrived();
    }, (error) => { shipped.replaceChildren(h("p", {class: "bad"}, error.message)); });
    paint();
    return {title: t("tools.packs.title"), tip: t("tools.packs.tip"), sub: t("tools.packs.lead"), body: [
      group("shipped", [t("machine.pack.shipped"), heads.shipped], shipped, nokb), group("company", [t("machine.pack.company.title"), heads.company], company),
      group("added", [t("machine.added.title"), h("span", {class: "mute"}, " · " + t("machine.added.sub"))], ...list.nodes, added)], foot: []};
  }

  // Added on this computer: a path field and Add, then the packs so added (Update, Remove). An installed name asks for a second click that says what it replaces.
  function addedBlock(ctx, box, change) {
    const path = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: t("machine.conn.install.ph"), "aria-label": t("machine.conn.install.ph")});
    const install = h("button", {type: "button", class: "act"}, t("machine.pack.add"));
    const said = h("div", {class: "mc-said", "aria-live": "polite"});
    let sure = null;  // {path, name} while the second click is waited for
    const reset = () => { sure = null; install.textContent = t("machine.pack.add"); install.classList.remove("danger"); };
    const clean = () => path.value.trim().replace(/^["']+|["']+$/g, "").trim();
    path.addEventListener("input", () => { if (sure && sure.path !== clean()) { reset(); said.replaceChildren(); } });
    install.addEventListener("click", () => {
      const value = clean();
      if (!value) { said.replaceChildren(h("span", {class: "bad"}, t("machine.conn.install.empty"))); return; }
      install.disabled = true;
      ask("toolpack-add", {path: value, replace: !!sure && sure.path === value}).then((got) => {
        if (got.confirm) {
          sure = {path: value, name: got.confirm.name};
          install.textContent = t("machine.conn.replace", {from: got.confirm.installed, to: got.confirm.version});
          install.classList.add("danger");
          said.replaceChildren(h("span", {class: "sub"}, t("machine.conn.replace.ask", {name: got.confirm.name, from: got.confirm.installed, to: got.confirm.version})));
          return;
        }
        reset();
        const done = got.added;
        said.replaceChildren(h("span", {class: "ok"}, "✓ " + t("machine.conn.installed", {name: done.installed, version: done.version, n: done.skills.length}) + (got.missing.length ? " " + t("machine.conn.installed.missing", {programs: got.missing.join(", ")}) : "")));
        path.value = "";
        change("toolpacks", "");
      }, (error) => { reset(); said.replaceChildren(h("span", {class: "bad"}, error.message)); }).then(() => { install.disabled = false; });
    });
    path.addEventListener("keydown", (event) => { if (isEnter(event)) install.click(); });
    return {nodes: [h("div", {class: "su-line mc-install"}, path, install), said], paint: (rows) => { box.replaceChildren(...(rows.length ? rows.map((row) => packRow(row, ctx, change)) : [h("p", {class: "tl-empty"}, t("tools.added.none"))])); }};
  }

  // The setup form (card 3, Tool packs): how many packs are on, which are ready, which come from the harness.
  function toolpacksSummary() {
    const on = (found) => found.toolpacks.filter((row) => row.active);  // a pack that is off is not counted (1.7.34)
    return ask("toolpacks").then((found) => ({n: on(found).length, ready: on(found).filter((row) => row.ok).length, company: Boolean(found.company), names: on(found).map((row) => ({name: row.name, ok: row.ok, from: row.from === "harness" ? "harness" : row.from === "company" ? "company" : "folder"}))}));
  }

  // The setup form (card 4, Local): the programs, the certificate bundle and MCP as facts.
  function summary() {
    return ask("state").then((found) => ({paths: found.paths.length, found: found.paths.filter((item) => item.found).length, certs: found.bundle.path ? found.bundle.n : 0, host: found.bundle.path ? found.bundle.host || "" : "", proxy: found.recipe && found.recipe.proxy || found.proxy || "", company_proxy: Boolean(found.recipe && (found.recipe.proxy || found.recipe.host)),
      programs: found.programs.map((row) => ({program: row.program, found: row.found, path: row.path})), mcp: found.mcp.allowed}));
  }

  return {localPanel, packsPanel, summary, toolpacksSummary};
})();
