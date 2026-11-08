"""What VS Code needs at its start so that the agent's commands reach the tools of this computer (1.7.11).

The agent's terminal commands run in the editor's agent host, which has the environment VS Code was started with: a setting of the editor's terminals
does not reach them. So two things are given when the board opens VS Code (`extra`), never later:

  tool folders  `HARNESS_TOOL_PATH` in `.harness/.env`: folders put before PATH (a tool unpacked under the person's own folder, where PATH cannot be
                changed without an administrator).
  CA bundle     `.harness/certs/ca-bundle.pem`, made here (`make`): the public roots a Python tool ships with (`certifi`), and the certificates of
                the chain this computer builds for an outside address, through the proxy when there is one. A proxy that inspects TLS signs
                with the company's own CA: the system trusts it, a tool with its own list of roots does not. The file is named by the variables
                in `TRUST_VARS` (and by those a tool pack asks for, later). `HARNESS_CA_HOST` and `HARNESS_CA_PROXY` keep what it was made with.

Nothing here is a secret; it sits in `.harness/.env` beside the identities because `reinstall` carries that file, and the gate keeps the agent from it.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import messages
from . import connections as conn_core
from .paths import utc_now

PATH_KEY = "HARNESS_TOOL_PATH"
BUNDLE_KEY = "HARNESS_CA_BUNDLE"
HOST_KEY = "HARNESS_CA_HOST"
PROXY_KEY = "HARNESS_CA_PROXY"
MADE_KEY = "HARNESS_CA_MADE"
MCP_KEY = "HARNESS_MCP"  # allowed | blocked (1.7.17): may tool packs add MCP servers to VS Code here? Blocked unless the person says otherwise
BUNDLE = Path(".harness") / "certs" / "ca-bundle.pem"
RECIPE = ".harness/policies/computer.company.json"  # 1.7.31: from `company/tools/computer.json`; what every colleague's computer needs and holds no secret
RECIPE_SCHEMA = {"type": "object", "properties": {
    "ca_bundle": {"type": "object", "properties": {
        "host": {"type": "string", "pattern": r"^[A-Za-z0-9.\-]+(:\d{1,5})?$", "maxLength": 260},
        "proxy": {"type": "string", "pattern": r"^[A-Za-z0-9.\-\[\]:]+:\d{1,5}$", "maxLength": 260}}},
    "tool_folders": {"type": "array", "maxItems": 20, "items": {"type": "object", "required": ["label"], "properties": {
        "label": {"type": "string", "minLength": 1, "maxLength": 80}, "hint": {"type": "string", "maxLength": 400},
        "program": {"type": "string", "pattern": r"^[\w.\-]+$", "maxLength": 60}}}}}}
TRUST_VARS = ("REQUESTS_CA_BUNDLE",)  # Python tools (az, pip's requests); NODE_EXTRA_CA_CERTS and others when a tool pack asks for them
DEFAULT_HOST = "example.com"
HTTPS_PORT = 443
HOST_FORM = re.compile(r"^([A-Za-z0-9.\-]+)(?::(\d{1,5}))?$")  # `host`, or `host:port` for a server that is not on 443 (1.7.38)


def split_host(value: str) -> Tuple[str, int]:
    """`(host, port)` of `host` or `host:port`; the port is 443 when none is written. ValueError for anything else."""
    found = HOST_FORM.match(value.strip())
    port = int(found.group(2)) if found and found.group(2) else HTTPS_PORT
    if not found or not 0 < port < 65536:
        raise ValueError(value)
    return found.group(1), port
SECONDS = 20
PEM = re.compile(r"-----BEGIN CERTIFICATE-----\s+([A-Za-z0-9+/=\s]+?)\s+-----END CERTIFICATE-----")
ROOTS_SEARCH_DEPTH = 8  # certifi/cacert.pem sits a few folders down in a tool's own Python


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


# --- what is kept ---------------------------------------------------------------------------------------------------------------------------------------------

def settings(root: Path) -> Dict[str, Any]:
    env = conn_core.read_env(root)
    return {"paths": [item for item in env.get(PATH_KEY, "").split(os.pathsep) if item], "bundle": env.get(BUNDLE_KEY, ""), "host": env.get(HOST_KEY, ""),
            "proxy": env.get(PROXY_KEY, ""), "made": env.get(MADE_KEY, "")}


def mcp_allowed(root: Path) -> bool:
    return conn_core.read_env(root).get(MCP_KEY, "") == "allowed"


def detect_mcp() -> str:
    """What this computer's VS Code says about MCP, when it says it: "blocked" (an organization policy or the person's setting turns MCP off), else ""."""
    found: List[Any] = []
    if os.name == "nt":
        try:
            import winreg  # noqa: PLC0415 - Windows only

            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\Policies\Microsoft\VSCode") as key:
                        index = 0
                        while True:
                            try:
                                name, value, _kind = winreg.EnumValue(key, index)
                            except OSError:
                                break
                            if "mcp" in name.lower():
                                found.append(value)
                            index += 1
                except OSError:
                    continue
        except ImportError:
            pass
    settings = Path(os.environ.get("APPDATA", "")) / "Code" / "User" / "settings.json" if os.name == "nt" else Path.home() / ("Library/Application Support" if sys.platform == "darwin" else ".config") / "Code" / "User" / "settings.json"
    try:
        text = settings.read_text(encoding="utf-8")
        for key in ("chat.mcp.access", "chat.mcp.enabled"):
            hit = re.search(r'"' + re.escape(key) + r'"\s*:\s*("?)([\w-]+)\1', text)
            if hit:
                found.append(hit.group(2))
    except OSError:
        pass
    return "blocked" if any(str(value).lower() in ("none", "false", "0", "disabled") for value in found) else ""


def set_mcp(root: Path, allowed: bool) -> Dict[str, Any]:
    """The person says whether MCP may be used here; the tool packs' MCP servers are added to `.vscode/mcp.json`, or taken out (core.toolpacks)."""
    from . import toolpacks  # it reads this module

    conn_core.write_env(root, {MCP_KEY: "allowed" if allowed else "blocked"})
    return toolpacks.apply_mcp(root)


