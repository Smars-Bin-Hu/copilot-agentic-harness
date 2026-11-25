"""One judgment, two ways in (hook speed, 1.8.50): every hook call of the existing hook tests is judged BOTH by the board's service and by a hook process of its own, on identical state, and the two are compared.

The service is only worth having if it is not another judge. `hookserve.py` runs `hook.answer`, the same function the hook process runs; what could differ is what is around it (the environment, the working folder, memory
kept in the board's process, the order of things). So the proof is not a list of cases written for it: it is every payload that the tests of the gate, the breaker, the observer and the task hooks already send,
whatever they are, sent to both.

How it works: some of the existing hook test files run again, each in a process of its own, with `HarnessTestCase.hook(data)` replaced by a function that, for each call:
  1. makes sure a service listens on the test's root (one per test, started again when the engine, the registry or the hook configuration of the root changed, as the board would restart on an upgrade),
  2. copies the whole root, asks the service as `launch.py` does (`hookclient.ask`, with the environment the test gives the hook process), keeps what is on disk, and puts the copy back,
  3. runs the real hook process, as the test always did, and keeps what is on disk,
  4. compares the two outputs and the two trees of files (the records, the state, the cards), field by field, with only the things that cannot be the same masked: times, durations, process numbers, `via`, `why`,
     the nonce (a record the service judged has one, a local one has none), and the random ids of approvals. `via`, `why`, `ms`, `pid` and `nonce` are masked in the rows of the hook logs only (the one place they differ by
     design); everywhere else a value under those names is compared as it is.
The test returns the answer of the hook process, so each test still checks what it always checked. A difference, a call the service would not judge, and a failure of the inner test, are listed. A call the service would not
judge is the hook process's own, which is right, but it is not compared: so its reason must be one of `ALLOWED_FALLBACKS` (none is expected in a normal run), and most of the calls must have been judged by the service, or the proof is empty.
For a call of PreToolUse, UserPromptSubmit or SessionStart the trace of the hook client (`hookclient.jsonl`) must have one new line whose nonce is in a record of the session log, and for any other call none.

Which files run is not kept by hand. `discover()` reads the test files and finds those that send hook calls (through `HarnessTestCase.hook`, also by a class that inherits a test class that does, or in a way that is not routed here:
`run_script(HOOK, ...)`, `hook.process(...)`); each is in `HOOK_TESTS` (run by default) or in `EXCLUDED` with its reason, and a test fails for a file that is in neither, so a new test file cannot be left out without a word.
`HOOKEQUIV_FILES=all` runs every file of both lists (the slow ones too: over an hour); `HOOKEQUIV_FILES=test_gate,test_breaker` runs the ones named (any `test_*.py` module of this folder); `HOOKEQUIV_JOBS` sets how many run
at once (default 4).
"""

from __future__ import annotations

import ast
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
import hookclient

HERE = Path(__file__).resolve().parent

