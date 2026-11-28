# harness-watch：harness 现在卡在哪

开在自己的窗口里，每 15 秒刷新一屏：harness 现在的负荷、哪些指标异常；每条异常写着“数据 → 症状 → 可能根因 → 对应的优化项 → 怎么排查”。只读，不改 harness 的任何东西，不往外发数据。**一屏就是一张照片**，拍下来发回。

## 第一次（下载一个文件）

在 PowerShell 里运行，把 `harness-watch.cmd` 下载到桌面：

```powershell
Invoke-WebRequest -Proxy http://127.0.0.1:9000 -OutFile "$env:USERPROFILE\Desktop\harness-watch.cmd" https://raw.githubusercontent.com/Smars-Bin-Hu/copilot-agentic-harness/pc-tests/harness-watch/harness-watch.cmd
```

## 每次

双击桌面上的 **harness-watch.cmd**。

- 第一次它会问 harness 文件夹（里面有 `.harness` 的那个），记住以后就不再问。要换文件夹：删掉 `%USERPROFILE%\harness-watch\folder.txt`。
- 每次启动它先从这里拿最新的监测脚本（拿不到就用上次的），所以以后改了脚本你不用做任何事。
- 按 Ctrl+C 停，再按 Y 关窗口。

看某一条的细节（最近 20 分钟的数、怎么查）：在 PowerShell 里

```powershell
& "$env:USERPROFILE\Desktop\harness-watch.cmd" D:\你的harness文件夹 --detail H1
```

把 `H1` 换成屏上那一条的代号（`R3`、`B2` 这样的）。

## 什么时候拍

1. 5 个任务在干活，监测开了 2 分钟以后，拍一张。
2. 10 个任务时，再拍一张。
3. 20 个任务时（如果有），再拍一张。
4. 屏上有 `!!` 的那条，看一次 `--detail <它的代号>`，拍一张。

照片里要看得清前两行（负荷、头号瓶颈）和每条 `!!` / `!`。如果字是方框、分隔线断成两行、或者画面往下滚，也拍下来发我（那是窗口或字体的问题，我来改）。

## 1.9 发版之前（现在的 1.8.61）

能看到：机器（CPU、内存、起一个进程多久、最忙的进程）、hook 的总时间和“自己判”的比例、同时有几个会话、Copilot 记录里的模型和工具时间。看板内部的数（接口快慢、文件检查、重算、页面卡顿、动作）和 hook 的分段会标“这一版没有”，这是正常的。现在拍一张，当 1.9 之前的底子。

## 它自己花多少

最后一行：每轮几个请求（问看板 1 次）、读了多少字节（只读日志新增的部分）、起了几个进程（只有每 5 分钟一次“起一个进程多久”的测量）、它自己的 CPU 和耗时。记录在 `%TEMP%\harness-watch\`，只留 1 天。

## 不用了

删掉桌面上的 `harness-watch.cmd`、`%USERPROFILE%\harness-watch\` 和 `%TEMP%\harness-watch\`。
