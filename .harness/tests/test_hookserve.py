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

from support import HOOK, REPO, HarnessTestCase, make_root, payload, post_tool, pre_tool

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
    """A program that is not the service, on a port. With `hello` (a key) it answers the hello line as a service that has that key would, then reads the request line and runs `behave(connection, request)`; with
    `hello=None` it is a program that knows nothing of the protocol: `behave` gets the first line, whatever it is. `seen` is every line it was sent."""

    def __init__(self, behave: Callable[[socket.socket, Dict[str, Any]], None], hello: Optional[str] = KEY) -> None:
        self.behave = behave
        self.hello = hello
        self.seen: List[Dict[str, Any]] = []
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
                buffer = b""

                def next_line() -> bytes:
                    nonlocal buffer
                    while b"\n" not in buffer:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        buffer += chunk
                    text, _, buffer = buffer.partition(b"\n")
                    return text

                first = next_line()
                request = json.loads(first) if first.strip() else {}
                self.seen.append(request)
                if self.hello is not None:
                    conn.sendall(json.dumps({"hello": hookserve.sign(self.hello, request["nonce"], "hello")}).encode("utf-8") + b"\n")
                    second = next_line()
                    if not second.strip():
                        continue  # the client did not go on: it did not believe the hello
                    request = json.loads(second)
                    self.seen.append(request)
                self.behave(conn, request)
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

    def log_exists(self) -> bool:
        return (self.root / ".harness" / "runtime" / "logs" / "vscode" / f"{SESSION}.jsonl").exists()

    def count(self, session: str = SESSION, root: Optional[Path] = None) -> int:
        """How many records the session has (0 when it has no log yet)."""
        try:
            return len(self.rows(root, session))
        except OSError:
            return 0

    def drain(self) -> None:
        """Wait until the service has nothing more to do with the connections it was given: whatever a late request would still write, it has written."""
        until = time.monotonic() + 10
        while self.service.busy and time.monotonic() < until:
            time.sleep(0.02)
        self.assertEqual(self.service.busy, 0)

    def failed_the_same_way(self, why: Any, data: Optional[Dict[str, Any]] = None) -> None:
        """The service did not answer for `why` (a tag, or a tuple of tags that are the same moment seen from two sides): the call was judged here, the answer is the plain one, it is not the empty answer of a call that
        passes, and it was judged ONCE: one record for one call, none from the service (a call that is begun by the service and again by the hook process counts a refusal twice and may write a card twice)."""
        data = data or REFUSED
        why = why if isinstance(why, tuple) else (why,)
        expected = self.plain(data)
        self.assertEqual(expected.get("permissionDecision"), "deny")
        before = self.count(data["session_id"])
        output, got = self.call(data)
        self.assertIn(got, why)
        self.assertEqual(output, expected)
        self.assertNotEqual(output, {})
        self.drain()
        rows = self.rows(session=data["session_id"])
        self.assertEqual(len(rows) - before, 1, [(row["via"], row["why"]) for row in rows])
        self.assertEqual((rows[-1]["via"], rows[-1]["why"]), ("local", got))

    # --- the service by hand ---------------------------------------------------------------------

    def info(self) -> Dict[str, Any]:
        return json.loads(hookserve.file_of(self.root).read_text(encoding="utf-8"))

    def plant(self, port: int, key: str = KEY, pid: Optional[int] = None, wait: float = 1.0, born: Optional[str] = None) -> None:
        pid = pid or os.getpid()
        hookserve.write_file(hookserve.file_of(self.root), {"v": 2, "port": port, "pid": pid, "born": born if born is not None else hookclient.born(pid), "key": key, "started": "", "wait": wait})

    def set_wait(self, wait: float) -> None:
        data = self.info()
        data["wait"] = wait
        hookserve.write_file(hookserve.file_of(self.root), data)

    def request_of(self, key: Optional[str] = None, sign: bool = True, data: Optional[Dict[str, Any]] = None, **over: Any) -> Dict[str, Any]:
        """A request as a hook process writes it, with `over` changing its fields, signed with the key of the file (or `key`)."""
        request = {"v": 2, "nonce": "a" * 32, "raw": json.dumps(data or ALLOWED), "env": dict(os.environ), "cwd": os.getcwd(), "py": [sys.version_info[0], sys.version_info[1]], "pid": os.getpid(), "deadline": time.time() + 20}
        request.update(over)
        if sign:
            request["mac"] = hookserve.sign(key or self.info()["key"], request["nonce"], hashlib.sha256(hookserve.canonical(request).encode("utf-8")).hexdigest())
        return request

    def states(self, root: Path, session: str = SESSION) -> Dict[str, Any]:
        data = json.loads((root / ".harness" / "runtime" / "state" / "vscode" / f"{session}.json").read_text(encoding="utf-8"))
        data.pop("created_at", None)
        data.pop("updated_at", None)
        return data

    def talk(self, key: Optional[str] = None, sign: bool = True, data: Optional[Dict[str, Any]] = None, hello: bool = True, **over: Any) -> List[Dict[str, Any]]:
        """One conversation with the service, written by hand with `over` changing the fields of the request: the hello first (its answer is checked), then the request; the lines the service answers the request with."""
        found = self.info()
        request = self.request_of(key, sign, data, **over)
        with socket.create_connection(("127.0.0.1", found["port"]), timeout=20) as sock:
            reader = sock.makefile("rb")
            if hello:
                sock.sendall(line({"v": 2, "nonce": request["nonce"]}))
                said = json.loads(reader.readline())
                self.assertEqual(said, {"hello": hookserve.sign(found["key"], request["nonce"], "hello")})
            sock.sendall(line(request))
            return [json.loads(text) for text in reader.read().split(b"\n") if text.strip()]


