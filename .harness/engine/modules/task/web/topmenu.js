// (1.8.39) The account menu at the top right of a served page: the avatar in the pill of stop.js (the initials of the name, a ring of the Copilot credits left, a dot for skipped
// setup items) opens a menu with who is signed in, the credits, Settings, the theme, Appearance, the setup guide, the version, Restart board and Stop board.
// It took the place of the Settings gear, the Appearance sliders and the stop button; the house is the logo at the top left (board.js).
// Needs common.js (h, t), acct.js (ACCT); uses, when the page has them: SETTINGS, SHELL, harnessTheme, READY, STOP. Every key in the menu works: arrows, Home, End, Esc, Tab.
"use strict";

const TOPMENU = (function () {
  const SEEN = "harness.menu.seen";  // the one-time hint was shown and closed (this browser)
  const EVERY = 5 * 60 * 1000;  // the credits are read again (the board asks gh at most this often anyway)
  const NS = "http://www.w3.org/2000/svg";
  const PATHS = {
    gear: ["M12 8.7a3.3 3.3 0 1 0 0 6.6 3.3 3.3 0 0 0 0-6.6z", "M12 2.4l1.5 2.55 3-0.6 0.9 3 2.85 1.2-1.05 2.85 1.95 2.4-2.4 1.95 0.15 3-3 0.45-1.5 2.7L12 20.4l-2.4 1.5-1.5-2.7-3-0.45 0.15-3L3 13.35l1.95-2.4-1.05-2.85 2.85-1.2 0.9-3 3 0.6z"],
    theme: ["M12 4a8 8 0 1 0 0 16z", "M12 4a8 8 0 0 1 0 16"],
    sliders: ["M4 7h9M17 7h3M13 5h4v4h-4zM4 17h3M11 17h9M7 15h4v4H7z"],
    guide: ["M4.5 12a7.5 7.5 0 1 0 2.2-5.3", "M4.5 4.5v3.2h3.2"],
    restart: ["M19.5 12a7.5 7.5 0 1 1-2.2-5.3", "M19.5 4.5v3.2h-3.2"],
    power: ["M12 4v7", "M7.2 7.4a7 7 0 1 0 9.6 0"],
    person: ["M12 12.2a3.6 3.6 0 1 0 0-7.2 3.6 3.6 0 0 0 0 7.2z", "M5.5 19.5c.9-3.3 3.4-5 6.5-5s5.6 1.7 6.5 5"],
  };
  function icon(name) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    for (const d of PATHS[name]) { const part = document.createElementNS(NS, "path"); part.setAttribute("d", d); svg.append(part); }
    return svg;
  }

  // "Ada Lovelace" -> "AL", "ada" -> "AD", a name of two Chinese characters stays whole; nothing -> "" (the page draws a person instead).
  function initials(name) {
    const words = String(name || "").trim().split(/\s+/).filter(Boolean);
    if (!words.length) return "";
    const first = Array.from(words[0]), last = Array.from(words[words.length - 1]);
    return (words.length > 1 ? first[0] + last[0] : first.slice(0, 2).join("")).toUpperCase();
  }

  // The avatar button for stop.js's pill. `name`: the person's name (`DATA.serve.user`).
  function avatar(name) {
    const letters = initials(name);
    return h("button", {type: "button", class: "hd-av", "aria-haspopup": "menu", "aria-expanded": "false", "aria-label": t("menu.open")},
      h("span", {class: "hd-ring", "aria-hidden": "true"}), letters ? h("span", {class: "hd-in"}, letters) : h("span", {class: "hd-in none"}, icon("person")), h("i", {class: "hd-dot", hidden: ""}));
  }

  let button = null, menu = null, coach = null, name = "", paired = false, found = {state: "none"}, notes = [], copilot = null, readTimer = 0, askStop = null;

  function paint() {  // the ring, the dot and the words of the avatar, from what is known now
    if (!button) return;
    const credits = found.state === "ok" && found.account ? found.account.credits : null;
    const share = ACCT.leftShare(credits);
    button.classList.toggle("ring", share !== null);
    button.classList.toggle("low", ACCT.level(credits) === "low");
    button.classList.toggle("out", ACCT.level(credits) === "out");
    button.style.setProperty("--left", share === null ? "0" : String(Math.round(share * 1000) / 10));
    button.querySelector(".hd-dot").hidden = !notes.length;
    const said = [name || t("menu.you"), credits ? t("menu.copilot") + ": " + ACCT.short(found.account) : "", notes.length ? t("menu.notes", {n: notes.length}) : ""].filter(Boolean).join(" · ");
    button.title = said;
    button.setAttribute("aria-label", t("menu.open") + ": " + said);
  }

  function read(fresh) {
    clearTimeout(readTimer);
    if (!paired || document.documentElement.classList.contains("embed")) return Promise.resolve();
    return ACCT.get(fresh).then((answer) => {
      found = answer || {state: "none"};
      paint();
      if (menu && !menu.hidden) fill();
      readTimer = setTimeout(() => read(false), found.state === "reading" || found.reading ? 3000 : EVERY);
    });
  }

  function readCopilot() {  // who is signed in to gh, from the Enter screen's checks (`/api/ready`, a cached read); a page in a frame of the board asks nothing
    if (typeof SERVE === "undefined" || document.documentElement.classList.contains("embed")) return;
    SERVE.call("/api/ready", {}, 8).then((data) => {
      copilot = ((data && data.checks) || []).find((check) => check.id === "copilot") || null;
      if (typeof READY !== "undefined" && Array.isArray(data.notes) && typeof READYBAR === "undefined") READY.notes(data.notes);  // a page with no block of the board (the task page) asks for itself
      if (menu && !menu.hidden) fill();
    }, () => {});
  }

  // One line of the menu: a button with an icon, words, and something at the right end.
  function item(label, iconName, run, extra) {
    const node = h("button", {type: "button", class: "hm-i", role: "menuitem", tabindex: "-1"}, iconName ? icon(iconName) : h("span", {class: "hm-noi"}), h("span", {class: "hm-t"}, label), extra || null);
    node.addEventListener("click", () => { close(false); run(node); });
    return node;
  }

  function fill() {
    const credits = found.state === "ok" && found.account ? found.account.credits : null;
    // (the check of /api/ready) ok: signed in and ready; signed in but the host is starting: starting; signed in and it failed: not ready; no login: not signed in
    const how = !copilot || !copilot.login ? "off" : copilot.state === "ok" ? "on" : copilot.state === "fail" ? "bad" : "wait";
    const who = h("div", {class: "hm-who"}, h("span", {class: "hm-big"}, initials(name) || icon("person")),
      h("div", {class: "hm-wt"}, h("b", null, name ? t("board.enter.hi") + name : t("menu.you")),
        copilot && copilot.login ? h("small", null, t("menu.github", {login: copilot.login})) : null,
        h("small", null, h("i", {class: "hm-cd " + how}), t("menu.copilot." + how))));
    const parts = [who];
    if (credits) {
      const box = h("button", {type: "button", class: "hm-cr" + (ACCT.level(credits) ? " " + ACCT.level(credits) : ""), role: "menuitem", tabindex: "-1"},
        h("span", {class: "hm-cap"}, h("b", null, t("acct.title")), h("span", {"aria-hidden": "true"}, "\u203a")),  // the reset day is in the line below
        ACCT.bar(credits), h("span", {class: "hm-n"}, ACCT.line(found.account)));
      box.addEventListener("click", () => { close(false); if (typeof SETTINGS !== "undefined") SETTINGS.open("copilot"); });
      parts.push(box);
    }
    parts.push(h("div", {class: "hm-hr", role: "separator"}));
    if (typeof SETTINGS !== "undefined") {
      parts.push(item(t("dock.setup"), "gear", () => SETTINGS.open(), notes.length ? h("i", {class: "hm-dot", title: t("board.enter.notes.title")}) : null));
      if (notes.length) parts.push(h("div", {class: "hm-notes"}, notes.map((note) => h("div", {class: "hm-note", title: note.effect || null}, h("i"), h("span", null, note.text)))));  // the names only: what each costs is on hover and in Settings
    }
    if (typeof harnessTheme !== "undefined") {
      const now = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
      const seg = h("span", {class: "hm-seg", role: "group", "aria-label": t("board.shell.theme")});
      for (const [value, label] of [["light", t("board.shell.light")], ["dark", t("board.shell.dark")]]) {
        const one = h("button", {type: "button", role: "menuitemradio", tabindex: "-1", "aria-checked": String(now === value), class: now === value ? "on" : ""}, label);
        one.addEventListener("click", (event) => { event.stopPropagation(); harnessTheme.set(value); fill(); focusAt(one.textContent); });
        seg.append(one);
      }
      parts.push(h("div", {class: "hm-i hm-row"}, icon("theme"), h("span", {class: "hm-t"}, t("board.shell.theme")), seg));
    }
    if (typeof SHELL !== "undefined" && SHELL.openSettings) parts.push(item(t("menu.look"), "sliders", () => SHELL.openSettings(button)));
    parts.push(item(t("settings.walk"), "guide", () => location.assign("/setup")));
    const version = typeof DATA !== "undefined" && DATA.serve && DATA.serve.version ? String(DATA.serve.version) : "";
    if (version) parts.push(h("div", {class: "hm-hr", role: "separator"}), h("div", {class: "hm-ver"}, t("menu.version", {v: version})));
    if (paired) {
      const acts = [];
      if (typeof SETTINGS !== "undefined" && SETTINGS.restart && typeof SHELL !== "undefined") acts.push(item(t("menu.restart"), "restart", () => SETTINGS.restart()));  // it asks first, as Stop does: both end in an ellipsis
      if (askStop) acts.push(item(t("menu.stop"), "power", () => askStop(button)));
      if (acts.length) parts.push(h("div", {class: "hm-hr", role: "separator"}), ...acts);
    }
    menu.replaceChildren(...parts);
  }

  const items = () => (menu ? [...menu.querySelectorAll('[role="menuitem"],[role="menuitemradio"]')] : []);
  function focusAt(text) { const found_ = items().find((node) => node.textContent === text); if (found_) found_.focus(); }
  function move(by) {
    const list = items();
    if (!list.length) return;
    const at = list.indexOf(document.activeElement);
    list[by === "first" ? 0 : by === "last" ? list.length - 1 : (at + by + list.length) % list.length].focus();
  }

  function open() {
    dropCoach(true);
    if (!menu) {
      menu = h("div", {class: "hd-menu", role: "menu", "aria-label": t("menu.title"), hidden: ""});
      menu.addEventListener("keydown", (event) => {
        if (event.key === "ArrowDown") { event.preventDefault(); move(1); }
        else if (event.key === "ArrowUp") { event.preventDefault(); move(-1); }
        else if (event.key === "Home") { event.preventDefault(); move("first"); }
        else if (event.key === "End") { event.preventDefault(); move("last"); }
        else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(true); }
        else if (event.key === "Tab") close(false);
      });
      document.body.append(menu);
    }
    fill();
    menu.hidden = false;
    button.setAttribute("aria-expanded", "true");
    readCopilot();
    read(false);
    const first = items()[0];
    if (first) first.focus({preventScroll: true});
  }
  function close(focusBack) {
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    button.setAttribute("aria-expanded", "false");
    if (focusBack) button.focus({preventScroll: true});
  }

  // The one-time hint under the avatar, for those who knew the buttons at the bottom right. Not on the Enter screen; gone once read or once the menu was opened.
  function seen() { try { return localStorage.getItem(SEEN) === "1"; } catch (error) { return true; } }
  function dropCoach(keep) {
    if (keep) { try { localStorage.setItem(SEEN, "1"); } catch (error) { /* this browser keeps nothing: the hint may come again */ } }
    if (coach) { coach.remove(); coach = null; }
  }
  function maybeCoach() {
    if (coach || seen() || !button || !button.isConnected) return;
    const root = document.documentElement;
    if (root.classList.contains("en-open") || root.classList.contains("embed") || root.classList.contains("wb-lock")) return;
    const ok = h("button", {type: "button", class: "hm-ok"}, t("menu.coach.ok"));
    ok.addEventListener("click", () => dropCoach(true));
    coach = h("div", {class: "hm-coach", role: "status"}, h("b", null, t("menu.coach.title")), h("span", null, t("menu.coach.text")), ok);
    document.body.append(coach);
  }

  // stop.js calls it with the avatar it put in the pill. `stop`: how to ask to stop the board (its confirm card), anchored on the avatar.
  function mount(node, given) {
    button = node;
    name = (given && given.name) || "";
    askStop = (given && given.stop) || null;
    button.addEventListener("click", () => (menu && !menu.hidden ? close(true) : open()));
    button.addEventListener("keydown", (event) => { if (event.key === "ArrowDown") { event.preventDefault(); open(); } });
    document.addEventListener("mousedown", (event) => { if (menu && !menu.hidden && !menu.contains(event.target) && !button.contains(event.target)) close(false); });
    if (typeof READY !== "undefined") READY.onNotes((list) => { notes = Array.isArray(list) ? list : []; paint(); if (menu && !menu.hidden) fill(); });
    paint();
    setInterval(maybeCoach, 2000);  // the Enter screen goes away without a reload: the hint waits for the board
    setTimeout(maybeCoach, 800);
    if (typeof READYBAR === "undefined") { setTimeout(readCopilot, 1500); setInterval(() => { if (!document.hidden) readCopilot(); }, 8000); }  // the task page fills READY itself; the board's block does it there
  }

  // stop.js says whether this browser is paired (the credits, Restart and Stop are for a paired browser only).
  function setPaired(value) {
    paired = Boolean(value);
    if (paired) read(false); else { found = {state: "none"}; paint(); }
  }

  return {avatar, mount, setPaired, initials};
})();
