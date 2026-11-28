"""Check: does a Copilot extension load on this computer, and how long does a hook take in it compared with a hook that starts a process?

    python <this file>            run it in the harness folder while the board is open

Standard library only (Python 3.9+), plus the harness's own `core.ahp` (the board's link to the agent host).
What it does, in order:
  1. Makes a new empty folder in TEMP (`harness-ext-probe`) with two probes for PreToolUse and nothing else (no harness, no gate):
       - a command hook (`.github/hooks/probe.json`): starts `python -S probe_hook.py` for each call, the same way the harness hook starts;
       - an extension (`.github/extensions/harness-probe/extension.mjs`): one Node process per chat, a hook is a function call in it.
     Both only write the time to a log. The command hook refuses a command with CMD-PROBE-DENY in it, the extension one with EXT-PROBE-DENY.
     For each call the extension also opens one connection to the board's judging service and does its handshake (no call is judged), to time that path.
  2. Connects to the agent host the board started, notes its `canvasesEnabled` value, sets it to true (the host loads extensions only then), and trusts the probe folder.
  3. Makes one chat in the probe folder (Copilot Fusion, Allow all) and asks it to run seven echo commands one by one. One short turn: a few credits.
  4. Waits until the chat is idle (at most 6 minutes), puts `canvasesEnabled` back as it was, and prints the result.
It does not touch the harness folder, its tasks, its hooks or its gate. It prints times, counts and the probe words; no paths but the probe folder (home as ~), no texts of other chats.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path.cwd()
if not (ROOT / ".harness" / "engine" / "core" / "ahp.py").is_file():
    sys.exit("Run this in the harness folder (the one with .harness in it).")
sys.path.insert(0, str(ROOT / ".harness" / "engine"))
from core import ahp, agenthost  # noqa: E402

HOME = str(Path.home())
BASE = Path(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp") / "harness-ext-probe"
RUN = uuid.uuid4().hex[:6]  # this run's mark: in every command and in the folder name, so a chat of an earlier run is never counted
PROBE = BASE / ("run-" + RUN)
LOGS = PROBE / "logs"
WAIT = 360
NAMES = ["probe-1", "probe-2", "EXT-PROBE-DENY", "probe-3", "CMD-PROBE-DENY", "probe-4", "probe-5"]
WORDS = [name + "-" + RUN for name in NAMES]


def short(path):
    text = str(path)
    return "~" + text[len(HOME):] if text.startswith(HOME) else text


HOOK = r'''import time
began = time.time()
import json, os, sys
raw = sys.stdin.read()
deny = "CMD-PROBE-DENY" in raw
try:
    data = json.loads(raw)
except ValueError:
    data = {}
call = data.get("tool_use_id") or data.get("toolCallId") or ""
if not call and isinstance(data.get("toolCalls"), list) and data["toolCalls"]:
    call = (data["toolCalls"][0] or {}).get("id") or ""
row = {"mine": "RUN_MARK" in raw, "began": began, "ended": time.time(), "call": call, "session": data.get("session_id") or data.get("sessionId") or "", "keys": sorted(data)[:20], "deny": deny, "python": sys.version.split()[0]}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "cmd.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps(row) + "\n")
print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": "cmd-probe: refused on purpose"} if deny else {}))
'''

EXTENSION = r'''// Probe (pc-tests 2026-11-27): a PreToolUse hook in a long-lived Copilot extension. Logs times; refuses EXT-PROBE-DENY; never judges anything else.
import { joinSession } from "@github/copilot-sdk/extension";
import fs from "node:fs";
import net from "node:net";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CONF = JSON.parse(fs.readFileSync(path.join(HERE, "probe.json"), "utf8"));
const note = (row) => { try { fs.appendFileSync(CONF.log, JSON.stringify({ at: Date.now() / 1000, pid: process.pid, ...row }) + "\n"); } catch {} };

// one connection to the board's judging service and its handshake: ms, or a word why not
function hello() {
    return new Promise((resolve) => {
        let info;
        try { info = JSON.parse(fs.readFileSync(CONF.service, "utf8")); } catch { return resolve("no-service-file"); }
        if (!info || !Number.isInteger(info.port) || typeof info.key !== "string") return resolve("bad-service-file");
        const began = Date.now();
        const nonce = crypto.randomBytes(16).toString("hex");
        const want = crypto.createHmac("sha256", info.key).update(nonce + "hello").digest("hex");
        const sock = net.connect({ host: "127.0.0.1", port: info.port });
        let buffer = "";
        const done = (value) => { clearTimeout(timer); sock.destroy(); resolve(value); };
        const timer = setTimeout(() => done("timeout"), 5000);
        sock.on("error", (error) => done("error:" + (error.code || "?")));
        sock.on("connect", () => sock.write(JSON.stringify({ nonce, v: 2 }) + "\n"));
        sock.on("data", (chunk) => {
            buffer += chunk.toString("utf8");
            const at = buffer.indexOf("\n");
            if (at < 0) return;
            let answer = null;
            try { answer = JSON.parse(buffer.slice(0, at)); } catch {}
            done(answer && answer.hello === want ? Date.now() - began : "bad-hello");
        });
    });
}

note({ event: "load", node: process.version });
const session = await joinSession({
    hooks: {
        onPreToolUse: async (input) => {
            const began = Date.now();
            try {
                const args = JSON.stringify(input.toolArgs || "");
                const deny = args.includes("EXT-PROBE-DENY");
                const shake = await hello();
                note({ event: "pre", call: input.toolCallId, tool: input.toolName, session: input.sessionId, sent: input.timestamp, began: began / 1000, ms: Date.now() - began, hello: shake, deny, mine: args.includes(CONF.run) });
                return deny ? { permissionDecision: "deny", permissionDecisionReason: "ext-probe: refused on purpose" } : undefined;
            } catch (error) {
                note({ event: "error", text: String(error).slice(0, 200) });
                return undefined;
            }
        },
    },
});
note({ event: "joined", session: session && session.sessionId });
'''


def make_probe():
    shutil.rmtree(BASE, ignore_errors=True)  # earlier runs (a file a running chat holds stays)
    ext = PROBE / ".github" / "extensions" / "harness-probe"
    ext.mkdir(parents=True)
    (PROBE / ".github" / "hooks").mkdir(parents=True)
    LOGS.mkdir()
    (ext / "extension.mjs").write_text(EXTENSION, encoding="utf-8")
    (ext / "probe.json").write_text(json.dumps({"run": RUN, "log": str(LOGS / "ext.jsonl"), "service": str(ROOT / ".harness" / "runtime" / "hookserve.json")}), encoding="utf-8")
    (PROBE / "probe_hook.py").write_text(HOOK.replace("RUN_MARK", RUN), encoding="utf-8")
    hook = {"type": "command", "exec": "python", "args": ["-S", "probe_hook.py"], "cwd": ".", "timeout": 120, "timeoutSec": 120}
    (PROBE / ".github" / "hooks" / "probe.json").write_text(json.dumps({"version": 1, "hooks": {"PreToolUse": [hook]}}, indent=1), encoding="utf-8")
    (PROBE / "README.md").write_text("Probe folder of a harness check (pc-tests 2026-11-27). Safe to delete.\n", encoding="utf-8")
    if shutil.which("git"):
        subprocess.run(["git", "init", "-q"], cwd=str(PROBE), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def canvases(link):
    state = link.subscribe(ahp.ROOT_CHANNEL, 20)
    link.unsubscribe(ahp.ROOT_CHANNEL, 20)
    values = (state.get("config") or {}).get("values") if isinstance(state.get("config"), dict) else None
    return (values or {}).get("canvasesEnabled"), state


def set_canvases(link, value):
    link.dispatch(ahp.ROOT_CHANNEL, {"type": "root/configChanged", "config": {"canvasesEnabled": value}})
    time.sleep(1)
    return canvases(link)[0]


def rows(name):
    try:
        with open(LOGS / name, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        return []


def events(session):
    if not session:
        return []
    path = Path(HOME) / ".copilot" / "session-state" / session / "events.jsonl"
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def stamp(value):
    """seconds from an ISO time of the record"""
    from datetime import datetime
    if isinstance(value, (int, float)):
        return value / 1000.0 if value > 1e11 else float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def session_of():
    for row in rows("ext.jsonl") + rows("cmd.jsonl"):
        if row.get("session") and row.get("mine"):
            return row["session"]
    return None


def stats(values):
    v = sorted(x for x in values if isinstance(x, (int, float)))
    if not v:
        return "n 0"
    return "n %d | min %d | p50 %d | max %d" % (len(v), v[0], v[len(v) // 2], v[-1])


def vscode_policy():
    """VS Code's machine or user policy `ChatCanvases` (Windows registry): None when not set."""
    try:
        import winreg
    except ImportError:
        return None
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Policies\Microsoft\VSCode") as key:
                return winreg.QueryValueEx(key, "ChatCanvases")[0]
        except OSError:
            continue
    return None


