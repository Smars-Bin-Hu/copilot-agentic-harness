"""Probe: does VS Code's own agent host accept the sign-in of GitHub CLI (gh) here?

    python gh-token-probe.py [--gh <path to gh.exe>]

Standard library only (Python 3.9+). It takes the token from `gh auth token`, starts `code agent host`
in its own folder (<home>/agent-host-probe), hands the token over the connection, counts the Copilot
models, runs one short turn, then restarts the host and hands the token again (gh keeps it, so no
new sign-in). The token is never printed and never written anywhere by this probe.
An editor that is open is not touched: the probe host has its own folders.
"""
import argparse
import base64
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid

HOME = os.environ.get("AGENT_HOST_PROBE_HOME") or os.path.join(os.path.expanduser("~"), "agent-host-probe")
WAIT = 300  # a first start downloads a server package
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
SECRET = re.compile(r"(gh[opsu]_|github_pat_)[A-Za-z0-9_]+")


def say(step, ok, text):
    print("[%s] %s  %s" % (step, "OK  " if ok else "FAIL", text), flush=True)


def scrub(text):
    text = SECRET.sub(r"\1***", text)
    return text.split("tkn=")[0] + "tkn=***" if "tkn=" in text else text


def find_gh(given):
    places = [given] if given else []
    places.append(os.path.join(os.path.expanduser("~"), "tools", "gh", "bin", "gh.exe" if os.name == "nt" else "gh"))
    for place in places:
        if place and os.path.isfile(place):
            return place
    return shutil.which("gh")


def gh_token(gh):
    done = subprocess.run([gh, "auth", "token"], capture_output=True, timeout=60, creationflags=FLAGS, stdin=subprocess.DEVNULL)
    return done.stdout.decode().strip() if done.returncode == 0 else ""


def find_code():
    places = []
    if sys.platform == "darwin":
        app = "Visual Studio Code.app/Contents/Resources/app/bin/code"
        places = ["/Applications/" + app, os.path.join(os.path.expanduser("~"), "Applications", app)]
    elif os.name == "nt":
        for key, folder in (("LOCALAPPDATA", "Programs\\Microsoft VS Code"), ("ProgramFiles", "Microsoft VS Code")):
            if os.environ.get(key):
                places.append(os.environ[key].rstrip("\\/") + "\\" + folder + "\\bin\\code.cmd")
    for place in places:
        if os.path.isfile(place):
            return place
    found = shutil.which("code")
    return found if found and "remote-cli" not in found.replace("\\", "/") else None


def clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("VSCODE_IPC") and k != "ELECTRON_RUN_AS_NODE"}


def dirs():
    return ["--user-data-dir", os.path.join(HOME, "user"), "--cli-data-dir", os.path.join(HOME, "cli")]


def run(code, arguments, timeout=60):
    done = subprocess.run([code] + arguments, capture_output=True, timeout=timeout, env=clean_env(), creationflags=FLAGS, stdin=subprocess.DEVNULL)
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


class Socket:
    """A small WebSocket client: text frames, one JSON-RPC message a frame."""

    def __init__(self, host, port, token):
        self.sock = socket.create_connection((host, port), timeout=180)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(("GET /?tkn=%s HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (token, key)).encode())
        raw = b""
        while b"\r\n\r\n" not in raw:
            data = self.sock.recv(4096)
            if not data:
                raise OSError("the host closed the connection")
            raw += data
        head, self.rest = raw.split(b"\r\n\r\n", 1)
        if b" 101" not in head.split(b"\r\n")[0]:
            raise OSError("the host refused the upgrade")
        self.counter = 0

    def _take(self, count):
        while len(self.rest) < count:
            data = self.sock.recv(65536)
            if not data:
                raise OSError("the host closed the connection")
            self.rest += data
        out, self.rest = self.rest[:count], self.rest[count:]
        return out

    def _frame(self, opcode, data):
        mask = os.urandom(4)
        size = len(data)
        head = bytes([0x80 | opcode]) + (bytes([0x80 | size]) if size < 126 else (bytes([0x80 | 126]) + struct.pack(">H", size) if size < 65536
                                                                                  else bytes([0x80 | 127]) + struct.pack(">Q", size)))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def read(self):
        text = b""
        while True:
            first, second = self._take(2)
            size = second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._take(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._take(8))[0]
            data = self._take(size)
            opcode = first & 0x0F
            if opcode == 9:
                self._frame(10, data)
                continue
            if opcode == 8:
                raise OSError("the host closed the connection")
            if opcode in (0, 1):
                text += data
                if first & 0x80:
                    return json.loads(text.decode("utf-8"))

    def send(self, message):
        self._frame(1, json.dumps(message).encode())

    def call(self, method, params):
        self.counter += 1
        mine = self.counter
        self.send({"jsonrpc": "2.0", "id": mine, "method": method, "params": params})
        while True:
            message = self.read()
            if message.get("id") == mine and "method" not in message:
                if "error" in message:
                    raise OSError("%s: %s" % (method, scrub(json.dumps(message["error"]))[:300]))
                return message.get("result") or {}
            if "method" in message and "id" in message:
                self.send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "method not found"}})


