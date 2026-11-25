# 检查：板子上一个新任务停在「The agent is opening the task」半小时

板子建了 chat、发了第一条消息后，就显示 *The agent is opening the task*。要等到出现一个**同名**任务才消失，最长等 1 小时。这段时间板子不看 chat 实际在干什么。所以先在公司电脑上看清楚：那个 chat 到底停在哪。

可能是：
1. agent 在问你问题，或在等你批准一条命令。
2. 第一轮已经结束，但没建任务（出错、被拒、或它停下来问你）。
3. 任务建了，但名字不一样，板子配不上。
4. 第一轮还在跑，卡在某一步（比如一个很慢的 hook 或命令）。
5. chat 根本没收到第一条消息。

脚本只读文件，不改任何东西。

## 1. 先看 VS Code

在 VS Code 的 chat 列表里找标题是这个任务名的 chat（或最新的那个），打开它，拍一张能看到最后几条的照片。

## 2. 写下脚本

在 harness 文件夹里打开 PowerShell，整段粘贴：

```powershell
@'
# Why a task the board made a chat for never appeared ("The agent is opening the task").
# Run in the harness folder:  python stuck_check.py "<task name>" [hours]
import json
import sys
import time
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / ".harness" / "engine"))
from core import copilot_events, logs  # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else ""
hours = float(sys.argv[2]) if len(sys.argv) > 2 else 6
since = time.time() - hours * 3600
S = copilot_events.seconds


def short(value, n=160):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n] + "..."


def clock(at):
    return time.strftime("%H:%M:%S", time.localtime(at)) if at else "?"


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(text_of(item.get("text") if isinstance(item, dict) else item) for item in content)
    return ""


state = copilot_events.home() / "session-state"
recent = []
for folder in state.iterdir() if state.is_dir() else []:
    ev = folder / "events.jsonl"
    try:
        if ev.is_file() and ev.stat().st_mtime >= since:
            recent.append(ev)
    except OSError:
        pass
print("== A. Copilot sessions changed in the last %g h: %d" % (hours, len(recent)))
found = []
for ev in recent:
    with open(ev, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"user.message"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if name and ("Task name: " + name) in text_of((row.get("data") or {}).get("content")):
                found.append(ev)
            break
print("   with 'Task name: %s' in the first message: %d" % (name, len(found)))
if not found:
    print("   (none: the chat never got its first message, or the name differs)")
    for ev in sorted(recent, key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
        print("   newest:", ev.parent.name, clock(ev.stat().st_mtime))

for ev in found:
    sid = ev.parent.name
    rows = []
    with open(ev, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    counts = {}
    for row in rows:
        counts[row.get("type")] = counts.get(row.get("type"), 0) + 1
    first, last = S(rows[0].get("timestamp")) if rows else None, S(rows[-1].get("timestamp")) if rows else None
    print("\n== B. session", sid)
    print("   first %s | last %s | %d events | last event %.1f min ago" % (clock(first), clock(last), len(rows), (time.time() - last) / 60 if last else -1))
    print("   counts:", ", ".join("%s %d" % (k, v) for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))
    starts = sum(1 for r in rows if r.get("type") == "assistant.turn_start")
    ends = sum(1 for r in rows if r.get("type") == "assistant.turn_end")
    print("   turns started %d, ended %d -> %s" % (starts, ends, "a turn is still open" if starts > ends else "no turn running"))
    print("   -- last 30 events")
    for row in rows[-30:]:
        kind, data, at = row.get("type"), row.get("data") or {}, S(row.get("timestamp"))
        extra = ""
        if kind == "tool.execution_start":
            extra = "%s %s" % (data.get("toolName"), short(copilot_events.command_of(data.get("arguments")) or data.get("arguments"), 140))
        elif kind == "tool.execution_complete":
            result = data.get("result") or {}
            extra = "success=%s %s" % (data.get("success"), short(result.get("content") if isinstance(result, dict) else result, 200))
        elif kind == "assistant.message":
            extra = short(text_of(data.get("content")), 200)
        elif kind in ("permission.requested", "permission.completed", "skill.invoked", "hook.end", "session.start"):
            extra = short({k: v for k, v in data.items() if k not in ("content", "transcriptPath")}, 200)
        elif "error" in str(kind) or "abort" in str(kind) or "warning" in str(kind):
            extra = short(data, 300)
        print("   %s %-28s %s" % (clock(at), kind, extra))
    path = logs.session_log_path(root, "vscode", sid)
    hook_rows = logs.read_lines(path) if path.is_file() else []
    print("   -- hook log: %d rows (%s)" % (len(hook_rows), path.name))
    for row in hook_rows[-15:]:
        target = row.get("target") or {}
        print("   %s %-18s %-10s %-8s %s %s" % (str(row.get("at", ""))[11:19], row.get("event", ""), row.get("tool_name") or row.get("tool") or "",
                                             row.get("decision") or "", short(target.get("command") or "", 80), short(row.get("reason") or "", 120)))

print("\n== C. task folders changed in the last %g h" % hours)
tasks = root / ".workspace" / "sandbox" / "tasks"
for folder in sorted(tasks.iterdir()) if tasks.is_dir() else []:
    try:
        if folder.is_dir() and folder.stat().st_mtime >= since:
            print("  ", folder.name, clock(folder.stat().st_mtime), "TASK.md" if (folder / "TASK.md").is_file() else "no TASK.md")
    except OSError:
        pass

print("\n== D. hook errors in the last %g h" % hours)
errors = root / ".harness" / "runtime" / "logs" / "hook-errors.jsonl"
for row in (logs.read_lines(errors) if errors.is_file() else [])[-50:]:
    at = S(row.get("at"))
    if at and at >= since:
        print("  ", clock(at), short(row.get("where"), 40), short(row.get("error"), 200))
'@ | Set-Content -Encoding UTF8 stuck_check.py
```

## 3. 运行

把 `<任务名>` 换成板子上那一行的名字：

```powershell
$env:PYTHONIOENCODING = "utf-8"
python stuck_check.py "<任务名>" 6
```

最后一个数是往回看几个小时。chat 是更早建的，就把 6 改大。

## 4. 发回来

- 第 1 步的照片。
- 第 3 步的全部输出（太长就分几张拍）。
- 板子上那一行现在还在不在，钟走到多少。

## 怎么读

- **A 段**：找到 0 个 session → 第 5 种，或名字不一样（看 C 段有没有新任务）。
- **B 段** `turns started / ended`：
  - `a turn is still open`，最后一个事件就在几分钟内 → 第 4 种，看最后几行卡在哪个工具上。
  - `a turn is still open`，但最后一个事件是很久以前 → 卡住了。看最后是 `permission.requested`（等批准）还是 `hook.start` 没有 `hook.end`（hook 卡住）。
  - `no turn running` → 第一轮结束了。看最后一条 `assistant.message`：它在问你（第 1、2 种），还是说任务建好了（第 3 种）。
- B 段里的 `harness task new` 那一行，`success=` 和后面的输出说明建任务这一步本身成没成功。
- **B 段的 hook log**：有 `deny` 或 `ask` 的行 → 门挡住了某一步。
- **C 段**：最近建的任务文件夹。有一个名字相近的 → 第 3 种。
- **D 段**：hook 自己的报错。
- 运行完删掉：`Remove-Item stuck_check.py`
