# Can Copilot run hooks inside a long-lived extension on this computer? Looks only, changes nothing.
# Prints versions, yes/no and counts; paths under the home folder start with ~.
import glob
import mmap
import os
import re
import shutil
import sys

HOME = os.path.expanduser("~")
BLOCKED = b"Standalone extensions are prohibited by managed policy"


def short(path):
    return "~" + path[len(HOME):] if path.startswith(HOME) else path


def version(app):
    for name in ("package.json", "product.json"):
        try:
            with open(os.path.join(app, name), encoding="utf-8") as f:
                found = re.search(r'"version"\s*:\s*"([^"]+)"', f.read())
            if found:
                return found.group(1)
        except OSError:
            pass
    return "?"


def apps():
    """Folders that hold a VS Code build: the editor, and the servers `code agent host` downloads."""
    roots = []
    code = shutil.which("code")
    if code:
        roots.append(os.path.dirname(os.path.dirname(os.path.realpath(code))))
    for env, rest in (("LOCALAPPDATA", r"Programs\Microsoft VS Code"), ("ProgramFiles", "Microsoft VS Code")):
        if os.environ.get(env):
            roots.append(os.path.join(os.environ[env], rest))
    roots.append("/Applications/Visual Studio Code.app/Contents/Resources/app")
    found = []
    for root in roots:
        for pattern in ("", "resources/app", "*/resources/app"):
            for app in glob.glob(os.path.join(root, pattern)):
                if os.path.isfile(os.path.join(app, "product.json")) and os.path.isdir(os.path.join(app, "out")):
                    found.append(("editor", app))
    for app in glob.glob(os.path.join(HOME, ".vscode*", "cli", "servers", "*", "server")):
        found.append(("agent host", app))
    seen, out = set(), []
    for kind, app in found:
        key = os.path.normcase(os.path.realpath(app))
        if key not in seen:
            seen.add(key)
            out.append((kind, app))
    return out


def has_bytes(path, needle):
    try:
        with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            return m.find(needle) >= 0
    except (OSError, ValueError):
        return False


def sdk_files(app, tail):
    hits = []
    for top in ("node_modules", "node_modules.asar.unpacked"):
        hits += glob.glob(os.path.join(app, top, "*", "copilot-sdk-*", *tail))
    return hits


print("== 1. VS Code builds on this computer ==")
print("python", sys.version.split()[0], "| code on PATH:", short(shutil.which("code") or "no"))
listed = apps()
if not listed:
    print("no VS Code build found")
for kind, app in listed:
    docs = sdk_files(app, ("copilot-sdk", "docs", "extensions.md"))
    host = os.path.join(app, "out", "vs", "platform", "agentHost", "node", "agentHostMain.js")
    gate = "no file"
    if os.path.isfile(host):
        with open(host, encoding="utf-8", errors="replace") as f:
            gate = str(f.read().count("canvasesEnabled"))
    runtimes = sdk_files(app, ("prebuilds", "*", "runtime.node"))
    policy = "yes" if any(has_bytes(r, BLOCKED) for r in runtimes) else ("no" if runtimes else "no file")
    print("")
    print("[%s] %s" % (kind, short(app)))
    print("  version                         :", version(app))
    print("  extensions.md in the Copilot SDK:", "yes" if docs else "no")
    print("  canvasesEnabled in agent host   :", gate)
    print("  runtime knows the policy block  :", policy)

print("")
print("== 2. Policy lines in the newest Copilot logs ==")
logs = sorted(glob.glob(os.path.join(HOME, ".copilot", "logs", "*.log")), key=os.path.getmtime, reverse=True)[:8]
if not logs:
    print("no log in ~/.copilot/logs")
lines, counts = [], {"prohibited by managed policy": 0, "Extension managed policy is unresolved": 0, "importing extension": 0}
for path in logs:
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            for key in counts:
                if key in line:
                    counts[key] += 1
            if "[managedSettings]" in line:
                text = line.split("[managedSettings]", 1)[1].strip()
                text = re.sub(r"https?://[^\s,)]+", "<address>", text)  # no host or account names
                text = re.sub(r"\d+", "#", text)[:300]
                if text not in lines:
                    lines.append(text)
print("logs read:", len(logs), "| newest:", short(logs[0]) if logs else "-")
for text in lines[:12]:
    print("  managedSettings:", text)
for key, n in counts.items():
    print("  lines with '%s': %d" % (key, n))