class FailureTests(Rig):
    """DESIGN 7: every row of the table of what goes wrong, and what the hook process does about it."""

    def test_no_board_no_file(self) -> None:
        self.service.stop()
        self.assertFalse(hookserve.file_of(self.root).exists())
        self.failed_the_same_way("absent")

    def test_a_board_that_ended_without_removing_the_file_is_a_dead_pid(self) -> None:
        done = subprocess.Popen([sys.executable, "-c", "pass"])
        done.wait()
        self.plant(self.info()["port"], self.info()["key"], pid=done.pid, born=self.info()["born"])
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
        fake = Fake(lambda conn, _request: conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n<html>nothing here</html>\n"), hello=None)
        self.addCleanup(fake.close)
        self.plant(fake.port)
        self.failed_the_same_way("reply")
        self.assertEqual([sorted(seen) for seen in fake.seen], [["nonce", "v"]])  # all it was given: the hello

    def test_another_program_that_says_pass_without_the_key_is_not_believed(self) -> None:
        fake = Fake(lambda conn, _request: conn.sendall(line({"ok": True, "output": {}, "mac": "0" * 64})), hello=None)
        self.addCleanup(fake.close)
        self.plant(fake.port)
        self.failed_the_same_way("reply")  # no hello: an answer is not looked at
        self.assertEqual([sorted(seen) for seen in fake.seen], [["nonce", "v"]])

    def test_a_program_that_cannot_sign_the_hello_is_given_nothing_private(self) -> None:
        for number, said in enumerate((hookserve.sign("w" * 64, "a" * 32, "hello"), "", 5, None)):
            fake = Fake(lambda conn, request, said=said: conn.sendall(line({"hello": said if said is not None else hookserve.sign(KEY, request["nonce"], "start")})), hello=None)
            self.addCleanup(fake.close)
            self.plant(fake.port)
            self.failed_the_same_way(("mac", "reply"), refused(f"hello-{number}"))
            self.assertEqual([sorted(seen) for seen in fake.seen], [["nonce", "v"]])  # the environment, the payload and the folder stayed here

    def test_a_program_that_answers_the_hello_of_another_conversation_is_not_believed(self) -> None:
        fake = Fake(lambda conn, request: None, hello=None)
        fake.behave = lambda conn, request: conn.sendall(line({"hello": hookserve.sign(KEY, "f" * 32, "hello")}))  # a good signature of a nonce that is not this one
        self.addCleanup(fake.close)
        self.plant(fake.port)
        self.failed_the_same_way("mac")
        self.assertEqual(len(fake.seen), 1)

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
        real = self.info()
        self.plant(real["port"], key="0" * 64, wait=5)
        self.failed_the_same_way("mac")  # the service answers the hello with its own key: the client sees it is not the one in the file, and sends nothing
        self.plant(real["port"], key=real["key"])
        self.assertEqual(self.talk(key="0" * 64), [{"ok": False, "why": "key"}])  # and a request signed with another key is not judged

    def test_a_service_that_does_not_start_in_time(self) -> None:
        self.set_wait(1.0)
        began = time.monotonic()
        with self.service.judging:  # the service is judging another call: the start line cannot come (the service gives up at the same moment the client does: `late`)
            self.failed_the_same_way(("wait", "late"))
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
        for name in ("TMPDIR", "TEMP", "TMP"):  # the client sends its environment, and the service compares the variables the temp folder is made from, as the system writes them
            self.assertEqual(self.talk(env=dict(os.environ, **{name: "/not/the/temp/folder of this process"})), [{"ok": False, "why": "tmp"}], name)
            without = {key: value for key, value in os.environ.items() if key != name}
            self.assertEqual(self.talk(env=without)[0].get("why") == "tmp", name in os.environ, name)  # a variable that is not there is not the one that is (and both missing is the same)
        same = {key: (os.path.normcase(value) if key == "TMPDIR" else value) for key, value in os.environ.items()}
        self.assertEqual(self.talk(env=same)[0].get("start"), True)
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
        self.assertEqual(self.talk(nonce="b" * 32, key=None, raw=json.dumps(ALLOWED), deadline=time.time() + 20)[0].get("start"), True)  # a good one is served
        self.assertEqual(self.talk(raw=5), [{"ok": False, "why": "request"}])
        self.assertEqual(self.talk(env=[1]), [{"ok": False, "why": "request"}])
        self.assertEqual(self.talk(env={"A": 1}), [{"ok": False, "why": "request"}])
        self.assertEqual(self.talk(v=1), [{"ok": False, "why": "request"}])
        self.assertEqual(self.talk(nonce="c" * 32, hello=True, raw=json.dumps(ALLOWED))[0].get("start"), True)
        self.assertEqual(self.talk(deadline="soon"), [{"ok": False, "why": "request"}])
        with socket.create_connection(("127.0.0.1", self.info()["port"]), timeout=10) as sock:
            sock.sendall(b"{{{ not json\n")
            self.assertEqual(json.loads(sock.recv(4096).decode("utf-8")), {"ok": False, "why": "request"})
        self.assertEqual(self.talk(hello=False, env={}), [{"ok": False, "why": "request"}])  # a request with no hello before it is not read as one (a big one is dropped: the hello may be 1 KB)

    def test_a_hello_that_is_not_one_is_refused_and_a_big_or_slow_one_is_dropped(self) -> None:
        port = self.info()["port"]
        for text in (b'{"v":2,"nonce":"not hex"}\n', b'{"v":2,"nonce":"' + b"a" * 32 + b'","extra":1}\n', b'{"v":1,"nonce":"' + b"a" * 32 + b'"}\n', b"[]\n", b"\n"):
            with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
                sock.sendall(text)
                self.assertEqual(sock.makefile("rb").read(), b'{"ok": false, "why": "request"}\n', text)
        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:  # a line that does not end, bigger than the hello may be: dropped without a word, and nothing was read of it that is kept
            sock.sendall(b"x" * 5000)
            try:
                self.assertEqual(sock.makefile("rb").read(), b"")
            except ConnectionResetError:  # it closed with bytes it had not read: the other side may hear that as a reset
                pass
        with mock.patch.object(hookserve, "HELLO_SECONDS", 0.3), socket.create_connection(("127.0.0.1", port), timeout=10) as sock:  # a client that says nothing
            began = time.monotonic()
            self.assertEqual(sock.makefile("rb").read(), b"")
            self.assertLess(time.monotonic() - began, 5)
        self.assertFalse(self.log_exists())

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
        self.assertEqual(lines[1]["mac"], hookserve.sign(self.info()["key"], "a" * 32, hookserve.canonical(lines[1]["output"])))
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


class LaunchTests(HarnessTestCase):
    """`launch.py` as Copilot starts it (`python -S`: not `-I`, whose `-E` turns off the system Python's bytecode cache on macOS and ignores PYTHONUTF8), on a copy of the engine, with the service of a board on that root."""

    def setUp(self) -> None:
        super().setUp()
        shutil.copytree(REPO / ".harness" / "engine", self.root / ".harness" / "engine", ignore=shutil.ignore_patterns("__pycache__"))
        self.ref = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ref, True)
        make_root(self.ref)
        self.launch = self.root / ".harness" / "engine" / "launch.py"

    def run_launch(self, data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        done = subprocess.run([sys.executable, "-S", str(self.launch)], input=json.dumps(data), text=True, encoding="utf-8", capture_output=True, check=False, env=self.env)
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
        self.assertEqual((data["v"], data["pid"], data["port"]), (2, os.getpid(), service.port))
        self.assertEqual(data["born"], hookclient.born(os.getpid()))
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



class IdentityTests(Rig):
    """The file names the board by the pid AND by when that process was created: a pid that another program has now is not the board (red team F1)."""

    def test_a_live_pid_that_is_another_process_than_the_board_is_not_believed(self) -> None:
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        real = self.info()
        for number, born in enumerate(("mac:1.000000", "linux:5", "nt:5")):  # what the file says of the board is not what the system says of this pid
            self.plant(real["port"], real["key"], pid=other.pid, born=born)
            self.failed_the_same_way("dead", refused(f"pid-{number}"))
        self.plant(real["port"], real["key"], pid=os.getpid(), born="mac:1.000000")  # this very process, which is alive, with a time that is not its own
        self.failed_the_same_way("dead", refused("same-pid"))
        self.plant(real["port"], real["key"], pid=os.getpid(), born=real["born"])
        self.assertEqual(self.call(ALLOWED)[1], "")  # and the right pair is served

    def test_a_system_that_does_not_say_is_a_board_that_is_not_believed_and_is_not_said_to_be_dead(self) -> None:
        with mock.patch.object(hookclient, "lookup", return_value=(None, "born")):
            self.failed_the_same_way("born")  # equivalence N1/red team N7: access denied is not "no such process"
        with mock.patch.object(hookclient, "lookup", return_value=(None, "dead")):
            self.failed_the_same_way("dead", refused("really-dead"))

    def test_a_process_that_is_not_there_is_dead_and_one_that_cannot_be_asked_is_born(self) -> None:
        done = subprocess.Popen([sys.executable, "-c", "pass"])
        done.wait()
        self.assertEqual(hookclient.lookup(done.pid), (None, "dead"))
        self.assertEqual(hookclient.lookup(0), (None, "dead"))
        self.assertEqual(hookclient.lookup(-5), (None, "dead"))
        found, problem = hookclient.lookup(os.getpid())
        self.assertTrue(found)
        self.assertEqual(problem, "")
        self.assertEqual(hookclient.lookup("not a pid"), (None, "born"))  # a call that cannot be made at all is not an answer
        platform = "_born_windows" if os.name == "nt" else "_born_mac" if sys.platform == "darwin" else "_born_linux"
        with mock.patch.object(hookclient, platform, side_effect=PermissionError("denied")):
            self.assertEqual(hookclient.lookup(os.getpid()), (None, "born"))
            self.assertIsNone(hookclient.born(os.getpid()))

    def test_a_file_of_an_older_board_or_without_the_time_is_not_a_file(self) -> None:
        real = self.info()
        for number, change in enumerate(({"v": 1}, {"born": None}, {"born": ""}, {"born": 5}, {"v": "2"})):
            hookserve.write_file(hookserve.file_of(self.root), dict(real, **change))
            self.failed_the_same_way("file", refused(f"old-{number}"))
        hookserve.write_file(hookserve.file_of(self.root), {key: value for key, value in real.items() if key != "born"})
        self.failed_the_same_way("file", refused("no-born"))

    def test_the_time_of_a_process_is_the_same_each_time_and_not_that_of_another(self) -> None:
        mine = hookclient.born(os.getpid())
        self.assertTrue(mine)
        self.assertEqual(hookclient.born(os.getpid()), mine)
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        self.assertNotEqual(hookclient.born(other.pid), mine)
        other.kill()
        other.wait()
        self.assertIsNone(hookclient.born(other.pid))
        for pid in (0, -1, "x", None, True and 10 ** 12):
            self.assertIsNone(hookclient.born(pid))

    def test_a_board_that_cannot_tell_when_it_began_does_not_serve(self) -> None:
        self.service.stop()
        service = hookserve.HookService(self.root, engine=self.watch)
        with mock.patch.object(hookclient, "born", return_value=None), contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(service.start())
        self.assertFalse(hookserve.file_of(self.root).exists())

    def test_the_windows_calls_say_what_they_take_and_give(self) -> None:
        """The Windows branch cannot run here: what can be checked is that every call of it is declared (a pointer-sized handle is cut to an int otherwise, and a 64-bit Windows fails in ways no log shows)."""
        text = (REPO / ".harness" / "engine" / "hookclient.py").read_text(encoding="utf-8")
        for name in ("OpenProcess", "GetExitCodeProcess", "GetProcessTimes", "CloseHandle"):
            self.assertIn(f"kernel.{name}.argtypes", text)
            self.assertIn(f"kernel.{name}.restype", text)
        self.assertIn("get_last_error() == 87", text)  # ERROR_INVALID_PARAMETER is "no such process"; any other reason that OpenProcess fails (access denied, 5) is `born`

    def test_the_client_does_not_load_tempfile(self) -> None:
        tree = ast_of(REPO / ".harness" / "engine" / "hookclient.py")
        self.assertNotIn("tempfile", tree)


def ast_of(path: Path) -> List[str]:
    """The names a file imports."""
    import ast

    found: List[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
    return found


@needs_procenv
class TraceTests(Rig):
    """Each time a hook process uses an answer of the service it writes one line, and the service writes the same nonce in the record of the call: the two can be matched (red team F1)."""

    def trace(self) -> List[Dict[str, Any]]:
        path = self.root / ".harness" / "runtime" / "logs" / "hookclient.jsonl"
        return [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines() if text.strip()] if path.exists() else []

    def test_a_used_answer_has_a_line_and_the_record_has_the_same_nonce(self) -> None:
        for data in (REFUSED, ALLOWED):
            self.assertEqual(self.call(data)[1], "")
        trace, rows = self.trace(), self.rows()
        self.assertEqual(len(trace), 2)
        self.assertEqual(len(rows), 2)
        for one, row in zip(trace, rows):
            self.assertEqual(sorted(one), ["at", "event", "nonce", "session_id"])
            self.assertEqual((one["session_id"], one["event"]), (SESSION, "PreToolUse"))
            self.assertRegex(one["nonce"], r"^[0-9a-f]{32}$")
            self.assertEqual(one["nonce"], row["nonce"])
            self.assertEqual(row["via"], "service")
        self.assertNotEqual(trace[0]["nonce"], trace[1]["nonce"])
        import datetime

        moment = datetime.datetime.fromisoformat(trace[0]["at"])
        self.assertEqual(moment.utcoffset(), datetime.timedelta(0))
        self.assertLess(abs(time.time() - moment.timestamp()), 60)

    def test_a_call_judged_here_has_no_line_and_no_nonce(self) -> None:
        self.service.stop()
        output, why = self.call(REFUSED)
        self.assertEqual(why, "absent")
        self.assertEqual(self.trace(), [])
        self.assertNotIn("nonce", self.rows()[-1])

    def test_a_call_the_service_refused_has_no_line(self) -> None:
        (self.watch / "a.py").write_text("x = 1  # edited\n", encoding="utf-8")
        self.failed_the_same_way("stale")
        self.assertEqual(self.trace(), [])

    def test_a_trace_that_cannot_be_written_changes_nothing(self) -> None:
        (self.root / ".harness" / "runtime" / "logs").mkdir(parents=True, exist_ok=True)
        (self.root / ".harness" / "runtime" / "logs" / "hookclient.jsonl").mkdir()  # a folder where the file should be
        expected = self.plain(REFUSED)
        self.assertEqual(self.call(REFUSED), (expected, ""))

    def test_only_a_call_whose_record_is_certain_is_traced(self) -> None:
        """A line for a call that leaves no row in the session log would be a false alarm in doctor (red team N2): the payload that is no object, one without a session, another event than the three, or an event name that is not spelled as the adapter reads it."""
        (self.root / ".harness" / "runtime" / "logs").mkdir(parents=True, exist_ok=True)
        raws = ("not json", "[1]", json.dumps({"hook_event_name": 5, "session_id": 7}), json.dumps({"session_id": "", "hook_event_name": "PreToolUse"}), json.dumps({"hook_event_name": "PostToolUse", "session_id": "p"}),
                json.dumps({"sessionId": "tr", "transformedPrompt": "x"}), json.dumps({"hookEventName": "PreToolUse", "session_id": "camelname"}), json.dumps({"sessionId": "camel", "hook_event_name": "SessionStart"}),
                json.dumps({"session_id": "snake", "hook_event_name": "UserPromptSubmit"}), json.dumps({"session_id": "pre", "hook_event_name": "PreToolUse"}))
        for number, raw in enumerate(raws):
            hookclient.trace(self.root, f"{number}" * 32, raw)
        self.assertEqual([(row["session_id"], row["event"]) for row in self.trace()], [("camel", "SessionStart"), ("snake", "UserPromptSubmit"), ("pre", "PreToolUse")])
        self.assertEqual(hook.RECORDED, hookclient.TRACED)

    def test_a_trace_is_only_written_for_the_events_of_the_list(self) -> None:
        self.assertEqual(hookclient.TRACED, ("PreToolUse", "UserPromptSubmit", "SessionStart"))
        for data in (post_tool(SESSION, "Read", {"path": "a.txt"}), payload("Stop", SESSION, stop_reason="end_turn")):
            self.assertEqual(self.call(data)[1], "")
        self.assertEqual(self.trace(), [])
        self.drain()
        self.assertTrue(all(row.get("nonce") for row in self.rows()))  # judged by the service: each has its record, with the nonce, all the same

    def test_a_session_of_every_kind_of_call_leaves_a_record_with_the_nonce_for_each_traced_call_and_doctor_finds_no_fault(self) -> None:
        import datetime

        import doctor
        from support import load_payload

        def of(name: str, **over: Any) -> Dict[str, Any]:
            data = load_payload(name)
            for key in ("session_id", "sessionId"):
                if key in data:
                    data[key] = SESSION
            data.update(over)
            return data

        session = [of("SessionStart.json"), of("UserPromptSubmit.json"), of("userPromptTransformed.json"), of("PreToolUse.Read.json"), of("PostToolUse.Read.json"), of("PreToolUse.Bash.json"), of("PostToolUse.Bash.json"),
                   of("PostToolUseFailure.Read.json"), of("SubagentStart.json"), of("SubagentStop.json"), of("Stop.json")]
        for data in session:
            self.assertEqual(self.call(data)[1], "", data.get("hook_event_name"))
        self.drain()
        trace, rows = self.trace(), self.rows()
        self.assertEqual(len(rows), len(session))
        self.assertTrue(all(row.get("nonce") for row in rows))
        self.assertEqual([row["event"] for row in trace], ["SessionStart", "UserPromptSubmit", "PreToolUse", "PreToolUse"])
        self.assertTrue({row["nonce"] for row in trace} <= {row["nonce"] for row in rows})
        report = doctor.Report()
        later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)
        doctor.check_hook_client_trace(report, self.root, later)
        self.assertEqual(report.errors, 0, report.lines)
        self.assertIn("[OK]", "\n".join(report.lines))

    def test_a_call_that_fails_to_be_judged_or_recorded_still_leaves_its_record_with_the_nonce(self) -> None:
        """A read that fails has nothing to tell the agent: its record used to be empty, and an empty record is no row (equivalence N3)."""
        for number, data in enumerate((pre_tool(SESSION, "Read", {"path": "a.txt"}), payload("UserPromptSubmit", SESSION, prompt="hello"), payload("SessionStart", SESSION))):
            before = self.count()
            with mock.patch.object(hook, "process", side_effect=RuntimeError("boom")):
                output, why = self.call(data)
            self.assertEqual(why, "", number)
            self.drain()
            rows = self.rows()
            self.assertEqual(len(rows) - before, 1, number)
            self.assertEqual((rows[-1]["session_id"], rows[-1]["event"], rows[-1]["via"]), (SESSION, data["hook_event_name"], "service"))
            self.assertRegex(rows[-1]["nonce"], r"^[0-9a-f]{32}$")
            self.assertEqual(self.trace()[-1]["nonce"], rows[-1]["nonce"])
        with mock.patch.object(hook.callrecord, "build", side_effect=RuntimeError("no record")):  # the record of a call that was judged cannot be made
            before = self.count()
            self.call(pre_tool(SESSION, "Read", {"path": "b.txt"}))
            self.drain()
            self.assertEqual(self.count() - before, 1)
        self.assertEqual(hook.leftover(json.dumps({"hook_event_name": "Stop", "session_id": "s"})), {})  # a call that is not traced leaves none that it did not leave before
        self.assertEqual(hook.leftover("[]"), {})

    def test_a_call_whose_registry_cannot_be_read_still_has_its_record_with_the_nonce(self) -> None:
        """The observe module is asked through the registry: when that cannot be read the call is refused and the module cannot be asked, and the trace of the hook process would have no record to match (found by the equivalence run)."""
        self.service.stop()
        (self.root / ".harness" / "registry.json").write_text("{ not json", encoding="utf-8")
        self.service = hookserve.HookService(self.root, engine=self.watch)
        self.assertTrue(self.service.start())
        self.addCleanup(self.service.stop)
        output, why = self.call(pre_tool(SESSION, "Read", {"path": "a.txt"}))
        self.assertEqual(why, "")
        self.drain()
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["event"], rows[0]["via"], rows[0]["nonce"]), ("PreToolUse", "service", self.trace()[0]["nonce"]))
        self.assertTrue(rows[0]["error"].startswith("observe: "))
        self.assertNotIn("target", rows[0])

    def test_an_answer_from_a_program_that_is_not_the_board_has_a_line_and_no_record_and_doctor_says_so(self) -> None:
        """The program read the key from the file and answers as a service would: the client takes the answer, and the board's log has nothing with that nonce (red team F1)."""
        import datetime

        import doctor

        fake = Fake(lambda conn, request: (conn.sendall(line(start_of(request, self.info()["key"]))), conn.sendall(line(answer_of(request, {}, self.info()["key"])))), hello=self.info()["key"])
        self.addCleanup(fake.close)
        data = pre_tool("forged-session", "Bash", {"command": "rm -rf /"})
        self.plant(fake.port, key=self.info()["key"])
        output, why = hookclient.ask(json.dumps(data), self.root)
        self.assertEqual((output, why), ({}, ""))  # the answer is taken: only the trace can say it was not the board's
        self.assertEqual(len(self.trace()), 1)
        report = doctor.Report()
        doctor.check_hook_client_trace(report, self.root, datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10))
        self.assertEqual(report.errors, 1, report.lines)
        self.assertIn("[ERROR]", "\n".join(report.lines))


