"""The two pages a person opens in a browser (M12-1, M6-6): one task's time and usage, and the board of all tasks.

Python gives the numbers and puts the page together; it draws nothing. The front end is in `web/`:

  task.html, board.html   the skeleton of each page; desk.html: one task as the board server sends it (M16)
  tokens.css, ui.css      the look, shared: the colours of the light and the dark theme, and how things look under them; theme.js sets the theme and Lite before the page is drawn
  status.js, status.css   the small status marks (model, context ring, run time, mini stage ribbon, TODO) under a task name and on the lobby card; the ribbon is shared: the task page draws its stage strip from it and opens a card on it (`Status.card`)
  batch.js, batch.css           a served task page only: the box over two held calls or more, one code for the ticked ones (1.7.38, F3)
  stmts.js, stmts.css           the task page: the statements of a held call one by one, numbered, each with its system and how its type judges it, the reads folded (1.7.38, F3)
  reopen.js, reopen.css         a served task page and the board (1.8.21): the card that says what a reopen of a closed task will be (same round, a new round, or why not) and the two ways on, the pill of the task page and the icon of a closed row in the list
  rounds.js, rounds.css         a served task page only: the earlier rounds of the chat, at the top of the Live tab
  run.js, run.css               a served task page only: the Ask agent and Run buttons of a shell code block, the panel of a running command
  live.js, reply.js, live.css   a served task page only: the stream of the Live tab (the latest items of the chat, changed in place) and the reply panel (a pill at the bottom centre; text, language, model, drafts, Send, Steer, Stop)
  desk.css                the task page shell: the slim header, the line of facts, the cards of waits, the tabs by function
  space.js, space.css     the board and the task page: the 3D stage behind the page (picture far back, dust nearer, floor grid and horizon with no picture), turning a little with the pointer; the frame-rate note
  wall.js, wall.css       the wallpaper (the pictures of the folder the person chose, small copies made in the browser), the glass panels over a picture, the Background part of the settings
  shell.js, shell.css     the board and the task page only: the search pill and Cmd+K palette, the gear and the settings panel, the VS Code banner (fixed to the window, outside the page)
  bot3d.js                the 3D robot of the Enter screen (WebGL, no library); enter.js keeps a flat one when it cannot run
  companion.js, companion.css   the board only, a served page: the pop-out of the super agent view, a small always-on-top window (Document Picture-in-Picture, Chrome and Edge) with the same data and buttons
  pet.js, super.js, super.css   the board only, a served page: the super agent view (1.8.1), with superhist.js for the earlier days, superdirect.js for the direct message of its chat, a messenger-like window of what waits for the person (`/api/super`) with the avatars of the tasks and a pet that walks over it (3D with bot3d.js, flat without WebGL); picked in the bar, never the default
  workbench.js, workbench.css   the board only, a served page: the full-screen workbench that holds the super agent view (the chat in the middle, the queue, panels, one card in Focus, the Task pane with the task page in an iframe)
  wbpanels.js, wbpanels.css     the board only, a served page: what the workbench draws in its places from the rows of the board (the tree of the agents that run, the Data panel, the picture of Focus, the hover card of a task, the entrance)
  enter.js, enter.css     a served page only: the Enter screen (wordmark, robot, hold to charge, the two blocks of `/api/ready`: Harness & Local required, From the company optional, and the VS Code button); a file on disk has none
  stop.js                 a served page only (1.8.11): the stop button at the top right (paired browsers; asks once, `POST /api/shutdown`), and the page that says the board has stopped and asks for nothing more
  readyui.js              a served page only: where a fix of the readiness answer leads (the setup form, a Tools window, the knowledge base window, the Terminal) and the VS Code button's restart (1.7.38)
  readybar.js, readybar.css   the board only: the red and the yellow block under its header after Enter (1.7.38)
  page.css, lobby.css     where things go, shared / the board's lobby
  common.js               helpers shared by both pages
  tools.js                a served page only: the three Tools windows (Tool packs, Connections & sign-ins, Local), opened one at a time, and the facts of Get ready (1.7.17, three windows 1.7.38)
  machine.js              a served page only: the Tool packs and Local windows (the packs, tool folders, the CA bundle, MCP)
  servers.js              a served page only: the Connections & sign-ins window (each connection with its sign-in and Test, Export) and Open VS Code with identities (1.7.10)
  perf.js, perf.css       the task's report page: the small part of the Agent Performance Review (1.7.41): the free accounts, the review's one line, the link to its page, the button that starts one
  perfpage.html, perfpage.js, perfpage.css   the Agent Performance Review page of a task (`/tasks/<task>/performance`, 1.7.41): the conclusion and the waste by owner, the cost of each prompt,
                          the findings as chains with their evidence, the prompt critiques, the suggestions by owner, the call timeline, the notes of each prompt
  task.js, board.js       how each page is drawn from its data; desk.js the task page, diffview.js the code compare of its Changes tab, highlight.js the colours of code, serve.js the server's buttons, chat.js the send panel, steer and stop

`build` copies the style, the scripts and the data (as JSON) into the skeleton, so the result is still one file that
opens with a double click and asks the network for nothing. To change how a page looks, change the files in `web/`.
The data a page gets: the numbers from taskinsight or `task list`, and `text`, the messages it may show (the message
table is the one place for wording; the scripts hold none).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
from collections import OrderedDict
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import messages, pace
from core.paths import cli_command

WEB = Path(__file__).resolve().parent / "web"
MARKS = re.compile("|".join(re.escape(mark) for mark in ("<!--REFRESH-->", "<!--ICON-->", "<!--TITLE-->", "<!--NOSCRIPT-->", "/*THEME*/", "/*CSS*/", "<!--DATA-->", "/*JS*/")))
TEXT_PREFIXES = ("report.", "board.", "insight.", "unit.", "task.kind.", "task.tier.", "task.waiting.", "desk.", "stage.", "setup.", "dock.", "term.", "connections.", "machine.", "tools.", "super.", "waits.", "send.refused.", "serve.refused.request")  # waits. (1.8.5): starting, error, being created, display name, on every page


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def page_text() -> Dict[str, str]:
    """The messages a page may show, by name. The scripts fill in the placeholders."""
    return {key: value for key, value in messages.fresh_table(messages.language()).items() if key.startswith(TEXT_PREFIXES)}


PAGE_LANGUAGE = '<html lang="en">'  # as the skeletons have it; the page gets the language of its texts


def as_json(data: Dict[str, Any]) -> str:
    """JSON that is safe inside a <script> element: no `</script>` and no `<!--` can end or open anything."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


