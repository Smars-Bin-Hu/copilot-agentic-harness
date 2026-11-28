"""Work-PC check (2026-11-28): with a chat NOT in Allow all, is a Copilot extension's `allow` the approval, and what waits without it?

    python 2026-11-28-default-lock.py [V1,V4,...]      in the harness folder, with the board open

Each variant is one new chat in a new probe folder in TEMP (Copilot Fusion, one turn, a few credits), on the board's own agent host:
  V1  default permission, extension on : mkdir / create file / read outside, once allowed by the extension and once with no answer
  V4  default permission, no extension : read README, mkdir, create file, read outside
  V5  Allow all, extension on          : the extension exits after the first call; two mkdir after it
  V6  default permission, extension on : the same, not Allow all
  V7  default permission, no extension : read-only shell commands (also of a file outside the folder), a redirect, python -c
  V8  default permission, extension on : three mkdir in one response (two allowed, one with no answer)
The extension answers by a word in the call: X-ALLOW allow, X-DIE no answer and then its process exits; anything else no answer.
The script answers the extension's own load question with "allow once" and refuses every other call that waits for a person.
It does not touch the harness folder, its tasks, hooks or gate. canvasesEnabled is put back at the end.
Prints calls, what was asked and what ran; the home folder shows as ~, the probe folders as <probe> and <outside>."""
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / ".harness" / "engine"))
try:
    from core import ahp, agenthost  # noqa: E402
except ImportError:
    sys.exit("Run this in the harness folder (the one with .harness in it).")

