"""Who may read the two secret files: `.harness/.env` (the person's identities) and `.harness/runtime/hookserve.json` (the key of the hook service in the board) (1.8.53, red team F2). Standard library only.

`check_secrets` (handler.py) asks this module three questions about a call:

- `path_kind`: is this path one of the files? The path is read the way the file system reads it: the case does not count on macOS and Windows, `..`, `.`, `//`, the trailing dots and spaces and the `::$DATA`
  of Windows do not count, and when both files exist `os.path.samefile` says whether they are one file (a link, another spelling, a Windows 8.3 short name).
- `search_kind`: does a search tool (Grep, Glob, grep_search, file_search...) aim at a file, a folder or a glob that reaches one of them? Every argument is read: a folder (`path`, `filePath`, `file_path`...), a glob
  (`glob`, `include`, `includePattern`, the pattern of Glob, the query of file_search...) and a flag that turns the ignore rules off.
- `command_kind`: does a terminal command name `.harness/runtime`, in any case, with `/` or `\\`, in any quoting, and read it (a program that reads or copies files, a wildcard that reaches the key), or spell `hookserve`?

The rule for a search that names no folder and no glob (the whole workspace, which is what Grep does by default): it passes. The search tools skip what `.gitignore` lists, and `.harness/runtime/` and `.harness/.env` are listed there.
A search that aims at the folder (`.harness`, `.harness/runtime`), or at a glob that matches the file (`**/*.json`, `.harness/**`, `**/hookserve*`), or that asks for the ignored files too (`includeIgnoredFiles`), is refused.
It is a net, like the rest of `check_secrets`: the key lets a process on this computer ask the service, and the service's own checks (the nonce, the record, `harness doctor`) are the other half."""

from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import shellwords

ENV = (".harness", ".env")
KEY = (".harness", "runtime", "hookserve.json")
RUNTIME = (".harness", "runtime")
KINDS = {ENV: "env", KEY: "hookserve"}

# (1) paths ------------------------------------------------------------------------------------------------------------------------------------------------------------------

_STREAM = re.compile(r"::\$\w*$")
_DRIVE = re.compile(r"^[A-Za-z]:")


def _split(text: str) -> Tuple[bool, List[str]]:
    """`(absolute, components)` of a path as the file systems of macOS and Windows read it: lower case, `\\` as `/`, no `.`, `..` taken, no trailing dots and spaces, no stream name, no `\\\\?\\`."""
    plain = _STREAM.sub("", text.strip().replace("\\", "/"))
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


def _braces(glob: str, limit: int = 64) -> List[str]:
    """`a/{b,c}.json` as `a/b.json` and `a/c.json`: the first group, again until none is left or `limit` is reached."""
    found = [glob]
    for _round in range(8):
        grown: List[str] = []
        for item in found:
            open_at = item.find("{")
            close_at = item.find("}", open_at + 1) if open_at >= 0 else -1
            if open_at < 0 or close_at < 0:
                grown.append(item)
                continue
            grown.extend(item[:open_at] + option + item[close_at + 1:] for option in item[open_at + 1:close_at].split(","))
        found = grown[:limit]
        if not any("{" in item for item in found):
            break
    return found


def _regex(glob: str) -> "re.Pattern[str]":
    out, index = "", 0
    while index < len(glob):
        char = glob[index]
        if glob.startswith("**/", index):
            out += "(?:.*/)?"
            index += 3
        elif glob.startswith("**", index):
            out += ".*"
            index += 2
        elif char == "*":
            out += "[^/]*"
            index += 1
        elif char == "?":
            out += "[^/]"
            index += 1
        elif char == "[":
            close = glob.find("]", index + 2)
            if close < 0:
                out += re.escape(char)
                index += 1
            else:
                body = glob[index + 1:close]
                out += "[" + ("^" if body.startswith("!") else "") + re.escape(body.lstrip("!")).replace("\\-", "-") + "]"
                index = close + 1
        else:
            out += re.escape(char)
            index += 1
    return re.compile(out + r"\Z", re.IGNORECASE)


