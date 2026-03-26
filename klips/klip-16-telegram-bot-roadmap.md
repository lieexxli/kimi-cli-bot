---
Author: "@claude"
Updated: 2026-03-26
Status: Draft
---

# KLIP-16: Telegram Bot 发展方向草稿

> 本文是 kimi-cli-bot 的发展方向探索草稿，供后续讨论用。参照两个同类产品——OpenClaw（原 Clawdbot/Moltbot，自托管 AI 助手平台，100k GitHub Stars）和 Claude Code（Anthropic 官方 CLI，kimi-cli 的直接竞品）——梳理 kimi-cli-bot 的可发展方向。

---

## 现状

kimi-cli-bot 是 kimi-cli 的 Telegram 适配版，通过 `ui/im/adapters/` 的适配器模式接入 Telegram，底层完整保留了 kimi-cli 的所有 Agent 能力。

**已有的能力：**
- Telegram IM 适配（长轮询）
- 完整工具集：Shell / 文件读写 / Web 搜索 / 图片识别 / 子 Agent / 后台任务
- 多用户会话隔离（按 `chat_id`），重启后自动续接
- IM 模式全自动审批（无需人工确认）
- MCP 协议支持（fastmcp）
- 插件系统（Skills + Tools）
- 上下文压缩管理

**定位重新认识：**

kimi-cli 和 Claude Code 是同类产品——都是 AI 编程 Agent，都在终端运行，都以工具调用驱动 Agent 循环。kimi-cli-bot 相当于「Claude Code 的 Telegram 版」。这个定位决定了发展方向不该只看 OpenClaw（通用 AI 助手），更应对标 Claude Code 的设计哲学。

---

## 方向一：KIMI.md 项目记忆注入

**对标：** Claude Code 的 `CLAUDE.md` 机制。

Claude Code 最受欢迎的特性之一：自动读取项目根目录的 `CLAUDE.md`，把项目背景、编码规范、常用命令注入到每次对话的系统提示里，无需用户每次重复描述。

kimi-cli-bot 可以做同样的事：
- 自动读取 `KIMI.md`（或沿用 `CLAUDE.md`，两者兼容），作为项目级持久化上下文
- 多层级覆盖：全局 `~/.kimi/KIMI.md`（个人偏好）+ 项目根目录 `KIMI.md`（项目规范）
- Telegram 命令 `/memory` 显示当前生效的记忆内容，`/memory edit` 在服务端触发编辑

**现有基础：** `config.py` 有配置加载逻辑，`soul/context.py` 管理系统提示注入，`agentspec.py` 有 agent 文件加载机制。

**实现成本：** 低。核心是在会话初始化时查找并读取 `KIMI.md`，追加到系统提示。

---

## 方向二：Plan Mode + Telegram InlineKeyboard 审批流

**对标：** Claude Code 的 Plan Mode 和 kimi-cli 现有的 `EnterPlanMode` 工具。

kimi-cli 已有 `EnterPlanMode` 工具，但在 IM 层没有对应的视觉交互。Claude Code 的 Plan Mode 是「先只读规划，用户确认后再写入执行」，这个模式在移动端场景价值更大——用户在手机上不方便打字，按按钮比输入"确认"快得多。

**目标体验：**
1. 用户在 Telegram 发送复杂任务，如「重构 auth 模块，按 domain 拆分，加单测」
2. Agent 进入 Plan Mode，回复一张「计划卡片」（Markdown 格式化的步骤列表）
3. 消息底部附带 Inline Keyboard：`[✅ 执行]` `[✏️ 修改计划]` `[❌ 取消]`
4. 用户点击「执行」后，Agent 退出 Plan Mode 开始实际操作

**现有基础：** `EnterPlanMode` 工具、`soul/approval.py` 审批框架、`aiogram` 支持 Inline Keyboard。

**差距：** `IMSession` 没有把 plan mode 的输出渲染成结构化卡片，也没有按钮交互的回调处理。

---

## 方向三：Git 原生 Telegram 命令

