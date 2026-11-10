// Connections & sign-ins (1.7.10, one window since 1.7.38): the connections of the company and the person's own, in one list, each with its sign-in (the account kept here, or the one a program keeps itself)
// and a Test that says which step broke. And "Open VS Code with identities", where the person picks which identities this window holds.
// The server (`/api/connections`) never sends a password back: a saved one shows as a mark. Needs common.js (h, t), serve.js (SERVE).
const SERVERS = (function () {
  const ask = (step, body) => SERVE.post("/api/connections", {step, ...(body || {})}).then((data) => data.result);
  const ENV_ORDER = ["dev", "ist", "qat", "prod"];
  const MARK = {ok: "✓", denied: "✗", down: "✗", failed: "✗", missing: "✗", mcp: "\u2192"};
  const keep = (key, value) => { try { localStorage.setItem("harness.servers." + key, JSON.stringify(value)); } catch (error) { /* a convenience only */ } };
  const kept = (key, fallback) => { try { const found = localStorage.getItem("harness.servers." + key); return found ? JSON.parse(found) : fallback; } catch (error) { return fallback; } };

  const field = (caption, input) => h("label", {class: "sv-field"}, h("span", {class: "sv-cap"}, caption), input);  // a field keeps its name once it is filled
  function envChip(env) { return env === "none" ? null : h("span", {class: "sv-env sv-env-" + env}, env.toUpperCase()); }  // env none: no chip at all (the rule since 1.7.19)
  function where(row) { const f = row.fields || {}; return [f.host, f.port].filter(Boolean).join(":") || Object.values(f).filter(Boolean).join(" · "); }
  function result(found) {  // a test's answer: a mark and a short word, the reason on hover
    const word = found.timeout ? t("connections.state.timeout", {seconds: found.timeout}) : t("connections.state." + found.state);
    const tip = found.timeout ? t("connections.tip.timeout", {seconds: found.timeout}) : found.state === "ok" ? t("connections.tip.ok.save", {who: found.who || "-", seconds: found.seconds}) : found.state === "missing" || found.state === "mcp" ? found.why : found.state === "failed" && found.why && !/^exit-\d+$/.test(found.why) ? t("connections.tip.failed") + "\n" + found.why : t("connections.tip." + found.state);
    return h("span", {class: "sv-result " + (found.state === "ok" || found.state === "mcp" ? "ok" : "bad"), title: tip}, h("b", null, MARK[found.state] || "?"), " ", word);
  }

  const STEPS = ["program", "signin", "access", "address"];
  const STEP_MARK = {ok: "\u2713 ", bad: "\u2717 ", unknown: "? ", skip: ""};
  // The four steps of a Test that did not pass (1.7.38): the first that broke is marked, the steps after it were not looked at; and one sentence with a link to the part of Local that helps.
  // `go(tab, part, focus)` opens that window.
  function layersBox(found, go) {
    const layers = found && found.layers;
    if (!layers || found.state === "ok" || found.state === "mcp") return null;
    const parts = [];
    STEPS.forEach((step, index) => {
      if (index) parts.push(h("span", {class: "tl-arrow"}, "\u2192"));
      const how = layers.steps[step] || "skip";
      parts.push(h("span", {class: "tl-step " + how, title: t("connections.step." + how + ".tip")}, STEP_MARK[how] + t("connections.step." + step)));
    });
    const text = [layers.text];
    if (layers.link && go) {
      const label = t("tools.local.title"), at = layers.text.lastIndexOf(label);
      const open = h("button", {type: "button", class: "tl-textlink"}, label);
      open.addEventListener("click", () => go("local", layers.link.part, layers.link.focus));
      if (at >= 0) text.splice(0, 1, layers.text.slice(0, at), open, layers.text.slice(at + label.length));
      else text.push(" ", open);
    }
    return h("div", {class: "tl-why"}, h("div", {class: "tl-steps"}, parts), h("p", {class: "tl-say"}, text));
  }

  // Forgetting a connection of the person's own takes the connection and its identity away, and nothing brings it back: the browser asks first, as Remove does for a pack (1.7.38).
  // A connection of a tool pack or the company only loses the identity (a program that keeps its own sign-in loses it for every connection that uses it): it is still listed, but the password has to be typed
  // again, so it asks once too (F1 L9).
  function sure(button, row, run) {
    const key = row.own ? "connections.forget.ask" : row.tool ? "connections.forget.tool.ask" : "connections.forget.signin.ask";
    if (window.confirm(t(key, {name: row.alias, program: row.tool || ""}))) run();
  }

  // The identity of a server, tested before it is kept. `own`: the fields of a server of the person's own (kind, env, auth, host, ...), or null.
  function identityForm(row, own, redraw, go) {
    if (row.identity === "tool") return toolForm(row, own, redraw, go);
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
      ask("test", values()).then((found) => { said.replaceChildren(...[result(found), layersBox(found, go)].filter(Boolean)); save.disabled = !["ok", "mcp"].includes(found.state); }, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); })
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
  function toolForm(row, own, redraw, go) {
    const said = h("span", {class: "sv-said"});
    const test = h("button", {type: "button", class: "act"}, t("connections.test"));
    const save = h("button", {type: "button", class: "act hot", disabled: ""}, t("connections.save"));
    const forget = row.saved ? h("button", {type: "button", class: "act danger"}, t("connections.forget")) : null;
    const values = () => ({alias: own ? own.alias() : row.alias, account: "", password: "", keyfile: "", own: own ? own.fields() : undefined});
    test.addEventListener("click", () => {
      test.classList.remove("hot", "live");
      test.disabled = true; save.disabled = true; said.replaceChildren(h("span", {class: "sub"}, t("connections.testing")));
      ask("test", values()).then((found) => { said.replaceChildren(...[result(found), layersBox(found, go)].filter(Boolean)); save.disabled = found.state !== "ok"; }, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); })
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
      TERM.run(["harness connections login", word(name), "--type", word(fields.type), ...Object.entries(fields).filter(([key, value]) => !["type", "env", "about"].includes(key) && value).map(([key, value]) => "--set " + word(key + "=" + value))].join(" "), signedIn);
    });
    return [h("p", {class: "sub sv-tool"}, t(row.saved ? "connections.tool.saved" : "connections.tool.hint", {account: row.account || ""})), h("div", {class: "sv-acts"}, signIn, test, save, forget, said)];
  }

  // A server of the person's own: a kind of this copy, its fields, its environment and way in, a name; then the same identity, test and save.
  function ownForm(kinds, redraw, go) {
    const names = Object.keys(kinds);
    if (!names.length) return h("p", {class: "sub"}, t("connections.own.nokind"));
    const kind = h("select", {class: "su-in", required: ""}, h("option", {value: ""}, t("connections.own.env.pick")), names.map((name) => h("option", {value: name}, kinds[name].label)));  // no kind chosen for you (1.7.38)
    const alias = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: t("connections.own.alias")});
    const env = h("select", {class: "su-in", required: ""}, h("option", {value: ""}, t("connections.own.env.pick")), ["dev", "ist", "qat"].map((name) => h("option", {value: name}, name.toUpperCase())), h("option", {value: "none"}, t("connections.env.none")));  // no environment chosen for you: a wrong one is easy to miss
    const envField = field(t("connections.own.env"), env);  // hidden until a kind is chosen, and for a kind that says it has no environment
    let envSet = false;  // the environment is "none" because the kind says so, not because the person chose it
    const auth = h("select", {class: "su-in"});
    const authField = field(t("connections.own.auth"), auth);  // hidden until a kind is chosen
    const about = h("input", {class: "su-in", autocomplete: "off", spellcheck: "false", maxlength: "120", placeholder: t("connections.own.about.ph")});  // one line the agent finds this connection by (`harness connections find`)
    const fields = h("div", {class: "sv-fields"});
    const rest = h("div");
    let inputs = {};
    const draw = () => {
      const spec = kinds[kind.value];
      envField.hidden = !spec || spec.env === "none";
      authField.hidden = !spec;
      if (!spec) { auth.replaceChildren(); fields.replaceChildren(); inputs = {}; rest.replaceChildren(h("p", {class: "sub"}, t("connections.own.kind.first"))); return; }
      const noEnv = spec.env === "none";
      if (noEnv) { env.value = "none"; envSet = true; } else if (envSet) { env.value = ""; envSet = false; }
      auth.replaceChildren(...Object.entries(spec.auth).map(([mode, item]) => h("option", {value: mode}, item.label)));
      inputs = {};
      fields.replaceChildren(...Object.entries(spec.fields).map(([name, item]) => field(item.label + (item.optional ? " " + t("connections.optional") : ""), (inputs[name] = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: item.placeholder || "", value: item.default || ""})))));
      drawIdentity();
    };
    const drawIdentity = () => {
      const spec = kinds[kind.value];
      const row = {alias: "", identity: (spec.auth[auth.value] || {}).identity, login: (spec.auth[auth.value] || {}).login || "", auth_label: (spec.auth[auth.value] || {}).label || "", saved: false, account: ""};
      rest.replaceChildren(...identityForm(row, {alias: () => alias.value.trim(), fields: () => ({type: kind.value, env: env.value, auth: auth.value, about: about.value.trim(), ...Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value.trim()]))})}, redraw, go));
    };
    kind.addEventListener("change", draw);
    auth.addEventListener("change", drawIdentity);
    draw();
    return h("div", {class: "sv-own-form"}, h("div", {class: "sv-fields"}, field(t("connections.own.kind"), kind), field(t("connections.own.name"), alias), envField, authField), h("p", {class: "sub"}, t("connections.own.env.prod")), field(t("connections.own.about"), about), fields, rest);  // why there is no PROD (1.7.38)
  }

  // One connection (1.7.38): name, type, where it points (the environment chip, or `org · project`), whether the company or the person added it, the sign-in (a dot and the account), Sign in and Test.
  // Under it: the form of a sign-in that needs typing, and the four steps of a Test that did not pass. A sign-in that a program keeps itself (`az`) is one for the whole computer: every connection that uses
  // it shows the same account, with a hover that says so.
  function place(row) {
    const f = row.fields || {};
    const address = [f.host, f.port].filter(Boolean).join(":");
    const rest = Object.entries(f).filter(([key, value]) => value && key !== "url").map(([, value]) => value);
    return address || rest.join(" · ") || Object.values(f).filter(Boolean).join(" · ");
  }
  function connRow(row, found, env) {  // env: {results: Map, paints: Map, redraw, go}
    const key = row.alias;
    const names = found.connections.filter((one) => row.tool && one.tool === row.tool && one.alias !== key).map((one) => one.alias);
    const stateBox = h("span", {class: "tl-state"});
    const why = h("div", {class: "tl-whybox"});
    const form = h("div", {class: "tl-form", hidden: ""});
    const signBtn = h("button", {type: "button", class: "act"}, t("connections.signin"));
    const testBtn = h("button", {type: "button", class: "act"}, t("connections.test"));
    const guard = row.guard || null;  // a type no pack that is on brings (1.7.38, S1): off (the gate still judges), faulty (the gate holds every call of the pack's programs), gone (nothing to judge by)
    const via = row.type && !row.known ? "nopack" : row.via === "mcp" ? "mcp" : "";
    const fail = () => {
      const last = env.results.get(key);
      return last ? !["ok", "mcp"].includes(last.state) : row.saved && (row.reach === "denied" || row.reach === "failed");
    };
    // A sign-in kept because its test never reached the system (Q1): the answer just now says `kept`; after the window was closed, the row says `untested`.
    const waiting = () => { const last = env.results.get(key); return last ? Boolean(last.kept) : Boolean(row.untested); };
    function paint() {
      const last = env.results.get(key);
      const wait = waiting();
      const slow = wait && (last ? last.kept_why === "no-answer" : row.untested_why === "no-answer");  // the test got no answer: saved all the same (1.7.38, C13 D3-1)
      const bad = fail() && !wait;
      const dot = h("span", {class: "su-dot " + (via ? "none" : bad ? "bad" : wait ? "ring" : row.signed ? "ok" : "ring")});  // `signed`: kept here, or a program's own sign-in that the last check got through (the Enter screen counts the same)
      let words;
      if (via === "mcp") words = h("span", {class: "tl-who none"}, t("connections.state.mcp"));
      else if (via === "nopack") { const mode = guard && ["faulty", "gone", "listfault"].includes(guard.state) ? guard.state : "off"; words = h("span", {class: "tl-who none", title: t(mode === "off" ? "connections.state.nopack.tip" : "connections.state." + mode + ".tip", {file: guard ? guard.file : "", problem: guard ? guard.problem : ""})}, t(mode === "off" ? "connections.state.nopack" : "connections.state." + mode)); }  // what the gate does with its calls is told as it is (1.7.38, S1)
      else if (!row.signed && !last) words = h("span", {class: "tl-who none"}, t("connections.none"));
      else {
        // Who it is signed in as (1.7.38): the account kept here; else the name the last test answered with; else, for a token, that a token is saved. A failed test of something not kept says it was not kept.
        const who = row.account || (last && last.state === "ok" && last.who) || ((row.saved || row.signed) && row.who) || (row.saved && row.identity === "token" ? t("connections.token.saved") : row.signed && !row.saved ? t("connections.tool.signed") : "");
        const failed = last && last.timeout ? t("connections.state.timeout", {seconds: last.timeout}) : t(row.saved ? "connections.state.testfailed" : "connections.state.notsaved");
        const note = wait ? t(slow ? (who ? "connections.state.untested.noanswer" : "connections.state.untested.noanswer.alone") : who ? "connections.state.untested" : "connections.state.untested.alone") : bad ? failed : "";  // "token saved · not tested yet": the name of the row already says saved
        words = h("span", {class: "tl-who" + (bad ? " bad" : "")}, who + (note ? (who ? " · " : "") + note : ""));
      }
      const tip = wait ? t(slow ? "connections.untested.noanswer.tip" : "connections.untested.tip") : last ? (last.state === "ok" ? t("connections.tip.ok", {who: last.who || "-", seconds: last.seconds}) : last.layers && last.layers.text ? last.layers.text : "") : row.saved ? (bad && row.reach_tip ? row.reach_tip : t("connections.saved.tip", {account: row.account || row.who || "-"})) : row.signed ? t("connections.signed.tip") : t("connections.none.tip");
      const share = row.tool ? h("span", {class: "sv-info", tabindex: "0", title: t(names.length ? "connections.shared.with" : "connections.shared.one", {program: row.tool, names: names.join(", ")})}, "ⓘ") : null;
      const forget = row.saved && !via ? h("button", {type: "button", class: "mc-x", title: t(row.own ? "connections.forget.own.tip" : "connections.forget.tip"), "aria-label": t("connections.forget")}, "×") : null;
      if (forget) forget.addEventListener("click", () => sure(forget, row, () => {
        forget.disabled = true;
        (row.tool ? ask("forget-tool", {program: row.tool}) : ask("forget", {alias: key})).then(() => { env.results.delete(key); env.redraw(); }, (error) => { why.replaceChildren(h("p", {class: "tl-say bad"}, error.message)); forget.disabled = false; });
      }));
      stateBox.replaceChildren(...[dot, words, share, forget].filter(Boolean));
      stateBox.title = tip;
      const note = env.notes.get(key);
      why.replaceChildren(...[last && layersBox(last, env.go), last && wait ? h("p", {class: "tl-say sub"}, t(slow ? "connections.kept.noanswer" : "connections.kept")) : null, last && bad && !row.saved ? h("p", {class: "tl-say sub"}, t("connections.notsaved")) : null, note ? h("p", {class: "tl-say" + (note.bad ? " bad" : " sub")}, note.said) : null].filter(Boolean));
      signBtn.className = "act" + (row.signed || via ? "" : " hot");
      testBtn.className = "act" + (wait ? " hot" : "");  // saved, not tested yet: the next thing to press
      signBtn.hidden = Boolean(via);
      testBtn.hidden = Boolean(via);
      testBtn.disabled = !row.saved && row.identity !== "tool";
      testBtn.title = testBtn.disabled ? t("connections.test.off") : "";
    }
    const again = () => (env.paints.get(key) || paint)();  // the list may have been drawn again while a test ran: the row that is on the page shows the answer
    const busy = (on, say) => { signBtn.disabled = testBtn.disabled = on; if (!on) again(); else why.replaceChildren(h("p", {class: "tl-say sub"}, say || t("connections.testing"))); };
    const keep = (found0) => { env.results.set(key, found0); };
    // A sign-in that a program keeps: it is tested, and the name it answers with is kept when the test passes (nothing secret is typed or kept here).
    const afterTool = () => {
      busy(true);
      ask("test", {alias: key}).then((answer) => {
        keep(answer);
        if (answer.state !== "ok") { busy(false); return; }
        return ask("save", {alias: key}).then(() => { env.results.delete(key); env.redraw(); });
      }, (error) => { busy(false); why.replaceChildren(h("p", {class: "tl-say bad"}, error.message)); });
    };
    testBtn.addEventListener("click", () => {
      busy(true);
      ask("test", {alias: key, saved: true}).then((answer) => {
        keep(answer);
        if (answer.state === "ok" && row.tool && (!row.saved || (answer.who && answer.who !== row.account))) return ask("save", {alias: key}).then(() => { env.results.delete(key); env.redraw(); });
        busy(false);
      }, (error) => { busy(false); why.replaceChildren(h("p", {class: "tl-say bad"}, error.message)); });
    });
    let drawn = false;
    signBtn.addEventListener("click", () => {
      if (row.identity === "tool") {
        if (typeof TERM === "undefined" || !row.login) { why.replaceChildren(h("p", {class: "tl-say bad"}, t("connections.signin.noterm"))); return; }
        TERM.run("harness connections login " + key, afterTool);  // the kind's own sign-in, in the Terminal window; when it ends the row tests and keeps the account
        return;
      }
      form.hidden = !form.hidden;
      if (!form.hidden && !drawn) { drawn = true; form.append(...typedForm(row, env, keep, busy)); }
      if (!form.hidden) { const first = form.querySelector("input"); if (first) first.focus(); }
    });
    const source = row.own ? h("span", {class: "sv-own sv-from", title: t("connections.own.tip")}, t("connections.own")) : h("span", {class: "sv-own sv-from", title: t("connections.company.tip")}, t("connections.company"));
    // A connection of one's own can go in the company pack (the place only, never the account): it was a button of the knowledge base window until 1.7.38.
    const up = row.own ? h("button", {type: "button", class: "mc-x tl-share", title: t("dock.connections.share.tip"), "aria-label": t("dock.connections.share.tip")}, "\u21ea") : null;
    if (up) up.addEventListener("click", () => shareWindow(row, (said, bad) => { env.notes.set(key, {said, bad}); env.redraw(); }));  // the list is read again: the row is the company's now, and says what was done
    const chip = envChip(row.env);
    const title = [...new Set([row.alias, row.label])].concat([row.about, row.type_label + (row.auth_label ? " · " + row.auth_label : ""), place(row), (row.fields || {}).url]).filter(Boolean).join("\n");
    paint();
    env.paints.set(key, paint);
    return h("div", {class: "tl-crow", "data-focus": "sign:" + key, "data-alias": key},
      h("div", {class: "tl-c1"}, h("span", {class: "tl-id", title}, h("b", {class: "sv-alias"}, key), h("span", {class: "sv-kind"}, row.type_label), chip || h("code", {class: "sv-where"}, place(row)), source),
        h("span", {class: "tl-act"}, stateBox, up, signBtn, testBtn)), why, form);
  }

  // What goes in the company pack, shown before it is written: the connection's fields, no account, no password.
  function shareWindow(row, tell) {
    const lines = [["type", row.type_label || row.type], ["env", row.env && row.env !== "none" ? row.env.toUpperCase() : ""], ["auth", row.auth_label || row.auth], ...Object.entries(row.fields || {})].filter(([, value]) => value);
    const note = h("p", {class: "su-note"});
    const go = h("button", {type: "button", class: "act hot"}, t("dock.connections.share.go"));
    const no = h("button", {type: "button", class: "act"}, t("board.new.close"));
    const win = SERVE.dialog([h("h2", null, t("dock.connections.share.title", {alias: row.alias})), h("p", {class: "sub"}, t("dock.connections.share.lead")),
      h("ul", {class: "kb-sv-lines"}, lines.map(([key, value]) => h("li", null, h("b", null, key + ": "), h("code", null, String(value))))), note, h("div", {class: "row win-foot"}, go, no)]);
    win.box.classList.add("kb-sv-win");
    no.addEventListener("click", win.close);
    go.addEventListener("click", () => {
      go.disabled = true;
      ask("share", {aliases: [row.alias]}).then((result) => {
        win.close();
        tell(result.next + (result.sync_error ? " " + String(result.sync_error).replace(/`/g, "") : ""), Boolean(result.sync_error));
      }, (error) => { go.disabled = false; note.classList.add("bad"); note.textContent = error.message || String(error); });
    });
  }

  // The form of a sign-in that needs typing: an account and a password (or one token, or a key file). Sign in tests with what was typed and keeps it only when the test passes.
  function typedForm(row, env, keep, busy) {
    const token = row.identity === "token";
    const account = h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: row.identity === "netonly" ? "DOMAIN\\id" : t("connections.account"), value: row.account || ""});
    const password = h("input", {class: "su-in su-mono", type: "password", autocomplete: "new-password", placeholder: row.saved ? t("connections.password.kept") : (token ? row.auth_label || t("connections.password") : t("connections.password"))});
    const keyfile = row.identity === "keyfile" ? h("input", {class: "su-in su-mono", autocomplete: "off", spellcheck: "false", placeholder: t("connections.keyfile")}) : null;
    const go = h("button", {type: "button", class: "act hot"}, t("connections.signin"));
    const run = () => {
      busy(true);
      const values = {alias: row.alias, account: account.value.trim(), password: password.value, keyfile: keyfile ? keyfile.value.trim() : ""};
      ask("test", {...values, keep: true}).then((answer) => {
        keep(answer);
        if (answer.kept) { password.value = ""; env.redraw(); return; }  // the test never reached the system: the sign-in is kept, and the row says so (Test works without typing again)
        if (!["ok", "mcp"].includes(answer.state)) { busy(false); return; }
        return ask("save", values).then(() => { password.value = ""; env.results.delete(row.alias); env.redraw(); });
      }, (error) => { busy(false); env.results.set(row.alias, {state: "failed", why: error.message, layers: {steps: {}, broken: "", text: error.message, link: null}}); busy(false); });
    };
    go.addEventListener("click", run);
    [account, password, keyfile].filter(Boolean).forEach((input) => input.addEventListener("keydown", (event) => { if (isEnter(event) && !go.disabled) run(); }));
    return [h("div", {class: "sv-fields"}, token ? null : field(t("connections.account"), account), field(token ? row.auth_label || t("connections.password") : t("connections.password"), password), keyfile ? field(t("connections.keyfile"), keyfile) : null), h("div", {class: "sv-acts"}, go)];
  }

  function orphanRow(item, redraw) {  // an identity kept for a connection the company no longer lists: only the person forgets it
    const forget = h("button", {type: "button", class: "act danger"}, t("connections.forget"));
    const said = h("span", {class: "sv-said"});
    forget.addEventListener("click", () => { if (!window.confirm(t("connections.forget.signin.ask", {name: item.name}))) return; forget.disabled = true; ask("forget", {alias: item.name}).then(redraw, (error) => { said.replaceChildren(h("span", {class: "bad"}, error.message)); forget.disabled = false; }); });  // asks once like every other forget (F1 L9)
    return h("div", {class: "tl-crow", "data-focus": "sign:" + item.name}, h("div", {class: "tl-c1 orphan", title: t("machine.signins.orphan.tip", {name: item.name})}, h("span", {class: "tl-id"}, h("b", {class: "sv-alias"}, item.name), h("span", {class: "sv-kind"}, t("machine.signins.orphan"))),
      h("span", {class: "tl-act"}, h("span", {class: "tl-state"}, h("span", {class: "su-dot none"}), h("span", {class: "tl-who none"}, item.account || "—")), forget)), said);
  }

  // The window (1.7.38): one list, a footer with "Add a connection of your own" and Export. `ctx.go(tab, part, focus)` opens another window at a part.
  function connectionsPanel(ctx) {
    const results = new Map();  // alias -> the answer of the last Test, kept while the window is open
    const list = h("div", {class: "tl-clist"}, h("p", {class: "sub tl-pad"}, t("connections.loading")));
    const addBox = h("div", {class: "tl-add", hidden: ""});
    const add = h("button", {type: "button", class: "act", "aria-expanded": "false"}, t("connections.own.add.go"));  // the action; the form it opens has the longer name as its title (F1 U3)
    const out = h("button", {type: "button", class: "act", title: t("connections.export.tip")}, t("connections.export"));  // one's own connections, to put in the company pack
    const env = {results, notes: new Map(), paints: new Map(), redraw: () => redraw(), go: (name, part, focus) => ctx.go(name, part, focus)};
    add.addEventListener("click", () => {
      const open = addBox.hidden;
      addBox.hidden = !open; add.setAttribute("aria-expanded", String(open));
      if (open) { const first = addBox.querySelector("input"); if (first) first.focus(); addBox.scrollIntoView({block: "nearest", behavior: "smooth"}); }
    });
    out.addEventListener("click", () => exportWindow());
    let kinds = null;
    const redraw = () => ask("list").then((found) => {
      out.disabled = !found.connections.some((row) => row.own);
      out.title = out.disabled ? t("connections.export.none") : t("connections.export.tip");
      const rows = found.connections.slice().sort((a, b) => a.type_label.localeCompare(b.type_label) || ENV_ORDER.indexOf(a.env) - ENV_ORDER.indexOf(b.env) || a.alias.localeCompare(b.alias));
      list.replaceChildren(...(found.list_fault ? [h("p", {class: "bad tl-pad", "data-fault": "connections"}, found.list_fault.text)] : []), ...(rows.length ? rows.map((row) => connRow(row, found, env)) : found.list_fault ? [] : [h("p", {class: "sub tl-pad"}, t("connections.empty"))]), ...found.signins.orphans.map((item) => orphanRow(item, redraw)));  // a list that cannot be read: the fault first, and no sign-in is offered to forget (1.7.38, C13 FR 3)
      if (JSON.stringify(Object.keys(found.types)) !== JSON.stringify(kinds)) { kinds = Object.keys(found.types); addBox.replaceChildren(h("h4", {class: "mc-h"}, t("connections.own.add")), ownForm(found.types, redraw, env.go)); }
      if (ctx.arrived) ctx.arrived();
    }, (error) => { list.replaceChildren(h("p", {class: "bad tl-pad"}, error.message)); });
    redraw();
    return {title: t("tools.conn.title"), tip: t("tools.conn.tip"), sub: t("tools.conn.lead"), body: [list, addBox], foot: [add, out]};
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
  // A connection whose tool pack is off is not counted (Q22); `off` names them, for the hover.
  function summary() {
    return ask("list").then((found) => ({orphans: found.signins.orphans.map((item) => item.name), n: found.connections.length, saved: found.connections.filter((row) => row.signed).length,
      off: found.connections.filter((row) => row.type && !row.known).map((row) => row.alias),
      rows: found.connections.filter((row) => row.via !== "mcp" && (!row.type || row.known)).map((row) => ({alias: row.alias, saved: Boolean(row.signed), account: row.account || "", env: row.env || "", own: Boolean(row.own), tool: row.tool || "", failed: Boolean(row.saved) && (row.reach === "denied" || row.reach === "failed")}))}));
  }

  // "Open VS Code with identities": tick the identities this window holds; those that cannot share it are reached through `harness as`, marked so.
  // `before`: a function that closes the VS Code that runs (1.7.38, readyui.js `vsAct`); it runs after the person pressed the button, never before: a window that is cancelled changes nothing.
  function choose(opened, before) {  // `opened`: what the page does once VS Code was started with the identities (the Enter screen waits for it, 1.7.19)
    const list = h("div", {class: "sv-list"}, h("p", {class: "sub"}, t("connections.loading")));
    const said = h("p", {class: "sub sv-plan"});
    const running = h("p", {class: "bad sv-plan", hidden: ""}, t("connections.open.running"));  // its own line: the plan does not write over it
    const closing = h("p", {class: "sub sv-plan", hidden: ""}, t("connections.open.restart.note"));  // with `before`: a VS Code that is open is closed first, the normal way
    const go = h("button", {type: "button", class: "act hot", disabled: ""}, t(before ? "connections.open.restart" : "connections.open.go"));
    const close = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const primaryNote = h("p", {class: "sub sv-plan", hidden: ""}, t("connections.primary.note"));  // (1.7.39) shown with the "window's account" choice: one Windows account per window, what `harness as` does for the others
    const view = SERVE.dialog([h("h2", null, t("connections.open.title")), h("p", {class: "sub"}, t("connections.open.lead")), h("div", {class: "win-body"}, list, primaryNote, said, running, closing), h("div", {class: "row win-foot"}, go, close)]);
    view.box.classList.add("wide", "sv-win");
    let rows = [], picked = kept("chosen", null), primary = kept("primary", ""), found0 = null;
    const marks = {};
    const replan = () => {
      const chosen = rows.filter((row) => picked.includes(row.alias)).map((row) => row.alias);
      keep("chosen", picked); keep("primary", primary);
      const blocked = found0.vscode_open && !before;  // with `before` an open VS Code is closed first: not a reason to wait
      go.disabled = !chosen.length || blocked || Boolean(go.dataset.busy);
      go.title = blocked ? t("connections.open.running") : !chosen.length ? t("connections.open.none") : "";
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
      primaryNote.hidden = windowsAccounts.length < 2;
      running.hidden = !found.vscode_open || Boolean(before);
      closing.hidden = !found.vscode_open || !before;
      replan();
    }, (error) => { list.replaceChildren(h("p", {class: "bad"}, error.message)); });
    go.addEventListener("click", () => {
      go.disabled = true; go.dataset.busy = "1";
      if (before) close.disabled = true;  // once VS Code is on its way out there is no way back
      const free = () => { delete go.dataset.busy; close.disabled = false; go.disabled = !picked.length; };
      (before ? before((view) => { if (typeof READY !== "undefined") said.replaceChildren(READY.restartNote(view)); }) : Promise.resolve()).then(() => ask("open", {chosen: picked, primary})).then((done) => {
        said.replaceChildren(done.started ? t("connections.open.started", {n: done.direct.length + done.wrap.length}) : h("span", {class: "bad"}, done.why || ""));
        if (done.started) { if (opened) opened(); close.disabled = false; setTimeout(view.close, 2500); } else free();
      }, (error) => { said.replaceChildren(error && error.quiet ? "" : h("span", {class: "bad"}, (error && error.message) || String(error))); free(); });  // the person said no to the question about a working agent: VS Code was not touched
    });
    close.addEventListener("click", view.close);
  }

  return {open, connectionsPanel, choose, summary};
})();
