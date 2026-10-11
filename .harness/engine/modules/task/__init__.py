"""Task: the task folder, its life, its two approvals, its independent checks, and what every prompt is told. Policy: task.json."""

from .handler import NAME, handle
from .policy import POLICY_NAME, validate_policy

__all__ = ["NAME", "POLICY_NAME", "handle", "validate_policy"]
