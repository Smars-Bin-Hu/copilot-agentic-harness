"""`target refs`: where are these names used? One search over every target repository and the knowledge base.

The impact check of a change used to be a long run of `grep` calls by the agent, one name and one repository at a time.
Here it is one `git grep` per repository, over the committed base branch (the same version `task fetch` reads), with all
names and their spellings at once. What comes back is short: per repository the files, the hits per name, and a few lines.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from core import gitread, messages, targets

from .common import CommandError, say

MIN_TERM = 3  # a shorter name (`id`, `dt`) matches everything: search `table.column` instead
MAX_LINES_READ = 200_000  # git output read per repository
MAX_FILE_BYTES = 1_000_000  # a plain knowledge base folder: files above this are skipped
SAMPLE_WIDTH = 140
WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
KB_SUFFIXES = {".md", ".txt", ".rst", ".sql", ".csv", ".json", ".yaml", ".yml", ".py", ".sh", ".xml", ".ini", ".toml"}


def spellings(term: str) -> List[str]:
    """The term as typed, and the other spellings of a name made of several words: snake, kebab, joined (covers camelCase), spaced.

    The search ignores case, so `ORDER_DELAY` and `Order_Delay` are the same spelling. One word has no other spelling.
    """
    words = [word.lower() for word in WORD.findall(term)]
    found = [term]
    if len(words) > 1 and "." not in term:  # a qualified name (`dbo.order_delay`) is searched as typed
        for form in ("_".join(words), "-".join(words), "".join(words), " ".join(words)):
            if form.lower() not in {item.lower() for item in found}:
                found.append(form)
    return found


def matcher(spelling: str) -> Tuple[re.Pattern, re.Pattern]:
    """(any occurrence, whole-word occurrence) of one spelling, ignoring case. Whole: not inside a longer name."""
    text = re.escape(spelling)
    return re.compile(text, re.IGNORECASE), re.compile(r"(?<![A-Za-z0-9_])" + text + r"(?![A-Za-z0-9_])", re.IGNORECASE)


class Search:
    """The terms, their spellings, and what is counted for each file."""

    def __init__(self, terms: List[str], variants: bool, whole_only: bool) -> None:
        self.terms = terms
        self.whole_only = whole_only
        self.spellings: Dict[str, List[str]] = {term: spellings(term) if variants else [term] for term in terms}
        self.patterns: Dict[str, List[Tuple[re.Pattern, re.Pattern]]] = {term: [matcher(item) for item in found] for term, found in self.spellings.items()}

    def literals(self) -> List[str]:
        return sorted({item for found in self.spellings.values() for item in found}, key=str.lower)

    def match(self, line: str) -> Dict[str, bool]:
        """term -> True when the line has it as a whole word, False when only inside a longer name. Terms not on the line are left out."""
        found: Dict[str, bool] = {}
        for term, patterns in self.patterns.items():
            for anywhere, whole in patterns:
                if anywhere.search(line):
                    is_whole = bool(whole.search(line))
                    if is_whole or not self.whole_only:
                        found[term] = found.get(term, False) or is_whole
        return found


class Tally:
    """What one repository (or folder) gave."""

    def __init__(self, search: Search, max_files: int, lines: int) -> None:
        self.search, self.max_files, self.lines = search, max_files, lines
        self.files: Dict[str, Dict[str, Any]] = {}
        self.terms: Dict[str, Dict[str, int]] = {term: {"hits": 0, "whole": 0, "files": 0} for term in search.terms}
        self.read = 0
        self.cut = False

    def add(self, path: str, number: int, text: str) -> None:
        found = self.search.match(text)
        if not found:
            return
        entry = self.files.setdefault(path, {"path": path, "hits": 0, "whole": 0, "terms": {}, "lines": []})
        entry["hits"] += 1
        entry["whole"] += 1 if any(found.values()) else 0
        for term, whole in found.items():
            entry["terms"][term] = entry["terms"].get(term, 0) + 1
            self.terms[term]["hits"] += 1
            self.terms[term]["whole"] += 1 if whole else 0
        if len(entry["lines"]) < self.lines:
            shown = text.strip()
            entry["lines"].append({"n": number, "text": shown if len(shown) <= SAMPLE_WIDTH else shown[: SAMPLE_WIDTH - 1] + "…"})

    def report(self) -> Dict[str, Any]:
        for entry in self.files.values():
            for term in entry["terms"]:
                self.terms[term]["files"] += 1
        ranked = sorted(self.files.values(), key=lambda entry: (-entry["whole"], -entry["hits"], entry["path"]))
        kinds: Dict[str, int] = {}
        for entry in ranked:
            kind = Path(entry["path"]).suffix.lower().lstrip(".") or "(none)"
            kinds[kind] = kinds.get(kind, 0) + 1
        return {
            "hit_files": len(ranked),
            "hits": sum(entry["hits"] for entry in ranked),
            "by_file_type": dict(sorted(kinds.items(), key=lambda item: -item[1])),
            "files": ranked[: self.max_files],
            "files_not_shown": max(0, len(ranked) - self.max_files),
            **({"truncated": True} if self.cut else {}),
        }


def grep_repo(repo: targets.Repo, commit: str, search: Search, tally: Tally, timeout: int) -> None:
    """One `git grep` over the committed tree: `-z` gives `commit:path NUL line NUL text`."""
    command = ["git", "-C", str(repo.path), "-c", "core.quotepath=off", "grep", "-n", "-I", "-i", "-F", "-z", "--no-color"]
    for literal in search.literals():
        command += ["-e", literal]
    command += [commit, "--"]
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=gitread.env())
    except (FileNotFoundError, PermissionError) as error:
        raise CommandError(say("target.git.missing")) from error
    prefix = commit + ":"
    try:
        assert process.stdout is not None
        for raw in process.stdout:
            tally.read += 1
            if tally.read > MAX_LINES_READ:
                tally.cut = True
                process.kill()
                break
            head, _, rest = raw.partition(b"\0")
            number, _, text = rest.partition(b"\0")
            path = head.decode("utf-8", errors="replace")
            path = path[len(prefix):] if path.startswith(prefix) else path
            try:
                line_number = int(number)
            except ValueError:
                continue
            tally.add(path, line_number, text.decode("utf-8", errors="replace").rstrip("\r\n"))
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        raise CommandError(say("target.timeout", timeout=timeout))
    if process.returncode not in (0, 1, -9):  # 1: no hit
        message = (process.stderr.read() if process.stderr else b"").decode("utf-8", errors="replace").strip()
        raise CommandError(say("target.git.failed", arguments="grep", repo=repo.name, message=message))


def walk_folder(folder: Path) -> Iterable[Tuple[str, int, str]]:
    """The lines of the text files of a plain folder (a knowledge base that is not a git repository)."""
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() not in KB_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relative = path.relative_to(folder).as_posix()
        for number, line in enumerate(content.splitlines(), 1):
            yield relative, number, line


def refs(root: Path, terms: List[str], repo: str = "", no_kb: bool = False, variants: bool = True, whole_only: bool = False, max_files: int = 30, lines: int = 2) -> Dict[str, Any]:
    clean = []
    for term in terms:
        text = term.strip()
        if len(text) < MIN_TERM:
            raise CommandError(say("refs.short", term=term, minimum=MIN_TERM))
        if text.lower() not in {item.lower() for item in clean}:
            clean.append(text)
    if not clean:
        raise CommandError(say("refs.no_terms"))
    found = targets.load(root)
    if repo:
        chosen = [found.get(repo)]
    else:
        chosen = [found.repos[name] for name in found.names()]
    search = Search(clean, variants, whole_only)
    searched: List[Dict[str, Any]] = []
    result_repos: Dict[str, Any] = {}
    notes: List[str] = []
    totals = {term: {"hits": 0, "whole": 0, "files": 0, "in": []} for term in clean}

    def take(name: str, kind: str, detail: Dict[str, Any], tally: Tally) -> None:
        shown = tally.report()
        result_repos[name] = {**detail, **shown}
        searched.append({"name": name, "kind": kind, **detail, "hit_files": shown["hit_files"]})
        for term, count in tally.terms.items():
            for key in ("hits", "whole", "files"):
                totals[term][key] += count[key]
            if count["hits"]:
                totals[term]["in"].append(name)
        if shown.get("truncated"):
            notes.append(say("refs.note.truncated", name=name, limit=MAX_LINES_READ))

    for item in chosen:
        commit = targets.ref_commit(item, found.timeout)
        if not commit:
            notes.append(say("refs.note.no_branch", name=item.name, base_ref=item.base_ref))
            continue
        tally = Tally(search, max_files, lines)
        grep_repo(item, commit, search, tally, found.timeout)
        take(item.name, "knowledge base" if item.knowledge_base else "repository", {"ref": item.base_ref, "commit": commit[:12]}, tally)
    if not no_kb and not repo:
        plain = root / targets.KB_DIR
        registered = {item.path.resolve() for item in chosen}
        if targets.knowledge_base_content(plain) and plain.resolve() not in registered:
            tally = Tally(search, max_files, lines)
            for path, number, text in walk_folder(plain):
                tally.add(path, number, text)
            take(targets.KB_DIR, "knowledge base", {"ref": "(folder)"}, tally)
    if not searched:
        raise CommandError(say("target.unset"))
    notes.append(say("refs.note.committed"))
    none = [term for term in clean if not totals[term]["hits"]]
    return {
        "terms": [
            {"term": term, "searched_as": search.spellings[term], "hits": totals[term]["hits"], "whole_word_hits": totals[term]["whole"], "files": totals[term]["files"], "found_in": totals[term]["in"]}
            for term in clean
        ],
        "searched": searched,
        "repos": result_repos,
        "no_hits": none,
        "notes": notes,
        "next": say("refs.next", none=messages.joined(none) if none else say("refs.next.none")),
    }
