// Settings (O4): the window the gear opens. A column of sections on the left (a row of chips on a narrow window), the section on the right. Most sections are the pages of the setup wizard drawn
// again without its steps (`WIZARD.mount`, wizard.js): You, Programs, Copilot, Knowledge base, Code repositories. Tool packs, Connections and Network are what machine.js and servers.js draw
// (`MACHINE.packsPanel`, `SERVERS.connectionsPanel`, `MACHINE.localPanel`); Advanced uses the old form's steps (`/api/setup` act, refuse, older; `/api/machine` mcp).
// Every old way in leads here: `SETTINGS.open(section, {done, part, focus})`; readyui.js, dock.js, tools.js and servers.js call it. A small yellow dot on a section: something of it is not set up (the notes of `/api/ready`).
// Needs common.js (h, t), serve.js (SERVE), readyui.js (READY), wizard.js (WIZARD), machine.js (MACHINE), servers.js (SERVERS), dock.js (DOCK, the folder picker).
"use strict";

const SETTINGS = (function () {
  const SECTIONS = ["you", "programs", "copilot", "kb", "packs", "repos", "connections", "adv"];  // Network is a part of Advanced since 1.8.34 (`network` and `local` still open it)
  const GROUPS = [["settings.g.harness", ["you", "programs", "copilot"]], ["settings.g.company", ["kb", "packs", "repos", "connections"]]];  // two groups under small headings, then Advanced alone (1.8.34)
  const LABELS = {you: "wizard.s.you", programs: "wizard.s.prog", copilot: "wizard.s.cop", kb: "wizard.s.kb", packs: "tools.packs.title", repos: "settings.s.repos", connections: "settings.s.connections", adv: "settings.s.adv"};
  const ALIASES = {company: "kb", computer: "programs", setup: "you", local: "adv", network: "adv", tools: "packs", advanced: "adv", repositories: "repos", prog: "programs", cop: "copilot", repo: "repos"};
  const NOTE_SECTION = {kb: "kb", instructions: "kb", skills: "kb", standards: "kb", sync: "kb", packs: "packs", connections: "connections", connlist: "connections", identity: "connections", signin: "connections", down: "connections", held: "connections", cert: "adv", repos: "repos"};
  const ask = (path, step, body) => SERVE.post(path, {step, ...(body || {})}).then((data) => data.result);
  const put = (node, ...children) => node.replaceChildren(...children.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false));
  const errorText = (error) => String((error && error.message) || error || "");
  const sectionOf = (name) => { const key = ALIASES[name] || name; return SECTIONS.includes(key) ? key : "you"; };

  let win = null;  // the window that is open: {view, show}
  let footNow = null;  // the foot of the left list that is open: Sign out from the Copilot page asks it to read the account again (1.8.35)

  // ------------------------------------------------------------------------------------------------ how it moves (1.8.34, motion.js; nothing here moves under Lite or the system's reduced motion but a fade)
  // The window grows out of the gear it was opened with (scale .96 to 1 and opacity, 280 ms; the shade 200 ms) and leaves the same way (200 ms); opened from elsewhere (a fix button, the palette): from its centre.
  let lastDown = {node: null, at: 0};
  document.addEventListener("pointerdown", (event) => { lastDown = {node: event.target, at: performance.now()}; }, true);
  const gearOf = () => {  // the avatar of the account menu (topmenu.js, 1.8.39; the gear before) when the person pressed or focused it just now, else null
    const gear = document.querySelector(".hd-av");
    if (!gear || !gear.isConnected) return null;
    const pressed = lastDown.node && gear.contains(lastDown.node) && performance.now() - lastDown.at < 800;
    return pressed || gear.contains(document.activeElement) ? gear : null;
  };
  const moves = () => typeof MOTION !== "undefined";
  const cut = (node) => { for (const running of (node.getAnimations ? node.getAnimations() : [])) running.cancel(); };
  const SHRINK = "scale(.96)";
  const LEAVE = 100, ARRIVE = 160;  // a section out in 100 ms and in over 160 ms, the selection glides as long as the content comes in: no pane is empty for longer than a frame
  // grow(box, shade, gear): the way in; returns the way out for the same window
  function grow(box, shade, gear) {
    if (!moves()) return () => {};
    document.body.classList.add("st-open");
    const at = box.getBoundingClientRect(), from = gear ? gear.getBoundingClientRect() : null;
    box.style.transformOrigin = (from ? from.left + from.width / 2 - at.left : at.width / 2) + "px " + (from ? from.top + from.height / 2 - at.top : at.height / 2) + "px";
    MOTION.play(box, [{opacity: 0, transform: SHRINK}, {opacity: 1, transform: "none"}], {ms: MOTION.MS.window});
    MOTION.play(shade, [{opacity: 0}, {opacity: 1}], {ms: MOTION.MS.show});
    return () => {  // the window is gone from the page (X, Esc, a click beside it, a close from outside): its shade comes back, inert, for 200 ms, and fades
      cut(box); cut(shade);
      document.body.classList.remove("st-open");
      document.body.append(shade);
      shade.inert = true;
      shade.style.pointerEvents = "none";
      Promise.all([
        MOTION.play(box, [{opacity: 1, transform: "none"}, {opacity: 0, transform: SHRINK}], {ms: MOTION.MS.show, ease: MOTION.OUT, fill: "forwards"}),
        MOTION.play(shade, [{opacity: 1}, {opacity: 0}], {ms: MOTION.MS.show, ease: MOTION.OUT, fill: "forwards"}),
      ]).then(() => shade.remove());
    };
  }
  // what a section looks like while it loads (S3): grey bars [width %, height px] in the shape of what comes
  const BAR = {sub: [70, 16], field: [100, 40], label: [24, 14], row: [100, 52], short: [60, 40]};
  const SHAPES = {
    you: ["sub", "label", "short", "label", "field"], programs: ["sub", "row", "row", "row", "row"], copilot: ["sub", "row", "row"], kb: ["sub", "label", "field", "row", "row", "row"],
    packs: ["sub", "row", "row", "row", "row"], repos: ["sub", "row", "row", "row"], connections: ["sub", "row", "row", "row"], network: ["sub", "label", "field", "label", "field"], adv: ["label", "field", "label", "field", "label", "short"],
  };
  const skeleton = (id) => h("div", {class: "st-skel", role: "status", "aria-label": t("settings.loading")}, (SHAPES[id] || SHAPES.you).map((kind) => h("div", {class: "st-sk " + kind, style: "width:" + BAR[kind][0] + "%;height:" + BAR[kind][1] + "px"})));

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
    const side = h("div", {class: "st-side"}, h("h2", {class: "st-h"}, t("dock.setup")), nav);
    const view = SERVE.dialog([side, pane]);
    view.box.classList.add("st-win");
    const shade = view.box.parentNode;
    const vanish = grow(view.box, shade, gearOf());
    let closing = false;
    const closer = new MutationObserver(() => { if (shade.isConnected || closing) return; closing = true; closer.disconnect(); vanish(); });  // any way of closing removes the shade: one place to move it out
    closer.observe(document.body, {childList: true});
    let queued = null;
    win = {view, show: (...asked) => { queued = asked; }};  // asked for before the rest is built: it goes to the section asked last
    const build = () => {  // the rest of the window is built in a task of its own: one task would be over 100 ms at 4x CPU (GOAL 12) (1.8.34)
      if (closing) { if (win && win.view === view) win = null; if (given.done) given.done(); return; }
      const items = SECTIONS.map((id) => {
        const mark = h("i", {class: "st-dot", hidden: ""});
        const node = h("button", {type: "button", class: "st-i", "data-sec": id}, h("span", {class: "st-n"}, t(LABELS[id])), mark);
        node.addEventListener("click", () => show(id));
        return {id, node, mark};
      });
      const sel = h("i", {class: "st-sel", "aria-hidden": "true"});  // the selected item's background: one block that glides to the item chosen (S2); in the narrow window the chips draw their own
      const place = (item) => { if (!item) return; Object.assign(sel.style, {left: item.node.offsetLeft + "px", top: item.node.offsetTop + "px", width: item.node.offsetWidth + "px", height: item.node.offsetHeight + "px"}); };
      put(nav, sel, GROUPS.map(([key, ids]) => h("div", {class: "st-grp", role: "group", "aria-label": t(key)}, h("div", {class: "st-gh"}, t(key)), ids.map((id) => items.find((item) => item.id === id).node))), h("div", {class: "st-grp st-alone"}, items.find((item) => item.id === "adv").node));
      let current = null;
      const relayout = () => { if (closing) window.removeEventListener("resize", relayout); else if (current) place(items.find((item) => item.id === current)); };
      window.addEventListener("resize", relayout);
      const refreshDots = () => {
        dots = dotsOf(typeof READY !== "undefined" ? READY.current() : [], hold);
        items.forEach((item) => { const on = dots.has(item.id); item.mark.hidden = !on; item.node.classList.toggle("hot", on); });
      };
      if (typeof READY !== "undefined") READY.onNotes(() => { if (win && win.view === view) refreshDots(); });
      const stopPart = () => { if (stop) { try { stop(); } catch (error) { /* a part that is gone */ } stop = null; } };
      let left = false, watch = 0;
      const leave = () => { if (left) return; left = true; clearInterval(watch); stopPart(); if (win && win.view === view) win = null; if (changed) location.reload(); else if (given.done) given.done(); };  // once: the X, a close from outside and the watch below all end here; the name, the knowledge base or the repositories changed: the page reads them again
      x.addEventListener("click", () => { view.close(); leave(); });
      watch = setInterval(() => { if (!view.box.isConnected || closing) leave(); }, 300);  // the dialog closes itself on Escape

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
        go: (sec, part, focus) => { const target = sec === "local" ? (part === "network" || part === "mcp" ? "adv" : "packs") : sec; show(sectionOf(target), part, focus); },
        close: () => { view.close(); leave(); }, arrived: () => reveal(),
      };
      const saved = () => { changed = true; };

      // The section area (S2, S3): the old section fades out (120 ms), the new one rises 8 px and fades in (200 ms); while it loads, grey bars stand in. One section is on screen at a time: a burst of
      // clicks shares the one fade out and only the last click lands.
      let fading = null;
      const fadeOut = () => {
        if (fading) return fading;
        if (!body.firstChild || !moves()) return Promise.resolve();
        const from = Number(getComputedStyle(body).opacity);
        const frames = [{opacity: Number.isFinite(from) ? from : 1}, {opacity: 0}];
        cut(body); cut(heading);
        const run = Promise.all([body, heading].map((node) => MOTION.play(node, frames, {ms: LEAVE, ease: MOTION.OUT, fill: "forwards"}))).then(() => { fading = null; });
        fading = run;
        return run;
      };
      const leaveBars = () => {  // the grey bars go (120 ms) before the section comes in: the title stays
        const from = Number(getComputedStyle(body).opacity);
        cut(body);
        return MOTION.play(body, [{opacity: Number.isFinite(from) ? from : 1}, {opacity: 0}], {ms: LEAVE, ease: MOTION.OUT, fill: "forwards"});
      };
      const rise = () => { if (!moves()) return; cut(body); cut(heading); MOTION.appear(body, {y: 8, ms: ARRIVE}); MOTION.appear(heading, {ms: ARRIVE}); };

      function show(id, part, focus) {
        stopPart();
        const mine = ++token;
        want = part || focus ? {part, focus} : null; until = Date.now() + 4000;
        const target = items.find((item) => item.id === id);
        const select = () => {
          items.forEach((item) => { item.node.classList.toggle("on", item.id === id); item.node.setAttribute("aria-current", item.id === id ? "page" : "false"); });
          place(target);
        };
        if (current && moves()) MOTION.glide(sel, select, ARRIVE); else select();
        current = id;
        const first = !body.firstChild;
        let ready = null, parted = false, onSkeleton = false, skeletonAt = 0;
        const arrive = (nodes) => {  // the section has drawn (or failed): in once the old one has left; over the grey bars with a fade of their own
          if (!parted) { ready = {nodes}; return; }
          if (!onSkeleton) { put(body, nodes); reveal(); return; }
          const land = () => { if (mine !== token) return; onSkeleton = false; cut(body); put(body, nodes); if (moves()) MOTION.appear(body, {y: 8, ms: ARRIVE}); reveal(); };
          if (first || performance.now() - skeletonAt < 120 || !moves()) land();  // the window's own opening covers the first one else leaveBars().then(land);
        };
        fadeOut().then(() => {
          if (mine !== token) return;
          parted = true;
          heading.textContent = t(LABELS[id]);
          body.className = "st-body wz st-sec-" + id;
          pane.scrollTop = 0;
          cut(body); cut(heading);
          if (ready) put(body, ready.nodes); else { put(body, skeleton(id)); onSkeleton = true; skeletonAt = performance.now(); }
          if (!first) rise();
          if (ready) reveal();
        });
        const live = () => mine === token && win && win.view === view;
        const env = {
          live, saved, refresh: () => { if (live()) refreshDots(); }, jump: (sec) => show(sec),
          inside: (nodes, stopper) => { if (!live()) { if (stopper) stopper(); return; } stop = stopper || null; arrive(nodes); },
        };
        const draw = {you: wizardSection, programs: wizardSection, copilot: wizardSection, kb: wizardSection, repos: wizardSection, packs: packsSection, connections: connectionsSection, adv: advancedSection}[id];
        Promise.resolve(draw(id, env)).catch((error) => { if (live()) arrive([h("p", {class: "bad"}, errorText(error))]); });
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

      // Advanced: the Python install command, the paths not to touch, the older copy go through `save` (part advanced), `refuse` and `older`; MCP is machine.js's switch
      function advancedSection(id, env) {
        return ask("/api/setup", "state").then((state) => {
          const rules = state.rules.slice(), refused = [];
          const field = (caption, node, hint) => h("div", {class: "wz-field"}, h("span", {class: "cap"}, caption), node, hint ? h("div", {class: "hint"}, hint) : null);
          const literal = (text) => text.split("{package}").flatMap((part, i) => (i ? [h("code", null, "{package}"), part] : [part]));  // `{package}` is a placeholder the person types: it always shows as it is, in the code font
          const install = h("input", {type: "text", class: "wz-in mono", maxlength: 500, autocomplete: "off", spellcheck: "false", placeholder: t("setup.install.ph"), value: state.install_command || "", "aria-label": t("setup.install")});
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
            const values = {part: "advanced", skill_prefix: state.skill_prefix || "",  /* the field is gone: the server writes the prefix on every Advanced save, so the one it holds goes back unchanged */ install_command: install.value, refused, rules, stamp: state.stamp};  // three fields: no knowledge base sync and no doctor
            ask("/api/setup", "save", values).then(() => {
              saved(); done.textContent = "✓ " + t("settings.saved");
              return ask("/api/setup", "state").then((now) => { state.stamp = now.stamp; refused.splice(0); rules.splice(0, rules.length, ...now.rules); paintRules(); });
            }).catch((error) => { said.textContent = errorText(error); said.hidden = false; }).then(() => { save.disabled = false; });
          });
          const older = h("button", {type: "button", class: "wz-btn sm"}, t("settings.adv.older.go"));
          older.addEventListener("click", () => olderDialog(saved));
          const made = MACHINE.localPanel(ctx, {stacked: true, title: t("settings.adv.net")});  // the Network part opens Advanced (1.8.34)
          env.inside([
            made.body.find((node) => node.dataset && node.dataset.part === "network"), h("div", {class: "st-rule"}),
            field(t("setup.install"), install, literal(t("setup.install.example"))),
            field(t("setup.refused"), h("div", {class: "st-add"}, path, add), t("setup.refused.hint")), h("div", {class: "st-under"}, list), said,
            h("div", {class: "st-line"}, save, done),
            h("div", {class: "st-rule"}), made.body.find((node) => node.dataset && node.dataset.part === "mcp"),
            h("div", {class: "st-rule"}), field(t("setup.older.title"), h("div", null, older), t("setup.older.hint")),
          ]);
        });
      }

      const foot = footOf(show); footNow = foot;  // the account and Restart board, at the bottom of the left list
      side.append(foot.node); foot.refresh();
      const footTimer = setInterval(() => { if (!view.box.isConnected || closing) clearInterval(footTimer); else foot.refresh(); }, 10000);
      win = {view, show};
      show(...(queued || [first, given.part, given.focus]));
      refreshDots();
      // the notes may not be known yet (a page that has no block of the board asks slowly): ask once now
      SERVE.call("/api/ready", {}, 8).then((data) => { if (typeof READY !== "undefined" && Array.isArray(data.checks)) READY.notes(data.notes); }, () => {});
    };
    setTimeout(build, 0);
  }

  // The foot of the left list (1.8.34): the GitHub account with Sign out, and Restart board. Both ask first (a window, as the prototype C-settings shows).
  function confirmDialog(title, paragraphs, goLabel, act) {
    const said = h("p", {class: "wz-err", role: "alert", hidden: ""});
    const no = h("button", {type: "button", class: "wz-btn sm"}, t("board.serve.cancel"));
    const go = h("button", {type: "button", class: "wz-btn sm primary"}, goLabel);
    const dialog = SERVE.dialog([h("h2", null, title), ...paragraphs.map((text) => h("p", {class: "sub"}, text)), said, h("div", {class: "row"}, no, go)]);
    dialog.box.classList.add("st-confirm", "wz");
    no.addEventListener("click", dialog.close);
    go.addEventListener("click", () => act(go, dialog, (words) => { said.textContent = words; said.hidden = false; }));
    return dialog;
  }
  function restartAsk() {
    confirmDialog(t("settings.restart.title"), [t("board.shell.restart.hint")], t("settings.restart.go"), (go, dialog, fail) => SHELL.restartBoard(go, fail));
  }
  function signOutAsk(done) {
    confirmDialog(t("settings.out.title"), [t("settings.out.one"), t("settings.out.two")], t("settings.out.go"), (go, dialog, fail) => {
      go.disabled = true;
      SERVE.post("/api/gh", {do: "logout"}).then(() => { dialog.close(); done(); }, (error) => { fail(errorText(error)); go.disabled = false; });
    });
  }
  function footOf(show) {
    const login = h("b", {class: "st-login"}), line = h("span", {class: "st-wline"}), out = h("button", {type: "button", class: "st-link"}, t("settings.who.signout"));
    const signin = h("button", {type: "button", class: "st-link"}, t("settings.who.signin"));
    const mark = typeof PROGRAM_ICONS !== "undefined" ? PROGRAM_ICONS.svg("gh") : null;
    const who = h("div", {class: "st-who"}, h("span", {class: "st-wmark"}, mark), h("div", {class: "st-wtext"}, login, h("div", {class: "st-wsub"}, line, " ", out, signin)));
    const restart = h("button", {type: "button", class: "wz-btn sm st-restart"}, t("board.shell.restart"));
    restart.addEventListener("click", restartAsk);
    const paint = (check) => {
      const on = typeof WIZARD !== "undefined" && WIZARD.signedIn ? WIZARD.signedIn(check) : Boolean(check && check.login);  // the Copilot page's rule, so the two never disagree (1.8.36)
      login.textContent = on ? check.login || "" : "";
      line.textContent = t(on ? "settings.who.line" : "settings.who.none");
      login.hidden = !on || !check.login; out.hidden = !on; signin.hidden = on;  // signed in with no account name read: no name, never a made-up one
    };
    const refresh = () => SERVE.call("/api/ready", {}, 8).then((data) => paint(((data && data.checks) || []).find((one) => one.id === "copilot")), () => {});
    out.addEventListener("click", () => signOutAsk(() => { paint(null); refresh(); }));
    signin.addEventListener("click", () => show("copilot"));
    paint(null);
    // (1.8.33) the whole setup guide again, step by step: /setup draws it for a copy that is set up too, and a copy that is set up stays so (wizard.mark), so leaving it halfway changes nothing
    const walk = h("button", {type: "button", class: "st-walk"}, h("span", {class: "st-walk-i", "aria-hidden": "true"}, "\u21bb"), h("span", null, t("settings.walk")));
    walk.addEventListener("click", () => location.assign("/setup"));  // no reload first: what Settings saved is on disk, the wizard reads it
    return {node: h("div", {class: "st-foot2 wz"}, who, walk, restart), refresh};  // the account, the guide again, Restart board (1.8.34)
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

  // (1.8.35) The Copilot page's Sign out is the foot's: the same window and request; `done` runs after it, and the foot reads the account again.
  const signOut = (done) => signOutAsk(() => { if (done) done(); if (footNow) footNow.refresh(); });
  return {open, signOut, restart: restartAsk, sections: SECTIONS, isOpen: () => Boolean(win)};  // restart: the account menu's Restart board asks the same way (1.8.39)  // isOpen: space.js keeps its slow-motion note away while the window is open (1.8.32)
})();