# Run by default: the files that send the most hook calls through the gate and the task hooks, and what those reach: the gate in all its parts (rules, lists, external programs, git, approvals, the super agent, red team, the hook
# key and the root-level files), the breaker, the observer, admin mode, the outbox and the language, the task hooks (autorun, rules) and the pins of a held call, the connections; and the small files of other areas (under a
# minute each: sessions replayed, map-reduce, the agents, the stages of a task, the eval check, the knowledge base status). About 13 minutes with 4 at once.
HOOK_TESTS = (
    "test_gate", "test_gate_lists", "test_gate_external", "test_gate_git", "test_gate_approval", "test_gate_ask", "test_gate_super", "test_gate_redteam", "test_keyguard", "test_open_pick",
    "test_breaker", "test_observe", "test_admin", "test_outbox", "test_language", "test_accept", "test_c13_d5",
    "test_autorun_hooks", "test_taskrules", "test_connections", "test_connection_find",
    "test_mapreduce", "test_taskagents", "test_rewind", "test_health", "test_wait", "test_evidence", "test_taskfork", "test_evalcheck", "test_kbstatus", "test_c12_fc", "test_autorun_spend", "test_testdefects", "test_taskinbox",
)
# Not run by default, and why. `HOOKEQUIV_FILES=all` runs the routed ones of these too (about two hours with 5 at once).
EXCLUDED: Dict[str, str] = {
    # time: minutes alone, with the service and the hook process both judging every call
    "test_c13_fr2": "30 minutes (850 calls); some of its tests send the call by a `hook` method of their own, with a language",
    "test_c13_f2": "over 25 minutes of calls (the SQL pack's cases)",
    "test_c13_fr": "17 minutes (300 calls); most of its calls go by `run_script`",
    "test_toolpacks": "16 minutes (445 calls); the calls are mostly the tool packs' own programs",
    "test_gate_dynamic": "time limits per input (2 s, 10 s) that two judgements of each call would break; its calls are `hook.process`/`hook.answer` in this process, not routed",
    "test_keyguard_fuzz": "time limits per input (2 s, 10 s) that two judgements of each call would break; its calls are `hook.process`/`hook.answer` in this process, not routed",
    "test_tasklife": "14 minutes (224 calls of the task hooks; run it with HOOKEQUIV_FILES when the task hooks change)",
    "test_taskreview": "13 minutes (269 calls of the task hooks and the review checks)",
    "test_taskboard": "10 minutes (211 calls; the board's text and waits)",
    "test_c13_d4": "9 minutes (230 calls: broken packs, scripts of a repository, ADO calls)",
    "test_task": "7 minutes (90 calls: plans, rounds and the report)",
    "test_autorun": "6 minutes (107 calls of the autorun worker)",
    "test_c13_f1": "5 minutes (88 calls: unreadable packs, unknown kinds, the queue at the gate)",
    "test_c13_f3": "4 minutes (83 calls: held calls with their delivery, model and effort)",
    "test_perfreview": "3.5 minutes (36 calls, most of the time is the review reading Copilot's record)",
    "test_boardserve": "3 minutes; it starts boards",
    "test_autorun_relay": "3 minutes (54 calls of the relay)",
    "test_c13_sql": "2.5 minutes (128 calls: the shipped SQL pack)",
    "test_testrecord": "2.5 minutes (60 calls of the test record)",
    "test_writeback_loose_ends": "2 minutes (58 calls)",
    "test_approval_wake": "2 minutes (42 calls of the wake after an approval)",
    "test_reviewcheck": "2 minutes (79 calls of the review gate and the commit message)",
    "test_c12_fd": "2 minutes (66 calls: script files)",
    "test_task_askturn": "2 minutes (43 calls: asking turns, waits kept, cancel and end)",
    "test_kb": "1.5 minutes (37 calls of the knowledge base register and promote)",
    "test_ticketflow": "1.5 minutes (27 calls of the ticket flow on the packs)",
    "test_superfacts": "1.5 minutes (66 calls; it starts boards)",
    "test_c12_fb": "1.5 minutes (40 calls: unknown commands, pinned files, the board that closes by itself)",
    "test_open_connection": "1 minute (42 calls of one card)",
    "test_intake": "1 minute (42 calls; it starts boards)",
    "test_taskstages": "1 minute (34 calls of the stages of a task)",
    "test_replay": "one of its tests asserts that the median hook process takes under 300 ms, which the routed run (two judgments of every call, and several files at once) does not keep on a busy computer; run it alone with HOOKEQUIV_FILES=test_replay",
    # not routed: these send their calls another way, so the service cannot be asked about the same ones here
    "test_copilot_sdk": "calls `hook.process` in its own process (the recorded Copilot payloads), not the hook process",
    "test_hookserve": "its subject is the service itself: it builds its own services and clients, and sends its calls by `hook.answer` and `run_script(HOOK, ...)`",
    "test_procenv": "its subject is the environment of the asking process: it runs the hook process itself with environments of its own",
}
MASK_KEYS = {"at", "created_at", "updated_at", "started", "ts", "time", "timestamp", "captured_at", "stamp", "reason_hash"}  # times, and a hash that has an approval code in it: by name, wherever they are
ROW_KEYS = {"ms", "pid", "via", "why", "nonce"}  # in the rows of the hook logs (`logs/<surface>/<session>.jsonl`) only: who judged, how long it took, the process that asked, the mark that ties the record to the trace of the hook process
ISO = re.compile(r"\d{4}-\d\d-\d\dT[\d:.]+(?:Z|[+-]\d\d:?\d\d)?")
AT = re.compile(r"@\d+\.\d+")
HEX12 = re.compile(r"^[0-9a-f]{12}$")
HEX6 = re.compile(r"(?<![0-9A-Za-z])[0-9A-F]{6}(?![0-9A-Za-z])")
SKIPPED_FILES = ("hookserve.json", "hookserve.json.part", "hookclient.jsonl")  # the service's own, and the trace of the hook process that asked it (the local path has none; it is checked apart, `trace_problem`)
MOST_SERVED = 0.8  # of all the calls, at least this part must have been judged by the service
# The reasons a call may not be judged by the service in this run, and why (a reason that is not here is a fault of the service or of the way the test calls it).
ALLOWED_FALLBACKS: Dict[str, str] = {}


