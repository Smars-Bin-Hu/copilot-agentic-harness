#!/usr/bin/env python3
"""The only hook entry point. One process per hook event.

  stdin  -> adapter (raw payload -> HookEvent)
         -> session state (locked) -> core subagent tracking
         -> modules from registry.json that subscribe to the event
         -> merge (deny > ask > allow; contexts joined; one block blocks)
  stdout <- adapter (Decision -> runtime output JSON)
  log    -> observe module: one line per call in the log of the session

A guardrail that cannot decide does not let the call through (1.7.38, C13 FR 16 to 18). When the engine cannot be imported (a syntax error, a conflict marker), when a module of the guardrails raises on a
PreToolUse call, when the session state or the registry cannot be read, or when a guardrail file is not what the person accepted (`integrity.py`), this file answers with the standard library only and without
any of the engine: every terminal command and every tool that may change a file is refused, with one line that says what is wrong and that the user repairs it; reads, the tool that asks the user and a subagent
stay. Every other event prints valid output and stops nothing. Only a failure of what is only shown or written down (the log, the record of a call) leaves the decision as it was.
Everything the emergency answer needs is in this file: do not move it into a module that the engine imports.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:  # nothing of the engine may stop this file from answering: a failure here is `ENGINE_FAULT`, and `main` answers with `emergency`
    import copy
    import importlib

    import adapters
    from core import breaker
    from core import callrecord
    from core import kbreads
    from core import registry as registry_module
    from core import state as state_module
    from core.context import Context
    from core.events import Decision, HookEvent, merge
    from core.failopen import call_safely
    from core.logs import log_error
    from core.paths import repo_root
    ENGINE_FAULT: Optional[BaseException] = None
except BaseException as _error:  # noqa: BLE001 - including SystemExit and KeyboardInterrupt from a file that was changed
    ENGINE_FAULT = _error


class GuardFailed(Exception):
    """A module of the guardrails raised on a PreToolUse call: the call cannot be judged, so it does not pass (`main` answers with `emergency`)."""


def run_modules(root: Path, event: HookEvent, ctx: Context, names: List[str], guards: Optional[set] = None) -> Tuple[List[Tuple[str, Decision]], List[str], Dict[str, Any]]:
    """Call each module. A module that raises has no opinion and its state changes are rolled back, except a module of the guardrails (`guards`: those the registry marks `H`) on a PreToolUse call: it cannot judge
    the call, so the call does not pass (`GuardFailed`, 1.7.38, C13 FR 16).

    Returns what each module decided (with its name), the modules that ran, and the facts they report for the log."""
    sources: List[Tuple[str, Decision]] = []
    ran: List[str] = []
    facts: Dict[str, Any] = {}
    for name in names:
        snapshot = copy.deepcopy(ctx.state)
        try:
            module = importlib.import_module(f"modules.{name}")
            decision = module.handle(event, ctx)
            ran.append(name)
        except Exception as error:
            log_error(root, f"module:{name}:{event.event}", error)
            ctx.state.clear()
            ctx.state.update(snapshot)
            if name in (guards or ()):
                if event.event == "PreToolUse":
                    raise GuardFailed(f"module {name}: {where(error)}") from error
                facts.setdefault("guard_failed", f"module {name}: {where(error)}")  # another event: nothing is refused, and `process` tells the agent
            decision = None
        if decision is not None:
            sources.append((name, decision))
            facts.update(decision.facts)
    return sources, ran, facts


def process(raw: str, root: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Payload text in, (runtime output, call record) out. Raises on any failure to decide; a failure after the decision was made (the state written back, the record of the call) leaves the decision as it is."""
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Hook payload is not a JSON object")
    adapter = adapters.detect(payload)
    event = adapter.parse(payload)
    registry = registry_module.load_registry(root)
    names = registry_module.modules_for(registry, event.event)
    guards = {name for name in names if "H" in ((registry.get("modules") or {}).get(name) or {}).get("enforcement", [])}
    link = None
    if event.event == "UserPromptSubmit" and not state_module.state_path(root, event.surface, event.session_id).exists():
        link = state_module.claim_child(root, event.surface, event)
    made: Dict[str, Any] = {}
    sources: List[Tuple[str, Decision]] = []
    ran: List[str] = []
    facts: Dict[str, Any] = {}
    denial = None
    admin = False
    parent_session_id = None
    try:
        with state_module.session(root, event.surface, event.session_id) as state:
            state_module.track_before(state, event)
            if link:
                state.update(link)  # a subagent session: it inherits the task its parent holds, and its first prompt is not the user
                event.from_subagent = True
            ctx = Context(root, state)
            sources, ran, facts = run_modules(root, event, ctx, names, guards)
            decision = merge([item for _name, item in sources])
            failed = facts.pop("guard_failed", "")
            if failed and event.event in ("UserPromptSubmit", "SessionStart"):  # a guardrail module could not run: the agent hears of it at the start, not only when a call is refused
                decision.context = (decision.context + "\n" if decision.context else "") + _say(root, "hook.emergency", failed)
            if event.event == "UserPromptTransformed":
                decision = state_module.restored_prompt(state, event)  # core: the rules the engine dropped, put back
                facts.update(decision.facts)
            denial = call_safely(root, "breaker", breaker.apply, root, state, event, decision)  # a refusal stays a refusal
            made["decision"] = decision  # decided: what follows is the state written back and the log
            state_module.track_after(state, event, decision)
            admin = ctx.admin
            parent_session_id = state.get("parent_session_id")
    except BaseException as error:  # noqa: BLE001
        if "decision" not in made:
            raise  # nothing was decided: the call does not pass (`main`)
        log_error(root, f"hook:after:{event.event}", error)
        decision = made["decision"]
    record: Dict[str, Any] = {}
    try:
        read = kbreads.of_event(root, event)
        if read:
            facts = dict(facts, kb=read)  # which knowledge base files the call read: the one thing kept of a call that went through
        record = callrecord.build(
            event,
            decision,
            engine=getattr(adapter, "engine", lambda _payload: "")(payload),
            ran=ran,
            sources=sources,
            facts=facts,
            parent_session_id=parent_session_id,
            denial=denial,
            admin=admin,
        )
    except Exception as error:  # noqa: BLE001 - the record of a call is a log: it is never a reason to change the answer
        log_error(root, f"hook:record:{event.event}", error)
    return adapter.render(event, decision), record