HOME = str(Path.home())
RUN = uuid.uuid4().hex[:6]
BASE = Path(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp") / "harness-lock-probe" / RUN
OUTSIDE = BASE / "outside" / "note.txt"
OUT_ALLOW = BASE / "outside" / "X-ALLOW-note.txt"
PY = "python" if os.name == "nt" else "python3"

EXTENSION = r'''import { joinSession } from "@github/copilot-sdk/extension";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const CONF = JSON.parse(fs.readFileSync(path.join(HERE, "probe.json"), "utf8"));
const note = (row) => { try { fs.appendFileSync(CONF.log, JSON.stringify({ at: Date.now() / 1000, pid: process.pid, ...row }) + "\n"); } catch {} };
note({ event: "load" });
await joinSession({
    hooks: {
        onPreToolUse: async (input) => {
            const args = JSON.stringify(input.toolArgs || "");
            const answer = args.includes("X-ALLOW") ? "allow" : args.includes("X-DIE") ? "die" : "none";
            note({ event: "pre", tool: input.toolName, answer });
            if (answer === "die") { setTimeout(() => { note({ event: "exit" }); process.exit(3); }, 400); return undefined; }
            if (answer === "allow") return { permissionDecision: "allow", permissionDecisionReason: "lock-probe: allowed by the extension" };
            return undefined;
        },
    },
});
note({ event: "joined" });
'''

SHELL = "Run this shell command in one tool call: `%s`."
MAKE = "Create the file %s with the one line `x`, with your file create or edit tool (not a shell command)."
VIEW = "Read the file %s with your file view tool (not a shell command)."
PAR = ("In ONE response, make these three shell tool calls at the same time (in parallel, not one after the other): `mkdir X-ALLOW-par1`, `mkdir X-ALLOW-par2`, `mkdir plain-par3`.")
VARIANTS = {
    "V1": ("default", True, [SHELL % "mkdir X-ALLOW-dir", SHELL % "mkdir plain-dir", MAKE % "X-ALLOW-file.txt", MAKE % "plain-file.txt", VIEW % OUT_ALLOW, VIEW % OUTSIDE]),
    "V4": ("default", False, [VIEW % "README.md", SHELL % "mkdir plain-dir", MAKE % "plain-file.txt", VIEW % OUTSIDE]),
    "V5": ("autoApprove", True, [SHELL % "echo X-DIE", SHELL % "mkdir after1", SHELL % "mkdir after2"]),
    "V6": ("default", True, [SHELL % "echo X-DIE", SHELL % "mkdir X-ALLOW-after", SHELL % "mkdir plain-after"]),
    "V7": ("default", False, [SHELL % ("cat %s" % OUTSIDE), SHELL % ("ls %s" % OUTSIDE.parent), SHELL % "cat README.md", SHELL % "echo x > plain-redirect.txt",
                              SHELL % ("%s -c \"print('plain')\"" % PY), SHELL % "git status --short"]),
    "V8": ("default", True, [PAR]),
}
MADE = ["X-ALLOW-dir", "plain-dir", "X-ALLOW-file.txt", "plain-file.txt", "after1", "after2", "X-ALLOW-after", "plain-after", "plain-redirect.txt", "X-ALLOW-par1", "X-ALLOW-par2", "plain-par3"]


def short(text):
    text = str(text)
    pairs = []
    for base in dict.fromkeys([str(BASE), os.path.realpath(str(BASE))]):
        pairs += [(os.path.join(base, "outside"), "<outside>"), (base, "<probe>")]
    pairs.sort(key=lambda pair: -len(pair[0]))
    pairs.append((HOME, "~"))
    for long, name in pairs:
        for form in (long, long.replace("\\", "\\\\"), long.replace("\\", "/")):
            text = text.replace(form, name)
            low = text.lower().find(form.lower())
            while low >= 0:  # Windows paths come back in other cases
                text = text[:low] + name + text[low + len(form):]
                low = text.lower().find(form.lower())
    return text


def stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def record(mark):
    """The Copilot record of the chat whose user message has the mark."""
    root = Path(HOME) / ".copilot" / "session-state"
    for folder in sorted(root.iterdir(), key=lambda p: -p.stat().st_mtime)[:15]:
        try:
            text = (folder / "events.jsonl").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if mark in text:
            out = []
            for line in text.splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
            return out
    return []


def vscode_policy():
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


def canvases(link, value=None):
    if value is not None:
        link.dispatch(ahp.ROOT_CHANNEL, {"type": "root/configChanged", "config": {"canvasesEnabled": value}})
        time.sleep(1)
    state = link.subscribe(ahp.ROOT_CHANNEL, 20)
    link.unsubscribe(ahp.ROOT_CHANNEL, 20)
    return ((state.get("config") or {}).get("values") or {}).get("canvasesEnabled"), state


def connect():
    host = json.loads(agenthost.record_file(ROOT).read_text(encoding="utf-8"))
    token = agenthost.token_file(ROOT).read_text(encoding="utf-8").strip()
    link = ahp.connect(ahp.Endpoint("tcp", "localhost:%s" % host["port"], host.get("pid"), "", token))
    link.start_reader()
    return host, link


def one(link, name, model):
    permission, extension, steps = VARIANTS[name]
    probe = BASE / name
    log = probe / "logs" / "ext.jsonl"
    log.parent.mkdir(parents=True)
    if extension:
        ext = probe / ".github" / "extensions" / "lock-probe"
        ext.mkdir(parents=True)
        (ext / "extension.mjs").write_text(EXTENSION, encoding="utf-8")
        (ext / "probe.json").write_text(json.dumps({"log": str(log)}), encoding="utf-8")
    (probe / "README.md").write_text("Probe folder. Safe to delete.\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(probe))
    canvases(link, extension)
    trusted = ahp.declare_trust(link, probe, 20)
    mark = "%s-%s" % (RUN, name)
    resource = "ahp-session:/" + str(uuid.uuid4())
    began = time.time()
    link.call("createSession", {"channel": resource, "provider": ahp.LOCAL_PROVIDER, "workingDirectories": [ahp.folder_uri(probe)],
                                "config": {"isolation": "folder", "mode": "interactive", "autoApprove": permission}}, timeout=60)
    chat = str(link.subscribe(resource, timeout=60).get("defaultChat") or "")
    link.subscribe(chat, timeout=60)
    text = ("This is a permission probe (%s). Do these steps in order, one tool call each unless a step says otherwise, and nothing else. If a step is refused, do not retry it "
            "and do not work around it: go on to the next step. Steps: %s When all are done, answer with one word: done."
            % (mark, " ".join("%d) %s" % (i + 1, s) for i, s in enumerate(steps))))
    message = {"text": text, "origin": {"kind": "user"}}
    if model:
        message["model"] = ahp.model_choice(model, ahp.FUSION_STANDARD if ahp.FUSION_STANDARD in ((model.get("thinking") or {}).get("levels") or []) else "")
    link.dispatch(chat, {"type": "chat/turnStarted", "turnId": str(uuid.uuid4()), "startedAt": ahp.utc_stamp(), "message": message})
    why, handled, consent, started = "time limit (240 s)", set(), [], False
    while time.time() - began < 240:
        time.sleep(2)
        try:
            state = link.subscribe(chat, 20)
        except Exception as error:  # noqa: BLE001
            why = "the host stopped answering (%s)" % type(error).__name__
            break
        turn = state.get("activeTurn")
        if isinstance(turn, dict):
            started = True
            for part in turn.get("responseParts") or []:
                call = (part or {}).get("toolCall") if isinstance(part, dict) else None
                if not isinstance(call, dict) or call.get("status") != "pending-confirmation" or call.get("toolCallId") in handled:
                    continue
                handled.add(call.get("toolCallId"))
                action = {"type": "chat/toolCallConfirmed", "turnId": turn.get("id"), "toolCallId": call.get("toolCallId")}
                if call.get("toolName") == "extension_permission_consent":
                    consent.append("%.1f s, options %s" % (time.time() - began, [o.get("id") for o in call.get("options") or []]))
                    action.update({"approved": True, "selectedOptionId": "allow-once"})
                else:
                    deny = next((str(o["id"]) for o in call.get("options") or [] if isinstance(o, dict) and o.get("kind") == "deny" and o.get("id")), "skip")
                    action.update({"approved": False, "reason": "denied", "reasonMessage": "lock-probe: nobody approved this call", "selectedOptionId": deny})
                link.dispatch(chat, action)
        elif started or state.get("turns"):
            why = "turn ended"
            break
    time.sleep(3)
    ev = record(mark)
    print("")
    print("== %s | permission %s | extension %s | trusted %s | %s after %.0f s" % (name, "Allow all" if permission == "autoApprove" else "default", "on" if extension else "off", trusted, why, time.time() - began))
    if consent:
        print("   extension load question: %s -> answered allow-once" % "; ".join(consent))
    calls, asked, answered = {}, {}, {}
    first = None
    for e in ev:
        kind, data = e.get("type"), e.get("data") or {}
        at = stamp(e.get("timestamp"))
        first = first or at
        cid = data.get("toolCallId") or ((data.get("permissionRequest") or {}).get("toolCallId"))
        if kind == "tool.execution_start":
            args = data.get("arguments")
            calls[cid] = {"at": (at or 0) - (first or 0), "tool": data.get("toolName"), "args": short(args.get("command") or args.get("path") or json.dumps(args) if isinstance(args, dict) else args)[:60].replace("\n", " "), "ok": None}
        elif kind == "tool.execution_complete" and cid in calls:
            calls[cid]["ok"] = data.get("success")
            calls[cid]["end"] = (at or 0) - (first or 0)
        elif kind == "permission.requested" and cid:
            asked[cid] = (data.get("permissionRequest") or {}).get("kind")
        elif kind == "permission.completed" and cid:
            answered[cid] = data.get("decisionSource") or ((data.get("result") or {}).get("kind"))
    print("   %6s %6s  %-12s %-60s %-40s %s" % ("start", "end", "tool", "call", "asked a person?", "ran"))
    for cid, c in calls.items():
        ans = answered.get(cid, "?")
        ask = "no" if cid not in asked else "yes (%s) -> %s" % (asked[cid], "refused by the probe" if str(ans).startswith("denied") else ans)
        if cid in asked and answered.get(cid) in ("host_policy",):
            ask = "no, host approved (%s)" % asked[cid]
        print("   %6.1f %6s  %-12s %-60s %-40s %s" % (c["at"], "%.1f" % c["end"] if "end" in c else "-", c["tool"], c["args"], ask[:40], "ran" if c["ok"] else "did not run" if c["ok"] is False else "?"))
    rows = []
    try:
        rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        pass
    print("   extension: processes %d | loads %d | joined %d | exits %d | answers %s" % (
        len({r.get("pid") for r in rows}), sum(r.get("event") == "load" for r in rows), sum(r.get("event") == "joined" for r in rows),
        sum(r.get("event") == "exit" for r in rows), [r.get("answer") for r in rows if r.get("event") == "pre"]))
    print("   made in the folder:", sorted(n for n in MADE if (probe / n).exists()) or "nothing")


def main():
    wanted = (sys.argv[1].split(",") if len(sys.argv) > 1 else list(VARIANTS))
    print("== 0. Before | run %s | python %s" % (RUN, sys.version.split()[0]))
    policy = vscode_policy()
    print("VS Code policy ChatCanvases:", "not set" if policy is None else policy)
    if policy is not None and str(policy).lower() in ("0", "false"):
        sys.exit("The organization turned canvases off for VS Code. Stop here: send this photo back.")
    try:
        host, link = connect()
    except (OSError, ValueError) as error:
        sys.exit("No agent host record (%s): open the board, wait for the task list, run again." % type(error).__name__)
    before, state = canvases(link)
    print("agent host %s | canvasesEnabled before %s | variants %s" % (host.get("version"), before, ",".join(wanted)))
    for _ in range(15):
        if ahp.models_of(state):
            break
        time.sleep(2)
        state = canvases(link)[1]
    model = next((m for m in ahp.models_of(state) if m.get("id") == ahp.FUSION_ID), None)
    print("model:", (model or {}).get("id", "default (Fusion not listed)"))
    OUTSIDE.parent.mkdir(parents=True, exist_ok=True)
    OUTSIDE.write_text("outside note\n", encoding="utf-8")
    OUT_ALLOW.write_text("outside note, allowed\n", encoding="utf-8")
    try:
        for name in wanted:
            try:
                one(link, name, model)
            except Exception as error:  # noqa: BLE001
                print("\n== %s stopped: %s %s" % (name, type(error).__name__, short(error)[:200]))
                try:
                    link.close()
                except Exception:  # noqa: BLE001
                    pass
                host, link = connect()
    finally:
        try:
            link.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            host, link = connect()
            now = canvases(link, bool(before))[0]
            link.close()
            print("\ncanvasesEnabled put back to", now)
        except Exception as error:  # noqa: BLE001
            print("\ncould not put canvasesEnabled back (%s): close the board and open it again" % type(error).__name__)
    print("probe folders stay for a look; delete when done:", short(BASE))


if __name__ == "__main__":
    main()
