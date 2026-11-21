# 检查：不开 VS Code 窗口，VS Code 自带的 agent host 能不能启动（1.9 的另一条路）

背景：公司的策略关了 Copilot CLI，所以 SDK 直连被挡（见 `2026-11-21-copilot-sdk.md`）。VS Code 自带一个可以独立运行的 agent host（`code agent host`），不用开编辑器窗口，board 现有的连接方式就能连它。Mac 上已经跑通。

这次只想弄清楚两件事：

1. 公司电脑上 `code agent host` 能不能启动。它第一次启动要下载一个 server 包，要看能不能穿过代理。
2. 一个普通的程序能不能连上它，看到 Copilot 这个 agent。

**这次不登录，不发送任何 token，也不会用到 Copilot 额度。** VS Code 开着或关着都可以：探针用的是自己的文件夹，不碰正在用的 VS Code。

## 第 1 步：取探针脚本

在 PowerShell 里运行（不用进 harness 文件夹，也不需要之前那个虚拟环境）：

```powershell
Invoke-WebRequest -Proxy http://127.0.0.1:9000 -OutFile "$env:USERPROFILE\agent-host-probe.py" `
  https://raw.githubusercontent.com/Smars-Bin-Hu/copilot-agentic-harness/pc-tests/checks/2026-11-21-agent-host-probe.py
```

脚本只用 Python 标准库，什么都不用装。

## 第 2 步：运行

```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:9000"
$env:HTTP_PROXY  = "http://127.0.0.1:9000"
python "$env:USERPROFILE\agent-host-probe.py"
```

- 第一次运行要下载 server 包，最多等 5 分钟。公司电脑启动进程慢，耐心等。
- 拍下全部输出。Mac 上的样子是：

  ```text
  [1] OK    Python 3.9.6, darwin
  [2] OK    VS Code 1.147.0 at ...
        host: ... Downloading server ...
        host: ... ready in 12065ms
  [3] OK    agent host started with no editor window in 13 s (kind standalone, protocol 0.1.0)
  [4] OK    connected; the host speaks protocol 1.1.0
        agent copilotcli: 0 models, sign-in required for: GitHub Copilot
  [5] OK    the Copilot agent is offered: True (0 models is right here: nobody signed in)
        stop: Killed agent host (pid ...).
  ```

- `0 models` 是对的：这次没有登录。
- 如果 `[3]` 失败，脚本会打印 agent host 最后的十几行输出，一起拍下来。常见原因是 server 包下载不了。
- 如果不设代理变量也想试一次：新开一个 PowerShell 窗口，直接运行最后那一行。两种结果都告诉我。

## 第 3 步：再跑一次，看第二次要多久

```powershell
python "$env:USERPROFILE\agent-host-probe.py"
```

第二次不用再下载。拍下 `[3]` 那一行的秒数：这就是以后每次启动要等的时间。

## 发回

- 第 2、3 步的照片。
- 运行时 VS Code 是开着还是关着。
- 做完后可以删掉 `%USERPROFILE%\agent-host-probe` 文件夹和 `%USERPROFILE%\agent-host-probe.py`。脚本结束时已经把它启动的 agent host 停掉了。
