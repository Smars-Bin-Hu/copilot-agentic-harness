"""Probe: can VS Code's own agent host run here with no editor window, and can a plain client reach it?

    python agent-host-probe.py

Standard library only (Python 3.9+). It starts `code agent host` in its own folder
(<home>/agent-host-probe), connects, reads what the host offers, then stops that host.
It needs no sign-in and sends no token. It never prints the host's connection secret.
An editor that is open is not touched: the probe host has its own folders.
"""
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid

HOME = os.environ.get("AGENT_HOST_PROBE_HOME") or os.path.join(os.path.expanduser("~"), "agent-host-probe")
WAIT = 300  # the first start downloads a server package


def say(step, ok, text):
    print("[%s] %s  %s" % (step, "OK  " if ok else "FAIL", text), flush=True)


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
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    done = subprocess.run([code] + arguments, capture_output=True, timeout=timeout, env=clean_env(), creationflags=flags, stdin=subprocess.DEVNULL)
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


class Socket:
    """A small WebSocket client: text frames, one JSON-RPC message a frame."""

    def __init__(self, host, port, token):
        self.sock = socket.create_connection((host, port), timeout=30)
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
        line = head.split(b"\r\n")[0].decode("latin-1")
        if " 101" not in line:
            raise OSError("the host refused the upgrade: " + line[:60])
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
        head = bytes([0x80 | opcode])
        size = len(data)
        head += bytes([0x80 | size]) if size < 126 else (bytes([0x80 | 126]) + struct.pack(">H", size) if size < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", size))
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

    def call(self, method, params):
        self.counter += 1
        mine = self.counter
        self._frame(1, json.dumps({"jsonrpc": "2.0", "id": mine, "method": method, "params": params}).encode())
        while True:
            message = self.read()
            if message.get("id") == mine:
                if "error" in message:
                    raise OSError("%s: %s" % (method, json.dumps(message["error"])[:300]))
                return message.get("result") or {}


def main():
    say(1, True, "Python %s, %s" % (sys.version.split()[0], sys.platform))
    code = find_code()
    if not code:
        say(2, False, "the `code` command was not found: is VS Code installed?")
        return
    status, out, _ = run(code, ["--version"])
    say(2, status == 0, "VS Code %s at %s" % ((out.split() or ["?"])[0], code))
    for name in ("HTTPS_PROXY", "HTTP_PROXY"):
        if os.environ.get(name):
            print("      env %s is set" % name)

    for folder in ("user", "cli", "server"):
        os.makedirs(os.path.join(HOME, folder), exist_ok=True)
    arguments = ["agent", "host", "--new-instance", "--foreground", "--server-data-dir", os.path.join(HOME, "server")] + dirs()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    start = time.time()
    host = subprocess.Popen([code] + arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=clean_env(), creationflags=flags)
    lines = []

    def pump():
        for raw in iter(host.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if "tkn=" in line:
                line = line.split("tkn=")[0] + "tkn=***"
            lines.append(line)
            if "ownload" in line or "rror" in line or "ready in" in line:
                print("      host: " + line[-160:], flush=True)

    threading.Thread(target=pump, daemon=True).start()
    endpoint = None
    try:
        while time.time() - start < WAIT and host.poll() is None and endpoint is None:
            time.sleep(3)
            try:
                status, out, _ = run(code, ["agent", "endpoints"] + dirs(), timeout=60)
                found = [e for e in (json.loads(out).get("endpoints") or []) if (e.get("endpoint") or {}).get("type") == "tcp"] if status == 0 and out.strip() else []
                endpoint = found[0] if found else None
            except (ValueError, OSError, subprocess.SubprocessError):
                pass
        if endpoint is None:
            say(3, False, "no agent host after %.0f s (exit code %s). Its last lines:" % (time.time() - start, host.poll()))
            for line in lines[-12:]:
                print("      " + line[-200:])
            return
        say(3, True, "agent host started with no editor window in %.0f s (kind %s, protocol %s)" % (time.time() - start, endpoint.get("type"), endpoint.get("protocolVersion")))

        place = endpoint["endpoint"]
        try:
            link = Socket(place.get("host") or "127.0.0.1", int(place["port"]), str(endpoint.get("connectionToken") or ""))
            hello = link.call("initialize", {"protocolVersions": ["1.1.0"], "clientId": str(uuid.uuid4())})
            say(4, True, "connected; the host speaks protocol %s" % hello.get("protocolVersion"))
            root = ((link.call("subscribe", {"channel": "ahp-root:/"}).get("snapshot") or {}).get("state")) or {}
            agents = root.get("agents") or []
            for agent in agents:
                needs = [r.get("resource_name") for r in (agent.get("protectedResources") or []) if r.get("required")]
                print("      agent %s: %d models, sign-in required for: %s" % (agent.get("provider"), len(agent.get("models") or []), ", ".join(needs) or "nothing"))
            copilot = [a for a in agents if a.get("provider") == "copilotcli"]
            say(5, bool(copilot), "the Copilot agent is offered: %s (0 models is right here: nobody signed in)" % bool(copilot))
        except (OSError, ValueError, KeyError) as error:
            say(4, False, "%s: %s" % (type(error).__name__, " ".join(str(error).split())[:300]))
    finally:
        try:
            status, out, err = run(code, ["agent", "kill"] + dirs(), timeout=60)
            print("      stop: " + ((out + err).strip().splitlines() or ["(no answer)"])[-1][:160])
        except (OSError, subprocess.SubprocessError) as error:
            print("      stop failed: %s" % type(error).__name__)
        try:
            host.terminate()
        except OSError:
            pass
    print("Done. You may delete the folder %s" % HOME)


if __name__ == "__main__":
    main()
