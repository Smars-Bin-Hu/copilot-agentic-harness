"""Who may read the two secret files: `.harness/.env` (the person's identities) and `.harness/runtime/hookserve.json` (the key of the hook service in the board) (1.8.53, red team F2, N1, N4). Standard library only.

`check_secrets` (handler.py) asks this module four questions about a call:

- `path_kind`: is this path one of the files? The path is read the way the file system reads it: the case does not count on macOS and Windows, `..`, `.`, `//`, the trailing dots and spaces and the `::$DATA`
  of Windows do not count, a `file://` address (percent-encoded, `file:///C:/x`, `file://localhost/x`) is the path it names, and when both files exist `os.path.samefile` says whether they are one file (a link,
  another spelling, a Windows 8.3 short name).
- `url_kind`: does any text of a tool's arguments (a `url` of a fetch tool, the `uri` of a read tool) hold a `file://` address of one of them?
- `search_kind`: does a search tool (Grep, Glob, grep_search, file_search...) aim at a file, a folder or a glob that reaches one of them? Every argument is read: a folder (`path`, `filePath`, `file_path`...), a glob
  (`glob`, `include`, `includePattern`, the pattern of Glob, the query of file_search...) and a flag that turns the ignore rules off.
- `command_kind`: does a terminal command name `hookserve.json` (in any spelling, or by a wildcard that reaches it), or name `.harness/runtime` (in any case, with `/` or `\\`, in any quoting) and read it (a program that
  reads or copies files, a wildcard that reaches the key)? A word that only has `hookserve` in it (`test_hookserve.py`, `hookserve.py`) is not the key, and a command that only lists names (`rg --files .harness`) or
  leaves the folder out (`--exclude-dir=.harness`) reads nothing.

The rule for a search that names no folder and no glob (the whole workspace, which is what Grep does by default): it passes. The search tools skip what `.gitignore` lists, and `.harness/runtime/` and `.harness/.env` are listed there.
A search that aims at the folder (`.harness`, `.harness/runtime`), or at a glob that matches the file (`**/*.json`, `.harness/**`, `**/hookserve*`), or that asks for the ignored files too (`includeIgnoredFiles`), is refused.

THE ACCEPTED LIMIT: a recursive search of the whole workspace from the terminal (`grep -r key .`, `rg -u key`, `find . -type f | xargs cat`) is not refused: the command names no folder of the harness, and what it would
read is what the shell can reach anyway. It is a net, like the rest of `check_secrets`: the key lets a process on this computer ask the hook service, and the service's own checks (the nonce, the record, `harness doctor`)
are the other half. A key alone does not make a forged call possible (the service judges with its own state); it lets the agent ask the real service, as running `launch.py` with a made-up payload already could at the base.

TIME (red team N1): the words of a command and the globs of a search are the agent's, so nothing here compiles them into a regular expression (a word like `****...x` made `re` backtrack for minutes). A wildcard is
matched by `glob_match`, which keeps a set of positions and never goes back: it takes time in proportion to (the length of the wildcard) x (the length of the name, which is always one of ours). A word longer than
`WORD_CAP` that holds a wildcard character is not read: it is taken as able to match anything, so it refuses where a match would refuse (a path word that reaches the key, a glob that reaches the file). The same for
a word with more than `PART_CAP` wildcard parts, and for a search with more than `GLOB_CAP_COUNT` globs."""

from __future__ import annotations

import os
import posixpath
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote

from . import shellwords

ENV = (".harness", ".env")
KEY = (".harness", "runtime", "hookserve.json")
RUNTIME = (".harness", "runtime")
KINDS = {ENV: "env", KEY: "hookserve"}

# (1) paths ------------------------------------------------------------------------------------------------------------------------------------------------------------------

_STREAM = re.compile(r"::\$\w*$")
_DRIVE = re.compile(r"^[A-Za-z]:")
_FILE_URL = re.compile(r"\s*file:", re.IGNORECASE)
_URL_IN_TEXT = re.compile(r"file:[^\s\"'<>`]{0,4096}", re.IGNORECASE)


