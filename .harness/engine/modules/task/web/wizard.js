// The first-run setup wizard (O2): one page, one question, a bar of six parts on top. The server does the work (modules/task/boardserve.py `/api/setup` steps programs, folder,
// scan, save, summary, finish, and the old ones); this page shows and sends. Needs common.js (h, t, clock, copyCommand), serve.js (SERVE), readyui.js (READY: dock.js reads it when it loads), dock.js (DOCK: the folder picker), servers.js (SERVERS: the connections window).
// `?only=programs` and `?only=copilot` draw that one page with a Done button (the Enter screen's fix button). `?fake=1` answers every call from data in the contract's shape, so the page walks end to end with no server
// work; more parameters pick a state for a picture: page, prog=missing|all|long, cop=idle|code|done, kb=empty|copy|done, kbsub, longname=1, job=0|1, lang, theme, hold=1 (no automatic step forward).
// (1.8.33) How it moves: the shell (top line, bar, robot, foot) is built once; a page turn, the bar, the robot and the foot go through motion.js and robot.js (see the shell section). Settings draws none of it.
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
  let holding = false;  // a language was written and this page is about to load again: serve.js waits (E6)
  if (typeof SERVE !== "undefined" && SERVE.stay) SERVE.stay(() => holding);

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
      host: (body) => send("/api/host", body),
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
    if (q("inroot", "") === "1") F.repos.slice(0, 2).forEach((row) => { row.picked = true; row.in_root = true; });  // ?inroot=1: two rows found through the repositories folder
    const rows = () => [
      {id: "python", name: "Python", required: true, found: true, path: long ? "C:\\Users\\a.very.long.user.name\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" : "/opt/homebrew/bin/python3", version: "3.12.4", how: "path", download: "https://www.python.org/downloads/", blocked: ""},
      {id: "git", name: "Git", required: true, found: true, path: long ? "C:\\Program Files\\Git\\cmd\\git.exe" : "/usr/bin/git", version: q("git", "") === "fails" ? "" : "2.47.1", how: "path", download: "https://git-scm.com/downloads", blocked: "", trouble: q("git", "") === "fails" ? "fails" : q("git", "") === "slow" ? "slow" : "", why: q("git", "") === "fails" ? "xcode-select: note: no developer tools were found" : ""},
      {id: "vscode", name: "VS Code", required: true, found: true, path: long ? "C:\\Users\\a.very.long.user.name\\AppData\\Local\\Programs\\Microsoft VS Code\\bin\\code.cmd" : "/usr/local/bin/code", version: "1.147.0", how: "standard", download: "https://code.visualstudio.com/download", blocked: ""},
      F.ghFound ? {id: "gh", name: "GitHub CLI", required: true, found: true, path: long ? "C:\\Users\\a.very.long.user.name\\AppData\\Local\\Programs\\GitHub CLI\\gh.exe" : "/opt/homebrew/bin/gh", version: "2.105.0", how: "path", download: "https://cli.github.com/", blocked: ""}
        : {id: "gh", name: "GitHub CLI", required: true, found: false, path: "", version: "", how: "", download: "https://cli.github.com/", blocked: ""},
      {id: "harness", name: "harness command", required: false, found: F.ranHarness || q("harness", "1") === "1", path: "/usr/local/bin/harness", version: "1.8.26", how: "path", download: "", blocked: "", command: "python3 .harness/engine/harness.py short"},
    ];
    const programs = () => { const list = rows(); return {rows: list, all_found: list.filter((row) => row.required).every((row) => row.found && !row.blocked && !row.trouble)}; };
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
      if (F.cop === "code" && !F.codeAt) F.codeAt = Date.now();  // the fake code runs down from its first look
      if (F.cop === "code") return {id: "copilot", state: "wait", why: "signing-in", code: "5F59-4EB2", url: "https://github.com/login/device", left: F.codeAt ? Math.max(0, 872 - Math.round((Date.now() - F.codeAt) / 1000)) : 872};
      if (F.cop === "done") return {id: "copilot", state: "ok", why: "ok", login: "alex", n: 25};
      if (q("cop", "") === "hostfailed") return {id: "copilot", state: "fail", why: "host-failed", detail: "it could not open its port", login: "alex"};  // ?cop=hostfailed | error: the lines that are not about the sign-in
      if (q("cop", "") === "error") return {id: "copilot", state: "fail", why: "error", detail: "OSError: the check could not read its state"};
      return {id: "copilot", state: "fail", why: F.ghFound ? "signin" : "no-gh", gh: "/opt/homebrew/bin/gh"};
    };
    const ready = () => {
      const line = copilot();
      if (q("job", "1") === "1" && M.page >= 3) {  // the fake download moves (about 6 MB a second from 312, and stops before the end), so a picture taken later does not look frozen (1.8.32)
        F.jobAt = F.jobAt || Date.now();
        const lapse = (Date.now() - F.jobAt) / 1000, mb = Math.min(600, 312 + Math.floor(lapse * 6));
        line.host = {state: "preparing", seconds: 64 + Math.floor(lapse), downloaded_mb: mb, total_mb: 620, percent: Math.round(mb / 620 * 100)};
      }
      return {ready: false, checks: [line]};
    };
    const setup = {
      state, programs: () => programs(),
      folder: (body) => (!String(body.path || "").trim() || /bad$/.test(body.path) ? fail("No " + body.program + " in that folder.") : (F.ghFound = true, programs())),
      short: () => { F.shortTries = (F.shortTries || 0) + 1; if (q("short", "") === "fail" && F.shortTries < 2) throw new Error("Could not write the short command: permission denied for /usr/local/bin"); F.ranHarness = true; return {done: true}; },  // ?short=fail: the first try fails
      scan: () => ({places: ["~/Developer", "~/source/repos"].slice(0, count ? 2 : 0), rows: F.repos, more: false}),
      probe: (body) => (/ahead$/.test(body.path) ? {ok: false, why: "The knowledge base here has 4 commits that this folder does not have (listed below). They stay, and nothing was changed. Send them to the folder first, then update again.", update: {state: "ahead", ahead: 4, branch: "main", subjects: ["Add the glossary page", "Fix a link in the checks", "Rename the sample domain"], pull: "git -C ./kb push ./folder main", send: {folder: body.path, branch: "main", ahead: 4, subjects: ["Add the glossary page", "Fix a link in the checks", "Rename the sample domain"]}}} : /bad$/.test(body.path) ? {ok: false, why: "Nothing in it looks like a knowledge base."} : kbHere() && body.kind === "folder" ? {ok: false, full: true, why: "A knowledge base is in place already, and this folder has no history in common with it."} : {ok: true, why: "", version: "3.2.0"}),
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
        const out = [{id: "you", required: true, done: true, label: t("wizard.v.you"), detail: F.name + " \u00b7 " + langName(F.lang), effect: ""},
          {id: "programs", required: true, done: list.all_found, label: t("wizard.v.prog"), detail: t("wizard.v.prog.s", {n: 5, total: 5}), effect: ""},
          {id: "copilot", required: true, done: F.cop === "done", label: t("wizard.v.cop"), detail: "alex", effect: ""}];
        out.push({id: "kb", done: kbHere(), label: t("wizard.v.kb"), detail: kbHere() ? "sample \u00b7 3.2.0" : "", effect: kbHere() ? "" : "No tool packs and no connections: the agent has only what the harness brings. You can bring one in later in Settings."});
        if (kbHere()) {
          out.push({id: "packs", done: F.sqlcmd, label: t("wizard.v.sq"), detail: "", effect: t("wizard.v.sq.e")});
          out.push({id: "connections", done: F.signed, label: t("wizard.v.cn"), detail: "", effect: t("wizard.v.cn.e")});
        }
        out.push({id: "repos", done: F.savedRepos.length > 0, label: t("wizard.v.repo"), detail: t(F.savedRepos.length === 1 ? "wizard.v.repo.s.one" : "wizard.v.repo.s", {n: F.savedRepos.length}), effect: t("wizard.v.repo.e")});
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
      setup: (step, body) => { try { return setup[step] ? done(setup[step](body || {})) : fail("fake: no step " + step); } catch (error) { return fail(error.message); } },
      poll: (step, body) => (setup[step] ? done(setup[step](body || {}), 20) : fail("fake: no step " + step)),
      machine, machinePoll: machine,
      gh: (body) => {
        if (body.do === "login") { F.cop = "code"; F.codeAt = Date.now(); if (q("hold", "") !== "1") setTimeout(() => { if (F.cop === "code") F.cop = "done"; }, 2500); }
        if (body.do === "cancel") F.cop = "idle";
        return done({state: F.cop});
      },
      host: (body) => done(body.do === "restart" && q("busy", "") === "1" ? {state: "waiting", busy: ["fix-the-tests", "write-notes"]} : {state: "restarted", busy: []}),
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
  // (1.8.32) What the person chose, as saved: the rows the scan marks as chosen, plus what was saved in this visit; the Welcome page counts this, never the number found
  function chosenRepos() {
    const rows = (M.scan && M.scan.rows) || [];
    return rows.filter((row) => row.picked || row.in_root || (M.saved.repos && M.picks && M.picks.has(row.path))).length;
  }
  // (1.8.32) "about N min" for Welcome: one minute for each page that will really show (the pages already fine are skipped), and the review
  const minutes = () => Math.max(1, [1, 2, 3, 4, 5].filter((page) => !fine(page)).length + 1);
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
    shell.job.title = host ? t("wizard.job.tip") : "";  // (1.8.32) what the download is, said on hover
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
  const packMissing = () => packPrograms().filter((row) => !row.found || row.blocked);
  const kbRest = () => packMissing().length + packConnections().filter((row) => !row.saved).length;
  const subs = () => (M.kb.step === "done" && M.extras ? [0, ...(packMissing().length || M.kbsub === 1 ? [1] : []), ...(packConnections().length ? [2] : [])] : [0, 1, 2]);  // the programs page only when one is missing (it stays while the person is on it)
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
    const item = (label, value, kind) => el("div", "wz-it", dot(kind === "hot" ? "hot" : "ok"), el("span", "n", label), el("span", "v" + (kind === "hot" ? " hot" : ""), value));  // (1.8.32) hot = orange dot and words
    const prog = (id, key) => (row(id).found && !row(id).trouble && !row(id).blocked ? item(t(key), row(id).version || t("wizard.p.found"), "ok") : item(t(key), t("wizard.nf"), "hot"));
    const st = M.st;
    const signed = copilotSignedIn(line);
    const found = M.scan ? M.scan.rows.length : 0;
    const chosen = chosenRepos();  // (1.8.32) the saved answer, not what was found
    const cells = [
      item(t("wizard.l.name"), st.name || t("wizard.notyet"), st.name ? "ok" : "hot"), item(t("wizard.l.lang"), langName(M.lang), "ok"),
      prog("python", "wizard.l.py"), prog("git", "wizard.l.git"), prog("vscode", "wizard.l.code"), prog("gh", "wizard.l.gh"),
      item(t("wizard.l.sign"), signed ? (line.login || t("wizard.p.found")) : t("wizard.notyet"), signed ? "ok" : "hot"),
      item(t("wizard.l.kb"), st.kb.here ? (st.kb.version || t("wizard.p.found")) : t("wizard.notyet"), st.kb.here ? "ok" : "hot"),
      chosen ? item(t("wizard.l.repo"), t(chosen === 1 ? "wizard.l.repo.n.one" : "wizard.l.repo.n", {n: chosen}), "ok") : item(t("wizard.l.repo"), found ? t("wizard.l.repo.v", {n: found}) : t("wizard.nf"), "hot"),  // none chosen yet: orange, in words that say so (1.8.32)
    ];
    const good = cells.filter((cell) => cell.querySelector(".wz-dot.ok")).length;
    const need = cells.length - good;
    put(box, el("div", "wz-slot"), h("h1", null, t("wizard.w.title")), el("p", "wz-sub", t("wizard.w.sub")), el("div", "wz-look", cells),
      el("p", "wz-look-sum", h("b", null, t("wizard.w.done", {a: good})), " \u00b7 ", t("wizard.w.rest", {b: need, c: minutes()})));
    return {stop() {}, foot: () => ({back: false, later: null, why: "", main: {label: t("wizard.start"), go: opts.next, wide: true}})};
  };

  parts.you = function (box, opts) {
    const name = input("big", {maxlength: 100, autocomplete: "name", value: M.name, "aria-label": t("wizard.y.name")});
    const said = el("p", "wz-err"); said.hidden = true;
    let kept = false;  // Settings: the page loaded again after a language was saved; it says so, the footer's note went with the old page
    try { kept = Boolean(opts.bare) && Date.now() - Number(sessionStorage.getItem("harness.saved.you") || 0) < 8000; } catch (error) { /* no note */ }  // the section may be drawn twice while the window reopens: the mark is not taken away, it just gets old
    const savedNote = el("p", "wz-saved", kept ? "\u2713 " + t("settings.saved") : "");
    if (kept) setTimeout(() => { savedNote.textContent = ""; }, 4000);
    const tile = (code) => {
      const b = h("button", {type: "button", class: "wz-tile" + (M.lang === code ? " on" : ""), "aria-pressed": M.lang === code ? "true" : "false"}, h("span", null, langName(code)), el("span", "ring"));
      b.addEventListener("click", () => { M.lang = code; put(tiles, tile("en"), tile("zh")); });
      return b;
    };
    const tiles = el("div", "wz-tiles", tile("en"), tile("zh"));
    name.addEventListener("input", () => { M.name = name.value; opts.changed(); });
    const prefilled = Boolean(M.st && (M.st.name || M.st.name_git));  // "both are filled in" only when a name came with the page (saved, or from Git); the language always has one
    put(box, ...head(opts, "wizard.s.you", t("wizard.y.title"), t(prefilled ? "wizard.y.sub" : "wizard.y.sub.noname")),
      el("div", "wz-field", el("span", "cap", t("wizard.y.name")), name, M.st && M.st.name_git && M.name ? el("div", "hint", t("wizard.y.hint")) : null),  // "Taken from your Git settings" only when Git gave the name
      el("div", "wz-field", el("span", "cap", t("wizard.y.lang")), tiles, el("div", "hint", t(opts.bare ? "wizard.y.lang.hint.save" : "wizard.y.lang.hint")), savedNote), said);  // the pick waits for Save (Settings) or Continue (the wizard) (1.8.32)
    const commit = () => {
      said.hidden = true;
      holding = !FAKE && M.lang !== document.documentElement.lang;  // (1.8.33) serve.js would load the page again the moment the save answers; this page does it itself, after the veil (E6)
      return api.setup("save", {part: "you", name: M.name.trim(), language: M.lang}).then(() => {
        M.saved.you = true;
        if (M.st) { M.st.name = M.name.trim(); M.st.language = M.lang; }
        if (!FAKE && M.lang !== document.documentElement.lang) {  // the texts are in the old language: the page loads again, and comes back here
          try {
            if (opts.bare) { sessionStorage.setItem("harness.reopen", "settings:you"); sessionStorage.setItem("harness.saved.you", String(Date.now())); }  // Settings: the window comes back at this section, with its "Saved"
            else sessionStorage.setItem(KEEP, JSON.stringify({page: nextFrom(M.page, 1)}));
          } catch (error) { /* starts at the welcome */ }
          const link = new URL(location.href);
          const again = () => { if (link.searchParams.has("page")) { link.searchParams.delete("page"); location.replace(link.toString()); } else location.reload(); };  // a `?page=` in the address would win over the page kept: one Continue must go on
          return MOTION.leave(again, {content: thinking()});  // (1.8.33) E6: the page fades to its own colour with a small robot thinking, so the new language comes out of it, not out of black
        }
        opts.next();
      }, (error) => { holding = false; said.textContent = errorText(error); said.hidden = false; });
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
      const ok = row.found && !row.blocked && !row.trouble;
      const slow = row.trouble === "slow";
      const note = ok && row.id === "vscode" ? t("wizard.p.code.n") : ok && row.id === "harness" ? t("wizard.p.hc.n") : "";
      const how = {path: t("wizard.p.how.path"), folder: t("wizard.p.how.folder"), standard: t("wizard.p.how.standard")}[row.how] || "";
      const label = row.id === "harness" ? t("wizard.p.hc") : row.name;
      const harnessBad = row.id === "harness" && !ok && !M.shortBusy && M.shortError;  // the short command did not go in: the reason, and a button, never the command text
      const state = ok ? el("span", "wz-state ok", dot("ok"), t("wizard.p.found")) : harnessBad ? el("span", "wz-state hot", dot("hot"), t("wizard.p.nf")) : row.id === "harness" ? el("span", "wz-state", spin(), t("wizard.p.adding"))
        : slow ? el("span", "wz-state", spin(), t("wizard.p.slow")) : el("span", "wz-state hot", dot("hot"), t(row.blocked || row.trouble ? "wizard.p.blocked" : "wizard.p.nf"));
      if (ok) state.title = how;
      const main = el("div", "wz-main", el("div", "wz-name", h("b", null, label), row.version ? h("small", null, row.version) : null),
        row.path ? where(row) : null, note ? el("div", "wz-where plain", note) : null, row.trouble === "fails" && row.why ? el("div", "wz-where plain", row.why) : null, harnessBad ? el("div", "wz-where plain", M.shortError) : null);
      const needsFix = !ok && !slow && row.id !== "harness";
      const again = harnessBad ? el("div", "wz-fix", el("div", "line", btn(t("wizard.p.again"), "sm primary", () => trySetShort()))) : null;
      return el("div", "wz-li" + (needsFix || harnessBad ? " miss" : ""), el("span", "wz-ic", programIcon[row.id] || row.id.slice(0, 2)), main, state, needsFix ? fix(row) : again);
    }
    function take(found) {
      const was = Boolean(M.progs && M.progs.all_found);
      M.progs = found;
      if (!was && found.all_found && !opts.bare && !ONLY) hopHead();  // (1.8.33) W7: the last program was found while the page was open
      const sign = JSON.stringify([found.rows.map((row) => [row.id, row.found, row.path, row.blocked, row.version, row.trouble, row.why]), M.shortBusy, M.shortError]);
      if (sign !== shown) { shown = sign; put(list, ...found.rows.map(paintRow)); }
      opts.changed();
      const harness = found.rows.find((row) => row.id === "harness");
      if (harness && !harness.found && !M.shortTried) { M.shortTried = true; trySetShort(); }
    }
    function trySetShort() {  // the `harness` short command: once by itself, and again on the button; a failure keeps its reason
      M.shortBusy = true; M.shortError = ""; if (M.progs) take(M.progs);
      api.setup("short").then(() => api.poll("programs")).then((found) => { M.shortBusy = false; take(found); }, (error) => { M.shortBusy = false; M.shortError = errorText(error) || t("wizard.p.nf"); if (M.progs) take(M.progs); });
    }
    function loop() {
      if (stopped) return;
      if (M.progs && M.progs.all_found && !(M.progs.rows || []).some((row) => !row.found && row.id === "harness")) { timer = setTimeout(loop, 3000); return; }  // everything is in: still looked at now and then
      api.poll("programs").then((found) => { if (!stopped) take(found); }, () => {}).then(() => { if (!stopped) timer = setTimeout(loop, 3000); });
    }
    put(box, ...head(opts, "wizard.s.prog", t("wizard.p.title"), t("wizard.p.sub")), list);
    if (M.progs) take(M.progs);
    timer = setTimeout(loop, 3000);
    const firstMissing = () => ((M.progs && M.progs.rows) || []).find((row) => row.required && (!row.found || row.blocked || row.trouble));
    return {stop() { stopped = true; clearTimeout(timer); }, foot() {
      const missing = firstMissing();
      return {back: !ONLY, later: null, why: missing ? t("wizard.p.need", {name: missing.name}) : "", main: {label: ONLY ? t("wizard.done") : t("wizard.cont"), off: Boolean(missing) || !M.progs, go: ONLY ? leave : opts.next}};
    }};
  };

  parts.copilot = function (box, opts) {
    const body = el("div");
    let timer = 0, stopped = false, shown = "", sawOut = false, advance = 0, starting = false, waitText = null, ticker = 0, base = null;
    const said = el("p", "wz-err"); said.hidden = true;
    function paint() {
      const line = copilotLine() || {state: "wait", why: "starting"};
      const signed = copilotSignedIn(line);
      if (!signed) sawOut = true;
      const sign = JSON.stringify([line.state, line.why, line.code, line.url, line.login, line.detail, line.last, starting]);
      base = line.why === "signing-in" ? {left: line.left || 0, at: Date.now()} : null;  // (1.8.32) the count runs down by itself between two answers
      if (waitText) waitText.textContent = t("wizard.c.wait", {t: clock(line.left || 0)});
      if (sign === shown) { opts.changed(); return; }
      shown = sign;
      if (signed) {
        put(body, el("div", "wz-signed", el("span", "wz-big-ok", "\u2713"), el("div", null, el("div", "t1", t("wizard.c.done", {u: line.login || "GitHub"})), el("div", "t2", ONLY || opts.bare ? "" : t("wizard.c.next")))));  // Settings (bare) only shows the state: no "Moving on", no step forward (1.8.32)
        if (sawOut && !ONLY && !opts.bare && !advance) hopHead();  // (1.8.33) W7: a step done: the head hops twice and the bulb lights
        if (sawOut && !ONLY && !opts.bare && q("hold", "") !== "1" && !advance) advance = setTimeout(() => { if (!stopped) opts.next(); }, HOLD);  // the card stays 1500 ms, never less than 900 (W7)
      } else if (line.why === "signing-in") {
        waitText = null;
        const copy = btn(t("wizard.c.copy"), "sm", () => copyCommand(copy, line.code));
        copy.dataset.label = t("wizard.c.copy");
        const open = btn("", "primary", () => window.open(line.url || "https://github.com/login/device", "_blank", "noopener"));
        open.append(ghIcon(), t("wizard.c.open") + " \u2197");
        const cancel = link(t("wizard.c.cancel"), () => api.gh({do: "cancel"}).then(tick, () => {}));
        put(body, el("div", "wz-codebox", el("div", "cap", t("wizard.c.cap")), el("div", "wz-code", el("span", "digits", line.code || "\u2026"), copy),
          el("div", "acts", open, cancel), el("div", "waiting", spin(), waitText = el("span", null, t("wizard.c.wait", {t: clock(line.left || 0)})))));
      } else if (line.why === "host-failed" || line.why === "error") {  // not about the sign-in: the reason, and the one thing a person can do (never the sign-in button)
        const act = line.why === "error"
          ? btn(t("wizard.c.again"), "primary", () => { act.disabled = true; said.hidden = true; tick().then(() => { act.disabled = false; }); })
          : btn(t("wizard.c.restart"), "primary", () => { act.disabled = true; said.hidden = true; api.host({do: "restart"}).then((found) => { if (found && found.state === "waiting") { said.textContent = t("wizard.c.host.waiting"); said.hidden = false; } return tick(); }, (error) => { said.textContent = errorText(error); said.hidden = false; }).then(() => { act.disabled = false; }); });
        put(body, el("p", "wz-err", t(line.why === "error" ? "wizard.c.error" : "wizard.c.hostfail", {why: line.detail || "-"})), el("div", "wz-cp", act));
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
    ticker = setInterval(() => { if (waitText && base) waitText.textContent = t("wizard.c.wait", {t: clock(Math.max(0, base.left - Math.round((Date.now() - base.at) / 1000)))}); }, 1000);
    return {stop() { stopped = true; clearTimeout(timer); clearTimeout(advance); clearInterval(ticker); }, foot: () => {
      const signed = copilotSignedIn(copilotLine());
      return {back: !ONLY, later: null, why: signed ? "" : t("wizard.c.need"), main: {label: ONLY ? t("wizard.done") : t("wizard.cont"), off: !signed, go: ONLY ? leave : opts.next}};
    }};
  };

  parts.kb = function (box, opts) {
    const sub = M.kbsub;
    const list = subs();
    const at = Math.max(0, list.indexOf(sub));
    const eyebrowText = t("wizard.s.kb");  // (1.8.32) no "n of m": the bar above has the step, and the middle page comes only when a program is missing
    const nextSub = () => { const rest = list.slice(at + 1); if (rest.length) { M.kbsub = rest[0]; opts.rerender(); } else opts.next(); };
    const prevSub = () => { if (at > 0) { M.kbsub = list[at - 1]; opts.rerender(); } else opts.back(); };
    let timer = 0, stopped = false;
    const stop = () => { stopped = true; clearTimeout(timer); };
    const later = (note) => ({note});

    if (sub === 1) return kbPrograms(box, opts, eyebrowText, nextSub, prevSub, stop);
    if (sub === 2) return kbConnections(box, opts, eyebrowText, nextSub, prevSub, stop);

    const k = M.kb, drop = {over: false};
    const zone = el("div");
    // Settings only (`opts.bare`): a folder that lacks commits made in this copy's knowledge base can take them. The probe answers `update.state == "ahead"` with `pull` (the engine's line) and `send` (what the window shows).
    const canSend = (probe) => Boolean(opts.bare && typeof TERM !== "undefined" && probe && probe.update && probe.update.state === "ahead" && probe.update.pull);
    // "Send to the folder" first asks: the folder that takes the commits, its branch, the title of each commit. "Send" runs the engine's line in the Terminal window (the line itself is never shown);
    // when it ended well the page probes the folder again and shows the new state.
    function sendWindow(u, path, mode) {
      const info = u.send || {}, titles = info.subjects || [], n = info.ahead || u.ahead || titles.length;
      const go = h("button", {type: "button", class: "act hot"}, t("settings.kb.send.go"));
      const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
      const view = SERVE.dialog([h("h2", null, t("settings.kb.send")), h("p", {class: "sub"}, t("settings.kb.send.about")),
        h("dl", {class: "su-send-facts"}, h("dt", null, t("settings.kb.send.folder")), h("dd", null, h("code", null, info.folder || "-")), h("dt", null, t("settings.kb.send.branch")), h("dd", null, h("code", null, info.branch || u.branch || "-")),
          h("dt", null, t(n === 1 ? "settings.kb.send.commits.one" : "settings.kb.send.commits", {n})), h("dd", null, h("ul", {class: "su-chg"}, titles.map((line) => h("li", null, line)), n > titles.length ? h("li", {class: "su-soft"}, t("settings.kb.send.more", {n: n - titles.length})) : null))),
        h("div", {class: "row"}, go, no)]);
      no.addEventListener("click", view.close);
      go.addEventListener("click", () => { view.close(); TERM.run(u.pull, () => recheck(path, mode)); });
      go.focus();
    }
    function recheck(path, mode) {
      api.setup("probe", {kind: mode === "package" ? "package" : "folder", path}).then((probe) => {
        if (stopped) return;
        k.send = canSend(probe) ? {path, mode, update: probe.update} : null;
        const inStep = Boolean(probe.ok && probe.update && probe.update.state === "same");
        k.sent = inStep;
        k.err = inStep ? "" : probe.why || "";
        if (inStep && (M.st && M.st.kb && M.st.kb.here)) k.step = "done";
        paint(); opts.changed();
      }, (error) => { if (stopped) return; k.err = errorText(error); paint(); opts.changed(); });
    }
    function sendBlock() {
      if (!k.send) return null;
      const u = k.send.update, titles = u.subjects || [], more = (u.ahead || titles.length) - titles.length;
      const go = h("button", {type: "button", class: "wz-btn sm", title: t("settings.kb.send.tip")}, t("settings.kb.send"));
      go.addEventListener("click", () => sendWindow(u, k.send.path, k.send.mode));
      return el("div", "wz-send", el("p", "wz-sub", k.err), el("ul", "su-chg", titles.map((line) => h("li", null, line)), more > 0 ? h("li", {class: "su-soft"}, t("settings.kb.send.more", {n: more})) : null), go);
    }
    function startJob(path, mode, replace) {
      k.err = ""; k.send = null; k.sent = false; k.step = "copy"; k.a = 0; k.b = 0; k.file = String(path).split(/[\\/]/).pop() || path;
      paint(); opts.changed();
      api.setup("probe", {kind: mode === "package" ? "package" : "folder", path}).then((probe) => {
        if (probe.full && !replace) {  // a knowledge base is in place already: replacing (or updating) it is the person's choice, said first
          k.step = "replace"; k.pending = {path, mode, why: probe.why || "", update: probe.update || null};
          paint(); opts.changed();
          return null;
        }
        if (!probe.ok && !(probe.full && replace)) { if (canSend(probe)) k.send = {path, mode, update: probe.update}; throw new Error(probe.why || "?"); }
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
        put(zone, dropBox, el("div", "wz-under", t("wizard.k.skipnote")), k.sent ? el("p", "wz-sub wz-sent", "\u2713 " + t("settings.kb.send.done")) : null, k.send ? sendBlock() : k.err ? el("p", "wz-err", k.err) : null);
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
          el("div", "wz-eyebrow", t("wizard.k.brought")), el("div", "wz-stats", stat(kb.domains || 0, t("wizard.k.dom")), stat(kb.domain_skills || 0, t("wizard.k.sk")), stat((company.packs || []).length, t("wizard.k.tp")), stat((company.connections || []).length, t("wizard.k.cn")), stat((company.recipe || {}).present ? "\u2713" : "\u2013", t("wizard.k.px")))), k.sent ? el("p", "wz-sub wz-sent", "\u2713 " + t("settings.kb.send.done")) : null);
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
      : {back: true, later: k.step === "replace" ? null : later(t("wizard.k.skipnote")), why: t(k.step === "copy" ? "wizard.k.why.copy" : k.step === "replace" ? "wizard.k.why.replace" : "wizard.k.why"), main: {label: t("wizard.cont"), off: true, go: nextSub}, backGo: prevSub})};  // a grey Continue says why (1.8.32)
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
      return {back: true, backGo: prevSub, later: rows.length ? {note: t("wizard.t.skipnote", {pack: forWho(rows[0]), program: rows[0].program})} : null, laterGo: nextSub, why: rows.length ? t("wizard.p.need", {name: rows[0].program}) : "", main: {label: t("wizard.cont"), off: rows.length > 0, go: nextSub}};  // the reason, as on the programs page; nothing to skip when nothing is missing (1.8.32)
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
    return {stop, foot: () => ({back: true, backGo: prevSub, later: packConnections().some((row) => !row.saved) ? {note: ""} : null, why: "", main: {label: t("wizard.cont"), go: nextSub}})};  // all signed in: nothing to skip (1.8.32)
  }

  // (1.8.32) The list shows whole rows only: its height is cut to the last row that fits in the height the sheet allows (a half row at the bottom looked broken; the fade says there is more)
  function snap(scroller) {
    scroller.style.maxHeight = "";
    if (!scroller.isConnected || scroller.scrollHeight <= scroller.clientHeight) return;
    const limit = scroller.clientHeight, base = scroller.getBoundingClientRect().top + scroller.clientTop;
    let fit = 0;
    for (const row of scroller.children) {
      const bottom = row.getBoundingClientRect().bottom - base;
      if (bottom > limit + 0.5) break;
      fit = bottom;
    }
    if (fit > 0) scroller.style.maxHeight = Math.ceil(fit) + (getComputedStyle(scroller).boxSizing === "border-box" ? scroller.offsetHeight - scroller.clientHeight : 0) + "px";
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
      all.textContent = t(everyOn() ? "wizard.r.none.all" : "wizard.r.all");
      const shownRows = visible();
      const was = listBox.querySelector(".wz-scroll"), at = was ? was.scrollTop : 0;  // a tick must not send the list back to the top
      if (!rows.length) { put(listBox, el("div", "wz-list", el("div", "wz-empty", t("wizard.r.none")))); count.textContent = ""; opts.changed(); return; }
      const scroller = el("div", "wz-list wz-scroll", ...(shownRows.length ? [] : [el("div", "wz-empty", t("wizard.r.nomatch"))]), ...shownRows.map((row) => {
        const fixed = Boolean(row.in_root);  // found through the repositories folder: it stays while that folder is set, so the box cannot be unticked here
        const on = fixed || M.picks.has(row.path);
        const item = el("div", "wz-li wz-repo" + (fixed ? " fixed" : ""), el("span", "wz-box" + (on ? " on" : ""), on ? "\u2713" : ""), el("div", "wz-main", el("span", "wz-name", row.name), el("div", "wz-where", h("bdi", null, row.shown || row.path)), fixed ? el("div", "wz-where plain", t("wizard.r.inroot")) : null));
        item.setAttribute("role", "checkbox"); item.setAttribute("aria-checked", on ? "true" : "false"); item.tabIndex = 0;
        if (fixed) { item.setAttribute("aria-disabled", "true"); item.tabIndex = -1; return item; }
        const flip = () => { if (on) M.picks.delete(row.path); else M.picks.add(row.path); paint(); };
        item.addEventListener("click", flip);
        item.addEventListener("keydown", (event) => { if (event.key === " " || isEnter(event)) { event.preventDefault(); flip(); } });
        return item;
      }));
      const fade = el("div", "wz-fade", scroller);  // a soft edge at the bottom says there is more to scroll to; it goes at the end of the list (1.8.32)
      const edge = () => fade.classList.toggle("end", scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 4);
      scroller.addEventListener("scroll", edge);
      put(listBox, fade);
      requestAnimationFrame(() => { snap(scroller); scroller.scrollTop = at; edge(); });
      count.textContent = t("wizard.r.found", {n: rows.length, places: scan.places.join(t("wizard.r.and"))});
      opts.changed();
    }
    filter.addEventListener("input", () => { M.filter = filter.value; paint(); });
    const choosable = () => visible().filter((row) => !row.in_root);
    const everyOn = () => { const list = choosable(); return list.length > 0 && list.every((row) => M.picks.has(row.path)); };
    const all = link(t("wizard.r.all"), () => { const on = everyOn(); choosable().forEach((row) => (on ? M.picks.delete(row.path) : M.picks.add(row.path))); paint(); });  // all ticked: it becomes "Select none" and unticks (1.8.32)
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
    const commit = () => api.setup("save", {part: "repos", paths: [...M.picks], shown: rows.map((row) => row.path)}).then(() => { M.saved.repos = true; opts.next(); }, (error) => { said.textContent = errorText(error); said.hidden = false; });
    return {stop() {}, foot: () => {
      const n = M.picks.size;
      return {back: true, later: {note: t("wizard.v.repo.e")}, why: "", main: {label: n ? t("wizard.r.cont", {n}) : t("wizard.cont"), off: !n, go: commit, minw: 160}};  // the same width with or without the number (1.8.32)
    }};
  };

  // (1.8.32) The gear of the dock's Settings button (dock.js draws the same two paths), with the yellow dot (wizard.css)
  const GEAR = ["M12 8.7a3.3 3.3 0 1 0 0 6.6 3.3 3.3 0 0 0 0-6.6z", "M12 2.4l1.5 2.55 3-0.6 0.9 3 2.85 1.2-1.05 2.85 1.95 2.4-2.4 1.95 0.15 3-3 0.45-1.5 2.7L12 20.4l-2.4 1.5-1.5-2.7-3-0.45 0.15-3L3 13.35l1.95-2.4-1.05-2.85 2.85-1.2 0.9-3 3 0.6z"];
  function gearIcon() {
    const NS = "http://www.w3.org/2000/svg", wrap = el("span", "wz-gear"), svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
    GEAR.forEach((d) => { const path = document.createElementNS(NS, "path"); path.setAttribute("d", d); svg.append(path); });
    wrap.append(svg);
    return wrap;
  }
  // (1.8.32) Every "Set up" row is "label · value", with a unit where it is a count; the server's detail is used as it is, except where it is a bare name (the sign-in) or empty
  const valueText = (row) => (row.id === "copilot" && row.detail ? t("wizard.v.cop.s", {name: row.detail}) : row.detail || t("wizard.v.ok"));
  parts.review = function (box, opts) {
    const holder = el("div");
    let summary = null, finishing = false;
    const where = {you: [1], programs: [2], copilot: [3], kb: [4, 0], packs: [4, 1], connections: [4, 2], repos: [5]};
    const said = el("p", "wz-err"); said.hidden = true;
    function paint() {
      if (!summary) { put(holder, ); return; }
      const ok = summary.rows.filter((row) => row.done), no = summary.rows.filter((row) => !row.done);
      if (title) title.textContent = t(no.length ? "wizard.v.title.check" : "wizard.v.title");
      const parts = [];
      if (ok.length) parts.push(el("div", "wz-grp", h("h4", null, t("wizard.v.done")), el("div", "wz-donegrid", ok.map((row) => el("div", "wz-d", dot("ok"), h("b", null, row.label), h("span", {class: "s", title: valueText(row)}, valueText(row)))))));
      if (no.length) parts.push(el("div", "wz-grp", h("h4", null, t("wizard.v.todo")), listOf(no.map((row) => {
        const set = btn(t("wizard.v.set"), "sm", () => { M.fromReview = true; const spot = where[row.id] || [2]; go(spot[0], spot[1] || 0); });
        return el("div", "wz-li wz-rv", dot("hot"), el("div", "wz-main", el("div", "t", row.label), el("div", "eff", row.effect || "")), set);
      }))));
      if (no.length) parts.push(el("div", "wz-later", gearIcon(), t("wizard.v.later")));
      put(holder, ...parts);
      opts.changed();
    }
    put(box, ...head(opts, "wizard.s.rev", t("wizard.v.title.check"), t("wizard.v.sub")), holder, said);
    const title = box.querySelector("h1");  // "Ready to go" only when nothing is left to set up (1.8.32)
    api.setup("summary").then((found) => { summary = found; paint(); }, (error) => { said.textContent = errorText(error); said.hidden = false; });
    const confirm = () => { finishing = true; opts.changed(); said.hidden = true; return api.setup("finish").then(() => { try { sessionStorage.removeItem(KEEP); } catch (error) { /* nothing kept */ } return toEnter(); }, (error) => { finishing = false; said.textContent = errorText(error); said.hidden = false; opts.changed(); }); };
    const lacking = () => (summary ? summary.rows.filter((row) => row.required && !row.done).map((row) => row.label) : []);  // what Confirm needs: the server refuses too (409)
    return {stop() {}, foot: () => { const need = lacking(); return {back: true, later: null, why: need.length ? t("wizard.v.need", {what: need.join(", ")}) : "", main: {label: t("wizard.v.go"), off: !summary || finishing || need.length > 0, go: confirm}}; }};
  };

  // ------------------------------------------------------------------------------------------------ the shell: top line, bar, page, foot, robot (1.8.33)
  // Built once, when the page opens (W1): a turn changes only the page (W4), the bar (W5), the robot (W3, W6) and the foot's place. All of it goes through motion.js and robot.js:
  // transform and opacity, nothing in Lite or under reduced motion, and no move blocks a button. In Settings (`opts.bare`) none of this exists: there is no shell there.
  const BOT = {fw: 91, fh: 96, hw: 30, hh: 31, k: 1.76, hx: 45.3, hy: 33.5};  // the whole robot, the small head, how much bigger the head of the whole robot is, the middle of that head
  const HOLD = 1500;  // W7: the "Signed in" card stays this long before the page goes on (never less than 900 ms)
  const at = (x, y, s) => "translate(" + x.toFixed(1) + "px," + y.toFixed(1) + "px)" + (s && s !== 1 ? " scale(" + s.toFixed(3) + ")" : "");
  let turning = false, busy = false, drawn = null, run = 0;  // a page turn is playing; a press is being answered; what is on screen {page, sub}; counts the renders

  function buildShell(root) {
    const alone = Boolean(ONLY);
    const count = el("div", "wz-count");
    const bars = alone ? [] : SEGMENTS.map(() => h("i", null, h("b", {class: "f"}), h("b", {class: "s"})));
    const names = alone ? [] : SEGMENTS.map((key) => h("span", null, el("span", "wz-mk", el("span", "wz-tk", h("i", null), h("i", null)), dot("hot wz-skip")), el("span", "wz-nm", t(key))));
    const content = el("div", "wz-pg"), footRow = el("div", "wz-row"), foot = el("div", "wz-foot", footRow);
    const job = el("div", "wz-job"); job.hidden = true;
    const full = alone ? null : el("div", "wz-mate full", ROBOT.svg({glow: true})), head = alone ? null : el("div", "wz-mate head", ROBOT.svg({head: true}));
    if (full) { full.hidden = true; head.hidden = true; }
    const body = el("div", "wz-body", el("div", "wz-page", content, foot));
    root.className = "wz";
    put(root, el("div", "wz-top", el("div", "wz-brand", "HARNESS"), count), alone ? null : el("div", "wz-prog", el("div", "wz-bars", bars), el("div", "wz-names", names)), body, job, full, head);
    shell = {root, count, bars, names, state: SEGMENTS.map(() => null), body, content, foot, footRow, job, full, head, mainBtn: null, mainGo: null, moving: false};
    if (!alone) { window.addEventListener("resize", settle); body.addEventListener("scroll", settle); }
  }

  // The bar. A part is done when it is behind the page and the computer says it is fine ("You" cannot be skipped, so behind us it is done); behind and not fine: skipped with Later, a yellow dot,
  // never a tick. Ahead of the page nothing shows: the head ticks a part as it passes it (W6).
  const barState = (i, idx) => (i === idx ? "cur" : i < idx ? (fine(i + 1) || i === 0 ? "done" : "skip") : null);
  const wanted = () => SEGMENTS.map((key, i) => barState(i, M.page - 1));
  function paintBar(states) {
    if (!shell || !shell.bars.length) return;
    states.forEach((state, i) => {
      if (shell.state[i] === state) return;
      shell.state[i] = state;
      for (const node of [shell.bars[i], shell.names[i]]) { node.classList.remove("cur", "done", "skip"); if (state) node.classList.add(state); }
    });
  }

  // The robot: the whole one stands in the slot of the welcome page; from the first step on a small head stands above the current part of the bar.
  const headAt = (i) => { const r = shell.bars[i].getBoundingClientRect(); return {x: r.left + r.width / 2 - BOT.hw / 2, y: r.top - BOT.hh - 5}; };
  const fullAt = () => { const slot = shell.content.querySelector(".wz-slot"); if (!slot) return null; const r = slot.getBoundingClientRect(); return {x: r.left + r.width / 2 - BOT.fw / 2, y: r.top}; };
  const placeAt = (node, spot) => { node.style.transform = at(spot.x, spot.y); };
  function settle() {  // the robot where this page wants it, with no move (also after a resize or a scroll)
    if (!shell || !shell.full || shell.moving) return;
    const hello = M.page === 0, spot = hello ? fullAt() : headAt(M.page - 1);
    shell.full.hidden = !(hello && spot);
    shell.head.hidden = hello || !spot;
    if (spot) placeAt(hello ? shell.full : shell.head, spot);
  }
  const rest = () => { for (const mate of [shell.full, shell.head]) for (const move of mate.getAnimations()) move.cancel(); };
  const headSvg = () => (shell && shell.head && !shell.head.hidden ? shell.head.querySelector("svg") : null);
  const hopHead = () => { const svg = headSvg(); if (svg && !turning) ROBOT.act(svg, "hop"); };

  // W3: the whole robot shrinks into the small head and flies to the bar (500 ms); `back` is the way home. Both are on screen at the middle of the flight, one fading as the other comes.
  function fly(a, b, back) {
    const small = 1 / BOT.k;
    const centre = (spot, whole) => (whole ? {x: spot.x + BOT.hx, y: spot.y + BOT.hy} : {x: spot.x + BOT.hw / 2, y: spot.y + BOT.hh / 2});  // the middle of the head, wherever the robot is
    const asHead = (c, s) => at(c.x - BOT.hw * s / 2, c.y - BOT.hh * s / 2, s);  // the small head, `s` times as big, with its middle at c
    const asFull = (c, s) => at(c.x - BOT.hx * s, c.y - BOT.hy * s, s);
    const whole = back ? b : a, little = back ? a : b;
    const wc = centre(whole, true), lc = centre(little, false);
    shell.full.hidden = false; shell.head.hidden = false;
    placeAt(shell.full, whole); placeAt(shell.head, little);
    const opts = {ms: 500, fill: "forwards"};
    const ofFull = back ? [{transform: asFull(lc, small), opacity: 0}, {opacity: 0, offset: .3}, {opacity: 1, offset: .7}, {transform: at(whole.x, whole.y), opacity: 1}]
      : [{transform: at(whole.x, whole.y), opacity: 1}, {opacity: 0, offset: .55}, {transform: asFull(lc, small), opacity: 0}];
    const ofHead = back ? [{transform: at(little.x, little.y), opacity: 1}, {opacity: 0, offset: .55}, {transform: asHead(wc, BOT.k), opacity: 0}]
      : [{transform: asHead(wc, BOT.k), opacity: 0}, {opacity: 0, offset: .25}, {opacity: 1, offset: .7}, {transform: at(little.x, little.y), opacity: 1}];
    return Promise.all([MOTION.play(shell.full, ofFull, opts), MOTION.play(shell.head, ofHead, opts)]);
  }

  // W3 / W6: the head walks along the bar. One step is the page turn's own length; several steps (the pages already fine are skipped) go cell by cell, 120 ms each, with a small hop, and
  // `arrived(i)` says each cell it reaches so the bar can tick it as the head passes.
  async function walk(a, b, mine, arrived) {
    const step = b > a ? 1 : -1, many = Math.abs(b - a) > 1;
    shell.head.hidden = false;
    let prev = headAt(a);
    for (let i = a + step; mine === run; i += step) {
      const next = headAt(i), top = Math.min(prev.y, next.y) - 6;
      await MOTION.play(shell.head, many ? [{transform: at(prev.x, prev.y)}, {transform: at((prev.x + next.x) / 2, top), offset: .5}, {transform: at(next.x, next.y)}] : [{transform: at(prev.x, prev.y)}, {transform: at(next.x, next.y)}], {ms: many ? MOTION.MS.micro : 100, fill: "forwards"});
      if (mine !== run) return;
      if (arrived) arrived(i);
      if (i === b) return;
      prev = next;
    }
  }

  // A page turn is in two steps that never overlap (W4): the old page is gone in 100 ms (and the head has landed, W6); only then the new page, the foot, the count and the bar change, all at once,
  // and the new page comes in over 180 ms. So no frame, however late it is drawn, shows two pages or the foot of one under the other.
  function render() {
    if (ctl && ctl.stop) ctl.stop();
    ctl = null;
    const root = shell.root, first = !drawn, mine = ++run;
    const dir = first ? 0 : M.page !== drawn.page ? (M.page > drawn.page ? 1 : -1) : M.kbsub !== drawn.sub ? (M.kbsub > drawn.sub ? 1 : -1) : 0;  // forward, back, or the same page again
    const from = first ? M.page : drawn.page, name = PAGES[M.page];
    const old = shell.content;
    const change = () => {  // the new page, the foot, the count: one moment
      const content = el("div", "wz-pg");
      shell.body.scrollTop = 0;  // before the swap: the layout is still clean, and nothing is forced after it
      old.replaceWith(content);
      shell.content = content;
      root.classList.toggle("wz-hello", name === "welcome");
      shell.count.textContent = M.page && !ONLY ? t("wizard.step", {n: M.page, m: 6}) : "";
      ctl = parts[name](content, {changed: drawFoot, rerender: render, next: forward, back: backward, jump: (page) => go(page)});
      drawn = {page: M.page, sub: M.kbsub};
      drawFoot();
      paintJob();
    };
    if (!dir) {  // the first page, or the same page drawn again (a state that changed): no turn
      change();
      if (first) {
        void root.offsetWidth;  // the bar was there before: its fill is a move from empty
        paintBar(wanted());
        settle();
        MOTION.appear(shell.content, {ms: MOTION.MS.show});
        MOTION.appear(shell.foot, {ms: MOTION.MS.show});
        for (const mate of [shell.full, shell.head]) if (mate && !mate.hidden) MOTION.play(mate, [{opacity: 0}, {opacity: 1}], {ms: MOTION.MS.show});
        if (M.page === 0) welcomeLife(shell.content);
      }
      if (ctl.focus) ctl.focus();
      return;
    }
    turning = true;
    const slide = dir * 24, final = wanted(), hello = from === 0, home = M.page === 0, there = M.page - 1;
    const moves = Boolean(shell.full) && M.page !== from;
    const wasFull = moves && hello ? fullAt() : null, wasHead = moves && !hello ? headAt(from - 1) : null;  // where the robot stands now
    const many = moves && !hello && !home && Math.abs(there - (from - 1)) > 1;  // pages skipped: the page stays while the head hops, then it turns
    const leaves = () => MOTION.play(old, [{opacity: 1, transform: "none"}, {opacity: 0, transform: "translateX(" + (-slide) + "px)"}], {ms: 100, ease: MOTION.OUT, fill: "forwards"});
    const out = many ? null : leaves();
    let flight = Promise.resolve();
    if (moves) {
      shell.moving = true;
      rest();
      if (hello) flight = fly(wasFull, headAt(there), false);  // W3: the whole robot becomes the head while the page turns (it does not hold the page)
      else if (!home) flight = walk(from - 1, there, mine, (i) => { if (i !== there) { const part = shell.state.slice(); part[i] = final[i]; paintBar(part); } });  // W6: each cell ticked as the head passes
    }
    const land = () => { if (moves && mine === run) { rest(); shell.moving = false; settle(); } };
    (many ? flight.then(leaves) : hello || home ? out : Promise.all([out, flight])).then(() => {  // the old page is gone, and the head has landed (W6)
      if (mine !== run) return;
      const fit = MOTION.glide(shell.foot, change);  // the foot goes where the new page's height puts it
      paintBar(final);
      if (moves && home) flight = fly(wasHead, fullAt(), true);  // measured before the new page starts to move in
      const came = MOTION.play(shell.content, [{opacity: 0, transform: "translateX(" + slide + "px)"}, {opacity: 1, transform: "none"}], {ms: 180});
      Promise.all([came, fit]).then(() => { if (mine === run) { turning = false; if (ctl && ctl.focus && !root.contains(document.activeElement)) ctl.focus(); } });
      flight.then(land);
    });
    setTimeout(() => { if (mine === run) turning = false; }, 1500);  // a safety: a turn that never reports does not hold the buttons
  }

  // W2: the welcome page's one blink and its list coming in row by row, 30 ms apart
  function welcomeLife(content) {
    const eyes = shell.full && shell.full.querySelector(".r-eyes");
    if (eyes) { eyes.style.transformBox = "fill-box"; eyes.style.transformOrigin = "center"; MOTION.play(eyes, [{transform: "none"}, {transform: "scaleY(.1)", offset: .5}, {transform: "none"}], {ms: 240, delay: 500}); }
    const cells = Array.from(content.querySelectorAll(".wz-it")), tops = [...new Set(cells.map((cell) => cell.offsetTop))];
    cells.forEach((cell) => MOTION.play(cell, [{opacity: 0}, {opacity: 1}], {ms: 140, delay: Math.min(120, tops.indexOf(cell.offsetTop) * 30)}));
  }

  // E6 (the language was saved and the page loads again): a small robot and three dots in the middle of the veil
  function thinking() {
    const mark = ROBOT.svg({head: true});
    return el("div", "m-think", mark, el("div", "m-dots", h("i", null), h("i", null), h("i", null)));
  }

  // W9 and the wizard's half of W10: the veil (the Enter screen's backdrop) starts with the page's fade, so no frame shows only the header. The head is lifted onto the veil, jumps, and goes to
  // HAND: the top centre of the viewport, where the Enter screen's robot starts. The page goes on when the head has landed; if the next page is slow, three dots appear under the head.
  const HAND = {w: 30, h: 31, top: 20, dots: 10};  // the head is 30 x 31 px, centred, its top edge 20 px from the top of the viewport; the dots sit 10 px under it
  function toEnter() {
    if (!shell) return Promise.resolve(leave());
    const mate = shell.head, svg = headSvg();
    MOTION.mark("from-wizard");
    let landed = Promise.resolve();
    if (mate && svg) {
      const box = mate.getBoundingClientRect(), x = Math.round(window.innerWidth / 2 - HAND.w / 2), y = HAND.top;
      document.body.append(mate);
      mate.classList.add("lifted");  // above the veil (wizard.css)
      mate.style.transform = at(x, y);
      landed = MOTION.play(mate, [{transform: at(box.left, box.top)}, {transform: at(x, y)}], {ms: 300, fill: "forwards"});  // nothing under reduced motion or Lite: it stands there
      ROBOT.act(svg, "cheer");
    }
    setTimeout(() => {
      const dots = el("div", "m-dots wz-wait", h("i", null), h("i", null), h("i", null));
      dots.style.top = HAND.top + HAND.h + HAND.dots + "px";
      document.body.append(dots);
      MOTION.appear(dots, {ms: MOTION.MS.show});
    }, 400);
    for (const node of [shell.content, shell.foot]) MOTION.play(node, [{opacity: 1}, {opacity: 0}], {ms: 120, ease: MOTION.OUT, fill: "forwards"});
    return MOTION.leave(() => landed.then(() => location.assign("/")), {cls: "enter-bg"});
  }

  // The foot. Its main button stays the same node from page to page, so a change between off and on is a fade (W8), and a press (Continue, Back, Skip) is answered once: a burst of clicks
  // moves one page, and nothing is pressed while a turn plays or a save is being answered.
  const pressed = MOTION.guard((go) => {
    const out = go();
    if (out && typeof out.then === "function") { busy = true; const done = () => { busy = false; }; out.then(done, done); setTimeout(done, 15000); }
    return out;
  }, 300);
  const press = (go) => { if (!turning && !busy) pressed(go); };
  function drawFoot() {
    if (!ctl || !shell) return;
    const foot = ctl.foot();
    const back = foot.back ? btn("← " + t("wizard.back"), "", () => press(foot.backGo || backward)) : null;
    const later = foot.later ? link(t("wizard.skip"), () => press(foot.laterGo || (() => (M.fromReview ? forward() : go(nextFrom(M.page, 1))))), foot.later.note) : null;  // `laterGo`: a small page of the knowledge base goes on to the next small page, not past all of them
    let main = shell.mainBtn;
    if (!main) { main = btn("", "primary"); main.addEventListener("click", () => { if (shell.mainGo) press(shell.mainGo); }); shell.mainBtn = main; }
    shell.mainGo = foot.main.off ? null : foot.main.go;
    main.textContent = foot.main.label + " →";
    main.className = "wz-btn primary" + (foot.main.off ? " off" : "");
    main.style.minWidth = foot.main.wide ? "200px" : foot.main.minw ? foot.main.minw + "px" : "";
    if (foot.main.off) main.setAttribute("aria-disabled", "true"); else main.removeAttribute("aria-disabled");
    const row = shell.footRow, wide = Boolean(foot.main.wide);
    const before = (wide ? [el("span", "wz-grow")] : [back, el("span", "wz-grow"), foot.why ? el("span", "wz-why", foot.why) : null, later]).filter(Boolean);
    const after = wide ? [el("span", "wz-grow")] : [];
    for (const child of Array.from(row.children)) if (child !== main) child.remove();
    for (const node of before) { if (main.parentNode === row) row.insertBefore(node, main); else row.append(node); }
    if (main.parentNode !== row) row.append(main);
    for (const node of after) row.append(node);
  }

  // ------------------------------------------------------------------------------------------------ start
  // What the pages know, read from the back end: the state, the programs, the readiness and the repositories found. Settings asks for it each time it opens a section (`opts.fresh` keeps what was read).
  const isUnpaired = (error) => Boolean(error && error.data && error.data.unpaired);
  function load() {
    M.unpaired = false;
    const first = (promise) => promise.catch((error) => { if (isUnpaired(error)) M.unpaired = true; return null; });  // an unknown is never drawn as "not found": an unpaired browser gets only the pairing line
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

  // This browser is not paired: no data was read, so the page says only that (the bar of serve.js is hidden on this page, it would cover the progress bar), and goes on by itself once the browser is paired.
  function unpairedPage(root) {
    shell = null;
    root.className = "wz";
    put(root, el("div", "wz-top", el("div", "wz-brand", "HARNESS"), el("div", "wz-count", "")),
      el("div", "wz-body", el("div", "wz-page", h("h1", null, t("wizard.unpaired.title")), el("p", "wz-sub", t("wizard.unpaired.sub")), el("p", "wz-unpaired", t("board.serve.notpaired"), " ", SERVE.pairControl()))));
    const look = () => SERVE.call("/api/status", {}, 6).then((data) => { if (data && data.paired) location.reload(); }, () => null);
    setInterval(look, 4000);
  }

  function start() {
    const root = document.getElementById("app");
    document.body.classList.add("wz-doc");  // the page has no gear and no help beside it (wizard.css)
    const theme = q("theme", "");
    if (FAKE && (theme === "light" || theme === "dark")) document.documentElement.setAttribute("data-theme", theme);
    api = FAKE ? fakeApi() : realApi();
    buildShell(root);  // (1.8.33) W1: the top line, the bar and the robot's place are there at once; the page fades in when what it shows has been read
    load().then(() => {
      if (M.unpaired) { unpairedPage(root); return null; }
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
    M.picks = null; M.extras = null; M.kbsub = 0; M.fromReview = false; M.kb.send = null; M.kb.sent = false;
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
