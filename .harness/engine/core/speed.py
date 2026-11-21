"""`harness speed`: where the time of the Copilot agents goes on this computer, and what is slow now.

Five parts, each from its own file, and a one-line verdict from fixed rules (no model):
  - history (`core/speedhist.py`): Copilot's own records of the last days, prompts grouped by how many agents ran at the same time; per group the time of one model
    call (and its first token), one hook, one tool call, and the share of each. A peak of the past is in it: no need to run this at a busy moment for that part.
  - hook start: the time Copilot counts for a hook minus the time the hook's own code ran (its log `ms`, counted after its imports): what starting the process and loading the harness cost here.
  - now (`core/speedhost.py`): starting a Python and a shell process, CPU busy over 2 s, memory, the 5 busiest processes. On Windows by system calls (ctypes), no
    `tasklist` or `wmic`: on a computer where a process takes 1.5 s to start, the measure must not be the load.
  - network (`core/speednet.py`): DNS, TCP to the proxy, CONNECT and the TLS handshake to the Copilot server (only a handshake: nothing is sent).
  - VS Code (`core/speednet.py`): seconds from a VS Code window seen to the board connected, as the board recorded them.

Each run is kept in `.harness/runtime/speed/<time>.json` and the run before is shown next to it, so a quiet run and a busy run compare. Numbers, times and process
names only: no prompt, no code, nothing leaves this computer. A part that fails says so; the others still run.
"""

from __future__ import annotations

import json
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import config, messages, pace
from core.paths import runtime_dir, utc_now

DAYS = 7  # the history read by default
KEEP_RUNS = 30  # runs kept in the folder; older ones are deleted
HOST = "api.githubcopilot.com"  # the server the network part shakes hands with; `speed.host` in the policy `task` changes it
FOLDER = "speed"


def folder(root: Path) -> Path:
    return runtime_dir(root) / FOLDER


def settings(root: Path) -> Dict[str, Any]:
    """`speed` of the policy `task`: `host` (the Copilot server), `days` (the history). Optional; a bad value is the default."""
    own = config.policy_or_empty(root, "task").get("speed")
    own = own if isinstance(own, dict) else {}
    host = own.get("host")
    days = own.get("days")
    return {
        "host": host.strip() if isinstance(host, str) and host.strip() and len(host) < 254 else HOST,
        "days": days if isinstance(days, int) and not isinstance(days, bool) and 0 < days <= 90 else DAYS,
    }


def part(name: str, make: Callable[[], Any]) -> Any:
    """One part of the run; an error is that part's answer, never the run's end."""
    started = time.monotonic()
    try:
        found = make()
    except Exception as error:  # noqa: BLE001 - a part that fails is reported, the others still run
        found = {"error": f"{type(error).__name__}: {error}"[:300]}
    if isinstance(found, dict):
        found.setdefault("took_s", round(time.monotonic() - started, 2))
    return found


def collect(root: Path, days: Optional[int] = None, parts: Optional[Dict[str, Callable[..., Any]]] = None) -> Dict[str, Any]:
    """The whole run. `parts` replaces the readers (tests)."""
    from core import speedhist, speedhost, speednet

    own = settings(root)
    days = days if isinstance(days, int) and days > 0 else own["days"]
    use = {"history": speedhist.collect, "host": speedhost.collect, "network": speednet.collect, "vscode": speednet.vscode_starts}
    use.update(parts or {})
    result: Dict[str, Any] = {"at": utc_now(), "pace": pace.info(root), "days": days}
    result["history"] = part("history", lambda: use["history"](root, days))
    result["host"] = part("host", lambda: use["host"](root))
    result["network"] = part("network", lambda: use["network"](root, own["host"]))
    result["vscode"] = part("vscode", lambda: {"starts": use["vscode"](root)})
    result["verdict"] = verdict(result)
    return result


# --- the verdict ----------------------------------------------------------------------------------------------------------------------------------------------

MIN_CALLS = 20  # a group with fewer calls says nothing
BUSY = ("4+", "2-3", "1")  # the busiest group with enough calls is judged
CPU_BUSY = 85.0  # % of the whole machine
MEMORY_LOW = 0.10  # share of memory still free
START_SLOW_MS = 1000.0  # ms; a quick computer starts a new Python process in well under 0.1 s
NETWORK_SHARE = 0.30  # the handshake against the first token of a model call: above this the network is a large part of the wait
GREW = 1.3  # a median that grew by this much from one agent to the busy group


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value else None