def file_path(text: str) -> str:
    """The path a `file:` address names, as the file system reads it: `file:///C:/x`, `file:///C|/x`, `file://localhost/x`, `file:/x`, with the percent-encoding taken away (again, until nothing changes: `%252e`) and no query or
    fragment. An address with another host is a network path (`//host/x`). Text that is no `file:` address is returned as it is."""
    if not _FILE_URL.match(text):
        return text
    rest = text.strip()[5:]
    host = ""
    if rest.startswith("//") or rest.startswith("\\\\"):
        host, _slash, path = rest[2:].replace("\\", "/").partition("/")
        rest = "/" + path
    for _round in range(3):
        again = unquote(rest)
        if again == rest:
            break
        rest = again
    rest = rest.split("#", 1)[0].split("?", 1)[0].replace("\\", "/")
    if re.match(r"^/[A-Za-z][:|]", rest):
        rest = rest[1:].replace("|", ":", 1)  # file:///C:/x
    if unquote(host).lower() not in ("", "localhost", "127.0.0.1", "::1", "[::1]"):
        return "//" + unquote(host) + rest
    return rest


def _split(text: str) -> Tuple[bool, List[str]]:
    """`(absolute, components)` of a path as the file systems of macOS and Windows read it: lower case, `\\` as `/`, no `.`, `..` taken, no trailing dots and spaces, no stream name, no `\\\\?\\`."""
    plain = _STREAM.sub("", file_path(text).strip().replace("\\", "/"))
    for prefix in ("//?/", "//./"):
        if plain.startswith(prefix):
            plain = plain[len(prefix):]
            break
    absolute = plain.startswith("/") or bool(_DRIVE.match(plain))
    parts: List[str] = []
    for part in plain.split("/"):
        part = part.rstrip(" .") if part.strip(". ") else part
        part = part.lower()
        if part in ("", "."):
            continue
        if part == ".." and parts and parts[-1] != "..":
            parts.pop()
        else:
            parts.append(part)
    return absolute, parts


def _roots(root: Path) -> List[List[str]]:
    found: List[List[str]] = []
    for text in (str(root), os.path.realpath(str(root))):
        parts = _split(text)[1]
        if parts and parts not in found:
            found.append(parts)
    return found


def relative(root: Path, text: str) -> Optional[Tuple[str, ...]]:
    """The components of `text` under the workspace root, lower case; None when the path is not under it (or names `..` above it)."""
    absolute, parts = _split(text)
    if not absolute:
        return None if parts[:1] == [".."] else tuple(parts)
    for base in _roots(root):
        if parts[:len(base)] == base:
            return tuple(parts[len(base):])
    return None


def _same_file(root: Path, text: str, secret: Path) -> bool:
    try:
        text = file_path(text)
        if not secret.exists():
            return False
        given = Path(text)
        target = given if given.is_absolute() or _DRIVE.match(text) else root / text
        return target.exists() and os.path.samefile(str(target), str(secret))
    except (OSError, ValueError):
        return False


def path_kind(root: Path, text: str) -> str:
    """`env`, `hookserve`, or "" for a path that names neither file. Never raises."""
    try:
        rel = relative(root, text)
        if rel in KINDS:
            return KINDS[rel]
        for parts, kind in KINDS.items():
            if _same_file(root, text, root.joinpath(*parts)):
                return kind
    except Exception:  # noqa: BLE001 - a path that cannot be read is not a path to a secret file; the other nets stay
        return ""
    return ""


URL_TEXTS = 256  # the most texts of a tool's arguments that are read for a `file:` address; with more, a call is refused if the rest cannot be read in time (`url_kind` says so)


def _every_string(value: Any, depth: int = 0) -> Iterable[str]:
    """Every text in a tool's arguments, in lists and in objects, to a depth of 6 (a deeper one is not read: `url_kind` refuses a call with more texts than it reads, a deep one is not a text of any tool)."""
    if isinstance(value, str):
        yield value
    elif depth < 6 and isinstance(value, dict):
        for item in value.values():
            yield from _every_string(item, depth + 1)
    elif depth < 6 and isinstance(value, (list, tuple)):
        for item in value:
            yield from _every_string(item, depth + 1)


