# 检查：聊天不用 Allow all 时，扩展的「放行」算不算数，没有扩展时什么会停下

上一个检查已经证明：公司电脑上看板的 agent host 能加载扩展，判断一次 16 毫秒。接下来的做法是：harness 开的聊天不再用 Allow all，Copilot 自己的权限检查当锁，扩展说「放行」才算批准。这样扩展没加载或者死掉时，有副作用的调用会停下来，不会不经判断就执行。

Mac 上已经验证过（host 1.147）。这次在公司电脑上（Windows、host 1.148）再看一遍。这一份不挡开发，开发照常在做。

## 这个脚本做什么，不做什么

- 在 TEMP 里新建 `harness-lock-probe\<随机6位>`，每种情况一个探针文件夹。
  - 有的文件夹里放一个探针扩展，只看调用里的一个词：`X-ALLOW` 就放行；`X-DIE` 就什么也不答，然后自己退出；其他的什么也不答。
  - 另有一个 `outside` 文件夹，里面两个小文本文件，用来试「读工作文件夹外的文件」。
- 它连的是**看板已经起好的那个 agent host**。先记下 `canvasesEnabled` 原来的值，每种情况按需要打开或关上，跑完改回原样。
- 一共 6 种情况，每种开**一个**聊天（Copilot Fusion，一轮），让它一条一条地跑几个调用。合计花一些 credits。每种最多等 4 分钟，正常整个 3 到 6 分钟。
- 有调用停下来等人批准时，脚本代你拒绝它，这样一轮能走完；扩展自己的加载询问，脚本答「允许一次」（Allow Once），不写任何长期设置。
- **不碰 harness 文件夹**，也不碰它的任务、hook 和 gate。
- 只打印调用、问没问人、有没有执行。用户目录显示成 `~`，探针文件夹显示成 `<probe>` 和 `<outside>`。
- 如果 VS Code 的企业策略 `ChatCanvases` 被设成关，脚本第一段就停下，什么都不做。

| 情况 | 权限 | 扩展 | 做什么 |
| --- | --- | --- | --- |
| V1 | 默认 | 有 | 建文件夹、建文件、读外面的文件，各一次被扩展放行、一次扩展不答 |
| V4 | 默认 | 没有 | 读 README、建文件夹、建文件、读外面的文件 |
| V5 | Allow all | 有 | 第一条之后扩展退出，再建两个文件夹（**这条是要看到「不经判断就执行」**） |
| V6 | 默认 | 有 | 和 V5 一样，只是不用 Allow all |
| V7 | 默认 | 没有 | 只读命令（`cat`、`ls`、`git status`，也读外面的文件）、`echo x > 文件`、`python -c` |
| V8 | 默认 | 有 | 一次同时发三条建文件夹（两条放行、一条不答） |

## 步骤

1. 打开看板（`harness task board`），等它显示出任务列表。
2. 在 GitHub 上打开这个分支的 `checks/2026-11-28-default-lock.py`，存进 **harness 文件夹**（和 `.harness` 在同一层）。
3. 在 PowerShell 里进到 harness 文件夹，把窗口拉宽（一行约 170 个字符），运行：

   ```powershell
   python .\2026-11-28-default-lock.py
   ```

   找不到 `python` 时改用 `py -3 .\2026-11-28-default-lock.py`。
4. 把输出拍照或截图发回。约 60 行，分几张拍，**每种情况的表格都要拍清楚**。
5. 用完后删掉 harness 文件夹里的 `2026-11-28-default-lock.py`。TEMP 里的探针文件夹可以删。

只想重跑其中几种时：`python .\2026-11-28-default-lock.py V5,V8`。

## 出了问题

- 报错：把那一屏拍下来发回，不用自己修。
- `No agent host record`：看板没开或还没起好。等任务列表出来再运行。
- 某一种情况显示 `stopped: ...`：照样拍下来，脚本会接着跑下一种。
- 出现 `could not put canvasesEnabled back`：关掉看板再打开就恢复了。也拍下来。

## 发回来以后看什么

每种情况一个表，一行一个调用：`asked a person?` 是 Copilot 有没有停下来问人（`no, host approved` 是 Copilot 自己批的），`ran` 是有没有执行。下面一行是扩展起了几个进程、答了什么，最后一行是文件夹里真的建出了什么。

Mac 上的结果（应该一样）：

| 情况 | 应该看到 |
| --- | --- |
| V1 | 开头有一次 `extension load question`；`X-ALLOW` 的三条 `no` / `ran`；其余三条 `yes` / `did not run`；建出 `X-ALLOW-dir`、`X-ALLOW-file.txt` |
| V4 | 读 README 是 `no, host approved` / `ran`；其余三条 `yes` / `did not run`；什么都没建 |
| V5 | 三条都 `no` / `ran`，建出 `after1`、`after2`（这就是 Allow all 的洞） |
| V6 | `echo` 之后两条都 `yes` / `did not run`，连带 `X-ALLOW` 的那条；什么都没建 |
| V7 | `cat`、`ls`、`git status` 都 `no` / `ran`（包括读外面的文件）；`echo x >` 和 `python -c` 是 `yes` / `did not run` |
| V8 | 三条同一时刻开始；两条 `X-ALLOW` 是 `ran`，`plain-par3` 是 `did not run` |

和 Mac 不一样的地方就是要找的东西，特别是：V6 里有没有哪条执行了；V7 里 PowerShell 下哪些命令不问人；V8 的并行有没有乱。