def norm(value: Any, key: str = "") -> Any:
    """The value with what cannot be the same masked (times, process numbers, random ids)."""
    if key in MASK_KEYS:
        return "<masked>"
    if isinstance(value, dict):
        masked: Dict[str, List[Any]] = {}
        for name, item in value.items():
            masked.setdefault(HEX12.sub("<id>", HEX6.sub("<code>", name)), []).append(norm(item, name))
        # keys that are the same once their random part is masked (the counts of the breaker are kept by a hash of the reason, which has an approval code in it) are compared as a set, not by the order the hashes fall in
        return {name: (items[0] if len(items) == 1 else sorted(items, key=lambda item: json.dumps(item, sort_keys=True))) for name, items in masked.items()}
    if isinstance(value, list):
        return [norm(item) for item in value]
    if isinstance(value, str):
        return HEX6.sub("<code>", AT.sub("@<time>", ISO.sub("<iso>", value)))
    if isinstance(value, float) and value > 1.7e9:
        return "<epoch>"
    return value


def is_hook_log(rel: Path) -> bool:
    """`.harness/runtime/logs/<surface>/<session>.jsonl`: the log of a session, one row per hook call."""
    return rel.suffix == ".jsonl" and rel.parts[:3] == (".harness", "runtime", "logs") and len(rel.parts) == 5


def content(path: Path, data: bytes, rel: Optional[Path] = None) -> Any:
    """What a file holds, for the comparison: JSON read and masked; the rows of a hook log with `ROW_KEYS` masked (there only); other text masked."""
    if path.suffix == ".jsonl":
        try:
            rows = [json.loads(text) for text in data.decode("utf-8").splitlines() if text.strip()]
            if rel is not None and is_hook_log(rel):
                # `nonce` is left out (a record the service judged has one, a local one has none: the trace is checked apart); the others are masked
                return [norm({key: ("<masked>" if key in ROW_KEYS else item) for key, item in row.items() if key != "nonce"} if isinstance(row, dict) else row) for row in rows]
            if rel is not None and rel.parts == (".harness", "runtime", "logs", "hook-errors.jsonl"):
                return [norm(dict(row, traceback="<masked>") if isinstance(row, dict) and "traceback" in row else row) for row in rows]  # the stack of an error has the frames of whoever called: the service's, or the hook process's
            return [norm(row) for row in rows]
        except ValueError:
            pass
    if path.suffix == ".json":
        try:
            found = json.loads(data)
            if rel is not None and rel.parts[:3] == (".harness", "runtime", "capture") and isinstance(found, dict):
                found = dict(found, pid="<masked>")  # a capture names the process that asked: here the test process asks the service, and a hook process of its own judges
            return norm(found)
        except ValueError:
            pass
    return norm(data.decode("utf-8", "replace")) if len(data) < 200000 else len(data)