def url_kind(root: Path, arguments: Dict[str, Any]) -> str:
    """`env` or `hookserve` when any text of a tool's arguments is, or holds, a `file:` address of one of the files: the `url` of a fetch tool, the `uri` of a read tool, a path written as an address. Never raises."""
    try:
        for count, text in enumerate(_every_string(arguments)):
            if count >= URL_TEXTS:
                return "hookserve"  # more texts than are read: the call cannot be judged, so it does not pass
            if "file:" not in text[:100000].lower():
                continue
            for found in _URL_IN_TEXT.finditer(text[:100000]):
                kind = path_kind(root, found.group(0))
                if kind:
                    return kind
    except Exception:  # noqa: BLE001 - an address that cannot be read is let through here; the call is judged by the rest of the gate
        return ""
    return ""


# (2) search tools -----------------------------------------------------------------------------------------------------------------------------------------------------------

SCOPE_KEYS = frozenset("path filepath file_path dir directory folder cwd root searchpath search_path paths directories folders uri".split())
GLOB_KEYS = frozenset("glob globs include includes includepattern include_pattern includepatterns files file_pattern filepattern files_to_include fileglob".split())
CONTENT_KEYS = frozenset("query pattern regex regexp text prompt description type output_mode mode lang language search replace term terms keywords keyword context".split())  # words to look for, not places
IGNORE_FLAGS = frozenset("includeignoredfiles include_ignored_files includeignored include_ignored no_ignore no-ignore noignore ignored hidden include_hidden includehidden unrestricted".split())
NAME_ONLY = frozenset(["glob", "file_search", "list_dir"])  # they list names and read nothing: the name of the file is no secret, so they are not judged
RESPECT_FLAGS = frozenset("respect_gitignore respectgitignore use_gitignore usegitignore respect_ignore".split())  # these turn the ignore rules off when they are false


def _strings(value: Any, depth: int = 0) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif depth < 4 and isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item, depth + 1)


def _truthy(value: Any) -> bool:
    return value is True or (isinstance(value, (int, float)) and not isinstance(value, bool) and value != 0) or (isinstance(value, str) and value.strip().lower() in ("true", "1", "yes", "on"))


def _falsy(value: Any) -> bool:
    return value is False or value == 0 or (isinstance(value, str) and value.strip().lower() in ("false", "0", "no", "off"))


WORD_CAP = 256  # the longest wildcard word read; a file name is 255 at most. A longer one that holds a wildcard character can match anything: it is taken as doing so (see the top of this file)
PART_CAP = 64  # the most wildcard parts one word of a command can have before it is taken as able to match anything
GLOB_CAP_COUNT = 256  # the most globs of one search that are read; with more, the search is taken as reaching the file
META = frozenset("*?[")
STAR_RUN = re.compile(r"\*{3,}")


def _has_meta(text: str) -> bool:
    return any(char in text for char in META)


def _braces(glob: str, limit: int = 64) -> List[str]:
    """`a/{b,c}.json` as `a/b.json` and `a/c.json`: the first group, again until none is left or `limit` is reached. The caller has cut the glob to `WORD_CAP`, so a group cannot be long and the work is bounded."""
    found = [glob]
    for _round in range(8):
        grown: List[str] = []
        for item in found:
            open_at = item.find("{")
            close_at = item.find("}", open_at + 1) if open_at >= 0 else -1
            if open_at < 0 or close_at < 0:
                grown.append(item)
                continue
            grown.extend(item[:open_at] + option + item[close_at + 1:] for option in item[open_at + 1:close_at].split(",")[:limit])
        found = grown[:limit]
        if not any("{" in item for item in found):
            break
    return found


# --- the matcher of a wildcard word ------------------------------------------------------------------------------------------------------------------------------------------------
# A wildcard word is tokens: ("c", char), ("?",) one character but `/`, ("*",) any run of characters but `/`, ("**",) any run, ("**/",) nothing or any run that ends in `/`, ("[", ranges, negated) one character of a class.
# `match_tokens` walks the name once and keeps the set of tokens it can be at (no going back): the time is (number of tokens) x (length of the name), whatever the wildcard says.