def glob_reaches(glob: str, rest: Sequence[str]) -> bool:
    """Does `glob` (relative to the folder searched) match the file `rest` (its components under that folder)? The rules are those of ripgrep and VS Code: no slash in the glob means any depth, and a folder it
    matches takes in what is under the folder."""
    plain = glob.strip().replace("\\", "/")
    if plain.startswith("!"):
        return False  # an exclusion reaches nothing
    plain = re.sub(r"^(?:\./)+", "", plain).lstrip("/")
    ways = ["/".join(rest[:count]) for count in range(1, len(rest) + 1)]
    for one in _braces(plain.lower()):
        one = one.rstrip("/") or "**"
        pattern = one if "/" in one else "**/" + one
        regex = _regex(pattern)
        if any(regex.match(way) for way in ways):
            return True
    return False


def _glob_text(root: Path, text: str) -> Optional[str]:
    """The glob as a path under the root: an absolute one under the workspace is cut to it; one elsewhere reaches nothing here (None)."""
    plain = text.strip().replace("\\", "/")
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
        for text in folders + globs:
            if re.search(r"hookserve", text.replace("\\", "").replace('"', "").replace("'", ""), re.IGNORECASE):
                return "hookserve"
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
UNRESTRICT = re.compile(r"(?:^|\s)(?:--no-ignore\S*|--hidden|--unrestricted|-[a-z]*u{1,3}[a-z]*)(?=\s|$)", re.IGNORECASE)
HARNESS_SEGMENT = re.compile(r"^\s*(?:(?:\S*/)?harness(?:\.cmd|\.exe|\.bat)?|python[\d.]*(?:\.exe)?\s+(?:-\S+\s+)*\S*cli\.py)(?=\s|$)")
HOOK_NAME = re.compile(r"hookserve", re.IGNORECASE)
VARIABLE = re.compile(r"[$%`~]|\{")


def _fn(name: str, pattern: str) -> bool:
    """Does the glob `pattern` (one word of a path) match `name`, whatever the case?"""
    return bool(_regex(pattern).match(name))


def _match(component: str, name: str) -> bool:
    """Does the word of a path (it may be a glob, or hold a variable we cannot know) stand for `name`?"""
    if VARIABLE.search(component):
        return True
    return _fn(name, component)


def _star_only(component: str) -> bool:
    return bool(component) and not component.strip("*?")


def _variants(command: str) -> Tuple[List[str], List[str]]:
    """`(paths, names)`: the command as paths are read (`/` for `\\`, quotes and escape marks taken away, lower case) and as names are read (also with the shell's backslashes taken away: `hook\\serve`)."""
    plain = shellwords.dialect(command, "power")
    paths: List[str] = []
    names: List[str] = []
    for text in [command] + ([plain] if plain else []):
        unquoted = re.sub(r"[\"'`^]", "", text)
        for one in dict.fromkeys([text, unquoted]):
            paths.append(one.replace("\\", "/").lower())
            names.append(one.lower())
        names.append(unquoted.replace("\\", "").lower())
    return list(dict.fromkeys(paths)), list(dict.fromkeys(names))


def _walk(token: str, harness_named: bool) -> Tuple[bool, bool, bool, bool]:
    """`(key, folder, harness, env)` of one word of the command: it names a path that reaches the key file, the runtime folder, `.harness` itself, or `.harness/.env` by a wildcard (`cd`, `ls` and `git` are no
    reading: the caller decides)."""
    parts = [part for part in token.strip().split("/") if part not in ("", ".")]
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
        if any(HOOK_NAME.search(text) for text in names):
            return "hookserve"
        for text in paths:
            if re.search(r"\.harness/+\.env(?![\w.-])", text):
                return "env"  # `.harness/'.env'`: the quotes are away here
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
                if any(base in ("rg", "ag", "fd") for base in bases) and UNRESTRICT.search(segment):
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