def tree(root: Path) -> Dict[str, Any]:
    """Every file under `root`, by its path (random parts masked), with its content. Files whose names are the same once the random part is masked (the cards of the outbox, one per call) are compared as a set."""
    found: Dict[str, List[Any]] = {}
    for path in Path(root).rglob("*"):
        if not path.is_file() or path.name in SKIPPED_FILES or "__pycache__" in path.parts:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        name = HEX6.sub("<code>", re.sub(r"\d{8}T\d{6}\.\d+", "<ts>", str(path.relative_to(root))))
        found.setdefault(re.sub(r"-\d+\.json$", "-<pid>.json", name), []).append(content(path, data, path.relative_to(root)))
    return {name: (items[0] if len(items) == 1 else sorted(items, key=lambda item: json.dumps(item, sort_keys=True))) for name, items in found.items()}


def differences(one: Any, other: Any, where: str = "") -> List[List[str]]:
    """`[[path, one, other], ...]`: where two values are not the same, down to the field."""
    out: List[List[str]] = []
    if isinstance(one, dict) and isinstance(other, dict):
        for key in sorted(set(one) | set(other)):
            if one.get(key) != other.get(key):
                out += differences(one.get(key), other.get(key), f"{where}/{key}")
    elif isinstance(one, list) and isinstance(other, list) and len(one) == len(other):
        for number, (left, right) in enumerate(zip(one, other)):
            if left != right:
                out += differences(left, right, f"{where}[{number}]")
    else:
        out.append([where, str(one)[:300], str(other)[:300]])
    return out


def restore(root: Path, backup: Path) -> None:
    for child in Path(root).iterdir():
        shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    for child in Path(backup).iterdir():
        if child.is_dir():
            shutil.copytree(child, Path(root) / child.name, symlinks=True)
        else:
            shutil.copy2(child, Path(root) / child.name)


# --- which files send hook calls --------------------------------------------------------------------------------------------------------------------

def _calls_hook(node: ast.AST) -> bool:
    """Does this code call `<something>.hook(...)`: the method of `HarnessTestCase` that this test routes to both ways?"""
    return any(isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and item.func.attr == "hook" for item in ast.walk(node))


def _calls_unrouted(node: ast.AST) -> bool:
    """Does it send a hook call that is not routed: `run_script(HOOK, ...)` (the name `HOOK` of `support`), or `hook.process(...)`, `hook.answer(...)`, `hook.main(...)` called directly?"""
    for item in ast.walk(node):
        if isinstance(item, ast.Name) and item.id == "HOOK":
            return True
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and item.func.attr in ("process", "answer", "main") and isinstance(item.func.value, ast.Name) and item.func.value.id == "hook":
            return True
    return False


def discover(folder: Path = HERE) -> Dict[str, str]:
    """`{module: "routed" or "not routed"}` for every `test_*.py` of `folder` that sends hook calls (itself left out). `routed`: it calls `.hook(...)`, or a class of it inherits a test class (of this file or an imported `test_*`
    module) that does: those calls go through `HarnessTestCase.hook`, which this test replaces. `not routed`: it sends its calls another way (`run_script(HOOK, ...)`, `hook.process(...)`), which is not compared here."""
    classes: Dict[Any, Any] = {}  # (module, class) -> (calls .hook, [(module, class) of its bases])
    unrouted: Dict[str, bool] = {}
    modules = sorted(path.stem for path in Path(folder).glob("test_*.py") if path.stem != "test_hookequiv")
    for module in modules:
        tree = ast.parse((Path(folder) / (module + ".py")).read_text(encoding="utf-8"))
        imported = {(item.asname or item.name): (node.module, item.name) for node in tree.body if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("test_") for item in node.names}
        unrouted[module] = _calls_unrouted(tree)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes[(module, node.name)] = (_calls_hook(node), [imported.get(base.id, (module, base.id)) for base in node.bases if isinstance(base, ast.Name)])
    memo: Dict[Any, bool] = {}

    def sends(key: Any, seen: tuple = ()) -> bool:
        if key not in classes or key in seen:
            return False
        if key not in memo:
            calls, bases = classes[key]
            memo[key] = calls or any(sends(base, seen + (key,)) for base in bases)
        return memo[key]

    routed = {module for module, _name in classes if sends((module, _name))}
    return {module: ("routed" if module in routed else "not routed") for module in modules if module in routed or unrouted[module]}


