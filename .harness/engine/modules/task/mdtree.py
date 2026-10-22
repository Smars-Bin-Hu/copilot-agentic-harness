"""Markdown into a tree of blocks for the task page (M16): Python reads, the page draws with textContent only.

Task files are written by an agent, so their text is never markup: no HTML passes, a link is kept only when it is
http(s), mailto, an anchor, or a path, and the page builds every node itself (web/desk.js). Only what task files use
is read: headings, paragraphs, lists (nested, with `[ ]` / `[x]`), tables, fenced code, quotes, rules; inline code,
**bold**, *italic*, ~~strike~~ and [links](...). Anything else stays text.

  block  {"t": "h", "level", "spans"} | {"t": "p", "spans"} | {"t": "ul"|"ol", "start", "items": [{"check", "spans", "blocks"}]}
         | {"t": "code", "lang", "text"} | {"t": "quote", "blocks"} | {"t": "table", "head", "align", "rows"} | {"t": "hr"}
  span   {"t": "text", "v"} | {"t": "code", "v"} | {"t": "b"|"i"|"s", "c": [spans]} | {"t": "a", "href", "c": [spans]} | {"t": "br"}
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

Block = Dict[str, Any]
Span = Dict[str, Any]

MAX_LINES = 5000
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([\w+.-]*)")
RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
CHECK = re.compile(r"^\[([ xX])\]\s+(.*)$")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
SAFE_SCHEME = re.compile(r"^(https?:|mailto:)", re.IGNORECASE)
ANY_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


# --- inline ---------------------------------------------------------------------------------------------


def safe_href(raw: str) -> Optional[str]:
    """The link as given when it is http(s), mailto, an anchor or a path; None for any other scheme (javascript:, data:)."""
    href = raw.strip().strip("<>").split()[0] if raw.strip() else ""
    if not href:
        return None
    if SAFE_SCHEME.match(href) or href.startswith("#"):
        return href
    if ANY_SCHEME.match(href) and not re.match(r"^[a-zA-Z]:[\\/]", href):  # `C:\...` is a path, not a scheme
        return None
    return href


CLOSERS = ")]},.;:!?"


def closing(text: str, start: int, mark: str) -> int:
    """Where `mark` closes, after `start`, with no space right before it; -1 when it does not."""
    index = text.find(mark, start)
    while index != -1:
        if index > start and not text[index - 1].isspace():
            return index
        index = text.find(mark, index + 1)
    return -1


def spans(text: str) -> List[Span]:
    """The inline parts of one paragraph, table cell or item."""
    out: List[Span] = []
    plain: List[str] = []

    def flush() -> None:
        if plain:
            out.append({"t": "text", "v": "".join(plain)})
            plain.clear()

    index, size = 0, len(text)
    while index < size:
        char = text[index]
        if char == "\\" and index + 1 < size and text[index + 1] in "\\`*_[]()#+-.!|~<>":
            plain.append(text[index + 1])
            index += 2
            continue
        if char == "`":
            ticks = len(text[index:]) - len(text[index:].lstrip("`"))
            end = text.find("`" * ticks, index + ticks)
            if end != -1:
                flush()
                out.append({"t": "code", "v": text[index + ticks:end].strip()})
                index = end + ticks
                continue
        if char == "\n":
            flush()
            out.append({"t": "br"})
            index += 1
            continue
        if char == "[":
            found = link_at(text, index)
            if found:
                label, href, end = found
                flush()
                safe = safe_href(href)
                out.append({"t": "a", "href": safe, "c": spans(label)} if safe else {"t": "text", "v": label})
                index = end
                continue
        for mark, kind in (("**", "b"), ("__", "b"), ("~~", "s"), ("*", "i")):
            if text.startswith(mark, index) and index + len(mark) < size and not text[index + len(mark)].isspace():
                if mark == "__" and index > 0 and text[index - 1].isalnum():
                    continue  # snake__case is a name, not bold
                if text[index + len(mark)] in CLOSERS:
                    continue  # `COUNT(*)`: a mark that closes a bracket at once opens nothing (B62: two of them on a line made italics)
                end = closing(text, index + len(mark), mark)
                if end != -1:
                    flush()
                    out.append({"t": kind, "c": spans(text[index + len(mark):end])})
                    index = end + len(mark)
                    break
        else:
            plain.append(char)
            index += 1
    flush()
    return out


def link_at(text: str, start: int) -> Optional[Tuple[str, str, int]]:
    """`[label](href)` at `start`: (label, href, the index after it). Brackets inside the label may nest once."""
    depth, index = 0, start
    while index < len(text):
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if depth == 0:
                break
        index += 1
    else:
        return None
    if not text.startswith("(", index + 1):
        return None
    depth, end = 1, index + 2
    while end < len(text) and depth:  # a link may hold balanced parentheses: `(https://x/a_(b))`
        depth += {"(": 1, ")": -1}.get(text[end], 0)
        end += 1
    if depth:
        return None
    return text[start + 1:index], text[index + 2:end - 1], end


# --- blocks ---------------------------------------------------------------------------------------------


def cells(line: str) -> List[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    parts, current, index = [], "", 0
    while index < len(body):
        if body[index] == "\\" and body[index + 1:index + 2] == "|":
            current += "|"
            index += 2
            continue
        if body[index] == "|":
            parts.append(current.strip())
            current = ""
        else:
            current += body[index]
        index += 1
    parts.append(current.strip())
    return parts


def align_of(cell: str) -> str:
    cell = cell.strip()
    if cell.startswith(":") and cell.endswith(":"):
        return "center"
    return "right" if cell.endswith(":") else "left" if cell.startswith(":") else ""


def indent_of(line: str) -> int:
    return len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip(" "))


def starts_block(line: str) -> bool:
    return bool(HEADING.match(line) or FENCE.match(line) or RULE.match(line) or ITEM.match(line) or line.lstrip().startswith(">"))


def list_block(lines: List[str], index: int) -> Tuple[Block, int]:
    """A list from `index`: its items, each with what is indented under it parsed as blocks of its own."""
    first = ITEM.match(lines[index])
    base = indent_of(lines[index])
    ordered = first.group(2)[0].isdigit()
    block: Block = {"t": "ol" if ordered else "ul", "start": int(first.group(2)[:-1]) if ordered else 1, "items": []}
    while index < len(lines):
        match = ITEM.match(lines[index])
        if not match or indent_of(lines[index]) != base or match.group(2)[0].isdigit() != ordered:
            break
        text = match.group(3)
        check: Optional[bool] = None
        ticked = CHECK.match(text)
        if ticked:
            check, text = ticked.group(1) != " ", ticked.group(2)
        index += 1
        body: List[str] = []
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                if index + 1 < len(lines) and lines[index + 1].strip() and indent_of(lines[index + 1]) > base:
                    body.append("")
                    index += 1
                    continue
                break
            if indent_of(line) <= base and (ITEM.match(line) or starts_block(line) or not body):
                if not ITEM.match(line) and not starts_block(line) and not body:
                    text += "\n" + line.strip()  # a lazy line of the item's own text
                    index += 1
                    continue
                break
            body.append(line)
            index += 1
        inner = [line[min(indent_of(line), base + 2):] if line.strip() else "" for line in body]
        lead: List[str] = []
        while inner and inner[0].strip() and not starts_block(inner[0]):
            lead.append(inner.pop(0).strip())
        if lead:
            text += "\n" + "\n".join(lead)
        block["items"].append({"check": check, "spans": spans(text.replace("\n", " ")), "blocks": blocks(inner) if inner else []})
        while index < len(lines) and not lines[index].strip() and index + 1 < len(lines) and ITEM.match(lines[index + 1]) and indent_of(lines[index + 1]) == base:
            index += 1  # a blank line between two items of the same list
    return block, index


def blocks(lines: List[str]) -> List[Block]:
    out: List[Block] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        fence = FENCE.match(line)
        if fence:
            marker, code = fence.group(2), []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(marker):
                code.append(lines[index])
                index += 1
            out.append({"t": "code", "lang": fence.group(3), "text": "\n".join(code)})
            index += 1
            continue
        heading = HEADING.match(line)
        if heading:
            out.append({"t": "h", "level": len(heading.group(1)), "spans": spans(heading.group(2))})
            index += 1
            continue
        if RULE.match(line):
            out.append({"t": "hr"})
            index += 1
            continue
        if ITEM.match(line):
            block, index = list_block(lines, index)
            out.append(block)
            continue
        if line.lstrip().startswith(">"):
            quoted = []
            while index < len(lines) and lines[index].lstrip().startswith(">"):
                quoted.append(re.sub(r"^\s*>\s?", "", lines[index]))
                index += 1
            out.append({"t": "quote", "blocks": blocks(quoted)})
            continue
        if "|" in line and index + 1 < len(lines) and TABLE_RULE.match(lines[index + 1]):
            head = cells(line)
            aligns = [align_of(cell) for cell in cells(lines[index + 1])]
            index += 2
            rows = []
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                row = cells(lines[index])
                rows.append([spans(cell) for cell in (row + [""] * len(head))[:len(head)]])
                index += 1
            out.append({"t": "table", "head": [spans(cell) for cell in head], "align": (aligns + [""] * len(head))[:len(head)], "rows": rows})
            continue
        paragraph = [line.strip()]
        index += 1
        while index < len(lines) and lines[index].strip() and not starts_block(lines[index]) and not ("|" in lines[index] and index + 1 < len(lines) and TABLE_RULE.match(lines[index + 1])):
            paragraph.append(lines[index].strip())
            index += 1
        text = " ".join(paragraph)
        out.append({"t": "p", "spans": spans(text)})
    return out


def parse(text: str) -> Dict[str, Any]:
    """{"blocks": [...], "cut": True when the text was longer than MAX_LINES (the rest is not shown)}."""
    text = text[1:] if text.startswith("\ufeff") else text  # a file written by Windows PowerShell or Notepad starts with a BOM: it would hide the first heading
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cut = len(lines) > MAX_LINES
    return {"blocks": blocks(lines[:MAX_LINES]), "cut": cut}