class RaceTests(Rig):
    """A call is judged once, by the service or by the hook process, never by both (equivalence F1)."""

    def slow_differs(self, seconds: float) -> Any:
        real = hookserve.HookService.differs

        def slow(service: Any, request: Dict[str, Any]) -> str:
            time.sleep(seconds)  # a long walk over the files of the engine on a slow computer
            return real(service, request)

        return mock.patch.object(hookserve.HookService, "differs", slow)

    @needs_procenv
    def test_a_service_that_took_too_long_to_begin_does_not_judge_what_the_hook_process_judged(self) -> None:
        self.set_wait(1.0)
        with self.slow_differs(1.6):
            self.failed_the_same_way("wait")  # the hook process gave up after a second and judged (and `failed_the_same_way` counts one record for one call)
            time.sleep(0.2)
        self.drain()
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.states(self.root), self.states(self.ref))  # one refusal counted, as for one judgment (the plain one was judged once, in `failed_the_same_way`)

    @needs_procenv
    def test_a_client_that_closed_the_connection_is_not_served(self) -> None:
        found = self.info()
        gate = threading.Event()
        real = hookserve.HookService.differs

        def held(service: Any, request: Dict[str, Any]) -> str:
            gate.wait(10)
            return real(service, request)

        with mock.patch.object(hookserve.HookService, "differs", held):
            with socket.create_connection(("127.0.0.1", found["port"]), timeout=10) as sock:
                reader = sock.makefile("rb")
                sock.sendall(line({"v": 2, "nonce": "a" * 32}))
                reader.readline()
                sock.sendall(line(self.request_of(data=REFUSED, raw=json.dumps(REFUSED), deadline=time.time() + 30)))
                time.sleep(0.3)  # the service has the request and waits in `differs`
                reader.close()  # (the file object keeps the connection open until it is closed)
            time.sleep(0.2)
            gate.set()
            self.drain()
        self.assertFalse(self.log_exists())
        self.assertFalse(self.state_file(SESSION).exists())

    @needs_procenv
    def test_a_request_with_too_little_time_left_is_not_begun(self) -> None:
        self.assertEqual(self.talk(deadline=time.time() + hookserve.MARGIN / 2, raw=json.dumps(REFUSED)), [{"ok": False, "why": "late"}])
        self.drain()
        self.assertFalse(self.log_exists())
        self.assertEqual(self.talk(deadline=time.time() + 20, raw=json.dumps(REFUSED))[0].get("start"), True)


