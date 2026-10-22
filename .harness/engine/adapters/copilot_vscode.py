"""VS Code, Copilot (SDK) sessions: the `@github/copilot` engine. Fixtures: eval/fixtures/hooks/copilot-sdk/.

Tool names like `Bash`, results in `tool_result`, SubagentStart is camelCase with no event name,
a failed tool call comes as PostToolUseFailure with `error` instead of PostToolUse (recorded 2026-10-10),
a subagent runs in its own session, output is plain top-level keys.

Local sessions (the older Copilot Chat engine) are not supported. Their payloads still parse, so a
Local session shows up in the log as `legacy` and `doctor` can say so. The output is the SDK format either way.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.events import EVENT_NAMES, Decision, HookEvent

from . import common

SURFACE = "vscode"

# Tool names only the SDK engine uses. The tools a subagent runs there carry older names (`read_file`, `grep_search`).
_CLI_TOOLS = ("Bash", "bash", "PowerShell", "powershell", "Read", "Write", "Edit", "Grep", "Glob", "Agent", "search_code_subagent", "WebFetch", "skill", "tool_search_tool", "task_complete")


def event_name(payload: Dict[str, Any]) -> Any:
    name = payload.get("hook_event_name")
    if name is None and "sessionId" in payload and "agentName" in payload:
        return "SubagentStart"  # the SDK engine sends this one without an event name
    if name is None and "sessionId" in payload and "transformedPrompt" in payload:
        return "UserPromptTransformed"  # configured by its camelCase name: the payload has no event name either
    return name


def matches(payload: Dict[str, Any]) -> bool:
    return event_name(payload) in EVENT_NAMES


def engine(payload: Dict[str, Any]) -> str:
    """`cli` for a Copilot (SDK) session, `legacy` for a Local one, `unknown` when the payload shows neither (e.g. a subagent's `file_search`)."""
    transcript = str(payload.get("transcript_path") or "")
    if (
        "tool_result" in payload
        or "sessionId" in payload
        or "stop_reason" in payload
        or "agent_name" in payload
        or payload.get("hook_event_name") == "PostToolUseFailure"
        or payload.get("tool_name") in _CLI_TOOLS
        or "session-state" in transcript
    ):
        return "cli"
    if "tool_use_id" in payload or "tool_response" in payload or transcript:
        return "legacy"
    return "unknown"


def _result_text(payload: Dict[str, Any]) -> str:
    result = payload.get("tool_result")
    if isinstance(result, dict):
        return common.text(result.get("text_result_for_llm"))
    return common.text(result)


def parse(payload: Dict[str, Any]) -> HookEvent:
    event = common.build_event(
        SURFACE,
        event_name(payload),
        payload,
        payload.get("session_id") or payload.get("sessionId"),
        payload.get("tool_name"),
        payload.get("tool_input"),
    )
    event.cwd = common.text(payload.get("cwd"))
    event.timestamp = common.text(payload.get("timestamp"))
    event.prompt = common.text(payload.get("prompt"))
    event.tool_response = _result_text(payload)
    event.error = common.text(payload.get("error"))
    event.agent_id = common.text(payload.get("agent_id"))
    event.agent_type = common.text(payload.get("agent_type") or payload.get("agentName"))
    event.stop_hook_active = bool(payload.get("stop_hook_active"))
    event.transformed_prompt = common.text(payload.get("transformedPrompt") or payload.get("transformed_prompt"))
    return event


def render(event: HookEvent, decision: Optional[Decision]) -> Dict[str, Any]:
    return common.render(event, decision)
