# 检查：看板的等待与出错（1.8.5）

在公司电脑上，用真的 VS Code 和 Copilot，把 1.8.5 的改动走一遍。每一步拍照发回。

## 准备

1. 在 harness 文件夹里换到 1.8.5（发版前用分支 `v1.8.5-board-waits`）：

   ```powershell
   git fetch origin v1.8.5-board-waits
   git checkout v1.8.5-board-waits
   harness --version
   ```

   应该显示 `1.8.5`。拍照。

2. 在看板的终端里按 Ctrl+C 停掉看板，再用 Start Harness 重新启动。页面上不能再有"the files are 1.8.x … start it again"那行红字。

3. 准备一个测试任务（模型选 Fusion）。

## 第 1 步：回答问题之后

1. 让 agent 问你一个问题（例如在消息里写"先问我一个问题再开始"）。
2. 在任务页点 Answer…，选一项，点 Send answer。
3. **点完马上拍照**（1 秒内），然后过 5 秒再拍一张。

应该看到：

- 头部标签是 **Starting…**，带一个转圈；
- 原来"Waiting for you"的卡片没有了，换成"Sent. Waiting for the agent to start…"，后面的秒数在走；
- 等你处理的按钮是灰的；
- agent 开始干活后，变成 working。

## 第 2 步：批准之后（需求、计划或回写）

1. 等一个 dev 任务写好 REQ 或 PLAN。
2. 在任务页 Confirm requirement 或 Approve plan，输入代码。
3. **输完代码马上拍照**，5 秒后再拍一张。

应该看到：确认卡片和按钮马上消失，变成 Starting…，不会再回到"告诉 agent 继续"的卡片。

## 第 3 步：出错（碰到再拍）

chat 出错的时候（限流、断网都可能），拍下任务页和 Live：

- 头部标签是红色的 **Error**，不是 working，也不是"等你"；
- 页面上方有红色提示条，写着错误原文，带 Try again（能重试时）和 Go on in a new chat；
- Live 末尾有一条红色的错误，下面的标签是红色的 Error；
- 如果这时还有等你确认的卡片，它是淡的，按钮不是黑色。

**如果头部还是 working**：同时拍下 VS Code 里那个 chat 的样子，发回来。

## 第 4 步：Try again

在出错的任务上点 Try again（页面上方的，或底部的）。

应该看到：按钮先转圈，然后变成 Starting…，Try again 消失；VS Code 里那个 chat 继续跑。

## 第 5 步：新建任务

1. 看板上点 New task，填好，点 Create and send。
2. **马上拍照**：按钮在转圈（Creating…）。
3. 弹窗变成"chat 已建好"以后，关掉它，切到 List 和 Lobby 各拍一张：

- List 里有一行带转圈的"Being created"，点不进去；
- Lobby 里有一个正在组装的机器人；
- Super agent 里有一个转圈的头像；
- agent 建好任务后，它们换成真的任务。

## 第 6 步：在新 chat 里继续

在一个没有在跑的任务上点 Go on in a new chat，在框里写一句话，点 Send。

应该看到：Send 在转圈；关掉提示后，这个任务显示 Starting…，直到新 chat 开始干活。

## 第 7 步：显示名

1. 任务页标题旁的铅笔，改成一个中文名字，回车。
2. 拍下任务页、List、Lobby、Super agent 各一张：都显示新名字，鼠标放上去显示原来的任务名。
3. 在 List 的搜索框和 Ctrl+K 里分别搜新名字和原名，都能找到。拍照。

## 第 8 步（可选）：一直没开始

关掉 VS Code，在一个任务上 Send 一条消息（会失败或卡住都拍下来）。如果任务进了 Starting…，等 2 分钟：应该变成黄色的"还没看到 agent 开始"，按钮能点了。
