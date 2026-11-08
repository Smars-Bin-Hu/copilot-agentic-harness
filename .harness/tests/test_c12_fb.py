"""1.7.38, the fixes after the real-task test C12 (TB-01 ... TB-19). The tests of the tasks themselves are with the code they test; the small ones that cross files are here."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401 - the engine on sys.path

ENGINE = Path(__file__).resolve().parents[1] / "engine"
WEB = ENGINE / "modules" / "task" / "web"
NODE = shutil.which("node")


def run_node(script: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as folder:
        file = Path(folder) / "check.js"
        file.write_text(script, encoding="utf-8")
        return subprocess.run([NODE, str(file)], capture_output=True, text=True, check=False)


def between(source: str, start: str, end: str) -> str:
    return source[source.index(start): source.index(end)]


@unittest.skipUnless(NODE, "node is not installed")
class ApprovedCardTests(unittest.TestCase):
    def test_a_command_that_has_run_takes_its_green_card_away_at_once_and_the_card_never_falls_back_to_tell_the_agent(self) -> None:
        """C12 TB-02: Approve while the agent waits. The agent ran the command in two seconds; the green card then said "Tell the agent to run it" for four more."""
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        source = between(desk, "  const toldCodes = new Set();", "  function approvedCard() {")
        script = r"""
const assert = require("assert");
const TELL_MINUTES = 10;
const approvedCalls = new Map();
""" + source + r"""
const T0 = 1_000_000;
approvedCalls.set("AB12CD", {at: T0, heard: "wait", title: "x"});
pruneApproved(new Set(), T0 + 500);        // the first poll: the entry is not listed yet (it may be a moment behind): the card stays
assert.strictEqual(approvedCalls.has("AB12CD"), true);
pruneApproved(new Set(["AB12CD"]), T0 + 1500);  // listed: seen
assert.strictEqual(approvedCalls.has("AB12CD"), true);
pruneApproved(new Set(), T0 + 3300);       // the agent ran it: gone from the list: the card goes now, not at 6 s
assert.strictEqual(approvedCalls.has("AB12CD"), false);
assert.strictEqual(seenCodes.has("AB12CD"), false);
// never listed at all (run before the first poll): kept for the 6 seconds, then dropped
approvedCalls.set("EF34AB", {at: T0, heard: "", title: "y"});
pruneApproved(new Set(), T0 + 5000);
assert.strictEqual(approvedCalls.has("EF34AB"), true);
pruneApproved(new Set(), T0 + 6500);
assert.strictEqual(approvedCalls.has("EF34AB"), false);
// a page with no list (a saved copy) drops nothing before the approval runs out
approvedCalls.set("ZZ99ZZ", {at: T0, heard: "", title: "z"});
pruneApproved(null, T0 + 60000);
assert.strictEqual(approvedCalls.has("ZZ99ZZ"), true);
pruneApproved(null, T0 + TELL_MINUTES * 60000 + 1);
assert.strictEqual(approvedCalls.has("ZZ99ZZ"), false);
"""
        done = run_node(script)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_answer_to_approve_says_whether_the_agent_waited_and_the_card_uses_it(self) -> None:
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn('data.result.agent === "wait" ? "wait" : ""', desk)
        self.assertIn("approvedCalls.get(code).heard", desk)


if __name__ == "__main__":
    unittest.main()
