"""What one file check, one folder listing, one file open and one program start cost on this computer.
Standard library only, Python 3.9+. Reads only; writes nothing inside the harness folder (the zip test uses the temp folder).

  python 2026-11-25-board-cost.py            the table (about one minute)
  python 2026-11-25-board-cost.py --stream   a page that holds one connection open for 10 minutes

Run it in the harness folder (the one that has .harness in it).
"""
import http.server
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path.cwd()
ENGINE = ROOT / ".harness" / "engine"
TASKS = ROOT / ".workspace" / "sandbox" / "tasks"


def ms(seconds):
    return "%8.3f ms" % (seconds * 1000.0)


def files_and_folders(limit=400):
    files, folders = [], []
    for base in (TASKS, ENGINE):
        for here, names, found in os.walk(str(base)):
            names[:] = [name for name in names if name != "__pycache__"]
            folders.append(here)
            files.extend(os.path.join(here, name) for name in found[:20])
            if len(files) >= limit and len(folders) >= 60:
                break
    return files[:limit], folders[:120]


def each(fn, items, rounds):
    """Median seconds of one call: `rounds` passes over the items, the first pass apart (it may be the slow one)."""
    first, rest = [], []
    for number in range(rounds):
        for item in items:
            began = time.perf_counter()
            try:
                fn(item)
            except OSError:
                continue
            (first if number == 0 else rest).append(time.perf_counter() - began)
    return (statistics.median(first) if first else 0.0, statistics.median(rest) if rest else 0.0, max(rest) if rest else 0.0, len(first) + len(rest))


def read_some(path):
    with open(path, "rb") as handle:
        handle.read(4096)


def start(args, times=5, env=None):
    """Median seconds to start a program and wait for it; None when it does not run."""
    spent = []
    for _ in range(times):
        began = time.perf_counter()
        try:
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, env=env, cwd=str(ROOT))
        except (OSError, subprocess.SubprocessError):
            return None
        spent.append(time.perf_counter() - began)
    return statistics.median(spent)


def modules_of(code):
    try:
        out = subprocess.run([sys.executable, "-c", "import sys; n=len(sys.modules); " + code + "; print(len(sys.modules)-n)"], capture_output=True, text=True, timeout=120, cwd=str(ROOT))
        return out.stdout.strip().splitlines()[-1] if out.returncode == 0 and out.stdout.strip() else "failed"
    except (OSError, subprocess.SubprocessError):
        return "failed"


