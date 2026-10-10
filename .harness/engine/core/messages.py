"""The message table (M11-11): what the engine says to people and agents, by name.

Code names a message; the text lives in `messages.<language>.json` next to this file. There is one language now (`zh`).
A translation is a second file with the same names. A name that is missing, or a table that cannot be read, gives the
name itself back: a wrong text must not stop a command or a hook.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_LANGUAGE = "zh"
_TABLES: Dict[str, Dict[str, str]] = {}


def table_path(language: str = DEFAULT_LANGUAGE) -> Path:
    return Path(__file__).resolve().parent / f"messages.{language}.json"


def table(language: str = DEFAULT_LANGUAGE) -> Dict[str, str]:
    if language not in _TABLES:
        try:
            with table_path(language).open(encoding="utf-8-sig") as handle:
                data = json.load(handle)
            _TABLES[language] = {key: value for key, value in data.items() if isinstance(value, str)} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _TABLES[language] = {}
    return _TABLES[language]


def text(key: str, **values: Any) -> str:
    """The message `key` with `{placeholders}` filled in. Never raises."""
    template = table().get(key)
    if template is None:
        return key
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        return template
