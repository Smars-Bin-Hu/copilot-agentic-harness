// Settings (O4): the window the gear opens. A column of sections on the left (a row of chips on a narrow window), the section on the right. Most sections are the pages of the setup wizard drawn
// again without its steps (`WIZARD.mount`, wizard.js): You, Programs, Copilot, Knowledge base, Code repositories. Tool packs, Connections and Network are what machine.js and servers.js draw
// (`MACHINE.packsPanel`, `SERVERS.connectionsPanel`, `MACHINE.localPanel`); Advanced uses the old form's steps (`/api/setup` act, refuse, older; `/api/machine` mcp).
// Every old way in leads here: `SETTINGS.open(section, {done, part, focus})`; readyui.js, dock.js, tools.js and servers.js call it. A small yellow dot on a section: something of it is not set up (the notes of `/api/ready`).
// Needs common.js (h, t), serve.js (SERVE), readyui.js (READY), wizard.js (WIZARD), machine.js (MACHINE), servers.js (SERVERS), dock.js (DOCK, the folder picker).
"use strict";

const SETTINGS = (function () {
  const SECTIONS = ["you", "programs", "copilot", "kb", "packs", "repos", "connections", "network", "adv"];
  const LABELS = {you: "wizard.s.you", programs: "wizard.s.prog", copilot: "wizard.s.cop", kb: "wizard.s.kb", packs: "tools.packs.title", repos: "settings.s.repos", connections: "settings.s.connections", network: "machine.net.title", adv: "settings.s.adv"};
  const ALIASES = {company: "kb", computer: "programs", setup: "you", local: "network", tools: "packs", advanced: "adv", repositories: "repos", prog: "programs", cop: "copilot", repo: "repos"};
  const NOTE_SECTION = {kb: "kb", instructions: "kb", skills: "kb", standards: "kb", sync: "kb", packs: "packs", connections: "connections", connlist: "connections", identity: "connections", signin: "connections", down: "connections", held: "connections", cert: "network", repos: "repos"};
  const ask = (path, step, body) => SERVE.post(path, {step, ...(body || {})}).then((data) => data.result);
  const put = (node, ...children) => node.replaceChildren(...children.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false));
  const errorText = (error) => String((error && error.message) || error || "");
  const sectionOf = (name) => { const key = ALIASES[name] || name; return SECTIONS.includes(key) ? key : "you"; };

  let win = null;  // the window that is open: {view, show}

  // ------------------------------------------------------------------------------------------------ the dots: what is not set up, by section
  function dotsOf(list, hold) {
    const out = new Set();
    (list || []).forEach((note) => { if (NOTE_SECTION[note.key]) out.add(NOTE_SECTION[note.key]); });
    if (hold) {  // what the wizard's pages know: the name, the programs, Copilot
      const M = WIZARD.M;
      if (M.st && !String(M.st.name || "").trim()) out.add("you");
      if (M.progs && !M.progs.all_found) out.add("programs");
      const line = ((M.ready && M.ready.checks) || []).find((one) => one.id === "copilot");
      if (line && line.state !== "ok" && !["host-starting", "host-preparing", "connecting", "models"].includes(line.why)) out.add("copilot");
    }
    return out;
  }

  // ------------------------------------------------------------------------------------------------ the window
  function open(name, opts) {
    const given = opts || {};
    const first = sectionOf(name || "you");
    if (win) { win.show(first, given.part, given.focus); return; }
    let stop = null, changed = false, token = 0, hold = false, dots = new Set();
    const nav = h("nav", {class: "st-nav", "aria-label": t("dock.setup")});
    const heading = h("h3", {class: "st-title"});
    const x = h("button", {type: "button", class: "st-x", "aria-label": t("board.new.close"), title: t("board.new.close")}, "✕");
    const body = h("div", {class: "st-body wz"});
    const pane = h("div", {class: "st-pane"}, h("div", {class: "st-head"}, heading, x), body);
    const view = SERVE.dialog([h("div", {class: "st-side"}, h("h2", {class: "st-h"}, t("dock.setup")), nav), pane]);
    view.box.classList.add("st-win");
    const items = SECTIONS.map((id) => {
      const mark = h("i", {class: "st-dot", hidden: ""});
      const node = h("button", {type: "button", class: "st-i", "data-sec": id}, h("span", {class: "st-n"}, t(LABELS[id])), mark);
      node.addEventListener("click", () => show(id));
      return {id, node, mark};
    });
    put(nav, items.map((item) => [item.id === "adv" ? h("div", {class: "st-sep"}) : null, item.node]));
    const refreshDots = () => {
      dots = dotsOf(typeof READY !== "undefined" ? READY.current() : [], hold);
      items.forEach((item) => { const on = dots.has(item.id); item.mark.hidden = !on; item.node.classList.toggle("hot", on); });
    };
    if (typeof READY !== "undefined") READY.onNotes(() => { if (win && win.view === view) refreshDots(); });
    const stopPart = () => { if (stop) { try { stop(); } catch (error) { /* a part that is gone */ } stop = null; } };
    let left = false, watch = 0;
    const leave = () => { if (left) return; left = true; clearInterval(watch); stopPart(); if (win && win.view === view) win = null; if (changed) location.reload(); else if (given.done) given.done(); };  // once: the X, a close from outside and the watch below all end here; the name, the knowledge base or the repositories changed: the page reads them again
    x.addEventListener("click", () => { view.close(); leave(); });
    watch = setInterval(() => { if (!view.box.isConnected) leave(); }, 300);  // the dialog closes itself on Escape

    // what to scroll to once the section has drawn (a part or a row): asked again as it fills in, for a few seconds
    let want = null, until = 0;
    const reveal = () => {
      if (!want || Date.now() > until) { want = null; return; }
      const row = want.focus ? [...body.querySelectorAll("[data-focus]")].find((node) => node.dataset.focus === want.focus) : null;
      const node = row || (want.part ? body.querySelector('[data-part="' + want.part + '"]') : null);
      if (!node) return;
      pane.scrollTop = Math.max(0, node.getBoundingClientRect().top - body.getBoundingClientRect().top - 4);
      if (row) { row.classList.remove("tl-flash"); void row.offsetWidth; row.classList.add("tl-flash"); want = null; }
    };
    // what machine.js and servers.js ask of their window: go to another section at a part
    const ctx = {
      go: (sec, part, focus) => { const target = sec === "local" ? (part === "network" ? "network" : part === "mcp" ? "adv" : "packs") : sec; show(sectionOf(target), part, focus); },
      close: () => { view.close(); leave(); }, arrived: () => reveal(),
    };
    const saved = () => { changed = true; };

    function show(id, part, focus) {
      stopPart();
      const mine = ++token;
      want = part || focus ? {part, focus} : null; until = Date.now() + 4000;
      items.forEach((item) => { item.node.classList.toggle("on", item.id === id); item.node.setAttribute("aria-current", item.id === id ? "page" : "false"); });
      heading.textContent = t(LABELS[id]);
      body.className = "st-body wz st-sec-" + id;
      pane.scrollTop = 0;
      put(body, h("p", {class: "st-wait"}, h("span", {class: "wz-spin"}), " ", t("settings.loading")));
      const live = () => mine === token && win && win.view === view;
      const env = {
        live, saved, refresh: () => { if (live()) refreshDots(); }, jump: (sec) => show(sec),
        inside: (nodes, stopper) => { if (!live()) { if (stopper) stopper(); return; } stop = stopper || null; put(body, nodes); reveal(); },
      };
      const draw = {you: wizardSection, programs: wizardSection, copilot: wizardSection, kb: wizardSection, repos: wizardSection, packs: packsSection, connections: connectionsSection, network: networkSection, adv: advancedSection}[id];
      Promise.resolve(draw(id, env)).catch((error) => { if (live()) put(body, h("p", {class: "bad"}, errorText(error))); });
    }

    // the sections that are pages of the wizard: prepared (read again), drawn bare, with a Save of their own where the page saves
    function wizardSection(id, env) {
      return WIZARD.prepare().then(() => {
        hold = true;
        if (!env.live()) return;
        const holder = h("div"), foot = h("div", {class: "st-foot"}), said = h("span", {class: "st-saved", role: "status"});
        let ctl = null, timer = 0;
        const savedNote = () => { said.textContent = "✓ " + t("settings.saved"); saved(); clearTimeout(timer); timer = setTimeout(() => { said.textContent = ""; }, 4000); env.refresh(); };
        const footer = () => {
          if (!ctl || !["you", "repos"].includes(id)) return;
          const main = ctl.foot().main, off = id === "you" && main.off;
          const button = h("button", {type: "button", class: "wz-btn primary" + (off ? " off" : "")}, t("settings.save"));
          button.addEventListener("click", () => { if (!off) main.go(); });  // the repositories may be saved with none: the page's own button wants one
          put(foot, button, said);
        };
        const draw = () => {
          if (ctl && ctl.stop) ctl.stop();
          ctl = WIZARD.mount(id, holder, {changed: footer, rerender: () => { if (env.live()) draw(); }, saved: savedNote, jump: (n) => env.jump(n === 2 ? "programs" : n === 3 ? "copilot" : "you")});
          footer();
        };
        draw();
        env.inside([id === "repos" ? h("p", {class: "st-sub"}, t("settings.repos.sub")) : null, holder, foot], () => { if (ctl && ctl.stop) ctl.stop(); clearTimeout(timer); });
        env.refresh();
      });
    }

    // Tool packs: with a knowledge base, the window of machine.js (and the programs the packs need); without one the factory packs are listed grey, and say who turns them on
    function packsSection(id, env) {
      return ask("/api/setup", "state").then((state) => {
        if (state.kb && state.kb.here) {
          const packs = MACHINE.packsPanel(ctx), local = MACHINE.localPanel(ctx);
          env.inside([h("p", {class: "st-sub"}, packs.sub), ...packs.body, ...local.body.filter((node) => node.dataset && node.dataset.part === "programs")]);
          return null;
        }
        return ask("/api/machine", "toolpacks").then((found) => {
          const rows = (found.toolpacks || []).filter((row) => row.from === "harness" && !row.sample);  // a sample pack (demotracker) is not a tool a newcomer has: not listed until a knowledge base turns it on (1.8.32)
          const list = h("div", {class: "st-packlist"}, rows.map((row) => h("div", {class: "st-pack"}, h("span", {class: "st-pdot"}), h("b", null, row.name), h("span", {class: "tl-ver"}, row.version || ""), h("span", {class: "st-pdesc", title: row.description || ""}, row.description || ""))));
          env.inside([h("p", {class: "st-sub"}, t("tools.packs.lead")), h("p", {class: "st-note"}, t("settings.packs.nokb")), list]);
        });
      });
    }

    function connectionsSection(id, env) {
      const made = SERVERS.connectionsPanel(ctx);
      env.inside([h("p", {class: "st-sub"}, made.sub), ...made.body, h("div", {class: "st-foot"}, ...made.foot)]);
    }

    function networkSection(id, env) {
      const made = MACHINE.localPanel(ctx, {bare: true});  // the window already says Network: the part does not say it again (1.8.32)
      env.inside([h("p", {class: "st-sub"}, made.sub), ...made.body.filter((node) => node.dataset && node.dataset.part === "network")]);
    }

    // Advanced: the Python install command, the paths not to touch, the skill prefix and the older copy go through `save` (part advanced), `refuse` and `older`; MCP is machine.js's switch
    function advancedSection(id, env) {
      return ask("/api/setup", "state").then((state) => {
        const rules = state.rules.slice(), refused = [];
        const field = (caption, node, hint) => h("div", {class: "wz-field"}, h("span", {class: "cap"}, caption), node, hint ? h("div", {class: "hint"}, hint) : null);
        const literal = (text) => text.split("{package}").flatMap((part, i) => (i ? [h("code", null, "{package}"), part] : [part]));  // `{package}` is a placeholder the person types: it always shows as it is, in the code font
        const install = h("input", {type: "text", class: "wz-in mono", maxlength: 500, autocomplete: "off", spellcheck: "false", placeholder: t("setup.install.ph"), value: state.install_command || "", "aria-label": t("setup.install")});
        const prefix = h("input", {type: "text", class: "wz-in mono st-short", maxlength: 31, autocomplete: "off", spellcheck: "false", value: state.skill_prefix || (state.kb && state.kb.prefix) || "", "aria-label": t("setup.prefix")});
        const path = h("input", {type: "text", class: "wz-in mono", maxlength: 1024, autocomplete: "off", spellcheck: "false", placeholder: state.example, "aria-label": t("setup.refused")});
        const add = h("button", {type: "button", class: "wz-btn sm", disabled: ""}, t("setup.refused.add"));
        const list = h("div", {class: "st-chips"}), said = h("p", {class: "wz-err"}), done = h("span", {class: "st-saved", role: "status"});
        said.hidden = true;
        const paintRules = () => {
          const chip = (text, off) => { const b = h("button", {type: "button", class: "st-cx", "aria-label": t("setup.refused.remove"), title: t("setup.refused.remove")}, "×"); b.addEventListener("click", () => { off(); paintRules(); }); return h("span", {class: "st-chip"}, h("code", null, text), b); };
          put(list, rules.map((rule) => chip(rule.repo + ": " + rule.rule, () => { rules.splice(rules.indexOf(rule), 1); })), refused.map((one) => chip(one, () => { refused.splice(refused.indexOf(one), 1); })));
        };
        const addPath = () => {
          if (!path.value.trim()) return;
          ask("/api/setup", "refuse", {repos_root: state.repos_root, singles: state.singles, path: path.value}).then((found) => { said.hidden = true; path.value = ""; add.disabled = true; if (!refused.includes(found.path)) refused.push(found.path); paintRules(); }, (error) => { said.textContent = errorText(error); said.hidden = false; });
        };
        path.addEventListener("input", () => { add.disabled = !path.value.trim(); });
        path.addEventListener("keydown", (event) => { if (isEnter(event)) addPath(); });
        add.addEventListener("click", addPath);
        paintRules();
        const save = h("button", {type: "button", class: "wz-btn primary"}, t("settings.save"));
        save.addEventListener("click", () => {
          said.hidden = true; done.textContent = ""; save.disabled = true;
          const values = {part: "advanced", skill_prefix: prefix.value, install_command: install.value, refused, rules, stamp: state.stamp};  // three fields: no knowledge base sync and no doctor
          ask("/api/setup", "save", values).then(() => {
            saved(); done.textContent = "✓ " + t("settings.saved");
            return ask("/api/setup", "state").then((now) => { state.stamp = now.stamp; refused.splice(0); rules.splice(0, rules.length, ...now.rules); paintRules(); });
          }).catch((error) => { said.textContent = errorText(error); said.hidden = false; }).then(() => { save.disabled = false; });
        });
        const older = h("button", {type: "button", class: "wz-btn sm"}, t("settings.adv.older.go"));
        older.addEventListener("click", () => olderDialog(saved));
        const made = MACHINE.localPanel(ctx);
        env.inside([
          field(t("setup.install"), install, literal(t("setup.install.example"))),
          field(t("setup.refused"), h("div", {class: "st-add"}, path, add), t("setup.refused.hint")), h("div", {class: "st-under"}, list), said,
          field(t("setup.prefix"), prefix, t("setup.prefix.hint")),
          h("div", {class: "st-line"}, save, done),
          h("div", {class: "st-rule"}), made.body.find((node) => node.dataset && node.dataset.part === "mcp"),
          h("div", {class: "st-rule"}), restartRow(),
          h("div", {class: "st-rule"}), field(t("setup.older.title"), h("div", null, older), t("setup.older.hint")),
        ]);
      });
    }

    win = {view, show};
    show(first, given.part, given.focus);
    refreshDots();
    // the notes may not be known yet (a page that has no block of the board asks slowly): ask once now
    SERVE.call("/api/ready", {}, 8).then((data) => { if (typeof READY !== "undefined" && Array.isArray(data.checks)) READY.notes(data.notes); }, () => {});
  }

  // Restart board (1.8.32: it was in the sliders panel, now Appearance): the same button and texts; SHELL.restartBoard waits for the new process and pairs again
  function restartRow() {
    const said = h("div", {class: "sp-bad", role: "alert", hidden: "hidden"});
    const go = h("button", {type: "button", class: "wz-btn sm"}, t("board.shell.restart"));
    go.addEventListener("click", () => SHELL.restartBoard(go, (words) => { said.textContent = words; said.hidden = false; }));
    return h("div", {class: "wz-field st-restart"}, h("span", {class: "cap"}, t("board.shell.restart.label")), h("div", null, go), h("div", {class: "hint"}, t("board.shell.restart.hint")), said);
  }

  // Coming from an older copy: look at what would come over, then bring it (the step `older` of the old form)
  function olderDialog(saved) {
    const path = h("input", {class: "code", autocomplete: "off", spellcheck: "false", placeholder: t("setup.older.ph"), "aria-label": t("setup.older.title")});
    const look = h("button", {type: "button", class: "act"}, t("setup.older.look"));
    const apply = h("button", {type: "button", class: "act hot", hidden: ""}, t("setup.older.apply"));
    const no = h("button", {type: "button", class: "act"}, t("board.new.close"));
    const out = h("div", {class: "st-older"});
    const dialog = SERVE.dialog([h("h2", null, t("setup.older.title")), h("p", {class: "sub"}, t("setup.older.hint")), path, out, h("div", {class: "row"}, look, apply, no)]);
    no.addEventListener("click", dialog.close);
    const groups = (list) => h("div", {class: "chips"}, Object.entries(list || {}).map(([group, names]) => h("span", {class: "chip", title: names.join("\n")}, group + " · " + names.length)));
    const folded = (key, list) => ((list || []).length ? h("details", {class: "st-older-list"}, h("summary", null, t(key, {n: list.length})), list.map((item) => h("div", {class: "st-older-row"}, h("code", null, item.what), " ", h("span", {class: "sub"}, item.why)))) : null);
    const busy = (key) => {
      const began = Date.now(), line = h("p", {class: "sub", role: "status"});
      const tick = () => { line.textContent = t(key, {time: clock((Date.now() - began) / 1000)}); };
      tick();
      const timer = setInterval(tick, 1000);
      put(out, line);
      path.disabled = look.disabled = apply.disabled = true;
      return () => { clearInterval(timer); path.disabled = look.disabled = apply.disabled = false; };
    };
    look.addEventListener("click", () => {
      const end = busy("setup.older.looking");
      ask("/api/setup", "older", {path: path.value}).then((found) => { end(); put(out, h("p", {class: "sub"}, t("setup.older.from", {from: found.from})), groups(found.would_copy), folded("setup.older.skipped.n", found.skipped)); apply.hidden = false; }, (error) => { end(); put(out, errorText(error)); });
    });
    apply.addEventListener("click", () => {
      const end = busy("setup.older.carrying");
      ask("/api/setup", "older", {path: path.value, apply: true}).then((found) => {
        end(); saved(); apply.hidden = true; look.hidden = true;
        const copied = Object.values(found.copied || {}).reduce((sum, names) => sum + names.length, 0);
        put(out, h("p", {class: "sub"}, t("setup.older.from", {from: found.from})),
          h("p", null, h("b", null, String(copied)), " ", t("setup.older.count.copied"), " · ", h("b", null, String((found.failed || []).length)), " ", t("setup.older.count.failed"), " · ", h("b", null, String((found.skipped || []).length)), " ", t("setup.older.count.skipped")),
          groups(found.copied), folded("setup.older.failed.n", found.failed), folded("setup.older.skipped.n", found.skipped));
      }, (error) => { end(); put(out, errorText(error)); });
    });
  }

  // The page loaded again after the language was chosen in the You section: the window comes back at that section
  try {
    const kept = sessionStorage.getItem("harness.reopen") || "";
    if (kept.startsWith("settings") && typeof DATA !== "undefined" && DATA.serve) { sessionStorage.removeItem("harness.reopen"); setTimeout(() => open(kept.split(":")[1] || "you"), 0); }
  } catch (error) { /* then the window stays shut */ }

  return {open, sections: SECTIONS, isOpen: () => Boolean(win)};  // isOpen: space.js keeps its slow-motion note away while the window is open (1.8.32)
})();
