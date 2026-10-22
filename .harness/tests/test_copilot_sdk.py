"""Copilot (SDK) sessions, from the recordings: tool names, subagent sessions, and the top-level output format."""

from __future__ import annotations

import json
import time
import unittest
from typing import Any, Dict, List, Optional

from support import FIXTURES, HarnessTestCase

import hook
from adapters import copilot_vscode
from core import state

PARENT = "session-parent-verifier"
CHILD = "session-child-verifier"


def recorded(name: str) -> List[Dict[str, Any]]:
    with (FIXTURES / "sessions" / name).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def ev(data: Dict[str, Any]) -> Any:
    return copilot_vscode.event_name(data)


def sid(data: Dict[str, Any]) -> Any:
    return data.get("session_id") or data.get("sessionId")


def sample(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / "payloads" / name).read_text(encoding="utf-8"))


class SdkTestCase(HarnessTestCase):
    def feed(self, data: Dict[str, Any]) -> tuple:
        return hook.process(json.dumps(data), self.root)

    def replay(self, name: str, drop: Optional[Any] = None, edit: Optional[Any] = None) -> List[tuple]:
        results = []
        for data in recorded(name):
            if drop and drop(data):
                continue
            if edit:
                data = edit(data)
            output, record = self.feed(data)
            results.append((data, output, record))
        return results

    def session(self, session_id: str) -> Dict[str, Any]:
        return state.read_state(state.state_path(self.root, "vscode", session_id), "vscode", session_id)

    def task_for(self, session_id: str, name: str = "job") -> str:
        """The session picks up a new task. Returns the task folder."""
        self.feed({**sample("UserPromptSubmit.json"), "session_id": session_id, "prompt": "work"})
        self.cli_json("task", "new", name, "--kind", "rca", "--session-id", session_id)
        return f".workspace/sandbox/tasks/{name}"


