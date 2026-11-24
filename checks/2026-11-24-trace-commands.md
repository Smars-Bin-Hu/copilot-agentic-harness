# 检查：Agent actions 里 Bash 没有命令，Live 里旧的一轮只有文字

现象（2026-11-24，公司电脑）：
- Agent actions 里，一个 prompt 下的 Bash 行没有命令，Grep 等行点不开。
- Live 顶部 Earlier rounds 打开这一轮，只有 agent 的文字和一行 `Tools: powershell × 8, …`，没有一个个可以点开的调用。

两件事都要看板把两份记录配上：
- **Bash 的命令**：hook 日志里的一次调用，和 Copilot 的 `events.jsonl` 里开始时间相差不超过 3 秒的那条命令，算同一次调用。
- **整轮的调用**：Copilot 记录里的一轮，和看板自己存的 `.task/stream.jsonl` 里开始时间相差不超过 5 秒的那一轮，算同一轮。

在 Mac 上两边只差约 0.1 秒。这次要知道公司电脑上差多少，或者 stream 里到底有没有这一轮。

脚本只打印时间和数量，不打印聊天内容。

## 1. 写下脚本

在 harness 文件夹里打开 PowerShell，整段粘贴：

```powershell
@'
# Why a round shows no calls, and why Bash rows show no command. Prints times and counts only, no text of the chat.
# Run in the harness folder:  python trace_check.py <task>
import sys
import time
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / ".harness" / "engine"))
from core import copilot_events, registry, tasks  # noqa: E402
from modules.task import chatrounds, chatstream, common, taskinsight  # noqa: E402

S = copilot_events.seconds
task = sys.argv[1].replace("\\", "/").strip("/")
if "/" not in task:
    task = ".workspace/sandbox/tasks/" + task
last = int(sys.argv[2]) if len(sys.argv) > 2 else 3  # the last N rounds


def hm(x):
    return time.strftime("%m-%d %H:%M:%S", time.localtime(x)) if x else "-"


def gap(a, b):
    return "-" if a is None or b is None else "%+.1f" % (b - a)


data = tasks.read(root, task)
if data is None:
    sys.exit("no such task: " + task)
print("A version", registry.harness_version(root), "| python", sys.version.split()[0], "| copilot_events", taskinsight.events_allowed(root))

path = chatstream.stream_file(root, task)
size = path.stat().st_size if path.is_file() else -1
found = chatstream.read(root, task)
turns = [t for t in found["turns"] if not t.get("sub")]
print("B stream bytes", size, "| main turns", len(turns), "| sub turns", len(found["turns"]) - len(turns), "| skipped", found["skipped"], "| cut", found["cut"])
for t in turns[-(last + 2):]:
    parts = t.get("parts") or []
    calls = sum(1 for p in parts if p.get("kind") == "toolCall")
    print("  turn", hm(S(t.get("at"))), "| parts", len(parts), "| calls", calls, "| state", t.get("state") or "(no end)")

live = chatrounds.live(data)
rounds = chatrounds.rounds_of(root, task)
print("C rounds", len(rounds), "| from", "copilot" if live else "stream")
for item in rounds[-last:]:
    at = S(item.get("at"))
    near = min(turns, key=lambda t: abs((S(t.get("at")) or 0) - (at or 0)), default=None)
    match = chatstream.turn_of_round(turns, item.get("at"), item.get("prompt"))
    print("  round", hm(at), "| tools", len(item.get("tools") or []), "| nearest turn", hm(S(near.get("at"))) if near else "-",
          "gap", gap(at, S(near.get("at")) if near else None), "| matched", "yes" if match else "NO")

info = taskinsight.of_task(root, task, None, True)
print("D sessions", len(info["sessions"]))
for sess in info["sessions"]:
    sid = str(sess.get("session_id") or "")
    ev = copilot_events.events_path(sid)
    print("  session", sid[:8], "| events.jsonl", "yes %d bytes" % ev.stat().st_size if ev else "NO")
    record = copilot_events.read(ev, 0, True) if ev else None
    cmds = [c for p in (record or {}).get("prompts") or [] for c in p.get("commands") or []]
    hooks = [r for r in common.read_session(root, str(data.get("surface") or "vscode"), sid) if r.get("event") == "PreToolUse" and r.get("tool_name")]
    starts = [(S(r.get("at")), str(r.get("tool_name"))) for r in hooks]
    starts = [x for x in starts if x[0] is not None]
    print("  commands in events", len(cmds), "| hook calls", len(starts))
    for c in cmds[-12:]:
        t = S(c["at"]) if not isinstance(c["at"], (int, float)) else float(c["at"])
        h = min(starts, key=lambda x: abs(x[0] - t), default=None)
        print("   ", hm(t), c["name"][:16], "| nearest hook", hm(h[0]) if h else "-", (h[1][:12] if h else ""), "gap", gap(t, h[0] if h else None))
'@ | Set-Content -Encoding UTF8 "$env:TEMP\trace_check.py"
```

## 2. 运行

`<任务名>` 换成那个任务的文件夹名（`.workspace\sandbox\tasks\` 下面的名字）。最后的 `3` 是看最近几轮，想多看就改大。

```powershell
python "$env:TEMP\trace_check.py" <任务名> 3
```

`python` 找不到就换成 `py`。

## 3. 发回

把整段输出拍照发回。出错的话，把报错也拍下来。

## 怎么读（给 Claude）

- **A**：版本，Python，`copilot_events`（False 表示策略关了，Bash 命令只能靠 stream）。
- **B**：`stream bytes -1` 表示文件不存在；后面列最近几轮的开始时间、part 数、调用数。看板没连着 chat 时跑的轮次、而且之后补写也没成功，就不在这里。
- **C**：`from copilot` 或 `stream`；每一轮离它最近的 stream 轮次和时间差 `gap`；`matched NO` 而 gap 在几秒到几十秒，说明是 5 秒容差太紧；没有 nearest turn，说明 stream 里没有这一轮。
- **D**：每个会话的 `events.jsonl` 在不在；最近 12 条命令和离它最近的 hook 调用的时间差。大多数 gap 超过 3 秒，说明是 3 秒容差太紧（hook 在公司电脑上慢）。
