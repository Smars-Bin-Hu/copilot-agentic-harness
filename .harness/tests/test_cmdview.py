"""The layout of a command for the small window of the task page (1.7.7), and the facts a company pack says to show beside it."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401 - puts the engine on the path

from modules.task import cmdview


class LayoutTests(unittest.TestCase):
    def test_a_query_tool_line_is_program_options_and_a_block(self) -> None:
        found = cmdview.layout('sqlcmd -S sql-dev.example.local,1433 -E -h -1 -W -Q "SET NOCOUNT ON; SELECT status FROM dbo.job_log WHERE job_name = N\'x\'"')
        self.assertEqual(found["program"], "sqlcmd")
        kinds = [(line["kind"], line["text"], line.get("value")) for line in found["lines"]]
        self.assertEqual(kinds[:4], [("program", "sqlcmd", None), ("option", "-S", "sql-dev.example.local,1433"), ("flag", "-E", None), ("option", "-h", "-1")])
        self.assertEqual(kinds[4], ("flag", "-W", None))
        self.assertEqual(kinds[5], ("option", "-Q", ""))
        self.assertEqual(kinds[6][0], "block")
        self.assertIn("SELECT status FROM dbo.job_log", kinds[6][1])
        self.assertIsNone(found["script"])

    def test_escaped_quotes_inside_a_quoted_value_stay_and_a_short_quoted_value_is_a_plain_value(self) -> None:
        found = cmdview.layout('harness wait --run "sqlcmd -Q \\"SELECT 1\\"" --until "DONE" --every 30')
        lines = found["lines"]
        self.assertEqual(lines[1], {"kind": "arg", "text": "wait"})
        self.assertEqual(lines[2]["kind"], "option")
        self.assertEqual(lines[2]["value"], 'sqlcmd -Q "SELECT 1"')
        self.assertEqual(lines[3], {"kind": "option", "text": "--until", "value": "DONE", "quoted": True})  # quoted: Copy the query takes this value when there is no block
        self.assertEqual(lines[4], {"kind": "option", "text": "--every", "value": "30"})
        self.assertEqual(cmdview.layout("")["lines"], [])

    def test_a_file_the_command_reads_is_shown_from_the_task_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "DEV" / "_manual").mkdir(parents=True)
            (folder / "DEV" / "_manual" / "load.sql").write_text("SET NOCOUNT ON;\nINSERT INTO t VALUES (1);\n", encoding="utf-8")
            found = cmdview.layout("sqlcmd -S h -E -i DEV/_manual/load.sql -v Day=1", folder)
            self.assertEqual((found["script"]["path"], found["script"]["lines"], found["script"]["cut"]), ("DEV/_manual/load.sql", 2, False))
            self.assertIn("INSERT INTO t", found["script"]["text"])
            self.assertIsNone(cmdview.layout("sqlcmd -i ../../etc/passwd.sql", folder)["script"])  # outside the task: not read
            self.assertIsNone(cmdview.layout("sqlcmd -i DEV/missing.sql", folder)["script"])

    def test_the_facts_come_from_the_packs_show_patterns(self) -> None:
        show = {"server": r"-S\s+([^\s,]+)", "port": r"-S\s+[^\s,]+,(\d+)", "bad": "(", "database": r"-d\s+(\S+)"}
        found = cmdview.facts("sqlcmd -S sql-dev.example.local,1433 -E -Q x", show)
        self.assertEqual(found, {"server": "sql-dev.example.local", "port": "1433"})
        self.assertEqual(cmdview.facts("sqlcmd -S h -Q x", None), {})


if __name__ == "__main__":
    unittest.main()