def trace_lines(root: Path) -> List[Dict[str, Any]]:
    path = Path(root) / ".harness" / "runtime" / "logs" / "hookclient.jsonl"
    try:
        return [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines() if text.strip()]
    except (OSError, ValueError):
        return []


def trace_problem(root: Path, before: int, data: Dict[str, Any], client: Optional[Path] = None) -> str:
    """"" when the trace of the hook client is what it should be after this call (the service judged it): for PreToolUse, UserPromptSubmit and SessionStart in a session, one new line whose nonce is the `nonce` of a row of the
    session log; for any other call, no line. Else what is wrong."""
    from core.logs import safe_name

    rows = trace_lines(client or root)[before:]
    try:
        watched = (json.loads((Path(root) / ".harness" / "registry.json").read_text(encoding="utf-8"))["modules"].get("observe") or {}).get("enabled")
    except (OSError, ValueError, KeyError, AttributeError):
        watched = True  # a registry that cannot be read: the call still leaves its line (hook.observe)
    session, event = data.get("session_id") or data.get("sessionId"), data.get("hook_event_name")
    if not (isinstance(session, str) and session and event in hookclient.TRACED):
        return f"{len(rows)} trace lines for a call that is not traced" if rows else ""
    if len(rows) != 1:
        return f"{len(rows)} trace lines, one expected"
    if (rows[0].get("session_id"), rows[0].get("event")) != (session, event):
        return f"the trace line names {rows[0].get('session_id')!r} {rows[0].get('event')!r}, the call is {session!r} {event!r}"
    if not watched:
        return ""  # the observe module is off: no record is made, and doctor says nothing about the trace then
    nonce = rows[0].get("nonce")
    for path in (Path(root) / ".harness" / "runtime" / "logs").glob("*/" + safe_name(session) + ".jsonl"):
        for text in path.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(text).get("nonce") == nonce:
                    return ""
            except (ValueError, AttributeError):
                continue
    return f"the trace line has nonce {nonce}, and no row of the session log has it"


# --- the inner process: one test file, with the hook call routed to both ways -----------------------------------------------------------------------

