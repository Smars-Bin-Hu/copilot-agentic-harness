"""Evidence (1.7.3): every saved run of a task has one number, E<n>, whoever ran it and whichever file holds it; the page lists them with where they are cited."""

from __future__ import annotations

import unittest

from test_tasklife import BASE, LifeCase

from modules.task import evidence, runrecord, testdefects, testrecord
from modules.task.common import CommandError


class EvidenceCase(LifeCase):
    def setUp(self) -> None:
        super().setUp()
        self.new("job", "rca")
        self.job = self.root / BASE / "job"
        (self.job / "RUNS" / "DEV").mkdir(parents=True)
        self.given = self.job / "RUNS" / "DEV" / "given.txt"
        self.given.write_text("count\n-----\n2310\n", encoding="utf-8")

    def record(self, env: str = "DEV", **extra):
        return runrecord.record(self.root, "job", env, str(self.given), **extra)


class RunTests(EvidenceCase):
    def test_a_run_by_the_agent_is_numbered_and_marked_as_its_own_in_any_kind_of_task(self) -> None:
        first = self.record(run_by="agent")
        self.assertEqual((first["evidence_id"], first["run_by"], first["run"]), ("E1", "agent", 1))
        self.assertIn("[E1]", first["next"])
        self.assertNotIn("screenshot", " ".join(first["warnings"]).lower())  # the agent's run needs no picture
        text = (self.job / "RUNS" / "DEV" / "results.md").read_text(encoding="utf-8")
        self.assertIn("## Run 1 (E1)", text)
        self.assertIn("<!-- evidence E1 by agent at ", text)
        self.assertIn("### As the agent saved them", text)
        self.assertIn("2310", text)
        second = self.record("IST", run_by="the user, this morning")
        self.assertEqual((second["evidence_id"], second["run_by"]), ("E2", "person"))  # one counter for the task, whoever ran it
        self.assertIn("### As the user gave them", (self.job / "RUNS" / "IST" / "results.md").read_text(encoding="utf-8"))
        self.assertEqual(self.data("job")["evidence_n"], 2)
        self.assertEqual(testrecord.last_run((self.job / "RUNS" / "DEV" / "results.md").read_text(encoding="utf-8")), 1)  # the number in the heading does not break the count of runs
        self.assertEqual(self.record(run_by="agent")["run"], 2)

    def test_the_listing_knows_each_run_and_where_it_is_cited(self) -> None:
        self.record(run_by="agent")
        self.record("IST")
        (self.job / "LOG.md").write_text("- 2026-11-05: 2,310 rows [E1]\n", encoding="utf-8")
        (self.job / "RCA.md").write_text("# RCA\n\nThe count was 2,310 [E1]; see also [E1] and [E9].\n", encoding="utf-8")
        found = evidence.listing(self.root, f"{BASE}/job")
        self.assertEqual([(item["id"], item["env"], item["by"], item["kind"], item["run"], item["file"]) for item in found],
                         [("E1", "DEV", "agent", "run", 1, "RUNS/DEV/results.md"), ("E2", "IST", "person", "run", 1, "RUNS/IST/results.md")])
        self.assertEqual(found[0]["cited_in"], ["LOG.md", "RCA.md"])
        self.assertEqual(found[1]["cited_in"], [])
        self.assertTrue(found[0]["at"].startswith("20"))

    def test_a_results_file_from_before_the_numbers_is_left_out_and_breaks_nothing(self) -> None:
        (self.job / "RUNS" / "DEV" / "results.md").write_text("# Run results: DEV\n\n## Run 1\n\nRun by: the user.\n", encoding="utf-8")
        self.assertEqual(evidence.listing(self.root, f"{BASE}/job"), [])
        found = self.record(run_by="agent")
        self.assertEqual((found["run"], found["evidence_id"]), (2, "E1"))
        self.assertEqual([item["id"] for item in evidence.listing(self.root, f"{BASE}/job")], ["E1"])


