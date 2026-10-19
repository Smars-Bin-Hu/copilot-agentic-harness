"""Where building the knowledge base stands, worked out from the files, never from what an agent remembers (M28).

  kb status   the steps from code repositories to learned domains, which are done, and the next one, with what to
              say or type for it. A wizard, a stop of a task and a person back after a week all read the same answer.

`quick` looks only at which files exist (a hook calls it); the full one also checks the facts of the map and how much
of each domain is left to learn.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import kbgraph, kblearn, kbmap, messages, targets
from .kbgraph import MapError

STEPS = ("targets", "kb_repo", "toolkit", "map", "audit", "domains", "learn", "maintain")
AUDIT_FILE = "audit.md"
PASSED = re.compile(r"^Result:\s*\**\s*pass\b", re.I | re.M)
ORDER = re.compile(r"harness kb order[^\n`]*")


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def knowledge_base(root: Path) -> Tuple[List[targets.Repo], Optional[targets.Repo]]:
    """(the code repositories, the registered knowledge base or None). Never raises."""
    try:
        found = targets.load(root)
    except Exception:  # noqa: BLE001 - a broken policy is doctor's to report; here it means "not set up"
        return [], None
    code = [repo for _name, repo in sorted(found.repos.items()) if not repo.knowledge_base]
    kb = next((repo for _name, repo in sorted(found.repos.items()) if repo.knowledge_base), None)
    return code, kb


def plan_command(path: Path) -> Optional[Dict[str, Any]]:
    """The `kb order` command a learn plan holds: its entry points, stops and shared-min. None when there is none yet."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in ORDER.findall(text):
        try:
            words = shlex.split(line)
        except ValueError:
            continue
        found: Dict[str, Any] = {"entries": [], "stops": [], "shared_min": None}
        for flag, value in zip(words, words[1:]):
            if flag == "--entry":
                found["entries"].append(value)
            elif flag == "--stop":
                found["stops"].append(value)
            elif flag == "--shared-min" and value.isdigit():
                found["shared_min"] = int(value)
        if found["entries"] and not any("<" in item for item in found["entries"]):
            return found
    return None


def flows_written(path: Path) -> bool:
    """architecture.md has at least one flow line: an arrow between two ids, under Flows."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    section = re.search(r"^## Flows\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return bool(section and re.search(r"`[a-z][a-z0-9_-]*:[^`]+`\s*(?:→|->)", section.group(1)))


def open_requests(path: Path) -> int:
    try:
        rows = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.startswith("|")]
    except OSError:
        return 0
    return sum(1 for row in rows[2:] if row.rstrip(" |").rsplit("|", 1)[-1].strip().lower().startswith("open"))


def domain_state(root: Path, folder: Path, deep: bool) -> Dict[str, Any]:
    plan = plan_command(folder / "discovery" / "learn-plan.md")
    state: Dict[str, Any] = {"domain": folder.name, "plan": plan is not None, "architecture": flows_written(folder / "architecture.md"),
                             "requests_open": open_requests(folder / "requests.md")}
    if deep and plan:
        try:
            order = kblearn.order(root, plan["entries"], plan["stops"], shared_min=plan["shared_min"], folder=folder)
            state.update(to_learn=order["to_learn"], batches_left=len(order["batches"]))
        except MapError as error:
            state["problem"] = str(error)
    state["done"] = state["plan"] and state["architecture"] and not state.get("to_learn")
    if not plan and cards(folder) and (folder / "architecture.md").is_file():
        state.update(done=True, migrated=True)  # learned before learn plans (a migration): built; refresh keeps it true
    return state


def cards(folder: Path) -> int:
    try:
        return sum(1 for line in (folder / "objects" / "index.jsonl").read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
    except OSError:
        return 0


def status(root: Path, deep: bool = True) -> Dict[str, Any]:
    """`kb status`: each step, done or not, and the next one."""
    code, kb = knowledge_base(root)
    steps: Dict[str, Dict[str, Any]] = {name: {"done": False} for name in STEPS}
    steps["targets"].update(done=bool(code), repos=[repo.name for repo in code])
    steps["kb_repo"].update(done=kb is not None, **({"repo": kb.name} if kb else {}))
    domains: List[Dict[str, Any]] = []
    if kb is not None:
        kit_folder = kb.path / kbmap.TOOLKIT_DIR
        kit = None
        if (kit_folder / kbmap.TOOLKIT_FILE).is_file():
            try:
                kit = kbmap.load_toolkit(kit_folder)
                steps["toolkit"].update(done=True, name=kit.name)
            except MapError as error:
                steps["toolkit"]["problem"] = str(error)
        covered = [repo.name for repo in code if kit is not None and kbmap.toolkit_for([kit], repo.name)]
        cached = [name for name in covered if kbgraph.cache_file(root, name).is_file()]
        steps["map"].update(done=bool(covered) and len(cached) == len(covered), mapped=cached,
                            **({"no_toolkit": sorted(set(repo.name for repo in code) - set(covered))} if kit is not None and len(covered) < len(code) else {}))
        if deep and kit is not None and cached:
            facts = kbgraph.Graph.load(root, cached).check_facts(kit.facts())
            steps["map"].update(facts=f"{facts['found']}/{facts['checked']}")
            if facts["missing"] or not facts["checked"]:
                steps["map"]["done"] = False
        audit = kit_folder / AUDIT_FILE
        try:
            text = audit.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        steps["audit"].update(done=bool(text and PASSED.search(text) and kit is not None and kit.signature in text),
                              **({"note": say("kbstatus.audit.old")} if text and kit is not None and kit.signature not in text else {}))
        folder = kb.path / "domains"
        try:
            names = sorted(item for item in folder.iterdir() if item.is_dir()) if folder.is_dir() else []
        except OSError:
            names = []
        domains = [domain_state(root, item, deep) for item in names]
        steps["domains"].update(done=bool(domains), count=len(domains))
        steps["learn"].update(done=bool(domains) and all(item["done"] for item in domains))
    steps["maintain"]["done"] = all(steps[name]["done"] for name in STEPS[:-1])
    current = next(name for name in STEPS if not steps[name]["done"]) if not steps["maintain"]["done"] else "maintain"
    learning = next((item for item in domains if not item["done"]), None)
    return {
        "stage": current, "step": STEPS.index(current) + 1, "of": len(STEPS),
        "steps": [{"step": name, **steps[name]} for name in STEPS], "domains": domains,
        "next": say(f"kbstatus.next.{current}", domain=(learning or {}).get("domain", "")) if current != "learn" else learn_next(learning),
        "requests_open": sum(item["requests_open"] for item in domains),
    }


def learn_next(item: Optional[Dict[str, Any]]) -> str:
    if item is None:
        return say("kbstatus.next.maintain")
    if not item["plan"]:
        return say("kbstatus.next.plan", domain=item["domain"])
    if item.get("to_learn"):
        return say("kbstatus.next.batch", domain=item["domain"], left=item["to_learn"], batches=item.get("batches_left", 0))
    return say("kbstatus.next.architecture", domain=item["domain"])