def chat_actions(value):
    if isinstance(value, dict):
        if str(value.get("type", "")).startswith("chat/"):
            yield value
        for inner in value.values():
            yield from chat_actions(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from chat_actions(inner)


def copilot_models(link):
    root = (link.call("subscribe", {"channel": "ahp-root:/"}).get("snapshot") or {}).get("state") or {}
    try:
        link.call("unsubscribe", {"channel": "ahp-root:/"})
    except OSError:
        pass
    agent = ([a for a in root.get("agents") or [] if a.get("provider") == "copilotcli"] or [{}])[0]
    return agent.get("models") or []


class Host:
    def __init__(self, code):
        self.code = code
        for folder in ("user", "cli", "server", "work"):
            os.makedirs(os.path.join(HOME, folder), exist_ok=True)
        self.process = subprocess.Popen([code, "agent", "host", "--new-instance", "--foreground", "--server-data-dir", os.path.join(HOME, "server")] + dirs(),
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=clean_env(), creationflags=FLAGS)
        self.lines = []
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for raw in iter(self.process.stdout.readline, b""):
            line = scrub(raw.decode("utf-8", "replace").rstrip())
            self.lines.append(line)
            if "ownload" in line:
                print("      host: " + line[-160:], flush=True)

    def endpoint(self):
        start = time.time()
        while time.time() - start < WAIT and self.process.poll() is None:
            time.sleep(3)
            try:
                status, out, _ = run(self.code, ["agent", "endpoints"] + dirs())
                found = [e for e in (json.loads(out).get("endpoints") or []) if (e.get("endpoint") or {}).get("type") == "tcp"] if status == 0 and out.strip() else []
                if found:
                    return found[0], time.time() - start
            except (ValueError, OSError, subprocess.SubprocessError):
                pass
        return None, time.time() - start

    def stop(self):
        try:
            run(self.code, ["agent", "kill"] + dirs())
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            self.process.terminate()
            self.process.wait(timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass


def connect(endpoint):
    place = endpoint["endpoint"]
    link = Socket(place.get("host") or "127.0.0.1", int(place["port"]), str(endpoint.get("connectionToken") or ""))
    link.call("initialize", {"protocolVersions": ["1.1.0"], "clientId": str(uuid.uuid4())})
    return link


def sign_in(link, token):
    link.call("authenticate", {"resource": "https://api.github.com", "token": token})
    until, models = time.time() + 60, []
    while time.time() < until and not models:
        time.sleep(3)
        models = copilot_models(link)
    return models


def one_turn(link, models):
    real = [m for m in models if str(m.get("id", "")).lower() != "auto"] or models
    pick = next((m for m in real if "haiku" in str(m.get("id", "")).lower()), real[0])
    session = "ahp-session:/" + str(uuid.uuid4())
    path = os.path.join(HOME, "work").replace("\\", "/")
    work = "file://" + urllib.parse.quote(path if path.startswith("/") else "/" + path, safe="/:")
    link.call("createSession", {"channel": session, "provider": "copilotcli", "workingDirectories": [work],
                                "config": {"isolation": "folder", "mode": "interactive", "autoApprove": "autoApprove"}})
    state = (link.call("subscribe", {"channel": session}).get("snapshot") or {}).get("state") or {}
    chat = str(state.get("defaultChat") or "")
    link.call("subscribe", {"channel": chat})
    message = {"text": "Reply with the single word: pong. Use no tools.", "origin": {"kind": "user"}, "model": {"id": pick["id"]}}
    started = time.time()
    link.counter += 1
    link.send({"jsonrpc": "2.0", "method": "dispatchAction", "params": {"channel": chat, "clientSeq": link.counter, "action": {
        "type": "chat/turnStarted", "turnId": str(uuid.uuid4()), "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "message": message}}})
    text, end = "", None
    while time.time() - started < 180 and end is None:
        for action in chat_actions(link.read()):
            part = action.get("part") if action["type"] == "chat/responsePart" else None
            if isinstance(part, dict) and part.get("kind") == "markdown":
                text += str(part.get("content") or "")
            if action["type"] == "chat/delta":
                text += str(action.get("content") or "")
            if action["type"] in ("chat/turnComplete", "chat/error", "chat/turnCancelled"):
                end = action
    if end is None:
        return False, "no end of turn in 180 s (model %s)" % pick["id"]
    if end["type"] != "chat/turnComplete":
        return False, "%s: %s" % (end["type"], scrub(json.dumps(end.get("error") or end.get("part") or end))[:400])
    return True, "turn complete in %.1f s with %s, reply %r" % (time.time() - started, pick["id"], text.strip()[:40])


def host_log_lines():
    logs = [os.path.join(r, f) for r, _, fs in os.walk(HOME) for f in fs if f == "agenthost.log"]
    if not logs:
        return
    newest = max(logs, key=os.path.getmtime)
    with open(newest, encoding="utf-8", errors="replace") as handle:
        lines = [scrub(line.rstrip()) for line in handle if re.search(r"warn|error|models|token", line, re.I)]
    print("      host log %s, last lines about models and errors:" % newest)
    for line in lines[-12:]:
        print("        " + line[:260])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gh", help="path to gh.exe, when it is not in <home>/tools/gh/bin or on PATH")
    args = parser.parse_args()
    say(1, True, "Python %s, %s" % (sys.version.split()[0], sys.platform))
    for name in ("HTTPS_PROXY", "HTTP_PROXY"):
        if os.environ.get(name):
            print("      env %s is set" % name)

    gh = find_gh(args.gh)
    if not gh:
        say(2, False, "gh not found: give --gh <path to gh.exe>")
        return
    try:
        done = subprocess.run([gh, "--version"], capture_output=True, timeout=60, creationflags=FLAGS, stdin=subprocess.DEVNULL)
        say(2, done.returncode == 0, "gh runs: %s" % (done.stdout.decode("utf-8", "replace").splitlines() or ["?"])[0])
    except OSError as error:
        say(2, False, "gh does not run (%s): it may be blocked on this computer" % type(error).__name__)
        return
    token = gh_token(gh)
    say(3, bool(token), "gh is signed in (token kind %s)" % token.split("_")[0] if token else "gh is not signed in: run `gh auth login` first")
    if not token:
        return

    code = find_code()
    if not code:
        say(4, False, "the `code` command was not found: is VS Code installed?")
        return
    for round_ in ("first start", "after a host restart"):
        print("\n--- %s ---" % round_, flush=True)
        if round_ != "first start":
            token = gh_token(gh)  # read again, as the board would at its next start
        host = Host(code)
        try:
            endpoint, took = host.endpoint()
            say(4, endpoint is not None, "agent host ready in %.0f s" % took)
            if endpoint is None:
                for line in host.lines[-12:]:
                    print("      " + line[-200:])
                return
            link = connect(endpoint)
            say(5, True, "connected; before sign-in: %d Copilot models" % len(copilot_models(link)))
            try:
                models = sign_in(link, token)
            except OSError as error:
                say(6, False, "the host refused the token: %s" % " ".join(str(error).split())[:300])
                return
            ids = [str(m.get("id")) for m in models]
            say(6, bool(models) and ids != ["auto"], "after handing the gh token: %d Copilot models: %s" % (len(models), ", ".join(ids)[:300]))
            if not models or ids == ["auto"]:
                host_log_lines()
                return
            ok, text = one_turn(link, models)
            say(7, ok, text)
            if not ok:
                host_log_lines()
                return
        except OSError as error:
            say(5, False, "%s: %s" % (type(error).__name__, " ".join(scrub(str(error)).split())[:300]))
            return
        finally:
            host.stop()
    print("\nDone. The probe host is stopped. You may delete the folder %s" % HOME)


if __name__ == "__main__":
    main()