_READ: Dict[str, Tuple[Tuple[int, int], str]] = {}  # the shipped page files, read again only when the file changed (mtime and size)


def read(name: str) -> str:
    path = WEB / name
    info = path.stat()
    stamp = (info.st_mtime_ns, info.st_size)
    found = _READ.get(name)
    if found is None or found[0] != stamp:
        found = (stamp, path.read_text(encoding="utf-8"))
        _READ[name] = found
    return found[1]


ASSET_LIMIT = 64  # assets kept in memory: the newest ones
ASSET_NAME = re.compile(r"[0-9a-f]{20}\.(css|js)")
ASSET_TYPES = {"css": "text/css; charset=utf-8", "js": "text/javascript; charset=utf-8"}
_ASSETS: "OrderedDict[str, Tuple[bytes, str]]" = OrderedDict()
_ASSET_LOCK = threading.Lock()


def keep_asset(content: str, extension: str) -> str:
    """Keep one asset of a linked page and give its link: the name is the first 20 hex digits of the content's sha256."""
    body = content.encode("utf-8")
    name = f"{hashlib.sha256(body).hexdigest()[:20]}.{extension}"
    with _ASSET_LOCK:
        _ASSETS[name] = (body, ASSET_TYPES[extension])
        _ASSETS.move_to_end(name)
        while len(_ASSETS) > ASSET_LIMIT:
            _ASSETS.popitem(last=False)
    return f"/asset/{name}"


def asset_of(name: str) -> Optional[Tuple[bytes, str]]:
    """(content, content type) of an asset a linked page has, or None."""
    if not ASSET_NAME.fullmatch(name):
        return None
    with _ASSET_LOCK:
        return _ASSETS.get(name)


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
REOPEN_CSS = "reopen.css"  # the served pages that have reopen.js get the card that says what a reopen will do, and the icon of a closed row
ROUNDS_CSS = "rounds.css"  # the served task page (rounds.js) gets the earlier rounds of the chat
AUTORUN_CSS = "autorun.css"  # the served pages that have autorun.js get the Start dialog and the run card
RUN_CSS = "run.css"  # the served task page (run.js) gets the panel of a running command
SUPER_CSS = "super.css"  # the served board (super.js) gets the super agent view
WORKBENCH_CSS = "workbench.css"  # ... and, with workbench.js, the full-screen workbench that holds it
WBPANELS_CSS = "wbpanels.css"  # ... and what the workbench draws in its places (wbpanels.js)
COMPANION_CSS = "companion.css"  # the pop-out of the super agent view (companion.js)
LIVE_CSS = "live.css"  # the served task page (live.js, reply.js) gets the stream of the Live tab and the reply panel after its shell
SPACE_CSS = "space.css"  # the pages that have space.js get the 3D stage behind the page last ...
WALL_CSS = "wall.css"  # ... and, with wall.js, the glass panels over a wallpaper and the Background part of the settings, over everything else


