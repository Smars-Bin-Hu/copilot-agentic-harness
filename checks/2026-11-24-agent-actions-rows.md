# 检查：Agent actions 里三个 `Edit · stopped` 没有路径，被拦命令的原因里少了反斜杠

现象（2026-11-24，公司电脑，1.8.46）：
- 一个 qa 任务的第 1 轮，17:33:18、17:33:19、17:33:21 三行 `Edit · stopped`，没有路径、没有时长；17:33:23 一行 `Edit · 7.0 s` 带路径。这一轮没有被停过。
- 第 2 轮里被 gate 拦下（held）的那条 `sqlcmd … -o "$env:TEMP\…"`，原因里显示成 `$env:TEMPusp_…`，反斜杠没了，开头的反引号露在外面。

要知道的：
- **Edit**：hook 只记了开始、没有记结束，这三次调用在 Copilot 的记录里是什么：失败了（报什么错），被取消了，还是根本不是 Edit。
- **反斜杠**：hook 日志里存的命令和原因本来就没有 `\`（gate 拆命令时丢的），还是日志里有、页面显示时丢的。
- **覆盖面**（为下一个版本「每一行都显示具体内容」做准备）：每种工具的行，有多少能配上看板的 stream，配上的有没有可显示的目标。

脚本只打印时间、工具名、数量和是否有某个字符。错误信息只打印前 60 个字。

## 1. 写下脚本

在 harness 文件夹里打开 PowerShell，整段粘贴：

```powershell
@'
# Why three Edit rows are "stopped" with no path, where a backslash of a held command went, and how many rows of each tool get a target.
# Times, tool names, counts and short error starts only. Run in the harness folder:  python rows_check.py <task> <HH:MM> [minutes]
import json
import sys
import time
from collections import Counter
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / ".harness" / "engine"))
from core import copilot_events, redact, registry, tasks  # noqa: E402
from modules.task import common, taskinsight, tasktrace  # noqa: E402

S = copilot_events.seconds
task = sys.argv[1].replace("\\", "/").strip("/")
if "/" not in task:
    task = ".workspace/sandbox/tasks/" + task
clock = sys.argv[2] if len(sys.argv) > 2 else ""
span = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0


def hm(x):
    return time.strftime("%m-%d %H:%M:%S", time.localtime(x)) if x else "-"


def short(text, n=60):
    flat = " ".join(redact.text(str(text or "")).split())
    return flat[:n] + ("…" if len(flat) > n else "")


data = tasks.read(root, task)
if data is None:
    sys.exit("no such task: " + task)
print("A version", registry.harness_version(root), "| python", sys.version.split()[0], "| copilot_events", taskinsight.events_allowed(root))
info = taskinsight.of_task(root, task, None, True)
surface = str(data.get("surface") or "vscode")