def inner(module: str, out: Path) -> int:
    """Run the tests of `module` with `HarnessTestCase.hook` routed to both ways; write what was found to `out` (JSON)."""
    sys.path.insert(0, str(HERE))
    import support  # noqa: PLC0415
    import hookclient  # noqa: PLC0415
    from core import filecache, messages  # noqa: PLC0415
    from modules.task import hookserve  # noqa: PLC0415

    original = support.HarnessTestCase.hook
    began = time.monotonic()
    report: Dict[str, Any] = {"module": module, "payloads": 0, "served": 0, "fallbacks": {}, "differences": [], "inner": []}
    started: Dict[int, Any] = {}
    planted: Dict[int, Optional[bytes]] = {}  # a test that writes its own `hookserve.json` (a file to refuse a read of): what it wrote, which the routed service would replace
    written: Dict[int, Optional[bytes]] = {}  # what the file was when the service had written it: a file that is not that was written by the test

    def service_for(case: Any, root: Path) -> Optional[Any]:
        """The service of this test's root: the one running while the engine and the root's own watched files are as it loaded them, else a new one (the board is restarted after an upgrade)."""
        service = started.get(id(case))
        if service is not None and hookserve.snapshot(root, service.engine) == service.loaded and service.server is not None:
            return service
        if service is not None:
            service.stop()
            started.pop(id(case), None)
        service = hookserve.HookService(root)
        if not service.start():
            return None
        started[id(case)] = service
        if not getattr(case, "_equiv_cleanup", False):
            case._equiv_cleanup = True
            case.addCleanup(service_stop, case)
        return service

    def service_stop(case: Any) -> None:
        service = started.pop(id(case), None)
        if service is not None:
            service.stop()

    def both(self: Any, data: Dict[str, Any]) -> Dict[str, Any]:
        root = Path(self.env.get("HARNESS_ROOT") or self.root)
        raw = json.dumps(data)
        mine = root / ".harness" / "runtime" / "hookserve.json"
        current = mine.read_bytes() if mine.is_file() else None
        if current is not None and current != written.get(id(self)):
            planted[id(self)] = current
        service = service_for(self, root)
        holder = Path(tempfile.mkdtemp(prefix="hookequiv-"))
        client = root  # the folder the hook client reads the file of the service in, and writes its trace in
        if service is not None:
            written[id(self)] = mine.read_bytes() if mine.is_file() else None
            if planted.get(id(self)) is not None:  # the root keeps the file the test wrote (the service judges with it there, as a hook process would); the client is given the service's own in a folder of its own
                service.write()
                client = holder / "client"
                (client / ".harness" / "runtime").mkdir(parents=True)
                shutil.copy2(mine, client / ".harness" / "runtime" / "hookserve.json")
                mine.write_bytes(planted[id(self)])
        try:
            backup = holder / "root"
            shutil.copytree(root, backup, symlinks=True)
            out_service: Optional[Dict[str, Any]] = None
            why = "no-service"
            traced_before = len(trace_lines(client))
            bad_trace = ""
            if service is not None:
                filecache.enable()  # the board keeps what it has read until a file changes: the service is judged as it is run
                try:
                    with mock.patch.dict(os.environ, self.env, clear=True):  # exactly the environment the test gives the hook process (a variable it took away is not there)
                        out_service, why = hookclient.ask(raw, client)
                finally:
                    filecache.enable(False)
                    messages.reset()
                if out_service is not None:
                    bad_trace = trace_problem(root, traced_before, data, client)
            tree_service = tree(root)
            restore(root, backup)
            if planted.get(id(self)) is not None:
                mine.write_bytes(planted[id(self)])
            out_local = original(self, data)
            tree_local = tree(root)
        finally:
            shutil.rmtree(holder, True)
        report["payloads"] += 1
        label = {"test": self.id(), "event": data.get("hook_event_name") or "?", "tool": data.get("tool_name") or data.get("toolName") or ""}
        if out_service is None:
            report["fallbacks"][why] = report["fallbacks"].get(why, 0) + 1
            return out_local
        report["served"] += 1
        if bad_trace:
            report["differences"].append(dict(label, kind="trace", diff=bad_trace))
        if norm(out_service) != norm(out_local):
            report["differences"].append(dict(label, kind="output", diff=differences(norm(out_service), norm(out_local))[:20]))
        if tree_service != tree_local:
            report["differences"].append(dict(label, kind="files", diff={name: differences(tree_service.get(name), tree_local.get(name))[:10] for name in sorted(set(tree_service) | set(tree_local)) if tree_service.get(name) != tree_local.get(name)}))
        return out_local

    support.HarnessTestCase.hook = both  # type: ignore[assignment]
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    result = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(suite)  # noqa: SIM115
    report["ran"] = result.testsRun
    report["seconds"] = round(time.monotonic() - began)
    report["inner"] = [test.id() + ": " + text.strip().splitlines()[-1][:300] for test, text in result.failures + result.errors if text.strip()]
    report["skipped"] = len(result.skipped)
    out.write_text(json.dumps(report), encoding="utf-8")
    return 0


# --- the test ----------------------------------------------------------------------------------------------------------------------------------

