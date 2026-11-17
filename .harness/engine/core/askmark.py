"""The mark of a question to a task through the board (1.8.2): a message that starts with `/harness-ask`. The board writes it (`modules/task/superroute.py`); the gate makes that turn
read only (`modules/gate/askturn.py`) and the task hooks leave the task as it was (`modules/task/handler.py`). It is here, in core, because both modules need it."""

from __future__ import annotations

MARKER = "/harness-ask"


def is_marker(prompt: str) -> bool:
    text = str(prompt or "").lstrip()
    return text.startswith(MARKER) and (len(text) == len(MARKER) or text[len(MARKER)].isspace())