@lru_cache(maxsize=512)
def tokens_of(glob: str) -> Tuple[Tuple[Any, ...], ...]:
    """The tokens of a (lower case) wildcard word. Runs of `*` are one token (`**`, or `**/` when there are exactly two and a `/` follows, as in the glob of ripgrep and VS Code); `[!a-c]` is a class; `[` with no `]` is a character."""
    tokens: List[Tuple[Any, ...]] = []
    index = 0
    while index < len(glob):
        char = glob[index]
        if char == "*":
            end = index
            while end < len(glob) and glob[end] == "*":
                end += 1
            if end - index == 2 and glob.startswith("/", end):
                tokens.append(("**/",))
                end += 1
            elif end - index >= 2:
                tokens.append(("**",))
            else:
                tokens.append(("*",))
            index = end
        elif char == "?":
            tokens.append(("?",))
            index += 1
        elif char == "[" and glob.find("]", index + 2) >= 0:
            close = glob.find("]", index + 2)
            body = glob[index + 1:close]
            negated = body.startswith("!")
            body = body.lstrip("!")
            ranges: List[Tuple[str, str]] = []
            at = 0
            while at < len(body):
                if at + 2 < len(body) and body[at + 1] == "-":
                    ranges.append((body[at], body[at + 2]))
                    at += 3
                else:
                    ranges.append((body[at], body[at]))
                    at += 1
            tokens.append(("[", tuple(ranges), negated))
            index = close + 1
        else:
            tokens.append(("c", char))
            index += 1
    return tuple(tokens)


def _close(tokens: Sequence[Tuple[Any, ...]], states: Iterable[int]) -> set:
    """The positions a walk can be at when it may also skip the tokens that match nothing (`*`, `**`, `**/`). A position `-(n + 1)` is inside the run of the `**/` at token `n`."""
    out: set = set()
    stack = list(states)
    while stack:
        state = stack.pop()
        if state in out:
            continue
        out.add(state)
        if 0 <= state < len(tokens) and tokens[state][0] in ("*", "**", "**/"):
            stack.append(state + 1)
    return out


def match_tokens(tokens: Sequence[Tuple[Any, ...]], text: str) -> bool:
    """Do the tokens match the whole of `text` (both lower case)?"""
    states = _close(tokens, [0])
    for char in text:
        reached: set = set()
        for state in states:
            if state < 0:  # inside a `**/` run: any character goes on, a `/` may end it
                reached.add(state)
                if char == "/":
                    reached.add(-state)
                continue
            if state >= len(tokens):
                continue
            token = tokens[state]
            kind = token[0]
            if kind == "c":
                if char == token[1]:
                    reached.add(state + 1)
            elif kind == "?":
                if char != "/":
                    reached.add(state + 1)
            elif kind == "*":
                if char != "/":
                    reached.add(state)
            elif kind == "**":
                reached.add(state)
            elif kind == "**/":
                reached.add(-(state + 1))
                if char == "/":
                    reached.add(state + 1)
            elif (any(low <= char <= high for low, high in token[1])) != token[2]:
                reached.add(state + 1)
        states = _close(tokens, reached)
        if not states:
            return False
    return len(tokens) in states


def glob_match(pattern: str, text: str) -> bool:
    """Does the wildcard word `pattern` match `text`, whatever the case? A pattern over `WORD_CAP` with a wildcard character in it is taken as matching (it is too long to be a name and cannot be read in a fixed time:
    the caller refuses where a match would refuse); one without is a name and is compared as it is."""
    low = STAR_RUN.sub("**", pattern.lower())  # a run of stars is one (`**`): the word is cut to its size before it is judged long
    if len(low) > WORD_CAP:
        return _has_meta(low) or low == text.lower()
    if not _has_meta(low):
        return low == text.lower()
    return match_tokens(tokens_of(low), text.lower())


