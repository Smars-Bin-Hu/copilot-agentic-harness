"""HookEvent (what a hook received) and Decision (what a module wants), independent of the runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

EVENT_NAMES = (
    "SessionStart",
    "UserPromptSubmit",
    "UserPromptTransformed",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PreCompact",
    "SubagentStart",
    "SubagentStop",
    "Stop",
)

# The hook config key of an event that has no VS Code (PascalCase) name: only the SDK engine has it.
CONFIG_KEYS = {"UserPromptTransformed": "userPromptTransformed"}

PERMISSION_RANK = {"allow": 1, "ask": 2, "deny": 3}


@dataclass
class HookEvent:
    surface: str
    event: str
    session_id: str
    cwd: str = ""
    timestamp: str = ""
    prompt: str = ""
    tool_name: str = ""
    tool_kind: str = ""
    command: str = ""
    paths: List[str] = field(default_factory=list)
    is_search: bool = False
    subagent_target: str = ""
    subagent_prompt: str = ""
    agent_id: str = ""
    agent_type: str = ""
    tool_response: str = ""
    # PostToolUseFailure (SDK engine): why the tool call failed, in the words of the engine.
    error: str = ""
    # The name of the skill a `skill` tool call loads.
    skill: str = ""
    stop_hook_active: bool = False
    # UserPromptTransformed (SDK engine): the whole text the model is about to get, the context of UserPromptSubmit included.
    transformed_prompt: str = ""
    # Set by core, not by the adapter: this UserPromptSubmit is a subagent call message, not the user.
    from_subagent: bool = False
    # Set by core: this UserPromptSubmit is the engine feeding back the reason of a Stop block, not the user (SDK engine).
    continuation: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    permission: Optional[str] = None  # allow | ask | deny (PreToolUse)
    reason: str = ""  # why denied, or why Stop is blocked
    block: bool = False  # Stop / SubagentStop
    context: str = ""  # text for the model (UserPromptSubmit, SessionStart, SubagentStart)
    prompt: str = ""  # UserPromptTransformed: the whole text the model gets instead (empty: it stays as it is)
    # Facts for the call log (observe). Not a decision: `merge` ignores them, and a Decision with only facts is empty.
    # Known keys: `kind` (what kind of refusal, e.g. "task-scope"), `judge` ("reviewer"), `verdict` ("PASS", "FAIL", "unknown").
    facts: Dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.permission or self.block or self.context or self.prompt)


def merge(decisions: Iterable[Optional[Decision]]) -> Decision:
    """deny > ask > allow. Contexts join in order. One block is enough to block."""
    items = [item for item in decisions if item is not None and not item.is_empty()]
    merged = Decision()
    ranked = [item.permission for item in items if item.permission in PERMISSION_RANK]
    if ranked:
        merged.permission = max(ranked, key=lambda name: PERMISSION_RANK[name])
    merged.block = any(item.block for item in items)
    reasons = [
        item.reason
        for item in items
        if item.reason and ((item.permission and item.permission == merged.permission) or item.block)
    ]
    merged.reason = "\n".join(reasons)
    merged.context = "\n\n".join(item.context for item in items if item.context)
    merged.prompt = next((item.prompt for item in items if item.prompt), "")
    return merged