def _median(group: Dict[str, Any], kind: str) -> Optional[float]:
    return _num(((group or {}).get(kind) or {}).get("median_ms"))


def network_ms(network: Dict[str, Any]) -> Optional[float]:
    """The time of one new connection to the Copilot server: the TCP or CONNECT step plus the TLS handshake."""
    parts = [_num((network or {}).get(key)) for key in ("connect_ms", "tls_ms")]
    return sum(parts) if all(value is not None for value in parts) else None  # type: ignore[arg-type]


def verdict(result: Dict[str, Any]) -> Dict[str, Any]:
    """`{key, values, notes: [{key, values}]}`: the largest part of the agents' time by fixed rules, and what is wrong now.

    The history is judged in its busiest group with MIN_CALLS calls or more. The largest share of model, tool and hook time wins:
      - model: the wait is on the server, unless one new connection (CONNECT + TLS) is NETWORK_SHARE or more of a model call's first token: then the network;
      - hook: starting processes (with the hook's own code next to it);
      - tool: the commands and file reads of the agents.
    Notes, each on its own: a median that grew GREW times from one agent to the busy group; CPU at CPU_BUSY % or more; less than MEMORY_LOW of the memory free; a
    new process slower than START_SLOW_MS; a network step that failed.
    """
    history = result.get("history") if isinstance(result.get("history"), dict) else {}
    groups = history.get("groups") if isinstance(history.get("groups"), dict) else {}
    host = result.get("host") if isinstance(result.get("host"), dict) else {}
    network = result.get("network") if isinstance(result.get("network"), dict) else {}
    notes: List[Dict[str, Any]] = []

    busy = next((name for name in BUSY if isinstance(groups.get(name), dict) and (groups[name].get("calls") or 0) >= MIN_CALLS), None)
    if busy is None:
        main = {"key": "speed.verdict.few", "values": {"calls": sum((group or {}).get("calls") or 0 for group in groups.values() if isinstance(group, dict)), "least": MIN_CALLS}}
    else:
        group = groups[busy]
        share = group.get("share") if isinstance(group.get("share"), dict) else {}
        kind = max(("model", "tool", "hook"), key=lambda name: _num(share.get(name)) or 0.0)
        values = {"group": group_text(busy), "share": round((_num(share.get(kind)) or 0.0) * 100), "median": seconds_text(_median(group, kind))}
        if kind == "model":
            first, net = _median(group, "first_token"), network_ms(network)
            if first and net is not None and net >= NETWORK_SHARE * first:
                main = {"key": "speed.verdict.network", "values": dict(values, network=seconds_text(net), first=seconds_text(first))}
            else:
                main = {"key": "speed.verdict.model", "values": values}
        elif kind == "hook":
            start = _num((history.get("hook_start") or {}).get("start_ms"))
            main = {"key": "speed.verdict.hook", "values": dict(values, start=seconds_text(start))}
        else:
            main = {"key": "speed.verdict.tool", "values": values}
        alone = groups.get("1") if isinstance(groups.get("1"), dict) else {}
        if busy != "1" and (alone.get("calls") or 0) >= MIN_CALLS:
            grown = []
            for name in ("model", "hook", "tool"):
                was, now = _median(alone, name), _median(group, name)
                if was and now and now >= GREW * was:
                    grown.append((now / was, name, was, now))
            if grown:
                _ratio, name, was, now = max(grown)
                notes.append({"key": "speed.note.grew", "values": {"what": kind_text(name), "group": group_text(busy), "was": seconds_text(was), "now": seconds_text(now)}})

    busy_pct = _num((host.get("cpu") or {}).get("busy_pct"))
    if busy_pct is not None and busy_pct >= CPU_BUSY:
        notes.append({"key": "speed.note.cpu", "values": {"pct": round(busy_pct)}})
    memory = host.get("memory") or {}
    total, free = _num(memory.get("total_mb")), _num(memory.get("free_mb"))
    if total and free is not None and free < MEMORY_LOW * total:
        notes.append({"key": "speed.note.memory", "values": {"free": gb_text(free), "total": gb_text(total)}})
    start = _num((host.get("process") or {}).get("python_ms"))
    if start is not None and start >= START_SLOW_MS:
        notes.append({"key": "speed.note.start", "values": {"time": seconds_text(start)}})
    if network.get("error"):
        notes.append({"key": "speed.note.network", "values": {"error": str(network["error"])[:200]}})
    main["notes"] = notes
    return main


