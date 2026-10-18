"""`task board --serve`: the board as a page on this computer only, with buttons that act (M15-4, M15-5).

  task board --serve [--port N] [--all]   a person starts it in a terminal; Ctrl+C stops it

Who may do what:
- Only a person at a terminal starts it (`person`), and the gate refuses an agent that tries. An agent that started it
  would be handed the pairing link.
- It listens on 127.0.0.1 only, and answers only to the Host and Origin of that address (no other web site, no DNS
  rebinding). Every POST needs the header `X-Harness-Board`, which a page of another site cannot send without asking.
- Pause and resume need nothing more: they guard nothing.
- The approvals need the paired browser. At start a random code is made and kept in memory only; the server opens the
  browser at `/#pair=<code>` and the page trades the code for a session cookie (HttpOnly, SameSite=Strict). The code
  works once. The terminal prints a new one only when the person presses Enter. When the server stops, it is gone.
- An approval runs the same function as the terminal command, in two steps: `preview` shows what the terminal would
  show and the code to type; `act` runs it with the code the person typed. A plan that changed between the two has
  another code, and the approval is refused, as in the terminal.
- `.harness/runtime/board-serve.json` holds the port while it runs: the gate refuses an agent's request to it.
"""

from __future__ import annotations

import http.server
import io
import json
import os
import secrets
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import unquote, urlparse

from core import config, messages
from core.paths import board_serve_file, utc_now

from . import autorun, common, task as task_ops, taskarchive, taskboard, taskdesk, taskhtml, tasklife, taskreview
from .common import CommandError

HEADER = "X-Harness-Board"
COOKIE = "harness_board"
MAX_BODY = 4096
MAX_ARCHIVE = 200  # tasks in one request
FREE = ("pause", "resume")  # no pairing: they guard nothing
REFRESH = 10  # seconds between two boards in the browser
# The pages may run their own inline script and talk to this server only: an agent's text drawn on a page cannot load
# or send anything elsewhere, even if it ever got past the drawing (which uses textContent only).
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def settings(root: Path) -> Dict[str, Any]:
    found = config.policy_or_empty(root, "task").get("board") or {}
    actions = found.get("actions")
    return {"port": config.whole(found.get("port"), 8765), "actions": list(actions) if isinstance(actions, list) else ["pause", "resume", "confirm-req", "approve-plan", "approve-promote", "review extend", "review waive", "autorun on", "recover", "archive", "close"]}


class Preview(Exception):
    """Raised by the reader in the first step of an approval: what the terminal would ask, without approving."""

    def __init__(self, asked: str) -> None:
        super().__init__(asked)
        self.asked = asked


def runner(root: Path, action: str, task: str) -> Callable[..., Dict[str, Any]]:
    """The function of the terminal command, ready to be called with reader/interactive/out."""
    table: Dict[str, Callable[..., Dict[str, Any]]] = {
        "approve-plan": lambda **kw: task_ops.approve_plan(root, task, **kw),
        "confirm-req": lambda **kw: task_ops.confirm_req(root, task, **kw),
        "approve-promote": lambda **kw: task_ops.approve_promote(root, task, **kw),
        "review extend": lambda **kw: taskreview.extend(root, task, 2, **kw),
        "review waive": lambda **kw: taskreview.waive(root, task, **kw),
        "autorun on": lambda **kw: autorun.turn_on(root, task, **kw),
        "recover": lambda **kw: task_ops.recover(root, task, **kw),
    }
    return table[action]