def bundle_path(root: Path) -> Optional[Path]:
    """The bundle that is kept, when it is there. Kept as a path inside the copy, so that `reinstall` carries it with `.harness/certs/`."""
    kept = settings(root)["bundle"]
    found = (root / kept) if kept and not Path(kept).is_absolute() else Path(kept) if kept else None
    return found if found and found.is_file() else None


def programs_in(folder: Path) -> List[str]:
    """The programs a folder holds, as PATH would find them (a few names, for the person to see it is the right folder)."""
    if not folder.is_dir():
        return []
    wanted = {".exe", ".cmd", ".bat", ".ps1"} if os.name == "nt" else None
    found = []
    for item in sorted(folder.iterdir()):
        if not item.is_file():
            continue
        if (wanted is not None and item.suffix.lower() in wanted) or (wanted is None and os.access(item, os.X_OK)):
            found.append(item.name)
    return found


def save_paths(root: Path, raw: List[str]) -> Dict[str, Any]:
    """Keep the tool folders. Each must be a folder that holds a program: a wrong line is refused, not kept."""
    paths: List[str] = []
    for item in raw:
        text = str(item).strip().strip('"')
        if not text or text in paths:
            continue
        folder = Path(os.path.expandvars(os.path.expanduser(text)))
        if not folder.is_absolute():
            raise ValueError(say("launch.path.relative", path=text))
        if not folder.is_dir():
            raise ValueError(say("launch.path.none", path=text))
        if not programs_in(folder):
            raise ValueError(say("launch.path.empty", path=text))
        paths.append(str(folder))
    conn_core.write_env(root, {PATH_KEY: os.pathsep.join(paths) or None})
    return {"paths": paths}


def add_folder(root: Path, program: str, raw: str) -> Dict[str, Any]:
    """"I installed it here" (1.7.37): add the folder to `HARNESS_TOOL_PATH` when it holds `program`, so the next check finds it. A folder without it is refused."""
    text = str(raw).strip().strip('"')
    folder = Path(os.path.expandvars(os.path.expanduser(text)))
    if not text or not folder.is_absolute():
        raise ValueError(say("launch.path.relative", path=text or "-"))
    if not folder.is_dir():
        raise ValueError(say("launch.path.none", path=text))
    if not shutil.which(program, path=str(folder)):
        raise ValueError(say("launch.path.noprogram", program=program, path=text))
    return save_paths(root, settings(root)["paths"] + [str(folder)])


