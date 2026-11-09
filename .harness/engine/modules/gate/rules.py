"""Texts the model sees when the gate refuses a call. Each says why it was refused and what to do next.

The texts are in the message table (`gate.*`). The log keeps only the first characters of a reason
(observe.json: max_text_chars), so each text starts with what happened and what to do.
"""

from __future__ import annotations

from typing import Any

from core import messages
from core.systems import place, verb_word
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
    """The kind of a call as a person reads it: the protocol word in English (`write`); in Chinese the word of the board only (`写`)."""
    return verb_word(verb)


def _verb(verb: str) -> str:
    """The verb with its article, for the English texts ("a write", "an exec"); the zh texts have the word of the board and no article."""
    return ("an " if verb[:1] in "aeiou" else "a ") + verb if messages.language() == "en" else word(verb)


def external_subagent(action: Any, command: str, agent: str) -> str:
    return say("gate.external.subagent", agent=agent, place=place(action.system, action.env), verb=word(action.verb), call=command)


def external_denied(action: Any, command: str, hint: Any = "") -> str:
    """`command` is the whole line as the agent wrote it: the person copies it, so its quotes must stay. `hint` (1.7.38, D1-7): the system's own words on what to do instead."""
    text = say("gate.external.denied", place=place(action.system, action.env), verb=word(action.verb), call=command)
    shown = messages.pick(hint) if hint else ""
    return text + messages.gap() + shown if shown else text


def external_denied_file(action: Any, command: str) -> str:
    """1.7.38, C12 RC-G1: the call is refused because of what a file it reads holds (`sqlcmd -i drop.sql`): the line names the file."""
    return say("gate.external.denied_file", place=place(action.system, action.env), verb=word(action.verb), file=action.file, call=command)


def external_refused(action: Any, command: str) -> str:
    """1.7.38, C12: a statement is on the refuse list of the type. The line says which one (and the file that holds it) and gives the reason the type wrote, which tells the agent the right way."""
    key = "gate.external.refused_file" if action.file_why == "refuse" and action.file else "gate.external.refused"
    return say(key, place=place(action.system, action.env), statement=action.note, file=action.file, reason=action.reason, call=command)


def external_human(action: Any, command: str) -> str:
    """`command` is the whole line as the agent wrote it: the person copies it, so its quotes must stay."""
    return say("gate.external.human", place=place(action.system, action.env), verb=word(action.verb), call=command, handoff_env="" if action.env in ("", "none") else f" --env {action.env.upper()}")


def external_task(action: Any, command: str) -> str:
    """`command` is the whole line as the agent wrote it: the person copies it, so its quotes must stay."""
    return say("gate.external.task", place=place(action.system, action.env), verb=word(action.verb), call=command)


def _what(action: Any, key: str) -> str:
    """The first sentence of a held call's text: what kind of call it is. A call of a pack whose file is faulty (G-1) has no kind: the gate could not judge it (1.7.38, M5), and it must not be told as a write."""
    place_ = place(action.system, action.env)
    if getattr(action, "zone", "") == "broken":
        return say(f"{key}.what.unknown", place=place_)
    return say(f"{key}.what", place=place_, verb=_verb(action.verb))


def too_many_waiting() -> str:
    """(1.7.38, C13 M1) A new call is not held because too many wait for the person already: one line that tells the agent to stop and the user to handle them first."""
    from core import approvals

    return say("gate.approvals.too_many", n=approvals.MAX_PENDING)


def external_outbox(action: Any, command: str, code: str, minutes: int, draft: str, offers: Any = None, changed: Any = None) -> str:
    where = say("gate.external.outbox_draft", draft=draft) if draft else say("gate.external.outbox_nodraft")
    key = {"unread": "gate.external.input_unread", "twice": "gate.external.input_twice"}.get(getattr(action, "file_why", ""))  # 1.7.38: a file the gate could not judge made this a write
    gap = messages.gap()
    note = say(key, file=action.file) + gap if key else ""
    if getattr(action, "zone", "") == "broken":  # 1.7.38 (G-1): a file of the tool pack is faulty: the call waits, and the line says which file and what is wrong
        note = say("gate.external.broken", note=action.note) + gap
    elif not key and getattr(action, "zone", "") == "ask" and action.note:  # 1.7.38: a call of a type with lists that is on no list: it waits, and opening the connection will not pass it
        note = say("gate.external.zone_ask", statement=action.note, place=place(action.system, action.env)) + gap
    text = note + (say("gate.external.changed_file", files=", ".join(str(one) for one in changed)) + gap if changed else "") + say("gate.external.outbox", what=_what(action, "gate.external.outbox"), call=command, code=code, minutes=minutes, where=where)
    if offers:  # 1.7.38: the card can also open the connection for the task; the agent says so, and runs the same command again if the user does
        buttons = messages.joined(say("gate.external.outbox.button", text=say("desk.outbox.open.items" if item.get("scope") == "items" else "desk.outbox.open", name=str(item["system"]))) for item in offers)  # the buttons as the card names them (C12 N12): a connection that opens only the linked items has its own words
        text += gap + say("gate.external.outbox.opens", buttons=buttons)
    return text + gap + say("gate.external.outbox.code", code=code)  # 1.7.38, C12 TB-10: the agent wrote the code in the chat: the person may then approve without reading the card first


def external_autorun(action: Any, command: str) -> str:
    return say("gate.external.autorun", what=_what(action, "gate.external.autorun"), call=command)


def external_approved(commands: Any) -> str:
    return say("gate.external.approved", calls="\n".join(f"- {item}" for item in commands))
