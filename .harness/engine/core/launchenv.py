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
BUNDLE = Path(".harness") / "certs" / "ca-bundle.pem"
TRUST_VARS = ("REQUESTS_CA_BUNDLE",)  # Python tools (az, pip's requests); NODE_EXTRA_CA_CERTS and others when a tool pack asks for them
DEFAULT_HOST = "example.com"
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


def extra(root: Path, environ: Optional[Dict[str, str]] = None, trust_vars: Optional[Tuple[str, ...]] = None) -> Dict[str, str]:
    """The variables the board adds when it starts VS Code: PATH with the tool folders first, and each trust variable naming the bundle (when it is there)."""
    base = dict(os.environ if environ is None else environ)
    kept = settings(root)
    out: Dict[str, str] = {}
    folders = [item for item in kept["paths"] if Path(item).is_dir()]
    if folders:
        key = next((name for name in base if name.upper() == "PATH"), "PATH")  # Windows writes `Path`
        rest = [item for item in base.get(key, "").split(os.pathsep) if item and item not in folders]
        out[key] = os.pathsep.join(folders + rest)
    bundle = bundle_path(root)
    if bundle:
        for name in (trust_vars if trust_vars is not None else trusted_by(root)):
            out[name] = str(bundle)
    return out


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
$h = $args[0]; $p = $args[1]
$global:zchain = @(); $global:zerr = ''
$cb = [Net.Security.RemoteCertificateValidationCallback]{ param($s, $c, $ch, $e) $global:zerr = "$e"; $global:zchain = @($ch.ChainElements | ForEach-Object { $_.Certificate }); $true }
if ($p) { $hp = $p.Split(':'); $tcp = [Net.Sockets.TcpClient]::new($hp[0], [int]$hp[1]); $ns = $tcp.GetStream()
  $req = [Text.Encoding]::ASCII.GetBytes("CONNECT ${h}:443 HTTP/1.1`r`nHost: ${h}:443`r`n`r`n"); $ns.Write($req, 0, $req.Length)
  $one = New-Object byte[] 1; $head = ''
  while (-not $head.EndsWith("`r`n`r`n")) { if ($ns.Read($one, 0, 1) -le 0) { break }; $head += [char]$one[0] }
  if ($head -notmatch '^HTTP/1\.[01] 2') { "PROXY " + ($head -split "`r`n")[0]; exit 3 } }
else { $tcp = [Net.Sockets.TcpClient]::new($h, 443); $ns = $tcp.GetStream() }
$ssl = [Net.Security.SslStream]::new($ns, $false, $cb); $ssl.AuthenticateAsClient($h); $tcp.Close()
"TRUST $zerr"
$zchain | ForEach-Object { "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($_.RawData, 'InsertLineBreaks') + "`n-----END CERTIFICATE-----" }
"""


def chain_windows(host: str, proxy: str, run: Callable[..., Any] = subprocess.run) -> Tuple[List[str], str]:
    """The chain Windows builds for `host`, through `proxy` when given (the root from the system's store included). `(blocks, trust)`: trust is
    "None" when Windows trusts it, else the reason (RemoteCertificateChainErrors, ...)."""
    done = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_CHAIN, host, proxy], capture_output=True, text=True, timeout=SECONDS,
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = done.stdout or ""
    found = re.search(r"^PROXY (.*)$", out, re.MULTILINE)
    if found:
        raise ValueError(say("launch.ca.proxy.refused", said=found.group(1).strip()))
    trust = re.search(r"^TRUST (.*)$", out, re.MULTILINE)
    if not trust:
        raise ValueError(say("launch.ca.chain.failed", said=((done.stderr or out).strip().splitlines() or ["-"])[-1][:300]))
    return pem_blocks(out), trust.group(1).strip() or "None"


def chain_openssl(host: str, proxy: str, run: Callable[..., Any] = subprocess.run) -> Tuple[List[str], str]:
    """The chain the server (or the proxy in its place) sends, read with `openssl s_client`. It may stop before the root: the root comes from the
    system's own list then."""
    program = shutil.which("openssl")
    if not program:
        raise ValueError(say("launch.ca.no_openssl"))
    argv = [program, "s_client", "-showcerts", "-servername", host, "-connect", f"{host}:443"] + (["-proxy", proxy] if proxy else [])
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
        if proxy:
            name, port = proxy.rsplit(":", 1)
            raw = socket.create_connection((name.strip("[]"), int(port)), timeout=timeout)
            raw.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode("ascii"))
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
            raw = socket.create_connection((host, 443), timeout=timeout)
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
    if not re.match(r"^[A-Za-z0-9.\-]+$", host):
        raise ValueError(say("launch.ca.host.bad", host=host))
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

def state(root: Path) -> Dict[str, Any]:
    kept = settings(root)
    bundle = bundle_path(root)
    n = len(pem_blocks(bundle.read_text(encoding="ascii", errors="ignore"))) if bundle else 0
    return {"paths": [{"path": item, "found": Path(item).is_dir(), "programs": programs_in(Path(item))[:8]} for item in kept["paths"]],
            "bundle": {"path": str(bundle) if bundle else "", "n": n, "host": kept["host"], "proxy": kept["proxy"], "made": kept["made"],
                       "vars": trusted_by(root)},
            "proxy": detect_proxy(), "default_host": DEFAULT_HOST}
