# 公司电脑：1.7.18 + ADO 工具包 0.3（`ado` 程序）速测（临时文档，测完删）

两个 zip：`main` 和 `tmp/ado-test`（本分支，`toolpacks/ado/` 是 0.3.0）。

## 0. 换新代码（5 分钟）

1. 关掉看板。把 `main` 的 zip **解压覆盖**到原来的 harness 文件夹（zip 里没有 `.harness\.env`、`.harness\certs`、`.harness\toolpacks`、任务，覆盖不会动它们）。
2. 在 harness 文件夹的 PowerShell：
   ```powershell
   harness doctor
   harness toolpack add "<解压的 tmp-ado-test 路径>\toolpacks\ado" --replace
   harness task board
   ```
   `add` 应显示 `version 0.3.0`，skill 是 `ado-workitem`、`ado-pipeline-triage`、`ado-release`。
3. （可选）工具 → 这台电脑 → CA bundle 再点一次 **Make**（地址 `dev.azure.com`，代理 `127.0.0.1:9000`）：这次应 ✓。不 ✓ 就截 hover，不影响下面。
4. 关掉 VS Code，从看板 **Open VS Code**。

## 1. 读（不用批）

新 chat：`读一下 ado:300965，再列出我名下没关的工单`

- 期望：agent 跑 `ado item 300965`、`ado items --mine`，一两步就出结果，没有 `az rest`、没有引号重试。

## 2. 关联条目开放后写（不用批）

1. 新 chat：`新建一个 other 任务 ado-links-test，关联 ado:300965`。
2. 任务页头部 **Open to the agent** → 点 chip **linked items**（变成 ✓）。
3. 同一个 chat：`给 ado:300965 加 3 条评论，每条两行：第一行 "harness test N"，第二行 "linked items open"`。
   - 期望：3 条 `ado comment 300965 --text "…"` **直接通过**，不用批；ADO 上 3 条评论，每条**两行**（不再挤成一行）。
4. `再给 ado:<另一个号> 加一条评论`。
   - 期望：被**拒绝**，原因写"这个任务没有关联它，先 `harness task link add ado:<号>`"。

## 3. Pipeline（读）

新 chat：`看一下 <pipeline 名> 最近 5 次 run；最近一次失败的，为什么失败`

- 期望：`ado runs <pipeline>` → `ado why <run> --out …RUNS/ADO` → 报出失败的 stage/job/task、错误行、日志末尾，并说原因。
- 记：几步、几秒；哪里不对截图。

## 4. 记下来发我

- 每一步 agent 用了哪些命令、有没有失败重试（截图）。
- 0 节第 3 步 Make 的结果。

组织名、项目名、工单内容打码。
