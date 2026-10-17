"""The message table (M11-11): what the engine says to people and agents, by name.

Code names a message; the text lives in `messages.<language>.json` next to this file, one file per language with the
same names. The language is `user.json`'s `language` (`en` or `zh`); `HARNESS_LANGUAGE` in the environment wins over
it. A name that is missing in one language is taken from the other; a name that is in neither, or a table that cannot
be read, gives the name itself back: a wrong text must not stop a command or a hook.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

LANGUAGES = ("en", "zh")
DEFAULT_LANGUAGE = "en"
ENVIRONMENT = "HARNESS_LANGUAGE"
POLICY_NAME = "user"
_TABLES: Dict[str, Dict[str, str]] = {}
_LANGUAGE: Optional[str] = None


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


def configured(root: Optional[Path] = None) -> Any:
    """What `user.json` (with its override) says, as written. None when it cannot be read: that is doctor's to report."""
    from . import config, paths  # here, not at the top: every module imports this one

    return config.policy_or_empty(root or paths.repo_root(), POLICY_NAME).get("language")


def language(root: Optional[Path] = None) -> str:
    """The language of this process. Read once: one command or one hook call speaks one language."""
    global _LANGUAGE
    if _LANGUAGE is None or root is not None:
        wanted = os.environ.get(ENVIRONMENT, "").strip().lower() or configured(root)
        found = wanted if wanted in LANGUAGES else DEFAULT_LANGUAGE
        if root is not None:
            return found
        _LANGUAGE = found
    return _LANGUAGE


def reset() -> None:
    """Forget the language that was read (tests change it between calls)."""
    global _LANGUAGE
    _LANGUAGE = None


def text(key: str, /, **values: Any) -> str:
    """The message `key` with `{placeholders}` filled in. Never raises."""
    spoken = language()
    template = table(spoken).get(key)
    if template is None:
        template = next((table(other)[key] for other in LANGUAGES if other != spoken and key in table(other)), None)
    if template is None:
        return key
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        return template


def pick(value: Any) -> str:
    """A text a policy file gives: one string, or one per language (`{"en": "...", "zh": "..."}`)."""
    if not isinstance(value, dict):
        return str(value)
    spoken = language()
    return str(value.get(spoken) or value.get(DEFAULT_LANGUAGE) or next(iter(value.values()), ""))


def joined(items: Any) -> str:
    """A list of names in one line, with the comma of the language."""
    return text("list.comma").join(str(item) for item in items)
