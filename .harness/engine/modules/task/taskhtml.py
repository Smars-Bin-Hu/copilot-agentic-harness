"""The two pages a person opens in a browser (M12-1, M6-6): one task's time and usage, and the board of all tasks.

Python gives the numbers and puts the page together; it draws nothing. The front end is in `web/`:

  task.html, board.html   the skeleton of each page; desk.html: one task as the board server sends it (M16)
  tokens.css, ui.css      the look, shared: the colours of the light and the dark theme, and how things look under them; theme.js sets the theme and Lite before the page is drawn
  status.js, status.css   the small status marks (model, context ring, run time, mini stage ribbon, TODO) under a task name and on the lobby card; the ribbon is shared: the task page draws its stage strip from it and opens a card on it (`Status.card`)
  rounds.js, rounds.css         a served task page only: the earlier rounds of the chat, at the top of the Live tab
  run.js, run.css               a served task page only: the Ask agent and Run buttons of a shell code block, the panel of a running command
  live.js, reply.js, live.css   a served task page only: the stream of the Live tab (the latest items of the chat, changed in place) and the reply panel (a pill at the bottom centre; text, language, model, drafts, Send, Steer, Stop)
  desk.css                the task page shell: the slim header, the line of facts, the cards of waits, the tabs by function
  space.js, space.css     the board and the task page: the 3D stage behind the page (picture far back, dust nearer, floor grid and horizon with no picture), turning a little with the pointer; the frame-rate note
  wall.js, wall.css       the wallpaper (the pictures of the folder the person chose, small copies made in the browser), the glass panels over a picture, the Background part of the settings
  shell.js, shell.css     the board and the task page only: the search pill and Cmd+K palette, the gear and the settings panel, the VS Code banner (fixed to the window, outside the page)
  bot3d.js                the 3D robot of the Enter screen (WebGL, no library); enter.js keeps a flat one when it cannot run
  enter.js, enter.css     a served page only: the Enter screen (wordmark, robot, hold to charge, the readiness list of `/api/ready`); a file on disk has none
  page.css, lobby.css     where things go, shared / the board's lobby
  common.js               helpers shared by both pages
  tools.js                a served page only: the Tools window (a tab each for Tool packs, Connections, This computer) and the Tools group of Get ready (1.7.17)
  machine.js              a served page only: This computer (tool folders and the CA bundle VS Code is started with, 1.7.11)
  servers.js              a served page only: the Servers window (each server and the person's identity, tested before it is kept) and Open VS Code with identities (1.7.10)
  task.js, board.js       how each page is drawn from its data; desk.js the task page, diffview.js the code compare of its Changes tab, highlight.js the colours of code, serve.js the server's buttons, chat.js the send panel, steer and stop

`build` copies the style, the scripts and the data (as JSON) into the skeleton, so the result is still one file that
opens with a double click and asks the network for nothing. To change how a page looks, change the files in `web/`.
The data a page gets: the numbers from taskinsight or `task list`, and `text`, the messages it may show (the message
table is the one place for wording; the scripts hold none).
"""

from __future__ import annotations

import base64
import json
import re
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import messages
from core.paths import cli_command

WEB = Path(__file__).resolve().parent / "web"
MARKS = re.compile("|".join(re.escape(mark) for mark in ("<!--REFRESH-->", "<!--ICON-->", "<!--TITLE-->", "<!--NOSCRIPT-->", "/*THEME*/", "/*CSS*/", "<!--DATA-->", "/*JS*/")))
TEXT_PREFIXES = ("report.", "board.", "insight.", "unit.", "task.kind.", "task.tier.", "task.waiting.", "desk.", "stage.", "setup.", "dock.", "term.", "connections.", "machine.", "tools.")


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


def icon() -> str:
    """The robot for the browser tab and the header, inside the page: a saved page has nothing beside it (1.6.85)."""
    address = "data:image/png;base64," + base64.b64encode((WEB / "icon.png").read_bytes()).decode("ascii")
    return f'<link rel="icon" type="image/png" href="{address}">\n<style>:root{{--logo:url({address})}}</style>'


LOOK = ["tokens.css", "page.css"]  # first: the tokens and where things go ...
FINISH = ["ui.css"]  # ... last: how they look, over the rest
STATUS_CSS = "status.css"  # the pages that have status.js (the board) get the status marks after ui.css
SHELL_CSS = "shell.css"  # the pages that have shell.js (the board and the task page) get the fixed search and settings, the palette and the VS Code banner after ui.css


DESK_CSS = "desk.css"  # the task page (desk.js) gets its shell last: the slim header, the info line, the tabs by function, the cards of waits
ENTER_CSS = "enter.css"  # the served pages (enter.js) get the Enter screen after the shell
ROUNDS_CSS = "rounds.css"  # the served task page (rounds.js) gets the earlier rounds of the chat
RUN_CSS = "run.css"  # the served task page (run.js) gets the panel of a running command
LIVE_CSS = "live.css"  # the served task page (live.js, reply.js) gets the stream of the Live tab and the reply panel after its shell
SPACE_CSS = "space.css"  # the pages that have space.js get the 3D stage behind the page last ...
WALL_CSS = "wall.css"  # ... and, with wall.js, the glass panels over a wallpaper and the Background part of the settings, over everything else


