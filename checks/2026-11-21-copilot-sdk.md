# 检查：不开 VS Code，能不能用 Copilot SDK 跑 Copilot（1.9 的前提）

想弄清楚三件事：

1. 公司电脑能不能装上 `microsoft-copilot-sdk`（pip 之前装 az 扩展时被挡过）；
2. SDK 第一次运行时，要从 GitHub 下载 Copilot runtime（约 100 MB），这一步能不能穿过代理；
3. 不开 VS Code 时怎么登录 Copilot，登录后 harness 的 hooks 会不会照常触发。

Mac 上已经全部跑通（2026-11-21）。每一步拍照发回。命令都在 PowerShell 里运行，不用开 VS Code。

## 准备

```powershell
python --version
```

要求 3.11 或更高（SDK 的硬性要求）。如果显示 3.9 或报错，再试试 `py -3.11 --version`，拍照发回。

## 第 1 步：建一个单独的虚拟环境，装 SDK

装在用户目录下，不会碰到 harness，也不会碰系统的 Python。

```powershell
python -m venv "$env:USERPROFILE\sdk-probe\venv"
$py = "$env:USERPROFILE\sdk-probe\venv\Scripts\python.exe"
& $py -m pip install microsoft-copilot-sdk==2.0.1
```

如果失败，按顺序试下面两种：

a. 走代理：

```powershell
& $py -m pip install --proxy http://127.0.0.1:9000 microsoft-copilot-sdk==2.0.1
```

b. 如果报 `CERTIFICATE_VERIFY_FAILED`：加上之前给 az 做的那个 CA 证书包，把 `<CA 证书包路径>` 换成那个文件的路径：

```powershell
& $py -m pip install --proxy http://127.0.0.1:9000 --cert "<CA 证书包路径>" microsoft-copilot-sdk==2.0.1
```

三种都装不上时，拍下最后的报错，然后跳到最后的“发回”。我会在 Mac 上把安装包（wheel）准备好，下次拷过去离线装。

## 第 2 步：取探针脚本

```powershell
mkdir "$env:USERPROFILE\sdk-probe" -Force | Out-Null
Invoke-WebRequest -Proxy http://127.0.0.1:9000 -OutFile "$env:USERPROFILE\sdk-probe\probe.py" `
  https://raw.githubusercontent.com/Smars-Bin-Hu/copilot-agentic-harness/pc-tests/checks/2026-11-21-copilot-sdk-probe.py
```

下载不了的话，就在 GitHub 上打开同一个文件夹里的 `2026-11-21-copilot-sdk-probe.py`，全选复制，用记事本另存为 `%USERPROFILE%\sdk-probe\probe.py`。

这个脚本不写任何文件，只是逐步打印 `[1] OK` 或 `[1] FAIL`。

## 第 3 步：第一次运行（会下载 runtime）

```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:9000"
$env:HTTP_PROXY  = "http://127.0.0.1:9000"
& $py "$env:USERPROFILE\sdk-probe\probe.py"
```

- 拍下全部输出。
- `[2]` 是 runtime：第一次运行会下载，可能要一两分钟。
  - 如果 `[2]` 报 `CERTIFICATE_VERIFY_FAILED`，先设置 `$env:SSL_CERT_FILE = "<CA 证书包路径>"`，再运行一次。
- `[3]` 是登录：大概率会显示 `signed in: False`，因为没开 VS Code，这台电脑上还没有可用的登录。这是正常的，继续第 4 步。

## 第 4 步：登录（任选一种能用的，从上往下试）

1. **已经有 GitHub CLI（`gh`）**：运行 `gh auth status`。如果已经登录，SDK 会直接用它；回到第 3 步再运行一次，`[3]` 应该显示 `way: gh-cli`。
2. **能装 Copilot CLI**：运行 `winget install GitHub.Copilot`，装好后运行 `copilot login`，按提示在浏览器里输入设备码。登录完回到第 3 步再运行一次。
3. **公司允许 fine-grained token**：在 GitHub 网页上建一个 fine-grained personal access token，只勾 **Copilot Requests** 这一项权限。然后**在你自己的 PowerShell 里**运行 `$env:COPILOT_GITHUB_TOKEN = "<token>"`，回到第 3 步再运行一次。token 只放在这个窗口的环境变量里，不要发给我，也不要拍进照片。

这三种都不行的话，拍下各自的报错。另外看一下 GitHub 网页上组织的 Copilot 设置里，“Copilot CLI”有没有被关掉（看不到这个设置也没关系，说一声就行）。

## 第 5 步：在 harness 文件夹里跑一次，看 hooks

登录成功后，在 harness 文件夹里运行：

```powershell
& $py "$env:USERPROFILE\sdk-probe\probe.py" --harness .
```

- `[6]` 会列出触发过的 hooks。应该有 `sessionStart`、`userPromptSubmitted`、`preToolUse`、`postToolUse`、`agentStop`，并且 `missing: none`。
- agent 只读 AGENTS.md 的第一行，不改任何文件。
- 如果 `[4]` 列出的模型里有更便宜的，可以加上 `--model <模型名>`，比如 Fusion 那一类。

## 发回

- 准备、第 1、3、5 步的照片（第 4 步只拍用了哪种方式和结果）。
- 每一步的耗时，尤其是 `[2]` 第一次下载用了多久、第二次又是多久。
- 做完以后可以删掉 `%USERPROFILE%\sdk-probe` 整个文件夹。登录信息不在里面。