def glob_reaches(glob: str, rest: Sequence[str]) -> bool:
    """Does `glob` (relative to the folder searched) match the file `rest` (its components under that folder)? The rules are those of ripgrep and VS Code: no slash in the glob means any depth, and a folder it
    matches takes in what is under the folder. A glob over `WORD_CAP` with a wildcard in it reaches (it cannot be read in a fixed time, so it is refused as a glob that matches would be)."""
    plain = glob.strip().replace("\\", "/")
    if plain.startswith("!"):
        return False  # an exclusion reaches nothing
    plain = STAR_RUN.sub("**", re.sub(r"^(?:\./)+", "", plain).lstrip("/"))
    if len(plain) > WORD_CAP:
        return any(char in plain for char in "*?[{")  # a long wildcard stands for any path; a long plain name is none of ours
    ways = ["/".join(rest[:count]) for count in range(1, len(rest) + 1)]
    for one in _braces(plain.lower()):
        one = one.rstrip("/") or "**"
        pattern = one if "/" in one else "**/" + one
        if any(glob_match(pattern, way) for way in ways):
            return True
    return False


def _glob_text(root: Path, text: str) -> Optional[str]:
    """The glob as a path under the root: an absolute one under the workspace is cut to it; one elsewhere reaches nothing here (None)."""
    plain = file_path(text).strip().replace("\\", "/")
    if plain.startswith("/") or _DRIVE.match(plain):
        for base in _roots(root):
            parts = _split(plain)[1]
            if parts[:len(base)] == base:
                return "/".join(parts[len(base):]) or "**"
        return None
    return plain


def _tool_words(arguments: Dict[str, Any]) -> Tuple[List[str], List[str], bool]:
    """`(folders, globs, ignore_off)` of a search call."""
    folders: List[str] = []
    globs: List[str] = []
    ignore_off = False
    for key, value in arguments.items():
        low = str(key).lower().lstrip("-")
        if low in IGNORE_FLAGS and _truthy(value):
            ignore_off = True
        elif low in RESPECT_FLAGS and _falsy(value):
            ignore_off = True
        elif low in SCOPE_KEYS:
            folders.extend(_strings(value))
        elif low in GLOB_KEYS:
            globs.extend(_strings(value))
        elif low not in CONTENT_KEYS and not isinstance(value, (bool, int, float)):
            for text in _strings(value):  # a key this module does not know: its text may be a folder or a glob
                folders.append(text)
                globs.append(text)
    return folders, globs, ignore_off


def search_kind(root: Path, tool: str, arguments: Dict[str, Any]) -> str:
    """`env` or `hookserve` when the search aims at a file, a folder or a glob that reaches it, or asks for the ignored files; else "". Never raises."""
    try:
        if tool.strip().lower() in NAME_ONLY:
            return ""
        folders, globs, ignore_off = _tool_words(arguments)
        if len(globs) > GLOB_CAP_COUNT or len(folders) > GLOB_CAP_COUNT:
            return "hookserve"  # more globs than are read: one of them may reach the key, so the search is refused as one that does
        for text in folders:
            kind = path_kind(root, text)  # the folder given is the file itself
            if kind:
                return kind
        scopes: List[Optional[Tuple[str, ...]]] = []
        for text in folders or [""]:
            scope = () if text.strip() in ("", ".", "./") else relative(root, text)
            if scope is not None:
                scopes.append(scope)
        for scope in scopes:
            for parts, kind in KINDS.items():
                if parts[:len(scope)] != scope or len(scope) == len(parts):
                    continue  # the key is not under this folder (or it is the file itself, and `path_kind` says so)
                rest = parts[len(scope):]
                if not globs:
                    if scope or ignore_off:
                        return kind  # a folder that holds the file, searched whole; or the whole workspace with the ignored files too
                    continue  # the whole workspace by default: the ignore rules keep the file out (see the top of this file)
                for text in globs:
                    glob = _glob_text(root, text)
                    if glob is not None and glob_reaches(glob, rest):
                        return kind
    except Exception:  # noqa: BLE001 - a search that cannot be read is let through here; the call is judged by the rest of the gate
        return ""
    return ""


# (3) terminal commands ------------------------------------------------------------------------------------------------------------------------------------------------------

