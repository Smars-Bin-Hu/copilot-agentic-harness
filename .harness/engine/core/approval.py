"""A person's approval at a terminal: the one mechanism behind approve-plan, approve-promote and recover.

A tool-call dialog cannot be the guard ("Allow in this Session" switches it off), so the approval needs a terminal the
person types in (stdin and stdout are a TTY) and a code that is bound to what is approved (the first characters of a
sha256). The gate also denies an agent that tries to run these commands.

The screen stays short on purpose: it names the file to read in the editor and never prints the content itself.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Optional

from . import messages

CODE_LENGTH = 6  # as long as the code of a held outside call, and written the same way: capitals (C12 N13: the code of a requirement was 8 small letters and digits, the others 6 capitals)


class Refused(Exception):
    """Not approved. The message says why and what to do next."""


def code_of(digest: str) -> str:
    return digest[:CODE_LENGTH].upper()


def terminal_person() -> bool:
    """A person runs this command: a terminal with a keyboard and a screen, or the board's Terminal window, which the board vouches for with a one-time code (1.7.39, `boardperson`)."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        return True
    from . import boardperson

    return boardperson.use()


def require_person(command: str, interactive: Optional[bool] = None, typed: bool = True) -> None:
    """`interactive` exists so tests can stand in for a person; the CLI passes None. `typed`: the command goes on to ask for a code."""
    if interactive is None:
        interactive = terminal_person()
    if not interactive:
        raise Refused(messages.text("approval.person_only.typed" if typed else "approval.person_only", name=command))


def is_person(interactive: Optional[bool] = None) -> bool:
    """Is this a person at a terminal? `interactive`: for the tests."""
    return terminal_person() if interactive is None else bool(interactive)


def ask(question: str, digest: str, refusal: str, reader: Optional[Callable[[str], str]] = None) -> None:
    """Ask the person to type the code of `digest`. Anything else raises Refused(refusal)."""
    code = code_of(digest)
    try:
        answer = (reader or input)(messages.text("approval.ask", question=question, code=code)).strip()
    except EOFError:  # (1.7.39) no keyboard behind this command: the board's Terminal window gives none
        raise Refused(messages.text("approval.no_input")) from None
    if answer.upper() != code:  # the letters of the code are capitals; a person may type them small. The old code of 8 small characters (before 1.7.38) is not taken any more
        raise Refused(refusal)


def say(out: Any, *lines: str) -> None:
    for line in lines:
        print(line, file=out or sys.stdout)
