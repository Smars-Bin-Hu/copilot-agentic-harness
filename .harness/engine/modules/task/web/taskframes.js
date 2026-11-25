// Task pages in tabs, one iframe of `/task/<name>?embed=1` each (1.8.36): what the workbench's Task pane and the board's task window (taskwin.js) share.
// A frame that is not shown is hidden, never destroyed or moved (a moved iframe reloads), so a tab switch is instant; a hidden frame asks nothing (common.js `unseen`) and looks again when it shows (`wake`).
// At most MAX frames stay loaded: past it, the one seen longest ago is unloaded and its tab stays, faded (`cold`); a click loads it again. `warm(name)` loads one page ahead (a hover), kept WARM_MS unless it is opened.
// The caller gives the two nodes (the tab strip, the box of the frames) and the class prefix of its look (`wb` or `tw`: `<p>-tab`, `<p>-tab-n`, `<p>-tab-x`, `<p>-frame`).
// Needs common.js (h, t, spinner).
"use strict";

const TASKFRAMES = (function () {
  const MAX = 6;
  const WARM_MS = 20000;
  const url = (name) => "/task/" + encodeURIComponent(name);

  // A hidden frame asked nothing: it looks again at once when it shows (common.js pollEvery listens to visibilitychange).
  function wake(frame) { setTimeout(() => { try { frame.contentDocument.dispatchEvent(new Event("visibilitychange")); } catch (error) { /* not loaded yet: it asks on its next round */ } }, 0); }

  // options: {tabs, frames, prefix, changed(), closed(name), title(name)}
  function create(options) {
    const p = options.prefix;
    let tabs = [], active = "", warm = null, shown = true;
    const changed = () => { if (options.changed) options.changed(); };
    const find = (name) => tabs.find((tab) => tab.name === name) || null;

    // F8: until the page of a frame has loaded, the board's turning circle shows over it (`<p>-wait`, shown only beside a frame that is not hidden): the first load of a task page can take many seconds on a slow computer
    function makeFrame(name) {
      const frame = h("iframe", {class: p + "-frame", src: url(name) + "?embed=1", "aria-label": options.title ? options.title(name) : name, hidden: ""});  // aria-label, not title: a title shows as a tooltip anywhere over the page
      frame.wait = h("div", {class: p + "-wait", role: "status", "aria-label": t("board.serve.working")}, spinner());
      frame.addEventListener("load", () => { if (frame.wait) { frame.wait.remove(); frame.wait = null; } });
      options.frames.append(frame, frame.wait);
      return frame;
    }
    function drop(frame) { if (frame.wait) { frame.wait.remove(); frame.wait = null; } frame.remove(); }
    function load(tab) {
      if (tab.frame) return;
      if (warm && warm.name === tab.name) { tab.frame = warm.frame; clearTimeout(warm.timer); warm = null; } else tab.frame = makeFrame(tab.name);
      tab.node.classList.remove("cold");
      const loaded = tabs.filter((one) => one.frame && one !== tab);
      if (loaded.length < MAX) return;
      const oldest = loaded.sort((a, b) => a.seen - b.seen)[0];
      drop(oldest.frame);
      oldest.frame = null;
      oldest.node.classList.add("cold");
    }
    function sync() {
      const one = find(active);
      if (one && shown) { load(one); one.seen = Date.now(); }
      for (const tab of tabs) {
        const on = tab === one;
        if (tab.frame) {
          const was = tab.frame.hidden;
          tab.frame.hidden = !on;
          if (on && was && shown) wake(tab.frame);
        }
        tab.node.classList.toggle("on", on);
        tab.label.setAttribute("aria-selected", on ? "true" : "false");
      }
      if (one) one.node.scrollIntoView({block: "nearest", inline: "nearest"});
      changed();
    }
    function close(name) {
      const tab = find(name);
      if (!tab) return;
      if (tab.frame) drop(tab.frame);
      tab.node.remove();
      tabs = tabs.filter((one) => one !== tab);
      if (active === name) active = tabs.length ? tabs[tabs.length - 1].name : "";
      sync();
      if (options.closed) options.closed(name);
    }
    function add(name) {  // a tab with no frame yet
      const label = h("button", {type: "button", class: p + "-tab-n", role: "tab", title: name}, name);
      const x = h("button", {type: "button", class: p + "-tab-x", title: t("super.wb.task.tab.close"), "aria-label": t("super.wb.task.tab.close")}, "✕");
      const node = h("div", {class: p + "-tab cold"}, label, x);
      const tab = {name, frame: null, node, label, seen: 0};
      label.addEventListener("click", () => select(name));
      x.addEventListener("click", () => close(name));
      node.addEventListener("auxclick", (event) => { if (event.button === 1) { event.preventDefault(); close(name); } });  // the middle button closes, as in a browser
      tabs.push(tab);
      options.tabs.append(node);
      return tab;
    }
    function open(name) { if (!find(name)) add(name); active = name; sync(); }
    function select(name) { if (find(name)) { active = name; sync(); } }
    return {
      open, select, close,
      closeAll() { for (const tab of tabs.slice()) { if (tab.frame) drop(tab.frame); tab.node.remove(); } tabs = []; active = ""; changed(); },
      restore(names, at) { for (const name of names) if (name && !find(name)) add(name); if (find(at)) active = at; else if (tabs.length && !find(active)) active = tabs[tabs.length - 1].name; for (const tab of tabs) tab.node.classList.toggle("on", tab.name === active); },  // tabs only: nothing loads until one shows
      warm(name) {  // load a page ahead of a click; one at a time
        if (!name || find(name) || (warm && warm.name === name)) return;
        if (warm) { clearTimeout(warm.timer); drop(warm.frame); }
        const frame = makeFrame(name);
        warm = {name, frame, timer: setTimeout(() => { if (warm && warm.frame === frame) { drop(frame); warm = null; } }, WARM_MS)};
      },
      setShown(value) { shown = Boolean(value); if (shown) sync(); },  // the box is on screen again: the active tab loads and looks again
      wakeActive() { const one = find(active); if (one && one.frame) wake(one.frame); },
      names: () => tabs.map((tab) => tab.name),
      active: () => (find(active) ? active : ""),
      count: () => tabs.length,
    };
  }
  return {create, url, wake, MAX};
})();
