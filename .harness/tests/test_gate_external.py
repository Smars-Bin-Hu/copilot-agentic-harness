"""External actions (M43-2): a company lists the systems an agent may reach; the gate turns a terminal command into {system, env, verb} and decides."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from unittest import mock
from typing import Any, Dict, List

from support import HarnessTestCase, pre_tool
from taskcase import NAME, SESSION, TaskCase

from modules.gate import external
from modules.gate.external import ALLOW, DENY, DESTROY, EXEC, HUMAN, OUTBOX, READ, TASK, WRITE

# Made-up systems: the harness ships none. `cloudctl` has environments, `tk` has none.
SYSTEMS: Dict[str, Any] = {
    "cloud": {
        "reach": {"cli": "cloudctl"},
        "env_from": [{"pattern": r"--sub\s+dev\b", "env": "dev"}, {"pattern": r"--sub\s+qat\b", "env": "qat"}],
        "verbs": [
            {"pattern": r"\b(?:list|show|get)\b", "verb": "read"},
            {"pattern": r"\b(?:delete|remove)\b", "verb": "destroy"},
            {"pattern": r"\b(?:run|start)\b", "verb": "exec"},
        ],
        "target": r"--name\s+(\S+)",
        "rules": {"dev": {"write": "task"}},
    },
    "tickets": {
        "reach": {"cli": ["tk"]},
        "env": "none",
        "verbs": [{"pattern": r"^(?:show|search)\b", "verb": "read"}],
    },
}


def judged(command: str, systems: Dict[str, Any] = SYSTEMS) -> List[tuple]:
    return [(item.system, item.env, item.verb, decision) for item, decision in external.classify(command, systems)]


class ClassifyTests(unittest.TestCase):
    def test_a_read_in_dev_is_allowed(self) -> None:
        self.assertEqual(judged("cloudctl --sub dev list"), [("cloud", "dev", READ, ALLOW)])

    def test_an_environment_no_rule_names_is_prod_and_prod_is_read_only(self) -> None:
        self.assertEqual(judged("cloudctl list"), [("cloud", "prod", READ, ALLOW)])
        self.assertEqual(judged("cloudctl create --name x"), [("cloud", "prod", WRITE, DENY)])
        self.assertEqual(judged("cloudctl run job"), [("cloud", "prod", EXEC, DENY)])
        self.assertEqual(judged("cloudctl delete --name x"), [("cloud", "prod", DESTROY, DENY)])

    def test_a_call_no_verb_rule_names_is_a_write(self) -> None:
        self.assertEqual(judged("cloudctl --sub dev frobnicate"), [("cloud", "dev", WRITE, TASK)])
        self.assertEqual(judged("cloudctl"), [("cloud", "prod", WRITE, DENY)])

    def test_a_call_with_no_verb_says_so_and_a_named_one_does_not(self) -> None:
        unnamed = external.classify("cloudctl --sub dev $Q", SYSTEMS)[0][0]
        self.assertEqual((unnamed.verb, unnamed.named, unnamed.facts()["named"]), (WRITE, False, False))
        named = external.classify("cloudctl --sub dev list", SYSTEMS)[0][0]
        self.assertTrue(named.named)
        self.assertNotIn("named", named.facts())

    def test_the_company_rule_wins_and_the_rest_keeps_the_defaults(self) -> None:
        self.assertEqual(judged("cloudctl --sub dev create"), [("cloud", "dev", WRITE, TASK)])  # rules.dev.write
        self.assertEqual(judged("cloudctl --sub dev run job"), [("cloud", "dev", EXEC, HUMAN)])  # default
        self.assertEqual(judged("cloudctl --sub dev delete x"), [("cloud", "dev", DESTROY, DENY)])  # default
        self.assertEqual(judged("cloudctl --sub qat create"), [("cloud", "qat", WRITE, OUTBOX)])  # default for an environment that is not prod

    def test_a_system_without_environments(self) -> None:
        self.assertEqual(judged("tk show T-1"), [("tickets", "none", READ, ALLOW)])
        self.assertEqual(judged("tk comment T-1 hello"), [("tickets", "none", WRITE, OUTBOX)])

    def test_the_target_is_read_when_the_policy_has_a_pattern(self) -> None:
        item = external.classify("cloudctl --sub dev delete --name job-7", SYSTEMS)[0][0]
        self.assertEqual(item.target, "job-7")
        self.assertEqual(external.classify("tk show T-1", SYSTEMS)[0][0].target, "")

    def test_how_it_is_written_does_not_hide_a_call(self) -> None:
        for command in (
            "/usr/local/bin/cloudctl --sub dev delete x", "CLOUDCTL.CMD --sub dev delete x", "cloudctl.exe --sub dev delete x", "sudo cloudctl --sub dev delete x",
            "FOO=1 cloudctl --sub dev delete x", "timeout 5 cloudctl --sub dev delete x", "cd x && cloudctl --sub dev delete x", "echo hi | xargs cloudctl --sub dev delete",
            'bash -c "cloudctl --sub dev delete x"', "echo $(cloudctl --sub dev delete x)", "cloudctl --sub dev delete x\ncloudctl list", "cloudctl --sub dev delete x # note",
        ):
            with self.subTest(command):
                self.assertIn(("cloud", "dev", DESTROY, DENY), judged(command))

    def test_a_word_in_an_argument_is_not_a_call(self) -> None:
        for command in ('rg "cloudctl delete" docs', "echo cloudctl delete", "grep cloudctl notes.txt", "cat cloudctl.md", "git commit -m 'cloudctl delete'", ""):
            with self.subTest(command):
                self.assertEqual(judged(command), [])

    def test_the_strictest_call_of_a_line_decides(self) -> None:
        both = external.classify("cloudctl --sub dev list && cloudctl --sub dev delete x && tk show T-1", SYSTEMS)
        item, decision = external.strictest(both)
        self.assertEqual((item.verb, decision), (DESTROY, DENY))
        self.assertIsNone(external.strictest([]))

    def test_no_systems_means_nothing_is_recognised(self) -> None:
        self.assertEqual(judged("cloudctl delete x", {}), [])


SHARED: Dict[str, Any] = {
    "boards": {
        "reach": {"cli": "hubctl", "when": r"^boards\b"},
        "env": "none",
        "verbs": [{"pattern": r"\b(?:show|list|query)\b", "verb": "read"}],
    },
    "cloud2": {"reach": {"cli": "hubctl"}, "verbs": [{"pattern": r"\b(?:list|show)\b", "verb": "read"}, {"pattern": r"\bdelete\b", "verb": "destroy"}]},
}


class SharedProgramTests(unittest.TestCase):
    """One program, several systems: `reach.when` picks the system from the arguments (one tool hosts a ticket board and a cloud)."""

    def test_the_first_system_whose_when_matches_owns_the_call(self) -> None:
        self.assertEqual(judged("hubctl boards work-item show --id 7", SHARED), [("boards", "none", READ, ALLOW)])
        self.assertEqual(judged("hubctl boards work-item update --id 7", SHARED), [("boards", "none", WRITE, OUTBOX)])
        self.assertEqual(judged("hubctl group list", SHARED), [("cloud2", "prod", READ, ALLOW)])
        self.assertEqual(judged("hubctl group delete -n x", SHARED), [("cloud2", "prod", DESTROY, DENY)])

    def test_a_call_no_system_claims_is_not_recognised(self) -> None:
        only_boards = {"boards": SHARED["boards"]}
        self.assertEqual(judged("hubctl group delete -n x", only_boards), [])

    def test_two_systems_may_share_a_program_only_if_all_but_one_have_a_when(self) -> None:
        self.assertEqual(external.validate(SHARED), [])
        both = {"a": {"reach": {"cli": "hubctl"}}, "b": {"reach": {"cli": "hubctl"}}}
        self.assertTrue(any("also the reach" in text for text in external.validate(both)))
        bad = copy.deepcopy(SHARED)
        bad["boards"]["reach"]["when"] = "("
        self.assertTrue(any("bad pattern" in text for text in external.validate(bad)))


class ValidateTests(unittest.TestCase):
    def bad(self, change) -> List[str]:
        systems = copy.deepcopy(SYSTEMS)
        change(systems)
        return external.validate(systems)

    def test_the_sample_and_an_empty_list_are_fine(self) -> None:
        self.assertEqual(external.validate(SYSTEMS), [])
        self.assertEqual(external.validate({}), [])
        self.assertEqual(external.validate(None), [])

    def test_what_is_wrong_is_said(self) -> None:
        cases = {
            "an unknown key": lambda s: s["cloud"].update({"envs": []}),
            "no reach": lambda s: s["cloud"].pop("reach"),
            "an empty reach": lambda s: s["cloud"].update({"reach": {"cli": []}}),
            "a verb that does not exist": lambda s: s["cloud"]["verbs"].append({"pattern": "x", "verb": "update"}),
            "a decision that does not exist": lambda s: s["cloud"]["rules"].update({"dev": {"write": "maybe"}}),
            "a verb in rules that does not exist": lambda s: s["cloud"]["rules"].update({"dev": {"sync": "allow"}}),
            "an environment that does not exist": lambda s: s["cloud"].update({"default_env": "staging"}),
            "a pattern that does not compile": lambda s: s["cloud"]["verbs"].append({"pattern": "(", "verb": "read"}),
            "a target that does not compile": lambda s: s["cloud"].update({"target": "["}),
            "one program for two systems": lambda s: s["tickets"].update({"reach": {"cli": "cloudctl"}}),
            "env and env_from together": lambda s: s["cloud"].update({"env": "dev"}),
            "a name with capitals": lambda s: s.update({"Cloud2": s["tickets"]}),
            "needs without a probe": lambda s: s["cloud"].update({"needs": {"launch": "x"}}),
            "needs with an unknown key": lambda s: s["cloud"].update({"needs": {"probe": "x", "password": "y"}}),
            "an expect that does not compile": lambda s: s["cloud"].update({"needs": {"probe": "x", "expect": "("}}),
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.assertTrue(self.bad(change), name)

    def test_warnings_name_what_looks_like_a_mistake(self) -> None:
        loose = {"x": {"reach": {"cli": "x"}, "default_env": "dev", "rules": {"prod": {"write": "allow"}, "*": {"destroy": "allow"}}}}
        text = "\n".join(external.warnings(loose))
        for part in ("no `verbs`", "default_env", "rules.prod.write", "rules.*.destroy"):
            self.assertIn(part, text)
        self.assertEqual(external.warnings(SYSTEMS), [])


class EnvironmentsTests(unittest.TestCase):
    def test_the_environments_the_listed_systems_reach_never_prod(self) -> None:
        from core import systems as outside

        found = outside.environments({"cloud": {"reach": {"cli": "c"}, "env_from": [{"pattern": "a", "env": "dev"}, {"pattern": "b", "env": "qat"}], "default_env": "prod"},
                                      "tickets": {"reach": {"cli": "t"}, "env": "none"}, "db": {"reach": {"cli": "d"}, "env": "dev"}})
        self.assertEqual(found, {"dev": ["cloud", "db"], "qat": ["cloud"]})
        self.assertEqual(outside.environments({}), {})


class ReachTests(unittest.TestCase):
    """1.7.1: `needs.probe` says whether a system is reachable from this session; the harness keeps no output of it."""

    def test_only_a_system_with_needs_is_probed_and_each_answer_is_judged(self) -> None:
        systems = {
            "fine": {"reach": {"cli": "a"}, "needs": {"probe": "a-probe", "expect": r"^CORP\\", "launch": "Start with a.cmd"}},
            "wrong": {"reach": {"cli": "b"}, "needs": {"probe": "b-probe", "expect": r"^CORP\\"}},
            "failed": {"reach": {"cli": "c"}, "needs": {"probe": "c-probe", "launch": "Sign in"}},
            "slow": {"reach": {"cli": "d"}, "needs": {"probe": "d-probe"}},
            "plain": {"reach": {"cli": "e"}},
        }
        answers = {"a-probe": (0, "CORP\\me\n"), "b-probe": (0, "guest\n"), "c-probe": (2, ""), "d-probe": (None, "no answer in 5 s")}
        found = external.reach(systems, lambda command: answers[command])
        self.assertEqual(set(found), {"fine", "wrong", "failed", "slow"})
        self.assertEqual(found["fine"], {"reachable": True, "why": "", "launch": "Start with a.cmd"})
        self.assertFalse(found["wrong"]["reachable"])
        self.assertIn("expect", found["wrong"]["why"])
        self.assertNotIn("guest", json.dumps(found))  # the output of a probe is never kept
        self.assertEqual((found["failed"]["reachable"], found["failed"]["launch"]), (False, "Sign in"))
        self.assertIn("exit code 2", found["failed"]["why"])
        self.assertEqual(found["slow"]["why"], "no answer in 5 s")

    def test_a_real_probe_runs_in_the_shell_with_a_deadline(self) -> None:
        code, output = external.run_probe(f"{sys.executable} -c \"print('hello')\"")
        self.assertEqual((code, output.strip()), (0, "hello"))
        code, output = external.run_probe(f"{sys.executable} -c \"import sys; sys.exit(4)\"")
        self.assertEqual(code, 4)
        with mock.patch.object(external, "PROBE_SECONDS", 0.2), mock.patch("core.systems.PROBE_SECONDS", 0.2):
            code, output = external.run_probe(f"{sys.executable} -c \"import time; time.sleep(3)\"")
        self.assertEqual(code, None)
        self.assertIn("no answer", output)

    def test_the_report_has_the_probes_only_when_asked_and_never_with_errors(self) -> None:
        systems = {"x": {"reach": {"cli": "x"}, "needs": {"probe": "p"}}}
        self.assertNotIn("reach", external.report(systems))
        self.assertEqual(external.report(systems, run=lambda command: (0, ""))["reach"], {"x": {"reachable": True, "why": "", "launch": ""}})
        broken = {"x": {"reach": {"cli": "x"}, "needs": {"probe": "p", "expect": "("}}}
        self.assertNotIn("reach", external.report(broken, run=lambda command: (0, "")))


class GateExternalTests(HarnessTestCase):
    session = "ext"

    def configure(self, systems: Any) -> None:
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": systems}), encoding="utf-8")

    def term(self, command: str, session: str = "ext") -> Dict[str, Any]:
        data = pre_tool(session, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def test_without_a_list_nothing_changes(self) -> None:
        self.assertEqual(self.term("cloudctl delete x"), {})

    def test_a_read_passes_and_the_rest_is_refused_with_what_to_do(self) -> None:
        self.configure(SYSTEMS)
        self.assertEqual(self.term("cloudctl --sub dev list"), {})
        self.assertEqual(self.term("tk show T-1"), {})
        denied = self.term("cloudctl --sub dev delete x")
        self.assertEqual(denied["permissionDecision"], "deny")
        for text in ("cloud", "dev", "销毁", "cloudctl --sub dev delete x", "不要重试"):
            self.assertIn(text, denied["permissionDecisionReason"])
        held = self.term("tk comment T-1 hello")  # a write to a system without environments: the outbox (M43-4)
        self.assertEqual(held["permissionDecision"], "deny")
        for text in ("tickets", "approve-action", "tk comment T-1 hello"):
            self.assertIn(text, held["permissionDecisionReason"])
        handed = self.term("cloudctl --sub dev run job")  # exec: the person runs it
        self.assertEqual(handed["permissionDecision"], "deny")
        for text in ("cloud", "task handoff run", "cloudctl --sub dev run job"):
            self.assertIn(text, handed["permissionDecisionReason"])

    def test_the_refusal_shows_the_command_as_it_was_written_quotes_included(self) -> None:
        self.configure(SYSTEMS)
        denied = self.term('tk comment T-1 "a b; c"')
        self.assertIn('tk comment T-1 "a b; c"', denied["permissionDecisionReason"])

    def test_a_task_decision_without_a_task_points_at_the_task_skill(self) -> None:
        self.configure(SYSTEMS)
        denied = self.term("cloudctl --sub dev create --name x")
        self.assertEqual(denied["permissionDecision"], "deny")
        self.assertIn("harness-my-task", denied["permissionDecisionReason"])

    def test_the_strictest_call_of_a_compound_line_decides(self) -> None:
        self.configure(SYSTEMS)
        self.assertEqual(self.term("cloudctl --sub dev list && cloudctl delete x")["permissionDecision"], "deny")

    def test_a_list_that_does_not_validate_is_ignored_and_tools_check_says_why(self) -> None:
        broken = copy.deepcopy(SYSTEMS)
        broken["cloud"]["verbs"].append({"pattern": "(", "verb": "read"})
        self.configure(broken)
        self.assertEqual(self.term("cloudctl delete x"), {})  # a hook that fails itself must not hurt normal work
        completed = self.cli("tools", "check")
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("bad pattern", completed.stdout)

    def test_tools_check_shows_what_the_gate_decides(self) -> None:
        self.configure(SYSTEMS)
        completed = self.cli("tools", "check")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        cloud = next(item for item in report["systems"] if item["system"] == "cloud")
        self.assertEqual(cloud["decides"]["prod"], "read=allow write=deny destroy=deny exec=deny")
        self.assertEqual(cloud["decides"]["dev"], "read=allow write=task destroy=deny exec=human")
        self.assertEqual(next(item for item in report["systems"] if item["system"] == "tickets")["decides"], {"none": "read=allow write=outbox destroy=deny exec=human"})

    def test_tools_check_probes_the_systems_that_have_needs_and_the_company_layer_is_read(self) -> None:
        """1.7.1: the company pack's copy (tools.company.json) is a layer under the person's override; `tools check` says which system is reachable."""
        systems = copy.deepcopy(SYSTEMS)
        systems["cloud"]["needs"] = {"probe": f"{sys.executable} -c \"print('CORP\\\\me')\"", "expect": r"^CORP\\", "launch": "Start VS Code with start-vscode.cmd."}
        systems["tickets"]["needs"] = {"probe": f"{sys.executable} -c \"import sys; sys.exit(1)\""}
        (self.root / ".harness" / "policies" / "tools.company.json").write_text(json.dumps({"systems": systems}), encoding="utf-8")
        completed = self.cli("tools", "check")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual({item["system"] for item in report["systems"]}, {"cloud", "tickets"})
        self.assertEqual(report["reach"]["cloud"], {"reachable": True, "why": "", "launch": "Start VS Code with start-vscode.cmd."})
        self.assertEqual(report["reach"]["tickets"]["reachable"], False)
        self.configure({"tickets": {"needs": {"probe": f"{sys.executable} -c \"print('x')\""}}})  # the person's override is merged on top of the company's, key by key
        report = json.loads(self.cli("tools", "check").stdout)
        self.assertEqual({item["system"] for item in report["systems"]}, {"cloud", "tickets"})
        self.assertTrue(report["reach"]["tickets"]["reachable"])
        self.assertEqual(self.term("tk show 1"), {})  # the company's `verbs` still hold: a read, allowed

    def test_tools_check_with_nothing_listed_is_fine(self) -> None:
        completed = self.cli("tools", "check")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["systems"], [])


class ExternalLogTests(HarnessTestCase):
    """M43-3: every call to a listed system leaves its line in the session log, allowed or not; never what it returned; no secrets."""

    def setUp(self) -> None:
        super().setUp()
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": SYSTEMS}), encoding="utf-8")

    def term(self, command: str, session: str = "log") -> Dict[str, Any]:
        data = pre_tool(session, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def test_an_allowed_and_a_refused_call_both_leave_their_action(self) -> None:
        self.term("cloudctl --sub dev list --name job-1")
        self.term("cloudctl --sub dev delete --name job-2")
        self.term("ls -la")
        rows = [row for row in self.session_log("log") if row.get("event") == "PreToolUse"]
        self.assertEqual(len(rows), 3)
        allowed, refused, plain = rows
        self.assertEqual(allowed["decision"], "none")
        self.assertEqual(allowed["external"], {"system": "cloud", "env": "dev", "verb": "read", "target": "job-1", "decision": "allow"})
        self.assertNotIn("target", allowed)  # a call that went through keeps no command
        self.assertEqual(refused["decision"], "deny")
        self.assertEqual(refused["kind"], "external")
        self.assertEqual(refused["external"], {"system": "cloud", "env": "dev", "verb": "destroy", "target": "job-2", "decision": "deny"})
        self.assertNotIn("external", plain)

    def test_a_call_another_rule_refused_still_names_its_action(self) -> None:
        self.term("cloudctl --sub dev list > .harness/registry.json")  # writes a guardrail file: refused by that rule
        row = [row for row in self.session_log("log") if row.get("event") == "PreToolUse"][-1]
        self.assertEqual(row["decision"], "deny")
        self.assertEqual(row["external"]["verb"], "read")
        self.assertNotEqual(row.get("kind"), "external")

    def test_a_secret_in_a_refused_command_does_not_reach_the_log(self) -> None:
        output = self.term('SECRET_TOKEN=abc123 cloudctl --sub dev delete x --password "p w" --token hunter2')  # a short -P is masked only for database tools (redact)
        self.assertIn("abc123", output["permissionDecisionReason"])  # the agent wrote it; the reason it gets back is not cut
        text = json.dumps(self.session_log("log"))
        for secret in ("abc123", "hunter2", "p w"):
            self.assertNotIn(secret, text)
        self.assertIn("SECRET_TOKEN=***", text)


class CountTests(unittest.TestCase):
    def test_the_task_report_counts_outside_calls_and_refusals(self) -> None:
        from modules.task import taskinsight

        at = "2026-01-01T00:00:0{}+00:00"
        rows = [
            {"at": at.format(1), "event": "PreToolUse", "decision": "none", "external": {"system": "cloud"}},
            {"at": at.format(2), "event": "PreToolUse", "decision": "deny", "external": {"system": "cloud"}},
            {"at": at.format(3), "event": "PreToolUse", "decision": "deny"},
            {"at": at.format(4), "event": "PostToolUse", "decision": "none", "external": {"system": "cloud"}},
        ]
        start = taskinsight.copilot_events.seconds(at.format(0))
        counted = taskinsight.count_rows(rows, start, start + 60)
        self.assertEqual((counted["external_calls"], counted["external_denied"], counted["denied"]), (2, 1, 2))


class GateExternalTaskTests(TaskCase):
    def configure(self) -> None:
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": SYSTEMS}), encoding="utf-8")

    def term(self, command: str) -> Dict[str, Any]:
        data = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def test_a_task_decision_passes_only_in_a_task_whose_plan_is_approved(self) -> None:
        self.configure()
        self.new()
        self.assertEqual(self.term("cloudctl --sub dev create --name x")["permissionDecision"], "deny")  # a task, no approved plan
        self.write_plan()
        self.approve_plan()
        self.assertEqual(self.term("cloudctl --sub dev create --name x"), {})
        self.assertEqual(self.term("cloudctl --sub dev delete x")["permissionDecision"], "deny")  # task does not open a destroy

    def test_in_a_test_task_the_grant_of_an_environment_stands_for_the_plan(self) -> None:
        """1.7.2: a test task has no plan; the person letting the agent run DEV (`task test runner`) lets a `task`-level call of dev through, and of dev only."""
        from modules.task import testrecord

        self.configure()
        self.new(name="t-test", kind="test")
        (self.root / ".workspace" / "sandbox" / "tasks" / "t-test" / "TEST-GUIDE.md").write_text("# G\n\n## DEV\n\nRunner: agent\n\n## QAT\n\nrun\n", encoding="utf-8")
        self.assertEqual(self.term("cloudctl --sub dev create --name x")["permissionDecision"], "deny")  # proposed in the guide is not granted
        testrecord.set_runner(self.root, "t-test", "DEV", True, interactive=True)
        self.assertEqual(self.term("cloudctl --sub dev create --name x"), {})
        self.assertEqual(self.term("cloudctl --sub qat create --name x")["permissionDecision"], "deny")  # another environment: not granted
        self.assertEqual(self.term("cloudctl --sub dev delete x")["permissionDecision"], "deny")  # the grant opens the task level only, never a destroy
        testrecord.set_runner(self.root, "t-test", "DEV", False, interactive=True)
        self.assertEqual(self.term("cloudctl --sub dev create --name x")["permissionDecision"], "deny")

    def test_the_person_opens_a_connection_for_one_task_and_the_switch_lets_writes_through_but_never_a_destroy_or_prod(self) -> None:
        """1.7.38: `task allow --conn cloud --on` is the task-level switch: task, outbox and human decisions of that connection pass; deny does not; prod cannot be opened."""
        from modules.task import tasklife

        self.configure()
        self.new()
        with self.assertRaises(Exception):
            tasklife.set_allow(self.root, NAME, "cloud", True, interactive=False)  # an agent's terminal
        with self.assertRaises(Exception):
            tasklife.set_allow(self.root, NAME, "prod", True, interactive=True)  # not a connection
        with self.assertRaises(Exception):
            tasklife.set_allow(self.root, NAME, "dev", True, interactive=True)  # an environment is not opened any more
        self.assertEqual(self.term("cloudctl --sub dev create --name x")["permissionDecision"], "deny")  # task level, no plan
        self.assertEqual(self.term("cloudctl --sub qat run --name j")["permissionDecision"], "deny")  # human
        found = tasklife.set_allow(self.root, NAME, "CLOUD", True, interactive=True)
        self.assertEqual((found["conn"], found["on"], found["open"]), ("cloud", True, ["cloud"]))
        self.assertEqual(self.term("cloudctl --sub dev create --name x"), {})
        self.assertEqual(self.term("cloudctl --sub dev run --name j"), {})  # human in dev: opened too
        self.assertEqual(self.term("cloudctl --sub qat run --name j"), {})  # the connection serves qat too, and the CLI opened it whole
        self.assertEqual(self.term("cloudctl --sub dev delete x")["permissionDecision"], "deny")  # never a destroy
        self.assertEqual(self.term("cloudctl run --name j")["permissionDecision"], "deny")  # no environment named: prod, never opened
        rows = [row["external"] for row in self.session_log(SESSION) if row.get("external")]
        self.assertEqual([(row["env"], row["verb"], row.get("opened")) for row in rows[-5:]], [("dev", "write", True), ("dev", "exec", True), ("qat", "exec", True), ("dev", "destroy", None), ("prod", "exec", None)])  # the log says what went through on the switch
        tasklife.set_allow(self.root, NAME, "cloud", False, interactive=True)
        self.assertEqual(self.term("cloudctl --sub dev create --name x")["permissionDecision"], "deny")
        self.assertEqual([event["detail"] for event in self.data()["events"] if event["what"] == "allow-env"], ["cloud: on", "cloud: off"])

    def test_an_old_allow_env_opens_nothing(self) -> None:
        """1.7.38: tasks that were opened by environment before keep their `allow_env`; it is not read, so nothing is open by it."""
        from taskcase import TASK

        self.configure()
        self.new()
        path = self.root / TASK / ".task" / "task.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["allow_env"] = {"dev": {"at": "2026-11-01T00:00:00+00:00"}}
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.term("cloudctl --sub dev create --name x")["permissionDecision"], "deny")

    def test_a_system_of_several_environments_opened_from_a_card_is_open_in_that_environment_only(self) -> None:
        from modules.task import tasklife

        self.configure()
        self.new()
        tasklife.set_allow(self.root, NAME, "cloud", True, interactive=True, env="dev")
        self.assertEqual(self.term("cloudctl --sub dev run --name j"), {})
        self.assertEqual(self.term("cloudctl --sub qat run --name j")["permissionDecision"], "deny")

    def test_open_to_the_agent_leaves_a_tool_packs_system_closed(self) -> None:
        """1.7.13: a tool pack's system (a ticket board, a pipeline) holds each write for the person, even when another connection is open; `openable` or `open` says otherwise."""
        from modules.task import tasklife

        board = dict(SYSTEMS["cloud"], reach={"cli": ["boardctl"]}, toolpack="tracker")
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": {**SYSTEMS, "board": board, "open-board": dict(board, reach={"cli": ["openctl"]}, openable=True)}}), encoding="utf-8")
        self.new()
        tasklife.set_allow(self.root, NAME, "cloud", True, interactive=True)
        with self.assertRaises(Exception):
            tasklife.set_allow(self.root, NAME, "board", True, interactive=True)  # its type does not let it open
        tasklife.set_allow(self.root, NAME, "open-board", True, interactive=True)
        self.assertEqual(self.term("cloudctl --sub dev create --name x"), {})
        self.assertEqual(self.term("boardctl --sub dev create --name x")["permissionDecision"], "deny")
        self.assertEqual(self.term("openctl --sub dev create --name x"), {})