class TimeTests(Rig):
    """What the hook process waits for, and for how long (Windows review F1, F2; red team F5): it must be able to judge the call itself well before Copilot gives up on the hook."""

    def test_the_limits(self) -> None:
        self.assertEqual((hookclient.CONNECT, hookclient.MOST, hookclient.AFTER), (1.0, 5.0, 20.0))  # after the start line: at most 20 s, however long it took to come (a stuck judgement must leave time for the local one before Copilot's 120 s)
        self.assertFalse(hasattr(hookclient, "TOTAL"))
        seen: List[Any] = []

        def refuse(*args: Any, **kwargs: Any) -> Any:
            seen.append(kwargs.get("timeout", args[1] if len(args) > 1 else None))
            raise OSError("no")

        with mock.patch.object(hookclient.socket, "create_connection", refuse):
            self.assertEqual(hookclient.ask(json.dumps(ALLOWED), self.root), (None, "connect"))
        self.assertEqual(seen, [1.0])

    def test_the_start_line_is_waited_for_at_most_the_cap_whatever_the_file_says(self) -> None:
        fake = Fake(lambda conn, _request: time.sleep(4))
        self.addCleanup(fake.close)
        self.plant(fake.port, wait=600)
        began = time.monotonic()
        with mock.patch.object(hookclient, "MOST", 0.5):
            self.failed_the_same_way("wait")
        self.assertLess(time.monotonic() - began, 3.5)

    def test_the_hello_is_waited_for_at_most_the_cap_too(self) -> None:
        fake = Fake(lambda conn, _request: time.sleep(4), hello=None)
        self.addCleanup(fake.close)
        self.plant(fake.port, wait=600)
        began = time.monotonic()
        with mock.patch.object(hookclient, "MOST", 0.5):
            self.failed_the_same_way("wait")
        self.assertLess(time.monotonic() - began, 3.5)

    def test_the_answer_is_waited_for_at_most_the_limit_after_the_start_line(self) -> None:
        fake = Fake(lambda conn, request: (conn.sendall(line(start_of(request))), time.sleep(5)))
        self.addCleanup(fake.close)
        self.plant(fake.port)
        began = time.monotonic()
        with mock.patch.object(hookclient, "AFTER", 1.5):
            self.failed_the_same_way("lost-after-start")
        self.assertLess(time.monotonic() - began, 4.5)

    def test_the_limit_counts_from_the_start_line_not_from_the_start_of_the_process(self) -> None:
        """A start line that took 1.2 s to come still leaves the whole limit after it (red team F5: 60 s from the start plus a slow hello and start could pass Copilot's 120 s)."""
        def slow_start(conn: socket.socket, request: Dict[str, Any]) -> None:
            time.sleep(1.2)
            conn.sendall(line(start_of(request)))
            time.sleep(1.0)
            conn.sendall(line(answer_of(request, {"fine": True})))

        fake = Fake(slow_start)
        self.addCleanup(fake.close)
        self.plant(fake.port, wait=5)
        with mock.patch.object(hookclient, "AFTER", 1.8):
            self.assertEqual(hookclient.ask(json.dumps(ALLOWED), self.root), ({"fine": True}, ""))