for sess in info["sessions"]:
    sid = str(sess.get("session_id") or "")
    rows = common.read_session(root, surface, sid)
    stamps = [S(r.get("at")) for r in rows if S(r.get("at"))]
    if not stamps:
        continue
    lo = hi = None
    if clock:
        day = time.localtime(stamps[-1])
        hh, mm = (int(x) for x in clock.split(":"))
        lo = time.mktime((day.tm_year, day.tm_mon, day.tm_mday, hh, mm, 0, 0, 0, -1)) - 30
        hi = lo + 60 * span + 30
    inside = lambda x: x is not None and (lo is None or lo <= x <= hi)  # noqa: E731
    print("B session", sid[:8], "| hook lines", len(rows))
    for r in rows:
        at = S(r.get("at"))
        if not inside(at) or r.get("event") not in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            continue
        target = r.get("target") if isinstance(r.get("target"), dict) else {}
        print("   ", hm(at), str(r.get("event"))[:18].ljust(18), str(r.get("tool_name"))[:22].ljust(22), "kind", str(r.get("tool_kind") or "-")[:8],
              "| paths", len(target.get("paths") or []), "| decision", r.get("decision") or "-", "| sub" if r.get("from_subagent") else "",
              ("| error " + short(r.get("error"))) if r.get("error") else "")
    held = [r for r in rows if r.get("event") == "PreToolUse" and r.get("decision") in ("deny", "ask")]
    print("C held or refused lines", len(held))
    for r in held[-6:]:
        target = r.get("target") if isinstance(r.get("target"), dict) else {}
        cmd, why = str(target.get("command") or ""), str(r.get("reason") or "")
        print("   ", hm(S(r.get("at"))), str(r.get("tool_name"))[:12], "| command: \\ x%d, ` x%d, \" x%d" % (cmd.count("\\"), cmd.count("`"), cmd.count('"')),
              "| reason: \\ x%d, ` x%d, \" x%d" % (why.count("\\"), why.count("`"), why.count('"')))
    ev = copilot_events.events_path(sid)
    print("D events.jsonl", "yes %d bytes" % ev.stat().st_size if ev else "NO")
    if ev:
        names = {}
        with open(ev, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"tool.execution_' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                kind, body, at = row.get("type"), row.get("data") or {}, S(row.get("timestamp"))
                ident = str(body.get("toolCallId") or "")
                if kind == "tool.execution_start":
                    names[ident] = str(body.get("toolName") or "")
                    if inside(at):
                        given = body.get("arguments") if isinstance(body.get("arguments"), dict) else {}
                        print("    start   ", hm(at), names[ident][:28].ljust(28), "| argument keys", ",".join(sorted(given))[:80])
                elif kind == "tool.execution_complete" and inside(at):
                    error = body.get("error")
                    said = error.get("message") if isinstance(error, dict) else error
                    print("    complete", hm(at), names.get(ident, "?")[:28].ljust(28), "| success", body.get("success"), ("| error " + short(said)) if said else "")

print("E Agent actions rows: how many of each tool have something to show")
tree = tasktrace.tree(root, task, data)
count = Counter()
for node in tree["prompts"]:
    for r in node["rows"]:
        if r.get("kind") != "tool":
            continue
        live = r.get("live") or {}
        name = str(r.get("tool"))
        count[(name, "all")] += 1
        count[(name, "live")] += bool(live)
        count[(name, "target")] += bool(live.get("target") or live.get("word"))
        count[(name, "command")] += bool(r.get("command"))
        count[(name, "paths")] += bool(r.get("paths"))
        count[(name, "stopped")] += bool(r.get("stopped"))
for name in sorted({k[0] for k in count}):
    print("   ", name[:24].ljust(24), " ".join("%s %d" % (what, count[(name, what)]) for what in ("all", "live", "target", "command", "paths", "stopped")))
'@ | Set-Content -Encoding UTF8 "$env:TEMP\rows_check.py"
```

## 2. 运行

`<任务名>` 换成那个任务的文件夹名。`17:32` 是从几点几分开始看，`3` 是看几分钟。

```powershell
python "$env:TEMP\rows_check.py" <任务名> 17:32 3
```

`python` 找不到就换成 `py`。

## 3. 发回

整段输出拍照发回。出错的话，把报错也拍下来。

## 怎么读（给 Claude）

- **B**：这几分钟里 hook 的每一行。三个 Edit 若只有 `PreToolUse`、没有 `PostToolUse*`，就是 hook 没看到结束；`paths 0` 在 Pre 行上是正常的（1.8.46 只在 Post 行存路径）。
- **C**：被拦行的命令和原因里各有几个 `\`、`` ` ``、`"`。命令里 `\ x1` 而原因里 `\ x0`：gate 写原因时丢的。两边都有：页面显示时丢的。
- **D**：Copilot 记录里同一段时间的调用。看 17:33:18–21 那几次的 `toolName`、`success` 和错误开头：`success False` 加一个错误，说明是失败的编辑，应该显示成红色「失败 + 原因」，而不是 `stopped`；同名但 `argument keys` 不同，说明是另一种编辑工具。
- **E**：整个任务里每种工具的行数（all），配上 stream 的（live），有目标可显示的（target），有命令的（command），有路径的（paths），标成 stopped 的。`live` 远小于 `all` 的工具，就需要别的来源（Copilot 记录或 hook 日志）补内容。

---

## 结果（2026-11-24 发回）

- **三个 `stopped` 的 Edit 都成功了。** Copilot 在 17:32:57 同时发出 7 个 `edit`，7 个都 `success True`。hook 一个一个跑：7 个 Pre 在 17:33:18–25（比 Copilot 晚 21–28 秒），7 个 Post 在 17:33:30–17:34:24，每个都带路径。错在 Agent actions 把 Post 配给 Pre 的方式：同名的调用，开始时间相差超过 3 秒（`SAME_CALL_S`）就不再算同一批，早的三个被丢下，没配上结束，于是成了 `stopped`。修法放在 1.8.47。
- **反斜杠**：hook 日志里命令有 1 个 `\`，原因里有 2 个。页面把原因当纯文本显示，不会吃掉它，所以丢的是原因开头 gate 自己拼出来的那段：gate 把命令拆成词再用空格拼回去，引号和 `\` 都没了。修法放在 1.8.47。
- **覆盖面**：Bash 31 行里 29 行配上了 stream，Edit 12 行里 9 行，Grep 1/1，skill 2/1，而且 skill 配上的那一行也没有目标。所以 stream 是主要来源，skill 名和没配上的行要从 Copilot 记录和 hook 日志补。
- Copilot 记录里工具名是 `powershell`、`edit`（参数 `path, old_str, new_str`），hook 里是 `Bash`、`Edit`。
