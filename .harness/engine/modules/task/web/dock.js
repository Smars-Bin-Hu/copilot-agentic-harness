// The buttons at the bottom right (1.6.61): the question mark and the one-click chats. The gear is shell.js's. The brain comes with the knowledge base window.
// DOCK.start asks with the whole message in view, sends, and brings VS Code forward. Needs common.js (h, t), serve.js (SERVE).
const DOCK = (function () {
  const ask = (step, body) => SERVE.post("/api/skill", {step, ...body}).then((data) => data.result);

  function done() {
    const close = h("button", {type: "button", class: "act hot"}, t("board.new.close"));
    const view = SERVE.dialog([h("h2", null, t("dock.sent")), h("p", null, t("dock.sent.where")), h("div", {class: "row"}, close)]);
    close.addEventListener("click", view.close);
  }

  function start(skill, words) {
    const lang = document.documentElement.lang === "zh" ? "zh" : "en";
    const body = {skill, words: words || "", lang};
    const preview = h("pre", {class: "send-preview"}, "...");
    const said = h("div", {class: "bad"});
    const go = h("button", {type: "button", class: "act hot", disabled: "disabled"}, t("dock.send"));
    const no = h("button", {type: "button", class: "act"}, t("board.serve.cancel"));
    const view = SERVE.dialog([h("h2", null, t("dock.title")), h("p", {class: "sub"}, t("dock.hint")), preview, said, h("div", {class: "row"}, go, no)]);
    no.addEventListener("click", view.close);
    ask("preview", body).then((found) => {
      preview.textContent = found.text;
      if (found.blocked) said.replaceChildren(...SERVE.reasons(found.blocked));
      go.disabled = Boolean(found.blocked);
    }, (error) => { preview.textContent = ""; said.replaceChildren(...SERVE.reasons(error.message || error)); });
    go.addEventListener("click", () => {
      go.disabled = true;
      ask("act", body).then(() => { view.close(); done(); }, (error) => { go.disabled = false; said.replaceChildren(...SERVE.reasons(error.message || error)); });
    });
  }

  function build() {
    const panel = h("section", {class: "dock-panel", hidden: ""});
    const box = h("input", {type: "text", class: "su-in", maxlength: 2000, placeholder: t("dock.ask.ph"), "aria-label": t("dock.ask")});
    const send = h("button", {type: "button", class: "act hot"}, t("dock.ask"));
    const deep = h("button", {type: "button", class: "act"}, t("dock.deep"));
    const first = h("button", {type: "button", class: "act"}, t("dock.first"));
    const askIt = () => { panel.hidden = true; start("harness-rookie-wondering", box.value); };
    send.addEventListener("click", askIt);
    box.addEventListener("keydown", (event) => { if (event.key === "Enter") askIt(); });
    deep.addEventListener("click", () => { panel.hidden = true; start("harness-rookie-wondering", ""); });
    first.addEventListener("click", () => { panel.hidden = true; start("harness-rookie-quick-start", ""); });
    panel.append(h("h3", null, t("dock.help")), h("div", {class: "dock-line"}, box, send), h("div", {class: "dock-line"}, deep, first));
    const button = h("button", {type: "button", class: "dock-btn dock-ask", "aria-label": t("dock.help"), title: t("dock.help")}, "?");
    button.addEventListener("click", () => { panel.hidden = !panel.hidden; if (!panel.hidden) box.focus(); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") panel.hidden = true; });
    document.body.append(panel, button);
  }

  if (typeof DATA !== "undefined" && DATA.serve) build();
  return {start};
})();
