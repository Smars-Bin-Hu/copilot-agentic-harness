"""1.7.38, the last fixes after the verification of C12 (RC-G1 ... RC-5). The tests of the tasks themselves are with the code they test; the small ones that cross files are here."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from support import pre_tool, use_packs
from taskcase import NAME, SESSION, TASK, TaskCase

from test_gatereview import GateCase, deny

from core import approvals, clip, connections, logs, messages, pinfiles, reach, systems
from core.paths import utc_now
from modules.gate import external, inputfiles, rules
from modules.task import boardserve, common, gatereview, ready, taskdesk, taskinsight, tasktrace

SERVER = "sqlcmd -S localhost,14332 -C -d AcmeDW"
SCRIPT = f"{TASK}/DEV/_manual/x.sql"


class ScriptFileTests(TaskCase):
    """RC-G1: a script file a call names as its input (`sqlcmd -i file`) is judged by what it holds, with the same words as a `-Q` text: a drop is refused (an opened connection does not change that), a write is
    held, a file of reads only runs, and a file the gate cannot judge is held."""

    def setUp(self) -> None:
        super().setUp()
        use_packs(self.root, "sqlserver")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {
            "acmedw-dev": {"type": "sqlserver", "env": "dev", "host": "localhost", "port": "14332", "auth": "sql"},
            "acmedw-qat": {"type": "sqlserver", "env": "qat", "host": "localhost", "port": "14330", "auth": "sql"}}}), encoding="utf-8")
        self.new()
        self.board = boardserve.Board(self.root, False, 8797, ["task allow", "approve-action", "dismiss action"])

    def script(self, text: str = "select 1;\n", name: str = "x.sql", encoding: str = "utf-8") -> str:
        path = self.root / TASK / "DEV" / "_manual" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
        return f"{TASK}/DEV/_manual/{name}"

    def term(self, command: str) -> Dict[str, Any]:
        data = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def pending(self) -> int:
        return len(approvals.pending(self.root, 10, file=approvals.ACTIONS))

    def refused(self, command: str, file: str = "") -> str:
        """The call is refused, with the line of a refused statement in a file (`file` is named in it), and nothing waits for the person."""
        before = self.pending()
        out = self.term(command)
        self.assertEqual(out.get("permissionDecision"), "deny", command)
        self.assertEqual(self.pending(), before, f"refused, not held: nothing to approve for {command}")
        reason = out["permissionDecisionReason"]
        if file:
            self.assertIn(f"`{file}`", reason, command)  # the line names the file that holds the refused statement
        return reason

    def held(self, command: str) -> str:
        before = self.pending()
        out = self.term(command)
        self.assertEqual(out.get("permissionDecision"), "deny", command)
        self.assertEqual(self.pending(), before + 1, f"held on a card: {command}")
        return out["permissionDecisionReason"]

    def open_connection(self) -> None:
        self.term(f'{SERVER} -Q "UPDATE t SET a = 1 WHERE b = 2"')
        code = approvals.pending(self.root, 10, file=approvals.ACTIONS)[-1]["code"]
        with mock.patch.object(boardserve.Board, "idle", return_value=False):
            self.board.act("task allow", NAME, "act", code=code, env_name="acmedw-dev", who="on")

    # the hole: a drop in a file was held as a write, approved, and dropped the table

    def test_a_drop_or_a_truncate_in_a_script_file_is_refused_with_a_line_that_names_the_file(self) -> None:
        for text in ("DROP TABLE dbo.orders;\n", "truncate table dbo.orders\ngo\n", "USE AcmeDW;\nGO\nDROP PROCEDURE dbo.usp_x;\n"):
            path = self.script(text)
            reason = self.refused(f"{SERVER} -i {path}", path)
            self.assertIn("DROP", reason.upper())
            self.assertEqual(approvals.pending(self.root, 10, file=approvals.ACTIONS), [])

    def test_the_same_words_are_refused_in_the_text_of_q_and_after_a_write_in_it(self) -> None:
        for text in ("DROP TABLE dbo.orders", "UPDATE dbo.orders SET a = 1; DROP TABLE dbo.orders"):
            self.assertEqual(self.term(f'{SERVER} -Q "{text}"')["permissionDecision"], "deny", text)
            self.assertEqual(self.pending(), 0, text)

    def test_a_drop_after_a_write_in_the_same_file_is_still_a_drop(self) -> None:
        path = self.script("UPDATE dbo.orders SET status = 1;\nINSERT INTO dbo.log SELECT 1;\nDROP TABLE dbo.orders;\n")
        self.refused(f"{SERVER} -i {path}", path)

    def test_an_opened_connection_never_lets_a_destroy_through_and_still_lets_a_write_through(self) -> None:
        self.open_connection()
        write = self.script("UPDATE dbo.orders SET status = 1 WHERE id = 3;\n", "w.sql")
        self.assertEqual(self.term(f"{SERVER} -i {write}"), {}, "a write on the opened connection runs")
        drop = self.script("DROP TABLE dbo.orders;\n", "d.sql")
        self.refused(f"{SERVER} -i {drop}", drop)
        self.refused(f"{SERVER} -i {write} -i {drop}", drop)

    # a write is held, reads pass, what cannot be read is held

    def test_a_script_that_writes_is_held_and_a_script_of_reads_runs(self) -> None:
        update = self.script("UPDATE dbo.orders SET status = 1 WHERE id = 3;\n", "u.sql")
        self.assertIn("「写」", self.held(f"{SERVER} -i {update}"))  # the tests run in Chinese: 写 only (C13 D5)
        read = self.script("-- a look\nUSE AcmeDW;\nGO\nSET NOCOUNT ON;\nSELECT TOP 5 * FROM dbo.orders;\n", "r.sql")
        self.assertEqual(self.term(f"{SERVER} -i {read}"), {})

    def test_a_file_with_a_line_the_gate_cannot_judge_is_refused_with_the_right_way(self) -> None:
        """A shell command (`!!`), another server (`:connect`), a file written (`:out`) or words made at run time (`:setvar`, `$(...)`) are not in the text: the refuse list refuses them and says what to do instead. An opened connection does not change that."""
        for name, text, word in (("shell.sql", "SELECT 1;\n!! rm -rf /tmp/x\n", "`!!`"), ("other.sql", ":connect prod-server\nSELECT 1;\n", "`:connect`"), ("var.sql", ":setvar what orders\nSELECT * FROM dbo.$(what);\n", "`:setvar`"), ("out.sql", ":out /tmp/x.txt\nSELECT 1;\n", "`:out`")):
            path = self.script(text, name)
            reason = self.refused(f"{SERVER} -i {path}", path)
            self.assertIn(word, reason, name)
        self.open_connection()
        self.refused(f"{SERVER} -i {self.script('SELECT 1;' + chr(10) + '!! whoami' + chr(10), 'shell2.sql')}", f"{TASK}/DEV/_manual/shell2.sql")
        self.held(f"{SERVER} -i {TASK}/DEV/_manual/missing.sql")  # a file it cannot read still waits for the person, opened or not
        self.held(f"{SERVER} -i {self.script(':on error exit' + chr(10) + 'SELECT 1;' + chr(10), 'onerr.sql')}")  # a sqlcmd line no list names: asks

    def test_a_script_that_calls_a_procedure_is_an_exec_and_waits_in_dev(self) -> None:
        path = self.script("EXEC dbo.usp_load;\n", "e.sql")
        self.held(f"{SERVER} -i {path}")
        action = external.classify(f"{SERVER} -i {path}", self.systems(), unseen=True, root=self.root, cwd=str(self.root))[0][0]
        self.assertEqual((action.verb, action.file_why), ("exec", ""))

    def systems(self) -> Dict[str, Any]:
        from core import config

        return config.load_policy(self.root, "tools")["systems"]

    def test_a_file_that_is_missing_too_big_or_not_text_is_held_with_the_reason(self) -> None:
        big = self.script("select 1;" + " " * 300000, "big.sql")
        binary = self.script(b"\x00\x01\x02 select 1", "bin.sql")
        for command, what in ((f"{SERVER} -i {TASK}/DEV/_manual/none.sql", "none.sql"), (f"{SERVER} -i {big}", "big.sql"), (f"{SERVER} -i {binary}", "bin.sql")):
            reason = self.held(command)
            self.assertIn(what, reason, command)
            self.assertIn("200 KB", reason)  # the line of the note

    def test_the_text_of_a_file_of_exactly_the_limit_is_read(self) -> None:
        path = self.script("DROP TABLE t;" + " " * (inputfiles.MAX_BYTES - 13), "limit.sql")
        self.assertEqual((self.root / path).stat().st_size, inputfiles.MAX_BYTES)
        self.refused(f"{SERVER} -i {path}", path)

    def test_a_unicode_file_with_its_mark_is_read_as_text(self) -> None:
        path = self.script("DROP TABLE dbo.orders;\r\n", "wide.sql", encoding="utf-16")  # Python writes the mark
        self.assertEqual((self.root / path).read_bytes()[:2], b"\xff\xfe")
        self.refused(f"{SERVER} -i {path}", path)

    def test_a_long_path_in_quotes_with_spaces_is_read_where_the_card_shows_it(self) -> None:
        folder = "Stored Procedures"
        long = f"{TASK}/DEV/acme_dw/AcmeDW/dbo/{folder}/dbo.usp_load_orders_into_the_warehouse_with_a_very_long_name_x.sql"
        path = self.root / long
        path.parent.mkdir(parents=True)
        path.write_text("DROP TABLE dbo.orders;\n", encoding="utf-8")
        self.assertGreater(len(long), 100)
        self.refused(f'{SERVER} -i "{long}"', long)
        path.write_text("UPDATE dbo.orders SET a = 1;\n", encoding="utf-8")
        self.held(f"cd {self.root} && {SERVER} -i '{long}'")

    def test_the_other_ways_to_write_the_option_and_the_places_a_path_is_looked_for(self) -> None:
        drop = self.script("DROP TABLE dbo.orders;\n", "d.sql")
        self.refused(f"{SERVER} -i{drop}", drop)
        self.refused(f"cd {self.root}/{TASK}/DEV/_manual && {SERVER} -i d.sql", "d.sql")  # after a cd of the line
        self.refused(f"{SERVER} -i DEV/_manual/d.sql", "DEV/_manual/d.sql")  # from the task folder
        data = pre_tool(SESSION, "run_in_terminal", {"command": f"{SERVER} -i d.sql", "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root / TASK / "DEV" / "_manual")  # from the terminal's own folder
        self.assertIn("`d.sql`", self.hook(data)["permissionDecisionReason"])
        self.assertEqual(self.pending(), 0)

    def test_several_files_in_one_option_and_a_file_a_file_includes_are_all_read(self) -> None:
        self.script("select 1;\n", "a.sql")
        self.script("DROP TABLE dbo.orders;\n", "b.sql")
        self.refused(f"{SERVER} -i {TASK}/DEV/_manual/a.sql,{TASK}/DEV/_manual/b.sql", f"{TASK}/DEV/_manual/b.sql")
        wrapper = self.script(f"select 1;\n:r {TASK}/DEV/_manual/b.sql\n", "w.sql")
        self.refused(f"{SERVER} -i {wrapper}", f"{TASK}/DEV/_manual/b.sql")  # a file that includes a file with a drop
        loop = self.script(f":r {TASK}/DEV/_manual/loop.sql\nselect 1;\n", "loop.sql")
        self.assertEqual(self.term(f"{SERVER} -i {loop}"), {}, "a file that includes itself ends")
        deep = self.script(f":r {TASK}/DEV/_manual/gone.sql\n", "deep.sql")
        self.assertIn("gone.sql", self.held(f"{SERVER} -i {deep}"))  # an included file that is missing

    def test_a_file_a_line_names_again_may_change_before_it_runs_so_it_is_held(self) -> None:
        path = self.script("select 1;\n")
        self.assertEqual(self.term(f"{SERVER} -i {path}"), {})
        reason = self.held(f"cat {path}; {SERVER} -i {path}")  # named again by a command that only reads: it asks as before
        self.assertIn(messages.text("gate.external.input_twice", file=path), reason)
        self.assertIn(messages.text("gate.external.same_line"), self.refused(f"echo 'DROP TABLE dbo.orders;' > {path}; {SERVER} -i {path}"))  # 1.7.38 (C13 F2): a command that may write it: refused, two calls

    def test_a_script_outside_the_task_is_read_too(self) -> None:
        outside = self.root / "outside.sql"
        outside.write_text("DROP TABLE dbo.orders;\n", encoding="utf-8")
        self.refused(f"{SERVER} -i outside.sql", "outside.sql")
        outside.write_text("select 1;\n", encoding="utf-8")
        self.assertEqual(self.term(f"{SERVER} -i outside.sql"), {})

    def test_the_log_says_which_file_decided(self) -> None:
        path = self.script("DROP TABLE dbo.orders;\n")
        action = external.classify(f"{SERVER} -i {path}", self.systems(), unseen=True, root=self.root, cwd=str(self.root))[0][0]
        self.assertEqual((action.verb, action.file, action.file_why), ("destroy", path, "refuse"))
        self.assertEqual(action.facts()["file"], path)
        plain = external.classify(f'{SERVER} -Q "select 1"', self.systems(), unseen=True, root=self.root)[0][0]
        self.assertNotIn("file", plain.facts())

    def test_without_the_root_the_call_stays_a_write_as_before(self) -> None:
        """`harness wait --run` and the board judge a line without a root: they cannot read the file, so the option still makes it a write."""
        path = self.script("select 1;\n")
        action = external.classify(f"{SERVER} -i {path}", self.systems())[0][0]
        self.assertEqual((action.verb, action.file_why, action.zone), ("write", "unread", "ask"))

    def test_a_type_with_no_input_is_judged_as_before(self) -> None:
        plain = {"sqlsys": {"reach": {"cli": ["sqlctl"]}, "env": "dev", "verbs": [{"pattern": r"\b-i\b", "verb": "write"}, {"pattern": r"\bselect\b", "verb": "read"}]}}
        path = self.script("DROP TABLE t;\n")
        found = external.classify(f"sqlctl -i {path}", plain, unseen=True, root=self.root)
        self.assertEqual([(item.verb, item.file_why) for item, _ in found], [("write", "")])


class InputDeclarationTests(unittest.TestCase):
    """The `input` word of a type: which options name a file, and how a file names more files."""

    def test_the_options_take_the_next_word_a_joined_value_or_an_equals_sign(self) -> None:
        self.assertEqual(inputfiles.split(["-S", "h", "-i", "a b.sql", "-v", "x=1"], ["-i"]), (["a b.sql"], ["-S", "h", "-v", "x=1"]))
        self.assertEqual(inputfiles.split(["-ia.sql", "-I"], ["-i"]), (["a.sql"], ["-I"]), "the option is exact in its case: -I is another option")
        self.assertEqual(inputfiles.split(["--input=a.sql", "--x"], ["--input"]), (["a.sql"], ["--x"]))
        self.assertEqual(inputfiles.split(["-i"], ["-i"]), ([], []), "an option with no value names no file")

    def test_the_strictest_verb_of_every_rule_that_matches_wins(self) -> None:
        system = {"verbs": [{"pattern": r"\bupdate\b", "verb": "write"}, {"pattern": r"\bdrop\b", "verb": "destroy"}, {"pattern": r"\bselect\b", "verb": "read"}]}
        self.assertEqual(inputfiles.verb_of_text(system, "select 1"), "read")
        self.assertEqual(inputfiles.verb_of_text(system, "select 1; update t set a = 1"), "write")
        self.assertEqual(inputfiles.verb_of_text(system, "update t set a = 1; DROP table t"), "destroy")
        self.assertIsNone(inputfiles.verb_of_text(system, "-- nothing"))

    def test_the_declaration_is_checked_in_the_type_and_in_the_systems(self) -> None:
        base = {"type": "x", "fields": {"host": {"label": "h"}}, "auth": {"env": {"identity": "env", "env": {}}}, "test": "x -t", "cli": ["x"], "match": "-S {host}", "verbs": []}
        self.assertEqual([item for item in connections.type_problems(dict(base, input={"options": ["-i"], "include": "^:r\\s+(\\S+)"})) if "input" in item], [])
        for bad in ({"options": []}, {"options": ["-i"], "include": "("}, {"include": "x"}, {"options": ["-i"], "more": 1}, ["-i"]):
            self.assertTrue([item for item in connections.type_problems(dict(base, input=bad)) if "input" in item], bad)
        system = {"reach": {"cli": ["x"]}, "env": "dev"}
        self.assertEqual(systems.validate({"x": dict(system, input={"options": ["-i"]})}), [])
        self.assertTrue(systems.validate({"x": dict(system, input={"options": ["-i"], "include": "("})}))
        self.assertTrue(systems.validate({"x": dict(system, input={"include": "x"})}))

    def test_the_sample_type_declares_it_and_its_destroy_rule_comes_first(self) -> None:
        kind = json.loads((Path(__file__).resolve().parents[1] / "toolpacks" / "sqlserver" / "types" / "sqlserver.json").read_text(encoding="utf-8"))
        self.assertEqual(kind["input"]["options"], ["-i", "--input-file"])
        self.assertEqual(connections.type_problems(kind), [])
        self.assertEqual(kind["verbs"][0]["verb"], "destroy", "a drop after an update in the same text is still a drop")
        import re

        self.assertEqual([hit.group(1) or hit.group(2) for hit in re.finditer(kind["input"]["include"], 'select 1\n  :r "a b.sql"\n:R c.sql\nx :r no.sql', re.I | re.M)], ["a b.sql", "c.sql"])

    def test_pinning_finds_a_file_inside_the_task_and_locate_finds_one_anywhere(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            (root / "task").mkdir()
            (root / "outside.sql").write_text("x", encoding="utf-8")
            (root / "task" / "in.sql").write_text("x", encoding="utf-8")
            self.assertEqual(pinfiles.locate("outside.sql", root, root / "task"), root / "outside.sql")
            self.assertIsNone(pinfiles.find("outside.sql", root, root / "task"))
            self.assertEqual(pinfiles.find("in.sql", root, root / "task"), root / "task" / "in.sql")
            self.assertIsNone(pinfiles.locate("none.sql", root, None))


class WordsTests(unittest.TestCase):
    """RC-2, RC-3, RC-5: one line, cut between words, and no space after a full stop in Chinese."""

    def test_one_line_is_not_lines(self) -> None:
        for language in ("en", "zh"):
            table = messages.table(language)
            self.assertIn("1", table["desk.outbox.lines.one"], language)
            self.assertNotIn("{n}", table["desk.outbox.lines.one"], language)
            self.assertNotIn("{n}", table["desk.outbox.script.note.one"], language)
        self.assertEqual(messages.table("en")["desk.outbox.lines.one"], "(1 line)")
        self.assertIn("1 line,", messages.table("en")["desk.outbox.script.note.one"])
        js = (Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "web" / "desk.js").read_text(encoding="utf-8")
        self.assertIn('lines === 1 ? "desk.outbox.lines.one"', js)
        self.assertIn('lines === 1 ? "desk.outbox.script.note.one"', js)

    def test_a_probe_answer_is_cut_between_words_with_a_mark(self) -> None:
        said = "ado: cannot reach https://localhost:18443: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: CA cert does not allow certificate signing (_ssl.c:1006) and then some more words after it"
        cut = reach.first_line(said + "\nsecond line")
        self.assertLessEqual(len(cut), 160)
        self.assertTrue(cut.endswith("…"))
        self.assertNotIn("\n", cut)
        self.assertTrue(said.startswith(cut[:-1].rstrip()), "what is left is the start of the answer")
        self.assertIn(said[len(cut[:-1].rstrip())], " ", "the cut falls on a space, not inside a word")
        self.assertEqual(reach.first_line("short answer"), "short answer")
        self.assertEqual(clip.words("a" * 30, 10), "a" * 9 + "…", "a text with no space is cut at the limit")
        self.assertEqual(clip.words("one two three four", 12), "one two…")
        self.assertEqual(clip.words("one two", 7), "one two")
        line = reach.judged({}, lambda: (None, said))
        self.assertTrue(line["said"].endswith("…"))

    def test_the_agent_text_of_a_held_call_has_no_space_after_a_chinese_full_stop(self) -> None:
        import re

        class Action:
            system, env, verb, file, file_why = "acmedw-dev", "dev", "write", "", ""

        for language, gap in (("zh", ""), ("en", " ")):
            with mock.patch.object(messages, "language", return_value=language):
                self.assertEqual(messages.gap(), gap)
                text = rules.external_outbox(Action(), "sqlcmd -Q x", "ABC123", 10, "", [{"system": "acmedw-dev", "scope": "all"}], ["x.sql"])
                if language == "zh":
                    self.assertIsNone(re.search(r"[。！？；：，、）”」] [^\s]", text), text)
                    self.assertIsNone(re.search(r"[\u4e00-\u9fff] [“「]", text), text)
                else:
                    self.assertIn(". The user can also press", text)
                    self.assertIn(". The code ABC123", text)

    def test_no_zh_message_has_a_space_after_a_full_width_mark(self) -> None:
        import re

        for key, text in messages.table("zh").items():
            self.assertIsNone(re.search(r"[。！？；，、）」”] +[\u4e00-\u9fff“「`]", text), key)

    def test_the_zh_pieces_that_are_put_after_a_sentence_start_with_no_space(self) -> None:
        zh = messages.table("zh")
        for key in ("task.step.page", "promote.done.close", "promote.done.person", "domain.next.name", "promote.done.commit_message", "promote.nothing.manual", "task.step.allow_conn", "connections.named.opened", "connections.named.items"):
            self.assertFalse(zh[key].startswith(" "), key)
            self.assertTrue(messages.table("en")[key].startswith(" "), key + ": English keeps its space")


class HeldIsNotRefusedTests(GateCase):
    """RC-4: the report.md counts, the Gate blocks of the page and the Agent actions tab keep a held call and a refused call apart."""

    def held(self, command: str = "sqlcmd -S h -Q \"UPDATE t SET a = 1\"", decision: str = "outbox") -> None:
        record = {"surface": "vscode", "session_id": SESSION, "event": "PreToolUse", "tool_name": "run_in_terminal", "decision": "deny", "judge": "rule", "by": ["gate"], "reason": "waits",
                  "external": {"system": "s", "env": "dev", "verb": "write", "target": "", "decision": decision}, "target": {"paths": [], "command": command}, "at": utc_now()}
        logs.log_call(self.root, record)

    def test_a_held_call_is_no_gate_block_and_the_page_says_how_many_were_held(self) -> None:
        self.held()
        self.held(decision="human")
        section = gatereview.section(self.root, self.data())
        self.assertEqual((section["count"], section["held"]), (3, 2), "the three refusals of the setup, and the two held calls beside them")
        self.assertEqual(len(self.blocks()), 3)
        self.assertEqual(len(gatereview.denies(self.root, self.data(), held=True)), 2)
        text = messages.text("report.gate.held", n=2)
        self.assertIn("2", text)
        js = (Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "web" / "task.js").read_text(encoding="utf-8")
        self.assertIn('t("report.gate.held", {n: gate.held})', js)

    def test_the_report_counts_and_lists_a_held_call_as_held(self) -> None:
        self.held()
        lines = common.log_section(self.root, self.data())
        counts = next(line for line in lines if messages.text("log.count.held") in line)
        self.assertIn(f"{messages.text('log.count.deny')} 3", counts)
        self.assertIn(f"{messages.text('log.count.held')} 1", counts)
        rows = [line for line in lines if line.startswith("|") and "UPDATE t SET" in line]
        self.assertEqual(len(rows), 1)
        self.assertIn("| held |", rows[0])
        self.assertEqual(sum(1 for line in lines if line.startswith("|") and "| deny |" in line), 3)

    def test_the_agent_actions_tab_marks_it_held_and_is_not_a_problem(self) -> None:
        self.held()
        rows = logs.read_session(self.root, "vscode", SESSION)
        entries = tasktrace.build(rows, 50)["entries"]
        gate = [item for item in entries if item["kind"] == "gate"]
        self.assertEqual(sorted(item["decision"] for item in gate), ["ask", "deny", "deny", "deny", "held"])
        self.assertEqual([tasktrace.problem(item) for item in gate if item["decision"] == "held"], [False])
        self.assertEqual(sum(1 for item in gate if tasktrace.problem(item)), 3)
        found = taskinsight.count_rows(rows, 0, float("inf"))
        self.assertEqual((found["denied"], found["held"], found["asked"]), (3, 1, 1))
        self.assertEqual(taskinsight.HELD_DECISIONS, common.HELD_DECISIONS)


class HoverTableTests(unittest.TestCase):
    """RC-1: when VS Code lacks the settings of this copy every row says it was not checked, the reason is said once under the table, and a connection with no sign-in says so."""

    def test_each_row_says_its_own_state_and_none_repeats_the_reason(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            check = ready.Ready(root, mock.Mock(), mock.Mock())
            long = "VS Code does not have what this copy sets for the tools: PATH x. Commands of the tools may fail here. Quit VS Code completely, then open it again with the identities."
            lines = [{"system": name, "env": env, "state": reach.DENIED, "why": "vscode-env", "at": "", "launch": long} for name, env in (("acme-dev", "dev"), ("acme-ist", "ist"), ("ado", "none"))]
            systems_in = {name: {"toolpack": "sqlserver"} for name in ("acme-dev", "acme-ist", "ado")}
            with mock.patch.object(ready.conn_core, "unsigned", return_value=["acme-ist"]), mock.patch.object(ready.conn_core, "listed", return_value={}), mock.patch.object(ready.conn_core, "types", return_value={}):
                got = check.table(systems_in, lines)
            rows = {row["system"]: row for row in got["rows"]}
            self.assertEqual((rows["acme-dev"]["state"], rows["acme-dev"]["reason"]), ("down", ""))
            self.assertEqual((rows["acme-ist"]["state"], rows["acme-ist"]["reason"]), ("unknown", messages.text("board.enter.cs.none")))
            self.assertFalse(any("VS Code" in row["reason"] for row in got["rows"]), "the sentence is not in a row")
            self.assertEqual({item["name"]: item["state"] for item in got["names"]}, {"acme-dev": "down", "acme-ist": "unknown", "ado": "down"})
        js = (Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "web" / "enter.js").read_text(encoding="utf-8")
        self.assertIn('c.env_wrong ? h("p", {class: "sy-off"}, t("board.enter.m.vscode.noenv"))', js, "said once, under the table")


if __name__ == "__main__":
    unittest.main()