class FloodTests(Rig):
    """A program that opens many connections, or sends big or slow ones, makes the hook processes judge for themselves (slower), never a call pass (red team F4)."""

    def test_connections_over_the_cap_are_closed_at_once(self) -> None:
        self.service.stop()
        with mock.patch.object(hookserve, "SLOTS", 2):
            self.service = hookserve.HookService(self.root, engine=self.watch)
            self.assertTrue(self.service.start())
        self.addCleanup(self.service.stop)
        port = self.info()["port"]
        idle = [socket.create_connection(("127.0.0.1", port), timeout=10) for _ in range(2)]
        self.addCleanup(lambda: [sock.close() for sock in idle])
        time.sleep(0.3)  # both have a place and wait for their hello
        began = time.monotonic()
        with socket.create_connection(("127.0.0.1", port), timeout=10) as over:
            try:
                self.assertEqual(over.recv(10), b"")
            except ConnectionResetError:
                pass
        self.assertLess(time.monotonic() - began, 1.5)
        self.failed_the_same_way(("closed", "wait"))
        for sock in idle:
            sock.close()
        self.drain()
        self.assertEqual(self.call(ALLOWED)[1], "")  # the places are given back

    def test_a_connection_that_never_says_hello_is_let_go(self) -> None:
        with mock.patch.object(hookserve, "HELLO_SECONDS", 0.3):
            with socket.create_connection(("127.0.0.1", self.info()["port"]), timeout=10):
                began = time.monotonic()
                self.drain()
                self.assertLess(time.monotonic() - began, 3)

    def test_the_big_request_line_is_read_only_after_the_hello(self) -> None:
        found = self.info()
        with socket.create_connection(("127.0.0.1", found["port"]), timeout=10) as sock:
            reader = sock.makefile("rb")
            sock.sendall(line({"v": 2, "nonce": "a" * 32}))
            reader.readline()
            sock.sendall(line(self.request_of(raw="x" * 3000000, env={"A": "b" * 3000000}, deadline=time.time() + 30)))  # a big one after the hello is read: it is signed and refused as a request that is no good
            said = json.loads(reader.readline())
        self.assertEqual(said.get("start"), None)
        self.assertEqual(self.count(), 0)

    def test_accepted_sockets_do_not_wait_to_fill_a_packet(self) -> None:
        seen: List[int] = []
        real = hookserve.HookService.serve

        def look(service: Any, sock: socket.socket) -> None:
            seen.append(sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY))
            real(service, sock)

        with mock.patch.object(hookserve.HookService, "serve", look):
            self.talk(deadline=time.time() - 1)
        self.assertTrue(seen and seen[0])