def run_inner(module: str, folder: Path) -> Dict[str, Any]:
    out = folder / (module + ".json")
    done = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--inner", module, str(out)], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, cwd=str(HERE))
    if not out.exists():
        return {"module": module, "crash": (done.stderr or done.stdout)[-2000:], "payloads": 0, "served": 0, "fallbacks": {}, "differences": [], "inner": []}
    return json.loads(out.read_text(encoding="utf-8"))


def files_to_run() -> List[str]:
    """`HOOKEQUIV_FILES`: `all` (every file of `HOOK_TESTS` and `EXCLUDED` that is routed here), or the names of test modules; not set: `HOOK_TESTS`."""
    named = [name.strip() for name in os.environ.get("HOOKEQUIV_FILES", "").split(",") if name.strip()]
    if named == ["all"]:
        found = discover()
        return [name for name in EXCLUDED if found.get(name) == "routed" and name not in HOOK_TESTS] + list(HOOK_TESTS)  # the slow ones first (in the order of EXCLUDED): the run ends when the last one does
    return named or list(HOOK_TESTS)


class WhichFilesTests(unittest.TestCase):
    """The list of files this proof runs is not kept by hand: a test file that sends hook calls and is in neither list fails here (equivalence F2)."""

    def test_every_file_that_sends_hook_calls_is_run_or_excluded_with_a_reason(self) -> None:
        found = discover()
        listed = set(HOOK_TESTS) | set(EXCLUDED)
        self.assertEqual(sorted(set(found) - listed), [], "these test files send hook calls and are not in HOOK_TESTS (run by default) or EXCLUDED (with the reason they are not)")
        self.assertEqual(sorted(listed - set(found)), [], "these are listed, and no longer send hook calls (or no longer exist): take them out of the list")
        self.assertEqual(sorted(set(HOOK_TESTS) & set(EXCLUDED)), [])
        self.assertEqual(len(HOOK_TESTS), len(set(HOOK_TESTS)))
        for name in HOOK_TESTS:
            self.assertEqual(found[name], "routed", f"{name} sends its calls in a way that is not routed here: it cannot be in HOOK_TESTS")
        for name, reason in EXCLUDED.items():
            self.assertTrue(isinstance(reason, str) and len(reason.split()) >= 3, f"{name}: say why in a line")

    def test_the_discovery_finds_direct_calls_inherited_ones_and_calls_that_are_not_routed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            files = {
                "test_a.py": "from support import HarnessTestCase\nclass A(HarnessTestCase):\n    def test_x(self):\n        self.hook({})\n",
                "test_b.py": "from test_a import A as Base\nclass B(Base):\n    pass\n",
                "test_c.py": "from support import HOOK\ndef f(self):\n    self.run_script(HOOK)\n",
                "test_d.py": "import hook\ndef f(raw, root):\n    return hook.process(raw, root)\n",
                "test_e.py": "from support import HarnessTestCase\nclass E(HarnessTestCase):\n    def test_x(self):\n        self.cli('x')\n",
                "test_f.py": "from test_e import E\nclass F(E):\n    pass\n",
                "test_hookequiv.py": "self.hook({})\n",
                "other.py": "self.hook({})\n",
            }
            for name, text in files.items():
                (Path(folder) / name).write_text(text, encoding="utf-8")
            self.assertEqual(discover(Path(folder)), {"test_a": "routed", "test_b": "routed", "test_c": "not routed", "test_d": "not routed"})

    def test_the_discovery_knows_the_files_this_proof_was_made_for(self) -> None:
        found = discover()
        for name in ("test_gate", "test_keyguard", "test_observe", "test_tasklife", "test_toolpacks"):
            self.assertEqual(found.get(name), "routed", name)
        self.assertEqual(found.get("test_procenv"), "not routed")

    def test_the_names_of_the_file_option(self) -> None:
        with mock.patch.dict(os.environ, {"HOOKEQUIV_FILES": ""}):
            self.assertEqual(files_to_run(), list(HOOK_TESTS))
        with mock.patch.dict(os.environ, {"HOOKEQUIV_FILES": "test_gate, test_breaker"}):
            self.assertEqual(files_to_run(), ["test_gate", "test_breaker"])
        with mock.patch.dict(os.environ, {"HOOKEQUIV_FILES": "all"}):
            everything = files_to_run()
        self.assertEqual(set(everything), set(HOOK_TESTS) | {name for name in EXCLUDED if discover().get(name) == "routed"})
        self.assertEqual(len(everything), len(set(everything)))

    def test_the_nonce_in_the_rows_is_masked_in_hook_logs_only(self) -> None:
        row = {"via": "service", "why": "", "nonce": "a" * 32, "ms": 3.1, "pid": 7, "event": "PreToolUse"}
        log = Path(".harness/runtime/logs/vscode/s.jsonl")
        data = (json.dumps(row) + "\n").encode("utf-8")
        self.assertEqual(content(Path("/x/s.jsonl"), data, log), content(Path("/x/s.jsonl"), (json.dumps(dict(row, via="local", pid=9, nonce="")) + "\n").encode("utf-8"), log))
        other = Path(".harness/runtime/other.jsonl")
        self.assertNotEqual(content(Path("/x/o.jsonl"), data, other), content(Path("/x/o.jsonl"), (json.dumps(dict(row, pid=9)) + "\n").encode("utf-8"), other))
        self.assertNotEqual(norm({"pid": 7}), norm({"pid": 8}))  # not by the name of a key, anywhere
        self.assertEqual(norm({"at": "x"}), norm({"at": "y"}))