class EngineDetectionTests(unittest.TestCase):
    def test_every_recorded_sdk_payload_parses(self) -> None:
        for path in sorted((FIXTURES / "payloads").glob("*.json")):
            with self.subTest(path.name):
                event = copilot_vscode.parse(json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(event.surface, "vscode")

    def test_the_recorded_tool_names_have_the_right_kinds(self) -> None:
        kinds = {
            "Bash": "terminal", "Read": "read", "Write": "create", "Edit": "edit", "Grep": "search",
            "Glob": "search", "Agent": "subagent", "search_code_subagent": "search",
        }
        for name, kind in kinds.items():
            with self.subTest(name):
                event = copilot_vscode.parse(sample(f"PreToolUse.{name}.json"))
                self.assertEqual(event.tool_kind, kind)

    def test_agent_target_and_prompt_come_from_agent_type_and_prompt(self) -> None:
        event = copilot_vscode.parse(sample("PreToolUse.Agent.json"))
        self.assertEqual(event.subagent_target, "verifier")
        self.assertIn("复核", event.subagent_prompt)

    def test_a_result_is_read_from_tool_result(self) -> None:
        event = copilot_vscode.parse(sample("PostToolUse.Agent.json"))
        self.assertTrue(event.tool_response.startswith("VERDICT: PASS"))

    def test_subagent_start_has_no_event_name_and_is_camel_case(self) -> None:
        data = sample("SubagentStart.json")
        self.assertNotIn("hook_event_name", data)
        event = copilot_vscode.parse(data)
        self.assertEqual((event.event, event.agent_type, event.session_id), ("SubagentStart", "verifier", data["sessionId"]))

    def test_a_failed_tool_call_is_its_own_event_with_the_error(self) -> None:
        data = sample("PostToolUseFailure.Read.json")
        self.assertNotIn("tool_result", data)
        event = copilot_vscode.parse(data)
        self.assertEqual((event.event, event.tool_name, event.tool_kind, event.error), ("PostToolUseFailure", "Read", "read", "Path does not exist"))
        self.assertEqual(copilot_vscode.engine(data), "cli")

    def test_a_terminal_command_that_exits_non_zero_is_not_a_failed_call(self) -> None:
        data = sample("PostToolUse.Bash.exit1.json")
        self.assertEqual(data["tool_result"]["result_type"], "success")
        self.assertIn("exit code 1", copilot_vscode.parse(data).tool_response)

    def test_the_tools_recorded_on_2026_10_10_have_a_kind(self) -> None:
        for name, kind in (("PreToolUse.WebFetch.json", "web"), ("PreToolUse.skill.json", "skill"), ("PreToolUse.tool_search_tool.json", "meta")):
            data = sample(name)
            self.assertEqual(copilot_vscode.parse(data).tool_kind, kind, name)
            self.assertEqual(copilot_vscode.engine(data), "cli", name)

    def test_a_terminal_tool_under_a_windows_name_is_still_a_terminal(self) -> None:
        # Never recorded on Windows. Whatever the engine calls the tool there, the gate has to read its command.
        for name in ("bash", "PowerShell", "powershell"):
            event = copilot_vscode.parse({**sample("PreToolUse.Bash.json"), "tool_name": name, "tool_input": {"command": "sudo ls"}})
            self.assertEqual((event.tool_kind, event.command), ("terminal", "sudo ls"), name)

    def test_loading_a_skill_gives_its_name(self) -> None:
        self.assertEqual(copilot_vscode.parse(sample("PreToolUse.skill.json")).skill, "harness-task-level")
        self.assertEqual(copilot_vscode.parse(sample("PreToolUse.Read.json")).skill, "")

    def test_the_engine_is_told_from_the_payload(self) -> None:
        self.assertEqual(copilot_vscode.engine(sample("PreToolUse.Bash.json")), "cli")
        self.assertEqual(copilot_vscode.engine(sample("Stop.json")), "cli")
        self.assertEqual(copilot_vscode.engine(sample("SubagentStart.json")), "cli")
        # A subagent's own tools carry older names and no other sign.
        self.assertEqual(copilot_vscode.engine(sample("PreToolUse.file_search.json")), "unknown")
        self.assertEqual(copilot_vscode.engine({"hook_event_name": "PreToolUse", "tool_use_id": "t1", "tool_name": "x"}), "legacy")  # a Local session: not supported, but `doctor` names it


class OutputFormatTests(SdkTestCase):
    def test_deny_is_top_level(self) -> None:
        self.feed({**sample("UserPromptSubmit.json"), "session_id": PARENT, "prompt": "change it"})
        agent = sample("PreToolUse.Agent.json")
        agent["session_id"] = PARENT
        output, _ = self.feed(agent)
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("不能调用子 agent", output["permissionDecisionReason"])
        self.assertNotIn("hookSpecificOutput", output)

    def test_deny_with_no_engine_sign_is_top_level_too(self) -> None:
        self.feed({**sample("UserPromptSubmit.json"), "session_id": "s", "prompt": "x"})
        data = {"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "runSubagent",
                "tool_input": {"agentName": "builder", "prompt": "p"}}
        output, _ = self.feed(data)
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertNotIn("hookSpecificOutput", output)

    def test_stop_block_is_top_level(self) -> None:
        task = self.task_for(PARENT)
        write = sample("PostToolUse.Write.json")
        write.update(session_id=PARENT, cwd=str(self.root.resolve()))
        write["tool_input"] = {"path": f"{self.root.resolve()}/{task}/RCA.md", "file_text": "x"}
        self.feed(write)
        output, _ = self.feed(sample("Stop.json") | {"session_id": PARENT})
        self.assertEqual(output["decision"], "block")
        self.assertIn("TASK.md", output["reason"])
        self.assertNotIn("hookSpecificOutput", output)

    def test_context_for_a_prompt_is_top_level(self) -> None:
        output, _ = self.feed({**sample("UserPromptSubmit.json"), "session_id": "fresh", "prompt": "hello"})
        self.assertIn("当前会话 id：fresh", output["additionalContext"])


class SubagentSessionTests(SdkTestCase):
    """The recording calls a subagent named `verifier` from a session that holds no task: the call itself is refused now,
    but the events that follow it still show how a subagent session is linked to its parent."""

    def test_the_recorded_session_replays_clean_and_the_call_is_refused(self) -> None:
        results = self.replay("cli-verifier-call.jsonl")
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])
        denied = [data["tool_name"] for data, out, _ in results if out.get("permissionDecision") == "deny"]
        self.assertEqual(denied, ["Agent"])
        stops = [out for data, out, _ in results if ev(data) == "Stop"]
        self.assertEqual(stops, [{}, {}])  # the child's Stop and the parent's Stop

    def test_the_child_session_is_linked_to_the_parent(self) -> None:
        self.replay("cli-verifier-call.jsonl")
        child = self.session(CHILD)
        self.assertEqual(child["parent_session_id"], PARENT)
        parent = self.session(PARENT)
        self.assertEqual(parent["subagents"]["active"], [])

    def test_the_child_inherits_the_task_its_parent_holds(self) -> None:
        events = recorded("cli-verifier-call.jsonl")
        task = self.task_for(PARENT)
        for data in events[1:]:
            self.feed(data)
        self.assertEqual(self.session(CHILD)["active_task"], task)

    def test_the_child_call_message_is_not_a_user_prompt(self) -> None:
        results = self.replay("cli-verifier-call.jsonl")
        prompts = [(sid(data), record["from_subagent"], out) for data, out, record in results
                   if ev(data) == "UserPromptSubmit"]
        self.assertEqual(prompts[0][1:], (False, prompts[0][2]))
        self.assertIn("additionalContext", prompts[0][2])
        self.assertEqual(prompts[1], (CHILD, True, {}))  # no rules for the subagent

    def test_nothing_is_refused_in_a_session_that_only_uses_tools(self) -> None:
        # Edit, Grep, Glob, the built-in search (a tool, with a session of its own for its searches).
        results = self.replay("cli-tools-and-search-subagent.jsonl")
        self.assertEqual([data.get("tool_name") for data, out, _ in results if out.get("permissionDecision")], [])
        self.assertEqual(self.session("session-child-search")["parent_session_id"], "session-parent-tools")
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])

    def test_a_new_user_session_is_not_taken_for_a_child_without_a_waiting_parent(self) -> None:
        output, record = self.feed({**sample("UserPromptSubmit.json"), "session_id": "someone-else", "prompt": "hi"})
        self.assertFalse(record["from_subagent"])
        self.assertNotIn("parent_session_id", self.session("someone-else"))

    def test_an_old_waiting_parent_does_not_claim_a_new_session(self) -> None:
        self.replay("cli-verifier-call.jsonl", drop=lambda d: sid(d) == CHILD or ev(d) in ("SubagentStop", "Stop"))

        def age(current: Dict[str, Any]) -> None:
            for entry in current["subagents"]["active"]:
                entry["at"] = time.time() - 120

        state.update_state(self.root, "vscode", PARENT, age)
        _, record = self.feed({**sample("UserPromptSubmit.json"), "session_id": "late", "prompt": "unrelated"})
        self.assertFalse(record["from_subagent"])

    def test_subagent_stop_removes_the_waiting_entry(self) -> None:
        self.replay("cli-verifier-call.jsonl", drop=lambda d: sid(d) == CHILD)
        self.assertEqual(self.session(PARENT)["subagents"]["active"], [])

    def test_the_recorded_block_of_a_subagent_stop_replays_clean(self) -> None:
        # The probe hook of that recording blocked a SubagentStop; ours has no such check. The child's second prompt is still not the user.
        results = self.replay("cli-subagent-stop-block.jsonl")
        child = [record["from_subagent"] for data, _, record in results if ev(data) == "UserPromptSubmit" and sid(data) == "session-child-stopblock"]
        self.assertEqual(child, [True, True])
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])


