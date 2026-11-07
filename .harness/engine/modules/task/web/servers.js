// Servers (1.7.10): the servers of the company pack and the person's own, each with the person's identity, tested before it is kept; and "Open VS Code
// with identities", where the person picks which identities this window holds. A window of its own, opened from Get ready and from the Enter screen.
// The server (`/api/servers`) never sends a password back: a saved one shows as a mark. Needs common.js (h, t), serve.js (SERVE).
const SERVERS = (function () {
  const ask = (step, body) => SERVE.post("/api/connections", {step, ...(body || {})}).then((data) => data.result);
  const ENV_ORDER = ["dev", "ist", "qat", "prod"];
  const MARK = {ok: "✓", denied: "✗", down: "✗", failed: "✗", missing: "✗", mcp: "\u2192"};
  const keep = (key, value) => { try { localStorage.setItem("harness.servers." + key, JSON.stringify(value)); } catch (error) { /* a convenience only */ } };
  const kept = (key, fallback) => { try { const found = localStorage.getItem("harness.servers." + key); return found ? JSON.parse(found) : fallback; } catch (error) { return fallback; } };

  const field = (caption, input) => h("label", {class: "sv-field"}, h("span", {class: "sv-cap"}, caption), input);  // a field keeps its name once it is filled
  function envChip(env) { return env === "none" ? h("span", {class: "sv-env", title: t("connections.env.none.tip")}, "\u2014") : h("span", {class: "sv-env sv-env-" + env}, env.toUpperCase()); }
  function where(row) { const f = row.fields || {}; return [f.host, f.port].filter(Boolean).join(":") || Object.values(f).filter(Boolean).join(" · "); }
  function result(found) {  // a test's answer: a mark and a short word, the reason on hover
    const word = found.timeout ? t("connections.state.timeout", {seconds: found.timeout}) : t("connections.state." + found.state);
    const tip = found.timeout ? t("connections.tip.timeout", {seconds: found.timeout}) : found.state === "ok" ? t("connections.tip.ok", {who: found.who || "-", seconds: found.seconds}) : found.state === "missing" || found.state === "mcp" ? found.why : found.state === "failed" && found.why && !/^exit-\d+$/.test(found.why) ? t("connections.tip.failed") + "\n" + found.why : t("connections.tip." + found.state);
    return h("span", {class: "sv-result " + (found.state === "ok" || found.state === "mcp" ? "ok" : "bad"), title: tip}, h("b", null, MARK[found.state] || "?"), " ", word);
  }

  // One server: a line (environment, name, kind, where, what is saved), and when opened, its identity, Test and Save.
  function serverRow(row, redraw) {
    const line = h("button", {type: "button", class: "sv-line" + (row.saved ? " saved" : ""), "aria-expanded": "false",
      title: [...new Set([row.alias, row.label])].concat([row.type_label + (row.auth_label ? " · " + row.auth_label : ""), where(row)]).filter(Boolean).join("\n")},
      envChip(row.env), h("b", {class: "sv-alias"}, row.alias), h("code", {class: "sv-where"}, where(row)),
      row.own ? h("span", {class: "sv-own", title: t("connections.own.tip")}, t("connections.own")) : null,
      row.toolpack ? h("span", {class: "sv-own sv-from", title: t("connections.from.tip", {pack: row.toolpack})}, row.toolpack) : null,
      h("span", {class: "sv-state " + (row.saved ? "ok" : "none"), title: row.saved ? t("connections.saved.tip", {account: row.account || "-"}) : t("connections.none.tip")}, row.saved ? "✓ " + (row.account || t("connections.saved")) : t("connections.none")));
    const box = h("div", {class: "sv-form", hidden: ""});
    let drawn = false;
    line.addEventListener("click", () => {
      const open = box.hidden;
      box.hidden = !open; line.setAttribute("aria-expanded", String(open));
      if (open && !drawn) { drawn = true; box.append(...identityForm(row, null, redraw)); }
      if (open) { const first = box.querySelector("input"); if (first) first.focus(); }
    });
    return h("div", {class: "sv-row"}, line, box);
  }

  // Forgetting a connection of the person's own takes the connection and its identity away, and nothing brings it back: one more click, within a few seconds (1.7.22). A connection of a tool pack or the company
  // only loses the identity: it is still listed, and one click is enough.
  function sure(button, row, run) {
    if (!row.own || button.dataset.sure) { run(); return; }
    const label = button.textContent;
    button.dataset.sure = "1"; button.textContent = t("connections.forget.sure"); button.title = t("connections.forget.sure.tip", {name: row.alias});
    setTimeout(() => { if (!button.isConnected) return; delete button.dataset.sure; button.textContent = label; button.removeAttribute("title"); }, 5000);
  }

  // The identity of a server, tested before it is kept. `own`: the fields of a server of the person's own (kind, env, auth, host, ...), or null.
  function identityForm(row, own, redraw) {
    if (row.identity === "tool") return toolForm(row, own, redraw);
    const needsKey = row.identity === "keyfile";
    const token = row.identity === "token";  // one secret under the label of the auth entry (1.7.21): no account box
    const account = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: row.identity === "netonly" ? "DOMAIN\\id" : t("connections.account"), value: row.account || ""});
    const password = h("input", {class: "su-in su-mono", type: "password", autocomplete: "new-password", placeholder: row.saved ? t("connections.password.kept") : (token ? row.auth_label || t("connections.password") : t("connections.password"))});
    const keyfile = needsKey ? h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: t("connections.keyfile")}) : null;
    const said = h("span", {class: "sv-said"});
    const test = h("button", {type: "button", class: "act"}, t("connections.test"));
    const save = h("button", {type: "button", class: "act hot", disabled: ""}, t("connections.save"));
    const forget = row.saved ? h("button", {type: "button", class: "act danger"}, t("connections.forget")) : null;
    const values = () => ({alias: (own ? own.alias() : row.alias), account: account.value.trim(), password: password.value, keyfile: keyfile ? keyfile.value.trim() : "", own: own ? own.fields() : undefined});
    const changed = () => { save.disabled = true; said.replaceChildren(); };
    [account, password, keyfile].filter(Boolean).forEach((input) => input.addEventListener("input", changed));
    test.addEventListener("click", () => {
      test.disabled = true; save.disabled = true; said.replaceChildren(h("span", {class: "sub"}, t("connections.testing")));
      ask("test", values()).then((found) => { said.replaceChildren(result(found)); save.disabled = !["ok", "mcp"].includes(found.state); }, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); })
        .then(() => { test.disabled = false; });
    });
    save.addEventListener("click", () => {
      save.disabled = true;
      ask("save", values()).then(() => { password.value = ""; redraw(); }, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); });
    });
    if (forget) forget.addEventListener("click", () => sure(forget, row, () => { forget.disabled = true; ask("forget", {alias: row.alias}).then(redraw, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); forget.disabled = false; }); }));
    password.addEventListener("keydown", (event) => { if (event.key === "Enter" && !test.disabled) test.click(); });
    return [h("div", {class: "sv-fields"}, token ? null : field(t("connections.account"), account), field(token ? row.auth_label || t("connections.password") : t("connections.password"), password), keyfile ? field(t("connections.keyfile"), keyfile) : null), h("div", {class: "sv-acts"}, test, save, forget, said)];
  }

  // A server whose program keeps its own sign-in (1.7.13): nothing to type. Test runs the kind's check; Save keeps only the name it answered with.
  function toolForm(row, own, redraw) {
    const said = h("span", {class: "sv-said"});
    const test = h("button", {type: "button", class: "act"}, t("connections.test"));
    const save = h("button", {type: "button", class: "act hot", disabled: ""}, t("connections.save"));
    const forget = row.saved ? h("button", {type: "button", class: "act danger"}, t("connections.forget")) : null;
    const values = () => ({alias: own ? own.alias() : row.alias, account: "", password: "", keyfile: "", own: own ? own.fields() : undefined});
    test.addEventListener("click", () => {
      test.classList.remove("hot", "live");
      test.disabled = true; save.disabled = true; said.replaceChildren(h("span", {class: "sub"}, t("connections.testing")));
      ask("test", values()).then((found) => { said.replaceChildren(result(found)); save.disabled = found.state !== "ok"; }, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); })
        .then(() => { test.disabled = false; });
    });
    save.addEventListener("click", () => { save.disabled = true; ask("save", values()).then(redraw, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); }); });
    if (forget) forget.addEventListener("click", () => sure(forget, row, () => { forget.disabled = true; ask("forget", {alias: row.alias}).then(redraw, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); forget.disabled = false; }); }));
    const signIn = row.login && typeof TERM !== "undefined" ? h("button", {type: "button", class: "act", title: row.login}, t("connections.tool.login")) : null;  // the kind's own sign-in, in the Terminal window
    const word = (text) => (/^[\w.:@\/-]+$/.test(text) ? text : '"' + String(text).replace(/"/g, "") + '"');
    const signedIn = () => { test.classList.add("hot", "live"); said.replaceChildren(h("span", {class: "sv-retest"}, t("connections.tool.retest"))); };  // the sign-in ran to its end: the person tests again (1.7.19)
    if (signIn) signIn.addEventListener("click", () => {
      if (!own) { TERM.run("harness connections login " + row.alias, signedIn); return; }
      const fields = own.fields();  // not saved yet: the kind and the fields typed so far
      const name = own.alias() || "new";
      TERM.run(["harness connections login", word(name), "--type", word(fields.type), ...Object.entries(fields).filter(([key, value]) => !["type", "env"].includes(key) && value).map(([key, value]) => "--set " + word(key + "=" + value))].join(" "), signedIn);
    });
    return [h("p", {class: "sub sv-tool"}, t(row.saved ? "connections.tool.saved" : "connections.tool.hint", {account: row.account || ""})), h("div", {class: "sv-acts"}, signIn, test, save, forget, said)];
  }

  // A server of the person's own: a kind of this copy, its fields, its environment and way in, a name; then the same identity, test and save.
  function ownForm(kinds, redraw) {
    const names = Object.keys(kinds);
    if (!names.length) return h("p", {class: "sub"}, t("connections.own.nokind"));
    const kind = h("select", {class: "su-in"}, names.map((name) => h("option", {value: name}, kinds[name].label)));
    const alias = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: t("connections.own.alias")});
    const env = h("select", {class: "su-in", required: ""}, h("option", {value: ""}, t("connections.own.env.pick")), ["dev", "ist", "qat"].map((name) => h("option", {value: name}, name.toUpperCase())), h("option", {value: "none"}, t("connections.env.none")));  // no environment chosen for you: a wrong one is easy to miss
    const auth = h("select", {class: "su-in"});
    const fields = h("div", {class: "sv-fields"});
    const rest = h("div");
    let inputs = {};
    const draw = () => {
      const spec = kinds[kind.value];
      auth.replaceChildren(...Object.entries(spec.auth).map(([mode, item]) => h("option", {value: mode}, item.label)));
      inputs = {};
      fields.replaceChildren(...Object.entries(spec.fields).map(([name, item]) => field(item.label + (item.optional ? " " + t("connections.optional") : ""), (inputs[name] = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: item.placeholder || "", value: item.default || ""})))));
      drawIdentity();
    };
    const drawIdentity = () => {
      const spec = kinds[kind.value];
      const row = {alias: "", identity: (spec.auth[auth.value] || {}).identity, login: (spec.auth[auth.value] || {}).login || "", auth_label: (spec.auth[auth.value] || {}).label || "", saved: false, account: ""};
      rest.replaceChildren(...identityForm(row, {alias: () => alias.value.trim(), fields: () => ({type: kind.value, env: env.value, auth: auth.value, ...Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value.trim()]))})}, redraw));
    };
    kind.addEventListener("change", draw);
    auth.addEventListener("change", drawIdentity);
    draw();
    return h("div", {class: "sv-own-form"}, h("div", {class: "sv-fields"}, field(t("connections.own.kind"), kind), field(t("connections.own.name"), alias), field(t("connections.own.env"), env), field(t("connections.own.auth"), auth)), fields, rest);
  }

  // The Servers window.
  // The Connections tab of the Tools window (tools.js): the connections grouped by type, each with the tool pack it comes from; one's own added below.
  function panel(ctx) {
    const list = h("div", {class: "sv-list"}, h("p", {class: "sub"}, t("connections.loading")));
    const addBox = h("details", {class: "sv-add"}, h("summary", null, t("connections.own.add")));
    const launch = h("button", {type: "button", class: "act hot"}, t("connections.open"));
    const out = h("button", {type: "button", class: "act", title: t("connections.export.tip")}, t("connections.export"));
    const redraw = () => ask("list").then((found) => {
      const rows = found.connections.slice().sort((a, b) => a.type_label.localeCompare(b.type_label) || ENV_ORDER.indexOf(a.env) - ENV_ORDER.indexOf(b.env) || a.alias.localeCompare(b.alias));
      const groups = [];
      rows.forEach((row) => { if (!groups.length || groups[groups.length - 1].label !== row.type_label) groups.push({label: row.type_label, rows: []}); groups[groups.length - 1].rows.push(row); });
      list.replaceChildren(...(rows.length ? groups.flatMap((group) => [h("div", {class: "sv-grp"}, group.label), ...group.rows.map((row) => serverRow(row, redraw))]) : [h("p", {class: "sub"}, t("connections.empty"))]));
      addBox.replaceChildren(h("summary", null, t("connections.own.add")), ownForm(found.types, redraw));
      launch.disabled = !rows.some((row) => row.saved);
      launch.title = launch.disabled ? t("connections.open.nothing") : "";
      out.disabled = !rows.some((row) => row.own);
      if (ctx.changed) ctx.changed();
    }, (error) => { list.replaceChildren(h("p", {class: "bad"}, error.message)); });
    launch.addEventListener("click", () => { ctx.close(); choose(); });
    out.addEventListener("click", () => exportWindow());
    redraw();
    return {body: [h("p", {class: "sub"}, t("connections.lead"), " ", h("span", {class: "sv-info", tabindex: "0", title: t("connections.lead.tip")}, "\u24d8")), list, addBox], foot: [launch, out]};
  }

  // Export: one's own connections in the form of connections.json (no account, no password): copy it, save it as a file, or put it in the company pack.
  function exportWindow() {
    const text = h("pre", {class: "sv-json"}, t("connections.loading"));
    const copy = h("button", {type: "button", class: "act"}, t("connections.export.copy"));
    const file = h("button", {type: "button", class: "act"}, t("connections.export.file"));
    const share = h("button", {type: "button", class: "act hot", title: t("connections.export.share.tip")}, t("connections.export.share"));
    const said = h("span", {class: "sv-said"});
    const close = h("button", {type: "button", class: "act"}, t("connections.close"));
    const view = SERVE.dialog([h("h2", null, t("connections.export")), h("p", {class: "sub"}, t("connections.export.lead")), h("div", {class: "win-body"}, text), h("div", {class: "row win-foot"}, share, copy, file, said, close)]);
    view.box.classList.add("wide", "sv-win");
    let found = null;
    ask("export").then((data) => { found = data; text.textContent = JSON.stringify(data, null, 2); }, (error) => { text.replaceChildren(h("span", {class: "bad"}, error.message)); });
    copy.addEventListener("click", () => { if (found && navigator.clipboard) navigator.clipboard.writeText(JSON.stringify(found, null, 2) + "\n").then(() => said.replaceChildren(h("span", {class: "sv-result ok"}, "\u2713"))); });
    file.addEventListener("click", () => {
      if (!found) return;
      const link = h("a", {href: URL.createObjectURL(new Blob([JSON.stringify(found, null, 2) + "\n"], {type: "application/json"})), download: "connections.json"});
      document.body.append(link); link.click(); link.remove();
    });
    share.addEventListener("click", () => {
      if (!found) return;
      share.disabled = true;
      ask("share", {aliases: Object.keys(found.connections)}).then((done) => { said.replaceChildren(h("span", {class: "sv-result ok", title: done.file}, "\u2713 " + t("connections.export.shared"))); }, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); share.disabled = false; });
    });
    close.addEventListener("click", view.close);
  }

  function open(done) {
    if (typeof TOOLS !== "undefined") TOOLS.open("connections", done);
  }

  // One line for Get ready and the Enter screen: how many servers, how many with the person's identity.
  function summary() {
    return ask("list").then((found) => ({n: found.connections.length, saved: found.connections.filter((row) => row.saved).length}));
  }

  // "Open VS Code with identities": tick the identities this window holds; those that cannot share it are reached through `harness as`, marked so.
  function choose(opened) {  // `opened`: what the page does once VS Code was started with the identities (the Enter screen waits for it, 1.7.19)
    const list = h("div", {class: "sv-list"}, h("p", {class: "sub"}, t("connections.loading")));
    const said = h("p", {class: "sub sv-plan"});
    const running = h("p", {class: "bad sv-plan", hidden: ""}, t("connections.open.running"));  // its own line: the plan does not write over it
    const go = h("button", {type: "button", class: "act hot", disabled: ""}, t("connections.open.go"));
    const close = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const view = SERVE.dialog([h("h2", null, t("connections.open.title")), h("p", {class: "sub"}, t("connections.open.lead")), h("div", {class: "win-body"}, list, said, running), h("div", {class: "row win-foot"}, go, close)]);
    view.box.classList.add("wide", "sv-win");
    let rows = [], picked = kept("chosen", null), primary = kept("primary", ""), found0 = null;
    const marks = {};
    const replan = () => {
      const chosen = rows.filter((row) => picked.includes(row.alias)).map((row) => row.alias);
      keep("chosen", picked); keep("primary", primary);
      go.disabled = !chosen.length || found0.vscode_open;
      go.title = found0.vscode_open ? t("connections.open.running") : !chosen.length ? t("connections.open.none") : "";
      if (!chosen.length) { Object.values(marks).forEach((node) => node.replaceChildren()); said.replaceChildren(); return; }
      ask("plan", {chosen, primary}).then((plan) => {
        for (const row of rows) {
          const node = marks[row.alias];
          if (!picked.includes(row.alias) || found0.env_wrong) { node.replaceChildren(); continue; }  // a VS Code started without this computer's settings holds none of them: "in the window" would be false (1.7.24)
          const wrapped = plan.wrap.includes(row.alias);
          node.replaceChildren(h("span", {class: "sv-how " + (wrapped ? "wrap" : "direct"), title: wrapped ? t("connections.how.wrap.tip", {alias: row.alias}) : t("connections.how.direct.tip")}, wrapped ? t("connections.how.wrap") : t("connections.how.direct")));
        }
        said.replaceChildren(plan.wrap.length ? t("connections.plan.wrap", {n: plan.wrap.length}) : "");
      });
    };
    ask("list").then((found) => {
      found0 = found;
      rows = found.connections.filter((row) => row.saved).sort((a, b) => ENV_ORDER.indexOf(a.env) - ENV_ORDER.indexOf(b.env) || a.alias.localeCompare(b.alias));
      if (picked === null) picked = rows.map((row) => row.alias);
      picked = picked.filter((alias) => rows.some((row) => row.alias === alias));
      const windowsAccounts = rows.filter((row) => row.identity === "netonly");
      list.replaceChildren(...(rows.length ? rows.map((row) => {
        const box = h("input", {type: "checkbox"});
        box.checked = picked.includes(row.alias);
        box.addEventListener("change", () => { picked = box.checked ? [...picked, row.alias] : picked.filter((alias) => alias !== row.alias); replan(); });
        const star = row.identity === "netonly" && windowsAccounts.length > 1 ? h("input", {type: "radio", name: "sv-primary", title: t("connections.primary.tip")}) : null;
        if (star) { star.checked = primary === row.alias; star.addEventListener("change", () => { primary = row.alias; replan(); }); }
        marks[row.alias] = h("span", {class: "sv-mark"});
        return h("label", {class: "sv-line sv-pick", title: [row.label, row.type_label + " · " + row.auth_label, where(row)].filter(Boolean).join("\n")},
          box, envChip(row.env), h("b", {class: "sv-alias"}, row.alias), h("span", {class: "sv-kind"}, row.account), star ? h("span", {class: "sv-primary"}, star, t("connections.primary")) : null, marks[row.alias]);
      }) : [h("p", {class: "sub"}, t("connections.open.nothing"))]));
      running.hidden = !found.vscode_open;
      replan();
    }, (error) => { list.replaceChildren(h("p", {class: "bad"}, error.message)); });
    go.addEventListener("click", () => {
      go.disabled = true;
      ask("open", {chosen: picked, primary}).then((done) => {
        said.replaceChildren(done.started ? t("connections.open.started", {n: done.direct.length + done.wrap.length}) : h("span", {class: "bad"}, done.why || ""));
        if (done.started) { if (opened) opened(); setTimeout(view.close, 2500); }
      }, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); go.disabled = false; });
    });
    close.addEventListener("click", view.close);
  }

  return {open, panel, choose, summary};
})();
