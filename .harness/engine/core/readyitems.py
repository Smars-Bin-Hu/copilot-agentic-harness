"""What the company brings, and what is still missing (1.7.38, block B): the Optional block of the Enter screen, the yellow block on the board after Enter, and any form that wants the same facts.

`items(root)` is the one function. It reads files only (a few listings, no process, no network), so a caller may keep its answer for a few seconds. It returns a list, one item for each thing a team plugs in:

  {key, state, detail, fix, names, problems}

  key       kb, instructions, skills, standards, packs, connections, repos
  state     ok (there, and right), grey (not there, nothing to do now), yellow (there or missing, and something is off)
  detail    the short value, in the language of the engine: `acme-kb . 4 domains . 12 domain skills`; `-` when there is nothing
  fix       the place that mends the item, or {}: {to, label, ...}; `to` is setup (the Get ready form: `sec`), tools (a window: `tab`, `part`), kb (the knowledge base window: `tab`)
  names     packs and connections: [{name, state}] (ok, need, down, none, untested), for a dot each
  problems  [{key, text, why, short, fix}]: one for each thing the person should look at; `text` and `why` for the board block, `short` for a note under the Enter row
  found     kb only: whether a knowledge base with content is in place

Nothing here blocks anything. A caller that counts "to look at" counts `problems`. MCP never appears: a connection that VS Code runs is not here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, domainskills, launchenv, messages, reach, skillcheck, skillgroups, targets, toolpacks
from . import connections as conn_core

SHOWN_NAMES = 4  # names in one sentence of the board block; the rest is "+N"
DASH = "—"
KEYS = ("kb", "instructions", "skills", "standards", "packs", "connections", "repos")
README = ("README.md", ".gitkeep")


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def count(n: int, key: str) -> str:
    """`3 files`, `1 file`: the message `key` for many, `key.one` for one."""
    return say(key + ".one" if n == 1 else key, n=n)


def names_text(names: List[str]) -> str:
    shown = names[:SHOWN_NAMES]
    return ", ".join(shown) + (f" +{len(names) - len(shown)}" if len(names) > len(shown) else "")


def fix_setup(sec: str, label: str, short: str = "") -> Dict[str, Any]:
    return {"to": "setup", "sec": sec, "label": label, **({"short": short} if short else {})}


def fix_tools(tab: str, label: str, part: str = "") -> Dict[str, Any]:
    return {"to": "tools", "tab": tab, "part": part, "label": label}


def fix_kb(tab: str, label: str) -> Dict[str, Any]:
    return {"to": "kb", "tab": tab, "label": label}


def files_in(folder: Optional[Path]) -> int:
    try:
        return len([item for item in folder.iterdir() if item.is_file() and item.suffix == ".md" and item.name not in README]) if folder is not None and folder.is_dir() else 0
    except OSError:
        return 0


def home_short(path: Path) -> str:
    """`~/repos` for a folder in the home folder, else the path as it is."""
    try:
        return "~/" + path.expanduser().resolve().relative_to(Path.home().resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def item(key: str, state: str, detail: str, fix: Optional[Dict[str, Any]] = None, names: Optional[List[Dict[str, str]]] = None, problems: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {"key": key, "state": state, "detail": detail, "fix": fix or {}, "names": names or [], "problems": problems or []}


# --- the knowledge base ------------------------------------------------------------------------------------------------------------------------------------------

def knowledge_base(root: Path) -> Tuple[Optional[str], Optional[Path]]:
    """(name, folder) of the first knowledge base that has content, else (None, None)."""
    for name, path in targets.knowledge_bases(root):
        if targets.knowledge_base_content(path):
            return name, path
    return None, None


def kb_item(root: Path, name: Optional[str], path: Optional[Path]) -> Dict[str, Any]:
    if name is None or path is None:
        problem = {"key": "kb", "text": say("ready.p.kb"), "why": say("ready.p.kb.why"), "short": say("ready.p.kb.short"), "fix": fix_setup("company", say("ready.fix.kb"), say("ready.fix.kb.short"))}
        return dict(item("kb", "yellow", say("ready.kb.none"), problem["fix"], problems=[problem]), found=False)
    try:
        domains = len(domainskills.domains(root))
    except OSError:
        domains = 0
    try:
        skills = len(domainskills.skills(root))
    except OSError:
        skills = 0
    return dict(item("kb", "ok", say("ready.kb.found", name=name, domains=count(domains, "ready.kb.domains"), skills=count(skills, "ready.kb.skills"))), found=True)


# --- skills, instructions, standards -----------------------------------------------------------------------------------------------------------------------------

def company_skills(root: Path, folder: Optional[Path], prefix: str, packs: Dict[str, Any]) -> List[Tuple[str, Path]]:
    """`(name, folder)` of the company's own skills: those in `.github/skills/` that are neither the harness's nor a tool pack's, and those in the knowledge base not copied yet."""
    here = root / skillcheck.SKILLS_DIR
    have = {path.parent.name: path.parent for path in sorted(here.glob("*/SKILL.md"))} if here.is_dir() else {}
    found = [(name, path) for name, path in have.items() if skillgroups.group(name, prefix, packs)[0] == "company"]
    source = folder / "skills" if folder is not None else None
    if source is not None and source.is_dir():
        found += [(path.name, path) for path in sorted(source.iterdir()) if path.is_dir() and (path / "SKILL.md").is_file() and path.name not in have]
    return found


