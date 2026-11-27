"""Numbers only, read-only: what a turn costs after a wait for a person, from Copilot's own session records.

It reads ~/.copilot/session-state/*/events.jsonl and prints counts, seconds, token sizes and credits.
It prints no file name, no path, no session id, no tool name, no model id and no text of any conversation.
(It looks at the first words of a message only to tell which fixed message of the board it is.)
It calls no model, uses no network and writes no file. Python 3.9 or newer, standard library only.

Run:  python 2026-11-26-approval-cost.py            the last 7 days
      python 2026-11-26-approval-cost.py --days 3   another window
      python 2026-11-26-approval-cost.py --chat 2   part 9 shows the chat with the 2nd most approvals
"""
import collections
import glob
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime

NANO = 1e9
TTL = 300          # seconds a Claude cache lives on Copilot (the records say so themselves, part 10)
WARM = 240         # a gap under this is surely inside the cache lifetime

KINDS = [  # the fixed messages the board or a hook sends, by their first words (English and Chinese)
    ("approved", re.compile(r"^(Approved: |已批准：)")),
    ("opened", re.compile(r"^(I opened .* for this task|我已为这个任务打开)")),
    ("stop-hook", re.compile(r"^(Independent checks are on for task|任务 .* 开启了独立检查)")),
    ("autorun", re.compile(r"^(Autorun is on|Go on with the next open step|Every step is )")),
    ("go-on", re.compile(r"(Go on\.|继续。)\s*$")),
]


def arg(name, default):
    if name in sys.argv:
        try:
            return int(sys.argv[sys.argv.index(name) + 1])
        except Exception:
            pass
    return default


def ts(text):
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def q(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))] if values else 0


def family(model):
    model = str(model or "").lower()
    for key in ("claude-opus", "claude-sonnet", "claude-haiku", "claude", "gpt", "gemini"):
        if key in model:
            return key
    return "other"


def credits(use):
    total = 0.0
    for part in (use.get("copilotUsage") or {}).get("tokenDetails") or []:
        try:
            total += part["tokenCount"] * part["costPerBatch"] / part["batchSize"]
        except Exception:
            pass
    return total / NANO


def kind_of(data):
    first = str(data.get("content") or "").strip().split("\n")[0][:400]
    for name, rule in KINDS:
        if rule.search(first):
            return name
    return "queued" if data.get("delivery") == "queued" else "other"


def cold(call):
    return call["in"] > 20000 and call["read"] < 0.5 * call["in"]


def k(number):
    return "%dk" % round(number / 1000.0) if number >= 1000 else str(int(number))


