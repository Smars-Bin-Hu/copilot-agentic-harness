"""What the company brings, and what is still missing (1.7.38, block B): the Optional block of the Enter screen, the yellow block on the board after Enter, and any form that wants the same facts.

`items(root)` is the one function. It reads files only (a few listings, no process, no network), so a caller may keep its answer for a few seconds. It returns a list, one item for each thing a team plugs in:

  {key, state, detail, fix, names, problems}

  key       kb, instructions, skills, standards, packs, connections, repos
  state     ok (there, and right), grey (not there, nothing to do now), yellow (there or missing, and something is off)
  detail    the short value, in the language of the engine: `acme-kb . 4 domains . 12 domain skills`; `-` when there is nothing
  fix       the place that mends the item, or {}: {to, label, ...}; `to` is setup (the Get ready form: `sec`), tools (a window: `tab`, `part`), kb (the knowledge base window: `tab`)
  names     packs and connections: [{name, state}] (ok, need, down, none, untested), for a dot each
  problems  [{key, text, why, short, fix}]: one for each thing the person should look at; `text` and `why` for the board block, `short` for a note under the Enter row
  tip       a sentence for the hover of the row; "" when there is none
  off       connections only: `{n, names, text}` for the connections whose tool pack is off. They are not counted, not in `names`, and give no "not signed in" problem; `text` is the hover's sentence
  found     kb only: whether a knowledge base with content is in place

Nothing here blocks anything. A caller that counts "to look at" counts `problems`. MCP never appears: a connection that VS Code runs is not here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import company, config, domainskills, launchenv, messages, reach, skillcheck, skillgroups, standards, targets, toolpacks
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


def home_short(path: Path) -> str:
    """`~/repos` for a folder in the home folder, else the path as it is."""
    try:
        return "~/" + path.expanduser().resolve().relative_to(Path.home().resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def item(key: str, state: str, detail: str, fix: Optional[Dict[str, Any]] = None, names: Optional[List[Dict[str, str]]] = None, problems: Optional[List[Dict[str, Any]]] = None, tip: str = "") -> Dict[str, Any]:
    return {"key": key, "state": state, "detail": detail, "fix": fix or {}, "names": names or [], "problems": problems or [], "tip": tip}


# --- the knowledge base ------------------------------------------------------------------------------------------------------------------------------------------

def knowledge_base(root: Path) -> Tuple[Optional[str], Optional[Path]]:
    """(name, folder) of the first knowledge base that has content, else (None, None)."""
    for name, path in targets.knowledge_bases(root):
        if targets.knowledge_base_content(path):
            return name, path
    return None, None


def sync_item(root: Path) -> Optional[Dict[str, Any]]:
    """The company content against its copies (`company.diff`, files only): a problem of the knowledge base row when a sync would change something (1.7.38), with the button that does it.
    None when they are the same, when there is no company content, and when the only thing wrong is the skill prefix (the Company skills row says that, with its own button)."""
    try:
        found = company.diff(root)
    except Exception:  # noqa: BLE001 - a broken copy is doctor's to report
        return None
    if not found.get("found") or found.get("in_sync") or found.get("fix"):
        return None
    if found.get("problem") and not found.get("changes"):  # a sync cannot go on (a company pack with the name of a factory pack, a file it cannot read): the window says why
        fix = fix_kb("company", say("ready.fix.show"))
        return {"key": "sync", "text": sentence(found["problem"]), "why": "", "short": "", "fix": fix}
    items = list(dict.fromkeys("/".join(str(row["path"]).split("/")[:3]) for row in found.get("changes") or []))  # a skill is one item, not one for each of its files
    if not items:
        return None  # only skills a sync cannot fix: the Company skills row has them
    n = len(items)
    names = [Path(path).name for path in items]
    return {"key": "sync", "text": say("ready.p.sync.one" if n == 1 else "ready.p.sync", n=n), "why": names_text(names), "short": say("ready.p.sync.short.one" if n == 1 else "ready.p.sync.short", n=n),
            "fix": {"to": "sync", "op": "sync", "label": say("ready.fix.sync")}}


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
    detail = say("ready.kb.found", name=name, domains=count(domains, "ready.kb.domains"), skills=count(skills, "ready.kb.skills"))
    problem = sync_item(root)
    if problem:
        return dict(item("kb", "yellow", detail, problem["fix"], problems=[problem]), found=True)
    return dict(item("kb", "ok", detail), found=True)


# --- skills, instructions, standards -----------------------------------------------------------------------------------------------------------------------------

def company_skills(root: Path, folder: Optional[Path], prefix: str, packs: Dict[str, Any]) -> List[Tuple[str, Path]]:
    """`(name, folder)` of the company's own skills: those in `.github/skills/` that are neither the harness's nor a tool pack's, and those in the knowledge base not copied yet."""
    here = root / skillcheck.SKILLS_DIR
    have = {path.parent.name: path.parent for path in sorted(here.glob("*/SKILL.md"))} if here.is_dir() else {}
    found = [(name, path) for name, path in have.items() if skillgroups.group(name, prefix, packs)[0] == "company"]
    source = folder / "skills" if folder is not None else None
    if source is not None and source.is_dir():
        found += [(path.name, path) for path in sorted(source.iterdir()) if path.is_dir() and not path.name.startswith(".") and path.name not in have]  # a folder with no SKILL.md is a skill not by the rules
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
    return (one[:1].upper() + one[1:] + ("" if one.endswith((".", "!", "?", "\u3002", "\uff01", "\uff1f")) else ".")) if one else ""  # a Chinese full stop is a stop too (no "。.")