def build(skeleton: str, scripts: List[str], title: str, data: Dict[str, Any], refresh: int = 0, styles: Optional[List[str]] = None) -> str:
    """One file: the skeleton with the style, the scripts and the data in it. `styles`: what goes between the tokens and ui.css."""
    data = dict(data, text=page_text())
    parts = {
        "<!--REFRESH-->": f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else "",
        "<!--ICON-->": icon(),
        "<!--TITLE-->": escape(title),
        "<!--NOSCRIPT-->": escape(say("report.noscript")),
        "/*THEME*/": read("theme.js"),
        "/*CSS*/": "\n".join(read(name) for name in [LOOK[0], *(styles or LOOK[1:]), *FINISH, *([STATUS_CSS] if "status.js" in scripts else []), *([SHELL_CSS] if "shell.js" in scripts else []), *([ENTER_CSS] if "enter.js" in scripts else []), *([DESK_CSS] if "desk.js" in scripts else []), *([LIVE_CSS] if "live.js" in scripts else []), *([RUN_CSS] if "run.js" in scripts else []), *(["dock.css", "kbatlas.css"] if "dock.js" in scripts else []), *(["setup.css"] if "setup.js" in scripts else []), *([ROUNDS_CSS] if "rounds.js" in scripts else []), *([SPACE_CSS] if "space.js" in scripts else []), *([WALL_CSS] if "wall.js" in scripts else [])]),
        "<!--DATA-->": as_json(data),
        "/*JS*/": "\n".join(read(name) for name in scripts),
    }
    skeleton_text = read(skeleton)
    for mark in parts:
        if skeleton_text.count(mark) != 1:
            raise ValueError(f"{skeleton}: the mark {mark} must be there once")
    # One pass over the skeleton: a mark that happens to be inside the data or a script is not touched.
    return MARKS.sub(lambda found: parts[found.group(0)], skeleton_text).replace(PAGE_LANGUAGE, f'<html lang="{messages.language()}">', 1)


def task_page(info: Dict[str, Any], refresh: int = 0, now: Optional[Dict[str, Any]] = None, serve: Optional[Dict[str, Any]] = None) -> str:
    """now: what the task waits for at this moment (tasklife.waiting_now), or None.
    serve: set when the board server sends the page (the Gate verdicts get buttons, and a link to save the page).
    Without it the page is a file: it shows the verdicts and has no calls to a server."""
    if serve is not None:
        return build("task.html", ["common.js", "serve.js", "chat.js", "dock.js", "term.js", "kbatlas.js", "servers.js", "machine.js", "tools.js", "setup.js", "task.js"], say("report.title", name=info["name"]), {"info": info, "now": now, "serve": serve}, refresh)
    return build("task.html", ["common.js", "task.js"], say("report.title", name=info["name"]), {"info": info, "now": now}, refresh)


def saved_report(info: Dict[str, Any], now: Optional[Dict[str, Any]] = None) -> str:
    """The report as one file to keep or send: as of now, no buttons, no server. It may run its own script and ask the network for nothing."""
    page = build("task.html", ["common.js", "task.js"], say("report.title", name=info["name"]), {"info": info, "now": now, "snapshot": True})
    return page.replace("<head>", f'<head>\n<meta http-equiv="Content-Security-Policy" content="{SNAPSHOT_CSP}">', 1)


def board_page(rows: List[Dict[str, Any]], as_of: str, refresh: int = 0, serve: Optional[Dict[str, Any]] = None, hidden: int = 0) -> str:
    """rows: what `task list` gives, each with `brief` (taskinsight.brief or None) and `report` (the file name of its page or '').
    serve: set when the board server sends the page: the actions it runs, and how often the page asks again.
    hidden: how many older closed tasks are not in the rows."""
    scripts = ["common.js", "serve.js", "chat.js", "status.js", "lobby.js", "space.js", "wall.js", "shell.js", "bot3d.js", "enter.js", "dock.js", "term.js", "kbatlas.js", "servers.js", "machine.js", "tools.js", "setup.js", "board.js"] if serve else ["common.js", "status.js", "lobby.js", "space.js", "wall.js", "shell.js", "board.js"]  # a file on disk never calls out
    return build("board.html", scripts, say("board.brand"), {"rows": rows, "hidden": hidden, "as_of": as_of, "refresh": int(refresh), "serve": serve, "cli": cli_command()}, refresh, ["page.css", "lobby.css"])


DESK_STYLES = ["page.css", "diffview.css", "highlight.css"]

# A saved copy opens from a disk, away from the board: it may run its own script and nothing else, and ask the network for nothing.
SNAPSHOT_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"


def setup_page(serve: Dict[str, Any]) -> str:
    """Get ready, as the board server sends it. It has no Enter screen: it is where a new copy goes from there."""
    return build("setup.html", ["common.js", "serve.js", "chat.js", "dock.js", "term.js", "kbatlas.js", "servers.js", "machine.js", "tools.js", "setup.js"], say("setup.title"), {"serve": serve, "getReady": True}, 0, ["page.css"])


def desk_page(desk: Dict[str, Any], serve: Optional[Dict[str, Any]] = None) -> str:
    """One task as the board server sends it (taskdesk.desk): documents, progress, history, changes, actions.
    Without `serve` it is a saved copy: one file with no buttons and no calls to a server, as of the time it was made."""
    if serve is not None:
        return build("desk.html", ["common.js", "serve.js", "chat.js", "status.js", "highlight.js", "diffview.js", "space.js", "wall.js", "shell.js", "bot3d.js", "enter.js", "dock.js", "term.js", "kbatlas.js", "servers.js", "machine.js", "tools.js", "setup.js", "live.js", "reply.js", "run.js", "rounds.js", "desk.js"], say("desk.title", name=desk["name"]), {"desk": desk, "serve": serve}, styles=DESK_STYLES)
    page = build("desk.html", ["common.js", "status.js", "highlight.js", "diffview.js", "space.js", "wall.js", "shell.js", "desk.js"], say("desk.title", name=desk["name"]), {"desk": desk, "snapshot": True}, styles=DESK_STYLES)
    return page.replace("<head>", f'<head>\n<meta http-equiv="Content-Security-Policy" content="{SNAPSHOT_CSP}">', 1)
