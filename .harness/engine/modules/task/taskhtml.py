"""The two pages a person opens in a browser (M12-1, M6-6): one task's time and usage, and the board of all tasks.

Python gives the numbers and puts the page together; it draws nothing. The front end is in `web/`:

  task.html, board.html   the skeleton of each page
  page.css                the look, shared
  common.js               helpers shared by both pages
  task.js, board.js       how each page is drawn from its data

`build` copies the style, the scripts and the data (as JSON) into the skeleton, so the result is still one file that
opens with a double click and asks the network for nothing. To change how a page looks, change the files in `web/`.
The data a page gets: the numbers from taskinsight or `task list`, and `text`, the messages it may show (the message
table is the one place for wording; the scripts hold none).
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import messages

WEB = Path(__file__).resolve().parent / "web"
MARKS = re.compile("|".join(re.escape(mark) for mark in ("<!--REFRESH-->", "<!--TITLE-->", "<!--NOSCRIPT-->", "/*CSS*/", "<!--DATA-->", "/*JS*/")))
TEXT_PREFIXES = ("report.", "board.", "insight.", "unit.", "task.kind.", "task.tier.")


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def page_text() -> Dict[str, str]:
    """The messages a page may show, by name. The scripts fill in the placeholders."""
    return {key: value for key, value in messages.table(messages.language()).items() if key.startswith(TEXT_PREFIXES)}


PAGE_LANGUAGE = '<html lang="en">'  # as the skeletons have it; the page gets the language of its texts


def as_json(data: Dict[str, Any]) -> str:
    """JSON that is safe inside a <script> element: no `</script>` and no `<!--` can end or open anything."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def build(skeleton: str, scripts: List[str], title: str, data: Dict[str, Any], refresh: int = 0) -> str:
    """One file: the skeleton with the style, the scripts and the data in it."""
    data = dict(data, text=page_text())
    parts = {
        "<!--REFRESH-->": f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else "",
        "<!--TITLE-->": escape(title),
        "<!--NOSCRIPT-->": escape(say("report.noscript")),
        "/*CSS*/": read("page.css"),
        "<!--DATA-->": as_json(data),
        "/*JS*/": "\n".join(read(name) for name in scripts),
    }
    skeleton_text = read(skeleton)
    for mark in parts:
        if skeleton_text.count(mark) != 1:
            raise ValueError(f"{skeleton}: the mark {mark} must be there once")
    # One pass over the skeleton: a mark that happens to be inside the data or a script is not touched.
    return MARKS.sub(lambda found: parts[found.group(0)], skeleton_text).replace(PAGE_LANGUAGE, f'<html lang="{messages.language()}">', 1)


def task_page(info: Dict[str, Any], refresh: int = 0, now: Optional[Dict[str, Any]] = None) -> str:
    """now: what the task waits for at this moment (tasklife.waiting_now), or None."""
    return build("task.html", ["common.js", "task.js"], say("report.title", name=info["name"]), {"info": info, "now": now}, refresh)


def board_page(rows: List[Dict[str, Any]], as_of: str, refresh: int = 0) -> str:
    """rows: what `task list` gives, each with `brief` (taskinsight.brief or None) and `report` (the file name of its page or '')."""
    return build("board.html", ["common.js", "board.js"], say("board.title"), {"rows": rows, "as_of": as_of, "refresh": int(refresh)}, refresh)
