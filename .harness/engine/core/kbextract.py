"""Running the extractors of a toolkit (M15-10d): one file in, its objects out. The contract is .harness/contracts/kb/map.md.

The extractors that know a stack live in the knowledge base (`<knowledge base>/toolkit/`), made by a team for its own
code. Here: decoding a file, loading an extractor from its file, running it so that one bad file cannot stop the map,
and the one extractor the harness ships, `regex`, whose rules are written in toolkit.json.
"""

from __future__ import annotations

import importlib.util
import re
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

Extractor = Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]


class ToolkitError(ValueError):
    """An extractor named in toolkit.json cannot be loaded."""


def decode(data: bytes) -> str:
    """UTF-16 with a BOM (SSMS on Windows saves scripts so), UTF-8, or else cp1252. Never raises."""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def load(file: Path, function: str) -> Extractor:
    """The function `function` of the Python file `file`, loaded under a name of its own (two toolkits may both have
    `extract_sql.py`)."""
    if not file.is_file():
        raise ToolkitError(f"{file} is not there")
    name = "kbtoolkit_" + sha256(str(file.resolve()).encode("utf-8")).hexdigest()[:12]
    spec = importlib.util.spec_from_file_location(name, file)
    if spec is None or spec.loader is None:
        raise ToolkitError(f"{file} cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:  # noqa: BLE001 - the error of someone else's code, shown as it is
        raise ToolkitError(f"{file}: {type(error).__name__}: {error}") from None
    found = getattr(module, function, None)
    if not callable(found):
        raise ToolkitError(f"{file} has no function {function}()")
    return found


def run(extractor: Extractor, data: bytes, context: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """(the objects of one file, the error when the extractor failed). Objects without an id or a type are dropped."""
    try:
        found = extractor(decode(data), context)
    except Exception as error:  # noqa: BLE001
        return [], f"{type(error).__name__}: {error}"
    if not isinstance(found, list):
        return [], "did not return a list"
    good = []
    for item in found:
        if isinstance(item, dict) and item.get("id") and item.get("type"):
            item.setdefault("name", str(item["id"]).split(":", 1)[-1])
            item["refs"] = [ref for ref in item.get("refs") or [] if isinstance(ref, dict) and ref.get("kind") and ref.get("name")]
            good.append(item)
    return good, None


def line_at(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def regex(text: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The extractor written as rules in toolkit.json: `node` {type, pattern with one group for the name} (no pattern: the
    file is the object, named by its path), `edges` [{kind, pattern with one group for the name used, as}]."""
    rule = context.get("rule") or {}
    node = rule.get("node") or {}
    kind = str(node.get("type") or "file")
    name, line = context["path"], 1
    if node.get("pattern"):
        match = re.search(node["pattern"], text, re.MULTILINE)
        if not match:
            return []
        name, line = match.group(1), line_at(text, match.start(1))
    refs, seen = [], set()
    for edge in rule.get("edges") or []:
        for match in re.finditer(edge["pattern"], text, re.MULTILINE):
            used = match.group(1)
            key = (edge.get("kind", "uses"), used)
            if used and used != name and key not in seen:
                seen.add(key)
                refs.append({"kind": edge.get("kind", "uses"), "name": used, "line": line_at(text, match.start(1)), **({"as": edge["as"]} if edge.get("as") else {})})
    return [{"id": f"{kind}:{name}", "type": kind, "name": name, "line": line, "dynamic": False, "refs": refs}]


BUILTIN: Dict[str, Extractor] = {"regex": regex}
