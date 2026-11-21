# 检查：打开一个任务页为什么要 10–20 秒（测量，不改任何东西）

在公司电脑上做。只读，不改文件，不影响正在跑的任务。每一步拍照发回。

## 第 1 步：Python 这边花了多少时间

1. 在 harness 文件夹里打开 PowerShell（看板可以开着）。
2. 把下面整段复制进去，回车。它会读几次文件、列出任务、为最多 3 个打开的任务生成任务页的数据，每一项打印用了多少毫秒、打开了多少次文件、文件打开一共花了多少毫秒。
3. 拍下输出（大约 12 行）。

```powershell
@'
import builtins, io, os, subprocess, sys, time
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / ".harness" / "engine"))
os.environ.setdefault("HARNESS_LANGUAGE", "en")
print("python", sys.version.split()[0], "| folder", root.name)

# 1. one file: open+read, and stat only
probe = root / ".harness" / "policies" / "target.json"
t = time.perf_counter()
for _ in range(200):
    with open(probe, encoding="utf-8") as handle:
        handle.read()
read_ms = (time.perf_counter() - t) * 1000 / 200
t = time.perf_counter()
for _ in range(200):
    os.stat(probe)
stat_ms = (time.perf_counter() - t) * 1000 / 200
print("1 file: open+read %.2f ms, stat %.3f ms" % (read_ms, stat_ms))

# every open from now on is counted and timed
stats = {"n": 0, "s": 0.0, "proc": 0}
real_open, real_io_open, real_popen = builtins.open, io.open, subprocess.Popen.__init__
def timed(*args, **kwargs):
    t0 = time.perf_counter()
    try:
        return real_open(*args, **kwargs)
    finally:
        stats["n"] += 1
        stats["s"] += time.perf_counter() - t0
def counted(self, *args, **kwargs):
    stats["proc"] += 1
    return real_popen(self, *args, **kwargs)
builtins.open = io.open = timed
subprocess.Popen.__init__ = counted

t = time.perf_counter()
from modules.task import taskdesk, taskhtml, tasklife
print("2 import: %.0f ms" % ((time.perf_counter() - t) * 1000))

def run(label, fn):
    stats.update(n=0, s=0.0, proc=0)
    t0 = time.perf_counter()
    out = fn()
    total = time.perf_counter() - t0
    print("%s: %.0f ms | %d opens, %.0f ms in opens | %d processes" % (label, total * 1000, stats["n"], stats["s"] * 1000, stats["proc"]))
    return out

rows = run("3 list all tasks", lambda: tasklife.list_tasks(root, True)["tasks"])
names = [row["name"] for row in rows if row.get("status") == "open"][:3] or [row["name"] for row in rows][:1]
print("   %d tasks, %d open" % (len(rows), sum(1 for row in rows if row.get("status") == "open")))
for name in names:
    found = run("4 task page data, first  (%s)" % name[:24], lambda: taskdesk.desk(root, name, ("send",), False))
    run("  task page data, again  (%s)" % name[:24], lambda: taskdesk.desk(root, name, ("send",), False))
html = taskhtml.desk_page(found, {"actions": ["send"], "refresh": 3, "run_kinds": [], "user": "", "version": ""})
print("5 page size: %d KB" % (len(html.encode("utf-8")) // 1024))
'@ | py -
```

如果提示找不到 `py`，把最后一行的 `py -` 换成 `python -` 再试一次。

## 第 2 步：浏览器这边花了多少时间

1. 在看板里打开一个任务页（和平常一样，会开一个新标签）。
2. 在这个任务页上按 `F12`，选 **Network**（网络）页签，勾上 **Disable cache**。
3. 按 `F5` 刷新，等页面完全出来。
4. 拍下 Network 页签最下面那一行（写着 `requests`、`transferred`、`Finish`、`DOMContentLoaded`、`Load`），以及列表最上面那一行（任务名那一行，鼠标停在 **Waterfall** 列上会弹出一个时间分解框，也拍下来）。
5. 再拍一张 **Performance**（性能）页签：点左上角的圆形刷新按钮（Start profiling and reload page），等它停下，拍下面的 **Summary** 饼图（Scripting、Rendering、System、Idle 各多少毫秒）。

## 发回

第 1 步的输出；第 2 步的 3 张照片；再写一句：这次打开任务页大概用了几秒。
