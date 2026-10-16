#!/usr/bin/env python3
"""Tools for translating a knowledge base from Simplified Chinese to English inside a `kb` task.

  terms  --task <task folder>                          candidate terms from the fetched originals, most used first
  check  --task <task folder> --glossary <glossary.md>  compare every translated file in DEV/ with its original

The originals are the files `harness task fetch` copied: `<task>/.task/base/<repo>/<path>`. The translations are the
same paths under `<task>/DEV/`. Only reads; writes nothing. `check` exits with 1 when it finds a problem.

What `check` looks at, per Markdown file: the headings (count per level), the tables (rows and columns), the code
blocks (lines without Chinese must stay the same), inline code and link targets (the same set), Chinese left outside
code, and the glossary (a term in the original must come out as its English). YAML and JSON: the keys stay the same,
and no Chinese is left.
Run with `python3` (Windows: `python`). Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
CJK_RUN = re.compile(r"[㐀-䶿一-鿿豈-﫿]{2,12}")
FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^(#{1,6})\s")
INLINE = re.compile(r"`([^`\n]+)`")
LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
KEY = re.compile(r"^(\s*-?\s*)([A-Za-z_][\w.-]*)\s*:")
TEXT_SUFFIXES = (".md", ".markdown")
DATA_SUFFIXES = (".yaml", ".yml", ".json")


def pairs(task: Path) -> List[Tuple[Path, Path, str]]:
    """(original, translation, path shown) for every text file in DEV/ that has an original."""
    base, dev = task / ".task" / "base", task / "DEV"
    out = []
    for path in sorted(dev.rglob("*")) if dev.is_dir() else []:
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES + DATA_SUFFIXES:
            relative = path.relative_to(dev)
            original = base / relative
            if original.is_file():
                out.append((original, path, relative.as_posix()))
    return out


def split(text: str) -> Tuple[List[str], List[List[str]]]:
    """(the lines outside code blocks, the code blocks as lists of lines)."""
    prose, blocks, inside = [], [], False
    for line in text.splitlines():
        if FENCE.match(line):
            if inside:
                inside = False
            else:
                inside = True
                blocks.append([])
            continue
        (blocks[-1] if inside else prose).append(line)
    return prose, blocks


def tables(prose: List[str]) -> List[Tuple[int, int]]:
    """(rows, columns) of every table, in order."""
    found, rows, columns = [], 0, 0
    for line in prose + [""]:
        if line.strip().startswith("|"):
            rows += 1
            columns = max(columns, line.strip().strip("|").count("|") + 1)
        elif rows:
            found.append((rows, columns))
            rows, columns = 0, 0
    return found


def glossary(path: Path) -> Dict[str, str]:
    """{Chinese term: English term} from the rows of the Markdown table(s) whose first cell has Chinese."""
    terms: Dict[str, str] = {}
    in_table = False
    for line in path.read_text(encoding="utf-8").splitlines():
        row = line.strip().startswith("|")
        header, in_table = row and not in_table, row  # the first row of a table names the columns
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if row and not header and len(cells) >= 2 and CJK.search(cells[0]) and cells[1] and not set(cells[1]) <= set("-: "):
            terms[cells[0]] = cells[1]
    return terms


def check_markdown(original: str, translated: str, terms: Dict[str, str]) -> List[str]:
    problems = []
    src_prose, src_code = split(original)
    dst_prose, dst_code = split(translated)
    levels = lambda lines: Counter(len(match.group(1)) for line in lines for match in [HEADING.match(line)] if match)  # noqa: E731
    if levels(src_prose) != levels(dst_prose):
        problems.append(f"headings differ: original {dict(sorted(levels(src_prose).items()))}, translation {dict(sorted(levels(dst_prose).items()))}")
    if tables(src_prose) != tables(dst_prose):
        problems.append(f"tables differ (rows, columns): original {tables(src_prose)}, translation {tables(dst_prose)}")
    if len(src_code) != len(dst_code):
        problems.append(f"code blocks: original {len(src_code)}, translation {len(dst_code)}")
    else:
        for number, (left, right) in enumerate(zip(src_code, dst_code), 1):
            if len(left) != len(right) or any(old != new for old, new in zip(left, right) if not CJK.search(old)):
                problems.append(f"code block {number}: a line without Chinese changed (only Chinese comments may be translated)")
    inline = lambda lines: Counter(code for line in lines for code in INLINE.findall(line) if not CJK.search(code))  # noqa: E731
    if inline(src_prose) != inline(dst_prose):
        lost = sorted((inline(src_prose) - inline(dst_prose)).elements())
        added = sorted((inline(dst_prose) - inline(src_prose)).elements())
        problems.append(f"inline code changed: missing {lost[:8]}, new {added[:8]}")
    links = lambda lines: sorted(target for line in lines for target in LINK.findall(line))  # noqa: E731
    if links(src_prose) != links(dst_prose):
        problems.append(f"link targets changed: original {links(src_prose)[:8]}, translation {links(dst_prose)[:8]}")
    left_over = [(number, line.strip()) for number, line in enumerate(dst_prose, 1) if CJK.search(INLINE.sub("", line))]
    for number, line in left_over[:10]:
        problems.append(f"Chinese left (prose line {number}): {line[:80]}")
    text_src, text_dst = "\n".join(src_prose), "\n".join(dst_prose).lower()
    for term, english in terms.items():
        if term in text_src and english.lower() not in text_dst:
            problems.append(f"glossary: `{term}` should come out as `{english}`")
    return problems


def check_data(original: str, translated: str) -> List[str]:
    problems = []
    keys = lambda text: [match.group(2) for line in text.splitlines() for match in [KEY.match(line)] if match]  # noqa: E731
    if keys(original) != keys(translated):
        problems.append("keys changed: translate values only, never keys")
    for number, line in enumerate(translated.splitlines(), 1):
        if CJK.search(line):
            problems.append(f"Chinese left (line {number}): {line.strip()[:80]}")
            break
    return problems


def cmd_check(task: Path, glossary_path: Path, as_json: bool) -> int:
    terms = glossary(glossary_path) if glossary_path and glossary_path.is_file() else {}
    report = {}
    for original, translated, shown in pairs(task):
        src, dst = original.read_text(encoding="utf-8"), translated.read_text(encoding="utf-8")
        found = check_markdown(src, dst, terms) if translated.suffix.lower() in TEXT_SUFFIXES else check_data(src, dst)
        report[shown] = found
    bad = {path: found for path, found in report.items() if found}
    if as_json:
        print(json.dumps({"checked": len(report), "with_problems": len(bad), "glossary_terms": len(terms), "problems": bad}, ensure_ascii=False, indent=2))
    else:
        print(f"checked {len(report)} file(s), {len(bad)} with problems, glossary terms {len(terms)}")
        for path, found in bad.items():
            print(f"\n{path}")
            for item in found:
                print(f"  - {item}")
    if not report:
        print("no translated file found: the translations go in DEV/ at the same path as the fetched originals", file=sys.stderr)
        return 1
    return 1 if bad else 0


def cmd_terms(task: Path, limit: int) -> int:
    """Candidates for the glossary: headings, table headers, bold words and repeated Chinese phrases of the originals."""
    counts: Counter = Counter()
    strong: Counter = Counter()
    base = task / ".task" / "base"
    for path in sorted(base.rglob("*")) if base.is_dir() else []:
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES + DATA_SUFFIXES:
            continue
        prose, _code = split(path.read_text(encoding="utf-8", errors="replace"))
        for line in prose:
            for run in CJK_RUN.findall(INLINE.sub("", line)):
                counts[run] += 1
            places = [line] if HEADING.match(line) else []
            places += BOLD.findall(line)
            if line.strip().startswith("|"):
                places += [cell for cell in line.strip().strip("|").split("|")]
            for place in places:
                for run in CJK_RUN.findall(place):
                    strong[run] += 1
    ranked = sorted(set(counts) | set(strong), key=lambda term: (-(strong[term] * 3 + counts[term]), term))
    for term in ranked[:limit]:
        print(f"{term}\t{counts[term]}\t{'heading/table/bold' if strong[term] else ''}")
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    terms = commands.add_parser("terms", help="candidate glossary terms from the fetched originals")
    terms.add_argument("--task", required=True, type=Path, help="the task folder")
    terms.add_argument("--limit", type=int, default=150)
    check = commands.add_parser("check", help="compare the translations in DEV/ with the originals")
    check.add_argument("--task", required=True, type=Path, help="the task folder")
    check.add_argument("--glossary", type=Path, default=None, help="the glossary (a Markdown table: Chinese | English | note)")
    check.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "terms":
        return cmd_terms(args.task, args.limit)
    return cmd_check(args.task, args.glossary, args.json)


if __name__ == "__main__":
    sys.exit(main())