def observe(root: Path, record: Dict[str, Any], raw: str, output: Dict[str, Any]) -> None:
    """Hand the call record to the observe module, if it is on. Logging must never get in the way of the hook."""
    try:
        entry = registry_module.load_registry(root)["modules"].get("observe")
        if entry is None or not entry["enabled"] or entry["status"] == "retired":
            return
        importlib.import_module("modules.observe").record_call(root, record, raw, output)
    except Exception as error:
        log_error(root, "observe", error)


# --- the emergency answer: the standard library only ----------------------------------------------------------------------------------------------------------

# Tools that cannot change a file or run a command, by the names the engines send (adapters/tool_kinds.json: read, search, meta, web, skill, subagent). A test keeps this list and that file together.
SAFE_TOOLS = frozenset((
    "read_file list_dir grep_search file_search semantic_search Read Grep Glob search_code_subagent WebFetch skill tool_search_tool task_complete AskUserQuestion ask_user Agent runSubagent "
    "read_bash read_powershell list_bash list_powershell report_intent"
).split())
TERMINAL_TOOLS = frozenset("run_in_terminal Bash bash PowerShell powershell".split())
TEXTS = {
    "hook.emergency": "The harness engine cannot decide, so nothing that runs a command or changes a file is allowed until it is repaired: {why}\nYou may still read. Tell the user what is wrong, and do not try to repair it or to go round it. The user puts the file back from the zip the harness came from, and checks it with `harness doctor`.",
    "hook.integrity": "A guardrail file is not what the user accepted: {why}\nNothing that runs a command or changes a file is allowed until the user has looked at it. You may still read. Tell the user which files changed, and do not try to repair it or to go round it. If the user changed them on purpose, they accept them with `harness doctor --accept` in their own terminal. If not, they put the files back from the zip the harness came from.",
    "hook.integrity.upgrade": "A new version of the harness was put in this folder, and the board has not been started since: {why}\nNothing that runs a command or changes a file is allowed until the board accepts the new version. You may still read. Tell the user to start the board (Start Harness, or `harness task board`): it accepts the new version when it starts. Do not try to repair it or to go round it.",
    "hook.busy": "The harness was busy with another call of this session and could not decide: {why}\nRun the same call again.",
}


def _root() -> Path:
    override = os.environ.get("HARNESS_ROOT")
    return Path(override).resolve() if override else HERE.parents[1]