FILE_READERS = frozenset(
    "cat tac type gc get-content more less most head tail nl bat view strings xxd od hexdump base64 cut sort uniq paste fold rev tr diff cmp comm grep egrep fgrep zgrep ag ack findstr select-string sls "
    "cp copy xcopy robocopy rsync scp install ditto mv move tar zip unzip gzip gunzip bzip2 7z 7za 7zr compress-archive curl wget jq awk sed ed ex vi vim nano code open".split()
)
INTERPRETERS = frozenset("python python3 py node nodejs perl ruby php deno bun lua tclsh pwsh powershell cmd bash sh zsh dash ksh fish".split())
GIT_UNTRACKED = re.compile(r"--no-index|--untracked|--ignored")  # a git command that also reads the files git does not track
HARNESS_SEGMENT = re.compile(r"^\s*(?:(?:\S*/)?harness(?:\.cmd|\.exe|\.bat)?|python[\d.]*(?:\.exe)?\s+(?:-\S+\s+)*\S*cli\.py)(?=\s|$)")
VARIABLE = re.compile(r"[$%`~]|\{")
KEY_NAME = "hookserve.json"
WORDS = re.compile(r"[^\s;|&<>()=,]+")
NAMES_ONLY = re.compile(r"(?:^|\s)--files(?=\s|$)")  # `rg --files`: the names of the files, not what is in them
# What a command leaves out of a search (`--exclude-dir=.harness`, `-g '!.harness'`, `find . -path ./.harness -prune`): the folder is named, and it is not read.
EXCLUSION = re.compile(
    r"--exclude(?:-dir|-from)?(?:=|\s+)\S+|--ignore(?:-dir|-file|-glob)?(?:=|\s+)\S+|(?:-g|--glob|--iglob)(?:=|\s*)!\S+|(?:-not\s+|!\s+)-i?path\s+\S+|-i?path\s+\S+\s+-prune\b"
)


def _unrestricted(segment: str) -> bool:
    """Does an `rg`, `ag` or `fd` line turn the ignore rules off (`--no-ignore`, `--hidden`, `--unrestricted`, `-u`, `-uu`, `-uuu`, `-Hu`)? Word by word: no pattern over the line."""
    for word in segment.lower().split():
        if word in ("--hidden", "--unrestricted") or word.startswith("--no-ignore"):
            return True
        if word.startswith("-") and not word.startswith("--") and "u" in word and word[1:].isalpha() and word.isascii():
            return True
    return False


def _fn(name: str, pattern: str) -> bool:
    """Does the wildcard word `pattern` (one word of a path) match `name`, whatever the case? (`glob_match`: no regular expression, and a word over `WORD_CAP` with a wildcard matches.)"""
    return glob_match(pattern, name)


def _match(component: str, name: str) -> bool:
    """Does the word of a path (it may be a glob, or hold a variable we cannot know) stand for `name`?"""
    if VARIABLE.search(component):
        return True
    return _fn(name, component)


def _star_only(component: str) -> bool:
    return bool(component) and not component.strip("*?")


def _variants(command: str) -> Tuple[List[str], List[str]]:
    """`(paths, names)`: the command as paths are read (`/` for `\\`, quotes and escape marks taken away, lower case) and as names are read (also with the shell's backslashes taken away: `hook\\serve`). A `file:` address
    in it is read with its percent-encoding taken away too."""
    plain = shellwords.dialect(command, "power")
    paths: List[str] = []
    names: List[str] = []
    sources = [command] + ([plain] if plain else [])
    if "%" in command and "file:" in command.lower():
        sources.append(unquote(command))
    for text in sources:
        unquoted = re.sub(r"[\"'`^]", "", text)
        for one in dict.fromkeys([text, unquoted]):
            paths.append(one.replace("\\", "/").lower())
            names.append(one.lower())
        names.append(unquoted.replace("\\", "").lower())
    return list(dict.fromkeys(paths)), list(dict.fromkeys(names))


def spells_key(word: str) -> bool:
    """Does one word of a command spell the file `hookserve.json`: its name in any case, with the trailing dots and spaces and the `::$DATA` of Windows, a wildcard that reaches the name (`hookserve.js*`, `h?okserve.json`: at
    least 6 letters of it written, so that `*.json` is not it), or its Windows short name (`HOOKSE~1.JSO`)? The folder does not matter: the key is the only file of that name. `hookserve.py`, `test_hookserve.py` and `hookserve` are not it."""
    base = word.rsplit("/", 1)[-1]
    base = STAR_RUN.sub("**", _STREAM.sub("", base).rstrip(" .").lower())
    if base == KEY_NAME:
        return True
    if "~" in base and re.fullmatch(r"hook\w{0,4}~\d{1,3}\.js\w{0,3}", base):
        return True
    if _has_meta(base):
        return len(base) > WORD_CAP or (glob_match(base, KEY_NAME) and sum(char.isalpha() for char in base) >= 6)
    return False