class FileTests(HarnessTestCase):
    def test_the_file_is_written_again_when_windows_refuses_the_replace_for_a_moment(self) -> None:
        real = os.replace
        calls: List[int] = []

        def refusing(source: Any, target: Any) -> None:
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(5, "Access is denied")
            real(source, target)

        path = hookserve.file_of(self.root)
        with mock.patch.object(os, "replace", refusing):
            hookserve.write_file(path, {"a": 1})
        self.assertEqual((len(calls), json.loads(path.read_text(encoding="utf-8"))), (3, {"a": 1}))

    def test_the_start_and_the_pace_measure_do_not_write_the_file_at_the_same_time(self) -> None:
        service = hookserve.HookService(self.root)
        self.assertTrue(service.start())
        self.addCleanup(service.stop)
        errors: List[BaseException] = []
        seen: List[Any] = []

        def write_many() -> None:
            try:
                for _ in range(40):
                    service.write()
                    seen.append(json.loads(hookserve.file_of(self.root).read_text(encoding="utf-8"))["port"])
            except BaseException as error:  # noqa: BLE001
                errors.append(error)

        threads = [threading.Thread(target=write_many) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(set(seen), {service.port})
        self.assertFalse(hookserve.file_of(self.root).with_name("hookserve.json.part").exists())

    def test_the_service_has_the_resolved_root(self) -> None:
        link = Path(tempfile.mkdtemp()) / "link"
        self.addCleanup(shutil.rmtree, link.parent, True)
        try:
            os.symlink(str(self.root), str(link))
        except (OSError, NotImplementedError):
            self.skipTest("no symbolic links here")
        self.assertEqual(hookserve.HookService(link).root, self.root.resolve())

    @needs_procenv
    def test_the_list_of_repositories_is_not_kept_for_a_judgment_of_the_service(self) -> None:
        from core import pinfiles, procenv, targets

        loads: List[int] = []
        real = targets.load

        def counting(root: Path) -> Any:
            loads.append(1)
            return real(root)

        pinfiles._HOMES.clear()
        with mock.patch.object(targets, "load", counting):
            pinfiles.repo_homes(self.root)
            pinfiles.repo_homes(self.root)
            self.assertEqual(len(loads), 1)  # here it is kept for a few seconds (a card looks at every word of a line)
            kept = dict(pinfiles._HOMES)
            with procenv.using(dict(os.environ), os.getcwd()):
                pinfiles.repo_homes(self.root)
                pinfiles.repo_homes(self.root)
            self.assertEqual(len(loads), 3)  # for the service every look is a new one, and it leaves nothing behind
            self.assertEqual(pinfiles._HOMES, kept)
        pinfiles._HOMES.clear()


@needs_procenv
class MixedTests(Rig):
    """Calls through the service and through real hook processes on one session at one moment end as the same calls one after another do (equivalence F4)."""

    def process(self, script: Path, data: Dict[str, Any], origin: str = "") -> Dict[str, Any]:
        env = dict(self.env, HARNESS_ROOT=str(self.root))
        if origin:
            env["HARNESS_HOOK_ORIGIN"] = origin
        done = subprocess.run([sys.executable, "-S", str(script)], input=json.dumps(data), text=True, encoding="utf-8", capture_output=True, check=False, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_the_service_and_hook_processes_on_one_session_at_once(self) -> None:
        self.call(pre_tool("warm-up", "Read", {"path": "a.txt"}))
        self.set_wait(60)
        payloads = [pre_tool(SESSION, "Bash", {"command": f"rm -rf /tmp/mixed-{number}"}) for number in range(12)]
        launch = REPO / ".harness" / "engine" / "launch.py"

        def one(number: int) -> Tuple[str, Dict[str, Any]]:
            data = payloads[number]
            if number % 3 == 0:
                return "client", self.call(data)[0]
            if number % 3 == 1:
                return "launch", self.process(launch, data)
            return "local", self.process(HOOK, data, "local:test")

        with concurrent.futures.ThreadPoolExecutor(12) as pool:
            done = list(pool.map(one, range(12)))
        one_after_another = [hook.answer(json.dumps(data), self.ref) for data in payloads]
        mine, theirs = self.rows(), self.rows(self.ref)
        self.assertEqual((len(mine), len(theirs)), (12, 12))
        self.assertIn("service", {row["via"] for row in mine})  # the launcher and the client were served (or some of them judged here, if the service was busy: both are right, none is missing)
        self.assertEqual(self.states(self.root), self.states(self.ref))
        self.assertEqual(sorted(row["decision"] for row in mine), sorted(row["decision"] for row in theirs))
        words = lambda outputs: sorted(json.dumps(output, sort_keys=True) for output in outputs)  # noqa: E731
        self.assertEqual(words(output for _how, output in done), words(one_after_another))
        self.assertTrue(all(output.get("permissionDecision") in ("ask", "deny") for _how, output in done), done)  # none passes, whoever judged it


class CrossProcessTests(LaunchTests):
    """`launch.py` in a process of its own, with another home, language and folder than the board's: the answer is the one a hook process of its own gives (equivalence F4)."""

    def launch_in(self, data: Dict[str, Any], env: Dict[str, str], cwd: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        done = subprocess.run([sys.executable, "-S", str(self.launch)], input=json.dumps(data), text=True, encoding="utf-8", capture_output=True, check=False, env=dict(self.env, **env), cwd=cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        path = self.root / ".harness" / "runtime" / "logs" / "vscode" / f"{data['session_id']}.jsonl"
        return json.loads(done.stdout), json.loads(path.read_text(encoding="utf-8").splitlines()[-1])

    @needs_procenv
    def test_another_home_language_and_folder(self) -> None:
        self.serving()
        home, repo = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        self.addCleanup(shutil.rmtree, repo, True)
        (repo / "sub").mkdir()
        (repo / ".git").mkdir()
        payloads = [
            ("home-guard", pre_tool("c1", "create_file", {"filePath": str(home / ".copilot-harness" / "integrity" / "x.json"), "content": "x"})),
            ("tilde", pre_tool("c2", "create_file", {"filePath": "~/.copilot-harness/integrity/x.json", "content": "x"})),
            ("relative-git", dict(pre_tool("c3", "create_file", {"filePath": ".git/config", "content": "x"}), cwd="")),
            ("relative-git-dot", dict(pre_tool("c4", "create_file", {"filePath": ".git/config", "content": "x"}), cwd=".")),
            ("terminal-home", pre_tool("c5", "run_in_terminal", {"command": "echo hi > ~/.copilot-harness/integrity/y"})),
            ("terminal-variable", pre_tool("c6", "run_in_terminal", {"command": "echo hi > $HOME/.copilot-harness/integrity/y"})),
            ("terminal-relative", dict(pre_tool("c7", "run_in_terminal", {"command": "rm -rf .git"}), cwd="")),
            ("a-read", pre_tool("c8", "read_file", {"filePath": "a.txt"})),
        ]
        file = hookserve.file_of(self.root)
        kept = file.read_text(encoding="utf-8")
        for language in ("en", "zh"):
            env = {"HOME": str(home), "USERPROFILE": str(home), "HARNESS_LANGUAGE": language}
            for name, data in payloads:
                served, row = self.launch_in(dict(data, session_id=data["session_id"] + language), env, str(repo / "sub"))
                self.assertEqual((name, row["via"], row["why"]), (name, "service", ""))
                file.unlink()  # no board: the same launcher judges here
                try:
                    here, local = self.launch_in(dict(data, session_id=data["session_id"] + language + "-here"), env, str(repo / "sub"))
                finally:
                    file.write_text(kept, encoding="utf-8")
                self.assertEqual((name, local["via"], local["why"]), (name, "local", "absent"))
                self.assertEqual((name, language, served), (name, language, here))


if __name__ == "__main__":
    unittest.main()
