"""Policy loading. A policy is .harness/policies/<name>.json; <name>.company.json (the company pack, copied there by `company sync`,
1.7.1) is merged on top, then <name>.override.json (the person's). The person's file wins.

Merge rules: objects merge key by key; anything else in the override replaces the default value (an array is replaced
as a whole); `"<key>+": [...]` appends to the default array `<key>`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .paths import policies_dir

OVERRIDE_SUFFIX = ".override.json"
COMPANY_SUFFIX = ".company.json"
LAYERS = (COMPANY_SUFFIX, OVERRIDE_SUFFIX)  # in the order they are merged
APPEND_MARK = "+"


class OverrideError(ValueError):
    """The override cannot be merged onto the default (for example `+` on something that is not an array)."""


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def is_append_key(key: str) -> bool:
    return len(key) > 1 and key.endswith(APPEND_MARK)


def deep_merge(base: Any, override: Any, path: str = "") -> Any:
    """The override on top of the base. Neither argument is changed."""
    if not isinstance(override, dict):
        return override
    merged: Dict[str, Any] = dict(base) if isinstance(base, dict) else {}
    plain = [(key, value) for key, value in override.items() if not is_append_key(key)]
    appended = [(key[: -len(APPEND_MARK)], value) for key, value in override.items() if is_append_key(key)]
    for key, value in plain:
        merged[key] = deep_merge(merged[key], value, f"{path}{key}.") if key in merged else deep_merge({}, value, f"{path}{key}.")
    for key, value in appended:
        where = f"{path}{key}"
        current = merged.get(key, [])
        if not isinstance(value, list) or not isinstance(current, list):
            raise OverrideError(f"'{where}{APPEND_MARK}' needs an array on both sides (the default and the override)")
        merged[key] = current + value
    return merged


def changes(base: Any, override: Any, path: str = "") -> List[Tuple[str, str, int]]:
    """Where the override touches the base: (dotted path, how, size). `how` is replaced, appended or added.

    `size` is the length of the array that was replaced or appended to, 0 for anything else.
    """
    found: List[Tuple[str, str, int]] = []
    if not isinstance(override, dict):
        return found
    base = base if isinstance(base, dict) else {}
    for key, value in override.items():
        if is_append_key(key):
            name = key[: -len(APPEND_MARK)]
            found.append((path + name, "appended", len(value) if isinstance(value, list) else 0))
        elif key not in base:
            found.append((path + key, "added", 0))
        elif isinstance(base[key], dict) and isinstance(value, dict):
            found += changes(base[key], value, f"{path}{key}.")
        else:
            found.append((path + key, "replaced", len(base[key]) if isinstance(base[key], list) else 0))
    return found


def override_path(root: Path, name: str) -> Path:
    return policies_dir(root) / f"{name}{OVERRIDE_SUFFIX}"


def company_path(root: Path, name: str) -> Path:
    return policies_dir(root) / f"{name}{COMPANY_SUFFIX}"


def _hold(root: Path, found: Dict[str, Any], who: str, error: BaseException) -> Dict[str, Any]:
    """(1.7.38, C13 F2) A part of the systems list could not be made (`who`): the programs that the tool packs and the tools policy name are held (one `broken-` system owns them all) and the card says what failed.
    Left out, those programs would be judged by nobody and pass. The names are read as plain text (`govern.programs`): none of the code that failed is used. Never raises."""
    try:
        from . import govern

        names = sorted(govern.programs(root))
        if names:
            text = f"{who}: {type(error).__name__}: {' '.join(str(error).split())}"[:400]
            return dict(found, systems={**(found.get("systems") or {}), f"broken-{who}": {"reach": {"cli": names}, "env": "none", "broken": text}})
    except Exception:  # noqa: BLE001 - the last net
        pass
    return found


def load_policy(root: Path, name: str) -> Dict[str, Any]:
    found = read_json(policies_dir(root) / f"{name}.json")
    for suffix in LAYERS:
        if name == "tools" and suffix == OVERRIDE_SUFFIX:  # the installed tool packs' systems: after the company pack's, before the person's own (1.7.12)
            try:
                from . import toolpacks

                found = deep_merge(found, toolpacks.rules_layer(root))
            except Exception as error:  # noqa: BLE001 - a broken tool pack must not take the other systems away; `tool pack check` reports it. 1.7.38 (C13 F2): its programs are held, not left unjudged
                found = _hold(root, found, "toolpacks", error) if isinstance(found, dict) else found
        path = policies_dir(root) / f"{name}{suffix}"
        if path.exists():
            found = deep_merge(found, read_json(path))
    if name == "tools" and isinstance(found, dict):  # each server of the company pack or the person's own is a system the gate knows (1.7.10)
        try:
            from . import connections

            made = connections.derived(root, found)
            if made:
                found = dict(found, systems={**made, **(found.get("systems") or {})})
            if found.get("systems"):  # 1.7.38: a system that also guards the hosts of the connections (`reach.also`)
                found = dict(found, systems=connections.widen(root, found["systems"]))
        except Exception as error:  # noqa: BLE001 - a broken server list must not take the gate's hand-written systems away; doctor reports it. 1.7.38 (C13 F2): the programs of the connection types are held below, never left unjudged
            found = _hold(root, found, "connections", error)
        try:  # 1.7.38 (C13 F2): a connection list that cannot be read (bad JSON, wrong shape): the programs of the packs that bring a connection type are held
            from . import connections

            held = connections.broken_systems(root)
            if held:
                found = dict(found, systems={**(found.get("systems") or {}), **held})
        except Exception as error:  # noqa: BLE001 - see above
            found = _hold(root, found, "connection-list", error)
        try:  # 1.7.38 (G-1): a tool pack with a faulty file: every call of its programs is held, never left unjudged
            from . import toolpacks

            held = toolpacks.broken_systems(root)
            if held:
                found = dict(found, systems={**(found.get("systems") or {}), **held})
        except Exception as error:  # noqa: BLE001 - a broken pack must not take the other systems away; doctor reports it. 1.7.38 (C13 F2): its programs are held
            found = _hold(root, found, "toolpack-files", error)
    return found


def policy_or_empty(root: Path, name: str) -> Dict[str, Any]:
    """The policy, or {} when it is missing or broken. For a hook or a setting with defaults: `doctor` reports the break."""
    try:
        found = load_policy(root, name)
    except Exception:  # noqa: BLE001 - fail open: the caller has defaults
        return {}
    return found if isinstance(found, dict) else {}


def whole(value: Any, default: int) -> int:
    """A setting that must be a whole number: the value when it is one, else the default (never raises)."""
    return value if isinstance(value, int) and not isinstance(value, bool) else default
