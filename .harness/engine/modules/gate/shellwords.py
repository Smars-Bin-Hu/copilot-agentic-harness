"""How the gate reads the words of a shell line and the wrappers in it (1.7.38, C13 FR3). Standard library only.

One rule: a word that was split and unquoted once is never joined again with spaces and read a second time. A `;` inside `-Q 'SELECT 1; DROP TABLE t'` is a character of the word, not a separator, and a joined
text forgets that. When a wrapper hands words to another shell, the gate reads the words as they were given (each one quoted again: `readings`) and also as the shell that gets them will join them (PowerShell and
`cmd` join the words of `-Command` and `/c` with spaces and read the result as code), and the stricter reading stands. A shell quotes in its own way (a PowerShell backtick, a `cmd` caret hide a letter from the
words as POSIX reads them), so the text of a PowerShell or `cmd` string is read once more with that escape taken away (`dialect`).

The names of the shells and the interpreters are here (`SHELL_NAMES`, `POWER_NAMES`, `INTERPRETERS`; `gitcmd.SHELLS` is made from them): one place to add a name when one is found. The wrapper words (`env`, `nohup`, `busybox`...) are `gitcmd.WRAPPERS`.
"""

from __future__ import annotations

import posixpath
import re
from typing import List, Optional, Tuple

SHELL_NAMES = frozenset("bash sh zsh dash fish ksh csh tcsh nu xonsh".split())  # a POSIX-like shell (and the ones that read the same `-c 'string'`)
POWER_NAMES = frozenset(["pwsh", "powershell"])
INTERPRETERS = frozenset("python python3 py node ruby perl cmd".split()) | SHELL_NAMES | POWER_NAMES
ENCODED = "encodedcommand"


def name(token: str) -> str:
    """`/usr/bin/git`, `C:\\Program Files\\Git\\cmd\\git.exe` and `git.exe` are all `git`."""
    base = posixpath.basename(token.replace("\\", "/")).lower()
    return base[:-4] if base.endswith(".exe") else base


def is_interpreter(token: str) -> bool:
    plain = name(token)
    return plain in INTERPRETERS or bool(re.fullmatch(r"python\d(?:\.\d+)?", plain))


def family(token: str) -> str:
    plain = name(token)
    if plain in SHELL_NAMES:
        return "shell"
    if plain in POWER_NAMES:
        return "power"
    if plain == "cmd":
        return "cmd"
    if plain == "node":
        return "node"
    if plain in ("ruby", "perl"):
        return "ruby"
    return "python"


def interp(tokens: List[str], at: int) -> Tuple[str, Optional[int]]:
    """What the interpreter at `tokens[at]` is given (1.7.25): `("script", i)` a file, `("module", i)` a module (`-m`), `("code", i)` code in the line (`-c`, `-e`, `-Command`, `/c`, `-EncodedCommand`),
    or `("stdin", None)` nothing: it reads its code from the pipe or the terminal. `i` is the index of the flag for `code`."""
    kind = family(tokens[at])
    index = at + 1
    while index < len(tokens):
        word = tokens[index]
        low = word.lower()
        if word in ("-", "<<<"):
            return "stdin", None
        if kind == "shell":
            if word in ("-o", "+o", "-O", "+O"):
                index += 2
                continue
            if word == "-s":
                return "stdin", None
            if low in ("--command", "--commands") or re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", word):  # `-c`, `-lc`, `-xc`, `-ce`; `nu --commands`, `fish --command`
                return "code", index
            if word.startswith("-") or word.startswith("+"):
                index += 1
                continue
        elif kind == "power":
            flag = low.lstrip("-/") if word[:1] in "-/" else ""
            if flag:
                if "command".startswith(flag) or ENCODED.startswith(flag) or flag == "ec":
                    if "command".startswith(flag) and index + 1 < len(tokens) and tokens[index + 1] == "-":
                        return "stdin", None  # `pwsh -Command -`: the code comes on the input
                    return "code", index
                if "file".startswith(flag):
                    return ("script", index + 1) if index + 1 < len(tokens) and tokens[index + 1] != "-" else ("stdin", None)
                index += 2 if flag in ("executionpolicy", "ep", "windowstyle", "w", "workingdirectory", "wd", "inputformat", "outputformat", "version", "v", "configurationname", "settingsfile", "custompipename") else 1
                continue
        elif kind == "cmd":
            if low in ("/c", "/k", "/r"):
                return "code", index
            index += 1  # `/d`, `/q`, `/s`, `/a`, `/u`, `/e:on`, `/v:on`, a word cmd ignores: no code in the line unless `/c` or `/k` comes
            continue
        elif kind == "node":
            if low in ("-e", "-p", "--eval", "--print"):
                return "code", index
            if low in ("-r", "--require"):
                index += 2
                continue
            if word.startswith("-"):
                index += 1
                continue
        elif kind == "ruby":
            if low == "-e" or re.fullmatch(r"-[0-9A-DF-HJ-Za-hj-z]*[eE]", word):  # `-ne`, `-pe`, `-lane` (not `-i`: it takes the rest of the word as a suffix)
                return "code", index
            if word.startswith("-"):
                index += 1
                continue
        else:
            if word == "-c":
                return "code", index
            if word == "-m":
                return ("module", index + 1) if index + 1 < len(tokens) else ("stdin", None)
            if word in ("-X", "-W", "-Q") or low in ("-w",):
                index += 2
                continue
            if word.startswith("-"):
                index += 1
                continue
        return "script", index
    return "stdin", None