def _program_rows(root: Path) -> List[Dict[str, Any]]:
    """The Programs block (1.7.37): one row per program a tool pack that is on needs, and who needs it; `python` first. Found on the PATH VS Code will get, with the place;
    a program not found carries the company recipe's hint for it, when there is one."""
    from . import toolpacks

    path = next((value for key, value in extra(root).items() if key.upper() == "PATH"), None)
    hints = {item["program"]: item for item in recipe(root)["tool_folders"] if item.get("program")}
    wanted: Dict[str, List[Dict[str, str]]] = {}
    for pack, rows in toolpacks.needs_report(root).items():
        for row in rows:
            who = {"pack": pack, "why": "signin" if row["why"].startswith("signin:") else "pack", "conn": row["why"][7:] if row["why"].startswith("signin:") else ""}
            if who not in wanted.setdefault(row["program"], []):
                wanted[row["program"]].append(who)
    python = shutil.which("python3", path=path) or shutil.which("python", path=path) or sys.executable
    out = [{"program": "python", "found": bool(python), "path": python or "", "needed_by": [{"pack": "harness", "why": "pack", "conn": ""}], "hint": "", "label": ""}]
    for program, who in sorted(wanted.items()):
        where = toolpacks.locate(program, path)
        hint = hints.get(program) or {}
        out.append({"program": program, "found": bool(where), "path": where, "blocked": "" if where else toolpacks.blocked(program, path), "needed_by": who, "hint": hint.get("hint", ""), "label": hint.get("label", "")})
    return out


def drop_bundle(root: Path) -> Dict[str, Any]:
    target = root / BUNDLE
    if target.is_file():
        target.unlink()
    conn_core.write_env(root, {BUNDLE_KEY: None, HOST_KEY: None, PROXY_KEY: None, MADE_KEY: None})
    return {"dropped": True}


# --- what VS Code is started with ---------------------------------------------------------------------------------------------------------------------------

def trusted_by(root: Path) -> List[str]:
    """The variables that name the bundle: Python's, and those an installed tool pack asks for for its own program (1.7.12)."""
    from . import toolpacks  # it reads this module for its checks

    return list(dict.fromkeys(list(TRUST_VARS) + toolpacks.trust_vars(root)))


def tool_folders(root: Path) -> List[str]:
    from . import toolpacks  # it reads this module

    return list(dict.fromkeys([item for item in settings(root)["paths"] if Path(item).is_dir()] + toolpacks.bin_folders(root)))  # a tool pack's own programs come with it (1.7.17)


def extra(root: Path, environ: Optional[Dict[str, str]] = None, trust_vars: Optional[Tuple[str, ...]] = None) -> Dict[str, str]:
    """The variables the board adds when it starts VS Code: PATH with the tool folders first, and each trust variable naming the bundle (when it is there)."""
    base = dict(os.environ if environ is None else environ)
    kept = settings(root)
    out: Dict[str, str] = {}
    from . import toolpacks  # it reads this module

    folders = tool_folders(root)
    if folders:
        key = next((name for name in base if name.upper() == "PATH"), "PATH")  # Windows writes `Path`
        rest = [item for item in base.get(key, "").split(os.pathsep) if item and item not in folders]
        out[key] = os.pathsep.join(folders + rest)
    bundle = bundle_path(root)
    if bundle:
        for name in (trust_vars if trust_vars is not None else trusted_by(root)):
            out[name] = str(bundle)
    return out


# --- what VS Code really got (1.7.21) ----------------------------------------------------------------------------------------------------------------------------

SEEN = Path(".harness") / "runtime" / "state" / "vscode-env.json"


def _same(one: str, other: str) -> bool:
    return os.path.normcase(os.path.normpath(one)) == os.path.normcase(os.path.normpath(other))


def lacking(root: Path, environ: Optional[Dict[str, str]] = None) -> List[str]:
    """What `extra` would give that this environment does not have: `PATH <folder>` for a tool folder not on the PATH, the name of a trust variable that does not name the bundle.
    Run by a hook, the environment is the one VS Code was started with: when it is not there, VS Code was started without the settings of this computer."""
    env = dict(os.environ if environ is None else environ)
    out: List[str] = []
    key = next((name for name in env if name.upper() == "PATH"), "PATH")
    on_path = [item for item in env.get(key, "").split(os.pathsep) if item]
    out.extend(f"PATH {folder}" for folder in tool_folders(root) if not any(_same(folder, item) for item in on_path))
    bundle = bundle_path(root)
    if bundle:
        out.extend(name for name in trusted_by(root) if not env.get(name) or not _same(env[name], str(bundle)))
    return out


