# 公司电脑：1.7 工具包 + Azure DevOps 配置（临时文档，测完删）

整段复制粘贴即可。`<...>` 换成你自己的值。代码在 `main`；ADO 工具包在本分支 `tmp/ado-test` 的 `toolpacks/ado/`。

## 0. 拿到新代码（PowerShell，在 harness 文件夹里）

```powershell
git fetch origin
git checkout main
git pull origin main
git fetch origin tmp/ado-test
git worktree add ..\ado-pack origin/tmp/ado-test
harness doctor
```

- `doctor` 最后一行应是 `errors: 0`。
- `..\ado-pack\toolpacks\ado` 就是 ADO 工具包（下面第 2 步装它）。
- 看板如果开着：在它的终端 Ctrl+C，再 `harness task board`（新代码要重启看板才生效）。

## 1. 这台电脑（看板 → Get ready → 工具 → 这台电脑）

1. **工具目录**：填 az 的 bin（ZIP 解压的那个，以前手工加进 PATH 的那个），保存 → ✓。
2. **CA bundle**：外部地址 `dev.azure.com`，代理 `127.0.0.1:9000`，**Make** → 期望 ✓ "reached with this bundle"。
3. **MCP**：保持 **被组织禁用**（你们公司本来就禁了）。

截图给我：Make 之后那行（hover 里的内容，公司名打码）。

## 2. 装 ADO 工具包（你自己的终端，不是 agent）

```powershell
harness toolpack check ..\ado-pack\toolpacks\ado
harness toolpack add ((Resolve-Path ..\ado-pack\toolpacks\ado).Path)
```

- `check` 应说 `No problem`；`add` 应说装好了 `ado`，skill 有 `ado-builds`、`ado-release`、`ado-workitem`。
- 看板 → 工具 → 工具包：`ado` 一行，点应是绿的（找到 az、有 CA bundle）。黄的话 hover 截图给我。

## 3. 连接（工具 → 连接 → Add a connection of your own）

- 类型 **Azure DevOps**，名字 `ado`，环境 **No environment**，Organization 填 dev.azure.com/ 后面那段，Project 填项目名。
- 先点 **Test**：你以前 `az login` 过，应该直接 ✓ 显示你的账号。
  - 如果 ✗：点 **Sign in**（看板的终端窗口会跑 `az login`，浏览器里登录），再 **Test**。
- **Save**。

## 4. Hello world

1. 关掉 VS Code，从看板 **Open VS Code**（这样 VS Code 才带着 az 目录和 CA bundle）。
2. 新 chat：`用 ado 列出 <pipeline 名> 最近 5 次 build 的结果`。
   - 期望：agent 用 `ado-builds` skill，跑 `az rest --resource 499b84ac-... --url "https://dev.azure.com/<org>/<project>/_apis/build/builds" --uri-parameters ...`，直接放行（读），给出结果。
   - 记：几步、几秒、有没有报证书或找不到 az。

## 5. 走通 update ticket

1. 新 chat：`新建一个 dev 任务，关联工单 ado:<一个你能改的工单号>，先读一下这个工单`。
   - 期望：任务页出现 `↗ ado:<号>`，点开就是工单网页；agent 读出标题、状态。
2. `给这个工单加一条评论：harness test`。
   - 期望：agent 按 `ado-workitem` 写一个 JSON 文件到任务的 `RUNS/`，跑 `az rest --method post ... comments`，**被扣下**；任务页出现待批卡片。
   - 你 **Approve** → agent 再跑同一条 → 通过。去 ADO 网页看评论在不在。
3. （可选）`把它的状态改成 <一个合法状态>` → 同样扣下、批准、生效。
4. 关闭任务：agent 应该**问**你要不要再更新工单，不自己动。

每一步的截图 / 结果发我（公司名、组织名、工单内容打码）。哪步不通就停在那，告诉我。
