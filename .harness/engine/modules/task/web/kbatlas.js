// The map of the domains, in the knowledge base window (core/kbatlas.py). A person reads it to see how the domains hang together, and what a change reaches. Only reads.
// Columns, not forces: what others build on stands left, what comes last stands right, and the same data draws the same picture every time, so a person learns where things are.
// A domain that many use and that uses none (a calendar, a log) would draw a line from everywhere: it stands in a strip below, with no lines, until the person asks for them.
// Nodes are buttons, lines are one SVG under them. Needs common.js (h, t).
"use strict";

const ATLAS = (function () {
  const NS = "http://www.w3.org/2000/svg";
  const WIDE = 176, HIGH = 62, STEP_X = 232, STEP_Y = 82, ROOMY = 136, EDGE = 18, SMALLEST = .62;
  const number = (value) => Number(value).toLocaleString();

  // The columns. A line that closes a circle (A uses B, B uses A) gets no weight here: it is drawn dashed, against the flow.
  function columns(names, links) {
    const uses = new Map(names.map((name) => [name, []]));
    links.forEach((link) => { if (uses.has(link.from) && uses.has(link.to)) uses.get(link.from).push(link); });
    const seen = new Map(), rank = new Map();
    function visit(name) {
      seen.set(name, 1);
      let high = 0;
      for (const link of uses.get(name)) {
        if (seen.get(link.to) === 1) { link.back = true; continue; }
        if (!seen.has(link.to)) visit(link.to);
        high = Math.max(high, rank.get(link.to) + 1);
      }
      seen.set(name, 2);
      rank.set(name, high);
    }
    names.forEach((name) => { if (!seen.has(name)) visit(name); });
    const out = [];
    names.forEach((name) => { (out[rank.get(name)] = out[rank.get(name)] || []).push(name); });
    const near = new Map(names.map((name) => [name, []]));
    links.forEach((link) => { if (near.has(link.from) && near.has(link.to)) { near.get(link.from).push(link.to); near.get(link.to).push(link.from); } });
    const place = new Map();
    const places = () => out.forEach((column) => (column || []).forEach((name, index) => place.set(name, index / Math.max(1, column.length - 1))));
    places();
    for (let round = 0; round < 6; round++) {  // each one moves towards its neighbours: fewer crossings
      out.forEach((column) => {
        if (!column) return;
        const mean = new Map(column.map((name) => [name, near.get(name).length ? near.get(name).reduce((sum, other) => sum + place.get(other), 0) / near.get(name).length : place.get(name)]));
        column.sort((one, two) => mean.get(one) - mean.get(two) || one.localeCompare(two));
      });
      places();
    }
    return out.filter(Boolean);
  }

  function draw(stage, data) {
    const st = {pick: "", mode: "uses", shared: false};
    const all = data.domains.map((item) => item.name);
    const byName = new Map(data.domains.map((item) => [item.name, item]));
    const into = (name) => data.links.filter((link) => link.to === name);
    const from = (name) => data.links.filter((link) => link.from === name);
    const most = Math.max(3, Math.ceil(all.length * .4));
    const common = new Set(all.filter((name) => into(name).length >= most && !from(name).length));  // a foundation, not a hub: it uses no other domain
    const canvas = h("div", {class: "ka-canvas"}), side = h("aside", {class: "ka-side"}), strip = h("div", {class: "ka-strip"});
    const nodes = new Map();
    let lines = [];

    function stateOf(item) { return item.left ? "learning" : item.done ? "done" : "open"; }
    function node(item) {
      const share = item.objects + item.left ? Math.round(item.objects / (item.objects + item.left) * 100) : 0;
      const flags = [item.outdated ? h("span", {class: "ka-flag"}, t("dock.atlas.outdated", {n: number(item.outdated)})) : null, item.requests ? h("span", {class: "ka-flag"}, t("dock.atlas.asks", {n: item.requests})) : null];
      const button = h("button", {type: "button", class: "ka-node " + stateOf(item), title: item.name}, h("span", {class: "ka-name"}, h("i"), h("b", null, item.name)),
        h("span", {class: "ka-sub"}, h("span", null, t("dock.atlas.objects", {n: number(item.objects)})), flags), h("span", {class: "ka-bar"}, h("span", {style: "width:" + share + "%"})));
      button.addEventListener("click", (event) => { event.stopPropagation(); st.pick = st.pick === item.name ? "" : item.name; paint(); });
      nodes.set(item.name, button);
      return button;
    }

    function layout() {
      nodes.clear();
      const shown = all.filter((name) => st.shared || !common.has(name));
      const links = data.links.filter((link) => shown.includes(link.from) && shown.includes(link.to));
      links.forEach((link) => { delete link.back; });
      const rows = columns(shown, links);
      const tall = Math.max(1, ...rows.map((column) => column.length));
      const width = rows.length * STEP_X - (STEP_X - WIDE) + EDGE * 2;
      const zoom = Math.max(SMALLEST, Math.min(1, (canvas.clientWidth - 4) / width));
      const down = Math.max(STEP_Y, Math.min(ROOMY, (canvas.clientHeight / zoom - EDGE * 2) / tall));  // few rows: they take the room there is, and the lines have space
      const height = tall * down - (down - HIGH) + EDGE * 2;
      const svg = document.createElementNS(NS, "svg");
      svg.setAttribute("width", width); svg.setAttribute("height", height);
      const marker = document.createElementNS(NS, "marker");
      for (const [key, value] of Object.entries({id: "ka-arrow", viewBox: "0 0 8 8", refX: 7, refY: 4, markerWidth: 7, markerHeight: 7, markerUnits: "userSpaceOnUse", orient: "auto"})) marker.setAttribute(key, value);
      const tip = document.createElementNS(NS, "path"); tip.setAttribute("d", "M0 0L8 4L0 8z"); tip.setAttribute("class", "ka-tip"); marker.append(tip);
      const defs = document.createElementNS(NS, "defs"); defs.append(marker); svg.append(defs);
      const at = new Map(), boxes = [];
      rows.forEach((column, x) => {
        const top = (tall - column.length) * down / 2;
        column.forEach((name, y) => {
          at.set(name, {x: EDGE + x * STEP_X, y: EDGE + top + y * down});
          const box = node(byName.get(name));
          box.style.left = at.get(name).x + "px"; box.style.top = at.get(name).y + "px";
          boxes.push(box);
        });
      });
      lines = links.map((link) => {
        const one = at.get(link.from), two = at.get(link.to), path = document.createElementNS(NS, "path");
        const right = one.x > two.x;  // the user stands to the right of what it uses; a line of a circle goes the other way
        const x1 = right ? one.x : one.x + WIDE, x2 = right ? two.x + WIDE : two.x, y1 = one.y + HIGH / 2, y2 = two.y + HIGH / 2, bend = Math.max(40, Math.abs(x2 - x1) / 2) * (right ? -1 : 1);
        const flat = one.x === two.x;
        path.setAttribute("d", flat ? `M${one.x + WIDE} ${y1}C${one.x + WIDE + 60} ${y1} ${two.x + WIDE + 60} ${y2} ${two.x + WIDE} ${y2}` : `M${x1} ${y1}C${x1 + bend} ${y1} ${x2 - bend} ${y2} ${x2} ${y2}`);
        path.setAttribute("class", "ka-line" + (link.back ? " back" : ""));
        path.setAttribute("stroke-width", (1 + Math.min(3.4, Math.log2(link.uses) * .55)).toFixed(2));
        path.setAttribute("marker-end", "url(#ka-arrow)");
        const label = document.createElementNS(NS, "title");
        label.textContent = t("dock.atlas.line", {from: link.from, to: link.to, n: number(link.uses)});
        path.append(label);
        svg.append(path);
        return {link, path};
      });
      canvas.replaceChildren(h("div", {class: "ka-world", style: "width:" + width + "px;height:" + height + "px;zoom:" + zoom.toFixed(3)}, svg, boxes));
      const chips = all.filter((name) => !shown.includes(name)).map((name) => {
        const chip = h("button", {type: "button", class: "ka-chip", title: t("dock.atlas.usedby", {n: into(name).length})}, name, h("span", null, String(into(name).length)));
        chip.addEventListener("click", () => { st.pick = st.pick === name ? "" : name; paint(); });
        nodes.set(name, chip);
        return chip;
      });
      const parts = [];
      if (chips.length) parts.push(h("span", {class: "sub"}, t("dock.atlas.common")), ...chips);
      if (common.size) {
        const toggle = h("button", {type: "button", class: "first-link"}, t(st.shared ? "dock.atlas.hide" : "dock.atlas.show"));
        toggle.addEventListener("click", () => { st.shared = !st.shared; layout(); paint(); });
        parts.push(toggle);
      }
      if (data.loose.objects) {
        const chip = h("button", {type: "button", class: "ka-chip loose"}, t("dock.atlas.loose", {n: number(data.loose.objects)}));
        chip.addEventListener("click", () => { st.pick = "\0loose"; paint(); });
        parts.push(chip);
      }
      strip.replaceChildren(...parts);
      strip.hidden = !parts.length;
    }

    // Who a change reaches: what uses it, what uses that, and so on. Each step is a ring.
    function reach(start) {
      const hops = new Map([[start, 0]]);
      let front = [start];
      for (let step = 1; front.length; step++) {
        const next = [];
        front.forEach((name) => into(name).forEach((link) => { if (!hops.has(link.from)) { hops.set(link.from, step); next.push(link.from); } }));
        front = next;
      }
      return hops;
    }

    function rows(title, list, name) {
      if (!list.length) return null;
      return h("section", null, h("h4", null, title), list.slice().sort((one, two) => two.uses - one.uses).map((link) => {
        const other = name(link);
        const body = h("div", {class: "ka-pairs", hidden: ""}, link.pairs.map((pair) => h("code", null, pair[0] + " → " + pair[1])), link.uses > link.pairs.length ? h("span", {class: "sub"}, t("dock.atlas.more", {n: number(link.uses - link.pairs.length)})) : null);
        const row = h("button", {type: "button", class: "ka-row", "aria-expanded": "false"}, h("span", null, other), h("b", null, number(link.uses)));
        row.addEventListener("click", () => { body.hidden = !body.hidden; row.setAttribute("aria-expanded", String(!body.hidden)); });
        return [row, body];
      }));
    }

    const fill = (...parts) => side.replaceChildren(...parts.flat().filter(Boolean));
    function details() {
      if (st.pick === "\0loose") {
        fill(h("h3", null, t("dock.atlas.loose", {n: number(data.loose.objects)})), h("p", {class: "sub"}, t("dock.atlas.loose.why")), h("div", {class: "ka-pairs"}, data.loose.sample.map((name) => h("code", null, name))));
        return;
      }
      const item = byName.get(st.pick);
      if (!item) {
        fill(h("h3", null, t("dock.atlas.head", {domains: number(all.length), objects: number(data.domains.reduce((sum, one) => sum + one.objects, 0)), lines: number(data.links.reduce((sum, one) => sum + one.uses, 0))})),
          h("p", {class: "sub"}, t("dock.atlas.read")), data.audited ? null : h("p", {class: "ka-warn"}, t("dock.atlas.unaudited")), data.twice && data.twice.length ? h("p", {class: "ka-warn"}, t("dock.atlas.twice", {n: data.twice.length, sample: data.twice[0]})) : null);
        return;
      }
      const head = [h("h3", {title: item.name}, item.name), item.about ? h("p", {class: "sub"}, item.about) : null];
      if (st.mode === "impact") {
        const hops = reach(item.name), steps = [];
        hops.forEach((hop, name) => { if (hop) (steps[hop] = steps[hop] || []).push(name); });
        fill(head, h("p", {class: "ka-big"}, t(hops.size > 1 ? "dock.atlas.reach" : "dock.atlas.reach.none", {n: hops.size - 1})),
          steps.filter(Boolean).map((names, index) => h("section", null, h("h4", null, t(index ? "dock.atlas.step" : "dock.atlas.first", {n: index + 1})), h("p", {class: "ka-names"}, names.join(", ")))));
        return;
      }
      const kinds = Object.entries(item.types).sort((one, two) => two[1] - one[1]).map(([kind, count]) => kind + " " + number(count)).join(" · ");
      const notes = [item.left ? t("dock.atlas.left", {n: number(item.left)}) : null, item.outdated ? t("dock.atlas.outdated", {n: number(item.outdated)}) : null, item.requests ? t("dock.atlas.asks", {n: item.requests}) : null, item.questions ? t("dock.atlas.questions", {n: item.questions}) : null].filter(Boolean);
      fill(head, h("p", {class: "sub"}, kinds), notes.length ? h("p", {class: "ka-warn"}, notes.join(" · ")) : null,
        rows(t("dock.atlas.uses"), from(item.name), (link) => link.to), rows(t("dock.atlas.usedin"), into(item.name), (link) => link.from),
        item.entries.length ? h("section", null, h("h4", null, t("dock.atlas.entries")), h("div", {class: "ka-pairs"}, item.entries.slice(0, 12).map((name) => h("code", null, name)))) : null);
    }

    function paint() {
      const name = st.pick, known = byName.has(name);
      const hops = known && st.mode === "impact" ? reach(name) : null;
      const close = new Set(known ? [name, ...from(name).map((link) => link.to), ...into(name).map((link) => link.from)] : []);
      nodes.forEach((box, key) => {
        box.classList.toggle("on", key === name);
        box.classList.toggle("dim", known && (hops ? !hops.has(key) : !close.has(key)));
        for (const step of [1, 2, 3]) box.classList.toggle("hop" + step, Boolean(hops) && (step === 3 ? hops.get(key) >= 3 : hops.get(key) === step));
      });
      lines.forEach(({link, path}) => {
        const lit = known && (hops ? hops.has(link.from) && hops.has(link.to) && hops.get(link.from) === hops.get(link.to) + 1 : link.from === name || link.to === name);
        path.classList.toggle("lit", Boolean(lit));
        path.classList.toggle("dim", known && !lit);
      });
      modes.forEach((chip) => chip.classList.toggle("on", chip.dataset.key === st.mode));
      details();
    }

    const modes = ["uses", "impact"].map((key) => {
      const chip = h("button", {type: "button", class: "chip", "data-key": key}, t("dock.atlas.mode." + key));
      chip.addEventListener("click", () => { st.mode = key; paint(); });
      return chip;
    });
    const search = h("input", {type: "text", class: "code ka-find", autocomplete: "off", spellcheck: "false", placeholder: t("dock.atlas.find")});
    const found = h("span", {class: "sub ka-found"});
    search.addEventListener("input", () => {
      const word = search.value.trim().toLowerCase();
      found.textContent = "";
      if (!word) return;
      const domain = all.find((name) => name.toLowerCase().includes(word));
      const object = domain ? null : Object.keys(data.owners || {}).find((id) => id.toLowerCase().includes(word));
      const hit = domain || (object && data.owners[object]);
      if (object) found.textContent = t("dock.atlas.owner", {id: object, domain: hit});
      else if (!hit) found.textContent = t("dock.skills.none");
      if (hit) { st.pick = hit; paint(); if (nodes.has(hit)) nodes.get(hit).scrollIntoView({block: "nearest", inline: "center"}); }
    });
    canvas.addEventListener("click", () => { if (st.pick) { st.pick = ""; paint(); } });
    stage.classList.add("ka-stage");
    stage.replaceChildren(h("div", {class: "ka-top"}, h("div", {class: "chips dock-tabs"}, modes), search, found), h("div", {class: "ka-body"}, h("div", {class: "ka-main"}, canvas, strip), side));
    if (!all.length) { stage.replaceChildren(h("p", {class: "sub"}, t("dock.kb.nodomains"))); return; }
    layout();
    paint();
  }
  return {draw};
})();