def skills_item(root: Path, folder: Optional[Path]) -> Dict[str, Any]:
    prefix = skillcheck.effective_prefix(root)  # the word the names are judged by: the person's, else the company's
    used = skillcheck.company_prefix(root)  # the word a sync copies by: only the person's file counts (1.7.38: the row tells when the two words differ)
    wanted = skillcheck.usable(company.wanted_prefix(folder)) if folder is not None else ""  # what the company content says its word is
    found = company_skills(root, folder, prefix, skillgroups.active_packs(root))
    clash = "other" if wanted and used and wanted != used.casefold() else "none" if wanted and not used and found else ""
    bad = [(path.name, skill_trouble(path, prefix)) for _name, path in found]
    bad = [(name, why) for name, why in bad if why]
    parts = [str(len(found))]
    if clash == "other":
        parts.append(say("ready.skills.prefix.other", prefix=used, wanted=wanted))
    elif clash == "none":
        parts.append(say("ready.skills.prefix.none", wanted=wanted))
    elif prefix:
        parts.append(say("ready.skills.prefix", prefix=prefix))
    elif found:
        parts.append(say("ready.skills.noprefix"))
    if bad and not clash:
        parts.append(say("ready.skills.bad", n=len(bad)))
    problems: List[Dict[str, Any]] = []
    fix = fix_kb("company", say("ready.fix.show"))
    use = {"to": "sync", "op": "prefix", "label": say("ready.fix.prefix", word=wanted)}
    if clash:  # nothing is copied while the two words differ, so that comes first; one button sets the company's word and syncs
        values = {"wanted": wanted, "prefix": used}
        text, short = ("ready.p.prefix.other", "ready.p.prefix.short.other") if clash == "other" else ("ready.p.prefix.none", "ready.p.prefix.short.none")
        problems.append({"key": "skills", "text": say(text, **values), "why": say("ready.p.prefix.why"), "short": say(short, **values), "fix": use})
        fix = use
    elif bad:
        problems.append({"key": "skills", "text": say("ready.p.skills.one" if len(bad) == 1 else "ready.p.skills", n=len(bad), names=names_text([name for name, _why in bad])), "why": bad[0][1], "short": "", "fix": fix})
    elif found and not prefix:
        problems.append({"key": "skills", "text": say("ready.p.noprefix"), "why": say("ready.p.noprefix.why"), "short": "", "fix": fix_setup("company", say("ready.fix.setup"))})
    state = "yellow" if problems else "ok" if found else "grey"
    return item("skills", state, " \u00b7 ".join(parts) if found or prefix else DASH, fix if problems else {}, problems=problems)