class Board:
    """What one server holds: the settings, the pairing code and the sessions of paired browsers. Memory only."""

    def __init__(self, root: Path, everything: bool, port: int, actions: List[str]) -> None:
        self.root = root
        self.everything = everything
        self.port = port
        self.actions = actions
        self.code = secrets.token_urlsafe(12)
        self.sessions: set = set()
        self.lock = threading.Lock()

    def new_code(self) -> str:
        with self.lock:
            self.code = secrets.token_urlsafe(12)
            return self.code

    def pair(self, code: str) -> Optional[str]:
        """A session token for the right code; the code is used up."""
        with self.lock:
            if not self.code or not secrets.compare_digest(code.encode(), self.code.encode()):
                return None
            self.code = ""
            token = secrets.token_urlsafe(24)
            self.sessions.add(token)
            return token

    def paired(self, token: str) -> bool:
        with self.lock:
            return bool(token) and token in self.sessions

    def rows(self) -> Dict[str, Any]:
        """The rows of the board as the page draws them, and how many older closed tasks are left out."""
        result, _problems = taskboard.board_rows(self.root, self.everything, 0, self.actions)
        return {"rows": result["tasks"], "hidden": result["closed_hidden"], "as_of": utc_now(), "archive_to": taskarchive.remembered(self.root)}

    def page(self) -> str:
        found = self.rows()
        return taskhtml.board_page(found["rows"], found["as_of"], 0, serve={"actions": self.actions, "refresh": REFRESH, "archive_to": found["archive_to"]}, hidden=found["hidden"])

    def desk(self, name: str) -> Dict[str, Any]:
        return taskdesk.desk(self.root, name, self.actions)

    def desk_page(self, name: str) -> str:
        return taskhtml.desk_page(self.desk(name), {"actions": self.actions, "refresh": REFRESH})

    def archive(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Move closed tasks out of the repository (`task archive`). `step`: `preview` says what would move; `act` moves them.
        The browser must be paired; no code is typed, for it changes no repository and an agent may do it with the person's yes."""
        if "archive" not in self.actions:
            raise CommandError(say("serve.action.off", action="archive"))
        names = data.get("tasks")
        if not isinstance(names, list) or not names or len(names) > MAX_ARCHIVE or not all(isinstance(name, str) and name for name in names):
            raise CommandError(say("serve.refused.request"))
        apply = str(data.get("step", "preview")) == "act"
        result = taskarchive.archive(self.root, names, False, str(data.get("to", "")).strip(), apply, bool(data.get("remember")) and apply)
        if apply:
            print(say("serve.did", action="archive", task=", ".join(result["archived"])), flush=True)
        return result

    def close(self, name: str) -> Dict[str, Any]:
        """Close a task (`task close`): the report is written, the session lets go. The folder stays; `task open` opens it again.
        The browser must be paired; no code is typed, for it undoes nothing that cannot be undone."""
        if "close" not in self.actions:
            raise CommandError(say("serve.action.off", action="close"))
        result = task_ops.close(self.root, name, say("serve.close.reason"))
        print(say("serve.did", action="close", task=task_ops.name_of(result["task"])), flush=True)
        return result

    def act(self, action: str, task: str, step: str, code: str = "") -> Dict[str, Any]:
        """Run one action. `step`: `preview` or `act` for an approval; pause and resume act at once."""
        if action not in self.actions:
            raise CommandError(say("serve.action.off", action=action))
        if action in FREE:
            result = (tasklife.pause if action == "pause" else tasklife.resume)(self.root, task, interactive=True)
            noted(self.root, result.get("task") or task, action)
            return result
        call = runner(self.root, action, task)
        out = io.StringIO()
        if step == "preview":
            def stop(asked: str) -> str:
                raise Preview(asked)

            try:
                call(reader=stop, interactive=True, out=out)
            except Preview as asked:
                return {"screen": [line for line in out.getvalue().splitlines() if line.strip()], "ask": asked.asked}
            raise CommandError(say("serve.preview.none"))
        result = call(reader=lambda _asked: code, interactive=True, out=out)
        noted(self.root, result.get("task") or task, action)
        return result


def noted(root: Path, task: str, action: str) -> None:
    """The audit trail says the action came from the board page, next to the line the action itself wrote."""
    try:
        with task_ops.locked(root, task_ops.resolve(root, task)) as data:
            task_ops.note(data, "board", action)
    except Exception:  # noqa: BLE001 - the action is done; a missing line must not undo it in the person's eyes
        pass


def handler_for(board: Board) -> type:
    allowed_hosts = {f"127.0.0.1:{board.port}", f"localhost:{board.port}"}
    allowed_origins = {f"http://{host}" for host in allowed_hosts}
    reports = (board.root / common.REPORTS_DIR).resolve()

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "harness-board"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the name is the base class's
            return  # the terminal shows only what the person needs

        def send(self, status: int, body: bytes, kind: str, extra: Optional[Dict[str, str]] = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if kind.startswith("text/html"):
                self.send_header("Content-Security-Policy", CSP)
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def answer(self, status: int, data: Dict[str, Any], extra: Optional[Dict[str, str]] = None) -> None:
            self.send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", extra)

        def host_ok(self) -> bool:
            return self.headers.get("Host", "") in allowed_hosts

        def token(self) -> str:
            for part in self.headers.get("Cookie", "").split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE:
                    return value
            return ""

        def do_GET(self) -> None:  # noqa: N802 - the name is the base class's
            if not self.host_ok():
                return self.send(403, b"", "text/plain")
            path = unquote(urlparse(self.path).path)
            if path in ("/", "/board.html") or path.startswith("/task/"):
                try:
                    page = board.page() if not path.startswith("/task/") else board.desk_page(path[len("/task/"):].strip("/"))
                    return self.send(200, page.encode("utf-8"), "text/html; charset=utf-8")
                except CommandError as error:  # a task the board does not list
                    return self.send(404, str(error).encode("utf-8"), "text/plain; charset=utf-8")
                except Exception as error:  # noqa: BLE001 - show it instead of a dead page
                    return self.send(500, f"{type(error).__name__}: {error}".encode("utf-8"), "text/plain; charset=utf-8")
            target = (reports / path.lstrip("/")).resolve()
            if not str(target).startswith(str(reports) + os.sep) or target.suffix != ".html" or not target.is_file():
                return self.send(404, b"", "text/plain")
            return self.send(200, target.read_bytes(), "text/html; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            origin = self.headers.get("Origin", "")
            if not self.host_ok() or (origin and origin not in allowed_origins) or self.headers.get(HEADER) != "1":
                return self.answer(403, {"error": say("serve.refused.request")})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(min(size, MAX_BODY)).decode("utf-8") or "{}") if 0 <= size <= MAX_BODY else None
            except (ValueError, UnicodeDecodeError):
                data = None
            if not isinstance(data, dict):
                return self.answer(400, {"error": say("serve.refused.body")})
            path = urlparse(self.path).path
            if path == "/api/pair":
                token = board.pair(str(data.get("code", "")))
                if token is None:
                    return self.answer(403, {"error": say("serve.pair.wrong")})
                cookie = f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/"
                return self.answer(200, {"paired": True}, {"Set-Cookie": cookie})
            if path == "/api/status":
                return self.answer(200, {"paired": board.paired(self.token())})
            if path == "/api/board":
                try:
                    return self.answer(200, board.rows())
                except Exception as error:  # noqa: BLE001 - the page keeps what it shows
                    return self.answer(500, {"error": str(error)})
            if path == "/api/close":
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed")})
                try:
                    return self.answer(200, {"result": board.close(str(data.get("task", "")))})
                except Exception as error:  # noqa: BLE001 - a refusal is shown on the page, as the terminal shows it
                    return self.answer(409, {"error": str(error)})
            if path == "/api/archive":
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed")})
                try:
                    return self.answer(200, {"result": board.archive(data)})
                except Exception as error:  # noqa: BLE001 - a refusal is shown on the page, as the terminal shows it
                    return self.answer(409, {"error": str(error)})
            if path == "/api/desk":
                try:
                    return self.answer(200, {"desk": board.desk(str(data.get("task", "")))})
                except Exception as error:  # noqa: BLE001 - the page keeps what it shows
                    return self.answer(404, {"error": str(error)})
            if path != "/api/act":
                return self.answer(404, {"error": say("serve.refused.request")})
            action, task, step = str(data.get("action", "")), str(data.get("task", "")), str(data.get("step", "act"))
            if action not in FREE and not board.paired(self.token()):
                return self.answer(403, {"error": say("serve.pair.needed")})
            try:
                result = board.act(action, task, step, str(data.get("code", "")))
            except Exception as error:  # noqa: BLE001 - a refusal is shown on the page, as the terminal shows it
                return self.answer(409, {"error": str(error)})
            print(say("serve.did", action=action, task=task_ops.name_of(task) if task else "-"), flush=True)
            return self.answer(200, {"result": result})

    return Handler


def serve(root: Path, everything: bool = True, port: Optional[int] = None, out: Any = None, interactive: Optional[bool] = None, opener: Callable[[str], Any] = webbrowser.open, ready: Optional[Callable[[Any], None]] = None) -> Dict[str, Any]:
    """Run until Ctrl+C. `opener` and `ready` exist for the tests: `ready` gets the server once it listens."""
    task_ops.person("task board --serve", interactive, typed=False)
    out = out or sys.stdout
    found = settings(root)
    board = Board(root, everything, port or found["port"], found["actions"])
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", board.port), handler_for(board))
    except OSError as error:
        raise CommandError(say("serve.port.busy", port=board.port, error=error))
    path = board_serve_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"port": board.port, "pid": os.getpid(), "started": utc_now()}), encoding="utf-8")
    address = f"http://127.0.0.1:{board.port}/"
    opened = False
    try:
        opened = bool(opener(f"{address}#pair={board.code}"))
    except Exception:  # noqa: BLE001 - the person can pair by hand
        opened = False
    print(say("serve.started", address=address, actions=", ".join(board.actions)), file=out, flush=True)
    print(say("serve.opened" if opened else "serve.not_opened"), file=out, flush=True)
    if ready is not None:
        ready(server)
    else:
        threading.Thread(target=wait_for_enter, args=(board, address, out), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            path.unlink()
        except OSError:
            pass
    return {"served": address, "stopped": True}


def wait_for_enter(board: Board, address: str, out: Any) -> None:
    """Enter in the server's terminal: a new pairing code for a browser that was not paired. The old one stops working."""
    while True:
        try:
            line = sys.stdin.readline()
        except Exception:  # noqa: BLE001
            return
        if not line:
            return
        print(say("serve.code", address=address, code=board.new_code()), file=out, flush=True)
