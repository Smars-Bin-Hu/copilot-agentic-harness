"""Which connection does a call reach? (1.7.38, C13 F2)

A tool pack type that takes its target on the command line (`sqlcmd -S host,port`) says how, in its `pin`:

  options      the options that name the target (`["-S", "--server"]`); the first one is how the gate writes it back when it matches the call with the connections
  fold         `[[pattern, replacement], ...]` applied to the value in order, ignoring case: the spellings that are certainly the same place (`tcp:` in front, a space around the comma, `host:port`
               for `host,port`, a dot at the end of the host, zeros in front of the port, the default port when none is given). Nothing else is folded and nothing is ever looked up in a name server
  other        options that choose the target in a way the gate cannot read (`-D`: the server name is a data source name)
  subcommand   true: a first word that is not an option is a subcommand of the program (`sqlcmd query "..."`): it runs on a target the line does not show
  free         options that only print help (`-?`, `--help`): such a call reaches nothing. A pin that has no `free` takes `DEFAULT_FREE` (`--help`, `-h`, `-?`, `--version`), and then only a call made of those words and nothing else
               is free (1.7.38, C13 F2c); `"free": []` turns it off

A call is pinned when exactly one option names a target, its value can be read and, folded, is the address of a connection (the caller matches it). Everything else is not pinned, and the gate does not
guess: the call is refused, with the way to a connection (`harness connections find`). Stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.systems import DEFAULT_FREE  # noqa: F401 - the words a pin with no `free` takes

OK, NONE, MANY, UNREAD, WORD, OTHER, FREE = "ok", "none", "many", "unread", "word", "other", "free"
_UNREADABLE = re.compile(r"[$`*?~{}]|%\w+%")  # the shell or the program fills these in: the gate sees the words, not the place they name


@dataclass
class Pinned:
    state: str  # OK, NONE (no option names a target), MANY (more than one), UNREAD (a value the shell or the program fills in, or one that is empty or not plain ASCII), WORD (a subcommand), OTHER (`other`), FREE (help only)
    value: str = ""  # the value as the line wrote it (the first one)
    canon: str = ""  # the value after `fold`: what is matched with the connections
    option: str = ""  # the option the gate names in its text (the first of `options`)


def _values(words: List[str], options: List[str]) -> Optional[List[str]]:
    """Every value the words give to one of `options` (`-S x`, `-Sx`, `--server x`, `--server=x`); None when an option stands last with no value."""
    found: List[str] = []
    index = 0
    while index < len(words):
        word = words[index]
        for option in options:
            if word == option:
                if index + 1 >= len(words):
                    return None
                found.append(words[index + 1])
                index += 1
                break
            if option.startswith("--") and word.startswith(option + "="):
                found.append(word[len(option) + 1:])
                break
            if not option.startswith("--") and len(option) == 2 and word.startswith(option) and len(word) > 2 and not word.startswith("--"):
                found.append(word[2:])
                break
        index += 1
    return found


def fold(pin: Dict[str, Any], value: str) -> str:
    """The value written the way a connection's address is written: only what `fold` of the type says."""
    text = value.strip()
    for step in pin.get("fold") or []:
        try:
            text = re.sub(str(step[0]), str(step[1]), text, flags=re.IGNORECASE)
        except (re.error, IndexError, TypeError):
            continue
    return text


def read(pin: Dict[str, Any], args: List[str]) -> Pinned:
    """What the words after the program (the options and the statements of the call) say about the target."""
    options = [str(item) for item in pin.get("options") or []]
    shown = options[0] if options else ""
    if not options:
        return Pinned(NONE, option=shown)
    other = [str(item) for item in pin.get("other") or []]
    if any(word == item or (item.startswith("--") and word.startswith(item + "=")) or (not item.startswith("--") and len(item) == 2 and word.startswith(item) and not word.startswith("--") and len(word) > 2)
           for word in args for item in other):
        return Pinned(OTHER, option=shown)
    given = _values(args, options)
    if pin.get("free") is None and args and all(word in DEFAULT_FREE for word in args):  # 1.7.38 (C13 F2c): the type declares no help words: the protocol's own, and nothing else on the line (no option, no value: nothing names a target)
        return Pinned(FREE, option=shown)
    free = [str(item) for item in pin.get("free") or []]
    if given is not None and not given and free and any(word in free for word in args):
        return Pinned(FREE, option=shown)
    if pin.get("subcommand") and args and not args[0].startswith("-"):
        return Pinned(WORD, value=args[0], option=shown)
    if given is None:
        return Pinned(UNREAD, option=shown)
    if not given:
        return Pinned(NONE, option=shown)
    if len(given) > 1:
        return Pinned(MANY, value=given[0], option=shown)
    value = given[0]
    if not value.strip() or not value.isascii() or _UNREADABLE.search(value):
        return Pinned(UNREAD, value=value, option=shown)
    return Pinned(OK, value=value, canon=fold(pin, value), option=shown)
