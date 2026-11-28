# 监测：harness 现在卡在哪（`harness-watch.py`）

一个独立的小程序，开在自己的 PowerShell 窗口里，每 15 秒刷新一屏：harness 现在的负荷、哪些指标异常；每条异常写着“数据 → 症状 → 可能根因 → 对应的优化项 → 怎么排查”。它只读，不改 harness 的任何东西，不往外发数据。

拍照发回就行：**一屏就是一张照片。**

## 准备（一次）

在 PowerShell 里下载脚本（只用 Python 标准库，什么都不用装）：

```powershell
Invoke-WebRequest -Proxy http://127.0.0.1:9000 -OutFile "$env:USERPROFILE\harness-watch.py" `
  https://raw.githubusercontent.com/Smars-Bin-Hu/copilot-agentic-harness/pc-tests/tools/harness-watch.py
```

## 运行

在 harness 文件夹里，开一个**新的** PowerShell 窗口（别用跑看板的那个），窗口拉宽一点（至少 100 列）：

```powershell
python "$env:USERPROFILE\harness-watch.py" .
```

- 它每 15 秒原地刷新。按 Ctrl+C 停。
- 想看某一条的细节（最近 20 分钟的数和怎么查），另开一个窗口：

```powershell
python "$env:USERPROFILE\harness-watch.py" . --detail H1
```

  把 `H1` 换成屏上那一条的代号（`R3`、`B2` 这样的）。

## 什么时候拍

1. 开着 5 个任务在干活，监测跑了 2 分钟以后，拍一张。
2. 10 个任务时，再拍一张。
3. 20 个任务时（如果有），再拍一张。
4. 屏上有 `!!` 的那条，跑一次 `--detail <它的代号>`，拍一张。

照片里要看得清第一、二行（负荷、头号瓶颈）和每条 `!!` / `!`。

## 1.9 发版之前（现在的 1.8.61）

能看到的只有：机器（CPU、内存、起一个进程多久、最忙的进程）、hook 的总时间和“自己判”的比例、同时有几个会话、Copilot 记录里的模型和工具时间。看板内部的数（接口快慢、文件检查、重算、页面卡顿、动作）会标“这一版没有”，hook 的分段（排队、起进程、判断）也是。这是正常的。现在拍一张，可以当 1.9 之前的底子。

## 它自己花多少

最后一行写着：每轮几个请求（问看板 1 次）、读了多少字节（只读日志新增的部分）、起了几个进程（只有每 5 分钟一次“起一个进程多久”的测量）、它自己的 CPU。记录文件在 `%TEMP%\harness-watch\`，只留 1 天。

## 用完

关掉窗口就行。可以删掉 `%USERPROFILE%\harness-watch.py` 和 `%TEMP%\harness-watch\`。
