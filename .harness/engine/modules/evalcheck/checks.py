"""Run the checks of one scenario against one finished run. Reads only; every answer is yes or no with a reason."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.logs import read_lines, session_files


def check_result(name: str, ok: bool, detail: str = "") -> Dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


# --- which run ------------------------------------------------------------------------------------


def newest_session(root: Path, surface: str) -> Optional[Tuple[str, str]]:
    """The newest session that is a main session (no parent). A subagent's own session is never the run."""
    for found_surface, path in reversed(list(session_files(root))):
        if surface and found_surface != surface:
            continue
        rows = read_lines(path)
        if rows and not any(row.get("parent_session_id") for row in rows):
            return found_surface, path.stem
    return None


def session_rows(root: Path, surface: str, session_id: str) -> List[Dict[str, Any]]:
    """The calls of the session and of the sessions of its subagents (SDK engine), in time order."""
    rows: List[Dict[str, Any]] = []
    for found_surface, path in session_files(root):
        if found_surface != surface:
            continue
        own = read_lines(path)
        if path.stem == session_id or (own and own[0].get("parent_session_id") == session_id):
            rows.extend(own)
    return sorted(rows, key=lambda row: row.get("at", ""))


def row_matches(row: Dict[str, Any], match: Dict[str, Any]) -> bool:
    for key, wanted in match.items():
        if key == "by":
            if wanted not in (row.get("by") or []):
                return False
        elif key == "reason_contains":
            if wanted not in (row.get("reason") or ""):
                return False
        elif key == "target_contains":
            target = row.get("target") or {}
            # Windows paths hold "\" and tool calls can give either kind: compare with "/" on both sides.
            wanted_text = wanted.replace("\\", "/")
            if not any(wanted_text in text.replace("\\", "/") for text in list(target.get("paths", [])) + [target.get("command", "")]):
                return False
        elif row.get(key) != wanted:
            return False
    return True


def describe(match: Dict[str, Any]) -> str:
    return "、".join(f"{key}={value}" for key, value in match.items()) or "任何行"


def check_calls(rows: List[Dict[str, Any]], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for item in items:
        count = sum(1 for row in rows if row_matches(row, item["match"]))
        if "exactly" in item:
            low = high = item["exactly"]
        else:
            high = item.get("max")
            low = item.get("min", 0 if high is not None and "min" not in item else 1)
        ok = count >= low and (high is None or count <= high)
        wanted = f"恰好 {low}" if low == high else f"{low} 到 {high}" if high is not None and low else f"最多 {high}" if high is not None else f"至少 {low}"
        results.append(check_result(item["name"], ok, f"匹配 {describe(item['match'])} 的有 {count} 行，要求{wanted}。"))
    return results


def check_order(rows: List[Dict[str, Any]], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for item in items:
        position, missing = 0, None
        for step in item["steps"]:
            while position < len(rows) and not row_matches(rows[position], step):
                position += 1
            if position >= len(rows):
                missing = step
                break
            position += 1
        ok = missing is None
        results.append(check_result(item["name"], ok, "顺序对。" if ok else f"找不到按顺序出现的这一步：{describe(missing or {})}。"))
    return results


# --- files and json -------------------------------------------------------------------------------


def check_files(root: Path, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for item in items:
        exists = (root / item["path"]).exists()
        results.append(check_result(f"文件：{item['path']}", exists == item["exists"], "存在。" if exists else "不存在。"))
    return results


def dig(data: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def check_json(root: Path, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for item in items:
        name = f"JSON：{item['file']} 的 {item['path']}"
        try:
            value = dig(json.loads((root / item["file"]).read_text(encoding="utf-8-sig")), item["path"])
        except (OSError, ValueError) as error:
            results.append(check_result(name, False, f"读不了：{error}"))
            continue
        if "equals" in item:
            results.append(check_result(name, value == item["equals"], f"值是 {value!r}，要求等于 {item['equals']!r}。"))
        else:
            results.append(check_result(name, value != item["not_equals"], f"值是 {value!r}，要求不等于 {item['not_equals']!r}。"))
    return results


# --- one scenario ---------------------------------------------------------------------------------


def run(root: Path, scenario: Dict[str, Any], surface: str, session_id: str) -> Dict[str, Any]:
    expect = scenario["expect"]
    if not session_id:
        picked = newest_session(root, surface)
        if picked is None:
            raise ValueError("没有找到会话日志。先在 Copilot 里跑一遍场景，或用 --session-id 指定。")
        surface, session_id = picked
    rows = session_rows(root, surface, session_id)
    if not rows:
        raise ValueError(f"会话 `{session_id}` 在 {surface} 下没有日志。检查 id（`harness stats` 能列出日志在不在），或日志是否被清理。")
    results = check_calls(rows, expect.get("calls", [])) + check_order(rows, expect.get("order", []))
    results += check_files(root, expect.get("files", [])) + check_json(root, expect.get("json", []))
    failed = [item for item in results if not item["ok"]]
    return {
        "scenario": scenario["id"],
        "passed": not failed,
        "failed": len(failed),
        "checks": results,
        "session": {"surface": surface, "session_id": session_id, "calls": len(rows)},
        "manual_checks": scenario["manual"],
        "note": "通过只代表确定性检查全部满足。人工检查项要你自己看。",
    }
