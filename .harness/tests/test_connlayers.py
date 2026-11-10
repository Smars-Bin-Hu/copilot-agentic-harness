"""Which step of a connection broke (1.7.38): program, sign-in, account access, address. The kind is the made-up `fakedb` of test_connections: the engine knows no kind of server."""

from __future__ import annotations

import json
from pathlib import Path

from support import put_type

from core import connections, connlayers
from test_connections import ConnectionsCase, KIND

STEPS = ("program", "signin", "access", "address")


def steps(found: dict) -> list:
    return [found["layers"]["steps"][step] for step in STEPS]


class LayersOfATest(ConnectionsCase):
    def test_a_test_that_passes_has_four_steps_ok_and_no_sentence(self) -> None:
        found = connections.test(self.root, "db-dev", {"account": "alice", "password": "right"})
        self.assertEqual((found["state"], steps(found), found["layers"]["broken"], found["layers"]["text"]), ("ok", ["ok"] * 4, "", ""))

    def test_the_server_turning_an_account_down_is_account_access_and_the_steps_after_it_were_not_looked_at(self) -> None:
        found = connections.test(self.root, "db-dev", {"account": "alice", "password": "wrong"})
        self.assertEqual((found["state"], found["layers"]["broken"], steps(found)), ("denied", "access", ["ok", "ok", "bad", "skip"]))
        self.assertIn("alice", found["layers"]["text"])
        self.assertIn("db1:5000", found["layers"]["text"], "it says where: host:port")

    def test_no_account_typed_is_the_sign_in(self) -> None:
        found = connections.test(self.root, "db-dev", {})
        self.assertEqual((found["layers"]["broken"], steps(found)), ("signin", ["ok", "bad", "skip", "skip"]))
        self.assertIn("db-dev", found["layers"]["text"])

    def test_a_server_that_does_not_answer_is_the_address_and_the_account_access_is_not_claimed(self) -> None:
        self.company({"db-dev": {"type": "fakedb", "env": "dev", "auth": "own", "host": "db1", "port": "9999"}})
        found = connections.test(self.root, "db-dev", {"account": "alice", "password": "right"})
        self.assertEqual((found["state"], found["layers"]["broken"], steps(found)), ("down", "address", ["ok", "ok", "unknown", "bad"]))
        self.assertIn("db1:9999", found["layers"]["text"])
        self.assertIsNone(found["layers"]["link"])

    def test_a_certificate_or_a_proxy_in_the_words_of_the_program_points_at_the_network_part_of_local(self) -> None:
        kind = dict(KIND, down="refused|CERTIFICATE")
        for words, key in (("tls: CERTIFICATE_VERIFY_FAILED", "address.cert"), ("407 proxy authentication required", "address.proxy")):
            found = connlayers.classify(kind, {"host": "db1", "port": "5000"}, "db-dev", "down", words, "env", {"account": "a"})
            self.assertEqual((found["key"], found["broken"], found["link"]), (key, "address", {"part": "network", "focus": ""}))
        self.assertIn(connlayers.say("tools.local.title"), found["text"], "the sentence names the window it points at")

    def test_a_program_that_names_a_network_fault_in_its_own_words_is_the_address_though_the_type_has_no_pattern_for_it(self) -> None:
        found = connlayers.classify(KIND, {"host": "db1"}, "db-dev", "failed", "lookup db1: no such host", "env", {"account": "a"})
        self.assertEqual((found["broken"], found["key"]), ("address", "address"))

    def test_the_program_missing_is_the_first_step_and_links_to_that_program_in_local(self) -> None:
        other = dict(KIND, type="nothere", cli=["no-such-program-x"], test="no-such-program-x --who")
        put_type(self.root, other)
        self.company({"x-dev": {"type": "nothere", "env": "dev", "auth": "own", "host": "h"}})
        found = connections.test(self.root, "x-dev", {"account": "a", "password": "b"})
        self.assertEqual((found["state"], found["layers"]["broken"], steps(found)), ("missing", "program", ["bad", "skip", "skip", "skip"]))
        self.assertEqual(found["layers"]["link"], {"part": "programs", "focus": "prog:no-such-program-x"})
        self.assertIn("no-such-program-x", found["layers"]["text"])

    def test_the_program_a_sign_in_way_needs_is_looked_for_before_the_test_runs(self) -> None:
        kind = dict(KIND, auth={"own": KIND["auth"]["own"], "signin": {"identity": "tool", "login": "fakedb-login --now", "needs": ["fakedb-login-nowhere"]}})
        put_type(self.root, kind)
        self.company({"db-dev": {"type": "fakedb", "env": "dev", "auth": "signin", "host": "db1", "port": "5000"}})
        found = connections.test(self.root, "db-dev", {})
        self.assertEqual((found["state"], found["layers"]["broken"]), ("missing", "program"))
        self.assertIn("fakedb-login-nowhere", found["layers"]["text"])

    def test_a_tool_sign_in_that_was_not_let_in_is_told_only_when_the_type_can_tell_the_two_apart(self) -> None:
        tool = {"identity": "tool", "login": "fakedb-login --now"}
        server = {"host": "db1", "port": "5000", "auth": "signin"}
        unsure = connlayers.classify(dict(KIND, auth={"signin": tool}), server, "db-dev", "denied", "Login failed for this user", "tool", {})
        self.assertEqual((unsure["broken"], unsure["key"], unsure["steps"]["signin"], unsure["steps"]["access"]), ("", "denied.unsure", "unknown", "unknown"), "cannot tell: no step is marked")
        kind = dict(KIND, auth={"signin": tool}, signin_lost="^fakedb: no sign-in")
        lost = connlayers.classify(kind, server, "db-dev", "denied", "fakedb: no sign-in found", "tool", {})
        self.assertEqual((lost["broken"], lost["key"]), ("signin", "signin.tool"))
        refused = connlayers.classify(kind, server, "db-dev", "denied", "403 Forbidden", "tool", {"account": "alice"})
        self.assertEqual((refused["broken"], refused["key"], refused["steps"]["signin"]), ("access", "access.tool", "ok"))
        self.assertIn("alice", refused["text"])

    def test_an_answer_that_names_no_account_and_a_timeout_mark_no_step(self) -> None:
        other = connlayers.classify(KIND, {"host": "db1"}, "db-dev", "denied", "who knows", "env", {"account": "a"}, why="other-identity")
        self.assertEqual((other["broken"], other["key"]), ("", "answer"))
        slow = connlayers.classify(KIND, {"host": "db1"}, "db-dev", "down", "no answer in 15 s", "env", {"account": "a"}, timeout=15)
        self.assertEqual((slow["broken"], slow["key"], slow["steps"]["program"]), ("", "timeout", "ok"))
        self.assertIn("15", slow["text"])
        weird = connlayers.classify(KIND, {"host": "db1"}, "db-dev", "failed", "something odd", "env", {"account": "a"})
        self.assertEqual((weird["broken"], weird["key"]), ("", "error"))
        self.assertIn("something odd", weird["text"])
        silent = connlayers.classify(KIND, {"host": "db1"}, "db-dev", "failed", "", "tool", {}, code=1, line="az account show --token Bearer abcdefghijklmnopqrstuvwxyz0123456789")
        self.assertEqual((silent["broken"], silent["key"]), ("", "silent"))  # (Windows) printed nothing: the command and its exit code, a secret hidden
        self.assertIn("az account show", silent["text"])
        self.assertIn("1", silent["text"])
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz0123456789", silent["text"])

    def test_a_windows_account_is_typed_first_and_nothing_is_run_without_it(self) -> None:
        self.company({"db-win": {"type": "fakedb", "env": "dev", "auth": "win", "host": "db1", "port": "5000"}})
        found = connections.test(self.root, "db-win", {})
        self.assertEqual((found["state"], found["layers"]["broken"]), ("denied", "signin"))

    def test_the_saved_identity_is_tested_when_nothing_is_typed(self) -> None:
        self.assertEqual(connections.test(self.root, "db-dev", {})["state"], "denied")
        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        found = connections.test(self.root, "db-dev", {}, saved=True)
        self.assertEqual((found["state"], found["who"]), ("ok", "alice"))

    def test_the_sentences_exist_in_both_languages_with_their_places_filled_in(self) -> None:
        core = Path(connlayers.__file__).resolve().parent
        for lang in ("en", "zh"):
            table = json.loads((core / f"messages.{lang}.json").read_text(encoding="utf-8"))
            for key in ("program", "signin.none", "signin.token", "signin.tool", "access.tool", "access.typed", "access.token", "denied.unsure", "answer", "address", "address.cert", "address.proxy", "timeout", "error", "silent"):
                self.assertIn("connections.layer." + key, table, (lang, key))
            for step in STEPS:
                self.assertIn("connections.step." + step, table)