def skill_trouble(path: Path, prefix: str) -> str:
    """Why a company skill is not by the rules, as one sentence, or ""."""
    if prefix and not path.name.startswith(prefix + "-"):
        return say("ready.why.prefix", prefix=prefix)
    errors = skillcheck.check(path, prefix)["errors"]
    return sentence(errors[0]) if errors else ""


def sentence(text: str) -> str:
    """A message of the checks for a person: no terminal marks, a capital, a full stop."""
    one = " ".join(str(text).replace("`", "").split())
    return (one[:1].upper() + one[1:] + ("" if one.endswith((".", "!", "?")) else ".")) if one else ""


def skills_item(root: Path, folder: Optional[Path]) -> Dict[str, Any]:
    prefix = skillcheck.effective_prefix(root)
    found = company_skills(root, folder, prefix, skillgroups.active_packs(root))
    bad = [(path.name, skill_trouble(path, prefix)) for _name, path in found]
    bad = [(name, why) for name, why in bad if why]
    parts = [str(len(found))]
    if prefix:
        parts.append(say("ready.skills.prefix", prefix=prefix))
    elif found:
        parts.append(say("ready.skills.noprefix"))
    if bad:
        parts.append(say("ready.skills.bad", n=len(bad)))
    problems: List[Dict[str, Any]] = []
    fix = fix_kb("company", say("ready.fix.show"))
    if bad:
        problems.append({"key": "skills", "text": say("ready.p.skills.one" if len(bad) == 1 else "ready.p.skills", n=len(bad), names=names_text([name for name, _why in bad])), "why": bad[0][1], "short": "", "fix": fix})
    elif found and not prefix:
        problems.append({"key": "skills", "text": say("ready.p.noprefix"), "why": say("ready.p.noprefix.why"), "short": "", "fix": fix_setup("company", say("ready.fix.setup"))})
    state = "yellow" if problems else "ok" if found else "grey"
    return item("skills", state, " · ".join(parts) if found or prefix else DASH, fix if problems else {}, problems=problems)


def files_item(key: str, folder: Optional[Path], has_kb: bool) -> Dict[str, Any]:
    n = files_in(folder)
    if n:
        return item(key, "ok", count(n, "ready.files"))
    return item(key, "grey", say("ready.none") if has_kb else DASH)


# --- tool packs and connections ----------------------------------------------------------------------------------------------------------------------------------

