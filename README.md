# kimi-cli-bot

把 [kimi-cli](https://github.com/MoonshotAI/kimi-cli) 接入 Telegram，让你在手机上也能用完整的 AI Agent 能力：执行命令、读写文件、联网搜索、识别图片……和在终端里用没有区别。

> 原版 kimi-cli 文档见 [MoonshotAI/kimi-cli](https://github.com/MoonshotAI/kimi-cli)

---

## 能做什么

kimi-cli 原有的工具在 Telegram 里全部可用：

- **Shell 命令**：让 AI 帮你跑脚本、查日志、管进程
- **文件读写**：读代码、改配置、生成文件
- **联网搜索**：基于 Gemini Grounding Search 改造
- **图片识别**：直接发图片，AI 自动分析内容
- **文件阅读**：发送文本、PDF、代码文件，AI 读取并处理（支持 txt/md/py/js/pdf/json/yaml 等）
- **长任务**：AI 完成后主动发消息通知你，不用守着等

多个用户可以共用同一个 Bot，会话互相隔离，重启后历史对话自动续接。

---

## 快速开始

### 1. 克隆并安装

```bash
git clone https://github.com/lieexxli/kimi-cli-bot.git
cd kimi-cli-bot
uv sync
```

### 2. 获取 Gemini API Key

前往 [Google AI Studio](https://aistudio.google.com/apikey) 创建一个免费的 API Key。

### 3. 配置

复制示例配置：

```bash
cp kimi.toml.example kimi.toml
```

编辑 `kimi.toml`，填入 API Key 和 Bot Token：

```toml
default_model = "gemini-3-flash"

[providers.google]
type = "openai"
base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
api_key = "YOUR_GEMINI_API_KEY"

# 多个模型可以指向同一个 provider，通过 /model 命令切换
[models.gemini-3-flash]
provider = "google"
model = "gemini-3-flash-preview"
max_context_size = 1048576

[models.gemini-3-1-pro]
provider = "google"
model = "gemini-3.1-pro-preview"
max_context_size = 1048576

[models.gemini-3-1-flash-lite]
provider = "google"
model = "gemini-3.1-flash-lite-preview"
max_context_size = 1048576

[im]
platform = "telegram"
token = ""                        # 或在 .env 里设置 TELEGRAM_BOT_TOKEN
allowed_chat_ids = ["你的chat_id"]  # 通过 @userinfobot 获取
admin_chat_ids = ["你的chat_id"]    # 管理员：不受 default_mode 限制，可用 /model /status
default_mode = "auto"             # suggest | auto | full-auto
work_dir = "."
session_idle_timeout = 1800       # 空闲超过此秒数后从内存卸载会话（下次消息自动续接）
```

通过 [@BotFather](https://t.me/BotFather) 创建 Telegram Bot，在项目目录创建 `.env`：

```env
TELEGRAM_BOT_TOKEN=xxxxxxxxxx:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> `kimi.toml` 和 `.env` 已加入 `.gitignore`，不会被提交。

### 4. 启动

```bash
uv run kimi-cli --config-file kimi.toml --im telegram
```

---

## 执行模式

Bot 有三种执行模式，在 `kimi.toml` 的 `[im]` 段配置，由管理员统一控制：

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `suggest` | 所有工具调用都需要点按钮审批 | 公开 Bot / 不完全信任的用户 |
| `auto` | 文件读写和命令执行自动通过，仅工作目录外的编辑需审批 | 个人或可信小圈子（推荐） |
| `full-auto` | 完全自动，无需任何审批 | 只给自己用 |

`admin_chat_ids` 中的用户永远走 `full-auto`，不受 `default_mode` 影响。

---

## Bot 命令

### Bot 层命令（直接操作会话）

| 命令 | 说明 | 权限 |
|------|------|------|
| `/cancel` | 中止当前正在运行的 AI 任务 | 所有人 |
| `/status` | 查看 Bot 状态（版本、模型、活跃会话数、context 用量） | 管理员 |
| `/model` | 查看当前会话的模型 | 管理员 |
| `/model <名称>` | 切换当前会话的模型，**下一条消息立即生效，历史 context 保留，无需 `/new`** | 管理员 |

### AI 对话命令（发给 AI 处理）

| 命令 | 说明 |
|------|------|
| `/new` 或 `/clear` | 清空上下文，开始新对话 |
| `/plan [on\|off\|view\|clear]` | 进入 / 退出 / 查看 / 清除 Plan 模式 |
| `/yolo` | 切换当前会话的全自动审批模式 |

### Shell 直通（`!` 前缀，仅管理员可用）

发送 `!` 开头的消息，直接在服务器运行 Shell 命令，不经过 AI，也不需要审批，**命令在该用户的独立工作目录下执行**：

```
!git clone https://github.com/example/repo
!cd repo          ← 切换目录（会话内持久生效）
!git log --oneline
!cd               ← 回到用户根目录
```

`!cd` 会在会话内持久生效，其余命令均为一次性执行。会话重启后状态重置。`!` 命令仅管理员（`admin_chat_ids`）可用。普通用户通过 AI 对话执行操作，AI 工具天然限制在各自的用户目录内。

---

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--im telegram` | 启动 Telegram Bot 模式 | — |
| `--im-token` | Bot Token（或 `TELEGRAM_BOT_TOKEN` 环境变量） | — |
| `--im-model` | 覆盖 kimi.toml 的默认模型 | kimi.toml 默认 |
| `--im-allow` | chat_id 白名单，可多次指定 | 允许所有 |
| `--config-file` | 配置文件路径 | 全局配置 |

---

## 安全说明

⚠️ **重要**：`full-auto` 或 `auto` 模式下，白名单内的 Telegram 用户等同于拥有运行本 Bot 的服务器 Shell 执行权限。

建议：
1. `allowed_chat_ids` 严格控制白名单，留空则允许所有人
2. 不确定时使用 `default_mode = "suggest"`，有操作时点按钮确认
3. 不要以 root 权限运行 Bot
4. `work_dir` 设置为 `chmod 700`，防止其他本地用户读取会话历史
5. Bot 会自动屏蔽输出中的 API Key、Token 等敏感信息（`output_masking_enabled = true`）

> `!cmd` 语法可绕过 AI 直接执行 shell 命令，同样受白名单控制，但**不经过审批流程**，请确保白名单内用户可信。

---

## 会话隔离

每个 Telegram 用户（chat_id）有完全独立的工作目录，所有磁盘交互都发生在该目录内：

```
work_dir/
  sessions/
    9876543222/        ← 用户 A 的独立空间
      context.jsonl    ← 对话历史
      state.json       ← 会话状态
      plans/           ← /plan 模式生成的计划文件
      uploads/         ← 用户发送的文件
      repo/            ← AI 克隆的仓库、生成的文件等
    1234567890/        ← 用户 B 的独立空间（互不可见）
```

- **AI 工具操作**（写文件、下载、创建文档等）均在用户自己的目录下进行
- **`!` Shell 命令**的工作目录（CWD）也是该用户的独立目录
- **Plan 文件**写入 `sessions/<chat_id>/plans/`，不再使用全局 `~/.kimi/plans/`

重启 Bot 后自动续接上次对话。会话在内存中空闲超过 `session_idle_timeout`（默认 30 分钟）后自动卸载，下次收到消息时从磁盘重载。