def read_chat(path, since):
    """One chat: its turns (a user message of the main agent up to the next one)."""
    turns = []
    cur = None
    last = None            # the previous model call of the main agent
    change = None          # the last model_change since the previous message
    texts = {}
    waits = [0, 0]         # harness wait --approval calls, other harness wait calls
    blocks = 0             # stop hooks that said "block"
    prices = {}
    running = {}           # tool call id -> (start, kind): wait-approval, wait-run, sub-agent, question, other
    finished = []          # (seconds, kind) of the tool calls that ended since the previous model call
    try:
        handle = open(path, errors="replace")
    except OSError:
        return [], waits, blocks, prices
    for line in handle:
        head = line[:240]
        if '"session.model_change"' in head:
            try:
                change = json.loads(line).get("data") or {}
            except Exception:
                pass
            continue
        if '"hook.end"' in head:
            if '"agentStop"' in line[:600] and '"block"' in line[:900]:
                blocks += 1
            continue
        if '"tool.execution_start"' in head:
            if cur is not None:
                cur["tools"] += 1
            what = "other"
            if "harness wait" in line or "harness.py wait" in line or "launch.py wait" in line:
                waits[0 if "--approval" in line else 1] += 1
                what = "wait-approval" if "--approval" in line else "wait-run"
            elif '"toolName":"task"' in line[:400]:
                what = "sub-agent"
            elif '"toolName":"ask_user"' in line[:400]:
                what = "question"
            try:
                started = json.loads(line)
                running[(started.get("data") or {}).get("toolCallId")] = (ts(started.get("timestamp")), what)
            except Exception:
                pass
            continue
        if '"tool.execution_complete"' in head:
            try:
                ended = json.loads(line)
            except Exception:
                continue
            begun = running.pop((ended.get("data") or {}).get("toolCallId"), None)
            if begun and begun[0] and ts(ended.get("timestamp")):
                finished.append((ts(ended.get("timestamp")) - begun[0], begun[1]))
            continue
        if '"user.message"' in head:
            try:
                record = json.loads(line)
            except Exception:
                continue
            data = record.get("data") or {}
            if record.get("type") != "user.message" or record.get("agentId") or data.get("agentId") or str(data.get("source") or "").startswith("agent-"):
                continue
            at = ts(record.get("timestamp"))
            if cur:
                cur["until"] = at
                turns.append(cur)
            digest = hashlib.sha1(str(data.get("content") or "").encode("utf-8", "replace")).hexdigest()
            again = None
            if digest in texts and at and at - texts[digest]["at"] < 600 and len(str(data.get("content") or "")) > 20:
                again = texts[digest]
            cur = {"at": at, "kind": kind_of(data), "delivery": str(data.get("delivery") or "-"), "gap": (at - last["at"]) if (at and last) else None,
                   "prev": last, "calls": [], "tools": 0, "sub": 0.0, "change": change, "again": again, "until": None, "wait_gap": 0.0}
            texts[digest] = cur
            change = None
            continue
        if cur is None or '"session.usage_record"' not in head:
            continue
        try:
            record = json.loads(line)
        except Exception:
            continue
        data = record.get("data") or {}
        use = data.get("usage") or {}
        at = ts(record.get("timestamp"))
        if at is None:
            continue
        spent = credits(use)
        main = use.get("interactionType") in (None, "", "conversation-agent") and not (record.get("agentId") or data.get("agentId") or data.get("parentToolCallId"))
        if not main:
            cur["sub"] += spent
            continue
        call = {"at": at, "in": use.get("inputTokens") or 0, "read": use.get("cacheReadTokens") or 0, "write": use.get("cacheWriteTokens") or 0, "aiu": spent,
                "fam": family(use.get("model")), "model": str(use.get("model") or ""), "offered": use.get("availableToolCount") or 0, "tooltok": use.get("toolTokenCount") or 0,
                "effort": str(use.get("reasoningEffort")), "limit": use.get("maxPromptTokens") or 0, "ttl": use.get("cacheTtlSeconds"), "out": use.get("outputTokens") or 0}
        call["gap"] = (at - last["at"]) if last else None
        call["first"] = not cur["calls"]
        call["during"] = max(finished) if finished else (0.0, "none")   # the longest tool call since the previous model call
        finished = []
        for part in (use.get("copilotUsage") or {}).get("tokenDetails") or []:
            try:
                prices.setdefault(call["fam"], {})[part["tokenType"]] = round(part["costPerBatch"] / part["batchSize"] * 1e6 / NANO, 1)
            except Exception:
                pass
        cur["calls"].append(call)
        last = call
    if cur:
        turns.append(cur)
    return [t for t in turns if t["calls"] and t["at"] and t["at"] >= since], waits, blocks, prices


def aiu(turn):
    return sum(call["aiu"] for call in turn["calls"])


def line(name, turns):
    if not turns:
        print("   %-12s n 0" % name)
        return
    first = [t["calls"][0] for t in turns]
    whole = [aiu(t) for t in turns]
    print("   %-12s n %3d cold %3d | 1st: ctx %5s w %5s cr p50 %5.1f avg %5.1f sum %5.0f | turn: calls %2d cr p50 %5.1f avg %5.1f sum %5.0f" % (
        name, len(turns), sum(1 for c in first if cold(c)), k(q([c["in"] for c in first], .5)), k(q([c["write"] for c in first], .5)), q([c["aiu"] for c in first], .5),
        sum(c["aiu"] for c in first) / len(first), sum(c["aiu"] for c in first), q([len(t["calls"]) for t in turns], .5), q(whole, .5), sum(whole) / len(whole), sum(whole)))


def changed(turn):
    """What a model_change before the message changed: - none, = same model and effort, M model, E effort, T tier."""
    change = turn["change"]
    if not change:
        return "-"
    marks = ""
    if change.get("previousModel") and change.get("previousModel") != change.get("newModel"):
        marks += "M"
    if change.get("previousReasoningEffort") != change.get("reasoningEffort") and (change.get("previousReasoningEffort") or change.get("reasoningEffort")):
        marks += "E"
    if change.get("contextTier") not in (None, "default"):
        marks += "T"
    return (marks or "=") + str(change.get("source") or "?")[:3]


def differs(turn):
    """What differs between the first call of the turn and the call before it: model, tools offered, tool tokens, effort, window."""
    before, now = turn["prev"], turn["calls"][0]
    if not before:
        return "-"
    out = []
    if before["model"] != now["model"]:
        out.append("model")
    if before["offered"] != now["offered"]:
        out.append("tools %d>%d" % (before["offered"], now["offered"]))
    if abs(before["tooltok"] - now["tooltok"]) > 50:
        out.append("tooltok %s>%s" % (k(before["tooltok"]), k(now["tooltok"])))
    if before["effort"] != now["effort"]:
        out.append("effort")
    if before["limit"] != now["limit"]:
        out.append("window %s>%s" % (k(before["limit"]), k(now["limit"])))
    if now["in"] < 0.7 * before["in"]:
        out.append("context shrank %s>%s" % (k(before["in"]), k(now["in"])))
    return ", ".join(out) or "same"


