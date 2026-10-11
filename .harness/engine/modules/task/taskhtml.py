"""The two pages a person opens in a browser (M12-1, M6-6): one task's time and usage, and the board of all tasks.

Each page is one file with everything in it: no script, no outside font, no network. The charts are plain boxes and
one SVG line. The numbers come from taskinsight; this file only draws them. It never raises over a missing number.
"""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Optional

from core import messages

from .taskinsight import amount, clock, percent, share

PARTS = ("model", "tool", "subagent", "approval", "other")
STYLE = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2330;--soft:#667085;--line:#e4e7ec;--model:#4f7cf0;--tool:#27a591;--subagent:#8e6fe0;
--approval:#eb9a26;--other:#c3c9d4;--wait:#e58a8a;--usage:#30364a;--good:#1f9d63;--bad:#d2493d;--track:#eef0f4}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--card:#1b2029;--ink:#e7eaf0;--soft:#98a2b3;--line:#2b3340;--other:#4a5364;
--usage:#cdd3e0;--track:#262d39}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 20px 56px}
h1{font-size:24px;margin:0 0 4px;font-weight:650}
h2{font-size:15px;margin:0 0 14px;font-weight:650}
a{color:var(--model);text-decoration:none}a:hover{text-decoration:underline}
.sub{color:var(--soft);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin-top:16px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:20px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi b{display:block;font-size:22px;font-weight:650;line-height:1.3}
.kpi span{color:var(--soft);font-size:12px}
.bar{display:flex;height:18px;border-radius:5px;overflow:hidden;background:var(--track)}
.bar.thin{height:8px;border-radius:4px}
.bar i{display:block;height:100%}
.model{background:var(--model)}.tool{background:var(--tool)}.subagent{background:var(--subagent)}.approval{background:var(--approval)}
.other{background:var(--other)}.work{background:var(--model)}.usage{background:var(--usage)}
.wait{background:repeating-linear-gradient(135deg,var(--wait) 0 6px,transparent 6px 10px)}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:10px;color:var(--soft);font-size:12.5px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.legend b{color:var(--ink);font-weight:600}
ol.findings{margin:0;padding-left:20px}ol.findings li{margin:6px 0}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--soft);font-weight:500;padding:6px 10px 6px 0;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:7px 10px 7px 0;border-bottom:1px solid var(--line);vertical-align:middle}
tr:last-child td{border-bottom:0}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.grow{width:42%}
.tag{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;background:var(--track);color:var(--soft);white-space:nowrap}
.tag.good{color:var(--good)}.tag.bad{color:var(--bad)}.tag.hot{background:var(--approval);color:#fff}
tr.gap td{color:var(--soft);font-size:12px;padding:3px 0 3px 0;border-bottom:1px dashed var(--line)}
.empty{color:var(--soft)}
footer{margin-top:22px;color:var(--soft);font-size:12px}
svg{display:block;width:100%;height:120px}
"""


def say(key: str, **values: Any) -> str:
    return messages.text(key, **values)


def cell(text: Any) -> str:
    return escape(str(text))


def page(title: str, body: List[str], refresh: int = 0) -> str:
    reload = f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else ""
    return (
        f'<!doctype html>\n<html lang="zh">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">{reload}\n'
        f"<title>{cell(title)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n<main>\n" + "\n".join(body) + "\n</main>\n</body>\n</html>\n"
    )


def kpi(value: str, label: str) -> str:
    return f'<div class="kpi"><b>{cell(value)}</b><span>{cell(label)}</span></div>'


def stacked(parts: List[tuple], whole: float, thin: bool = False) -> str:
    """parts: (css class, value, tooltip). The bar is as wide as its box; each part takes value / whole of it."""
    pieces = []
    for name, value, tip in parts:
        if value and whole:
            pieces.append(f'<i class="{name}" style="width:{min(100.0, value / whole * 100):.2f}%" title="{cell(tip)}"></i>')
    return f'<div class="bar{" thin" if thin else ""}">' + "".join(pieces) + "</div>"


def legend(items: List[tuple]) -> str:
    """items: (css class, label, value text)."""
    return '<div class="legend">' + "".join(f'<span><i class="{name}"></i>{cell(label)} <b>{cell(value)}</b></span>' for name, label, value in items) + "</div>"


def stage_label(name: str) -> str:
    return say(f"insight.stage.{name}")


def wait_label(name: str) -> str:
    return say(f"insight.wait.{name}")


def part_label(name: str) -> str:
    return say(f"insight.part.{name}")


def time_parts(entry: Dict[str, Any]) -> List[tuple]:
    if entry.get("model_s") is None:
        return [("work", entry["active_s"], f"{say('report.active')} {clock(entry['active_s'])}")]
    return [(name, entry.get(f"{name}_s") or 0.0, f"{part_label(name)} {clock(entry.get(f'{name}_s'))}") for name in PARTS]


def line_chart(values: List[Optional[float]]) -> str:
    """One line over the prompts. Missing points are skipped."""
    points = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(points) < 2:
        return ""
    width, height, pad = 1000.0, 120.0, 10.0
    top = max(value for _index, value in points) or 1.0
    last = max(1, len(values) - 1)
    spots = [(pad + index / last * (width - 2 * pad), height - pad - value / top * (height - 2 * pad)) for index, value in points]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in spots)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="var(--model)"><title>#{index + 1}: {amount(value)}</title></circle>' for (x, y), (index, value) in zip(spots, points))
    return (
        f'<svg viewBox="0 0 {width:.0f} {height:.0f}" preserveAspectRatio="none" role="img">'
        f'<polyline points="{path}" fill="none" stroke="var(--model)" stroke-width="2" vector-effect="non-scaling-stroke"/>{dots}</svg>'
    )


def verdict_tag(verdict: str) -> str:
    if not verdict:
        return f'<span class="tag">{cell(say("report.review.none"))}</span>'
    return f'<span class="tag {"good" if verdict == "PASS" else "bad"}">{cell(verdict)}</span>'


# --- one task --------------------------------------------------------------------------------------


def task_page(info: Dict[str, Any]) -> str:
    totals = info["totals"]
    active, waiting = totals["active_s"], totals["waiting_s"]
    has_split, has_usage = totals["model_s"] is not None, totals["aiu"] is not None
    kind = say(f"task.kind.{info['kind'] or 'none'}")
    tier = say(f"task.tier.{info['tier'] or 'none'}")
    source = say(f"report.source.{info['source'].replace('-', '_')}")
    status = say("report.status.open") if info["status"] == "open" else say("report.status.closed")
    subtitle = say("report.subtitle", kind=kind, tier=tier, status=status, start=info["span"]["from"][:16].replace("T", " "), end=info["span"]["to"][:16].replace("T", " "))
    footer = say("report.footer", as_of=info["as_of"][:19].replace("T", " "), source=source)
    body = [
        f"<h1>{cell(say('report.title', name=info['name']))}</h1>",
        '<div class="sub">' + cell(subtitle) + "</div>",
        '<div class="kpis">',
        kpi(clock(active), say("report.kpi.active")),
        kpi(clock(waiting), say("report.kpi.waiting")),
        kpi(str(totals["prompts"]), say("report.kpi.prompts")),
        kpi(amount(totals["aiu"]) if has_usage else "-", say("report.kpi.aiu")),
        kpi(amount(totals["premium_requests"]) if totals["premium_requests"] is not None else "-", say("report.kpi.premium")),
        kpi(say("report.kpi.reviews.value", checks=totals["reviews"], fails=totals["review_fails"]), say("report.kpi.reviews")),
        "</div>",
    ]
    if not info["prompts"]:
        body.append(f'<div class="card empty">{cell(say("report.empty"))}</div>')
        body.append(f"<footer>{cell(footer)}</footer>")
        return page(say("report.title", name=info["name"]), body)

    body.append(f'<div class="card"><h2>{cell(say("report.findings"))}</h2><ol class="findings">')
    body += [f"<li>{cell(item['text'])}</li>" for item in info["findings"]]
    body.append("</ol></div>")

    body.append(f'<div class="card"><h2>{cell(say("report.time"))}</h2>')
    body.append(stacked([("work", active, f"{say('report.active')} {clock(active)}"), ("wait", waiting, f"{say('report.waiting')} {clock(waiting)}")], active + waiting))
    body.append(legend([("work", say("report.active"), f"{clock(active)} · {percent(share(active, active + waiting))}"), ("wait", say("report.waiting"), f"{clock(waiting)} · {percent(share(waiting, active + waiting))}")]))
    if has_split:
        body.append('<div style="height:16px"></div>')
        body.append(stacked(time_parts(totals), active))
        body.append(legend([(name, part_label(name), f"{clock(totals[name + '_s'])} · {percent(share(totals[name + '_s'], active))}") for name in PARTS]))
    body.append("</div>")

    longest = max(entry["active_s"] for entry in info["prompts"]) or 1.0
    dearest = max((entry["aiu"] or 0.0 for entry in info["prompts"]), default=0.0) or 1.0
    body.append(f'<div class="card"><h2>{cell(say("report.prompts"))}</h2><table><tr><th>#</th><th>{cell(say("report.col.at"))}</th><th>{cell(say("report.col.stage"))}</th><th>{cell(say("report.col.time"))}</th><th class="num"></th>')
    if has_usage:
        body.append(f'<th>AIU</th><th class="num"></th>')
    body.append(f'<th class="num">{cell(say("report.col.turns"))}</th><th class="num">{cell(say("report.col.calls"))}</th></tr>')
    columns = 9 if has_usage else 7
    for entry in info["prompts"]:
        notes = "".join(
            f' <span class="tag bad">{cell(say(key, n=entry[field]))}</span>'
            for key, field in (("report.tag.denied", "denied"), ("report.tag.blocks", "stop_blocks"), ("report.tag.failed", "failed_tool_calls")) if entry[field]
        )
        row = f'<tr><td>{entry["n"]}</td><td>{cell(entry["at"][5:16].replace("T", " "))}</td><td><span class="tag">{cell(stage_label(entry["stage"]))}</span>{notes}</td>'
        row += f'<td class="grow">{stacked(time_parts(entry), longest)}</td><td class="num">{cell(clock(entry["active_s"]))}</td>'
        if has_usage:
            row += f'<td style="width:14%">{stacked([("usage", entry["aiu"] or 0.0, "AIU " + amount(entry["aiu"]))], dearest, thin=True)}</td><td class="num">{cell(amount(entry["aiu"]))}</td>'
        row += f'<td class="num">{entry["turns"] or "-"}</td><td class="num">{entry["tool_calls"]}</td></tr>'
        body.append(row)
        if entry["waited_after_s"] and entry["waited_after_s"] >= 60:
            reason = next((item["reason"] for item in info["waits"] if item["after_prompt"] == entry["n"]), "reply")
            body.append(f'<tr class="gap"><td></td><td colspan="{columns - 1}">⏸ {cell(say("report.gap", time=clock(entry["waited_after_s"]), reason=wait_label(reason)))}</td></tr>')
    body.append("</table>")
    if has_split:
        body.append(legend([(name, part_label(name), "") for name in PARTS]))
    body.append("</div>")

    if len(info["stages"]) > 1 or info["stages"] and info["stages"][0]["stage"] != "work":
        body.append(f'<div class="card"><h2>{cell(say("report.stages"))}</h2><table><tr><th>{cell(say("report.col.stage"))}</th><th class="num">{cell(say("report.col.prompts"))}</th><th>{cell(say("report.col.time"))}</th><th class="num"></th>')
        if has_usage:
            body.append('<th>AIU</th><th class="num"></th>')
        body.append("</tr>")
        for stage in info["stages"]:
            row = f'<tr><td>{cell(stage["label"])}</td><td class="num">{stage["prompts"]}</td><td style="width:32%">{stacked([("work", stage["share_time"], percent(stage["share_time"]))], 1.0, thin=True)}</td><td class="num">{cell(clock(stage["active_s"]))} · {percent(stage["share_time"])}</td>'
            if has_usage:
                row += f'<td style="width:32%">{stacked([("usage", stage["share_aiu"], percent(stage["share_aiu"]))], 1.0, thin=True)}</td><td class="num">{cell(amount(stage["aiu"]))} · {percent(stage["share_aiu"])}</td>'
            body.append(row + "</tr>")
        body.append("</table></div>")

    chart = line_chart([entry["context_tokens"] for entry in info["prompts"]])
    if chart:
        body.append(f'<div class="card"><h2>{cell(say("report.context"))}</h2>{chart}<div class="sub">{cell(say("report.context.note", first=amount(totals["context_tokens_first"]), largest=amount(totals["context_tokens_max"])))}</div></div>')

    if info["tools"]:
        slowest = max(tool["total_s"] for tool in info["tools"]) or 1.0
        body.append(f'<div class="card"><h2>{cell(say("report.tools"))}</h2><table><tr><th>{cell(say("report.col.tool"))}</th><th class="num">{cell(say("report.col.calls"))}</th><th>{cell(say("report.col.total"))}</th><th class="num"></th><th class="num">{cell(say("report.col.longest"))}</th><th class="num">{cell(say("report.col.failed"))}</th><th class="num">{cell(say("report.col.result_tokens"))}</th></tr>')
        for tool in info["tools"][:15]:
            body.append(
                f'<tr><td>{cell(tool["name"])}</td><td class="num">{tool["calls"]}</td><td style="width:30%">{stacked([("tool", tool["total_s"], clock(tool["total_s"]))], slowest, thin=True)}</td>'
                f'<td class="num">{cell(clock(tool["total_s"]))}</td><td class="num">{cell(clock(tool["max_s"]))}</td><td class="num">{tool["failed"] or "-"}</td><td class="num">{cell(amount(tool["result_tokens"]))}</td></tr>'
            )
        body.append("</table></div>")

    if info["reviews"]:
        body.append(f'<div class="card"><h2>{cell(say("report.reviews"))}</h2><table><tr><th>{cell(say("report.col.check"))}</th><th>{cell(say("report.col.at"))}</th><th>{cell(say("report.col.verdict"))}</th><th class="num">{cell(say("report.col.time"))}</th><th class="num">token</th><th>{cell(say("report.col.model"))}</th></tr>')
        for item in info["reviews"]:
            body.append(
                f'<tr><td>round-{int(item["number"] or 0):03d}</td><td>{cell(str(item["started_at"])[5:16].replace("T", " "))}</td><td>{verdict_tag(item["verdict"])}</td>'
                f'<td class="num">{cell(clock(item["seconds"]))}</td><td class="num">{cell(amount(item["tokens"]))}</td><td>{cell(item["model"] or "-")}</td></tr>'
            )
        body.append("</table></div>")

    body.append("<footer>" + cell(footer) + "<br>" + cell(say("report.footer.note")) + "</footer>")
    return page(say("report.title", name=info["name"]), body)


# --- the board -------------------------------------------------------------------------------------


def board_page(rows: List[Dict[str, Any]], as_of: str, refresh: int = 0) -> str:
    """rows: what `task list` gives, each with `brief` (taskinsight.brief or None) and `report` (the file name of its page or '')."""
    open_rows = [row for row in rows if row["status"] == "open"]
    waiting = [row for row in rows if row["waiting"]]
    usage = [row["brief"]["aiu"] for row in rows if row.get("brief") and row["brief"]["aiu"] is not None]
    body = [
        f"<h1>{cell(say('board.title'))}</h1>",
        f'<div class="sub">{cell(say("board.subtitle", as_of=as_of[:19].replace("T", " ")))}</div>',
        '<div class="kpis">',
        kpi(str(len(open_rows)), say("board.kpi.open")),
        kpi(str(len(waiting)), say("board.kpi.waiting")),
        kpi(clock(max((row["waited_s"] or 0 for row in waiting), default=None)) if waiting else "-", say("board.kpi.longest")),
        kpi(clock(sum(row["brief"]["active_s"] for row in rows if row.get("brief"))), say("board.kpi.active")),
        kpi(amount(sum(usage)) if usage else "-", say("board.kpi.aiu")),
        "</div>",
    ]
    if not rows:
        body.append(f'<div class="card empty">{cell(say("board.empty"))}</div>')
        return page(say("board.title"), body, refresh)
    longest = max((row["brief"]["active_s"] + row["brief"]["waiting_s"] for row in rows if row.get("brief")), default=0.0) or 1.0
    body.append(
        f'<div class="card"><table><tr><th>{cell(say("board.col.task"))}</th><th>{cell(say("board.col.kind"))}</th><th>{cell(say("board.col.waiting"))}</th><th class="num">{cell(say("board.col.waited"))}</th>'
        f'<th>{cell(say("board.col.time"))}</th><th class="num"></th><th class="num">AIU</th><th class="num">{cell(say("board.col.prompts"))}</th><th class="num">{cell(say("board.col.reviews"))}</th><th>{cell(say("board.col.updated"))}</th></tr>'
    )
    for row in rows:
        name = f'<a href="{cell(row["report"])}">{cell(row["name"])}</a>' if row.get("report") else cell(row["name"])
        if row["status"] != "open":
            state = '<span class="tag">' + cell(say("board.state.new") if row["status"] == "new" else say("board.state.closed")) + "</span>"
        elif row["waiting"]:
            state = f'<span class="tag hot">{cell(row["waiting"])}</span>'
        else:
            state = f'<span class="tag good">{cell(say("board.state.running"))}</span>'
        needs = f'<div class="sub">{cell(say("board.depends", names="、".join(row["depends_on"])))}</div>' if row.get("depends_on") else ""
        brief = row.get("brief")
        kind = say(f"task.kind.{row['kind'] or 'none'}") + " · " + say(f"task.tier.{row['tier'] or 'none'}") if row["status"] != "new" else "-"
        line = f'<tr><td>{name}{needs}</td><td>{cell(kind)}</td><td>{state}</td><td class="num">{cell(clock(row["waited_s"]) if row["waiting"] and row["waited_s"] is not None else "-")}</td>'
        if brief:
            bar = stacked([("work", brief["active_s"], f"{say('report.active')} {clock(brief['active_s'])}"), ("wait", brief["waiting_s"], f"{say('report.waiting')} {clock(brief['waiting_s'])}")], longest, thin=True)
            line += (
                f'<td style="width:22%">{bar}</td><td class="num">{cell(clock(brief["active_s"]))}</td><td class="num">{cell(amount(brief["aiu"]))}</td>'
                f'<td class="num">{brief["prompts"]}</td><td class="num">{cell(say("report.kpi.reviews.value", checks=brief["reviews"], fails=brief["review_fails"]) if brief["reviews"] else "-")}</td>'
            )
        else:
            line += '<td></td><td class="num">-</td><td class="num">-</td><td class="num">-</td><td class="num">-</td>'
        body.append(line + f'<td class="sub">{cell(row["updated_at"][5:16].replace("T", " "))}</td></tr>')
    body.append("</table>")
    body.append(legend([("work", say("report.active"), ""), ("wait", say("report.waiting"), "")]))
    body.append("</div>")
    body.append("<footer>" + cell(say("board.footer")) + "</footer>")
    return page(say("board.title"), body, refresh)
