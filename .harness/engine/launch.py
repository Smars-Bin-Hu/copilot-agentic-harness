#!/usr/bin/env python3
"""The one file `.github/hooks/harness.json` starts (1.7.38, C13 FR2 4). Standard library only, small on purpose: nobody should have a reason to change it.

It loads `hook.py` and runs it. When `hook.py` cannot be loaded (a syntax error, a conflict marker, a missing file), it answers in its place the way `hook.py` answers when the engine cannot decide: a command, a file
change and any tool it does not know are refused, with the file and the fault; reads, asking the user and subagents stay; a prompt or a session start gets the words as context. Nothing is read from the engine here."""
import importlib.util
import io
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SAFE = frozenset(("read_file list_dir grep_search file_search semantic_search Read Grep Glob search_code_subagent WebFetch skill tool_search_tool task_complete AskUserQuestion ask_user Agent runSubagent "
                  "read_bash read_powershell list_bash list_powershell report_intent").split())  # tests keep this list the same as `SAFE_TOOLS` of hook.py
WORDS = ("The harness hook cannot start, so nothing that runs a command or changes a file is allowed until it is repaired: %s\nYou may still read. Tell the user what is wrong, and do not try to repair it or to go round it. "
         "The user puts the file back from the copy or the zip the harness came from, and checks it with `harness doctor`.")


def where(error):
    name, line = getattr(error, "filename", None), getattr(error, "lineno", None)
    if not name:
        frames = [f for f in traceback.extract_tb(error.__traceback__) if HERE in str(f.filename)]
        name, line = (frames[-1].filename, frames[-1].lineno) if frames else ("", None)
    name = os.path.relpath(str(name), HERE).replace(os.sep, "/") if name else ""
    return "%s%s: %s: %s" % (name, ":%s" % line if line else "", type(error).__name__, " ".join(str(getattr(error, "msg", None) or error).split()))[:300]


def answer(raw, why):
    try:
        data = json.loads(raw.decode("utf-8-sig", errors="replace"))
        data = data if isinstance(data, dict) else {}
        tool, given = data.get("tool_name", data.get("toolName")), data.get("tool_input", data.get("toolArgs"))
        event = data.get("hook_event_name") or data.get("hookEventName") or ("PreToolUse" if tool is not None and not ("toolResult" in data or "tool_result" in data) else "")
        if isinstance(given, str):
            try:
                given = json.loads(given)
            except ValueError:
                pass
        if event == "PreToolUse":
            safe = tool in SAFE and not (isinstance(given, dict) and isinstance(given.get("command"), str))
            return {} if safe else {"permissionDecision": "deny", "permissionDecisionReason": WORDS % why}
        if event in ("UserPromptSubmit", "SessionStart"):
            return {"additionalContext": WORDS % why}
    except BaseException:  # noqa: BLE001 - a call that cannot be read as a tool call is not one
        pass
    return {}


def main():
    raw = sys.stdin.buffer.read()
    try:
        spec = importlib.util.spec_from_file_location("harness_hook", os.path.join(HERE, "hook.py"))
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
        return hook.main()
    except BaseException as error:  # noqa: BLE001 - including SystemExit from a file that was changed
        sys.stdout.write(json.dumps(answer(raw, where(error))) + "\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
