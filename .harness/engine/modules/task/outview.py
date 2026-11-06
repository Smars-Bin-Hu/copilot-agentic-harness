"""How the output of a run is laid out for a person (1.7.9). The file keeps the output as it came; the window lays it out. A generic reader of console output,
with no knowledge of any program:

  - a block whose second line is runs of dashes is a table: the dash runs give the columns, the first line the names, the lines after it the rows (sqlcmd, osql, bcp, many CLIs);
    dash runs joined by one separator character (`|`, `,`, `;`, a tab: `sqlcmd -s "|"`) cut the columns at that character instead;
  - a block framed with `+---+` lines, or whose lines start and end with `|`, is a table (psql, mysql, markdown);
  - a block of lines with the same number of tabs is a table (TSV);
  - `(n rows affected)`, `Msg …`, `Error …`, `Warning …`: notes; an error note is red on the page;
  - anything else is text.

Several result sets become several tables, each in its own tab. A table longer than ROWS_SHOWN rows is cut for the page and says so; Text has it whole.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

ROWS_SHOWN = 200
MAX_CHARS = 2_000_000  # what is laid out (the tables are cut to ROWS_SHOWN rows anyway); past this the layout stops and says so
_DASHES = re.compile(r"^(?:-{1,}\s*)+$")
_SEPARATED = re.compile(r"^-+(?:([|,;\t])-+)+$")  # `--|-----|---`: dash runs joined by one separator character
_FRAME = re.compile(r"^\+(?:-+\+)+$")
_NOTE = re.compile(r"^\((\d+|\?) rows? affected\)$|^(Msg \d+|Error|ERROR|Warning|WARNING|Sqlcmd: Error|HResult)\b", re.IGNORECASE)
_ERROR = re.compile(r"^(Msg \d+|Error|ERROR|Sqlcmd: Error|HResult)\b|\bLevel 1[1-9]\b", re.IGNORECASE)
_NUMBER = re.compile(r"^[-+]?\d[\d,]*(?:\.\d+)?$")


def _blocks(lines: List[str]) -> List[List[str]]:
    """The lines in blocks, split at empty lines."""
    out: List[List[str]] = [[]]
    for line in lines:
        if line.strip():
            out[-1].append(line.rstrip("\r"))
        elif out[-1]:
            out.append([])
    return [block for block in out if block]


def _ruler(line: str) -> bool:
    """A line that underlines a head: runs of dashes, with spaces, tabs or one separator character between them."""
    stripped = line.strip()
    return bool(_DASHES.match(stripped.replace("\t", " ")) or _SEPARATED.match(stripped))


def _split_at_dashes(block: List[str]) -> List[List[str]]:
    """A block that holds a dash line further down (sqlcmd prints `(n rows affected)` right before the next result set, with no empty line) is cut before the head of that table."""
    for index in range(2, len(block)):
        if _ruler(block[index]) and not _ruler(block[index - 1]):
            return [block[:index - 1], *_split_at_dashes(block[index - 1:])]
    return [block]


def _dash_table(block: List[str]) -> Optional[Dict[str, Any]]:
    if len(block) < 2:
        return None
    ruler = block[1].strip()
    if not _ruler(ruler):
        return None
    separated = _SEPARATED.match(ruler)
    if separated:  # the dashes are joined by a separator (sqlcmd -s "|" or -s "\t"): it cuts the columns, not the places of the dashes
        char = separated.group(1)
        cells = [[cell.strip() for cell in line.split(char)] for line in block if not _NOTE.match(line.strip())]
        notes = [line.strip() for line in block[2:] if _NOTE.match(line.strip())]
        return _table(cells[0], [row for row in cells[2:]], notes)
    spans = [(found.start(), found.end()) for found in re.finditer(r"-+", block[1])]
    if not spans:
        return None
    cut = lambda line: [line[start:end if index + 1 < len(spans) else None].strip() for index, (start, end) in enumerate(spans)]  # noqa: E731 - the last column takes the rest
    columns = cut(block[0])
    rows = [cut(line) for line in block[2:] if not _NOTE.match(line.strip())]
    notes = [line.strip() for line in block[2:] if _NOTE.match(line.strip())]
    return _table(columns, rows, notes)


def _frame_table(block: List[str]) -> Optional[Dict[str, Any]]:
    lines = [line for line in block if not _FRAME.match(line.strip())]
    if len(lines) < 1 or not all(line.strip().startswith("|") and line.strip().endswith("|") for line in lines):
        return None
    cells = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    if len(cells) >= 2 and all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells[1]):  # a markdown table: its second line is the ruler
        cells.pop(1)
    return _table(cells[0], cells[1:], [])


def _tab_table(block: List[str]) -> Optional[Dict[str, Any]]:
    counts = {line.count("\t") for line in block}
    if len(counts) != 1 or counts == {0} or len(block) < 2:
        return None
    cells = [line.split("\t") for line in block]
    return _table([cell.strip() for cell in cells[0]], [[cell.strip() for cell in row] for row in cells[1:]], [])


def _table(columns: List[str], rows: List[List[str]], notes: List[str]) -> Dict[str, Any]:
    width = len(columns)
    rows = [(row + [""] * width)[:width] for row in rows]
    numeric = [all(_NUMBER.match(row[index]) or row[index] in ("", "NULL") for row in rows) and any(_NUMBER.match(row[index]) for row in rows) for index in range(width)] if rows else [False] * width
    return {"columns": columns, "rows": rows[:ROWS_SHOWN], "total": len(rows), "cut": len(rows) > ROWS_SHOWN, "numeric": numeric, "notes": notes}


def layout(text: str) -> Dict[str, Any]:
    """`{kind: text|tables, sets: [...], notes: [{text, error, after}], cut}`. `kind` is `text` when no table was found: the page shows the text whole then."""
    whole = text or ""
    cut = len(whole) > MAX_CHARS
    sets: List[Dict[str, Any]] = []
    notes: List[Dict[str, Any]] = []
    for block in (part for chunk in _blocks(whole[:MAX_CHARS].splitlines()) for part in _split_at_dashes(chunk) if part):
        table = _dash_table(block) or _frame_table(block) or _tab_table(block)
        if table is not None:
            for note in table.pop("notes"):
                notes.append({"text": note, "error": bool(_ERROR.match(note)), "after": len(sets) + 1})
            sets.append(table)
            continue
        for line in block:
            stripped = line.strip()
            if _NOTE.match(stripped) or _ERROR.match(stripped):
                notes.append({"text": stripped, "error": bool(_ERROR.match(stripped)), "after": len(sets)})
            elif notes and notes[-1]["error"] and notes[-1]["after"] == len(sets) and not sets:  # the lines of an error message that follow its head
                notes[-1]["text"] += "\n" + stripped
            elif notes and notes[-1]["error"] and notes[-1]["after"] == len(sets):
                notes[-1]["text"] += "\n" + stripped
            else:
                notes.append({"text": stripped, "error": False, "after": len(sets)}) if sets else None
    return {"kind": "tables" if sets else "text", "sets": sets, "notes": notes, "cut": cut, "rows": sum(table["total"] for table in sets)}