def _walk(token: str, harness_named: bool) -> Tuple[bool, bool, bool, bool]:
    """`(key, folder, harness, env)` of one word of the command: it names a path that reaches the key file, the runtime folder, `.harness` itself, or `.harness/.env` by a wildcard (`cd`, `ls` and `git` are no
    reading: the caller decides). A word with more than `PART_CAP` parts that hold a wildcard is taken as reaching all four (see the top of this file)."""
    parts = [part for part in token.strip().split("/") if part not in ("", ".")]
    if sum(1 for part in parts if _has_meta(part)) > PART_CAP:
        return True, True, True, True
    key = folder = harness = env = False
    for index, part in enumerate(parts):
        anchored = not _star_only(part) and not VARIABLE.search(part) and _fn(".harness", part)
        start = index + 1 if anchored else (index if harness_named and part == "runtime" else -1)
        if start < 0:
            continue
        if anchored and start >= len(parts):
            harness = True
            continue
        if anchored and any(char in parts[start] for char in "*?[") and _fn(".env", parts[start]):
            env = True  # `.harness/.e*`: the literal name is `SECRET_FILE`'s
        if not _match(parts[start], "runtime") or (not anchored and parts[start] != "runtime"):
            continue
        rest = parts[start + 1:]
        if not rest:
            folder = True
        elif _match(rest[0], "hookserve.json"):
            key = True
            folder = True
    return key, folder, harness, env


def command_kind(command: str) -> str:
    """`hookserve` when a terminal command spells the file, or names `.harness/runtime` and reads it; `env` is left to `SECRET_FILE` in handler.py. Never raises."""
    try:
        paths, names = _variants(command)
        for text in names + paths:
            if "hook" in text or "~" in text or _has_meta(text):
                if any(spells_key(word) for word in WORDS.findall(text)):
                    return "hookserve"
        for text in paths:
            if re.search(r"\.harness/+\.env(?![\w.-])", text):
                return "env"  # `.harness/'.env'`: the quotes are away here
            text = EXCLUSION.sub(" ", text)  # `--exclude-dir=.harness` names the folder to leave out
            if ".harness" not in text and not _has_meta(text):
                continue  # no word of it can stand for `.harness`
            harness_named = bool(re.search(r"(?:^|[\s/=;&|(,])\.harness(?![\w.-])", text))
            segments = [part for part in re.split(r"[;&|\n]+", text) if part.strip()]
            reading = {"files": False, "all": False}
            for segment in segments:
                if HARNESS_SEGMENT.match(segment):
                    continue  # the board's own command line: `harness ...`, `python .harness/engine/cli.py ...`
                words = [word for word in re.split(r"[\s()=,<>]+", segment) if word]
                bases = [posixpath.basename(word).rsplit(".exe", 1)[0] for word in words]
                if bases[:1] == ["git"]:
                    if GIT_UNTRACKED.search(segment):
                        reading["files"] = reading["all"] = True
                    continue  # git reads what it tracks, and `.harness/runtime/` is ignored
                if "<" in segment or any(base in FILE_READERS for base in bases):
                    reading["files"] = reading["all"] = True
                if any(base in INTERPRETERS or re.fullmatch(r"python\d+(?:\.\d+)?", base) for base in bases):
                    reading["all"] = True
                if any(base in ("rg", "ag", "fd") for base in bases) and not NAMES_ONLY.search(segment) and _unrestricted(segment):
                    reading["files"] = reading["all"] = True
            for word in re.split(r"[\s;|&<>()=,]+", text):
                key, folder, harness, env = _walk(word, harness_named)
                if key:
                    return "hookserve"
                if env and reading["all"]:
                    return "env"
                if (folder and reading["all"]) or (harness and reading["files"]):
                    return "hookserve"
    except Exception:  # noqa: BLE001 - a command that cannot be read is judged by the rest of the gate
        return ""
    return ""
