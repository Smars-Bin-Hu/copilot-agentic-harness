# 检查：board 自己的 agent host（1.8.28，目标 1.8.x-agent-host 验收第 7 条）

背景：board 不再打开 VS Code 窗口。它自己用 `code agent host` 起一个 agent host，用 gh 的登录交给它。身份（连接里存的账号）由 host 自动带上。Mac 上 1–6 条已经过（证据在 `.local/中心设计思想/1.8.x-agent-host/evidence-H8/`）。这里在公司电脑上再走一遍，加上只有 Windows 才能测的几件事。

要用的版本：1.8.28 或更新（含这个目标的那个版本，合进 main 以后才有）。旧的那份不用删，解压到新文件夹也行。

**先关掉 VS Code。** 每一步拍照发回。

## 1. 第一次启动（验收 1）

1. 双击 `Start Harness.cmd`。
2. Enter 页：VS Code 一行是“已安装”和版本号；Copilot 一行如果 host 在第一次准备，有一张卡写“正在准备”和进度。
3. 记下从双击到 Enter 页全绿用了多久。

## 2. Copilot 登录（验收 2）

如果 gh 已经登录，Copilot 一行直接是绿的，显示账号和模型数。拍照即可。

想把登录流程也走一遍（不会动你现有的 gh 登录）：

```powershell
$env:GH_CONFIG_DIR = "$env:TEMP\gh-h8"
& ".\Start Harness.cmd"
```

- Copilot 一行变红“没登录”，旁边有 **Sign in to Copilot**。按它：页面上出现一次性的码和 **Open GitHub**。
- 在浏览器里批准。回到 Enter 页，这一行变绿，有模型数。
- 结束后关掉这个窗口，删掉 `%TEMP%\gh-h8`。

## 3. 发一句话（验收 3）

1. Enter → **New task**，类型 Q&A，模型 **Copilot Fusion**，What to do 写：`Run hostname and whoami in the terminal and tell me both, in one line.`
2. 等 agent 交付（任务变成 to accept）。拍任务页。
3. 看 hooks 有没有触发（这个以前在公司电脑上没测过）：

```powershell
Get-ChildItem .harness\runtime\logs\vscode\*.jsonl | Sort-Object LastWriteTime | Select-Object -Last 1 | Get-Content | ForEach-Object { ($_ | ConvertFrom-Json).event } | Group-Object | Format-Table Name,Count
```

要看到 SessionStart、PreToolUse、Stop。

## 4. 代理、工具目录、证书包（H5）

在同一个任务的聊天里让 agent 跑：

```text
Run these and show the output: where.exe sqlcmd ; echo $env:HTTPS_PROXY ; echo $env:NO_PROXY ; echo $env:REQUESTS_CA_BUNDLE
```

- sqlcmd 找得到，代理是 `http://127.0.0.1:9000`（或你们的代理），NO_PROXY 里有 localhost，证书包是 `.harness\certs\ca-bundle.pem`。
- 然后在 Local 里加一个工具目录（或者重新做一次证书包）：Local 窗口要说 host 已重启，或者在等哪个 chat 干完。

## 5. Windows 账号身份（H5b、H6）

前提：Connections 里有一个用 Windows 账号的 SQL Server 连接，已登录、测试通过。

1. 不用勾任何东西：host 自动带上它。重启 board 或者等 Local 说 host 重启过。
2. 让 agent 跑 `sqlcmd -S <服务器> -E -Q "select suser_name()"`，再让它写一个小 python 脚本用 Windows 认证连同一个库、打印 `suser_name()` 并运行它。两个都要是那个账号，不是你自己的登录账号。
3. Copilot 还能用吗（公司代理如果用 Windows 身份认证，会带上这个账号）：再发一句话，看有没有回复。
4. 只在密码正好过期或改过时做（不要为了测试去改密码）：存着的旧密码会让 host 起不来。Enter 页 Copilot 一行要说 host 起不来，原因看得懂。拍照。
5. 如果有两个不同的 Windows 账号的连接：连接那一行有黄色提示，带 **Choose the main account**。选另一个，host 重启后 agent 用的是新的那个；另一个连接的调用 agent 每次单独登录（`harness as`）。

## 6. 快捷命令新装上（H6）

只在 `harness` 命令还不在 PATH 上时做：Get ready 里装上它，不重启 board。等 Local 或 Enter 页说 host 重启过，让 agent 跑 `harness --version`：要能跑。

## 7. 停止

1. 按 board 右上角的电源按钮停掉 board。
2. 任务管理器里看：`code-tunnel` / `Code` 的 agent host 进程会再留一会儿（它没有客户端后自己结束），再次启动 board 会接上它。
3. 重启电脑，再双击 Start Harness（验收 4）：不用再登录，Copilot 一行直接绿。

## 8. VS Code 升级以后（验收 5）

下次 VS Code 升级后第一次启动：Enter 页又显示“正在准备”和进度，完了照常可用。拍照。

## 发回

- 每一步的照片；第 1 步的时间；第 3 步 hooks 的那张表。
- 哪一步不对，拍下 Enter 页和 `.harness\runtime\board.log` 的最后几十行。