STYLE_BLOCK = "<style>\n/*CSS*/\n</style>"
SCRIPT_BLOCK = "<script>\n/*JS*/\n</script>"


def build(skeleton: str, scripts: List[str], title: str, data: Dict[str, Any], refresh: int = 0, styles: Optional[List[str]] = None, linked: bool = False) -> str:
    """One file: the skeleton with the style, the scripts and the data in it. `styles`: what goes between the tokens and ui.css.
    `linked` (the board server's pages): the style, the scripts and the texts are files of `/asset/` (`asset_of`) that the browser keeps; the theme and the data stay in the page."""
    data = dict(data, pace=pace.factor())  # 1.8.15: the time limits of the page grow with this computer's slowness (`core.pace`)
    texts = page_text()
    if not linked:
        data["text"] = texts  # a file on its own carries its texts; a linked page loads them from /asset/ (window.PAGE_TEXT, 1.8.24)
    css = "\n".join(read(name) for name in [LOOK[0], *(styles or LOOK[1:]), *FINISH, *([STATUS_CSS] if "status.js" in scripts else []), *([SHELL_CSS] if "shell.js" in scripts else []), *([ENTER_CSS] if "enter.js" in scripts else []), *([DESK_CSS] if "desk.js" in scripts else []), *([LIVE_CSS] if "live.js" in scripts else []), *([RUN_CSS] if "run.js" in scripts else []), *([AUTORUN_CSS] if "autorun.js" in scripts else []), *(["dock.css", "kbatlas.css", "company.css"] if "dock.js" in scripts else []), *(["setup.css"] if "setup.js" in scripts else []), *(["readybar.css"] if "readybar.js" in scripts else []), *([ROUNDS_CSS] if "rounds.js" in scripts else []), *([REOPEN_CSS] if "reopen.js" in scripts else []), *([SPACE_CSS] if "space.js" in scripts else []), *([WALL_CSS] if "wall.js" in scripts else []), *(["list.css"] if "board.js" in scripts else []), *([SUPER_CSS] if "super.js" in scripts else []), *([WORKBENCH_CSS] if "workbench.js" in scripts else []), *([WBPANELS_CSS] if "wbpanels.js" in scripts else []), *([COMPANION_CSS] if "companion.js" in scripts else []), *(["perf.css"] if "perf.js" in scripts else [])])
    js = "\n".join(read(name) for name in scripts)
    parts = {
        "<!--REFRESH-->": f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else "",
        "<!--ICON-->": icon(),
        "<!--TITLE-->": escape(title),
        "<!--NOSCRIPT-->": escape(say("report.noscript")),
        "/*THEME*/": read("theme.js"),
        "/*CSS*/": css,
        "<!--DATA-->": as_json(data),
        "/*JS*/": js,
    }
    skeleton_text = read(skeleton)
    for mark in parts:
        if skeleton_text.count(mark) != 1:
            raise ValueError(f"{skeleton}: the mark {mark} must be there once")
    if linked:  # the style and the scripts are links; the script of the page stays last in the body, after the data
        if STYLE_BLOCK not in skeleton_text or SCRIPT_BLOCK not in skeleton_text:
            raise ValueError(f"{skeleton}: the style and the script must be in their own blocks")
        text_link = keep_asset(f"window.PAGE_TEXT={as_json(texts)};", "js")
        skeleton_text = skeleton_text.replace(STYLE_BLOCK, f'<link rel="stylesheet" href="{keep_asset(css, "css")}">', 1).replace(SCRIPT_BLOCK, f'<script src="{text_link}"></script>\n<script src="{keep_asset(js, "js")}"></script>', 1)
        parts = {mark: value for mark, value in parts.items() if mark not in ("/*CSS*/", "/*JS*/")}
    # One pass over the skeleton: a mark that happens to be inside the data or a script is not touched.
    return MARKS.sub(lambda found: parts[found.group(0)], skeleton_text).replace(PAGE_LANGUAGE, f'<html lang="{messages.language()}">', 1)


def task_page(info: Dict[str, Any], refresh: int = 0, now: Optional[Dict[str, Any]] = None, serve: Optional[Dict[str, Any]] = None, linked: bool = False) -> str:
    """now: what the task waits for at this moment (tasklife.waiting_now), or None.
    serve: set when the board server sends the page (the Gate verdicts get buttons, and a link to save the page).
    Without it the page is a file: it shows the verdicts and has no calls to a server."""
    if serve is not None:
        return build("task.html", ["common.js", "serve.js", "chat.js", "dock.js", "term.js", "stop.js", "kbatlas.js", "companytab.js", "servers.js", "machine.js", "tools.js", "setup.js", "perf.js", "task.js"], say("report.title", name=info["name"]), {"info": info, "now": now, "serve": serve}, refresh, linked=linked)
    return build("task.html", ["common.js", "perf.js", "task.js"], say("report.title", name=info["name"]), {"info": info, "now": now}, refresh)