def files_item(key: str, folder: Optional[Path], has_kb: bool) -> Dict[str, Any]:
    """Instructions and code standards. Instructions: every file named `<name>.instructions.md` counts, the engine copies each for the agent (1.7.38). Code standards: only the one the standards skill reads
    (`standards.COMPANY_FILE`). The others are told in the hover and by a short mark, because nothing reads them."""
    used_names = (Path(standards.COMPANY_FILE).name,)
    try:
        names = sorted(path.name for path in folder.iterdir() if path.is_file() and path.suffix == ".md" and path.name not in README) if folder is not None and folder.is_dir() else []
    except OSError:
        names = []
    used = [name for name in names if name.endswith(company.INSTRUCTION_SUFFIX) and not name.startswith(".")] if key == "instructions" else [name for name in names if name in used_names]
    unused = [name for name in names if name not in used]
    tip = say("ready.tip.instr", names=names_text(unused)) if unused and key == "instructions" else say("ready.tip.stds", names=names_text(unused), used=used_names[0]) if unused else ""
    if names and not used and key == "instructions":
        fix = fix_kb("company", say("ready.fix.show"))
        return item(key, "yellow", say("ready.instr.main"), fix, problems=[{"key": key, "text": say("ready.p.instr"), "why": say("ready.p.instr.why"), "short": "", "fix": fix}], tip=tip)
    if used:
        return item(key, "ok", count(len(used), "ready.files") + (" \u00b7 " + say("ready.files.skipped", n=len(unused)) if unused else ""), tip=tip)
    return item(key, "grey", (say("ready.files.none.skipped", n=len(unused)) if unused else say("ready.none")) if has_kb else DASH, tip=tip)


# --- tool packs and connections ----------------------------------------------------------------------------------------------------------------------------------

def packs_item(root: Path) -> Dict[str, Any]:
    needs = toolpacks.needs_report(root)
    names: List[Dict[str, str]] = []
    problems: List[Dict[str, Any]] = []
    for name in toolpacks.active(root):
        rows = [row for row in needs.get(name, []) if not row["found"]]
        lost = list(dict.fromkeys(row["program"] for row in rows))
        names.append({"name": name, "state": "need" if lost else "ok", "missing": ", ".join(lost)})
        if lost:
            many = len(lost) > 1
            stuck = {row["program"] for row in rows if row.get("blocked")}  # there, but with no run bit: told in its own words (1.7.38)
            if stuck and len(stuck) == len(lost):
                problems.append({"key": "packs", "text": say("ready.p.program.blocked", programs=names_text(lost)), "why": say("ready.p.program.blocked.why", pack=name), "short": say("ready.p.program.blocked.short", pack=name, programs=", ".join(lost)),
                                 "fix": fix_tools("local", say("ready.fix.local"), "programs")})
                continue
            problems.append({"key": "packs", "text": say("ready.p.program", programs=names_text(lost)), "why": say("ready.p.program.why.many" if many else "ready.p.program.why", pack=name),
                             "short": say("ready.p.program.short", pack=name, programs=", ".join(lost)), "fix": fix_tools("local", say("ready.fix.local"), "programs")})
    broken = toolpacks.faults(root)  # 1.7.38 (G-1): a faulty file of a pack the gate reads: red, with the file and what is wrong; the pack's programs are held
    for one in broken:
        mark = next((entry for entry in names if entry["name"] == one["pack"]), None)
        if mark is None:
            mark = {"name": one["pack"], "state": "bad", "missing": ""}
            names.append(mark)
        mark["state"] = "bad"
        first = one["faults"][0]
        mark["fault"] = f"{first['file']}: {first['problem']}"[:300]
        problems.insert(0, {"key": "packs", "text": say("ready.p.broken", pack=one["pack"], file=first["file"]), "why": first["problem"][:240],
                            "short": say("ready.p.broken.short", pack=one["pack"], file=first["file"], problem=first["problem"][:240]), "fix": fix_tools("packs", say("board.enter.t.packs"))})
    if not names:
        return item("packs", "grey", say("ready.none"))
    if broken:
        return item("packs", "red", count(len(broken), "ready.packs.broken"), problems[0]["fix"], names, problems)
    return item("packs", "yellow" if problems else "ok", count(len(names), "ready.packs"), problems[0]["fix"] if problems else {}, names, problems)


