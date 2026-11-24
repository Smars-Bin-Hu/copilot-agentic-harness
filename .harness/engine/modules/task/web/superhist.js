// The history of the super agent chat (1.8.1): a panel over the messages of the super view with the earlier days (`/api/super/history`), each one read back as it was,
// and archived (hidden from the list, restored from "Archived"), or deleted for good after a second click (`/api/super/history/act`, the paired browser only). Today is not in it:
// the view itself shows today. Needs common.js (h, t, when), serve.js (SERVE.call) and pet.js (PET.face); super.js calls `SUPERHIST.create`.
"use strict";

const SUPERHIST = (function () {
  // `wrap`: the box of the messages, which the panel covers; `linked(text)`: the words as the chat draws them (super.js `rich`: bold, code, links, task names as links; 1.8.43, was task names only). Returns {button, close}.
  function create(wrap, linked) {
    const button = h("button", {type: "button", class: "sa-pop sa-histbtn", title: t("super.hist.open"), "aria-label": t("super.hist.open")}, "◷");
    const title = h("b", {class: "sa-hist-title"});
    const back = h("button", {type: "button", class: "sa-hist-back", hidden: ""}, "← " + t("super.hist.title"));
    const toggle = h("button", {type: "button", class: "sa-hist-link", hidden: ""});
    const shut = h("button", {type: "button", class: "sa-hist-x", title: t("super.hist.close"), "aria-label": t("super.hist.close")}, "✕");
    const note = h("div", {class: "sa-hist-note", role: "status", hidden: ""});
    const body = h("div", {class: "sa-hist-body"});
    const panel = h("div", {class: "sa-hist", hidden: "", role: "region", "aria-label": t("super.hist.title")}, h("div", {class: "sa-hist-top"}, back, title, h("span", {class: "sa-sp"}), toggle, shut), note, body);
    wrap.append(panel);
    let archivedView = false, days = [], token = 0;

    const dayName = (day) => {
      const date = new Date(day + "T12:00:00"), lang = document.documentElement.lang || undefined;
      const options = {weekday: "short", month: "short", day: "numeric"};
      if (date.getFullYear() !== new Date().getFullYear()) options.year = "numeric";
      return isNaN(date) ? day : date.toLocaleDateString(lang, options);
    };
    function say(text) { note.hidden = !text; note.textContent = text || ""; }
    function failure(error) { return (error && error.data && error.data.error) || (error && error.message) || ""; }

    async function list() {
      const mine = ++token;
      back.hidden = true;
      title.textContent = archivedView ? t("super.hist.archived.title") : t("super.hist.title");
      body.replaceChildren(h("div", {class: "sa-hist-empty"}, "…"));
      let answer;
      try { answer = await SERVE.call("/api/super/history", {}, 8); } catch (error) { if (mine === token) { body.replaceChildren(); say(t("super.hist.failed", {why: failure(error)})); } return; }
      if (mine !== token) return;
      days = answer.days || [];
      const hidden = days.filter((one) => one.archived).length, shown = days.filter((one) => one.archived === archivedView);
      toggle.hidden = !archivedView && !hidden;
      toggle.textContent = archivedView ? t("super.hist.unarchived") : t("super.hist.archived", {n: hidden});
      if (!shown.length) { body.replaceChildren(h("div", {class: "sa-hist-empty"}, archivedView ? t("super.hist.none.archived") : t("super.hist.none"))); return; }
      body.replaceChildren(...shown.map(rowOf));
    }
    function rowOf(one) {
      const open = h("button", {type: "button", class: "sa-hday"}, h("b", null, dayName(one.day)),
        h("span", null, t(one.turns === 1 ? "super.hist.turns.one" : "super.hist.turns", {n: one.turns})), h("span", null, t("super.hist.spent", {n: amount(one.spent || 0)})));
      open.addEventListener("click", () => read(one.day));
      const keep = h("button", {type: "button", class: "sa-hist-act"}, one.archived ? t("super.hist.restore") : t("super.hist.archive"));
      keep.addEventListener("click", () => act(one.day, one.archived ? "restore" : "archive"));
      const drop = h("button", {type: "button", class: "sa-hist-act bad"}, t("super.hist.delete"));
      let armed = 0;
      drop.addEventListener("click", () => {  // a delete cannot be undone: the first click asks, the second one (within 4 s) deletes
        if (armed) { clearTimeout(armed); armed = 0; act(one.day, "delete"); return; }
        drop.textContent = t("super.hist.sure"); drop.classList.add("armed");
        armed = setTimeout(() => { armed = 0; drop.textContent = t("super.hist.delete"); drop.classList.remove("armed"); }, 4000);
      });
      return h("div", {class: "sa-hrow"}, open, keep, drop);
    }
    async function act(day, action) {
      say("");
      let answer;
      try { answer = await SERVE.call("/api/super/history/act", {day, action}, 8); } catch (error) { say(t("super.hist.failed", {why: failure(error)})); return; }
      if (!answer.ok) { say(t("super.hist.failed", {why: answer.why || ""})); return; }
      list();
    }
    async function read(day) {
      const mine = ++token;
      say("");
      back.hidden = false;
      toggle.hidden = true;
      title.textContent = dayName(day);
      body.replaceChildren(h("div", {class: "sa-hist-empty"}, "…"));
      let answer;
      try { answer = await SERVE.call("/api/super/history", {day}, 8); } catch (error) { if (mine === token) { body.replaceChildren(); say(t("super.hist.failed", {why: failure(error)})); } return; }
      if (mine !== token) return;
      if (!answer.ok) { body.replaceChildren(h("div", {class: "sa-hist-empty"}, t("super.hist.gone"))); return; }
      title.textContent = dayName(day) + " · " + t("super.hist.spent", {n: amount(answer.spent || 0)});
      const SAY_WHY = {stopped: "super.why.stopped", accept: "super.why.accept", cancelled: "super.why.cancelled"};  // written out: a search for a key finds its place
      // 1.8.43: what the tasks said when they stopped (`says`) is read back among the messages, by its time, grey (its wait is over)
      const says = (answer.says || []).filter((one) => one && one.id).map((one) => ({...one, role: "say"}));
      const all = [...(answer.messages || []), ...says].sort((x, y) => String(x.at || "").localeCompare(String(y.at || "")));
      body.replaceChildren(...all.map((message) => (message.role === "say"
        ? h("div", {class: "sa-row sayrow settled", "data-task": message.task}, h("span", {class: "sa-mini hot"}, PET.face("you", "", 0)),
          h("div", {class: "sa-bub fwd"}, h("div", {class: "sa-fw"}, h("span", {class: "sa-task"}, message.task), h("span", {class: "sa-ttag"}, t(SAY_WHY[message.why] || "super.why.other")), message.at ? h("span", {class: "sa-when"}, when(message.at, 11, 16)) : null),
            h("div", {class: "sa-text"}, linked(message.text))))
        : message.role === "you"
        ? h("div", {class: "sa-row me"}, h("div", {class: "sa-bub", title: message.at ? when(message.at, 11, 16) : null}, message.kind === "summary" ? t("super.quick.summary") : message.text))
        : h("div", {class: "sa-row"}, h("span", {class: "sa-mini boss"}, PET.face("calm", "", 0, true)),
          h("div", {class: "sa-bub agent"}, h("div", {class: "sa-fw"}, h("b", null, t("super.name")), message.at ? h("span", {class: "sa-when"}, when(message.at, 11, 16)) : null),
            h("div", {class: "sa-text"}, message.text ? linked(message.text) : t("super.hist.noanswer")))))));
      body.scrollTop = 0;
    }

    function open() { panel.hidden = false; button.classList.add("on"); archivedView = false; say(""); list(); }
    function close() { panel.hidden = true; button.classList.remove("on"); token++; }
    button.addEventListener("click", () => (panel.hidden ? open() : close()));
    shut.addEventListener("click", close);
    back.addEventListener("click", () => { say(""); list(); });
    toggle.addEventListener("click", () => { archivedView = !archivedView; say(""); list(); });
    panel.addEventListener("keydown", (event) => { if (event.key === "Escape") { event.stopPropagation(); close(); button.focus(); } });
    return {button, close};
  }

  return {create};
})();