# --- keeping the runs -----------------------------------------------------------------------------------------------------------------------------------------

def save(root: Path, result: Dict[str, Any]) -> Optional[Path]:
    """Keep the run; KEEP_RUNS at most. A run that cannot be kept is still shown."""
    try:
        where = folder(root)
        where.mkdir(parents=True, exist_ok=True)
        name = result["at"].replace(":", "").replace("-", "")[:15] + ".json"
        path = where / name
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        for old in sorted(where.glob("*.json"))[:-KEEP_RUNS]:
            old.unlink()
        return path
    except (OSError, KeyError, TypeError, ValueError):
        return None


def previous(root: Path) -> Optional[Dict[str, Any]]:
    """The newest kept run, or None."""
    try:
        runs = sorted(folder(root).glob("*.json"))
    except OSError:
        return None
    for path in reversed(runs):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def run(root: Path, days: Optional[int] = None) -> Dict[str, Any]:
    """`harness speed`: collect, put the run before next to it, keep it."""
    before = previous(root)
    result = collect(root, days)
    path = save(root, result)
    result["before"] = before
    result["kept"] = str(path) if path else ""
    return result


# --- the text -------------------------------------------------------------------------------------------------------------------------------------------------

def seconds_text(ms: Optional[float]) -> str:
    """1234.5 ms -> "1.2 s", 45 -> "45 ms", None -> "—"."""
    if ms is None:
        return "—"
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.1f} s"


def gb_text(mb: Optional[float]) -> str:
    return "—" if mb is None else f"{mb / 1024:.1f} GB"


def kind_text(kind: str) -> str:
    return {"model": messages.text("speed.kind.model"), "hook": messages.text("speed.kind.hook"), "tool": messages.text("speed.kind.tool")}.get(kind, kind)


def group_text(name: str) -> str:
    """How many agents a group is, in a sentence: "one agent alone", "2-3 agents at once", "4 or more agents at once"."""
    return {"1": messages.text("speed.at.one"), "2-3": messages.text("speed.at.few"), "4+": messages.text("speed.at.many")}.get(name, name)


def width(text: str) -> int:
    """Columns on a terminal: a Chinese character takes two."""
    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)


def pad(text: str, columns: int) -> str:
    return text + " " * max(0, columns - width(text))


def said(entry: Dict[str, Any]) -> str:
    return messages.text(entry.get("key", ""), **(entry.get("values") or {}))


def was_text(now: Any, before: Any, show: Callable[[Optional[float]], str]) -> str:
    """The value, and the one of the run before when there is one and it differs."""
    value, old = _num(now), _num(before)
    shown = show(value)
    if old is None or before is None or show(old) == shown:
        return shown
    return shown + messages.text("speed.before", value=show(old))


def _get(data: Any, *path: str) -> Any:
    for key in path:
        data = data.get(key) if isinstance(data, dict) else None
    return data


