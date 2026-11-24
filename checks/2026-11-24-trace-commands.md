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

---

## 第二部分（第一部分的结果发回以后加的）

第一部分的结果：
- stream 里有这几轮，Copilot 的轮次和 stream 的轮次时间差 0.0 秒，都能配上（C）。所以「整轮只有文字」不是缺数据。
- 公司电脑上 hook 记下的时间比 Copilot 记的晚 3–13 秒（D；Mac 上是 0.1 秒），超出了 3 秒容差，Bash 命令配不上。
- hook 里叫 `Bash`，Copilot 里叫 `powershell`：按名字配调用的地方也配不上。

这一部分看：点开一轮时服务器拿到了什么，Agent actions 的每一行配上了什么。

### 4. 写下第二个脚本

```powershell
@'
# Part 2: what the Agent actions tree and the Earlier rounds answer get for the last rounds. Times, names and counts only.
# Run in the harness folder:  python trace_check2.py <task> [N]
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / ".harness" / "engine"))
from core import copilot_events, tasks  # noqa: E402
from modules.task import chatlive, chatrounds, chatstream, tasktrace  # noqa: E402

S = copilot_events.seconds
task = sys.argv[1].replace("\\", "/").strip("/")
if "/" not in task:
    task = ".workspace/sandbox/tasks/" + task
last = int(sys.argv[2]) if len(sys.argv) > 2 else 2


def hm(x):
    return time.strftime("%m-%d %H:%M:%S", time.localtime(x)) if x else "-"


data = tasks.read(root, task)
turns = [t for t in chatstream.read(root, task)["turns"] if not t.get("sub")]

print("E Earlier rounds: what a click on a round gets")
for n, item in list(enumerate(chatrounds.rounds_of(root, task)))[-last:]:
    found = chatrounds.one(root, task, n)
    try:
        turn = chatstream.turn_of_round(turns, found.get("at"), found.get("prompt"))
        items = chatlive.items_of(turn, False, {}, root) if turn is not None else None
        kinds = Counter(i.get("k") for i in items or [])
        print("  round", n, hm(S(found.get("at"))), "| turn", "yes" if turn else "NO", "| items", None if items is None else len(items), dict(kinds))
    except Exception:  # noqa: BLE001
        print("  round", n, "ERROR")
        print(traceback.format_exc()[-1500:])
    print("    stream_round:", "None" if chatrounds.stream_round(root, task, found) is None else "ok")

print("F Agent actions tree")
try:
    tree = tasktrace.tree(root, task, data)
except Exception:  # noqa: BLE001
    print(traceback.format_exc()[-1500:])
    sys.exit(1)
for node in tree["prompts"][:last]:
    rows = [r for r in node["rows"] if r.get("kind") == "tool"]
    print("  #%s" % node["n"], hm(S(node["at"])), "| turn", "yes" if node.get("turn") else "NO", "| tool rows", len(rows), "| cut", node.get("cut"))
    print("    hook names :", dict(Counter(str(r.get("tool")) for r in rows)))
    print("    with live  :", sum(1 for r in rows if r.get("live")), "| with command:", sum(1 for r in rows if r.get("command")))
    turn = next((t for t in turns if t.get("id") == node.get("turn")), None)
    if turn is not None:
        names = [str((p.get("toolCall") or {}).get("toolName")) for p in turn.get("parts") or [] if p.get("kind") == "toolCall"]
        print("    stream names:", dict(Counter(names)))
'@ | Set-Content -Encoding UTF8 "$env:TEMP\trace_check2.py"
```

### 5. 运行并发回

```powershell
python "$env:TEMP\trace_check2.py" <任务名> 2
```

整段输出拍照发回。

### 怎么读（给 Claude）

- **E**：每一轮 `turn yes`、`items` 有几十个、`stream_round: ok`，那服务器是对的，问题在页面（或者看板进程是旧版本，重启看板后再看一次）。`ERROR` 带出异常，`None` 表示服务器给了退回的样子。
- **F**：每个 prompt 的 `turn`；tool 行里 `with live` 和 `with command` 各有几个；`hook names` 和 `stream names` 对照，看哪些名字两边不一样。

---

## 第三部分（第二部分发回以后加的）

第二部分的结果：现在服务器点开 14:47:36 这一轮，能拿到全部 36 项（E），可截图的时候页面只显示了文字。stream 里同一轮有两份记录，开始时间差 19–39 秒（14:47:17 和 14:47:36，15:11:54 和 15:12:33）。猜测：截图时只有早的那一份，和 Copilot 记的时间差超过 5 秒，配不上；晚的那一份是后来补写的。

### 6. 先看一眼页面

不重启看板，在 Live 顶部 Earlier rounds 里重新点开 14:47:36 那一行。拍照：现在是一个个调用，还是只有文字和一行 `Tools: …`？

### 7. 写下第三个脚本

```powershell
@'
# Part 3: the turns of the task's stream, which chat and id each has, and when its parts were seen. No text of the chat.
# Run in the harness folder:  python trace_check3.py <task>
import json
import sys
import time
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / ".harness" / "engine"))
from core import copilot_events  # noqa: E402
from modules.task import chatstream  # noqa: E402

S = copilot_events.seconds
task = sys.argv[1].replace("\\", "/").strip("/")
if "/" not in task:
    task = ".workspace/sandbox/tasks/" + task


def hm(x):
    return time.strftime("%m-%d %H:%M:%S", time.localtime(x)) if x else "-"


path = chatstream.stream_file(root, task)
print("G stream", path.stat().st_size, "bytes, modified", hm(path.stat().st_mtime))
chats = {}
lines = []
with open(path, encoding="utf-8") as handle:
    for number, line in enumerate(handle, 1):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("k") == "turn":
            chat = str(rec.get("chat"))
            chats.setdefault(chat, "C%d" % (len(chats) + 1))
            lines.append((number, chats[chat], str(rec.get("turn"))[-8:], rec.get("at"), bool(rec.get("sub"))))
for chat, name in chats.items():
    print("  ", name, "=", chat[:12] + "…" + chat[-10:])
print("  line | chat | turn id | startedAt | sub")
for number, name, ident, at, sub in lines:
    print("  %5d | %s | %s | %s | %s" % (number, name, ident, hm(S(at)), sub))
print("H first and last part seen, per turn")
for turn in chatstream.read(root, task)["turns"]:
    stamps = [p.get("t0") for p in turn.get("parts") or [] if p.get("t0")]
    print("  ", chats.get(turn["chat"], "?"), turn["id"][-8:], "| at", hm(S(turn.get("at"))), "| parts", len(turn.get("parts") or []),
          "| seen", hm(min(stamps) / 1000) if stamps else "-", "→", hm(max(stamps) / 1000) if stamps else "-")
'@ | Set-Content -Encoding UTF8 "$env:TEMP\trace_check3.py"
```

### 8. 运行并发回

```powershell
python "$env:TEMP\trace_check3.py" <任务名>
```

整段输出拍照发回。

### 怎么读（给 Claude）

- **G**：stream 里每个 `turn` 记录在第几行、属于哪个 chat（C1、C2……）、id、startedAt。同一轮的两份记录在不同的 chat 里：两个 chat 各是谁（VS Code 的、看板自己 host 的）；行号说明谁先写进文件。
- **H**：每一轮的步骤实际是什么时候看到的。早的那份如果「seen」是 14:47 前后，说明它是边跑边记的；晚的那份 seen 是 `-` 或者很晚，说明是后来补写的。
