# kimi-cli-bot

在 [kimi-cli](https://github.com/MoonshotAI/kimi-cli) 基础上增加 Telegram Bot 接入，将 CLI Agent 的能力搬到手机上。

> 原版 kimi-cli 文档见 [UPSTREAM_README.md](UPSTREAM_README.md)

---

## 相比原版 kimi-cli 的增量

### 用户视角

- 通过 Telegram 与 AI Agent 交互
- 多用户共用一个 Bot，会话互相隔离
- Agent 可主动推送消息通知（长任务完成后无需轮询）

### 技术视角

**新增：Telegram Bot 接入层**
- `--im telegram` 启动模式，长轮询，无需公网地址
- `IMServer` 负责多用户路由，每个 `chat_id` 对应独立的 `KimiCLI` 实例和会话目录
- `SendIMNotification` 工具：让 Agent 可以主动给用户发消息（不等用户发起）

**新增：GeminiSearch 工具**
- 单独发起一次 Gemini API 调用，开启 Google Search grounding，从返回的 `grounding_chunks` 中提取 URL、标题、摘要，封装成标准 kimi-cli 工具结果

**Gemini 适配修复**
- 原版 kimi-cli 要求所有 provider 必须配置 `base_url`，Gemini 不需要——修复了这个判断
- google-genai SDK 默认用 aiohttp 做异步请求，在 Windows 上与其他 aiohttp 组件存在事件循环冲突——改为强制使用 httpx

**其他**
- 支持 `.env` 文件（`python-dotenv`）

---

## 快速开始

### 1. 安装依赖

```bash
git clone https://github.com/lieexxli/kimi-cli-bot.git
cd kimi-cli-bot
uv sync --extra im
```

### 2. 配置 LLM

```bash
cp kimi.toml.example kimi.toml
```

编辑 `kimi.toml`，填入 [Google Gemini API Key](https://aistudio.google.com/apikey)：

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

> `kimi.toml` 已加入 `.gitignore`，不会被提交。

### 3. 配置 Telegram Bot Token

通过 [@BotFather](https://t.me/BotFather) 创建 Bot，在项目目录创建 `.env`：

```env
TELEGRAM_BOT_TOKEN=xxxxxxxxxx:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

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

建议通过 `--im-allow` 限制可用用户，避免 Bot 被陌生人使用。

> IM 模式下所有工具调用自动批准（等同于 `--yolo`）。