class HookEquivalence(unittest.TestCase):
    def test_every_hook_call_of_the_hook_tests_is_judged_the_same_by_the_service_and_by_a_hook_process(self) -> None:
        modules = files_to_run()
        jobs = max(1, int(os.environ.get("HOOKEQUIV_JOBS") or 4))
        folder = Path(tempfile.mkdtemp(prefix="hookequiv-report-"))
        self.addCleanup(shutil.rmtree, folder, True)
        began = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
            reports = list(pool.map(lambda name: run_inner(name, folder), modules))
        problems: List[str] = []
        table: List[str] = []
        total = served = 0
        for report in reports:
            total += report["payloads"]
            served += report["served"]
            table.append(f"{report['module']:24s} {report.get('seconds', 0):4d} s  calls {report['payloads']:5d}  served {report['served']:5d}  judged here {sorted(report['fallbacks'].items())}")
            if report.get("crash"):
                problems.append(f"{report['module']}: the inner run did not finish: {report['crash']}")
            problems += [f"{report['module']}: a test of the file fails with the routing on: {text}" for text in report["inner"]]
            for found in report["differences"]:
                problems.append(f"{found['test']} ({found['event']} {found['tool']}) {found['kind']} differ: {json.dumps(found['diff'], ensure_ascii=False)[:1500]}")
        summary = "\n".join(table) + f"\n{total} hook calls, {served} judged by the service as well as by a hook process, in {time.monotonic() - began:.0f} s"
        print("\n" + summary, file=sys.stderr)
        odd: Dict[str, int] = {}
        for report in reports:
            for why, count in report["fallbacks"].items():
                if why not in ALLOWED_FALLBACKS:
                    odd[why] = odd.get(why, 0) + count
        if odd:
            problems.append(f"calls the service did not judge, for reasons that are not allowed (ALLOWED_FALLBACKS): {sorted(odd.items())}\n" + "\n".join(f"  {report['module']}: {sorted(report['fallbacks'].items())}" for report in reports if set(report["fallbacks"]) - set(ALLOWED_FALLBACKS)))
        if total and served < MOST_SERVED * total:
            problems.append(f"only {served} of {total} calls were judged by the service: the proof is empty\n{summary}")
        if not total:
            problems.append("no hook call was sent: nothing was compared")
        self.assertEqual([], problems, "\n" + "\n".join(problems[:40]) + (f"\n... {len(problems) - 40} more" if len(problems) > 40 else "") + "\n" + summary)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--inner":
        raise SystemExit(inner(sys.argv[2], Path(sys.argv[3])))
    unittest.main()
