"""The files and the text a call reads its statements from (1.7.38, C12).

`sqlcmd -Q "DROP TABLE t"` carries its statement in the line, `sqlcmd -i drop.sql` in a file, and the same words in a file must weigh the same. A type says which options name such a file
(`input.options`: `["-i"]`), which options take the statement text itself (`input.text`: `["-Q"]`) and, when a file can name more files itself, how (`input.include`: a pattern whose group is a file,
`:r other.sql`). The gate reads each file (up to 200 KB), cuts all the text into statements (`statements.py`) and hands them to `statements.judge`, which answers by the type's lists (`reads`, `writes`,
`refuse`). A type that has no `reads` keeps the older way: the `verbs` rules judge the whole text, every rule on the whole text, the strictest verb wins. A file the gate cannot read (missing, too big, a binary, too many files, named again in the same line, which may change it
before it runs) is a call that asks the person, never a pass. Stdlib and `core.pinfiles` only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import pinfiles

from . import statements

MAX_BYTES = 200 * 1024  # a file bigger than this is not read
MAX_FILES = 12  # the files of one call, the files they include too
MAX_DEPTH = 3  # files that include files that include files
ORDER = ("read", "write", "exec", "destroy")  # from the loosest to the strictest


@dataclass
class Found:
    verb: Optional[str] = None  # the strictest verb of what the files say (a type with no `reads`); None when no rule matched in any of them
    file: str = ""  # the file that made it a destroy (a type with no `reads`), or else the first file that could not be judged
    state: str = ""  # "": the files were judged; "unread" (missing, too big, not text, too many) and "twice" (the line names the file again): the call asks the person
    rest: str = ""  # the words of the call without the options, the files and the text, to be judged as always
    items: List[statements.Statement] = field(default_factory=list)  # the statements of the text and of every file, in order (a sqlcmd line of `include` that was followed is not one)
    files: Dict[str, str] = field(default_factory=dict)  # the file each statement came from (by its text): to name it in a refusal
    sources: int = 0  # how many texts and files the call gave: 0 means the program reads what it is given on its input, and the gate sees none of it
    named: List[str] = field(default_factory=list)  # every script file the call reads: the ones it names (`-i a.sql`) and the ones they include (1.7.38, C13 F2: no other command of the line may change them)
    unsure: str = ""  # a text that holds a shell variable or a command substitution (`$X`, `$(...)`, a backtick): the shell fills it in before the program sees it


def strictest(verbs: List[Optional[str]]) -> Optional[str]:
    known = [verb for verb in verbs if verb in ORDER]
    return max(known, key=ORDER.index) if known else None


def split(args: List[str], options: List[str], text: bool = False) -> Tuple[List[str], List[str]]:
    """`(the words that name files, the other words)`. An option of `options` takes the next word, or its own end (`-ifile.sql`, `--input=file.sql`); the check is on the exact option, in its case.
    With `text`, the next word is the value whatever it starts with (a statement may start with `--`)."""
    files: List[str] = []
    rest: List[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        value = None
        for option in options:
            if word == option:
                if index + 1 < len(args) and (text or not args[index + 1].startswith("-")):
                    value = args[index + 1]
                    index += 1
                else:
                    value = ""
                break
            if option.startswith("--") and word.startswith(option + "="):
                value = word[len(option) + 1:]
                break
            if not option.startswith("--") and len(option) == 2 and word.startswith(option) and len(word) > 2:
                value = word[2:]
                break
        if value is None:
            rest.append(word)
        elif value:
            files.append(value)
        index += 1
    return files, rest


def variables(args: List[str], options: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """`(the values the call gives its script variables, the other words)` (1.7.38, C13 SQL): an option of `options` (`sqlcmd -v a=1 b="x y"`) takes the words after it that are `name=value`, until one that is not.
    The names are lower case; a value keeps what the shell left of it."""
    found: Dict[str, str] = {}
    rest: List[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        if word in options:
            index += 1
            while index < len(args) and not args[index].startswith("-") and re.match(r"^[A-Za-z_][\w-]*=", args[index]):
                name, _, value = args[index].partition("=")
                found[name.lower()] = value
                index += 1
            continue
        rest.append(word)
        index += 1
    return found, rest


def verb_of_text(system: Dict[str, Any], text: str) -> Optional[str]:
    """The strictest verb of the `verbs` rules that match anywhere in the text; None when none does."""
    found: List[Optional[str]] = []
    for rule in system.get("verbs") or []:
        try:
            if re.search(rule["pattern"], text, re.IGNORECASE):
                found.append(rule["verb"])
        except re.error:
            continue
    return strictest(found)


def _text(path: Path) -> Optional[str]:
    """The text of a file, or None when it is too big, cannot be read, or is no text (a binary). A UTF-16 file with its mark (SQL tools save one) is text."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if b"\0" in data[:8000]:
        return None
    return data.decode("utf-8-sig", errors="replace")


