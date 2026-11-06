// This computer (1.7.11): what VS Code is started with when the board opens it, so that the agent's commands reach the tools here: tool folders put
// before PATH, and a CA bundle made for a proxy that inspects TLS. A window of its own, opened from Get ready. Needs common.js (h, t), serve.js (SERVE).
const MACHINE = (function () {
  const ask = (step, body) => SERVE.post("/api/machine", {step, ...(body || {})}).then((data) => data.result);
  const field = (caption, input) => h("label", {class: "sv-field"}, h("span", {class: "sv-cap"}, caption), input);

  function bundleLine(found) {
    const b = found.bundle;
    if (!b.path) return h("span", {class: "sv-state none", title: t("machine.ca.none.tip")}, t("machine.ca.none"));
    return h("span", {class: "sv-state ok", title: t("machine.ca.tip", {path: b.path, host: b.host || "-", proxy: b.proxy || t("machine.proxy.none"), made: b.made || "-", vars: b.vars.join(", ")})},
      "✓ " + t("machine.ca.state", {n: b.n}));
  }

  function made(result) {  // the answer of Make: whether a tool trusting only this bundle reached the address
    const tip = t("machine.ca.made.tip", {roots: result.roots || "-", n_roots: result.n_roots, added: result.added, system: result.system || 0, trust: result.trust, proxy: result.proxy || t("machine.proxy.none")});
    return result.ok ? h("span", {class: "sv-result ok", title: tip}, h("b", null, "✓"), " ", t("machine.ca.made.ok", {host: result.host, added: result.added}))
      : h("span", {class: "sv-result bad", title: tip}, h("b", null, "✗"), " ", t("machine.ca.made.bad", {why: result.why}));
  }

  function open(done) {
    const paths = h("textarea", {class: "su-in su-mono mc-paths", rows: "3", spellcheck: "false", placeholder: t("machine.paths.placeholder")});
    const pathsSaid = h("span", {class: "sv-said"});
    const savePaths = h("button", {type: "button", class: "act"}, t("machine.paths.save"));
    const found = h("div", {class: "mc-found"});
    const host = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false"});
    const proxy = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: t("machine.proxy.none")});
    const make = h("button", {type: "button", class: "act hot"}, t("machine.ca.make"));
    const drop = h("button", {type: "button", class: "act danger"}, t("machine.ca.drop"));
    const caState = h("span");
    const caInfo = h("span", {class: "sv-info", tabindex: "0"}, "\u24d8");
    const caSaid = h("span", {class: "sv-said"});
    const open_ = h("p", {class: "sub", hidden: ""}, t("machine.vscode.open"));
    const close = h("button", {type: "button", class: "act"}, t("servers.close"));
    const view = SERVE.dialog([h("h2", null, t("machine.title")), h("p", {class: "sub"}, t("machine.lead"), " ", h("span", {class: "sv-info", tabindex: "0", title: t("machine.lead.tip")}, "ⓘ")),
      h("div", {class: "win-body"},
        h("h3", {class: "mc-h"}, t("machine.paths"), " ", h("span", {class: "sv-info", tabindex: "0", title: t("machine.paths.tip")}, "ⓘ")), paths, found, h("div", {class: "sv-acts"}, savePaths, pathsSaid),
        h("h3", {class: "mc-h"}, t("machine.ca"), " ", h("span", {class: "sv-info", tabindex: "0", title: t("machine.ca.lead.tip")}, "ⓘ"), " ", caState),
        h("div", {class: "sv-fields"}, field(t("machine.ca.host"), host), field(t("machine.ca.proxy"), proxy)), h("div", {class: "sv-acts"}, make, drop, caSaid), open_),
      h("div", {class: "row win-foot"}, close)]);
    view.box.classList.add("wide", "sv-win");
    const paint = (state) => {
      paths.value = state.paths.map((item) => item.path).join("\n");
      found.replaceChildren(...state.paths.map((item) => h("span", {class: "mc-dir " + (item.found ? "ok" : "bad"), title: item.found ? (item.programs.join("\n") || "-") : t("machine.paths.gone")}, (item.found ? "✓ " : "✗ ") + item.path)));
      host.placeholder = state.default_host;
      if (!host.value) host.value = state.bundle.host || "";
      if (!proxy.value) proxy.value = state.bundle.proxy || state.proxy || "";
      caState.replaceChildren(bundleLine(state));
      caInfo.title = t("machine.ca.lead.tip", {vars: state.bundle.vars.join(", ")});
      drop.hidden = !state.bundle.path;
      open_.hidden = !state.vscode_open;
    };
    ask("state").then(paint, (error) => { caSaid.replaceChildren(h("span", {class: "bad"}, error.message)); });
    savePaths.addEventListener("click", () => {
      savePaths.disabled = true; pathsSaid.replaceChildren();
      ask("paths", {paths: paths.value.split("\n")}).then((state) => { paint(state); pathsSaid.replaceChildren(h("span", {class: "sv-result ok"}, "✓ " + t("machine.saved"))); },
        (error) => { pathsSaid.replaceChildren(h("span", {class: "bad"}, error.message)); }).then(() => { savePaths.disabled = false; });
    });
    make.addEventListener("click", () => {
      make.disabled = true; caSaid.replaceChildren(h("span", {class: "sub"}, t("machine.ca.making")));
      ask("bundle", {host: host.value.trim(), proxy: proxy.value.trim()}).then((state) => { paint(state); caSaid.replaceChildren(made(state.made)); },
        (error) => { caSaid.replaceChildren(h("span", {class: "bad"}, error.message)); }).then(() => { make.disabled = false; });
    });
    drop.addEventListener("click", () => { drop.disabled = true; ask("drop").then((state) => { paint(state); caSaid.replaceChildren(); }, (error) => { caSaid.replaceChildren(h("span", {class: "bad"}, error.message)); }).then(() => { drop.disabled = false; }); });
    close.addEventListener("click", view.close);
    if (done) { const watch = setInterval(() => { if (!view.box.isConnected) { clearInterval(watch); done(); } }, 400); }
  }

  // One line for Get ready: how many tool folders, whether there is a bundle.
  function summary() {
    return ask("state").then((found) => ({paths: found.paths.length, certs: found.bundle.path ? found.bundle.n : 0}));
  }

  return {open, summary};
})();
