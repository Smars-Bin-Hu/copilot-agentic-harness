"""The variables and the command substitutions of a terminal command line, read the way the gate needs them (hook speed round 3, red team: a write to a guardrail folder through a path built at run time). Standard library only.

`d=.harness; printf x > $d/runtime/x.json` names no guardrail path in any one place: the literal rules of the gate see `$d/runtime`. Two helpers read what the line itself says about it:

- `scan`: one pass over the text, character by character (never a pattern that can go back), that keeps what the shell keeps together as one word. The text comes out twice, of the same length: as it was written (`plain`) and as the
  gate reads the structure (`mask`): a `;`, `&`, `|`, `<`, `>`, `(`, `)` or a new line inside a quote or inside `$( )`, a backtick pair or `${ }` is no separator, so it is replaced by `FILL`; the opening and closing of a
  substitution are `TICK`. A `$(echo x)` or a backtick pair that only echoes one plain word is taken as that word (`$(echo .harness)/runtime` is `.harness/runtime`). A `$` inside single quotes is `LITERAL` in the mask: nothing puts
  a value in there.
- `expand`: the same line with the variables the line sets in it put in, segment by segment, in the order they are set (`d=.harness`, `export d=...`, `$d = '.harness'`, `$env:d=...`, `set d=.harness`, `set "d=..."`, `for d in a b`),
  as `$d`, `${d}`, `$env:d` and `%d%`. What is not known stays as it is. The result can be read by every rule that reads a line as written (`terminal._texts`, `scriptcheck.refusal`).

Both take time in proportion to the length of the text. The nesting is limited (`MAX_DEPTH`) and so is the size of the expanded text (`EXPAND_CAP`: `a=xxxx...; echo $a$a$a...` would double it at each step); a line that goes over either is reported
as one that could not be read (`ok` False), and the caller refuses it."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

FILL = "\x01"  # in the mask: a character that is part of a word, whatever it is in the text
TICK = "\x03"  # in the mask: where a substitution opens or closes
LITERAL = "\x02"  # in the mask: a `$` inside single quotes
MAX_DEPTH = 64
EXPAND_CAP = 200_000
VARIANTS = 6  # a `for` over several values is read once for each of the first ones

_SPECIAL = frozenset(";&|<>()\n")
_SPACE = frozenset(" \t\r\n\f\v")
_ESCAPABLE = frozenset(" \t;&|<>()\"'$`\\\n")
_ROOT_SEPARATORS = frozenset(";&|\n()")


class _Frame:
    __slots__ = ("kind", "quote", "plain", "mask", "depth")

    def __init__(self, kind: str) -> None:
        self.kind = kind  # root, paren (`$( )`), tick (a backtick pair), brace (`${ }`)
        self.quote = ""
        self.plain: List[str] = []
        self.mask: List[str] = []
        self.depth = 0


def _evaluate(inner: str) -> Optional[str]:
    """What a substitution that only echoes one plain word is: `echo .harness`, `echo -n x`, `printf %s x`. None for anything else (a command's output is not known)."""
    parts = inner.split()
    if len(parts) == 3 and (parts[:2] == ["echo", "-n"] or parts[:2] == ["printf", "%s"]):
        word = parts[2]
    elif len(parts) == 2 and parts[0] in ("echo", "printf"):
        word = parts[1]
    else:
        return None
    word = word.replace('"', "").replace("'", "")
    if not word or any(char in word for char in "$`(){}*?[]%\\;&|<>~") or word.startswith("-"):
        return None
    return word


def scan(text: str) -> Tuple[str, str, bool]:
    """`(plain, mask, ok)`: see the top of the file. `plain` and `mask` are as long as each other. `ok` is False when substitutions are nested deeper than `MAX_DEPTH`."""
    root = _Frame("root")
    stack = [root]
    ok = True
    index, size = 0, len(text)

    def emit(frame: _Frame, plain: str, mask: str) -> None:
        frame.plain.append(plain)
        frame.mask.append(mask)

    def close(frame: _Frame) -> None:
        inner_plain, inner_mask = "".join(frame.plain), "".join(frame.mask)
        parent = stack[-1]
        word = _evaluate(inner_plain) if frame.kind in ("paren", "tick") and "(" not in inner_plain[:1] else None
        if word is not None:
            emit(parent, word, word)
        elif frame.kind == "tick":
            emit(parent, "`" + inner_plain + "`", TICK + inner_mask + TICK)
        elif frame.kind == "paren":
            emit(parent, "$(" + inner_plain + ")", "$" + TICK + inner_mask + TICK)
        else:
            emit(parent, "${" + inner_plain + "}", "$" + TICK + inner_mask + TICK)

    while index < size:
        char = text[index]
        frame = stack[-1]
        inner = len(stack) > 1
        quote = frame.quote
        if char == "\\" and quote != "'" and index + 1 < size and text[index + 1] in _ESCAPABLE:
            following = text[index + 1]
            emit(frame, char + following, char + (FILL if (inner or quote) or following in _SPECIAL or following in _SPACE or following in "\"'" else following))
            index += 2
            continue
        if char == "$" and quote != "'" and index + 1 < size and text[index + 1] in "({":
            if len(stack) <= MAX_DEPTH:
                stack.append(_Frame("paren" if text[index + 1] == "(" else "brace"))
                index += 2
                continue
            ok = False
        elif char == "`" and quote != "'":
            if frame.kind == "tick":
                stack.pop()
                close(frame)
                index += 1
                continue
            if len(stack) <= MAX_DEPTH:
                stack.append(_Frame("tick"))
                index += 1
                continue
            ok = False
        elif char in "\"'":
            if not quote:
                frame.quote = char
            elif quote == char:
                frame.quote = ""
            emit(frame, char, FILL if inner else char)
            index += 1
            continue
        elif not quote:
            if frame.kind == "paren":
                if char == ")":
                    if frame.depth == 0:
                        stack.pop()
                        close(frame)
                        index += 1
                        continue
                    frame.depth -= 1
                elif char == "(":
                    frame.depth += 1
            elif frame.kind == "brace" and char == "}":
                stack.pop()
                close(frame)
                index += 1
                continue
        if char == "$" and quote == "'":
            mask = LITERAL
        elif inner or quote:
            mask = FILL if (char in _SPECIAL or (inner and char in _SPACE)) else char
        else:
            mask = char
        emit(frame, char, mask)
        index += 1
    while len(stack) > 1:  # a substitution that never closed: its text stays, as one word
        frame = stack.pop()
        inner_plain, inner_mask = "".join(frame.plain), "".join(frame.mask)
        opener = {"paren": ("$(", "$" + TICK), "tick": ("`", TICK), "brace": ("${", "$" + TICK)}[frame.kind]
        emit(stack[-1], opener[0] + inner_plain, opener[1] + inner_mask)
    return "".join(root.plain), "".join(root.mask), ok


# --- variables ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

_HEAD = re.compile(r"[ \t]*(?:(?:do|then|else|elif|if|while|until|\{|!)[ \t]+)*")
_FOR = re.compile(r"for[ \t]+\$?([A-Za-z_]\w*)[ \t]+in[ \t]+", re.IGNORECASE)
_ASSIGN = re.compile(
    r"""(?:(?:export|declare|typeset|local|readonly|set|setx)[ \t]+(?:-\w+[ \t]+)*)?(?:\$(?:env:|script:|global:|local:)?)?(["']?)([A-Za-z_]\w*)[ \t]*(\+?=)[ \t]*""", re.IGNORECASE
)
_USE = re.compile(r"\$env:(\w+)|\$\{(\w+)\}|\$(\w+)|%(\w+)%", re.IGNORECASE)
_PERCENT = re.compile(r"%\w+%")


def dynamic(word: str) -> bool:
    """Is this word of a command built at run time: `$x`, `${x}`, `$(...)`, a backtick pair, `%X%` (cmd), `$env:X` (PowerShell)? (The words of `scan`'s mask: a `$` inside single quotes is not one.)"""
    return "$" in word or bool(_PERCENT.search(word))


def _word_end(segment: str, start: int, quote: str) -> int:
    end = start
    while end < len(segment):
        char = segment[end]
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char in " \t\r":
            break
        end += 1
    return end


class _Run:
    """One reading of the line: the values set so far, the size of what was put in."""

    def __init__(self, choice: int) -> None:
        self.known: Dict[str, str] = {}
        self.choice = choice
        self.size = 0
        self.over = False

    def put(self, text: str) -> str:
        def one(found: "re.Match[str]") -> str:
            name = next(group for group in found.groups() if group)
            value = self.known.get(name.lower())
            if value is None:
                return found.group(0)
            self.size += len(value)
            if self.size > EXPAND_CAP:
                self.over = True
                return found.group(0)
            return value
        return _USE.sub(one, text) if ("$" in text or "%" in text) else text


def _read(plain: str, mask: str, choice: int) -> Tuple[str, bool, int]:
    """`(expanded text, ok, the most values a `for` was given)`."""
    run = _Run(choice)
    out: List[str] = []
    widest = 1
    index, size = 0, len(mask)
    while index <= size:
        end = index
        while end < size and mask[end] not in _ROOT_SEPARATORS:
            end += 1
        segment = plain[index:end]
        head = _HEAD.match(segment).end()  # type: ignore[union-attr]
        found = _FOR.match(segment, head)
        pure = False
        if found:
            values = [item.replace('"', "").replace("'", "") for item in segment[found.end():].split()]
            values = [run.put(item) for item in values if item]
            widest = max(widest, len(values))
            if values:
                run.known[found.group(1).lower()] = values[min(run.choice, len(values) - 1)]
        else:
            at = head
            while True:
                match = _ASSIGN.match(segment, at)
                if not match:
                    break
                stop = _word_end(segment, match.end(), match.group(1))
                value = run.put(segment[match.end():stop].replace('"', "").replace("'", ""))
                name = match.group(2).lower()
                run.known[name] = (run.known.get(name, "") + value) if match.group(3) == "+=" else value
                at = stop
                while at < len(segment) and segment[at] in " \t\r":
                    at += 1
                pure = at >= len(segment)
        out.append(segment if pure or found else run.put(segment))  # a line that only sets a value (or names the values of a loop) is left as it is
        if end < size:
            out.append(plain[end])
        index = end + 1
    return "".join(out), not run.over, widest


def expand(text: str) -> Tuple[List[str], bool]:
    """`(texts, ok)`: the readings of the line with its own variables put in, each different from `text`; `[]` when the line sets none that it uses. `ok` False: the line could not be read (nested deeper than `MAX_DEPTH`, or
    its expanded text over `EXPAND_CAP`): the caller does not pass it."""
    if "$" not in text and "%" not in text and "`" not in text:
        return [], True
    plain, mask, ok = scan(text)
    found: List[str] = []
    for choice in range(VARIANTS):
        read, fine, widest = _read(plain, mask, choice)
        ok = ok and fine
        if read != text and read not in found:
            found.append(read)
        if choice + 1 >= widest:
            break
    return found, ok