class NetonlyToldTests(ConnectionsCase):
    """1.7.39 (Windows): a test with a Windows account (network credentials) that printed nothing is told apart: the shell never ran, the wait failed, or the command answered."""

    def test_each_case_says_what_happened(self) -> None:
        from core import netonly

        self.assertIn("did not run", netonly.told(1, "", 0)[1])
        self.assertEqual(netonly.told(259, "", 0)[0], 259)
        self.assertIn("still running", netonly.told(259, "", 0)[1])
        self.assertEqual(netonly.told(1, netonly.MARK + "\r\nLogin failed for user 'x'.", 0), (1, "Login failed for user 'x'."))
        self.assertEqual(netonly.told(0, netonly.MARK + "\r\nTESTBNS\\me", 0), (0, "TESTBNS\\me"))
        self.assertEqual(netonly.told(0, "", netonly.WAIT_FAILED, 5), (None, "could not wait for the process started with these credentials (Windows error 5)"))
        self.assertNotEqual(netonly.told(0, "", 0)[0], 0, "a shell that wrote nothing never passes as ok")


class WaySettingsTests(ConnectionsCase):
    """1.7.39 (Windows): a sign-in way's `settings` reach its login and its test; a wrong shape is a fault of the type."""

    def test_the_ado_way_turns_off_the_question_after_the_account(self) -> None:
        kind = json.loads((Path(connections.__file__).resolve().parents[2] / "toolpacks/ado/types/azure-devops.json").read_text(encoding="utf-8"))
        self.assertEqual(connections.way_settings(kind, {"auth": "signin"}), {"AZURE_CORE_LOGIN_EXPERIENCE_V2": "off"})
        self.assertEqual(connections.way_settings(kind, {"auth": "token"}), {})
        self.assertEqual(connections.type_problems(kind), [])
        bad = dict(kind, auth=dict(kind["auth"], signin=dict(kind["auth"]["signin"], settings={"not a name": 1})))
        self.assertTrue(any(".settings" in item for item in connections.type_problems(bad)))
