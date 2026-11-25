"""The board's judging service for hook calls (hook speed, 1.8.50): `hookclient.py` (in the hook process), `hookserve.py` (in the board) and `hook.answer` (the one judgment, run by either).

The one rule behind every test here: whatever goes wrong with the service, the call is judged as it is judged without a service. So each failure is checked the same way: what the hook process ends up with (the service's
answer when it is a good one, else its own judgment, as `launch.py` does) equals what a plain `hook.answer` gives for the same call on a root of the same state, and a call that is refused locally is never `{}`.

The service runs in this process, on a temp root, as the board runs it. The tests that need `core.procenv` (the environment and folder of the asking process, for the judgment; another change) are skipped where it is not there.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest import mock

from support import REPO, HarnessTestCase, make_root, pre_tool

import hook
import hookclient
import integrity
from core import filecache
from modules.gate import commands
from modules.task import hookserve

try:
    from core import procenv  # noqa: F401
    HAVE_PROCENV = True
except ImportError:
    HAVE_PROCENV = False
needs_procenv = unittest.skipUnless(HAVE_PROCENV, "core.procenv is not in this tree (another change adds it)")

KEY = "k" * 64
SESSION = "hs-1"
REFUSED = pre_tool(SESSION, "Bash", {"command": "rm -rf /"})  # a call that the gate refuses on a plain root
ALLOWED = pre_tool(SESSION, "Read", {"path": "a.txt"})


def refused(session: str) -> Dict[str, Any]:
    """The same refused call in another session (the gate's breaker counts the refusals of one session)."""
    return pre_tool(session, "Bash", {"command": "rm -rf /"})


class Sink:
    def write(self, _text: str) -> int:
        return 0

    def flush(self) -> None:
        pass


class Fake:
    """A program that is not the service, on a port: it reads the request line and runs `behave(connection, request)`."""

    def __init__(self, behave: Callable[[socket.socket, Dict[str, Any]], None]) -> None:
        self.behave = behave
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.run, daemon=True).start()

    def run(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            try:
                line = b""
                while b"\n" not in line:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    line += chunk
                self.behave(conn, json.loads(line) if line.strip() else {})
            except Exception:  # noqa: BLE001 - a fake that fails is a connection that ends
                pass
            finally:
                conn.close()

    def close(self) -> None:
        self.sock.close()


def line(data: Any) -> bytes:
    return json.dumps(data).encode("utf-8") + b"\n"


def start_of(request: Dict[str, Any], key: str = KEY) -> Dict[str, Any]:
    return {"start": True, "mac": hookserve.sign(key, request["nonce"], "start")}


def answer_of(request: Dict[str, Any], output: Any, key: str = KEY) -> Dict[str, Any]:
    return {"ok": True, "output": output, "mac": hookserve.sign(key, request["nonce"], hookserve.canonical(output))}


class Rig(HarnessTestCase):
    """A root with the service listening on it (as the board runs it), a second root of the same state to judge the same call without the service, and what a hook process does with both."""

    def setUp(self) -> None:
        super().setUp()
        self.ref = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ref, True)
        make_root(self.ref)
        self.watch = self.root / "engine-watch"  # the files whose change makes the service say `stale`: a small tree, not the real engine
        (self.watch / "sub").mkdir(parents=True)
        (self.watch / "a.py").write_text("x = 1\n", encoding="utf-8")
        (self.watch / "sub" / "b.py").write_text("y = 2\n", encoding="utf-8")
        filecache.enable()  # the board keeps what it read until the file changes: the tests run as it does
        self.addCleanup(filecache.enable, False)
        self.service = hookserve.HookService(self.root, engine=self.watch)
        self.assertTrue(self.service.start())
        self.addCleanup(self.service.stop)

    # --- what a hook process does --------------------------------------------------------------

    def call(self, data: Dict[str, Any], root: Optional[Path] = None) -> Tuple[Dict[str, Any], str]:
        """`(output, why)`: what `launch.py` does. The service's answer when it is a good one (why is ""), else the judgment in this process."""
        root = root or self.root
        raw = json.dumps(data)
        output, why = hookclient.ask(raw, root)
        if output is None:
            output = hook.answer(raw, root, origin="local:" + why)
        return output, why

    def plain(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """The judgment without any service, on the root of the same state."""
        return hook.answer(json.dumps(data), self.ref)

    def rows(self, root: Optional[Path] = None, session: str = SESSION) -> List[Dict[str, Any]]:
        path = (root or self.root) / ".harness" / "runtime" / "logs" / "vscode" / f"{session}.jsonl"
        return [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines() if text.strip()]

    def failed_the_same_way(self, why: str, data: Optional[Dict[str, Any]] = None) -> None:
        """The service did not answer for `why`: the call was judged here, the answer is the plain one, and it is not the empty answer of a call that passes."""
        data = data or REFUSED
        expected = self.plain(data)
        self.assertEqual(expected.get("permissionDecision"), "deny")
        output, got = self.call(data)
        self.assertEqual(got, why)
        self.assertEqual(output, expected)
        self.assertNotEqual(output, {})
        row = self.rows(session=data["session_id"])[-1]
        self.assertEqual((row["via"], row["why"]), ("local", why))

    # --- the service by hand ---------------------------------------------------------------------

    def info(self) -> Dict[str, Any]:
        return json.loads(hookserve.file_of(self.root).read_text(encoding="utf-8"))

    def plant(self, port: int, key: str = KEY, pid: Optional[int] = None, wait: float = 1.0) -> None:
        hookserve.write_file(hookserve.file_of(self.root), {"v": 1, "port": port, "pid": pid or os.getpid(), "key": key, "started": "", "wait": wait})

    def set_wait(self, wait: float) -> None:
        data = self.info()
        data["wait"] = wait
        hookserve.write_file(hookserve.file_of(self.root), data)

    def talk(self, key: Optional[str] = None, sign: bool = True, data: Optional[Dict[str, Any]] = None, **over: Any) -> List[Dict[str, Any]]:
        """One request to the service, written by hand with `over` changing its fields; the lines it answers with."""
        found = self.info()
        request = {"v": 1, "nonce": "n" * 32, "raw": json.dumps(data or ALLOWED), "env": dict(os.environ), "cwd": os.getcwd(), "tmp": tempfile.gettempdir(), "py": [sys.version_info[0], sys.version_info[1]], "pid": os.getpid(), "deadline": time.time() + 20}
        request.update(over)
        if sign:
            request["mac"] = hookserve.sign(key or found["key"], request["nonce"], hashlib.sha256(hookserve.canonical(request).encode("utf-8")).hexdigest())
        got: List[Dict[str, Any]] = []
        with socket.create_connection(("127.0.0.1", found["port"]), timeout=20) as sock:
            sock.sendall(line(request))
            buffer = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
            for text in buffer.split(b"\n"):
                if text.strip():
                    got.append(json.loads(text))
        return got


class FailureTests(Rig):
    """DESIGN 7: every row of the table of what goes wrong, and what the hook process does about it."""

    def test_no_board_no_file(self) -> None:
        self.service.stop()
        self.assertFalse(hookserve.file_of(self.root).exists())
        self.failed_the_same_way("absent")

    def test_a_board_that_ended_without_removing_the_file_is_a_dead_pid(self) -> None:
        done = subprocess.Popen([sys.executable, "-c", "pass"])
        done.wait()
        self.plant(self.info()["port"], self.info()["key"], pid=done.pid)
        self.failed_the_same_way("dead")

    def test_a_file_that_is_not_what_the_service_writes(self) -> None:
        for number, text in enumerate(("{ not json", "[]", json.dumps({"v": 1, "port": "x", "pid": os.getpid(), "key": KEY, "wait": 1}), json.dumps({"v": 1, "port": 5, "pid": os.getpid(), "key": "", "wait": 1}))):
            hookserve.file_of(self.root).write_text(text, encoding="utf-8")
            self.failed_the_same_way("file", refused(f"file-{number}"))

    def test_nothing_listens_on_the_port(self) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.plant(port)
        self.failed_the_same_way("connect")

    def test_another_program_on_the_port_that_answers_with_words(self) -> None:
        fake = Fake(lambda conn, _request: conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n<html>nothing here</html>\n"))
        self.addCleanup(fake.close)
        self.plant(fake.port)
        self.failed_the_same_way("reply")

    def test_another_program_that_says_pass_without_the_key_is_not_believed(self) -> None:
        fake = Fake(lambda conn, _request: conn.sendall(line({"ok": True, "output": {}, "mac": "0" * 64})))
        self.addCleanup(fake.close)
        self.plant(fake.port)
        self.failed_the_same_way("reply")  # no start line: an answer is not looked at

    def test_a_start_line_with_a_wrong_mac(self) -> None:
        fake = Fake(lambda conn, request: conn.sendall(line(start_of(request, "w" * 64)) + line(answer_of(request, {}, "w" * 64))))
        self.addCleanup(fake.close)
        self.plant(fake.port)
        self.failed_the_same_way("mac")

    def test_an_answer_with_a_wrong_mac_after_a_right_start(self) -> None:
        fake = Fake(lambda conn, request: conn.sendall(line(start_of(request)) + line(answer_of(request, {}, "w" * 64))))
        self.addCleanup(fake.close)
        self.plant(fake.port)
        self.failed_the_same_way("mac")

    def test_an_answer_whose_output_was_changed_after_it_was_signed(self) -> None:
        def behave(conn: socket.socket, request: Dict[str, Any]) -> None:
            good = answer_of(request, {"permissionDecision": "deny"})
            good["output"] = {}
            conn.sendall(line(start_of(request)) + line(good))

        fake = Fake(behave)
        self.addCleanup(fake.close)
        self.plant(fake.port)
        self.failed_the_same_way("mac")

    def test_an_answer_that_is_not_json(self) -> None:
        fake = Fake(lambda conn, request: conn.sendall(line(start_of(request)) + b"this is not json\n"))
        self.addCleanup(fake.close)
        self.plant(fake.port)
        self.failed_the_same_way("reply")

    def test_an_answer_that_is_json_but_not_an_object_or_has_no_object_for_output(self) -> None:
        for number, second in enumerate((b"[1, 2]\n", line({"ok": True, "output": [1], "mac": "x"}), line({"ok": True, "output": "{}", "mac": "x"}), line({"output": {}}))):
            fake = Fake(lambda conn, request, second=second: conn.sendall(line(start_of(request)) + second))
            self.addCleanup(fake.close)
            self.plant(fake.port)
            self.failed_the_same_way("reply", refused(f"shape-{number}"))

    def test_the_wrong_key(self) -> None:
        self.plant(self.info()["port"], key="0" * 64, wait=5)
        self.failed_the_same_way("key")

    def test_a_service_that_does_not_start_in_time(self) -> None:
        self.set_wait(1.0)
        began = time.monotonic()
        with self.service.judging:  # the service is judging another call: the start line cannot come
            self.failed_the_same_way("wait")
        self.assertLess(time.monotonic() - began, 10)

    def test_a_program_that_never_answers(self) -> None:
        fake = Fake(lambda conn, _request: time.sleep(4))
        self.addCleanup(fake.close)
        self.plant(fake.port)
        self.failed_the_same_way("wait")

    def test_the_connection_closed_before_the_start_line(self) -> None:
        fake = Fake(lambda conn, _request: None)
        self.addCleanup(fake.close)
        self.plant(fake.port)
        self.failed_the_same_way("closed")

    def test_the_connection_closed_after_the_start_line(self) -> None:
        fake = Fake(lambda conn, request: conn.sendall(line(start_of(request))))
        self.addCleanup(fake.close)
        self.plant(fake.port)
        self.failed_the_same_way("lost-after-start")

    def test_a_service_that_began_and_could_not_finish(self) -> None:
        fake = Fake(lambda conn, request: conn.sendall(line(start_of(request)) + line({"ok": False, "why": "boom"})))
        self.addCleanup(fake.close)
        self.plant(fake.port)
        self.failed_the_same_way("lost-after-start")

    def test_an_exception_in_the_service_before_the_start_line(self) -> None:
        with mock.patch.object(hookserve.HookService, "differs", side_effect=RuntimeError("boom")):
            self.failed_the_same_way("error:RuntimeError")

    @needs_procenv
    def test_an_exception_while_judging_is_refused_as_without_a_service(self) -> None:
        with mock.patch.object(hook, "process", side_effect=RuntimeError("boom")):  # `hook.answer` answers as it does when a guardrail cannot decide
            expected = self.plain(REFUSED)
            output, why = self.call(REFUSED)
        self.assertEqual(why, "")  # the service judged, and its answer is signed
        self.assertEqual(output, expected)
        self.assertEqual(output.get("permissionDecision"), "deny")
        self.assertEqual(self.rows()[-1]["via"], "service")

    @needs_procenv
    def test_hook_answer_itself_raising_ends_the_connection_and_the_hook_process_judges(self) -> None:
        expected = self.plain(REFUSED)
        real = hook.answer
        seen: List[int] = []

        def once(*args: Any, **kwargs: Any) -> Any:
            if not seen:
                seen.append(1)
                raise RuntimeError("boom")
            return real(*args, **kwargs)

        with mock.patch.object(hook, "answer", once):
            output, why = self.call(REFUSED)
        self.assertEqual(why, "lost-after-start")
        self.assertEqual(output, expected)
        self.assertNotEqual(output, {})

    def test_code_on_disk_that_is_not_the_code_in_the_board(self) -> None:
        (self.watch / "a.py").write_text("x = 1  # edited\n", encoding="utf-8")
        self.failed_the_same_way("stale")

    @needs_procenv
    def test_a_new_and_a_removed_file_of_the_engine_are_stale_too(self) -> None:
        (self.watch / "sub" / "new.py").write_text("z = 3\n", encoding="utf-8")
        self.failed_the_same_way("stale", refused("new-file"))
        (self.watch / "sub" / "new.py").unlink()
        self.assertEqual(self.call(ALLOWED)[1], "")  # back as it was loaded (the same files, sizes and times): the service is right again
        (self.watch / "sub" / "b.py").unlink()
        self.failed_the_same_way("stale", refused("removed-file"))

    def test_the_registry_and_the_hook_configuration_are_watched(self) -> None:
        registry = self.root / ".harness" / "registry.json"
        registry.write_text(registry.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.failed_the_same_way("stale", refused("registry"))
        hooks = self.root / ".github" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "harness.json").write_text("{}", encoding="utf-8")
        self.failed_the_same_way("stale", refused("hook-config"))

    def test_another_temp_folder_or_python_is_not_served(self) -> None:
        self.assertEqual(self.talk(tmp="/not/the/temp/folder of this process"), [{"ok": False, "why": "tmp"}])
        self.assertEqual(self.talk(py=[2, 7]), [{"ok": False, "why": "python"}])
        self.assertEqual(self.talk(py="3.12"), [{"ok": False, "why": "python"}])

    def test_a_request_that_came_too_late_is_not_judged(self) -> None:
        self.assertEqual(self.talk(deadline=time.time() - 1), [{"ok": False, "why": "late"}])
        self.assertFalse(self.log_exists())  # nothing was judged or written for it

    def test_a_request_that_waited_for_the_lock_past_its_deadline(self) -> None:
        with self.service.judging:
            self.assertEqual(self.talk(deadline=time.time() + 0.5), [{"ok": False, "why": "late"}])

    @needs_procenv
    def test_a_request_that_is_not_signed_or_not_well_formed(self) -> None:
        self.assertEqual(self.talk(sign=False), [{"ok": False, "why": "key"}])
        self.assertEqual(self.talk(key="0" * 64), [{"ok": False, "why": "key"}])
        self.assertEqual(self.talk(nonce="another one", key=None, raw=json.dumps(ALLOWED), deadline=time.time() + 20)[0].get("start"), True)  # a good one is served
        self.assertEqual(self.talk(raw=5), [{"ok": False, "why": "request"}])
        self.assertEqual(self.talk(env=[1]), [{"ok": False, "why": "request"}])
        self.assertEqual(self.talk(env={"A": 1}), [{"ok": False, "why": "request"}])
        self.assertEqual(self.talk(v=2), [{"ok": False, "why": "request"}])
        self.assertEqual(self.talk(deadline="soon"), [{"ok": False, "why": "request"}])
        with socket.create_connection(("127.0.0.1", self.info()["port"]), timeout=10) as sock:
            sock.sendall(b"{{{ not json\n")
            self.assertEqual(json.loads(sock.recv(4096).decode("utf-8")), {"ok": False, "why": "request"})

    def test_without_procenv_the_service_refuses(self) -> None:
        import core

        saved = core.__dict__.pop("procenv", None)
        try:
            with mock.patch.dict(sys.modules, {"core.procenv": None}):
                self.assertEqual(self.talk(), [{"ok": False, "why": "procenv"}])
                self.failed_the_same_way("procenv")
        finally:
            if saved is not None:
                core.procenv = saved  # type: ignore[attr-defined]

    def log_exists(self) -> bool:
        return (self.root / ".harness" / "runtime" / "logs" / "vscode" / f"{SESSION}.jsonl").exists()


class GuardrailFileTests(Rig):
    """A guardrail file that is not the one the person accepted: the service runs the same check as a hook process, and refuses the same."""

    def accept_and_change(self, relative: str) -> None:
        for root in (self.root, self.ref):
            self.assertTrue(integrity.accept(root)["files"] > 0)
            path = root / relative
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    @needs_procenv
    def test_a_changed_policy_is_refused_by_the_service(self) -> None:
        self.accept_and_change(".harness/policies/gate.json")  # policies are not watched for `stale`: this is judged by the service
        expected = self.plain(REFUSED)
        self.assertIn("deny", expected.get("permissionDecision", ""))
        output, why = self.call(REFUSED)
        self.assertEqual((why, output), ("", expected))
        self.assertEqual(self.rows()[-1]["via"], "service")
        self.assertEqual(self.call(ALLOWED)[0], self.plain(ALLOWED))  # a read stays free, as in the hook process

    def test_a_changed_registry_is_refused_too(self) -> None:
        self.accept_and_change(".harness/registry.json")  # watched: the service says `stale`, the hook process judges and refuses
        self.failed_the_same_way("stale")


@needs_procenv
class FreshnessTests(Rig):
    """The service keeps the engine, not what the person changes: the next answer follows the policy, the registry and admin mode."""

    def both(self, action: Callable[[Path], None]) -> None:
        for root in (self.root, self.ref):
            action(root)

    def test_the_happy_path(self) -> None:
        for data in (REFUSED, ALLOWED):
            expected = self.plain(data)
            output, why = self.call(data)
            self.assertEqual((why, output), ("", expected))
        row = self.rows()[-1]
        self.assertEqual((row["via"], row["why"]), ("service", ""))
        self.assertEqual(self.rows(self.ref)[-1]["via"], "local")

    def test_the_record_names_the_hook_process_that_asked(self) -> None:
        lines = self.talk(pid=424242, data=ALLOWED, raw=json.dumps(ALLOWED))
        self.assertEqual(lines[0]["start"], True)
        self.assertEqual(lines[1]["ok"], True)
        self.assertEqual(lines[1]["mac"], hookserve.sign(self.info()["key"], "n" * 32, hookserve.canonical(lines[1]["output"])))
        row = self.rows()[-1]
        self.assertEqual((row["pid"], row["via"]), (424242, "service"))

    def test_the_language_is_the_one_of_the_process_that_asked(self) -> None:
        for root in (self.root, self.ref):
            integrity.accept(root)
            path = root / ".harness" / "policies" / "gate.json"
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        said = {}
        for language in ("en", "zh"):
            with mock.patch.dict(os.environ, {"HARNESS_LANGUAGE": language}):
                said[language] = hook.answer(json.dumps(REFUSED), self.ref)["permissionDecisionReason"]
            lines = self.talk(env=dict(os.environ, HARNESS_LANGUAGE=language), raw=json.dumps(REFUSED))
            self.assertEqual(lines[1]["output"]["permissionDecisionReason"], said[language], language)
        self.assertNotEqual(said["en"], said["zh"])

    def test_a_policy_changed_between_two_calls(self) -> None:
        data = pre_tool(SESSION, "Bash", {"command": "echo freshness-check"})
        self.assertEqual(self.call(data), (self.plain(data), ""))
        self.assertEqual(self.call(data)[0], {})
        override = json.dumps({"terminal": {"deny+": [{"pattern": "freshness-check", "why": "no fresh checks"}]}})
        self.both(lambda root: (root / ".harness" / "policies" / "gate.override.json").write_text(override, encoding="utf-8"))
        expected = self.plain(data)
        self.assertEqual(expected.get("permissionDecision"), "deny")
        output, why = self.call(data)
        self.assertEqual((why, output), ("", expected))  # the service itself, not a hook process, gives the new answer

    def test_the_registry_changed_between_two_calls(self) -> None:
        first = self.call(REFUSED)
        self.assertEqual(first, (self.plain(REFUSED), ""))

        def switch_off(root: Path) -> None:
            path = root / ".harness" / "registry.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["modules"]["gate"]["enabled"] = False
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        self.both(switch_off)
        expected = self.plain(REFUSED)
        output, why = self.call(REFUSED)
        self.assertEqual(why, "stale")  # the registry is part of what was loaded: the hook process judges
        self.assertEqual(output, expected)
        self.assertNotEqual(output, first[0])

    def test_admin_mode_switched_on_between_two_calls(self) -> None:
        data = pre_tool(SESSION, "create_file", {"filePath": str(self.root / ".harness" / "policies" / "gate.json"), "content": "x"})
        data["cwd"] = str(self.root)
        mine = dict(data)
        theirs = dict(data, cwd=str(self.ref), tool_input={"filePath": str(self.ref / ".harness" / "policies" / "gate.json"), "content": "x"})
        self.assertEqual(self.call(mine)[0].get("permissionDecision"), "deny")
        self.assertEqual(hook.answer(json.dumps(theirs), self.ref).get("permissionDecision"), "deny")
        for root in (self.root, self.ref):
            commands.admin_switch_on(root, SESSION, reader=lambda question: question.split("输入 ")[1].split("（")[0], interactive=True, out=Sink())
        expected = hook.answer(json.dumps(theirs), self.ref)
        self.assertEqual(expected.get("permissionDecision"), None)
        output, why = self.call(mine)
        self.assertEqual((why, output), ("", expected))


@needs_procenv
class ConcurrencyTests(Rig):
    def test_ten_hooks_of_one_session_at_once_end_as_ten_one_after_another(self) -> None:
        self.call(pre_tool("warm-up", "Read", {"path": "a.txt"}))  # the first call loads the modules of the engine: it is not what is measured here
        self.set_wait(60)
        one_after_another = [hook.answer(json.dumps(REFUSED), self.ref) for _ in range(10)]
        with concurrent.futures.ThreadPoolExecutor(10) as pool:
            done = list(pool.map(lambda _n: self.call(REFUSED), range(10)))
        self.assertEqual([why for _output, why in done], [""] * 10)  # every one was judged by the service
        words = lambda outputs: sorted(json.dumps(output, sort_keys=True) for output in outputs)  # noqa: E731 - the breaker changes its words after some refusals, so the order matters not, the set does
        self.assertEqual(words(output for output, _why in done), words(one_after_another))
        mine, theirs = self.rows(), self.rows(self.ref)
        self.assertEqual((len(mine), len(theirs)), (10, 10))
        self.assertEqual(sorted(row["decision"] for row in mine), sorted(row["decision"] for row in theirs))
        self.assertEqual({row["via"] for row in mine}, {"service"})
        self.assertEqual(self.states(self.root), self.states(self.ref))

    def states(self, root: Path) -> Dict[str, Any]:
        data = json.loads((root / ".harness" / "runtime" / "state" / "vscode" / f"{SESSION}.json").read_text(encoding="utf-8"))
        data.pop("created_at", None)
        data.pop("updated_at", None)
        return data


class LaunchTests(HarnessTestCase):
    """`launch.py` as Copilot starts it (`python -I -S`), on a copy of the engine, with the service of a board on that root."""

    def setUp(self) -> None:
        super().setUp()
        shutil.copytree(REPO / ".harness" / "engine", self.root / ".harness" / "engine", ignore=shutil.ignore_patterns("__pycache__"))
        self.ref = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ref, True)
        make_root(self.ref)
        self.launch = self.root / ".harness" / "engine" / "launch.py"

    def run_launch(self, data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        done = subprocess.run([sys.executable, "-I", "-S", str(self.launch)], input=json.dumps(data), text=True, encoding="utf-8", capture_output=True, check=False, env=self.env)
        self.assertEqual(done.returncode, 0, done.stderr)
        path = self.root / ".harness" / "runtime" / "logs" / "vscode" / f"{SESSION}.jsonl"
        return json.loads(done.stdout), json.loads(path.read_text(encoding="utf-8").splitlines()[-1])

    def serving(self) -> hookserve.HookService:
        service = hookserve.HookService(self.root)
        self.assertTrue(service.start())
        self.addCleanup(service.stop)
        return service

    @needs_procenv
    def test_the_service_answers_and_the_record_names_the_hook_process(self) -> None:
        self.serving()
        output, row = self.run_launch(REFUSED)
        self.assertEqual(output, hook.answer(json.dumps(REFUSED), self.ref))
        self.assertEqual((row["via"], row["why"]), ("service", ""))
        self.assertNotEqual(row["pid"], os.getpid())  # the hook process that asked, not the board

    def test_no_board(self) -> None:
        output, row = self.run_launch(REFUSED)
        self.assertEqual(output, hook.answer(json.dumps(REFUSED), self.ref))
        self.assertEqual((row["via"], row["why"]), ("local", "absent"))

    def test_a_hookclient_that_cannot_be_loaded_is_a_service_that_does_not_answer(self) -> None:
        expected = hook.answer(json.dumps(REFUSED), self.ref)
        client = self.root / ".harness" / "engine" / "hookclient.py"
        client.write_text("def broken(:\n", encoding="utf-8")
        output, row = self.run_launch(REFUSED)
        self.assertEqual((output, row["why"]), (expected, "client:SyntaxError"))
        client.unlink()
        shutil.rmtree(self.ref)
        make_root(self.ref)
        shutil.rmtree(self.root / ".harness" / "runtime" / "logs")
        output, row = self.run_launch(REFUSED)
        self.assertEqual((output, row["why"]), (expected, "client:FileNotFoundError"))

    def test_the_launcher_is_still_small_and_the_client_has_no_engine_import(self) -> None:
        text = (REPO / ".harness" / "engine" / "hookclient.py").read_text(encoding="utf-8")
        for name in ("from core", "import core", "from modules", "import modules", "import hook\n", "from adapters", "import adapters"):
            self.assertNotIn(name, text)


class ServiceLifeTests(HarnessTestCase):
    def test_the_file_is_private_and_goes_when_the_service_stops(self) -> None:
        service = hookserve.HookService(self.root)
        self.assertTrue(service.start())
        path = hookserve.file_of(self.root)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((data["v"], data["pid"], data["port"]), (1, os.getpid(), service.port))
        self.assertEqual(len(data["key"]), 64)
        self.assertGreaterEqual(data["wait"], 3)
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with socket.create_connection(("127.0.0.1", service.port), timeout=5) as sock:
            self.assertEqual(sock.getsockname()[0], "127.0.0.1")
        service.stop()
        self.assertFalse(path.exists())
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", service.port), timeout=2)

    def test_a_file_that_is_another_boards_stays_when_this_one_stops(self) -> None:
        service = hookserve.HookService(self.root)
        self.assertTrue(service.start())
        path = hookserve.file_of(self.root)
        other = json.loads(path.read_text(encoding="utf-8"))
        other["pid"] = os.getpid() + 1
        path.write_text(json.dumps(other), encoding="utf-8")
        service.stop()
        self.assertTrue(path.exists())

    def test_it_listens_on_the_local_address_only_and_never_reuses_a_port(self) -> None:
        service = hookserve.HookService(self.root)
        self.assertTrue(service.start())
        self.addCleanup(service.stop)
        self.assertEqual(service.server.server_address[0], "127.0.0.1")
        self.assertFalse(hookserve.Listener.allow_reuse_address)

    def test_a_service_that_cannot_start_leaves_the_board_alone(self) -> None:
        with mock.patch.object(hookserve.Listener, "server_bind", side_effect=OSError("no port")), contextlib.redirect_stderr(io.StringIO()):
            service = hookserve.HookService(self.root)
            self.assertFalse(service.start())
        self.assertFalse(hookserve.file_of(self.root).exists())

    def test_the_wait_grows_with_the_pace_factor(self) -> None:
        (self.root / ".harness" / "runtime").mkdir(parents=True, exist_ok=True)
        (self.root / ".harness" / "runtime" / "pace.json").write_text(json.dumps({"factor": 4.0}), encoding="utf-8")
        from core import pace

        pace.forget(self.root)
        service = hookserve.HookService(self.root)
        self.assertTrue(service.start())
        self.addCleanup(service.stop)
        self.assertEqual(json.loads(hookserve.file_of(self.root).read_text(encoding="utf-8"))["wait"], 12.0)

    def test_the_board_setting(self) -> None:
        from modules.task import boardserve

        self.assertTrue(boardserve.settings(self.root)["hook_service"])
        (self.root / ".harness" / "policies" / "task.override.json").write_text(json.dumps({"board": {"hook_service": False}}), encoding="utf-8")
        self.assertFalse(boardserve.settings(self.root)["hook_service"])


if __name__ == "__main__":
    unittest.main()
