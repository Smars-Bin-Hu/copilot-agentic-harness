"""Texts the model sees when the gate refuses a call. Each says why it was refused and what to do next.

The texts are in the message table (`gate.*`). The log keeps only the first characters of a reason
(observe.json: max_text_chars), so each text starts with what happened and what to do.
"""

from __future__ import annotations

from typing import Any

from core import messages
from core.systems import place
from core.paths import cli_command


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def write_no_path(tool: str) -> str:
    return say("gate.write.no_path", tool=tool)


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


def task_plan_req(relative: str, task: str) -> str:
    return say("gate.task.plan_req", relative=relative, task=task)


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


def word(verb: str) -> str:
    """The kind of a call as a person reads it: the protocol word in English (`write`); in Chinese the word of the board with the protocol word after it (`写（write）`: the rules and the log use it)."""
    if messages.language() == "en":
        return verb
    found = messages.text(f"desk.outbox.verb.{verb}")
    return verb if found == f"desk.outbox.verb.{verb}" else f"{found}（{verb}）"


def _verb(verb: str) -> str:
    """The verb with its article, for the English texts ("a write", "an exec"); the zh texts have the word of the board and no article."""
    return ("an " if verb[:1] in "aeiou" else "a ") + verb if messages.language() == "en" else word(verb)


def external_subagent(action: Any, command: str, agent: str) -> str:
    return say("gate.external.subagent", agent=agent, place=place(action.system, action.env), verb=word(action.verb), call=command)


def external_denied(action: Any, command: str) -> str:
    """`command` is the whole line as the agent wrote it: the person copies it, so its quotes must stay."""
    return say("gate.external.denied", place=place(action.system, action.env), verb=word(action.verb), call=command)


def external_human(action: Any, command: str) -> str:
    """`command` is the whole line as the agent wrote it: the person copies it, so its quotes must stay."""
    return say("gate.external.human", place=place(action.system, action.env), verb=word(action.verb), call=command, handoff_env="" if action.env in ("", "none") else f" --env {action.env.upper()}")


def external_task(action: Any, command: str) -> str:
    """`command` is the whole line as the agent wrote it: the person copies it, so its quotes must stay."""
    return say("gate.external.task", place=place(action.system, action.env), verb=word(action.verb), call=command)


def external_outbox(action: Any, command: str, code: str, minutes: int, draft: str, offers: Any = None, changed: Any = None) -> str:
    where = say("gate.external.outbox_draft", draft=draft) if draft else say("gate.external.outbox_nodraft")
    text = (say("gate.external.changed_file", files=", ".join(str(one) for one in changed)) + " " if changed else "") + say("gate.external.outbox", place=place(action.system, action.env), verb=_verb(action.verb), call=command, code=code, minutes=minutes, where=where)
    if offers:  # 1.7.38: the card can also open the connection for the task; the agent says so, and runs the same command again if the user does
        names = ", ".join(str(item["system"]) for item in offers)
        text += " " + say("gate.external.outbox.opens", names=names)
    return text + " " + say("gate.external.outbox.code", code=code)  # 1.7.38, C12 TB-10: the agent wrote the code in the chat: the person may then approve without reading the card first


def external_autorun(action: Any, command: str) -> str:
    return say("gate.external.autorun", place=place(action.system, action.env), verb=_verb(action.verb), call=command)


def external_approved(commands: Any) -> str:
    return say("gate.external.approved", calls="\n".join(f"- {item}" for item in commands))