def connections_off(root: Path) -> List[str]:
    """The connections whose tool pack is off or gone (1.7.38): the company lists them, the gate still judges their calls, but there is no sign-in or test for them here. The Enter screen does not count them."""
    known = conn_core.types(root)
    return [alias for alias, server in conn_core.listed(root).items() if server.get("type") and not known.get(str(server.get("type")))]


def connection_states(root: Path) -> List[Dict[str, Any]]:
    """`[{name, state, saved}]` of every connection VS Code does not run (MCP is left out) whose tool pack is on. state: ok (the last test passed), down (a sign-in is saved and the last test failed),
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
        if kind.get("via") == "mcp" or (server.get("type") and not kind):  # no kind: its tool pack is off (counted in `connections_off`)
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
    out = connections_counted(root)
    off = connections_off(root)
    if off:  # the hover says how many more there are (Q22); the screen and the problems count the others only
        out["off"] = {"n": len(off), "names": off, "text": say("ready.conn.off.one" if len(off) == 1 else "ready.conn.off", n=len(off), names=names_text(off))}
        out["tip"] = out["off"]["text"]
    return out


def connections_counted(root: Path) -> Dict[str, Any]:
    found = connection_states(root)
    problems: List[Dict[str, Any]] = []
    none = [one["name"] for one in found if one["state"] == "none"]
    down = [one["name"] for one in found if one["state"] == "down"]
    if none:
        problems.append({"key": "signin", "text": say("ready.p.signin.one" if len(none) == 1 else "ready.p.signin", n=len(none), names=names_text(none)), "why": say("ready.p.signin.why"),
                         "short": say("ready.p.signin.short", n=len(none)), "fix": fix_tools("connections", say("ready.fix.signin"))})
    if down:
        problems.append({"key": "down", "text": say("ready.p.down.one" if len(down) == 1 else "ready.p.down", n=len(down), names=names_text(down)), "why": say("ready.p.down.why"),
                         "short": say("ready.p.down.short.one" if len(down) == 1 else "ready.p.down.short", n=len(down)), "fix": fix_tools("connections", say("ready.fix.test"))})
    if certificate_missing(root):
        problems.append({"key": "cert", "text": say("ready.p.cert"), "why": say("ready.p.cert.why"), "short": say("ready.p.cert.short"), "fix": fix_tools("local", say("ready.fix.local"), "network")})
    if not found:
        return item("connections", "yellow" if problems else "grey", say("ready.none"), problems[0]["fix"] if problems else {}, problems=problems)
    ok = len([one for one in found if one["state"] == "ok"])
    parts = [say("ready.conn.signed", n=ok)] if ok else []
    for state, key, single in (("none", "ready.conn.unsigned", "ready.conn.unsigned"), ("down", "ready.conn.down", "ready.conn.down.one"), ("untested", "ready.conn.untested", "ready.conn.untested")):
        n = len([one for one in found if one["state"] == state])
        if n:
            parts.append(say(single if n == 1 else key, n=n))
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
        out[-1]["home"] = home(key)
    return out


def home(key: str) -> Dict[str, Any]:
    """Where the name of a row leads: its own window (Tool packs for the packs, even when the fix of a problem is in Local). A note's link leads to the fix."""
    if key == "packs":
        return fix_tools("packs", say("board.enter.t.packs"))
    if key == "connections":
        return fix_tools("connections", say("board.enter.t.connections"))
    if key == "repos":
        return fix_setup("company", say("board.enter.t.repos"))
    return fix_kb("overview" if key == "kb" else "company", say(f"board.enter.t.{key}"))


def problems(listed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every problem of the items, in the order of the screen, each with the key of its item in `row`."""
    return [dict(problem, row=entry["key"]) for entry in listed for problem in entry["problems"]]