def render(result: Dict[str, Any]) -> str:
    """The text a person reads: the verdict first, then history, now, network, VS Code, and where the run was kept."""
    before = result.get("before") if isinstance(result.get("before"), dict) else {}
    lines = [messages.text("speed.title", at=str(result.get("at", ""))[:16].replace("T", " "), factor=_get(result, "pace", "factor") or 1)]
    verdict_of = result.get("verdict") or {}
    lines.append(messages.text("speed.verdict", said=said(verdict_of)))
    lines.extend("  · " + said(note) for note in verdict_of.get("notes") or [])

    history = result.get("history") or {}
    lines.append("")
    if history.get("error"):
        lines.append(messages.text("speed.history.error", error=history["error"]))
    else:
        lines.append(messages.text("speed.history", days=result.get("days", DAYS), sessions=history.get("sessions", 0), prompts=history.get("prompts", 0)))
        groups = history.get("groups") or {}
        names = ["1", "2-3", "4+"]
        heads = [messages.text("speed.group.one"), messages.text("speed.group.few"), messages.text("speed.group.many")]
        rows = [
            (messages.text("speed.row.calls"), [str(_get(groups, name, "calls") or 0) for name in names]),
            (messages.text("speed.row.model"), [seconds_text(_num(_get(groups, name, "model", "median_ms"))) for name in names]),
            (messages.text("speed.row.first"), [seconds_text(_num(_get(groups, name, "first_token", "median_ms"))) for name in names]),
            (messages.text("speed.row.hook"), [seconds_text(_num(_get(groups, name, "hook", "median_ms"))) for name in names]),
            (messages.text("speed.row.tool"), [seconds_text(_num(_get(groups, name, "tool", "median_ms"))) for name in names]),
            (messages.text("speed.row.share"), ["/".join(str(round((_num(_get(groups, name, "share", kind)) or 0) * 100)) for kind in ("model", "tool", "hook")) + " %" if _get(groups, name, "share") else "—" for name in names]),
        ]
        first = max(width(label) for label, _cells in rows) + 2
        lines.append("  " + pad("", first) + "".join(pad(head, 14) for head in heads))
        for label, cells in rows:
            lines.append("  " + pad(label, first) + "".join(pad(cell, 14) for cell in cells))
        start = history.get("hook_start") or {}
        if _num(start.get("start_ms")) is not None:
            lines.append("  " + messages.text("speed.hookstart", copilot=seconds_text(_num(start.get("copilot_ms"))), own=seconds_text(_num(start.get("own_ms"))), start=seconds_text(_num(start.get("start_ms")))))

    host = result.get("host") or {}
    lines.append("")
    lines.append(messages.text("speed.now"))
    if host.get("error"):
        lines.append("  " + messages.text("speed.part.error", error=host["error"]))
    else:
        lines.append("  " + messages.text("speed.now.start", python=was_text(_get(host, "process", "python_ms"), _get(before, "host", "process", "python_ms"), seconds_text),
                                          shell=was_text(_get(host, "process", "shell_ms"), _get(before, "host", "process", "shell_ms"), seconds_text)))
        pct = lambda value: "—" if value is None else f"{value:.0f} %"  # noqa: E731
        lines.append("  " + messages.text("speed.now.cpu", busy=was_text(_get(host, "cpu", "busy_pct"), _get(before, "host", "cpu", "busy_pct"), pct), cores=_get(host, "cpu", "cores") or "—"))
        lines.append("  " + messages.text("speed.now.memory", used=gb_text(_num(_get(host, "memory", "used_mb"))), total=gb_text(_num(_get(host, "memory", "total_mb"))),
                                          free=was_text(_get(host, "memory", "free_mb"), _get(before, "host", "memory", "free_mb"), gb_text)))
        top = [item for item in host.get("top") or [] if isinstance(item, dict)]
        if top:
            lines.append("  " + messages.text("speed.now.top", list=" · ".join(f"{item.get('name', '?')} {_num(item.get('cpu_pct')) or 0:.0f} %" for item in top[:5])))

    network = result.get("network") or {}
    lines.append("")
    proxy = network.get("proxy") or ""
    lines.append(messages.text("speed.network.proxy" if proxy else "speed.network.direct", host=network.get("host", ""), proxy=proxy))
    lines.append("  " + messages.text("speed.network.steps.proxy" if proxy else "speed.network.steps", dns=seconds_text(_num(network.get("dns_ms"))), proxy=seconds_text(_num(network.get("proxy_ms"))),
                                      connect=was_text(network.get("connect_ms"), _get(before, "network", "connect_ms"), seconds_text),
                                      tls=was_text(network.get("tls_ms"), _get(before, "network", "tls_ms"), seconds_text)))
    if network.get("cert"):
        lines.append("  " + messages.text("speed.network.cert"))
    if network.get("error"):
        lines.append("  " + messages.text("speed.part.error", error=network["error"]))

    starts = [item for item in _get(result, "vscode", "starts") or [] if isinstance(item, dict) and _num(item.get("seconds")) is not None]
    lines.append("")
    lines.append(messages.text("speed.vscode", list=messages.joined([f"{_num(item['seconds']):.0f} s" for item in starts[:5]])) if starts else messages.text("speed.vscode.none"))
    if result.get("kept"):
        lines.append(messages.text("speed.kept", path=result["kept"]))
    return "\n".join(lines)
