# 检查：hook 能不能不每次起进程（只看，不改东西）

背景：现在每次工具调用，Copilot 都起一个 Python 进程跑 hook。公司电脑上光起进程就要约 1.5 秒，进程退出前还要再等 1–2 秒；10 个任务同时跑时，这些 hook 进程还会挤在一起扫描文件。Copilot 有一种「扩展」（`.github/extensions/<名字>/extension.mjs`），每个会话一个长驻的 Node 进程，hook 在它里面是一次函数调用。在开发用的 Mac 上试过（VS Code 1.147，模拟公司电脑速度的实验副本，10 个任务）：preToolUse 中位 7.1 → 2.1 秒。

不过这套东西是在 1.147 上看到的，公司电脑是 1.145。不知道两件事：

1. 1.145 有没有扩展这套东西，agent host 里有没有打开它的那个内部设置（`canvasesEnabled`）。
2. 公司有没有用企业策略禁掉扩展。Copilot 的运行时里有这么一句话：`Standalone extensions are prohibited by managed policy`。

这次检查只回答这两件事。两件都没问题，才值得开一个 goal 把它做成正式的。

## 这个脚本做什么，不做什么

- 只读文件：VS Code 安装目录（编辑器本身，和 `code agent host` 下载到 `%USERPROFILE%\.vscode\cli\servers\` 的那几份），以及 `%USERPROFILE%\.copilot\logs\` 里最新的 8 个日志。
- 不启动 VS Code 或 Copilot，不联网，不写文件，不花 credits，也不用 harness。
- 只打印版本号、有没有、出现的次数，以及日志里 `[managedSettings]` 开头的那几行。那几行里的网址（会带账号或主机名）换成 `<address>`，数字换成 `#`。路径里的用户目录换成 `~`。
- Python 3.9 就能跑，只用标准库。在 Mac 上跑一次不到 1 秒。

## 步骤

1. 在 GitHub 上打开这个分支的 `checks/2026-11-27-hook-extension.py`，存到公司电脑上任意一个文件夹，不用放进 harness 的文件夹。
2. 在 PowerShell 里进到那个文件夹，运行：

   ```powershell
   python .\2026-11-27-hook-extension.py
   ```

   找不到 `python` 时改用 `py -3 .\2026-11-27-hook-extension.py`。
3. 输出分两段，约 20 到 40 行。拍照或截图发回。
4. 再在同一个窗口里运行下面这条，拍下它的输出：

   ```powershell
   code --version
   ```

   这条报错也没关系（有的电脑 `code` 不在 PATH 里），把报错拍下来就行。

## 出了问题

- 报错：把报错那一屏拍照发回，不用自己修。
- 第 1 段只有一行 `no VS Code build found`：脚本没找到 VS Code 装在哪里。在 VS Code 里点 Help → About，拍下那个窗口；再运行下面这条，拍下输出：

  ```powershell
  Get-ChildItem "$env:LOCALAPPDATA\Programs", "$env:ProgramFiles" -Directory -Filter "*VS Code*" | Select-Object FullName
  ```

## 发回来以后看什么

第 1 段，每一份 VS Code 一组（`[editor]` 是编辑器，`[agent host]` 是看板用的 `code agent host`。看板用的是 agent host 那一份，它最要紧）：

| 一行 | 怎么读 |
| --- | --- |
| `version` | 1.147 或更高：和 Mac 上试过的一样。1.145：继续看下面三行 |
| `extensions.md in the Copilot SDK` | `yes`：这一版的 Copilot SDK 有扩展。`no`：没有，只能等 VS Code 升级 |
| `canvasesEnabled in agent host` | 大于 0：agent host 里有那个开关，看板能像在 Mac 上那样打开它。`0`：开关的名字或条件不一样，要再做一次实际加载的试验才知道。`no file`：这一份没有 agent host |
| `runtime knows the policy block` | `yes`：这一版能用企业策略禁扩展（只说明有这个能力，不说明真禁了）。真禁没禁看第 2 段 |

Mac 上的样子：1.147.0 和 1.148.0 都是 `yes`、`2`、`yes`。

第 2 段：

| 一行 | 怎么读 |
| --- | --- |
| `managedSettings: device MDM: ...` | 这台电脑上有没有管理软件下发的 Copilot 策略 |
| `managedSettings: server policy: ...` | GitHub 那边有没有给这个账号配策略。`none for this account` 是没有 |
| `managedSettings: effective policy resolved: source=...` | 最后生效的策略从哪里来。`source=none` 是没有策略 |
| `prohibited by managed policy` 的次数 | 大于 0：扩展被策略禁了，这条路走不通。`0` 只说明没见过：扩展从来没加载过时也是 0 |
| `Extension managed policy is unresolved` 的次数 | 大于 0：策略没拿到，扩展的状态不确定 |
| `importing extension` 的次数 | 公司电脑上应该是 0（还没有扩展）。大于 0 说明有扩展加载过 |

Mac 上：`source=none`，`server policy: none for this account`，三个次数是 0、0、2（2 是实验时加载过的扩展）。

读完之后：

- 第 1 段 agent host 那一份是 `yes` / 大于 0，第 2 段没有策略、`prohibited` 是 0：下一步是在公司电脑上实际加载一次扩展（另写一个检查），然后开一个新 goal。
- 任何一处走不通：这条路先放着，留在命令 hook 上继续优化。

即使都通过，还有一个要人定的问题，和这次检查无关：扩展没被加载时，没有任何东西拦住调用，调用直接执行。这和「未知不算通过」的规则冲突。
