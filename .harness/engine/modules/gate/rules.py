"""Texts the model sees when the gate refuses a call. Each says why it was refused and what to do next.

The texts are in the message table (`gate.*`). The log keeps only the first characters of a reason
(observe.json: max_text_chars), so each text starts with what happened and what to do.
"""

from __future__ import annotations

from typing import Any

from core import messages
from core.paths import cli_command


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def guardrail_file(relative: str, pattern: str) -> str:
    return say("gate.guardrail.file", relative=relative, pattern=pattern)


def admin_locked_file(relative: str, pattern: str) -> str:
    return say("gate.admin.file", relative=relative, pattern=pattern)


def admin_locked_terminal(why: str) -> str:
    return say("gate.admin.terminal", why=why)


def guardrail_terminal(why: str) -> str:
    return say("gate.guardrail.terminal", why=why)


def git_folder(shown: str) -> str:
    return say("gate.git_folder.file", shown=shown)


def git_folder_terminal(why: str) -> str:
    return say("gate.git_folder.terminal", why=why)


def target_refused_file(repo: str, relative: str, pattern: str) -> str:
    return say("gate.target.refused", repo=repo, relative=relative, pattern=pattern)


def target_tree_file(repo: str, relative: str) -> str:
    return say("gate.target.direct", repo=repo, relative=relative)


def target_tree_terminal(why: str) -> str:
    return say("gate.target.terminal", why=why)


def task_plan_first(relative: str, task: str) -> str:
    return say("gate.task.plan_first", relative=relative, task=task)


def task_outside(relative: str, task: str) -> str:
    return say("gate.task.outside", relative=relative, task=task)


def task_person_files(relative: str, task: str) -> str:
    return say("gate.task.person_files", relative=relative, task=task)


def terminal_denied(why: str) -> str:
    return say("gate.terminal.denied", why=why)


def board_request(port: int) -> str:
    return say("gate.board.request", port=port)


def terminal_ask(why: str) -> str:
    return say("gate.terminal.ask", why=why)


def cli_owned_file(relative: str) -> str:
    return say("gate.cli_owned.file", relative=relative)


def cli_owned_terminal(why: str) -> str:
    return say("gate.cli_owned.terminal", why=why)


def git_never(why: str, command: str) -> str:
    return say("gate.git.never", why=why, git_command=command)


def git_needs_approval(why: str, command: str, code: str, minutes: int) -> str:
    return say("gate.git.needs_approval", why=why, git_command=command, code=code, minutes=minutes)