def note_seen(root: Path, environ: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Called by the hook at the start of a chat: keep what this environment lacks. `{ok, missing, at}`."""
    found = {"ok": False, "missing": lacking(root, environ), "at": utc_now()}
    found["ok"] = not found["missing"]
    target = root / SEEN
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, target)
    return found


def seen(root: Path) -> Dict[str, Any]:
    """What the hook of the latest chat found: `{ok, missing, at}`; empty when no chat has told yet."""
    try:
        found = json.loads((root / SEEN).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def mark_started(root: Path) -> None:
    """The board starts VS Code itself, with the settings: what an older VS Code lacked no longer holds. The next chat's hook says what is true."""
    target = root / SEEN
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"ok": True, "missing": [], "at": utc_now(), "by": "board"}), encoding="utf-8")
    except OSError:
        pass


def vscode_running(run: Callable[..., Any] = subprocess.run, platform: str = sys.platform) -> bool:
    """Is a VS Code running on this computer? macOS and Linux: `pgrep`; Windows: one `tasklist`. A start that finds one running gives it no environment."""
    try:
        if platform.startswith("win"):
            done = run(["tasklist", "/FI", "IMAGENAME eq Code.exe", "/NH"], capture_output=True, text=True, timeout=10)
            return "Code.exe" in (done.stdout or "")
        pattern = "Visual Studio Code.app" if platform == "darwin" else "/code"
        return run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# --- the CA bundle ----------------------------------------------------------------------------------------------------------------------------------------------

def detect_proxy(environ: Optional[Dict[str, str]] = None) -> str:
    """`host:port` of the HTTPS proxy this computer names (the environment, then the system's own setting), or ""."""
    env = os.environ if environ is None else environ
    found = env.get("HTTPS_PROXY") or env.get("https_proxy") or ""
    if not found and environ is None:
        try:
            found = urllib.request.getproxies().get("https", "")
        except Exception:  # noqa: BLE001 - a setting we cannot read is no proxy
            found = ""
    return proxy_address(found)


def proxy_address(text: str) -> str:
    """`http://127.0.0.1:9000/` → `127.0.0.1:9000`; "" when it is not an address."""
    text = str(text or "").strip()
    text = re.sub(r"^[a-z]+://", "", text).split("/")[0].split("@")[-1]
    return text if re.match(r"^[A-Za-z0-9.\-\[\]:]+:\d{1,5}$", text) else ""


def pem_blocks(text: str) -> List[str]:
    """Each certificate of a PEM text, as one block with a line break every 64 characters."""
    out = []
    for body in PEM.findall(text or ""):
        flat = re.sub(r"\s+", "", body)
        out.append("-----BEGIN CERTIFICATE-----\n" + "\n".join(flat[i:i + 64] for i in range(0, len(flat), 64)) + "\n-----END CERTIFICATE-----\n")
    return out


def der_to_pem(der: bytes) -> str:
    return pem_blocks("-----BEGIN CERTIFICATE-----\n" + base64.b64encode(der).decode("ascii") + "\n-----END CERTIFICATE-----")[0]