def saved_report(info: Dict[str, Any], now: Optional[Dict[str, Any]] = None) -> str:
    """The report as one file to keep or send: as of now, no buttons, no server. It may run its own script and ask the network for nothing."""
    page = build("task.html", ["common.js", "perf.js", "task.js"], say("report.title", name=info["name"]), {"info": info, "now": now, "snapshot": True})
    return page.replace("<head>", f'<head>\n<meta http-equiv="Content-Security-Policy" content="{SNAPSHOT_CSP}">', 1)


def perf_page(data: Dict[str, Any], linked: bool = False) -> str:
    """The Agent Performance Review page of a task (1.7.41), served only: it reads nothing and has no buttons but a way back to the report."""
    return build("perfpage.html", ["common.js", "perf.js", "perfpage.js"], say("report.perf.page.title", name=data["name"]), {"perf": data}, 0, ["page.css", "perfpage.css"], linked)


def board_page(rows: List[Dict[str, Any]], as_of: str, refresh: int = 0, serve: Optional[Dict[str, Any]] = None, hidden: int = 0, linked: bool = False) -> str:
    """rows: what `task list` gives, each with `brief` (taskinsight.brief or None) and `report` (the file name of its page or '').
    serve: set when the board server sends the page: the actions it runs, and how often the page asks again.
    hidden: how many older closed tasks are not in the rows."""
    scripts = ["common.js", "serve.js", "chat.js", "reopen.js", "status.js", "lobby.js", "space.js", "wall.js", "shell.js", "bot3d.js", "readyui.js", "enter.js", "dock.js", "term.js", "stop.js", "kbatlas.js", "companytab.js", "servers.js", "machine.js", "tools.js", "setup.js", "readybar.js", "autorun.js", "pet.js", "companion.js", "superhist.js", "superdirect.js", "super.js", "wbpanels.js", "workbench.js", "board.js"] if serve else ["common.js", "status.js", "lobby.js", "space.js", "wall.js", "shell.js", "board.js"]  # a file on disk never calls out
    return build("board.html", scripts, say("board.brand"), {"rows": rows, "hidden": hidden, "as_of": as_of, "refresh": int(refresh), "serve": serve, "cli": cli_command()}, refresh, ["page.css", "lobby.css"], linked)


DESK_STYLES = ["page.css", "diffview.css", "highlight.css", "stmts.css", "batch.css"]

# A saved copy opens from a disk, away from the board: it may run its own script and nothing else, and ask the network for nothing.
SNAPSHOT_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"


def setup_page(serve: Dict[str, Any], linked: bool = False) -> str:
    """Get ready, as the board server sends it. It has no Enter screen: it is where a new copy goes from there."""
    return build("setup.html", ["common.js", "serve.js", "chat.js", "dock.js", "term.js", "stop.js", "kbatlas.js", "companytab.js", "servers.js", "machine.js", "tools.js", "setup.js"], say("setup.title"), {"serve": serve, "getReady": True}, 0, ["page.css"], linked)


def desk_page(desk: Dict[str, Any], serve: Optional[Dict[str, Any]] = None, linked: bool = False) -> str:
    """One task as the board server sends it (taskdesk.desk): documents, progress, history, changes, actions.
    Without `serve` it is a saved copy: one file with no buttons and no calls to a server, as of the time it was made."""
    if serve is not None:
        return build("desk.html", ["common.js", "serve.js", "chat.js", "reopen.js", "status.js", "highlight.js", "stmts.js", "batch.js", "diffview.js", "space.js", "wall.js", "shell.js", "bot3d.js", "readyui.js", "enter.js", "dock.js", "term.js", "stop.js", "kbatlas.js", "companytab.js", "servers.js", "machine.js", "tools.js", "setup.js", "live.js", "reply.js", "run.js", "rounds.js", "autorun.js", "desk.js"], say("desk.title", name=desk["name"]), {"desk": desk, "serve": serve}, styles=DESK_STYLES, linked=linked)
    page = build("desk.html", ["common.js", "status.js", "highlight.js", "stmts.js", "diffview.js", "space.js", "wall.js", "shell.js", "desk.js"], say("desk.title", name=desk["name"]), {"desk": desk, "snapshot": True}, styles=DESK_STYLES)
    return page.replace("<head>", f'<head>\n<meta http-equiv="Content-Security-Policy" content="{SNAPSHOT_CSP}">', 1)
