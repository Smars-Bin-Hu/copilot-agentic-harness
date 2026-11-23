// The first-run setup wizard (O2): one page, one question, a bar of six parts on top. The server does the work (modules/task/boardserve.py `/api/setup` steps programs, folder,
// scan, save, summary, finish, and the old ones); this page shows and sends. Needs common.js (h, t, clock, copyCommand), serve.js (SERVE), readyui.js (READY: dock.js reads it when it loads), dock.js (DOCK: the folder picker), servers.js (SERVERS: the connections window).
// `?only=programs` and `?only=copilot` draw that one page with a Done button (the Enter screen's fix button). `?fake=1` answers every call from data in the contract's shape, so the page walks end to end with no server
// work; more parameters pick a state for a picture: page, prog=missing|all|long, cop=idle|code|done, kb=empty|copy|done, kbsub, longname=1, job=0|1, lang, theme, hold=1 (no automatic step forward).
// Each page's drawing is `WIZARD.parts.<page>(box, opts)`, so the Settings window can draw the same page without the steps (`opts.bare`: no title).
"use strict";

const WIZARD = (function () {
  const Q = new URLSearchParams(location.search);
  const q = (key, fallback) => (Q.has(key) ? Q.get(key) : fallback);
  const FAKE = q("fake", "") === "1";
  const ONLY = ["programs", "copilot"].includes(q("only", "")) ? q("only", "") : "";
  const PAGES = ["welcome", "you", "programs", "copilot", "kb", "repos", "review"];  // the bar has the six after welcome
  const SEGMENTS = ["wizard.s.you", "wizard.s.prog", "wizard.s.cop", "wizard.s.kb", "wizard.s.repo", "wizard.s.rev"];
  const KEEP = "harness.wizard";  // the page to come back to after the language made the page load again

  // ------------------------------------------------------------------------------------------------ small pieces
  const el = (tag, cls, ...children) => h(tag, {class: cls}, ...children);
  const dot = (kind) => el("span", "wz-dot " + kind);
  const tick = () => el("span", "wz-tick", "\u2713");
  const spin = () => el("span", "wz-spin");
  const btn = (label, cls, go) => { const b = h("button", {type: "button", class: "wz-btn " + (cls || "")}, label); if (go) b.addEventListener("click", go); return b; };
  const link = (label, go, tip) => { const b = h("button", {type: "button", class: "wz-link", title: tip || null}, label); if (go) b.addEventListener("click", go); return b; };
  const input = (cls, attrs) => h("input", {type: "text", class: "wz-in " + (cls || ""), autocomplete: "off", spellcheck: "false", ...(attrs || {})});
  const eyebrow = (key) => el("div", "wz-eyebrow", typeof key === "string" && key.startsWith("wizard.") ? t(key) : key);
  const head = (opts, eyebrowText, title, sub) => (opts.bare ? [] : [eyebrow(eyebrowText), h("h1", null, title), el("p", "wz-sub", sub)]);
  const langName = (code) => t(code === "zh" ? "desk.send.lang.name.zh" : "desk.send.lang.en");  // the name of a language in that language: the same in both tables
  const listOf = (rows, cls) => el("div", "wz-list" + (cls ? " " + cls : ""), rows);
  const GITHUB = "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z";
  function ghIcon() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 16 16"); svg.setAttribute("class", "wz-gh"); svg.setAttribute("fill", "currentColor");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", GITHUB); svg.append(path);
    return svg;
  }
  const programIcon = {python: "py", git: "git", vscode: "</>", gh: "gh", harness: "h"};
  const shortPath = (text) => String(text || "");
  const put = (node, ...children) => node.replaceChildren(...children.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false));  // replaceChildren would write a null as the word
  const errorText = (error) => String((error && error.message) || error || "");

  // ------------------------------------------------------------------------------------------------ the model: what the page knows
  const M = {
    page: 0, kbsub: 0, st: null, progs: null, ready: null, scan: null, extras: null,
    name: "", lang: "en", picks: null, filter: "", saved: {you: false, repos: false}, fromReview: false, shortTried: false,
    kb: {step: "empty", a: 0, b: 0, err: "", file: ""},
  };
  let api = null, ctl = null, shell = null, readyTimer = 0;

  // ------------------------------------------------------------------------------------------------ the calls: real, or fake
  function realApi() {
    const call = (path, body, seconds) => SERVE.call(path, body, seconds);
    const send = (path, body) => SERVE.post(path, body).then((data) => data.result);
    return {
      setup: (step, body) => send("/api/setup", {step, ...(body || {})}),
      poll: (step, body) => call("/api/setup", {step, ...(body || {})}, 12).then((data) => data.result),  // a read that comes again and again: no button waits for it
      machine: (step, body) => send("/api/machine", {step, ...(body || {})}),
      machinePoll: (step, body) => call("/api/machine", {step, ...(body || {})}, 12).then((data) => data.result),
      gh: (body) => send("/api/gh", body),
      ready: () => call("/api/ready", {}, 8),
      language: (language) => SERVE.post("/api/language", {language}, true),
    };
  }

  // The fake answers: contract §2 shapes, kept in one object that the steps change.
  function fakeApi() {
    const page = Number(q("page", "0")) || 0, kbsub = Number(q("kbsub", "0")) || 0;
    const long = q("prog", page <= 2 ? "missing" : "all") === "long";
    const missing = q("prog", page <= 2 ? "missing" : "all") === "missing";
    const F = {
      name: q("longname", "0") === "1" ? "Maximiliano Alessandro Fern\u00e1ndez-Castellanos de la Vega" : "Alex Rivera",
      lang: q("lang", "en"), ghFound: !missing,
      cop: q("cop", page > 3 ? "done" : "idle"),
      kb: q("kb", page > 4 || kbsub > 0 ? "done" : "empty"), copyAt: 0, copyStatic: q("kb", "") === "copy",
      sqlcmd: false, signed: false, repos: Array.from({length: 0}), savedRepos: [], codeAt: 0, copAt: 0, ranHarness: false,
    };
    const NAMES = ["orders-service", "billing-pipeline", "data-platform-ingestion-nightly-batch-jobs-for-the-warehouse-and-the-reporting-layer", "kb-tools", "web-frontend", "customer-events-stream", "finance-reports", "dbt-models", "airflow-dags", "ml-feature-store", "infra-terraform", "notebooks", "api-gateway", "sandbox"];
    const count = Number(q("repos", String(NAMES.length)));
    const names = Array.from({length: count}, (item, i) => (i < NAMES.length ? NAMES[i] : "service-" + (i + 1) + "-with-a-name"));
    const home = long ? "C:\\Users\\a.very.long.user.name\\source\\repos\\" : "/Users/alex/Developer/";
    F.repos = names.map((name, i) => ({path: home + name, shown: (long ? "" : "~/Developer/") + (long ? home : "") + name, name, branch: "main", picked: false}));
    const rows = () => [
      {id: "python", name: "Python", required: true, found: true, path: long ? "C:\\Users\\a.very.long.user.name\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" : "/opt/homebrew/bin/python3", version: "3.12.4", how: "path", download: "https://www.python.org/downloads/", blocked: ""},
      {id: "git", name: "Git", required: true, found: true, path: long ? "C:\\Program Files\\Git\\cmd\\git.exe" : "/usr/bin/git", version: "2.47.1", how: "path", download: "https://git-scm.com/downloads", blocked: ""},
      {id: "vscode", name: "VS Code", required: true, found: true, path: long ? "C:\\Users\\a.very.long.user.name\\AppData\\Local\\Programs\\Microsoft VS Code\\bin\\code.cmd" : "/usr/local/bin/code", version: "1.147.0", how: "standard", download: "https://code.visualstudio.com/download", blocked: ""},
      F.ghFound ? {id: "gh", name: "GitHub CLI", required: true, found: true, path: long ? "C:\\Users\\a.very.long.user.name\\AppData\\Local\\Programs\\GitHub CLI\\gh.exe" : "/opt/homebrew/bin/gh", version: "2.105.0", how: "path", download: "https://cli.github.com/", blocked: ""}
        : {id: "gh", name: "GitHub CLI", required: true, found: false, path: "", version: "", how: "", download: "https://cli.github.com/", blocked: ""},
      {id: "harness", name: "harness command", required: false, found: F.ranHarness || q("harness", "1") === "1", path: "/usr/local/bin/harness", version: "1.8.26", how: "path", download: "", blocked: "", command: "python3 .harness/engine/harness.py short"},
    ];
    const programs = () => { const list = rows(); return {rows: list, all_found: list.filter((row) => row.required).every((row) => row.found && !row.blocked)}; };
    const kbHere = () => F.kb === "done";
    const state = () => ({name: F.name, name_git: q("gitname", "1") === "1" && !F.nameSaved, language: F.lang, kb: kbHere() ? {here: true, domains: 3, domain_skills: 12, version: "3.2.0", path: "~/harness/knowledge-base", prefix: "sample"} : {here: false, domains: 0, domain_skills: 0, version: "", path: "", prefix: ""},
      company: kbHere() ? {packs: ["ado", "sqlserver"], connections: [{}, {}, {}], recipe: {present: true}} : {packs: [], connections: [], recipe: {present: false}}});
    const packRows = () => [
      {program: "az", found: true, path: "/opt/homebrew/bin/az", blocked: "", needed_by: [{pack: "ado"}]},
      {program: "sqlcmd", found: F.sqlcmd, path: F.sqlcmd ? "/opt/mssql-tools18/bin/sqlcmd" : "", blocked: "", needed_by: [{pack: "sqlserver"}]},
    ];
    const done = (value, wait) => new Promise((resolve) => setTimeout(() => resolve(JSON.parse(JSON.stringify(value === undefined ? {} : value))), wait || 40));
    const fail = (text) => new Promise((resolve, reject) => setTimeout(() => reject(new Error(text)), 40));
    const copilot = () => {
      if (F.cop === "code") return {id: "copilot", state: "wait", why: "signing-in", code: "5F59-4EB2", url: "https://github.com/login/device", left: F.codeAt ? Math.max(0, 872 - Math.round((Date.now() - F.codeAt) / 1000)) : 872};
      if (F.cop === "done") return {id: "copilot", state: "ok", why: "ok", login: "alex", n: 25};
      return {id: "copilot", state: "fail", why: F.ghFound ? "signin" : "no-gh", gh: "/opt/homebrew/bin/gh"};
    };
    const ready = () => {
      const line = copilot();
      if (q("job", "1") === "1" && M.page >= 3) line.host = {state: "preparing", seconds: 64, downloaded_mb: 312, total_mb: 620, percent: 50};
      return {ready: false, checks: [line]};
    };
    const setup = {
      state, programs: () => programs(),
      folder: (body) => (!String(body.path || "").trim() || /bad$/.test(body.path) ? fail("No " + body.program + " in that folder.") : (F.ghFound = true, programs())),
      short: () => { F.ranHarness = true; return {done: true}; },
      scan: () => ({places: ["~/Developer", "~/source/repos"].slice(0, count ? 2 : 0), rows: F.repos, more: false}),
      probe: (body) => (/bad$/.test(body.path) ? {ok: false, why: "Nothing in it looks like a knowledge base."} : kbHere() && body.kind === "folder" ? {ok: false, full: true, why: "A knowledge base is in place already, and this folder has no history in common with it."} : {ok: true, why: "", version: "3.2.0"}),
      repo: (body) => ({kind: "repo", name: String(body.path).split(/[\\/]/).pop() || "extra", path: body.path}),
      save: (body) => {
        if (body.part === "kb") { F.kb = "copy"; F.copyAt = Date.now(); F.copyStatic = false; }
        if (body.part === "repos") F.savedRepos = body.paths;
        if (body.part === "you") { F.name = body.name; F.lang = body.language; F.nameSaved = true; }
        return {saved: true};
      },
      job: () => {
        if (F.kb === "copy" && F.copyStatic) return {lines: [{key: "kb", ok: true}], running: true, done: false, total: 3};
        if (F.kb === "copy" && Date.now() - F.copyAt > 1200) F.kb = "done";
        return F.kb === "done" ? {lines: [1, 2, 3].map((n) => ({key: "step" + n, ok: true, detail: ""})), running: false, done: true, total: 3} : {lines: [{key: "kb", ok: true, detail: ""}], running: true, done: false, total: 3};
      },
      summary: () => {
        const list = programs();
        const out = [{id: "you", done: true, label: t("wizard.v.you"), detail: F.name + " \u00b7 " + langName(F.lang), effect: ""},
          {id: "programs", done: list.all_found, label: t("wizard.v.prog"), detail: t("wizard.v.prog.s", {n: 5}), effect: ""},
          {id: "copilot", done: F.cop === "done", label: t("wizard.v.cop"), detail: "alex", effect: ""}];
        out.push({id: "kb", done: kbHere(), label: t("wizard.v.kb"), detail: kbHere() ? "sample 3.2.0" : "", effect: kbHere() ? "" : "No tool packs and no connections: the agent has only what the harness brings. You can bring one in later in Settings."});
        if (kbHere()) {
          out.push({id: "packs", done: F.sqlcmd, label: t("wizard.v.sq"), detail: "", effect: t("wizard.v.sq.e")});
          out.push({id: "connections", done: F.signed, label: t("wizard.v.cn"), detail: "", effect: t("wizard.v.cn.e")});
        }
        out.push({id: "repos", done: F.savedRepos.length > 0, label: t("wizard.v.repo"), detail: F.savedRepos.length + "", effect: t("wizard.v.repo.e")});
        return {rows: out};
      },
      finish: () => ({ok: true}),
    };
    const machine = (step, body) => {
      if (step === "state") return done({programs: [{program: "python", found: true, path: "/usr/bin/python3", needed_by: [{pack: "harness"}]}, ...packRows()], paths: [], bundle: {path: kbHere() ? "~/.harness/certs/ca-bundle.pem" : ""}, recipe: {proxy: kbHere() ? "proxy.example.test:9000" : "", tool_folders: []}});
      if (step === "folder-add") { if (/bad$/.test(body.path)) return fail("No " + body.program + " in that folder."); F.sqlcmd = true; return done({added: {}, missing: []}); }
      if (step === "toolpacks") return done({toolpacks: [{name: "ado", programs: {az: true}, connections: [{alias: "ado-main", saved: true}]}, {name: "sqlserver", programs: {sqlcmd: F.sqlcmd}, connections: [{alias: "sql-dev", saved: F.signed}, {alias: "sql-ist", saved: F.signed}]}]});
      return fail("fake: no step " + step);
    };
    return {
      setup: (step, body) => (setup[step] ? done(setup[step](body || {})) : fail("fake: no step " + step)),
      poll: (step, body) => (setup[step] ? done(setup[step](body || {}), 20) : fail("fake: no step " + step)),
      machine, machinePoll: machine,
      gh: (body) => {
        if (body.do === "login") { F.cop = "code"; F.codeAt = Date.now(); if (q("hold", "") !== "1") setTimeout(() => { if (F.cop === "code") F.cop = "done"; }, 2500); }
        if (body.do === "cancel") F.cop = "idle";
        return done({state: F.cop});
      },
      ready: () => done(ready(), 20),
      language: (language) => { F.lang = language; return done({language}); },
      fake: F,
    };
  }

  // ------------------------------------------------------------------------------------------------ the flow
  const known = {
    // is the part of the bar (0..5) already fine by what the computer says?
    1: () => Boolean(M.progs && M.progs.all_found),
    2: () => Boolean(copilotSignedIn(copilotLine())),
    3: () => Boolean(M.st && M.st.kb && M.st.kb.here && M.extras && !kbRest()),
    4: () => Boolean(M.saved.repos || (M.scan && M.scan.rows.some((row) => row.picked))),
  };
  const fine = (page) => (known[page - 1] ? known[page - 1]() : false);
  function nextFrom(page, step) {  // the next page that is not already fine; the review and the welcome are never skipped
    let at = page + step;
    while (at > 1 && at < 6 && fine(at)) at += step;
    return Math.max(0, Math.min(6, at));
  }
  function go(page, sub) {
    M.page = page;
    M.kbsub = sub || 0;
    try { sessionStorage.setItem(KEEP, JSON.stringify({page})); } catch (error) { /* a reload then starts at the welcome */ }
    render();
  }
  const forward = () => { if (M.fromReview) { M.fromReview = false; go(6); } else go(nextFrom(M.page, 1)); };
  const backward = () => { M.fromReview = false; go(nextFrom(M.page, -1)); };
  const leave = () => location.assign("/");

  // ------------------------------------------------------------------------------------------------ copilot's line of /api/ready
  const copilotLine = () => ((M.ready && M.ready.checks) || []).find((line) => line.id === "copilot") || null;
  const copilotSignedIn = (line) => Boolean(line) && (line.state === "ok" || ["host-starting", "host-preparing", "connecting", "models"].includes(line.why));
  function paintJob() {
    if (!shell) return;
    const line = copilotLine();
    const host = line && line.host;
    shell.job.hidden = !host;
    if (!host) return;
    const bar = el("span", "mini", h("i", {style: "width:" + Math.max(3, Math.min(100, Number(host.percent) || 0)) + "%"}));
    put(shell.job, spin(), t("wizard.job.prep"), bar, el("span", "wz-mono", host.total_mb ? t("wizard.job.mb", {a: Math.round(host.downloaded_mb || 0), b: Math.round(host.total_mb)}) : host.percent !== undefined ? host.percent + "%" : ""));
  }
  function pollReady() {
    return api.ready().then((found) => { M.ready = found; paintJob(); return found; }, () => null);
  }

  // ------------------------------------------------------------------------------------------------ the kb's extra pages: programs of the packs, connections
  const packPrograms = () => ((M.extras && M.extras.machine && M.extras.machine.programs) || []).filter((row) => row.program !== "python");
  const packConnections = () => {
    const out = [];
    (((M.extras && M.extras.packs) || {}).toolpacks || []).forEach((pack) => (pack.connections || []).forEach((conn) => out.push({alias: conn.alias, pack: pack.name, saved: Boolean(conn.saved)})));
    return out;
  };
  const kbRest = () => packPrograms().filter((row) => !row.found || row.blocked).length + packConnections().filter((row) => !row.saved).length;
  const subs = () => (M.kb.step === "done" && M.extras ? [0, ...(packPrograms().length ? [1] : []), ...(packConnections().length ? [2] : [])] : [0, 1, 2]);
  function loadExtras() {
    return Promise.all([api.machine("state").catch(() => null), api.machine("toolpacks").catch(() => null)]).then(([machine, packs]) => { M.extras = {machine: machine || {programs: []}, packs: packs || {toolpacks: []}}; });
  }

  // ------------------------------------------------------------------------------------------------ pages: each draws its question into `box` and says what its foot is
  // box: where to draw. opts: {bare, rerender(), changed(), next(), back(), jump(page, sub)}. It returns {stop(), foot()}: foot() = {back, later: {note}|null, why, main: {label, off, go}}.
  const parts = {};

  parts.welcome = function (box, opts) {
    const rows = (M.progs && M.progs.rows) || [];
    const row = (id) => rows.find((item) => item.id === id) || {found: false, version: ""};
    const line = copilotLine();
    const item = (label, value, kind) => el("div", "wz-it", dot(kind === "hot" ? "hot" : kind === "none" ? "none" : "ok"), el("span", "n", label), el("span", "v" + (kind === "hot" ? " hot" : ""), value));
    const prog = (id, key) => (row(id).found ? item(t(key), row(id).version || t("wizard.p.found"), "ok") : item(t(key), t("wizard.nf"), "hot"));
    const st = M.st;
    const signed = copilotSignedIn(line);
    const repos = M.scan ? M.scan.rows.length : 0;
    const cells = [
      item(t("wizard.l.name"), st.name || t("wizard.notyet"), st.name ? "ok" : "hot"), item(t("wizard.l.lang"), langName(M.lang), "ok"),
      prog("python", "wizard.l.py"), prog("git", "wizard.l.git"), prog("vscode", "wizard.l.code"), prog("gh", "wizard.l.gh"),
      item(t("wizard.l.sign"), signed ? (line.login || t("wizard.p.found")) : t("wizard.notyet"), signed ? "ok" : "hot"),
      item(t("wizard.l.kb"), st.kb.here ? (st.kb.version || t("wizard.p.found")) : t("wizard.notyet"), st.kb.here ? "ok" : "hot"),
      item(t("wizard.l.repo"), repos ? t("wizard.l.repo.v", {n: repos}) : t("wizard.nf"), "none"),
    ];
    const good = cells.filter((cell) => cell.querySelector(".wz-dot.ok")).length;
    const need = cells.length - good;
    const bot = el("div", "wz-bot");
    put(box, bot, h("h1", null, t("wizard.w.title")), el("p", "wz-sub", t("wizard.w.sub")), el("div", "wz-look", cells),
      el("p", "wz-look-sum", h("b", null, t("wizard.w.done", {a: good})), " \u00b7 ", t("wizard.w.rest", {b: need, c: need > 1 ? 4 : 1})));
    return {stop() {}, foot: () => ({back: false, later: null, why: "", main: {label: t("wizard.start"), go: opts.next, wide: true}})};
  };

  parts.you = function (box, opts) {
    const name = input("big", {maxlength: 100, autocomplete: "name", value: M.name, "aria-label": t("wizard.y.name")});
    const said = el("p", "wz-err"); said.hidden = true;
    const tile = (code) => {
      const b = h("button", {type: "button", class: "wz-tile" + (M.lang === code ? " on" : ""), "aria-pressed": M.lang === code ? "true" : "false"}, h("span", null, langName(code)), el("span", "ring"));
      b.addEventListener("click", () => { M.lang = code; put(tiles, tile("en"), tile("zh")); });
      return b;
    };
    const tiles = el("div", "wz-tiles", tile("en"), tile("zh"));
    name.addEventListener("input", () => { M.name = name.value; opts.changed(); });
    put(box, ...head(opts, "wizard.s.you", t("wizard.y.title"), t("wizard.y.sub")),
      el("div", "wz-field", el("span", "cap", t("wizard.y.name")), name, M.st && M.st.name_git && M.name ? el("div", "hint", t("wizard.y.hint")) : null),  // "Taken from your Git settings" only when Git gave the name
      el("div", "wz-field", el("span", "cap", t("wizard.y.lang")), tiles, el("div", "hint", t("wizard.y.lang.hint"))), said);
    const commit = () => {
      said.hidden = true;
      return api.setup("save", {part: "you", name: M.name.trim(), language: M.lang}).then(() => {
        M.saved.you = true;
        if (M.st) { M.st.name = M.name.trim(); M.st.language = M.lang; }
        if (!FAKE && M.lang !== document.documentElement.lang) {  // the texts are in the old language: the page loads again, and comes back here
          try {
            if (opts.bare) sessionStorage.setItem("harness.reopen", "settings:you");  // Settings: the window comes back at this section
            else sessionStorage.setItem(KEEP, JSON.stringify({page: nextFrom(M.page, 1)}));
          } catch (error) { /* starts at the welcome */ }
          location.reload();
          return;
        }
        opts.next();
      }, (error) => { said.textContent = errorText(error); said.hidden = false; });
    };
    return {stop() {}, focus: () => name.focus(), foot: () => ({back: true, later: null, why: "", main: {label: t("wizard.cont"), off: !M.name.trim(), go: commit}})};
  };

  parts.programs = function (box, opts) {
    const list = el("div", "wz-list");
    const wait = {values: new Map(), said: new Map(), busy: new Set()};
    let timer = 0, shown = "", stopped = false;
    const where = (row) => el("div", "wz-where", h("bdi", null, shortPath(row.path)));
    function fix(row) {
      const field = input("mono", {placeholder: t("wizard.p.ph"), "aria-label": t("wizard.p.or") + " " + row.name});
      field.value = wait.values.get(row.id) || "";
      field.addEventListener("input", () => wait.values.set(row.id, field.value));
      const say = el("p", "wz-err"); say.hidden = !wait.said.get(row.id); say.textContent = wait.said.get(row.id) || "";
      const use = btn(t("wizard.p.use"), "sm", () => {
        const value = field.value.trim();
        if (!value) return;
        use.disabled = true; wait.said.delete(row.id); say.hidden = true;
        api.setup("folder", {program: row.id, path: value}).then((found) => { wait.values.delete(row.id); take(found); }, (error) => { wait.said.set(row.id, errorText(error)); say.textContent = errorText(error); say.hidden = false; }).then(() => { use.disabled = false; });
      });
      field.addEventListener("keydown", (event) => { if (isEnter(event)) use.click(); });
      const download = row.download ? h("a", {class: "wz-btn sm primary", href: row.download, target: "_blank", rel: "noopener noreferrer"}, t("wizard.p.dl").replace("cli.github.com", new URL(row.download).host) , " \u2197") : null;
      return el("div", "wz-fix", download ? el("div", "line", download) : null, el("div", "line", t("wizard.p.or"), field, use), say, el("div", "watch", spin(), t("wizard.p.watch")));
    }
    function paintRow(row) {
      const ok = row.found && !row.blocked;
      const note = ok && row.id === "vscode" ? t("wizard.p.code.n") : ok && row.id === "harness" ? t("wizard.p.hc.n") : "";
      const how = {path: t("wizard.p.how.path"), folder: t("wizard.p.how.folder"), standard: t("wizard.p.how.standard")}[row.how] || "";
      const label = row.id === "harness" ? t("wizard.p.hc") : row.name;
      const state = ok ? el("span", "wz-state ok", dot("ok"), t("wizard.p.found")) : row.id === "harness" ? el("span", "wz-state", spin(), t("wizard.p.adding")) : el("span", "wz-state hot", dot("hot"), t(row.blocked ? "wizard.p.blocked" : "wizard.p.nf"));
      if (ok) state.title = how;
      const main = el("div", "wz-main", el("div", "wz-name", h("b", null, label), row.version ? h("small", null, row.version) : null),
        row.path ? where(row) : row.command && row.id === "harness" ? el("div", "wz-where plain", row.command) : null, note ? el("div", "wz-where plain", note) : null);
      const needsFix = !ok && row.id !== "harness";
      return el("div", "wz-li" + (needsFix ? " miss" : ""), el("span", "wz-ic", programIcon[row.id] || row.id.slice(0, 2)), main, state, needsFix ? fix(row) : null);
    }
    function take(found) {
      M.progs = found;
      const sign = JSON.stringify(found.rows.map((row) => [row.id, row.found, row.path, row.blocked, row.version]));
      if (sign !== shown) { shown = sign; put(list, ...found.rows.map(paintRow)); }
      opts.changed();
      const harness = found.rows.find((row) => row.id === "harness");
      if (harness && !harness.found && !M.shortTried) { M.shortTried = true; api.setup("short").then(() => api.poll("programs")).then(take, () => {}); }
    }
    function loop() {
      if (stopped) return;
      if (M.progs && M.progs.all_found && !(M.progs.rows || []).some((row) => !row.found && row.id === "harness")) { timer = setTimeout(loop, 3000); return; }  // everything is in: still looked at now and then
      api.poll("programs").then((found) => { if (!stopped) take(found); }, () => {}).then(() => { if (!stopped) timer = setTimeout(loop, 3000); });
    }
    put(box, ...head(opts, "wizard.s.prog", t("wizard.p.title"), t("wizard.p.sub")), list);
    if (M.progs) take(M.progs);
    timer = setTimeout(loop, 3000);
    const firstMissing = () => ((M.progs && M.progs.rows) || []).find((row) => row.required && (!row.found || row.blocked));
    return {stop() { stopped = true; clearTimeout(timer); }, foot() {
      const missing = firstMissing();
      return {back: !ONLY, later: null, why: missing ? t("wizard.p.need", {name: missing.name}) : "", main: {label: ONLY ? t("wizard.done") : t("wizard.cont"), off: Boolean(missing) || !M.progs, go: ONLY ? leave : opts.next}};
    }};
  };

  parts.copilot = function (box, opts) {
    const body = el("div");
    let timer = 0, stopped = false, shown = "", sawOut = false, advance = 0, starting = false, waitText = null;
    const said = el("p", "wz-err"); said.hidden = true;
    function paint() {
      const line = copilotLine() || {state: "wait", why: "starting"};
      const signed = copilotSignedIn(line);
      if (!signed) sawOut = true;
      const sign = JSON.stringify([line.state, line.why, line.code, line.url, line.login, line.detail, line.last, starting]);
      if (waitText) waitText.textContent = t("wizard.c.wait", {t: clock(line.left || 0)});
      if (sign === shown) { opts.changed(); return; }
      shown = sign;
      if (signed) {
        put(body, el("div", "wz-signed", el("span", "wz-big-ok", "\u2713"), el("div", null, el("div", "t1", t("wizard.c.done", {u: line.login || "GitHub"})), el("div", "t2", ONLY ? "" : t("wizard.c.next")))));
        if (sawOut && !ONLY && q("hold", "") !== "1" && !advance) advance = setTimeout(() => { if (!stopped) opts.next(); }, 1500);
      } else if (line.why === "signing-in") {
        waitText = null;
        const copy = btn(t("wizard.c.copy"), "sm", () => copyCommand(copy, line.code));
        copy.dataset.label = t("wizard.c.copy");
        const open = btn("", "primary", () => window.open(line.url || "https://github.com/login/device", "_blank", "noopener"));
        open.append(ghIcon(), t("wizard.c.open") + " \u2197");
        const cancel = link(t("wizard.c.cancel"), () => api.gh({do: "cancel"}).then(tick, () => {}));
        put(body, el("div", "wz-codebox", el("div", "cap", t("wizard.c.cap")), el("div", "wz-code", el("span", "digits", line.code || "\u2026"), copy),
          el("div", "acts", open, cancel), el("div", "waiting", spin(), waitText = el("span", null, t("wizard.c.wait", {t: clock(line.left || 0)})))));
      } else if (line.why === "no-gh" || line.why === "gh-broken") {
        put(body, el("p", "wz-err", t("wizard.c.nogh")), link(t("wizard.s.prog") + " \u2192", () => opts.jump(2)));
      } else {
        const start = btn("", "primary gh-btn", () => { starting = true; start.disabled = true; said.hidden = true; api.gh({do: "login"}).then(tick, (error) => { starting = false; said.textContent = errorText(error); said.hidden = false; start.disabled = false; }); });
        start.append(ghIcon(), t("wizard.c.btn"));
        start.disabled = starting;
        const why = line.last && line.last !== "cancelled" ? t("wizard.c.trouble", {why: line.detail || line.last}) : "";
        put(body, el("div", "wz-cp", start, el("div", "wz-under", t("wizard.c.how"))), why ? el("p", "wz-err", why) : null);
      }
      opts.changed();
    }
    function tick() { return pollReady().then(() => { if (!stopped) { starting = false; paint(); } }); }
    function loop() { if (!stopped) tick().then(() => { if (!stopped) timer = setTimeout(loop, 2000); }); }
    put(box, ...head(opts, "wizard.s.cop", t("wizard.c.title"), t("wizard.c.sub")), body, said);
    paint();
    timer = setTimeout(loop, 2000);
    return {stop() { stopped = true; clearTimeout(timer); clearTimeout(advance); }, foot: () => {
      const signed = copilotSignedIn(copilotLine());
      return {back: !ONLY, later: null, why: signed ? "" : t("wizard.c.need"), main: {label: ONLY ? t("wizard.done") : t("wizard.cont"), off: !signed, go: ONLY ? leave : opts.next}};
    }};
  };

  parts.kb = function (box, opts) {
    const sub = M.kbsub;
    const list = subs();
    const at = Math.max(0, list.indexOf(sub));
    const eyebrowText = t("wizard.k.eyebrow", {n: at + 1, m: list.length});
    const nextSub = () => { const rest = list.slice(at + 1); if (rest.length) { M.kbsub = rest[0]; opts.rerender(); } else opts.next(); };
    const prevSub = () => { if (at > 0) { M.kbsub = list[at - 1]; opts.rerender(); } else opts.back(); };
    let timer = 0, stopped = false;
    const stop = () => { stopped = true; clearTimeout(timer); };
    const later = (note) => ({note});

    if (sub === 1) return kbPrograms(box, opts, eyebrowText, nextSub, prevSub, stop);
    if (sub === 2) return kbConnections(box, opts, eyebrowText, nextSub, prevSub, stop);

    const k = M.kb, drop = {over: false};
    const zone = el("div");
    function startJob(path, mode, replace) {
      k.err = ""; k.step = "copy"; k.a = 0; k.b = 0; k.file = String(path).split(/[\\/]/).pop() || path;
      paint(); opts.changed();
      api.setup("probe", {kind: mode === "package" ? "package" : "folder", path}).then((probe) => {
        if (probe.full && !replace) {  // a knowledge base is in place already: replacing (or updating) it is the person's choice, said first
          k.step = "replace"; k.pending = {path, mode, why: probe.why || "", update: probe.update || null};
          paint(); opts.changed();
          return null;
        }
        if (!probe.ok && !(probe.full && replace)) throw new Error(probe.why || "?");
        return api.setup("save", {part: "kb", kb_mode: mode, kb_path: path, kb_replace: Boolean(replace)}).then(follow);
      }).catch((error) => { k.step = "empty"; k.err = errorText(error); paint(); opts.changed(); });
    }
    function follow() {
      if (stopped) return;
      api.poll("job").then((job) => {
        k.a = job.lines.length; k.b = job.total || job.lines.length;
        const bad = job.lines.find((line) => line.ok === false);
        if (bad) { k.step = "empty"; k.err = (bad.detail || "") + ""; paint(); opts.changed(); return; }
        if (job.running) { paint(); timer = setTimeout(follow, 1000); return; }
        return Promise.all([api.poll("state").then((st) => { M.st = Object.assign(M.st || {}, st); }), loadExtras()]).then(() => { k.step = "done"; paint(); opts.changed(); });
      }, (error) => { k.step = "empty"; k.err = errorText(error); paint(); opts.changed(); });
    }
    function choose(kind) {
      if (FAKE) return startJob(kind === "file" ? "sample-knowledge-base.zip" : "/Users/alex/sample-knowledge-base", kind === "file" ? "package" : "folder");
      DOCK.chooseOnPage(kind, "", (path) => startJob(path, kind === "file" ? "package" : "folder"));
    }
    function paint() {
      if (k.step === "empty") {
        const dropBox = el("div", "wz-drop", el("span", "wz-zip"), h("b", null, t("wizard.k.drop")), el("span", "or", t("wizard.k.or") + " ", link(t("wizard.k.file"), () => choose("file")), " \u00b7 ", link(t("wizard.k.folder"), () => choose("folder"))));
        dropBox.addEventListener("dragover", (event) => { event.preventDefault(); dropBox.classList.add("over"); });
        dropBox.addEventListener("dragleave", () => dropBox.classList.remove("over"));
        dropBox.addEventListener("drop", (event) => { event.preventDefault(); dropBox.classList.remove("over"); k.err = t("wizard.k.nodrop"); paint(); });  // a browser gives no path of a dropped file
        put(zone, dropBox, el("div", "wz-under", t("wizard.k.skipnote")), k.err ? el("p", "wz-err", k.err) : null);
      } else if (k.step === "replace") {
        const kb = (M.st && M.st.kb) || {}, ask = k.pending || {};
        const update = Boolean(ask.update && ask.update.state === "behind");  // a folder that is ahead of this copy updates it (what was changed here stays); any other replaces it (the old one is moved to a backup)
        const stat = (n, label) => el("div", "wz-stat", el("div", "n", n), el("div", "l", label));
        put(zone, el("div", "wz-kbcard wz-have", el("div", "wz-eyebrow", t("wizard.k.have")),
          el("div", "wz-kbhead", h("span", {class: "wz-big-ok", style: "width:36px;height:36px;font-size:17px"}, "\u2713"), h("div", {style: "flex:1;min-width:0"}, el("div", "ttl", (kb.prefix || t("wizard.k.name")) + (kb.version ? " \u00b7 " + kb.version : "")), el("div", "meta", kb.path || ""))),
          el("div", "wz-stats", stat(kb.domains || 0, t("wizard.k.dom")), stat(kb.domain_skills || 0, t("wizard.k.sk"))),
          el("p", "wz-sub wz-hv", ask.why || ""), el("p", "wz-sub wz-hv", t(update ? "wizard.k.update.note" : "wizard.k.replace.note")),
          el("div", "wz-choice", btn(t(update ? "wizard.k.update" : "wizard.k.replace"), "primary", () => startJob(ask.path, ask.mode, true)), link(t("wizard.k.keep"), () => { k.step = kb.here ? "done" : "empty"; k.pending = null; paint(); opts.changed(); }))));
      } else if (k.step === "copy") {
        put(zone, el("div", "wz-kbcard", el("div", "wz-kbhead", spin(), el("div", null, el("div", "ttl", k.file || ""), el("div", "meta", t("wizard.k.copying", {a: k.a, b: k.b || 3})))), el("div", "wz-meter", h("i", {style: "width:" + (k.b ? Math.round(100 * k.a / k.b) : 8) + "%"}))));
      } else {
        const kb = (M.st && M.st.kb) || {}, company = (M.st && M.st.company) || {};
        const stat = (n, label) => el("div", "wz-stat", el("div", "n", n), el("div", "l", label));
        const title = (kb.prefix || t("wizard.k.name")) + (kb.version ? " \u00b7 " + kb.version : "");
        const again = link(t("wizard.k.other"), () => { k.step = "empty"; k.err = ""; paint(); opts.changed(); });
        put(zone, el("div", "wz-kbcard", el("div", "wz-kbhead", h("span", {class: "wz-big-ok", style: "width:36px;height:36px;font-size:17px"}, "\u2713"), h("div", {style: "flex:1;min-width:0"}, el("div", "ttl", title), el("div", "meta", kb.path || "")), again),
          el("div", "wz-eyebrow", t("wizard.k.brought")), el("div", "wz-stats", stat(kb.domains || 0, t("wizard.k.dom")), stat(kb.domain_skills || 0, t("wizard.k.sk")), stat((company.packs || []).length, t("wizard.k.tp")), stat((company.connections || []).length, t("wizard.k.cn")), stat((company.recipe || {}).present ? "\u2713" : "\u2013", t("wizard.k.px")))));
      }
    }
    k.step = M.kb.step === "empty" && M.st && M.st.kb && M.st.kb.here ? "done" : M.kb.step;
    if (FAKE && q("kb", "") === "copy" && k.step === "copy" && !M.kbFakeStarted) { M.kbFakeStarted = true; k.a = 1; k.b = 2; k.file = "sample-knowledge-base.zip"; }
    put(box, ...head(opts, eyebrowText, t("wizard.k.title"), t("wizard.k.sub")), zone);
    paint();
    if (k.step === "copy" && !k.file) follow();
    if (k.step === "done" && !M.extras) loadExtras().then(() => { if (!stopped) { opts.rerender(); } });
    return {stop, foot: () => (k.step === "done"
      ? {back: true, later: null, why: "", main: {label: t("wizard.cont"), go: nextSub}, backGo: prevSub}
      : {back: true, later: k.step === "replace" ? null : later(t("wizard.k.skipnote")), why: "", main: {label: t("wizard.cont"), off: true, go: nextSub}, backGo: prevSub})};
  };

  function kbPrograms(box, opts, eyebrowText, nextSub, prevSub, stop) {
    const list = el("div", "wz-list");
    let timer = 0, stopped = false, shown = "";
    const wait = {values: new Map(), said: new Map()};
    const forWho = (row) => (row.needed_by || []).map((item) => item.pack).filter((name) => name && name !== "harness").join(", ");
    function fix(row) {
      const field = input("mono", {placeholder: t("wizard.p.ph"), "aria-label": t("wizard.p.or") + " " + row.program});
      field.value = wait.values.get(row.program) || "";
      field.addEventListener("input", () => wait.values.set(row.program, field.value));
      const say = el("p", "wz-err"); say.hidden = !wait.said.get(row.program); say.textContent = wait.said.get(row.program) || "";
      const use = btn(t("wizard.p.use"), "sm", () => {
        const value = field.value.trim();
        if (!value) return;
        use.disabled = true; wait.said.delete(row.program); say.hidden = true;
        api.machine("folder-add", {program: row.program, path: value}).then(() => { wait.values.delete(row.program); return refresh(); }, (error) => { wait.said.set(row.program, errorText(error)); say.textContent = errorText(error); say.hidden = false; }).then(() => { use.disabled = false; });
      });
      field.addEventListener("keydown", (event) => { if (isEnter(event)) use.click(); });
      return el("div", "wz-fix", el("div", "line", t("wizard.p.or"), field, use), say, el("div", "watch", spin(), t("wizard.p.watch")));
    }
    function paint() {
      const rows = packPrograms();
      const sign = JSON.stringify(rows.map((row) => [row.program, row.found, row.path, row.blocked]));
      if (sign !== shown) {
        shown = sign;
        const machine = (M.extras && M.extras.machine) || {};
        const bundle = machine.bundle && machine.bundle.path;
        const items = rows.map((row) => {
          const ok = row.found && !row.blocked;
          return el("div", "wz-li" + (ok ? "" : " miss"), el("span", "wz-ic", row.program.slice(0, 3)), el("div", "wz-main", el("div", "wz-name", h("b", null, row.program), h("small", null, t("wizard.t.for", {p: forWho(row)}))), ok ? el("div", "wz-where", h("bdi", null, shortPath(row.path))) : null),
            ok ? el("span", "wz-state ok", dot("ok"), t("wizard.p.found")) : el("span", "wz-state hot", dot("hot"), t(row.blocked ? "wizard.p.blocked" : "wizard.p.nf")), ok ? null : fix(row));
        });
        if (bundle) items.push(el("div", "wz-li", el("span", "wz-ic", "ca"), el("div", "wz-main", el("div", "wz-name", h("b", null, t("wizard.t.net"))), el("div", "wz-where plain", t("wizard.t.made"))), el("span", "wz-state ok", dot("ok"), "\u2713")));
        put(list, ...items);
      }
      opts.changed();
    }
    const refresh = () => api.machinePoll ? api.machinePoll("state").then((machine) => { if (!stopped) { M.extras.machine = machine; paint(); } }, () => {}) : Promise.resolve();
    function loop() { if (stopped) return; timer = setTimeout(() => { if (!packPrograms().some((row) => !row.found || row.blocked)) return loop(); refresh().then(loop); }, 3000); }
    put(box, ...head(opts, eyebrowText, t("wizard.t.title"), t("wizard.t.sub")), list);
    paint();
    loop();
    const miss = () => packPrograms().filter((row) => !row.found || row.blocked);
    return {stop() { stopped = true; clearTimeout(timer); stop(); }, foot: () => {
      const rows = miss();
      return {back: true, backGo: prevSub, later: {note: rows.length ? t("wizard.t.skipnote", {pack: forWho(rows[0]), program: rows[0].program}) : ""}, laterGo: nextSub, why: "", main: {label: t("wizard.cont"), off: rows.length > 0, go: nextSub}};
    }};
  }

  function kbConnections(box, opts, eyebrowText, nextSub, prevSub, stop) {
    const list = el("div", "wz-list");
    function paint() {
      put(list, ...packConnections().map((row) => {
        const state = row.saved ? el("span", "wz-state ok", dot("ok"), t("wizard.n.ok")) : btn(t("wizard.n.sign"), "sm", () => signIn());
        return el("div", "wz-li", el("span", "wz-ic", row.pack.slice(0, 3)), el("div", "wz-main", el("div", "wz-name", h("b", null, row.alias)), el("div", "wz-where plain", row.pack)), state);
      }));
      opts.changed();
    }
    const refresh = () => api.machine("toolpacks").then((packs) => { M.extras.packs = packs; paint(); }, () => {});
    function signIn() {
      if (FAKE) { api.fake.signed = true; ((M.extras.packs.toolpacks || []).forEach((pack) => (pack.connections || []).forEach((conn) => { conn.saved = true; }))); paint(); return; }
      const title = h("h2"), sub = h("p", {class: "sub tl-sub"}), body = h("div", {class: "win-body tl-body"}), foot = h("div", {class: "row win-foot"});
      const close = h("button", {type: "button", class: "act"}, t("connections.close"));
      const view = SERVE.dialog([title, sub, body, foot]);
      view.box.classList.add("wide", "sv-win", "tl-win");
      const made = SERVERS.connectionsPanel({go: () => {}, close: view.close, arrived: () => {}});
      put(title, made.title);
      sub.textContent = made.sub;
      put(body, ...made.body);
      put(foot, ...made.foot, h("span", {class: "tl-grow"}), close);
      close.addEventListener("click", view.close);
      const watch = setInterval(() => { if (!view.box.isConnected) { clearInterval(watch); refresh(); } }, 400);
    }
    put(box, ...head(opts, eyebrowText, t("wizard.n.title"), t("wizard.n.sub")), list);
    paint();
    return {stop, foot: () => ({back: true, backGo: prevSub, later: {note: ""}, why: "", main: {label: t("wizard.cont"), go: nextSub}})};
  }

  parts.repos = function (box, opts) {
    const scan = M.scan || {places: [], rows: [], more: false};
    if (!M.picks) M.picks = new Set(scan.rows.filter((row) => row.picked).map((row) => row.path));
    const rows = scan.rows.slice();
    const listBox = el("div"), count = el("span", "cnt");
    const filter = input("", {placeholder: t("wizard.r.filter"), "aria-label": t("wizard.r.filter"), value: M.filter});
    const said = el("p", "wz-err"); said.hidden = true;
    const visible = () => { const word = M.filter.trim().toLowerCase(); return word ? rows.filter((row) => (row.name + " " + row.shown).toLowerCase().includes(word)) : rows; };
    function paint() {
      all.hidden = !rows.length; filter.hidden = !rows.length;
      const shownRows = visible();
      if (!rows.length) { put(listBox, el("div", "wz-list", el("div", "wz-empty", t("wizard.r.none")))); count.textContent = ""; opts.changed(); return; }
      put(listBox, el("div", "wz-list wz-scroll", ...shownRows.map((row) => {
        const on = M.picks.has(row.path);
        const item = el("div", "wz-li wz-repo", el("span", "wz-box" + (on ? " on" : ""), on ? "\u2713" : ""), el("div", "wz-main", el("span", "wz-name", row.name), el("div", "wz-where", h("bdi", null, row.shown || row.path))));
        item.setAttribute("role", "checkbox"); item.setAttribute("aria-checked", on ? "true" : "false"); item.tabIndex = 0;
        const flip = () => { if (on) M.picks.delete(row.path); else M.picks.add(row.path); paint(); };
        item.addEventListener("click", flip);
        item.addEventListener("keydown", (event) => { if (event.key === " " || isEnter(event)) { event.preventDefault(); flip(); } });
        return item;
      })));
      count.textContent = t("wizard.r.found", {n: rows.length, places: scan.places.join(t("wizard.r.and"))});
      opts.changed();
    }
    filter.addEventListener("input", () => { M.filter = filter.value; paint(); });
    const all = link(t("wizard.r.all"), () => { const shownRows = visible(); const every = shownRows.every((row) => M.picks.has(row.path)); shownRows.forEach((row) => (every ? M.picks.delete(row.path) : M.picks.add(row.path))); paint(); });
    const add = link("+ " + t("wizard.r.add"), () => {
      const taken = (path) => { api.setup("repo", {path, repos_root: "", singles: [...M.picks]}).then((found) => {
        const fresh = (found.kind === "repo" ? [{path: found.path, name: found.name}] : (found.repos || []).filter((row) => !row.held && !row.off)).filter((row) => !rows.some((have) => have.path === row.path));
        fresh.forEach((row) => { rows.push({path: row.path, shown: row.path, name: row.name, branch: "", picked: true}); M.picks.add(row.path); });
        scan.rows = rows; said.hidden = true; paint();
      }, (error) => { said.textContent = errorText(error); said.hidden = false; }); };
      if (FAKE) taken("/Users/alex/Developer/extra-service-" + (rows.length + 1));
      else DOCK.chooseOnPage("folder", "", taken);
    });
    put(box, ...head(opts, "wizard.s.repo", t("wizard.r.title"), t("wizard.r.sub")), el("div", "wz-tools", filter, count, el("span", "wz-grow"), all), listBox, el("div", "wz-under", add), said);
    paint();
    const commit = () => api.setup("save", {part: "repos", paths: [...M.picks]}).then(() => { M.saved.repos = true; opts.next(); }, (error) => { said.textContent = errorText(error); said.hidden = false; });
    return {stop() {}, foot: () => {
      const n = M.picks.size;
      return {back: true, later: {note: t("wizard.v.repo.e")}, why: "", main: {label: n ? t("wizard.r.cont", {n}) : t("wizard.cont"), off: !n, go: commit}};
    }};
  };

  parts.review = function (box, opts) {
    const holder = el("div");
    let summary = null, finishing = false;
    const where = {you: [1], programs: [2], copilot: [3], kb: [4, 0], packs: [4, 1], connections: [4, 2], repos: [5]};
    const said = el("p", "wz-err"); said.hidden = true;
    function paint() {
      if (!summary) { put(holder, ); return; }
      const ok = summary.rows.filter((row) => row.done), no = summary.rows.filter((row) => !row.done);
      const parts = [];
      if (ok.length) parts.push(el("div", "wz-grp", h("h4", null, t("wizard.v.done")), el("div", "wz-donegrid", ok.map((row) => el("div", "wz-d", dot("ok"), h("b", null, row.label), el("span", "s", row.detail || ""))))));
      if (no.length) parts.push(el("div", "wz-grp", h("h4", null, t("wizard.v.todo")), listOf(no.map((row) => {
        const set = btn(t("wizard.v.set"), "sm", () => { M.fromReview = true; const spot = where[row.id] || [2]; go(spot[0], spot[1] || 0); });
        return el("div", "wz-li wz-rv", dot("hot"), el("div", "wz-main", el("div", "t", row.label), el("div", "eff", row.effect || "")), set);
      }))));
      if (no.length) parts.push(el("div", "wz-later", el("span", "wz-gear", "\u2699"), t("wizard.v.later")));
      put(holder, ...parts);
      opts.changed();
    }
    put(box, ...head(opts, "wizard.s.rev", t("wizard.v.title"), t("wizard.v.sub")), holder, said);
    api.setup("summary").then((found) => { summary = found; paint(); }, (error) => { said.textContent = errorText(error); said.hidden = false; });
    const confirm = () => { finishing = true; opts.changed(); said.hidden = true; return api.setup("finish").then(() => { try { sessionStorage.removeItem(KEEP); } catch (error) { /* nothing kept */ } leave(); }, (error) => { finishing = false; said.textContent = errorText(error); said.hidden = false; opts.changed(); }); };
    return {stop() {}, foot: () => ({back: true, later: null, why: "", main: {label: t("wizard.v.go"), off: !summary || finishing, go: confirm}})};
  };

  // ------------------------------------------------------------------------------------------------ the shell: top line, bar, page, foot, strip
  function bar() {
    const idx = M.page - 1;
    const part = M.page === 4 ? ((subs().indexOf(M.kbsub) + 1) / subs().length) * 100 : 55;
    // a part is done when the computer says it is fine ("You" cannot be skipped, so behind us it is done); a part behind us that is not fine was skipped with Later: a yellow dot, never a tick
    const state = (i) => (i === idx ? "cur" : fine(i + 1) || (i === 0 && i < idx) ? "done" : i < idx ? "skip" : null);
    const bars = SEGMENTS.map((key, i) => h("i", {class: state(i), style: "--part:" + part + "%"}));
    const names = SEGMENTS.map((key, i) => h("span", {class: state(i)}, state(i) === "done" ? [tick(), ""] : state(i) === "skip" ? [dot("hot wz-skip"), ""] : "", t(key)));
    return el("div", "wz-prog", el("div", "wz-bars", bars), el("div", "wz-names", names));
  }

  function render() {
    if (ctl && ctl.stop) ctl.stop();
    ctl = null;
    const root = document.getElementById("app");
    const name = PAGES[M.page];
    const alone = Boolean(ONLY);
    const content = el("div");
    const footRow = el("div", "wz-row");
    const job = el("div", "wz-job"); job.hidden = true;
    shell = {job, footRow};
    const count = el("div", "wz-count", M.page && !alone ? t("wizard.step", {n: M.page, m: 6}) : "");
    root.className = "wz" + (name === "welcome" ? " wz-hello" : "");
    put(root, el("div", "wz-top", el("div", "wz-brand", el("span", "wz-bot"), "HARNESS"), count), M.page && !alone ? bar() : "", el("div", "wz-body", el("div", "wz-page", content, el("div", "wz-foot", footRow))), job);
    const opts = {
      changed: drawFoot, rerender: render, next: forward, back: backward,
      jump: (page) => go(page),
    };
    ctl = parts[name](content, opts);
    drawFoot();
    paintJob();
    if (ctl.focus) ctl.focus();
    document.querySelector(".wz-body").scrollTop = 0;
  }
  function drawFoot() {
    if (!ctl || !shell) return;
    const foot = ctl.foot();
    const back = foot.back ? btn("\u2190 " + t("wizard.back"), "", foot.backGo || backward) : null;
    const later = foot.later ? link(t("wizard.skip"), foot.laterGo || (() => (M.fromReview ? forward() : go(nextFrom(M.page, 1)))), foot.later.note) : null;  // `laterGo`: a small page of the knowledge base goes on to the next small page, not past all of them
    const main = btn(foot.main.label + " \u2192", "primary" + (foot.main.off ? " off" : ""), () => { if (!foot.main.off) foot.main.go(); });
    if (foot.main.wide) main.style.minWidth = "200px";
    if (foot.main.off) main.setAttribute("aria-disabled", "true");
    put(shell.footRow, ...(foot.main.wide ? [el("span", "wz-grow"), main, el("span", "wz-grow")] : [back, el("span", "wz-grow"), foot.why ? el("span", "wz-why", foot.why) : null, later, main]));
  }

  // ------------------------------------------------------------------------------------------------ start
  // What the pages know, read from the back end: the state, the programs, the readiness and the repositories found. Settings asks for it each time it opens a section (`opts.fresh` keeps what was read).
  function load() {
    const first = (promise) => promise.catch(() => null);
    return Promise.all([first(api.setup("state")), first(api.setup("programs")), first(api.ready()), first(api.setup("scan"))]).then(([st, progs, ready, scan]) => {
      M.st = st || {name: "", language: document.documentElement.lang || "en", kb: {here: false}, company: {packs: [], connections: [], recipe: {}}};
      M.progs = progs;
      M.ready = ready;
      M.scan = scan || {places: [], rows: [], more: false};
      M.name = M.st.name || "";
      M.lang = FAKE ? q("lang", M.st.language || "en") : (M.st.language || document.documentElement.lang || "en");
      M.kb.step = M.st.kb && M.st.kb.here ? "done" : q("kb", "") === "copy" && FAKE ? "copy" : "empty";
    });
  }

  function start() {
    const root = document.getElementById("app");
    document.body.classList.add("wz-doc");  // the page has no gear and no help beside it (wizard.css)
    root.className = "wz wz-loading";
    put(root, );
    const theme = q("theme", "");
    if (FAKE && (theme === "light" || theme === "dark")) document.documentElement.setAttribute("data-theme", theme);
    api = FAKE ? fakeApi() : realApi();
    load().then(() => {
      let page = Number(q("page", "")) ;
      if (ONLY) page = ONLY === "programs" ? 2 : 3;
      else if (!Number.isFinite(page) || !q("page", "")) {
        page = 0;
        try { const kept = JSON.parse(sessionStorage.getItem(KEEP) || "null"); if (kept && Number.isInteger(kept.page)) page = Math.max(0, Math.min(6, kept.page)); sessionStorage.removeItem(KEEP); } catch (error) { page = 0; }
      }
      M.page = Math.max(0, Math.min(6, page));
      M.kbsub = Number(q("kbsub", "0")) || 0;
      if (FAKE && M.page === 5 && !M.picks) M.picks = new Set([0, 1, 3].map((n) => M.scan.rows[n]).filter(Boolean).map((row) => row.path));
      const needs = M.page === 4 && M.kb.step === "done" ? loadExtras() : Promise.resolve();
      return needs.then(() => pollReady()).then(() => {
        render();
        readyTimer = setInterval(() => { if (!document.hidden && !(ctl && M.page === 3)) pollReady(); }, 5000);
      });
    });
  }

  // ------------------------------------------------------------------------------------------------ for the Settings window (settings.js)
  // `prepare()` reads what the pages know (again each time). `mount(name, box, hooks)` draws one page bare: no title, no bar, no Back or Later. The page's own button is made by the caller from `foot()`:
  // {main: {label, off, go}}; `hooks.changed()` says when it may have changed, `hooks.saved()` when the page saved and wanted to go on. The kb page stays on its first small page (the import).
  function prepare() {
    if (!api) api = FAKE ? fakeApi() : realApi();
    M.picks = null; M.extras = null; M.kbsub = 0; M.fromReview = false;
    return load().then(() => pollReady()).then(() => {
      // a repository kept that the scan did not find (outside the usual places) is shown too, or saving the page would drop it
      const have = new Set(M.scan.rows.map((row) => row.path));
      ((M.st && M.st.singles) || []).forEach((path) => { if (!have.has(path)) { M.scan.rows.unshift({path, shown: path, name: String(path).split(/[\\/]/).pop() || path, branch: "", picked: true}); have.add(path); } });
    });
  }
  function mount(name, box, hooks) {
    const opts = {bare: true, changed: hooks.changed || (() => {}), rerender: hooks.rerender || (() => {}), next: hooks.saved || (() => {}), back: () => {}, jump: hooks.jump || (() => {})};
    M.kbsub = 0;
    return parts[name](box, opts);
  }

  if (typeof DATA !== "undefined" && DATA.wizard) start();
  return {parts, M, start, go, prepare, mount};
})();
