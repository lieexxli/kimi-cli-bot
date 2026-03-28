# kimi-cli-bot

把 [kimi-cli](https://github.com/MoonshotAI/kimi-cli) 接入 Telegram，让你在手机上也能用完整的 AI Agent 能力：执行命令、读写文件、联网搜索、识别图片……和在终端里用没有区别。

底层模型使用 Google Gemini。

> 原版 kimi-cli 文档见 [MoonshotAI/kimi-cli](https://github.com/MoonshotAI/kimi-cli)

---

## 能做什么

kimi-cli 原有的工具在 Telegram 里全部可用：

- **Shell 命令**：让 AI 帮你跑脚本、查日志、管进程
- **文件读写**：读代码、改配置、生成文件
- **联网搜索**：基于 Gemini Google Search grounding
- **图片识别**：直接发图片，或者粘贴图片链接
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
default_model = "gemini/gemini-2.5-flash-lite"

[models."gemini/gemini-2.5-flash-lite"]
provider = "gemini"
model = "gemini-2.5-flash-lite"
max_context_size = 1048576
capabilities = ["image_in", "thinking", "video_in"]

[providers.gemini]
type = "gemini"
base_url = "https://generativelanguage.googleapis.com"
api_key = "YOUR_GEMINI_API_KEY"

[im]
platform = "telegram"
token = ""                        # 或在 .env 里设置 TELEGRAM_BOT_TOKEN
allowed_chat_ids = ["你的chat_id"]  # 通过 @userinfobot 获取
admin_chat_ids = ["你的chat_id"]    # 管理员：不受 default_mode 限制
default_mode = "auto"             # suggest | auto | full-auto
work_dir = "."
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

| 命令 | 说明 |
|------|------|
| `/cancel` | 中止当前正在运行的 AI 任务 |
| `/status` | 查看 Bot 状态（版本、模型、活跃会话数）（管理员可用） |

### AI 对话命令（发给 AI 处理）

| 命令 | 说明 |
|------|------|
| `/new` 或 `/clear` | 清空上下文，开始新对话 |
| `/yolo` | 切换当前会话的 yolo（全自动）模式 |
| `/compact` | 手动压缩上下文 |
| `/plan` | 进入 / 退出 Plan 模式 |
| `/export` | 导出当前会话 |

### Shell 直通（`!` 前缀）

发送 `!` 开头的消息，直接在服务器运行 Shell 命令，不经过 AI，也不需要审批：

```
!pwd
!ls -la
!git status
```

不管当前是哪种执行模式，`!` 命令都直接执行。

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

每个 Telegram 用户（chat_id）有独立的工作目录和会话历史：

```
work_dir/
  sessions/
    9876543222/   ← 用户 A
    1234567890/   ← 用户 B
```

重启 Bot 后自动续接上次对话。
