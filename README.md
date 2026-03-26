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

```bash
cp kimi.toml.example kimi.toml
```

编辑 `kimi.toml`，填入 API Key：

```toml
default_model = "gemini/gemini-2.5-flash-lite"

[models."gemini/gemini-2.5-flash-lite"]
provider = "gemini"
model = "gemini-2.5-flash-lite"
max_context_size = 1048576
capabilities = ["image_in", "thinking", "video_in"]

[providers.gemini]
type = "gemini"
api_key = "YOUR_GEMINI_API_KEY"
```

通过 [@BotFather](https://t.me/BotFather) 创建 Telegram Bot，在项目目录创建 `.env`：

```env
TELEGRAM_BOT_TOKEN=xxxxxxxxxx:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> `kimi.toml` 和 `.env` 已加入 `.gitignore`，不会被提交。

### 4. 启动

```bash
uv run kimi --config-file kimi.toml --im telegram --work-dir .
```

---

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--im telegram` | 启动 Telegram Bot 模式 | — |
| `--im-token` | Bot Token（或 `TELEGRAM_BOT_TOKEN` 环境变量） | — |
| `--im-model` | 覆盖 kimi.toml 的默认模型 | kimi.toml 默认 |
| `--im-allow` | chat_id 白名单，可多次指定 | 允许所有 |
| `--work-dir` | 工作目录，会话存于 `<work-dir>/sessions/<chat_id>/` | `.` |
| `--config-file` | 配置文件路径 | 全局配置 |

**建议配置 `--im-allow`**，避免 Bot 被陌生人使用：

```bash
uv run kimi --config-file kimi.toml --im telegram --work-dir . --im-allow 123456789
```

你的 Telegram user ID 可以通过 [@userinfobot](https://t.me/userinfobot) 查询。

---

## 常用命令

| 命令 | 说明 |
|------|------|
| `/new` | 开启新对话（清空上下文） |

---

## 注意事项

- 使用长轮询，无需公网地址
- IM 模式下工具调用全部自动批准，适合个人使用
- 会话历史存储在 `<work-dir>/sessions/<chat_id>/` 下，重启后自动续接