class WindowTests(EvidenceCase):
    """1.7.8: the listing carries each run's command (laid out) and output, for the window of a citation; the page turns [E7] into a chip."""

    def test_the_listing_reads_the_command_and_the_output_of_each_run(self) -> None:
        ran = self.job / "RUNS" / "DEV" / "ran.txt"
        ran.write_text('sqlcmd -S h,1433 -E -h -1 -Q "SELECT COUNT(*) FROM dbo.t"\n', encoding="utf-8")
        self.record(run_by="agent", ran_file=str(ran))
        found = evidence.listing(self.root, f"{BASE}/job")[0]
        self.assertEqual(found["command"], 'sqlcmd -S h,1433 -E -h -1 -Q "SELECT COUNT(*) FROM dbo.t"')
        self.assertEqual(found["layout"]["program"], "sqlcmd")
        self.assertEqual((found["output"], found["output_cut"]), ("count\n-----\n2310", False))
        self.assertIn("agent", found["run_by"].lower())
        self.given.write_text("x" * 25000, encoding="utf-8")
        self.record("IST")
        second = evidence.listing(self.root, f"{BASE}/job")[1]
        self.assertEqual((len(second["output"]), second["output_cut"], second["command"], second["layout"]), (20000, True, "", None))
        self.assertEqual(second["output_view"]["kind"], "text")
        rows = "id\n--\n" + "\n".join(str(i) for i in range(500)) + "\n"
        self.given.write_text(rows * 4, encoding="utf-8")  # 4 result sets, 2000 rows, well past the text cap
        third = self.record(run_by="agent")
        view = evidence.listing(self.root, f"{BASE}/job")[2]["output_view"]
        self.assertEqual((len(view["sets"]), view["rows"], view["sets"][0]["total"], len(view["sets"][0]["rows"])), (4, 2000, 500, 200))  # the tables come from the whole output

    def test_the_output_is_laid_out_for_the_window(self) -> None:
        self.given.write_text("id  name\n--- -----\n1   a\n2   b\n\n(2 rows affected)\n", encoding="utf-8")
        self.record(run_by="agent")
        found = evidence.listing(self.root, f"{BASE}/job")[0]["output_view"]
        self.assertEqual((found["kind"], found["sets"][0]["columns"], found["sets"][0]["rows"], found["notes"][0]["text"]), ("tables", ["id", "name"], [["1", "a"], ["2", "b"]], "(2 rows affected)"))
        from modules.task import taskhtml

        desk = (taskhtml.WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn('["table", "text"].map((mode) =>', desk)  # Table / Text
        self.assertIn('const ids = [...view.sets.map((_set, index) => "set" + index), ...(view.notes.length ? ["notes"] : [])];', desk)  # one tab per result set, the notes
        self.assertIn(".out-table thead th{position:sticky;top:0", (taskhtml.WEB / "desk.css").read_text(encoding="utf-8"))
        self.assertIn(".out-table{max-height:min(55vh,560px)}", (taskhtml.WEB / "desk.css").read_text(encoding="utf-8"))  # inside .cmd-scroll: both ways

    def test_the_page_draws_chips_and_the_window(self) -> None:
        from core import messages
        from modules.task import taskhtml

        desk = (taskhtml.WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn('const CITED = /\\[(E\\d+)\\]/g;', desk)
        self.assertIn('if (span.t === "text") return withEvidence(span.v);', desk)
        self.assertIn('class: "ev" + (item ? (item.by === "agent" ? " agent" : "") : " missing")', desk)
        self.assertIn('open.addEventListener("click", () => { view.close(); openRun(item); });', desk)
        self.assertIn('runPick["file:" + item.file] = item.run;', desk)  # the Files tab opens the file at that run (hand test B90-c)
        self.assertIn('event.preventDefault(); event.stopPropagation(); if (item) evidenceWindow(item);', desk)  # a chip inside a link opens the window only
        self.assertIn(".ev.missing{border-color:var(--bad)", (taskhtml.WEB / "desk.css").read_text(encoding="utf-8"))
        en, zh = messages.table("en"), messages.table("zh")
        for key in ("desk.evidence.tip", "desk.evidence.missing", "desk.evidence.see", "desk.evidence.open", "desk.evidence.output", "desk.evidence.nooutput"):
            self.assertIn(key, en, key)
            self.assertIn(key, zh, key)


class TestRunTests(LifeCase):
    def test_a_test_run_takes_the_same_counter_and_is_listed_as_a_test_run(self) -> None:
        self.new("job", "test")
        folder = self.root / BASE / "job"
        folder.joinpath("TEST-GUIDE.md").write_text("# Guide\n\n## DEV\n\nrun\n\n## IST\n\nrun\n", encoding="utf-8")
        (folder / "TEST").mkdir(exist_ok=True)
        given = folder / "TEST" / "given.txt"
        given.write_text("ok\n", encoding="utf-8")
        (folder / "RUNS" / "DEV").mkdir(parents=True)
        look = folder / "RUNS" / "DEV" / "given.txt"
        look.write_text("12 rows\n", encoding="utf-8")
        first = runrecord.record(self.root, "job", "DEV", str(look), run_by="agent")  # a look-up in a test task: allowed now, same counter
        self.assertEqual(first["evidence_id"], "E1")
        second = testrecord.record(self.root, "job", "DEV", str(given), ["c::ok::PASS"])
        self.assertEqual((second["evidence_id"], second["verdict"]), ("E2", "PASS"))
        text = folder.joinpath("TEST", "results-DEV.md").read_text(encoding="utf-8")
        self.assertIn("## Run 1 (E2)", text)
        self.assertIn("**Verdict for DEV: PASS**", text)
        found = evidence.listing(self.root, f"{BASE}/job")
        self.assertEqual([(item["id"], item["kind"], item["env"], item["file"]) for item in found], [("E1", "run", "DEV", "RUNS/DEV/results.md"), ("E2", "test", "DEV", "TEST/results-DEV.md")])
        self.assertEqual(testdefects.verdicts(self.root, f"{BASE}/job")["DEV"][0], "PASS")  # the verdict is still read from the file
        with self.assertRaises(CommandError):
            testrecord.record(self.root, "job", "DEV", str(given), ["c::ok::PASS"], run_by="agent")  # a test run by the agent still needs the grant


if __name__ == "__main__":
    unittest.main()