class ContinuationTests(SdkTestCase):
    """After a Stop block the engine sends the reason back as a UserPromptSubmit. That is not the user."""

    def blocked(self) -> str:
        task = self.task_for(PARENT)
        write = sample("PostToolUse.Write.json")
        write.update(session_id=PARENT, cwd=str(self.root.resolve()))
        write["tool_input"] = {"path": f"{self.root.resolve()}/{task}/RCA.md", "file_text": "x"}
        self.feed(write)
        output, _ = self.feed(sample("Stop.json") | {"session_id": PARENT})
        return output["reason"]

    def prompt(self, text: str) -> tuple:
        return self.feed({**sample("UserPromptSubmit.json"), "session_id": PARENT, "prompt": text})

    def test_the_fed_back_reason_is_not_a_new_prompt(self) -> None:
        reason = self.blocked()
        output, record = self.prompt(reason)
        self.assertTrue(record["continuation"])
        self.assertEqual(output, {})  # no rules injected a second time
        again, _ = self.feed(sample("Stop.json") | {"session_id": PARENT})
        self.assertEqual(again, {})  # the reminder of this prompt was already given

    def test_a_real_next_prompt_still_starts_a_new_window(self) -> None:
        self.blocked()
        output, record = self.prompt("另一件事")
        self.assertFalse(record["continuation"])
        self.assertIn("additionalContext", output)

    def test_the_reason_is_only_matched_once(self) -> None:
        reason = self.blocked()
        self.prompt(reason)
        _, record = self.prompt(reason)
        self.assertFalse(record["continuation"])