class SamplePackTests(unittest.TestCase):
    """The sample SQL Server pack (1.7.9): a SELECT beside a statement it fears does not make the line a read; plain reads stay reads."""

    def test_the_sample_pack_holds_or_refuses_what_is_not_a_plain_read(self) -> None:
        import json
        from pathlib import Path

        import shutil
        import tempfile

        from core import config

        examples = Path(__file__).resolve().parents[1] / "examples"
        root = Path(tempfile.mkdtemp())
        shutil.copytree(Path(__file__).resolve().parents[1] / "policies", root / ".harness" / "policies")
        shutil.copytree(examples.parent / "toolpacks" / "sqlserver", root / ".harness" / "toolpacks" / "sqlserver")
        from support import add_path

        add_path(root, root / ".harness" / "toolpacks" / "sqlserver")  # on: a folder this computer added
        listed = json.loads((examples / "connections.json").read_text(encoding="utf-8"))["connections"]
        (root / ".harness" / "policies" / "connections.company.json").write_text(json.dumps({"connections": {name: item for name, item in listed.items() if item["type"] == "sqlserver"}}), encoding="utf-8")
        systems = config.load_policy(root, "tools")["systems"]  # each connection of the sample is a system (1.7.10)
        self.assertEqual(sorted(systems), ["orders-dev", "orders-ist", "orders-qat", "sqlserver-other"])  # the last is the pack's own (1.7.38, C13 F2): the programs that reach a SQL Server with no connection are refused
        self.assertEqual(external.validate(systems), [])
        verb = lambda query: external.classify(f'sqlcmd -S sql-dev.example.local,1433 -E -Q "{query}"', systems)[0][0].verb  # noqa: E731
        self.assertEqual(external.classify('sqlcmd -S sql-ist.example.local -E -Q "SELECT 1"', systems)[0][0].system, "orders-ist")  # the default port may be left out
        for query in ("SELECT 1; COMMIT", "SELECT 1; BEGIN TRAN", "SELECT 1; BACKUP DATABASE x TO DISK = 'y'", "SELECT 1; DBCC CHECKDB", "SELECT 1; RECONFIGURE", "SELECT * FROM OPENROWSET('a', 'b', 'c')", "UPDATE t SET a = 1"):
            self.assertEqual(verb(query), WRITE, query)
        for query in ("SELECT 1; KILL 52", "SELECT 1; RESTORE DATABASE x", "DROP TABLE t", "SELECT 1; SHUTDOWN"):
            self.assertEqual(verb(query), DESTROY, query)
        for query in ("SELECT order_id, committed_at FROM dbo.Orders", "SELECT backup_date FROM t", "SELECT COUNT(*) FROM dbo.Orders"):
            self.assertEqual(verb(query), READ, query)


if __name__ == "__main__":
    unittest.main()