LEGEND = ("   row: no. day time kind | gap: seconds since the chat's previous model call, delivery, chg | first call: context, r read from cache, w written, credits |\n"
          "        turn: c model calls, t tool calls, credits, s sub-agents | ig longest gap inside the turn (s), ci calls inside with no cache and their credits | differs from the call before")
GROUPS = "   columns: n turns, cold = first call met no cache | 1st = the first call: context p50, written p50, credits | turn = the whole turn: model calls p50, credits"


def row(number, turn, day0):
    first = turn["calls"][0]
    when = datetime.fromtimestamp(turn["at"])
    gap = "    -" if turn["gap"] is None else "%5d" % turn["gap"]
    inside = max([c["gap"] or 0 for c in turn["calls"][1:]] or [0])
    cold_in = sum(1 for c in turn["calls"][1:] if cold(c))
    cold_in_aiu = sum(c["aiu"] for c in turn["calls"][1:] if cold(c))
    return "   %3d d%-2d %s %-9s| gap %s %-5s %-5s| %5s r%-5s w%-5s %6.1f %s | c%-3d t%-3d %6.1f s%-5.1f| ig%-4d ci%d %5.1f | %s" % (
        number, int((turn["at"] - day0) // 86400), when.strftime("%H:%M:%S"), turn["kind"], gap, turn["delivery"][:5], changed(turn), k(first["in"]), k(first["read"]), k(first["write"]),
        first["aiu"], "COLD" if cold(first) else "warm", len(turn["calls"]), turn["tools"], aiu(turn), turn["sub"], inside, cold_in, cold_in_aiu, differs(turn))


def main():
    days = arg("--days", 7)
    pick = arg("--chat", 1)
    since = time.time() - days * 86400
    chats = []
    waits = [0, 0]
    blocks = 0
    prices = {}
    started = time.time()
    paths = glob.glob(os.path.join(os.path.expanduser("~"), ".copilot", "session-state", "*", "events.jsonl"))
    for path in paths:
        try:
            if os.path.getmtime(path) < since:
                continue
        except OSError:
            continue
        turns, w, b, p = read_chat(path, since)
        waits[0] += w[0]
        waits[1] += w[1]
        blocks += b
        for fam, table in p.items():
            prices.setdefault(fam, {}).update(table)
        if turns:
            chats.append(turns)
    everything = [t for turns in chats for t in turns]
    claude = [t for t in everything if t["calls"][0]["fam"].startswith("claude")]
    if not claude:
        print("no priced Claude usage records found in the last %d days (%d session files)" % (days, len(paths)))
        return
    day0 = min(t["at"] for t in everything)
    day0 -= day0 % 86400
    total = sum(aiu(t) for t in claude)
    print("1. last %d days: chats %d, turns %d (Claude %d), credits main agent %.0f, sub-agents %.0f; by model family: %s; read in %.0f s" % (
        days, len(chats), len(everything), len(claude), total, sum(t["sub"] for t in claude),
        dict(collections.Counter(t["calls"][0]["fam"] for t in everything)), time.time() - started))

    later = [t for t in claude if t["gap"] is not None and t["prev"] and t["prev"]["model"] == t["calls"][0]["model"]]
    print("\n2. a turn after the first of its chat, by the time since the chat's previous model call (same model)")
    print(GROUPS)
    for name, low, high in (("< 1 min", 0, 60), ("1-4 min", 60, 240), ("4-5 min", 240, 300), ("5-6 min", 300, 360), ("6-30 min", 360, 1800), ("30 min-4 h", 1800, 14400), ("4-24 h", 14400, 86400), ("> 24 h", 86400, 1e12)):
        line(name, [t for t in later if low <= t["gap"] < high])
    colds = [t for t in later if cold(t["calls"][0])]
    print("   first calls that met no cache: %d of %d turns; their credits %.0f = %.0f%% of all credits of these turns (%.0f)" % (
        len(colds), len(later), sum(t["calls"][0]["aiu"] for t in colds), 100 * sum(t["calls"][0]["aiu"] for t in colds) / max(sum(aiu(t) for t in later), 1e-9), sum(aiu(t) for t in later)))

    print("\n3. by the message that started the turn (approved = the board after an approval; stop-hook = a blocked stop; go-on, autorun = the board's wake)")
    for name in ("approved", "opened", "stop-hook", "go-on", "autorun", "queued", "other"):
        line(name, [t for t in claude if t["kind"] == name])

    print("\n4. how late the approval came: 'approved' turns by the time since the chat's previous model call")
    for name, low, high in (("< 1 min", 0, 60), ("1-5 min", 60, 300), ("5-10 min", 300, 600), ("10-30 min", 600, 1800), ("30 min-2 h", 1800, 7200), ("> 2 h", 7200, 1e12)):
        line(name, [t for t in claude if t["kind"] == "approved" and t["gap"] is not None and low <= t["gap"] < high])

    odd = [t for t in later if t["gap"] < WARM and cold(t["calls"][0])]
    print("\n5. inside the cache lifetime (gap < %d s) and still no cache on the first call: %d of %d" % (WARM, len(odd), sum(1 for t in later if t["gap"] < WARM)))
    print("   chg: - no model_change before the message, = same model and effort, M model, E effort, T tier; then who (sdk, age = agent, use = user)")
    print(LEGEND)
    for number, turn in enumerate(sorted(odd, key=lambda t: -t["calls"][0]["aiu"])[:15], 1):
        print(row(number, turn, day0))

    twice = [t for t in claude if t["again"] is not None and t["again"]["calls"]]
    print("\n6. the same text sent twice within 10 minutes in one chat: %d (rows in pairs: first send, second send)" % len(twice))
    for number, turn in enumerate(sorted(twice, key=lambda t: -aiu(t))[:8], 1):
        before = turn["again"]
        print("   pair %d: %d s apart; the first turn had %s when the second came" % (number, turn["at"] - before["at"], "ended" if turn["delivery"] == "idle" else "not ended (%s)" % turn["delivery"]))
        print(row(1, before, day0))
        print(row(2, turn, day0))

    inside = [c for t in claude for c in t["calls"][1:] if (c["gap"] or 0) > TTL]
    print("\n7. waiting inside a turn: `harness wait --approval` calls %d, other `harness wait` calls %d; model calls that came more than %d s after the call before, inside one turn: %d, of them no cache %d, credits of those %.0f" % (
        waits[0], waits[1], TTL, len(inside), sum(1 for c in inside if cold(c)), sum(c["aiu"] for c in inside if cold(c))))

    by_kind = collections.defaultdict(lambda: [0, 0, 0.0])
    for c in inside:
        entry = by_kind[c["during"][1]]
        entry[0] += 1
        entry[1] += 1 if cold(c) else 0
        entry[2] += c["aiu"]
    print("   by what ran in the gap (the longest tool call): kind -> calls, no cache, credits: %s" % {name: (v[0], v[1], round(v[2], 1)) for name, v in sorted(by_kind.items(), key=lambda item: -item[1][2])})
    print("   the dearest ones: seconds since the call before | the longest tool call in between: seconds, kind | context, r read, w written, credits")
    for c in sorted(inside, key=lambda c: -c["aiu"])[:12]:
        print("      gap %5d s | tool %5d s %-13s | %5s r%-5s w%-5s %6.1f %s" % (c["gap"], c["during"][0], c["during"][1], k(c["in"]), k(c["read"]), k(c["write"]), c["aiu"], "COLD" if cold(c) else "warm"))

    stops = sorted([t for t in claude if t["kind"] == "stop-hook"], key=lambda t: -aiu(t))
    print("\n8. stop hooks that said block (any reason): %d; turns started by the independent-check message: %d, credits p50 %.1f p90 %.1f max %.1f sum %.0f; the three dearest:" % (
        blocks, len(stops), q([aiu(t) for t in stops], .5), q([aiu(t) for t in stops], .9), max([aiu(t) for t in stops] or [0]), sum(aiu(t) for t in stops)))
    for number, turn in enumerate(stops[:3], 1):
        print(row(number, turn, day0))

    ranked = sorted(chats, key=lambda turns: (-sum(1 for t in turns if t["kind"] == "approved"), -sum(aiu(t) for t in turns)))
    if ranked and pick <= len(ranked):
        chosen = ranked[pick - 1]
        print("\n9. every turn of the chat with the %s most approvals (%d turns, %d approvals, credits %.0f + sub-agents %.0f, context window %s)" % (
            {1: "", 2: "2nd", 3: "3rd"}.get(pick, "%dth" % pick), len(chosen), sum(1 for t in chosen if t["kind"] == "approved"), sum(aiu(t) for t in chosen), sum(t["sub"] for t in chosen), k(chosen[-1]["calls"][-1]["limit"])))
        for number, turn in enumerate(chosen[:70], 1):
            print(row(number, turn, day0))
        if len(chosen) > 70:
            print("   ... %d more turns not shown" % (len(chosen) - 70))

    print("\n10. prices seen, credits per 1M tokens, by model family: %s" % {fam: table for fam, table in sorted(prices.items()) if fam.startswith("claude")})
    print("    cache lifetime in the records (family, seconds): %s" % dict(collections.Counter((c["fam"], c["ttl"]) for t in claude for c in t["calls"]).most_common(4)))
    print("    thinking effort of main-agent calls: %s" % dict(collections.Counter(c["effort"] for t in claude for c in t["calls"]).most_common(5)))


if __name__ == "__main__":
    main()
