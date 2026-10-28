"""External actions (M43-2): a company lists the systems an agent may reach; the gate turns a terminal command into {system, env, verb} and decides."""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any, Dict, List

from support import HarnessTestCase, pre_tool
from taskcase import SESSION, TaskCase

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
        for text in ("cloud", "dev", "destroy", "cloudctl --sub dev delete x", "不要重试"):
            self.assertIn(text, denied["permissionDecisionReason"])
        handed = self.term("tk comment T-1 hello")
        self.assertEqual(handed["permissionDecision"], "deny")
        for text in ("tickets", "task handoff run", "tk comment T-1 hello"):
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
        output = self.term('SECRET_TOKEN=abc123 cloudctl --sub dev delete x --password "p w" -P hunter2')
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


if __name__ == "__main__":
    unittest.main()