def _names(value: str, root: Path, folder: Optional[Path], cwd: str, command: str) -> List[str]:
    """One word may name several files, joined with a comma (`-i a.sql,b.sql`): the whole word when it is a file, else its parts."""
    if "," in value and pinfiles.locate(value, root, folder, cwd, command) is None:
        return [part.strip() for part in value.split(",") if part.strip()]
    return [value]


_SHELL = re.compile(r"\$[A-Za-z_{(]|`")  # the shell fills these in before the program sees the text: the gate sees the words, not what they become


def read(system: Dict[str, Any], args: List[str], root: Optional[Path], folder: Optional[Path], cwd: str, command: str) -> Optional[Found]:
    """What the text and the files this call names as its input say, or None when the system declares no input, or (a type with no `reads`) the call names none. `args` are the words after the
    program; `command` is the whole line as written; `root` is None where files cannot be looked for (every file is then unread)."""
    given = system.get("input")
    if not isinstance(given, dict):
        return None
    file_options = [str(item) for item in given.get("options") or []]
    listed = bool(system.get("reads"))  # the lists judge the statements; without them the `verbs` do, as before (and the text of a call is judged with the whole line)
    text_options = [str(item) for item in given.get("text") or []] if listed else []
    if not file_options and not text_options:
        return None
    named, rest = split(args, file_options) if file_options else ([], list(args))
    texts, rest = split(rest, text_options, text=True) if text_options else ([], rest)
    known, rest = variables(rest, [str(item) for item in given.get("variables") or []]) if listed else ({}, rest)
    if not named and not texts and not listed:
        return None
    found = Found(rest=" ".join(rest), sources=len(named) + len(texts))
    try:
        include = re.compile(str(given["include"]), re.IGNORECASE | re.MULTILINE) if given.get("include") else None
    except re.error:
        include = None
    seen: List[Path] = []
    verbs: List[Optional[str]] = []

    def unread(name: str, state: str = "unread") -> None:
        found.state = found.state or state
        found.file = found.file or name

    def add(items: List[statements.Statement], name: str) -> None:
        for item in items:
            found.items.append(item)
            found.files.setdefault(item.text, name)

    def visit(name: str, depth: int) -> None:
        if name not in found.named:
            found.named.append(name)  # a file a script includes counts as a file the call reads
        path = pinfiles.locate(name, root, folder, cwd, command) if root is not None else None
        if path is None or depth > MAX_DEPTH or len(seen) >= MAX_FILES:
            return unread(name)
        if path in seen:
            return
        seen.append(path)
        text = _text(path)
        if text is None:
            return unread(name)
        if command.count(Path(name.replace("\\", "/")).name) > 1 and depth == 0:  # the line names the file in another place too (`echo ... > x.sql; sqlcmd -i x.sql`): it may be changed before it runs
            unread(name, "twice")
        followed = [hit for hit in (include.finditer(text) if include is not None else [])]
        if listed:
            add([item for item in statements.split(text, known) if not (item.directive and include is not None and include.search(item.text))], name)  # a `:r` line is followed below, so its file is judged in its place
        else:
            verb = verb_of_text(system, text)
            verbs.append(verb)
            if verb == "destroy":
                found.file = name  # the file that decided: named in the refusal
                found.state = "destroy"
        for hit in followed:
            for inner in (group for group in hit.groups() if group):
                visit(inner, depth + 1)

    for word in named:
        for name in _names(word, root, folder, cwd, command) if root is not None else [word]:
            visit(name, 0)
    for text in texts:
        if _SHELL.search(text):
            found.unsure = found.unsure or text
        add(statements.split(text, known), "")
    found.verb = strictest(verbs)
    return found