def policy_lines(since):
    counts = {"prohibited by managed policy": 0, "Extension managed policy is unresolved": 0}
    for path in (Path(HOME) / ".copilot" / "logs").glob("*.log"):
        try:
            if path.stat().st_mtime < since:
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    for key in counts:
                        if key in line:
                            counts[key] += 1
        except OSError:
            continue
    return counts


def main():
    print("== 0. Before ==")
    policy = vscode_policy()
    print("VS Code policy ChatCanvases:", "not set" if policy is None else policy)
    if policy is not None and str(policy).lower() in ("0", "false"):
        sys.exit("The organization turned canvases off for VS Code. Stop here: send this photo back.")
    print("python", sys.version.split()[0], "| probe folder", short(PROBE))
    record = agenthost.record_file(ROOT)
    if not record.is_file():
        sys.exit("No agent host record: open the board first (harness task board), wait until it shows the tasks, then run this again.")
    host = json.loads(record.read_text(encoding="utf-8"))
    token = agenthost.token_file(ROOT).read_text(encoding="utf-8").strip()
    print("agent host version", host.get("version"), "| port", host.get("port"))
    make_probe()

    link = ahp.connect(ahp.Endpoint("tcp", "localhost:%s" % host["port"], host.get("pid"), "", token))
    before = None
    resource = "ahp-session:/" + str(uuid.uuid4())
    began = time.time()
    try:
        before, root_state = canvases(link)
        after = set_canvases(link, True)
        trust = ahp.declare_trust(link, PROBE, 20)
        print("canvasesEnabled before", before, "-> now", after, "| probe folder trusted", trust)
        for _ in range(10):
            if ahp.models_of(root_state):
                break
            time.sleep(2)
            root_state = canvases(link)[1]
        model = next((m for m in ahp.models_of(root_state) if m.get("id") == ahp.FUSION_ID), None)
        link.call("createSession", {"channel": resource, "provider": ahp.LOCAL_PROVIDER, "workingDirectories": [ahp.folder_uri(PROBE)],
                                    "config": {"isolation": "folder", "mode": "interactive", "autoApprove": "autoApprove"}}, timeout=ahp.create_timeout())
        chat = str(link.subscribe(resource, timeout=ahp.create_timeout()).get("defaultChat") or "")
        if not chat:
            sys.exit("The host made no chat.")
        link.subscribe(chat, timeout=60)
        text = ("This is a timing probe. Run these shell commands one at a time, in this order, each in its own tool call, and nothing else. "
                "If a command is refused, do not retry it and go on with the next one. Do not read or change any file. Commands: "
                + "; ".join("echo " + w for w in WORDS) + ". When all are done, answer with one word: done.")
        message = {"text": text, "origin": {"kind": "user"}}
        if model:
            message["model"] = ahp.model_choice(model, ahp.FUSION_STANDARD if ahp.FUSION_STANDARD in ((model.get("thinking") or {}).get("levels") or []) else "")
        link.dispatch(chat, {"type": "chat/turnStarted", "turnId": str(uuid.uuid4()), "startedAt": ahp.utc_stamp(), "message": message})
        print("chat made and asked; model", (message.get("model") or {}).get("id", "the host's default"), "| waiting (at most %d s)" % WAIT)
        state = "no record yet"
        while time.time() - began < WAIT:
            time.sleep(4)
            ev = events(session_of())
            done = [e for e in ev if e.get("type") == "tool.execution_complete"]
            last = ev[-1] if ev else {}
            quiet = time.time() - (stamp(last.get("timestamp")) or time.time())
            state = "%d tool calls done, last event %s" % (len(done), last.get("type"))
            if last.get("type") in ("assistant.turn_end", "session.idle", "session.shutdown") and quiet > 10 and done:
                break
        print("chat state at the end:", state, "| %d s" % (time.time() - began))
    finally:
        link.close()
        try:
            again = ahp.connect(ahp.Endpoint("tcp", "localhost:%s" % host["port"], host.get("pid"), "", token))
            try:
                print("canvasesEnabled put back to", set_canvases(again, bool(before)))
            finally:
                again.close()
        except Exception as error:  # noqa: BLE001
            print("could not put canvasesEnabled back:", type(error).__name__, "- closing and opening the board puts it back")

    ext, cmd = rows("ext.jsonl"), [r for r in rows("cmd.jsonl") if r.get("mine")]
    pres = [r for r in ext if r.get("event") == "pre" and r.get("mine")]
    session = session_of()
    print("")
    print("== 1. Did the extension load? ==")
    loads = [r for r in ext if r.get("event") == "load"]
    print("load", len(loads), "| joined", len([r for r in ext if r.get("event") == "joined"]), "| node", loads[0].get("node") if loads else "-",
          "| errors", len([r for r in ext if r.get("event") == "error"]))
    if loads:
        print("seconds from asking the host to the extension's first line: %.1f" % (loads[0]["at"] - began))
    print("Copilot log lines since the start:", policy_lines(began - 5))
    print("command hook ran", len(cmd), "times | its python", cmd[0].get("python") if cmd else "-", "| payload keys", cmd[0].get("keys") if cmd else "-")

    print("")
    print("== 2. Each tool call (ms) ==")
    ev = events(session) if session else []
    if not ev:
        print("no Copilot record found for the chat (session %s)" % ("found" if session else "unknown"))
    starts = {}
    hooks = {}
    results = {}
    for e in ev:
        data, kind = e.get("data") or {}, e.get("type")
        at = stamp(e.get("timestamp"))
        if kind == "tool.execution_start":
            starts[data.get("toolCallId")] = (at, data.get("toolName"), json.dumps(data.get("arguments") or {}))
        elif kind in ("hook.start", "hook.end") and data.get("hookType") == "preToolUse":
            hooks.setdefault(data.get("hookInvocationId"), {})[kind] = (at, data)
        elif kind == "tool.execution_complete":
            err = ((data.get("error") or {}).get("message") or "") if isinstance(data.get("error"), dict) else ""
            results[data.get("toolCallId")] = "ran" if data.get("success") else ("denied:ext" if "ext-probe" in err else "denied:cmd" if "cmd-probe" in err else "denied" if "Denied" in err else "failed")
    by_call = {}
    for inv in hooks.values():
        start = inv.get("hook.start")
        if not start:
            continue
        calls = [c.get("id") for c in (start[1].get("input") or {}).get("toolCalls") or [] if isinstance(c, dict)]
        end = inv.get("hook.end")
        for call in calls:
            by_call.setdefault(call, []).append((start[0], end[0] if end else None))
    ext_by = {r.get("call"): r for r in pres}
    cmd_by = {r.get("call"): r for r in cmd}
    print("ms from the start of Copilot's preToolUse: cmd> python's first line, cmd< its last line, ext> Copilot calls the extension, ext< the extension answered, end = Copilot's hook end")
    print("%-15s %-5s %5s %6s %6s %6s %6s %6s %6s  %s" % ("word", "tool", "hooks", "cmd>", "cmd<", "ext>", "ext<", "hello", "end", "result"))
    col = {k: [] for k in ("start", "work", "gap", "reach", "inside", "hello", "whole", "ext_only")}
    for call, (at, tool, args) in sorted(starts.items(), key=lambda kv: kv[1][0] or 0):
        if RUN not in args:
            continue
        word = next((n for n, w in zip(NAMES, WORDS) if w in args), "other")
        spans = by_call.get(call, [])
        h0 = min((s for s, _ in spans), default=None)
        h1 = max((e for _, e in spans if e), default=None)
        er, cr = ext_by.get(call), cmd_by.get(call)
        rel = lambda t: int((t - h0) * 1000) if (t is not None and h0) else None  # noqa: E731
        c0, c1 = (rel(cr["began"]), rel(cr["ended"])) if cr else (None, None)
        sent = stamp(er.get("sent")) if er else None
        e0, e1 = (rel(sent), rel(er["began"] + er.get("ms", 0) / 1000.0)) if er else (None, None)
        end = rel(h1)
        shake = er.get("hello") if er else None
        pairs = (("start", c0), ("work", c1 - c0 if None not in (c0, c1) else None), ("gap", e0 - c1 if None not in (e0, c1) else None),
                 ("reach", rel(er["began"]) - e0 if er and e0 is not None else None), ("inside", er.get("ms") if er else None), ("hello", shake), ("whole", end),
                 ("ext_only", end - e0 if None not in (end, e0) else None))
        for key, value in pairs:
            if isinstance(value, int):
                col[key].append(value)
        show = lambda v: "-" if v is None else str(v)  # noqa: E731
        print("%-15s %-5s %5s %6s %6s %6s %6s %6s %6s  %s" % (word, str(tool)[:5], len(spans), show(c0), show(c1), show(e0), show(e1), show(shake), show(end), results.get(call, "?")))
    print("")
    print("== 3. Summary (ms) ==")
    print("Copilot's whole preToolUse (both hooks)        :", stats(col["whole"]))
    print("command hook: until python's first line        :", stats(col["start"]))
    print("command hook: python's own work                :", stats(col["work"]))
    print("command hook ended -> Copilot calls extension  :", stats(col["gap"]))
    print("extension: Copilot's call -> function runs     :", stats(col["reach"]))
    print("extension: inside the function (with handshake):", stats(col["inside"]))
    print("extension: handshake with the board's service  :", stats(col["hello"]))
    print("extension part: Copilot's call -> hook end     :", stats(col["ext_only"]))
    print("")
    print("run", RUN, "| the probe folder stays for a look; delete it when done:", short(BASE))


if __name__ == "__main__":
    main()
