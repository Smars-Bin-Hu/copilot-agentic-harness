// Servers (1.7.10): the servers of the company pack and the person's own, each with the person's identity, tested before it is kept; and "Open VS Code
// with identities", where the person picks which identities this window holds. A window of its own, opened from Get ready and from the Enter screen.
// The server (`/api/servers`) never sends a password back: a saved one shows as a mark. Needs common.js (h, t), serve.js (SERVE).
const SERVERS = (function () {
  const ask = (step, body) => SERVE.post("/api/servers", {step, ...(body || {})}).then((data) => data.result);
  const ENV_ORDER = ["dev", "ist", "qat", "prod"];
  const MARK = {ok: "✓", denied: "✗", down: "✗", failed: "✗", missing: "✗"};
  const keep = (key, value) => { try { localStorage.setItem("harness.servers." + key, JSON.stringify(value)); } catch (error) { /* a convenience only */ } };
  const kept = (key, fallback) => { try { const found = localStorage.getItem("harness.servers." + key); return found ? JSON.parse(found) : fallback; } catch (error) { return fallback; } };

  const field = (caption, input) => h("label", {class: "sv-field"}, h("span", {class: "sv-cap"}, caption), input);  // a field keeps its name once it is filled
  function envChip(env) { return env === "none" ? h("span", {class: "sv-env", title: t("servers.env.none.tip")}, "\u2014") : h("span", {class: "sv-env sv-env-" + env}, env.toUpperCase()); }
  function where(row) { const f = row.fields || {}; return [f.host, f.port].filter(Boolean).join(":") || Object.values(f).filter(Boolean).join(" · "); }
  function result(found) {  // a test's answer: a mark and a short word, the reason on hover
    const word = t("servers.state." + found.state);
    const tip = found.state === "ok" ? t("servers.tip.ok", {who: found.who || "-", seconds: found.seconds}) : found.state === "missing" ? found.why : t("servers.tip." + found.state);
    return h("span", {class: "sv-result " + (found.state === "ok" ? "ok" : "bad"), title: tip}, h("b", null, MARK[found.state] || "?"), " ", word);
  }

  // One server: a line (environment, name, kind, where, what is saved), and when opened, its identity, Test and Save.
  function serverRow(row, redraw) {
    const line = h("button", {type: "button", class: "sv-line" + (row.saved ? " saved" : ""), "aria-expanded": "false",
      title: [row.label, row.kind_label + (row.auth_label ? " · " + row.auth_label : ""), where(row)].filter(Boolean).join("\n")},
      envChip(row.env), h("b", {class: "sv-alias"}, row.alias), h("span", {class: "sv-kind"}, row.kind_label), h("code", {class: "sv-where"}, where(row)),
      row.own ? h("span", {class: "sv-own", title: t("servers.own.tip")}, t("servers.own")) : null,
      h("span", {class: "sv-state " + (row.saved ? "ok" : "none"), title: row.saved ? t("servers.saved.tip", {account: row.account || "-"}) : t("servers.none.tip")}, row.saved ? "✓ " + (row.account || t("servers.saved")) : t("servers.none")));
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

  // The identity of a server, tested before it is kept. `own`: the fields of a server of the person's own (kind, env, auth, host, ...), or null.
  function identityForm(row, own, redraw) {
    if (row.identity === "tool") return toolForm(row, own, redraw);
    const needsKey = row.identity === "keyfile";
    const account = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: row.identity === "netonly" ? "DOMAIN\\id" : t("servers.account"), value: row.account || ""});
    const password = h("input", {class: "su-in su-mono", type: "password", autocomplete: "new-password", placeholder: row.saved ? t("servers.password.kept") : t("servers.password")});
    const keyfile = needsKey ? h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: t("servers.keyfile")}) : null;
    const said = h("span", {class: "sv-said"});
    const test = h("button", {type: "button", class: "act"}, t("servers.test"));
    const save = h("button", {type: "button", class: "act hot", disabled: ""}, t("servers.save"));
    const forget = row.saved ? h("button", {type: "button", class: "act danger"}, t("servers.forget")) : null;
    const values = () => ({alias: (own ? own.alias() : row.alias), account: account.value.trim(), password: password.value, keyfile: keyfile ? keyfile.value.trim() : "", own: own ? own.fields() : undefined});
    const changed = () => { save.disabled = true; said.replaceChildren(); };
    [account, password, keyfile].filter(Boolean).forEach((input) => input.addEventListener("input", changed));
    test.addEventListener("click", () => {
      test.disabled = true; save.disabled = true; said.replaceChildren(h("span", {class: "sub"}, t("servers.testing")));
      ask("test", values()).then((found) => { said.replaceChildren(result(found)); save.disabled = found.state !== "ok"; }, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); })
        .then(() => { test.disabled = false; });
    });
    save.addEventListener("click", () => {
      save.disabled = true;
      ask("save", values()).then(() => { password.value = ""; redraw(); }, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); });
    });
    if (forget) forget.addEventListener("click", () => { forget.disabled = true; ask("forget", {alias: row.alias}).then(redraw, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); forget.disabled = false; }); });
    password.addEventListener("keydown", (event) => { if (event.key === "Enter" && !test.disabled) test.click(); });
    return [h("div", {class: "sv-fields"}, field(t("servers.account"), account), field(t("servers.password"), password), keyfile ? field(t("servers.keyfile"), keyfile) : null), h("div", {class: "sv-acts"}, test, save, forget, said)];
  }

  // A server whose program keeps its own sign-in (1.7.13): nothing to type. Test runs the kind's check; Save keeps only the name it answered with.
  function toolForm(row, own, redraw) {
    const said = h("span", {class: "sv-said"});
    const test = h("button", {type: "button", class: "act"}, t("servers.test"));
    const save = h("button", {type: "button", class: "act hot", disabled: ""}, t("servers.save"));
    const forget = row.saved ? h("button", {type: "button", class: "act danger"}, t("servers.forget")) : null;
    const values = () => ({alias: own ? own.alias() : row.alias, account: "", password: "", keyfile: "", own: own ? own.fields() : undefined});
    test.addEventListener("click", () => {
      test.disabled = true; save.disabled = true; said.replaceChildren(h("span", {class: "sub"}, t("servers.testing")));
      ask("test", values()).then((found) => { said.replaceChildren(result(found)); save.disabled = found.state !== "ok"; }, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); })
        .then(() => { test.disabled = false; });
    });
    save.addEventListener("click", () => { save.disabled = true; ask("save", values()).then(redraw, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); }); });
    if (forget) forget.addEventListener("click", () => { forget.disabled = true; ask("forget", {alias: row.alias}).then(redraw, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); forget.disabled = false; }); });
    const signIn = row.login && !own && typeof TERM !== "undefined" ? h("button", {type: "button", class: "act", title: row.login}, t("servers.tool.login")) : null;  // the kind's own sign-in, in the Terminal window
    if (signIn) signIn.addEventListener("click", () => TERM.run("harness servers login " + row.alias));
    return [h("p", {class: "sub sv-tool"}, t(row.saved ? "servers.tool.saved" : "servers.tool.hint", {account: row.account || ""})), h("div", {class: "sv-acts"}, signIn, test, save, forget, said)];
  }

  // A server of the person's own: a kind of this copy, its fields, its environment and way in, a name; then the same identity, test and save.
  function ownForm(kinds, redraw) {
    const names = Object.keys(kinds);
    if (!names.length) return h("p", {class: "sub"}, t("servers.own.nokind"));
    const kind = h("select", {class: "su-in"}, names.map((name) => h("option", {value: name}, kinds[name].label)));
    const alias = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: t("servers.own.alias")});
    const env = h("select", {class: "su-in", required: ""}, h("option", {value: ""}, t("servers.own.env.pick")), ["dev", "ist", "qat"].map((name) => h("option", {value: name}, name.toUpperCase())), h("option", {value: "none"}, t("servers.env.none")));  // no environment chosen for you: a wrong one is easy to miss
    const auth = h("select", {class: "su-in"});
    const fields = h("div", {class: "sv-fields"});
    const rest = h("div");
    let inputs = {};
    const draw = () => {
      const spec = kinds[kind.value];
      auth.replaceChildren(...Object.entries(spec.auth).map(([mode, item]) => h("option", {value: mode}, item.label)));
      inputs = {};
      fields.replaceChildren(...Object.entries(spec.fields).map(([name, item]) => field(item.label + (item.optional ? " " + t("servers.optional") : ""), (inputs[name] = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: item.placeholder || "", value: item.default || ""})))));
      drawIdentity();
    };
    const drawIdentity = () => {
      const spec = kinds[kind.value];
      const row = {alias: "", identity: (spec.auth[auth.value] || {}).identity, login: (spec.auth[auth.value] || {}).login || "", saved: false, account: ""};
      rest.replaceChildren(...identityForm(row, {alias: () => alias.value.trim(), fields: () => ({kind: kind.value, env: env.value, auth: auth.value, ...Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value.trim()]))})}, redraw));
    };
    kind.addEventListener("change", draw);
    auth.addEventListener("change", drawIdentity);
    draw();
    return h("div", {class: "sv-own-form"}, h("div", {class: "sv-fields"}, field(t("servers.own.kind"), kind), field(t("servers.own.name"), alias), field(t("servers.own.env"), env), field(t("servers.own.auth"), auth)), fields, rest);
  }

  // The Servers window.
  function open(done) {
    const list = h("div", {class: "sv-list"}, h("p", {class: "sub"}, t("servers.loading")));
    const addBox = h("details", {class: "sv-add"}, h("summary", null, t("servers.own.add")));
    const launch = h("button", {type: "button", class: "act hot"}, t("servers.open"));
    const close = h("button", {type: "button", class: "act"}, t("servers.close"));
    const view = SERVE.dialog([h("h2", null, t("servers.title")), h("p", {class: "sub"}, t("servers.lead"), " ", h("span", {class: "sv-info", tabindex: "0", title: t("servers.lead.tip")}, "\u24d8")), h("div", {class: "win-body"}, list, addBox), h("div", {class: "row win-foot"}, launch, close)]);
    view.box.classList.add("wide", "sv-win");
    const redraw = () => ask("list").then((found) => {
      const rows = found.servers.slice().sort((a, b) => ENV_ORDER.indexOf(a.env) - ENV_ORDER.indexOf(b.env) || a.alias.localeCompare(b.alias));
      list.replaceChildren(...(rows.length ? rows.map((row) => serverRow(row, redraw)) : [h("p", {class: "sub"}, t("servers.empty"))]));
      addBox.replaceChildren(h("summary", null, t("servers.own.add")), ownForm(found.kinds, redraw));
      launch.disabled = !rows.some((row) => row.saved);
      launch.title = launch.disabled ? t("servers.open.nothing") : "";
    }, (error) => { list.replaceChildren(h("p", {class: "bad"}, error.message)); });
    launch.addEventListener("click", () => { view.close(); choose(); });
    close.addEventListener("click", view.close);
    redraw();
    if (done) { const watch = setInterval(() => { if (!view.box.isConnected) { clearInterval(watch); done(); } }, 400); }  // the caller's summary follows what was saved
  }

  // One line for Get ready and the Enter screen: how many servers, how many with the person's identity.
  function summary() {
    return ask("list").then((found) => ({n: found.servers.length, saved: found.servers.filter((row) => row.saved).length}));
  }

  // "Open VS Code with identities": tick the identities this window holds; those that cannot share it are reached through `harness as`, marked so.
  function choose() {
    const list = h("div", {class: "sv-list"}, h("p", {class: "sub"}, t("servers.loading")));
    const said = h("p", {class: "sub sv-plan"});
    const running = h("p", {class: "bad sv-plan", hidden: ""}, t("servers.open.running"));  // its own line: the plan does not write over it
    const go = h("button", {type: "button", class: "act hot", disabled: ""}, t("servers.open.go"));
    const close = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const view = SERVE.dialog([h("h2", null, t("servers.open.title")), h("p", {class: "sub"}, t("servers.open.lead")), h("div", {class: "win-body"}, list, said, running), h("div", {class: "row win-foot"}, go, close)]);
    view.box.classList.add("wide", "sv-win");
    let rows = [], picked = kept("chosen", null), primary = kept("primary", ""), found0 = null;
    const marks = {};
    const replan = () => {
      const chosen = rows.filter((row) => picked.includes(row.alias)).map((row) => row.alias);
      keep("chosen", picked); keep("primary", primary);
      go.disabled = !chosen.length || found0.vscode_open;
      go.title = found0.vscode_open ? t("servers.open.running") : !chosen.length ? t("servers.open.none") : "";
      if (!chosen.length) { Object.values(marks).forEach((node) => node.replaceChildren()); said.replaceChildren(); return; }
      ask("plan", {chosen, primary}).then((plan) => {
        for (const row of rows) {
          const node = marks[row.alias];
          if (!picked.includes(row.alias)) { node.replaceChildren(); continue; }
          const wrapped = plan.wrap.includes(row.alias);
          node.replaceChildren(h("span", {class: "sv-how " + (wrapped ? "wrap" : "direct"), title: wrapped ? t("servers.how.wrap.tip", {alias: row.alias}) : t("servers.how.direct.tip")}, wrapped ? t("servers.how.wrap") : t("servers.how.direct")));
        }
        said.replaceChildren(plan.wrap.length ? t("servers.plan.wrap", {n: plan.wrap.length}) : "");
      });
    };
    ask("list").then((found) => {
      found0 = found;
      rows = found.servers.filter((row) => row.saved).sort((a, b) => ENV_ORDER.indexOf(a.env) - ENV_ORDER.indexOf(b.env) || a.alias.localeCompare(b.alias));
      if (picked === null) picked = rows.map((row) => row.alias);
      picked = picked.filter((alias) => rows.some((row) => row.alias === alias));
      const windowsAccounts = rows.filter((row) => row.identity === "netonly");
      list.replaceChildren(...(rows.length ? rows.map((row) => {
        const box = h("input", {type: "checkbox"});
        box.checked = picked.includes(row.alias);
        box.addEventListener("change", () => { picked = box.checked ? [...picked, row.alias] : picked.filter((alias) => alias !== row.alias); replan(); });
        const star = row.identity === "netonly" && windowsAccounts.length > 1 ? h("input", {type: "radio", name: "sv-primary", title: t("servers.primary.tip")}) : null;
        if (star) { star.checked = primary === row.alias; star.addEventListener("change", () => { primary = row.alias; replan(); }); }
        marks[row.alias] = h("span", {class: "sv-mark"});
        return h("label", {class: "sv-line sv-pick", title: [row.label, row.kind_label + " · " + row.auth_label, where(row)].filter(Boolean).join("\n")},
          box, envChip(row.env), h("b", {class: "sv-alias"}, row.alias), h("span", {class: "sv-kind"}, row.account), star ? h("span", {class: "sv-primary"}, star, t("servers.primary")) : null, marks[row.alias]);
      }) : [h("p", {class: "sub"}, t("servers.open.nothing"))]));
      running.hidden = !found.vscode_open;
      replan();
    }, (error) => { list.replaceChildren(h("p", {class: "bad"}, error.message)); });
    go.addEventListener("click", () => {
      go.disabled = true;
      ask("open", {chosen: picked, primary}).then((done) => {
        said.replaceChildren(done.started ? t("servers.open.started", {n: done.direct.length + done.wrap.length}) : h("span", {class: "bad"}, done.why || ""));
        if (done.started) setTimeout(view.close, 2500);
      }, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); go.disabled = false; });
    });
    close.addEventListener("click", view.close);
  }

  return {open, choose, summary};
})();