class FailedCallsAndSkillsInTheLogTests(SdkTestCase):
    """Recorded 2026-10-10. A failed call has no PostToolUse, so without PostToolUseFailure it never shows as done."""

    def test_a_failed_call_goes_through_and_leaves_a_line_with_the_error(self) -> None:
        self.feed(sample("UserPromptSubmit.json"))
        data = {**sample("PostToolUseFailure.Read.json"), "session_id": sample("UserPromptSubmit.json")["session_id"]}
        output, record = self.feed(data)
        self.assertEqual(output, {})
        self.assertEqual((record["event"], record["tool_name"], record["error"], record["decision"]), ("PostToolUseFailure", "Read", "Path does not exist", "none"))
        self.assertNotIn("target", record)  # still no arguments in the log

    def test_a_long_error_is_clipped_like_a_reason(self) -> None:
        from modules.observe.handler import clip_record

        self.assertEqual(clip_record({"error": "x" * 50}, 10)["error"], "x" * 10 + "…")

    def test_a_skill_call_goes_through_and_the_log_names_the_skill(self) -> None:
        self.feed(sample("UserPromptSubmit.json"))
        session_id = sample("UserPromptSubmit.json")["session_id"]
        output, record = self.feed({**sample("PreToolUse.skill.json"), "session_id": session_id})
        self.assertNotIn("permissionDecision", output)
        self.assertEqual((record["tool_kind"], record["skill"]), ("skill", "harness-task-level"))
        _output, record = self.feed({**sample("PreToolUse.Read.json"), "session_id": session_id})
        self.assertNotIn("skill", record)

    def test_fetch_and_tool_search_are_not_refused(self) -> None:
        self.feed(sample("UserPromptSubmit.json"))
        session_id = sample("UserPromptSubmit.json")["session_id"]
        for name in ("PreToolUse.WebFetch.json", "PreToolUse.tool_search_tool.json"):
            output, record = self.feed({**sample(name), "session_id": session_id})
            self.assertNotIn("permissionDecision", output, name)
            self.assertEqual(record["engine"], "cli", name)

    def test_stats_count_failed_calls_and_loaded_skills(self) -> None:
        from modules.observe import record_call, stats

        self.feed(sample("UserPromptSubmit.json"))
        session_id = sample("UserPromptSubmit.json")["session_id"]
        for name in ("PreToolUse.skill.json", "PostToolUseFailure.Read.json", "PostToolUseFailure.Read.json"):
            _output, record = self.feed({**sample(name), "session_id": session_id})
            record_call(self.root, record)
        numbers = stats.collect(self.root)
        self.assertEqual(numbers["failed_tool_calls_by_tool"], {"Read": 2})
        self.assertEqual(numbers["skills_loaded"], {"harness-task-level": 1})


class DroppedRulesTests(SdkTestCase):
    """VS Code's own prompt handler takes the one `additionalContext` place (the reminder to rename the chat), and the rules
    of UserPromptSubmit are lost; UserPromptTransformed puts them back (recorded 2026-10-22, 1.5.34)."""

    def told(self, prompt: str) -> str:
        output, _record = self.feed({**sample("UserPromptSubmit.json"), "prompt": prompt})
        return output["additionalContext"]

    def transformed(self, **change: Any) -> tuple:
        return self.feed({**sample("userPromptTransformed.json"), **change})

    def test_the_event_is_known_by_its_payload(self) -> None:
        self.assertEqual(ev(sample("userPromptTransformed.json")), "UserPromptTransformed")

    def test_rules_the_engine_dropped_are_put_back_at_the_end(self) -> None:
        whole = sample("userPromptTransformed.json")["transformedPrompt"]
        rules = self.told(sample("userPromptTransformed.json")["prompt"])
        output, record = self.transformed()
        self.assertEqual(set(output), {"modifiedTransformedPrompt"})
        self.assertTrue(output["modifiedTransformedPrompt"].startswith(whole.rstrip()))
        self.assertIn("rename_chat", output["modifiedTransformedPrompt"])  # the engine's own reminder stays
        self.assertTrue(output["modifiedTransformedPrompt"].rstrip().endswith(rules + "\n</system_reminder>"))
        self.assertEqual(record["event"], "UserPromptTransformed")

    def test_nothing_changes_when_the_rules_arrived(self) -> None:
        prompt = sample("userPromptTransformed.json")["prompt"]
        rules = self.told(prompt)
        output, _record = self.transformed(transformedPrompt=f"{prompt}\n\n<system_reminder>\n{rules}\n</system_reminder>")
        self.assertEqual(output, {})

    def test_another_prompt_or_one_with_nothing_told_is_left_alone(self) -> None:
        self.told("something else entirely")
        self.assertEqual(self.transformed()[0], {})
        state_file = state.state_path(self.root, "vscode", sample("userPromptTransformed.json")["sessionId"])
        data = json.loads(state_file.read_text(encoding="utf-8"))
        data["prompt_context"] = {"prompt": state.prompt_digest(sample("userPromptTransformed.json")["prompt"]), "text": "", "at": time.time()}
        state_file.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.transformed()[0], {})

    def test_an_old_note_is_not_used(self) -> None:
        self.told(sample("userPromptTransformed.json")["prompt"])
        state_file = state.state_path(self.root, "vscode", sample("userPromptTransformed.json")["sessionId"])
        data = json.loads(state_file.read_text(encoding="utf-8"))
        data["prompt_context"]["at"] -= state.PROMPT_CONTEXT_TTL_SECONDS + 1
        state_file.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.transformed()[0], {})


if __name__ == "__main__":
    unittest.main()