def encoded(tokens: List[str], at: int) -> bool:
    """PowerShell at `tokens[at]` given an encoded command (`-EncodedCommand`, `-enc`, `-e`: any start of the word): its text is not readable."""
    return family(tokens[at]) == "power" and any(item[:1] in "-/" and len(item) > 1 and (ENCODED.startswith(item[1:].lower()) or item[1:].lower() == "ec") for item in tokens[at + 1:])


def quote(token: str) -> str:
    """The word as a POSIX shell is given it again: one word, whatever is in it."""
    return "'" + token.replace("'", "'\"'\"'") + "'" if re.search(r"[\s;&|()$`<>\"'\\]", token) or not token else token


_POWER_ESCAPE = re.compile(r"`(\r?\n|.)", re.DOTALL)
_CMD_ESCAPE = re.compile(r"\^(\r?\n|.)", re.DOTALL)


def dialect(text: str, kind: str) -> str:
    """The text of a PowerShell (`power`) or `cmd` string with the escape of that shell taken away: `` s`qlcmd `` is `sqlcmd` to PowerShell and `s^qlcmd` is `sqlcmd` to `cmd`, but a POSIX reading sees two words (a backtick
    and a caret are separators or letters there). "" when the text has no such escape. It is one reading more, never the only one."""
    if kind == "power" and "`" in text:
        return _POWER_ESCAPE.sub(lambda found: "" if found.group(1) in ("\n", "\r\n") else found.group(1), text)
    if kind == "cmd" and "^" in text:
        return _CMD_ESCAPE.sub(lambda found: "" if found.group(1) in ("\n", "\r\n") else found.group(1), text)
    return ""


def readings(words: List[str], kind: str) -> List[str]:
    """The text(s) a shell is given as its command, from the words that follow `-c`, `-Command` or `/c`: the texts the gate reads, the strictest answer standing.

    One word is a whole command line of that shell. Several words are what the shell that started it was given: a POSIX shell takes the first as the command (the rest are `$0`, `$1`...), PowerShell and `cmd` join all
    of them with spaces and read that as code. So the words are read as they were given (the first as it is, the others quoted again, so a `;` inside one stays inside it) and, for PowerShell and `cmd`, joined as the shell
    joins them. The PowerShell or `cmd` escape is taken away from each text as one more reading."""
    if not words:
        return []
    first = words[0]
    texts = [first]
    if len(words) > 1:
        texts = ([first] if kind == "shell" else []) + [first + " " + " ".join(quote(item) for item in words[1:]), " ".join(words)]
    for text in list(texts):
        plain = dialect(text, kind)
        if plain:
            texts.append(plain)
    return [text for text in dict.fromkeys(texts) if text.strip()]