**对标：** Claude Code 的 `/commit`、PR 创建、diff review 等一等公民工作流。

kimi-cli-bot 的用户场景很可能是：手边没有电脑，在手机上通过 Telegram 指挥 Agent 改代码、提 PR。那么 git 工作流命令就是刚需，而不是可选项。

**目标命令：**

| 命令 | 功能 |
|------|------|
| `/commit` | AI 分析 diff，生成 Conventional Commits 消息，Telegram 确认后提交 |
| `/diff` | 把当前 `git diff` 渲染成 Telegram 代码块（语法高亮） |
| `/pr` | AI 生成 PR 标题和描述，自动创建 Pull Request |
| `/review` | AI 审查当前改动，在 Telegram 给出建议 |
| `/log` | 格式化显示最近几条 commit 记录 |

**实现路径：** 在 `soul/slash.py` 的斜杠命令系统中注册这些命令，每个命令触发一次针对性的 Agent 运行（传入预设的 prompt + git 上下文）。

---

## 方向四：Hooks 系统

**对标：** Claude Code 的 Hooks 系统（PreToolUse、PostToolUse、Stop 等生命周期事件）。

Claude Code 的 Hooks 是强大的差异化功能：在工具调用的生命周期节点注入自定义命令，实现「文件修改后自动格式化」「命令执行后自动跑测试」这样的自动化工作流，无需用户每次手动触发。

在 IM 场景下，Hooks 价值更大：
- **PostToolUse(WriteFile)**：文件被修改后，自动把 diff 推送到 Telegram
- **PostToolUse(Shell)**：Shell 命令执行后，如果有测试失败，自动汇报给用户
- **Stop**：Agent 完成任务后，自动发送总结通知
- **PreToolUse(Shell)**：危险命令执行前，发 Telegram 按钮要求确认

**实现路径：** 在 `soul/toolset.py` 的工具执行入口增加生命周期 hook 分发，Hook 配置存储在 `kimi.toml` 中，IM 专属 hook 类型可以触发 Telegram 消息推送。

**现有基础：** `soul/toolset.py` 有工具执行包装，`SendIMNotification` 工具可主动推送消息。

---

## 方向五：细粒度权限规则

**对标：** Claude Code 的 `allow`/`deny`/`ask` 三层权限 + 前缀匹配规则。

当前 IM 模式是全自动批准，这对于个人使用足够，但：
- 多用户场景下，不同用户应该有不同权限
- 某些高危操作（如 `rm -rf`、写入系统文件）即使在 IM 模式下也应该需要确认

**目标：**

```toml
# kimi.toml
[im.permissions]
allow = ["Shell(git:*)", "ReadFile", "SearchWeb"]
ask   = ["WriteFile", "Shell(rm:*)", "Shell(pip:*)"]
deny  = ["Shell(curl * | bash:*)"]
```

`ask` 规则触发时，通过 Telegram InlineKeyboard 弹出「允许/拒绝」按钮，而不是自动放行。

**现有基础：** `soul/approval.py` 已有完整的审批框架和 `ApprovalRequest`/`ApprovalResponse` 协议，`aiogram` 支持 Inline Keyboard 回调。

---

## 方向六：多 IM 平台适配器

**对标：** OpenClaw 的 50+ 平台支持。

kimi-cli-bot 当前只支持 Telegram。项目的适配器模式（`ui/im/adapters/`）已经为多平台做好了架构准备。

优先级排序：

1. **Discord**（开发者聚集，有 slash commands 和频道权限，适合团队协作场景）
2. **Slack**（企业用户，有 bot 框架和工作流集成）
3. **飞书 / 企业微信**（中国市场）
4. **Matrix**（开源社区，自托管友好）

每个平台只需实现 `IMAdapter` 接口，处理各自的消息格式和 API，会话管理层无需改动。

---

## 方向七：浏览器自动化工具

**对标：** OpenClaw 的 Chrome DevTools Protocol 浏览器控制；kimi-cli 现有的 `FetchURL` 只能被动抓取。

