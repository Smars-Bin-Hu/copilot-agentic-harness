"""The part of YAML a knowledge base uses, read and written with the standard library only.

Read: mappings and lists by indentation (`key: value`, `key:` + a block, `- item`, `- key: value` + more keys),
quoted and plain scalars, `true`/`false`/`null`, whole numbers, flow lists of scalars (`[a, b]`), `#` comments.
Not read: anchors, tags, multi-line strings, flow mappings. Such a file gives a YamlError with the line number.
"""

from __future__ import annotations

import json
import re
from typing import Any, List, Tuple

KEY = re.compile(r"^([^\s#'\"][^:#]*?|'[^']*'|\"[^\"]*\")\s*:(?:\s+(.*))?$")
PLAIN_SAFE = re.compile(r"^[A-Za-z0-9_./@<>()+=,-][^#:]*$")


class YamlError(ValueError):
    pass


def strip_comment(text: str) -> str:
    quote = ""
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or text[index - 1] in " \t"):
            return text[:index].rstrip()
    return text.rstrip()


def scalar(text: str) -> Any:
    text = text.strip()
    if text == "" or text in ("null", "~"):
        return None
    if text in ("true", "false"):
        return text == "true"
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1].replace("''", "'") if text[0] == "'" else json.loads(text)
    if text == "{}":
        return {}
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [scalar(part) for part in split_flow(inner)] if inner else []
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def split_flow(text: str) -> List[str]:
    parts, current, quote = [], "", ""
    for char in text:
        if quote:
            current += char
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
            current += char
        elif char == ",":
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [part.strip() for part in parts]


def loads(text: str) -> Any:
    lines: List[Tuple[int, int, str]] = []  # (line number, indent, content)
    for number, raw in enumerate(text.lstrip("﻿").splitlines(), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlError(f"line {number}: a tab in the indent")
        content = strip_comment(raw)
        if content.strip() and content.strip() != "---":
            lines.append((number, len(content) - len(content.lstrip(" ")), content.strip()))
    if not lines:
        return None
    value, position = block(lines, 0, lines[0][1])
    if position != len(lines):
        raise YamlError(f"line {lines[position][0]}: not where an item of the level above can be")
    return value


def block(lines: List[Tuple[int, int, str]], position: int, indent: int) -> Tuple[Any, int]:
    """The mapping or list that starts at `position` and holds the lines indented exactly `indent`."""
    if lines[position][2].startswith("- ") or lines[position][2] == "-":
        return sequence(lines, position, indent)
    return mapping(lines, position, indent)


def mapping(lines: List[Tuple[int, int, str]], position: int, indent: int, first: str = "") -> Tuple[dict, int]:
    out: dict = {}
    while position < len(lines):
        number, level, content = lines[position]
        if first:
            content, first = first, ""
        elif level != indent:
            if level < indent:
                break
            raise YamlError(f"line {number}: indented more than the keys around it")
        if content.startswith("- "):
            break
        match = KEY.match(content)
        if not match:
            raise YamlError(f"line {number}: expected `key: value`")
        key, rest = scalar(match.group(1)), (match.group(2) or "").strip()
        position += 1
        if rest:
            out[key] = scalar(rest)
        elif position < len(lines) and (lines[position][1] > indent or (lines[position][1] == indent and lines[position][2].startswith("- "))):
            out[key], position = block(lines, position, lines[position][1])
        else:
            out[key] = None
    return out, position


def sequence(lines: List[Tuple[int, int, str]], position: int, indent: int) -> Tuple[list, int]:
    out: list = []
    while position < len(lines):
        number, level, content = lines[position]
        if level != indent or not (content.startswith("- ") or content == "-"):
            if level > indent:
                raise YamlError(f"line {number}: indented more than the items around it")
            break
        rest = content[1:].strip()
        if not rest:
            position += 1
            item, position = block(lines, position, lines[position][1]) if position < len(lines) and lines[position][1] > indent else (None, position)
            out.append(item)
        elif KEY.match(rest) and not (rest[0] in "'\"" and rest.endswith(rest[0])):
            item, position = mapping(lines, position, indent + 2 + (len(rest) - len(rest.lstrip())), first=rest)
            out.append(item)
        else:
            out.append(scalar(rest))
            position += 1
    return out, position


def quote(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if text and PLAIN_SAFE.match(text) and text not in ("true", "false", "null", "~") and not re.fullmatch(r"-?\d+", text) and text == text.strip():
        return text
    return json.dumps(text, ensure_ascii=False)


def dumps(value: Any, indent: int = 0) -> str:
    return "\n".join(emit(value, indent)) + "\n"


def emit(value: Any, indent: int) -> List[str]:
    pad = " " * indent
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                out.append(f"{pad}{quote(key)}:")
                out += emit(item, indent + 2 if isinstance(item, dict) else indent + 2)
            else:
                out.append(f"{pad}{quote(key)}: {'[]' if item == [] else '{}' if item == {} else quote(item)}")
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict) and item:
                inner = emit(item, indent + 2)
                out.append(f"{pad}- {inner[0].lstrip()}")
                out += inner[1:]
            elif isinstance(item, list) and item:
                out.append(f"{pad}-")
                out += emit(item, indent + 2)
            else:
                out.append(f"{pad}- {quote(item)}")
        return out
    return [pad + quote(value)]