def packs_item(root: Path) -> Dict[str, Any]:
    needs = toolpacks.needs_report(root)
    names: List[Dict[str, str]] = []
    problems: List[Dict[str, Any]] = []
    for name in toolpacks.active(root):
        lost = list(dict.fromkeys(row["program"] for row in needs.get(name, []) if not row["found"]))
        names.append({"name": name, "state": "need" if lost else "ok", "missing": ", ".join(lost)})
        if lost:
            many = len(lost) > 1
            problems.append({"key": "packs", "text": say("ready.p.program", programs=names_text(lost)), "why": say("ready.p.program.why.many" if many else "ready.p.program.why", pack=name),
                             "short": say("ready.p.program.short", pack=name, programs=", ".join(lost)), "fix": fix_tools("local", say("ready.fix.local"), "programs")})
    if not names:
        return item("packs", "grey", say("ready.none"))
    return item("packs", "yellow" if problems else "ok", count(len(names), "ready.packs"), problems[0]["fix"] if problems else {}, names, problems)


def connection_states(root: Path) -> List[Dict[str, Any]]:
    """`[{name, state, saved}]` of every connection VS Code does not run (MCP is left out). state: ok (the last test passed), down (a sign-in is saved and the last test failed),
    none (no sign-in, and no test passed), untested (a sign-in is saved and no test has run yet)."""
    known, env = conn_core.types(root), conn_core.read_env(root)
    systems = config.policy_or_empty(root, "tools").get("systems") or {}
    try:
        seen = reach.view(root, systems) if systems else []
    except Exception:  # noqa: BLE001 - a broken list of systems is doctor's to report: the sign-ins are still told
        seen = []
    out: List[Dict[str, Any]] = []
    for alias, server in conn_core.listed(root).items():
        kind = known.get(str(server.get("type"))) or {}
        if kind.get("via") == "mcp":
            continue
        saved = bool(conn_core.identity_of(env, alias, kind, server))
        states = [reach.UNKNOWN if line.get("why") == "vscode-env" else line["state"] for line in seen if line["system"] == alias]  # a VS Code started without this computer's settings says nothing of the sign-in: its own row says that
        passed = bool(states) and all(state == reach.OK for state in states) or (not states and saved)
        failed = any(state in (reach.DENIED, reach.FAILED) for state in states)
        state = "ok" if passed else "none" if not saved else "down" if failed else "untested"
        out.append({"name": alias, "state": state, "saved": saved})
    return out


def certificate_missing(root: Path) -> bool:
    """The company's recipe for this computer asks for a certificate bundle (a proxy or an outside host) and there is none."""
    try:
        recipe = launchenv.recipe(root)
    except Exception:  # noqa: BLE001 - a broken file is doctor's to report
        return False
    return bool(recipe.get("host") or recipe.get("proxy")) and launchenv.bundle_path(root) is None


def connections_item(root: Path) -> Dict[str, Any]:
    found = connection_states(root)
    problems: List[Dict[str, Any]] = []
    none = [one["name"] for one in found if one["state"] == "none"]
    down = [one["name"] for one in found if one["state"] == "down"]
    if none:
        problems.append({"key": "signin", "text": say("ready.p.signin.one" if len(none) == 1 else "ready.p.signin", n=len(none), names=names_text(none)), "why": say("ready.p.signin.why"),
                         "short": say("ready.p.signin.short", n=len(none)), "fix": fix_tools("connections", say("ready.fix.signin"))})
    if down:
        problems.append({"key": "down", "text": say("ready.p.down.one" if len(down) == 1 else "ready.p.down", n=len(down), names=names_text(down)), "why": say("ready.p.down.why"),
                         "short": say("ready.p.down.short", n=len(down)), "fix": fix_tools("connections", say("ready.fix.test"))})
    if certificate_missing(root):
        problems.append({"key": "cert", "text": say("ready.p.cert"), "why": say("ready.p.cert.why"), "short": say("ready.p.cert.short"), "fix": fix_tools("local", say("ready.fix.local"), "network")})
    if not found:
        return item("connections", "yellow" if problems else "grey", say("ready.none"), problems[0]["fix"] if problems else {}, problems=problems)
    ok = len([one for one in found if one["state"] == "ok"])
    parts = [say("ready.conn.signed", n=ok)] if ok else []
    for state, key in (("none", "ready.conn.unsigned"), ("down", "ready.conn.down"), ("untested", "ready.conn.untested")):
        n = len([one for one in found if one["state"] == state])
        if n:
            parts.append(say(key, n=n))
    detail = " \u00b7 ".join(parts)
    return item("connections", "yellow" if problems else "ok" if ok == len(found) else "grey", detail, problems[0]["fix"] if problems else {}, [{"name": one["name"], "state": one["state"], "saved": one["saved"]} for one in found], problems)


