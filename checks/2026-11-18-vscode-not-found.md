# 检查：VS Code 开着，看板一直"等待"（1.8.7）

看板每隔几秒跑一次 `code agent endpoints` 来找 VS Code。Mac 上这个命令 0.2 秒就回。公司电脑上它每次 25 秒都不回，看板就一直写"code 命令回得慢"。这是卡住了，不是慢。下面找出卡在哪。

- 在**普通 PowerShell 窗口**里跑（从开始菜单打开）。不要在 VS Code 的终端里跑：那里的 `code` 走另一条路，结果不准。
- 看板和 VS Code 都保持开着。
- 下面的命令不打印 token，可以直接拍照。

## 第 0 步：VS Code 左下角的齿轮

截图里齿轮上有一个蓝色的转圈小标。鼠标放上去，拍下它写的字（比如 Checking for Updates、Downloading Update、Updating，或 Settings Sync）。再点开齿轮，看菜单里有没有 **Restart to Update**，拍照。

先别点它。做完第 1–5 步再点。

## 第 1 步：看板用的是哪个 code

```powershell
"HARNESS_VSCODE_CLI = [$env:HARNESS_VSCODE_CLI]"
$places = @("$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd", "$env:ProgramFiles\Microsoft VS Code\bin\code.cmd", "${env:ProgramFiles(x86)}\Microsoft VS Code\bin\code.cmd")
$places | ForEach-Object { "{0,-6} {1}" -f (Test-Path $_), $_ }
where.exe code.cmd
$code = @($env:HARNESS_VSCODE_CLI) + $places | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $code) { $code = where.exe code.cmd | Select-Object -First 1 }
"board uses: $code"
```

看板按这个顺序挑：`HARNESS_VSCODE_CLI`；然后上面三个位置里第一个 `True` 的；都没有才用 `where.exe` 找到的。拍照。

## 第 2 步：这个 code 的版本，和 VS Code 窗口的版本

```powershell
Get-ChildItem env:VSCODE_IPC* -ErrorAction SilentlyContinue | Remove-Item
Remove-Item env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
$sw = [Diagnostics.Stopwatch]::StartNew(); $v = & $code --version 2>&1
"code --version: {0:N1} s" -f $sw.Elapsed.TotalSeconds
$v
```

超过 60 秒没回，就按 Ctrl+C，记下"版本也卡住"。

再在 VS Code 里点 Help > About，拍下版本号那一行。两个版本号不同，说明找到的 `code` 和开着的窗口不是同一个。

## 第 3 步：像看板那样跑一次（最多等 60 秒）

```powershell
$out = "$env:TEMP\hx-ep-out.txt"; $err = "$env:TEMP\hx-ep-err.txt"
$sw = [Diagnostics.Stopwatch]::StartNew()
$p = Start-Process -FilePath $code -ArgumentList 'agent','endpoints' -RedirectStandardOutput $out -RedirectStandardError $err -NoNewWindow -PassThru
$null = $p.Handle
$null = $p.WaitForExit(60000)
"exited: {0}  after {1:N1} s" -f $p.HasExited, $sw.Elapsed.TotalSeconds
if ($p.HasExited) { "exit code: $($p.ExitCode)" }
$o = "$(Get-Content $out -Raw -ErrorAction SilentlyContinue)"
"stdout: {0} chars, editor: {1}, pipe: {2}" -f $o.Length, ($o -match '"editor"'), ($o -match 'pipe')
"stderr:"; Get-Content $err -ErrorAction SilentlyContinue | Select-Object -First 15
```

拍照。

## 第 4 步：只在第 3 步是 `exited: False` 时做——它开了哪些进程

```powershell
$all = Get-CimInstance Win32_Process
function Show-Kids($id, $depth) {
  $all | Where-Object { $_.ParentProcessId -eq $id } | ForEach-Object {
    $cmd = "$($_.CommandLine)"; if ($cmd.Length -gt 140) { $cmd = $cmd.Substring(0, 140) }
    ("  " * $depth) + "$($_.ProcessId) $($_.Name)  $cmd"
    Show-Kids $_.ProcessId ($depth + 1)
  }
}
"$($p.Id) start"; Show-Kids $p.Id 1
```

拍照，然后结束它：

```powershell
taskkill /T /F /PID $p.Id
```

## 第 5 步：看板之前的尝试有没有留下进程

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.Name -in 'Code.exe','cmd.exe','code-tunnel.exe' -and "$($_.CommandLine)" -match 'cli\.js|agent endpoints|tunnel' } | Select-Object ProcessId, ParentProcessId, Name, CreationDate | Format-Table -AutoSize
```

拍照。很多行、开始时间一个接一个，说明看板每轮都留下一个卡住的进程。

## 第 6 步：重启 VS Code 再试

1. 第 0 步是更新：等它变成 **Restart to Update**，点它。不是更新：File > Exit 关掉所有 VS Code 窗口，再打开 harness 文件夹。
2. 等 1–2 分钟，看看板的 VS Code 一行有没有变绿。拍照。
3. 重跑第 1 步和第 3 步，拍照。

## 怎么读

| 看到的 | 说明 |
| --- | --- |
| 第 3 步几秒内退出，`editor: True` | 命令本身没事，差别在看板的启动环境。告诉我看板是怎么启动的（Start Harness 还是终端）。 |
| 第 3 步退出了，exit code 不是 0，或 stderr 有字 | 看 stderr 的原话。 |
| 第 3 步 60 秒没退出 | 命令自己卡住。第 4 步看卡在哪个进程上。 |
| 第 2 步两个版本号不同，或第 0 步是更新 | 找到的 `code` 和开着的 VS Code 不是同一版。第 6 步重启后应该好。 |
| 第 6 步之后就好了 | 是 VS Code 自己的状态（更新中、还没起好）。看板这边要改提示：不该一直说"慢"。 |
