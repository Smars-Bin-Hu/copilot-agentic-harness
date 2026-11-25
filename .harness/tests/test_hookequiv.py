"""One judgment, two ways in (hook speed, 1.8.50): every hook call of the existing hook tests is judged BOTH by the board's service and by a hook process of its own, on identical state, and the two are compared.

The service is only worth having if it is not another judge. `hookserve.py` runs `hook.answer`, the same function the hook process runs; what could differ is what is around it (the environment, the working folder, memory
kept in the board's process, the order of things). So the proof is not a list of cases written for it: it is every payload that the tests of the gate, the breaker, the observer and the task hooks already send,
whatever they are, sent to both.

How it works: some of the existing hook test files run again, each in a process of its own, with `HarnessTestCase.hook(data)` replaced by a function that, for each call:
  1. makes sure a service listens on the test's root (one per test, started again when the engine, the registry or the hook configuration of the root changed, as the board would restart on an upgrade),
  2. copies the whole root, asks the service as `launch.py` does (`hookclient.ask`, with the environment the test gives the hook process), keeps what is on disk, and puts the copy back,
  3. runs the real hook process, as the test always did, and keeps what is on disk,
  4. compares the two outputs and the two trees of files (the records, the state, the cards), field by field, with only the things that cannot be the same masked: times, durations, process numbers, `via`, `why`,
     the nonce (a record the service judged has one, a local one has none), and the random ids of approvals.
The test returns the answer of the hook process, so each test still checks what it always checked. A difference, a call the service would not judge (listed by its reason: those are the calls whose answer is the hook process's
own, which is right, but they are not compared), and a failure of the inner test, are listed. Most of the calls must have been judged by the service, or the proof is empty.

The files run are the ones that send the most hook calls through the gate and the task hooks (`HOOK_TESTS`); `HOOKEQUIV_FILES=test_gate,test_breaker` runs others (any `test_*.py` module of this folder), `HOOKEQUIV_JOBS` sets
how many run at once (default 4). A hook call that a test sends by `run_script(HOOK, ...)` or through a method of its own (as `test_c13_fr2` does with a language) is not routed here.
"""

from __future__ import annotations

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

HERE = Path(__file__).resolve().parent

# Chosen for how many hook calls they send, and for what the calls reach: the gate in all its parts (rules, lists, external programs, git, approvals, the super agent, red team), the breaker, the observer, admin mode, the
# outbox and the language, the task hooks (autorun, rules) and the pins of a held call. Left out, and why: test_tasklife (700 s) and test_taskreview (700 s: 490 calls of the task hooks, run them with HOOKEQUIV_FILES when the task hooks change), test_c13_f2 (over 20 minutes of calls alone), test_c13_fr2 (its own `hook` with a language, and 500 s), test_c13_fr (350 s, most calls by
# `run_script`), test_toolpacks (340 s, the calls are mostly the tool packs' own programs), test_boardserve (starts boards), the tests of the board and the page (no hook calls).
HOOK_TESTS = (
    "test_gate", "test_gate_lists", "test_gate_external", "test_gate_git", "test_gate_approval", "test_gate_ask", "test_gate_super", "test_gate_redteam",
    "test_breaker", "test_observe", "test_admin", "test_outbox", "test_language", "test_accept", "test_c13_d5",
    "test_autorun_hooks", "test_taskrules", "test_connections", "test_connection_find",
)
MASK_KEYS = {"at", "ms", "pid", "via", "why", "nonce", "created_at", "updated_at", "started", "ts", "time", "timestamp", "captured_at", "stamp", "reason_hash"}
ISO = re.compile(r"\d{4}-\d\d-\d\dT[\d:.]+(?:Z|[+-]\d\d:?\d\d)?")
AT = re.compile(r"@\d+\.\d+")
HEX12 = re.compile(r"^[0-9a-f]{12}$")
HEX6 = re.compile(r"(?<![0-9A-Za-z])[0-9A-F]{6}(?![0-9A-Za-z])")
SKIPPED_FILES = ("hookserve.json", "hookserve.json.part", "hookclient.jsonl")  # the service's own, and the trace of the hook process that asked it: the local path has none
MOST_SERVED = 0.8  # of all the calls, at least this part must have been judged by the service


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


def content(path: Path, data: bytes) -> Any:
    """What a file holds, for the comparison: JSON read and masked; the records of a log without their nonce (a record the service judged has one, a local one has none); other text masked."""
    if path.suffix == ".jsonl":
        try:
            rows = [json.loads(text) for text in data.decode("utf-8").splitlines() if text.strip()]
            return [norm({key: item for key, item in row.items() if key != "nonce"} if isinstance(row, dict) else row) for row in rows]
        except ValueError:
            pass
    if path.suffix == ".json":
        try:
            return norm(json.loads(data))
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
        found.setdefault(re.sub(r"-\d+\.json$", "-<pid>.json", name), []).append(content(path, data))
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
        service = service_for(self, root)
        holder = Path(tempfile.mkdtemp(prefix="hookequiv-"))
        try:
            backup = holder / "root"
            shutil.copytree(root, backup, symlinks=True)
            out_service: Optional[Dict[str, Any]] = None
            why = "no-service"
            if service is not None:
                filecache.enable()  # the board keeps what it has read until a file changes: the service is judged as it is run
                try:
                    with mock.patch.dict(os.environ, self.env, clear=True):  # exactly the environment the test gives the hook process (a variable it took away is not there)
                        out_service, why = hookclient.ask(raw, root)
                finally:
                    filecache.enable(False)
                    messages.reset()
            tree_service = tree(root)
            restore(root, backup)
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


class HookEquivalence(unittest.TestCase):
    def test_every_hook_call_of_the_hook_tests_is_judged_the_same_by_the_service_and_by_a_hook_process(self) -> None:
        modules = [name.strip() for name in os.environ.get("HOOKEQUIV_FILES", "").split(",") if name.strip()] or list(HOOK_TESTS)
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
        if total and served < MOST_SERVED * total:
            problems.append(f"only {served} of {total} calls were judged by the service: the proof is empty\n{summary}")
        if not total:
            problems.append("no hook call was sent: nothing was compared")
        self.assertEqual([], problems, "\n" + "\n".join(problems[:40]) + (f"\n... {len(problems) - 40} more" if len(problems) > 40 else "") + "\n" + summary)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--inner":
        raise SystemExit(inner(sys.argv[2], Path(sys.argv[3])))
    unittest.main()
