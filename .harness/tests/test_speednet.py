"""`harness speed` network and VS Code parts: `core.speednet`."""

from __future__ import annotations

import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401 - puts the engine on the path

from core import speednet


def fake_proxy(reply: bytes):
    """A local TCP server: reads the CONNECT header, answers `reply`, closes. Returns (port, stop)."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    server.settimeout(0.2)
    done = threading.Event()

    def loop() -> None:
        while not done.is_set():
            try:
                conn, _ = server.accept()
            except (socket.timeout, OSError):
                continue
            try:
                conn.settimeout(2)
                conn.recv(4096)
                conn.sendall(reply)
            except OSError:
                pass
            finally:
                conn.close()

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()

    def stop() -> None:
        done.set()
        thread.join(2)
        server.close()

    return server.getsockname()[1], stop


class NetTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def run_with(self, proxy: str, **kw):
        with mock.patch.object(speednet.launchenv, "detect_proxy", return_value=proxy), mock.patch.object(speednet.pace, "scaled", return_value=3.0):
            return speednet.collect(self.root, "localhost", **kw)

    def test_proxy_200_then_tls_fails(self) -> None:
        port, stop = fake_proxy(b"HTTP/1.1 200 Connection established\r\n\r\n")
        self.addCleanup(stop)
        out = self.run_with(f"127.0.0.1:{port}")
        self.assertEqual(out["proxy"], f"127.0.0.1:{port}")
        for key in ("dns_ms", "proxy_ms", "connect_ms"):
            self.assertIsNotNone(out[key], key)
        self.assertIsNone(out["tls_ms"])
        self.assertTrue(out["error"])
        self.assertLessEqual(len(out["error"]), 200)

    def test_proxy_407(self) -> None:
        port, stop = fake_proxy(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
        self.addCleanup(stop)
        out = self.run_with(f"127.0.0.1:{port}")
        self.assertIsNotNone(out["proxy_ms"])
        self.assertIsNone(out["connect_ms"])
        self.assertIsNone(out["tls_ms"])
        self.assertIn("407 Proxy Authentication Required", out["error"])

    def test_no_proxy_injected_connect(self) -> None:
        calls = []

        def connect(address, timeout):
            calls.append(address)
            raise OSError("refused")

        out = self.run_with("", connect=connect)
        self.assertEqual(out["proxy"], "")
        self.assertIsNone(out["proxy_ms"])
        self.assertIsNone(out["connect_ms"])
        self.assertEqual(calls, [("localhost", 443)])  # a step that failed is not tried again
        self.assertIn("refused", out["error"])

    def test_no_proxy_real_listener_non_tls(self) -> None:
        port, stop = fake_proxy(b"nope\r\n\r\n")
        self.addCleanup(stop)
        out = self.run_with("", port=port)
        self.assertIsNotNone(out["connect_ms"])
        self.assertIsNone(out["tls_ms"])
        self.assertTrue(out["error"])

    def test_never_raises(self) -> None:
        with mock.patch.object(speednet.launchenv, "detect_proxy", side_effect=RuntimeError("boom")):
            out = speednet.collect(self.root, "localhost")
        self.assertIn("boom", out["error"])


class VscodeTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_empty(self) -> None:
        self.assertEqual(speednet.vscode_starts(self.root), [])

    def test_keeps_newest_ten_newest_first(self) -> None:
        for i in range(13):
            speednet.record_vscode_start(self.root, float(i))
        got = speednet.vscode_starts(self.root)
        self.assertEqual([x["seconds"] for x in got], [float(i) for i in range(12, 2, -1)])
        self.assertIn("at", got[0])

    def test_broken_file(self) -> None:
        speednet.record_vscode_start(self.root, 1.0)
        speednet._file(self.root).write_text("{nope", encoding="utf-8")
        self.assertEqual(speednet.vscode_starts(self.root), [])
        speednet.record_vscode_start(self.root, 2.0)  # a broken file is replaced
        self.assertEqual([x["seconds"] for x in speednet.vscode_starts(self.root)], [2.0])

    def test_bad_value_and_never_raises(self) -> None:
        speednet.record_vscode_start(self.root, "x")  # type: ignore[arg-type]
        speednet.record_vscode_start(self.root, -1)
        self.assertEqual(speednet.vscode_starts(self.root), [])
        speednet.record_vscode_start(Path("/nonexistent-dir/x\0y"), 1.0)

    def test_not_in_runs_folder(self) -> None:
        speednet.record_vscode_start(self.root, 1.0)
        self.assertFalse(list((speednet._file(self.root).parent / "speed").glob("*.json")))


if __name__ == "__main__":
    unittest.main()
