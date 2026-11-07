# 公司电脑：1.7.29 + ADO 工具包 0.4.5 速测（临时文档，测完删）

两个 zip：`main`（1.7.29）和 `tmp/ado-test`（本分支，`toolpacks/ado/` 是 0.4.5）。约 25 分钟。组织名、项目名、工单内容截图前打码。

## 0. 换新代码（5 分钟）

1. **完全退出 VS Code**（所有窗口），关掉看板。把 `main` 的 zip 解压覆盖到原来的 harness 文件夹（不会动 `.harness\.env`、`.harness\certs`、`.harness\toolpacks`、任务）。
2. 看板起来后：Get ready → Tools → **Tool packs** → "Install from a folder"，粘贴 `<解压的 tmp-ado-test>\toolpacks\ado`（带引号也行）→ Install → 已装的会让你再点一次"替换 0.3.0 → 0.4.5"。
   - 期望：显示 `0.4.5`，skill `ado-workitem`、`ado-pipeline-triage`、`ado-release`，没有"Missing programs"。
3. Tools → **Connections** → `ado` → **Test**（az 登录的那种，超时 60 秒）→ 绿。
4. 从看板 **Open VS Code**。
   - 如果看板说"VS Code 已在运行，拿不到设置"：说明第 1 步没退干净，按它说的做。

## 1. Enter 页（1 分钟）

- "Outside systems" 一行只显示名字和点（`● ado`）；鼠标放上去是一张表（环境、状态、原因、时间、工具包）。开 VS Code 后约 5 秒内变绿，不用等第一个 chat。

## 2. 读（不用批）

新任务（Q&A）：`读一下 ado:<工单号>，再列出我名下没关的工单`

- 期望：`ado item …`、`ado items --mine`，一两步出结果；没有 `az rest`、没有 `--query` 重试。

## 3. 写：扣下的卡（要批）

同一个任务：`给 ado:<工单号> 加一条两行的评论：第一行 "harness 0.4 test"，第二行 "held card"`

- 期望：任务页出一张卡，标题是一句人话（"Add a comment to work item …"，中文界面是中文），正文块显示两行评论，原始命令折叠着。点 View → code 自动填好 → Approve → Tell → ADO 上两行评论。
- 截图这张卡。

## 4. 关联条目开放（不用批）

1. 新任务，New task 窗口 **Link tickets** 填 `ado:<工单号>`。
2. 任务页 Open to the agent → chip **linked items**（✓）。
3. `给它加 2 条评论` → 直接通过。
4. `再给 ado:<另一个号> 加一条评论` → 拒绝，告诉 agent 怎么关联；agent 自己关联后再写 → **扣下等你批**（不是直接通过）。

## 5. Pipeline（读 + 执行）

1. `看一下 <pipeline 名> 最近 5 次 run；最近一次失败的，为什么失败` → `ado runs`、`ado why`，报出失败的 stage/job/task 和错误行。
2. `在 main 上重新排一次这个 pipeline` → **扣下**，卡上看得到 branch 和参数 → 你决定批不批（批了会真的跑一次）。

## 6. 记下来发我

- 每一步 agent 用了哪些命令、有没有被误扣（读也被扣）、有没有失败重试。
- 第 0 步的安装和 Test 结果；第 3、4、5 步的卡片截图。
- Windows 上 `ado.cmd`、`az.cmd` 有没有问题（命令找不到、引号、中文）。
