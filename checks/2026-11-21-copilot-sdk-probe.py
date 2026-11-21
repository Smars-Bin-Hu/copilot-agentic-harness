"""Probe: can this PC run Copilot through the Copilot SDK, without VS Code?

Run with the Python of the venv that has `microsoft-copilot-sdk` installed:
    python probe.py                      # steps 1-5
    python probe.py --harness <folder>   # also step 6: hooks of the harness in that folder
Options: --model <id> (default: auto), --runtime <path to a copilot runtime>.
It prints one line per step. It writes no file; step 6 asks the agent only to read a file.
"""
import argparse
import asyncio
import os
import sys
import tempfile
import time
import traceback


def say(step, ok, text):
    print("[%s] %s  %s" % (step, "OK  " if ok else "FAIL", text), flush=True)


def short(error):
    text = "%s: %s" % (type(error).__name__, " ".join(str(error).split()))
    return text[:400]


async def turn(client, folder, model, prompt, hooks):
    from copilot.session import PermissionHandler
    counts = {}

    def on_event(event):
        name = getattr(event.type, "value", str(event.type))
        if name == "hook.start":
            kind = getattr(getattr(event, "data", None), "hook_type", None)
            kind = getattr(kind, "value", kind) or "?"
            counts[kind] = counts.get(kind, 0) + 1
        if name == "session.error":
            counts["session.error"] = counts.get("session.error", 0) + 1

    options = dict(model=model, working_directory=folder,
                   permissions={"on_request": PermissionHandler.approve_all},
                   events={"on_event": on_event})
    if hooks:
        options.update(enable_config_discovery=True, hooks={"enable_repository_hooks": True},
                       skills={"enabled": True}, filesystem={"trust_working_directory": "session"})
    session = await client.create_session(**options)
    start = time.time()
    reply = await session.send_and_wait(prompt, timeout=180)
    seconds = round(time.time() - start, 1)
    text = str(getattr(getattr(reply, "data", None), "content", reply))
    await session.disconnect()
    return seconds, " ".join(text.split())[:200], counts


async def main(args):
    say(1, sys.version_info >= (3, 11), "Python %s at %s" % (sys.version.split()[0], sys.executable))
    try:
        from importlib.metadata import version
        from copilot import CopilotClient
        from copilot.client import RuntimeConnection
        say(1, True, "microsoft-copilot-sdk %s" % version("microsoft-copilot-sdk"))
    except Exception as error:  # noqa: BLE001
        say(1, False, "SDK not importable: " + short(error))
        return
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(name):
            print("      env %s is set" % name)

    runtime = RuntimeConnection.for_spawned_stdio(path=args.runtime) if args.runtime else None
    client = CopilotClient(mode="coding-agent", runtime=runtime)
    start = time.time()
    try:
        await client.start()
        status = await client.get_status()
        say(2, True, "runtime %s started in %.1f s (first run downloads it)" % (status.version, time.time() - start))
    except Exception as error:  # noqa: BLE001
        say(2, False, "runtime did not start after %.1f s: %s" % (time.time() - start, short(error)))
        traceback.print_exc(limit=3)
        return
    try:
        auth = await client.get_auth_status()
        login = auth.login or ""
        masked = (login[:2] + "***") if login else "-"
        say(3, bool(auth.is_authenticated), "signed in: %s, way: %s, host: %s, user: %s" % (auth.is_authenticated, auth.auth_type, auth.host, masked))
        if not auth.is_authenticated:
            print("      " + " ".join(str(auth.status_message or "").split())[:300])
            return
        try:
            models = await client.list_models()
            ids = [m.id for m in models]
            say(4, bool(ids), "%d models: %s" % (len(ids), ", ".join(ids)[:600]))
        except Exception as error:  # noqa: BLE001 - go on: a turn may still work
            say(4, False, "model list refused: " + short(error)[:200])
        try:
            with tempfile.TemporaryDirectory() as folder:
                seconds, text, _ = await turn(client, folder, args.model, "Reply with the single word OK.", hooks=False)
            say(5, "OK" in text.upper(), "one turn in an empty folder, %s s, model %s, reply: %s" % (seconds, args.model, text))
        except Exception as error:  # noqa: BLE001
            say(5, False, "turn refused: " + short(error)[:300])
            return
        if args.harness:
            folder = os.path.abspath(args.harness)
            seconds, text, counts = await turn(client, folder, args.model,
                                               "Read the first line of AGENTS.md with your file read tool and reply with that line only. Do not change any file.", hooks=True)
            wanted = ("sessionStart", "userPromptSubmitted", "preToolUse", "postToolUse", "agentStop")
            missing = [k for k in wanted if not counts.get(k)]
            say(6, not missing, "turn in %s, %s s; hooks fired: %s; missing: %s; reply: %s" % (folder, seconds, counts, missing or "none", text[:120]))
    except Exception as error:  # noqa: BLE001
        say("x", False, short(error))
        traceback.print_exc(limit=3)
    finally:
        await client.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="auto")
    parser.add_argument("--runtime")
    parser.add_argument("--harness")
    asyncio.run(main(parser.parse_args()))
