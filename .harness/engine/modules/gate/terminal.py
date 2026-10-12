"""Terminal commands: what writes a guardrail file, what is denied, what needs a person to confirm.

Reads (`cat`, `rg`, `ls`, `git diff`) match nothing here. A command that matches nothing is allowed, and the
runtime's own terminal confirmation still applies. This is a net for common cases, not a sandbox: a command can write
any path in ways a regular expression does not see.
"""

from __future__ import annotations

import re
from typing import List, Optional, Pattern, Tuple

from .policy import Compiled

# (permission, why)
Verdict = Tuple[str, str]


_SEPARATORS = ";&|(\n"


def normalize(command: str) -> str:
    """One spelling for paths in a command (`\\` becomes `/`), and quoted text cannot start a new command.

    `rg "rm -rf|git checkout" src` has a `|` inside quotes. It is not a pipe, so it is turned into a space.
    A quote that never closes is left alone.
    """
    text = command.replace("\\", "/")
    out = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in "\"'":
            end = text.find(char, index + 1)
            if end != -1:
                inner = "".join(" " if item in _SEPARATORS else item for item in text[index + 1:end])
                out.append(char + inner + char)
                index = end + 1
                continue
        out.append(char)
        index += 1
    return "".join(out)


_CD = re.compile(r"^(?:cd|pushd|chdir|set-location|push-location|sl)$", re.IGNORECASE)
_SPLIT = re.compile(r"(\s*(?:&&|\|\||[;&|\n()])\s*)")
_REDIRECT = re.compile(r"^(\d*>>?)(.*)$")
_INLINE = re.compile(r"^(?:python3?|py|node|perl|ruby)$", re.IGNORECASE)


def _bare(word: str) -> str:
    return word.strip("\"'")


def _relative(word: str) -> bool:
    """A word that can be a path under the current folder: not an option, not absolute, not a variable, not a URL."""
    text = _bare(word)
    return bool(text) and not text.startswith(("-", "/", "~", "$", "%", "<", ">", "{", "*")) and ":" not in text and "=" not in text


def _join(folder: str, word: str) -> str:
    quote = word[0] if word[:1] in "\"'" and word[-1:] == word[:1] and len(word) > 1 else ""
    return f"{quote}{folder.rstrip('/')}/{_bare(word).lstrip('./') if _bare(word).startswith('./') else _bare(word)}{quote}"


def after_cd(text: str) -> Optional[str]:
    """The command with the paths after a `cd` written out from where the command began, or None when it has no `cd`.

    `cd tasks/t1/.task && echo x > task.json` names no guarded path in any single part. Written out it is
    `echo x > tasks/t1/.task/task.json`, and the write rules see it. An inline script (`python -c`) after a `cd` gets the
    folder as a word in front of its code, so the inline-script rule sees a guarded folder. A `cd` to a variable ends the
    rewriting: where it goes is not known. This stays a net, not a sandbox.
    """
    folder = ""
    found = False
    out = []
    for part in _SPLIT.split(text):
        if not part or _SPLIT.fullmatch(part):
            out.append(part)
            continue
        words = part.split()
        if not words:
            out.append(part)
            continue
        if _CD.match(words[0]):
            target = _bare(next((word for word in words[1:] if not word.startswith("-")), ""))
            if not target or target.startswith(("$", "%", "-")):
                return "".join(out) + text[len("".join(out)):] if found else None  # unknown from here on
            folder = target if target.startswith(("/", "~")) or ":" in target or not folder else f"{folder.rstrip('/')}/{target}"
            found = True
            out.append(part)
            continue
        if not folder:
            out.append(part)
            continue
        rewritten = [words[0]]
        for word in words[1:]:
            redirect = _REDIRECT.match(word)
            if redirect and redirect.group(2):
                rewritten.append(redirect.group(1) + (_join(folder, redirect.group(2)) if _relative(redirect.group(2)) else redirect.group(2)))
            elif _relative(word):
                rewritten.append(_join(folder, word))
            else:
                rewritten.append(word)
        if _INLINE.match(words[0]):
            rewritten.insert(1, folder.rstrip("/") + "/")  # the script runs in that folder: its bare file names are in it
        out.append(" ".join(rewritten))
    return "".join(out) if found else None


def _texts(command: str) -> List[str]:
    text = normalize(command)
    try:
        moved = after_cd(text)
    except Exception:  # noqa: BLE001 - the plain text is still checked
        moved = None
    return [text, moved] if moved and moved != text else [text]


def _first(command: str, rules: List[Tuple[Pattern[str], str]]) -> Optional[str]:
    for text in _texts(command):
        for regex, why in rules:
            if regex.search(text):
                return why
    return None


def guardrail_write(command: str, compiled: Compiled) -> Optional[str]:
    """Why this command changes a guardrail file, or None."""
    return _first(command, compiled.guard_writes)


def owned_write(command: str, compiled: Compiled) -> Optional[str]:
    """Why this command changes a file only the CLI writes, or None."""
    return _first(command, compiled.owned_writes)


def git_write(command: str, compiled: Compiled) -> Optional[str]:
    """Why this command changes a `.git` folder or a path a target repository refuses, or None."""
    return _first(command, compiled.target_writes)


def tree_write(command: str, compiled: Compiled) -> Optional[str]:
    """Why this command writes into the working tree of a target repository (named by its full path), or None."""
    return _first(command, compiled.tree_writes)


def check(command: str, compiled: Compiled) -> Optional[Verdict]:
    """`("deny", why)`, `("ask", why)` or None. Deny rules come first."""
    if not command.strip():
        return None
    text = normalize(command)
    for regex, why in compiled.deny:
        if regex.search(text):
            return "deny", why
    for regex, why in compiled.ask:
        if regex.search(text):
            return "ask", why
    return None
