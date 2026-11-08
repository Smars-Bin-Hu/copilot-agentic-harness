"""The files a call reads its statements from (1.7.38, C12 RC-G1).

`sqlcmd -Q "DROP TABLE t"` carries its statement in the line, and the gate judges it by the `verbs` of the type. `sqlcmd -i drop.sql` carries it in a file, and the same words in a file must
weigh the same. A type says which options name such a file (`input.options`: `["-i"]`) and, when the file can name more files itself, how (`input.include`: a pattern whose group is a file,
`:r other.sql`). The gate reads each file (up to 200 KB) and judges its text with the same `verbs`, every rule on the whole text, not the first that matches: a script holds many statements,
and a `DROP` after an `UPDATE` is still a drop. The strictest verb wins: any destroy is refused, any write is held, only reads pass as a read. A file the gate cannot read or judge (missing,
too big, a binary, too many files, named again in the same line, which may change it before it runs) holds the call as a write. Stdlib and `core.pinfiles` only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import pinfiles

MAX_BYTES = 200 * 1024  # a file bigger than this is not read
MAX_FILES = 12  # the files of one call, the files they include too
MAX_DEPTH = 3  # files that include files that include files
ORDER = ("read", "write", "exec", "destroy")  # from the loosest to the strictest


@dataclass
class Found:
    verb: Optional[str] = None  # the strictest verb of what the files say; None when no rule matched in any of them
    file: str = ""  # the file that made it a destroy, or else the first file that could not be judged
    state: str = ""  # "": the files were judged; "unread" (missing, too big, not text, too many) and "twice" (the line names the file again): the call is held as a write
    rest: str = ""  # the words of the call without the options and files, to be judged as always


def strictest(verbs: List[Optional[str]]) -> Optional[str]:
    known = [verb for verb in verbs if verb in ORDER]
    return max(known, key=ORDER.index) if known else None


def split(args: List[str], options: List[str]) -> Tuple[List[str], List[str]]:
    """`(the words that name files, the other words)`. An option of `options` takes the next word, or its own end (`-ifile.sql`, `--input=file.sql`); the check is on the exact option, in its case."""
    files: List[str] = []
    rest: List[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        value = None
        for option in options:
            if word == option:
                if index + 1 < len(args) and not args[index + 1].startswith("-"):
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


def read(system: Dict[str, Any], args: List[str], root: Path, folder: Optional[Path], cwd: str, command: str) -> Optional[Found]:
    """What the files this call names as its input say, or None when the system declares no input or the call names none. `args` are the words after the program; `command` is the whole line as written."""
    given = system.get("input")
    if not isinstance(given, dict) or not given.get("options"):
        return None
    named, rest = split(args, [str(item) for item in given["options"]])
    if not named:
        return None
    found = Found(rest=" ".join(rest))
    try:
        include = re.compile(str(given["include"]), re.IGNORECASE | re.MULTILINE) if given.get("include") else None
    except re.error:
        include = None
    try:  # lines the gate cannot judge from the text (sqlcmd's `!!` runs a shell command, `:connect` sends what follows to another server, `$(...)` makes words at run time)
        unjudged = re.compile(str(given["unjudged"]), re.IGNORECASE | re.MULTILINE) if given.get("unjudged") else None
    except re.error:
        unjudged = re.compile(r"(?!)")  # a broken pattern judges nothing as safe: every file with input is held below
    seen: List[Path] = []
    verbs: List[Optional[str]] = []

    def unread(name: str, state: str = "unread") -> None:
        found.state = found.state or state
        found.file = found.file or name

    def visit(name: str, depth: int) -> None:
        path = pinfiles.locate(name, root, folder, cwd, command)
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
        verb = verb_of_text(system, text)
        verbs.append(verb)
        if verb != "destroy" and unjudged is not None and (unjudged.pattern == "(?!)" or unjudged.search(text)):
            unread(name, "directive")  # held as a write, never passed as a read: what it does is not in its words (a destroy found in it still refuses)
        if verb == "destroy":
            found.file = name  # the file that decided: named in the refusal
            found.state = "destroy"
        for hit in (include.finditer(text) if include is not None else []):
            for inner in (group for group in hit.groups() if group):
                visit(inner, depth + 1)

    for word in named:
        for name in _names(word, root, folder, cwd, command):
            visit(name, 0)
    found.verb = strictest(verbs)
    return found
