"""`core.speedhost`: what is slow on this computer now. The arithmetic is pure; the Windows system calls run only on Windows."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import support  # noqa: F401 - puts the engine on the path

from core import speedhost


class PureTests(unittest.TestCase):
    def test_busy_pct_from_filetime_numbers(self) -> None:
        # idle 1.0 s of 4.0 s total elapsed: 75 % busy
        self.assertEqual(speedhost.busy_pct((10.0, 100.0), (11.0, 104.0)), 75.0)
        self.assertEqual(speedhost.busy_pct((0.0, 0.0), (20_000_000 / 1e7, 20_000_000 / 1e7)), 0.0)
        self.assertIsNone(speedhost.busy_pct((5.0, 50.0), (5.0, 50.0)))
        self.assertEqual(speedhost.busy_pct((0.0, 0.0), (9.0, 4.0)), 0.0)  # clamped

    def test_shares_are_of_the_whole_machine(self) -> None:
        before = {1: ("Code.exe", 10.0, 100.0), 2: ("Code.exe", 5.0, 50.0), 3: ("gone.exe", 1.0, 1.0)}
        after = {1: ("Code.exe", 11.0, 110.0), 2: ("Code.exe", 5.0, 60.0), 4: ("new.exe", 0.4, 7.0)}
        rows = {r["name"] + str(i): r for i, r in enumerate(speedhost.shares(before, after, 2.0, 4))}
        self.assertAlmostEqual(rows["Code.exe0"]["cpu_pct"], 12.5)  # 1 s of 8 core-seconds
        self.assertAlmostEqual(rows["Code.exe1"]["cpu_pct"], 0.0)
        self.assertAlmostEqual(rows["new.exe2"]["cpu_pct"], 5.0)  # started inside the sample: from zero
        self.assertEqual(len(rows), 3)  # the ended one is gone
        self.assertEqual(speedhost.shares(before, after, 0.0, 4), [])
        self.assertEqual(speedhost.shares(before, after, 2.0, 0), [])

    def test_pid_reuse_with_other_name_counts_from_zero(self) -> None:
        rows = speedhost.shares({1: ("a", 100.0, 1.0)}, {1: ("b", 1.0, 1.0)}, 1.0, 1)
        self.assertAlmostEqual(rows[0]["cpu_pct"], 100.0)

    def test_group_and_top_five(self) -> None:
        rows = [{"name": "Code.exe", "cpu_pct": 3.0, "mem_mb": 100}, {"name": "Code.exe", "cpu_pct": 4.5, "mem_mb": 200.4}]
        rows += [{"name": f"p{i}", "cpu_pct": float(i), "mem_mb": 10} for i in range(1, 8)]
        top = speedhost.group_top(rows)
        self.assertEqual(len(top), 5)
        self.assertEqual(top[1], {"name": "p7", "cpu_pct": 7.0, "mem_mb": 10, "count": 1})
        code = [t for t in top if t["name"] == "Code.exe"][0]
        self.assertEqual((code["cpu_pct"], code["mem_mb"], code["count"]), (7.5, 300, 2))
        self.assertEqual([t["name"] for t in top], ["Code.exe", "p7", "p6", "p5", "p4"])
        self.assertEqual(speedhost.group_top([]), [])
        self.assertEqual(speedhost.group_top([{"name": None, "cpu_pct": None, "mem_mb": None}])[0]["name"], "?")

    def test_parse_ps(self) -> None:
        text = "  12.0  2048 /Applications/Code Helper.app/Contents/MacOS/Code Helper\n   0.0 100 /sbin/launchd\nbad line\n  x y z\n"
        rows = speedhost.parse_ps(text, 4)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["name"], "Code Helper")
        self.assertAlmostEqual(rows[0]["cpu_pct"], 3.0)
        self.assertAlmostEqual(rows[0]["mem_mb"], 2.0)
        self.assertEqual(rows[1]["name"], "launchd")

    def test_mem_dict(self) -> None:
        self.assertEqual(speedhost.mem_dict(8 * 1048576, 3 * 1048576), {"total_mb": 8, "used_mb": 5, "free_mb": 3})
        self.assertEqual(speedhost.mem_dict(1048576, 5 * 1048576)["used_mb"], 0)


class StartTests(unittest.TestCase):
    def test_median_of_three_and_calls(self) -> None:
        calls = []
        ticks = iter([0, 0.1, 1, 1.5, 2, 2.3])  # 100 ms, 500 ms, 300 ms per start

        def run(args, timeout):
            calls.append((list(args), timeout))
            return SimpleNamespace(returncode=0)

        self.assertEqual(speedhost.time_starts(["x"], 30, run, lambda: next(ticks)), 300.0)
        self.assertEqual(len(calls), 3)

    def test_failures_count_for_nothing(self) -> None:
        def boom(args, timeout):
            raise OSError("no")

        self.assertIsNone(speedhost.time_starts(["x"], 30, boom, lambda: 0.0))
        self.assertIsNone(speedhost.time_starts(["x"], 30, lambda a, t: SimpleNamespace(returncode=1), lambda: 0.0))

    def test_collect_starts_six_processes_at_most(self) -> None:
        calls = []

        def run(args, timeout):
            calls.append(args)
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as folder, mock.patch.object(speedhost, "SAMPLE_S", 0.0):
            found = speedhost.collect(Path(folder), run=run)
        self.assertEqual(len(calls), 6)
        self.assertEqual(sum(1 for c in calls if c[0] == sys.executable), 3)
        self.assertEqual(set(found), {"platform", "process", "cpu", "memory", "top"})
        self.assertIsNotNone(found["process"]["python_ms"])

    def test_a_failing_piece_leaves_the_others(self) -> None:
        def boom():
            raise RuntimeError("x")

        mem = {"total_mb": 1, "used_mb": 0, "free_mb": 1}
        out = speedhost.snapshot(4, sleep=lambda s: None, read=(boom, boom, lambda: mem))
        self.assertEqual(out["memory"], mem)
        self.assertIsNone(out["cpu"]["busy_pct"])
        self.assertEqual(out["top"], [])
        ticks = iter([0.0, 2.0])
        procs = iter([{1: ("a", 0.0, 5.0)}, {1: ("a", 1.0, 5.0)}])
        cpus = iter([(0.0, 0.0), (4.0, 8.0)])
        out = speedhost.snapshot(2, sleep=lambda s: None, clock=lambda: next(ticks), read=(lambda: next(cpus), lambda: next(procs), lambda: mem))
        self.assertEqual(out["cpu"]["busy_pct"], 50.0)
        self.assertEqual(out["top"], [{"name": "a", "cpu_pct": 25.0, "mem_mb": 5, "count": 1}])


class LiveTests(unittest.TestCase):
    def test_real_numbers_in_sane_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = speedhost.collect(Path(folder))
        self.assertIn(found["platform"], ("windows", "mac", "linux"))
        for key in ("python_ms", "shell_ms"):
            self.assertTrue(0 < found["process"][key] < 30000, found)
        self.assertTrue(0 <= found["cpu"]["busy_pct"] <= 100, found)
        self.assertGreaterEqual(found["cpu"]["cores"], 1)
        mem = found["memory"]
        self.assertTrue(0 < mem["total_mb"] and 0 <= mem["free_mb"] <= mem["total_mb"] and 0 <= mem["used_mb"] <= mem["total_mb"], found)
        self.assertTrue(1 <= len(found["top"]) <= 5, found)
        for row in found["top"]:
            self.assertTrue(row["name"] and row["cpu_pct"] >= 0 and row["mem_mb"] >= 0 and row["count"] >= 1, row)

    @unittest.skipUnless(sys.platform == "win32", "Windows system calls")
    def test_windows_calls(self) -> None:
        win = speedhost._Win()
        idle, total = win.cpu_times()
        self.assertTrue(0 <= idle <= total)
        self.assertGreater(win.memory()["total_mb"], 0)
        self.assertTrue(win.processes())


if __name__ == "__main__":
    unittest.main()