def where(error: BaseException) -> str:
    """Which file and what: `modules/gate/pin.py:12: SyntaxError: invalid syntax`. A syntax error names its file; another error, the last frame of the engine in its traceback."""
    try:
        name, line = getattr(error, "filename", None), getattr(error, "lineno", None)
        if not name:
            for frame in reversed(traceback.extract_tb(error.__traceback__)):
                if str(HERE) in str(frame.filename):
                    name, line = frame.filename, frame.lineno
                    break
        shown = str(name or "")
        try:
            shown = Path(shown).resolve().relative_to(HERE).as_posix() if shown else ""
        except (ValueError, OSError):
            pass
        text = " ".join(str(getattr(error, "msg", None) or error).split())
        return f"{shown + (':' + str(line) if line else '') + ': ' if shown else ''}{type(error).__name__}: {text}"[:300]
    except BaseException:  # noqa: BLE001 - this is the last net
        return type(error).__name__


def _language(root: Path) -> str:
    """`en` or `zh`: the environment, else `user.json` and its override, as plain files. Any doubt says `en`."""
    word = os.environ.get("HARNESS_LANGUAGE", "")
    if word not in ("en", "zh"):
        word = ""
        for name in ("user.json", "user.override.json"):
            try:
                found = json.loads((root / ".harness" / "policies" / name).read_text(encoding="utf-8-sig")).get("language")
                word = found if found in ("en", "zh") else word
            except (OSError, ValueError, AttributeError):
                pass
    return word or "en"


def _say(root: Path, key: str, why: str) -> str:
    """The words of the message table when it can be read (the table is a plain JSON file), else the English text above."""
    text = ""
    try:
        text = json.loads((HERE / "core" / f"messages.{_language(root)}.json").read_text(encoding="utf-8-sig")).get(key) or ""
    except (OSError, ValueError, AttributeError):
        pass
    text = text if isinstance(text, str) and "{why}" in text else TEXTS[key]
    return text.replace("{why}", why)


def _payload(raw: str) -> Dict[str, Any]:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def event_of(payload: Dict[str, Any]) -> str:
    name = payload.get("hook_event_name") or payload.get("hookEventName") or ""
    if not name and ("toolName" in payload or "tool_name" in payload) and not ("toolResult" in payload or "tool_result" in payload):
        return "PreToolUse"  # the camelCase payload of a tool call that is not yet run has no event name
    return name if isinstance(name, str) else ""


def tool_of(payload: Dict[str, Any]) -> Tuple[str, Any]:
    """`(tool name, its input as a dict, or the text of it)` in the shape of either engine (`tool_name` and `tool_input`, or `toolName` and `toolArgs`, which may be a JSON text)."""
    name = payload.get("tool_name") if payload.get("tool_name") is not None else payload.get("toolName")
    given = payload.get("tool_input") if payload.get("tool_input") is not None else payload.get("toolArgs")
    if isinstance(given, str):
        try:
            decoded = json.loads(given)
            given = decoded if isinstance(decoded, dict) else given
        except ValueError:
            pass
    return name if isinstance(name, str) else "", given


def may_pass(name: str, given: Any) -> bool:
    """Does a PreToolUse call stay allowed while the engine cannot decide? Only a tool that cannot run a command or change a file: a read, a search, the tool that asks the user, a subagent. A terminal tool, a tool whose
    input has a `command`, an edit or create tool and any tool that is not known are refused."""
    if not name or name in TERMINAL_TOOLS or (isinstance(given, dict) and isinstance(given.get("command"), str)):
        return False
    return name in SAFE_TOOLS


def emergency(root: Path, raw: str, why: str, kind: str = "hook.emergency") -> Dict[str, Any]:
    """The answer when the engine cannot decide (or a guardrail file changed): standard library only. A PreToolUse call that may change something is refused with the words; reads pass; a prompt or a session start
    gets the words as context; every other event, nothing. Always valid output, never raises."""
    try:
        payload = _payload(raw)
        event = event_of(payload)
        text = _say(root, kind, why)
        if event == "PreToolUse":
            name, given = tool_of(payload)
            return {} if may_pass(name, given) else {"permissionDecision": "deny", "permissionDecisionReason": text}
        if event in ("UserPromptSubmit", "SessionStart"):
            return {"additionalContext": text}
    except BaseException:  # noqa: BLE001 - this is the last net: a call that cannot be read as a tool call is not one
        pass
    return {}


def note(root: Path, where_: str, error: BaseException, raw: str = "") -> None:
    """One line in `hook-errors.jsonl` when the engine's own log cannot be used. Never raises."""
    try:
        path = root / ".harness" / "runtime" / "logs" / "hook-errors.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "where": where_, "error": where(error), "sample": raw[:300]}, ensure_ascii=False) + "\n")
    except BaseException:  # noqa: BLE001
        pass


