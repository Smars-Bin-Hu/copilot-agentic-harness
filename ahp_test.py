"""AHP test, Python standard library only. Never prints the connection token.
  python ahp_test.py               read only: connect, list the 5 newest sessions
  python ahp_test.py send <id>     send one test message to that session (the id, or its first 8 characters)
"""
import base64, datetime, json, os, socket, struct, subprocess, sys, threading, traceback, uuid


def code(arguments):
    return json.loads(subprocess.check_output("code agent " + arguments, shell=True))


class Pipe:
    def __init__(self, path):
        self.file = open(path, "r+b", buffering=0)  # a Windows named pipe

    def read(self, size):
        return self.file.read(size)

    def write(self, data):
        self.file.write(data)


class Unix:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.connect(path)

    def read(self, size):
        return self.sock.recv(size)

    def write(self, data):
        self.sock.sendall(data)


class Ahp:
    def __init__(self):
        items = code("endpoints")["endpoints"]
        print("endpoints:", [item.get("type") for item in items])
        found = [item for item in items if item.get("type") == "editor"]
        if not found:
            sys.exit("no editor endpoint: is VS Code open?")
        print("field names:", sorted(found[0]), sorted(found[0]["endpoint"]))
        path = found[0]["endpoint"]["path"]
        print("endpoint kind:", "named pipe" if path.startswith("\\\\") else "unix socket", "| path starts:", path[:24])
        self.link = (Pipe if path.startswith("\\\\") else Unix)(path)
        self.buf = b""
        self.next = 0
        key = base64.b64encode(os.urandom(16)).decode()
        self.link.write(("GET /?tkn=%s HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (found[0]["connectionToken"], key)).encode())
        while b"\r\n\r\n" not in self.buf:
            self.buf += self.link.read(1) if isinstance(self.link, Pipe) else self.link.read(4096)
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        print("upgrade:", head.split(b"\r\n")[0].decode())

    def send(self, message):
        data = json.dumps(message).encode()
        mask, size = os.urandom(4), len(data)
        if size < 126:
            head = b"\x81" + bytes([0x80 | size])
        elif size < 65536:
            head = b"\x81" + bytes([0x80 | 126]) + struct.pack(">H", size)
        else:
            head = b"\x81" + bytes([0x80 | 127]) + struct.pack(">Q", size)
        self.link.write(head + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(data)))

    def need(self, size):
        while len(self.buf) < size:
            data = self.link.read(size - len(self.buf) if isinstance(self.link, Pipe) else 65536)
            if not data:
                raise EOFError("the host closed the connection")
            self.buf += data

    def take(self, size):
        self.need(size)
        data, self.buf = self.buf[:size], self.buf[size:]
        return data

    def recv(self):
        parts = b""
        while True:
            first, second = self.take(2)
            size = second & 127
            if size == 126:
                size = struct.unpack(">H", self.take(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self.take(8))[0]
            body = self.take(size)
            kind = first & 15
            if kind == 9:  # a ping asks for a pong
                mask = os.urandom(4)
                self.link.write(bytes([0x8A, 0x80 | len(body)]) + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(body)))
                continue
            if kind == 10:
                continue
            if kind == 8:
                raise EOFError("the host closed the connection")
            parts += body
            if first & 128:
                return json.loads(parts)

    def call(self, method, params):
        self.next += 1
        me = self.next
        self.send({"jsonrpc": "2.0", "id": me, "method": method, "params": params})
        while True:
            message = self.recv()
            if message.get("id") == me:
                if "error" in message:
                    sys.exit("%s failed: %s" % (method, message["error"]))
                return message["result"]

    def hello(self):
        answer = self.call("initialize", {"protocolVersions": ["1.1.0"], "clientId": str(uuid.uuid4()), "clientInfo": {"name": "harness-test", "version": "0"}})
        print("protocol:", answer["protocolVersion"])


def sessions():
    rows = [row for host in code("ps --all --json") for row in host["sessions"]]
    return sorted(rows, key=lambda row: row.get("modifiedAt", ""), reverse=True)


def listing():
    Ahp().hello()
    rows = sessions()
    print(len(rows), "sessions; newest:")
    for row in rows[:5]:
        print(" ", row["resource"].rsplit("/", 1)[-1], row.get("status"), row.get("provider"), row.get("title", "")[:40])


def send(wanted, text="This is a harness test. Reply with exactly: outside message received. Do not use any tools."):
    match = [row for row in sessions() if row["resource"].rsplit("/", 1)[-1].startswith(wanted)]
    if len(match) != 1:
        sys.exit("expected one session, found %d" % len(match))
    session = match[0]["resource"]
    link = Ahp()
    link.hello()
    state = link.call("subscribe", {"channel": session})["snapshot"]["state"]
    chat = state["defaultChat"]
    print("title:", state.get("title"), "| status:", state.get("status"))
    if not state.get("status", 0) & 1:
        sys.exit("the session is not idle: nothing sent")
    link.call("subscribe", {"channel": chat})
    started = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    link.send({"jsonrpc": "2.0", "method": "dispatchAction", "params": {"channel": chat, "clientSeq": 1, "action": {
        "type": "chat/turnStarted", "turnId": str(uuid.uuid4()), "startedAt": started, "message": {"text": text, "origin": {"kind": "user"}}}}})
    print("sent; waiting up to 120 s")
    while True:
        action = (link.recv().get("params") or {}).get("action") or {}
        if action.get("type") in ("chat/turnComplete", "chat/turnCancelled", "chat/error"):
            print("end:", action["type"])
            break
    turn = link.call("subscribe", {"channel": chat})["snapshot"]["state"]["turns"][-1]
    print("reply:", [part.get("content", "")[:200] for part in turn["responseParts"] if part.get("kind") == "markdown"])


if __name__ == "__main__":
    print("python", sys.version.split()[0], sys.platform, flush=True)
    threading.Timer(150, lambda: (print("timed out", flush=True), os._exit(1))).start()
    result = 1
    try:
        send(sys.argv[2]) if sys.argv[1:2] == ["send"] else listing()
        result = 0
    except SystemExit as stop:
        print("stopped:", stop.code)
    except BaseException:
        traceback.print_exc(file=sys.stdout)
    finally:
        print("finished, exit code", result)
        sys.stdout.flush()
        os._exit(result)
