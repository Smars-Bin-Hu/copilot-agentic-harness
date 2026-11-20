# 检查：已关闭任务的重开模式（版本号发布时定，1.8.21 或之后）

在公司电脑上走一遍。每一步拍照发回。用真 Copilot，模型选 Fusion。

## 准备

1. 点看板右上角的电源按钮停掉看板。
2. 更新到新版本，运行 `harness --version` 看版本号。
3. 双击 Start Harness，等看板起来。
4. 准备两个已关闭的任务：一个 promote 过（有 round 1 → round 2 的那种），一个没 promote 就关了（比如 Q&A 任务）。

## 第 1 步：任务页的 Reopen 按钮

1. 打开 promote 过的那个任务的任务页。`Checks after the close` 左边应该有 **↻ Reopen**。拍照。
2. 点它。卡片应该写：New round · round N、哪些文件会挪走（`DEV/` → `DEV_r…/`、`PLAN.md` → `PLAN_r…md`）、要重新确认需求、要重新批准计划。拍照。
3. 点 **Cancel**。任务应该还是 closed。

## 第 2 步：只重开（不开对话）

1. 打开没 promote 的那个任务，点 Reopen。卡片应该写 Go on · same round。拍照。
2. 点 **Reopen only**。任务变成 open，VS Code 里**不应该**多出新对话。拍照（看板和 VS Code 各一张）。
3. 在 VS Code 里开个新对话，说"接着做 <任务名>"。agent 应该能接上这个任务。拍照。

## 第 3 步：新一轮要重新确认需求

1. 回到 promote 过的任务，点 Reopen → **Reopen only**。
2. 打开 Requirement 页签：应该有橙色印章 "Round N: confirm again …"，任务头上是"需求等你确认"。拍照。
3. 看任务文件夹：`DEV_r…/` 和 `PLAN_r…md` 都在，`REQ.md` 的确认行写着 "not yet (round …: …)"。拍照。

## 第 4 步：交给 agent

1. 再找一个已关闭的任务，点 Reopen，在卡片里写一句话，点 **Reopen and hand to the agent**。
2. VS Code 里应该开出一个新对话，agent 先 `harness task open`，再照你的话做。拍照。

## 第 5 步：任务列表

1. 看板 → List → Closed。已关闭的行在 Archive 旁边有 ↻。鼠标停在上面看说明。拍照。
2. 点 ↻，弹出同一张卡片。拍照，然后 Cancel。

## 第 6 步：super view

1. 打开 Super agent，点头像条末尾的 **Closed (n)**。每个任务右边有小标记：new round / same round / recover first。拍照。
2. 选一个，输入框上方写着模式和 **Reopen only**。拍照。
3. 点开发送菜单（⋯）：已关闭任务上叫 **Checks after the close**，下面一行说明不会重开。拍照。

## 发回

每一步的照片；哪一步和上面写的不一样，写一句。
