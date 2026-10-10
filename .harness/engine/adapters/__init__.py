"""Runtime adapters: raw hook payload <-> HookEvent / Decision."""

from __future__ import annotations

from typing import Any, Dict

from . import copilot_vscode

_ADAPTERS = (copilot_vscode,)


def detect(payload: Dict[str, Any]) -> Any:
    """Pick the adapter for this payload."""
    for adapter in _ADAPTERS:
        if adapter.matches(payload):
            return adapter
    raise ValueError("Unrecognized hook payload: no adapter matches")


def get(surface: str) -> Any:
    for adapter in _ADAPTERS:
        if adapter.SURFACE == surface:
            return adapter
    raise ValueError(f"Unknown surface: {surface}")
