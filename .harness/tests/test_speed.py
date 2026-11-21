"""`harness speed` (core/speed.py): the run of the parts, the kept runs, the verdict rules and the text."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401 - puts the engine on the path

from core import messages, pace, speed


def stats(median: float, n: int = 30) -> dict:
    return {"n": n, "median_ms": median, "p90_ms": median * 2}


def group(calls: int, model: float, first: float, hook: float, tool: float, share: dict) -> dict:
    return {"calls": calls, "model": stats(model), "first_token": stats(first), "hook": stats(hook), "tool": stats(tool), "share": share}


EMPTY = {"calls": 0, "model": stats(0, 0), "first_token": stats(0, 0), "hook": stats(0, 0), "tool": stats(0, 0), "share": {}}


def result(groups: dict, host: dict = None, network: dict = None, start_ms: float = 300.0) -> dict:
    return {
        "history": {"sessions": 5, "prompts": 40, "groups": {"1": EMPTY, "2-3": EMPTY, "4+": EMPTY, **groups},
                    "hook_start": {"copilot_ms": start_ms + 80, "own_ms": 80.0, "start_ms": start_ms, "sessions": 3}},
        "host": host or {"process": {"python_ms": 40.0, "shell_ms": 10.0}, "cpu": {"busy_pct": 20.0, "cores": 8}, "memory": {"total_mb": 16384, "used_mb": 8000, "free_mb": 8384}, "top": []},
        "network": network or {"host": "api.example.test", "proxy": "", "dns_ms": 3.0, "proxy_ms": None, "connect_ms": 20.0, "tls_ms": 40.0, "cert": "", "error": ""},
    }


class Speak:
    def speak(self, language: str) -> None:
        before = os.environ.get(messages.ENVIRONMENT)
        os.environ[messages.ENVIRONMENT] = language
        messages.reset()

        def back() -> None:
            if before is None:
                os.environ.pop(messages.ENVIRONMENT, None)
            else:
                os.environ[messages.ENVIRONMENT] = before
            messages.reset()

        self.addCleanup(back)  # type: ignore[attr-defined]


class RunTests(Speak, unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / ".harness" / "policies").mkdir(parents=True)
        pace.forget()
        self.addCleanup(pace.forget)
        self.speak("en")

    def parts(self, **over):
        parts = {"history": lambda root, days: {"days": days, "groups": {}}, "host": lambda root: {"cpu": {"busy_pct": 5.0}},
                 "network": lambda root, host: {"host": host}, "vscode": lambda root: [{"at": "x", "seconds": 95.0}]}
        parts.update(over)
        return parts

    def test_a_part_that_fails_is_reported_and_the_others_still_run(self) -> None:
        def broken(root, days):
            raise OSError("no record")

        found = speed.collect(self.root, 3, self.parts(history=broken))
        self.assertIn("OSError: no record", found["history"]["error"])
        self.assertEqual(found["host"]["cpu"]["busy_pct"], 5.0)
        self.assertEqual(found["network"]["host"], speed.HOST)
        self.assertEqual(found["vscode"]["starts"][0]["seconds"], 95.0)
        self.assertEqual(found["verdict"]["key"], "speed.verdict.few")

    def test_the_policy_sets_the_host_and_the_days_and_a_bad_value_is_the_default(self) -> None:
        policy = self.root / ".harness" / "policies" / "task.json"
        policy.write_text(json.dumps({"speed": {"host": "copilot.example.test", "days": 3}}), encoding="utf-8")
        found = speed.collect(self.root, None, self.parts())
        self.assertEqual((found["network"]["host"], found["history"]["days"]), ("copilot.example.test", 3))
        policy.write_text(json.dumps({"speed": {"host": 7, "days": 900}}), encoding="utf-8")
        self.assertEqual(speed.settings(self.root), {"host": speed.HOST, "days": speed.DAYS})

    def test_runs_are_kept_the_one_before_is_shown_and_old_ones_go(self) -> None:
        self.assertIsNone(speed.previous(self.root))
        with mock.patch.object(speed, "collect", side_effect=lambda root, days: {"at": "2026-11-21T10:00:00Z", "n": 1}):
            first = speed.run(self.root)
        self.assertIsNone(first["before"])
        self.assertTrue(Path(first["kept"]).is_file())
        with mock.patch.object(speed, "collect", side_effect=lambda root, days: {"at": "2026-11-21T10:05:00Z", "n": 2}):
            second = speed.run(self.root)
        self.assertEqual(second["before"]["n"], 1)
        for minute in range(40):
            speed.save(self.root, {"at": f"2026-11-22T10:{minute:02d}:00Z"})
        kept = sorted(speed.folder(self.root).glob("*.json"))
        self.assertEqual(len(kept), speed.KEEP_RUNS)
        self.assertTrue(kept[-1].name.startswith("20261122T1039"))

    def test_a_broken_kept_run_is_skipped(self) -> None:
        speed.save(self.root, {"at": "2026-11-21T10:00:00Z", "n": 1})
        (speed.folder(self.root) / "20991231T000000.json").write_text("{", encoding="utf-8")
        self.assertEqual(speed.previous(self.root)["n"], 1)


class VerdictTests(Speak, unittest.TestCase):
    def setUp(self) -> None:
        self.speak("en")

    def test_too_few_calls_says_so(self) -> None:
        found = speed.verdict(result({"1": group(5, 2000, 900, 300, 500, {"model": 0.7, "tool": 0.2, "hook": 0.1})}))
        self.assertEqual(found["key"], "speed.verdict.few")
        self.assertEqual(found["values"], {"calls": 5, "least": speed.MIN_CALLS})

    def test_the_busiest_group_with_enough_calls_is_judged(self) -> None:
        found = speed.verdict(result({"1": group(50, 2000, 900, 300, 500, {"model": 0.7, "tool": 0.2, "hook": 0.1}),
                                      "4+": group(10, 9000, 900, 3000, 500, {"model": 0.1, "tool": 0.1, "hook": 0.8})}))
        self.assertEqual((found["key"], found["values"]["group"]), ("speed.verdict.model", "one agent alone"))  # 4+ has 10 calls: not enough

    def test_model_time_is_the_server_unless_a_new_connection_is_a_large_part_of_the_first_word(self) -> None:
        busy = {"2-3": group(40, 2500, 1000, 300, 500, {"model": 0.66, "tool": 0.25, "hook": 0.09})}
        self.assertEqual(speed.verdict(result(busy))["key"], "speed.verdict.model")
        slow = {"host": "api.example.test", "proxy": "proxy.test:9000", "dns_ms": 3.0, "proxy_ms": 5.0, "connect_ms": 150.0, "tls_ms": 200.0, "error": ""}
        found = speed.verdict(result(busy, network=slow))
        self.assertEqual(found["key"], "speed.verdict.network")
        self.assertEqual((found["values"]["network"], found["values"]["first"]), ("350 ms", "1.0 s"))

    def test_hooks_that_take_most_of_the_time_name_the_start_of_processes(self) -> None:
        found = speed.verdict(result({"1": group(60, 2000, 900, 400, 500, {"model": 0.6, "tool": 0.3, "hook": 0.1}),
                                      "4+": group(80, 2200, 900, 3100, 600, {"model": 0.35, "tool": 0.15, "hook": 0.5})}, start_ms=2800))
        self.assertEqual(found["key"], "speed.verdict.hook")
        self.assertEqual(found["values"], {"group": "4 or more agents at once", "share": 50, "median": "3.1 s", "start": "2.8 s"})
        self.assertEqual(found["notes"][0]["key"], "speed.note.grew")
        self.assertEqual(found["notes"][0]["values"]["was"], "400 ms")

    def test_the_tools(self) -> None:
        found = speed.verdict(result({"2-3": group(30, 1000, 500, 100, 4000, {"model": 0.2, "tool": 0.75, "hook": 0.05})}))
        self.assertEqual(found["key"], "speed.verdict.tool")

    def test_notes_on_what_is_wrong_now(self) -> None:
        host = {"process": {"python_ms": 1600.0}, "cpu": {"busy_pct": 92.0}, "memory": {"total_mb": 16384, "free_mb": 900}}
        network = {"host": "api.example.test", "error": "407 Proxy Authentication Required"}
        found = speed.verdict(result({}, host=host, network=network))
        self.assertEqual([note["key"] for note in found["notes"]], ["speed.note.cpu", "speed.note.memory", "speed.note.start", "speed.note.network"])

    def test_nothing_at_all(self) -> None:
        found = speed.verdict({})
        self.assertEqual((found["key"], found["notes"]), ("speed.verdict.few", []))


class TextTests(Speak, unittest.TestCase):
    def full(self) -> dict:
        found = result({"1": group(60, 2000, 900, 400, 500, {"model": 0.6, "tool": 0.3, "hook": 0.1}),
                        "4+": group(80, 2200, 900, 3100, 600, {"model": 0.35, "tool": 0.15, "hook": 0.5})}, start_ms=2800)
        found.update({"at": "2026-11-21T10:00:00Z", "pace": {"factor": 1.0}, "days": 7, "vscode": {"starts": [{"seconds": 180.4}, {"seconds": 95}]}, "kept": "/x/run.json"})
        found["host"]["top"] = [{"name": "Code Helper", "cpu_pct": 12.4}]
        found["verdict"] = speed.verdict(found)
        found["before"] = {"host": {"process": {"python_ms": 1500.0}}}
        return found

    def test_the_text_has_the_verdict_the_numbers_and_the_run_before(self) -> None:
        self.speak("en")
        text = speed.render(self.full())
        self.assertIn("Verdict: with 4 or more agents at once, 50% of the time is the hooks", text)
        self.assertIn("a hook grew from 400 ms with one agent to 3.1 s with 4 or more agents at once", text)
        self.assertIn("Python 40 ms (before 1.5 s)", text)
        self.assertIn("Code Helper 12 %", text)
        self.assertIn("180 s, 95 s", text.replace(" and ", ", "))
        self.assertIn("Kept in /x/run.json", text)

    def test_chinese(self) -> None:
        self.speak("zh")
        text = speed.render(self.full())
        self.assertIn("结论：同时 4 个以上 agent 时，50% 的时间是 hook", text)
        self.assertIn("（上次 1.5 s）", text)
        self.assertIn("一次 hook：从 1 个 agent 时的 400 ms 变成同时 4 个以上 agent 时的 3.1 s", text)

    def test_an_empty_run_still_reads(self) -> None:
        self.speak("en")
        text = speed.render({"verdict": speed.verdict({})})
        self.assertIn("not enough history yet", text)
        self.assertIn("no record yet", text)

    def test_seconds(self) -> None:
        self.assertEqual([speed.seconds_text(value) for value in (None, 45.2, 999.4, 1234.5)], ["—", "45 ms", "999 ms", "1.2 s"])


if __name__ == "__main__":
    unittest.main()