def _key(block: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", "", block).encode("ascii")).hexdigest()


def merge(*groups: List[str]) -> List[str]:
    """The certificates of all groups, each once, in the order first seen."""
    seen, out = set(), []
    for group in groups:
        for block in group:
            if _key(block) not in seen:
                seen.add(_key(block))
                out.append(block)
    return out


def base_roots(paths: List[str]) -> Tuple[str, List[str]]:
    """The public roots to start from: a tool's own `certifi/cacert.pem` under a tool folder (the list that tool trusts today), else this Python's
    `certifi`, else the file this Python's OpenSSL reads. `(where, blocks)`; ("", []) when there is none."""
    for folder in paths:
        top = Path(folder).parent  # az's bin\ sits beside Lib\site-packages\certifi
        for found in _find(top, "cacert.pem", ROOTS_SEARCH_DEPTH):
            if found.parent.name == "certifi" and "_vendor" not in found.parts:  # pip's own copy is not the list the tool uses
                return str(found), pem_blocks(found.read_text(encoding="ascii", errors="ignore"))
    try:
        spec = importlib.util.find_spec("certifi")  # found, not imported: the engine needs no package beyond the standard library
    except (ImportError, ValueError):
        spec = None
    if spec and spec.origin and (Path(spec.origin).parent / "cacert.pem").is_file():
        where = Path(spec.origin).parent / "cacert.pem"
        return str(where), pem_blocks(where.read_text(encoding="ascii", errors="ignore"))
    cafile = ssl.get_default_verify_paths().cafile
    if cafile and Path(cafile).is_file():
        return cafile, pem_blocks(Path(cafile).read_text(encoding="ascii", errors="ignore"))
    return "", []


MAC_KEYCHAINS = ("/Library/Keychains/System.keychain", "/System/Library/Keychains/SystemRootCertificates.keychain")


def system_roots(platform: str = sys.platform, run: Callable[..., Any] = subprocess.run) -> List[str]:
    """The roots the system itself trusts, when a tool's list leaves them out: on a Mac the system keychains (a company's own root is put there by its
    device management). Windows needs none: the chain it builds ends in the root of its own store. Linux: the file OpenSSL reads has them already."""
    if platform != "darwin":
        return []
    try:
        done = run(["security", "find-certificate", "-a", "-p", *MAC_KEYCHAINS], capture_output=True, text=True, timeout=SECONDS)
    except (OSError, subprocess.SubprocessError):
        return []
    return pem_blocks(done.stdout or "")


def _find(top: Path, name: str, depth: int, budget: int = 20000):
    """Files called `name` under `top`, the shallowest first (a tool's own Python before one deep in a sub-environment), looking into at most `budget` folders."""
    level = [top] if top.is_dir() else []
    for _ in range(depth + 1):
        following = []
        for folder in level:
            budget -= 1
            if budget < 0:
                return
            try:
                items = sorted(folder.iterdir())
            except OSError:
                continue
            for item in items:
                if item.name == name and item.is_file():
                    yield item
                elif item.is_dir() and not item.is_symlink():
                    following.append(item)
        level = following


WINDOWS_CHAIN = r"""
$h = '__HOST__'; $port = __PORT__; $p = '__PROXY__'
$global:zchain = @(); $global:zerr = ''
$cb = [Net.Security.RemoteCertificateValidationCallback]{ param($s, $c, $ch, $e) $global:zerr = "$e"; $global:zchain = @($ch.ChainElements | ForEach-Object { $_.Certificate }); $true }
if ($p) { $hp = $p.Split(':'); $tcp = [Net.Sockets.TcpClient]::new($hp[0], [int]$hp[1]); $ns = $tcp.GetStream()
  $req = [Text.Encoding]::ASCII.GetBytes("CONNECT ${h}:${port} HTTP/1.1`r`nHost: ${h}:${port}`r`n`r`n"); $ns.Write($req, 0, $req.Length)
  $one = New-Object byte[] 1; $head = ''
  while (-not $head.EndsWith("`r`n`r`n")) { if ($ns.Read($one, 0, 1) -le 0) { break }; $head += [char]$one[0] }
  if ($head -notmatch '^HTTP/1\.[01] 2') { "PROXY " + ($head -split "`r`n")[0]; exit 3 } }
else { $tcp = [Net.Sockets.TcpClient]::new($h, $port); $ns = $tcp.GetStream() }
$ssl = [Net.Security.SslStream]::new($ns, $false, $cb); $ssl.AuthenticateAsClient($h); $tcp.Close()
"TRUST $zerr"
$zchain | ForEach-Object { "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($_.RawData, 'InsertLineBreaks') + "`n-----END CERTIFICATE-----" }
"""


def chain_windows(host: str, proxy: str, run: Callable[..., Any] = subprocess.run) -> Tuple[List[str], str]:
    """The chain Windows builds for `host`, through `proxy` when given (the root from the system's store included). `(blocks, trust)`: trust is
    "None" when Windows trusts it, else the reason (RemoteCertificateChainErrors, ...)."""
    # The values go into the script's text: `-Command <script> <args>` hands the script no $args. Both were checked to hold no quote (make, proxy_address).
    host, port = split_host(host)
    script = WINDOWS_CHAIN.replace("__HOST__", host).replace("__PORT__", str(port)).replace("__PROXY__", proxy)
    done = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=SECONDS,
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = done.stdout or ""
    found = re.search(r"^PROXY (.*)$", out, re.MULTILINE)
    if found:
        raise ValueError(say("launch.ca.proxy.refused", said=found.group(1).strip()))
    trust = re.search(r"^TRUST (.*)$", out, re.MULTILINE)
    blocks = pem_blocks(out)
    if not trust or not blocks:  # no chain read: say why, never "None" (the system trusted nothing it was shown)
        raise ValueError(say("launch.ca.chain.failed", said=((done.stderr or out).strip().splitlines() or ["-"])[-1][:300]))
    return blocks, trust.group(1).strip() or "None"


def chain_openssl(host: str, proxy: str, run: Callable[..., Any] = subprocess.run) -> Tuple[List[str], str]:
    """The chain the server (or the proxy in its place) sends, read with `openssl s_client`. It may stop before the root: the root comes from the
    system's own list then."""
    program = shutil.which("openssl")
    if not program:
        raise ValueError(say("launch.ca.no_openssl"))
    host, port = split_host(host)
    argv = [program, "s_client", "-showcerts", "-servername", host, "-connect", f"{host}:{port}"] + (["-proxy", proxy] if proxy else [])
    done = run(argv, input="", capture_output=True, text=True, timeout=SECONDS)
    blocks = pem_blocks(done.stdout or "")
    if not blocks:
        raise ValueError(say("launch.ca.chain.failed", said=((done.stderr or "").strip().splitlines() or ["-"])[-1][:300]))
    verify = re.search(r"Verify return code: (\d+) \(([^)]*)\)", done.stdout or "")
    return blocks, ("None" if verify and verify.group(1) == "0" else (verify.group(2) if verify else "?"))


def chain(host: str, proxy: str) -> Tuple[List[str], str]:
    return chain_windows(host, proxy) if os.name == "nt" else chain_openssl(host, proxy)


def check(bundle: Path, host: str, proxy: str, timeout: float = SECONDS) -> Tuple[bool, str]:
    """Can a tool that trusts only this bundle reach `host` (through `proxy`)? The same check as az's Python makes. `(ok, why)`."""
    context = ssl.create_default_context(cafile=str(bundle))
    try:
        host, wanted = split_host(host)
        if proxy:
            name, port = proxy.rsplit(":", 1)
            raw = socket.create_connection((name.strip("[]"), int(port)), timeout=timeout)
            raw.sendall(f"CONNECT {host}:{wanted} HTTP/1.1\r\nHost: {host}:{wanted}\r\n\r\n".encode("ascii"))
            head = b""
            while b"\r\n\r\n" not in head:
                piece = raw.recv(1)
                if not piece:
                    break
                head += piece
            if not re.match(rb"^HTTP/1\.[01] 2", head):
                raw.close()
                return False, say("launch.ca.proxy.refused", said=head.split(b"\r\n")[0].decode("latin-1"))
        else:
            raw = socket.create_connection((host, wanted), timeout=timeout)
        with context.wrap_socket(raw, server_hostname=host):
            return True, ""
    except ssl.SSLCertVerificationError as error:
        return False, str(error.verify_message or error)
    except (OSError, ValueError) as error:
        return False, str(error)


def verify_with(trial: Path, certs: List[str], host: str, proxy: str, verify: Callable[[Path, str, str], Tuple[bool, str]]) -> Tuple[bool, str]:
    trial.write_text("".join(certs), encoding="ascii")
    return verify(trial, host, proxy)


def make(root: Path, host: str = "", proxy: Optional[str] = None, get_chain: Callable[[str, str], Tuple[List[str], str]] = chain,
         verify: Callable[[Path, str, str], Tuple[bool, str]] = check, own_roots: Callable[[], List[str]] = system_roots) -> Dict[str, Any]:
    """Make the bundle: the public roots, then every certificate of the chain but the first (the site's own). Kept only when the check passes with it,
    so a bundle that would not help never replaces one that does."""
    host = (host or DEFAULT_HOST).strip()
    try:
        split_host(host)
    except ValueError:
        raise ValueError(say("launch.ca.host.bad", host=host)) from None
    proxy = detect_proxy() if proxy is None else proxy_address(proxy) if proxy.strip() else ""
    paths = settings(root)["paths"]
    where, roots = base_roots(paths)
    blocks, trust = get_chain(host, proxy)
    added = blocks[1:]
    target = root / BUNDLE
    target.parent.mkdir(parents=True, exist_ok=True)
    trial = target.with_suffix(".tmp")
    certs = merge(roots, added)
    ok, why = verify_with(trial, certs, host, proxy, verify)
    system = 0
    if not ok:  # the chain stopped before its root (the proxy did not send it): the system's own roots may have it
        more = merge(certs, own_roots())
        system = len(more) - len(certs)
        if system:
            certs = more
            ok, why = verify_with(trial, certs, host, proxy, verify)
    out = {"host": host, "proxy": proxy, "roots": where, "n_roots": len(roots), "added": len(added), "system": system if ok else 0, "n": len(certs), "trust": trust, "ok": ok, "why": why}
    if not ok:
        trial.unlink()
        return out
    os.replace(trial, target)
    conn_core.write_env(root, {BUNDLE_KEY: BUNDLE.as_posix(), HOST_KEY: host, PROXY_KEY: proxy or None, MADE_KEY: utc_now()})
    return out


# --- what Get ready shows ---------------------------------------------------------------------------------------------------------------------------------

_FAULT = re.compile(r"^\$(?P<path>[^:]*): (?P<what>.*)$", re.S)
_REASONS = {"host": "may hold letters, digits, dots and hyphens, and a port after a colon (`host:port`)", "proxy": "must look like `host:port`, for example `127.0.0.1:9000`"}


def _plain_fault(item: str) -> str:
    """One sentence for one fault of `schema.validate`: the key, then what is wrong. (The raw text holds a regex; its `$` must stay as it is.)"""
    found = _FAULT.match(item)
    if not found:
        return item
    path, what = found.group("path").lstrip("."), found.group("what")
    key = path.replace("[", ".").replace("]", "").split(".")[-1] if path else ""
    where = f"`{path}`" if path else "the file"
    if what.startswith("missing required key"):
        return f"{where} lacks the key {what.split('key', 1)[1].strip().replace(chr(39), chr(96))}"
    if "does not match" in what:
        return f"{where} {_REASONS.get(key, 'is not in the form expected')}"
    if what.startswith("expected"):
        return f"{where} has the wrong kind of value ({what.replace('expected ', 'wanted ')})"
    if "characters" in what or "items" in what:
        return f"{where} is {what}" if "longer" in what or "shorter" in what else f"{where} has {what}"
    return f"{where}: {what}"


def recipe_errors(data: Any) -> List[str]:
    """What is wrong in a `computer.json`, in words that name the key; [] when it is right."""
    from . import schema

    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    errors = [_plain_fault(item) for item in schema.validate(data, RECIPE_SCHEMA)]
    for key in data:
        if key not in RECIPE_SCHEMA["properties"]:
            errors.append(f"unknown key `{key}` (it holds `ca_bundle` and `tool_folders`)")
    if isinstance(data.get("ca_bundle"), dict):
        errors += [f"ca_bundle: unknown key `{key}`" for key in data["ca_bundle"] if key not in ("host", "proxy")]
    return errors


def recipe(root: Path) -> Dict[str, Any]:
    """The company's recipe for this computer: `{"host", "proxy", "tool_folders": [{label, hint, program}], "error"}`. Empty with no file; a file with faults gives every fault, joined, and no values."""
    out: Dict[str, Any] = {"host": "", "proxy": "", "tool_folders": [], "error": ""}
    path = root / RECIPE
    if not path.is_file():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        out["error"] = str(error)
        return out
    errors = recipe_errors(data)
    if errors:
        out["error"] = "; ".join(errors)
        return out
    out["host"] = str((data.get("ca_bundle") or {}).get("host") or "")
    out["proxy"] = str((data.get("ca_bundle") or {}).get("proxy") or "")
    out["tool_folders"] = [{"label": str(item["label"]), "hint": str(item.get("hint") or ""), **({"program": str(item["program"])} if item.get("program") else {})} for item in data.get("tool_folders") or []]
    return out


def state(root: Path) -> Dict[str, Any]:
    kept = settings(root)
    bundle = bundle_path(root)
    n = len(pem_blocks(bundle.read_text(encoding="ascii", errors="ignore"))) if bundle else 0
    return {"programs": _program_rows(root), "paths": [{"path": item, "found": Path(item).is_dir(), "programs": programs_in(Path(item))[:8]} for item in kept["paths"]],
            "bundle": {"path": str(bundle) if bundle else "", "n": n, "host": kept["host"], "proxy": kept["proxy"], "made": kept["made"],
                       "vars": trusted_by(root)},
            "proxy": detect_proxy(), "recipe": recipe(root), "default_host": DEFAULT_HOST, "mcp": {"allowed": mcp_allowed(root), "detected": detect_mcp(),
            "set": bool(conn_core.read_env(root).get(MCP_KEY))}}