kimi-cli-bot 当前的 Web 能力是「只读」的（搜索 + 抓取）。Playwright 可以让 Agent 真正「操作」网页：填表单、点按钮、处理动态内容、截图并发回 Telegram。

```python
# 新增 Browser 工具
class BrowserTool(CallableTool2):
    async def navigate(self, url: str) -> str: ...
    async def click(self, selector: str) -> None: ...
    async def fill(self, selector: str, value: str) -> None: ...
    async def screenshot(self) -> bytes: ...  # 截图直接发 Telegram
```

**技术选型：** `playwright`（Python 原生，维护活跃，比 Puppeteer 更适合 Python 项目）。

---

## 方向八：定时任务 / Cron 支持

**对标：** OpenClaw 的 Cron 自动化。

让用户通过 Telegram 设置定时 Agent 任务，到期自动触发并推送结果。

```
/cron add "0 9 * * 1-5" "拉取最新代码，跑测试，把结果发给我"
/cron list
/cron delete <id>
```

**现有基础：** `SendIMNotification` 可主动推消息，`TaskList` 后台任务管理，`soul/slash.py` 斜杠命令系统。

**技术选型：** `apscheduler`（Python，支持 cron 表达式，asyncio 兼容）。

---

## 方向九：Docker 容器化部署

**对标：** OpenClaw 的多部署选项（本地、远程、Docker、Nix）。

当前部署需要手动安装 uv、配置 Python 环境。Docker 化可以显著降低门槛。

```dockerfile
FROM python:3.12-slim
# + uv + 依赖 + 应用代码
```

```yaml
# docker-compose.yml
services:
  kimi-bot:
    image: kimi-cli-bot
    volumes:
      - ./kimi.toml:/app/kimi.toml
      - ./data:/app/data   # 会话存储
    env_file: .env
```

---

## 方向十：多模型运行时切换

**对标：** Claude Code 的模型配置；kimi-cli 已有 `kosong` LLM 抽象层。

允许用户在 Telegram 会话中动态切换模型：

```
/model list          → 显示 kimi.toml 中配置的可用模型
/model gemini-2.5-pro → 切换当前会话模型
/model reset         → 恢复默认模型
```

`kosong` 已经支持多供应商，这个功能基本是在 IM 层暴露已有能力。

---

## 优先级矩阵

| 优先级 | 方向 | 价值 | 实现成本 | 理由 |
|--------|------|------|----------|------|
| 1 | **KIMI.md 项目记忆** | 高 | 低 | Claude Code 验证的模式，实现简单 |
| 2 | **Plan Mode + InlineKeyboard** | 高 | 中 | 把已有能力在 IM 层渲染好 |
| 3 | **Git 原生命令** | 高 | 中 | 编程 Agent 最核心使用场景 |
| 4 | **细粒度权限规则** | 中高 | 中 | 完善已有审批系统 |
| 5 | **Hooks 系统** | 高 | 高 | 架构改动较大，但差异化最强 |
| 6 | **浏览器自动化** | 中高 | 中 | 功能增量大，相对独立 |
| 7 | **Discord 适配器** | 中 | 中 | 适配器模式清晰，开发者社区 |
| 8 | **定时任务 Cron** | 中 | 中 | 增加使用粘性 |
| 9 | **Docker 部署** | 中 | 低 | 降低门槛 |
| 10 | **多模型切换** | 低 | 低 | 暴露已有能力 |

---

## 总结

kimi-cli-bot 的定位是**「Claude Code 的移动端 / IM 端版本」**，而不是通用聊天机器人。核心价值是让开发者在 Telegram 上获得接近 Claude Code 的编程 Agent 体验——随时随地发指令、review 改动、提交代码。

近期最值得做的三件事：

1. **KIMI.md**：实现成本低，立竿见影，让用户感受到 Agent 真的「懂」自己的项目
2. **Git 命令**：`/commit` `/diff` `/pr` 是移动场景下最刚需的工作流
3. **Plan Mode InlineKeyboard**：让「复杂任务先规划再执行」这个已有的设计真正用起来