def zip_test():
    """The same import from the folder and from one zip of compiled files: does opening one file instead of many help here?"""
    work = Path(tempfile.mkdtemp(prefix="harness-cost-"))
    try:
        copy = work / "engine"
        shutil.copytree(str(ENGINE), str(copy), ignore=shutil.ignore_patterns("__pycache__", "web", "*.json", "*.md"))
        subprocess.run([sys.executable, "-m", "compileall", "-b", "-q", str(copy)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        packed = work / "engine.zip"
        with zipfile.ZipFile(str(packed), "w", zipfile.ZIP_STORED) as out:
            for found in copy.rglob("*.pyc"):
                out.write(str(found), str(found.relative_to(copy)).replace(os.sep, "/"))
        want = "import core.paths, core.state, core.config, core.tasks"
        folder = start([sys.executable, "-S", "-c", "import sys; sys.path.insert(0, r'%s'); %s" % (ENGINE, want)])
        zipped = start([sys.executable, "-S", "-c", "import sys; sys.path.insert(0, r'%s'); %s" % (packed, want)])
        return folder, zipped
    except Exception as error:  # noqa: BLE001 - a side test: say why and go on
        return None, str(error)[:60]
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def table():
    if not ENGINE.is_dir():
        print("Run this in the harness folder (no .harness/engine here).")
        return 2
    files, folders = files_and_folders()
    print("Python %s on %s; %d files, %d folders sampled" % (sys.version.split()[0], sys.platform, len(files), len(folders)))
    print("")
    print("%-34s %12s %12s %12s" % ("one call", "first pass", "later", "slowest"))
    for name, fn, items, rounds in (("file check (os.stat)", os.stat, files, 5), ("folder listing (os.listdir)", os.listdir, folders, 5), ("open a file and read 4 KB", read_some, files, 3)):
        first, later, worst, count = each(fn, items, rounds)
        print("%-34s %12s %12s %12s   (%d calls)" % (name, ms(first), ms(later), ms(worst), count))
    print("")
    print("%-52s %12s" % ("start a program and wait for it (median of 5)", "time"))
    tiny = ["hostname"] if shutil.which("hostname") else (["cmd", "/c", "exit"] if os.name == "nt" else ["true"])
    hook = "import sys; sys.path.insert(0, r'%s'); import hook" % ENGINE
    cli = "import sys; sys.path.insert(0, r'%s'); import cli" % ENGINE
    rows = (
        ("a tiny native program (%s)" % tiny[0], tiny),
        ("python -S -c pass", [sys.executable, "-S", "-c", "pass"]),
        ("python -c pass", [sys.executable, "-c", "pass"]),
        ("python: import hook (what a hook loads)", [sys.executable, "-c", hook]),
        ("python: import cli (what a harness command loads)", [sys.executable, "-c", cli]),
    )
    for name, args in rows:
        spent = start(args)
        print("%-52s %12s" % (name, "did not run" if spent is None else ms(spent)))
    print("%-52s %12s" % ("modules loaded by import hook", modules_of(hook)))
    print("%-52s %12s" % ("modules loaded by import cli", modules_of(cli)))
    folder, zipped = zip_test()
    print("")
    print("the same four modules, from the folder and from one zip")
    print("%-52s %12s" % ("from the folder", "failed" if folder is None else ms(folder)))
    print("%-52s %12s" % ("from one zip", zipped if isinstance(zipped, str) else ("failed" if zipped is None else ms(zipped))))
    return 0


PAGE = """<!doctype html><meta charset="utf-8"><title>stream check</title>
<body style="font:16px system-ui;margin:40px"><h2>One connection, 10 minutes</h2>
<p>Leave this page open. A line comes every 5 seconds.</p>
<pre id="o" style="font-size:20px">starting</pre>
<script>
const o = document.getElementById("o"); let got = 0, late = 0, worst = 0, breaks = 0, last = performance.now(), began = Date.now();
function show(state) { o.textContent = state + "\\nlines: " + got + " of 120\\nlate lines (over 7 s): " + late + "\\nlongest gap: " + (worst / 1000).toFixed(1) + " s\\nbreaks: " + breaks + "\\nminutes: " + ((Date.now() - began) / 60000).toFixed(1); }
async function run() {
  try {
    const answer = await fetch("/stream", {method: "POST", headers: {"X-Check": "1"}});
    const reader = answer.body.getReader();
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      const now = performance.now(), gap = now - last; last = now;
      const lines = new TextDecoder().decode(part.value).split("\\n").filter(Boolean).length;
      got += lines; if (gap > 7000) late += 1; if (gap > worst) worst = gap;
      show("running");
    }
    show(got >= 120 ? "DONE: the connection held" : "ENDED EARLY");
  } catch (error) { breaks += 1; show("BROKEN: " + error); }
}
run();
</script>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_GET(self):  # noqa: N802
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            for number in range(120):
                self.wfile.write((json.dumps({"t": "beat", "n": number}) + "\n").encode("utf-8"))
                self.wfile.flush()
                time.sleep(5)
        except OSError:
            return


def stream():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print("Open this address in the browser you use for the board, leave it 10 minutes, then take a photo of the page:")
    print("  http://127.0.0.1:%d/" % server.server_address[1])
    print("Press Ctrl+C here when done.")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(stream() if "--stream" in sys.argv else table())
