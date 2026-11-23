"""The first-run wizard's side of the board (1.8.x, O1): which copies are sent to it, the pages it saves, the repositories it offers, and the list on its last page.

The page (`web/wizard.js`) draws and asks; every sentence of the list is made here from the messages. The knowledge base is copied by `setupjob` (the old job, three of its steps).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import messages, readyitems, setup, targets

MARK = "setup_wizard"
PLACES = ("Developer", "source/repos", "git", "repos", "code", "projects")  # under the home folder; one level deep, a folder with `.git` in it is a repository
MAX_ROWS = 300
MAX_PICKS = 300
ORDER = ("you", "programs", "copilot", "kb", "packs", "connections", "repos")
LABELS = {"you": "setup.w.label.you", "programs": "setup.w.label.programs", "copilot": "setup.w.label.copilot", "kb": "setup.w.label.kb", "packs": "setup.w.label.packs", "connections": "setup.w.label.connections", "repos": "setup.w.label.repos"}
LANGUAGE_NAMES = {"en": "desk.send.lang.en", "zh": "desk.send.lang.name.zh"}  # each language in its own words: the same messages as the language tiles of the wizard page


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


# --- which copy goes to the wizard -------------------------------------------------------------------------------------

def mark(root: Path) -> None:
    """The first page that saves something: the wizard is under way (`setup_wizard`), and until Confirm this copy is not set up."""
    if not setup.kept(root, "user").get(MARK):
        setup.write(root, "user", {MARK: "open"})


def finish(root: Path) -> None:
    """Confirm: this copy is set up, the wizard is not under way any more."""
    setup.write(root, "user", {"setup_done": True})
    setup.remove(root, "user", [MARK])


def under_way(root: Path) -> bool:
    try:
        return bool(setup.kept(root, "user").get(MARK))
    except ValueError:
        return False


# --- save, one page at a time ------------------------------------------------------------------------------------------

def stamp_ok(root: Path, data: Dict[str, Any]) -> None:
    now = setup.stamp(root)
    if not now:  # a broken file of the person's: told as it is, never overwritten
        for name in ("user", "target", "tools"):
            setup.kept(root, name)
    elif data.get("stamp") and data["stamp"] != now:
        raise ValueError(say("setup.changed"))


def save_you(root: Path, data: Dict[str, Any]) -> None:
    """Name and language, checked as `setup.check` does; the skill prefix and the rest of the file stay."""
    name = " ".join(str(data.get("name") or "").split())
    language = str(data.get("language") or "").strip().lower()
    wrong: List[str] = []
    if not name or len(name) > setup.MAX_NAME:
        wrong.append(say("setup.name.need", limit=setup.MAX_NAME))
    if language not in messages.LANGUAGES:
        wrong.append(say("setup.language.need"))
    forced = setup.forced_language()
    if forced and forced != language:
        wrong.append(say("serve.language.env", name=messages.ENVIRONMENT))
    stamp_ok(root, data)
    if wrong:
        raise ValueError(" ".join(wrong))
    mark(root)
    setup.write(root, "user", {"name": name, **({} if forced else {"language": language})})


def save_repos(root: Path, data: Dict[str, Any]) -> int:
    """The repositories picked, as singles of the target file (`setup.steps`' own writing); the folder of repositories (`repos_root`) stays as it is. Returns how many."""
    stamp_ok(root, data)
    paths = data.get("paths")
    if not isinstance(paths, list) or len(paths) > MAX_PICKS or not all(isinstance(item, str) for item in paths):
        raise ValueError(say("serve.refused.request"))
    held: List[str] = []
    wrong: List[str] = []
    for item in [setup.clean_path(one) for one in paths]:
        try:
            if setup.add_repo(item, "", held, root)["kind"] != "repo":
                wrong.append(f"{item}: {say('setup.repos.none')}")
            held.append(item)
        except ValueError as error:
            wrong.append(f"{item}: {error}")
    if wrong:
        raise ValueError(" ".join(wrong))
    mark(root)
    base = str(setup.kept(root, "target").get("repos_root") or "")
    dict(setup.steps(root, {"repos_root": base, "singles": held}))["target"]()
    return len(held)


def save_advanced(root: Path, data: Dict[str, Any]) -> None:
    """Settings, Advanced (O5): the skill prefix (user), the Python install command (tools) and the paths not to touch (target). The fields are checked as `setup.check` checks them; the name,
    the language, the folder of repositories (`repos_root`) and the single repositories stay as they are, and nothing else runs (no sync, no doctor)."""
    wrong: List[str] = []
    prefix = str(data.get("skill_prefix") or "").strip()
    command = str(data.get("install_command") or "").strip()
    if prefix and not setup.PREFIX.fullmatch(prefix):
        wrong.append(say("setup.prefix.bad"))
    if len(command) > setup.MAX_INSTALL:
        wrong.append(say("setup.install.long", limit=setup.MAX_INSTALL))
    for key in ("refused", "rules"):
        if key in data and not isinstance(data[key], list):
            raise ValueError(say("serve.refused.request"))
    stamp_ok(root, data)
    held = setup.kept(root, "target")
    base = str(held.get("repos_root") or "")
    singles = [setup.clean_path(entry["path"]) for entry in (held.get("repos") or {}).values() if setup.is_single(entry)]
    for item in data.get("refused") or []:
        try:
            setup.refused(base, item, singles)
        except ValueError as error:
            wrong.append(f"{item}: {error}")
    if wrong:
        raise ValueError(" ".join(wrong))
    setup.write(root, "user", {"skill_prefix": prefix})
    pick = {"repos_root": base, "singles": singles, "install_command": command}
    if "refused" in data:
        pick["refused"] = data["refused"]
    if "rules" in data:
        pick["rules"] = data["rules"]
    todo = dict(setup.steps(root, pick))
    todo["tools"]()
    todo["target"]()


# --- scan: the repositories on this computer ---------------------------------------------------------------------------

def picked_paths(root: Path) -> set:
    try:
        found = targets.load(root)
        kb = {name for name, _path in targets.knowledge_bases(root)}
        return {str(repo.path.resolve()) for name, repo in found.repos.items() if name not in kb and not repo.knowledge_base}
    except Exception:  # noqa: BLE001 - a broken policy is doctor's to report; nothing is shown as picked
        return set()


def scan(root: Path, home: Optional[Path] = None) -> Dict[str, Any]:
    """`{places, rows, more}`: the git repositories one level below the usual places (and below `repos_root`), the knowledge base and this harness left out, at most MAX_ROWS."""
    home = Path.home() if home is None else home
    wanted: List[Path] = [home / name for name in PLACES]
    try:
        base = str(setup.kept(root, "target").get("repos_root") or "").strip()
    except ValueError:
        base = ""
    if base:
        wanted.append(Path(setup.clean_path(base)))
    places: List[Path] = []
    for place in wanted:
        try:
            if place.is_dir() and place.resolve() not in [one.resolve() for one in places]:
                places.append(place)
        except OSError:
            continue
    own = setup.own_folders(root)
    picked = picked_paths(root)
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    more = False
    for place in places:
        try:
            names = sorted((item for item in place.iterdir() if not item.name.startswith(".")), key=lambda item: item.name.casefold())
        except OSError:
            continue
        for item in names:
            try:
                if not item.is_dir() or not setup.has_git(item) or not targets.REPO_NAME.match(item.name):
                    continue
                full = item.resolve()
                if full in own or full in seen or setup.kb_like(item):
                    continue
                if len(rows) >= MAX_ROWS:
                    more = True
                    break
                seen.add(full)
                rows.append({"path": str(item), "shown": setup.shown_path(root, item), "name": item.name, "branch": setup.head_branch(item), "picked": str(full) in picked})
            except OSError:
                continue
        if more:
            break
    return {"places": [setup.shown_path(root, place) for place in places], "rows": rows, "more": more}


# --- summary: the list on the last page --------------------------------------------------------------------------------

def language_name(code: str) -> str:
    return say(LANGUAGE_NAMES[code]) if code in LANGUAGE_NAMES else code


def summary(root: Path, programs: Dict[str, Any], copilot: Dict[str, Any]) -> Dict[str, Any]:
    """`{rows}`: one row for each thing the wizard asked, `{id, done, label, detail, effect}`, in ORDER. Tool packs and connections show only when there is something of the kind.
    `programs` is the answer of the step `programs`, `copilot` the Copilot line of `/api/ready`. `effect`: what is lost while it is not done; empty when done."""
    items = {entry["key"]: entry for entry in readyitems.items(root)}
    kept = setup.kept(root, "user")
    name = str(kept.get("name") or "")
    language = str(kept.get("language") or messages.language())
    found = programs.get("rows") or []
    have = [row for row in found if row.get("required") and row.get("found") and not row.get("blocked")]
    total = len([row for row in found if row.get("required")])
    kb = items.get("kb") or {}
    out: List[Dict[str, Any]] = []

    def add(key: str, done: bool, detail: str, effect: str = "") -> None:
        out.append({"id": key, "done": done, "label": say(LABELS[key]), "detail": detail if detail != readyitems.DASH else "", "effect": "" if done else effect})

    add("you", bool(name), f"{name} · {language_name(language)}" if name else "", say("setup.w.you.effect"))
    add("programs", bool(programs.get("all_found")), say("setup.w.programs.detail", n=len(have), total=total), say("setup.w.programs.effect"))
    ok = copilot.get("state") == "ok"
    add("copilot", ok, str(copilot.get("login") or "") if ok else "", say("setup.w.copilot.effect"))
    held = setup.kb_state(root)  # the same name and version as the knowledge base card of the wizard page (`prefix` and `version`)
    kb_detail = (str(held.get("prefix") or "") or say("wizard.k.name")) + (f" · {held['version']}" if held.get("version") else "") if held.get("here") else ""
    add("kb", bool(kb.get("found")), kb_detail if kb.get("found") else "", say("ready.effect.kb"))
    if kb.get("found") and (items.get("packs") or {}).get("names"):
        add("packs", items["packs"]["state"] == "ok", str(items["packs"].get("detail") or ""), say("ready.effect.packs"))
    if kb.get("found") and (items.get("connections") or {}).get("names"):
        add("connections", items["connections"]["state"] == "ok", str(items["connections"].get("detail") or ""), say("ready.effect.connections"))
    repos = items.get("repos") or {}
    add("repos", repos.get("state") == "ok", str(repos.get("detail") or "") if repos.get("state") == "ok" else "", say("ready.effect.repos"))
    return {"rows": sorted(out, key=lambda row: ORDER.index(row["id"]))}