def fail_closed(root: Path, raw: str, error: BaseException) -> Dict[str, Any]:
    """The output when the whole hook failed to decide. A PreToolUse call that names a program or an MCP tool of a tool pack is refused with its own words (modules/gate/failclosed.py); every other call that may run a command or
    change a file is refused by `emergency`; reads and the other events pass (1.7.38, C13 FR 16 and 18)."""
    try:
        from modules.gate import failclosed

        found = failclosed.on_hook_error(root, raw, error)
        if found:
            return found
    except BaseException:  # noqa: BLE001 - the engine is what failed: the standard library answers
        pass
    busy = isinstance(error, TimeoutError)
    return emergency(root, raw, where(error), "hook.busy" if busy else "hook.emergency")


def integrity_problem(root: Path, raw: str) -> Tuple[str, str]:
    """`(the files of the guardrails that are not what the person accepted (`integrity.py`), why)` for the calls that decide something; `("", "")` when all are, when nothing was accepted yet, in admin mode, and for the events
    that decide nothing. Why is `upgrade` (a new version was put in, the board has not been started) or `changed`. A check that cannot run because `integrity.py` cannot load is a problem too."""
    payload = _payload(raw)
    if event_of(payload) not in ("PreToolUse", "UserPromptSubmit", "SessionStart"):
        return "", ""
    try:
        import integrity

        session_id = payload.get("session_id") or payload.get("sessionId") or ""
        if isinstance(session_id, str) and session_id and integrity.admin_session(root, "vscode", session_id):
            return "", ""  # the person switched admin mode on for this session: changing these files is its job
        return integrity.status(root)
    except BaseException as error:  # noqa: BLE001 - the file that checks is itself changed or gone
        return where(error), "changed"


def refusal_record(raw: str, output: Dict[str, Any], kind: str) -> Dict[str, Any]:
    """The record of a call that this file refused itself (a guardrail file that is not as accepted, a hook that could not decide), as the log of a refusal has it, so that the task page, Live and the report show it (1.7.38, C13
    FR2 5). Needs the engine's event reader: `{}` when it cannot be had (the caller keeps a thin record)."""
    try:
        payload = _payload(raw)
        adapter = adapters.detect(payload)
        event = adapter.parse(payload)
        decision = Decision(permission="deny" if output.get("permissionDecision") == "deny" else None, reason=str(output.get("permissionDecisionReason") or ""), context=str(output.get("additionalContext") or ""))
        return callrecord.build(event, decision, engine=getattr(adapter, "engine", lambda _payload: "")(payload), ran=[], sources=[], facts={"kind": kind}, parent_session_id=None, denial=None)
    except BaseException:  # noqa: BLE001 - a log line is never a reason to change the answer
        return {}


def main() -> int:
    started = time.monotonic()
    root = _root()
    output: Dict[str, Any] = {}
    record: Dict[str, Any] = {}
    raw = ""
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        changed, why = integrity_problem(root, raw)
        key = "hook.integrity.upgrade" if why == "upgrade" else "hook.integrity"
        if ENGINE_FAULT is not None:
            raise ENGINE_FAULT
        if changed and event_of(_payload(raw)) == "PreToolUse":
            output = emergency(root, raw, changed, key)
            record = refusal_record(raw, output, "integrity") or {"error": f"integrity: {changed}"}  # the refusal is in the log of the session, with a kind the pages name
        else:
            output, record = process(raw, root)
            if changed:  # a prompt or a session start: the agent hears of it at once
                output = dict(output, additionalContext=(output.get("additionalContext", "") + "\n" if output.get("additionalContext") else "") + _say(root, key, changed))
    except BaseException as error:  # noqa: BLE001 - including SystemExit: a guardrail that cannot decide does not pass (`fail_closed`)
        if ENGINE_FAULT is None:
            try:
                log_error(root, "hook", error, sample=raw)
            except BaseException:  # noqa: BLE001
                pass
        else:
            note(root, "hook", error, raw)
        output = fail_closed(root, raw, error)
        record = (refusal_record(raw, output, "engine") if ENGINE_FAULT is None and (output.get("permissionDecision") or output.get("additionalContext")) else {})
        record = dict(record, error=where(error))
    record["ms"] = round((time.monotonic() - started) * 1000, 1)
    record["pid"] = os.getpid()
    if ENGINE_FAULT is None:
        observe(root, record, raw, output)
    sys.stdout.write(json.dumps(output))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