# --- code repositories -------------------------------------------------------------------------------------------------------------------------------------------

def repos_item(root: Path) -> Dict[str, Any]:
    fix = fix_setup("company", say("ready.fix.add"))
    try:
        found = targets.load(root)
        kb = {name for name, _path in targets.knowledge_bases(root)}
        repos = [repo for name, repo in found.repos.items() if name not in kb and not repo.knowledge_base]
        where = ""
        policy = config.policy_or_empty(root, "target")
        base = str(policy.get("repos_root") or "").strip()
        if base and repos:
            where = home_short(targets.expand(base))
        if found.problems and not repos:
            problem = {"key": "repos", "text": say("ready.p.repos.bad", first=found.problems[0][:160]), "why": say("ready.p.repos.bad.why"), "short": "", "fix": fix}
            return item("repos", "yellow", say("ready.repos.problem"), fix, problems=[problem])
        if repos:
            n = count(len(repos), "ready.repos")
            problems = []
            if found.problems:
                problems.append({"key": "repos", "text": say("ready.p.repos.bad", first=found.problems[0][:160]), "why": say("ready.p.repos.bad.why"), "short": "", "fix": fix})
            return item("repos", "yellow" if problems else "ok", f"{where} · {n}" if where else n, fix if problems else {}, problems=problems)
    except Exception as error:  # noqa: BLE001 - a broken policy is doctor's to report; here it is a yellow item
        problem = {"key": "repos", "text": say("ready.p.repos.bad", first=f"{type(error).__name__}: {error}"[:160]), "why": say("ready.p.repos.bad.why"), "short": "", "fix": fix}
        return item("repos", "yellow", say("ready.repos.problem"), fix, problems=[problem])
    problem = {"key": "repos", "text": say("ready.p.repos"), "why": say("ready.p.repos.why"), "short": "", "fix": fix}
    return item("repos", "yellow", say("ready.repos.none"), fix, problems=[problem])


# --- the list ----------------------------------------------------------------------------------------------------------------------------------------------------

def items(root: Path) -> List[Dict[str, Any]]:
    """The seven items in the order of the screen. A part that cannot be read is a yellow item with a problem, never an error of the caller."""
    name, path = knowledge_base(root)
    folder = targets.company_folder(root)
    has_kb = name is not None
    parts: List[Tuple[str, Callable[[], Dict[str, Any]]]] = [
        ("kb", lambda: kb_item(root, name, path)),
        ("instructions", lambda: files_item("instructions", folder / "instructions" if folder else None, has_kb)),
        ("skills", lambda: skills_item(root, folder)),
        ("standards", lambda: files_item("standards", folder / "standards" if folder else None, has_kb)),
        ("packs", lambda: packs_item(root)),
        ("connections", lambda: connections_item(root)),
        ("repos", lambda: repos_item(root)),
    ]
    out: List[Dict[str, Any]] = []
    for key, make in parts:
        try:
            out.append(make())
        except Exception as error:  # noqa: BLE001 - one part that cannot be read must not hide the others
            problem = {"key": key, "text": say("ready.p.error", name=say(f"board.enter.t.{key}")), "why": f"{type(error).__name__}: {error}"[:200], "short": "", "fix": {}}
            out.append(item(key, "yellow", say("ready.error"), problems=[problem]))
    return out


def problems(listed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every problem of the items, in the order of the screen, each with the key of its item in `row`."""
    return [dict(problem, row=entry["key"]) for entry in listed for problem in entry["problems"]]
