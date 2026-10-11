"""Gate: guardrail files, the write scope of a task and dangerous terminal commands. Policy: .harness/policies/gate.json."""

from .handler import NAME, handle
from .policy import POLICY_NAME, validate_policy

__all__ = ["NAME", "POLICY_NAME", "handle", "validate_policy"]
